# 김비서 음성 쪽 설정 읽기 — 귀 서버(ear_server.py)·목소리 서버(tts_server.py)가 같이 쓴다.
#
# 순서(뒤가 앞을 덮음, 깊은 병합)
#   1) 이 파일의 DEFAULTS (음성 쪽 항목 전부 — 코드가 기본값 없이 꺼내 써도 KeyError 가 나지 않게)
#   2) 저장소의 app/config/default.json 이 있으면 그 안의 같은 항목
#   3) 사용자 설정: --settings <파일> > 환경변수 KIMBISEO_SETTINGS > %APPDATA%\KimBiseo\settings.json
# 경로 값의 %APPDATA%·%LOCALAPPDATA% 같은 환경변수는 읽을 때 풀어 준다.
# 모델 값이 절대 경로가 아니면 '경로.모델' 폴더 아래의 그 이름으로 본다(installer/get_models.py 가 받는 곳).
import copy
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
VOICES_FILE = os.path.join(HERE, "voices.json")
DEFAULT_VOICE = "kimbiseo"
GENDER_VOICES = {"여": "kimbiseo", "남": "kimbiseo_m"}

DEFAULTS = {
    "언어": "ko",                   # 앱 언어(0.1.18~) — 받아쓰기·목소리 기본 언어. ko·en·ja·zh
    "포트": {"목소리": 8871, "귀": 8872},
    "경로": {
        "자료": "%APPDATA%/KimBiseo",          # 읽을 때 abspath 가 윈도우 경로(\)로 바꿈
        "모델": "%LOCALAPPDATA%/KimBiseo/models",
        "캐시": "%LOCALAPPDATA%/KimBiseo/cache",
        "로그": "%APPDATA%/KimBiseo/logs",
    },
    "펫": {
        "성별": "여",               # 목소리 자동 연결: 여 → kimbiseo, 남 → kimbiseo_m (사용자 목소리 고정이 없을 때)
    },
    "모델": {
        "오프라인": True,          # 모델은 설치 때 받아 두고, 켤 때는 인터넷에 묻지 않음(HF_HUB_OFFLINE=1)
        "hf_home": "",            # 비우면 '경로.캐시'\hf_home (라이브러리가 쓰는 작은 캐시 자리)
    },
    "귀": {
        "엔진": "whisper",
        "모델": "whisper-large-v3-turbo",
        "장치": "auto",            # auto | cuda | cpu
        "언어": "korean",           # 예전 칸(0.1.17 까지). 앱 언어가 ko 일 때만 씀 — 받아쓰기 언어는 ear_language()
        "받아쓰기_언어": "",          # ""(앱 언어 따름) | auto(말마다 자동 감지) | ko·en·ja·zh
        "핫워드": [],              # 잘 못 알아듣는 낱말(예: 제품 이름)을 whisper 앞글로 줌
        "그래픽메모리_필요_GB": 2.2,   # auto 일 때 그래픽카드를 고르는 남은 메모리 기준
        "최대_초": 60,             # 한 번에 받는 소리 길이 상한
        "CPU_스레드": 8,           # 그래픽카드 없이 돌 때 쓰는 CPU 스레드 수
        "로그_글_남기기": False,     # True 면 받아쓴 글 앞부분을 로그에 남김(기본은 글자 수만)
    },
    "목소리": {
        "엔진": "qwen",            # qwen(김비서 목소리) | windows(윈도우 기본 음성)
        "예비": "windows",         # qwen 을 못 띄우면 이것으로(빈 값이면 예비 없음)
        "모델": "Qwen3-TTS-12Hz-0.6B-Base",
        "장치": "auto",            # auto | cuda | cpu (방식 gguf 일 때: auto=불칸 그래픽 있으면 그것 | cpu)
        "방식": "auto",            # auto(엔비디아면 torch, 아니면 GGUF 가 깔려 있으면 gguf, 둘 다 아니면 예전대로 윈도우 음성) | torch | gguf
        "GGUF_모델": "Qwen3-TTS-12Hz-0.6B-Base-GGUF",   # 라데온 판(installer/radeon) 이 받는 모델 폴더 이름
        "GGUF_실행폴더": "",         # llama.cpp(b10621) DLL 폴더. 비우면 <설치폴더>/runtime/llama-tts
        "불칸_장치": "",             # 그래픽카드가 여럿일 때 번호(GGML_VK_VISIBLE_DEVICES). 비우면 첫째
        "그래픽메모리_상한_GB": 1.8,
        "CPU_스레드": 8,
        "목소리": "kimbiseo",       # voices.json 의 이름. 사용자 설정에 이 값이 있으면 고정,
                                     #   없으면 펫.성별 자동(여: kimbiseo, 남: kimbiseo_m)
        "성별_목소리": {"여": "kimbiseo", "남": "kimbiseo_m"},   # voices.json 의 같은 항목이 있으면 그것을 우선
        "참고음성_폴더": "",         # 비우면 voices.json 의 폴더. 폴더 안에 참고목록.json + wav
        "윈도우_목소리": "",         # 윈도우 음성 이름 일부(비우면 한국어 음성 중 첫째)
        "발음사전": "",             # 사용자 발음 사전(tsv) — 저장소 기본 사전보다 먼저 적용
        "미리만들기": True,          # phrases.txt 의 말을 켤 때 미리 만들어 캐시에 둠
        "닮음검사": {"켜기": False, "모델": "", "도우미_파이썬": ""},
        "로그_글_남기기": False,
        # 세부 설정(설정 화면 → 목소리 → 세부 설정). 범위는 GEN_LIMITS — 벗어난 값은 기본값으로 읽음
        "온도": 0.7,               # 김비서 목소리(qwen) 억양 변화. 낮을수록 늘 비슷하게
        "세부_온도": 0.9,           # 소리 잔결(코드 예측기)
        "반복_벌점": 1.05,
        "top_k": 50,               # 서버를 켤 때만 읽음(그래픽카드 그래프에 굳는 값)
        "문장_쉼_초": 0.0,          # 문장 사이에 더 넣는 쉼
    },
}

# 목소리 세부 설정이 받을 수 있는 범위(설정 이름 → (최소, 최대, 기본, 정수인지)). 화면(app/config/choices.json '목소리_세부')과 같은 값.
GEN_LIMITS = {
    "온도": (0.3, 1.0, 0.7, False),
    "세부_온도": (0.5, 1.1, 0.9, False),
    "반복_벌점": (1.0, 1.3, 1.05, False),
    "top_k": (10, 100, 50, True),
    "문장_쉼_초": (0.0, 1.0, 0.0, False),
}
GEN_API = {"temperature": "온도", "sub_temperature": "세부_온도", "repetition_penalty": "반복_벌점", "top_k": "top_k", "gap": "문장_쉼_초"}


def gen_check(name, value):
    """세부 설정 값 하나 검사 → (값, 오류 글|None). 범위를 벗어나면 고쳐 넣지 않고 오류."""
    lo, hi, _d, whole = GEN_LIMITS[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, f"{name}: 숫자로 넣어 주세요"
    x = float(value)
    if x != x or x < lo - 1e-9 or x > hi + 1e-9:
        return None, f"{name}: {lo:g}부터 {hi:g}까지만 돼요"
    if whole:
        if abs(x - round(x)) > 1e-9:
            return None, f"{name}: 소수점 없는 숫자로 넣어 주세요"
        return int(round(x)), None
    return round(min(hi, max(lo, x)), 3), None


def gen_from_cfg(cfg, warn=None):
    """설정의 목소리 세부 값 → {이름: 값}. 없거나 범위를 벗어난 값은 기본값(한 줄 알림)."""
    vc = cfg.get("목소리") or {}
    out = {}
    for name, (_lo, _hi, default, _w) in GEN_LIMITS.items():
        v, err = gen_check(name, vc.get(name, default))
        if err:
            if warn is not None:
                warn(f"[설정] 목소리.{err} → 기본값 {default}")
            v = default
        out[name] = v
    return out


def _load_voices():
    try:
        with open(VOICES_FILE, encoding="utf-8-sig") as f:
            j = json.load(f)
        return j if isinstance(j, dict) else {}
    except (OSError, ValueError):
        return {}


def _user_voice(user):
    if not isinstance(user, dict):
        return None
    v = (user.get("목소리") or {}).get("목소리")
    return v if isinstance(v, str) and v.strip() and v.strip() != "auto" else None   # "auto" = 직접 고르지 않음(옷·성별에 맞춤)


def _asset_problem(name, reg):
    entry = (reg.get("목록") or {}).get(name)
    if not isinstance(entry, dict):
        return f"목소리 {name} 정보 없음"
    folder = str(entry.get("폴더") or "").strip()
    if not folder:
        return f"목소리 {name} 폴더 정보 없음"
    folder = os.path.expandvars(folder)
    folder = folder if os.path.isabs(folder) else os.path.normpath(os.path.join(REPO, folder))
    manifest = os.path.join(folder, "참고목록.json")
    if not os.path.isfile(manifest):
        return f"목소리 {name} 참고음성 없음"
    try:
        with open(manifest, encoding="utf-8-sig") as f:
            j = json.load(f)
    except (OSError, ValueError):
        return f"목소리 {name} 참고목록.json 읽기 실패"
    base = j.get("기본") if isinstance(j.get("기본"), dict) else {}
    wav = str(base.get("wav") or "").strip()
    if not wav:
        return f"목소리 {name} 참고음성 없음"
    if not os.path.isfile(os.path.join(folder, wav)):
        return f"목소리 {name} 참고음성 파일 없음({wav})"
    return ""


def resolve_voice(cfg, user=None, log=None):
    """사용자 설정에 '목소리.목소리' 가 있으면 고정, 없으면("auto" 포함) 펫.성별 로 고른다.
    (펫이 입은 옷에 맞춘 목소리는 본체·펫이 요청마다 "voice" 로 보낸다 — 여기서 정하는 것은 서버의 기본 목소리.)
    고른 목소리의 참고음성이 없으면 기본목소리로 대체하고 한 줄 남긴다(서버가 윈도우 음성으로
    넘어가지 않게, 기본목소리는 그대로 쓸 수 있게). 목소리 서버는 요청마다 voice 를 받으므로
    실행 중 성별이 바뀌어도 이 값은 다음에 서버를 켤 때 반영된다."""
    reg = _load_voices()
    default = str(reg.get("기본목소리") or DEFAULT_VOICE)
    pinned = _user_voice(user)
    gender = str((cfg.get("펫") or {}).get("성별") or "여")
    mapping = reg.get("성별_목소리") if isinstance(reg.get("성별_목소리"), dict) else None
    if not isinstance(mapping, dict):
        mapping = (cfg.get("목소리") or {}).get("성별_목소리")
    if not isinstance(mapping, dict):
        mapping = GENDER_VOICES
    want = pinned or str(mapping.get(gender) or default)
    problem = _asset_problem(want, reg)
    effective = default if problem else want
    if problem and log is not None:
        log(f"{problem} → 기본 {default} 사용")
    cfg.setdefault("목소리", {})["목소리"] = effective
    return cfg


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        j = json.load(f)
    if not isinstance(j, dict):
        raise ValueError(f"설정 파일이 객체(JSON {{}})가 아님: {path}")
    return j


def user_settings_path(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("KIMBISEO_SETTINGS"):
        return os.environ["KIMBISEO_SETTINGS"]
    return os.path.abspath(os.path.join(os.path.expandvars(DEFAULTS["경로"]["자료"]), "settings.json"))


def load(settings_path=None, warn=print):
    cfg = copy.deepcopy(DEFAULTS)
    repo_default = os.path.join(REPO, "app", "config", "default.json")
    if os.path.isfile(repo_default):
        j = _read_json(repo_default)
        cfg = deep_merge(cfg, {k: j[k] for k in DEFAULTS if k in j})
    p = user_settings_path(settings_path)
    user = None
    if os.path.isfile(p):
        try:
            user = _read_json(p)
            cfg = deep_merge(cfg, user)
        except (OSError, ValueError) as ex:
            warn(f"[설정] 사용자 설정을 못 읽음 → 기본값: {p} ({ex})")
    elif settings_path:
        warn(f"[설정] 사용자 설정 파일 없음 → 기본값: {p}")
    cfg = resolve_voice(cfg, user or {}, log=warn)
    cfg["_settings_file"] = p if os.path.isfile(p) else ""
    return cfg


WHISPER_NAMES = {"ko": "korean", "en": "english", "ja": "japanese", "zh": "chinese"}
TTS_NAMES = {"ko": "Korean", "en": "English", "ja": "Japanese", "zh": "Chinese"}


def app_lang(cfg):
    v = str((cfg or {}).get("언어") or "ko").strip().lower()[:2]
    return v if v in WHISPER_NAMES else "ko"


def ear_language(cfg):
    """받아쓰기 기본 언어(whisper 이름) — None 이면 자동 감지.
    귀.받아쓰기_언어: ''(앱 언어) | 'auto' | 코드. 앱 언어가 ko 이고 칸이 비면 예전 칸 귀.언어(기본 korean)."""
    e = (cfg or {}).get("귀") or {}
    v = str(e.get("받아쓰기_언어") or "").strip().lower()
    if v == "auto":
        return None
    if v[:2] in WHISPER_NAMES:
        return WHISPER_NAMES[v[:2]]
    lg = app_lang(cfg)
    if lg == "ko":
        return str(e.get("언어") or "korean")
    return WHISPER_NAMES[lg]


def path(cfg, key):
    """'경로' 항목 하나를 풀어 준다(폴더는 만들지 않음)."""
    return os.path.abspath(os.path.expandvars(str(cfg["경로"][key])))


def model_path(cfg, value):
    """모델 값(절대 경로 / 받은 모델 이름) → 폴더 경로."""
    v = os.path.expandvars(str(value or ""))
    if not v:
        return ""
    if os.path.isabs(v):
        return v
    return os.path.join(path(cfg, "모델"), v)


def gguf_paths(cfg):
    """(GGUF 모델 폴더, llama.cpp DLL 폴더) — 라데온 판 목소리."""
    v = cfg["목소리"]
    lib_dir = os.path.expandvars(str(v.get("GGUF_실행폴더") or os.environ.get("KIMBISEO_GGUF_LIB") or ""))
    if not lib_dir:
        lib_dir = os.path.join(os.path.dirname(REPO), "runtime", "llama-tts")     # <설치폴더>/src/voice → <설치폴더>/runtime
    return model_path(cfg, v.get("GGUF_모델") or "Qwen3-TTS-12Hz-0.6B-Base-GGUF"), os.path.abspath(lib_dir)


def gguf_ready(cfg):
    """라데온 판 목소리가 깔려 있는지(모델 폴더의 토커 파일 + llama.dll)."""
    m, d = gguf_paths(cfg)
    dll = "llama.dll" if os.name == "nt" else "libllama.so"
    return bool(m) and os.path.isfile(os.path.join(m, "qwen3_tts_talker.q5_k.gguf")) and os.path.isfile(os.path.join(d, dll))


def apply_hf_env(cfg):
    """transformers·huggingface_hub 를 import 하기 전에 부른다."""
    if cfg["모델"].get("오프라인", True):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    hf_home = os.path.expandvars(str(cfg["모델"].get("hf_home") or "")) or os.path.join(path(cfg, "캐시"), "hf_home")
    os.environ.setdefault("HF_HOME", hf_home)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def gpu_free_mib():
    """(남은 MiB, 전체 MiB). nvidia-smi 가 없으면 (0, 0)."""
    import subprocess
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=flags).stdout.strip().splitlines()[0]
        used, tot = [float(v) for v in out.split(",")]
        return tot - used, tot
    except Exception:  # noqa: BLE001
        return 0.0, 0.0


def pick_device(want, need_gb, log=print):
    """'auto' → 그래픽카드 남은 메모리가 need_gb 이상이고 CUDA 가 되면 cuda, 아니면 cpu."""
    want = str(want or "auto").lower()
    if want != "auto":
        return want
    import torch
    free, _ = gpu_free_mib()
    dev = "cuda" if (torch.cuda.is_available() and free >= need_gb * 1024) else "cpu"
    log(f"장치 자동 선택: 그래픽 메모리 남은 {free:.0f}MiB / 필요 {need_gb * 1024:.0f}MiB → {dev}")
    return dev


class Logger:
    """콘솔 + 파일(경로.로그 아래). 파일을 못 쓰면 콘솔만."""

    def __init__(self, name, log_dir=None, tag=""):
        self.tag = tag
        self.file = None
        if log_dir:
            try:
                os.makedirs(log_dir, exist_ok=True)
                self.file = os.path.join(log_dir, name)
            except OSError:
                self.file = None

    def __call__(self, *parts):
        import time
        line = time.strftime("%Y-%m-%d %H:%M:%S ") + (self.tag + " " if self.tag else "") + " ".join(str(p) for p in parts)
        try:
            print(line, flush=True)
        except (OSError, ValueError):
            pass
        if self.file:
            try:
                with open(self.file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
