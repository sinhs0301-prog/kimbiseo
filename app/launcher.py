# 김비서 실행기 — 두뇌(llama-server)·귀·목소리·본체·펫을 창 없이 켜고, 김비서 창을 열고, 창을 닫으면 자기가 켠 것만 끈다.
#   pythonw -m app.launcher [--settings 설정.json]                 바탕화면 '김비서' 아이콘이 부르는 것(창 열기)
#   python  -m app.launcher [--settings ...] start --no-window      시험용: 창 없이 켜고, 끝낼 때까지 기다림(Ctrl+C·stop 으로 끝)
#   python  -m app.launcher [--settings ...] stop                   실행 기록에 적힌 우리 PID 만 끔(실행 파일·시작 시각 확인 뒤)
#   python  -m app.launcher [--settings ...] status                 무엇이 켜져 있는지
#   python  -m app.launcher [--settings ...] restart 목소리|귀       (창 안 '지금 다시 켜기' 단추와 같은 일 — 켜져 있는 실행기에 부탁)
#
# 지키는 것
#   - 창(명령창)이 보이지 않게(CREATE_NO_WINDOW). 서버 출력은 자료 폴더 logs\<이름>.log 로.
#   - 자기가 켠 PID 만 관리: 자료 폴더 run\launcher.json 에 (PID·실행 파일·시작 시각)을 적고, 끌 때 셋이 모두 맞아야 끔.
#     이름(python·electron·llama-server)으로 찾아 끄지 않음. 귀·목소리·본체는 --parent_pid 로 실행기가 사라지면 스스로 끝남.
#   - 두뇌를 그래픽카드로 켜려는데 남은 그래픽 메모리가 모자라면(3.8GB 미만) CPU 로 켜고 알림(다른 프로그램을 끄지 않음).
import argparse
import ctypes
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C  # noqa: E402
from app.shell import WinApi  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
ORDER = ["brain", "ear", "tts", "body", "pet"]
# 0.1.8 까지 설치 때 설정에 적던 옷 목록 주소(본 저장소 릴리스의 packs.json) — 이 값이면 펫 기본(옷 저장소 outfits.json)을 씀
OLD_PACK_CATALOGS = ("https://github.com/sinhs0301-prog/kimbiseo/releases/latest/download/packs.json",)
KO = {"brain": "두뇌", "ear": "귀(받아쓰기)", "tts": "목소리", "body": "본체", "pet": "펫"}
WHAT = {"목소리": "tts", "귀": "ear"}
BRAIN_GPU_NEED_MIB = 3800        # Gemma 4 E4B Q4 문맥 8K 그래픽 몫 약 3.5GB(3단계 실측) + 여유
BRAIN_GPU_NEED_MIB_E2B = 2400    # E2B Q4: 층 가중치 약 1.4GB(층별 임베딩 1.8GB 는 CPU 램) + 문맥·계산 — 14단계 실측으로 맞춤


def brain_gpu_need(model):
    """두뇌 모델 파일 이름 → 그래픽카드로 켜는 데 필요한 남은 그래픽 메모리(MiB)."""
    return BRAIN_GPU_NEED_MIB_E2B if "e2b" in os.path.basename(str(model or "")).lower() else BRAIN_GPU_NEED_MIB
LOG = None


LOG_MAX = 5 * 1024 * 1024   # 기록 파일 하나 상한(5MB) — 넘으면 .1 .2 로 밀고 새로(모두 3개까지)
LOG_KEEP = 3


def rotate(path, max_bytes=None, keep=LOG_KEEP):
    """path 가 max_bytes 이상이면 path → path.1 → path.2 … (keep 개까지) 로 밀고, 가장 옛것은 지움."""
    try:
        if os.path.getsize(path) < (max_bytes or LOG_MAX):
            return False
    except OSError:
        return False
    for i in range(keep - 1, 0, -1):
        src, dst = (path if i == 1 else f"{path}.{i - 1}"), f"{path}.{i}"
        try:
            if os.path.exists(src):
                os.replace(src, dst)
        except OSError:
            pass
    return True


def pump(stream, path, head=b""):
    """자식 프로그램의 출력(파이프)을 기록 파일로 — 크기 상한을 넘으면 나눔. 자식이 끝나면(파이프 닫힘) 끝."""
    f = None
    try:
        rotate(path)
        f = open(path, "ab")
        if head:
            f.write(head)
            f.flush()
        for line in iter(stream.readline, b""):
            f.write(line)
            f.flush()
            if f.tell() >= LOG_MAX:
                f.close()
                rotate(path)
                f = open(path, "ab")
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass
        if f:
            f.close()


def log(*a):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    try:
        rotate(LOG)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except (OSError, TypeError):
        pass
    if sys.stdout is not None:
        try:
            print(line, flush=True)
        except (OSError, ValueError):
            pass


# ---------------------------------------------------------------- 프로세스(자기 것만)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None


def proc_info(pid):
    """→ (실행 파일 경로, 시작 시각 정수) 또는 None(없음·못 엶)."""
    if not _k32 or not pid:
        return None
    h = _k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if _k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:   # STILL_ACTIVE
            return None
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        exe = buf.value if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
        ft = [wintypes.FILETIME() for _ in range(4)]
        ok = _k32.GetProcessTimes(h, *[ctypes.byref(x) for x in ft])
        created = (ft[0].dwHighDateTime << 32 | ft[0].dwLowDateTime) if ok else 0
        return exe, created
    finally:
        _k32.CloseHandle(h)


def same_proc(rec):
    info = proc_info(rec.get("pid"))
    if not info:
        return False
    exe, created = info
    return os.path.normcase(exe) == os.path.normcase(rec.get("exe", "")) and created == rec.get("created")


def kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)


# ---------------------------------------------------------------- 상태 확인
def http_ok(url, timeout=2.0):
    try:
        req = urllib.request.Request(url, headers={"Host": url.split("/")[2]})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def ear_ok(port, timeout=2.0):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as s:
            s.sendall(b'{"op":"ping"}\n')
            s.settimeout(timeout)
            return b"pong" in s.recv(200)
    except OSError:
        return False


def port_busy(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def gpu_free_mib():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=10, creationflags=NO_WINDOW).stdout.split()
        return max(float(x) for x in out) if out else 0.0
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0.0


# ---------------------------------------------------------------- 실행기
class Launcher:
    def __init__(self, settings):
        self.settings = os.path.abspath(C.user_settings_path(settings))
        self.cfg = C.load(settings, warn=lambda m: log("설정:", m))
        self.data = C.path(self.cfg, "자료")
        self.logs = C.path(self.cfg, "로그")
        os.makedirs(self.logs, exist_ok=True)
        global LOG
        LOG = os.path.join(self.logs, "launcher.log")
        self.run_file = os.path.join(self.data, "run", "launcher.json")
        self.mine = {}       # 이름 → {"pid","exe","created","cmd","popen"}
        self.state = {}      # 이름 → "끔"|"켜는 중"|"켜짐"|"실패"|"안 씀"|"이미 켜져 있음"
        self.why = {}        # 이름 → 쉬운 이유
        self.notes = []
        self.closing = False   # 창이 닫히는 중 — 켜는 차례(다른 줄)가 아직 돌아도 새로 켜지 않음
        self.lock = threading.RLock()
        self.on_change = None

    # ---- 설정 → 켤 것
    def reload(self):
        self.cfg = C.load(self.settings, warn=lambda m: log("설정:", m))

    def port(self, k):
        return int(self.cfg["포트"][{"brain": "두뇌", "ear": "귀", "tts": "목소리", "body": "본체", "pet": "펫"}[k]])

    def run_cfg(self):
        return self.cfg.get("실행") or {}

    def _python(self, key):
        r = self.run_cfg()
        p = os.path.expandvars(str(r.get(key) or ""))
        if p and os.path.isfile(p):
            return p
        return sys.executable.replace("pythonw.exe", "python.exe")

    def spec(self, k):
        """→ (명령, 작업 폴더, 추가 환경, 안 쓰는 이유|None)"""
        r = self.run_cfg()
        me = str(os.getpid())
        if k == "brain":
            if str(self.cfg["두뇌"].get("방식")) != "local":
                return None, None, None, "두뇌 = 구독·바깥 AI(이 PC 에서 안 켬)"
            exe = os.path.expandvars(str(r.get("두뇌_실행파일") or ""))
            model = os.path.expandvars(str(r.get("두뇌_모델") or ""))
            if not exe or not os.path.isfile(exe):
                return None, None, None, "두뇌 프로그램(llama-server)이 설치되지 않았어요"
            if not model or not os.path.isfile(model):
                return None, None, None, "두뇌 모델 파일이 없어요"
            dev = str(r.get("두뇌_장치") or "gpu")
            env = {}
            if dev == "gpu" and os.path.basename(os.path.dirname(exe)).lower() != "vulkan":
                free = gpu_free_mib()
                need = brain_gpu_need(model)
                if free and free < need:
                    self.notes.append(f"그래픽 메모리가 {free / 1024:.1f}GB 만 남아 두뇌를 CPU 로 켰어요(느릴 수 있어요).")
                    log(f"두뇌: 남은 그래픽 메모리 {free:.0f}MiB < {need} → CPU")
                    dev = "cpu"
            ctx = int(self.cfg["두뇌"].get("문맥_토큰") or 8192)
            cmd = [exe, "-m", model, "--host", "127.0.0.1", "--port", str(self.port("brain")), "-c", str(ctx), "-np", "1",
                   "--jinja", "--no-webui", "--alias", str(self.cfg["두뇌"].get("모델") or "gemma-4-E4B-it")]
            if dev == "cpu":
                cmd += ["-ngl", "0", "-dev", "none"]
                env["CUDA_VISIBLE_DEVICES"] = "-1"
            else:
                cmd += ["-ngl", "99"]
            cmd += [str(x) for x in (r.get("두뇌_인자") or [])]
            self.why["brain_mode"] = dev
            return cmd, os.path.dirname(exe), env, None
        if k in ("ear", "tts"):
            py = self._python("음성_파이썬")
            if k == "ear" and r.get("귀_파이썬"):
                py = self._python("귀_파이썬")
            script = os.path.join(ROOT, "voice", "ear_server.py" if k == "ear" else "tts_server.py")
            return [py, "-B", "-X", "utf8", script, "--settings", self.settings, "--parent_pid", me], ROOT, {}, None
        if k == "body":
            py = self._python("앱_파이썬").replace("pythonw.exe", "python.exe")
            return [py, "-B", "-X", "utf8", "-m", "app.main", "serve", "--settings", self.settings, "--parent_pid", me], ROOT, {}, None
        if k == "pet":
            pc = self.cfg.get("펫") or {}
            if not pc.get("켜기", True) or str((self.cfg.get("화면") or {}).get("얼굴") or "") != "펫":
                return None, None, None, "펫 끔(설정)"
            exe = os.path.expandvars(str(r.get("펫_실행파일") or ""))
            folder = os.path.expandvars(str(r.get("펫_폴더") or os.path.join(ROOT, "pet")))
            if not exe or not os.path.isfile(exe) or not os.path.isfile(os.path.join(folder, "main.js")):
                return None, None, None, "펫 프로그램이 설치되지 않았어요"
            cmd = [exe, folder, "--profile=" + os.path.join(self.data, "pet")]
            lang = str(self.cfg.get("언어") or "ko")[:2]   # 펫 메뉴·알림 글 언어(0.1.18~)
            if lang in ("en", "ja", "zh"):
                cmd.append("--lang=" + lang)
            if pc.get("옷_받기") is True:
                cmd.append("--auto-pack")
            want = str(pc.get("옷") or "").strip()
            if re.fullmatch(r"[0-9A-Za-z_-]{1,40}", want):   # 설정에서 고른 펫 캐릭터 — 옷이 하나도 없을 때 펫이 이 옷부터 받음
                cmd.append("--want-pack=" + want)
            src = str(pc.get("옷목록_주소") or "").strip()
            if src and src not in OLD_PACK_CATALOGS:   # 옛 판 기본 주소는 넘기지 않음 → 펫 config.json 의 새 옷 목록(+ 옛 주소는 예비)
                cmd.append("--pack-source=" + src)
            return cmd, folder, {}, None
        raise KeyError(k)

    def healthy(self, k):
        p = self.port(k)
        if k == "brain":
            return http_ok(f"http://127.0.0.1:{p}/health")
        if k == "ear":
            return ear_ok(p)
        if k == "tts":
            return http_ok(f"http://127.0.0.1:{p}/status")
        if k == "body":
            return http_ok(f"http://127.0.0.1:{p}/api/status")
        if k == "pet":
            return http_ok(f"http://127.0.0.1:{p}/status")
        return False

    # ---- 실행 기록
    def save_run(self):
        os.makedirs(os.path.dirname(self.run_file), exist_ok=True)
        rec = {"launcher": {"pid": os.getpid(), **dict(zip(("exe", "created"), proc_info(os.getpid()) or ("", 0)))},
               "settings": self.settings, "services": {k: {x: v[x] for x in ("pid", "exe", "created", "cmd")} for k, v in self.mine.items()}}
        tmp = self.run_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.run_file)

    def read_run(self):
        try:
            with open(self.run_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def other_launcher_alive(self):
        r = self.read_run()
        if not r:
            return False
        l = r.get("launcher") or {}
        return l.get("pid") != os.getpid() and same_proc(l)

    def clean_stale(self):
        """지난번 실행기가 비정상으로 끝나 남은 서버(기록과 실행 파일·시작 시각이 같은 것만)를 끔."""
        r = self.read_run()
        if not r:
            return
        for k, rec in (r.get("services") or {}).items():
            if same_proc(rec):
                log(f"지난번에 남은 {KO.get(k, k)} PID {rec['pid']} 끔")
                kill_tree(rec["pid"])
        try:
            os.remove(self.run_file)
        except OSError:
            pass

    # ---- 켜고 끄기
    def _set(self, k, st, why=None):
        with self.lock:
            self.state[k] = st
            if why is not None:
                self.why[k] = why
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001
                pass

    def start_one(self, k, wait=True):
        cmd, cwd, env, skip = self.spec(k)
        if skip:
            self._set(k, "안 씀", skip)
            log(f"{KO[k]}: 안 켬 — {skip}")
            return True
        if self.healthy(k):
            self._set(k, "이미 켜져 있음", f"포트 {self.port(k)} 에서 이미 돌고 있어요(이 실행기가 켠 것이 아님 — 끄지 않음)")
            log(f"{KO[k]}: 이미 켜져 있음(포트 {self.port(k)}) — 그대로 씀")
            return True
        if k != "pet" and port_busy(self.port(k)):
            if k == "brain":     # 본체가 설정 저장 직후 먼저 켰을 수 있다 — 잠깐 준비를 기다려 본다(다른 프로그램이면 실패)
                for _ in range(40):
                    if self.healthy(k):
                        self._set(k, "이미 켜져 있음", f"포트 {self.port(k)} 에서 이미 돌고 있어요(본체가 먼저 켬 — 끄지 않음)")
                        log(f"{KO[k]}: 이미 켜져 있음(포트 {self.port(k)}, 본체가 먼저 켬)")
                        return True
                    time.sleep(0.5)
            self._set(k, "실패", f"포트 {self.port(k)} 를 다른 프로그램이 쓰고 있어요. 그 프로그램을 끄거나 설정에서 포트를 바꿔 주세요.")
            log(f"{KO[k]}: 포트 {self.port(k)} 사용 중 → 못 켬")
            return False
        self._set(k, "켜는 중", "")
        # 자식 출력은 파이프로 받아 실행기가 기록 파일에 씀(5MB 넘으면 나눔 · 3개까지) — 파일을 자식에게 넘기면 크기를 못 막음
        head = ("\n==== " + time.strftime("%Y-%m-%d %H:%M:%S") + " 실행기가 켬\n").encode("utf-8")
        full_env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", **(env or {})}
        try:
            p = subprocess.Popen(cmd, cwd=cwd, env=full_env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 creationflags=NO_WINDOW | NEW_GROUP)
        except OSError as ex:
            self._set(k, "실패", f"프로그램을 켜지 못했어요: {ex}")
            log(f"{KO[k]}: 켜기 실패 {ex}")
            return False
        threading.Thread(target=pump, args=(p.stdout, os.path.join(self.logs, f"{k}.log"), head), daemon=True,
                         name=f"log-{k}").start()
        info = proc_info(p.pid) or (cmd[0], 0)
        with self.lock:
            self.mine[k] = {"pid": p.pid, "exe": info[0], "created": info[1], "cmd": cmd, "popen": p}
            self.save_run()
        log(f"{KO[k]}: 켬 PID {p.pid} · {' '.join(cmd[:3])} …")
        return self.wait_ready(k) if wait else True

    def wait_ready(self, k):
        limit = float(self.run_cfg().get("준비_기다림_초") or 300)
        t0 = time.time()
        rec = self.mine.get(k)
        while True:
            if self.healthy(k):
                self._set(k, "켜짐", "")
                log(f"{KO[k]}: 준비됨 ({time.time() - t0:.1f}초)")
                return True
            if rec and rec["popen"].poll() is not None:
                tail = self.log_tail(k)
                self._set(k, "실패", f"{KO[k]}이(가) 켜지다가 꺼졌어요." + (f" 기록: {tail}" if tail else ""))
                log(f"{KO[k]}: 켜지다 꺼짐(코드 {rec['popen'].returncode}) {tail}")
                with self.lock:
                    self.mine.pop(k, None)
                    self.save_run()
                return False
            if time.time() - t0 > limit:
                self._set(k, "실패", f"{KO[k]}이(가) {int(limit)}초 안에 준비되지 않았어요(아직 켜지는 중일 수 있어요). '다시 시도'를 눌러 주세요.")
                log(f"{KO[k]}: {limit:.0f}초 넘게 준비 안 됨(끄지 않고 둠)")
                return False
            time.sleep(0.5)

    def log_tail(self, k, n=300):
        try:
            with open(os.path.join(self.logs, f"{k}.log"), "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 4000))
                lines = [x for x in f.read().decode("utf-8", "replace").splitlines() if x.strip()]
            return " / ".join(lines[-3:])[-n:]
        except OSError:
            return ""

    def stop_one(self, k):
        with self.lock:
            rec = self.mine.pop(k, None)
        if not rec:
            return
        if k == "body":   # 먼저 정중하게(끄기 비밀값) — 안 되면 아래에서 끔
            try:
                sec = open(os.path.join(self.data, "secrets", "shutdown_secret.txt"), encoding="utf-8").read().strip()
                p = self.port("body")
                req = urllib.request.Request(f"http://127.0.0.1:{p}/api/shutdown", data=b"{}", method="POST",
                                             headers={"Content-Type": "application/json", "Host": f"127.0.0.1:{p}", "X-KimBiseo-Shutdown": sec})
                urllib.request.urlopen(req, timeout=3).read()
                rec["popen"].wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
        if rec["popen"].poll() is None and same_proc(rec):
            kill_tree(rec["pid"])
            try:
                rec["popen"].wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        log(f"{KO[k]}: 끔 PID {rec['pid']}")
        self._set(k, "끔")
        with self.lock:
            self.save_run()

    def start_all(self, only=None):
        self.notes.clear()
        ok = True
        for k in ORDER:
            if self.closing:
                return False
            if only and k not in only:
                continue
            if k in self.mine and self.mine[k]["popen"].poll() is None:
                continue
            ok = self.start_one(k) and ok
            if self.closing:          # 켜는 동안 창이 닫힘 → 방금 켠 것도 끔(펫이 혼자 남지 않게)
                self.stop_one(k)
                return False
            if k == "body" and self.state.get("body") == "실패":
                return False
        return ok and self.state.get("body") in ("켜짐", "이미 켜져 있음")

    def stop_all(self):
        for k in reversed(ORDER):
            self.stop_one(k)
        try:
            if not self.mine:
                os.remove(self.run_file)
        except OSError:
            pass

    def restart(self, what_list):
        """'지금 다시 켜기': 목소리·귀 서버를 지금 설정으로 다시 켜고, 본체에 알림(/api/pending/clear)."""
        self.reload()
        done = []
        for w in what_list:
            k = WHAT.get(w)
            if not k:
                continue
            if k not in self.mine and self.state.get(k) == "이미 켜져 있음":
                log(f"{KO[k]}: 이 실행기가 켠 것이 아니라 다시 켜지 않음")
                continue
            self.stop_one(k)
            if self.start_one(k):
                done.append(w)
                self.tell_body("/api/pending/clear", {"무엇": w})
        return done

    def apply_brain(self, restart=False):
        """화면에서 두뇌를 바꾼 뒤: Gemma(local)면 두뇌 프로그램을 켜고(restart 면 다시 켬), 아니면 내가 켠 것을 끔."""
        self.reload()
        kind = str(self.cfg["두뇌"].get("방식"))
        if kind == "local":
            if restart or ("brain" in self.mine and self.mine["brain"]["popen"].poll() is not None):
                self.stop_one("brain")
            if "brain" in self.mine:
                return {"두뇌": "켜져 있음"}
            ok = self.start_one("brain")
            return {"두뇌": self.state.get("brain"), "ok": ok, "이유": self.why.get("brain", "")}
        self.stop_one("brain")
        self._set("brain", "안 씀", "두뇌 = 구독·바깥 AI(이 PC 에서 안 켬)")
        return {"두뇌": "안 씀", "ok": True}

    def tell_body(self, path, body):
        p = self.port("body")
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{p}{path}", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                         method="POST", headers={"Content-Type": "application/json", "Host": f"127.0.0.1:{p}"})
            return json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
        except Exception as ex:  # noqa: BLE001
            log("본체에 알리기 실패", path, ex)
            return None

    def summary(self):
        with self.lock:
            return {"상태": {KO[k]: self.state.get(k, "끔") for k in ORDER}, "이유": {KO[k]: self.why.get(k, "") for k in ORDER if self.why.get(k)},
                    "알림": list(self.notes), "두뇌_장치": self.why.get("brain_mode", "")}


# ---------------------------------------------------------------- 창
SPLASH = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>김비서</title>
<style>html,body{height:100%}body{margin:0;font:16px/1.5 "Malgun Gothic",sans-serif;background:#0b0c0f;color:#ececf1;display:flex;border:1px solid #1d1f26;box-sizing:border-box;overflow-y:auto;padding:48px 0 16px}
main{margin:auto}
.bar{position:fixed;top:0;left:0;right:0;height:48px;display:flex;align-items:center;justify-content:space-between;padding:0 12px}
.bar button{width:36px;height:36px;padding:0;border:0;border-radius:8px;background:transparent;color:#8b8f9a;display:inline-flex;align-items:center;justify-content:center}
.bar button:hover{background:#1b1d24;color:#ececf1}.bar svg{width:17px;height:17px}
main{width:min(420px,88vw)}h1{font-size:22px;font-weight:600;margin:0 0 4px}ul{list-style:none;padding:0;margin:16px 0;font-size:15px}li{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #262932;color:#ececf1}
li span+span{font-size:14px;color:#8b8f9a}.켜짐,.이미{color:#56d364!important}.실패{color:#ff8a8a!important}.why{font-size:14px;color:#ff8a8a;margin:4px 0 0}.note{font-size:15px;color:#8b8f9a}
button{font:inherit;padding:10px 22px;border-radius:8px;border:1px solid #262932;background:transparent;color:#ececf1;cursor:pointer}button:hover{border-color:#3a3e4a}</style>
<div class="bar win-drag"><button type="button" title="작업 표시줄로 내리기" onclick="window.pywebview.api.minimize()"><svg viewBox="0 0 20 20"><path d="M4 10h12" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg></button>
<button type="button" title="끄기" onclick="window.pywebview.api.close()"><svg viewBox="0 0 20 20"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg></button></div>
<main class="win-drag"><h1>김비서를 켜는 중이에요</h1><p class="note">처음 켤 때는 1~2분 걸릴 수 있어요.</p><ul id="l"></ul><div id="e"></div></main>
<script>
// 창 옮기기: 누르면 시작·놓으면 끝만 알림(계산은 창 프로그램이 진짜 픽셀로 — app/winbox.py)
document.addEventListener('pointerdown',e=>{if(e.button!==0||e.target.closest('button')||!e.target.closest('.win-drag'))return;
const a=window.pywebview&&window.pywebview.api;if(!a||!a.drag_start)return;a.drag_start();
const up=()=>{window.removeEventListener('pointerup',up);if(a.drag_end)a.drag_end();};window.addEventListener('pointerup',up);});
function show(s){const l=document.getElementById('l');l.innerHTML='';for(const [k,v] of Object.entries(s['상태'])){const li=document.createElement('li');
li.innerHTML='<span></span><span></span>';li.children[0].textContent=k;li.children[1].textContent=v;li.children[1].className=v.split(' ')[0];l.appendChild(li);
const w=(s['이유']||{})[k];if(w&&v==='실패'){const p=document.createElement('p');p.className='why';p.textContent=w;l.appendChild(p);}}
const e=document.getElementById('e');e.innerHTML='';for(const n of s['알림']||[]){const p=document.createElement('p');p.className='note';p.textContent=n;e.appendChild(p);}
if(s['실패']){const b=document.createElement('button');b.textContent='다시 시도';b.onclick=()=>window.pywebview.api.retry();e.appendChild(b);}}
</script></html>"""


class Api(WinApi):
    def __init__(self, la, win=None, box=None):
        super().__init__(win, box)
        self._la = la

    def close(self):
        log("화면: 끄기 단추")
        return super().close()

    def restart_services(self, keys):
        keys = [k for k in (keys or []) if k in WHAT]
        log("화면: 지금 다시 켜기", keys)
        return {"ok": True, "다시켬": self._la.restart(keys)}

    def apply_brain(self, restart=False):
        log("화면: 두뇌 바꿈 반영", "다시 켜기" if restart else "")
        try:
            return {"ok": True, **self._la.apply_brain(bool(restart))}
        except Exception as ex:  # noqa: BLE001
            log("두뇌 반영 실패", ex)
            return {"ok": False, "오류": str(ex)}

    def status(self):
        return self._la.summary()

    # ---- 펫 프로그램을 나중에 설치했을 때(설정 → 펫): 파일 고르기·펫 켜기·기록 폴더 열기
    def pick_zip(self):
        """파일 고르기 창(압축 파일) → 고른 경로, 안 골랐으면 ''."""
        w = self._win.get("w")
        if w is None:
            return ""
        try:
            r = w.create_file_dialog(10, allow_multiple=False, file_types=("압축 파일 (*.zip)", "모든 파일 (*.*)"))   # 10 = 파일 열기
        except Exception as ex:  # noqa: BLE001
            log("파일 고르기 실패", repr(ex))
            return ""
        return str(r[0]) if r else ""

    def start_pet(self):
        """펫 프로그램을 방금 설치한 뒤: 설정을 다시 읽고 펫을 켠다(이미 켜져 있으면 그대로)."""
        log("화면: 펫 켜기")
        try:
            la = self._la
            la.reload()
            if "pet" in la.mine and la.mine["pet"]["popen"].poll() is None:
                return {"ok": True, "펫": "켜져 있음"}
            la.mine.pop("pet", None)
            ok = la.start_one("pet")
            return {"ok": bool(ok) and la.state.get("pet") in ("켜짐", "이미 켜져 있음"), "펫": la.state.get("pet"), "이유": la.why.get("pet", "")}
        except Exception as ex:  # noqa: BLE001
            log("펫 켜기 실패", repr(ex))
            return {"ok": False, "이유": str(ex)}

    def open_pet_download(self, url):
        """'직접 넣기 ①': 펫 프로그램 파일 주소를 기본 브라우저로 연다. 공식 배포처(깃허브 electron 릴리스) 주소만 연다."""
        u = str(url or "")
        if not u.startswith("https://github.com/electron/electron/releases/download/") or any(c in u for c in ' "\'<>|^&'):
            log("브라우저 열기 거절(허용 안 된 주소)")
            return False
        try:
            os.startfile(u)
            return True
        except OSError as ex:
            log("브라우저 열기 실패", repr(ex))
            return False

    def open_logs(self):
        """기록 폴더를 탐색기로 연다(문제가 생겼을 때 기록 파일을 찾기 쉽게)."""
        try:
            os.startfile(self._la.logs)
            return True
        except OSError:
            return False

    def retry(self):
        threading.Thread(target=self._la._boot, daemon=True).start()
        return True


def message_box(text, title="김비서"):
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    except Exception:  # noqa: BLE001
        pass


def run_window(la):
    from app import winbox
    dpi_mode = winbox.set_dpi_awareness((la.cfg.get("화면") or {}).get("배율_방식", "모니터별"))     # 창 틀을 불러오기 전에
    log("창 배율 방식:", dpi_mode)
    import webview
    from app.shell import WINDOW_MIN, attach_box, make_box, patch_permissions, window_size
    origin = f"http://127.0.0.1:{la.port('body')}"
    win = {"w": None}

    def push():
        w = win["w"]
        if w is None or la.state.get("body") in ("켜짐", "이미 켜져 있음") and getattr(la, "_loaded", False):
            return
        s = la.summary()
        s["실패"] = any(v == "실패" for v in la.state.values())
        try:
            w.evaluate_js("show(" + json.dumps(s, ensure_ascii=False) + ")")
        except Exception:  # noqa: BLE001
            pass

    def boot():
        la._loaded = False
        la._booting = True
        try:
            ok = la.start_all()
        finally:
            la._booting = False
        push()
        if la.state.get("body") in ("켜짐", "이미 켜져 있음"):
            la._loaded = True
            win["w"].load_url(origin + "/")
            if la.notes:
                log("알림:", " / ".join(la.notes))
        log("켜기 끝", "됨" if ok else "일부 실패", la.summary())

    la._boot = boot
    la.on_change = push
    patch_permissions(origin)
    w, hh = window_size()
    box = make_box(la.cfg, log)
    win["w"] = webview.create_window("김비서", html=SPLASH, js_api=Api(la, win, box), width=w, height=hh, min_size=WINDOW_MIN,
                                     frameless=True, easy_drag=False, background_color="#0B0C0F", text_select=True)
    attach_box(win["w"], box)
    win["w"].events.loaded += lambda: push()
    try:
        webview.start(boot, private_mode=False, storage_path=os.path.join(C.path(la.cfg, "캐시"), "창"))
    finally:
        log("창 닫힘 → 내가 켠 것 끔")
        la.closing = True
        la.stop_all()
        t_end = time.time() + 30          # 켜는 차례가 아직 돌면(예: 펫 켜기 직전) 끝날 때까지 조금 기다렸다 한 번 더 끔
        while getattr(la, "_booting", False) and time.time() < t_end:
            time.sleep(0.2)
        if la.mine:
            la.stop_all()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kimbiseo-launcher")
    ap.add_argument("--settings", default=None)
    ap.add_argument("cmd", nargs="?", default="open", choices=["open", "start", "stop", "status", "restart"])
    ap.add_argument("what", nargs="*")
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--only", default="", help="start 시험용: 켤 것만(brain,ear,tts,body,pet)")
    a = ap.parse_args(argv)
    la = Launcher(a.settings)
    if a.cmd == "status":
        r = la.read_run() or {}
        alive = {k: (same_proc(v) and v["pid"]) for k, v in (r.get("services") or {}).items()}
        ln = r.get("launcher") or {}
        print(json.dumps({"실행기": ln.get("pid") if same_proc(ln) else None, "서버": alive}, ensure_ascii=False))
        return 0
    if a.cmd == "stop":
        r = la.read_run() or {}
        ln = r.get("launcher") or {}
        if same_proc(ln):
            log(f"실행기 PID {ln['pid']} 끔(기록 확인)")
            kill_tree(ln["pid"])
        la.clean_stale()
        print("끔")
        return 0
    if a.cmd == "restart":
        print("이 명령은 켜져 있는 창의 '지금 다시 켜기' 단추를 쓰세요(실행기 안에서만 서버를 다시 켤 수 있어요).")
        return 1
    if la.other_launcher_alive():
        log("이미 켜진 실행기가 있음 → 창만 안내")
        message_box("김비서가 이미 켜져 있어요. 작업 표시줄의 김비서 창을 눌러 주세요.")
        return 0
    la.clean_stale()
    if a.cmd == "start" and a.no_window:
        only = [x for x in a.only.split(",") if x] or None
        ok = la.start_all(only)
        print(json.dumps({"ok": ok, **la.summary()}, ensure_ascii=False), flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            la.stop_all()
        return 0
    try:
        run_window(la)
    except Exception as ex:  # noqa: BLE001
        log("창 오류", repr(ex))
        la.stop_all()
        message_box(f"김비서 창을 열지 못했어요.\n{ex}\n\n기록: {LOG}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
