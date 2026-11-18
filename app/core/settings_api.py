# 화면(처음 화면·설정)에서 바꾸는 설정 — 받을 수 있는 항목·값 검사·언제 반영되는지.
#   반영 시점
#     즉시      : 저장하면 지금 대화에도 바로(이름·별칭·호칭·말투·말 빠르기·끼어들기 감도·이름 부르기·두뇌 모드·목소리 견본)
#     다음대화  : 대화를 다시 연결하면(두뇌 방식·주소·모델, 연결 인사, 기억 켜기)
#     다시켜기  : 그 서버를 다시 켜야(목소리 엔진·장치 → 목소리 서버, 받아쓰기 장치 → 귀 서버)
#     펫        : 펫에 바로 알림(옷 받기 동의 → 펫 /packs/auto, 옷 → 펫 /skin) · 펫이 꺼져 있으면 다음에 켜질 때(실행기가 --auto-pack)
#   비밀값(열쇠)은 여기로 받지 않는다 — /api/secret → core/keystore.
import json
import os
import re
import time

import httpx

from . import config as C
from . import keystore
from . import voice_choice as V
from .wake import name_warning

CHOICES_FILE = os.path.join(C.APP, "config", "choices.json")
SECRET_NAMES = ("url", "openai", "claude", "compat")
CLI_KINDS = ("claude_cli", "codex_cli")


def choices():
    with open(CHOICES_FILE, encoding="utf-8") as f:
        return json.load(f)


def _enum(*vals):
    return {"t": "enum", "v": vals}


def _range(lo, hi, whole=False):
    return {"t": "range", "min": lo, "max": hi, "int": whole}


# 목소리 세부 설정(온도·쉼·빠르기 …)의 범위·기본값 — 화면 고르기 목록(choices.json '목소리_세부')과 같은 표를 쓴다.
#   목소리 서버(voice/config.py GEN_LIMITS)도 같은 범위로 한 번 더 막는다(tests/unit/test_settings.py 가 두 표가 같은지 봄).
VOICE_DETAIL_WHEN = {"top_k": "다시켜기:목소리"}       # CUDA 그래프에 굳는 값이라 서버를 다시 켜야 함. 나머지는 바로.


def voice_detail():
    """[{key, 이름, min, max, step, 기본, 단위, 엔진, 설명, 정수?}] — choices.json 에서."""
    try:
        rows = choices().get("목소리_세부") or []
    except (OSError, ValueError):
        rows = []
    return [r for r in rows if isinstance(r, dict) and r.get("key")]


def _voice_fields():
    out = {}
    for r in voice_detail():
        k = "목소리." + str(r["key"])
        out[k] = (_range(float(r["min"]), float(r["max"]), bool(r.get("정수"))), VOICE_DETAIL_WHEN.get(r["key"], "즉시"), str(r.get("이름") or r["key"]))
    return out


# 경로 → (검사, 반영 시점, 화면 이름)
FIELDS = {
    "언어": (_enum("ko", "en", "ja", "zh"), "다음대화", "언어"),
    "귀.받아쓰기_언어": (_enum("", "auto", "ko", "en", "ja", "zh"), "다음대화", "받아쓰기 언어"),
    "비서.이름": ({"t": "name"}, "즉시", "비서 이름"),
    "비서.별칭": ({"t": "list", "n": 20, "len": 20}, "즉시", "비슷한 이름(별칭)"),
    "비서.말투": (_enum("auto", "존댓말", "편한 존댓말", "반말"), "즉시", "말투"),
    "비서.성격": ({"t": "persona"}, "즉시", "성격 설명"),
    "비서.답길이": (_enum("짧게", "보통", "자세히"), "즉시", "답 길이"),
    "사용자.호칭": ({"t": "str", "len": 10, "empty": True}, "즉시", "나를 부르는 말"),
    "사용자.기본장소": ({"t": "str", "len": 30, "empty": True}, "즉시", "사는 곳(날씨)"),
    "펫.성별": (_enum("여", "남"), "펫", "펫 성별"),
    "펫.옷": ({"t": "pet"}, "펫", "펫 캐릭터"),
    "펫.옷_받기": ({"t": "bool"}, "펫", "기본 옷 받기(동의)"),
    "펫.옷목록_주소": ({"t": "url", "empty": True}, "펫", "옷 목록 주소"),
    "두뇌.방식": (_enum("claude_cli", "codex_cli", "local", "url", "compat", "openai", "claude"), "다음대화", "두뇌"),
    "두뇌.호환_주소": ({"t": "url", "empty": True}, "다음대화", "OpenAI 호환 API 주소"),
    "두뇌.호환_모델": ({"t": "str", "len": 120, "empty": True}, "다음대화", "OpenAI 호환 API 모델 이름"),
    "두뇌.구독_클로드_모델": (_enum("haiku", "sonnet", "opus"), "다음대화", "구독 클로드 모델"),
    "두뇌.구독_GPT_모델": ({"t": "str", "len": 60, "empty": True}, "다음대화", "구독 GPT 모델"),
    "두뇌.구독_GPT_생각": (_enum("", "none", "minimal", "low", "medium", "high"), "다음대화", "구독 GPT 생각 정도"),
    "두뇌.주소": ({"t": "url", "empty": True}, "다음대화", "두뇌 주소"),
    "두뇌.모델": ({"t": "str", "len": 120, "empty": True}, "다음대화", "두뇌 모델 이름"),
    "두뇌.모드": (_enum("빠른", "꼼꼼"), "즉시", "빠른·꼼꼼 모드"),
    "두뇌.openai_주소": ({"t": "url", "empty": True}, "다음대화", "GPT 주소"),
    "두뇌.openai_모델": ({"t": "str", "len": 80, "empty": True}, "다음대화", "GPT 모델 이름"),
    "두뇌.claude_모델": ({"t": "claude"}, "다음대화", "클로드 모델"),
    "목소리.엔진": (_enum("qwen", "windows"), "다시켜기:목소리", "목소리 종류"),
    "목소리.목소리": ({"t": "voice"}, "즉시", "목소리 견본"),
    "목소리.장치": (_enum("auto", "cuda", "cpu"), "다시켜기:목소리", "목소리 장치"),
    "목소리.말속도": (_range(0.7, 1.6), "즉시", "말 빠르기"),       # choices.json '목소리_세부'가 있으면 아래에서 그 범위로 덮음
    "귀.장치": (_enum("auto", "cuda", "cpu"), "다시켜기:귀", "받아쓰기 장치"),
    "대화.끼어들기_감도": ({"t": "num", "v": (0.3, 0.4, 0.5)}, "즉시", "끼어들기 감도"),
    "대화.이름부르기": ({"t": "bool"}, "즉시", "이름을 불러야 대답"),
    "대화.연결인사": ({"t": "bool"}, "다음대화", "연결 인사"),
    "화면.마이크": ({"t": "str", "len": 300, "empty": True}, "즉시", "마이크"),
    "화면.마이크_이름": ({"t": "str", "len": 200, "empty": True}, "즉시", "마이크 이름"),
    "화면.스피커": ({"t": "str", "len": 300, "empty": True}, "즉시", "스피커"),
    "화면.스피커_이름": ({"t": "str", "len": 200, "empty": True}, "즉시", "스피커 이름"),
    "화면.글자": (_enum("보통", "크게", "아주 크게"), "즉시", "글자 크기"),
    "통역.켜기": ({"t": "bool"}, "즉시", "통역 모드 쓰기"),
    "통역.목소리_엔진": (_enum("원어민", "글자만"), "즉시", "통역 목소리"),
    "통역.환율_켜기": ({"t": "bool"}, "즉시", "통역 환율(원화로 바꿔 보여 주기)"),
    "통역.자동끔_분": ({"t": "range", "min": 1, "max": 60, "int": True}, "즉시", "통역 자동으로 끄기(분)"),
    "통역.두뇌_주소": ({"t": "url", "empty": True}, "즉시", "통역용 AI 주소(선택)"),
    "통역.두뇌_모델": ({"t": "str", "len": 120, "empty": True}, "즉시", "통역용 AI 모델 이름(선택)"),
    "폰.켜기": ({"t": "bool"}, "폰", "폰 연결 켜기"),
    "폰.테일스케일_허용": ({"t": "bool"}, "폰", "테일스케일로도 연결 받기"),
    "폰.PC조작_허용": ({"t": "bool"}, "다음대화", "폰으로 말해도 PC 조작"),
    "목소리등록.명령만": ({"t": "bool"}, "즉시", "등록한 목소리만 명령 받기"),
    "목소리등록.문턱": ({"t": "num", "v": (0.35, 0.4, 0.48)}, "즉시", "목소리 확인 엄격함"),
    "기억.켜기": ({"t": "bool"}, "다음대화", "기억 켜기"),
    "기억.자동": ({"t": "bool"}, "다음대화", "자동 기억"),
    "기억.일기": ({"t": "bool"}, "다음대화", "대화 일기"),
    "처음설정.끝": ({"t": "bool"}, "즉시", "처음 설정 끝"),
}
FIELDS.update(_voice_fields())      # 목소리.온도·세부_온도·반복_벌점·top_k·문장_쉼_초·말속도
VOICE_GEN_KEYS = tuple(k for k in FIELDS if k.startswith("목소리.") and k.split(".", 1)[1] in ("온도", "세부_온도", "반복_벌점", "top_k", "문장_쉼_초"))
RESTART_NAME = {"목소리": "목소리 서버", "귀": "받아쓰기(귀) 서버"}
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def flatten(d, pre=""):
    out = {}
    for k, v in (d or {}).items():
        key = f"{pre}.{k}" if pre else str(k)
        if isinstance(v, dict) and key not in FIELDS:
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def nest(flat):
    out = {}
    for k, v in flat.items():
        cur = out
        parts = k.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = v
    return out


def get(cfg, key, default=None):
    cur = cfg
    for p in key.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


# ---------------------------------------------------------------- 성별 → 목소리
def resolve_voice(cfg, user=None, log=None, registry=None):
    """지금 쓸 목소리 판단(펫.성별 자동 / 사용자 목소리 고정 / 자산 없음 대체).
    시험과 화면이 같은 함수를 쓴다. 자세한 규칙은 core/voice_choice.py."""
    return V.resolve(cfg, user=user, log=log, registry=registry)


def resolve_tone(cfg, user=None):
    """지금 쓸 말투 판단(사용자 고정 / 펫.성별 자동). 시험과 화면이 같은 함수를 쓴다."""
    return V.resolve_tone(cfg, user=user)


def voice_warning(cfg, clean):
    """이번 저장으로 목소리가 자산 없는 값이 되면 화면·기록에 보일 한 줄. 아니면 ""."""
    if not ({"펫.성별", "목소리.목소리"} & set(clean)):
        return ""
    user = V.user_from_cfg(cfg)
    pinned = clean["목소리.목소리"] if "목소리.목소리" in clean else V.user_voice(user)
    if pinned == V.AUTO:
        pinned = None
    if pinned:
        target = pinned
    else:
        target = V.voice_for_gender(clean.get("펫.성별", (cfg.get("펫") or {}).get("성별")))
    problem = V.asset_problem(target)
    return f"{problem} → 기본 {V.DEFAULT_VOICE} 사용" if problem else ""


def _clean_str(v, n, empty):
    if not isinstance(v, str):
        raise ValueError("글자로 넣어 주세요.")
    s = _CTRL.sub("", v).strip()
    if not s and not empty:
        raise ValueError("비어 있으면 안 돼요.")
    if len(s) > n:
        raise ValueError(f"{n}글자까지 돼요.")
    return s


def _check(key, rule, v, ch):
    t = rule["t"]
    if t == "name":
        s = _clean_str(v, 12, False)
        if not re.search(r"[0-9A-Za-z가-힣぀-ヿ一-鿿]", s):
            raise ValueError("한글·영어·숫자가 들어간 이름이어야 해요.")
        return s
    if t == "str":
        return _clean_str(v, rule["len"], rule.get("empty", False))
    if t == "list":
        if not isinstance(v, list):
            raise ValueError("목록으로 넣어 주세요.")
        out = []
        for x in v[: rule["n"]]:
            s = _clean_str(x, rule["len"], True)
            if s and s not in out:
                out.append(s)
        return out
    if t == "enum":
        if v not in rule["v"]:
            raise ValueError("고를 수 있는 값이 아니에요: " + ", ".join(map(str, rule["v"])))
        return v
    if t == "num":
        if isinstance(v, bool):
            raise ValueError("숫자로 넣어 주세요.")
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise ValueError("숫자로 넣어 주세요.") from None
        hit = next((c for c in rule["v"] if abs(c - x) < 0.026), None)
        if hit is None:
            raise ValueError("고를 수 있는 값: " + ", ".join(map(str, rule["v"])))
        return hit
    if t == "range":
        if isinstance(v, bool) or isinstance(v, (list, dict)):
            raise ValueError("숫자로 넣어 주세요.")
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise ValueError("숫자로 넣어 주세요.") from None
        if x != x or x in (float("inf"), float("-inf")):
            raise ValueError("숫자로 넣어 주세요.")
        lo, hi = rule["min"], rule["max"]
        if x < lo - 1e-9 or x > hi + 1e-9:       # 범위를 벗어난 값은 고쳐 넣지 않고 막는다
            raise ValueError(f"{lo:g}부터 {hi:g}까지만 돼요.")
        x = min(hi, max(lo, x))
        if rule.get("int"):
            if abs(x - round(x)) > 1e-9:
                raise ValueError("소수점 없는 숫자로 넣어 주세요.")
            return int(round(x))
        return round(x, 3)
    if t == "persona":
        from .prompt import PERSONA_MAX
        if not isinstance(v, str):
            raise ValueError("글자로 넣어 주세요.")
        s = re.sub(r"\s+", " ", _CTRL.sub(" ", v)).strip()
        if len(s) > PERSONA_MAX:
            raise ValueError(f"{PERSONA_MAX}글자까지 돼요.")
        return s
    if t == "bool":
        if not isinstance(v, bool):
            raise ValueError("켜기/끄기(true/false)로 넣어 주세요.")
        return v
    if t == "url":
        s = _clean_str(v, 300, rule.get("empty", False))
        if s and not re.match(r"^https?://[^\s/]+(/[^\s]*)?$", s):
            raise ValueError("http:// 또는 https:// 로 시작하는 주소를 넣어 주세요.")
        if s and "@" in s.split("//", 1)[1].split("/", 1)[0]:
            raise ValueError("주소에 계정·비밀번호(…@)를 넣지 말아 주세요. 열쇠는 '열쇠' 칸에 넣어요.")      # 주소는 설정 파일·기록에 남으므로
        return s.rstrip("/")
    if t == "pet":
        ids = [p["id"] for p in ch.get("펫", [])]
        if v not in ids:
            raise ValueError("목록에 있는 펫만 고를 수 있어요.")
        return v
    if t == "voice":
        if v == V.AUTO:      # '옷에 맞춤(자동)' — 직접 고르지 않음
            return v
        ok = [x["id"] for x in ch.get("목소리", []) if x.get("준비")]
        if v not in ok:
            raise ValueError("아직 준비되지 않은 목소리예요." if v in [x["id"] for x in ch.get("목소리", [])] else "모르는 목소리예요.")
        return v
    if t == "claude":
        if v not in ch.get("클로드_모델", []):
            raise ValueError("목록에 있는 클로드 모델만 고를 수 있어요.")
        return v
    raise ValueError("모르는 항목")


def validate(changes, cfg, voice_warn=""):
    """화면이 보낸 바꿀 값(겹친 dict 또는 '가.나' 키) → (깨끗한 평평한 값, 오류{키: 글}, 경고[글]).
    voice_warn: 이 PC 사양으로 김비서 목소리가 무거울 때의 안내(sysinfo.recommend 의 목소리_경고)."""
    ch = choices()
    flat = flatten(changes if isinstance(changes, dict) else {})
    clean, errors, warns = {}, {}, []
    for k, v in flat.items():
        if k not in FIELDS:
            errors[k] = "화면에서 바꿀 수 없는 항목이에요."
            continue
        try:
            clean[k] = _check(k, FIELDS[k][0], v, ch)
        except ValueError as ex:
            errors[k] = str(ex)
    if "비서.이름" in clean:
        w = name_warning(clean["비서.이름"])
        if w:
            warns.append(w)
        if clean["비서.이름"] != C.names(cfg)[0] and "비서.별칭" not in clean:
            clean["비서.별칭"] = []   # 이름만 바꾸면 옛 이름의 별칭은 버림(옛 이름으로 깨지 않게)
    if "비서.별칭" in clean:
        name = clean.get("비서.이름") or C.names(cfg)[0]
        clean["비서.별칭"] = [a for a in clean["비서.별칭"] if a != name]
    if clean.get("비서.성격"):
        from .prompt import persona_parts
        _kept, dropped = persona_parts(clean["비서.성격"])
        if dropped:      # 규칙을 바꾸려는 문장은 저장은 하되 두뇌에는 전달하지 않는다 — 무엇이 빠지는지 알려 줌
            warns.append("성격 설명에는 말투·분위기만 적어 주세요. 이 문장은 두뇌에 전달하지 않아요: " + " / ".join(d[:40] for d in dropped[:3]))
    if clean.get("목소리.엔진") == "qwen" and voice_warn:
        warns.append(voice_warn)
    w = voice_warning(cfg, clean)
    if w:
        warns.append(w)
    # 두뇌 방식이 바뀌면 열쇠 이름을 맞춰 둔다(GPT·클로드는 정해진 이름, 내 AI 주소는 열쇠가 있을 때만)
    if "두뇌.방식" in clean:
        kind = clean["두뇌.방식"]
        if kind == "url":
            clean["두뇌.열쇠_이름"] = "url" if keystore.get("url", cfg) else ""
        else:
            clean["두뇌.열쇠_이름"] = ""
        if kind == "local" and "두뇌.주소" not in clean:
            clean["두뇌.주소"] = f"http://127.0.0.1:{cfg['포트']['두뇌']}/v1"
        addr = clean["두뇌.주소"] if "두뇌.주소" in clean else (get(cfg, "두뇌.주소") if get(cfg, "두뇌.방식") == "url" else "")
        if kind == "url" and not addr and "두뇌.주소" not in errors:
            errors["두뇌.주소"] = "내 AI 주소를 넣어 주세요(예: http://127.0.0.1:1234/v1)."
        if kind == "compat":
            for k, msg in (("두뇌.호환_주소", "OpenAI 호환 API 주소를 넣어 주세요(예: https://…/v1)."), ("두뇌.호환_모델", "모델 이름을 넣어 주세요.")):
                if not (clean[k] if k in clean else get(cfg, k)) and k not in errors:
                    errors[k] = msg
    return clean, errors, warns


def when_groups(keys):
    """바뀐 키 → {"즉시": [이름], "다음대화": [...], "다시켜기": {"목소리": [...]}, "펫": [...]}"""
    out = {"즉시": [], "다음대화": [], "다시켜기": {}, "펫": [], "폰": []}
    for k in keys:
        if k not in FIELDS:
            continue
        _, when, label = FIELDS[k]
        if when.startswith("다시켜기:"):
            out["다시켜기"].setdefault(when.split(":", 1)[1], []).append(label)
        else:
            out[when].append(label)
    return out


def changed_keys(cfg, clean):
    out = []
    for k, v in clean.items():
        if k == "목소리.목소리" and isinstance(cfg.get("_voice_choice"), dict):
            # cfg 에는 자동으로 고른 실제 이름이 들어 있다 — '자동 → 자동' 만 안 바뀐 것이고,
            # 자동일 때 같은 이름을 직접 고르면 그때부터 고정이므로 바뀐 것으로 본다.
            auto_now = bool(cfg["_voice_choice"].get("자동"))
            if (v == V.AUTO and not auto_now) or (v != V.AUTO and (auto_now or get(cfg, k) != v)):
                out.append(k)
        elif k == "비서.말투" and isinstance(cfg.get("_tone_choice"), dict):
            # 말투도 같다 — cfg 에는 펫 성별로 정한 실제 말투가 들어 있다. '자동 → 자동'만 안 바뀐 것이고,
            #   자동일 때 같은 말투를 직접 고르면 그때부터 고정(펫 성별을 바꿔도 그대로).
            auto_now = bool(cfg["_tone_choice"].get("자동"))
            if (v == V.AUTO and not auto_now) or (v != V.AUTO and (auto_now or get(cfg, k) != v)):
                out.append(k)
        elif isinstance(v, float) and isinstance(get(cfg, k), (int, float)) and not isinstance(get(cfg, k), bool):
            if abs(float(get(cfg, k)) - v) > 1e-9:
                out.append(k)
        elif get(cfg, k) != v:
            out.append(k)
    return out


def view(cfg):
    """화면에 보여 줄 지금 설정(비밀값 없음)."""
    name, al = C.names(cfg)
    out = {k: get(cfg, k) for k in FIELDS}
    out["비서.이름"], out["비서.별칭"] = name, al
    out["열쇠"] = {n: bool(keystore.get(n, cfg)) for n in SECRET_NAMES}
    v = nest(out)
    # 화면이 '옷·성별에 맞춰 자동으로 골랐는지 / 자산이 없어 대체되는지' 를 보여 줄 수 있게.
    #   자동이면 화면의 고른 값은 "auto"('옷에 맞춤(자동)'), 실제로 고른 이름은 해석["목소리"].
    d = V.describe(cfg)
    v.setdefault("목소리", {})["해석"] = d
    if d.get("자동"):
        v["목소리"]["목소리"] = V.AUTO
    # 말투도 같다: 자동이면 화면의 고른 값은 "auto", 실제 말투는 말투_해석["말투"]
    t = V.describe_tone(cfg)
    v.setdefault("비서", {})["말투_해석"] = t
    if t.get("자동"):
        v["비서"]["말투"] = V.AUTO
    from .prompt import persona_parts
    v["비서"]["성격_빠짐"] = persona_parts(get(cfg, "비서.성격", ""))[1]
    return v


def save_secret(cfg, name, value):
    if name not in SECRET_NAMES:
        raise ValueError("모르는 열쇠 이름")
    v = _CTRL.sub("", str(value or "")).strip()
    if len(v) > 400:
        raise ValueError("열쇠가 너무 길어요.")
    if not v:
        p = os.path.join(C.path(cfg, "자료"), "secrets", name + ".bin")
        try:
            os.remove(p)
        except OSError:
            pass
        return {"있음": False}
    keystore.put(name, v, cfg)
    return {"있음": True, "보기": keystore.mask_key(v)}


# ---------------------------------------------------------------- 두뇌 연결 시험
_TEST_TOOL = [{"type": "function", "function": {
    "name": "calc", "description": "숫자 계산", "parameters": {"type": "object", "properties": {
        "expression": {"type": "string", "description": "계산식(예: 3+4)"}}, "required": ["expression"]}}}]


async def cli_test(cfg, b, kind, timeout=60.0):
    """구독 두뇌 연결 시험 — 로그인 확인 후 따로 띄운 세션에 한 문장(대화 세션과 섞지 않음)."""
    import asyncio
    from . import cli_brain, cli_detect
    name = "claude" if kind == "claude_cli" else "codex"
    res = {"방식": kind, "ok": False}
    st = await asyncio.to_thread(cli_detect.status, name, 20, True)
    res["구독"] = {k: st.get(k) for k in ("있음", "로그인", "판")}
    if not st["있음"] or st["로그인"] is False:
        res["오류"] = st["안내"]
        return res
    tc = C.deep_merge(cfg, {"두뇌": b})
    t0 = time.perf_counter()
    be = cli_brain.ClaudeCli(tc) if kind == "claude_cli" else cli_brain.CodexCli(tc)
    try:
        if kind == "codex_cli":
            await be.ensure()
        await be.prepare("짧게 한국어로 답한다.")
        out, first = [], None
        async for t in be.ask("'안녕하세요'라고만 답해 주세요.", first_timeout=timeout):
            if first is None:
                first = time.perf_counter() - t0
            out.append(t)
        res["답"] = re.sub(r"\s+", " ", "".join(out)).strip()[:80]
        res["ok"] = bool(res["답"])
        res["ms"] = round((time.perf_counter() - t0) * 1000)
        res["첫글자_ms"] = round(first * 1000) if first is not None else None
        if not res["ok"]:
            res["오류"] = "답이 비어 있어요."
    except cli_brain.CliError as ex:
        res["오류"] = str(ex)
    except Exception as ex:  # noqa: BLE001
        res["오류"] = f"구독 두뇌를 부르지 못했어요({ex.__class__.__name__})."
    finally:
        try:
            await be.close()
        except Exception:  # noqa: BLE001
            pass
    return res


async def brain_test(cfg, over=None, timeout=25.0):
    """화면의 '연결 시험' — 한 문장 묻고 답 + 도구 호출 1번(저장 전 값 over 로). 열쇠 값은 결과·기록에 안 남김."""
    b = C.deep_merge(cfg["두뇌"], over or {})
    kind = str(b.get("방식") or "local")
    res = {"방식": kind, "ok": False}
    if kind in CLI_KINDS:
        return await cli_test(cfg, b, kind)
    if kind == "claude":
        try:
            import anthropic  # noqa: F401
        except Exception:  # noqa: BLE001
            res["오류"] = "클로드를 쓰려면 anthropic 꾸러미가 필요해요(설치.bat 에서 '클로드 쓰기')."
            return res
        key = keystore.get("claude", cfg)
        if not key:
            res["오류"] = "클로드 열쇠를 먼저 넣어 주세요."
            return res
        base, model, headers = "https://api.anthropic.com/v1", b.get("claude_모델") or "claude-opus-5-5", {
            "x-api-key": key, "anthropic-version": "2023-06-01"}
        body = {"model": model, "max_tokens": 40, "messages": [{"role": "user", "content": "'안녕하세요'라고만 답해 주세요."}]}
        url = base + "/messages"
    else:
        if kind == "openai":
            base, model, key = b.get("openai_주소") or "https://api.openai.com/v1", b.get("openai_모델") or "", keystore.get("openai", cfg)
            if not model:
                res["오류"] = "GPT 모델 이름을 넣어 주세요."
                return res
            if not key:
                res["오류"] = "GPT 열쇠를 먼저 넣어 주세요."
                return res
        elif kind == "compat":
            base, model, key = str(b.get("호환_주소") or "").strip(), str(b.get("호환_모델") or "").strip(), keystore.get("compat", cfg)
            if not base or not model:
                res["오류"] = "주소와 모델 이름을 넣어 주세요."
                return res
        else:
            base = b.get("주소") or f"http://127.0.0.1:{cfg['포트']['두뇌']}/v1"
            model = b.get("모델") or "local"
            key = keystore.get("url", cfg) if kind == "url" else ""
        headers = {"Authorization": f"Bearer {key or 'none'}"}
        body = {"model": model, "max_tokens": 40, "temperature": 0, "stream": False,
                "messages": [{"role": "user", "content": "'안녕하세요'라고만 답해 주세요."}]}
        if kind in ("local", "url"):
            body["chat_template_kwargs"] = {"enable_thinking": False}
            body["cache_prompt"] = False
            body["id_slot"] = -1
        url = base.rstrip("/") + "/chat/completions"
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0)) as cl:
            r = await cl.post(url, json=body, headers=headers)
            res["ms"] = round((time.perf_counter() - t0) * 1000)
            if r.status_code in (401, 403):
                res["오류"] = "열쇠가 맞지 않아요(거절됨)."
                return res
            if r.status_code == 404:
                res["오류"] = "주소나 모델 이름이 맞지 않아요(404)."
                return res
            if r.status_code == 503 and kind in ("local", "url"):
                res["오류"] = "두뇌 프로그램이 아직 모델을 읽는 중이에요(1~2분). 잠시 뒤 다시 눌러 주세요."
                return res
            if r.status_code >= 400:
                res["오류"] = f"두뇌가 오류를 냈어요({r.status_code})."
                return res
            j = r.json()
            if kind == "claude":
                text = "".join(x.get("text", "") for x in j.get("content") or [] if isinstance(x, dict))
            else:
                text = str(((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
            res["답"] = re.sub(r"\s+", " ", text).strip()[:80]
            res["ok"] = bool(res["답"])
            if not res["ok"]:
                res["오류"] = "답이 비어 있어요."
            if kind != "claude" and res["ok"]:
                tb = dict(body, max_tokens=60, tools=_TEST_TOOL,
                          messages=[{"role": "user", "content": "삼 더하기 사는 얼마야? 계산 도구를 써."}])
                r2 = await cl.post(url, json=tb, headers=headers)
                calls = []
                if r2.status_code < 400:
                    m = ((r2.json().get("choices") or [{}])[0].get("message") or {})
                    calls = [c.get("function", {}).get("name") for c in m.get("tool_calls") or []]
                res["도구"] = "calc" in calls
    except httpx.ConnectError:
        res["오류"] = "두뇌에 연결할 수 없어요. 주소가 맞는지, 두뇌 프로그램이 켜져 있는지 봐 주세요."
    except httpx.TimeoutException:
        res["오류"] = f"{int(timeout)}초 안에 답이 없어요."
    except (httpx.HTTPError, ValueError) as ex:
        res["오류"] = f"연결 오류({ex.__class__.__name__})"
    return res


async def brain_models(cfg, over=None, timeout=15.0):
    """'모델 목록 불러오기' — OpenAI 호환 주소의 GET /models. 저장 전 값(over)으로. 열쇠 값은 결과·기록에 안 남김. → {"ok", "모델": [...]}"""
    b = C.deep_merge(cfg["두뇌"], over or {})
    kind = str(b.get("방식") or "")
    if kind == "compat":
        base, key = str(b.get("호환_주소") or "").strip(), keystore.get("compat", cfg)
    elif kind == "url":
        base, key = str(b.get("주소") or "").strip(), keystore.get("url", cfg)
    else:
        return {"ok": False, "오류": "이 방식은 모델 목록을 불러오지 않아요."}
    if not base:
        return {"ok": False, "오류": "주소를 먼저 넣어 주세요."}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0)) as cl:
            r = await cl.get(base.rstrip("/") + "/models", headers={"Authorization": f"Bearer {key or 'none'}"})
        if r.status_code in (401, 403):
            return {"ok": False, "오류": "열쇠가 맞지 않아요(거절됨)." if key else "열쇠가 필요해요. 열쇠를 넣고 '열쇠 저장'을 눌러 주세요."}
        if r.status_code >= 400:
            return {"ok": False, "오류": f"모델 목록을 주지 않는 주소예요({r.status_code}). 모델 이름을 직접 넣어 주세요."}
        data = r.json()
        items = data.get("data") if isinstance(data, dict) else data
        ids = sorted({str(x.get("id") if isinstance(x, dict) else x)[:120] for x in (items or []) if (x.get("id") if isinstance(x, dict) else x)})
        return {"ok": bool(ids), "모델": ids[:300], **({} if ids else {"오류": "모델 목록이 비어 있어요. 모델 이름을 직접 넣어 주세요."})}
    except httpx.ConnectError:
        return {"ok": False, "오류": "그 주소에 연결하지 못했어요."}
    except httpx.TimeoutException:
        return {"ok": False, "오류": "그 주소가 응답하지 않아요."}
    except (httpx.HTTPError, ValueError):
        return {"ok": False, "오류": "모델 목록을 읽지 못했어요. 모델 이름을 직접 넣어 주세요."}
