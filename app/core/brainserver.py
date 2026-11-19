# 로컬 두뇌(llama.cpp llama-server) 준비 — 두뇌를 '내 PC(Gemma)'로 바꾼 직후 서버가 없으면 켜고,
#   준비(모델 읽기)가 끝날 때까지 기다린다. 대화는 그동안 화면에 '두뇌 준비 중(n초)'을 보여 주고 이어서 답한다.
#   실패는 까닭을 나눠 알려 준다: 프로그램 없음 / 모델 파일 없음 / 포트를 다른 프로그램이 씀 / 메모리 부족 / 시간 초과.
#   실행기(app/launcher.py)가 이미 켠 서버가 있으면 그대로 쓴다(끄지 않음). 본체가 직접 켠 것만 자기 것으로 기억했다가
#   본체가 끝날 때 그 PID 만 끈다(다른 프로세스는 건드리지 않음).
import asyncio
import collections
import json
import os
import re
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit

import httpx
from loguru import logger

from . import config as C
from . import i18n

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GPU_NEED_MIB = 3800        # Gemma 4 E4B Q4 문맥 8K 그래픽 몫(3단계 실측 3.5GB) + 여유
GPU_NEED_MIB_E2B = 2400    # E2B Q4(14단계 실측)
HEALTH_TIMEOUT = 1.5
LOCK = None                # asyncio.Lock — 첫 대화에서 만든다(이벤트 루프 밖에서 만들면 판이 묶임)
OWNED = {"popen": None, "pid": 0, "port": 0, "tail": collections.deque(maxlen=60), "log": ""}


def _lock():
    global LOCK
    if LOCK is None:
        LOCK = asyncio.Lock()
    return LOCK


def base_url(cfg):
    return str((cfg.get("두뇌") or {}).get("주소") or f"http://127.0.0.1:{cfg['포트']['두뇌']}/v1").rstrip("/")


def root_url(base=None, cfg=None):
    b = str(base or base_url(cfg or {}))
    return re.sub(r"/v1/?$", "", b)


def health_url(cfg):
    return root_url(cfg=cfg) + "/health"


def _port_of(base, cfg):
    try:
        u = urlsplit(base)
        if u.port and u.hostname in ("127.0.0.1", "localhost", "::1"):
            return int(u.port)
    except ValueError:
        pass
    return int(cfg["포트"]["두뇌"])


def _expand(p):
    return os.path.expandvars(str(p or "")).strip().strip('"')


def paths(cfg):
    r = cfg.get("실행") or {}
    return _expand(r.get("두뇌_실행파일")), _expand(r.get("두뇌_모델"))


def brain_gpu_need(model):
    return GPU_NEED_MIB_E2B if "e2b" in os.path.basename(str(model or "")).lower() else GPU_NEED_MIB


def _gpu_free_mib():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW).stdout.split()
        return max(float(x) for x in out) if out else 0.0
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0.0


def _pid_alive(pid):
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k.OpenProcess(0x1000, False, int(pid))    # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        k.CloseHandle(h)


def _launcher_brain_alive(cfg):
    """실행기의 실행 기록(run/launcher.json)에 두뇌 PID 가 살아 있으면 True — 그 서버가 켜지는 중일 수 있다."""
    try:
        p = os.path.join(C.path(cfg, "자료"), "run", "launcher.json")
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        if time.time() - os.path.getmtime(p) > 180:
            return False
        b = ((rec.get("services") or {}).get("brain") or {})
        return _pid_alive(b.get("pid"))
    except (OSError, ValueError):
        return False


def _tail_text(n=3):
    return " / ".join([x for x in list(OWNED["tail"])[-n:] if x])[-300:]


def _classify_log(text):
    t = str(text or "").lower()
    if any(x in t for x in ("out of memory", "failed to allocate", "cannot allocate", "insufficient memory",
                            "erroroutofdevicememory", "cuda error: out of memory")):
        return "memory"
    if any(x in t for x in ("address already in use", "failed to bind", "couldn't bind", "bind: ")):
        return "port_busy"
    if any(x in t for x in ("failed to load model", "error loading model", "failed to load vocabulary",
                            "unknown model architecture", "no such file", "does not exist")):
        return "model_missing"
    return ""


def _reader(stream, log_path):
    """자식 출력(파이프) → 마지막 몇 줄 기억 + 자료 폴더 logs/brain.log 에 덧붙임."""
    f = None
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        f = open(log_path, "a", encoding="utf-8", errors="replace")
        f.write("\n==== " + time.strftime("%Y-%m-%d %H:%M:%S") + " 본체가 두뇌를 켬\n")
        f.flush()
    except OSError:
        f = None
    try:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if not line:
                continue
            OWNED["tail"].append(line)
            if f:
                try:
                    f.write(line + "\n")
                    f.flush()
                except OSError:
                    pass
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass
        if f:
            try:
                f.close()
            except OSError:
                pass


def spawn(cfg):
    """llama-server 를 이 PC 에서 켠다(실행기와 같은 인자). → (ok, code, detail)"""
    exe, model = paths(cfg)
    if not exe or not os.path.isfile(exe):
        return False, "exe_missing", exe
    if not model or not os.path.isfile(model):
        return False, "model_missing", model
    b = cfg["두뇌"]
    port = _port_of(base_url(cfg), cfg)
    ctx = int(b.get("문맥_토큰") or 8192)
    alias = str(b.get("모델") or "gemma-4-E4B-it")
    dev = str((cfg.get("실행") or {}).get("두뇌_장치") or "gpu")
    env = {**os.environ}
    if dev == "gpu" and os.path.basename(os.path.dirname(exe)).lower() != "vulkan":
        free = _gpu_free_mib()
        need = brain_gpu_need(model)
        if free and free < need:
            logger.info(f"두뇌: 남은 그래픽 메모리 {free:.0f}MiB < {need} → CPU 로 켬")
            dev = "cpu"
    cmd = [exe, "-m", model, "--host", "127.0.0.1", "--port", str(port), "-c", str(ctx), "-np", "1",
           "--jinja", "--no-webui", "--alias", alias]
    if dev == "cpu":
        cmd += ["-ngl", "0", "-dev", "none"]
        env["CUDA_VISIBLE_DEVICES"] = "-1"
    else:
        cmd += ["-ngl", "99"]
    cmd += [str(x) for x in ((cfg.get("실행") or {}).get("두뇌_인자") or [])]
    logs = C.path(cfg, "로그")
    log_path = os.path.join(logs, "brain.log")
    try:
        p = subprocess.Popen(cmd, cwd=os.path.dirname(exe), env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    except OSError as ex:
        return False, "start_failed", str(ex)[:200]
    OWNED.update(popen=p, pid=p.pid, port=port, log=log_path)
    OWNED["tail"].clear()
    threading.Thread(target=_reader, args=(p.stdout, log_path), daemon=True, name="brain-log").start()
    logger.info(f"두뇌(로컬)를 본체가 켬 PID {p.pid} · 포트 {port} · {dev}")
    return True, "", ""


def stop_owned():
    """본체가 직접 켠 두뇌만 끈다(실행기가 켠 것·다른 프로그램은 건드리지 않음)."""
    p = OWNED.get("popen")
    if p is None:
        return
    pid = OWNED.get("pid")
    try:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
    except OSError:
        pass
    logger.info(f"본체가 켠 두뇌를 끔 PID {pid}")
    OWNED.update(popen=None, pid=0, port=0)


def has_owned():
    p = OWNED.get("popen")
    return p is not None and p.poll() is None


async def _healthy(cfg, timeout=HEALTH_TIMEOUT):
    # 닫힌 포트에 HTTP 를 곧바로 시도하면 윈도우에서 2초 가까이 걸린다 — 포트부터 짧게 본다.
    try:
        port = _port_of(base_url(cfg), cfg)
    except (KeyError, TypeError, ValueError):
        port = 0
    if port and not _port_open(port, timeout=0.3):
        return False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=timeout)) as cl:
            r = await cl.get(health_url(cfg))
        return 200 <= r.status_code < 300
    except (httpx.HTTPError, OSError, ValueError):
        return False


def _port_open(port, timeout=0.4):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


async def ensure_local(cfg, on_wait=None):
    """로컬 두뇌가 준비됐는지 확인하고, 없으면 켜고 기다린다.
    → (ok, 까닭 코드, 자세히). 까닭 코드: '' | exe_missing | model_missing | port_busy | memory |
      start_failed | timeout | not_running. on_wait(지난초, 최대초) 는 기다리는 동안 1초마다 부른다."""
    async with _lock():
        if str((cfg.get("두뇌") or {}).get("방식")) != "local":
            return False, "switched", ""
        if await _healthy(cfg):
            return True, "", ""
        base = base_url(cfg)
        port = _port_of(base, cfg)
        # 우리가 켠 서버가 죽었으면 그 기록(메모리 부족 등)을 먼저 살핀다.
        p = OWNED.get("popen")
        if p is not None and p.poll() is not None:
            code = _classify_log(_tail_text(8)) or "start_failed"
            detail = _tail_text(3)
            OWNED.update(popen=None)
            return False, code, detail
        if not _port_open(port):
            # 실행기가 막 켜는 중일 수 있으니 잠깐(최대 2초) 기다린 뒤, 그래도 없으면 본체가 켠다.
            for _ in range(4):
                if await _healthy(cfg):
                    return True, "", ""
                if _port_open(port) or _launcher_brain_alive(cfg):
                    break
                await asyncio.sleep(0.5)
            if str((cfg.get("두뇌") or {}).get("방식")) != "local":
                return False, "switched", ""
            if not _port_open(port) and not _launcher_brain_alive(cfg):
                ok, code, detail = spawn(cfg)
                if not ok:
                    return False, code, detail
        limit = float((cfg.get("실행") or {}).get("준비_기다림_초") or
                      (cfg.get("두뇌") or {}).get("준비_기다림_초") or 300)
        t0 = time.time()
        last_sec = -1
        while True:
            if str((cfg.get("두뇌") or {}).get("방식")) != "local":
                return False, "switched", ""
            if await _healthy(cfg):
                return True, "", ""
            p = OWNED.get("popen")
            if p is not None and p.poll() is not None:
                code = _classify_log(_tail_text(8)) or "start_failed"
                detail = _tail_text(3)
                logger.warning(f"두뇌가 켜지다 꺼짐(코드 {p.returncode}) {detail}")
                OWNED.update(popen=None)
                return False, code, detail
            elapsed = time.time() - t0
            sec = int(elapsed)
            if sec != last_sec:
                last_sec = sec
                if on_wait is not None:
                    try:
                        on_wait(sec, int(limit))
                    except Exception:  # noqa: BLE001
                        pass
            if elapsed > limit:
                detail = _tail_text(3)
                code = _classify_log(detail) or ("port_busy" if (_port_open(port) and not has_owned()) else "timeout")
                return False, code, detail
            await asyncio.sleep(0.5)


def explain(code, detail="", cfg=None):
    """준비 실패 까닭 코드 → 사용자에게 말할 글(앱 언어). cfg 는 포트 표시 등에만 쓴다."""
    code = str(code or "")
    port = ""
    try:
        port = str(_port_of(base_url(cfg or {}), cfg or {"포트": {"두뇌": "?"}}))
    except (KeyError, TypeError, ValueError):
        port = "?"
    if code == "exe_missing":
        return i18n.tr("두뇌 프로그램(llama-server)이 없어요. 설정 → 두뇌에서 'Gemma 설치'를 눌러 받아 주세요.")
    if code == "model_missing":
        return i18n.tr("두뇌 모델 파일이 없어요. 설정 → 두뇌에서 'Gemma 설치'를 눌러 받아 주세요.")
    if code == "port_busy":
        return i18n.tr("두뇌 포트({0})를 다른 프로그램이 쓰고 있어요. 그 프로그램을 끄거나 설정에서 포트를 바꿔 주세요.", **{"0": port})
    if code == "memory":
        return i18n.tr("메모리가 부족해 두뇌를 켜지 못했어요. 다른 프로그램을 닫고 다시 말해 주세요.")
    if code == "timeout":
        return i18n.tr("두뇌가 준비되는 데 오래 걸려요. 잠시 뒤 다시 말해 주세요.")
    if code == "start_failed":
        return i18n.tr("두뇌 프로그램을 켜지 못했어요. 설정 → 두뇌에서 상태를 확인해 주세요.")
    return i18n.tr("두뇌 프로그램이 꺼져 있어요. 다시 말하면 자동으로 켜 볼게요.")


def describe_exception(ex, cfg=None):
    """두뇌 요청이 실패한 까닭 → 사용자에게 말할 글(앱 언어). 주소·열쇠 값은 넣지 않는다."""
    name = type(ex).__name__.lower()
    text = str(ex).lower()
    cause = getattr(ex, "__cause__", None)
    cname = type(cause).__name__.lower() if cause is not None else ""
    status = getattr(ex, "status_code", None)
    if status is None:
        status = getattr(getattr(ex, "response", None), "status_code", None)
    if any(x in text for x in ("out of memory", "insufficient memory", "failed to allocate", "cannot allocate")):
        return i18n.tr("메모리가 부족해 두뇌가 답하지 못했어요. 다른 프로그램을 닫고 다시 말해 주세요.")
    if "connect" in name or "connect" in cname or "connection" in text or "connect" in text:
        return i18n.tr("두뇌 주소에 연결하지 못했어요. 주소와 서버가 켜져 있는지 확인해 주세요.")
    if "timeout" in name or "timeout" in cname or "timed out" in text:
        return i18n.tr("두뇌가 제때 답하지 않았어요. 잠시 뒤 다시 말해 주세요.")
    if status in (401, 403):
        return i18n.tr("두뇌 열쇠가 맞지 않아요. 설정에서 열쇠를 확인해 주세요.")
    if status == 404:
        return i18n.tr("두뇌 주소나 모델 이름이 맞지 않아요. 설정에서 확인해 주세요.")
    if "model" in text and any(x in text for x in ("not found", "does not exist", "unknown model", "not loaded")):
        return i18n.tr("두뇌 모델 이름이 맞지 않아요. 설정에서 확인해 주세요.")
    if status and int(status) >= 500:
        return i18n.tr("두뇌 서버에 문제가 생겼어요({0}). 잠시 뒤 다시 말해 주세요.", **{"0": status})
    return i18n.tr("두뇌가 답하지 못했어요. 잠시 뒤 다시 말해 주세요.")