# 기억 — 전부 이 PC 의 자료 폴더(설정 경로.자료, 기본 %APPDATA%\KimBiseo)에만 저장. 밖으로 보내지 않는다.
#   기억\facts.json     : 지식 [{"id","내용","만든때","출처"}] — 출처 '말'(기억해 줘)·'자동'(대화에서 저절로)·'화면'(사용자가 직접)
#   기억\diary\날짜.md  : 일기 — 대화가 끝나면 두뇌가 만든 2~4줄 요약을 날짜별로 덧붙임
#   기억\archive.jsonl  : 대화 원문 보관(한 대화가 끝날 때마다 한 줄) — '지난주에 뭐라고 했지' 찾기용
#   기억\context.json   : 마지막 대화의 최근 차례 + 요약 — 껐다 켜도 이어 가기(문맥.이어가기_시간 안이면 원문 차례도)
#   저장 전에 redact.mask 로 비밀번호·카드번호·토큰 같은 값을 가린다. 주변 대화(부르지 않은 말)는 저장하지 않는다.
#   사용자가 보기·지우기: list_facts / delete / forget / diary_list / diary_delete / clear_all (본체 HTTP 와 화면에서 씀)
import datetime
import json
import os
import re
import threading
import time

from . import i18n, redact

AMBIENT_HEAD = re.compile(r"^\[주변 대화[^\]]*\][^\n]*\n")
TIME_TAG = re.compile(r"\n?\(지금 시각: [^)]*\)\s*$")


def _today():
    return datetime.date.today()


def plain_turns(msgs, cap=400):
    """대화 메시지 → [(누가, 말)] (사용자·비서 글만, 주변 대화·시각 꼬리표는 뺌)."""
    out = []
    for m in msgs or []:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            continue
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
        if not isinstance(c, str) or not c.strip():
            continue
        c = TIME_TAG.sub("", AMBIENT_HEAD.sub("", c)).strip()
        if c:
            out.append((m["role"], c[:cap]))
    return out


_SUBJ = re.compile(r"^(?:사용자|[가-힣]{1,5}님)(?:께서는|께서|은|는|이|가|의)?")


def _words(text):
    return [w for w in re.findall(r"[0-9A-Za-z가-힣぀-ヿ一-鿿]{2,}", _SUBJ.sub("", str(text or "").strip(), count=1))]


def _covered(new, old):
    """자동 기억 겹침 — 새 사실의 낱말(조사 뗀 꼴)이 모두 옛 사실에 있으면 같은 것으로 봄.
    날짜·요일·이름처럼 한 낱말이라도 다르면 새 사실로 저장(바뀐 약속을 버리지 않게)."""
    nw, ow = _words(new), _words(old)
    if not nw or not ow:
        return False
    def stem(w):
        return w[:-1] if len(w) > 2 else w
    return all(any(o.startswith(stem(w)) or w.startswith(stem(o)) for o in ow) for w in nw)


def _fact_key(text):
    """같은 사실 찾기용 — 글자·숫자만 남기고 앞의 주어('사용자는'·'사장님은')를 뗌."""
    k = re.sub(r"[^0-9A-Za-z가-힣぀-ヿ一-鿿]", "", str(text or ""))
    return _SUBJ.sub("", k, count=1)


class Memory:
    def __init__(self, folder, max_facts=200):
        self.folder = folder
        self.diary_dir = os.path.join(folder, "diary")
        self.facts_path = os.path.join(folder, "facts.json")
        self.archive_path = os.path.join(folder, "archive.jsonl")
        self.context_path = os.path.join(folder, "context.json")
        self.max_facts = max_facts
        self._lock = threading.Lock()
        os.makedirs(self.diary_dir, exist_ok=True)
        self.facts = self._load()

    def _load(self):
        try:
            with open(self.facts_path, encoding="utf-8") as f:
                d = json.load(f)
            return [x for x in d.get("facts", []) if isinstance(x, dict) and x.get("내용")]
        except (OSError, ValueError):
            return []

    def _write_json(self, path, obj):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    def _save(self):
        self._write_json(self.facts_path, {"설명": "비서가 기억하는 사용자 정보. 화면 '기억'에서 보고 지울 수 있음. 비밀값은 가려서 저장.",
                                           "facts": self.facts})

    # ---------------- 지식
    def add(self, text, source="말"):
        raw = re.sub(r"\s+", " ", str(text or "")).strip()[:300]
        if len(raw) < 2:
            return {"오류": "기억할 내용이 비어 있어요."}
        masked = redact.mask(raw)
        key = _fact_key(masked)
        with self._lock:
            for f in self.facts:
                if _fact_key(f["내용"]) == key or (source == "자동" and _covered(masked, f["내용"])):
                    return {"이미있음": True, "내용": f["내용"]}
            fid = "m" + str(int(time.time() * 1000))[-9:] + str(len(self.facts) % 10)
            self.facts.append({"id": fid, "내용": masked, "만든때": time.strftime("%Y-%m-%d %H:%M"), "출처": source})
            self.facts = self.facts[-self.max_facts:]
            self._save()
        out = {"저장": True, "id": fid, "내용": masked}
        if masked != raw:
            out["가림"] = "비밀번호·카드번호 같은 값은 가리고 저장했어요."
        return out

    def list_facts(self):
        return list(self.facts)

    def find(self, query):
        ws = [w for w in re.findall(r"[0-9A-Za-z가-힣぀-ヿ一-鿿]{2,}", str(query or ""))
              if w not in ("기억", "잊어", "지워", "그거", "내용", "기억해", "잊어줘")]
        if not ws:
            return []
        scored = []
        for f in self.facts:
            n = sum(1 for w in ws if w in f["내용"] or (len(w) > 2 and w[:-1] in f["내용"]))
            if n:
                scored.append((n, f))
        scored.sort(key=lambda x: -x[0])
        if not scored:
            return []
        best = scored[0][0]
        return [f for n, f in scored if n == best]

    def delete(self, fid):
        with self._lock:
            n = len(self.facts)
            self.facts = [f for f in self.facts if f["id"] != fid]
            if len(self.facts) != n:
                self._save()
                return True
        return False

    def forget(self, query, all_matches=False):
        hits = self.find(query)
        if not hits:
            return {"못찾음": True, "안내": "그런 기억은 없어요."}
        if len(hits) > 1 and not all_matches:
            return {"여럿": [h["내용"] for h in hits[:5]], "안내": "여러 개가 맞아요. 어느 것을 잊을지 물어보세요(전부면 all=true)."}
        for h in hits:
            self.delete(h["id"])
        return {"지움": [h["내용"] for h in hits]}

    def prompt_block(self, honor="사용자", n=40, lang=None):
        if not self.facts:
            return ""
        lines = [f"- {f['내용']}" for f in self.facts[-n:]]
        if i18n.norm(lang or i18n.current()) != "ko":
            return (f"Things remembered about {honor} (use naturally only when relevant; do not list them unless asked):\n"
                    + "\n".join(lines))
        return (f"{honor}에 대해 기억하는 것(관련 있을 때만 자연스럽게 쓰고, 묻지 않으면 늘어놓지 않는다):\n" + "\n".join(lines))

    # ---------------- 자동 기억(대화에서 저절로)
    AUTO_PROMPT = ("다음은 음성 비서와 사용자의 대화입니다. 사용자에 대해 나중에도 쓸모 있는 오래가는 사실만 골라 JSON 으로만 답하세요.\n"
                   "고를 것: 사용자 이름·부르는 말(호칭) 바람, 좋아하는 것·싫어하는 것, 가족·반려동물, 사는 곳·일하는 곳, 약속·일정, 계속 지킬 부탁.\n"
                   "고르지 말 것: 날씨·검색 결과·잡담·한 번 묻고 끝난 질문, 비서가 한 말, 이미 아는 사실 목록에 있는 것, "
                   "비밀번호·카드번호·계좌·주민번호 같은 값.\n"
                   "각 사실은 '사용자는 ~' 꼴의 짧은 한국어 한 문장. 없으면 빈 목록.\n"
                   "형식: {\"facts\": [\"...\", \"...\"]}  (최대 5개)")
    AUTO_PROMPT_EN = ("Below is a conversation between a voice assistant and the user. Pick only long-lasting facts about the user that will be useful later, "
                      "and answer only in JSON.\n"
                      "Pick: the user's name or preferred form of address, likes and dislikes, family and pets, where they live or work, "
                      "appointments and schedules, standing requests.\n"
                      "Do not pick: weather or search results, small talk, one-off questions, things the assistant said, facts already in the known "
                      "list, or secrets such as passwords, card numbers, account numbers, or national ID numbers.\n"
                      "Write each fact as one short sentence in {language}. If there are none, an empty list.\n"
                      "Format: {\"facts\": [\"...\", \"...\"]}  (up to 5)")

    def auto_request(self, msgs, honor="사용자"):
        """자동 기억 요청 메시지(두뇌에 보낼 것). 사용자 말이 없으면 None."""
        turns = plain_turns(msgs)
        if sum(1 for r, _ in turns if r == "user") < 1:
            return None
        code = i18n.current()
        known = "\n".join(f"- {f['내용']}" for f in self.facts[-40:]) or ("(없음)" if code == "ko" else "(none)")
        if code == "ko":
            lines = "\n".join(("사용자: " if r == "user" else "비서: ") + c for r, c in turns[-30:])
            return [{"role": "system", "content": self.AUTO_PROMPT},   # 사실은 늘 '사용자는 ~' 꼴(호칭을 넣으면 '사장님는'처럼 조사가 틀림)
                    {"role": "user", "content": f"[이미 아는 사실]\n{known}\n\n[대화]\n{lines}"}]
        lines = "\n".join(("User: " if r == "user" else "Assistant: ") + c for r, c in turns[-30:])
        return [{"role": "system", "content": self.AUTO_PROMPT_EN.replace("{language}", i18n.en_name(code))},
                {"role": "user", "content": f"[Known facts]\n{known}\n\n[Conversation]\n{lines}"}]

    def auto_apply(self, reply):
        """두뇌 답(JSON) → 지식에 더함(출처 '자동'). 더한 것 목록."""
        m = re.search(r"\{.*\}", str(reply or ""), re.S)
        if not m:
            return []
        try:
            facts = json.loads(m.group(0)).get("facts") or []
        except (ValueError, AttributeError):
            return []
        added = []
        for x in facts[:5]:
            if not isinstance(x, str) or len(x.strip()) < 4 or redact.has_secret(x):
                continue
            r = self.add(x, source="자동")
            if r.get("저장"):
                added.append(r["내용"])
        return added

    # ---------------- 일기
    def diary_path(self, day):
        return os.path.join(self.diary_dir, f"{day}.md")

    DIARY_PROMPT = ("다음은 음성 비서와 사용자의 대화입니다. 나중에 다시 볼 일기로 한국어 2~4줄로 요약하세요. "
                    "무엇을 묻고 무엇을 했는지·정한 것·할 일 위주로. 비밀번호·카드번호 같은 값은 쓰지 마세요. 줄마다 '- '로 시작.")
    DIARY_PROMPT_EN = ("Below is a conversation between a voice assistant and the user. Summarize it in 2-4 lines as a diary to read later, "
                       "in {language}. Focus on what was asked, what was done, decisions, and to-dos. Do not write passwords, card numbers, "
                       "or similar values. Start each line with '- '.")

    def diary_request(self, msgs):
        turns = plain_turns(msgs)
        if sum(1 for r, _ in turns if r == "user") < 1 or len(turns) < 2:
            return None
        code = i18n.current()
        if code == "ko":
            lines = "\n".join(("사용자: " if r == "user" else "비서: ") + c for r, c in turns[-40:])
            return [{"role": "system", "content": self.DIARY_PROMPT}, {"role": "user", "content": lines}]
        lines = "\n".join(("User: " if r == "user" else "Assistant: ") + c for r, c in turns[-40:])
        return [{"role": "system", "content": self.DIARY_PROMPT_EN.replace("{language}", i18n.en_name(code))},
                {"role": "user", "content": lines}]

    def diary_add(self, summary, when=None):
        s = redact.mask(str(summary or "").strip())
        if not s:
            return False
        d = datetime.datetime.fromtimestamp(when or time.time())
        p = self.diary_path(d.strftime("%Y-%m-%d"))
        with self._lock:
            new = not os.path.exists(p)
            with open(p, "a", encoding="utf-8") as f:
                if new:
                    if i18n.current() == "ko":
                        f.write(f"# {d.year}년 {d.month}월 {d.day}일 대화 일기\n")
                    else:
                        f.write(f"# Diary for {d.year}-{d.month:02d}-{d.day:02d}\n")
                f.write(f"\n## {d.strftime('%H:%M')}\n{s}\n")
        return True

    def diary_list(self, days=14):
        out = []
        try:
            names = sorted((x for x in os.listdir(self.diary_dir) if re.match(r"\d{4}-\d{2}-\d{2}\.md$", x)), reverse=True)
        except OSError:
            names = []
        for x in names[:days]:
            try:
                with open(os.path.join(self.diary_dir, x), encoding="utf-8") as f:
                    out.append({"날짜": x[:-3], "내용": f.read()[-6000:]})
            except OSError:
                pass
        return out

    def diary_delete(self, day):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(day or "")):
            return False
        try:
            os.remove(self.diary_path(day))
            return True
        except OSError:
            return False

    # ---------------- 대화 원문 보관 · 찾기
    def archive_append(self, msgs, sid=""):
        turns = plain_turns(msgs, cap=800)
        if not turns:
            return False
        rec = {"시각": time.strftime("%Y-%m-%d %H:%M:%S"), "세션": sid,
               "turns": [[r, redact.mask(c)] for r, c in turns]}
        with self._lock, open(self.archive_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True

    @staticmethod
    def day_range(when):
        """'오늘'·'어제'·'그제'·'지난주'·'이번 주'·'3일 전'·'YYYY-MM-DD' → (시작 날짜, 끝 날짜) 또는 None."""
        t = _today()
        w = re.sub(r"\s+", "", str(when or ""))
        if not w:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", w):
            d = datetime.date.fromisoformat(w)
            return d, d
        rel = {"오늘": 0, "어제": 1, "그제": 2, "그저께": 2, "엊그제": 2,
               "today": 0, "yesterday": 1, "daybeforeyesterday": 2, "thedaybeforeyesterday": 2,
               "今日": 0, "きょう": 0, "昨日": 1, "きのう": 1, "一昨日": 2, "おととい": 2,
               "今天": 0, "昨天": 1, "前天": 2}   # 0.1.18 다국어
        if w in rel:
            d = t - datetime.timedelta(days=rel[w])
            return d, d
        m = re.fullmatch(r"(\d+)\s*(?:일전|days?ago)", w)
        if m:
            d = t - datetime.timedelta(days=int(m.group(1)))
            return d, d
        monday = t - datetime.timedelta(days=t.weekday())
        if w in ("이번주", "금주", "thisweek", "今週", "本周"):
            return monday, t
        if w in ("지난주", "저번주", "lastweek", "先週", "上周"):
            return monday - datetime.timedelta(days=7), monday - datetime.timedelta(days=1)
        if w in ("이번달", "thismonth", "今月", "本月"):
            return t.replace(day=1), t
        if w in ("지난달", "저번달", "lastmonth", "先月", "上月"):
            last = t.replace(day=1) - datetime.timedelta(days=1)
            return last.replace(day=1), last
        return None

    def search_archive(self, query=None, when=None, limit=6, cap=300):
        """원문 보관에서 찾기 — 낱말이 모두 든 말(최근 것부터), when 이면 그 날짜 범위 안만. [{시각, 누가, 말}]"""
        ws = [w for w in re.findall(r"[0-9A-Za-z가-힣぀-ヿ一-鿿]{2,}", str(query or ""))
              if w not in ("뭐라고", "했지", "했었지", "말했지", "얘기", "대화", "지난주", "어제", "오늘")][:4]
        rng = self.day_range(when) if when else None
        if not os.path.isfile(self.archive_path) or (not ws and not rng):
            return []
        try:
            with open(self.archive_path, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            return []
        out = []
        for ln in reversed(lines[-2000:]):
            try:
                d = json.loads(ln)
                day = datetime.date.fromisoformat(str(d.get("시각", ""))[:10])
            except (ValueError, TypeError):
                continue
            if rng and not (rng[0] <= day <= rng[1]):
                continue
            for r, c in reversed(d.get("turns") or []):
                if ws and not all(w in c or (len(w) > 2 and w[:-1] in c) for w in ws):
                    continue
                out.append({"시각": d.get("시각"), "누가": "사용자" if r == "user" else "비서", "말": c[:cap]})
                if len(out) >= limit:
                    return out
        return out

    def recall(self, query=None, day=None):
        """두뇌용 찾기: 지식 + 일기 + 대화 원문. day = 'YYYY-MM-DD'·'어제'·'지난주' 등."""
        res = {}
        rng = self.day_range(day) if day else None
        if rng:
            ds = []
            d = rng[0]
            while d <= rng[1] and len(ds) < 8:
                p = self.diary_path(d.isoformat())
                if os.path.isfile(p):
                    with open(p, encoding="utf-8") as f:
                        ds.append({"날짜": d.isoformat(), "내용": f.read()[-1500:]})
                d += datetime.timedelta(days=1)
            res["일기"] = ds or "그때 일기가 없어요."
        if query:
            res["지식"] = [f["내용"] for f in self.find(query)][:8]
            ws = [w for w in re.findall(r"[0-9A-Za-z가-힣぀-ヿ一-鿿]{2,}", str(query))][:4]
            hits = []
            for e in self.diary_list(60):
                for blk in e["내용"].split("\n## ")[1:]:
                    if ws and all(w in blk for w in ws):
                        hits.append({"날짜": e["날짜"], "내용": blk[:500]})
            if hits:
                res["일기_찾음"] = hits[:5]
        if query or rng:
            said = self.search_archive(query, day)
            if said:
                res["대화_원문"] = said
        if not any(res.get(k) for k in ("지식", "일기_찾음", "대화_원문")) and not rng:
            res["지식"] = [f["내용"] for f in self.facts[-20:]]
            res["최근일기"] = [{"날짜": e["날짜"], "내용": e["내용"][-800:]} for e in self.diary_list(3)]
        return res

    # ---------------- 껐다 켜도 이어 가기
    def save_context(self, msgs, summary="", keep_turns=6):
        """최근 사용자 차례 keep_turns 개(와 그 뒤 비서 답·도구 결과)와 요약을 저장 — 비밀값 가림."""
        msgs = [m for m in (msgs or []) if isinstance(m, dict) and m.get("role") in ("user", "assistant", "tool")]
        users = [i for i, m in enumerate(msgs) if m.get("role") == "user"]
        cut = users[-keep_turns] if len(users) > keep_turns else (users[0] if users else len(msgs))
        keep = []
        for m in msgs[cut:]:
            m2 = dict(m)
            if isinstance(m2.get("content"), str):
                m2["content"] = redact.mask(AMBIENT_HEAD.sub("", m2["content"]))
            keep.append(m2)
        self._write_json(self.context_path, {"갱신": time.time(), "갱신시각": time.strftime("%Y-%m-%d %H:%M:%S"),
                                             "요약": redact.mask(summary or ""), "messages": keep})

    def load_context(self, hours=6.0):
        """→ (원문 메시지 목록, 요약). hours 가 지난 대화면 원문은 비우고 요약만."""
        try:
            with open(self.context_path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return [], ""
        msgs = d.get("messages") or []
        if time.time() - float(d.get("갱신") or 0) > hours * 3600:
            msgs = []
        while msgs and msgs[0].get("role") != "user":   # 도구 결과가 앞에 남지 않게
            msgs = msgs[1:]
        return msgs, str(d.get("요약") or "")

    def clear_context(self):
        try:
            os.remove(self.context_path)
        except OSError:
            pass

    def clear_all(self):
        """사용자가 '기억 전부 지우기' — 지식·일기·원문 보관·이어가기 전부."""
        with self._lock:
            self.facts = []
            self._save()
            for x in os.listdir(self.diary_dir):
                if x.endswith(".md"):
                    try:
                        os.remove(os.path.join(self.diary_dir, x))
                    except OSError:
                        pass
            for p in (self.archive_path, self.context_path):
                try:
                    os.remove(p)
                except OSError:
                    pass
