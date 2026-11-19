# 0.1.9 단위 시험 — 구독 클로드 진짜 도구(MCP)·메모장 쓰기(type_text)·약속만 한 답 다시 묻기·도구 규칙·날씨 지명·가격 조사·
#   계산기 켜기·춤 부탁. python -m tests.unit.test_tools_019 (pytest tests/unit 로도 됨). 소리·두뇌 서버·인터넷·화면 없이 돈다
#   (김비서 메모 창은 가짜로 바꿔 끼움 — 실제 창을 띄우지 않음).
import asyncio
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import cli_mcp                 # noqa: E402
from app.core import config as C            # noqa: E402
from app.core import prompt                  # noqa: E402
from app.core.brain import (FILLER, RESCUE, after_tool_say, body_line, drop_promise_turns, fix_after_tool,  # noqa: E402
                            make_llm, self_intro_only)
from app.core.state import SessionState      # noqa: E402
from app.tools.basic import handlers         # noqa: E402
from app.tools.registry import ToolContext, load_packs  # noqa: E402

TT = handlers.typing
WEB = handlers.web
PC = handlers.pc


def cfg(**over):
    c = C.load(os.path.join(tempfile.mkdtemp(), "없음.json"), warn=lambda m: None)
    return C.deep_merge(c, over)


# ================================================================ 구독 클로드 MCP
class FakeBrain:
    def __init__(self):
        self.tool_specs = [{"type": "function", "function": {"name": "calc", "description": "계산",
                                                               "parameters": {"type": "object", "properties": {"expression": {"type": "string"}},
                                                                              "required": ["expression"]}}}]
        self.calls = []

    async def mcp_call(self, name, args):
        self.calls.append((name, args))
        return {"답": 2} if name == "calc" else {"오류": "그런 도구는 없어요."}


def test_mcp_auth_and_protocol():
    b = FakeBrain()
    tok = cli_mcp.bind(b)
    try:
        run = asyncio.run
        code, o = run(cli_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, "Bearer 틀림"))
        assert code == 401 and o["error"]["code"] == -32001
        code, o = run(cli_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, None))
        assert code == 401
        auth = "Bearer " + tok
        code, o = run(cli_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}, auth))
        assert code == 200 and o["result"]["protocolVersion"] == "2025-11-25" and "tools" in o["result"]["capabilities"]
        code, o = run(cli_mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}, auth))
        assert o["result"]["protocolVersion"] in cli_mcp.VERSIONS
        code, o = run(cli_mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, auth))
        assert code == 202 and o is None
        code, o = run(cli_mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "server/discover"}, auth))
        assert o["error"]["code"] == -32601
        code, o = run(cli_mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, auth))
        t = o["result"]["tools"][0]
        assert t["name"] == "calc" and t["inputSchema"]["required"] == ["expression"]
        code, o = run(cli_mcp.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "calc", "arguments": {"expression": "1+1"}}}, auth))
        assert b.calls == [("calc", {"expression": "1+1"})] and json.loads(o["result"]["content"][0]["text"]) == {"답": 2}
        assert o["result"]["isError"] is False
        code, o = run(cli_mcp.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "없음", "arguments": "글"}}, auth))
        assert o["result"]["isError"] is True and b.calls[-1] == ("없음", {})
        code, o = run(cli_mcp.handle([{"jsonrpc": "2.0", "id": 7, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/x"}], auth))
        assert code == 200 and len(o) == 1 and o[0]["id"] == 7
        code, o = run(cli_mcp.handle({"id": 8, "method": "ping"}, auth))
        assert o["error"]["code"] == -32600
    finally:
        cli_mcp.unbind(tok)
    assert asyncio.run(cli_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "Bearer " + tok))[0] == 401, "풀린 열쇠는 거절"


def _spawn_args(mcp):
    from app.core import cli_brain as CB
    got = {}
    old = CB.D.find, CB.D.command, CB._Proc, CB.workdir
    d = tempfile.mkdtemp()

    class P:
        def __init__(self, cmd, wd, env, tag):
            got["cmd"], got["env"] = cmd, env
            self.p = type("p", (), {"pid": 1})()

        def alive(self):
            return True

        def kill(self):
            pass
    CB.D.find = lambda name: "claude.exe"
    CB.D.command = lambda name, args, exe: [exe] + list(args)
    CB._Proc = P
    CB.workdir = lambda c: d
    try:
        be = CB.ClaudeCli(cfg())
        be.mcp = mcp
        be._spawn()
    finally:
        CB.D.find, CB.D.command, CB._Proc, CB.workdir = old
    return got


def test_claude_cli_spawn_args():
    g = _spawn_args(None)
    cmd = g["cmd"]
    assert "--safe-mode" in cmd and "--strict-mcp-config" in cmd and "--mcp-config" not in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and cmd[cmd.index("--setting-sources") + 1] == ""
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert g["env"].get("CLAUDE_CODE_DISABLE_CLAUDE_MDS") == "1" and g["env"].get("CLAUDE_CODE_DISABLE_AUTO_MEMORY") == "1"
    g = _spawn_args({"config": "x.json", "allowed": ["mcp__kimbiseo__calc", "mcp__kimbiseo__get_weather"]})
    cmd = g["cmd"]
    assert "--safe-mode" not in cmd, "--safe-mode 는 --mcp-config 를 꺼 버림"
    assert cmd[cmd.index("--mcp-config") + 1] == "x.json" and "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__kimbiseo__calc,mcp__kimbiseo__get_weather"
    assert cmd[cmd.index("--tools") + 1] == "", "클로드 자신의 명령·파일·웹 도구는 없음"


def test_cli_brain_mcp_config_and_release():
    from app.core import cli_brain as CB
    d = tempfile.mkdtemp()
    old_wd, old_port = CB.workdir, cli_mcp.PORT
    CB.workdir = lambda c: d
    cli_mcp.PORT = 18999
    try:
        c = cfg(두뇌={"방식": "claude_cli"})
        specs, hs = load_packs(c)
        br = CB.CliBrain(SessionState(c), c, "claude_cli", tool_names=[s["function"]["name"] for s in specs])
        assert br._mcp() is None, "도구를 아직 안 달았으면 글 약속으로"
        br.tool_specs = specs

        async def h(params):
            await params.result_callback({"답": 3})
        br.funcs = {"calc": h, "get_weather": h}
        m = br._mcp()
        assert m["allowed"] == ["mcp__kimbiseo__get_weather", "mcp__kimbiseo__calc"] or sorted(m["allowed"]) == ["mcp__kimbiseo__calc", "mcp__kimbiseo__get_weather"]
        j = json.load(open(m["config"], encoding="utf-8"))
        srv = j["mcpServers"]["kimbiseo"]
        assert srv["url"] == "http://127.0.0.1:18999" + cli_mcp.PATH and srv["headers"]["Authorization"].startswith("Bearer ")
        tok = srv["headers"]["Authorization"][7:]
        code, o = asyncio.run(cli_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                              "params": {"name": "calc", "arguments": {"expression": "1+2"}}}, "Bearer " + tok))
        assert code == 200 and json.loads(o["result"]["content"][0]["text"]) == {"답": 3} and br.mcp_calls == 1
        assert br._mcp()["config"] == m["config"], "같은 대화는 같은 열쇠"
        br.mcp_release()
        assert not os.path.exists(m["config"]), "대화가 끝나면 열쇠 파일 지움"
        assert asyncio.run(cli_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "Bearer " + tok))[0] == 401
    finally:
        CB.workdir, cli_mcp.PORT = old_wd, old_port


def test_prompt_native_guide_and_rules():
    old = cli_mcp.PORT
    try:
        c = cfg(두뇌={"방식": "claude_cli"})
        specs, _ = load_packs(c)
        cli_mcp.PORT = None
        a = prompt.system_prompt(c, specs)
        assert "<<도구이름" in a, "MCP 주소가 없으면 글 약속"
        cli_mcp.PORT = 18999
        b = prompt.system_prompt(c, specs)
        assert "<<" not in b and "kimbiseo" in b and "도구 쓰는 규칙" in b
    finally:
        cli_mcp.PORT = old
    loc = prompt.system_prompt(cfg(), specs)
    assert "도구 쓰는 규칙" in loc and "type_text" in loc and "calc 는 숫자가 있는 계산" in loc
    off = cfg(도구={"컴퓨터조작": {"켜기": False}})
    s2, _ = load_packs(off)
    names = {s["function"]["name"] for s in s2}
    assert "type_text" not in names and "pc_action" not in names
    r = prompt.tool_rules(s2)
    assert "type_text" not in r and "pc_action" not in r and "web_search" in r, "끈 도구를 말하는 규칙 줄은 뺌"
    assert prompt.tool_rules([]) == ""


# ================================================================ 메모장 쓰기(type_text) — 김비서 메모 창(가짜 창으로, 화면에 안 띄움)
class _FakeMemo:
    made = []

    def __init__(self, d):
        self.dir, self.path = d, TT.new_memo_name(d)
        self.body, self.closed, self.fronted = "", False, 0
        self.ready = __import__("threading").Event()
        self.ready.set()
        self.error = None
        _FakeMemo.made.append(self)

    def alive(self):
        return not self.closed

    def text(self):
        return self.body

    def append(self, body):
        add = ("\r\n" if self.body else "") + body.replace("\n", "\r\n")
        self.body += add
        return len(add)

    def ask_front(self):
        self.fronted += 1


def _fake_memo_window():
    saved = TT._new_window, TT._api
    TT._new_window = _FakeMemo
    TT._api = lambda: object()
    TT._S.memos.clear()
    _FakeMemo.made = []
    return saved


def _restore_memo(saved):
    TT._new_window, TT._api = saved
    TT._S.memos.clear()


def test_memo_window_open_and_type():
    d = tempfile.mkdtemp()
    saved = _fake_memo_window()
    try:
        r = TT.open_result(d)
        assert r["ok"] and r["새로_엶"] and len(_FakeMemo.made) == 1 and "메모" in r["말"]
        r = TT.open_result(d)
        assert r["ok"] and not r["새로_엶"] and len(_FakeMemo.made) == 1 and _FakeMemo.made[0].fronted == 1, "빈 창이 있으면 그 창을 앞으로"
        r = TT.type_memo("RTX 5090\n가격 정리", d)
        assert r["ok"] and not r["새로_엶"] and r["방법"] == "김비서 메모 창" and _FakeMemo.made[0].body == "RTX 5090\r\n가격 정리"
        r = TT.type_memo("둘째 줄", d)
        assert r["ok"] and _FakeMemo.made[0].body.endswith("\r\n둘째 줄")
        r = TT.open_result(d)
        assert r["새로_엶"] and len(_FakeMemo.made) == 2, "글이 있는 창 말고 새 창"
        r = TT.type_memo("새 메모", d, new=True)
        assert r["ok"] and r["새로_엶"] and len(_FakeMemo.made) == 3
        _FakeMemo.made[2].closed = True
        r = TT.type_memo("이어서", d)
        assert r["ok"] and _FakeMemo.made[1].body == "이어서", "닫힌 창은 건너뛰고 가장 최근의 열린 창"
        assert not os.listdir(d), "저장하기 전에는 파일을 만들지 않음"
        for _ in range(5):
            TT.type_memo("x", d, new=True)
        r = TT.type_memo("y", d, new=True)
        assert r["ok"] is False and "너무 많음" in r["이유"], "창은 5개까지"
    finally:
        _restore_memo(saved)


def test_memo_never_launches_windows_notepad():
    import subprocess
    d = tempfile.mkdtemp()
    saved = _fake_memo_window()
    old_popen = subprocess.Popen
    launched = []
    subprocess.Popen = lambda *a, **k: launched.append(a) or (_ for _ in ()).throw(OSError("막음"))
    c = cfg(도구={"글쓰기": {"메모_폴더": d}})
    try:
        r = asyncio.run(handlers.pc_action(ToolContext(SessionState(c), c), {"action": "open_program", "program": "notepad"}))
        assert r["ok"] and "메모" in r["말"]
        r = asyncio.run(handlers.type_text(ToolContext(SessionState(c), c), {"text": "회의 10시"}))
        assert r["ok"] and _FakeMemo.made[-1].body == "회의 10시"
        assert launched == [], "윈도우 메모장(notepad.exe)을 저절로 켜지 않음"
    finally:
        subprocess.Popen = old_popen
        _restore_memo(saved)


def test_memo_text_rules_and_save():
    t, cut = TT.clean_text("가" * 5000)
    assert len(t) == TT.MAX_CHARS and cut
    t, cut = TT.clean_text("a\x07b\r\nc\td", 100)
    assert t == "ab\nc\td" and not cut
    assert TT.type_memo("   ", tempfile.mkdtemp())["ok"] is False
    r = TT.type_memo("x" * 10, tempfile.mkdtemp(), limit=4, dry=True)
    assert r["ok"] and r["시험"] and r["쓸_글자"] == 4 and r["잘림"]
    assert TT.open_result(tempfile.mkdtemp(), dry=True)["시험"]
    d = tempfile.mkdtemp()
    p = os.path.join(d, "하위", "메모.txt")
    TT.save_file(p, "첫 줄\r\n둘째 줄\n셋째")
    assert open(p, "rb").read().decode("utf-8") == "첫 줄\r\n둘째 줄\r\n셋째" and not os.path.exists(p + ".kbtmp")
    a = TT.new_memo_name(d)
    assert os.path.basename(a).startswith(TT.MEMO_PREFIX) and a.endswith(".txt") and not os.path.exists(a)
    open(a, "w").close()
    assert TT.new_memo_name(d) != a, "있는 파일 이름은 피함"
    old = os.environ.get("KIMBISEO_MEMO_DIR")
    os.environ["KIMBISEO_MEMO_DIR"] = d
    try:
        assert TT.memo_dir("무시") == d
    finally:
        os.environ.pop("KIMBISEO_MEMO_DIR", None)
        if old:
            os.environ["KIMBISEO_MEMO_DIR"] = old
    assert TT.memo_dir("").endswith("김비서 메모") and TT.memo_dir("D:\\메모") == "D:\\메모"


def test_type_text_handler_limits():
    c = cfg(도구={"글쓰기": {"최대_글자": 99999}, "컴퓨터조작": {"시험_실행안함": True}})
    os.environ["KIMBISEO_PC_DRYRUN"] = "1"
    try:
        r = asyncio.run(handlers.type_text(ToolContext(SessionState(c), c), {"text": "가" * 9000}))
        assert r["ok"] and r["쓸_글자"] == 4000 and r["잘림"], "설정을 크게 해도 4000자까지"
        r = asyncio.run(handlers.pc_action(ToolContext(SessionState(c), c), {"action": "open_program", "program": "notepad"}))
        assert r["ok"] and r["열었을것"] == "김비서 메모"
    finally:
        os.environ.pop("KIMBISEO_PC_DRYRUN", None)


# ================================================================ 계산기 켜기 / 사이트 이름을 프로그램으로 부름
def test_calc_word_opens_calculator_program():
    c = cfg(도구={"컴퓨터조작": {"시험_실행안함": True}})
    ctx = ToolContext(SessionState(c), c)
    r = asyncio.run(handlers.calc(ctx, {"expression": "계산기"}))
    assert r.get("ok") and r.get("시험"), r
    r = asyncio.run(handlers.calc(ctx, {"expression": "계산기 켜"}))
    assert r.get("ok") and "답" not in r
    assert asyncio.run(handlers.calc(ctx, {"expression": "32000+14000"}))["답"] == 46000
    assert "오류" in asyncio.run(handlers.calc(ctx, {"expression": "사과"})), "숫자 없는 다른 글은 그냥 계산 오류"
    off = cfg(도구={"컴퓨터조작": {"켜기": False}})
    assert "오류" in asyncio.run(handlers.calc(ToolContext(SessionState(off), off), {"expression": "계산기"})), "컴퓨터 조작을 껐으면 안 켬"
    specs, _ = load_packs(c)
    d = next(s["function"]["description"] for s in specs if s["function"]["name"] == "calc")
    assert not d.startswith("계산기") and "calculator" in d


def test_pc_action_site_name_as_program():
    c = cfg()
    pc_ = c["도구"]["컴퓨터조작"]
    s, a = pc_.get("사이트") or {}, pc_.get("별명") or {}
    act, err = PC.from_llm({"action": "open_program", "program": "youtube"}, s, a)
    assert err is None and act["action"] == "open_url" and "youtube.com" in act["url"]
    act, err = PC.from_llm({"action": "open_program", "program": "유튜브"}, s, a)
    assert err is None and act["kind"] == "site"
    for bad in ("evil.com", "https://evil.com", "cmd", "powershell", "file:c:/x"):
        act, err = PC.from_llm({"action": "open_program", "program": bad}, s, a)
        assert act is None and err["ok"] is False, bad
    act, _ = PC.from_llm({"action": "open_program", "program": "calculator"}, s, a)
    assert act["program"] == "calculator"
    act, _ = PC.from_llm({"open_program": "calculator"}, s, a)          # 작은 두뇌가 동작 이름을 칸 이름으로 씀
    assert act["action"] == "open_program" and act["program"] == "calculator"
    act, _ = PC.from_llm({"action": "open_website", "engine": "youtube", "query": "유튜브"}, s, a)
    assert act["kind"] == "site" and "youtube.com" in act["url"]
    act, err = PC.from_llm({"action": "open_website", "query": "evil.com"}, s, a)
    assert act is None, "사이트 칸이 비면 사전 이름만 받음"
    act, err = PC.from_llm({"open_program": "cmd"}, s, a)
    assert act is None


# ================================================================ 약속만 한 답 다시 묻기 판단
def test_need_retry_rules():
    N = ["pc_action", "web_search", "type_text", "calc", "get_weather"]
    assert RESCUE.is_promise("네, 메모장을 열어 드릴게요.") and not RESCUE.is_promise("내일은 맑아요.")
    assert RESCUE.wants_action("메모장 열어줘") and not RESCUE.wants_action("춤 춰 줘") and not RESCUE.wants_action("안녕")
    assert RESCUE.strong_action("계산기 켜 줘") and RESCUE.strong_action("3+4 얼마야") and not RESCUE.strong_action("요즘 어때 알려줘")
    assert RESCUE.need_retry("메모장 열어줘", "메모장을 열어 드릴게요.", "", N)
    assert RESCUE.need_retry("메모장 열어줘", "메모장을 열었습니다.", "", N), "켰다고 거짓말(도구 없음)도 다시"
    assert not RESCUE.need_retry("안녕", "안녕하세요!", "", N)
    assert not RESCUE.need_retry("춤 좀 춰 줘", "네, 춰 볼게요!", "", N), "몸동작은 도구가 아님"
    assert RESCUE.need_retry("날씨 알려줘", "", "", N, dropped=True)
    assert RESCUE.need_retry("RTX 5090 찾아서 메모장에 정리해 줘", "가격은 이래요", "", N, after_tool=True, called=["web_search"])
    assert not RESCUE.need_retry("RTX 5090 찾아서 메모장에 정리해 줘", "다 적었어요", "", N, after_tool=True, called=["web_search", "type_text"])
    assert not RESCUE.need_retry("부산 날씨 어때", "맑아요", "", N, after_tool=True, called=["get_weather"]), "결과 뒤엔 같은 도구 또 안 부름"
    assert not RESCUE.need_retry("메모장 열어줘", "켰어요", "", N, called=["pc_action"])


def _conv(user, name, res, args=None):
    return [{"role": "user", "content": user},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function", "function": {
                "name": name, "arguments": json.dumps(args or {}, ensure_ascii=False)}}]},
            {"role": "tool", "content": json.dumps(res, ensure_ascii=False)}]


def test_fix_after_tool():
    """녹화·성공률 시험에서 본 나쁜 답들 — 행동 도구 결과 뒤에만 고침."""
    calc = _conv("3만2천 더하기 1만4천은 얼마야?", "calc", {"식": "32000+14000", "답": 46000})
    assert fix_after_tool("안녕하세요.", calc, "3만2천 더하기 1만4천은 얼마야?", "김비서") == "답은 46,000이에요."
    assert fix_after_tool("4만 6천이에요.", calc, "3만2천 더하기 1만4천은 얼마야?", "김비서") is None
    assert fix_after_tool("김비서입니다. 답은 4만 6천이에요.", calc, "x", "김비서") == "답은 4만 6천이에요."
    pc_ = _conv("계산기 켜 줘", "pc_action", {"ok": True, "말": "계산기 켰어요."})
    assert fix_after_tool("계산기 켜 줘", pc_, "계산기 켜 줘", "김비서") == "계산기 켰어요.", "사용자 말 따라 하기"
    srch = _conv("네이버에서 부산 날씨 검색해 줘", "pc_action", {"ok": True, "말": "네이버에서 부산 날씨 검색 화면을 열었어요."})
    assert fix_after_tool("부산은 맑고 12도예요.", srch, "네이버에서 부산 날씨 검색해 줘", "김비서") == "네이버에서 부산 날씨 검색 화면을 열었어요.", \
        "검색 화면만 열었는데 날씨 숫자를 지어냄"
    memo = _conv("메모장에 내일 열 시 회의라고 적어 줘", "type_text", {"ok": True, "말": "메모장에 적었어요."}, {"text": "내일 10시 회의"})
    assert fix_after_tool("메모장에 내일 10시 회의라고 적었어요.", memo, "메모장에 내일 열 시 회의라고 적어 줘", "김비서") is None, "적은 글의 숫자는 됨"
    assert fix_after_tool("잠깐만요.", memo, "x", "김비서") == "메모장에 적었어요."
    rem = _conv("내가 커피를 좋아한다고 기억해 줘", "remember", {"ok": True, "저장": True})
    assert fix_after_tool("기억해 줘", rem, "내가 커피를 좋아한다고 기억해 줘", "김비서") == "기억할게요.", "부탁 끝만 따라 하기"
    assert fix_after_tool("기억할게요.", rem, "내가 커피를 좋아한다고 기억해 줘", "김비서") is None
    wx = _conv("내일 날씨", "get_weather", {"장소": "부산"})
    assert fix_after_tool("안녕하세요.", wx, "내일 날씨", "김비서") is None, "조사 도구 뒤 긴 답은 건드리지 않음(흘려보냄)"
    assert fix_after_tool("다 했어요", [{"role": "user", "content": "x"}], "x", "김비서") is None


def test_history_and_fallback_helpers():
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": "크롬 열어줘"}, {"role": "assistant", "content": "네, 크롬을 열어 드릴게요."},
            {"role": "user", "content": "날씨 알려줘"}, {"role": "assistant", "content": "날씨 볼게요.", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "{}"}, {"role": "assistant", "content": "맑아요."},
            {"role": "user", "content": "메모장 열어줘"}]
    out = drop_promise_turns(msgs)
    assert [m["content"] for m in out if m["role"] == "user"] == ["날씨 알려줘", "메모장 열어줘"], "약속만 한 차례만 뺌"
    assert drop_promise_turns(msgs[-1:]) == msgs[-1:]
    t = lambda r: [{"role": "tool", "content": json.dumps(r, ensure_ascii=False)}]   # noqa: E731
    assert after_tool_say(t({"식": "1+1", "답": 46000})) == "답은 46,000이에요."
    assert after_tool_say(t({"ok": True, "말": "메모장 켰어요."})) == "메모장 켰어요."
    assert after_tool_say(t({"ok": True, "말": "(시험이라 실제로 열지 않음) 메모장"})) == "다 했어요."
    assert after_tool_say(t({"저장": True})) == "기억할게요." and after_tool_say([{"role": "user", "content": "x"}]) == ""
    assert self_intro_only("김비서입니다.", "김비서") and self_intro_only("안녕하세요. 김비서입니다. 무엇을 도와드릴까요?", "김비서")
    assert not self_intro_only("4만6천입니다.", "김비서") and not self_intro_only("김비서입니다.", "")
    assert FILLER.fullmatch("잠깐만요.") and FILLER.fullmatch("네, 잠시만요…") and not FILLER.fullmatch("네, 춰 볼게요!")


# ================================================================ BrainLLM: 다시 묻기 흐름·춤 한마디
def _run_brain(user, passes, c=None):
    """passes = [첫 답 조각들, 다시 물었을 때 조각들(또는 'call')] → (내보낸 글, 실행한 호출, 다시 물을 때 tool_choice 강제였나)."""
    from pipecat.frames.frames import FunctionCallFromLLM
    from pipecat.services.openai.llm import OpenAILLMService
    c = c or cfg()
    llm = make_llm(SessionState(c), c, ["pc_action", "calc", "type_text", "web_search", "get_weather"])
    sent, ran, forced = [], [], []
    step = {"i": 0}

    async def fake_parent(self, context):
        p = passes[min(step["i"], len(passes) - 1)]
        step["i"] += 1
        forced.append(self._force_tool)
        if p == "call":
            await self.run_function_calls([FunctionCallFromLLM(context=context, tool_call_id="t1", function_name="pc_action",
                                                               arguments={"action": "open_program", "program": "notepad"})])
            return
        for x in p:
            await self._push_llm_text(x)

    async def fake_push(self, text):
        sent.append(text)

    async def fake_run(self, calls):
        ran.extend(x.function_name for x in calls)

    old = OpenAILLMService._process_context, OpenAILLMService._push_llm_text, OpenAILLMService.run_function_calls
    OpenAILLMService._process_context, OpenAILLMService._push_llm_text, OpenAILLMService.run_function_calls = fake_parent, fake_push, fake_run

    class Ctx:
        messages = [{"role": "system", "content": "x"}, {"role": "user", "content": user}]
    try:
        asyncio.run(llm._process_context(Ctx()))
    finally:
        OpenAILLMService._process_context, OpenAILLMService._push_llm_text, OpenAILLMService.run_function_calls = old
    return "".join(sent), ran, forced


def test_brainllm_retry_does_not_speak_twice():
    said, ran, forced = _run_brain("메모장 열어줘", [["메모장을 열었습니다."], "call"])
    assert ran == ["pc_action"] and forced == [False, True] and said == "", (said, ran, forced)
    said, ran, forced = _run_brain("메모장 열어줘", [["메모장 열게요. "], "call"])
    assert ran == ["pc_action"] and "열게요" not in said
    said, ran, forced = _run_brain("메모장 열어줘", ["call"])
    assert ran == ["pc_action"] and forced == [False], "처음부터 부르면 다시 안 물음"
    said, ran, forced = _run_brain("안녕", [["안녕하세요! "], ["반가워요."]])
    assert said == "안녕하세요! " and forced == [False], "잡담은 바로 흘려보냄"
    said, ran, forced = _run_brain("메모장 열어줘", [["메모장 열게요."], ["열었어요."]])
    assert said == "열었어요." and ran == [] and len(forced) == 2


def test_brainllm_dance_line():
    said, ran, forced = _run_brain("춤 한 번 보여 줘", [["잠깐만요."]])
    assert said == "네, 춰 볼게요!" and ran == [] and forced == [False], said
    said, _, _ = _run_brain("춤 좀 춰 줘", [[""]])
    assert said == "네, 춰 볼게요!"
    said, _, _ = _run_brain("춤 좀 춰 줘", [["좋아요, ", "신나게 춰 볼게요~"]])
    assert said == "좋아요, 신나게 춰 볼게요~", "두뇌가 제대로 답하면 그대로"
    said, _, _ = _run_brain("춤 좀 춰 줘", [[""]], c=cfg(화면={"얼굴": "기본"}))
    assert said == "", "펫이 아니면 몸동작 한마디 없음"
    assert body_line(cfg(), "춤 한 번 보여 줘") == "네, 춰 볼게요!" and body_line(cfg(), "계산기 켜 줘") == ""


def test_dance_phrases():
    from app.pet_link.face import motion_for
    for t in ("춤 한 번 보여 줘", "춤 좀 춰 줘", "춤춰", "춤 춰 볼래?", "댄스 타임", "신나게 한번 춰 봐", "춤 출 수 있어?", "한 곡 춰 줘",
              "김비서 춤"):
        assert motion_for(t, ["김비서"]) == "dance", t
    for t in ("춤 추지 마", "춤 그만", "요즘 유행하는 춤이 뭐야", "계산기 켜 줘"):
        assert motion_for(t, ["김비서"]) != "dance", t


def test_named_dance_phrases():
    from app.pet_link.face import motion_for, motion_line, motion_for_reply
    # 말한 춤 이름을 그대로 펫에 넘긴다(펫이 그 옷에 없으면 기본 춤으로 대신 춤)
    cases = {
        "dance_zerotwo": ("제로투 춰줘", "제로투 춤 보여 줘", "Zero Two dance", "zero-two dancing", "ゼロツー踊って",
                          "零二跳舞", "제로투"),
        "dance_bad": ("BAD 춰줘", "bad dance", "배드 춤 춰 줘", "バッド踊って", "에스텔라 말고 BAD 춰줘"),
        "dance_estella": ("에스텔라 춰줘", "Estella dance", "エステラ踊って", "에스텔라 춤"),
    }
    for want, texts in cases.items():
        for t in texts:
            assert motion_for(t, ["김비서"]) == want, (t, motion_for(t, ["김비서"]))
    assert motion_for("댄스 타임", ["김비서"]) == "dance", "이름 없는 춤은 기본 춤"
    assert motion_for("dance", ["김비서"]) == "dance"
    assert motion_for("제로투 춤 추지 마", ["김비서"]) != "dance_zerotwo", "안 춘다고 하면 빼기"
    assert motion_line("제로투 춰줘") == "네, 춰 볼게요!"
    assert motion_for_reply("네, 제로투 출게요.") == "dance_zerotwo"
    assert motion_for_reply("네, BAD 춰 볼게요.") == "dance_bad"
    assert motion_for_reply("네, 춤 출게요.") == "dance"


# ================================================================ 날씨 지명·가격 조사(인터넷 없이)
def test_geocode_korea_first():
    tries = WEB._geo_tries("광주", "광주")
    assert [x["name"] for x in tries] == ["광주시", "광주군", "광주", "광주"] and all(x.get("countryCode") == "KR" for x in tries[:3])
    assert "countryCode" not in tries[-1], "마지막에만 나라 제한 없이(외국 도시)"

    class R:
        def __init__(self, res):
            self.res = res

        def json(self):
            return {"results": self.res}

    class Cl:
        def __init__(self, table):
            self.table, self.asked = table, []

        async def get(self, url, params=None):
            self.asked.append(params)
            return R(self.table.get((params.get("name"), params.get("countryCode")), []))
    kp = {"name": "청진", "country_code": "KP", "country": "북한", "latitude": 41.8, "longitude": 129.8}
    kr = {"name": "어딘가", "country_code": "KR", "latitude": 36.1, "longitude": 127.1}
    cl = Cl({("어딘가", None): [kp, kr]})
    label, ll = asyncio.run(WEB._geocode(cl, "어딘가"))
    assert ll == (36.1, 127.1), "같은 이름 북한 지명은 고르지 않음"
    cl = Cl({("어떤곳", None): [kp]})
    assert asyncio.run(WEB._geocode(cl, "어떤곳"))[1] is None, "북한 지명뿐이면 못 찾음"
    cl = Cl({("북한 청진", None): [kp]})
    assert asyncio.run(WEB._geocode(cl, "북한 청진"))[1] == (41.8, 129.8), "북한을 말하면 고름"
    assert asyncio.run(WEB._geocode(Cl({}), "서울"))[1] == WEB.CITIES["서울"]
    jp = {"name": "도쿄", "country_code": "JP", "country": "일본", "latitude": 35.6, "longitude": 139.6}
    label, ll = asyncio.run(WEB._geocode(Cl({("도쿄", None): [jp]}), "도쿄"))
    assert ll == (35.6, 139.6) and label == "일본 도쿄"


def test_price_helpers_and_danawa_parser():
    assert WEB._product_query("RTX 5090 요즘 가격 조사해서 정리해 줘") == "RTX 5090"
    assert WEB._has_money({"결과": [{"제목": "RTX 5090 349만 원"}]}) and not WEB._has_money({"결과": [{"제목": "RTX 5090 출시"}]})
    lines = WEB._money_lines("짧음\nRTX 5090 최저가는 3,490,000원입니다\n관계 없는 줄입니다")
    assert lines == ["RTX 5090 최저가는 3,490,000원입니다"]
    page = "\n".join([
        "RTX 5090 관련기사", "1,000,000원",
        "ASUS ROG Astral 지포스 RTX 5090 O32G", "12%5,490,000원", "4,830,000원",
        "MSI 지포스 RTX 5090 게이밍 트리오 OC D7 32GB", "4,290,000원",
        "GIGABYTE 지포스 RTX 5090 WINDFORCE OC", "4,050,000원",
        "RTX 5090 쿨러 브래킷", "9,900원",
    ])

    async def fake_fetch(cfg_, url, ua=None, raw=False):
        assert "search.danawa.com" in url and "RTX%205090" in url
        return {"본문": page}
    old = WEB._fetch_text
    WEB._fetch_text = fake_fetch
    try:
        r = asyncio.run(WEB.danawa_prices({}, "RTX 5090 요즘 가격 조사해서 정리해 줘"))
    finally:
        WEB._fetch_text = old
    assert r and r["출처"] == "다나와", r
    assert r["가격대"] == "405만 원~483만 원", r["가격대"]
    assert not any("관련기사" in x or "브래킷" in x for x in r["상품"]), "기사·싼 부품(가격대에서 크게 벗어난 값)은 뺌"


def main():
    fails = 0
    for k, f in list(globals().items()):
        if k.startswith("test_") and callable(f):
            try:
                f()
                print("됨  ", k)
            except Exception as ex:  # noqa: BLE001
                fails += 1
                import traceback
                traceback.print_exc()
                print("안 됨", k, ex.__class__.__name__, ex)
    print("실패", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
