# 말싸움(토론) 모드 — AI끼리 붙을 때 쓴다. 0.1.18 공개판.
#   켜기/끄기: 말("말싸움 하자"·"토론하자" / "말싸움 그만"·"평소로") 또는 글로. 언어별 말은 app/config/lang/<언어>.json.
#   켜진 동안
#     · 두뇌에 개인 정보를 안 넘긴다 — 지시문에서 사용자를 부르는 말·기억·성격을 빼고, 대화 기록·도구 결과에서도
#       사용자 설정·기억에서 그때그때 만든 금지어(이름·주소·전화·기억 낱말)가 든 문장을 뺀다.
#       금지어 값은 코드·설정·기록에 두지 않고 이 대화 메모리에만 둔다(로그에도 안 남김).
#     · 도구는 검색·날씨·계산 같은 바깥 정보만 남긴다(기억·메일·파일·PC 조작 제외).
#     · 끼어들기: 등록한 목소리만(등록이 없으면 아무도 못 끊음) — 상대가 끼어들어도 하던 답을 끝까지 한다.
#     · 말 끝 기다림은 '침묵_비율'·'최소_침묵_초' 방식으로 늘린다(끄면 원래 값 그대로).
#   끄기 말 확인: 목소리 등록을 안 쓴 사용자면 끄기 말 뒤 "정말 그만할까?"를 한 번 묻는다(상대 AI가 끄는 것 방지).
#   30분 동안 사용자 말이 없으면 저절로 꺼지고, 연결이 끊기면 새 대화는 꺼진 상태로 시작한다.
#   성인 말싸움(19+) = 설정 '말싸움.성인'. PC 판만 — 폰 앱으로 하는 대화에서는 항상 꺼진다.
import re
import time

from loguru import logger

from . import config as C

DEFAULT_TOOLS = ("web_search", "read_page", "get_weather", "calc")
PENDING_SEC = 15.0          # 끄기 확인을 기다리는 시간

_PUNCT = re.compile(r"[\s,.!?~\"'“”‘’…·ㆍ、。！？:;()\[\]{}<>]+")
_SENT = re.compile(r"(?<=[.!?。？！…])\s+|\n+")
_TAG_LINE = re.compile(r"^\[(?:자동 정보:|최근 연 페이지\(자동 정보\):|지난 대화 요약|주변 대화)")
_TOKEN = re.compile(r"[0-9A-Za-z가-힣぀-ヿ一-鿿]{2,}")

# 끄기 확인에 '네'로 볼 말(언어 파일 '확인_말' 을 먼저 쓰고, 비면 이 기본값)
_YES = {"네", "응", "그래", "맞아", "예", "좋아", "yes", "yeah", "yep", "sure", "ok", "okay",
        "はい", "うん", "そう", "是", "对", "好", "嗯", "可以"}
_PREFIX = {"이제", "좀", "다시", "그럼", "그러면", "자", "now", "ok", "okay", "then", "じゃあ", "では", "さあ", "那", "那么"}
_SUFFIX = {"요", "해", "해요", "해줘", "주세요", "줘", "할래", "할까", "하자", "할게", "할게요",
           "please", "now", "よ", "ね", "ください", "お願い", "吧", "啊", "呀", "了", "好吗"}

# 기억 속 낱말에서 흔한 것(금지어로 쓰면 멀쩡한 문장까지 지워지므로 뺀다)
_GENERIC = {"사용자", "사장님", "비서", "좋아", "좋아한다", "좋아해", "싫어", "싫어한다", "싫어해",
            "있다", "없다", "한다", "했다", "입니다", "습니다", "그리고", "관련", "정도", "때문", "오늘", "내일",
            "어제", "주말", "아침", "저녁", "점심", "이름", "위치", "주소", "전화", "번호", "기억", "대화", "사람",
            "장소", "것", "수", "등", "및", "좀", "더", "잘", "안", "못", "주로", "자주", "가끔", "항상", "계속",
            "아주", "너무", "정말", "매우", "가장", "제일", "매일", "한번", "다시", "이번", "지난", "다음"}
_EN_STOP = {"the", "and", "user", "users", "likes", "like", "loves", "hates", "lives", "works", "name", "address",
            "phone", "number", "favorite", "favourite", "birthday", "family", "home", "with", "from", "that", "this",
            "has", "have", "his", "her", "their", "they", "she", "him", "about", "into", "when", "where", "what"}
# 값이 그대로 나가면 안 되는 꼴(전화·사업자·주민·카드·메일·IP). 값은 어디에도 적지 않는다.
_PATTERNS = (
    re.compile(r"(?<!\d)0\d{1,3}[- ]?\d{3,4}[- ]?\d{4}(?!\d)"),
    re.compile(r"(?<!\d)\d{2,6}[- ]\d{2,6}[- ]\d{4,8}(?!\d)"),
    re.compile(r"(?<!\d)\d{6}[- ]?\d{7}(?!\d)"),
    re.compile(r"(?<!\d)\d{13,19}(?!\d)"),
    re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"),
)


# ---------------------------------------------------------------- 기본값·언어 말
def cget(c):
    return (c or {}).get("말싸움") or {}


def _num(c, key, default):
    try:
        return float(cget(c).get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _text(c, key, default=""):
    v = cget(c).get(key)
    return str(v) if v is not None else default


def allowed_names(c):
    raw = cget(c).get("허용_도구") or DEFAULT_TOOLS
    return {str(x) for x in raw if str(x).strip()}


def _norm(s):
    return _PUNCT.sub("", str(s or "").lower())


def _phrases(c, key):
    return [str(x) for x in (cget(c).get(key) or []) if str(x).strip()]


def _strip_edges(c, n):
    """이름('김비서')·'이제/좀' 같은 앞말을 떼고, 뒤에 붙은 '요/해' 같은 꼬리도 떼 본다."""
    name, aliases = C.names(c)
    for head in [name] + list(aliases):
        h = _norm(head)
        if h and n.startswith(h) and len(n) > len(h):
            n = n[len(h):]
            break
    changed = True
    while changed:
        changed = False
        for p in _PREFIX:
            pn = _norm(p)
            if pn and n.startswith(pn) and len(n) > len(pn):
                n = n[len(pn):]
                changed = True
                break
    return n


def intent(c, text):
    """'on' | 'off' | None — 짧은 명령 문장만 본다(긴 잡담 속 낱말은 안 봄)."""
    t = str(text or "").strip()
    if not t or len(t) > 40:
        return None
    n = _strip_edges(c, _norm(t))
    if not n:
        return None
    for kind, key in (("on", "켜기_말"), ("off", "끄기_말")):
        for p in _phrases(c, key):
            pn = _norm(p)
            if pn and (n == pn or (n.startswith(pn) and n[len(pn):] in _SUFFIX)):
                return kind
    return None


def _is_yes(c, text):
    n = _norm(text)
    if not n:
        return False
    for p in (_phrases(c, "확인_말") or list(_YES)):
        pn = _norm(p)
        if pn and (n == pn or (n.startswith(pn) and n[len(pn):] in _SUFFIX)):
            return True
    return False


# ---------------------------------------------------------------- 상태
def on(st):
    return bool(st is not None and getattr(st, "debate", False))


def adult_allowed(st):
    return bool(getattr(st, "debate_adult_allowed", True))


def adult(st):
    """지금 성인 단계인가 — 설정 '말싸움.성인' 이고 PC 대화일 때만."""
    return adult_allowed(st) and bool(cget(getattr(st, "cfg", None)).get("성인"))


def touch(st):
    """사용자 말이 있을 때마다 '마지막 말' 시각 갱신(30분 자동 끔 기준)."""
    if on(st):
        st.debate_t = time.time()


def may_interrupt(st, gate_on, owner):
    """켜진 동안 말을 끊을 수 있는가 — 등록한 목소리 문이 켜져 있고 그 목소리일 때만."""
    return bool(on(st) and gate_on and owner)


# ---------------------------------------------------------------- 말 끝 기다림
def silence(base, c):
    """켜진 동안의 말 끝 기다림 = 지금 값 × 침묵_비율(최소 최소_침묵_초). 꺼짐은 원래 값."""
    try:
        ratio = _num(c, "침묵_비율", 1.5)
        low = _num(c, "최소_침묵_초", 0.5)
        return max(low, float(base) * ratio)
    except (TypeError, ValueError):
        return base


def _set_timers(st, is_on):
    c = getattr(st, "cfg", None)
    vad, base = getattr(st, "vad", None), getattr(st, "vad_stop_base", None)
    if vad is not None and base is not None:
        try:
            vad.params.stop_secs = silence(base, c) if is_on else float(base)
            setter = getattr(vad, "set_params", None)
            if setter is not None:      # pipecat VAD 는 안쪽 프레임 수를 다시 계산해야 실제로 바뀐다
                setter(vad.params)
        except Exception:  # noqa: BLE001
            pass
    turn, tbase = getattr(st, "smart_turn", None), getattr(st, "smart_stop_base", None)
    if turn is not None and tbase is not None:
        try:
            sec = silence(tbase, c) if is_on else float(tbase)
            turn.params.stop_secs = sec
            if hasattr(turn, "_stop_ms"):
                turn._stop_ms = sec * 1000
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- 금지어(개인 값)
def _add_value(out, v):
    s = str(v or "").strip()
    if len(s) >= 2:
        out.append(_norm(s))


def _fact_tokens(memory):
    try:
        facts = memory.list_facts() if memory is not None else []
    except Exception:  # noqa: BLE001
        facts = []
    out = []
    seen = set()
    for f in facts:
        s = str((f or {}).get("내용") or "")
        for w in _TOKEN.findall(s):
            if re.fullmatch(r"[A-Za-z]+", w):
                if len(w) < 4 or w.lower() in _EN_STOP:
                    continue
            elif len(w) < 2 or w in _GENERIC:
                continue
            if w not in seen:
                seen.add(w)
                out.append(w)
            if len(out) >= 600:
                return out
    return out


def banned_rules(c, memory=None):
    """사용자 설정의 개인 칸 + 기억 낱말 + 전화·주소 꼴 → (금지 낱말, 정규식). 값은 이 메모리에만 둔다."""
    vals = []
    u = (c or {}).get("사용자") or {}
    _add_value(vals, C.honorific(c))
    _add_value(vals, u.get("기본장소"))
    sc = (c or {}).get("화면") or {}
    for k in ("마이크", "마이크_이름", "스피커", "스피커_이름"):
        _add_value(vals, sc.get(k))
    _add_value(vals, ((c or {}).get("비서") or {}).get("성격"))
    br = (c or {}).get("두뇌") or {}
    for k in ("주소", "호환_주소", "openai_주소"):
        _add_value(vals, br.get(k))
    for w in _fact_tokens(memory):
        _add_value(vals, w)
    words = tuple(dict.fromkeys(w for w in vals if w))
    return words, tuple(_PATTERNS)


def rules(st):
    got = getattr(st, "debate_ban", None)
    if got is None:
        got = banned_rules(getattr(st, "cfg", None), getattr(st, "debate_memory", None))
        st.debate_ban = got
    return got


def _banned(sentence, words, pats):
    n = _norm(sentence)
    if any(w and w in n for w in words):
        return True
    return any(p.search(sentence) for p in pats)


def _filter(text, words, pats):
    s = str(text or "")
    if not s.strip() or (not words and not pats):
        return text
    if not _banned(s, words, pats):
        return text
    parts = [p for p in _SENT.split(s) if p and p.strip()]
    if len(parts) <= 1:
        return ""
    kept = [p for p in parts if not _banned(p, words, pats)]
    if len(kept) == len(parts):
        return text
    return re.sub(r"\s{2,}", " ", " ".join(kept)).strip()


def filter_text(text, st):
    """켜진 동안 말로 나가기 직전 한 겹 — 금지어가 든 문장만 뺀다. 꺼짐/안 걸림이면 원문 그대로."""
    if not on(st):
        return text
    words, pats = rules(st)
    return _filter(text, words, pats)


def filter_messages(msgs, st):
    """켜진 동안 두뇌에 보내는 대화 기록에서도 개인 값이 든 문장을 뺀다.
    기기·최근 페이지·지난 대화 요약·주변 대화 같은 자동 꼬리표도 뺀다(시각 줄만 남김)."""
    if not on(st) or not isinstance(msgs, list):
        return msgs
    words, pats = rules(st)
    out = []
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") == "system":
            out.append(m)
            continue
        c0 = m.get("content")
        if isinstance(c0, str) and c0:
            if c0.lstrip().startswith("[지난 대화 요약"):
                c1 = ""      # 지난 대화 요약은 통째로 안 넘김(개인 정보가 섞일 수 있음)
            else:
                lines = c0.splitlines()
                kept = [ln for ln in lines if not _TAG_LINE.match(ln.strip())]
                c1 = "\n".join(kept) if len(kept) != len(lines) else c0
            t = _filter(c1, words, pats)
            if t != c0:
                m = {**m, "content": t}
        out.append(m)
    return out


def filter_tools(tools, c):
    """켜진 동안 두뇌에 줄 도구 — 검색·날씨·계산 같은 바깥 정보만 남긴다."""
    if not isinstance(tools, list):
        return tools
    keep = allowed_names(c)
    out = []
    for t in tools:
        name = ""
        if isinstance(t, dict):
            name = str((t.get("function") or {}).get("name") or t.get("name") or "")
        if name in keep:
            out.append(t)
    return out


# ---------------------------------------------------------------- 켜기/끄기
def set_on(st):
    if st is None:
        return
    st.debate = True
    st.debate_t = time.time()
    st.debate_confirm_off_t = 0.0
    st.debate_ban = banned_rules(getattr(st, "cfg", None), getattr(st, "debate_memory", None))
    _set_timers(st, True)
    cb = getattr(st, "on_debate_change", None)
    if callable(cb):
        try:
            cb()
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"말싸움 지시문 갱신 실패: {ex.__class__.__name__}")
    try:
        st.event("debate", on=True, adult=adult(st))
    except Exception:  # noqa: BLE001
        pass


def set_off(st, auto=False):
    if st is None:
        return
    st.debate = False
    st.debate_t = 0.0
    st.debate_confirm_off_t = 0.0
    st.debate_ban = None
    _set_timers(st, False)
    cb = getattr(st, "on_debate_change", None)
    if callable(cb):
        try:
            cb()
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"말싸움 지시문 갱신 실패: {ex.__class__.__name__}")
    try:
        st.event("debate", on=False, auto=bool(auto), adult=adult(st))
    except Exception:  # noqa: BLE001
        pass


def tick(st):
    """자동끔_분 넘게 사용자 말이 없으면 끈다. 껐으면 True."""
    if not on(st):
        return False
    mins = _num(getattr(st, "cfg", None), "자동끔_분", 30)
    if mins > 0 and time.time() - float(getattr(st, "debate_t", 0.0) or 0.0) >= mins * 60:
        set_off(st, auto=True)
        return True
    return False


def command(st, text, typed=False, voice_ok=None, gate_on=False):
    """켜기/끄기 말이면 바꾸고 짧게 말할 문장을 돌려준다. 아니면 None.
    목소리 등록 문이 켜져 있으면(spoken) 등록 목소리일 때만. 등록이 없으면 누구 말이든 받되
    끄기 말은 '정말 그만할까?'를 한 번 묻는다(상대 AI가 끄는 것 방지). 글로 쓴 말은 사용자가 쓴 것."""
    c = getattr(st, "cfg", None)
    kind = intent(c, text)
    now = time.time()
    pending = float(getattr(st, "debate_confirm_off_t", 0.0) or 0.0)
    if pending and now - pending > PENDING_SEC:
        st.debate_confirm_off_t = pending = 0.0

    if kind is None:
        if pending and on(st) and not typed and not gate_on and _is_yes(c, text):
            set_off(st)
            logger.info("말싸움 모드 꺼짐(확인)")
            return _text(c, "꺼짐_한마디", "좋아, 평소로 돌아갈게.")
        return None

    if gate_on and not typed and not voice_ok:
        return _text(c, "남의목소리_한마디", "그건 등록한 목소리로만 바꿀 수 있어.")

    if kind == "on":
        st.debate_confirm_off_t = 0.0
        if on(st):
            touch(st)
            return _text(c, "이미켜짐_한마디", "지금 이미 말싸움 중이야.")
        set_on(st)
        logger.info("말싸움 모드 켜짐")
        return _text(c, "켜짐_한마디", "좋아, 말싸움 모드.")

    # 끄기
    if not on(st):
        return _text(c, "이미꺼짐_한마디", "지금은 말싸움 모드가 아니야.")
    if typed or gate_on or pending:
        set_off(st)
        logger.info("말싸움 모드 꺼짐")
        return _text(c, "꺼짐_한마디", "좋아, 평소로 돌아갈게.")
    st.debate_confirm_off_t = now
    return _text(c, "확인_질문", "정말 그만할까?")