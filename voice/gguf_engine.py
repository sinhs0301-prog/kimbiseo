# 김비서 목소리 엔진(GGUF 판) — 같은 Qwen3-TTS-12Hz-0.6B-Base 음성 복제를 llama.cpp(불칸·CPU) + 코덱 ONNX(CPU)로.
#   엔비디아가 없는 PC(라데온·인텔·내장 그래픽·그래픽카드 없음)용. torch 를 쓰지 않는다.
#   tts_engine.QwenVoice 와 같은 겉모양(prompts·voices·add_voice·stream·speak·seed_for·set_sampling·sampling_tag·voice_tag·to_int16)
#   → tts_server.py 는 엔진 종류를 몰라도 됨.
# 장치(device): "auto" = 불칸 장치가 있으면 토커를 그래픽카드로, 없으면 CPU · "vulkan"/"gpu" = 그래픽카드(안 되면 오류) · "cpu".
#   코드예측기(한 프레임에 15번 도는 작은 모델)는 predictor="auto" 면 켤 때 그래픽카드·CPU 를 짧게 재서 빠른 쪽(작은 내장 그래픽은 CPU 가 빠름).
# 보내는 방식(stream): 실시간보다 빠르면 조각(첫 6프레임 → 12프레임씩), 느리면 '끊기지 않을 만큼 모은 뒤' 보냄(앞 문장들로 잰 속도·글 길이로 계산).
# 같은 글·같은 감정 → 같은 시드 → 같은 소리(QwenVoice 와 같은 규칙).
import hashlib
import os
import re
import time
import zlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from gguf_tts import codec, lib, parts

SR = 24000
SPF = 1920
MANIFEST_NAME = "참고목록.json"
FILES = {"talker": "qwen3_tts_talker.q5_k.gguf", "predictor": "qwen3_tts_predictor.q8_0.gguf",
         "decoder": "qwen3_tts_decoder.fp32.onnx", "codec_enc": "qwen3_tts_codec_encoder.fp32.onnx",
         "spk_enc": "qwen3_tts_speaker_encoder.fp32.onnx", "tokenizer": "tokenizer.json"}
ALIAS = {"neutral": "기본", "normal": "기본", "보통": "기본", "happy": "기쁨", "joy": "기쁨", "worried": "걱정",
         "worry": "걱정", "concern": "걱정", "sleepy": "졸림", "tired": "졸림", "surprised": "놀람", "surprise": "놀람"}


def emotion_name(e):
    if not e:
        return "기본"
    e = str(e).strip()
    return ALIAS.get(e.lower(), e)


def model_files(model_dir):
    """모델 폴더에 꼭 있어야 하는 파일 중 없는 것 목록(빈 목록 = 됨)."""
    need = [FILES[k] for k in FILES] + [os.path.join("embeddings", "text_embedding_projected.npy")]
    need += [os.path.join("embeddings", f"codec_embedding_{i}.npy") for i in range(16)]
    for k in ("decoder", "codec_enc", "spk_enc"):
        if ".fp32." in FILES[k]:            # fp32 내보내기는 가중치가 옆 .data 파일에 있음
            need.append(FILES[k] + ".data")
    return [n for n in need if not os.path.isfile(os.path.join(model_dir, n))]


class _Anchor:
    __slots__ = ("text", "codes", "spk", "state")

    def __init__(self, text, codes, spk, state):
        self.text, self.codes, self.spk, self.state = text, codes, spk, state


class GgufVoice:
    native_speed = False

    def __init__(self, model_dir, ref_dir, refs=None, device="auto", lib_dir="", threads=None, predictor="auto",
                 temperature=0.7, top_k=50, sub_temperature=0.9, sub_top_k=50, repetition_penalty=1.05,
                 dec_threads=None, link_root="", verbose=True, log=print):
        t0 = time.time()
        self.log = log
        from tokenizers import Tokenizer
        miss = model_files(model_dir)
        if miss:
            raise FileNotFoundError(f"목소리 모델(GGUF) 파일 없음: {', '.join(miss[:3])}{' 외' if len(miss) > 3 else ''}")
        lib.load(lib_dir)
        gpus = lib.gpu_devices()
        want = str(device or "auto").lower()
        if want in ("vulkan", "gpu", "cuda") and not gpus:
            raise RuntimeError("불칸 그래픽 장치를 못 찾음(드라이버 확인) — 장치를 cpu 로 바꾸면 CPU 로 돌아요")
        use_gpu = bool(gpus) and want != "cpu"
        cores = os.cpu_count() or 4
        # 스레드: 작은 llama 모델(토커 한 토큰·예측기)은 2~4개가 가장 빠름(개발 PC 32스레드 CPU 실측 — 많으면 오히려 느림)
        self.threads = int(threads or max(2, min(4, cores // 4)))
        self._pool = ThreadPoolExecutor(1, thread_name_prefix="gguf-dec")
        P = lambda k: os.path.join(model_dir, FILES[k])  # noqa: E731
        self.assets = parts.Assets(model_dir)
        self.tok = Tokenizer.from_file(P("tokenizer"))
        self.builder = parts.PromptBuilder(self.tok, self.assets)
        self.t_model = lib.Model(P("talker"), use_gpu=use_gpu, link_root=link_root)
        pred_mode = str(predictor or "auto").lower()
        self.p_models = {}
        if use_gpu and pred_mode in ("auto", "gpu", "vulkan"):
            self.p_models["gpu"] = lib.Model(P("predictor"), use_gpu=True, link_root=link_root)
        if not use_gpu or pred_mode in ("auto", "cpu"):
            self.p_models["cpu"] = lib.Model(P("predictor"), use_gpu=False, link_root=link_root)
        self.talker = parts.make_talker(self.t_model, self.assets, threads=self.threads)
        self.pred_threads = int(os.environ.get("KIMBISEO_GGUF_PRED_THREADS") or self.threads)
        self.preds = {k: parts.make_predictor(m, self.assets, threads=self.pred_threads) for k, m in self.p_models.items()}
        self.dec_threads = int(dec_threads or max(2, min(8, cores // 4)))
        self.dec = codec.StatefulDecoder(P("decoder"), chunk_size=12, threads=self.dec_threads)
        self.cenc = codec.CodecEncoder(P("codec_enc"), threads=self.dec_threads)
        self.senc = codec.SpeakerEncoder(P("spk_enc"), threads=self.dec_threads)
        self.lang = parts.LANGUAGE["korean"]
        self.top_k, self.sub_top_k = int(top_k), int(sub_top_k)
        self._temp, self._sub_temp, self._rep = float(temperature), float(sub_temperature), float(repetition_penalty)
        self.gpu_name = gpus[0][1] or gpus[0][0] if use_gpu else ""
        self.prompts, self.voices = {}, {}
        self.load_refs(refs or load_refs(ref_dir), ref_dir)
        self.pred_key = self._pick_predictor()
        if len(self.preds) > 1:
            for k in [k for k in self.preds if k != self.pred_key]:   # 안 쓰는 쪽은 놓아 줌
                self.preds.pop(k)
                self.p_models.pop(k).close()
        self.dev = ("vulkan" if use_gpu else "cpu")
        self.device_note = (f"불칸 {self.gpu_name}" if use_gpu else f"CPU {self.threads}스레드") + f" · 예측기 {'그래픽카드' if self.pred_key == 'gpu' else 'CPU'}"
        self.cuda = False
        self.rtf = None          # 앞 문장들로 잰 실시간 배율(만드는 시간 / 소리 길이)
        self.fpc = 3.0           # 글자당 프레임(앞 문장들로 고침)
        self.load_sec = time.time() - t0
        if verbose:
            log(f"[목소리 엔진 GGUF] {self.device_note} 준비 {self.load_sec:.1f}초, 감정 {list(self.prompts)}")

    # ---------- 샘플링 값 ----------
    @property
    def temp(self):
        return round(self._temp, 4)

    @property
    def sub_temp(self):
        return round(self._sub_temp, 4)

    @property
    def rep_pen(self):
        return round(self._rep, 4)

    def set_sampling(self, temperature=None, sub_temperature=None, repetition_penalty=None):
        if temperature is not None:
            self._temp = float(temperature)
        if sub_temperature is not None:
            self._sub_temp = float(sub_temperature)
        if repetition_penalty is not None:
            self._rep = float(repetition_penalty)
        return {"temperature": self.temp, "sub_temperature": self.sub_temp, "repetition_penalty": self.rep_pen, "top_k": self.top_k}

    def sampling_tag(self):
        return f"g{self.temp}s{self.sub_temp}r{self.rep_pen}k{self.top_k}"

    # ---------- 참고음성 ----------
    def _anchor(self, wav_path, text):
        w = codec.load_wav(wav_path)
        codes = np.asarray(self.cenc.encode(w), dtype=np.int64)
        spk = self.senc.encode(w)
        _, st = self.dec.decode(codes, state=None, is_final=True)     # 복원기 앞 문맥(참고음성)을 미리 채움
        return _Anchor(text, codes, spk, st)

    def build_prompts(self, refs, ref_dir, anchor_xvec=True):
        tag = hashlib.sha1(b"gguf|")
        prompts, base_spk = {}, None
        for emo, (fn, text) in refs.items():
            path = fn if os.path.isabs(fn) else os.path.join(ref_dir, fn)
            if not os.path.exists(path):
                self.log(f"[목소리 엔진 GGUF] 참고음성 없음 → {emo} 건너뜀: {os.path.basename(path)}")
                continue
            tag.update(f"{emo}|{text}|{os.path.getsize(path)}|{int(os.path.getmtime(path))}|".encode("utf-8"))
            a = self._anchor(path, text)
            if emo == "기본":
                base_spk = a.spk
            prompts[emo] = a
        if anchor_xvec and base_spk is not None:
            for a in prompts.values():
                a.spk = base_spk
        return prompts, tag.hexdigest()[:10]

    def load_refs(self, refs, ref_dir, anchor_xvec=True):
        self.prompts, self.ref_tag = self.build_prompts(refs, ref_dir, anchor_xvec)
        if "기본" not in self.prompts:
            raise ValueError("참고음성 '기본' 을 못 읽음")

    def add_voice(self, name, refs, ref_dir, anchor_xvec=True):
        prompts, tag = self.build_prompts(refs, ref_dir, anchor_xvec)
        if "기본" not in prompts:
            raise ValueError(f"목소리 '{name}' 에 기본 참고음성이 없음")
        self.voices[name] = (prompts, tag)
        return tag

    def voice_tag(self, voice=None):
        return self.voices[voice][1] if voice and voice in self.voices else self.ref_tag

    # ---------- 예측기 장치 고르기 ----------
    def _pick_predictor(self):
        if len(self.preds) == 1:
            return next(iter(self.preds))
        a = self.prompts["기본"]
        h = np.asarray(self.assets.tts_pad, dtype=np.float32)
        best, tm = None, {}
        for k, p in self.preds.items():
            s = lib.Sampler(temperature=self._sub_temp, top_k=self.sub_top_k, seed=1)
            try:
                p.frame(h, int(a.codes[0, 0]), s)                     # 첫 번은 예열
                t0 = time.perf_counter()
                for i in range(4):
                    p.frame(h, int(a.codes[i % len(a.codes), 0]), s)
                tm[k] = (time.perf_counter() - t0) / 4
            finally:
                s.close()
            if best is None or tm[k] < tm[best]:
                best = k
        self.log(f"[목소리 엔진 GGUF] 예측기 한 프레임: " + " · ".join(f"{k} {v * 1000:.0f}ms" for k, v in tm.items()) + f" → {best}")
        return best

    # ---------- 공개 API ----------
    def seed_for(self, text, emotion):
        return zlib.crc32(f"{emotion}|{text}".encode("utf-8")) & 0x7FFFFFFF

    def _start_after(self, n_chars, first_chunk):
        """처음 소리를 내보내기 전에 모을 프레임 수. 실시간보다 빠르면 first_chunk, 느리면 끊기지 않을 만큼."""
        r = self.rtf
        if r is None or r < 0.85:
            return first_chunk
        est = max(8.0, self.fpc * n_chars)
        need = est * (1.0 - 1.0 / (r * 1.1)) + 6
        return int(min(est + 40, max(first_chunk, need)))

    def set_language(self, name):
        """기본 말 언어(0.1.18) — 'English'·'japanese' 처럼. 모르면 그대로."""
        self.lang = parts.LANGUAGE.get(str(name or "").lower(), self.lang)

    def stream(self, text, emotion="기본", seed=None, first_chunk=6, chunk=12, stats=None, voice=None, lang=None):
        """float32 24kHz 조각을 차례로. text 는 이미 읽기 변환된 글. lang = 'English' 같은 언어 이름(없으면 기본)."""
        emotion = emotion_name(emotion)
        prompts = self.voices[voice][0] if voice and voice in self.voices else self.prompts
        a = prompts.get(emotion) or prompts["기본"]
        t0 = time.perf_counter()
        seed = self.seed_for(text, emotion) if seed is None else int(seed)
        n_chars = len(re.sub(r"\s", "", text))
        lid = parts.LANGUAGE.get(str(lang or "").lower(), self.lang)
        x, trailing = self.builder.clone(text, a.text, a.codes, a.spk, lid)
        max_frames = min(40 + 6 * n_chars, self.talker.n_ctx - x.shape[0] - 4)
        if max_frames < 8:
            raise ValueError("글이 너무 깁니다(문장으로 나눠 주세요)")
        start_at = self._start_after(n_chars, first_chunk)
        T, Pd = self.talker, self.preds[self.pred_key]
        T.clear()
        h = T.prefill(x, trailing)
        ts = lib.Sampler(temperature=self._temp, top_k=self.top_k, repeat_penalty=self._rep, penalty_last_n=128,
                         seed=seed, n_vocab=self.t_model.n_vocab)
        ps = lib.Sampler(temperature=self._sub_temp, top_k=self.sub_top_k, seed=seed + 1)
        allow = (parts.PROTOCOL["EOS"], parts.PROTOCOL["PAD"], parts.PROTOCOL["BOS"])
        # 복원기(ONNX)는 일꾼 스레드 하나에서 차례로 → 그동안 토커·예측기(llama.cpp)는 다음 프레임을 계속 만듦(둘 다 GIL 을 놓음).
        st_box = [a.state]

        def dec_job(codes_, final):
            pcm_, st_box[0] = self.dec.decode(codes_, state=st_box[0], is_final=final)
            return pcm_

        jobs = deque()
        buf, produced, first_t, hit_eos = [], 0, None, False
        first_size = max(1, min(first_chunk, chunk))
        try:
            while produced < max_frames:
                c0 = int(ts.sample(T.ctx, idx=-1, limit=(0, 2048), allow=allow))
                ts.accept(c0)
                if c0 == parts.PROTOCOL["EOS"]:
                    hit_eos = True
                    break
                codes, embs = Pd.frame(h, c0, ps)
                h = T.step_audio(np.sum(embs, axis=0))
                buf.append(codes)
                produced += 1
                if len(buf) >= (first_size if not jobs and produced == len(buf) else chunk):
                    jobs.append(self._pool.submit(dec_job, np.array(buf), False))
                    buf = []
                if produced >= start_at:                       # 모을 만큼 모였으면 다 된 조각부터 내보냄
                    while jobs and jobs[0].done():
                        pcm = jobs.popleft().result()
                        if len(pcm):
                            if first_t is None:
                                first_t = time.perf_counter() - t0
                            yield pcm
            jobs.append(self._pool.submit(dec_job, np.array(buf) if buf else np.zeros((0, 16), np.int64), True))
            while jobs:
                pcm = jobs.popleft().result()
                if len(pcm):
                    if first_t is None:
                        first_t = time.perf_counter() - t0
                    yield pcm
        finally:
            for j in jobs:
                j.cancel()
            for j in jobs:
                if not j.cancelled():
                    try:
                        j.result()
                    except Exception:  # noqa: BLE001
                        pass
            ts.close()
            ps.close()
        total = time.perf_counter() - t0
        audio_sec = produced * SPF / SR
        if produced >= 6 and audio_sec > 0:
            r = total / audio_sec
            self.rtf = r if self.rtf is None else 0.6 * self.rtf + 0.4 * r
            if n_chars:
                f = produced / n_chars
                self.fpc = 0.7 * self.fpc + 0.3 * f
        if stats is not None:
            stats.update(frames=produced, audio_sec=audio_sec, first_chunk_sec=first_t, total_sec=total, prompt_len=int(x.shape[0]),
                         hit_eos=hit_eos, seed=seed, emotion=emotion, start_at=start_at, rtf=round(total / audio_sec, 3) if audio_sec else None)

    def speak(self, text, emotion="기본", seed=None, stats=None, **kw):
        kw.setdefault("first_chunk", 10 ** 6)   # 통째로(조각 안 나눔)
        parts_ = list(self.stream(text, emotion, seed=seed, stats=stats, **kw))
        return np.concatenate(parts_) if parts_ else np.zeros(0, np.float32)

    @staticmethod
    def to_int16(pcm):
        return (np.clip(pcm, -1, 1) * 32767).astype(np.int16)

    def close(self):
        self._pool.shutdown(wait=True)
        for p in list(self.p_models.values()):
            p.close()
        self.t_model.close()


def load_refs(ref_dir):
    import json
    mf = os.path.join(ref_dir, MANIFEST_NAME)
    with open(mf, encoding="utf-8-sig") as f:
        j = json.load(f)
    refs = {k: (v["wav"], v["text"]) for k, v in j.items() if not k.startswith("_") and isinstance(v, dict)}
    if "기본" not in refs:
        raise ValueError(f"참고목록에 '기본' 이 없음: {mf}")
    return refs
