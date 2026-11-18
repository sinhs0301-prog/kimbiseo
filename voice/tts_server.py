# 김비서 목소리 서버 — 이 PC 안(127.0.0.1) 전용
#   POST /tts         {"text": "...", "emotion": 선택, "seed": 선택, "voice": 선택}  → audio/wav (24kHz 16bit 모노)
#   POST /tts_stream  같은 입력 → 만들어지는 대로 조각 전송(Transfer-Encoding: chunked, WAV 머리 + PCM)
#   POST /tts_lip     같은 입력 → JSON {"wav_base64", "lip": {dur, fps, lead, frames:[[t, 입모양, 벌림]...]}, "read", "emotion"}
#                     (입모양 = 소리만으로 추정한 펫 립싱크 자료 — lipsync.py)
#   POST /read        {"text": "..."} → {"read": 글 정리 결과, "sentences": [...]}
#   GET  /status      → 엔진(qwen|windows)·장치·감정·캐시·바쁨·idle_sec(마지막 요청 뒤 지난 초)·그래픽 메모리·gen(세부 설정)
#   GET  /config      → 목소리 세부 설정(온도·세부 온도·반복 벌점·top-k·문장 사이 쉼) 지금 값·기본값·받는 범위
#   POST /config      {"temperature": 0.3~1.0, "sub_temperature": 0.5~1.1, "repetition_penalty": 1.0~1.3, "gap": 0~1.0} 중 바꿀 것만,
#                     또는 {"reset": true}(기본값으로) → 다음 문장부터 반영. 범위를 벗어나면 400(아무것도 안 바뀜).
#                     top_k 는 서버를 켤 때만 읽는다(여기로 보내면 "restart": ["top_k"] 로 알려 줌). 윈도우 음성은 gap 만 쓴다.
#
#   본체용 스트림: /tts_stream 에 "raw": true 면 글 정리 없이(본체가 이미 숫자·모델명 읽기를 함 — 두 번 바꾸지 않게, 하품만 뺌)
#         캐시 없이 바로 만들고, 앞 무음을 잘라 내고(첫 소리 빠르게), "session"·"pace"(초)·"speed" 로 재생 시계를 맞춰
#         재생보다 pace 초 넘게 앞서면 쉼(그래픽카드를 귀 서버와 나눠 씀). "reset": true 면 그 세션 시계를 0 으로.
#         받는 쪽이 연결을 끊으면(끼어들기) 바로 멈춤.
#   빠르기: "speed"(0.5~2.0). windows 엔진은 직접 빠르게 읽음. qwen 엔진은 "apply_speed": true 이고 이 환경에 PyAV 가 있으면
#         서버가 소리를 줄여서 보냄(speech_rate.py). 서버가 줄였는지는 머리 X-Speed-Applied: 1/0 으로 알려 줌 — 0 이면 받는 쪽이 처리.
#   하품: 글의 하암·(하품) 같은 하품 소리는 읽지 않음. JSON 은 "yawn": true, /tts·/tts_stream 은 머리 X-Yawn: 1.
#         하품뿐인 글은 400 {"error": "읽을 글이 없습니다", "yawn": true} (부르는 쪽이 졸림 표정만).
#   엔진: 설정 '목소리.엔진' = qwen(김비서 목소리, Qwen3-TTS) | windows(윈도우 기본 음성).
#         qwen 을 못 띄우면(모델·참고음성 없음, 오류) '목소리.예비' 엔진(기본 windows)으로 → /status 의 fallback_reason.
#         장치 auto 인데 그래픽 메모리가 모자라(또는 엔비디아가 없어) CPU 로 가야 하면 → 처음부터 윈도우 음성(목소리.CPU면_윈도우, 기본 켬).
#           CPU 김비서 목소리는 첫 소리 13~15초(0.1.3 실측)라 대화가 끊기는 것보다 윈도우 음성이 낫다.
#         켜진 뒤에도: CPU 로 도는 qwen 의 첫 소리가 목소리.느림_기준_초(기본 4초)를 넘으면 그 답을 끝낸 뒤 윈도우 음성으로,
#           그래픽카드 메모리 모자람(out of memory)이 나면 그 자리에서 윈도우 음성으로 바꿔 이어 읽는다(끊지 않음).
#         시험용: 환경변수 KIMBISEO_FORCE_VRAM_LOW=1 이면 남은 그래픽 메모리를 0 으로 본다.
# 지키는 것: 127.0.0.1 에서 온 요청만, Origin 머리 있는 요청(웹페이지) 거절, JSON 만, 글 500자까지, 동시에 하나만 만들고 대기 3개까지.
# 실행: python tts_server.py [--settings 설정.json] [--port 8871] [--device auto|cuda|cpu] [--engine qwen|windows]
import argparse
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.parse
import wave
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402
import text_norm  # noqa: E402
from text_norm import drop_yawn, has_yawn, normalize, split_sentences  # noqa: E402

VERSION = "0.1.0"
SR = 24000
GAP = 0.12            # 문장 사이 쉼(초) — 여기에 설정 '목소리.문장_쉼_초'(STATE["gen"])를 더함
MAX_TEXT = 500
MAX_BODY = 16 * 1024
VOICES_FILE = os.path.join(HERE, "voices.json")
PHRASES = os.path.join(HERE, "phrases.txt")
# 김비서 목소리(Qwen)를 그래픽카드로 켜는 최소 남은 그래픽 메모리(MiB). 상한+0.6GB(2,458) 로는 켠 뒤 카드가 꽉 차
# 소리를 실시간보다 3~8배 느리게 만들어 끊김(15단계 실측) → 이보다 적게 남으면 윈도우 음성으로.
QWEN_GPU_FREE_MIN_MIB = 3300

STATE = dict(judge=None, engine=None, engine_name=None, device=None, dtype=None, busy=False, waiting=0, started=time.time(),
             served=0, cache_hits=0, error=None, fallback_reason=None, last_use=time.time(), voices={}, default_voice="",
             voice_load={}, voice_fallback=None, cache_dir=None, log=print, show_text=False, cfg=None, wanted=None,
             switched_at=None, switch_after=None, gen=None)
GEN_LOCK = threading.Lock()
WAIT_LOCK = threading.Lock()
_SWITCHED = object()
PLAY = {}             # 본체 raw 스트림: 세션 → 보낸 소리가 받는 쪽에서 다 재생되는 예상 시각(monotonic)
MEM = OrderedDict()   # (글, 감정, 시드) → PCM16
MEM_MAX = 200
# 앞 무음 자르기 — 숨소리 'ㅎ' 까지 살림
ONSET_DB, LEAD_DB, LEAD_MAX, PRE_ROLL, MAX_TRIM_SEC = -46.0, -55.0, 0.3, 0.06, 2.0


def log(msg):
    STATE["log"](msg)


def gen_now():
    """지금 목소리 세부 설정({이름: 값}). 서버를 켤 때 설정 파일에서 읽고 POST /config 로 바뀐다."""
    if STATE["gen"] is None:
        STATE["gen"] = C.gen_from_cfg(STATE["cfg"] or {}, warn=log)
    return STATE["gen"]


def gap_sec():
    return GAP + float(gen_now().get("문장_쉼_초") or 0.0)


def gen_view():
    eng = STATE["engine"]
    g = gen_now()
    out = {"engine": STATE["engine_name"], "values": {api: g[name] for api, name in C.GEN_API.items()},
           "defaults": {api: C.GEN_LIMITS[name][2] for api, name in C.GEN_API.items()},
           "limits": {api: list(C.GEN_LIMITS[name][:2]) for api, name in C.GEN_API.items()},
           "live": ["temperature", "sub_temperature", "repetition_penalty", "gap"], "needs_restart": ["top_k"]}
    if STATE["engine_name"] == "qwen" and eng is not None:
        out["engine_now"] = {"temperature": eng.temp, "sub_temperature": eng.sub_temp, "repetition_penalty": eng.rep_pen, "top_k": eng.top_k}
    else:
        out["note"] = "윈도우 음성은 문장 사이 쉼(gap)만 씁니다"
    return out


def gen_apply(body):
    """POST /config 본문 → (바뀐 것, 다시 켜야 하는 것). 범위를 벗어난 값이 하나라도 있으면 ValueError(아무것도 안 바뀜).
    GEN_LOCK 안에서 부른다(말하는 도중에 엔진 값을 바꾸지 않게)."""
    if body.get("reset") is True:
        want = {name: C.GEN_LIMITS[name][2] for name in C.GEN_LIMITS}
    else:
        want, errs = {}, []
        for api, name in C.GEN_API.items():
            if api in body:
                v, err = C.gen_check(name, body[api])
                if err:
                    errs.append(err)
                else:
                    want[name] = v
        unknown = [k for k in body if k not in C.GEN_API and k != "reset"]
        if unknown:
            errs.append("모르는 항목: " + ", ".join(str(k)[:20] for k in unknown[:5]))
        if errs:
            raise ValueError(" · ".join(errs))
    g = gen_now()
    changed = {name: v for name, v in want.items() if g.get(name) != v}
    restart = []
    eng = STATE["engine"]
    if "top_k" in changed:
        if STATE["engine_name"] == "qwen" and eng is not None and int(eng.top_k) != int(changed["top_k"]):
            restart.append("top_k")
    g.update(changed)
    if STATE["engine_name"] == "qwen" and eng is not None and hasattr(eng, "set_sampling"):
        eng.set_sampling(temperature=g["온도"], sub_temperature=g["세부_온도"], repetition_penalty=g["반복_벌점"])
    if changed:
        log("세부 설정 바뀜: " + ", ".join(f"{k}={v}" for k, v in changed.items()) + (" (top_k 는 다시 켜야 반영)" if restart else ""))
    return changed, restart


def shown(text):
    return text[:60] if STATE["show_text"] else f"(글 {len(text)}자)"


class NoText(ValueError):
    def __init__(self, msg, yawn=False):
        super().__init__(msg)
        self.yawn = yawn


def _onset(pcm):
    """float 소리에서 말 시작 샘플(없으면 None). 바로 앞에 이어진 숨소리(-55dB 넘게)는 최대 0.3초 살림."""
    import numpy as np
    w = int(0.01 * SR)
    n = len(pcm) // w
    if n == 0:
        return None
    x = pcm[: n * w].reshape(n, w)
    rms = np.sqrt((x * x).mean(1))
    idx = np.where(rms > 10 ** (ONSET_DB / 20))[0]
    if not len(idx):
        return None
    i = int(idx[0])
    floor, stop = 10 ** (LEAD_DB / 20), max(0, int(idx[0]) - int(round(LEAD_MAX / 0.01)))
    while i > stop and rms[i - 1] > floor:
        i -= 1
    return i * w


def wav_bytes(pcm16):
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm16.tobytes())
    return bio.getvalue()


def stream_header():
    import struct
    big = 0xFFFFFFFF
    return (b"RIFF" + struct.pack("<I", big) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, SR, SR * 2, 2, 16)
            + b"data" + struct.pack("<I", big))


# ---------------- 목소리 목록 ----------------
def load_voice_list():
    """voices.json → ({이름: 정보}, 기본목소리). 설정 '목소리.목소리' 가 기본목소리보다 우선."""
    reg, default = {}, ""
    try:
        with open(VOICES_FILE, encoding="utf-8-sig") as f:
            j = json.load(f)
        for k, v in (j.get("목록") or {}).items():
            if isinstance(v, dict):
                reg[str(k)] = v
        default = str(j.get("기본목소리") or "")
    except (OSError, ValueError) as ex:
        log(f"voices.json 읽기 실패: {ex}")
    want = str(STATE["cfg"]["목소리"].get("목소리") or "")
    if want:
        default = want
    if default and default not in reg:
        reg[default] = {"폴더": ""}
    return reg, default


def voice_folder(name):
    """목소리 이름 → 참고음성 폴더. 기본 목소리는 설정 '목소리.참고음성_폴더' 가 있으면 그것."""
    cfg = STATE["cfg"]
    if name == STATE["default_voice"] and cfg["목소리"].get("참고음성_폴더"):
        return os.path.abspath(os.path.expandvars(cfg["목소리"]["참고음성_폴더"]))
    folder = str((STATE["voices"].get(name) or {}).get("폴더") or "")
    if not folder:
        return ""
    folder = os.path.expandvars(folder)
    return folder if os.path.isabs(folder) else os.path.normpath(os.path.join(C.REPO, folder))


def voice_asset_problem(name):
    """그 목소리의 참고음성(참고목록.json + wav)이 쓸 수 있는지 → 문제 한 줄(없으면 "")."""
    folder = voice_folder(name)
    if not folder:
        return "폴더 정보 없음"
    manifest = os.path.join(folder, "참고목록.json")
    if not os.path.isfile(manifest):
        return "참고음성 없음"
    try:
        with open(manifest, encoding="utf-8-sig") as f:
            j = json.load(f)
    except (OSError, ValueError):
        return "참고목록.json 읽기 실패"
    base = j.get("기본") if isinstance(j.get("기본"), dict) else {}
    wav = str(base.get("wav") or "").strip()
    if not wav:
        return "참고음성 없음"
    if not os.path.isfile(os.path.join(folder, wav)):
        return f"참고음성 파일 없음({wav})"
    return ""


def ensure_voice(name):
    """기본 목소리가 아니면 그 목소리 참고음성을 엔진에 올림(GEN_LOCK 안에서 부름). → 엔진에 넘길 voice 값(None = 기본).
    자산이 없는 목소리(kimbiseo_m 등)가 선택되면 기본 목소리로 대체하고 이유를 한 줄 남긴다(서버 재시작 불필요)."""
    if not name or name == STATE["default_voice"] or STATE["engine_name"] != "qwen":
        return None
    eng = STATE["engine"]
    if name not in eng.voices:
        problem = voice_asset_problem(name)
        if problem:
            fallback = STATE["default_voice"] or "kimbiseo"
            reason = f"목소리 {name} {problem} → 기본 {fallback} 사용"
            STATE["voice_fallback"] = {"voice": name, "fallback": fallback, "reason": reason}
            log(reason)
            return None
        load_refs = _emod().load_refs
        t0 = time.perf_counter()
        folder = voice_folder(name)
        eng.add_voice(name, load_refs(folder), folder)
        STATE["voice_fallback"] = None
        STATE["voice_load"][name] = round(time.perf_counter() - t0, 2)
        log(f"목소리 '{name}' 올림 {STATE['voice_load'][name]}초 · 그래픽 메모리 {vram_info()}")
    return name


def vram_info():
    # torch 는 cuda 로 돌 때만 불러옴 — GGUF(llama.cpp) 를 올린 뒤 torch 를 불러오면 OpenMP 가 부딪혀 프로세스가 죽음(2026-11-17 실측)
    if not (STATE["device"] and str(STATE["device"]).startswith("cuda")):
        return None
    try:
        import torch
        mb = 1024 * 1024
        return dict(allocated_mib=round(torch.cuda.memory_allocated() / mb, 1), reserved_mib=round(torch.cuda.memory_reserved() / mb, 1),
                    max_allocated_mib=round(torch.cuda.max_memory_allocated() / mb, 1))
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------- 엔진 ----------------
def _emod():
    """지금 엔진의 모듈(감정 이름·참고목록 읽기) — GGUF 면 torch 를 불러오지 않게."""
    if STATE.get("dtype") == "gguf":
        import gguf_engine
        return gguf_engine
    import tts_engine
    return tts_engine


def _has_nvidia():
    """엔비디아 그래픽카드가 있는지 — torch 를 불러오지 않고 nvidia-smi 로(GGUF 를 쓸 PC 에서 torch 를 먼저 올리지 않게)."""
    return C.gpu_free_mib()[1] > 0


def voice_method(cfg):
    """'목소리.방식' → torch | gguf. auto: 엔비디아(CUDA)면 torch, 아니면 GGUF 가 깔려 있으면 gguf, 둘 다 아니면 torch(→ 예전 규칙)."""
    m = str(cfg["목소리"].get("방식") or "auto").lower()
    if m in ("torch", "gguf"):
        return m
    if os.environ.get("KIMBISEO_FORCE_VRAM_LOW") != "1" and _has_nvidia():
        return "torch"
    return "gguf" if C.gguf_ready(cfg) else "torch"


def load_gguf(cfg, device, threads):
    """라데온 판 목소리: llama.cpp(불칸 → CPU) + 코덱 ONNX(CPU). torch 를 쓰지 않음."""
    from gguf_engine import GgufVoice, load_refs
    model, lib_dir = C.gguf_paths(cfg)
    if not model or not os.path.isdir(model):
        raise FileNotFoundError(f"목소리 모델(GGUF) 폴더 없음 — 라데온 판 설치로 받으세요: {os.path.basename(model)}")
    folder = voice_folder(STATE["default_voice"])
    if not folder or not os.path.isfile(os.path.join(folder, "참고목록.json")):
        raise FileNotFoundError("참고음성 없음 — 설정 '목소리.참고음성_폴더' 에 참고목록.json 이 든 폴더를 적어 주세요")
    vk = str(cfg["목소리"].get("불칸_장치") or "").strip()
    if vk:
        os.environ["GGML_VK_VISIBLE_DEVICES"] = vk
    want = str(device or "auto").lower()
    want = "cpu" if want.startswith("cpu") else ("vulkan" if want in ("vulkan", "gpu") else "auto")
    refs = load_refs(folder)
    g = gen_now()
    link_root = os.path.join(C.path(cfg, "캐시"), "gguf_links")
    kw = dict(refs=refs, lib_dir=lib_dir, threads=cfg["목소리"].get("GGUF_스레드") or None, log=log, link_root=link_root,
              temperature=g["온도"], sub_temperature=g["세부_온도"], repetition_penalty=g["반복_벌점"], top_k=g["top_k"])
    try:
        eng = GgufVoice(model, folder, device=want, **kw)
    except Exception as ex:  # noqa: BLE001  — 그래픽 장치 쪽 오류면 CPU 로 한 번 더
        if want == "cpu":
            raise
        log(f"GGUF 그래픽 장치로 못 띄움 → CPU 로 다시: {type(ex).__name__}: {ex}")
        eng = GgufVoice(model, folder, device="cpu", **kw)
    dev = "gguf-" + eng.dev       # 'cpu' 로 시작하지 않게 → 'CPU 면 윈도우 음성' 규칙은 torch CPU 에만
    STATE.update(engine=eng, engine_name="qwen", judge=None, device=dev, dtype="gguf", gguf_note=eng.device_note)
    return eng


def load_qwen(cfg, device, threads):
    if voice_method(cfg) == "gguf":
        return load_gguf(cfg, device, threads)
    import torch
    from tts_engine import QwenVoice, load_refs
    model = C.model_path(cfg, cfg["목소리"].get("모델"))
    if not model or not os.path.isdir(model):
        raise FileNotFoundError(f"목소리 모델 폴더 없음 — installer/get_models.py 로 받으세요: {os.path.basename(model)}")
    folder = voice_folder(STATE["default_voice"])
    if not folder or not os.path.isfile(os.path.join(folder, "참고목록.json")):
        raise FileNotFoundError("참고음성 없음 — 설정 '목소리.참고음성_폴더' 에 참고목록.json 이 든 폴더를 적어 주세요")
    cap = float(cfg["목소리"].get("그래픽메모리_상한_GB") or 1.8)
    want = str(device or "auto").lower()
    if want == "auto":
        free, tot = C.gpu_free_mib()
        if os.environ.get("KIMBISEO_FORCE_VRAM_LOW") == "1":
            log(f"시험: KIMBISEO_FORCE_VRAM_LOW=1 → 남은 그래픽 메모리를 0 으로 봄(실제 {free:.0f}MiB)")
            free = 0.0
        need = max((cap + 0.6) * 1024, QWEN_GPU_FREE_MIN_MIB)
        ok_gpu = torch.cuda.is_available() and free >= need
        log(f"장치 판별: 엔비디아 {'있음' if torch.cuda.is_available() else '없음'} · 그래픽 메모리 남은 {free:.0f}/{tot:.0f}MiB · 필요 {need:.0f}MiB"
            f" → {'cuda' if ok_gpu else 'cpu'}")
        if not ok_gpu and cfg["목소리"].get("CPU면_윈도우", True):
            raise SlowVoice(f"그래픽 메모리 모자람(남은 {free:.0f}MiB < 필요 {need:.0f}MiB) — CPU 김비서 목소리는 첫 소리가 10초 넘게 걸려 윈도우 음성으로")
        device = "cuda" if ok_gpu else "cpu"
    else:
        device = want
    if device.startswith("cuda"):
        torch.cuda.set_per_process_memory_fraction(min(1.0, cap * 2**30 / torch.cuda.mem_get_info()[1]))
    dtype = "bfloat16"     # CPU 도 bf16 이 fp32 보다 약 2배 빠름
    refs = load_refs(folder)
    g = gen_now()
    eng = QwenVoice(model, folder, refs=refs, device=device, dtype=dtype, threads=threads, log=log,
                    temperature=g["온도"], sub_temperature=g["세부_온도"], repetition_penalty=g["반복_벌점"], top_k=g["top_k"])
    judge = None
    vc = cfg["목소리"].get("닮음검사") or {}
    if vc.get("켜기"):
        from voice_check import VoiceCheck
        b = refs["기본"][0]
        judge = VoiceCheck(b if os.path.isabs(b) else os.path.join(folder, b), C.model_path(cfg, vc.get("모델")),
                           os.path.expandvars(str(vc.get("도우미_파이썬") or "")), log=log)
        if judge.ok and judge.sim(__import__("numpy").zeros(SR, "int16")) is None:   # 실제로 도는지 확인
            judge.ok = False
        judge = judge if judge.ok else None
    STATE.update(engine=eng, engine_name="qwen", judge=judge, device=device, dtype=dtype)
    return eng


class SlowVoice(RuntimeError):
    """김비서 목소리를 그래픽카드로 못 돌려 느릴 때(윈도우 음성으로 바꿈)."""


def switch_to_windows(reason):
    """켜진 뒤 김비서 목소리(qwen)가 느리거나 그래픽 메모리가 모자라면 윈도우 음성으로 바꿈(GEN_LOCK 안에서 부름)."""
    if STATE["engine_name"] == "windows":
        return STATE["engine"]
    old = STATE["engine"]
    STATE["fallback_reason"] = reason
    STATE["switched_at"] = time.strftime("%H:%M:%S")
    eng = load_windows(STATE["cfg"])
    log(f"목소리 바꿈: qwen → windows ({reason}) · 윈도우 음성 {eng.voice_name}")
    del old
    try:
        import gc
        gc.collect()
        if "torch" in sys.modules:          # GGUF 엔진이면 torch 를 새로 불러오지 않음(OpenMP 충돌)
            torch = sys.modules["torch"]
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass
    return eng


def _is_oom(ex):
    t = f"{type(ex).__name__} {ex}".lower()
    return "out of memory" in t or "outofmemory" in t


WARM_TEXT = {"ko": "안녕하세요.", "en": "Hello.", "ja": "こんにちは。", "zh": "你好。"}


def set_engine_lang(eng):
    """엔진의 기본 말 언어 = 앱 언어(0.1.18). 요청마다 'lang' 으로 바꿀 수 있음."""
    name = C.TTS_NAMES.get(STATE.get("lang") or "ko", "Korean")
    if hasattr(eng, "set_language"):
        eng.set_language(name)
    elif hasattr(eng, "lang_name"):
        eng.lang_name = name
    return eng


def load_windows(cfg):
    from sapi_engine import SapiVoice
    eng = SapiVoice(voice_hint=str(cfg["목소리"].get("윈도우_목소리") or ""), log=log, lang=STATE.get("lang") or "ko")
    STATE.update(engine=eng, engine_name="windows", judge=None, device="cpu(윈도우 음성)", dtype=None)
    return eng


def load_engine(cfg, engine, device, threads):
    STATE["voices"], STATE["default_voice"] = load_voice_list()
    STATE["wanted"] = engine
    if engine == "qwen":
        try:
            eng = set_engine_lang(load_qwen(cfg, device, threads))
            log(f"엔진 준비: qwen {STATE['device']} {STATE['dtype']} {eng.load_sec:.1f}초, 목소리 {STATE['default_voice']}, "
                f"감정 {list(eng.prompts)}, 닮음검사 {'켬' if STATE['judge'] else '끔'}")
            return eng
        except Exception as ex:  # noqa: BLE001
            spare = str(cfg["목소리"].get("예비") or "")
            STATE["fallback_reason"] = f"{type(ex).__name__}: {ex}"
            if spare != "windows":
                raise
            log(f"qwen 엔진을 못 띄움 → 예비(윈도우 음성): {STATE['fallback_reason']}")
    eng = load_windows(cfg)
    log(f"엔진 준비: windows {eng.voice_name} ({eng.culture})")
    return eng


def cache_key(read, emotion, seed, voice=None, lang=None):
    eng = STATE["engine"]
    if lang and lang != "ko":
        read = f"{read}|lang={lang}"      # 다른 언어로 읽은 소리는 따로 캐시(한국어는 예전 열쇠 그대로)
    tag = eng.voice_tag(voice)   # 참고음성(목소리)·온도 같은 샘플링 값·닮음검사가 바뀌면 옛 캐시는 안 씀
    j = "j1" if STATE["judge"] is not None and STATE["judge"].ok and not voice else "j0"
    samp = eng.sampling_tag() if hasattr(eng, "sampling_tag") else f"t{getattr(eng, 'temp', '')}"
    return hashlib.sha1(f"{STATE['engine_name']}|{tag}|{samp}|{j}|{emotion}|{seed}|{read}".encode("utf-8")).hexdigest()[:24]


def synth(read_sentences, emotion, seed=None, check=True, voice=None, speed=1.0, lang=None):
    """문장들을 차례로 만들어 PCM16 조각을 내놓는다.
    check=True(/tts·/tts_lip·미리 만들기): 문장을 다 만든 뒤 닮음 검사 → 낮으면 다른 시드로 다시(voice_check.py, 켰을 때만).
    check=False(/tts_stream): 만들어지는 대로 조각 전송(검사는 끝난 뒤 하고, 기준 못 넘으면 캐시에 안 남김).
    speed 는 windows 엔진만(직접 빠르게 읽음). qwen 은 1.0 으로 만들고 줄이기는 부르는 쪽."""
    import numpy as np
    from voice_check import MIN_SEC, THRESHOLD, pick_best
    eng, judge = STATE["engine"], (None if voice else STATE["judge"])
    native = getattr(eng, "native_speed", False)
    kw = {"speed": speed} if native else {}
    lang = lang or STATE.get("lang") or "ko"
    if not native:
        kw["lang"] = C.TTS_NAMES.get(lang, "Korean")
    for i, s in enumerate(read_sentences):
        sd = eng.seed_for(s, emotion) if seed is None else int(seed) + i
        key = cache_key(s + (f"|x{speed}" if native and speed != 1.0 else ""), emotion, sd, voice, lang)
        fn = os.path.join(STATE["cache_dir"], key + ".wav") if STATE["cache_dir"] else ""
        if key in MEM:
            MEM.move_to_end(key)
            pcm = MEM[key]
            STATE["cache_hits"] += 1
        elif fn and os.path.exists(fn):
            with wave.open(fn) as w:
                pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
            STATE["cache_hits"] += 1
        else:
            pcm = None
        if pcm is not None:
            yield pcm, True
        elif check and judge is not None:
            pcm, info = pick_best(eng, judge, s, emotion, sd, voice=voice, **({"lang": kw["lang"]} if "lang" in kw else {}))
            if len(info["tries"]) > 1 or (info["sim"] is not None and info["sim"] < THRESHOLD):
                log(f"닮음 검사 다시 만듦: {info['tries']} → 시드 {info['seed']} | {shown(s)}")
            yield pcm, False
        else:
            parts = []
            for chunk in eng.stream(s, emotion, seed=sd, voice=voice, **kw):
                p16 = eng.to_int16(chunk)
                parts.append(p16)
                yield p16, False
            pcm = np.concatenate(parts) if parts else np.zeros(0, np.int16)
            sim = judge.sim(pcm) if (judge is not None and len(pcm) >= MIN_SEC * SR) else None
            if sim is not None and sim < THRESHOLD:
                log(f"스트리밍 문장 닮음 {sim} < {THRESHOLD} → 캐시에 안 남김 | {shown(s)}")
                pcm = None
        if pcm is not None and key not in MEM:
            MEM[key] = pcm
            if len(MEM) > MEM_MAX:
                MEM.popitem(last=False)
            if fn and not os.path.exists(fn):
                try:
                    os.makedirs(STATE["cache_dir"], exist_ok=True)
                    with open(fn + ".tmp", "wb") as f:
                        f.write(wav_bytes(pcm))
                    os.replace(fn + ".tmp", fn)
                except OSError:
                    pass
        if i < len(read_sentences) - 1:
            yield np.zeros(int(gap_sec() * SR), np.int16), True


def prepare(body):
    emotion_name = _emod().emotion_name
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text 가 비었습니다")
    if len(text) > MAX_TEXT:
        raise ValueError(f"text 는 {MAX_TEXT}자까지")
    emo_in = body.get("emotion")
    if emo_in is not None and not isinstance(emo_in, str):
        raise ValueError("emotion 은 글자")
    emo = emotion_name(emo_in or "기본")
    eng = STATE["engine"]
    if emo not in eng.prompts:     # 이 목소리에 없는 감정 → 기본
        emo = "기본"
    seed = body.get("seed")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        raise ValueError("seed 는 정수")
    voice = body.get("voice")
    if isinstance(voice, str) and voice not in STATE["voices"]:   # 목록에 새로 넣은 목소리 — 서버 재시작 없이 다시 읽음
        STATE["voices"] = load_voice_list()[0]
    if voice is not None and not isinstance(voice, str):
        raise ValueError("voice 는 글자")
    if voice is not None and voice not in STATE["voices"]:
        # 모르는 목소리 이름(옛 설정·다른 판의 옷 꾸러미 등) → 말이 빠지지 않게 기본 목소리로 말하고 이유를 남김
        fallback = STATE["default_voice"] or "kimbiseo"
        reason = f"목소리 {voice[:40]} 는 목록에 없음 → 기본 {fallback} 사용"
        if (STATE["voice_fallback"] or {}).get("reason") != reason:
            log(reason)
        STATE["voice_fallback"] = {"voice": voice[:40], "fallback": fallback, "reason": reason}
        voice = None
    body["_voice"] = voice
    try:
        speed = min(2.0, max(0.5, float(body.get("speed") or 1.0)))
    except (TypeError, ValueError):
        speed = 1.0
    body["_speed"] = speed
    yawn_word = has_yawn(text)
    lg = body.get("lang")
    lg = lg.strip().lower()[:2] if isinstance(lg, str) and lg.strip() else ""
    body["_lang"] = lg if lg in C.TTS_NAMES else (STATE.get("lang") or "ko")
    if body.get("raw") or body["_lang"] != "ko":   # 본체: 글 정리는 본체가 이미 함 / 한국어가 아니면 한국어 읽기 변환(숫자→한글)을 안 함
        read = re.sub(r"\s+", " ", drop_yawn(text)).strip()
        if not re.search(r"[0-9A-Za-z가-힣\u3040-\u30ff\u4e00-\u9fff]", read):
            read = ""
    else:
        read = normalize(text)
    sents = split_sentences(read) if read else []
    if not sents:
        raise NoText("읽을 글이 없습니다", yawn=yawn_word)
    return read, sents, emo, seed, yawn_word


class H(BaseHTTPRequestHandler):
    server_version = "KimBiseoVoice/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _guard(self):
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self._json(403, {"error": "127.0.0.1 만"}); return False
        if self.headers.get("Origin") not in (None, "", "null"):
            self._json(403, {"error": "웹페이지 요청 거절(Origin)"}); return False
        return True

    def _body(self):
        ct = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ct != "application/json":
            self._json(415, {"error": "Content-Type: application/json 만"}); return None
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n <= 0 or n > MAX_BODY:
            self._json(413 if n > MAX_BODY else 400, {"error": "본문 길이 오류"}); return None
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            assert isinstance(body, dict)
            return body
        except Exception:  # noqa: BLE001
            self._json(400, {"error": "JSON 오류"}); return None

    def do_GET(self):
        if not self._guard():
            return
        if self.path.split("?")[0] == "/status":
            eng = STATE["engine"]
            extra = {}
            if STATE["engine_name"] == "windows" and eng is not None:
                extra = dict(windows_voice=eng.voice_name, windows_culture=eng.culture)
            self._json(200, dict(ok=eng is not None, version=VERSION, engine=STATE["engine_name"], device=STATE["device"], dtype=STATE["dtype"],
                                 emotions=list(eng.prompts) if eng else [], voice_check=STATE["judge"] is not None, busy=STATE["busy"],
                                 waiting=STATE["waiting"], served=STATE["served"], cache_hits=STATE["cache_hits"], mem_cache=len(MEM),
                                 uptime_sec=round(time.time() - STATE["started"]), error=STATE["error"], fallback_reason=STATE["fallback_reason"],
                                 idle_sec=0 if STATE["busy"] else round(time.time() - STATE["last_use"]), pid=os.getpid(),
                                 raw_stream=True, speed_on_server=bool(eng is not None and (getattr(eng, "native_speed", False) or speed_available())),
                                 voice=STATE["default_voice"], voices=list(STATE["voices"]),
                                 voices_loaded=list(getattr(eng, "voices", {}) or {}) if eng else [],
                                 voice_load_sec=STATE["voice_load"], voice_fallback=STATE["voice_fallback"],
                                 vram=vram_info(), wanted_engine=STATE["wanted"],
                                 switched_at=STATE["switched_at"], gen=gen_view()["values"], **extra))
        elif self.path.split("?")[0] == "/config":
            self._json(200, {"ok": True, **gen_view()})
        else:
            self._json(404, {"error": "없는 주소"})

    def do_POST(self):
        if not self._guard():
            return
        path = self.path.split("?")[0]
        if path not in ("/tts", "/tts_stream", "/tts_lip", "/read", "/config"):
            self._json(404, {"error": "없는 주소"}); return
        body = self._body()
        if body is None:
            return
        if path == "/config":       # 세부 설정 바꾸기 — 엔진이 아직 준비 중이어도 값은 받아 둠(엔진이 뜨면 그 값으로)
            try:
                with GEN_LOCK:
                    changed, restart = gen_apply(body)
            except ValueError as ex:
                self._json(400, {"ok": False, "error": str(ex), **gen_view()}); return
            self._json(200, {"ok": True, "changed": {api: changed[name] for api, name in C.GEN_API.items() if name in changed},
                             "restart": restart, **gen_view()})
            return
        if STATE["engine"] is None:
            self._json(503, {"error": "엔진 준비 중" if not STATE["error"] else STATE["error"]}); return
        STATE["last_use"] = time.time()
        try:
            read, sents, emo, seed, yawn_word = prepare(body)
        except NoText as ex:
            self._json(400, {"error": str(ex), **({"yawn": True} if ex.yawn else {})}); return
        except ValueError as ex:
            self._json(400, {"error": str(ex)}); return
        self._yawn_word = yawn_word
        if path == "/read":
            self._json(200, {"read": read, "sentences": sents, "emotion": emo, "yawn": yawn_word}); return
        with WAIT_LOCK:
            if STATE["waiting"] >= 3:
                self._json(503, {"error": "대기 많음"}); return
            STATE["waiting"] += 1
        t0 = time.perf_counter()
        raw = path == "/tts_stream" and bool(body.get("raw"))
        sess = str(body.get("session") or "")[:64]
        try:
            with GEN_LOCK:
                STATE["waiting"] -= 1
                STATE["busy"] = True
                try:
                    voice = ensure_voice(body.get("_voice"))
                    if raw:
                        self._make_raw(body, sents, emo, seed, t0, sess, voice)
                    else:
                        self._make(path, read, sents, emo, seed, t0, voice, body)
                finally:
                    if STATE["switch_after"]:
                        why, STATE["switch_after"] = STATE["switch_after"], None
                        try:
                            switch_to_windows(why)
                        except Exception as ex:  # noqa: BLE001
                            log(f"윈도우 음성으로 바꾸지 못함: {type(ex).__name__}: {ex}")
                    STATE["busy"] = False
                    STATE["last_use"] = time.time()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            if raw:
                PLAY[sess] = 0.0
            log("받는 쪽이 연결을 끊음" + (" (본체 끼어들기·중단)" if raw else ""))
        except Exception as ex:  # noqa: BLE001
            STATE["error"] = f"{type(ex).__name__}: {ex}"
            log("오류: " + traceback.format_exc().replace("\n", " | "))
            try:
                self._json(500, {"error": STATE["error"]})
            except Exception:  # noqa: BLE001
                pass

    # ---- 빠르기: windows 는 엔진이 직접, qwen 은 apply_speed 일 때 서버가 줄임 ----
    def _speed_plan(self, body):
        speed = body.get("_speed", 1.0)
        eng = STATE["engine"]
        if speed == 1.0:
            return 1.0, None, True
        if getattr(eng, "native_speed", False):
            return speed, None, True
        if body.get("apply_speed"):
            from speech_rate import TimeStretch
            st = TimeStretch(speed, SR)
            if st.ok:
                return 1.0, st, True
        return 1.0, None, False

    def _make(self, path, read, sents, emo, seed, t0, voice, body):
        import numpy as np
        q = urllib.parse.quote(read)
        eng_speed, stretch, applied = self._speed_plan(body)

        def stretched(p16):
            return np.frombuffer(stretch.feed(p16.tobytes()), np.int16) if stretch else p16

        if path in ("/tts", "/tts_lip"):
            parts, hit = [], True
            for p, cached in synth(sents, emo, seed, voice=voice, speed=eng_speed, lang=body.get("_lang")):
                parts.append(stretched(p)); hit = hit and cached
            if stretch:
                parts.append(np.frombuffer(stretch.flush(), np.int16))
            pcm = np.concatenate(parts) if parts else np.zeros(0, np.int16)
            b = wav_bytes(pcm)
            gen = time.perf_counter() - t0
            if path == "/tts_lip":
                import base64
                from lipsync import lip_from_pcm16
                self._json(200, {"wav_base64": base64.b64encode(b).decode("ascii"), "lip": lip_from_pcm16(pcm, SR),
                                 "read": read, "emotion": emo, "yawn": self._yawn_word, "audio_sec": round(len(pcm) / SR, 2),
                                 "gen_sec": round(gen, 2), "cache": "hit" if hit else "miss", "engine": STATE["engine_name"],
                                 "speed_applied": applied, "voice": voice or STATE["default_voice"]})
                STATE["served"] += 1
                log(f"/tts_lip {emo} {len(pcm) / SR:.1f}초 소리 / {gen:.2f}초 | {shown(read)}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("X-Read", q)
            self.send_header("X-Emotion", urllib.parse.quote(emo))
            self.send_header("X-Audio-Seconds", f"{len(pcm) / SR:.2f}")
            self.send_header("X-Gen-Seconds", f"{gen:.2f}")
            self.send_header("X-Cache", "hit" if hit else "miss")
            self.send_header("X-Engine", STATE["engine_name"])
            self.send_header("X-Voice", urllib.parse.quote(str(voice or STATE["default_voice"] or "")))   # 실제로 말한 목소리(대체됐으면 기본)
            self.send_header("X-Speed-Applied", "1" if applied else "0")
            if self._yawn_word:
                self.send_header("X-Yawn", "1")
            self.end_headers()
            self.wfile.write(b)
            STATE["served"] += 1
            log(f"/tts {emo} {len(pcm) / SR:.1f}초 소리 / {gen:.2f}초 {'캐시' if hit else ''} | {shown(read)}")
        else:
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("X-Read", q)
            self.send_header("X-Emotion", urllib.parse.quote(emo))
            self.send_header("X-Engine", STATE["engine_name"])
            self.send_header("X-Speed-Applied", "1" if applied else "0")
            if self._yawn_word:
                self.send_header("X-Yawn", "1")
            self.end_headers()

            def send(b):
                if b:
                    self.wfile.write(f"{len(b):X}\r\n".encode() + b + b"\r\n")
                    self.wfile.flush()
            send(stream_header())
            first, total = None, 0
            for p, _ in synth(sents, emo, seed, check=False, voice=voice, speed=eng_speed, lang=body.get("_lang")):
                p = stretched(p)
                if len(p) == 0:
                    continue
                if first is None:
                    first = time.perf_counter() - t0
                total += len(p)
                send(p.tobytes())
            if stretch:
                tail = stretch.flush()
                total += len(tail) // 2
                send(tail)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            STATE["served"] += 1
            log(f"/tts_stream {emo} 첫 소리 {first or 0:.2f}초 · {total / SR:.1f}초 소리 / {time.perf_counter() - t0:.2f}초 | {shown(read)}")

    def _guarded(self, gen):
        """qwen 조각을 그대로 넘기다 그래픽 메모리 모자람이 나면 윈도우 음성으로 바꾸고 _SWITCHED 표시를 한 번 넘김."""
        try:
            for c in gen:
                yield c
        except Exception as ex:  # noqa: BLE001
            if STATE["engine_name"] == "qwen" and _is_oom(ex):
                switch_to_windows(f"그래픽 메모리 모자람({type(ex).__name__}) — 말하는 중에 윈도우 음성으로")
                yield _SWITCHED
                return
            raise

    def _gone(self):
        """받는 쪽이 연결을 닫았나(요청 본문 뒤로는 보낼 것이 없으니, 읽을 게 생기면 = 닫힘)."""
        import select
        import socket
        try:
            r, _, _ = select.select([self.connection], [], [], 0)
            if r:
                return self.connection.recv(1, socket.MSG_PEEK) == b""
        except OSError:
            return True
        return False

    def _make_raw(self, body, sents, emo, seed, t0, sess, voice=None):
        """본체용 스트림: 캐시·닮음 검사 없이 바로, 앞 무음 자르기, 재생 시계 맞추기(pace), 끊기면 바로 멈춤."""
        import numpy as np
        eng = STATE["engine"]
        try:
            pace = min(10.0, max(0.0, float(body.get("pace") or 0)))
        except (TypeError, ValueError):
            pace = 0.0
        eng_speed, stretch, applied = self._speed_plan(body)
        speed = body.get("_speed", 1.0)
        # 재생 시계: 보낸 소리가 이미 빨라졌으면(엔진·서버가 처리) 1배로, 아니면 받는 쪽이 줄일 것이므로 speed 로 나눔
        clock_div = 1.0 if (applied and speed != 1.0) else speed
        if body.get("reset"):
            PLAY[sess] = 0.0
        trim = body.get("trim", True) is not False
        kw = {"speed": eng_speed} if getattr(eng, "native_speed", False) else {"lang": C.TTS_NAMES.get(body.get("_lang") or "ko", "Korean")}
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Emotion", urllib.parse.quote(emo))
        self.send_header("X-Engine", STATE["engine_name"])
        self.send_header("X-Voice", urllib.parse.quote(str(voice or STATE["default_voice"] or "")))
        self.send_header("X-Speed-Applied", "1" if applied else "0")
        if self._yawn_word:
            self.send_header("X-Yawn", "1")
        self.end_headers()

        def send(b):
            if b:
                self.wfile.write(f"{len(b):X}\r\n".encode() + b + b"\r\n")
                self.wfile.flush()

        def paced(n):
            if not pace:
                return
            now = time.monotonic()
            PLAY[sess] = max(PLAY.get(sess, 0.0), now) + n / SR / clock_div
            while PLAY[sess] - time.monotonic() > pace:
                if self._gone():
                    raise ConnectionAbortedError("받는 쪽 끊음")
                time.sleep(min(0.05, PLAY[sess] - time.monotonic() - pace))
        send(stream_header())
        first, total, trimmed = None, 0, 0
        leading, tail = trim, np.zeros(0, np.float32)
        for i, s in enumerate(sents):
            sd = eng.seed_for(s, emo) if seed is None else int(seed) + i
            gen = eng.stream(s, emo, seed=sd, voice=voice, **kw)
            try:
                for chunk in self._guarded(gen):
                    if chunk is _SWITCHED:     # 그래픽 메모리 모자람 → 윈도우 음성으로 이 문장부터 다시(끊지 않음)
                        gen.close()
                        eng = STATE["engine"]
                        voice, stretch = None, None
                        kw = {"speed": speed} if speed != 1.0 else {}
                        gen = eng.stream(s, emo, seed=sd, **kw)
                        for c2 in gen:
                            p16 = eng.to_int16(c2)
                            if len(p16) == 0:
                                continue
                            if first is None:
                                first = time.perf_counter() - t0
                            total += len(p16)
                            send(p16.tobytes())
                            paced(len(p16))
                        leading = False
                        break
                    if self._gone():
                        raise ConnectionAbortedError("받는 쪽 끊음")
                    if leading:
                        chunk = np.concatenate([tail, chunk])
                        k = _onset(chunk)
                        if k is None and trimmed < MAX_TRIM_SEC * SR:
                            keep = int((PRE_ROLL + LEAD_MAX) * SR)
                            trimmed += max(0, len(chunk) - keep)
                            tail = chunk[-keep:]
                            continue
                        st = max(0, (k or 0) - int(PRE_ROLL * SR))
                        trimmed += st
                        chunk = chunk[st:]
                        leading = False
                    p16 = eng.to_int16(chunk)
                    if stretch:
                        p16 = np.frombuffer(stretch.feed(p16.tobytes()), np.int16)
                    if len(p16) == 0:
                        continue
                    if first is None:
                        first = time.perf_counter() - t0
                    total += len(p16)
                    send(p16.tobytes())
                    paced(len(p16))
            finally:
                gen.close()
            slow = float(STATE["cfg"]["목소리"].get("느림_기준_초", 4.0) or 4.0)
            if (i == 0 and first is not None and first > slow and STATE["engine_name"] == "qwen"
                    and str(STATE["device"]).startswith("cpu") and STATE["cfg"]["목소리"].get("CPU면_윈도우", True)):
                STATE["switch_after"] = f"CPU 김비서 목소리 첫 소리 {first:.1f}초 > 기준 {slow:.0f}초"
                log(f"느림 감지: {STATE['switch_after']} → 이 답을 끝낸 뒤 윈도우 음성으로 바꿈")
            if i < len(sents) - 1 and not leading:
                g = np.zeros(int(gap_sec() * SR), np.int16)
                total += len(g)
                send(g.tobytes())
                paced(len(g))
        if stretch:
            b = stretch.flush()
            total += len(b) // 2
            send(b)
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        STATE["served"] += 1
        log(f"/tts_stream(raw{'' if not voice else ' ' + voice}) 첫 소리 {(first or 0) * 1000:.0f}ms (앞 무음 {trimmed / SR * 1000:.0f}ms 자름) · {total / SR:.1f}초 소리"
            f"{'' if speed == 1.0 else f' (빠르기 {speed}배, 서버 처리 {int(applied)})'} / {time.perf_counter() - t0:.2f}초 | {shown(' '.join(sents))}")


def speed_available():
    try:
        import av  # noqa: F401
        return True
    except ImportError:
        return False


def warm_phrases():
    """phrases.txt(감정<TAB>문장) 를 미리 만들어 캐시에 둔다(CPU 일 때 특히 효과)."""
    if not os.path.exists(PHRASES):
        return
    n = 0
    began = time.time()          # GGUF: 켠 뒤 첫 10초는 미리 만들기를 쉼(앱의 첫 인사가 기다리지 않게)
    for ln in open(PHRASES, encoding="utf-8-sig"):
        ln = ln.strip()
        if not ln or ln.startswith("#") or "\t" not in ln:
            continue
        emo, text = ln.split("\t", 1)
        try:
            _, sents, emo, _, _ = prepare({"text": text, "emotion": emo})
        except ValueError:
            continue
        if STATE.get("dtype") == "gguf":
            # GGUF(라데온 판)는 한 문장 만드는 데 몇 초 걸림 → 사용자 요청이 기다리지 않게, 요청이 없고 조용할 때만 하나씩
            while STATE["waiting"] > 0 or STATE["busy"] or time.time() - max(STATE["last_use"], began) < 10.0:
                time.sleep(0.5)
        with GEN_LOCK:
            STATE["busy"] = True
            try:
                for _ in synth(sents, emo):
                    pass
                n += 1
            finally:
                STATE["busy"] = False
        time.sleep(0.05)
    log(f"자주 쓰는 말 {n}개 준비(캐시)")


def watch_parent(pid):
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x00100000, False, pid)            # SYNCHRONIZE
    if not h:
        log(f"부모 PID {pid} 못 찾음 — 감시 안 함"); return
    k.WaitForSingleObject(h, 0xFFFFFFFF)                  # 부모가 끝날 때까지 기다림
    log(f"부모 PID {pid} 끝남 → 목소리 서버도 끝냄")
    os._exit(0)


def main():
    ap = argparse.ArgumentParser(description="김비서 목소리 서버")
    ap.add_argument("--settings", default=None, help="사용자 설정 JSON(기본 %%APPDATA%%/KimBiseo/settings.json)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--device", default=None, help="auto | cuda | cpu (설정 '목소리.장치' 보다 우선)")
    ap.add_argument("--engine", default=None, help="qwen | windows (설정 '목소리.엔진' 보다 우선)")
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--no_warm", action="store_true")
    ap.add_argument("--no_cache", action="store_true", help="디스크 캐시를 쓰지 않음(메모리 캐시만)")
    ap.add_argument("--parent_pid", type=int, default=0)  # 실행 관리·펫이 켠 서버: 그 프로세스가 끝나면 서버도 끝남
    a = ap.parse_args()

    cfg = C.load(a.settings)
    STATE["cfg"] = cfg
    STATE["lang"] = C.app_lang(cfg)
    STATE["log"] = C.Logger("voice.log", C.path(cfg, "로그"), "[목소리 서버]")
    STATE["gen"] = C.gen_from_cfg(cfg, warn=log)
    STATE["show_text"] = bool(cfg["목소리"].get("로그_글_남기기"))
    STATE["cache_dir"] = None if a.no_cache else os.path.join(C.path(cfg, "캐시"), "tts")
    C.apply_hf_env(cfg)
    user_dict = os.path.expandvars(str(cfg["목소리"].get("발음사전") or ""))
    if user_dict:
        text_norm.EXTRA_DICTS[:] = [user_dict]
    port = a.port or int(cfg["포트"]["목소리"])
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)   # 포트가 이미 쓰이면 여기서 오류로 끝남
    srv.daemon_threads = True
    log(f"목소리 서버 {VERSION} 시작 http://127.0.0.1:{port}  (PID {os.getpid()})")
    engine = (a.engine or cfg["목소리"].get("엔진") or "qwen").lower()
    device = a.device or cfg["목소리"].get("장치") or "auto"
    threads = a.threads or int(cfg["목소리"].get("CPU_스레드") or 8)

    def boot():
        try:
            eng = load_engine(cfg, engine, device, threads)
            with GEN_LOCK:   # 첫 요청이 느리지 않게 짧은 말 하나로 예열(캐시에 남기지 않음)
                t0 = time.perf_counter()
                eng.speak(WARM_TEXT.get(STATE.get("lang") or "ko", "안녕하세요."))
                log(f"예열 {time.perf_counter() - t0:.1f}초")
            if not a.no_warm and cfg["목소리"].get("미리만들기", True):
                warm_phrases()
        except Exception as ex:  # noqa: BLE001
            STATE["error"] = f"{type(ex).__name__}: {ex}"
            log("엔진 준비 실패: " + traceback.format_exc().replace("\n", " | "))
    threading.Thread(target=boot, daemon=True).start()
    if a.parent_pid:
        threading.Thread(target=watch_parent, args=(a.parent_pid,), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
