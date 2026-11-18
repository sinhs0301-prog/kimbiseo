# 김비서 귀 — 한국어 받아쓰기(whisper-large-v3-turbo, transformers pipeline).
#
# 사용:
#   from ear import Ear
#   ear = Ear(model="<모델 폴더 또는 허브 이름>", device="cuda")
#   ear.transcribe(wav16k)                       # 한 번에
#   st = ear.start()
#   for pcm in mic_chunks: print(ear.feed(st, pcm))   # 부분 결과(chunk_sec 만큼 모일 때마다 지금까지 소리 전체를 다시 받아씀)
#   print(ear.finish(st))                        # 말 끝난 뒤 최종
import time
from dataclasses import dataclass, field

import numpy as np
import torch

SR = 16000
DEFAULT_MODEL = "openai/whisper-large-v3-turbo"


def token_cap(sec):
    """받아쓰기 글 토큰 상한 — 1초에 12토큰(빠른 한국어 말도 넉넉) + 24, 위스퍼 최대 440."""
    return int(max(24, min(440, 24 + 12 * float(sec))))


@dataclass
class ListenState:
    chunk_samples: int
    buffer: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    audio: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    chunk_id: int = 0
    text: str = ""
    steps: list = field(default_factory=list)  # (소리 길이 초, 계산 초)


def _f32(x):
    x = np.asarray(x).reshape(-1)
    return x.astype(np.float32) / 32768.0 if x.dtype == np.int16 else x.astype(np.float32, copy=False)


class Ear:
    backend = "whisper"

    def __init__(self, model=None, device="cuda", language="korean", chunk_sec=1.0, verbose=True, log=print):
        from transformers import pipeline

        t0 = time.time()
        self.dev = str(device)
        self.cuda = self.dev.startswith("cuda")
        self.language = language
        self.chunk_sec = chunk_sec
        dtype = torch.float16 if self.cuda else torch.float32
        self.pipe = pipeline("automatic-speech-recognition", model=model or DEFAULT_MODEL, torch_dtype=dtype,
                             device=self.dev if self.cuda else "cpu")
        self.transcribe(np.zeros(SR, np.float32))  # 예열
        self.load_sec = time.time() - t0
        if verbose:
            vram = f", 그래픽 메모리 {torch.cuda.memory_allocated() / 1e9:.2f}GB" if self.cuda else ""
            log(f"[귀/whisper] {self.dev} 준비 {self.load_sec:.1f}초{vram}")

    def transcribe(self, wav16k, max_new_tokens=None, prompt_ids=None, language="default"):
        """language: 'default' = 켤 때 정한 언어 · None = 자동 감지 · 'english' 같은 whisper 이름(요청마다 — 0.1.18 다국어)."""
        wav = _f32(wav16k)
        lang = self.language if language == "default" else language
        kw = {"task": "transcribe"}
        if lang:
            kw["language"] = lang
        # 조용한·짧은 조각에서 위스퍼가 같은 말을 수백 자 되풀이하며(실기: 0.8초 조각 → 64초·443자) 귀를 막는 일 → 소리 길이에 맞춘 상한
        kw["max_new_tokens"] = int(max_new_tokens) if max_new_tokens else token_cap(len(wav) / SR)
        if prompt_ids is not None:
            kw["prompt_ids"] = prompt_ids
        return self.pipe({"raw": wav, "sampling_rate": SR}, generate_kwargs=kw)["text"].strip()

    def prompt_ids(self, text):
        """앞글(핫워드)을 whisper 프롬프트 토큰으로."""
        return self.pipe.tokenizer.get_prompt_ids(text, return_tensors="pt").to(self.pipe.device)

    # ---------- 이어 받아쓰기 ----------
    def start(self):
        return ListenState(chunk_samples=int(round(self.chunk_sec * SR)))

    def _step(self, st):
        t0 = time.perf_counter()
        st.text = self.transcribe(st.audio)
        if self.cuda:
            torch.cuda.synchronize()
        st.steps.append((len(st.audio) / SR, time.perf_counter() - t0))
        st.chunk_id += 1

    def feed(self, st, pcm16k):
        """16kHz 소리를 아무 길이로 넣는다. chunk_sec 만큼 모일 때마다 전체를 다시 받아써 부분 결과 갱신."""
        x = _f32(pcm16k)
        if len(x):
            st.buffer = np.concatenate([st.buffer, x])
        while len(st.buffer) >= st.chunk_samples:
            st.audio = np.concatenate([st.audio, st.buffer[:st.chunk_samples]])
            st.buffer = st.buffer[st.chunk_samples:]
            self._step(st)
        return st.text

    def finish(self, st):
        """말이 끝났을 때(VAD 등) 남은 소리까지 넣어 최종 결과."""
        if len(st.buffer):
            st.audio = np.concatenate([st.audio, st.buffer])
            st.buffer = np.zeros(0, np.float32)
            self._step(st)
        return st.text


def cer(ref, hyp):
    """글자 오류율(공백·문장부호 빼고)."""
    import re

    norm = lambda s: re.sub(r"[\s\.,!?~·…'\"“”‘’\-]", "", s)  # noqa: E731
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))
