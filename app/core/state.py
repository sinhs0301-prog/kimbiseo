# 한 대화(연결) 동안 부품들이 같이 보는 상태 + 자기 목소리(메아리) 판정에 쓰는 글·소리 비교.
#   자기 목소리 거르기(운영판과 같은 부품·같은 값):
#     1층 메아리 창 — 비서가 말하는 중 + 멈춘 뒤 '자기목소리_뒤여유_초'(끼어들기로 끊겼으면 0.5초) 안에 시작한 말만 의심
#     2층 첫소리 무시 — 비서가 말을 시작하고 '첫소리_무시_초' 동안 들린 말소리는 끼어들기로 보지 않음(turns.py)
#     3층 글 비교 — 받아쓴 글이 방금 비서가 말한 글의 어느 부분과 '자기목소리_유사도' 이상 같으면 메아리
#     4층 소리 크기 모양 — 마이크 소리 크기가 비서가 0~0.8초 앞서 낸 소리 크기를 따라 움직이면(상관 '메아리_상관_기준') 메아리
import re
import time
from collections import Counter, deque

import numpy as np
from loguru import logger

from . import config as C
from .wake import NameMatcher

from .voice_link import text_norm  # 저장소 voice/text_norm.py — 목소리에 넣는 글과 같은 읽기 변환


def norm_text(s):
    """비서가 말한 글과 받아쓴 글을 같은 꼴로(읽기 변환 → 글자·숫자만, 소문자)."""
    try:
        s = text_norm.normalize(s or "")
    except Exception:  # noqa: BLE001
        s = s or ""
    # 통역(0.1.15~): 태국·그리스·키릴·베트남 성조 글자·가나·한자도 남김 — 원어민 목소리 메아리를 알아보고, 외국어 말이 '빈 말'로 버려지지 않게
    return re.sub(r"[^0-9A-Za-z가-힣぀-ヿ一-鿿\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF\u0E00-\u0E7F\u1E00-\u1EFF\u3040-\u30FF\u4E00-\u9FFF]", "", s).lower()


def approx_substring_similarity(t, ref):
    """t 가 ref 안의 어느 부분과 얼마나 같은지(0~1). 부분 문자열 편집거리."""
    m = len(t)
    if m == 0 or not ref:
        return 0.0
    prev = [0] * (len(ref) + 1)
    for i in range(1, m + 1):
        cur = [i] + [0] * len(ref)
        ti = t[i - 1]
        for j in range(1, len(ref) + 1):
            c = prev[j - 1] + (ti != ref[j - 1])
            a = prev[j] + 1
            b = cur[j - 1] + 1
            cur[j] = a if a < b and a < c else (b if b < c else c)
        prev = cur
    return 1.0 - min(prev) / m


def is_repeat_junk(text, audio_sec=None):
    """받아쓰기 반복 환각(말 안 했는데 같은 낱말 수백 번) — 같은 낱말·구절이 4번 넘게 이어지거나,
    말 길이에 비해 글자가 비정상으로 많으면 True(버림)."""
    t = str(text or "")
    toks = re.findall(r"[가-힣A-Za-z0-9぀-ヿ一-鿿]+", t)
    if len(toks) >= 4:
        run = best = 1
        for i in range(1, len(toks)):
            run = run + 1 if toks[i] == toks[i - 1] else 1
            best = max(best, run)
        if best >= 4:
            return True
        for k in (2, 3):
            grams = [" ".join(toks[i:i + k]) for i in range(0, len(toks) - k + 1)]
            if grams:
                _, c = Counter(grams).most_common(1)[0]
                if c >= 4 and c * k >= len(toks) * 0.5:
                    return True
        if len(set(toks)) <= max(1, len(toks) // 6):
            return True
    if audio_sec and audio_sec > 0:
        chars = len(re.sub(r"\s+", "", t))
        if chars > 14 * audio_sec + 20:   # 사람이 1초에 14글자 넘게 말하지 못함
            return True
    return False


def is_hallucination(text, cfg, audio_sec=None):
    n = norm_text(text)
    if not n:
        return True
    bad = {norm_text(x) for x in (cfg.get("귀") or {}).get("환각문구", [])}
    return n in bad or bool(_NEWS_SIGNOFF.match(n)) or is_repeat_junk(text, audio_sec)


# 받아쓰기가 조용한 끝자락에서 지어내는 방송 마무리 말('MBC 뉴스 ○○○입니다') — 운영 환각문구 'MBC뉴스' 를 앞부분 일치로 넓힘
#   norm_text 가 영문을 읽는 소리로 바꾸므로(MBC → 엠비씨) 읽는 꼴로 맞춘다. '뉴스 + 이름 + 입니다' 꼴만 — 'MBC 뉴스 틀어 줘' 같은 부탁은 통과.
_NEWS_SIGNOFF = re.compile(r"^(?:엠비씨|케이비에스|에스비에스|와이티엔|제이티비씨|엠비엔|오비에스|mbc|kbs|sbs|ytn|jtbc|mbn|obs)뉴스[가-힣]{2,4}(?:입니다|이었습니다|였습니다)$", re.I)


def apply_fixes(text, fixes):
    """받아쓰기 교정 사전(설정 '받아쓰기_교정' {틀린 꼴: 바른 꼴}) — 긴 것부터 바꿈."""
    if not fixes or not text:
        return text
    for k in sorted(fixes, key=len, reverse=True):
        v = fixes[k]
        if k and isinstance(v, str):
            text = text.replace(k, v)
    return text


class LevelTrace:
    """10ms 마다 소리 크기(dB)를 시각과 함께 적어 둔다. 자기 목소리 거르기 4층(크기 모양 상관)에 씀."""

    def __init__(self, keep=15.0):
        self.keep = keep
        self.t = deque()
        self.d = deque()

    def add(self, t_end, x, sr):
        w = int(sr * 0.01)
        n = len(x) // w
        if n == 0:
            return
        seg = x[: n * w].reshape(n, w)
        dbs = 20 * np.log10(np.maximum(np.sqrt((seg * seg).mean(1)), 1e-6))
        for i in range(n):
            self.t.append(t_end - (n - 1 - i) * 0.01)
            self.d.append(float(dbs[i]))
        while self.t and self.t[0] < t_end - self.keep:
            self.t.popleft()
            self.d.popleft()

    def arrays(self):
        return np.fromiter(self.t, float), np.fromiter(self.d, float)

    def at(self, grid, arr=None):
        """grid 시각들의 dB(그 시각 직전 기록, 없거나 0.05초 넘게 비면 -70)."""
        t, d = arr if arr is not None else self.arrays()
        if len(t) == 0:
            return np.full(len(grid), -70.0)
        i = np.searchsorted(t, grid, side="right") - 1
        ok = (i >= 0) & (np.abs(grid - t[np.clip(i, 0, None)]) < 0.05)
        out = np.where(ok, d[np.clip(i, 0, None)], -70.0)
        return np.clip(out, -70.0, 0.0)


class SessionState:
    """한 대화(연결) 동안 부품들이 같이 보는 상태."""

    def __init__(self, cfg, send_ui=None, pet=None):
        self.cfg = cfg
        self.send_ui = send_ui or (lambda ev: None)
        self.pet = pet
        name, aliases = C.names(cfg)
        self.names = NameMatcher(name, aliases)
        dc = cfg.get("대화") or {}
        self.stop_words = tuple(dict.fromkeys(
            [str(w) for w in dc.get("멈춤말", []) if str(w).strip()] + list(self.names.words)))
        self.bot_speaking = False
        self.bot_started_at = 0.0
        self.bot_stopped_at = 0.0
        self.bot_interrupted = False
        self.spoken = deque(maxlen=40)       # (시각, 정규화된 글) — 비서가 말한(말하려는) 문장
        self.mic = deque(maxlen=50)          # (시각, dBFS) 20ms 단위
        self.mic_env = LevelTrace()
        self.bot_env = LevelTrace()
        self.bot_spans = deque(maxlen=50)    # (시작, 끝 or None)
        self.turn_no = 0
        self.lang_mode = None
        self.lang_until = 0.0
        self.lang_turns = 0
        self.tool_busy = 0                   # 도구 진행 중(웹·날씨 등)
        self.stop_now = False                # 지금 사용자 말이 '그만·멈춰' 류 — 도구를 못 부르게
        self.no_tools_key = None             # 도구 폭주로 멈춘 그 질문(이 질문엔 도구 없이 답)
        self.user_speaking = False
        self.last_asr_t = 0.0
        self.always_name = bool(dc.get("이름부르기", False))    # 설정: 늘 이름을 불러야 대답
        self.wake = self.always_name                            # 지금 이름 부르기 모드인가(대기 도구로도 켜짐)
        self.wake_follow = float(dc.get("이름부르기_이어듣기_초", 15))
        self.wake_until = 0.0
        self.follow_block = False   # 대기 도구로 들어간 대기(이어듣기 막음)
        self.ambient_keep = float(dc.get("주변기억_초", 120))
        self.ambient = deque(maxlen=40)      # 부르지 않은 주변 말 — 메모리에만(디스크·기록·화면에 안 남김)
        self.ear_calls = deque(maxlen=200)   # (시각, '짧은'|'긴') — 대기 중 귀 부름 횟수 상한
        self.thinking = False
        self.thinking_t = 0.0
        self.pre_key = None
        self.log = []                        # 시험용 사건 기록
        self.fixes = dict(cfg.get("받아쓰기_교정") or {})
        self.last_typed = None
        self.speed = float((cfg.get("목소리") or {}).get("말속도", 1.0) or 1.0)
        # 말싸움(토론) 모드 — 대화(연결) 상태에만 둔다. 재시작·새 연결이면 꺼진 상태(core/debate.py).
        self.debate = False
        self.debate_t = 0.0
        self.debate_confirm_off_t = 0.0
        self.debate_adult_allowed = True       # 폰 앱 대화면 False(성인 말싸움 항상 끔)
        self.debate_ban = None                # (금지 낱말, 정규식) — 값은 이 메모리에만
        self.debate_memory = None             # 대화의 기억(금지어를 실행 때 만드는 데 씀)
        self.on_debate_change = None          # 켜기/끄기 때 지시문을 다시 만드는 Session 함수
        self.vad = None                        # 말 끝 기다림 늘리기용(켜면 늘리고 끄면 원래 값)
        self.vad_stop_base = None
        self.smart_turn = None
        self.smart_stop_base = None

    # ---- 사건(화면·펫·시험 기록)
    def event(self, kind, **kw):
        kw.update(type=kind, t=time.time())
        self.log.append(kw)
        try:
            self.send_ui(kw)
        except Exception as ex:  # noqa: BLE001
            logger.debug(f"화면 전송 실패: {ex}")
        if self.pet is not None:
            try:
                self.pet.on_event(self, kind, kw)
            except Exception as ex:  # noqa: BLE001
                logger.debug(f"펫 사건 오류: {ex}")

    def refresh_names(self):
        """설정의 비서 이름·별칭이 바뀌면(화면에서 저장) 깨우는 이름·멈춤 말을 지금 대화에도 바로 바꾼다."""
        name, aliases = C.names(self.cfg)
        self.names = NameMatcher(name, aliases)
        dc = self.cfg.get("대화") or {}
        self.stop_words = tuple(dict.fromkeys(
            [str(w) for w in dc.get("멈춤말", []) if str(w).strip()] + list(self.names.words)))
        self.event("names", name=name, aliases=list(aliases))

    # ---- 이름 부르기
    def addressed(self, text):
        return self.names.mentions(text)

    def is_stop(self, text):
        """짧은 '그만·멈춰·됐어' 류 말(긴 요청 속 낱말은 아님). 비서 이름은 멈춤 말이 아님."""
        t = str(text or "").strip()
        t = re.sub(r"\n?\(지금 시각: [^)]*\)\s*$", "", t).strip()
        if not 0 < len(t) <= 30:
            return False
        n = norm_text(t)
        return any(norm_text(w) and norm_text(w) in n
                   for w in (self.cfg.get("대화") or {}).get("멈춤말", []))

    def has_stop_word(self, text):
        n = norm_text(text)
        return any(norm_text(w) and norm_text(w) in n for w in self.stop_words)

    def set_wake(self, on, why=""):
        on = bool(on) or self.always_name
        # '쉬어·대기' 로 들어간 대기: 그 대답 뒤 이어듣기(15초)도 열지 않음 — 이름을 부를 때까지 주변 말에 답하지 않게.
        #   (운영판은 대기 때 접속 앱이 연결을 끊고 기기에서 이름만 기다려서 이 문제가 없었음)
        if why == "대기 도구":
            self.follow_block = True
        elif not on or why == "이름을 부름":
            self.follow_block = False
        if on != self.wake:
            self.wake = on
            self.event("wake_mode", on=on, why=why)

    def in_follow(self, t=None):
        """이름 부르기 모드에서 이름 없이도 대답하는 때: 방금 부른 뒤 잠깐, 생각·말하는 중, 말을 마친 뒤 잠깐.
        대기 도구로 들어간 대기면 '방금 부른 뒤 잠깐'만."""
        t = t or time.time()
        if self.follow_block:
            return t < self.wake_until
        return (self.bot_speaking or self.thinking or t < self.wake_until
                or (self.bot_stopped_at and t - self.bot_stopped_at < self.wake_follow))

    def ear_cap_ok(self, kind):
        """대기 중(이름 부르기, 이어듣기 밖) 귀 부름 상한 — 1분에 짧은 조각 '짧은'번, 긴 조각 '긴'번."""
        cap = (self.cfg.get("대화") or {}).get("대기_귀_상한") or {}
        lim = int(cap.get(kind, 30 if kind == "짧은" else 12))
        now = time.time()
        n = sum(1 for ts, k in self.ear_calls if k == kind and now - ts < 60)
        if n >= lim:
            return False
        self.ear_calls.append((now, kind))
        return True

    def ambient_text(self):
        now = time.time()
        xs = [x for ts, x in self.ambient if now - ts < self.ambient_keep]
        return " / ".join(xs)[-1200:]

    # ---- 자기 목소리
    def add_spoken(self, text):
        n = norm_text(text)
        if n:
            self.spoken.append((time.time(), n))

    def recent_bot_text(self, window=40.0, last=None):
        now = time.time()
        xs = [t for ts, t in self.spoken if now - ts < window]
        if last:
            xs = xs[-last:]
        return "|".join(xs)

    def in_echo_window(self, t=None):
        t = t or time.time()
        tail = 0.5 if self.bot_interrupted else float(self.cfg["대화"].get("자기목소리_뒤여유_초", 1.2))
        return self.bot_speaking or (t - self.bot_stopped_at) < tail

    def bot_spoke_between(self, t0, t1):
        return any(s < t1 and (e is None or e > t0) for s, e in self.bot_spans)

    def echo_corr(self, t0, t1, max_lag=0.8):
        """[t0,t1] 동안 마이크 소리 크기 모양이 비서가 0~0.8초 앞서 낸 소리 크기 모양을 따라가는지(최대 상관, 판단 가능 여부)."""
        if t1 - t0 < 0.3:
            return 0.0, False
        grid = np.arange(t0, t1, 0.01)
        m = self.mic_env.at(grid)
        barr = self.bot_env.arrays()
        best, active = 0.0, False
        for k in range(0, int(max_lag / 0.01) + 1):
            b = self.bot_env.at(grid - k * 0.01, barr)
            mask = b > -50.0
            if mask.sum() < 20 or b[mask].std() < 2.0:
                continue
            active = True
            mm = m[mask]
            if mm.std() < 2.0:
                continue
            c = float(np.corrcoef(mm, b[mask])[0, 1])
            if c > best:
                best = c
        return best, active

    def mic_db(self, window=0.15):
        now = time.time()
        v = [d for ts, d in self.mic if now - ts < window]
        return max(v) if v else -120.0
