# 이름 부르기(호출어) — 학습 자료 없이, 받아쓴 글이 비서 이름(설정 '비서.이름' + '비서.별칭')으로 '부르는 말'인지 본다.
#   부르는 말 = 문장 맨 앞(앞에 '야·저기·헤이' 같은 부르는 말은 됨)에 이름이 오고, 이름 바로 뒤에 조사가 붙지 않은 것.
#     '김비서'·'김비서야'·'김 비서님, 불 켜 줘'(O) / '김비서한테 물어봐'·'우리 김비서가'(X — 이름을 말한 것이지 부른 게 아님)
#   별칭 = 받아쓰기(whisper)가 이름을 흔히 틀리게 적는 꼴. 처음 화면에서 이름을 몇 번 불러 받아쓴 꼴을 별칭으로 모은다(learn_aliases).
#   이름은 아무 말이나 여러 개 됨. 한 글자·흔한 말('야'·'저기')은 경고(name_warning).
import re

# 이름·부르는 말에 쓰는 글자 — 한국어(가-힣), 영어·숫자, 일본어 가나(ぁ-ヿ), 중국어 한자(一-鿿).
#   0.1.18 다국어: 예전에는 [0-9a-z가-힣] 만 남겨 'キム秘書'·'金秘书'가 빈 글이 되어 깨우지 못했다.
_KEEP = "0-9a-z가-힣ぁ-ヿ一-鿿"
_KEEP_SP = _KEEP + r"\s"
_CALL_TAIL = "야아요님씨さんちゃん様呀啊呢吗吧哦"
_MENTION_TAIL = ("한테", "에게", "보고", "더러", "이랑", "랑", "하고", "처럼", "같이", "까지", "부터", "밖에", "조차", "마저",
                 "은", "는", "이", "가", "을", "를", "의", "도", "만", "에", "께", "와", "과", "로", "이라", "라고", "라는", "라도",
                 "였", "입니", "예요", "인데", "네요", "들", "라서", "라면", "란")
# 앞에 와도 되는 부르는 말 — 언어마다(한국어·영어·일본어·중국어). 이름보다 먼저 떼고 본다.
_CALL_INTERJ = ("어이", "저기요", "저기", "헤이", "hey", "하이", "이봐", "오케이", "okay", "ok", "야", "아", "어", "자", "얘", "음", "네", "안녕",
                "hi", "hello", "yo", "excuse", "um", "uh",
                "ねえ", "あの", "もしもし", "すみません", "おい",
                "喂", "嘿", "哎", "你好", "嗯", "那个")
_COMMON = {"야", "저기", "저기요", "여보세요", "이봐", "어이", "헤이", "hey", "네", "응", "아", "어", "음", "자", "얘", "그거", "이거", "안녕",
           "hi", "hello", "yo", "ねえ", "もしもし", "喂", "嘿", "你好"}
_HALLU = ("감사합니다", "고맙습니다", "시청해", "다음영상", "구독", "좋아요", "뉴스", "자막", "2부에서", "계속됩니다",
          "시청", "영상편집", "번역", "thank you for watching", "thanks for watching", "subscribe")
_TOKEN = re.compile(r"[^" + _KEEP + r"\s]")   # 남길 글자 밖은 띄어 씀


def compact(t):
    return re.sub(r"[^" + _KEEP + "]", "", str(t or "").lower())


def _tokens(text):
    """글 → 낱말 목록(한국어·영어·일본어·중국어 글자만 남김)."""
    return [t for t in _TOKEN.sub(" ", str(text or "").lower()).split() if t]


def name_warning(name):
    """이름으로 쓰기 어려우면 이유(글), 괜찮으면 None."""
    c = compact(name)
    if not c:
        return "이름이 비어 있어요."
    if len(c) < 2:
        return "한 글자 이름은 다른 말과 헷갈려 잘못 깨어날 수 있어요."
    if c in _COMMON:
        return "흔히 쓰는 말이라 대화 중에 잘못 깨어날 수 있어요."
    return None


def hallucination(text):
    t = compact(text)
    if not t:
        return True
    if any(h in t for h in _HALLU):
        return True
    if len(t) >= 12 and len(set(t)) <= 3:
        return True
    ws = _tokens(text)
    return len(ws) >= 6 and len(set(ws)) <= 2


def _jamo(ch):
    o = ord(ch) - 0xAC00
    if not 0 <= o < 11172:
        return None
    return o // 588, (o % 588) // 28, o % 28


_CONS_GROUPS = [{0, 1, 15}, {3, 4, 16}, {7, 8, 17, 6}, {9, 10, 12, 13, 14}]          # ㄱㄲㅋ / ㄷㄸㅌ / ㅂㅃㅍㅁ / ㅅㅆㅈㅉㅊ
_VOW_GROUPS = [{20, 16, 19}, {4, 8, 0, 6, 12, 2, 18}, {5, 1}, {13, 17}]                # ㅣㅟㅢ / ㅓㅗㅏㅕㅛㅑㅡ / ㅔㅐ / ㅜㅠ
_NASAL = {16, 4, 21}                                                                    # 받침 ㅁ ㄴ ㅇ
_OPEN_TAIL = {0, 1, 21, 4, 19, 8}                                                       # 받침 없음 ↔ ㄱ ㅇ ㄴ ㅅ ㄹ


def _grp(groups, x):
    for g in groups:
        if x in g:
            return g
    return {x}


def _near_syll(a, b, first):
    (c1, v1, t1), (c2, v2, t2) = a, b
    if c1 not in _grp(_CONS_GROUPS, c2) and not (first and c1 == 11):
        return False
    if v1 not in _grp(_VOW_GROUPS, v2):
        return False
    if t2 in _NASAL:
        return t1 in _NASAL or t1 == 0
    if t2 == 0:
        return t1 in _OPEN_TAIL
    return t1 == t2


class NameMatcher:
    """설정의 비서 이름·별칭으로 '부르는 말'을 판정한다. 이름을 바꾸면 새로 만들면 됨(상태 없음)."""

    def __init__(self, name, aliases=()):
        self.name = str(name or "").strip() or "김비서"
        words = [compact(x) for x in (self.name, *aliases)]
        self.words = tuple(dict.fromkeys(w for w in words if len(w) >= 2))
        self._rx = re.compile("|".join(re.escape(w) for w in sorted(self.words, key=len, reverse=True)) or r"(?!)")

    def rx_source(self, spaced=True):
        """다른 정규식에 붙여 쓸 이름 꼴. spaced=True 면 글자 사이 공백 하나 허용('김 비서')."""
        if not spaced:
            return self._rx.pattern
        return "|".join(r"\s?".join(re.escape(c) for c in w) for w in sorted(self.words, key=len, reverse=True)) or r"(?!)"

    def mentions(self, text):
        """글 어디든 이름(별칭)이 있나."""
        return bool(text) and bool(self._rx.search(compact(text)))

    def call(self, text):
        """글이 비서를 '부르는 말'이면 이름, 아니면 None."""
        if not text:
            return None
        for sent in re.split(r"[.!?。…！？、\n]+", str(text)):
            toks = _tokens(sent)
            while toks and toks[0] in _CALL_INTERJ and compact(toks[0]) not in self.words:
                toks = toks[1:]
            if not toks:
                continue
            for k in (1, 2, 3):   # 이름이 띄어 받아써진 꼴('김 비서', 'Kim Biseo')
                if len(toks) < k:
                    break
                head = "".join(toks[:k])
                hit = next((w for w in sorted(self.words, key=len, reverse=True) if head.startswith(w)), None)
                if hit is None:
                    continue
                rest = head[len(hit):]
                # 꼬리말(한국어 야·요·님·씨 / 일본어 さん·ちゃん·様 / 중국어 呀·啊·呢 …)은 불러도 됨
                if rest == "" or (len(rest) <= 3 and all(ch in _CALL_TAIL for ch in rest)) \
                        or (len(rest) == 2 and rest[0] in _CALL_TAIL and rest[1] == "요"):
                    return self.name
                r2 = rest[1:] if rest[:1] in "님씨" else rest
                if not r2:
                    return self.name
                break   # 이름 + 조사(말한 것) 또는 이름 뒤에 다른 글자('김비서실') → 이 문장은 아님
        return None

    def near(self, text):
        """이름과 소리 모양이 가까운 짧은 부름(받아쓰기가 이름을 틀리게 적은 꼴). call() 이 None 일 때만 의미 있음."""
        if not text or self.call(text):
            return False
        target = [_jamo(c) for c in compact(self.name)]
        if len(target) < 2 or any(j is None for j in target):
            return False
        toks = _tokens(text)
        while toks and toks[0] in _CALL_INTERJ:
            toks = toks[1:]
        w = "".join(toks)
        if len(w) == len(target) + 1 and w[-1] in _CALL_TAIL:
            w = w[:-1]
        if len(w) != len(target):
            return False
        js = [_jamo(c) for c in w]
        if any(j is None for j in js):
            return False
        return all(_near_syll(a, b, i == 0) for i, (a, b) in enumerate(zip(js, target)))

    def only_name(self, text):
        """이름만 부른 말인가 — '김비서!'·'김 비서?'·'저기 김비서야'(O), '김비서 불 켜 줘'(X)."""
        if not self.call(text):
            return False
        t = compact(text)
        for w in sorted(_CALL_INTERJ, key=len, reverse=True):
            if t.startswith(w) and not self._rx.match(t):
                t = t[len(w):]
                break
        # 꼬리('아·야·요·!')를 한 글자씩 떼며 본다 — 이름이 '아'로 끝나는 경우('현아', '현아야')에 한꺼번에 떼면 이름이 잘림
        while t:
            if self._rx.fullmatch(t):
                return True
            if t[-1] not in _CALL_TAIL:
                return False
            t = t[:-1]
        return False

    def strip_call(self, text):
        """부른 이름 부분을 뺀 나머지 말('김비서, 내일 날씨 어때?' → '내일 날씨 어때?'). 못 빼면 그대로."""
        t = str(text or "").strip()
        m = re.match(r"^\s*(?:(?:" + "|".join(re.escape(x) for x in _CALL_INTERJ) + r")\s*[,!]?\s*)?(?:" + self.rx_source()
                     + r")\s*(?:야|아|요|님|씨)?\s*[,.!?~]*\s*", t, re.I)
        return t[m.end():].strip() if m and m.end() < len(t) else t


def learn_aliases(name, heard, keep=()):
    """처음 화면에서 '이름을 세 번 불러 보세요'로 받아쓴 글들 → 별칭 목록(이름과 다른 꼴만, 흔한 말·환각 제외)."""
    base = compact(name)
    out = [a for a in keep if compact(a)]
    for h in heard:
        if hallucination(h):
            continue
        toks = _tokens(h)
        while toks and toks[0].lower() in _CALL_INTERJ:
            toks = toks[1:]
        w = compact("".join(toks)).rstrip(_CALL_TAIL) or compact("".join(toks))
        if len(w) < 2 or w == base or w in _COMMON or len(w) > len(base) + 3:
            continue
        if w not in [compact(x) for x in out]:
            out.append(w)
    return out
