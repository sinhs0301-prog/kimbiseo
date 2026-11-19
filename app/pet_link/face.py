# 펫 신호 — 대화 사건·내보낸 소리를 바탕화면 펫(127.0.0.1:포트.펫, 기본 17961)으로 보낸다(운영판 펫얼굴을 옮김).
#   /expr   표정: 듣는 중 = 보통 / 생각·도구 중 = 생각 / 말하는 중 = 답 글로 고른 감정 / 하품 글 = 졸림
#   /mouth  입: 출력 전송부가 내보낸 소리를 40ms 마다 크기(0~1)로 바꿔 '재생 시계'에 맞춰, 화면.펫_입_지연_초 만큼 늦춰 보냄
#   /bubble 말풍선: 답 글(마지막 두 문장, 90자 안)   /talk 말하기 준비   /emotion 감정 되돌리기
#   /motion 동작: 사용자 말(받아쓴 말·친 글)의 낱말 규칙 → 비서가 그 말을 받아들였을 때('생각 중'이 6초 안에 옴)만.
#           두뇌 답이 '네, 앉을게요'처럼 하겠다는 말이면 한 번 더 확인(안전망).
#   설정 화면.얼굴 = "펫" 일 때만 켬. 펫이 꺼져 있으면 5초 동안 보내지 않고 쌓인 입 움직임은 버림.
#   보내는 것: JSON, Content-Type: application/json, 127.0.0.1 만(펫은 Origin 머리가 있는 요청을 거절해야 함).
import heapq
import http.client
import json
import re
import threading
import time
from collections import deque

import numpy as np

STEP = 0.04
EMO_HOLD = 5.0
_KW = [
    ("기쁨", r"축하|다행|잘됐|잘 됐|좋네요|좋아요|좋습니다|좋은 하루|좋은 소식|반갑|감사합니다|고맙|기쁘|멋지|훌륭|완료했|끝냈|성공|해냈|하하|ㅎㅎ"),
    ("놀람", r"어머|깜짝|놀랍|놀랐|대단하|세상에|정말요\?|진짜요\?|와,|우와"),
    ("생각", r"죄송|미안|문제가|오류|실패|안 됩니다|안 돼요|못 했|못했|어렵|걱정|주의|조심|확인해 보|글쎄|잘 모르"),
    ("부끄러움", r"과찬|부끄럽|쑥스럽|별말씀"),
]
# 춤 이름 → 꾸러미 클립 이름. 말한 이름을 그대로 펫에 넘기면 펫이 지금 옷에 그 춤이 있는지 보고
#   없으면 기본 춤(dance1~3)으로 대신 춘다(pet/renderer/real/motion_names.js resolve·FALLBACK).
#   4개 언어(한·영·일·중)로 부르는 말을 받는다. '춤'만 말하면 아래 기본 춤(dance).
_DANCE_NAME = r"(?:제로\s*투|제로투|zero[\s_-]*two|zerotwo|ゼロツー|ゼロトゥ|零二|零２)"
_DANCE_VERB = r"(?:춤|댄스|춰|추|출|보여|틀어|dance|dancing|踊|ダンス|舞|跳舞|跳)"
_DANCE_BAD = r"(?:bad|배드|バッド)"
_DANCE_ESTELLA = r"(?:에스텔라|estella|エステラ)"
_MOTION_KW = [
    # 이름 있는 춤(기본 춤보다 먼저) — '제로투 춰줘'·'Zero Two dance'·'ゼロツー踊って'·'零二跳舞'·'BAD 춰줘'
    ("dance_zerotwo", _DANCE_NAME + r".{0,12}?" + _DANCE_VERB + r"|" + _DANCE_VERB + r".{0,12}?" + _DANCE_NAME +
                       r"|^\s*" + _DANCE_NAME + r"\s*[.!~]*\s*$"),
    ("dance_bad", _DANCE_BAD + r".{0,12}?" + _DANCE_VERB + r"|" + _DANCE_VERB + r".{0,12}?" + _DANCE_BAD +
                  r"|^\s*" + _DANCE_BAD + r"\s*[.!~]*\s*$"),
    ("dance_estella", _DANCE_ESTELLA + r".{0,12}?" + _DANCE_VERB + r"|" + _DANCE_VERB + r".{0,12}?" + _DANCE_ESTELLA +
                       r"|^\s*" + _DANCE_ESTELLA + r"\s*[.!~]*\s*$"),
    ("stand", r"일어나|일어서|일어날래|그만 앉아"),
    ("sit", r"앉아(?!서|도|야)|앉으세요|앉을래|앉으렴"),
    ("lie", r"누워|누울래|눕자|드러누워|누우렴"),
    # '춤 좀 춰 줘'·'춤 한 번 보여 줘'·'춤춰'·'춤 춰 볼래?'·'댄스 타임'·'한 곡 춰 줘' (춤과 동사 사이에 낱말 둘까지)
    #   영어·일본어·중국어의 '춤 춰'도 받는다(dance·dancing·踊って·ダンス·跳舞 …).
    ("dance", r"(춤|댄스)\s*(?:[가-힣]{1,4}\s*){0,2}?(춰|추자|추어|추세요|출래|출\s*수|춥시다|보여|해\s*줘|해\s*봐|타임|부탁)|"
              r"(한\s*곡|신나게|한번|한\s*번)\s*춰|댄스|춤\s*$|"
              r"\b(?:dance|dancing)\b|踊って|踊り|ダンス|跳舞|跳个舞|舞蹈"),
    ("heart_big", r"큰\s*하트|머리\s*위\s*하트"),
    ("heart_cheek", r"볼\s*하트"),
    ("heart_hand", r"손\s*하트|하트"),
    ("v_wink", r"윙크"),
    ("v_double", r"양손\s*브이"),
    ("v_cheek", r"브이"),
    ("clap", r"박수"),
    ("thumbs", r"엄지\s*척|엄지척|최고야|잘했어"),
    ("stretch", r"기지개"),
    ("search_start", r"찾아\s*줘|찾아\s*봐|찾아\s*주|검색|알아\s*봐|조사해|정보\s*(좀|를|좀\s*줘|알려)"),
]
_REPLY_YES = re.compile(r"^\s*(네|넵|예|그럼요|좋아요|알겠어요|알겠습니다)[\s,.!~]")
_REPLY_DO = re.compile(r"(ㄹ게요|을게요|를게요|볼게요|할게요|출게요|줄게요|일게요|울게요|날게요|설게요|겠습니다|드릴게요)[\s.!~]*$|[가-힣]게요[\s.!~]*$")
_REPLY_NO = re.compile(r"\?|못\s|못해|안\s?돼|안\s?됩|없어요|없습니다|아직|어려워|대신")
_REPLY_OK = {"stand", "sit", "lie", "dance", "heart_big", "heart_cheek", "heart_hand", "v_wink", "v_double", "v_cheek",
             "clap", "thumbs", "stretch"}
BUSY = ("생각 중", "도구 사용 중", "컴퓨터 조작 중")


_NOT_DANCE = re.compile(r"추지\s*마|춤\s*(은|좀)?\s*그만|그만\s*(춰|추)|안\s*춰|멈춰|춤\s*(이|은)\s*(뭐|무슨)|춤\s*(얘기|이야기|영상|노래|장르|학원|대회)")


def motion_for(text, names):
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        return None
    for name, pat in _MOTION_KW:
        if re.search(pat, t, re.IGNORECASE):
            if name.startswith("dance") and _NOT_DANCE.search(t):
                continue
            return name
    called = any(n and n.replace(" ", "") in t.replace(" ", "") for n in names)
    if re.search(r"안녕|반가워|반갑|하이\b|좋은 아침|굿모닝", t) and (called or len(t) <= 12):
        return "wave"
    return None


_LINES = {"dance": "네, 춰 볼게요!", "sit": "네, 앉을게요.", "lie": "네, 누울게요.", "stand": "네, 일어날게요.",
          "heart_big": "하트 크게 드릴게요!", "heart_cheek": "볼 하트 할게요!", "heart_hand": "하트 드릴게요!",
          "v_wink": "윙크 할게요!", "v_double": "양손 브이!", "v_cheek": "브이!", "clap": "짝짝짝, 박수 쳐 드릴게요!",
          "thumbs": "최고예요!", "stretch": "으쌰, 기지개 켤게요.", "wave": "안녕하세요!"}


def motion_line(text, names=()):
    """몸동작 부탁(펫)이면 그 동작에 맞는 짧은 답('네, 춰 볼게요!'), 아니면 ''. 검색 동작은 제외."""
    m = motion_for(text, names)
    return _LINES["dance" if m and m.startswith("dance") else m] if m else ""


def motion_for_reply(text):
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t or len(t) > 40 or _REPLY_NO.search(t) or not _REPLY_YES.search(t) or not _REPLY_DO.search(t):
        return None
    body = _REPLY_YES.sub("", t, count=1)
    if re.search(r"춰|출게|춤|dance|dancing|踊|ダンス|跳舞|舞", body, re.IGNORECASE):
        m0 = motion_for(body, [])                   # '제로투 출게요'처럼 춤 이름을 말했으면 그 춤
        if m0 and m0.startswith("dance"):
            return m0
        return "dance" if re.search(r"춰\s*볼게요|출게요|춰\s*드릴게요", body) else None
    m = motion_for(body, [])
    if m is None:
        for name, pat in (("sit", r"앉을게요|앉아\s*있을게요|앉겠습니다"), ("lie", r"누울게요|누워\s*있을게요|눕겠습니다"),
                          ("stand", r"일어날게요|일어설게요|일어나겠습니다")):
            if re.search(pat, body):
                return name
    return m if (m in _REPLY_OK or (m and m.startswith("dance"))) else None


def pet_call(cfg, path, body=None, timeout=3.0):
    """펫 입구에 한 번 보냄(설정 반영용: 옷 받기 동의 /packs/auto · 옷 갈아입기 /skin). → (상태 코드|None, JSON)
    펫이 꺼져 있으면 (None, {}) — 그때는 실행기가 다음에 펫을 켤 때 설정대로 켬."""
    data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
    try:
        c = http.client.HTTPConnection("127.0.0.1", int(cfg["포트"]["펫"]), timeout=timeout)
        c.request("POST", path, body=data, headers={"Content-Type": "application/json", "Host": "127.0.0.1"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return r.status, {}
    except (OSError, http.client.HTTPException):
        return None, {}


def pet_get(cfg, path, timeout=2.0):
    """펫 입구에서 읽기(GET /status 등). → (상태 코드|None, JSON). 펫이 꺼져 있으면 (None, {})."""
    try:
        c = http.client.HTTPConnection("127.0.0.1", int(cfg["포트"]["펫"]), timeout=timeout)
        c.request("GET", path, headers={"Host": "127.0.0.1"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return r.status, {}
    except (OSError, http.client.HTTPException, KeyError, TypeError, ValueError):
        return None, {}


def mode_on(cfg):
    return str((cfg.get("화면") or {}).get("얼굴") or "기본") == "펫"


_OUTFIT = {"t": 0.0, "v": None, "port": None}
_OUTFIT_LOCK = threading.Lock()


def pet_outfit(cfg, max_age=0.5, timeout=0.6):
    """펫이 지금 입은 옷 {"id", "gender", "voice"(꾸러미 pack.json 의 voice, 없으면 "")} — 옷이 없거나 펫이 꺼져 있으면 None.
    목소리 고르기(core/voice_choice.voice_for_outfit)가 문장마다 부르므로 max_age 초 동안은 기억한 값을 준다.
    펫에 못 붙으면 5초 동안 다시 묻지 않는다(말이 늦어지지 않게)."""
    try:
        port = int(cfg["포트"]["펫"])
    except (KeyError, TypeError, ValueError):
        return None
    with _OUTFIT_LOCK:
        now = time.time()
        if _OUTFIT["port"] == port and now < _OUTFIT["t"]:
            return _OUTFIT["v"]
        val, keep = None, 5.0
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
            c.request("GET", "/extras", headers={"Host": "127.0.0.1"})
            r = c.getresponse()
            raw = r.read(4 << 20)      # 동작이 많은 옷은 표가 큼(수백 KB) — 넉넉히
            c.close()
            j = json.loads(raw.decode("utf-8") or "{}") if r.status == 200 else {}
            if isinstance(j, dict) and j.get("ok"):
                keep = max_age
                if isinstance(j.get("skin"), str) and j["skin"]:
                    val = {"id": j["skin"][:40], "gender": str(j.get("gender") or "")[:10],
                           "voice": str(j.get("packVoice") or "")[:40]}
        except (OSError, ValueError, http.client.HTTPException):
            val = None
        _OUTFIT.update(t=time.time() + keep, v=val, port=port)
        return val


def forget_outfit():
    """옷을 방금 바꿨을 때(설정 저장 → 펫 /skin) 기억한 옷을 버려 다음 문장이 바로 새 옷을 보게 한다."""
    with _OUTFIT_LOCK:
        _OUTFIT["t"] = 0.0


def guess_emotion(text):
    for emo, pat in _KW:
        if re.search(pat, text or ""):
            return emo
    return "보통"


class PetFace:
    def __init__(self, cfg, names=(), log=None):
        self.cfg = cfg
        self.names = list(names)
        self.log = log or (lambda *_a, **_k: None)
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.q = []
        self.seq = 0
        self.conn = None
        self.owner = None
        self.owner_t = 0.0
        self.status = None
        self.expr = "보통"
        self.expr_until = 0.0
        self.hold = None
        self.play_end = 0.0
        self.turn_text = ""
        self.turn_no = None
        self.fail_t = 0.0
        self.sent = self.err = self.mouth_sent = 0
        self.hist = deque(maxlen=40)
        self.motion_wait = None
        self.searching = False
        self.search_spoke = False
        self.search_t = 0.0
        self.motions = deque(maxlen=20)
        self.user_t = 0.0
        self.reply_checked = True
        self.rule_motion_t = 0.0
        self._stop = False
        threading.Thread(target=self._run, name="pet-send", daemon=True).start()
        threading.Thread(target=self._refresh, name="pet-expr", daemon=True).start()

    def port(self):
        return int(self.cfg["포트"]["펫"])

    def delay(self):
        try:
            return max(0.0, min(2.0, float((self.cfg.get("화면") or {}).get("펫_입_지연_초", 0.15))))
        except (TypeError, ValueError):
            return 0.15

    def _put(self, due, path, body):
        with self.cv:
            self.seq += 1
            heapq.heappush(self.q, (due, self.seq, path, body))
            if len(self.q) > 3000:
                self.q = sorted(self.q)[-1500:]
                heapq.heapify(self.q)
            self.cv.notify()

    def _post(self, path, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        for attempt in range(2):
            try:
                if self.conn is None:
                    self.conn = http.client.HTTPConnection("127.0.0.1", self.port(), timeout=1.0)
                self.conn.request("POST", path, body=data, headers={"Content-Type": "application/json", "Host": "127.0.0.1"})
                r = self.conn.getresponse()
                r.read()
                if r.status >= 400:
                    self.err += 1
                    return r.status
                self.sent += 1
                if path == "/mouth":
                    self.mouth_sent += 1
                return r.status
            except (OSError, http.client.HTTPException):
                try:
                    self.conn.close()
                except Exception:  # noqa: BLE001
                    pass
                self.conn = None
                if attempt:
                    raise
        return None

    def _run(self):
        while not self._stop:
            with self.cv:
                while not self.q:
                    self.cv.wait()
                due, _s, path, body = self.q[0]
                wait = due - time.time()
                if wait > 0.002:
                    self.cv.wait(min(wait, 0.5))
                    continue
                heapq.heappop(self.q)
                if path == "/mouth" and wait < -0.3:
                    continue
            if time.time() < self.fail_t:
                continue
            try:
                self._post(path, body)
            except Exception:  # noqa: BLE001
                self.err += 1
                self.fail_t = time.time() + 5.0

    def _refresh(self):
        while not self._stop:
            time.sleep(3.0)
            if self.searching and time.time() - self.search_t > 180:
                self.motion("search_end")
            with self.lock:
                now = time.time()
                if self.hold and now >= self.hold[1]:
                    self.hold = None
                    name, send = self.expr, True
                else:
                    name = self.hold[0] if self.hold else self.expr
                    send = name != "보통" and now < self.expr_until
            if send:
                self._put(time.time(), "/expr", {"name": name, "seconds": EMO_HOLD})

    def set_expr(self, name, keep=60.0, delay=0.0):
        with self.lock:
            if name != self.expr:
                self.hist.append((round(time.time(), 2), name))
            self.expr = name
            self.expr_until = time.time() + keep
            if self.hold:
                return
        self._put(time.time() + delay, "/expr", {"name": name, "seconds": EMO_HOLD if name != "보통" else 2})

    def hold_expr(self, name, sec=6.0, delay=0.0):
        with self.lock:
            self.hist.append((round(time.time(), 2), name + "(잠깐)"))
            self.hold = (name, time.time() + delay + sec)
        self._put(time.time() + delay, "/expr", {"name": name, "seconds": min(30.0, sec)})

    def _own(self, st):
        now = time.time()
        if self.owner is not st and self.owner is not None and now - self.owner_t < 1.5 and getattr(self.owner, "bot_speaking", False):
            return False
        if self.owner is not st:
            self.owner = st
            self.play_end = 0.0
        self.owner_t = now
        return True

    def motion(self, name, delay=0.0):
        if name == "search_start":
            if self.searching:
                return
            self.searching, self.search_spoke, self.search_t = True, False, time.time()
        elif name == "search_end":
            if not self.searching:
                return
            self.searching = False
        elif name in ("stand", "sit", "wave") and self.searching:
            self.searching = False
        self.motions.append((round(time.time(), 2), name))
        self._put(time.time() + delay, "/motion", {"name": name})

    def on_event(self, st, kind, kw):
        if kind in ("latency", "peek", "asr", "duck", "unduck", "vad_stop", "ambient"):
            return
        if not self._own(st):
            return
        d = self.delay()
        if kind in ("user", "typed"):
            now = time.time()
            m = motion_for(kw.get("text"), self.names)
            self.user_t, self.reply_checked = now, False
            self.turn_no, self.turn_text = None, ""
            if m:
                self.motion_wait = (m, now)
                self.rule_motion_t = now
            return
        if kind == "status":
            s = kw.get("state") or ""
            self.status = s
            now = time.time()
            if s == "생각 중" and self.motion_wait and now - self.motion_wait[1] < 6.0:
                self.motion(self.motion_wait[0])
                self.motion_wait = None
            elif s == "도구 사용 중" and not self.searching:
                self.motion("search_start")
            if s == "말하는 중" and self.searching:
                self.search_spoke = True
            elif s not in ("말하는 중",) + BUSY and self.searching and self.search_spoke:
                self.motion("search_end", delay=d + 1.2)
            if s == "말하는 중":
                self._clear_mood(st)
                self.set_expr(guess_emotion(self.turn_text), keep=40.0, delay=d)
            elif s in BUSY:
                self.set_expr("생각", keep=180.0)
            else:
                self.set_expr("보통", keep=0)
        elif kind == "vad_start":
            if not st.bot_speaking and self.expr != "보통":
                self.set_expr("보통", keep=0)
        elif kind == "bot":
            text = str(kw.get("text") or "").strip()
            if not text:
                return
            if self.turn_no != st.turn_no:
                self.turn_no, self.turn_text = st.turn_no, ""
            if not self.reply_checked:
                self.reply_checked = True
                now = time.time()
                if self.rule_motion_t < self.user_t and now - self.user_t < 30:
                    rm = motion_for_reply(text)
                    if rm and not any(n == rm and now - t0 < 40 for t0, n in self.motions):
                        self.motion(rm)
            self.turn_text = (self.turn_text + " " + text).strip()[-400:]
            emo = guess_emotion(self.turn_text)
            if st.bot_speaking and emo != self.expr:
                self.set_expr(emo, keep=40.0, delay=d)
            sents = re.split(r"(?<=[.!?。…~])\s+", self.turn_text)
            show = " ".join(sents[-2:]) if len(" ".join(sents[-2:])) <= 90 else sents[-1]
            if len(show) > 90:
                show = show[:88] + "…"
            self._put(time.time() + d, "/bubble", {"text": show, "seconds": max(4.0, min(20.0, len(text) * 0.17 + 2.5))})
        elif kind == "yawn":
            self.hold_expr("졸림", 6.0, delay=d)
        elif kind == "interrupted":
            self.play_end = 0.0
            with self.cv:
                self.q = [x for x in self.q if x[2] not in ("/mouth", "/bubble")]
                heapq.heapify(self.q)
            self._put(time.time(), "/mouth", {"level": 0})
            self.set_expr("보통", keep=0)

    def _clear_mood(self, st):
        now = time.time()
        self._put(now, "/emotion", {"name": "보통"})
        self._put(now, "/talk", {"on": True})

    def on_audio(self, st, now, a, sr):
        if self.owner is not st and not self._own(st):
            return
        self.owner_t = now
        n = len(a)
        if not n or not sr:
            return
        dur = n / float(sr)
        start = max(now + self.delay(), self.play_end)
        self.play_end = start + dur
        hop = max(1, int(sr * STEP))
        for i in range(0, n, hop):
            seg = a[i:i + hop]
            rms = float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0
            level = max(0.0, min(1.0, (20.0 * np.log10(rms + 1e-6) + 48.0) / 33.0))
            self._put(start + i / float(sr), "/mouth", {"level": round(level, 3)})

    def end(self, st):
        if self.owner is st:
            self.play_end = 0.0
            self._put(time.time(), "/mouth", {"level": 0})
            self.set_expr("보통", keep=0)
            self.owner = None

    def info(self):
        return {"보냄": self.sent, "입": self.mouth_sent, "실패": self.err, "표정": self.expr,
                "표정기록": list(self.hist)[-12:], "동작기록": list(self.motions)[-8:], "검색자세": self.searching}
