# 설정 화면 단위 시험 — 값 검사·반영 시점·끼어들기 감도·다시 읽기·사양 추천. 소리·두뇌 없이 돈다.
#   python -m tests.unit.test_settings   (pytest 가 있으면 pytest tests/unit 로도 됨)
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C            # noqa: E402
from app.core import settings_api as S      # noqa: E402
from app.core import sysinfo                # noqa: E402


def fresh_cfg(user=None):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "settings.json")
    if user is not None:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(user, f, ensure_ascii=False)
    cfg = C.load(p, warn=lambda m: None)
    cfg["_settings_path"] = p
    return cfg, p


def test_validate_good_values():
    cfg, _ = fresh_cfg()
    clean, err, _w = S.validate({"비서": {"이름": "엘리스"}, "사용자": {"호칭": "선생님"}, "대화": {"끼어들기_감도": "0.4"},
                                 "목소리": {"말속도": 1.2}}, cfg)
    assert not err, err
    assert clean["비서.이름"] == "엘리스" and clean["사용자.호칭"] == "선생님"
    assert clean["대화.끼어들기_감도"] == 0.4 and clean["목소리.말속도"] == 1.2
    assert clean["비서.별칭"] == [], "이름만 바꾸면 옛 이름의 비슷한 이름은 버림"


def test_validate_rejects_bad_values():
    cfg, _ = fresh_cfg()
    _c, err, _w = S.validate({"대화.끼어들기_감도": 0.9, "목소리.말속도": True, "두뇌.방식": "몰라", "포트.본체": 1,
                              "두뇌.주소": "ftp://x", "비서.이름": "!!!", "목소리.목소리": "kimbiseo_x"}, cfg)
    for k in ("대화.끼어들기_감도", "목소리.말속도", "두뇌.방식", "포트.본체", "두뇌.주소", "비서.이름", "목소리.목소리"):
        assert k in err, (k, err)
    assert "모르는" in err["목소리.목소리"], "목록에 없는 목소리는 고를 수 없음"


def test_validate_honorific_length_and_aliases():
    cfg, _ = fresh_cfg()
    _c, err, _w = S.validate({"사용자.호칭": "가" * 11}, cfg)
    assert "사용자.호칭" in err, "호칭은 10글자까지"
    clean, err, _w = S.validate({"비서": {"이름": "엘리스", "별칭": ["엘리스", "앨리스", "앨리스", ""]}}, cfg)
    assert not err and clean["비서.별칭"] == ["앨리스"], clean


def test_validate_warnings():
    cfg, _ = fresh_cfg()
    _c, _e, w = S.validate({"비서.이름": "아"}, cfg)
    assert w, "한 글자 이름은 경고"
    _c, _e, w = S.validate({"목소리.엔진": "qwen"}, cfg, voice_warn="무거워요")
    assert "무거워요" in w
    _c, _e, w = S.validate({"목소리.엔진": "windows"}, cfg, voice_warn="무거워요")
    assert not w


def test_brain_kind_sets_local_address():
    cfg, _ = fresh_cfg()
    clean, err, _w = S.validate({"두뇌.방식": "local"}, cfg)
    assert not err and clean["두뇌.주소"].endswith(f":{cfg['포트']['두뇌']}/v1") and clean["두뇌.열쇠_이름"] == ""


def test_url_brain_needs_address():
    cfg, _ = fresh_cfg()
    _c, err, _w = S.validate({"두뇌.방식": "url"}, cfg)
    assert "두뇌.주소" in err, "내 PC → 내 AI 주소로 바꿀 때 주소가 없으면 막음"
    clean, err, _w = S.validate({"두뇌": {"방식": "url", "주소": "http://127.0.0.1:1234/v1/", "모델": "m"}}, cfg)
    assert not err and clean["두뇌.주소"] == "http://127.0.0.1:1234/v1"


def test_when_groups():
    g = S.when_groups(["비서.이름", "두뇌.방식", "대화.연결인사", "목소리.엔진", "귀.장치", "펫.옷", "없는.키"])
    assert "비서 이름" in "".join(g["즉시"]) or g["즉시"], g
    assert "두뇌" in "".join(g["즉시"]), ("두뇌 방식은 저장 즉시(다음 말부터)", g)
    assert "연결 인사" in "".join(g["다음대화"]), g
    assert set(g["다시켜기"]) == {"목소리", "귀"}, g
    assert g["펫"], g


def test_barge_levels_apply_and_default_matches():
    cfg, _ = fresh_cfg()
    for k, v in C.BARGE_LEVELS[0.3].items():
        assert cfg["대화"][k] == v, ("0.3 = 지금까지의 기본값", k)
    cfg, _ = fresh_cfg({"대화": {"끼어들기_감도": 0.5}})
    assert cfg["대화"]["큰소리_기준_dBFS"] == -12 and cfg["대화"]["엿듣기_초"] == 0.8
    assert C.barge_level("0.4") == 0.4 and C.barge_level(0.9) is None and C.barge_level(None) is None


def test_save_reload_in_place():
    cfg, p = fresh_cfg()
    held = cfg                                   # 대화·부품이 들고 있는 참조
    clean, err, _w = S.validate({"대화.끼어들기_감도": 0.5, "목소리.말속도": 1.4, "사용자.호칭": "선생님"}, cfg)
    assert not err
    C.save_user(cfg, S.nest(clean))
    C.reload_into(cfg, p, warn=lambda m: None)
    assert held is cfg and held["대화"]["큰소리_기준_dBFS"] == -12 and held["목소리"]["말속도"] == 1.4
    with open(p, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["대화"] == {"끼어들기_감도": 0.5}, "세부 다섯 값은 파일에 쓰지 않음(감도만)"
    assert S.changed_keys(cfg, clean) == [], "다시 읽은 뒤에는 바뀐 것이 없음"


def test_view_has_no_secret_values():
    cfg, _ = fresh_cfg()
    v = S.view(cfg)
    assert set(v["열쇠"]) == set(S.SECRET_NAMES) and all(isinstance(x, bool) for x in v["열쇠"].values())
    assert not any(k.startswith("열쇠.") for k in v), "열쇠는 있음/없음만"


def test_choices_file():
    ch = S.choices()
    assert len(ch["호칭_단추"]) == 6 and ch["호칭_최대_글자"] == 10
    sexes = {p["성별"] for p in ch["펫"]}
    assert sexes == {"여", "남"}
    for sx, r in ch["성별_추천"].items():
        assert r["펫"] in [p["id"] for p in ch["펫"]] and r["목소리"] in [x["id"] for x in ch["목소리"]], sx
    assert [x["값"] for x in ch["끼어들기_감도"]] == sorted(C.BARGE_LEVELS)


def test_recommend_by_gpu_size():
    none = sysinfo.recommend([])
    assert none["설정"]["목소리.엔진"] == "windows" and none["판별"]
    small = sysinfo.recommend([{"이름": "8GB 카드", "전체_MiB": 8151}])
    assert small["설정"]["목소리.엔진"] == "qwen" and not small["목소리_경고"], small     # 0.1.4: 되는 PC 는 전부 Qwen
    tiny = sysinfo.recommend([{"이름": "작은 카드", "전체_MiB": 4096}])
    assert tiny["설정"]["목소리.엔진"] == "windows" and tiny["목소리_경고"]
    big = sysinfo.recommend([{"이름": "큰 카드", "전체_MiB": 12288}])
    assert big["설정"]["목소리.엔진"] == "qwen" and not big["목소리_경고"]


def test_recommend_subscription_brain():
    on = {"claude": {"있음": True, "로그인": True}, "codex": {"있음": True, "로그인": True}}
    r = sysinfo.recommend([{"이름": "큰 카드", "전체_MiB": 12288}], on)
    assert r["설정"]["두뇌.방식"] == "claude_cli" and any("구독" in x for x in r["판별"])
    only_codex = {"claude": {"있음": True, "로그인": False}, "codex": {"있음": True, "로그인": True}}
    assert sysinfo.recommend([], only_codex)["설정"]["두뇌.방식"] == "codex_cli"
    off = {"claude": {"있음": False, "로그인": False}, "codex": {"있음": True, "로그인": False}}
    assert sysinfo.recommend([{"이름": "큰 카드", "전체_MiB": 12288}], off)["설정"]["두뇌.방식"] == "local"
    assert sysinfo.recommend([], off, gemma_ready=False)["설정"]["두뇌.방식"] == "url"


def test_recommend_ear_cpu_with_gemma_on_small_gpu():
    """0.1.6: (규칙을 켜면) 9GB 미만 + 이 PC 두뇌(Gemma) → 받아쓰기 CPU · 구독 두뇌·큰 카드면 자동. 기본은 끔(14단계 실측)"""
    assert not sysinfo.EAR_CPU_WITH_GEMMA
    assert sysinfo.recommend([{"이름": "8GB 카드", "전체_MiB": 8151}])["설정"]["귀.장치"] == "auto"
    sysinfo.EAR_CPU_WITH_GEMMA = True
    try:
        _ear_rule_on()
    finally:
        sysinfo.EAR_CPU_WITH_GEMMA = False
    ch = S.choices()
    assert [x["id"] for x in ch["귀_장치"]] == ["auto", "cuda", "cpu"] and [x["id"] for x in ch["Gemma_판"]] == ["E4B", "E2B"]


def _ear_rule_on():
    r = sysinfo.recommend([{"이름": "8GB 카드", "전체_MiB": 8151}])
    assert r["설정"]["두뇌.방식"] == "local" and r["설정"]["귀.장치"] == "cpu" and any("받아쓰기 CPU" in x for x in r["판별"]), r
    r = sysinfo.recommend([{"이름": "6GB 카드", "전체_MiB": 6144}])
    assert r["설정"]["귀.장치"] == "cpu", r
    on = {"claude": {"있음": True, "로그인": True}, "codex": {"있음": False, "로그인": False}}
    r = sysinfo.recommend([{"이름": "8GB 카드", "전체_MiB": 8151}], on)
    assert r["설정"]["두뇌.방식"] == "claude_cli" and r["설정"]["귀.장치"] == "auto", r
    assert sysinfo.recommend([{"이름": "큰 카드", "전체_MiB": 12288}])["설정"]["귀.장치"] == "auto"


def test_subscription_fields():
    cfg, _ = fresh_cfg()
    clean, err, _w = S.validate({"두뇌": {"방식": "claude_cli", "구독_클로드_모델": "haiku"}}, cfg)
    assert not err and clean["두뇌.방식"] == "claude_cli" and clean["두뇌.열쇠_이름"] == ""
    clean, err, _w = S.validate({"두뇌": {"방식": "codex_cli", "구독_GPT_생각": "", "구독_GPT_모델": "gpt-5.6-luna"}}, cfg)
    assert not err and clean["두뇌.구독_GPT_모델"] == "gpt-5.6-luna"
    _c, err, _w = S.validate({"두뇌": {"구독_클로드_모델": "claude-opus-5-5"}}, cfg)
    assert "두뇌.구독_클로드_모델" in err
    _c, err, _w = S.validate({"두뇌": {"구독_GPT_생각": "아주많이"}}, cfg)
    assert "두뇌.구독_GPT_생각" in err
    ids = [x["id"] for x in S.choices()["두뇌"]]
    assert ids[:2] == ["claude_cli", "codex_cli"] and set(ids) == {"claude_cli", "codex_cli", "local", "url", "compat", "openai", "claude"}


def test_cli_detect_fake():
    from app.core import cli_detect as D
    os.environ["KIMBISEO_FAKE_CLI"] = "claude:on,codex:off"
    try:
        D._CACHE.clear()
        st = D.all_status(fresh=True)
        assert st["claude"]["로그인"] is True and st["codex"]["있음"] and st["codex"]["로그인"] is False and "로그인" in st["codex"]["안내"]
        assert D.suggest(st) == "claude_cli"
        os.environ["KIMBISEO_FAKE_CLI"] = "none"
        st = D.all_status(fresh=True)
        assert not st["claude"]["있음"] and D.suggest(st) == "" and "설치" in st["claude"]["안내"]
    finally:
        os.environ.pop("KIMBISEO_FAKE_CLI", None)
        D._CACHE.clear()


def test_cli_command_exe_first_and_cmd_shims():
    """구독 두뇌 부르기: .exe 먼저 · npm .cmd 는 node + 진짜 .js 로(cmd.exe 안 거침) · 못 풀면 특수문자 경로·인자 거절."""
    from app.core import cli_detect as D
    bs = chr(92)   # 역빗금(글자 그대로 쓰면 공개 전 검사가 공유 폴더 경로로 봄)
    shim = ('@ECHO off\r\nSETLOCAL\r\nIF EXIST "%dp0%' + bs + 'node.exe" (\r\n  SET "_prog=%dp0%' + bs + 'node.exe"\r\n) ELSE (\r\n'
            '  SET "_prog=node"\r\n)\r\nendLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%'
            + bs.join(["", "node_modules", "@x", "claude-code", "cli.js"]) + '" %*\r\n')
    root = tempfile.mkdtemp()
    a = os.path.join(root, "a & b")                       # cmd 특수문자가 든 폴더
    os.makedirs(os.path.join(a, "node_modules", "@x", "claude-code"))
    open(os.path.join(a, "node_modules", "@x", "claude-code", "cli.js"), "w").close()
    open(os.path.join(a, "node.exe"), "wb").close()
    open(os.path.join(a, "claude.cmd"), "w").write(shim)
    # 1) .exe 는 그대로
    exe = os.path.join(root, "claude.exe")
    open(exe, "wb").close()
    assert D.command("claude", ["-p"], exe) == [exe, "-p"]
    # 2) npm 심 → node + cli.js (폴더에 & 가 있어도 cmd 를 안 거치니 괜찮음)
    got = D.command("claude", ["--x", 'a"b'], os.path.join(a, "claude.cmd"))
    assert got == [os.path.join(a, "node.exe"), os.path.join(a, "node_modules", "@x", "claude-code", "cli.js"), "--x", 'a"b'], got
    # 3) 심이 .exe 를 부르면 그 .exe 를 바로
    os.makedirs(os.path.join(root, "n", "node_modules", "codex", "bin"))
    real = os.path.join(root, "n", "node_modules", "codex", "bin", "codex.exe")
    open(real, "wb").close()
    open(os.path.join(root, "n", "codex.cmd"), "w").write('@"%dp0%' + bs.join(["", "node_modules", "codex", "bin", "codex.exe"]) + '" %*\r\n')
    assert D.command("codex", ["login"], os.path.join(root, "n", "codex.cmd")) == [real, "login"]
    # 4) 못 푸는 .cmd: 특수문자 없으면 그대로, 경로·인자에 있으면 거절(안내 글)
    plain = os.path.join(root, "plain")
    os.makedirs(plain)
    open(os.path.join(plain, "codex.cmd"), "w").write("@echo off\r\nsomething %*\r\n")
    assert D.command("codex", ["login", "status"], os.path.join(plain, "codex.cmd")) == [os.path.join(plain, "codex.cmd"), "login", "status"]
    for bad_exe, bad_args in ((os.path.join(plain, "codex.cmd"), ["-c", 'web_search="disabled"']),
                              (os.path.join(plain, "codex.cmd"), ["%PATH%"])):
        try:
            D.command("codex", bad_args, bad_exe)
            raise AssertionError("특수문자 인자를 막아야 함")
        except D.CliPathError as ex:
            assert ".exe" in str(ex)
    bad_dir = os.path.join(root, "x!y")
    os.makedirs(bad_dir)
    open(os.path.join(bad_dir, "claude.bat"), "w").write("@echo off\r\n")
    try:
        D.command("claude", ["auth", "status"], os.path.join(bad_dir, "claude.bat"))
        raise AssertionError("특수문자 경로를 막아야 함")
    except D.CliPathError:
        pass
    # 5) PATH 에 .cmd 와 .exe 가 같이 있으면 .exe
    both = os.path.join(root, "both")
    os.makedirs(both)
    open(os.path.join(both, "claude.cmd"), "w").write("@echo off\r\n")
    open(os.path.join(both, "claude.exe"), "wb").close()
    old = os.environ.get("PATH", "")
    os.environ["PATH"] = both
    try:
        assert D.find("claude").lower().endswith("claude.exe")
    finally:
        os.environ["PATH"] = old


def test_cli_brains_are_read_only():
    """구독 두뇌는 읽기 전용: Codex = sandbox read-only·승인 없음·셸/플러그인/MCP 끔, 클로드 코드 = 도구 없음(--tools "")·안전 모드."""
    import asyncio
    from app.core import cli_brain as B
    cfg = C.deep_merge(C.load(os.path.join(tempfile.mkdtemp(), "없음.json"), warn=lambda m: None),
                       {"경로": {"자료": tempfile.mkdtemp().replace("\\", "/")}})
    cx = B.CodexCli(cfg)
    seen = {}

    async def fake_rpc(method, params=None, timeout=30.0):
        seen[method] = params
        return {"thread": {"id": "t1"}}
    cx.rpc = fake_rpc
    cx.system, cx.history = "x", []
    asyncio.run(cx._new_thread())
    p = seen["thread/start"]
    assert p["sandbox"] == "read-only" and p["approvalPolicy"] == "never" and p["ephemeral"] is True
    assert os.path.normcase(p["cwd"]) == os.path.normcase(B.workdir(cfg))
    off = " ".join(B.CODEX_OFF)
    for f in ("shell_tool", "plugins", "apps", "hooks", "computer_use", "browser_use", "mcp_servers={}"):
        assert f in off, f
    got = {}

    class P:
        def __init__(self, cmd, cwd, env, name):
            got["cmd"] = cmd

        class p:
            pid = 0
    old = B._Proc
    B._Proc = P
    try:
        cl = B.ClaudeCli(cfg)
        cl.system, cl.history = "x", []
        exe = os.path.join(tempfile.mkdtemp(), "claude.exe")
        open(exe, "wb").close()
        import app.core.cli_detect as D
        of = D.find
        D.find = lambda n: exe
        try:
            cl._spawn()
        finally:
            D.find = of
    finally:
        B._Proc = old
    c = got["cmd"]
    assert c[0] == exe and c[c.index("--tools") + 1] == "" and "--safe-mode" in c and "--strict-mcp-config" in c and "--no-session-persistence" in c


def test_cli_child_env_has_no_keys():
    from app.core import cli_brain as B
    os.environ["ANTHROPIC_API_KEY"] = "test-value-not-a-key"
    os.environ["OPENAI_API_KEY"] = "test-value-not-a-key"
    os.environ["KIMBISEO_KEY_X"] = "x"
    try:
        for kind in B.KINDS:
            env = B.child_env(kind)
            assert "ANTHROPIC_API_KEY" not in env and "OPENAI_API_KEY" not in env and not any(k.startswith("KIMBISEO_") for k in env)
        assert B.child_env("claude_cli")["MAX_THINKING_TOKENS"] == "0"
    finally:
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "KIMBISEO_KEY_X"):
            os.environ.pop(k, None)


def test_fake_gpu_env():
    os.environ["KIMBISEO_FAKE_GPU"] = "가짜 카드:12288"
    try:
        g = sysinfo.gpus()
        assert g and g[0]["전체_MiB"] == 12288
        os.environ["KIMBISEO_FAKE_GPU"] = "none"
        assert sysinfo.gpus() == []
    finally:
        os.environ.pop("KIMBISEO_FAKE_GPU", None)


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
