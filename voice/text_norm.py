# 글 정리(읽기 변환) — 목소리에 넣기 직전에 글을 '소리 나는 대로' 바꾼다. 화면 글은 그대로 두고 소리로 가는 글만 바뀐다.
# 순서: 정리 → 발음 사전(사용자 사전 → 저장소 기본 사전 pronunciation.tsv, 사전 우선) → 부품 규칙(그래픽·CPU·칩셋)
#       → 전화·날짜·판 번호(0.1.12)·시각 → 돈 기호·온도·속도·분수·범위·퍼센트·단위 → 숫자+세는 말(고유어/한자어) → 남은 숫자
#       → 영어(아는 낱말·약어 철자·글자+숫자) → 기호
# 부품 이름 읽기 규칙: 그래픽 숫자 한 자리씩(0=공) / CPU 숫자 통째 / 인텔 울트라 3자리 한 자리씩 / Ti=티아이 / 9070XT=구공칠공 엑스티
#   AMD CPU 예외(9950X3D=구구오공): 끝 두 자리가 00 이 아니면 한 자리씩 읽는다고 해석.
# 숫자 읽기 규칙(0.1.13 에서 넓힘 — 시험 = tests/unit/test_text_norm.py)
#   세는 말: 개·명·살·시간·마리·잔 … = 고유어(세 개·스무 살), 원·분·초·년·층·개월 … = 한자어(삼 개월·십이 분)
#   시각: 2시 30분 = 두 시 삼십 분 · 14:05 = 오후 두 시 오 분 · 날짜: 2026-11-16 · 2026.11.16 · 2026. 11. 16. = 이천이십육 년 십일월 십육 일
#   판 번호: 0.1.12 = 영 점 일 점 십이 · v2.0 = 버전 이 점 영 · 전화: 010-1234-5678 = 공일공, 일이삼사, 오육칠팔 · 1588-1234
#   돈: 3,500원 · $100 = 백 달러 · 온도: 23℃ = 이십삼 도 · -3도 = 영하 삼 도 · 속도: 100km/h = 시속 백 킬로미터 · 분수: 1/2 = 이분의 일
#   '번'은 횟수면 고유어(세 번 눌러), 번호면 한자어(삼 번 버스·이 번이) · '배'는 열 배까지 고유어(두 배)
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DICT_PATH = os.path.join(HERE, "pronunciation.tsv")
EXTRA_DICTS = []   # 목소리 서버가 설정 '목소리.발음사전' 을 여기에 넣음(기본 사전보다 먼저 적용)

SINO = ["영", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
CODE_DIGIT = ["공", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]   # 모델명·전화번호
N_ONES = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
N_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
EN_NUM = {"0": "제로", "1": "원", "2": "투", "3": "쓰리", "4": "포", "5": "파이브", "6": "식스", "7": "세븐", "8": "에잇", "9": "나인"}
LETTER = {"A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프", "G": "지", "H": "에이치", "I": "아이",
          "J": "제이", "K": "케이", "L": "엘", "M": "엠", "N": "엔", "O": "오", "P": "피", "Q": "큐", "R": "알",
          "S": "에스", "T": "티", "U": "유", "V": "브이", "W": "더블유", "X": "엑스", "Y": "와이", "Z": "제트"}
SUFFIX = {"TI": "티아이", "SUPER": "슈퍼", "XTX": "엑스티엑스", "XT": "엑스티", "GRE": "지알이", "X3D": "엑스쓰리디",
          "X": "엑스", "F": "에프", "G": "지", "K": "케이", "KF": "케이에프", "KS": "케이에스", "T": "티", "E": "이",
          "M": "엠", "I": "아이", "H": "에이치", "HX": "에이치엑스", "U": "유"}
# 숫자 뒤 세는 말 — 고유어 수(한·두·세)로 읽는 것
NATIVE_UNITS = ["시간", "사람", "군데", "가지", "켤레", "마리", "시", "건", "개", "명", "살", "잔", "장", "권", "곳", "달", "벌", "판", "통", "대", "번째",
                "송이", "그루", "봉지", "상자", "박스", "자루", "바퀴", "걸음", "방울", "모금", "조각", "덩어리", "그릇", "접시", "숟가락", "스푼"]
# 고유어로 읽지만 한 글자라 다른 낱말의 앞 글자일 수 있는 것(3병원·2채널·5곡선) — 뒤에 조사·띄어쓰기·문장 끝이 올 때만
NATIVE_STRICT = ["채", "척", "병", "줄", "알", "쌍", "편", "곡", "끼", "컵", "캔", "팩", "포기", "톨"]
# 한자어 수로 읽는 세는 말(소리 그대로 붙임). 긴 것이 먼저 맞음(개월 > 개, 배속 > 배, 주일 > 주)
SINO_UNITS = ["개월", "주일", "퍼센트", "분", "초", "원", "층", "호", "점", "등", "회", "차", "도", "세", "년", "일", "주", "배", "위", "번", "인분", "종",
              "개국", "개년", "개소", "개사", "주년", "주차", "배속", "세트", "세대", "년대", "년생", "달러", "유로", "위안", "파운드", "페이지", "학년", "번지",
              "교시", "단계", "등급", "킬로그램", "킬로미터", "센티미터", "밀리미터", "제곱미터", "킬로", "미터", "센티", "밀리", "그램", "리터",
              "기가", "테라", "메가", "와트", "볼트", "헤르츠", "칼로리", "포인트", "픽셀"]
# 한자어로 읽지만 한 글자(또는 다른 낱말의 앞부분)라 조심할 것(3엔진·2프로그램·4인치·5평균·2박자)
SINO_STRICT = ["엔", "프로", "평", "쪽", "인", "박", "급", "조", "승", "패", "골", "표", "칸", "쪽지"]
MEASURE = {"GB": "기가", "TB": "테라", "MB": "메가", "KB": "킬로바이트", "kW": "킬로와트", "W": "와트", "GHz": "기가헤르츠",
           "MHz": "메가헤르츠", "kHz": "킬로헤르츠", "Hz": "헤르츠", "mm": "밀리", "cm": "센티", "km": "킬로미터", "kg": "킬로그램", "ms": "밀리초",
           "fps": "에프피에스", "FPS": "에프피에스", "Mbps": "메가비피에스", "Gbps": "기가비피에스", "nm": "나노", "V": "볼트",
           "mAh": "밀리암페어", "인치": "인치", "m": "미터", "g": "그램", "K": "케이", "k": "케이",
           "ml": "밀리리터", "mL": "밀리리터", "㎖": "밀리리터", "L": "리터", "ℓ": "리터", "mg": "밀리그램", "kcal": "킬로칼로리", "cal": "칼로리",
           "kWh": "킬로와트시", "dB": "데시벨", "px": "픽셀", "㎡": "제곱미터", "m²": "제곱미터", "m2": "제곱미터", "㎥": "세제곱미터", "m³": "세제곱미터",
           "km²": "제곱킬로미터", "㎢": "제곱킬로미터", "㎞": "킬로미터", "㎏": "킬로그램", "㎝": "센티", "㎜": "밀리", "㎓": "기가헤르츠", "㎐": "헤르츠",
           "%p": "퍼센트포인트", "㎍": "마이크로그램", "µg": "마이크로그램", "μg": "마이크로그램"}
CURRENCY = {"$": "달러", "＄": "달러", "₩": "원", "￦": "원", "€": "유로", "¥": "엔", "￥": "엔", "£": "파운드"}
WORDS = {"ok": "오케이", "okay": "오케이", "wifi": "와이파이", "wi-fi": "와이파이", "bluetooth": "블루투스", "windows": "윈도우",
         "intel": "인텔", "nvidia": "엔비디아", "geforce": "지포스", "radeon": "라데온", "ryzen": "라이젠", "core": "코어",
         "ultra": "울트라", "pro": "프로", "max": "맥스", "super": "슈퍼", "samsung": "삼성", "logitech": "로지텍",
         "corsair": "커세어", "discord": "디스코드", "youtube": "유튜브", "google": "구글", "chrome": "크롬", "excel": "엑셀",
         "kakao": "카카오", "email": "이메일", "e-mail": "이메일", "claude": "클로드", "chatgpt": "챗지피티", "gemini": "제미나이",
         "hi": "하이", "hello": "헬로", "update": "업데이트", "driver": "드라이버", "error": "에러", "server": "서버",
         "file": "파일", "check": "체크", "monitor": "모니터", "mouse": "마우스", "keyboard": "키보드", "case": "케이스",
         "cooler": "쿨러", "power": "파워", "board": "보드", "gaming": "게이밍", "game": "게임", "steam": "스팀",
         "valorant": "발로란트", "overwatch": "오버워치", "minecraft": "마인크래프트", "photoshop": "포토샵", "arc": "아크",
         "thank": "땡큐", "thanks": "땡스", "sorry": "쏘리", "yes": "예스", "no": "노", "black": "블랙", "white": "화이트",
         "edition": "에디션", "gen": "젠", "ram": "램", "ssd": "에스에스디", "rgb": "알지비", "argb": "에이알지비",
         # 약어지만 낱말처럼 읽는 것·자주 나오는 이름
         "nasa": "나사", "unesco": "유네스코", "nato": "나토", "opec": "오펙", "fifa": "피파", "kospi": "코스피", "kosdaq": "코스닥",
         "unicef": "유니세프", "asean": "아세안", "apec": "에이펙", "lan": "랜", "rom": "롬", "sim": "심", "pin": "핀", "jpeg": "제이펙",
         "covid": "코비드", "iphone": "아이폰", "ipad": "아이패드", "galaxy": "갤럭시", "android": "안드로이드", "apple": "애플",
         "microsoft": "마이크로소프트", "amazon": "아마존", "netflix": "넷플릭스", "instagram": "인스타그램", "facebook": "페이스북",
         "twitter": "트위터", "telegram": "텔레그램", "kakaotalk": "카카오톡", "naver": "네이버", "tesla": "테슬라", "openai": "오픈에이아이",
         "app": "앱", "web": "웹", "online": "온라인", "offline": "오프라인", "login": "로그인", "logout": "로그아웃", "wow": "와우",
         "bye": "바이", "good": "굿", "top": "톱", "best": "베스트", "new": "뉴", "live": "라이브", "news": "뉴스", "menu": "메뉴"}


# ---------------- 숫자 읽기 ----------------
def sino(n: int) -> str:
    """한자어 수: 12345 → 만이천삼백사십오, 0 → 영."""
    if n == 0:
        return "영"
    big = ["", "만", "억", "조", "경"]
    out = []
    i = 0
    while n > 0:
        n, g = divmod(n, 10000)
        if g:
            s = ""
            for d, u in zip(f"{g:04d}", ["천", "백", "십", ""]):
                d = int(d)
                if d == 0:
                    continue
                s += (u if (d == 1 and u) else SINO[d] + u)
            if i == 1 and s == "일":
                s = ""          # 일만 → 만
            out.append(s + big[i])
        i += 1
    return "".join(reversed(out))


def native(n: int) -> str:
    """고유어 관형 수(세는 말 앞): 1 한, 20 스무, 23 스물세. 100 이상은 끝 두 자리가 1~19 일 때만 고유어를 섞음(101 백한, 112 백열두),
    그 밖에는 한자어(120 백이십, 125 백이십오)."""
    if n <= 0:
        return sino(n)
    if n >= 100:
        tail = n % 100
        return sino(n - tail) + native(tail) if 1 <= tail <= 19 else sino(n)
    t, o = divmod(n, 10)
    if n == 20:
        return "스무"
    return N_TENS[t] + N_ONES[o]


def digits(s: str) -> str:
    return "".join(CODE_DIGIT[int(c)] for c in s if c.isdigit())


def decimal(s: str) -> str:
    a, b = s.split(".", 1)
    return sino(int(a)) + " 점 " + "".join(SINO[int(c)] for c in b)


def read_number(s: str) -> str:
    s = s.replace(",", "")
    if "." in s:
        return decimal(s)
    if len(s) > 1 and s.startswith("0"):
        return digits(s)
    if len(s) >= 13:
        return digits(s)
    return sino(int(s))


def spell(w: str) -> str:
    out = []
    for c in w:
        if c.upper() in LETTER:
            out.append(LETTER[c.upper()])
        elif c.isdigit():
            out.append(CODE_DIGIT[int(c)])
    return "".join(out)


def spell_mixed(w: str) -> str:
    """글자와 숫자가 섞인 짧은 이름: 숫자 한 자리 = 영어 숫자(A4 에이포·MP3 엠피쓰리·PS5 피에스파이브), 두 자리 = 한자어(G20 지이십·F16 에프십육),
    세 자리 넘으면 한 자리씩(A380 에이삼팔공). 글자 묶음은 아는 낱말이면 그 읽기, 아니면 철자."""
    out = []
    for run in re.findall(r"[A-Za-z]+|\d+", w):
        if run.isdigit():
            out.append(EN_NUM[run] if len(run) == 1 else sino(int(run)) if len(run) == 2 and run[0] != "0" else digits(run))
        elif run.lower() in WORDS:
            out.append(WORDS[run.lower()])
        elif run.isupper() or len(run) <= 3:
            out.append(spell(run))
        else:
            out.append(" " + run + " ")     # 긴 영어 낱말은 그대로(목소리 모델이 영어로 읽음)
    return re.sub(r"\s{2,}", " ", "".join(out)).strip()


# ---------------- 발음사전 ----------------
_dict_cache = {}   # 경로 → (mtime, rules)


def _key_regex(key: str):
    runs = re.findall(r"[A-Za-z]+|\d+|[가-힣]+|\s+|.", key)
    parts = []
    prev_alnum = False
    for r in runs:
        if r.isspace():
            parts.append(r"\s*")
            prev_alnum = False
            continue
        if r == "-":
            parts.append(r"[\s-]?")
            prev_alnum = False
            continue
        alnum = r[0].isalnum()
        if alnum and prev_alnum:
            parts.append(r"[\s-]?")
        parts.append(re.escape(r))
        prev_alnum = alnum
    flags = re.IGNORECASE if re.search(r"\d", key) else 0
    return re.compile(r"(?<![A-Za-z0-9])" + "".join(parts) + r"(?![A-Za-z0-9])", flags)


def load_dict(path=DICT_PATH):
    """발음 사전(원문<TAB>읽기[<TAB>분류]) → [(정규식, 읽기, 원문)] (긴 원문 먼저). 없으면 []."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return []
    hit = _dict_cache.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for ln in f:
            if ln.startswith("#") or not ln.strip():
                continue
            p = ln.rstrip("\r\n").split("\t")
            if len(p) >= 2 and p[0].strip() and p[1].strip():
                rows.append((p[0].strip(), p[1].strip()))
    rows.sort(key=lambda x: -len(x[0]))
    rules = [(_key_regex(a), b, a) for a, b in rows]
    _dict_cache[path] = (mt, rules)
    return rules


# ---------------- 부품 규칙(사전에 없을 때) ----------------
def _gpu(m):
    pre, num, suf = m.group(1), m.group(2), m.group(3)
    s = spell(pre) + " " + digits(num)
    if suf:
        s += " " + SUFFIX.get(suf.upper(), spell(suf))
    return s


def _intel(m):
    tier, num, suf = m.group(1), m.group(2), m.group(3)
    s = "아이" + EN_NUM[tier] + " " + sino(int(num))
    if suf:
        s += " " + SUFFIX.get(suf.upper(), spell(suf))
    return s


def _ultra(m):
    tier, num, suf = m.group(1), m.group(2), m.group(3)
    s = "울트라 " + EN_NUM[tier] + " " + digits(num)
    if suf:
        s += " " + SUFFIX.get(suf.upper(), spell(suf))
    return s


def _amd_cpu(m):
    num, suf = m.group(1), m.group(2)
    n = sino(int(num)) if num.endswith("00") else digits(num)
    return n + " " + SUFFIX.get(suf.upper(), spell(suf))


def _bare_gpu(m):
    return digits(m.group(1)) + " " + SUFFIX[m.group(2).upper()]


def _chipset(m):
    s = LETTER[m.group(1).upper()] + digits(m.group(2))
    if m.group(3):
        s += " " + SUFFIX.get(m.group(3).upper(), spell(m.group(3)))
    return s


B0, B1 = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
HW_RULES = [
    (re.compile(B0 + r"(RTX|GTX|RX|GT)[\s-]?(\d{3,4})[\s-]?(Ti|SUPER|Super|XTX|XT|GRE)?" + B1, re.I), _gpu),
    (re.compile(B0 + r"i([3579])[\s-]?(\d{4,5})(KF|KS|K|F|T|H|HX|U)?" + B1), _intel),
    (re.compile(B0 + r"(?:Core\s+)?Ultra\s*([3579])\s*(\d{3})(K|KF|F|H|HX|U|V)?" + B1, re.I), _ultra),
    (re.compile(B0 + r"(\d{4})[\s-]?(XTX|XT)" + B1, re.I), _bare_gpu),
    (re.compile(B0 + r"([3-9]\d{3})(X3D|X|F|G)" + B1), _amd_cpu),
    (re.compile(B0 + r"([ABHXZ])(\d{3})(E|M|I)?" + B1), _chipset),
]


# ---------------- 날짜·시각·전화·판 번호 ----------------
def _month(n):
    return {6: "유", 10: "시"}.get(n, sino(n))


def _phone(m):
    return ", ".join(digits(g) for g in re.split(r"[-.\s]+", m.group(0).strip()) if g)


def _has_batchim(word):
    ch = (word or " ")[-1]
    return "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0


_AMPM = re.compile(r"(오전|오후|새벽|아침|낮|점심|저녁|밤)\s*$")
# 숫자를 읽고 나면 끝소리가 달라져 뒤 조사가 안 맞는 경우(14:05예요 → …오 분이에요)에만 조사를 맞춘다
_JOSA_FIX = [("예요", "이에요"), ("였", "이었"), ("가", "이"), ("는", "은"), ("를", "을"), ("와", "과"), ("로", "으로"), ("라", "이라"), ("야", "이야"), ("랑", "이랑")]


def hour_words(h, before=""):
    """시(0~24) → 읽는 말. 13~23 시는 '오후 한 시'처럼(앞에 오전·오후·저녁 같은 말이 이미 있으면 붙이지 않음)."""
    if h == 0:
        return "영 시"
    if h == 24 or h > 24:
        return sino(h) + " 시"
    if h <= 12:
        return native(h) + " 시"
    return ("" if _AMPM.search(before) else "오후 ") + native(h - 12) + " 시"


def _fix_josa(tail, said):
    """said(방금 읽은 말) 뒤에 붙은 조사 tail 을 끝소리에 맞춤. 받침이 생겼을 때만."""
    if not _has_batchim(said):
        return tail
    for a, b in _JOSA_FIX:
        if tail.startswith(a) and not tail.startswith(b):
            return b + tail[len(a):]
    return tail


def _clock(s):
    """14:05 · 9:30:15 → 읽는 말. 뒤에 붙은 조사는 끝소리에 맞춤."""
    out, pos = [], 0
    for m in re.finditer(r"(?<![\d:.])([01]?\d|2[0-4]):([0-5]\d)(?::([0-5]\d))?(?![\d:])", s):
        h, mi, se = int(m.group(1)), int(m.group(2)), m.group(3)
        said = hour_words(h, s[max(0, m.start() - 8):m.start()])
        if mi:
            said += " " + sino(mi) + " 분"
        if se and int(se):
            said += " " + sino(int(se)) + " 초"
        out.append(s[pos:m.start()] + said)
        pos = m.end()
        tail = s[pos:pos + 3]
        fixed = _fix_josa(tail, said)
        if fixed != tail:
            out.append(fixed)
            pos += 3
    out.append(s[pos:])
    return "".join(out)


def _date(m):
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return m.group(0)
    return f"{sino(y)} 년 {_month(mo)}월 {sino(d)} 일"


def _version(m):
    """0.1.12 · 1.2.3.4 · v2.0 → 마디마다 한자어 수로, 사이는 '점'. 앞의 v 는 '버전'(이미 '버전'이라고 썼으면 한 번만)."""
    pre, body = m.group(1) or "", m.group(2)
    parts = [sino(int(p)) if not (len(p) > 1 and p.startswith("0")) else digits(p) for p in body.split(".")]
    said = " 점 ".join(parts)
    if pre and not re.search(r"(버전|판)\s*$", m.string[max(0, m.start() - 4):m.start()]):
        said = "버전 " + said
    return said


# ---------------- 숫자 + 세는 말 ----------------
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
# 한 글자 세는 말 뒤에 올 수 있는 것: 문장 끝·띄어쓰기·기호, 또는 조사·말끝(뒤에 다른 낱말이 이어지면 세는 말이 아님: 3병원·2채널)
_PART = (r"(?=$|[^가-힣]|이에요|예요|입니|이야|이고|인데|이라|이나|이랑|이면|이네|이죠|이요|밖에|까지|부터|보다|정도|짜리|마다|씩|째|쯤|"
         r"[이가은는을를의에도만과와로랑요])")
_STRICT = set(NATIVE_STRICT) | set(SINO_STRICT)
_NATIVE = set(NATIVE_UNITS) | set(NATIVE_STRICT)
_UNITS = sorted(_NATIVE | set(SINO_UNITS) | set(SINO_STRICT), key=len, reverse=True)
_UNIT_RX = "|".join((re.escape(u) + _PART) if u in _STRICT else re.escape(u) for u in _UNITS)
_MU = "|".join(sorted(map(re.escape, MEASURE), key=len, reverse=True))
# '번': 번호로 쓰일 때 바로 뒤에 오는 말(3번 버스·1번 출구) — 이럴 때와 조사 이·가·은·는·을·를·의·과·와 가 붙을 때는 한자어, 그 밖에는 횟수(고유어)
_BEON_NOUN = "버스|출구|선수|타자|문제|문항|후보|트랙|채널|국도|창구|테이블|레인|게이트|승강장|플랫폼|코스|좌석|자리|사물함|타석|항목|선택지|카드|라운드"
_BEON_SINO = re.compile(r"(?:\s*(?:" + _BEON_NOUN + r")|\s*(?:방|줄|칸|홀)" + _PART + r"|(?:이|가|은|는|을|를|의|과|와)(?![가-힣]))")


KEEP = chr(0xE001)    # 지켜야 하는 띄어쓰기 자리(변환 맨 끝에 보통 띄어쓰기로 되돌림)
_OFTEN = re.compile(r"(?:에|마다|매일|매주|매달|매년)\s*$")   # '하루에 1번은' = 횟수


def _counted(m):
    num, unit = m.group(1), m.group(2)
    v = num.replace(",", "")
    rest = m.string[m.end():]
    if "." in v:
        return decimal(v) + (KEEP if unit == "도" else " ") + unit
    n = int(v)
    if unit == "번째":
        return ("첫" if n == 1 else native(n)) + " 번째"
    if unit == "시":
        if rest[:1] in ("즌", "리", "스", "장", "절", "도", "작", "험", "대"):      # 3시즌·2시리즈 — 시각이 아님(남은 숫자 읽기에 맡김)
            return m.group(0)
        return hour_words(n, m.string[max(0, m.start() - 8):m.start()])
    if unit == "대" and n >= 10 and n % 10 == 0:
        return sino(n) + " 대"         # 20대(나이대)
    if unit == "번":
        number = _BEON_SINO.match(rest) and not _OFTEN.search(m.string[max(0, m.start() - 6):m.start()])
        return (sino(n) if number else native(n)) + " 번"
    if unit == "배":
        return (native(n) if 1 <= n <= 10 else sino(n)) + " 배"
    if unit in _NATIVE:
        return native(n) + " " + unit
    if unit == "도":
        return sino(n) + KEEP + unit      # '삼 도.' 가 조사 '도'처럼 붙지 않게
    return sino(n) + " " + unit


def _measure(m):
    num, unit = m.group(1), m.group(2)
    v = num.replace(",", "")
    r = decimal(v) if "." in v else sino(int(v))
    return r + " " + MEASURE[unit]


def _plain_num(m):
    return read_number(m.group(0))


def _numv(s):
    v = s.replace(",", "")
    return decimal(v) if "." in v else sino(int(v))


def _fraction(m):
    a, b = int(m.group(1)), int(m.group(2))
    if not (0 < a < b <= 10):
        return m.group(0)
    return sino(b) + "분의 " + sino(a) + (" " if "가" <= m.string[m.end():m.end() + 1] <= "힣" else "")


_ORDINAL = ["", "첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째", "일곱째", "여덟째", "아홉째", "열째"]
_LIST_RX = re.compile(r"(?:(?<=^)|(?<=\s))(\d{1,2})\.\s+(?=[가-힣A-Za-z])")


def _list_marks(s):
    """'1. 사과 2. 배 3. 감' 같은 목록 번호 → 첫째, 둘째, 셋째. 글 맨 앞의 번호(1~10)와 그 뒤로 차례대로 이어지는 번호만 바꾼다
    ('정답은 3. 다음은'처럼 문장 끝 숫자는 건드리지 않음)."""
    out, pos, expect = [], 0, None
    for m in _LIST_RX.finditer(s):
        n = int(m.group(1))
        first = not s[:m.start()].strip()
        if not ((first and 1 <= n <= 10) or (expect is not None and n == expect and n <= 10)):
            continue
        out.append(s[pos:m.start()] + _ORDINAL[n] + ", ")
        pos = m.end()
        expect = n + 1
    out.append(s[pos:])
    return "".join(out)


# ---------------- 메인 ----------------
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


# 하품 의성어(하암·하아암·하~암·후아암·흐아암·아함 …)와 '(하품)' 같은 지문은 소리로 안 읽음 — 읽으면 가짜 티가 남.
#   하품은 펫 그림 동작으로만. 낱말 '하품'(예: 하품이 나요)은 그대로 둠 — 괄호·별표 지문일 때만 뺌.
YAWN = re.compile(r"(?<![가-힣])(?:(?:하|후|흐)[아으ㅏ~\-]*암+|아+함+|하아+함+)+(?![가-힣])[\s~!.,…]*")   # '아암(그렇지)'은 안 뺌
YAWN_NOTE = re.compile(r"[\(\[\*]+\s*(?:하품|하품하며|하품을 하며|하품 소리)\s*[\)\]\*]+")


def has_yawn(s: str) -> bool:
    return bool(YAWN_NOTE.search(s) or YAWN.search(s))


def drop_yawn(s: str) -> str:
    s = YAWN_NOTE.sub(" ", s)
    s = YAWN.sub(" ", s)
    s = re.sub(r"^[\s,.~!…]+", "", s)                 # 앞에 남은 쉼표·마침표
    s = re.sub(r"([.!?])\s*[,~]+", r"\1", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def normalize(text: str, dict_paths=None) -> str:
    s = text
    s = EMOJI.sub("", s)
    s = drop_yawn(s)
    s = re.sub(r"https?://\S+", "링크", s)
    # 날짜: 2026-11-16 · 2026.11.16 · 2026/11/16 · 2026. 11. 16. (목록 번호·판 번호보다 먼저)
    s = re.sub(r"(?<![\d.])((?:19|20)\d{2})\s?[-./]\s?(\d{1,2})\s?[-./]\s?(\d{1,2})(?:\.(?=\s|$))?(?![\d])", _date, s)
    s = _list_marks(s)                                # '1. 사과 2. 배' 목록 번호
    s = re.sub(r"[*_`#>|]+", " ", s)                  # 마크다운 기호
    s = s.replace("…", "...").replace("“", "").replace("”", "").replace("‘", "").replace("’", "")
    s = s.replace("−", "-").replace("％", "%").replace("：", ":").replace("∼", "~").replace("〜", "~")
    s = re.sub(r"[\(\)\[\]{}]", ", ", s)
    s = re.sub(r"[ \t]+", " ", s)

    for p in (dict_paths if dict_paths is not None else [*EXTRA_DICTS, DICT_PATH]):
        for rx, rd, _ in load_dict(p):
            s = rx.sub(rd, s)
    for rx, fn in HW_RULES:
        s = rx.sub(fn, s)
    # 글자로 시작해 숫자가 섞인 짧은 이름(A4·MP3·G20·H2O) — 뒤의 숫자 읽기가 먼저 바꾸기 전에
    s = re.sub(r"(?<![A-Za-z0-9.,])(?![vV]\d)[A-Za-z]{1,8}\d{1,4}[A-Za-z0-9]{0,6}(?![A-Za-z0-9]|[.,]\d|-\d)",
               lambda m: WORDS.get(m.group(0).lower()) or spell_mixed(m.group(0)), s)

    # 전화번호: 010-1234-5678 · 02-123-4567 · 010 1234 5678 · 1588-1234
    s = re.sub(r"(?<!\d)0\d{1,3}-\d{3,4}-\d{4}(?!\d)", _phone, s)
    s = re.sub(r"(?<![\d.])01[016789][ .]\d{3,4}[ .]\d{4}(?!\d)", _phone, s)
    s = re.sub(r"(?<![\d-])1[5-9]\d{2}-\d{4}(?![\d-])", _phone, s)
    # 판 번호: 0.1.12 · v2.0 (점이 두 번 넘게 나오는 숫자 · v 로 시작하는 숫자)
    s = re.sub(B0 + r"([vV])?(\d+(?:\.\d+){2,})" + r"(?![\d])", _version, s)
    s = re.sub(B0 + r"([vV])(\d+(?:\.\d+)?)" + B1, _version, s)
    # 시각: 14:05 · 오전/오후 3pm
    s = _clock(s)
    s = re.sub(r"(?<![\d:.])(\d{1,3}):(\d{1,3})(?![\d:])", r"\1" + KEEP + "대" + KEEP + r"\2", s)   # 3:2 로 이겼어요 · 16:9 화면(세는 말 '대'와 구별)
    s = re.sub(r"(?<![A-Za-z])(\d{1,2})\s?(am|pm|AM|PM|a\.m\.|p\.m\.)(?![A-Za-z])",
               lambda m: ("오전 " if m.group(2).lower().startswith("a") else "오후 ") + m.group(1) + "시", s)
    s = re.sub(r"(?<![A-Za-z])(AM|PM)\s?(?=\d)", lambda m: "오전 " if m.group(1) == "AM" else "오후 ", s)
    s = re.sub(r"(?<!\d)(\d{1,2})\s*월(?![가-힣]{2})", lambda m: _month(int(m.group(1))) + "월", s)
    # 돈 기호: $100 → 100달러(뒤의 세는 말 규칙이 읽음)
    s = re.sub(r"([$＄₩￦€¥￥£])\s?(" + NUM + r")", lambda m: m.group(2) + CURRENCY[m.group(1)], s)
    # 온도·음수: 23℃ · -3도 → 영하 삼 도 · 그 밖의 -5 → 마이너스 오
    s = re.sub(r"(" + NUM + r")\s*(?:℃|°\s?C|도씨)", r"\1도", s)
    s = re.sub(r"(?:화씨\s*)?(" + NUM + r")\s*(?:℉|°\s?F)", r"화씨 \1도", s)
    s = re.sub(r"(" + NUM + r")\s*°", r"\1도", s)
    s = re.sub(r"(?:영하\s*)?(?<![\d가-힣A-Za-z)\]%.,])-\s?(" + NUM + r")(?=\s*도)", r"영하 \1", s)
    s = re.sub(r"(?<![\d가-힣A-Za-z)\]%.,-])-(?=\d)", "마이너스 ", s)
    s = re.sub(r"(?<![\d가-힣A-Za-z)\]%.,+])\+(?=\d)", "플러스 ", s)
    # 속도·분수·날짜(11/16에)·곱하기
    s = re.sub(r"(" + NUM + r")\s*(?:㎍|µg|μg)/(?:㎥|m³|m3)", r"\1㎍", s)
    s = re.sub(r"(" + NUM + r")\s*(KB|MB|GB)/s(?![A-Za-z])", lambda m: "초당 " + m.group(1) + m.group(2), s)
    s = re.sub(r"(?<![\d/.])(1[0-2]|0?[1-9])/([12]\d|3[01]|0?[1-9])(?=에|부터|까지|일|\s*[월화수목금토일]요일)",
               lambda m: f"{int(m.group(1))}월 {int(m.group(2))}일", s)
    s = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", " 곱하기 ", s)
    s = re.sub(r"\s*[×✕]\s*", " 곱하기 ", s)
    s = re.sub(r"(?<![A-Za-z])No\.\s?(\d)(?!\d)", lambda m: "넘버" + EN_NUM[m.group(1)], s)
    s = re.sub(r"(" + NUM + r")\s*(?:km/h|㎞/h|kph)(?![A-Za-z])", r"시속 \1km", s)
    s = re.sub(r"(" + NUM + r")\s*m/s(?![A-Za-z])", r"초속 \1m", s)
    s = re.sub(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?![\d/.])", _fraction, s)
    s = re.sub(r"(\d+)\s*분의\s*(\d+)", lambda m: sino(int(m.group(1))) + "분의 " + sino(int(m.group(2))), s)
    # 글자 하나짜리 이름: 4K·5G·3D·2D·3M (숫자를 영어로)
    s = re.sub(r"(?<![A-Za-z0-9.,])([1-9])(DX|[KGDM])(?![A-Za-z0-9])", lambda m: EN_NUM[m.group(1)] + spell(m.group(2)), s)
    # 범위 3~4시간 → 세 시간에서 네 시간
    s = re.sub(r"(" + NUM + r")\s*[~-]\s*(" + NUM + r")\s*(" + _MU + "|" + _UNIT_RX + r"|%)",
               lambda m: f"{m.group(1)}{m.group(3)}에서 {m.group(2)}{m.group(3)}", s)
    s = re.sub(r"(" + NUM + r")\s*~\s*(" + NUM + r")", r"\1에서 \2", s)
    s = re.sub(r"(" + NUM + r")\s*%p(?![A-Za-z])", lambda m: _numv(m.group(1)) + " 퍼센트포인트", s)
    s = re.sub(r"(" + NUM + r")\s*%", lambda m: _numv(m.group(1)) + " 퍼센트", s)
    s = re.sub(r"(" + NUM + r")\s*(" + _MU + r")(?![A-Za-z])", _measure, s)
    # 큰 수 낱말: 1만 원 → 만 원 · 1천 명 → 천 명 · 120만원 → 백이십만 원 · 2.8조 원
    s = re.sub(r"(?<![\d.])1\s*만(?=\s*원|\s|$|[가-힣])", "만", s)
    s = re.sub(r"(?<![\d.,])1(?=(?:천|백)(?:만|억|조)?(?:\s|원|명|개|건|번|장|대|$|[^가-힣]))", "", s)
    s = re.sub(r"(" + NUM + r")\s*(천만|백만|십만|만|억|조)\s*원", lambda m: read_number(m.group(1)) + m.group(2) + " 원", s)
    s = re.sub(r"(" + NUM + r")\s*(" + _UNIT_RX + r")", _counted, s)
    s = re.sub(NUM, _plain_num, s)

    # 영어
    def _word(m):
        w = m.group(0)
        lw = w.lower()
        if lw in WORDS:
            return WORDS[lw]
        if re.search(r"\d", w):
            return spell_mixed(w)
        if re.fullmatch(r"[A-Z]+", w):
            return spell(w)
        return w                                        # 일반 영어 낱말은 그대로(모델이 영어로 읽음)
    s = re.sub(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z]+)?", _word, s)

    # 기호
    s = re.sub(r"(?<=\S)\s*&\s*(?=\S)", " 앤 ", s)
    s = re.sub(r"(?<=[가-힣])\s*\+\s*(?=[가-힣])", " 플러스 ", s)
    s = re.sub(r"(?<=[가-힣])\s*=\s*(?=[가-힣])", lambda m: ("은 " if _has_batchim(m.string[:m.start()]) else "는 "), s)
    s = re.sub(r"\s*÷\s*", " 나누기 ", s)
    s = re.sub(r"\s*/\s*", " ", s)
    s = re.sub(r"~+(?=\s|$|[.!?])", "", s)
    s = re.sub(r"(?<=[가-힣])-(?=[가-힣])", " ", s)
    s = re.sub(r"\s+([,.!?])", r"\1", s)
    s = re.sub(r",\s*,+", ",", s)
    s = re.sub(r"^\s*,\s*|\s*,\s*$", "", s)
    # 바꾼 말 뒤 띄어 쓴 조사 붙이기(이 는 숫자 2 와 헷갈려 제외)
    s = re.sub(r"(?<=[가-힣])\s+(에서|에게|으로|부터|까지|에|은|는|가|을|를|의|와|과|로)(?=[\s,.!?]|$)", r"\1", s)
    s = re.sub(r"(?<=[가-힣])(?<![영일이삼사오육칠팔구십백천만억])\s+도(?=[\s,.!?]|$)", "도", s)   # '삼십 도.'(온도·각도)는 그대로 띄움
    s = re.sub(r"\s+", " ", s.replace(KEEP, " ")).strip()
    return s


def split_sentences(text: str, max_len=60):
    """문장 단위로 나눈다(먼저 말하기용). 너무 긴 문장은 쉼표에서 한 번 더 나눔."""
    parts = re.split(r"(?<=[.!?。…])\s+|(?<=[。！？])|\n+", text.strip())
    if not re.search(r"[가-힣぀-ヿ一-鿿]", text):
        max_len = max(max_len, 110)      # 영어 등 라틴 글은 한 문장이 길어 쉼표에서 덜 자름(억양이 끊기지 않게)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        while len(p) > max_len and "," in p[10:max_len]:
            k = p.rfind(",", 10, max_len) + 1
            out.append(p[:k].strip())
            p = p[k:].strip()
        out.append(p)
    # 아주 짧은 문장('네, 알겠습니다.')은 다음 문장과 붙임 → 따로 만들면 억양이 끊기고 목소리 검사도 못 함
    merged = []
    for p in out:
        if merged and len(merged[-1]) < 15 and len(merged[-1]) + 1 + len(p) <= max_len:
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)
    if len(merged) > 1 and len(merged[-1]) < 15 and len(merged[-2]) + 1 + len(merged[-1]) <= max_len:
        merged[-2:] = [merged[-2] + " " + merged[-1]]     # 끝에 남은 짧은 문장은 앞에 붙임
    return merged


if __name__ == "__main__":
    import sys
    for t in sys.argv[1:]:
        print(normalize(t))
