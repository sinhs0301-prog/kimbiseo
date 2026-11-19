# 두뇌 바꾸기 시험 — 0.1.18 사용자 제보(로컬 llm 으로 바꾸면 대화에 바로 적용 안 됨·두뇌 연결 안 됨).
#   ① 설정을 바꾸면 지금 대화의 두뇌 부품을 새로 만들어 파이프라인에서 갈아 끼우는지
#   ② 바꾼 직후 '다음 말'이 새 두뇌로 가는지(옛 두뇌 서버에 더 요청하지 않는지)
#   ③ 로컬 두뇌가 없을 때 까닭(프로그램/모델 없음·메모리·포트·시간)을 나눠 알려 주는지
#   ④ 새 안내 글이 en/ja/zh 로 나오는지
#   pytest 없이도 돈다: python -B -m tests.unit.test_brain_switch
import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import brainserver, config as C, i18n, settings_api as S   # noqa: E402
from app.core.brain import make_llm                                  # noqa: E402
from app.core.session import Session                                # noqa: E402
from app.core.state import SessionState                             # noqa: E402
from app.tools.registry import ToolContext                          # noqa: E402
from pipecat.processors.aggregators.llm_context import LLMContext   # noqa: E402


def cfg(**over):
    c = C.load(os.path.join(tempfile.mkdtemp(), "없음.json"), warn=lambda m: None)
    return C.deep_merge(c, over)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class FakeBrain(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    answer = "A"
    hits = 0
    lock = threading.Lock()

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.split("?")[0].endswith("/health"):
            return self._json(200, {"status": "ok"})
        return self._json(200, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        with type(self).lock:
            type(self).hits += 1
        if not self.path.split("?")[0].endswith("/chat/completions"):
            return self._json(200, {})
        text = self.answer
        if not body.get("stream"):
            return self._json(200, {"id": "f", "object": "chat.completion", "model": "fake",
                                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                                 "finish_reason": "stop"}]})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        j = {"id": "f", "object": "chat.completion.chunk", "model": "fake",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]}
        self.wfile.write(("data: " + json.dumps(j, ensure_ascii=False) + "\n\n").encode("utf-8"))
        j2 = {"id": "f", "object": "chat.completion.chunk", "model": "fake",
              "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        self.wfile.write(("data: " + json.dumps(j2, ensure_ascii=False) + "\n\ndata: [DONE]\n\n").encode("utf-8"))
        self.wfile.flush()
        self.close_connection = True


def start_fake(answer):
    port = free_port()
    cls = type("B_" + answer, (FakeBrain,), {"answer": answer, "hits": 0,
                                             "lock": threading.Lock()})
    srv = ThreadingHTTPServer(("127.0.0.1", port), cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port, cls


class FakeProc:
    def __init__(self, kind):
        self.kind = kind
        self._setup = None
        self._prev = None
        self._next = None

    def link(self, other):
        self._next = other
        other._prev = self


class FakePipeline:
    def __init__(self, procs):
        self._processors = list(procs)


def session_for(c, st, llm):
    s = Session.__new__(Session)
    s.cfg, s.state, s.sid, s.guards, s.llm = c, st, "t", {}, llm
    s.specs, s.handlers = [], {}
    s.tool_ctx = ToolContext(st, c, None, {})
    s.pipeline, s.context, s.opts = None, None, {}
    s.cli, s._retired = False, []
    return s


def test_switch_changes_live_llm():
    a, b = start_fake("A"), start_fake("B")
    try:
        ca = cfg(두뇌={"방식": "url", "주소": f"http://127.0.0.1:{a[1]}/v1", "모델": "a"})
        st = SessionState(ca, lambda ev: None)
        s = session_for(ca, st, make_llm(st, ca, [], {}, session_key="t"))
        assert s.llm.kind == "url"
        cb = C.deep_merge(ca, {"두뇌": {"주소": f"http://127.0.0.1:{b[1]}/v1", "모델": "b"}})
        s.cfg = cb
        done = asyncio.run(s.apply_settings(["두뇌.방식", "두뇌.주소", "두뇌.모델"]))
        assert "두뇌" in done, done
        assert s.llm.kind == "url" and str(s.llm._client.base_url).startswith(f"http://127.0.0.1:{b[1]}/")
    finally:
        a[0].shutdown()
        b[0].shutdown()


def test_next_turn_uses_new_brain():
    a, b = start_fake("A"), start_fake("B")
    try:
        ca = cfg(두뇌={"방식": "url", "주소": f"http://127.0.0.1:{a[1]}/v1", "모델": "a", "첫응답_제한_초": 5})
        st = SessionState(ca, lambda ev: None)
        llm = make_llm(st, ca, [], {}, session_key="t")
        s = session_for(ca, st, llm)
        ctx1 = LLMContext(messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "안녕"}])
        asyncio.run(llm._process_context(ctx1))
        assert "A" in "".join(llm._said), llm._said
        assert a[2].hits == 1, a[2].hits
        cb = C.deep_merge(ca, {"두뇌": {"주소": f"http://127.0.0.1:{b[1]}/v1", "모델": "b"}})
        s.cfg = cb
        asyncio.run(s.apply_settings(["두뇌.방식", "두뇌.주소"]))
        ctx2 = LLMContext(messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "또 안녕"}])
        asyncio.run(s.llm._process_context(ctx2))
        assert "B" in "".join(s.llm._said), s.llm._said
        assert b[2].hits == 1, b[2].hits
        assert a[2].hits == 1, "바꾼 뒤 옛 두뇌에 또 물으면 안 됨"
    finally:
        a[0].shutdown()
        b[0].shutdown()


def test_local_reasons_and_language():
    old = i18n.current()
    try:
        p = free_port()
        c = cfg(두뇌={"방식": "local", "주소": f"http://127.0.0.1:{p}/v1"},
                실행={"두뇌_실행파일": "", "두뇌_모델": ""},
                포트={"두뇌": p})
        ok, code, detail = asyncio.run(brainserver.ensure_local(c))
        assert not ok and code == "exe_missing", (ok, code, detail)

        c2 = cfg(두뇌={"방식": "local", "주소": f"http://127.0.0.1:{p}/v1"},
                 실행={"두뇌_실행파일": sys.executable, "두뇌_모델": os.path.join(tempfile.gettempdir(), "없는모델.gguf")},
                 포트={"두뇌": p})
        ok2, code2, _ = asyncio.run(brainserver.ensure_local(c2))
        assert not ok2 and code2 == "model_missing", (ok2, code2)

        i18n.set_lang("en")
        for code3 in ("exe_missing", "model_missing", "port_busy", "memory", "timeout", "start_failed", "not_running"):
            msg = brainserver.explain(code3, "", c)
            assert msg and not any("가" <= ch <= "힣" for ch in msg), (code3, msg)
        assert "connect" in brainserver.describe_exception(ConnectionError("x"), c).lower()
        assert "time" in brainserver.describe_exception(TimeoutError("x"), c).lower() or \
               "moment" in brainserver.describe_exception(TimeoutError("x"), c).lower()
    finally:
        i18n.set_lang(old)


def test_new_messages_translated():
    keys = ["두뇌 주소에 연결하지 못했어요. 주소와 서버가 켜져 있는지 확인해 주세요.",
            "두뇌 준비 중({0}초)", "메모리가 부족해 두뇌를 켜지 못했어요. 다른 프로그램을 닫고 다시 말해 주세요.",
            "두뇌 프로그램(llama-server)이 없어요. 설정 → 두뇌에서 'Gemma 설치'를 눌러 받아 주세요."]
    for lang in ("en", "ja", "zh"):
        for k in keys:
            got = i18n.tr(k, lang=lang)
            assert got != k and not any("가" <= ch <= "힣" for ch in got), (lang, k, got)


def test_brain_fields_immediate():
    for k in ("두뇌.방식", "두뇌.주소", "두뇌.모델", "두뇌.호환_주소", "두뇌.호환_모델"):
        assert S.FIELDS[k][1] == "즉시", (k, S.FIELDS[k][1])


def main():
    fails = 0
    for k, f in list(globals().items()):
        if k.startswith("test_") and callable(f):
            try:
                f()
                print("됨  ", k)
            except Exception as ex:  # noqa: BLE001
                fails += 1
                print("안 됨", k, ex.__class__.__name__, ex)
    print("실패", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())