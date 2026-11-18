# 김비서 설치 본체 — 설치 창(install.ps1)이 부른다. 파이썬 표준 라이브러리만(설치 때 막 받은 파이썬으로 돎).
#   python setup_core.py install --prefix <프로그램 폴더> --data <자료 폴더> --status <상태 파일> [--source <소스 폴더>]
#                                [--local-brain] [--desktop-dir 폴더] [--startmenu-dir 폴더] [--reg-key KimBiseo]
#                                [--display-name 김비서] [--packs-catalog 주소] [--no-shortcuts] [--no-register]
#   python setup_core.py plan [--prefix …] [--local-brain]      구성만 보기(JSON)
#   python setup_core.py gemma-install --prefix … --data … --status <상태 파일> [--gemma E4B|E2B]   설정 '두뇌 바꾸기 → Gemma 설치·다시 설치'
#       (두뇌 프로그램 llama.cpp + 고른 Gemma 4 무검열 판(E4B 기본 약 5.3GB · E2B 약 3.4GB)만 받음. 다 받으면 다른 Gemma 폴더는 지워 공간을 돌려줌)
#   install 에도 --gemma E2B 를 주면 이 PC 두뇌를 작은 판으로 받음(기본 E4B)
#   python setup_core.py gemma-remove --prefix … --data …     Gemma·두뇌 프로그램 지우기(지운 크기 JSON 으로)
#   python setup_core.py pet-install --prefix … --data … --status <상태 파일> [--file <받아 둔 electron zip>]
#       펫 실행 틀(Electron)만 다시 설치 — 설치 창의 '펫 다시 받기'·'직접 넣기', 김비서 설정 → 펫 의 같은 단추가 부름.
#       --file 은 사용자가 브라우저로 직접 받은 압축 파일(크기·sha256 이 목록과 같아야 씀).
#   python setup_core.py interp-install --prefix … --data … --status <상태 파일>
#       통역 원어민 목소리(선택) — 김비서 설정 → 통역 '통역 목소리 받기'가 부름. runtime\python-interp(locks/interp.json: Kokoro·Piper, CPU)
#       + 목소리 모델(installer/interp/models.json — models.json 과 따로(업데이트 DEPS 에 안 걸리게): Kokoro-82M · Piper 독일어·그리스어·러시아어·터키어 · 태국어 MrJMThaiTTS+FastThaiG2P, 약 770MB). Piper(GPL-3.0)는
#       사용자 PC 가 PyPI 에서 직접 받아 따로 도는 프로그램(voice/interp_voice.py)에서만 씀 — 우리는 다시 나눠 주지 않음.
#   python setup_core.py voiceprint-install --prefix … --data … --status <상태 파일>
#       내 목소리 확인 모델(선택, models.json 의 titanet-small 약 40MB) — 김비서 설정 → 내 목소리 '확인 모델 받기'가 부름.
# 0.1.4~ 두뇌: 이 PC 에 클로드 코드·Codex 로그인이 있으면 Gemma 를 받지 않음(plan.py). 업데이트(덮어 설치) 때
#   이미 있는 Gemma·두뇌 프로그램은 지우지 않고, 설정의 두뇌 경로는 디스크에 실제 있는 파일로 맞춘다.
#
# 차례(이미 된 것은 건너뜀 — '다시 하기'를 누르면 멈춘 곳부터):
#   python(설치 창이 먼저 함) → 사양 확인 → 프로그램 파일 → 파이썬 부품(본체·음성) → 두뇌 프로그램 → 모델 → 펫 → 바탕화면 아이콘·마무리
# 받는 것은 모두 공식 배포처(파이썬 = python.org, 부품 = PyPI·PyTorch, llama.cpp·Electron = GitHub 릴리스, 모델 = 허깅페이스)에서
# 사용자 PC 가 직접 받고, 판 고정 + sha256 으로 확인한다(runtimes.json · locks/*.json · models.json). 우리는 아무것도 다시 나눠 주지 않는다.
# 상태 파일(JSON)은 설치 창이 0.5초마다 읽어 화면에 보여 줌. 기록은 <자료>\logs\install.log.
# 0.1.12~ 받기 실패에 강하게(사용자 보고: '펫' 단계에서 받기가 멈춰 설치가 끝나지 않음)
#   - 받기: 조금이라도 받아지면 계속 이어 받고, 파이썬으로 안 되면 윈도우 내려받기(curl.exe → 파워셸)로 대신 받음(get_models.download).
#     받은 파일이 원본과 다르면(sha256) 한 번은 저절로 새로 받음. 실패하면 원인(인증서·주소 못 찾음·막힘·끊김·거절 …)을 쉬운 말로 알림.
#   - '펫' 단계는 실패해도 설치를 끝냄(OPTIONAL) — 김비서(대화)는 먼저 쓰고, 펫은 나중에 '펫 다시 받기'·'직접 넣기'로.
#   - 멈춘 것처럼 보이지 않게: 2초마다 상태 파일을 새로 쓰고(경과_초·조용_초), 큰 부품을 디스크에 푸는 동안 풀린 양을 3초마다 보여 줌.
#     상태 파일의 "주의" 에 무엇이 빠졌는지·직접 받을 주소·넣을 곳을 적어 설치 창이 보여 줌.
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, SRC_ROOT)      # 이 꾸러미의 app(사전 포함)을 먼저 보게(설치된 옛 src 를 보지 않게)
import get_models as GM  # noqa: E402
import plan as PLAN  # noqa: E402

# 설치 화면 언어(0.1.18~) — 사전은 app/i18n/<언어>.json(본체와 같은 파일). 한국어면 그대로.
try:
    from app.core import i18n as I18N  # noqa: E402
except Exception:  # noqa: BLE001  (사전 파일이 없는 옛 꾸러미에서도 설치는 되게)
    I18N = None
LANG = "ko"


def set_lang(code):
    global LANG
    LANG = (I18N.norm(code) if I18N else "ko") or "ko"
    if I18N:
        I18N.set_lang(LANG)
    return LANG


def L(text):
    """사용자에게 보이는 한국어 글 → 고른 언어 글(사전·틀 대조). 없으면 한국어 그대로."""
    s = str(text)
    if LANG == "ko" or not I18N:
        return s
    try:
        return I18N.lookup(s, LANG)
    except Exception:  # noqa: BLE001
        return s


def T(text, *a):
    """사전 열쇠(한국어 틀)를 고른 언어로 바꾸고 {0}·{1} 자리를 채운다 — 조각을 이어 붙이는 진행 글용."""
    s = L(text)
    if a:
        try:
            s = s.format(*a)
        except (IndexError, KeyError, ValueError):
            pass
    return s

def _read_version():
    import re
    try:
        with open(os.path.join(SRC_ROOT, "app", "version.py"), encoding="utf-8") as f:
            return re.search(r'^VERSION\s*=\s*"([0-9.]+)"', f.read(), re.M).group(1)
    except (OSError, AttributeError):
        return "0.0.0"


VERSION = _read_version()   # 판 번호는 app/version.py 한 곳
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STEPS = [("python", "파이썬 준비"), ("plan", "이 PC 사양 확인"), ("files", "프로그램 파일"), ("packages", "파이썬 부품"),
         ("brain", "두뇌 프로그램"), ("models", "모델(두뇌·귀·목소리)"), ("pet", "펫"), ("finish", "바탕화면 아이콘·마무리")]
WEIGHT = {"python": 2, "plan": 1, "files": 1, "packages": 30, "brain": 6, "models": 45, "pet": 8, "finish": 2}
COPY_ITEMS = ["app", "voice", "pet", "installer", "brain", "assets", "LICENSE", "NOTICE", "README.md", "ASSETS-LICENSE.md", "PRIVACY.md",
              "SECURITY.md", "THIRD_PARTY_LICENSES"]
SKIP_NAMES = {"__pycache__", ".git", "node_modules", ".pytest_cache"}
OPTIONAL = {"pet"}        # 실패해도 설치를 끝내는 단계(나중에 그 단계만 다시 할 수 있음)


class Fail(Exception):
    """사용자에게 보여 줄 쉬운 이유가 있는 실패."""

    def __init__(self, why, detail="", **info):
        super().__init__(why)
        self.why = why
        self.detail = detail
        self.info = info          # 받기 실패면 {"원인", "주소", "파일", "넣을곳", "크기"} — 설치 창이 '직접 받기' 안내에 씀


# ---------------------------------------------------------------- 상태·기록
class Status:
    def __init__(self, path, log_path):
        self.path = path
        self.log_path = log_path
        self.d = None
        try:
            with open(path, encoding="utf-8-sig") as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            pass
        if not isinstance(self.d, dict) or [s.get("id") for s in self.d.get("단계", [])] != [s[0] for s in STEPS]:
            self.d = {"단계": [{"id": i, "이름": n, "상태": "기다림", "글": ""} for i, n in STEPS]}
        for _s in self.d.get("단계") or []:          # 단계 이름은 고른 언어로(상태 값 '기다림'·'됨'은 설치 창이 쓰는 열쇠라 그대로)
            _s["이름"] = L(dict(STEPS).get(_s.get("id"), _s.get("이름") or ""))
        self.d.update({"끝": False, "성공": False, "오류": None, "지금": "", "글": "", "진행": 0, "전체": 0, "주의": []})
        self.cur = None
        self._last = 0
        self.t0 = time.time()           # 설치 시작(지난 시간 표시)
        self.step_t0 = time.time()      # 지금 단계 시작
        self.alive_t = time.time()      # 마지막으로 '진짜 진전'이 있던 때(받은 양이 늘었거나 다음 일로 넘어감)
        self._beat = None
        self._lock = threading.Lock()
        self.d.update({"시각": "", "경과_초": 0, "단계_경과_초": 0, "조용_초": 0})

    def heartbeat(self, on=True):
        """2초마다 상태 파일을 새로 씀(지난 시간 · '조용_초' = 진전이 없던 시간). 설치 창은 '조용_초'가 길어지면
        '멈췄을 수 있어요' 안내를 띄운다 — 일꾼이 살아만 있고 일이 안 나가는 경우와, 오래 걸리지만 나아가는 경우를 가름."""
        if not on:
            self._beat = None
            return
        if self._beat is not None:
            return
        me = self._beat = object()

        def run():
            while self._beat is me and not self.d.get("끝"):
                time.sleep(2.0)
                try:
                    self.write(force=True)
                except Exception:  # noqa: BLE001  (다른 줄이 상태를 고치는 순간과 겹치면 다음 번에)
                    pass
        threading.Thread(target=run, name="status-beat", daemon=True).start()

    def touch(self):
        """진짜 진전이 있었음."""
        self.alive_t = time.time()

    def log(self, *a):
        line = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        try:
            print(line, flush=True)
        except (OSError, ValueError):
            pass

    def step(self, sid):
        return next(s for s in self.d["단계"] if s["id"] == sid)

    def begin(self, sid):
        self.cur = sid
        st = self.step(sid)
        st["상태"], st["글"] = "하는 중", ""
        self.d["지금"] = sid
        self.d["진행"] = 0
        self.step_t0 = time.time()
        self.touch()
        self.log(f"==== {st['이름']}")
        self.write(force=True)

    def end(self, sid, state="됨", text=""):
        st = self.step(sid)
        st["상태"], st["글"] = state, L(text)
        self.d["진행"] = 100
        self.touch()
        self.log(f"---- {st['이름']}: {state} {text}")
        self.write(force=True)

    def progress(self, frac, text="", alive=True):
        """alive=False = 글만 고침(지난 시간 표시처럼 진전이 아닌 것) — '조용_초'를 되돌리지 않음."""
        self.d["진행"] = max(0, min(100, round(frac * 100, 1)))
        if text:
            self.d["글"] = L(text)
        if alive:
            self.touch()
        self.write()

    def say(self, text):
        self.d["글"] = L(text)
        self.touch()
        self.log("  " + text)
        self.write()

    def total(self):
        done = sum(WEIGHT[s["id"]] for s in self.d["단계"] if s["상태"] in ("됨", "건너뜀"))
        cur = WEIGHT.get(self.cur, 0) * self.d.get("진행", 0) / 100 if self.cur and self.step(self.cur)["상태"] == "하는 중" else 0
        return round(100 * (done + cur) / sum(WEIGHT.values()), 1)

    def write(self, force=False):
        if not force and time.time() - self._last < 0.4:
            return
        self._last = time.time()
        with self._lock:              # 살아 있음 표시 줄과 일하는 줄이 같은 임시 파일을 동시에 쓰지 않게
            now = time.time()
            self.d["전체"] = self.total()
            self.d["시각"] = time.strftime("%H:%M:%S")
            self.d["경과_초"] = int(now - self.t0)
            self.d["단계_경과_초"] = int(now - self.step_t0)
            self.d["조용_초"] = 0 if self.d.get("끝") else int(now - self.alive_t)
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.d, f, ensure_ascii=False, indent=0)
                for _ in range(20):   # 설치 창이 읽는 중이면 잠깐 기다렸다가
                    try:
                        os.replace(tmp, self.path)
                        break
                    except PermissionError:
                        time.sleep(0.05)
            except OSError:
                pass


def human(n):
    return GM.human(n)


def took(sec):
    """지난 시간 글: 45초 · 3분 20초 · 1시간 5분."""
    sec = int(sec)
    if sec < 60:
        return T('{0}초', sec)
    if sec < 3600:
        return T('{0}분 {1}초', sec // 60, sec % 60)
    return T('{0}시간 {1}분', sec // 3600, sec % 3600 // 60)


# 받기 실패 까닭 한 줄(설치 창의 '까닭:' 줄) — 받기 원인은 get_models.WHY, 그 밖은 여기
SHORT_WHY = {"hash": "받은 파일이 원본과 달라요(백신이나 회사 인터넷이 파일을 바꾸는 것 같아요).",
             "disk": "디스크 공간이 모자라요.", "file": "파일을 저장하거나 풀지 못했어요(백신이 막았을 수 있어요)."}


def short_why(kind, why=""):
    if kind in SHORT_WHY:
        return SHORT_WHY[kind]
    if kind in GM.WHY:
        return GM.WHY[kind]
    return (str(why).split(". ")[0].rstrip(".") + ".") if why else ""


def unpacked_size(files):
    """받은 부품(.whl = zip)들이 디스크에 풀리면 차지할 크기(바이트) — 설치 진행 막대의 분모. 못 읽는 파일은 받은 크기의 2배로 어림."""
    total = 0
    for f in files:
        try:
            with zipfile.ZipFile(f) as z:
                total += sum(i.file_size for i in z.infolist())
        except (OSError, zipfile.BadZipFile):
            try:
                total += os.path.getsize(f) * 2
            except OSError:
                pass
    return total


def tree_size(path):
    """폴더 크기(바이트) — 부품을 설치하는 동안 얼마나 풀렸는지 보려고. 못 읽는 파일은 건너뜀."""
    total = 0
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def sha256_of(path, progress=None):
    return GM.file_hashes(path, progress=progress)[0]


# ---------------------------------------------------------------- 받기 공통
def head(url, hosts):
    """시험(--dry-run): 받지 않고 크기만 물음(넘겨주기도 허용 호스트만). → (최종 주소, 크기|None)"""
    import urllib.request
    opener = GM.make_opener(hosts)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": GM.UA})
    with opener.open(req, timeout=30) as r:
        n = r.headers.get("X-Linked-Size") or r.headers.get("Content-Length") or ""
        return r.geturl(), (int(n) if n.isdigit() else None)


class Fetcher:
    def __init__(self, st, hosts, dry=False):
        self.st = st
        self.hosts = tuple(hosts)
        self.dry = dry
        self.checked = []

    def get(self, url, dest, sha256, size=None, label="", frac=(0.0, 1.0)):
        """dest 가 이미 맞으면 건너뜀. 아니면 받고(이어 받기·다시 시도) sha256 확인. 틀리면 지우고 Fail."""
        a, b = frac
        name = label or os.path.basename(dest)
        if self.dry:
            if not GM.host_ok(url, self.hosts):
                raise Fail(f"{name}: 허용하지 않은 주소", url)
            if not (isinstance(sha256, str) and len(sha256) == 64):
                raise Fail(f"{name}: sha256 이 없어요", url)
            try:
                final, n = head(url, self.hosts)
            except Exception as ex:  # noqa: BLE001
                raise Fail(f"{name}: 주소 확인 실패", f"{url} {ex}") from None
            if size is not None and n is not None and n != size:
                raise Fail(f"{name}: 크기가 목록과 달라요({n} ≠ {size})", url)
            self.checked.append({"이름": name, "주소": url, "크기": n, "목록_크기": size})
            self.st.progress(b, f"[시험] {name} 주소 확인 {human(n or 0)}")
            return dest
        if os.path.isfile(dest) and (size is None or os.path.getsize(dest) == size):
            if sha256_of(dest) == sha256:
                self.st.progress(b, f"{name} — 있음(확인됨)")
                return dest
            os.remove(dest)
        info = {"주소": url, "파일": os.path.basename(dest), "넣을곳": os.path.dirname(dest), "크기": size}
        self.need_space(dest, size, name)

        def prog(done, total, rate):
            t = total or size or 0
            f = (done / t) if t else 0
            msg = T('{0} 받는 중 {1} / {2}', L(name), human(done), human(t))
            if rate:
                msg += " " + T('· {0}/초', human(rate))
            if rate and t and t > done:
                msg += " " + T('· 남은 시간 약 {0}', eta(t - done, rate))
            self.st.progress(a + (b - a) * f, msg)
        for round_ in (1, 2):
            try:
                GM.download(url, dest, size, say=lambda m: self.st.log(m), progress=prog, hosts=self.hosts, native=True)
            except GM.DownloadError as ex:
                raise Fail(f"{name} 을(를) 받지 못했어요. {ex.why}", str(ex), 원인=ex.kind, 방식=ex.tried, **info) from None
            except RuntimeError as ex:
                raise Fail(f"{name} 을(를) 받지 못했어요. 인터넷 연결에 문제가 있어요.", str(ex),
                           원인="net", **info) from None
            self.st.progress(b, T('{0} 확인 중(원본과 같은지)', L(name)))
            got = sha256_of(dest)
            if got == sha256:
                return dest
            try:                                   # 원본과 다름(받다 깨짐·중간에서 바뀜) → 지우고 한 번은 저절로 새로 받음
                os.remove(dest)
            except OSError:
                pass
            self.st.log(f"  {name}: 받은 파일이 원본과 다름(sha256 {got[:16]}… ≠ {sha256[:16]}…)" + (" → 새로 받음" if round_ == 1 else ""))
        raise Fail(f"받은 {name} 이(가) 두 번 다 원본과 달라요. 백신이나 회사 인터넷이 받는 파일을 바꾸는 것 같아요. "
                   "다른 인터넷(휴대폰 핫스팟 등)으로 바꿔서 다시 해 보거나, 브라우저로 직접 받아 넣어 주세요.",
                   f"sha256 {got} ≠ {sha256}", 원인="hash", **info)

    def need_space(self, dest, size, name):
        """받을 자리 확인 — 모자라면 받기 전에 쉬운 말로 멈춤(받다가 꽉 차서 깨진 파일이 남지 않게). 이미 받은 만큼(.part)은 뺌."""
        if not size:
            return
        folder = os.path.dirname(dest)
        try:
            os.makedirs(folder, exist_ok=True)
            free = shutil.disk_usage(folder).free
        except OSError:
            return
        try:
            have = os.path.getsize(dest + ".part")
        except OSError:
            have = 0
        need = int(size * 1.05) + 64 * 1024 * 1024 - have
        if free < need:
            raise Fail(f"{name} 을(를) 받을 디스크 공간이 모자라요. {human(need)} 가 필요한데 {human(free)} 남았어요. 공간을 비우고 '다시 하기'를 눌러 주세요.",
                       f"free {free} < need {need} @ {folder}", 원인="disk")

    def take_file(self, src, dest, sha256, size, name):
        """사용자가 직접 받아 둔 파일(src)을 확인해서 받는 자리(dest)에 둔다. 크기·sha256 이 목록과 같아야 함."""
        if not os.path.isfile(src):
            raise Fail("고른 파일을 찾을 수 없어요.", src, 원인="file")
        n = os.path.getsize(src)
        if size and n != size:
            raise Fail(f"고른 파일이 {name} 이(가) 아니에요(크기가 달라요 — {human(n)}, 받아야 할 파일은 {human(size)}). "
                       "받다가 끊긴 파일일 수 있으니 다시 받아 주세요.", f"{src} size {n} ≠ {size}", 원인="hash")
        self.st.progress(0.2, T('{0}: 고른 파일을 확인하는 중', L(name)))
        got = sha256_of(src)
        if got != sha256:
            raise Fail(f"고른 파일이 {name} 원본과 달라요. '직접 넣기'의 ①로 다시 받아 주세요.", f"{src} sha256 {got} ≠ {sha256}", 원인="hash")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(dest)):
            shutil.copyfile(src, dest)
        self.st.log(f"  {name}: 직접 받은 파일 확인됨(sha256 맞음) ← {os.path.basename(src)}")
        return dest


def eta(left_bytes, rate):
    sec = left_bytes / max(1.0, rate)
    if sec < 90:
        return T('{0}초', max(1, int(sec)))
    if sec < 5400:
        return T('{0}분', int(round(sec / 60)))
    return T('{0}시간', f"{sec / 3600:.1f}")


def extract_zip(zpath, dest, strip_single_root=False):
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        root = ""
        if strip_single_root:
            tops = {n.split("/", 1)[0] for n in names if n.strip("/")}
            if len(tops) == 1 and all("/" in n for n in names if n.strip("/")):
                root = tops.pop() + "/"
        dest_abs = os.path.abspath(dest)
        for n in names:
            rel = n[len(root):] if root and n.startswith(root) else n
            if not rel or rel.endswith("/"):
                continue
            out = os.path.abspath(os.path.join(dest, *rel.split("/")))
            if not (out == dest_abs or out.startswith(dest_abs + os.sep)):
                raise Fail("압축 파일 안에 이상한 경로가 있어요.", n)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(n) as src, open(out, "wb") as f:
                shutil.copyfileobj(src, f, 1024 * 1024)


def dir_size(path):
    total = 0
    for dp, _dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def rmtree(path):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=False, onerror=lambda f, p, e: (os.chmod(p, 0o666), f(p)))


def rmtree_quiet(path):
    try:
        rmtree(path)
    except OSError:
        pass


# ---------------------------------------------------------------- 설치
class Installer:
    def __init__(self, a):
        self.a = a
        self.P = os.path.abspath(a.prefix)
        self.D = os.path.abspath(a.data)
        self.src = os.path.abspath(a.source or SRC_ROOT)
        self.st = Status(os.path.abspath(a.status), os.path.join(self.D, "logs", "install.log"))
        with open(os.path.join(HERE, "runtimes.json"), encoding="utf-8") as f:
            self.rt = json.load(f)
        self.dry = bool(getattr(a, "dry_run", False))
        self.fetch = Fetcher(self.st, self.rt["hosts"], self.dry)
        self.dl = os.path.join(self.P, "install", "downloads")
        self.wheels = os.path.join(self.P, "install", "wheels")
        self.state_path = os.path.join(self.P, "install", "state.json")
        self.state = self._load_state()
        self.plan = None
        self.bm = PLAN.brain_model(getattr(a, "gemma", None))   # 받을 Gemma 판(models.json 이름)
        # 판: --edition > installer/edition.json(라데온 판 설치 파일) > 지난 설치 기록 > nvidia
        self.edition = PLAN.edition_of(getattr(a, "edition", None) or (None if os.path.isfile(os.path.join(HERE, "edition.json"))
                                                                       else self.state.get("edition")))
        self.rrt = {}
        try:
            with open(os.path.join(HERE, "radeon", "runtimes.json"), encoding="utf-8") as f:
                self.rrt = json.load(f)
        except (OSError, ValueError):
            pass
        self.skipped = {}          # 실패했지만 넘어간 단계(OPTIONAL) → {단계: 주의 내용}

    def _load_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_state(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=1)
        os.replace(self.state_path + ".tmp", self.state_path)

    def path(self, *p):
        return os.path.join(self.P, *p)

    # ---- 1. 사양
    def current_settings(self):
        try:
            with open(self.settings_file(), encoding="utf-8-sig") as f:
                cur = json.load(f)
            return cur if isinstance(cur, dict) else {}
        except (OSError, ValueError):
            return {}

    def gemma_dirs(self):
        """설치 폴더 models 안의 Gemma 폴더 이름들(새 무검열 판 먼저)."""
        root = self.path("models")
        try:
            names = [n for n in os.listdir(root) if n.lower().startswith("gemma-") and os.path.isdir(os.path.join(root, n))]
        except OSError:
            return []
        return sorted(names, key=lambda n: (n != self.bm, n != PLAN.BRAIN_MODEL, n))

    def gemma_file(self):
        """디스크에 다 받아진 Gemma gguf 경로(없으면 '') — 무검열 판이 있으면 그것."""
        try:
            mf = GM.load_manifest(os.path.join(HERE, "models.json"))
        except (OSError, ValueError, SystemExit):
            mf = {}
        for n in self.gemma_dirs():
            m = mf.get(n)
            files = [f["path"] for f in (m or {}).get("files", []) if f["path"].endswith(".gguf")]
            for fp in files:
                full = os.path.join(self.path("models", n), *fp.split("/"))
                want = next((f["size"] for f in m["files"] if f["path"] == fp), None)
                if os.path.isfile(full) and (not want or os.path.getsize(full) == want):
                    return full
        return ""

    def do_plan(self):
        self.st.say("그래픽카드·메모리·디스크·구독 두뇌 로그인을 살펴보는 중이에요.")
        cur = self.current_settings()
        again = bool((cur.get("처음설정") or {}).get("끝"))
        uses_local = again and str((cur.get("두뇌") or {}).get("방식") or "local") == "local"
        # 이미 '내 PC(Gemma)'로 쓰는 사람의 업데이트는 두뇌를 바꾸지 않음(구독 로그인이 있어도) — 바꾸는 건 설정에서
        self.plan = PLAN.detect(self.P, self.a.local_brain or uses_local, cli=not uses_local, gemma=self.a.gemma, edition=self.edition)
        p = self.plan
        if uses_local:
            p["판별"].append("두뇌: 이미 '내 PC(Gemma)'로 쓰는 중 → 업데이트에서 바꾸지 않음")
            bm = p["두뇌_모델"]
            old = [n for n in self.gemma_dirs() if n != bm]
            if bm in p["모델"] and bm not in self.gemma_dirs() and old:
                p["모델"] = [old[0] if n == bm else n for n in p["모델"]]
                p["판별"].append(f"두뇌: 옛 Gemma({old[0]}) 그대로 씀 — 무검열 판은 설정 '두뇌 바꾸기 → Gemma 다시 설치'로(5GB 받기)")
        g = p.get("그래픽카드")
        self.st.log("사양:", json.dumps({k: p[k] for k in ("구성", "그래픽카드", "다른_그래픽카드", "램_GB", "디스크_여유_GB", "드라이버", "torch",
                                                     "llama", "모델", "필요_디스크_GB", "구독", "두뇌_제안")}, ensure_ascii=False))
        for line in p.get("판별") or []:
            self.st.log("판별:", line)
        self.st.d["구성"] = {"이름": L(p["구성"]), "그래픽카드": (g or {}).get("이름") or L("엔비디아 그래픽카드 없음"),
                           "그래픽_GB": round((g or {}).get("전체_MiB", 0) / 1024, 1), "램_GB": p["램_GB"], "디스크_여유_GB": p["디스크_여유_GB"],
                           "필요_GB": p["필요_디스크_GB"], "안내": [L(x) for x in p["안내"]], "경고": [L(x) for x in p["경고"]], "모델": p["모델"],
                           "두뇌": {"claude_cli": "클로드 코드(구독)", "codex_cli": "GPT·Codex(구독)"}.get(p.get("두뇌_제안") or "")
                           or (f"이 PC(Gemma · {p['llama']})" if p["llama"] else "바깥 AI"), "판별": p.get("판별") or []}
        self.st.d["구성"]["두뇌"] = L(self.st.d["구성"]["두뇌"])
        if p.get("디스크_모자람"):
            raise Fail(f"디스크 공간이 모자라요. 약 {p['필요_디스크_GB']}GB 가 필요한데 {p['디스크_여유_GB']}GB 남았어요. "
                       "공간을 비우거나 다른 드라이브에 설치해 주세요.")
        self.state["plan"] = {k: p[k] for k in ("구성", "torch", "llama", "모델", "설정", "판", "목소리_gguf")}
        self.state["edition"] = p["판"]
        self.st.d["구성"]["판"] = L("라데온 판" if p["판"] == "radeon" else "엔비디아 판")
        bits = [(" · " + L("라데온 판")) if p["판"] == "radeon" else "", L(p["구성"]),
                " " + T('· 두뇌 = {0}', self.st.d["구성"]["두뇌"]),
                (" " + L("· 목소리 = 김비서 목소리(GGUF)")) if p.get("목소리_gguf") else ""]
        return "".join(bits)

    # ---- 2. 프로그램 파일
    def do_files(self):
        self.st.say("프로그램 파일을 설치 폴더에 복사해요.")
        dst = self.path("src")
        if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(self.src):
            return "건너뜀", "설치 폴더에서 다시 실행 — 복사 안 함"
        os.makedirs(dst, exist_ok=True)
        items = [x for x in COPY_ITEMS if os.path.exists(os.path.join(self.src, x))]
        for i, it in enumerate(items):
            s, d = os.path.join(self.src, it), os.path.join(dst, it)
            self.st.progress(i / len(items), f"복사: {it}")
            if os.path.isdir(s):
                rmtree(d)
                shutil.copytree(s, d, ignore=lambda _d, names: [n for n in names if n in SKIP_NAMES or n.endswith((".pyc", ".bak", ".part"))])
            else:
                shutil.copy2(s, d)
        self.state["files"] = {"from": self.src, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        return "됨", f"{len(items)}개"

    # ---- 3. 파이썬 부품
    def make_python(self, folder):
        """공식 embeddable 파이썬을 folder 에 풀고 pip 를 넣는다(이미 있으면 그대로)."""
        py = os.path.join(folder, "python.exe")
        mark = os.path.join(folder, "kimbiseo_python.txt")
        ver = self.rt["python"]["version"] + "+pip" + self.rt["pip"]["version"]
        if os.path.isfile(py) and os.path.isfile(mark) and open(mark, encoding="utf-8").read().strip() == ver:
            return py
        r = self.rt["python"]
        z = self.fetch.get(r["url"], os.path.join(self.dl, os.path.basename(r["url"])), r["sha256"], r["size"], "파이썬")
        if self.dry:
            self.fetch.get(self.rt["pip"]["url"], "pip", self.rt["pip"]["sha256"], self.rt["pip"]["size"], "pip")
            return py
        rmtree(folder)
        extract_zip(z, folder)
        self._write_pth(folder)
        pip = self.rt["pip"]
        w = self.fetch.get(pip["url"], os.path.join(self.dl, os.path.basename(pip["url"])), pip["sha256"], pip["size"], "pip")
        extract_zip(w, os.path.join(folder, "Lib", "site-packages"))
        with open(mark, "w", encoding="utf-8") as f:
            f.write(ver)
        return py

    def _write_pth(self, folder):
        with open(os.path.join(folder, self.rt["python"]["pth"]), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(chr(10).join(["python311.zip", ".", os.path.join("Lib", "site-packages"), os.path.join("..", "..", "src"),
                               "# 김비서: 위 줄 = 설치 폴더의 src(본체 코드). 환경변수·레지스트리는 보지 않음", "import site", ""]))

    def pip(self, py, args, label, frac=(0.0, 1.0), count=0, expect=0, site=None):
        """pip 를 돌린다. 큰 부품(수 GB)을 디스크에 푸는 동안 pip 는 몇 분씩 아무 말도 안 하므로, 그동안 3초마다
        '설치하는 중 · 지금까지 풀린 양 / 예상 양 · 지난 시간'을 상태에 적어 멈춘 것처럼 보이지 않게 한다(expect = 다 풀렸을 때 크기 바이트)."""
        cmd = [py, "-m", "pip", *args, "--disable-pip-version-check", "--no-warn-script-location", "--progress-bar", "off"]
        self.st.log("  $ " + " ".join(cmd[:6]) + " …")
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PIP_NO_INPUT": "1", "PIP_CONFIG_FILE": os.devnull,
               "PIP_CACHE_DIR": self.path("install", "pipcache")}
        for k in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_FIND_LINKS", "PYTHONPATH", "PYTHONHOME"):
            env.pop(k, None)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                             creationflags=NO_WINDOW, cwd=self.path("install"))
        seen, tail = 0, []
        a, b = frac
        site = site or os.path.join(os.path.dirname(py), "Lib", "site-packages")      # 부품이 풀리는 곳(크기를 재서 진행을 보임)
        watch = {"on": True, "phase": "", "t0": time.time(), "log_t": time.time()}

        def beat():
            base = tree_size(site)
            prev, gap = -1, 3.0
            while watch["on"]:
                time.sleep(gap)
                if not watch["on"]:
                    break
                if watch["phase"] != "install":
                    continue
                t = time.time()
                cur = max(0, tree_size(site) - base)
                gap = max(3.0, min(20.0, (time.time() - t) * 4))     # 크기 재기가 느린 PC(백신 검사)에서는 덜 자주
                el = time.time() - watch["t0"]
                f = min(0.97, cur / expect) if expect else 0.5
                msg = T('{0}: 디스크에 푸는 중 {1}', L(label), human(cur))
                if expect:
                    msg += T(' / 약 {0}', human(expect))
                msg += " " + T('· {0}째 — 큰 부품은 몇 분 걸려요(멈춘 것이 아니에요)', took(el))
                self.st.progress(a + (b - a) * max(0.3, f), msg, alive=cur != prev)
                prev = cur
                if time.time() - watch["log_t"] >= 60:          # 기록에도 1분마다 한 줄(어디서 오래 걸렸는지 나중에 알 수 있게)
                    watch["log_t"] = time.time()
                    self.st.log(f"    … {label}: 디스크에 푸는 중 {human(cur)} · {took(el)}째")
        threading.Thread(target=beat, name="pip-beat", daemon=True).start()
        try:
            for raw in p.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                if not line:
                    continue
                self.st.log("    " + line[:300])
                tail = (tail + [line])[-15:]
                if line.startswith("Installing collected packages"):
                    watch["phase"] = "install"
                if line.startswith(("Processing ", "Building wheel", "Installing collected")):
                    seen += 1
                    nm = line.split()[1] if line.startswith("Processing") else ("부품을 디스크에 설치하는 중" if line.startswith("Installing") else line)
                    self.st.progress(a + (b - a) * min(0.3, 0.3 * seen / max(1, count + 2)), T('{0}: {1}', L(label), os.path.basename(nm)[:60]))
            rc = p.wait()
        finally:
            watch["on"] = False
        self.st.log(f"    {label}: pip 끝(코드 {rc}) · {took(time.time() - watch['t0'])}")
        if rc != 0:
            text = " / ".join(tail[-6:])
            if "No space left" in text or "Errno 28" in text:
                raise Fail("디스크 공간이 모자라요. 공간을 비우고 '다시 하기'를 눌러 주세요.", text, 원인="disk")
            if "WinError 5" in text or "WinError 32" in text or "PermissionError" in text or "Access is denied" in text:
                raise Fail(f"{label} 을(를) 설치하다 파일을 쓰지 못했어요. 김비서가 켜져 있으면 끄고, 백신 알림을 확인한 뒤 '다시 하기'를 눌러 주세요.", text, 원인="file")
            if "WinError 206" in text or "path too long" in text.lower() or "Filename too long" in text:
                raise Fail("설치 폴더 경로가 너무 길어요. 설치 위치를 짧은 폴더(예: C 드라이브 바로 아래 폴더)로 바꿔서 다시 설치해 주세요.", text, 원인="file")
            raise Fail(f"{label} 설치에 실패했어요. '다시 하기'를 눌러 주세요. 계속되면 '기록 보기'의 글을 보내 주세요.", text)

    def try_import(self, py, probe, text):
        """깔린 부품을 불러와 본다(큰 부품은 처음에 1~2분 — 백신 검사가 있으면 더). 그동안 지난 시간을 보여 줌 → (종료 코드, 오류 글)."""
        p = subprocess.Popen([py, "-B", "-c", probe], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        t0 = time.time()
        while True:
            try:
                err = p.communicate(timeout=3)[1]
                break
            except subprocess.TimeoutExpired:
                el = time.time() - t0
                # 10분까지는 '하는 중'으로 침. 그보다 길면 진전 없음으로 두어 설치 창이 알려 주게 함(끊지는 않고 계속 기다림)
                self.st.progress(self.st.d.get("진행", 0) / 100, T('{0} · {1}째(처음에는 1~2분 걸려요)', L(text), took(el)), alive=el < 600)
        return p.returncode, (err or b"").decode("utf-8", "replace")

    def env_ready(self, name, py, lock_path, probe):
        mark = os.path.join(os.path.dirname(py), f"kimbiseo_{name}_lock.txt")
        want = sha256_of(lock_path)
        if os.path.isfile(mark) and open(mark, encoding="utf-8").read().strip() == want:
            self.st.say(T('이미 깔린 {0} 부품을 확인하는 중이에요.', L(name)))
            rc, err = self.try_import(py, probe, T('이미 깔린 {0} 부품을 확인하는 중', L(name)))
            if rc == 0:
                return True, mark, want
            self.st.log(f"  {name}: 기록은 있는데 불러오기 시험 실패 → 다시 설치", err[-300:])
        return False, mark, want

    def install_env(self, name, folder, lock_name, probe, frac):
        a, b = frac
        py = self.make_python(folder)
        lock_path = os.path.join(HERE, "locks", lock_name)
        if self.dry:
            with open(lock_path, encoding="utf-8") as f:
                pk = json.load(f)["packages"]
            for i, x in enumerate(pk):
                self.fetch.get(x["url"], x["file"], x["sha256"], None, T('{0} 부품 {1}', L(name), f"{x['name']}=={x['version']}"),
                               (a + (b - a) * i / len(pk), a + (b - a) * (i + 1) / len(pk)))
            if any(x["sdist"] for x in pk):
                s_ = self.rt["setuptools"]
                self.fetch.get(s_["url"], "setuptools", s_["sha256"], s_["size"], "setuptools")
            return f"[시험] {len(pk)}개 주소 확인"
        ok, mark, want = self.env_ready(name, py, lock_path, probe)
        if ok:
            self.st.progress(b, T('{0}: 이미 설치됨', L(name)))
            return "이미 설치됨"
        with open(lock_path, encoding="utf-8") as f:
            lock = json.load(f)
        pk = lock["packages"]
        os.makedirs(self.wheels, exist_ok=True)
        mid = a + (b - a) * 0.6
        for i, x in enumerate(pk):
            self.fetch.get(x["url"], os.path.join(self.wheels, x["file"]), x["sha256"], None,
                           T('{0} 부품 {1}/{2} {3}', L(name), i + 1, len(pk), x['name']), (a + (mid - a) * i / len(pk), a + (mid - a) * (i + 1) / len(pk)))
        if any(x["sdist"] for x in pk):   # 소스판만 있는 작은 꾸러미 → setuptools 먼저(빌드 격리 없이 만듦)
            s = self.rt["setuptools"]
            w = self.fetch.get(s["url"], os.path.join(self.wheels, os.path.basename(s["url"])), s["sha256"], s["size"], "setuptools")
            self.pip(py, ["install", "--no-index", "--no-deps", w], T('{0} 준비(setuptools)', L(name)))
        req = os.path.join(self.path("install"), f"req_{name}.txt")
        with open(req, "w", encoding="utf-8") as f:
            for x in pk:
                f.write(f"{x['name']}=={x['version']} --hash=sha256:{x['sha256']}\n")
        have = [os.path.join(self.wheels, x["file"]) for x in pk if os.path.isfile(os.path.join(self.wheels, x["file"]))]
        got = sum(os.path.getsize(f) for f in have)
        self.st.say(f"{name} 부품 {len(pk)}개를 다 받았어요({human(got)}). 이제 디스크에 풀어요 — 큰 부품이 있으면 몇 분 걸려요.")
        self.pip(py, ["install", "--no-index", "--find-links", self.wheels, "--no-deps", "--require-hashes", "--no-build-isolation",
                      "-r", req], T('{0} 부품 설치', L(name)), (mid, b), len(pk), expect=unpacked_size(have))
        self.st.say(T('{0} 부품이 잘 깔렸는지 불러와 보는 중이에요(처음에는 1~2분 걸릴 수 있어요).', L(name)))
        rc, err = self.try_import(py, probe, T('{0} 부품이 잘 깔렸는지 불러와 보는 중', L(name)))
        if rc != 0:
            raise Fail(f"{name} 부품을 설치했지만 불러오지 못했어요. 백신이 파일을 지웠거나 막았을 수 있어요 — 백신 알림을 확인하고 '다시 하기'를 눌러 주세요.", err[-400:])
        with open(mark, "w", encoding="utf-8") as f:
            f.write(want)
        return f"{len(pk)}개"

    def do_packages(self):
        p = self.state["plan"]
        voice_lock = "voice-cuda.json" if p["torch"] == "cu128" else "voice-cpu.json"
        self.st.say("파이썬 부품을 받아서 설치해요(본체 → 음성). 엔비디아 그래픽카드가 있으면 약 3GB 를 받아요.")
        r1 = self.install_env("본체", self.path("runtime", "python-app"), "app.json",
                              "import pipecat, fastapi, uvicorn, webview, aiortc, av, onnxruntime, anthropic, openai", (0.0, 0.3))
        gg = bool(p.get("목소리_gguf"))
        probe = "import torch, torchaudio, transformers, qwen_tts, soundfile, librosa" + (", onnxruntime, tokenizers, scipy" if gg else "")
        r2 = self.install_env("음성", self.path("runtime", "python-voice"), voice_lock, probe, (0.3, 0.9 if gg else 1.0))
        r3 = ""
        if gg:
            r3 = " " + T('· 목소리 실행 파일 {0}', L(self.install_tts_runtime((0.9, 1.0))))
        return "됨", T('본체 {0} · 음성 {1}({2} 판){3}', L(r1), L(r2), T('엔비디아') if p['torch'] == 'cu128' else "CPU", r3)

    def install_tts_runtime(self, frac=(0.0, 1.0)):
        """라데온 판 목소리용 llama.cpp(b10621 불칸 — CPU 백엔드도 들어 있음)를 runtime/llama-tts 에. 두뇌(runtime/llama)와 따로."""
        import fnmatch
        t = (self.rrt or {}).get("llama_cpp_tts")
        if not t:
            raise Fail("라데온 판 목록(installer/radeon/runtimes.json)이 없어요. 설치 파일을 다시 받아 주세요.")
        dest = self.path("runtime", "llama-tts")
        mark = os.path.join(dest, "kimbiseo_llama_tts.txt")
        tag = f"{t['version']} {t['sha256'][:12]}"
        if os.path.isfile(os.path.join(dest, "llama.dll")) and os.path.isfile(mark) and open(mark, encoding="utf-8").read().strip() == tag:
            return f"이미 설치됨({t['version']})"
        if self.dry:
            self.fetch.get(t["url"], t["file"], t["sha256"], t["size"], t["file"])
            return f"[시험] {t['version']} 주소 확인"
        z = self.fetch.get(t["url"], os.path.join(self.dl, t["file"]), t["sha256"], t["size"], t["file"], (frac[0], frac[0] + (frac[1] - frac[0]) * 0.8))
        rmtree(dest)
        os.makedirs(dest, exist_ok=True)
        keep = t.get("keep") or ["*"]
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                base = n.replace("\\", "/").rsplit("/", 1)[-1]
                if base and any(fnmatch.fnmatch(base.lower(), k.lower()) for k in keep):
                    with zf.open(n) as src_, open(os.path.join(dest, base), "wb") as out:
                        shutil.copyfileobj(src_, out)
        if not os.path.isfile(os.path.join(dest, "llama.dll")):
            raise Fail("목소리 실행 파일을 풀었는데 llama.dll 이 없어요.", ", ".join(os.listdir(dest))[:300])
        with open(mark, "w", encoding="utf-8") as f:
            f.write(tag)
        return t["version"]

    # ---- 4. 두뇌 프로그램
    def do_brain(self):
        v = self.state["plan"]["llama"]
        dest = self.path("runtime", "llama")
        if not v:   # 있던 두뇌 프로그램은 지우지 않음(설정에서 Gemma 로 돌아갈 수 있게 — 지우기는 'Gemma 삭제')
            return "건너뜀", T('두뇌 = 구독·바깥 AI(Gemma 안 받음)') + ((" " + T('· 있던 두뇌 프로그램은 그대로')) if os.path.isdir(dest) else "")
        ll = self.rt["llama_cpp"]
        mark = os.path.join(dest, "kimbiseo_llama.txt")
        tag = f"{ll['version']} {v}"
        if os.path.isfile(os.path.join(dest, "llama-server.exe")) and os.path.isfile(mark) and open(mark, encoding="utf-8").read().strip() == tag:
            return "됨", f"이미 설치됨({tag})"
        files = ll["variants"][v]
        if self.dry:
            for f in files:
                self.fetch.get(f["url"], f["file"], f["sha256"], f["size"], f["file"])
            return "됨", f"[시험] {tag} 주소 확인"
        zs = []
        for i, f in enumerate(files):
            zs.append(self.fetch.get(f["url"], os.path.join(self.dl, f["file"]), f["sha256"], f["size"], f["file"],
                                     (0.9 * i / len(files), 0.9 * (i + 1) / len(files))))
        self.st.progress(0.92, "푸는 중")
        rmtree(dest)
        for z in zs:
            extract_zip(z, dest, strip_single_root=True)
        if not os.path.isfile(os.path.join(dest, "llama-server.exe")):
            raise Fail("두뇌 프로그램을 풀었는데 llama-server.exe 가 없어요.", ", ".join(os.listdir(dest))[:300])
        with open(mark, "w", encoding="utf-8") as f:
            f.write(tag)
        return "됨", tag

    # ---- 5. 모델
    def do_models(self):
        names = self.state["plan"]["모델"]
        mf = GM.load_manifests(os.path.join(HERE, "models.json"), PLAN.RADEON_MODELS, self.INTERP_MODELS)
        root = self.path("models")
        total = sum(mf[n]["size_total"] for n in names)
        base = 0
        got_all = 0
        if self.dry:
            for n in names:
                m = mf[n]
                for f in m["files"]:
                    url = GM.file_url(m, f)
                    self.fetch.get(url, f["path"], f.get("sha256") or "0" * 64, f["size"], f"{n}/{f['path']}")
            return "됨", f"[시험] {len(names)}개 · {human(total)} 주소 확인"
        for n in names:
            m = mf[n]

            def prog(done, tot, rate, what, _b=base, _n=n):
                msg = T('{0} {1} {2} / {3}', L(_n), T('받는 중' if what == '받기' else '확인 중'), human(done), human(tot))
                if rate:
                    msg += " " + T('· {0}/초', human(rate))
                self.st.progress((_b + done) / total, msg)
            self.st.say(T('{0} ({1}) — {2}', n, human(m['size_total']), L(m['role'])))
            ok, failed, got = GM.ensure_model(m, root, say=lambda x: self.st.log(x), progress=prog)
            got_all += got
            if not ok:
                raise Fail(f"모델 {n} 을(를) 받지 못했어요. 인터넷 연결을 확인하고 '다시 하기'를 눌러 주세요(받은 만큼은 이어서 받아요).",
                           ", ".join(failed))
            base += m["size_total"]
        return "됨", f"{len(names)}개 · 새로 받음 {human(got_all)}"

    # ---- 6. 펫
    def do_pet(self):
        e = self.rt["electron"]
        dest = self.path("runtime", "electron")
        mark = os.path.join(dest, "kimbiseo_electron.txt")
        if os.path.isfile(os.path.join(dest, "electron.exe")) and os.path.isfile(mark) and open(mark, encoding="utf-8").read().strip() == e["version"]:
            return "됨", f"이미 설치됨({e['version']})"
        zdest = os.path.join(self.dl, os.path.basename(e["url"]))
        manual = getattr(self.a, "file", "") or ""
        if manual and not self.dry:                 # '직접 넣기' — 사용자가 브라우저로 직접 받은 압축 파일
            self.fetch.take_file(os.path.abspath(manual), zdest, e["sha256"], e["size"], "펫 프로그램 파일")
        z = self.fetch.get(e["url"], zdest, e["sha256"], e["size"], "펫 프로그램 파일", (0, 0.85))
        if self.dry:
            return "됨", f"[시험] Electron {e['version']} 주소 확인"
        self.st.progress(0.9, "펫 프로그램 파일을 푸는 중")
        tmp = dest + ".새로"                        # 다 풀린 뒤에 바꿔 끼움 — 풀다가 멈춰도 반쯤 풀린 폴더가 '설치됨'으로 보이지 않게
        rmtree(tmp)
        try:
            extract_zip(z, tmp)
        except (zipfile.BadZipFile, OSError) as ex:
            rmtree_quiet(tmp)
            if isinstance(ex, OSError) and (getattr(ex, "errno", 0) == 28 or getattr(ex, "winerror", 0) == 112):
                raise
            raise Fail("펫 프로그램 파일을 풀지 못했어요. 백신이 막았을 수 있어요 — 백신 알림을 확인한 뒤 다시 해 주세요.",
                       f"{type(ex).__name__}: {ex}", 원인="file") from None
        if not os.path.isfile(os.path.join(tmp, "electron.exe")):
            rmtree_quiet(tmp)
            raise Fail("펫 프로그램을 풀었는데 실행 파일이 없어요. 백신이 지웠을 수 있어요 — 백신의 격리 목록을 확인해 주세요.",
                       "electron.exe 없음", 원인="file")
        rmtree(dest)
        os.replace(tmp, dest)
        with open(mark, "w", encoding="utf-8") as f:
            f.write(e["version"])
        return "됨", f"펫 프로그램 {e['version']}"

    def pet_help(self):
        """펫 실행 틀을 직접 받아 넣는 데 필요한 것(설치 창·설정 화면이 보여 줌)."""
        e = self.rt["electron"]
        return {"주소": e["url"], "파일": os.path.basename(e["url"]), "크기": e["size"], "크기_글": human(e["size"]), "sha256": e["sha256"],
                "넣을곳": self.dl, "판": e["version"]}

    # ---- 7. 마무리
    def settings_file(self):
        return os.path.join(self.D, "settings.json")

    def write_settings(self):
        p = self.settings_file()
        os.makedirs(self.D, exist_ok=True)
        try:
            with open(p, encoding="utf-8-sig") as f:
                cur = json.load(f)
            if not isinstance(cur, dict):
                cur = {}
        except (OSError, ValueError):
            cur = {}
        plan = self.state["plan"]
        first = not (cur.get("처음설정") or {}).get("끝")
        if first or not cur.get("언어"):      # 설치 창에서 고른 언어 — 0.1.17 까지 쓰던 사람(언어 없음)은 고른 언어로
            cur["언어"] = LANG
        for k, v in plan["설정"].items():          # 사양 추천은 처음 설치(처음 화면 전)이고 사용자가 정하지 않은 것만
            sec, key = k.split(".", 1)
            if sec == "실행":
                continue
            if first and key not in (cur.get(sec) or {}):
                cur.setdefault(sec, {})[key] = v
        cur.setdefault("경로", {}).update({"자료": self.D, "모델": self.path("models"), "캐시": self.path("cache"),
                                           "로그": os.path.join(self.D, "logs")})
        run = cur.setdefault("실행", {})
        llama_exe = self.path("runtime", "llama", "llama-server.exe")
        prev = os.path.expandvars(str(run.get("두뇌_모델") or ""))   # 사용자가 고른 Gemma 판(E4B·E2B)이 디스크에 있으면 그대로
        keep = (not getattr(self.a, "gemma", None) and prev and os.path.isfile(prev)
                and os.path.normcase(os.path.abspath(prev)).startswith(os.path.normcase(self.path("models")) + os.sep))
        run.update({"앱_파이썬": self.path("runtime", "python-app", "python.exe"),
                    "음성_파이썬": self.path("runtime", "python-voice", "python.exe"),
                    "두뇌_실행파일": llama_exe if os.path.isfile(llama_exe) else "",     # 디스크에 실제 있는 것으로
                    "두뇌_모델": prev if keep else self.gemma_file(),
                    "펫_실행파일": self.path("runtime", "electron", "electron.exe"),
                    "펫_폴더": self.path("src", "pet")})
        if "실행.두뇌_장치" in plan["설정"] and (first or "두뇌_장치" not in run):
            run["두뇌_장치"] = plan["설정"]["실행.두뇌_장치"]
        if self.a.packs_catalog is not None and (self.a.packs_catalog or not (cur.get("펫") or {}).get("옷목록_주소")):
            cur.setdefault("펫", {})["옷목록_주소"] = self.a.packs_catalog
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=1)
        os.replace(p + ".tmp", p)
        return p

    def known_dir(self, csidl):
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
        return buf.value

    def make_shortcut(self, lnk, target, args, workdir, icon, desc):
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:K_LNK);$s.TargetPath=$env:K_TGT;$s.Arguments=$env:K_ARGS;"
              "$s.WorkingDirectory=$env:K_WD;$s.IconLocation=$env:K_ICON;$s.Description=$env:K_DESC;$s.WindowStyle=1;$s.Save()")
        env = {**os.environ, "K_LNK": lnk, "K_TGT": target, "K_ARGS": args, "K_WD": workdir, "K_ICON": icon, "K_DESC": desc}
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps], env=env,
                           capture_output=True, creationflags=NO_WINDOW)
        if r.returncode != 0 or not os.path.isfile(lnk):
            raise Fail("바탕화면 아이콘을 만들지 못했어요.", r.stderr.decode("utf-8", "replace")[-300:])

    def do_finish(self):
        sp = self.write_settings()
        self.st.say("설정 파일: " + sp)
        if self.dry:
            self.state["dry_checked"] = len(self.fetch.checked)
            return "됨", f"[시험] 설정만 씀 · 아이콘·앱 목록은 만들지 않음 · 주소 {len(self.fetch.checked)}개 확인"
        pyw = self.path("runtime", "python-app", "pythonw.exe")
        icon = self.path("src", "pet", "renderer", "img", "icon.ico") + ",0"
        launch_args = f'-B -X utf8 -m app.launcher --settings "{sp}"'
        un_ps1 = self.path("src", "installer", "uninstall.ps1")
        un_args = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{un_ps1}" -Prefix "{self.P}"'
        links = []
        if not self.a.no_shortcuts:
            desk = self.a.desktop_dir or self.known_dir(0x10)            # CSIDL_DESKTOPDIRECTORY
            menu = self.a.startmenu_dir or os.path.join(self.known_dir(0x02), self.a.display_name)   # CSIDL_PROGRAMS
            name = self.a.display_name
            for lnk, tgt, args, desc in [(os.path.join(desk, f"{name}.lnk"), pyw, launch_args, L("김비서 켜기")),
                                         (os.path.join(menu, f"{name}.lnk"), pyw, launch_args, L("김비서 켜기")),
                                         (os.path.join(menu, f"{name} 제거.lnk"), "powershell.exe", un_args, L("김비서 지우기"))]:
                self.make_shortcut(lnk, tgt, args, self.path("src"), icon, desc)
                links.append(lnk)
            self.state["menu_dir"] = menu
        self.state["shortcuts"] = links
        if not self.a.no_register:
            self.register(un_args, icon)
        # 받는 동안만 쓴 것 치우기(다시 받을 수 있음). 빠진 단계(펫)가 있으면 받다 만 파일은 남김 — '펫 다시 받기' 때 이어서 받게
        for d in ((self.wheels, self.path("install", "pipcache")) if self.skipped else (self.dl, self.wheels, self.path("install", "pipcache"))):
            rmtree_quiet(d)
        for f in os.listdir(self.path("install")):
            if f.startswith("req_"):
                os.remove(self.path("install", f))
        return "됨", f"아이콘 {len(links)}개"

    def register(self, un_args, icon):
        import winreg
        key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{self.a.reg_key}"
        size_kb = 0
        for r, _ds, fs in os.walk(self.P):
            for f in fs:
                try:
                    size_kb += os.path.getsize(os.path.join(r, f)) // 1024
                except OSError:
                    pass
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            for n, v in [("DisplayName", self.a.display_name), ("DisplayVersion", VERSION), ("Publisher", L("김비서 프로젝트")),
                         ("InstallLocation", self.P), ("DisplayIcon", icon.rsplit(",", 1)[0]),
                         ("UninstallString", f"powershell.exe {un_args}"), ("QuietUninstallString", f"powershell.exe {un_args} -Quiet"),
                         ("InstallDate", datetime.date.today().strftime("%Y%m%d"))]:
                winreg.SetValueEx(k, n, 0, winreg.REG_SZ, v)
            for n, v in [("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", min(size_kb, 0x7FFFFFFF))]:
                winreg.SetValueEx(k, n, 0, winreg.REG_DWORD, v)
        self.state["reg_key"] = self.a.reg_key

    # ---- 돌리기
    def run(self):
        os.makedirs(self.path("install"), exist_ok=True)
        self.st.heartbeat()
        self.state.update({"version": VERSION, "prefix": self.P, "data": self.D, "settings": self.settings_file(),
                           "display_name": self.a.display_name})
        py_step = self.st.step("python")
        if py_step["상태"] != "됨":
            py_step["상태"] = "됨" if os.path.isfile(self.path("runtime", "python-app", "python.exe")) else py_step["상태"]
        for sid, fn in [("plan", self.do_plan), ("files", self.do_files), ("packages", self.do_packages), ("brain", self.do_brain),
                        ("models", self.do_models), ("pet", self.do_pet), ("finish", self.do_finish)]:
            self.st.begin(sid)
            t0 = time.time()
            try:
                r = fn()
            except Exception as ex:  # noqa: BLE001
                why, detail, info = self.explain(ex)
                if sid in OPTIONAL:                 # 펫: 실패해도 설치를 끝냄 — 김비서(대화)는 먼저 쓰고 펫은 나중에
                    self.skip(sid, why, detail, info)
                    continue
                return self.fail(sid, why, detail, info)
            state, text = r if isinstance(r, tuple) else ("됨", r or "")
            self.st.end(sid, state, f"{text} ({time.time() - t0:.0f}초)")
            self.save_state()
        self.state["installed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.state["skipped"] = sorted(self.skipped)
        self.save_state()
        done_text = "설치가 끝났어요." if not self.skipped else "설치가 끝났어요(펫은 아직 — 김비서는 지금 쓸 수 있어요)."
        self.st.d.update({"끝": True, "성공": True, "지금": "", "글": L(done_text), "설정": self.settings_file(),
                          "주의": list(self.skipped.values()),
                          "실행": {"파이썬": self.path("runtime", "python-app", "pythonw.exe"), "작업폴더": self.path("src"),
                                 "인자": ["-B", "-X", "utf8", "-m", "app.launcher", "--settings", self.settings_file()]}})
        self.st.write(force=True)
        self.st.log(f"==== 설치 끝 (전체 {took(time.time() - self.st.t0)})")
        return 0

    # ---- 설정 '두뇌 바꾸기' — Gemma 만 설치 / 지우기
    def run_gemma(self):
        os.makedirs(self.path("install"), exist_ok=True)
        self.st.heartbeat()
        self.st.log(f"==== Gemma 설치 시작 (김비서 {VERSION})")
        for sid in ("python", "files", "packages", "pet"):
            self.st.end(sid, "건너뜀", "Gemma 만 설치")
        steps = [("plan", None), ("brain", self.do_brain), ("models", self.do_models), ("finish", None)]
        for sid, fn in steps:
            self.st.begin(sid)
            t0 = time.time()
            try:
                if sid == "plan":
                    p = PLAN.detect(self.P, local_brain=True, cli=False, gemma=self.bm)
                    if not p["llama"]:   # 6GB 미만 그래픽카드 — 그래도 사용자가 원하면 그 카드(또는 CPU)로
                        p = PLAN.make_plan([], p["램_GB"], p["디스크_여유_GB"], others=p["다른_그래픽카드"], local_brain=True, gemma=self.bm)
                    self.state["plan"] = dict(self.state.get("plan") or {}, llama=p["llama"], 모델=[self.bm])
                    self.st.log("Gemma 설치 판별:", p["llama"], p["구성"])
                    need = (GM.load_manifest(os.path.join(HERE, "models.json"))[self.bm]["size_total"] / (1024 ** 3)) + 1.5
                    if p["디스크_여유_GB"] is not None and p["디스크_여유_GB"] < need:
                        raise Fail(f"디스크 공간이 모자라요. 약 {need:.1f}GB 가 필요한데 {p['디스크_여유_GB']}GB 남았어요.")
                    r = ("됨", f"두뇌 프로그램 {p['llama']} · {self.bm}")
                    self._gemma_dev = "gpu" if p["llama"] in ("cuda12", "cuda13", "vulkan") else "cpu"
                elif sid == "finish":
                    freed = 0
                    for n in self.gemma_dirs():
                        if n != self.bm:
                            freed += dir_size(self.path("models", n))
                            rmtree(self.path("models", n))
                    cur = self.current_settings()
                    run = cur.setdefault("실행", {})
                    run.update({"두뇌_실행파일": self.path("runtime", "llama", "llama-server.exe"), "두뇌_모델": self.gemma_file(),
                                "두뇌_장치": self._gemma_dev})
                    write_json(self.settings_file(), cur)
                    r = ("됨", "설정에 두뇌 경로를 적었어요" + (f" · 옛 Gemma 지움 {human(freed)}" if freed else ""))
                else:
                    r = fn()
            except Fail as ex:
                return self.fail(sid, ex.why, ex.detail)
            except Exception as ex:  # noqa: BLE001
                return self.fail(sid, "Gemma 를 설치하다 문제가 생겼어요. 인터넷을 확인하고 다시 눌러 주세요(받은 만큼은 이어서 받아요).",
                                 f"{type(ex).__name__}: {ex}")
            state, text = r if isinstance(r, tuple) else ("됨", r or "")
            self.st.end(sid, state, f"{text} ({time.time() - t0:.0f}초)")
        self.save_state()
        self.st.d.update({"끝": True, "성공": True, "지금": "", "글": L("Gemma 설치가 끝났어요.")})
        self.st.write(force=True)
        self.st.log("==== Gemma 설치 끝")
        return 0

    def remove_gemma(self):
        """Gemma 모델 폴더 전부 + 두뇌 프로그램(runtime\\llama) 지우기 → 돌려준 바이트. 켜져 있으면 실행 관리가 먼저 끔."""
        freed, gone, left = 0, [], []
        targets = [self.path("models", n) for n in self.gemma_dirs()] + [self.path("runtime", "llama")]
        for t in targets:
            if not os.path.isdir(t):
                continue
            n = dir_size(t)
            try:
                rmtree(t)
                freed += n
                gone.append(os.path.basename(t))
            except OSError as ex:
                left.append(f"{os.path.basename(t)}: {type(ex).__name__}")
        cur = self.current_settings()
        if cur:
            run = cur.setdefault("실행", {})
            run["두뇌_모델"] = self.gemma_file()
            llama_exe = self.path("runtime", "llama", "llama-server.exe")
            run["두뇌_실행파일"] = llama_exe if os.path.isfile(llama_exe) else ""
            write_json(self.settings_file(), cur)
        self.st.log(f"Gemma 지움: {', '.join(gone) or '없음'} · {human(freed)}" + (f" · 못 지움 {left}" if left else ""))
        return {"ok": not left, "지움": gone, "못지움": left, "돌려준_바이트": freed, "돌려준": human(freed)}

    def explain(self, ex):
        """예외 → (사용자에게 보일 이유, 기술 내용, 받기 정보)."""
        if isinstance(ex, Fail):
            return ex.why, ex.detail, dict(ex.info)
        if isinstance(ex, OSError):
            why = ("디스크 공간이 모자라요. 공간을 비우고 '다시 하기'를 눌러 주세요." if getattr(ex, "errno", 0) == 28 or getattr(ex, "winerror", 0) == 112
                   else "파일을 쓰거나 지우지 못했어요(백신 프로그램이 막았거나 김비서가 켜져 있을 수 있어요). 김비서를 끄고 '다시 하기'를 눌러 주세요."
                   if isinstance(ex, PermissionError) or getattr(ex, "winerror", 0) in (5, 32) else
                   "파일을 다루다 문제가 생겼어요. '다시 하기'를 눌러 주세요.")
            return why, f"{type(ex).__name__}: {ex}", {"원인": "disk" if "디스크" in why else "file"}
        return ("생각하지 못한 문제가 생겼어요. '다시 하기'를 눌러 주세요. 계속되면 기록 파일을 보내 주세요.", traceback.format_exc()[-800:], {})

    def skip(self, sid, why, detail, info=None):
        """선택 단계(펫)가 실패 → 설치는 계속. 무엇이 빠졌고 어떻게 넣는지를 상태 파일 '주의'에 남김."""
        name = dict(STEPS)[sid]
        note = {"id": sid, "단계": L(name), "이유": L(why), "자세히": str(detail)[-800:], "기록": self.st.log_path, **(info or {})}
        note["까닭"] = L(short_why(note.get("원인"), why))
        if sid == "pet":
            note["직접받기"] = self.pet_help()
        self.skipped[sid] = note
        self.st.end(sid, "실패", why)
        self.st.log(f"!!!! {name} 실패(넘어감 — 나머지 설치는 계속):", why, "|", detail)
        self.diagnose(note)
        self.save_state()

    def diagnose(self, note):
        """받기 실패 때 기록에 남기는 진단 줄(개인정보 없음: 프록시는 켜짐/꺼짐과 종류만, 주소·계정은 안 적음)."""
        try:
            import platform
            import urllib.request
            px = urllib.request.getproxies()
            free = shutil.disk_usage(self.P).free
            curl = os.path.isfile(os.path.join(os.environ.get("SystemRoot", ""), "System32", "curl.exe"))
            pac = False
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software" + chr(92) + "Microsoft" + chr(92) + "Windows" + chr(92) + "CurrentVersion"
                                    + chr(92) + "Internet Settings") as k:
                    pac = bool(winreg.QueryValueEx(k, "AutoConfigURL")[0])
            except OSError:
                pass
            self.st.log("진단:", json.dumps({"윈도우": platform.version(), "파이썬": platform.python_version(), "원인": note.get("원인"),
                                         "인증서": GM.tls_note(), "PC_시각": time.strftime("%Y-%m-%d %H:%M"),
                                         "써본_방식": note.get("방식"), "프록시_설정": sorted(px) if px else "없음",
                                         "프록시_자동설정": pac, "curl_있음": curl, "디스크_여유": human(free),
                                         "받는_곳": (note.get("주소") or "").split("/")[2] if note.get("주소") else ""}, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass

    def fail(self, sid, why, detail, info=None):
        self.st.end(sid, "실패", why)
        err = {"id": sid, "단계": L(dict(STEPS)[sid]), "이유": L(why), "자세히": str(detail)[-800:], "기록": self.st.log_path, **(info or {})}
        err["까닭"] = L(short_why(err.get("원인"), why))
        self.st.d.update({"끝": True, "성공": False, "오류": err})
        self.st.write(force=True)
        self.st.log("!!!! 실패:", sid, why, "|", detail)
        if (info or {}).get("주소"):
            self.diagnose(err)
        self.save_state()
        return 1

    # ---- 펫 실행 틀만 다시 설치(설치 창 '펫 다시 받기'·'직접 넣기' · 김비서 설정 → 펫)
    # ---- 통역 원어민 목소리(선택 부품)
    INTERP_MODELS = os.path.join(HERE, "interp", "models.json")

    def interp_models(self):
        mf = GM.load_manifest(self.INTERP_MODELS)
        return list(mf), mf

    def do_interp_packages(self):
        r = self.install_env("통역", self.path("runtime", "python-interp"), "interp.json",
                             "import torch, kokoro, misaki, piper, onnxruntime, soundfile", (0.0, 0.9))
        # 태국어(0.1.17~): 같은 환경에 pythainlp 만 더함 — 따로 잠가서 이미 통역 목소리를 받은 사람은 이것만 받음
        r2 = self.install_env("통역 태국어", self.path("runtime", "python-interp"), "interp-thai.json",
                              "import pythainlp.tokenize, pythainlp.util", (0.9, 1.0))
        return "됨", f"통역 부품 {r} · 태국어 {r2}"

    def do_interp_models(self):
        names, mf = self.interp_models()
        self.state["plan"] = dict(self.state.get("plan") or {}, 모델=names)
        total = sum(mf[n]["size_total"] for n in names)
        free = shutil.disk_usage(self.P).free if os.path.isdir(self.P) else None
        if free is not None and free < total + 2 * 1024 ** 3:
            raise Fail(f"디스크 공간이 모자라요. 통역 목소리에 약 {human(total + 2 * 1024 ** 3)} 가 필요한데 {human(free)} 남았어요.")
        return self.do_models()

    def finish_interp(self):
        cur = self.current_settings()
        cur.setdefault("실행", {})["통역_파이썬"] = self.path("runtime", "python-interp", "python.exe")
        write_json(self.settings_file(), cur)
        for d in (self.wheels, self.path("install", "pipcache")):
            rmtree_quiet(d)
        for f in os.listdir(self.path("install")):
            if f.startswith("req_"):
                os.remove(self.path("install", f))
        return "됨", "설정에 통역 목소리 경로를 적었어요"

    def run_interp(self):
        os.makedirs(self.path("install"), exist_ok=True)
        self.st.heartbeat()
        self.st.log(f"==== 통역 목소리 설치 시작 (김비서 {VERSION})")
        for sid in ("python", "plan", "files", "brain", "pet"):
            self.st.end(sid, "건너뜀", "통역 목소리만 설치")
        for sid, fn in (("packages", self.do_interp_packages), ("models", self.do_interp_models), ("finish", self.finish_interp)):
            self.st.begin(sid)
            t0 = time.time()
            try:
                r = fn()
            except Fail as ex:
                return self.fail(sid, ex.why.replace("'다시 하기'", "'통역 목소리 받기'"), ex.detail)
            except Exception as ex:  # noqa: BLE001
                why, detail, info = self.explain(ex)
                return self.fail(sid, why.replace("'다시 하기'", "'통역 목소리 받기'"), detail, info)
            state, text = r if isinstance(r, tuple) else ("됨", r or "")
            self.st.end(sid, state, f"{text} ({time.time() - t0:.0f}초)")
        self.save_state()
        self.st.d.update({"끝": True, "성공": True, "지금": "", "글": L("통역 목소리를 설치했어요. 다음 통역부터 그 나라 목소리로 읽어요."), "주의": []})
        self.st.write(force=True)
        self.st.log("==== 통역 목소리 설치 끝")
        return 0

    # ---- 내 목소리 확인 모델(선택) — 설정 → 내 목소리 '확인 모델 받기'. models.json 의 titanet-small(약 40MB)만 받음
    def run_voiceprint(self):
        os.makedirs(self.path("install"), exist_ok=True)
        self.st.heartbeat()
        self.st.log(f"==== 목소리 확인 모델 받기 시작 (김비서 {VERSION})")
        for sid in ("python", "plan", "files", "packages", "brain", "pet"):
            self.st.end(sid, "건너뜀", "목소리 확인 모델만")
        self.state["plan"] = dict(self.state.get("plan") or {}, 모델=["titanet-small"])
        for sid, fn in (("models", self.do_models),):
            self.st.begin(sid)
            t0 = time.time()
            try:
                r = fn()
            except Fail as ex:
                return self.fail(sid, ex.why.replace("'다시 하기'", "'확인 모델 받기'"), ex.detail)
            except Exception as ex:  # noqa: BLE001
                why, detail, info = self.explain(ex)
                return self.fail(sid, why.replace("'다시 하기'", "'확인 모델 받기'"), detail, info)
            state, text = r if isinstance(r, tuple) else ("됨", r or "")
            self.st.end(sid, state, f"{text} ({time.time() - t0:.0f}초)")
        self.st.end("finish", "됨", "받은 모델은 김비서가 바로 씀")
        self.save_state()
        self.st.d.update({"끝": True, "성공": True, "지금": "", "글": L("목소리 확인 모델을 받았어요. 이제 내 목소리를 등록할 수 있어요."), "주의": []})
        self.st.write(force=True)
        self.st.log("==== 목소리 확인 모델 받기 끝")
        return 0

    def run_pet(self):
        os.makedirs(self.path("install"), exist_ok=True)
        self.st.heartbeat()
        self.st.log(f"==== 펫 다시 설치 시작 (김비서 {VERSION})" + (" · 받아 둔 파일로" if getattr(self.a, "file", "") else ""))
        for sid in ("python", "plan", "files", "packages", "brain", "models"):
            self.st.end(sid, "건너뜀", "펫만 설치")
        for sid, fn in (("pet", self.do_pet), ("finish", self.finish_pet)):
            self.st.begin(sid)
            t0 = time.time()
            try:
                r = fn()
            except Exception as ex:  # noqa: BLE001
                why, detail, info = self.explain(ex)
                if sid == "pet":
                    info["직접받기"] = self.pet_help()
                return self.fail(sid, why.replace("'다시 하기'", "'펫 다시 받기'"), detail, info)
            state, text = r if isinstance(r, tuple) else ("됨", r or "")
            self.st.end(sid, state, f"{text} ({time.time() - t0:.0f}초)")
        self.state["skipped"] = [x for x in self.state.get("skipped") or [] if x != "pet"]
        self.save_state()
        self.st.d.update({"끝": True, "성공": True, "지금": "", "글": L("펫을 설치했어요. 김비서를 다시 켜면 펫이 나와요."), "주의": []})
        self.st.write(force=True)
        self.st.log("==== 펫 다시 설치 끝")
        return 0

    def finish_pet(self):
        cur = self.current_settings()
        run = cur.setdefault("실행", {})
        run.update({"펫_실행파일": self.path("runtime", "electron", "electron.exe"), "펫_폴더": self.path("src", "pet")})
        write_json(self.settings_file(), cur)
        z = os.path.join(self.dl, os.path.basename(self.rt["electron"]["url"]))
        for f in (z, z + ".part", z + ".bad"):
            try:
                os.remove(f)
            except OSError:
                pass
        return "됨", "설정에 펫 경로를 적었어요"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["install", "plan", "gemma-install", "gemma-remove", "pet-install", "pet-help", "interp-install",
                                    "voiceprint-install"])
    ap.add_argument("--prefix", default=os.path.expandvars(r"%LOCALAPPDATA%\KimBiseo"))
    ap.add_argument("--data", default=os.path.expandvars(r"%APPDATA%\KimBiseo"))
    ap.add_argument("--status", default="")
    ap.add_argument("--source", default="")
    ap.add_argument("--local-brain", action="store_true")
    ap.add_argument("--gemma", default=None, help="이 PC 두뇌 판: E4B(기본, 약 5.3GB) | E2B(약 3.4GB)")
    ap.add_argument("--desktop-dir", default="")
    ap.add_argument("--startmenu-dir", default="")
    ap.add_argument("--reg-key", default="KimBiseo")
    ap.add_argument("--display-name", default="김비서")
    ap.add_argument("--packs-catalog", default=None)
    ap.add_argument("--edition", default=None, help="nvidia | radeon (비우면 installer/edition.json → 지난 설치 기록 → nvidia)")
    ap.add_argument("--no-shortcuts", action="store_true")
    ap.add_argument("--no-register", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="시험: 받기·설치 없이 차례만(받을 주소는 크기만 물어 확인)")
    ap.add_argument("--file", default="", help="pet-install: 직접 받아 둔 펫 실행 틀 압축 파일(크기·sha256 이 목록과 같아야 씀)")
    ap.add_argument("--lang", default="ko", help="설치 화면 언어: ko | en | ja | zh (기본 ko — 0.1.17 까지 그대로)")
    a = ap.parse_args()
    set_lang(a.lang)
    if a.packs_catalog is None:   # 옷 목록 주소 = install_config.json 한 줄(설치 창에서 따로 주지 않았을 때)
        try:
            with open(os.path.join(HERE, "install_config.json"), encoding="utf-8") as f:
                a.packs_catalog = str(json.load(f).get("packs_catalog") or "")
        except (OSError, ValueError):
            a.packs_catalog = None
    if a.cmd == "plan":
        print(json.dumps(PLAN.detect(a.prefix, a.local_brain, gemma=a.gemma), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "pet-help":       # 펫 실행 틀을 직접 받을 주소·크기·넣을 곳(JSON)
        a.status = os.path.join(a.prefix, "install", "pet_help_status.json")
        os.makedirs(os.path.dirname(os.path.abspath(a.status)), exist_ok=True)
        print(json.dumps(Installer(a).pet_help(), ensure_ascii=False))
        return 0
    if not a.status:
        a.status = os.path.join(a.prefix, "install", "gemma_status.json" if a.cmd.startswith("gemma") else
                                "pet_status.json" if a.cmd == "pet-install" else
                                "interp_status.json" if a.cmd == "interp-install" else
                                "voiceprint_status.json" if a.cmd == "voiceprint-install" else "status.json")
    os.makedirs(os.path.dirname(os.path.abspath(a.status)), exist_ok=True)
    if a.cmd == "gemma-remove":
        print(json.dumps(Installer(a).remove_gemma(), ensure_ascii=False))
        return 0
    if a.cmd == "gemma-install":
        if os.path.isfile(a.status):
            os.remove(a.status)
        return Installer(a).run_gemma()
    if a.cmd == "pet-install":
        if os.path.isfile(a.status):
            os.remove(a.status)
        return Installer(a).run_pet()
    if a.cmd == "interp-install":
        if os.path.isfile(a.status):
            os.remove(a.status)
        return Installer(a).run_interp()
    if a.cmd == "voiceprint-install":
        if os.path.isfile(a.status):
            os.remove(a.status)
        return Installer(a).run_voiceprint()
    return Installer(a).run()


if __name__ == "__main__":
    sys.exit(main())
