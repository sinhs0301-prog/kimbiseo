# 화면 한글 남음 자동 검사(0.1.18) — 실제 Chrome(헤드리스)으로 en/ja/zh 화면을 열어
#   document.body.innerText + 모든 placeholder·title·aria-label·aria-valuetext·alt + CSS ::before/::after content
#   에 남은 한글(가-힣) 글자 수를 센다. 허용 목록(tools/ui_hangul_allowlist.json)에 적은 글만 뺀다.
#   대화(빈 화면·글 하나 보낸 뒤)·기억·설정 모든 탭·마법사 8단계·말싸움 켬·통역 켬 상태를 연다.
#   크롬 프로필은 임시 폴더에 만들고 끝나면 지운다(사용자 프로필을 건드리지 않음).
#   python -B -X utf8 tools/ui_hangul_check.py [--langs en,ja,zh] [--out 결과.json] [--shots 사진폴더]
#     [--repo 저장소] [--python 본체를 돌릴 파이썬] [--chrome 크롬경로] [--keep-profile]
#   표준 라이브러리만(CDP 는 작은 WebSocket 구현으로 붙는다). 통과 = 남은 한글 0 → 종료 코드 0.
import argparse
import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LANGS = ("en", "ja", "zh")
HANGUL = re.compile(r"[가-힣]")
CHROME_DEFAULT = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ALLOW_FILE = os.path.join(HERE, "ui_hangul_allowlist.json")
ATTRS = ("title", "placeholder", "aria-label", "aria-valuetext", "alt")


def hangul_n(s):
    return len(HANGUL.findall(str(s or "")))


# ---------------------------------------------------------------- 작은 WebSocket(CDP)
class WS:
    def __init__(self, url, timeout=60):
        m = re.match(r"ws://([^/:]+):(\d+)(/.*)?$", url)
        if not m:
            raise ValueError("ws 주소가 아님: " + url)
        host, port, path = m.group(1), int(m.group(2)), m.group(3) or "/"
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET " + path + " HTTP/1.1\r\nHost: " + host + ":" + str(port) +
               "\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: " + key +
               "\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            part = self.sock.recv(4096)
            if not part:
                raise RuntimeError("WebSocket 연결이 끊김")
            buf += part
        head = buf.split(b"\r\n\r\n", 1)[0]
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise RuntimeError("WebSocket 101 아님: " + head[:200].decode("latin-1", "replace"))

    def _exact(self, n):
        out = b""
        while len(out) < n:
            part = self.sock.recv(n - len(out))
            if not part:
                raise EOFError("WebSocket 닫힘")
            out += part
        return out

    def send(self, obj, opcode=1):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8") if not isinstance(obj, bytes) else obj
        mask = os.urandom(4)
        n = len(data)
        head = bytearray([0x80 | opcode])
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        head += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(head) + masked)

    def recv(self):
        out = b""
        while True:
            b1, b2 = self._exact(2)
            fin, opcode = bool(b1 & 0x80), b1 & 0x0F
            masked, n = bool(b2 & 0x80), b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._exact(8))[0]
            mask = self._exact(4) if masked else None
            payload = self._exact(n) if n else b""
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 9:                      # ping → pong
                self.send(payload, opcode=10)
                continue
            if opcode == 8:
                raise EOFError("WebSocket 닫힘")
            out += payload
            if fin:
                return out

    def close(self):
        try:
            self.send(b"", opcode=8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


class CDP:
    def __init__(self, url):
        self.ws = WS(url)
        self.n = 0

    def call(self, method, **params):
        self.n += 1
        mid = self.n
        self.ws.send({"id": mid, "method": method, "params": params})
        while True:
            m = json.loads(self.ws.recv().decode("utf-8"))
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError(method + ": " + json.dumps(m["error"], ensure_ascii=False)[:300])
                return m.get("result") or {}

    def js(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError("JS 오류: " + str(r["exceptionDetails"])[:400])
        return (r.get("result") or {}).get("value")

    def shot(self, path):
        self.call("Runtime.evaluate", expression="window.scrollTo(0,0)")
        r = self.call("Page.captureScreenshot", format="png")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))

    def close(self):
        self.ws.close()


# ---------------------------------------------------------------- 가짜 두뇌(대화 한 번)
class Brain(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p.endswith("/health"):
            return self._send(200, {"status": "ok"})
        if p.endswith("/models"):
            return self._send(200, {"data": [{"id": "fake"}]})
        return self._send(200, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        p = self.path.split("?")[0]
        if p.endswith("/apply-template"):
            return self._send(200, {"prompt": "test prompt"})
        if p.endswith("/tokenize"):
            return self._send(200, {"tokens": [1, 2, 3]})
        if not p.endswith("/chat/completions"):
            return self._send(200, {})
        answer = "This is a test answer."
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            j = {"id": "fake", "object": "chat.completion.chunk", "created": int(time.time()), "model": "fake",
                 "choices": [{"index": 0, "delta": {"role": "assistant", "content": answer}, "finish_reason": None}]}
            self.wfile.write(("data: " + json.dumps(j, ensure_ascii=False) + "\n\n").encode("utf-8"))
            j2 = {"id": "fake", "object": "chat.completion.chunk", "created": int(time.time()), "model": "fake",
                  "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            self.wfile.write(("data: " + json.dumps(j2, ensure_ascii=False) + "\n\ndata: [DONE]\n\n").encode("utf-8"))
            self.wfile.flush()
            self.close_connection = True
            return
        return self._send(200, {"id": "fake", "object": "chat.completion", "created": int(time.time()), "model": "fake",
                                 "choices": [{"index": 0, "message": {"role": "assistant", "content": answer},
                                              "finish_reason": "stop"}],
                                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


def start_brain(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Brain)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


# ---------------------------------------------------------------- 서버·크롬
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_http(url, sec=90):
    end = time.time() + sec
    last = None
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.4)
    raise RuntimeError("서버 응답 없음: " + url + " (" + type(last).__name__ + ")")


def start_server(python, repo, settings, logpath):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["KIMBISEO_FAKE_GPU"] = "none"
    env["KIMBISEO_FAKE_CLI"] = "none"
    log = open(logpath, "wb")
    # 임베디드 파이썬(.pth)은 저장소 밖 설치 src 를 먼저 보므로, 저장소를 sys.path 맨 앞에 넣고 본체를 부른다.
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from app.main import main; "
            "sys.exit(main(['serve', '--settings', sys.argv[2]]))")
    proc = subprocess.Popen([python, "-B", "-X", "utf8", "-c", code, repo, settings],
                            cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return proc, log


def kill_tree(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def start_chrome(chrome, profile, port, lang):
    os.makedirs(profile, exist_ok=True)
    args = [chrome, "--headless=new", "--remote-debugging-port=" + str(port),
            "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--disable-sync", "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding", "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required",
            "--lang=" + lang, "--window-size=1280,950", "about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    url = None
    for _ in range(150):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=2) as r:
                tl = json.loads(r.read())
            pages = [t for t in tl if t.get("type") == "page"]
            if pages:
                url = pages[0]["webSocketDebuggerUrl"]
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
    if not url:
        kill_tree(proc)
        raise RuntimeError("Chrome DevTools 에 붙지 못함")
    return proc, CDP(url)


COLLECT_JS = r"""
(() => {
  const H = /[가-힣]/;
  const out = {text: [], attrs: [], pseudo: []};
  const t = document.body ? (document.body.innerText || "") : "";
  if (H.test(t)) out.text.push(t);
  for (const el of document.querySelectorAll("*")) {
    for (const a of ["title", "placeholder", "aria-label", "aria-valuetext", "alt"]) {
      const v = el.getAttribute(a);
      if (v && H.test(v)) out.attrs.push({attr: a, tag: el.tagName, id: el.id || "", value: v.slice(0, 400)});
    }
    if (el.tagName === "INPUT" && /^(button|submit|reset)$/i.test(el.type) && H.test(el.value || ""))
      out.attrs.push({attr: "value", tag: el.tagName, id: el.id || "", value: String(el.value).slice(0, 400)});
  }
  for (const el of document.querySelectorAll("*")) {
    for (const which of ["::before", "::after"]) {
      let c = "";
      try { c = getComputedStyle(el, which).content || ""; } catch (_) { c = ""; }
      if (c && c !== "none" && c !== "normal" && H.test(c))
        out.pseudo.push({which: which, tag: el.tagName, cls: el.className || "", content: c.slice(0, 400)});
    }
  }
  return out;
})()
"""


def load_allow():
    try:
        with open(ALLOW_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return [x for x in (data.get("items") or []) if isinstance(x, dict) and x.get("match")]
    except (OSError, ValueError):
        return []


def strip_allowed(s, screen, allow):
    """허용 목록에 적은 글(그 화면용)을 지운 뒤 남은 글."""
    for it in allow:
        screens = it.get("screens")
        if screens and screen not in screens:
            continue
        if it.get("kind") == "regex":
            try:
                s = re.sub(it["match"], "", s)
            except re.error:
                continue
        else:
            s = s.replace(it["match"], "")
    return s


def analyze(collected, screen, allow):
    raw = left = 0
    bad = []
    for kind in ("text", "attrs", "pseudo"):
        for item in collected.get(kind) or []:
            val = item if isinstance(item, str) else (item.get("value") or item.get("content") or "")
            r = hangul_n(val)
            if not r:
                continue
            raw += r
            rest = strip_allowed(str(val), screen, allow)
            n = hangul_n(rest)
            left += n
            if n:
                bad.append({"kind": kind, "attr": item.get("attr") if isinstance(item, dict) else "",
                            "which": item.get("which") if isinstance(item, dict) else "",
                            "left": n, "value": str(val)[:400]})
    return {"raw": raw, "left": left, "allowed": raw - left, "bad": bad}


def screen_list(lang_dir, lang):
    """검사할 화면 이름(사진 파일 이름·표 이름)."""
    return [
        ("conversation_empty", "대화(빈 화면)"),
        ("conversation_one", "대화(글 하나 보낸 뒤)"),
        ("memory", "기억"),
        ("settings_general", "설정:일반"),
        ("settings_name", "설정:이름·호칭"),
        ("settings_pet", "설정:펫"),
        ("settings_brain", "설정:두뇌"),
        ("settings_voice", "설정:목소리"),
        ("settings_mic", "설정:마이크·스피커"),
        ("settings_talk", "설정:대화"),
        ("settings_interp", "설정:통역"),
        ("settings_phone", "설정:폰 연결"),
        ("settings_myvoice", "설정:내 목소리"),
        ("settings_about", "설정:정보"),
        ("debate_on", "말싸움 켬"),
        ("interp_on", "통역 켬"),
    ] + [("wizard_step_%d" % i, "마법사 %d단계" % (i + 1)) for i in range(8)]


def wait_ready(cdp, ms=8000):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        try:
            if cdp.js("document.readyState === 'complete' && document.body && document.body.dataset.ready === '1'"):
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    return False


def run_lang(lang, args, brain_port, allow):
    base = None
    lang_dir = os.path.join(args.work, lang)
    os.makedirs(lang_dir, exist_ok=True)
    port = free_port()
    settings = {
        "언어": lang,
        "포트": {"본체": port, "목소리": free_port(), "귀": free_port(), "두뇌": brain_port, "펫": free_port()},
        "경로": {k: os.path.join(lang_dir, k) for k in ("자료", "모델", "캐시", "로그")},
        "처음설정": {"끝": True},
        "두뇌": {"방식": "url", "주소": "http://127.0.0.1:%d/v1" % brain_port, "모델": "fake"},
        "귀": {"모델": "", "장치": "cpu"},
        "목소리": {"엔진": "windows", "미리만들기": False},
        "펫": {"켜기": False, "얼굴": "펫", "옷_받기": False},
        "화면": {"얼굴": "펫", "글자": "크게"},
    }
    spath = os.path.join(lang_dir, "settings.json")
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=1)
    srv = log = None
    chrome_proc = cdp = None
    profile = os.path.join(lang_dir, "_크롬프로필")
    result = {"lang": lang, "screens": {}, "notes": []}
    try:
        srv, log = start_server(args.python, args.repo, spath, os.path.join(lang_dir, "서버_콘솔.txt"))
        wait_http("http://127.0.0.1:%d/api/status" % port, sec=120)
        base = "http://127.0.0.1:%d/" % port
        chrome_proc, cdp = start_chrome(args.chrome, profile, free_port(), lang)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        if args.shots:
            os.makedirs(args.shots, exist_ok=True)

        def snap(key, label):
            collected = cdp.js(COLLECT_JS) or {}
            res = analyze(collected, label, allow)
            result["screens"][label] = res
            if args.shots:
                cdp.shot(os.path.join(args.shots, ("%s_%s.png" % (lang, key))))
            return res

        cdp.call("Page.navigate", url=base)
        wait_ready(cdp, 15000)
        # i18n 사전이 붙어 lang 이 바뀔 때까지
        want = "zh-CN" if lang == "zh" else lang
        for _ in range(60):
            if cdp.js("document.documentElement.lang === %s" % json.dumps(want)):
                break
            time.sleep(0.3)
        time.sleep(1.0)
        snap("conversation_empty", "대화(빈 화면)")

        # 글 하나 보내기 — 실제 화면 입력줄로 보낸다. 연결이 늦으면 화면 코드로 한 줄 넣어 확인한다.
        sent = False
        try:
            cdp.js("(()=>{const i=document.getElementById('chat-text'); i.value='Hello from the check';"
                   "const f=document.getElementById('chat-form'); if(f.requestSubmit) f.requestSubmit(); else f.dispatchEvent(new Event('submit')); return true;})()")
            for _ in range(40):
                n = cdp.js("document.querySelectorAll('#chat li').length") or 0
                if n >= 1:
                    sent = True
                    break
                time.sleep(0.5)
        except Exception as ex:  # noqa: BLE001
            result["notes"].append("글 보내기 실패: " + str(ex)[:200])
        if not sent:
            cdp.js("(()=>{Chat.add('user','Hello from the check'); Chat.bot('This is a test answer.'); return true;})()")
            result["notes"].append("WebRTC 대화가 늦어 화면 코드로 글 한 줄을 넣음")
        else:
            for _ in range(30):          # 가짜 두뇌 답이 화면에 붙을 때까지(최대 15초)
                if (cdp.js("document.querySelectorAll('#chat li.bot').length") or 0) >= 1:
                    break
                time.sleep(0.5)
        time.sleep(1.0)
        snap("conversation_one", "대화(글 하나 보낸 뒤)")

        cdp.js("document.getElementById('nav-memory').click()")
        time.sleep(1.0)
        snap("memory", "기억")

        cdp.js("document.getElementById('nav-settings').click()")
        time.sleep(1.5)
        tabs = [("general", "설정:일반"), ("name", "설정:이름·호칭"), ("pet", "설정:펫"), ("brain", "설정:두뇌"),
                ("voice", "설정:목소리"), ("mic", "설정:마이크·스피커"), ("talk", "설정:대화"),
                ("interp", "설정:통역"), ("phone", "설정:폰 연결"), ("myvoice", "설정:내 목소리"), ("about", "설정:정보")]
        for tid, label in tabs:
            cdp.js("(()=>{const b=document.getElementById('set-tab-%s'); if(b) b.click(); return !!b;})()" % tid)
            time.sleep(2.0 if tid in ("brain", "voice", "phone", "myvoice", "about") else 1.3)
            snap("settings_" + tid, label)

        # 말싸움 켬 — 실제 세션이 있으면 말로 켠다(없으면 화면 표시만).
        cdp.js("document.getElementById('nav-main').click()")
        time.sleep(0.8)
        debate = False
        try:
            phrase = {"en": "let's argue", "ja": "口論しよう", "zh": "来吵架"}.get(lang, "let's argue")
            resp = cdp.js("fetch('/api/text',{method:'POST',headers:{'Content-Type':'application/json'},"
                          "body:JSON.stringify({text:%s})}).then(r=>r.json().then(j=>({ok:r.ok,j}))).catch(e=>({ok:false,j:String(e)}))" % json.dumps(phrase, ensure_ascii=False))
            result["notes"].append("말싸움 명령 응답: " + json.dumps(resp, ensure_ascii=False)[:200])
            for _ in range(40):          # 앞 차례 대답이 끝날 때까지 기다렸다가 바뀔 수 있음(최대 20초)
                debate = bool(cdp.js("(()=>{const b=document.getElementById('debate-badge'); return b && !b.hidden;})()"))
                if debate:
                    break
                time.sleep(0.5)
        except Exception as ex:  # noqa: BLE001
            result["notes"].append("말싸움 명령 실패: " + str(ex)[:200])
            debate = False
        if not debate:
            cdp.js("(()=>{const b=document.getElementById('debate-badge'); if(b){b.hidden=false; b.dataset.adult='0';} return true;})()")
            result["notes"].append("말싸움: 세션 명령이 닿지 않아 배지 표시만 확인")
        time.sleep(0.8)
        snap("debate_on", "말싸움 켬")

        # 통역 켬
        cdp.js("(()=>{ if(typeof Interp !== 'undefined'){ Interp.turn(true); return true; } return false; })()")
        for _ in range(20):          # 통역 칸이 뜰 때까지(최대 10초)
            if bool(cdp.js("(()=>{const b=document.getElementById('interp-box'); return b && !b.hidden;})()")):
                break
            time.sleep(0.5)
        time.sleep(1.0)
        snap("interp_on", "통역 켬")

        # 마법사 8단계 (?wizard=1 로 처음 화면을 다시 연다)
        cdp.call("Page.navigate", url=base + "?wizard=1")
        wait_ready(cdp, 15000)
        time.sleep(1.5)
        for i in range(8):
            end = time.time() + 8
            while time.time() < end:
                ok = cdp.js("(()=>{const c=document.getElementById('wz-card'); return !!c && c.dataset.step === String(%d);})()" % i)
                if ok:
                    break
                time.sleep(0.3)
            time.sleep(1.0)
            snap("wizard_step_%d" % i, "마법사 %d단계" % (i + 1))
            if i == 1:
                cdp.js("(()=>{const b=document.getElementById('wz-pack-false') || document.querySelector('#wz-body [id^=wz-pack-]'); if(b) b.click(); return true;})()")
            if i == 2:
                cdp.js("(()=>{const b=document.querySelector('#wz-body [id^=wz-honor-]'); if(b) b.click(); return true;})()")
            if i < 7:
                cdp.js("(()=>{const b=document.getElementById('wz-next'); if(b) b.click(); return true;})()")
                time.sleep(0.8)
        return result
    finally:
        if cdp is not None:
            cdp.close()
        if chrome_proc is not None:
            kill_tree(chrome_proc)
        if log is not None:
            try:
                log.close()
            except Exception:
                pass
        if srv is not None:
            kill_tree(srv)
        if not args.keep_profile:
            for _ in range(8):
                try:
                    shutil.rmtree(profile, ignore_errors=True)
                    if not os.path.isdir(profile):
                        break
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(0.4)


def main():
    ap = argparse.ArgumentParser(description="실제 크롬으로 en/ja/zh 화면의 남은 한글을 센다")
    ap.add_argument("--repo", default=ROOT)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--chrome", default=CHROME_DEFAULT)
    ap.add_argument("--langs", default=",".join(LANGS))
    ap.add_argument("--out", default="")
    ap.add_argument("--shots", default="")
    ap.add_argument("--work", default="")
    ap.add_argument("--keep-profile", action="store_true")
    a = ap.parse_args()
    a.repo = os.path.abspath(a.repo)
    if not a.work:
        a.work = tempfile.mkdtemp(prefix="kimbiseo-ui-hangul-")
        a.own_work = True
    else:
        os.makedirs(a.work, exist_ok=True)
        a.own_work = False
    allow = load_allow()
    brain_port = free_port()
    brain = start_brain(brain_port)
    results = []
    bad = 0
    try:
        for lang in [x.strip() for x in a.langs.split(",") if x.strip()]:
            print("[%s] 검사 시작" % lang, flush=True)
            r = run_lang(lang, a, brain_port, allow)
            results.append(r)
            for label, s in r["screens"].items():
                bad += s["left"]
                print("  %-18s 한글 %4d (허용 %d) 남음 %d" % (label, s["raw"], s["allowed"], s["left"]), flush=True)
                for b in s["bad"][:8]:
                    print("      - [%s] %s" % (b["kind"], b["value"][:100].replace("\n", " / ")), flush=True)
            for note in r["notes"]:
                print("  참고:", note, flush=True)
        data = {"ok": bad == 0, "langs": list(results), "work": a.work}
        if a.out:
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        print("합계: 남은 한글 %d %s" % (bad, "— 통과" if bad == 0 else "— 실패"), flush=True)
        return 0 if bad == 0 else 1
    finally:
        try:
            brain.shutdown()
        except Exception:  # noqa: BLE001
            pass
        if getattr(a, "own_work", False) and not a.keep_profile:
            # 결과 사진·JSON 을 밖에 적었다면 작업 폴더(서버 자료·프로필)는 지운다
            shutil.rmtree(a.work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())