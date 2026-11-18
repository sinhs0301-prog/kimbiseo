# 다국어(0.1.18~) — 화면·말·도구 결과의 글을 고른 언어로.
#   언어 = 설정 "언어"(ko·en·ja·zh). 설정에 없으면 ko(0.1.17 까지 쓰던 사람은 그대로 한국어).
#   사전 = app/i18n/<언어>.json — {한국어 원문: 번역}. 한국어는 원문 그대로라 사전이 없다.
#     숫자·이름이 끼는 글은 원문에 {이름}·{n}·{0} 자리를 둔다: tr("{n}글자까지 돼요.", n=5)
#     이미 채워진 글("5글자까지 돼요.")도 틀(자리 → 아무 글)로 대조해 바꾼다(화면 번역기 app/ui/i18n.js 와 같은 규칙).
#   사전에 없는 글은 원문(한국어) 그대로 — 검사 도구 tools/i18n_scan.py check 가 빠진 것을 찾는다.
#   표준 라이브러리만(설치기 installer/setup_core.py 도 이 파일을 씀).
import json
import os
import re
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
I18N_DIR = os.path.join(os.path.dirname(HERE), "i18n")
LANGS = ("ko", "en", "ja", "zh")
NAMES = {"ko": "한국어", "en": "English", "ja": "日本語", "zh": "中文"}
# 두뇌 지시문·통역에 쓰는 영어 이름 / 받아쓰기(whisper) 이름 / 목소리(Qwen3-TTS) 이름
EN_NAMES = {"ko": "Korean", "en": "English", "ja": "Japanese", "zh": "Chinese"}
WHISPER = {"ko": "korean", "en": "english", "ja": "japanese", "zh": "chinese"}
DEFAULT = "ko"
_PH = re.compile(r"\{([^{}\s]{1,40})\}")
_HANGUL = re.compile(r"[가-힣]")
_STATE = {"lang": DEFAULT}
_CACHE = {}
_LOCK = threading.Lock()


def norm(code):
    """'en-US'·'EN'·'japanese'·'zh-Hans' → 'en'·'ja'·'zh'. 모르면 ko."""
    c = str(code or "").strip().lower().replace("_", "-")
    if not c:
        return DEFAULT
    if c in LANGS:
        return c
    head = c.split("-", 1)[0]
    if head in LANGS:
        return head
    for k, v in list(EN_NAMES.items()) + list(WHISPER.items()):
        if c == v.lower():
            return k
    if c in ("jp", "日本語"):
        return "ja"
    if c in ("cn", "中文", "简体中文", "繁體中文"):
        return "zh"
    if c in ("kr", "한국어"):
        return "ko"
    return DEFAULT


def lang_of(cfg):
    return norm((cfg or {}).get("언어"))


def set_lang(code):
    _STATE["lang"] = norm(code)
    return _STATE["lang"]


def current():
    return _STATE["lang"]


def _load(code):
    p = os.path.join(I18N_DIR, f"{code}.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {}, []
    with _LOCK:
        got = _CACHE.get(code)
        if got and got[0] == mt:
            return got[1], got[2]
        try:
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        exact = {k: v for k, v in raw.items() if isinstance(v, str) and not k.startswith("_")}
        pats = []
        for k, v in exact.items():
            if _PH.search(k):
                names = _PH.findall(k)
                parts = _PH.split(k)
                rx = "".join(re.escape(x) if i % 2 == 0 else "(.+?)" for i, x in enumerate(parts))
                try:
                    pats.append((re.compile("^" + rx + "$", re.S), names, v, len(k)))
                except re.error:
                    continue
        pats.sort(key=lambda x: -x[3])     # 긴 틀 먼저(더 구체적인 것)
        _CACHE[code] = (mt, exact, pats)
        return exact, pats


def table(code):
    """{원문: 번역} 전체(화면이 받아 감). ko 면 {}."""
    code = norm(code)
    return {} if code == "ko" else dict(_load(code)[0])


def _fill(text, kw):
    if not kw:
        return text
    return _PH.sub(lambda m: str(kw[m.group(1)]) if m.group(1) in kw else m.group(0), text)


def lookup(text, code=None):
    """채워진 글 → 그 언어 글(사전 → 틀 대조). 없으면 원문."""
    code = norm(code or _STATE["lang"])
    s = str(text)
    if code == "ko" or not _HANGUL.search(s):
        return s
    exact, pats = _load(code)
    lead = len(s) - len(s.lstrip())
    core = s.strip()
    tail = s[lead + len(core):]
    if core in exact:
        return s[:lead] + exact[core] + tail
    for rx, names, v, _n in pats:
        m = rx.match(core)
        if m:
            vals = {n: lookup(g, code) for n, g in zip(names, m.groups())}
            return s[:lead] + _fill(v, vals) + tail
    # '앞말: 나머지' — 앞말만 사전에 있으면 앞말만 바꿈(오류 글 뒤에 까닭이 붙는 꼴)
    for sep in (": ", ":", " — ", " - "):
        if sep in core:
            head, rest = core.split(sep, 1)
            key = head + sep.rstrip()
            if key in exact or head in exact:
                return s[:lead] + (exact.get(key) or exact[head] + sep.rstrip()) + (" " if sep.endswith(" ") else "") + lookup(rest, code) + tail
    return s


def tr(text, lang=None, **kw):
    """원문(한국어 틀) → 고른 언어 글, {자리} 채움. tr('{n}개 받음', n=3)"""
    code = norm(lang or _STATE["lang"])
    s = str(text)
    if code != "ko":
        exact, _p = _load(code)
        if s in exact:
            s = exact[s]
        elif not kw:
            s = lookup(s, code)
    return _fill(s, kw)


def ear_request_lang(cfg):
    """본체 → 귀 서버 요청의 받아쓰기 언어. None = 귀 서버가 켤 때 정한 언어(한국어 사용자 — 예전 그대로).
    설정 귀.받아쓰기_언어: ''(앱 언어 따름) · 'auto'(말마다 자동 감지) · 코드."""
    v = str(((cfg or {}).get("귀") or {}).get("받아쓰기_언어") or "").strip().lower()
    if v == "auto":
        return "auto"
    if v[:2] in LANGS:
        return v[:2]
    lg = lang_of(cfg)
    return None if lg == "ko" else lg


def pipecat_lang(code):
    from pipecat.transcriptions.language import Language
    return {"ko": Language.KO, "en": Language.EN, "ja": Language.JA, "zh": Language.ZH}.get(norm(code), Language.KO)


def en_name(code):
    return EN_NAMES.get(norm(code), "Korean")


def whisper_name(code):
    return WHISPER.get(norm(code), "korean")


def system_language():
    """윈도우 화면 언어(설치 때 처음 고를 값) — 못 읽으면 ko."""
    try:
        import locale
        loc = locale.getlocale()[0] or ""
    except Exception:  # noqa: BLE001
        loc = ""
    if os.name == "nt":
        try:
            import ctypes
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return {0x12: "ko", 0x09: "en", 0x11: "ja", 0x04: "zh"}.get(lid, "en")
        except Exception:  # noqa: BLE001
            pass
    return norm(loc[:2]) if loc else DEFAULT
