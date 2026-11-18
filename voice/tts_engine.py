# 김비서 목소리 엔진 — Qwen3-TTS-12Hz-0.6B-Base 음성 복제(ICL)로 참고음성의 목소리를 매번 같게 낸다.
#
# 고정 방법
#   - 기준 목소리 = 참고음성(wav) + 그 글 → ICL 참고. 참고음성 폴더의 참고목록.json 이 {감정: {"wav", "text"}} 를 정함
#   - 감정(기쁨·걱정 등) 참고음성이 더 있으면 그 소리 코드(말투)를 쓰되, 화자 벡터(x-vector)는 늘 '기본' 것을 씀
#     → 음색은 고정, 말투만 감정을 따름. 없는 감정은 '기본'
#   - 같은 글·같은 감정 → 같은 시드(글 해시) → 같은 소리
# 빠르게
#   - qwen_tts 원래 generate 는 프레임(80ms)마다 HF generate 2번 → 느림.
#     여기서는 같은 가중치로 토커·코드예측기 정적 KV 캐시 + 직접 샘플링(top-k 50·반복벌점 1.05·EOS 규칙은 원래와 같음.
#     온도는 토커 0.7(원래 0.9 — 문장마다 목소리 흔들림이 줄어 바꿈)·코드예측기 0.9 가 기본.
#     온도·반복벌점은 텐서 자리에 두어 set_sampling() 으로 켜진 채 바꿀 수 있음(CUDA 그래프가 그 자리를 다시 읽음).
#     top-k 는 그래프 모양에 굳으므로 바꾸려면 엔진을 새로 만들 것.)
#   - GPU 면 한 프레임 전체를 CUDA 그래프로, CPU 면 그냥 실행.
#   - 코덱은 인과적이라 앞 문맥 프레임을 겹쳐 조각 단위로 복원 → 첫 조각부터 바로 내보냄(스트리밍).
# 프롬프트(참고음성+글 임베딩)는 qwen_tts 의 generate_voice_clone 을 그대로 부르고 talker.generate 직전에 가로채서 만든다
# → 원래 코드와 같은 입력이 보장됨.
# 모델 폴더·참고음성 폴더는 부르는 쪽(tts_server.py)이 설정에서 받아 넘긴다 — 이 파일에는 경로가 없다.
import dataclasses
import json
import os
import re
import time
import zlib

import numpy as np
import torch
import torch.nn.functional as F

SR = 24000
SPF = 1920  # 샘플/프레임 (12.5Hz)
MANIFEST_NAME = "참고목록.json"


def load_refs(ref_dir):
    """참고음성 폴더 → {감정: (wav 파일, 그 글)}. 참고목록.json 이 없으면 FileNotFoundError."""
    mf = os.path.join(ref_dir, MANIFEST_NAME)
    with open(mf, encoding="utf-8-sig") as f:
        j = json.load(f)
    refs = {k: (v["wav"], v["text"]) for k, v in j.items() if not k.startswith("_") and isinstance(v, dict)}
    if "기본" not in refs:
        raise ValueError(f"참고목록에 '기본' 이 없음: {mf}")
    return refs


ALIAS = {"neutral": "기본", "normal": "기본", "보통": "기본", "happy": "기쁨", "joy": "기쁨", "worried": "걱정",
         "worry": "걱정", "concern": "걱정", "sleepy": "졸림", "tired": "졸림", "surprised": "놀람", "surprise": "놀람"}


def emotion_name(e):
    if not e:
        return "기본"
    e = str(e).strip()
    return ALIAS.get(e.lower(), e)


def _rms(x, w, eps):
    dt = x.dtype
    x = x.float()
    x = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + eps)
    return w * x.to(dt)


def _rot_half(x):
    h = x.shape[-1] // 2
    return torch.cat((-x[..., h:], x[..., :h]), dim=-1)


def _rope_table(inv_freq, n, dtype, device):
    pos = torch.arange(n, device=device, dtype=torch.float32)
    freqs = torch.outer(pos, inv_freq.float().to(device))
    emb = torch.cat((freqs, freqs), dim=-1)
    return emb.cos().to(dtype), emb.sin().to(dtype)


class _Layers:
    """HF 디코더 층 가중치를 그대로 쓰는 정적 KV 캐시 forward."""

    def __init__(self, layers, n_heads, n_kv, head_dim, eps, max_len, device, dtype, fuse=False):
        self.L = list(layers)
        self.nh, self.nkv, self.hd, self.eps = n_heads, n_kv, head_dim, eps
        self.rep = n_heads // n_kv
        self.k = [torch.zeros(1, n_kv, max_len, head_dim, device=device, dtype=dtype) for _ in self.L]
        self.v = [torch.zeros(1, n_kv, max_len, head_dim, device=device, dtype=dtype) for _ in self.L]
        # fuse=True(CPU): q·k·v 와 gate·up 가중치를 이어 붙여 행렬곱 수를 7→4 로(작은 연산 부담 줄이기). 계산 결과는 같음
        self.fused = None
        if fuse:
            self.fused = []
            for layer in self.L:
                a, m = layer.self_attn, layer.mlp
                assert a.q_proj.bias is None and m.gate_proj.bias is None
                self.fused.append((torch.cat([a.q_proj.weight, a.k_proj.weight, a.v_proj.weight]).contiguous(),
                                   torch.cat([m.gate_proj.weight, m.up_proj.weight]).contiguous()))
        self.sq, self.skv = n_heads * head_dim, n_kv * head_dim

    def _qkv(self, a, x, cos, sin, i=None):
        T = x.shape[1]
        if self.fused is not None:
            q, k, v = F.linear(x, self.fused[i][0]).split([self.sq, self.skv, self.skv], dim=-1)
        else:
            q, k, v = a.q_proj(x), a.k_proj(x), a.v_proj(x)
        q = _rms(q.reshape(1, T, self.nh, self.hd), a.q_norm.weight, self.eps).transpose(1, 2)
        k = _rms(k.reshape(1, T, self.nkv, self.hd), a.k_norm.weight, self.eps).transpose(1, 2)
        v = v.reshape(1, T, self.nkv, self.hd).transpose(1, 2)
        return q * cos + _rot_half(q) * sin, k * cos + _rot_half(k) * sin, v

    def _mlp(self, layer, x, i=None):
        m = layer.mlp
        if self.fused is not None:
            g, u = F.linear(x, self.fused[i][1]).chunk(2, dim=-1)
            return m.down_proj(F.silu(g) * u)
        return m.down_proj(F.silu(m.gate_proj(x)) * m.up_proj(x))

    def prefill(self, x, cos, sin):
        T = x.shape[1]
        for i, layer in enumerate(self.L):
            a = layer.self_attn
            q, k, v = self._qkv(a, _rms(x, layer.input_layernorm.weight, self.eps), cos, sin, i)
            self.k[i][:, :, :T] = k
            self.v[i][:, :, :T] = v
            o = F.scaled_dot_product_attention(q, k.repeat_interleave(self.rep, 1), v.repeat_interleave(self.rep, 1), is_causal=T > 1)
            x = x + a.o_proj(o.transpose(1, 2).reshape(1, T, -1))
            x = x + self._mlp(layer, _rms(x, layer.post_attention_layernorm.weight, self.eps), i)
        return x

    def step_static(self, x, cos, sin, p):
        for i, layer in enumerate(self.L):
            a = layer.self_attn
            q, k, v = self._qkv(a, _rms(x, layer.input_layernorm.weight, self.eps), cos, sin, i)
            self.k[i][:, :, p:p + 1] = k
            self.v[i][:, :, p:p + 1] = v
            qq = q.reshape(1, self.nkv, self.rep, self.hd)
            o = F.scaled_dot_product_attention(qq, self.k[i][:, :, :p + 1], self.v[i][:, :, :p + 1])
            x = x + a.o_proj(o.reshape(1, 1, -1))
            x = x + self._mlp(layer, _rms(x, layer.post_attention_layernorm.weight, self.eps), i)
        return x

    def step_dynamic(self, x, cos, sin, pos, mask, bucket):
        for i, layer in enumerate(self.L):
            a = layer.self_attn
            q, k, v = self._qkv(a, _rms(x, layer.input_layernorm.weight, self.eps), cos, sin, i)
            self.k[i].index_copy_(2, pos, k)
            self.v[i].index_copy_(2, pos, v)
            qq = q.reshape(1, self.nkv, self.rep, self.hd)
            o = F.scaled_dot_product_attention(qq, self.k[i][:, :, :bucket], self.v[i][:, :, :bucket], attn_mask=mask)
            x = x + a.o_proj(o.reshape(1, 1, -1))
            x = x + self._mlp(layer, _rms(x, layer.post_attention_layernorm.weight, self.eps), i)
        return x


class _Captured(Exception):
    pass


class QwenVoice:
    BUCKETS = (256, 512, 1024)

    def __init__(self, model_path, ref_dir, refs=None, device="cpu", dtype=None, threads=None, anchor_xvec=True,
                 temperature=0.7, top_k=50, sub_temperature=0.9, sub_top_k=50, repetition_penalty=1.05,
                 left_context=72, verbose=True, cuda_graph=True, log=print):
        from qwen_tts import Qwen3TTSModel

        t0 = time.time()
        if threads:
            torch.set_num_threads(int(threads))
        self.dev = torch.device(device)
        self.cuda = self.dev.type == "cuda"
        if dtype is None:
            dtype = "bfloat16" if self.cuda else "float32"
        self.dtype = {"float32": torch.float32, "bfloat16": torch.bfloat16, "float16": torch.float16}[dtype]
        # 모델 전체는 CPU 에 둔다(프롬프트 만들기·참고음성 인코딩용 — 글 임베딩 311M 은 GPU 에 안 올림).
        # GPU 면 생성에 필요한 부분(토커 층·코드예측기·코덱 머리·코덱 복원기)만 복사해서 올림 → VRAM 약 1.4GB.
        self.tts = Qwen3TTSModel.from_pretrained(model_path, device_map="cpu", dtype=self.dtype)
        m = self.tts.model
        self.m, self.tk = m, m.talker
        dec = m.speech_tokenizer.model.decoder
        if self.cuda:
            import copy
            g = lambda mod: copy.deepcopy(mod).to(self.dev)
            self.t_layers, self.cp, self.codec_emb, self.codec_head, self.decoder = (
                g(self.tk.model.layers), g(self.tk.code_predictor), g(self.tk.get_input_embeddings()), g(self.tk.codec_head), g(dec))
            self.norm_w = self.tk.model.norm.weight.detach().to(self.dev)
        else:
            self.t_layers, self.cp, self.codec_emb, self.codec_head, self.decoder = (
                self.tk.model.layers, self.tk.code_predictor, self.tk.get_input_embeddings(), self.tk.codec_head, dec)
            self.norm_w = self.tk.model.norm.weight
        tc = m.config.talker_config
        self.tc = tc
        self.n_groups = tc.num_code_groups
        self.eos = tc.codec_eos_token_id
        self.max_len = self.BUCKETS[-1]
        self.left_context = left_context
        self.top_k, self.sub_top_k = int(top_k), int(sub_top_k)     # top-k 는 그래프 모양에 굳음 — 바꾸려면 엔진을 새로
        # 온도·반복 벌점은 '텐서 자리'로 둔다. CUDA 그래프는 캡처 때 값이 아니라 이 자리를 다시 읽으므로
        # set_sampling() 으로 값을 바꾸면 엔진을 새로 만들지 않아도 다음 문장부터 반영된다.
        f32 = dict(device=self.dev, dtype=torch.float32)
        self._temp_t = torch.tensor(float(temperature), **f32)
        self._sub_temp_t = torch.tensor(float(sub_temperature), **f32)
        self._rep_t = torch.tensor(float(repetition_penalty), **f32)
        fuse = not self.cuda
        self.T = _Layers(self.t_layers, tc.num_attention_heads, tc.num_key_value_heads, tc.head_dim,
                         tc.rms_norm_eps, self.max_len, self.dev, self.dtype, fuse)
        cc = tc.code_predictor_config
        self.C = _Layers(self.cp.model.layers, cc.num_attention_heads, cc.num_key_value_heads, cc.head_dim,
                         cc.rms_norm_eps, self.n_groups + 1, self.dev, self.dtype, fuse)
        self.t_cos, self.t_sin = _rope_table(self.tk.model.rotary_emb.inv_freq, self.max_len, self.dtype, self.dev)
        self.c_cos, self.c_sin = _rope_table(self.cp.model.rotary_emb.inv_freq, self.n_groups + 1, self.dtype, self.dev)
        V = tc.vocab_size
        with torch.inference_mode():
            sup = torch.zeros(V, device=self.dev)
            sup[V - 1024:] = float("-inf")
            sup[self.eos] = 0.0
            self.suppress = sup
            self.eos_bias = torch.zeros(V, device=self.dev)
            self.seen = torch.zeros(V, dtype=torch.bool, device=self.dev)
        self.prompts = {}
        self.voices = {}   # 목소리 세트(기본 목소리 말고 더 올린 것): 이름 → ({감정: 프롬프트}, 태그)
        self.log = log
        self.load_refs(refs or load_refs(ref_dir), ref_dir, anchor_xvec)
        self.graphs = {}
        self.dec_graph = None
        self.use_graph = self.cuda and cuda_graph
        if self.use_graph:
            self._init_graph_buffers()
            self._capture()
        self.load_sec = time.time() - t0
        if verbose:
            log(f"[목소리 엔진] {self.dev} {dtype} 준비 {self.load_sec:.1f}초, 감정 {list(self.prompts)}")

    # ---------- 샘플링 값(설정 화면 '목소리 세부 설정') ----------
    @property
    def temp(self):
        return round(float(self._temp_t), 4)

    @property
    def sub_temp(self):
        return round(float(self._sub_temp_t), 4)

    @property
    def rep_pen(self):
        return round(float(self._rep_t), 4)

    def set_sampling(self, temperature=None, sub_temperature=None, repetition_penalty=None):
        """온도(토커)·세부 온도(코드 예측기)·반복 벌점을 바꾼다 — 다음 문장부터. 범위 검사는 부르는 쪽(목소리 서버)이 한다.
        말하는 도중에는 부르지 말 것(목소리 서버는 만들기 잠금 안에서 부름)."""
        with torch.no_grad():
            if temperature is not None:
                self._temp_t.fill_(float(temperature))
            if sub_temperature is not None:
                self._sub_temp_t.fill_(float(sub_temperature))
            if repetition_penalty is not None:
                self._rep_t.fill_(float(repetition_penalty))
        return {"temperature": self.temp, "sub_temperature": self.sub_temp, "repetition_penalty": self.rep_pen, "top_k": self.top_k}

    def sampling_tag(self):
        """캐시 열쇠용 — 샘플링 값이 바뀌면 옛 소리 캐시를 쓰지 않게."""
        return f"t{self.temp}s{self.sub_temp}r{self.rep_pen}k{self.top_k}"

    # ---------- 참고음성 ----------
    def build_prompts(self, refs, ref_dir, anchor_xvec=True):
        """참고음성들 → ({감정: 프롬프트}, 태그). 프롬프트(소리 코드·화자 벡터)는 CPU 에 있고 말할 때만 잠깐 GPU 로 옮김
        → 목소리를 더 올려도 그래픽 메모리는 거의 안 늘어남."""
        import hashlib
        import soundfile as sf
        base_x = None
        tag = hashlib.sha1()
        prompts = {}
        for emo, (fn, text) in refs.items():
            path = fn if os.path.isabs(fn) else os.path.join(ref_dir, fn)
            if not os.path.exists(path):
                self.log(f"[목소리 엔진] 참고음성 없음 → {emo} 건너뜀: {os.path.basename(path)}")
                continue
            tag.update(f"{emo}|{text}|{os.path.getsize(path)}|{int(os.path.getmtime(path))}|".encode("utf-8"))
            w, sr = sf.read(path, dtype="float32")
            if w.ndim > 1:
                w = w.mean(1)
            item = self.tts.create_voice_clone_prompt(ref_audio=(w, sr), ref_text=text, x_vector_only_mode=False)[0]
            if emo == "기본":
                base_x = item.ref_spk_embedding
            prompts[emo] = item
        if anchor_xvec and base_x is not None:
            for emo in list(prompts):
                prompts[emo] = dataclasses.replace(prompts[emo], ref_spk_embedding=base_x)
        return prompts, tag.hexdigest()[:10]

    def load_refs(self, refs, ref_dir, anchor_xvec=True):
        self.prompts, self.ref_tag = self.build_prompts(refs, ref_dir, anchor_xvec)

    def add_voice(self, name, refs, ref_dir, anchor_xvec=True):
        """목소리 세트: 같은 엔진(가중치·CUDA 그래프 그대로)에 다른 목소리 참고음성만 더 올림. → 태그"""
        prompts, tag = self.build_prompts(refs, ref_dir, anchor_xvec)
        if "기본" not in prompts:
            raise ValueError(f"목소리 '{name}' 에 기본 참고음성이 없음")
        self.voices[name] = (prompts, tag)
        return tag

    def voice_tag(self, voice=None):
        return self.voices[voice][1] if voice and voice in self.voices else self.ref_tag

    lang_name = "Korean"     # 기본 말 언어(0.1.18 다국어 — 목소리 서버가 앱 언어로 정함). stream(lang=…) 로 문장마다 바꿀 수 있음

    def _prompt(self, text, item, lang=None):
        cap = {}

        def fake(**kw):
            cap.update(kw)
            raise _Captured()

        self.tk.generate = fake
        try:
            self.tts.generate_voice_clone(text=text, language=lang or self.lang_name, voice_clone_prompt=[item], non_streaming_mode=False)
        except _Captured:
            pass
        finally:
            del self.tk.generate
        return cap["inputs_embeds"], cap["trailing_text_hidden"], cap["tts_pad_embed"]

    # ---------- 샘플링(원래 HF 설정과 같게: 반복벌점 → 특수토큰 막기 → top-k → 온도 → 다항 샘플) ----------
    def _sample(self, logits, k, temp):
        v, idx = torch.topk(logits, k, dim=-1)
        u = torch.rand_like(v).clamp_(1e-10, 1.0)
        g = -torch.log(-torch.log(u))
        j = torch.argmax(v / temp + g, dim=-1, keepdim=True)
        return torch.gather(idx, -1, j)

    def _talker_logits(self, h):
        logits = self.codec_head(h).float().view(1, -1)
        pen = torch.where(logits > 0, logits / self._rep_t, logits * self._rep_t)
        logits = torch.where(self.seen.view(1, -1), pen, logits)
        return logits + self.suppress + self.eos_bias

    def _subcodes(self, h_prev, code0):
        """코드예측기: 직전 토커 출력 + code0 → 코드 1~15, 다음 토커 입력(16개 임베딩 합)."""
        cp, C = self.cp, self.C
        e0 = self.codec_emb(code0.view(1, 1))
        x = cp.small_to_mtp_projection(torch.cat([h_prev, e0], dim=1))
        x = C.prefill(x, self.c_cos[:2], self.c_sin[:2])
        hs = _rms(x[:, -1:], cp.model.norm.weight, C.eps)
        codes = [code0.view(1)]
        emb_sum = e0.float()
        c = self._sample(cp.lm_head[0](hs).float().view(1, -1), self.sub_top_k, self._sub_temp_t)
        for g in range(1, self.n_groups - 1):
            codes.append(c.view(1))
            e = cp.model.codec_embedding[g - 1](c).view(1, 1, -1)
            emb_sum = emb_sum + e.float()
            p = g + 1
            y = C.step_static(cp.small_to_mtp_projection(e), self.c_cos[p:p + 1], self.c_sin[p:p + 1], p)
            hs = _rms(y, cp.model.norm.weight, C.eps)
            c = self._sample(cp.lm_head[g](hs).float().view(1, -1), self.sub_top_k, self._sub_temp_t)
        codes.append(c.view(1))
        emb_sum = emb_sum + cp.model.codec_embedding[self.n_groups - 2](c).view(1, 1, -1).float()
        return torch.cat(codes), emb_sum.to(self.dtype)

    # ---------- GPU: 프레임 전체 CUDA 그래프 ----------
    def _init_graph_buffers(self):
        d, D = self.dev, self.tc.hidden_size
        self.g_code0 = torch.zeros(1, 1, dtype=torch.long, device=d)
        self.g_h = torch.zeros(1, 1, D, dtype=self.dtype, device=d)
        self.g_pos = torch.zeros(1, dtype=torch.long, device=d)
        self.g_fidx = torch.zeros(1, dtype=torch.long, device=d)
        self.g_trail = torch.zeros(1, self.max_len, D, dtype=self.dtype, device=d)
        self.g_codes = torch.zeros(self.max_len + 1, self.n_groups, dtype=torch.long, device=d)
        self.ar = torch.arange(self.max_len, device=d)

    def _g_frame(self, bucket):
        codes, emb = self._subcodes(self.g_h, self.g_code0)
        self.g_codes.index_copy_(0, self.g_fidx, codes.view(1, -1))
        x = emb + self.g_trail.index_select(1, self.g_fidx)
        cos = self.t_cos.index_select(0, self.g_pos).view(1, 1, 1, -1)
        sin = self.t_sin.index_select(0, self.g_pos).view(1, 1, 1, -1)
        mask = (self.ar[:bucket] <= self.g_pos).view(1, 1, 1, bucket)
        y = self.T.step_dynamic(x, cos, sin, self.g_pos, mask, bucket)
        h = _rms(y, self.norm_w, self.T.eps)
        nxt = self._sample(self._talker_logits(h), self.top_k, self._temp_t)
        self.seen.index_fill_(0, nxt.view(1), True)
        self.g_code0.copy_(nxt.view(1, 1))
        self.g_h.copy_(h)
        self.g_pos.add_(1)
        self.g_fidx.add_(1)

    def _capture(self):
        pool = None
        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        with torch.inference_mode(), torch.cuda.stream(s):
            for b in self.BUCKETS:
                for _ in range(2):
                    self._g_frame(b)
                self._g_reset()
                g = torch.cuda.CUDAGraph()
                with torch.cuda.graph(g, pool=pool, stream=s):
                    self._g_frame(b)
                pool = g.pool()
                self.graphs[b] = g
        torch.cuda.current_stream().wait_stream(s)
        torch.cuda.synchronize()
        self._g_reset()

    @torch.inference_mode()
    def _g_reset(self):
        self.g_pos.zero_(); self.g_fidx.zero_(); self.seen.zero_(); self.g_code0.zero_(); self.g_h.zero_()

    # ---------- 코덱 복원 ----------
    @torch.inference_mode()
    def _decode(self, codes, a, b):
        """codes (N,16) 의 프레임 [a,b) 소리. 앞 문맥 left_context 프레임(참고음성 코드 포함)을 겹쳐 복원."""
        start = max(0, a - self.left_context)
        wav = self.decoder(codes[start:b].clamp(0, 2047).t().unsqueeze(0))[0, 0]
        return wav[(a - start) * SPF:(b - start) * SPF].float().cpu().numpy()

    # ---------- 공개 API ----------
    def seed_for(self, text, emotion):
        return zlib.crc32(f"{emotion}|{text}".encode("utf-8")) & 0x7FFFFFFF

    @torch.inference_mode()
    def stream(self, text, emotion="기본", seed=None, first_chunk=4, chunk=None, stats=None, voice=None, lang=None):
        """float32 24kHz numpy 조각을 차례로 내놓는다. text 는 이미 읽기 변환된 글.
        voice = add_voice 로 올린 목소리 이름(없으면 기본 목소리). 그 목소리에 없는 감정은 그 목소리의 기본.
        lang = 'English' 같은 Qwen3-TTS 언어 이름(없으면 lang_name)."""
        emotion = emotion_name(emotion)
        prompts = self.voices[voice][0] if voice and voice in self.voices else self.prompts
        item = prompts.get(emotion) or prompts["기본"]
        if chunk is None:
            chunk = 10 if self.cuda else 0          # GPU=조각 스트리밍, CPU=문장 통째(실시간보다 느려 조각이 이득 없음)
        t0 = time.perf_counter()
        seed = self.seed_for(text, emotion) if seed is None else int(seed)
        torch.manual_seed(seed)
        x, trailing, pad = (t.to(self.dev) for t in self._prompt(text, item, lang))
        L = x.shape[1]
        n_chars = len(re.sub(r"\s", "", text))
        max_frames = min(40 + 6 * n_chars, self.max_len - L - 2)
        if max_frames < 8:
            raise ValueError("글이 너무 깁니다(문장으로 나눠 주세요)")
        ref = item.ref_code.to(self.dev)
        ctx = ref[-self.left_context:] if self.left_context else ref[:0]
        nctx = ctx.shape[0]
        codes = torch.zeros(nctx + max_frames + 1, self.n_groups, dtype=torch.long, device=self.dev)
        codes[:nctx] = ctx
        T = self.T
        # prefill
        self.seen.zero_()
        self.eos_bias.zero_()
        self.eos_bias[self.eos] = float("-inf")           # min_new_tokens=2
        y = T.prefill(x, self.t_cos[:L].view(1, 1, L, -1), self.t_sin[:L].view(1, 1, L, -1))
        h = _rms(y[:, -1:], self.norm_w, T.eps)
        code0 = self._sample(self._talker_logits(h), self.top_k, self._temp_t)
        self.seen.index_fill_(0, code0.view(1), True)
        n_trail = trailing.shape[1]
        produced, emitted, hit_eos, first_t = 0, 0, False, None
        if self.use_graph:
            self.g_trail[:, :max_frames + 1] = pad
            k = min(n_trail, max_frames + 1)
            if n_trail > 1:
                self.g_trail[:, :k] = trailing[:, :k]
            self.g_code0.copy_(code0.view(1, 1)); self.g_h.copy_(h)
            self.g_pos.fill_(L); self.g_fidx.zero_()
        while produced < max_frames and not hit_eos:
            want = (first_chunk if emitted == 0 else chunk) if chunk else max_frames   # chunk=0 → 문장 통째로 만든 뒤 한 번에 복원(CPU 권장)
            n = min(want, max_frames - produced)
            if self.use_graph:
                for _ in range(n):
                    if produced == 1:
                        self.eos_bias[self.eos] = 0.0
                    p = L + produced
                    self.graphs[next(bb for bb in self.BUCKETS if bb > p)].replay()
                    produced += 1
                c0 = self.g_codes[produced - n:produced, 0].tolist()
                if self.eos in c0:
                    hit_eos = True
                    produced = produced - n + c0.index(self.eos)
                codes[nctx + emitted:nctx + produced] = self.g_codes[emitted:produced]
            else:
                for _ in range(n):
                    if int(code0) == self.eos:
                        hit_eos = True
                        break
                    fr, emb = self._subcodes(h, code0)
                    codes[nctx + produced] = fr
                    inp = emb + (trailing[:, produced:produced + 1] if produced < n_trail else pad)
                    p = L + produced
                    yy = T.step_static(inp, self.t_cos[p:p + 1].view(1, 1, 1, -1), self.t_sin[p:p + 1].view(1, 1, 1, -1), p)
                    h = _rms(yy, self.norm_w, T.eps)
                    produced += 1
                    if produced == 2:
                        self.eos_bias[self.eos] = 0.0
                    code0 = self._sample(self._talker_logits(h), self.top_k, self._temp_t)
                    self.seen.index_fill_(0, code0.view(1), True)
                if not hit_eos and int(code0) == self.eos:
                    hit_eos = True
            if produced > emitted:
                pcm = self._decode(codes, nctx + emitted, nctx + produced)
                if first_t is None:
                    first_t = time.perf_counter() - t0
                emitted = produced
                yield pcm
        if stats is not None:
            stats.update(frames=emitted, audio_sec=emitted * SPF / SR, first_chunk_sec=first_t,
                         total_sec=time.perf_counter() - t0, prompt_len=L, hit_eos=hit_eos, seed=seed, emotion=emotion)

    def speak(self, text, emotion="기본", seed=None, stats=None, **kw):
        parts = list(self.stream(text, emotion, seed=seed, stats=stats, **kw))   # kw 에 voice= 가능
        return np.concatenate(parts) if parts else np.zeros(0, np.float32)

    @staticmethod
    def to_int16(pcm):
        return (np.clip(pcm, -1, 1) * 32767).astype(np.int16)
