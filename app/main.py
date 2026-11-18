# 김비서 본체 — 이 PC 안(127.0.0.1:포트.본체, 기본 8870)에서 돈다.
#   실행: python -m app.main serve [--settings 설정.json] [--parent_pid N]
#         python -m app.main script <대본.json> --out <결과폴더> [--settings 설정.json]   (시험: 마이크 대신 wav 대본)
#   serve:
#     GET   /                 대화창(app/ui/index.html) — 처음 설정이 안 끝났으면 처음 화면(마법사)부터
#     GET   /ui/<파일>         화면 파일(app/ui 안 정해진 종류만)
#     POST  /api/offer        WebRTC 대화 연결(SmallWebRTC). 한 번에 한 기기만 — 새 연결이 오면 앞 대화를 끝냄.
#     PATCH /api/offer        ICE 후보
#     POST  /api/text         {"text": "..."} 글 입력(같은 두뇌로, 말하는 중이면 끊고 답)
#     GET   /api/events       화면에 보낼 사건(상태·자막·설정 반영) — Server-Sent Events
#     GET   /api/status       상태(두뇌·이름·캐시 가드·펫·대화 중·마이크 처리(메아리 지우기)·다시 켜야 할 것)
#     GET   /api/settings     지금 설정(비밀값 없음) + 고르기 목록   POST /api/settings {"바꿀것": {...}} 저장 → 바로 반영
#     POST  /api/secret       {"이름": "url"|"openai"|"claude"|"compat", "값": "..."} 열쇠 저장(값은 돌려주지 않음)
#     POST  /api/brain/models  {"두뇌": {...}} OpenAI 호환 주소의 모델 목록(저장 전 값으로)
#     GET   /api/system       이 PC 사양 + 추천 구성     POST /api/brain/test  두뇌 연결 시험(저장 전 값으로)
#     GET   /api/brain/options  두뇌 바꾸기 — 구독 두뇌(claude·codex) 설치·로그인 상태, 권하는 두뇌, Gemma 설치 상태
#     POST  /api/brain/login  {"이름": "claude"|"codex"} 그 프로그램의 로그인 창을 엶(사용자가 직접 로그인 — 김비서는 계정을 안 봄)
#     POST  /api/brain/gemma/install {"판":"E4B"|"E2B"} · GET /api/brain/gemma/status   Gemma 설치(다시 설치) — 설치 프로그램을 따로 띄워 받음
#     POST  /api/brain/gemma/remove  Gemma·두뇌 프로그램 지우기(두뇌가 Gemma 가 아닐 때만)
#     POST  /api/ear/hear     PCM16 16kHz(application/octet-stream) → 받아쓴 글(?name= 이면 그 이름으로 불렀는지)
#     POST  /api/name/learn   {"이름", "들은것": [...]} → 별칭·경고       POST /api/name/check {"이름"} → 경고
#     POST  /api/voice/sample {"글"?, "목소리"?} → 목소리 견본 wav       GET /api/voice/status  목소리·귀 서버 상태
#     POST  /api/client       화면 마이크 처리 결과(getSettings: 메아리 지우기·잡음 줄이기·소리 크기 자동) 기록
#     POST  /api/pending/clear {"무엇": "목소리"|"귀"}  (실행 관리가 서버를 다시 켠 뒤)
#     GET   /api/memory       기억 보기(지식·일기)   POST /api/memory/delete {"id"|"day"|"all": true}  기억 지우기
#     GET   /api/interp       통역 상태(켜짐·상대 언어·최근 번역)   POST /api/interp {"켜기": true|false, "언어": "auto"|코드}
#     GET   /api/interp/runtime  통역 목소리 부품·모델 받았는지   POST /api/interp/install  '통역 목소리 받기'(설치 프로그램을 따로 띄움)
#     GET   /api/update       업데이트 상태(지금 판·새 판·받는 중·지난 결과)   POST /api/update/check · /download · /apply · /seen · /page
#     POST  /api/shutdown     끄기(머리글 X-KimBiseo-Shutdown = 자료 폴더 secrets\shutdown_secret.txt 값)
#   지키는 것: 127.0.0.1 에서만 듣고, Host·Origin·Content-Type 검사(core/guard). 기억·대화 기록·열쇠는 자료 폴더에만.
import argparse
import asyncio
import json
import os
import re
import sys
import time

from loguru import logger

from .core import config as C
from .core import guard as G
from .core import i18n
from .core.memory import Memory
from .version import VERSION as APP_VERSION

CFG = None
MEM = None
GUARDS = {}
PET = None
CURRENT = {"session": None, "task": None}
SETTINGS_PATH = ""
PENDING = {}            # 다시 켜야 반영되는 것 {"목소리": [항목 이름], "귀": [...]}
RUNNING = {}            # 다시 켜야 반영되는 항목의 '지금 켜져 있는 서버' 값(본체를 켤 때 값 · 서버를 다시 켜면 /api/pending/clear 로 갱신)
CLIENT_AUDIO = {}       # 화면이 알려 준 마이크 처리 상태(메아리 지우기 등)
SYS = {}                # 마지막 사양 보기 결과
QUEUES = set()          # /api/events 받는 곳
LOOP = None
VP = None               # 내 목소리 등록·확인(core/voiceprint) — '등록한 목소리만 명령 받기'
PHONE = {"auth": None, "gw": None}      # 폰 연결(core/phone) — 등록 기기·관문 서버
CONFIRMS = {}           # PC 창 '실행할까요?' 단추 기다림 {id: Future}
UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
UI_EVENTS = {"status", "user", "bot", "typed", "asr", "tool", "wake_mode", "wake", "name_call", "interrupted",
             "brain_error", "speed", "settings_applied", "names", "session", "settings", "client_audio", "echo",
             "barge", "tool_halt", "conn", "update", "interp", "confirm", "confirm_done", "voice_gate", "phone"}


def _make_memory():
    mc = CFG.get("기억") or {}
    if not mc.get("켜기", True):
        return None
    return Memory(os.path.join(C.path(CFG, "자료"), "기억"), int(mc.get("지식_최대", 200)))


def _setup(settings):
    global CFG, MEM, PET, SETTINGS_PATH, VP
    SETTINGS_PATH = os.path.abspath(C.user_settings_path(settings))
    CFG = C.load(settings, warn=lambda m: logger.warning(m))
    CFG["_settings_path"] = SETTINGS_PATH
    i18n.set_lang(CFG.get("언어"))       # 앱 언어(0.1.18) — 말·화면에 나가는 고정 문구(tr)가 이 언어를 씀
    data = C.path(CFG, "자료")
    os.makedirs(data, exist_ok=True)
    MEM = _make_memory()
    from .pet_link.face import PetFace, mode_on
    if mode_on(CFG):
        name, al = C.names(CFG)
        PET = PetFace(CFG, [name] + al)
    logs = C.path(CFG, "로그")
    os.makedirs(logs, exist_ok=True)
    # 마이크가 없거나 꺼져 있으면 pipecat 이 2초마다 같은 경고를 남겨 기록이 하루 4만 줄씩 불어남 → 그 한 줄만 뺌
    def _quiet(rec):
        return not (rec["level"].name == "WARNING" and "No audio frame received" in rec["message"])
    logger.remove()
    if sys.stderr is not None:
        logger.add(sys.stderr, level="INFO", filter=_quiet, diagnose=False, backtrace=False)   # 변수 값(열쇠 등)이 오류 기록에 찍히지 않게
    logger.add(os.path.join(logs, "body_{time:YYYYMMDD}.log"), rotation="1 day", retention=14, level="INFO", encoding="utf-8", filter=_quiet,
               diagnose=False, backtrace=False)
    from .core.voiceprint import VoicePrint
    VP = VoicePrint(CFG, log=logger.info)
    from .core import phone as PH
    PHONE["auth"] = PH.PhoneAuth(os.path.join(PH.secret_dir(CFG), "phones.json"), os.path.join(logs, "phone_access.jsonl"))


def _reload():
    C.reload_into(CFG, SETTINGS_PATH, warn=lambda m: logger.warning(m))
    CFG["_settings_path"] = SETTINGS_PATH
    i18n.set_lang(CFG.get("언어"))       # 설정에서 '언어'를 바꾸면 다음 문장·다음 화면부터


def _restart_keys(what=None):
    from .core import settings_api as S
    return [k for k, v in S.FIELDS.items() if v[1].startswith("다시켜기:") and (what is None or v[1] == "다시켜기:" + what)]


def _mark_running(what=None):
    """그 서버(목소리·귀, 없으면 전부)가 지금 설정 값으로 켜져 있다고 적음."""
    from .core import settings_api as S
    for k in _restart_keys(what):
        RUNNING[k] = S.get(CFG, k)


def _recompute_pending():
    """PENDING = 지금 설정이 켜져 있는 서버 값과 다른 '다시 켜야' 항목만(바꿨다 되돌리면 사라짐)."""
    from .core import settings_api as S
    out = {}
    for k in _restart_keys():
        if S.get(CFG, k) != RUNNING.get(k):
            out.setdefault(S.FIELDS[k][1].split(":", 1)[1], []).append(S.FIELDS[k][2])
    PENDING.clear()
    PENDING.update({w: sorted(set(v)) for w, v in out.items()})


def _tell_pet(keys):
    """펫 설정이 바뀌면 켜져 있는 펫에 바로 알림: 옷 받기 동의 → /packs/auto · 펫 캐릭터(옷) → /skin."""
    from .pet_link.face import pet_call
    out = {}
    pc = CFG.get("펫") or {}
    if "펫.옷_받기" in keys and pc.get("옷_받기") is True:
        code, j = pet_call(CFG, "/packs/auto", {})
        out["옷받기"] = {"코드": code, **({k: j.get(k) for k in ("ok", "started", "already", "error", "code") if k in j})}
    if "펫.옷" in keys and pc.get("옷"):
        code, j = pet_call(CFG, "/skin", {"id": str(pc["옷"])})
        out["옷"] = {"코드": code, "ok": j.get("ok"), "error": j.get("error"), **({"받는중": True} if j.get("fetching") else {})}
        from .pet_link.face import forget_outfit
        forget_outfit()      # 다음 문장이 바로 새 옷의 목소리를 고르게
    logger.info(f"펫에 알림: {out}")
    return out


def _voice_gen_body():
    """설정의 목소리 세부 값 → 목소리 서버 POST /config 본문(top_k 는 서버를 다시 켜야 읽으므로 안 보냄)."""
    vc = CFG.get("목소리") or {}
    out = {}
    for api, key in (("temperature", "온도"), ("sub_temperature", "세부_온도"), ("repetition_penalty", "반복_벌점"), ("gap", "문장_쉼_초")):
        v = vc.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[api] = float(v)
    return out


def _tell_voice():
    """목소리 세부 설정(온도·쉼 …)이 바뀌면 켜져 있는 목소리 서버에 바로 알림. 꺼져 있으면 다음에 켤 때 설정 파일에서 읽음.
    → {"코드": 200|400|None, "바뀜": {...}, "오류": "..."}"""
    import http.client
    body = json.dumps(_voice_gen_body()).encode("utf-8")
    port = int(CFG["포트"]["목소리"])
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("POST", "/config", body=body, headers={"Content-Type": "application/json", "Host": f"127.0.0.1:{port}"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            j = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            j = {}
        out = {"코드": r.status, "바뀜": j.get("changed") or {}, "엔진": j.get("engine")}
        if r.status != 200:
            out["오류"] = str(j.get("error") or "")[:200]
        logger.info(f"목소리 서버에 세부 설정 알림: {out}")
        return out
    except (OSError, http.client.HTTPException) as ex:
        logger.info(f"목소리 서버가 꺼져 있어 세부 설정은 다음에 켤 때 반영({ex.__class__.__name__})")
        return {"코드": None}


def broadcast(ev):
    """사건 하나를 화면(/api/events)에 — 어느 스레드에서 불러도 됨. 받는 곳이 밀리면 버림."""
    if not QUEUES or not isinstance(ev, dict) or ev.get("type") not in UI_EVENTS:
        return
    if ev.get("type") == "asr" and ev.get("verdict") not in (None, "pass"):
        return   # 주변 말·메아리·잡음은 화면에 안 보냄

    def put():
        for q in list(QUEUES):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass
    try:
        if LOOP is not None and LOOP.is_running():
            LOOP.call_soon_threadsafe(put)
    except RuntimeError:
        pass


async def _run(session, on_start=None):
    from pipecat.workers.runner import WorkerRunner
    session.build()
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(session.worker)
    saver = asyncio.ensure_future(session._autosave_loop())
    starter = asyncio.ensure_future(on_start(session)) if on_start else None
    try:
        await runner.run()
    finally:
        saver.cancel()
        if starter is not None:
            starter.cancel()
        if session.state.pet is not None:
            session.state.pet.end(session.state)
        try:
            await asyncio.wait_for(session.finish(), timeout=120)
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"대화 끝 정리 실패: {ex.__class__.__name__}")


# ================================================================ 시험: wav 대본
async def run_script(script_path, out_dir):
    from .core.session import Session
    from .core.wav_transport import Room, WavTransport
    with open(script_path, encoding="utf-8") as f:
        sc = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.dirname(os.path.abspath(script_path))
    ev = sc.get("events") or []
    length = float(sc.get("length_sec") or (max([e.get("t", 0) for e in ev] + [0]) + 20))
    echo = sc.get("echo") or {}
    room = Room(length, echo_gain=float(echo.get("gain", 0)), echo_delay=float(echo.get("delay", 0.12)))
    for e in ev:
        if e.get("wav"):
            p = e["wav"] if os.path.isabs(e["wav"]) else os.path.join(base, e["wav"])
            e["_dur"] = room.place(float(e["t"]), p, float(e.get("gain", 1.0)))
    log_f = open(os.path.join(out_dir, "events.jsonl"), "w", encoding="utf-8")

    def ui(x):
        log_f.write(json.dumps({**x, "rt": round(room.now(), 3)}, ensure_ascii=False, default=str) + "\n")
        log_f.flush()

    opts = {"greeting": sc.get("greeting", True), "새대화": sc.get("new_conversation", False), "voiceprint": VP}
    if "confirm_answer" in sc:          # 시험: 위험한 도구의 '실행할까요?'에 대본이 정한 답(true/false)
        async def _answer(text, timeout=45.0, _v=bool(sc["confirm_answer"])):
            ui({"type": "confirm", "text": text, "answer": _v})
            return _v
        opts["confirm"] = _answer
    s = Session(CFG, lambda d: WavTransport(room, ducker=d), memory=MEM, guards=GUARDS, pet=PET, send_ui=ui, opts=opts)

    async def drive(sess):
        await asyncio.sleep(0.3)
        if sc.get("warmup", True):
            await sess.warmup()
        await sess.greet()
        t_end = length
        for e in sorted([e for e in ev if e.get("text") or e.get("end")], key=lambda x: x["t"]):
            wait = float(e["t"]) - room.now()
            if wait > 0:
                await asyncio.sleep(wait)
            if e.get("text"):
                await sess.send_text(e["text"])
            if e.get("end"):
                t_end = float(e["t"])
                break
        wait = t_end - room.now()
        if wait > 0:
            await asyncio.sleep(wait)
        for _ in range(int(sc.get("drain_sec", 20) * 10)):   # 말하던 중이면 끝날 때까지 기다림
            if not (sess.state.bot_speaking or sess.state.thinking or sess.state.tool_busy):
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(1.0)
        await sess.worker.cancel()

    t0 = time.time()
    await _run(s, drive)
    log_f.close()
    room.save(os.path.join(out_dir, "room_mic_L_bot_R.wav"), os.path.join(out_dir, "bot_24k.wav"))
    g = s.llm.guard if s.llm else None
    rep = {"초": round(time.time() - t0, 1), "두뇌": s.llm.kind if s.llm else None,
           "타이밍": s.llm.timing_log if s.llm else [], "건짐": s.llm.rescued if s.llm else 0,
           "캐시가드": {"검사": g.checks, "걸림": g.trips, "쓸수있음": g.ok} if g else None,
           "이음새_고침": s._tts.smoother.fixed if getattr(s, "_tts", None) else None,
           "끝정리": s.end_report, "이어받은_차례": s.restored_n, "이름": s.state.names.name,
           "펫": PET.info() if PET else None,
           "문맥": [{"role": m.get("role"), "content": (m.get("content") if isinstance(m.get("content"), str) else str(m.get("content")))[:400],
                     **({"tool_calls": [c.get("function", {}).get("name") for c in m.get("tool_calls") or []]} if m.get("tool_calls") else {})}
                    for m in s.context.messages[1:] if isinstance(m, dict)]}
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    return rep


# ================================================================ serve: WebRTC + HTTP + 화면
_UI_FILE = re.compile(r"^[a-z0-9_-]+\.(html|js|css|png|svg|ico)$")
_UI_TYPES = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8",
             "png": "image/png", "svg": "image/svg+xml", "ico": "image/x-icon"}
EAR_MAX_BYTES = 16000 * 2 * 12          # 받아쓰기 시험 한 번 최대 12초


def make_app():
    from fastapi import BackgroundTasks, FastAPI, Request
    from fastapi.responses import JSONResponse, Response, StreamingResponse
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
    from pipecat.transports.smallwebrtc.request_handler import (SmallWebRTCPatchRequest, SmallWebRTCRequest,
                                                                SmallWebRTCRequestHandler)
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    from .core import settings_api as S
    from .core import sysinfo
    from .core.session import Session
    from .core.voice_link import EarLink
    from .core.wake import NameMatcher, learn_aliases, name_warning

    app = FastAPI()
    handler = SmallWebRTCRequestHandler()
    from .core.update import Updater, UpdateError
    upd = Updater(CFG, SETTINGS_PATH)

    def auto_check():
        try:
            if upd.due():
                v = upd.check()
                logger.info(f"업데이트 확인(자동): 지금 {v['지금_판']} · 새 판 {(v['새판'] or {}).get('판') or '없음'}")
                if v["새판"]:
                    broadcast({"type": "update", **v})
        except UpdateError as ex:
            logger.info(f"업데이트 확인(자동) 못 함: {ex}")
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"업데이트 확인(자동) 오류: {ex.__class__.__name__}")
    import threading
    t_auto = threading.Timer(15.0, auto_check)
    t_auto.daemon = True
    t_auto.start()
    port = int(CFG["포트"]["본체"])
    secret = G.shutdown_secret(os.path.join(C.path(CFG, "자료"), "secrets"))
    names = set(G.LOOP_NAMES)
    binary = {"/api/ear/hear": ("application/octet-stream",), "/api/voiceprint/clip": ("application/octet-stream",),
              "/api/voiceprint/test": ("application/octet-stream",)}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        global LOOP
        if LOOP is None:
            LOOP = asyncio.get_running_loop()   # 사건을 다른 스레드에서도 화면으로 보내려고(broadcast)
        host = request.client.host if request.client else ""
        path = request.url.path
        if host not in ("127.0.0.1", "::1"):
            return JSONResponse({"ok": False, "오류": "이 PC 안에서만 됩니다"}, status_code=403)
        bad = G.check(request.method, path, request.headers, names, port, binary_types=binary)
        if bad and not (path == "/api/shutdown" and bad[0] == 415):
            logger.warning(f"요청 거절({bad[0]}): {request.method} {path}")
            return JSONResponse({"ok": False, "오류": "허용되지 않은 요청입니다"}, status_code=bad[0])
        if path == "/api/shutdown" and not G.same_secret(request.headers.get(G.SHUTDOWN_HEADER.lower()), secret):
            return JSONResponse({"ok": False, "오류": "끄기 비밀값이 없습니다"}, status_code=403)
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        if path == "/" or path.startswith("/ui/"):
            # 화면은 이 PC 의 본체 주소에서만, 다른 곳의 글·스크립트는 안 불러옴
            resp.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                                                       "media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")
            resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    # ---------------------------------------------------------------- 화면 파일
    def _ui(name):
        if not _UI_FILE.match(name):
            return JSONResponse({"ok": False}, status_code=404)
        p = os.path.join(UI_DIR, name)
        if not os.path.isfile(p):
            return JSONResponse({"ok": False}, status_code=404)
        with open(p, "rb") as f:
            return Response(f.read(), media_type=_UI_TYPES[name.rsplit(".", 1)[1]])

    @app.get("/")
    async def index():
        return _ui("index.html")

    @app.get("/ui/{name}")
    async def ui_file(name: str):
        return _ui(name)

    @app.get("/api/i18n.js")
    async def i18n_js():
        """화면 번역 사전(0.1.18) — app/i18n/<언어>.json 을 화면 번역기(app/ui/i18n.js)에 넣고 시작.
        한국어면 빈 사전이라 화면 번역기가 아무것도 바꾸지 않는다."""
        code = i18n.lang_of(CFG)
        data = json.dumps({"lang": code, "dict": i18n.table(code)}, ensure_ascii=False, separators=(",", ":"))
        js = ("window.I18N&&I18N.load(" + data + ");window.I18N&&I18N.start();\n")
        return Response(js, media_type="text/javascript; charset=utf-8")

    # ---------------------------------------------------------------- 대화 연결
    async def kick(who="PC 창"):
        """한 번에 한 기기만 대화 — 새 연결(PC 창·폰)이 오면 앞 대화를 끝냄. 앞이 폰이면 폰에 먼저 알림."""
        s = CURRENT.get("session")
        link = CURRENT.get("link")
        if link is not None:
            link.send({"type": "kicked", "by": who})
            await asyncio.sleep(0.3)        # 알림이 먼저 닿게
        if s is not None and s.worker is not None:
            logger.info(f"새 연결({who}) — 앞 대화를 끝냄(한 번에 한 기기)")
            try:
                await s.worker.cancel()
            except Exception:  # noqa: BLE001
                pass
            for _ in range(30):             # 앞 대화의 귀·목소리 연결이 풀릴 때까지 잠깐(최대 3초)
                if CURRENT.get("session") is not s:
                    break
                await asyncio.sleep(0.1)

    # ---------------------------------------------------------------- 위험한 도구의 '실행할까요?'(PC 창) — registry.confirmed 가 부름
    async def pc_confirm(text, timeout=45.0):
        if not QUEUES:
            return False                    # 화면이 안 떠 있으면 묻지 못함 → 실행 안 함
        import secrets as _sec
        cid = _sec.token_hex(6)
        fut = asyncio.get_running_loop().create_future()
        CONFIRMS[cid] = fut
        broadcast({"type": "confirm", "id": cid, "text": str(text)[:300], "초": int(timeout)})
        try:
            return bool(await asyncio.wait_for(fut, timeout))
        except asyncio.TimeoutError:
            return False
        finally:
            CONFIRMS.pop(cid, None)
            broadcast({"type": "confirm_done", "id": cid})

    @app.post("/api/confirm")
    async def confirm_answer(request: Request):
        b = await request.json()
        fut = CONFIRMS.get(str((b or {}).get("id") or ""))
        if fut is None or fut.done():
            return JSONResponse({"ok": False, "오류": "이미 끝난 확인이에요"}, status_code=404)
        fut.set_result((b or {}).get("ok") is True)
        return {"ok": True}

    async def run_conn(conn: SmallWebRTCConnection, greeting=True):
        def tf(_ducker):
            return SmallWebRTCTransport(webrtc_connection=conn, params=TransportParams(
                audio_in_enabled=True, audio_out_enabled=True, audio_in_sample_rate=16000, audio_out_sample_rate=24000))
        s = Session(CFG, tf, memory=MEM, guards=GUARDS, pet=PET, send_ui=broadcast,
                    opts={"greeting": greeting, "confirm": pc_confirm, "voiceprint": VP})
        CURRENT["session"] = s

        async def start(sess):
            tr = sess.transport

            @tr.event_handler("on_client_connected")
            async def _c(_t, _cl):
                broadcast({"type": "conn", "on": True})
                await sess.warmup()
                await sess.greet()

            @tr.event_handler("on_client_disconnected")
            async def _d(_t, _cl):
                await sess.worker.cancel()
        s.build_hook = start
        try:
            await _run_with_hook(s)
        finally:
            if CURRENT.get("session") is s:
                CURRENT["session"] = None
                broadcast({"type": "conn", "on": False})

    async def _run_with_hook(s):
        from pipecat.workers.runner import WorkerRunner
        s.build()
        await s.build_hook(s)
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(s.worker)
        saver = asyncio.ensure_future(s._autosave_loop())
        try:
            await runner.run()
        finally:
            saver.cancel()
            if s.state.pet is not None:
                s.state.pet.end(s.state)
            try:
                await asyncio.wait_for(s.finish(), timeout=120)
            except Exception as ex:  # noqa: BLE001
                logger.warning(f"대화 끝 정리 실패: {ex.__class__.__name__}")

    # ---------------------------------------------------------------- 구독 클로드 두뇌용 김비서 도구(MCP) — core/cli_mcp.py
    from .core import cli_mcp

    @app.post(cli_mcp.PATH)
    async def mcp_post(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}, status_code=400)
        code, out = await cli_mcp.handle(body, request.headers.get("authorization"))
        return Response(status_code=code) if out is None else JSONResponse(out, status_code=code)

    @app.get(cli_mcp.PATH)
    async def mcp_get():
        return Response(status_code=405)   # 서버가 먼저 보내는 알림 통로(SSE)는 안 씀

    @app.delete(cli_mcp.PATH)
    async def mcp_delete():
        return Response(status_code=405)
    cli_mcp.PORT = port

    @app.post("/api/offer")
    async def offer(request: SmallWebRTCRequest, background_tasks: BackgroundTasks):
        if not request.pc_id:
            await kick()
        rd = request.request_data if isinstance(getattr(request, "request_data", None), dict) else {}
        greeting = rd.get("greeting", True) is not False

        async def cb(conn):
            background_tasks.add_task(run_conn, conn, greeting)
        return await handler.handle_web_request(request=request, webrtc_connection_callback=cb)

    @app.patch("/api/offer")
    async def ice(request: SmallWebRTCPatchRequest):
        await handler.handle_patch_request(request)
        return {"ok": True}

    @app.post("/api/text")
    async def text(request: Request):
        body = await request.json()
        s = CURRENT.get("session")
        if s is None:
            return JSONResponse({"ok": False, "오류": "대화가 연결되어 있지 않아요"}, status_code=409)
        return {"ok": await s.send_text(body.get("text"))}

    @app.get("/api/events")
    async def events():
        q = asyncio.Queue(maxsize=300)
        QUEUES.add(q)

        async def gen():
            try:
                hello = {"type": "hello", "대화중": CURRENT.get("session") is not None, "이름": C.names(CFG)[0]}
                yield "retry: 2000\n\ndata: " + json.dumps(hello, ensure_ascii=False) + "\n\n"
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), 15)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield "data: " + json.dumps(ev, ensure_ascii=False, default=str) + "\n\n"
            finally:
                QUEUES.discard(q)
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/status")
    async def status():
        s = CURRENT.get("session")
        name, al = C.names(CFG)
        return {"ok": True, "판": APP_VERSION, "대화중": s is not None, "두뇌": (CFG["두뇌"].get("방식")), "두뇌_모드": CFG["두뇌"].get("모드"),
                "이름": name, "별칭": al, "호칭": C.honorific(CFG),
                "끼어들기_감도": CFG["대화"].get("끼어들기_감도"),
                "끼어들기_값": {k: ((s.cfg if s else CFG)["대화"].get(k)) for k in C.BARGE_LEVELS[0.3]}, "말속도": (s.state.speed if s else CFG["목소리"].get("말속도")),
                "지금_대화_이름": s.state.names.name if s else None,
                "처음설정_끝": bool((CFG.get("처음설정") or {}).get("끝")),
                "마이크_처리": CLIENT_AUDIO or None, "다시켜기_필요": PENDING,
                "캐시가드": {k: {"검사": g.checks, "걸림": g.trips, "쓸수있음": g.ok} for k, g in GUARDS.items()},
                "펫": PET.info() if PET else None}

    # ---------------------------------------------------------------- 설정
    @app.get("/api/settings")
    async def settings_get():
        return {"ok": True, "설정": S.view(CFG), "선택지": S.choices(), "다시켜기_필요": PENDING,
                "반영시점": {k: v[1] for k, v in S.FIELDS.items()}}

    @app.post("/api/settings")
    async def settings_post(request: Request):
        global MEM
        body = await request.json()
        changes = body.get("바꿀것") if isinstance(body, dict) else None
        if not isinstance(changes, dict):
            return JSONResponse({"ok": False, "오류": {"": "바꿀것 이 없어요"}}, status_code=400)
        warn = ((SYS.get("추천") or {}).get("목소리_경고")) or ""
        clean, errors, warns = S.validate(changes, CFG, voice_warn=warn)
        if errors:
            return JSONResponse({"ok": False, "오류": errors}, status_code=400)
        for w in warns:
            logger.warning(w)     # 목소리 자산 없음 대체 같은 안내를 기록에도 남김
        keys = S.changed_keys(CFG, clean)
        if keys:
            old_tone = S.get(CFG, "비서.말투")
            if not C.save_user(CFG, S.nest({k: clean[k] for k in keys})):
                return JSONResponse({"ok": False, "오류": {"": "설정 파일을 저장하지 못했어요"}}, status_code=500)
            mem_was = (CFG.get("기억") or {}).get("켜기", True)
            _reload()
            # 성별만 바꾼 경우(말투를 직접 고정하지 않음) 말투도 함께 바뀐다 — 지금 대화에도 바로 반영.
            #   자동으로 정한 말투는 설정 파일에 쓰지 않는다(다음 성별 변경에도 계속 자동).
            if "펫.성별" in keys and "비서.말투" not in keys and S.get(CFG, "비서.말투") != old_tone:
                keys.append("비서.말투")
            if (CFG.get("기억") or {}).get("켜기", True) != mem_was:
                MEM = _make_memory()
        groups = S.when_groups(keys)
        _recompute_pending()
        s = CURRENT.get("session")
        applied = s.apply_settings(keys) if (s is not None and keys) else []
        if PET is not None and {"비서.이름", "비서.별칭"} & set(keys):
            PET.names = [C.names(CFG)[0]] + C.names(CFG)[1]
        pet_said = await asyncio.to_thread(_tell_pet, keys) if {"펫.옷_받기", "펫.옷"} & set(keys) else {}
        voice_said = await asyncio.to_thread(_tell_voice) if set(S.VOICE_GEN_KEYS) & set(keys) else {}
        phone_said = {}
        if {"폰.켜기", "폰.테일스케일_허용"} & set(keys):
            await phone_apply()
            phone_said = gw.info()
        if "두뇌.방식" in keys or "두뇌.구독_GPT_모델" in keys:
            from .core import cli_brain
            asyncio.ensure_future(cli_brain.shutdown_except(str(CFG["두뇌"].get("방식"))))
            asyncio.ensure_future(cli_brain.prewarm(CFG))
        if keys:
            logger.info(f"설정 바뀜: {', '.join(keys)} → 지금 대화 반영 {applied}")
            broadcast({"type": "settings", "keys": keys, "applied": applied})
        return {"ok": True, "바뀜": keys, "반영": groups, "지금_대화에_반영": applied, "경고": warns,
                "다시켜기_필요": PENDING, "설정": S.view(CFG), "펫": pet_said, "목소리서버": voice_said, "폰": phone_said}

    # ---------------------------------------------------------------- 펫 크기(펫이 제 설정에 기억 — 본체는 전해 주기만)
    @app.get("/api/pet/size")
    async def pet_size_get():
        from .pet_link.face import pet_get
        code, j = await asyncio.to_thread(pet_get, CFG, "/status")
        if code != 200:
            return {"ok": False, "켜짐": False, "오류": "펫이 꺼져 있어요. 펫이 켜져 있을 때 크기를 바꿀 수 있어요."}
        return {"ok": True, "켜짐": True, "크기": j.get("size"), "퍼센트": j.get("sizePct"), "픽셀": j.get("sizePx"),
                "범위": j.get("sizeRange") or [50, 200], "단계": j.get("sizes") or []}

    @app.post("/api/pet/size")
    async def pet_size_post(request: Request):
        from .pet_link.face import pet_call
        b = await request.json()
        pct = (b or {}).get("퍼센트")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not (50 <= float(pct) <= 200):
            return JSONResponse({"ok": False, "오류": "펫 크기는 50%부터 200%까지만 돼요."}, status_code=400)
        code, j = await asyncio.to_thread(pet_call, CFG, "/size", {"percent": int(round(float(pct)))})
        if code is None:
            return JSONResponse({"ok": False, "켜짐": False, "오류": "펫이 꺼져 있어요. 펫이 켜져 있을 때 크기를 바꿀 수 있어요."}, status_code=409)
        if code != 200:
            return JSONResponse({"ok": False, "오류": str(j.get("error") or "펫이 크기를 바꾸지 못했어요.")[:200]}, status_code=400)
        logger.info(f"펫 크기 {j.get('sizePct')}%")
        return {"ok": True, "퍼센트": j.get("sizePct"), "픽셀": j.get("sizePx"), "크기": j.get("size")}

    @app.post("/api/pending/clear")
    async def pending_clear(request: Request):
        b = await request.json()
        what = str((b or {}).get("무엇") or "")
        _mark_running(None if what == "전부" else what)     # 그 서버를 지금 설정으로 다시 켰음
        _recompute_pending()
        return {"ok": True, "다시켜기_필요": PENDING}

    @app.post("/api/secret")
    async def secret_post(request: Request):
        b = await request.json()
        try:
            r = S.save_secret(CFG, str((b or {}).get("이름") or ""), (b or {}).get("값"))
        except (ValueError, OSError) as ex:
            return JSONResponse({"ok": False, "오류": str(ex) if isinstance(ex, ValueError) else "저장 실패"}, status_code=400)
        name = str(b.get("이름"))
        if name == "url" and CFG["두뇌"].get("방식") == "url":
            C.save_user(CFG, {"두뇌": {"열쇠_이름": "url" if r["있음"] else ""}})
            _reload()
        logger.info(f"열쇠 저장: {name} {'있음' if r['있음'] else '지움'}")
        return {"ok": True, **r}

    @app.get("/api/system")
    async def system():
        cli = await asyncio.to_thread(cli_detect.all_status)
        rep = await asyncio.to_thread(sysinfo.report, C.path(CFG, "모델"), cli, gemma_info()["있음"])
        SYS.clear()
        SYS.update(rep)
        return {"ok": True, **rep}

    # ---------------------------------------------------------------- 두뇌 바꾸기
    from .core import cli_brain, cli_detect
    prefix = os.path.dirname(os.path.abspath(C.path(CFG, "모델")))
    setup_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "installer", "setup_core.py")
    gem = {"proc": None}
    gem_status = os.path.join(C.path(CFG, "로그"), "gemma_status.json")

    def gemma_info():
        root = C.path(CFG, "모델")
        dirs = []
        try:
            dirs = [n for n in os.listdir(root) if n.lower().startswith("gemma-") and os.path.isdir(os.path.join(root, n))]
        except OSError:
            pass
        size = 0
        for n in dirs:
            for dp, _dn, fn in os.walk(os.path.join(root, n)):
                for f in fn:
                    try:
                        size += os.path.getsize(os.path.join(dp, f))
                    except OSError:
                        pass
        run = CFG.get("실행") or {}
        model = os.path.expandvars(str(run.get("두뇌_모델") or ""))
        exe = os.path.expandvars(str(run.get("두뇌_실행파일") or ""))
        p = gem["proc"]
        st = {}
        try:
            with open(gem_status, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            pass
        return {"있음": bool(model and os.path.isfile(model) and exe and os.path.isfile(exe)), "폴더": dirs, "크기": size,
                "크기_GB": round(size / 1024 ** 3, 1), "무검열": "abliterated" in os.path.basename(model).lower(),
                "판": "E2B" if "e2b" in os.path.basename(model).lower() else "E4B" if "e4b" in os.path.basename(model).lower() else "",
                "설치중": bool(p is not None and p.poll() is None),
                "진행": {k: st.get(k) for k in ("끝", "성공", "전체", "글", "오류", "단계")} if st else None}

    @app.get("/api/brain/options")
    async def brain_options(fresh: int = 0):
        st = await asyncio.to_thread(cli_detect.all_status, bool(fresh))
        return {"ok": True, "지금": CFG["두뇌"].get("방식"), "구독": st, "제안": cli_detect.suggest(st), "Gemma": gemma_info()}

    @app.post("/api/brain/login")
    async def brain_login(request: Request):
        b = await request.json()
        name = str((b or {}).get("이름") or "")
        if name not in cli_detect.KINDS:
            return JSONResponse({"ok": False, "오류": "claude 또는 codex 만 돼요"}, status_code=400)
        try:
            await asyncio.to_thread(cli_detect.open_login, name)
        except FileNotFoundError as ex:
            return JSONResponse({"ok": False, "오류": str(ex), "설치": True}, status_code=400)
        logger.info(f"구독 두뇌 로그인 창 열기: {name}")
        return {"ok": True, "안내": "새로 뜬 창에서 본인 계정으로 로그인한 뒤 이 화면에서 '다시 확인'을 눌러 주세요."}

    @app.post("/api/brain/gemma/install")
    async def gemma_install(request: Request):
        try:
            b = await request.json()
        except ValueError:
            b = {}
        size = str((b or {}).get("판") or "E4B").upper()
        if size not in ("E4B", "E2B"):
            return JSONResponse({"ok": False, "오류": "판은 E4B 또는 E2B 만 돼요"}, status_code=400)
        p = gem["proc"]
        if p is not None and p.poll() is None:
            return {"ok": True, "이미": True}
        py = sys.executable.replace("pythonw.exe", "python.exe")
        try:
            os.remove(gem_status)
        except OSError:
            pass
        gem["proc"] = __import__("subprocess").Popen(
            [py, "-B", "-X", "utf8", setup_py, "gemma-install", "--prefix", prefix, "--data", C.path(CFG, "자료"), "--status", gem_status,
             "--gemma", size],
            cwd=os.path.dirname(setup_py), creationflags=getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0))
        logger.info(f"Gemma 설치 시작({size}) PID {gem['proc'].pid}")
        return {"ok": True, "PID": gem["proc"].pid}

    @app.get("/api/brain/gemma/status")
    async def gemma_status():
        info = gemma_info()
        if info["진행"] and info["진행"].get("끝") and info["진행"].get("성공"):
            _reload()      # 설치 프로그램이 적은 두뇌 경로를 읽어 둠
            info = gemma_info()
        return {"ok": True, **info}

    @app.post("/api/brain/gemma/remove")
    async def gemma_remove():
        if str(CFG["두뇌"].get("방식")) == "local":
            return JSONResponse({"ok": False, "오류": "지금 두뇌가 Gemma 예요. 먼저 다른 두뇌로 바꾼 뒤 지워 주세요."}, status_code=400)
        p = gem["proc"]
        if p is not None and p.poll() is None:
            return JSONResponse({"ok": False, "오류": "Gemma 를 받는 중이에요. 끝난 뒤 지워 주세요."}, status_code=400)
        py = sys.executable.replace("pythonw.exe", "python.exe")
        sp = __import__("subprocess")
        r = await asyncio.to_thread(sp.run, [py, "-B", "-X", "utf8", setup_py, "gemma-remove", "--prefix", prefix, "--data", C.path(CFG, "자료"),
                                             "--status", os.path.join(C.path(CFG, "로그"), "gemma_remove_status.json")],
                                    capture_output=True, cwd=os.path.dirname(setup_py), creationflags=getattr(sp, "CREATE_NO_WINDOW", 0))
        try:
            res = json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return JSONResponse({"ok": False, "오류": "지우지 못했어요(기록 파일을 봐 주세요)."}, status_code=500)
        _reload()
        logger.info(f"Gemma 지움: {res.get('지움')} {res.get('돌려준')} 못지움={res.get('못지움')}")
        return {**res, "Gemma": gemma_info()}

    # ---------------------------------------------------------------- 통역(번역만 — 두뇌 대화·도구로 안 넘김) · 원어민 목소리 부품
    from .core import fx, interp
    fx.set_dir(C.path(CFG, "자료"))
    interp_job = {"proc": None}
    interp_status = os.path.join(C.path(CFG, "로그"), "interp_status.json")

    def interp_runtime():
        run = CFG.get("실행") or {}
        py = os.path.expandvars(str(run.get("통역_파이썬") or "")) or os.path.join(prefix, "runtime", "python-interp", "python.exe")
        root = C.path(CFG, "모델")
        langs = []
        for code, info in interp.L.langs(CFG).items():
            v = str(info.get("목소리") or "")
            ms = interp.L.models_of(v)
            langs.append({"코드": code, "이름": info.get("이름") or code, "목소리": bool(v),
                          "받음": bool(ms) and all(os.path.isdir(os.path.join(root, m)) for m in ms)})
        st = {}
        try:
            with open(interp_status, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            pass
        p = interp_job["proc"]
        return {"부품": os.path.isfile(py), "언어": langs, "엔진": str((CFG.get("통역") or {}).get("목소리_엔진") or "원어민"),
                "설치중": bool(p is not None and p.poll() is None), "기록폴더": C.path(CFG, "로그"),
                "진행": {k: st.get(k) for k in ("끝", "성공", "전체", "글", "오류")} if st else None}

    @app.get("/api/interp")
    async def interp_get(after: int = 0):
        return {"ok": True, **interp.view(CFG), "최근": interp.recent(after), "켜기_가능": interp.enabled(CFG)}

    @app.post("/api/interp")
    async def interp_post(request: Request):
        try:
            b = await request.json()
        except ValueError:
            b = {}
        b = b if isinstance(b, dict) else {}
        err = interp_set(b.get("켜기"), str(b.get("언어") or "").strip(), "화면 단추")
        if err:
            return JSONResponse({"ok": False, "오류": err}, status_code=400)
        return {"ok": True, **interp.view(CFG)}

    def interp_set(on, lang, why):
        """통역 켜기·끄기·언어 바꾸기(PC 화면 단추·폰 통역 화면 공통) → 오류 글 또는 ''."""
        if on is False:
            interp.turn_off(why)
            broadcast_all({"type": "interp", "state": "off", **interp.view(CFG)})
            return ""
        if not interp.enabled(CFG):
            return "설정에서 통역이 꺼져 있어요"
        if lang and lang != "auto" and lang not in interp.L.langs(CFG):
            return "모르는 언어예요"
        if on is True or not interp.active(CFG):
            interp.turn_on(CFG, lang or "auto")
        if lang:
            interp.set_mode(CFG, lang)
        interp.warm_voice(CFG)
        broadcast_all({"type": "interp", "state": "on", **interp.view(CFG)})
        return ""

    def broadcast_all(ev):
        """PC 화면 + 지금 폰 대화(있으면)."""
        broadcast(ev)
        link = CURRENT.get("link")
        if link is not None:
            link.ui(ev)

    @app.get("/api/interp/runtime")
    async def interp_runtime_get():
        info = interp_runtime()
        if info["진행"] and info["진행"].get("끝") and info["진행"].get("성공") and not (CFG.get("실행") or {}).get("통역_파이썬"):
            _reload()          # 설치 프로그램이 적은 통역 목소리 경로를 읽어 둠
            info = interp_runtime()
        return {"ok": True, **info}

    @app.post("/api/interp/install")
    async def interp_install():
        p = interp_job["proc"]
        if p is not None and p.poll() is None:
            return {"ok": True, "이미": True}
        try:
            os.remove(interp_status)
        except OSError:
            pass
        sp = __import__("subprocess")
        interp_job["proc"] = sp.Popen([sys.executable.replace("pythonw.exe", "python.exe"), "-B", "-X", "utf8", setup_py, "interp-install",
                                       "--prefix", prefix, "--data", C.path(CFG, "자료"), "--status", interp_status],
                                      cwd=os.path.dirname(setup_py), creationflags=getattr(sp, "CREATE_NO_WINDOW", 0))
        logger.info(f"통역 목소리 설치 시작 PID {interp_job['proc'].pid}")
        return {"ok": True, "PID": interp_job["proc"].pid}

    # ---------------------------------------------------------------- 폰 연결(선택, 기본 꺼짐) — core/phone.py
    from .core import phone as PH
    auth = PHONE["auth"]

    def phone_status(_did=None):
        """폰 앱에 보여 줄 것(비밀값·주소 없음)."""
        return {"비서": C.names(CFG)[0], "판": APP_VERSION, "PC": (os.environ.get("COMPUTERNAME") or "PC")[:30],
                "통역": interp.enabled(CFG), "목소리확인": bool(VP and VP.gate_on()),
                "PC조작": bool((CFG.get("폰") or {}).get("PC조작_허용", True))}

    async def run_phone(ws, did, hello):
        name = str((auth.devices.get(did) or {}).get("이름") or "폰")
        await kick(f"폰 {name}")
        link = PH.PhoneLink(ws, did, name, caps={k: hello.get(k) is True for k in ("open_app", "navigate", "dial", "sms", "confirm")})
        link.loop = asyncio.get_running_loop()
        pc = CFG.get("폰") or {}

        def tf(_ducker):
            return PH.make_transport(ws, link, lead=float(pc.get("앞서보내기_초", 1.5) or 0), hold=float(pc.get("처음모으기_초", 1.0) or 0))

        def ui(ev):
            broadcast(ev)
            link.ui(ev)
        s = Session(CFG, tf, memory=MEM, guards=GUARDS, pet=None, send_ui=ui,
                    opts={"greeting": hello.get("greeting") is True, "phone": link, "voiceprint": VP})
        CURRENT["session"], CURRENT["link"] = s, link

        def on_interp(m):
            err = interp_set(m.get("on") if isinstance(m.get("on"), bool) else None, str(m.get("lang") or "").strip()[:8], "폰 통역 화면")
            if err:
                link.send({"type": "interp", "state": "error", "why": err})
        link.handlers = {"text": lambda m: s.send_text(str(m.get("text") or "")[:2000]),
                         "interp": on_interp,
                         "interp_get": lambda m: link.send({"type": "interp", "state": "view", **interp.view(CFG)}),
                         "bye": lambda m: s.worker.cancel() if s.worker is not None else None}

        async def start(sess):
            tr = sess.transport

            @tr.event_handler("on_client_connected")
            async def _c(_t, _cl):
                broadcast({"type": "conn", "on": True, "via": "폰", "name": name})
                broadcast({"type": "phone", "state": "on", "name": name})
                await sess.warmup()
                await sess.greet()

            @tr.event_handler("on_client_disconnected")
            async def _d(_t, _cl):
                await sess.worker.cancel()
        s.build_hook = start
        logger.info(f"폰 대화 시작: {did}")
        try:
            await _run_with_hook(s)
        finally:
            link.close()
            if CURRENT.get("session") is s:
                CURRENT["session"], CURRENT["link"] = None, None
                broadcast({"type": "conn", "on": False})
            broadcast({"type": "phone", "state": "off", "name": name})
            logger.info(f"폰 대화 끝: {did}")

    gw = PHONE["gw"] = PH.Gateway(CFG, auth, run_phone, phone_status)

    @app.on_event("startup")
    async def _phone_start():
        if PH.enabled(CFG):
            await gw.start()

    async def phone_apply():
        """설정 폰.켜기·테일스케일_허용 을 바꾼 뒤 — 관문을 다시 켜거나 끔. 끄면 지금 폰 대화도 끝냄."""
        if not PH.enabled(CFG) and CURRENT.get("link") is not None:
            await kick("폰 연결 끔")
        await gw.start()

    @app.get("/api/phone")
    async def phone_get():
        link = CURRENT.get("link")
        return {"ok": True, **gw.info(), "기기": auth.list(), "코드_남은초": auth.code_left(),
                "대화중_폰": link.name if link is not None else None}

    @app.post("/api/phone/code")
    async def phone_code():
        if not gw.running():
            return JSONResponse({"ok": False, "오류": "폰 연결을 먼저 켜 주세요"}, status_code=400)
        addrs = PH.lan_addresses(CFG)
        if not addrs:
            return JSONResponse({"ok": False, "오류": "이 PC 가 집 안 네트워크(와이파이·유선)에 연결돼 있지 않아요"}, status_code=400)
        code, ttl = auth.new_code()
        url = PH.pair_url(addrs, PH.port(CFG), code, gw.fp, phone_status()["PC"])
        return {"ok": True, "코드": code, "초": ttl, "주소": addrs, "포트": PH.port(CFG), "지문": PH.fp_words(gw.fp), "QR": PH.qr_svg(url)}

    @app.post("/api/phone/remove")
    async def phone_remove(request: Request):
        b = await request.json()
        did = None if (b or {}).get("전부") is True else str((b or {}).get("기기") or "")
        if did == "":
            return JSONResponse({"ok": False, "오류": "지울 기기를 골라 주세요"}, status_code=400)
        link = CURRENT.get("link")
        n = auth.remove(did)
        if link is not None and (did is None or link.did == did):
            await kick("등록 지움")
        return {"ok": True, "지움": n, "기기": auth.list()}

    # ---------------------------------------------------------------- 내 목소리 등록(선택) — core/voiceprint.py
    vp_clips = []
    vp_job = {"proc": None}
    vp_status = os.path.join(C.path(CFG, "로그"), "voiceprint_status.json")

    def vp_install_state():
        st = {}
        try:
            with open(vp_status, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            pass
        p = vp_job["proc"]
        return {"설치중": bool(p is not None and p.poll() is None),
                "진행": {k: st.get(k) for k in ("끝", "성공", "전체", "글", "오류")} if st else None}

    @app.get("/api/voiceprint")
    async def vp_get():
        from .core.voiceprint import ENROLL_MIN, SENTENCES
        return {"ok": True, **VP.view(), "모은문장": len(vp_clips), "받기": vp_install_state(), "읽을문장": list(SENTENCES),
                "최소문장": ENROLL_MIN}

    def _pcm_ok(pcm):
        return 16000 <= len(pcm) <= EAR_MAX_BYTES and len(pcm) % 2 == 0

    @app.post("/api/voiceprint/clip")
    async def vp_clip(request: Request):
        from .core.voiceprint import ENROLL_MIN_SEC, SR, speech_part
        pcm = await request.body()
        if not _pcm_ok(pcm):
            return JSONResponse({"ok": False, "오류": "소리 길이가 맞지 않아요(0.5~12초)"}, status_code=400)
        if not VP.ready():
            return JSONResponse({"ok": False, "오류": "목소리 확인 모델을 먼저 받아 주세요"}, status_code=400)
        import numpy as np
        sec = len(speech_part(np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0)) / SR
        if sec < ENROLL_MIN_SEC:
            return {"ok": True, "받음": False, "말_초": round(sec, 1), "모은문장": len(vp_clips),
                    "안내": "말소리가 짧게 들렸어요. 문장을 끝까지 또박또박 읽어 주세요."}
        if len(vp_clips) >= 8:
            vp_clips.pop(0)
        vp_clips.append(pcm)
        return {"ok": True, "받음": True, "말_초": round(sec, 1), "모은문장": len(vp_clips)}

    @app.post("/api/voiceprint/finish")
    async def vp_finish():
        try:
            ok, msg, info = await asyncio.to_thread(VP.enroll, list(vp_clips))
        except Exception as ex:  # noqa: BLE001
            return JSONResponse({"ok": False, "오류": f"등록하지 못했어요({ex.__class__.__name__})"}, status_code=500)
        if ok:
            vp_clips.clear()
            logger.info(f"내 목소리 등록: {msg}")
        return {"ok": ok, "글": msg, **info, **VP.view()} if ok else JSONResponse({"ok": False, "오류": msg, **info}, status_code=400)

    @app.post("/api/voiceprint/reset")
    async def vp_reset():
        vp_clips.clear()
        return {"ok": True, "모은문장": 0}

    @app.post("/api/voiceprint/forget")
    async def vp_forget():
        vp_clips.clear()
        VP.forget()
        logger.info("내 목소리 등록 지움")
        return {"ok": True, **VP.view()}

    @app.post("/api/voiceprint/test")
    async def vp_test(request: Request):
        pcm = await request.body()
        if not _pcm_ok(pcm):
            return JSONResponse({"ok": False, "오류": "소리 길이가 맞지 않아요(0.5~12초)"}, status_code=400)
        if VP.me is None:
            return JSONResponse({"ok": False, "오류": "먼저 목소리를 등록해 주세요"}, status_code=400)
        r = await asyncio.to_thread(VP.score_pcm, pcm)
        return {"ok": True, **r, "문턱": VP.threshold(bool(r.get("짧음"))), "같은사람": VP.is_me(r)}

    @app.get("/api/voiceprint/install")
    async def vp_install_get():
        return {"ok": True, **vp_install_state(), "모델있음": VP.ready()}

    @app.post("/api/voiceprint/install")
    async def vp_install():
        p = vp_job["proc"]
        if p is not None and p.poll() is None:
            return {"ok": True, "이미": True}
        if VP.ready():
            return {"ok": True, "이미있음": True}
        try:
            os.remove(vp_status)
        except OSError:
            pass
        sp = __import__("subprocess")
        vp_job["proc"] = sp.Popen([sys.executable.replace("pythonw.exe", "python.exe"), "-B", "-X", "utf8", setup_py, "voiceprint-install",
                                   "--prefix", prefix, "--data", C.path(CFG, "자료"), "--status", vp_status],
                                  cwd=os.path.dirname(setup_py), creationflags=getattr(sp, "CREATE_NO_WINDOW", 0))
        logger.info(f"목소리 확인 모델 받기 시작 PID {vp_job['proc'].pid}")
        return {"ok": True, "PID": vp_job["proc"].pid}

    # ---------------------------------------------------------------- 펫 프로그램(실행 틀)만 다시 설치 — 설치 때 '펫' 단계를 못 받았을 때
    pet_job = {"proc": None}
    pet_status = os.path.join(C.path(CFG, "로그"), "pet_status.json")

    def pet_runtime():
        """펫 실행 틀이 설치돼 있는지 + 직접 받을 때 필요한 것(주소·파일 이름·크기)."""
        run = CFG.get("실행") or {}
        exe = os.path.expandvars(str(run.get("펫_실행파일") or "")) or os.path.join(prefix, "runtime", "electron", "electron.exe")
        have = os.path.isfile(exe)
        help_ = {}
        try:
            with open(os.path.join(os.path.dirname(setup_py), "runtimes.json"), encoding="utf-8") as f:
                e = json.load(f)["electron"]
            help_ = {"주소": e["url"], "파일": os.path.basename(e["url"]), "크기": e["size"], "크기_글": f"{e['size'] / 1024 / 1024:.0f}MB"}
        except (OSError, ValueError, KeyError):
            pass
        st = {}
        try:
            with open(pet_status, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            pass
        p = pet_job["proc"]
        from .pet_link.face import mode_on
        return {"있음": have, "얼굴_펫": mode_on(CFG) and bool((CFG.get("펫") or {}).get("켜기", True)),
                "설치중": bool(p is not None and p.poll() is None), "직접받기": help_, "기록폴더": C.path(CFG, "로그"),
                "진행": {k: st.get(k) for k in ("끝", "성공", "전체", "글", "오류")} if st else None}

    @app.get("/api/pet/runtime")
    async def pet_runtime_get():
        info = pet_runtime()
        if info["진행"] and info["진행"].get("끝") and info["진행"].get("성공") and not (CFG.get("실행") or {}).get("펫_실행파일"):
            _reload()          # 설치 프로그램이 적은 펫 경로를 읽어 둠
            info = pet_runtime()
        return {"ok": True, **info}

    @app.post("/api/pet/install")
    async def pet_install(request: Request):
        try:
            b = await request.json()
        except ValueError:
            b = {}
        p = pet_job["proc"]
        if p is not None and p.poll() is None:
            return {"ok": True, "이미": True}
        args = [sys.executable.replace("pythonw.exe", "python.exe"), "-B", "-X", "utf8", setup_py, "pet-install", "--prefix", prefix,
                "--data", C.path(CFG, "자료"), "--status", pet_status]
        f = str((b or {}).get("파일") or "").strip()
        if f:
            if not (os.path.isfile(f) and f.lower().endswith(".zip")):
                return JSONResponse({"ok": False, "오류": "고른 파일을 찾을 수 없어요(.zip 파일을 골라 주세요)."}, status_code=400)
            args += ["--file", f]
        try:
            os.remove(pet_status)
        except OSError:
            pass
        sp = __import__("subprocess")
        pet_job["proc"] = sp.Popen(args, cwd=os.path.dirname(setup_py), creationflags=getattr(sp, "CREATE_NO_WINDOW", 0))
        logger.info(f"펫 프로그램 설치 시작 PID {pet_job['proc'].pid}" + (" (받아 둔 파일)" if f else ""))
        return {"ok": True, "PID": pet_job["proc"].pid}

    @app.on_event("startup")
    async def _prewarm():
        asyncio.ensure_future(cli_brain.prewarm(CFG))

    @app.post("/api/brain/models")
    async def brain_models(request: Request):
        b = await request.json()
        over = (b or {}).get("두뇌") if isinstance(b, dict) else None
        if not isinstance(over, dict):
            over = None
        if over:
            clean, errors, _w = S.validate({"두뇌": {k: v for k, v in over.items() if k in ("방식", "주소", "호환_주소")}}, CFG)
            errors = {k: v for k, v in errors.items() if k != "두뇌.호환_모델"}       # 목록을 받으려는 것이라 모델 이름은 아직 없어도 됨
            if errors:
                return JSONResponse({"ok": False, "오류": "; ".join(errors.values())}, status_code=400)
            over = {k.split(".", 1)[1]: v for k, v in clean.items()}
        r = await S.brain_models(CFG, over)
        logger.info(f"두뇌 모델 목록: ok={r.get('ok')} {len(r.get('모델') or [])}개 {r.get('오류') or ''}")
        return r

    @app.post("/api/brain/test")
    async def brain_test(request: Request):
        b = await request.json()
        over = (b or {}).get("두뇌") if isinstance(b, dict) else None
        if over is not None and not isinstance(over, dict):
            over = None
        if over:
            clean, errors, _w = S.validate({"두뇌": over}, CFG)
            if errors:
                return JSONResponse({"ok": False, "오류": "; ".join(errors.values())}, status_code=400)
            over = {k.split(".", 1)[1]: v for k, v in clean.items()}
        r = await S.brain_test(CFG, over)
        logger.info(f"두뇌 연결 시험: {r.get('방식')} ok={r.get('ok')} {r.get('ms')}ms 도구={r.get('도구')} {r.get('오류') or ''}")
        return r

    # ---------------------------------------------------------------- 소리 시험·이름 연습
    @app.post("/api/ear/hear")
    async def ear_hear(request: Request):
        pcm = await request.body()
        if len(pcm) < 3200 or len(pcm) > EAR_MAX_BYTES or len(pcm) % 2:
            return JSONResponse({"ok": False, "오류": "소리 길이가 맞지 않아요(0.1~12초)"}, status_code=400)
        name = (request.query_params.get("name") or "").strip()[:12]
        link = EarLink(CFG["포트"]["귀"])
        t0 = time.perf_counter()
        try:
            r = await asyncio.wait_for(link.transcribe(pcm, max_tokens=24 if name else None, quiet=True), 30)
        except (OSError, ConnectionError, asyncio.TimeoutError):
            return JSONResponse({"ok": False, "오류": "받아쓰기(귀) 서버가 꺼져 있거나 바빠요."}, status_code=503)
        finally:
            await link.close()
        text = (r.get("text") or "").strip()
        out = {"ok": True, "글": text[:200], "ms": round((time.perf_counter() - t0) * 1000), "소리_초": round(len(pcm) / 32000, 2)}
        if name:
            m = NameMatcher(name, [x for x in request.query_params.get("aliases", "").split(",") if x.strip()][:20])
            out["부름"] = bool(m.call(text))
            out["비슷"] = bool(m.near(text))
        return out

    @app.post("/api/name/learn")
    async def name_learn(request: Request):
        b = await request.json()
        name = str((b or {}).get("이름") or "").strip()[:12]
        heard = [str(x)[:60] for x in ((b or {}).get("들은것") or [])][:10]
        if not name:
            return JSONResponse({"ok": False, "오류": "이름이 비어 있어요"}, status_code=400)
        keep = [str(x)[:20] for x in ((b or {}).get("기존") or []) if isinstance(x, str)][:20]
        al = learn_aliases(name, heard, keep=keep)
        m = NameMatcher(name, al)
        hit = sum(1 for h in heard if m.call(h) or m.near(h) or m.only_name(h))
        return {"ok": True, "별칭": al, "경고": name_warning(name), "알아들음": hit, "들은수": len(heard)}

    @app.post("/api/name/check")
    async def name_check(request: Request):
        b = await request.json()
        return {"ok": True, "경고": name_warning(str((b or {}).get("이름") or ""))}

    @app.post("/api/voice/sample")
    async def voice_sample(request: Request):
        import httpx
        b = await request.json()
        text = re.sub(r"\s+", " ", str((b or {}).get("글") or "")).strip()[:120]
        if not text:
            text = C.fill(CFG, "안녕하세요, {이름}입니다. 이 목소리로 말씀드릴게요.")
        req = {"text": text}
        v = (b or {}).get("목소리")
        if v == "auto":      # '옷에 맞춤(자동)' → 지금 실제로 말할 목소리(펫이 입은 옷 > 펫 성별)
            from .core import voice_choice
            from .pet_link.face import pet_outfit
            outfit = await asyncio.to_thread(pet_outfit, CFG) if PET is not None else None
            v = voice_choice.voice_for_outfit(outfit) or voice_choice.voice_for_gender((CFG.get("펫") or {}).get("성별"))
        if isinstance(v, str) and re.match(r"^[a-z0-9_]{1,40}$", v):
            req["voice"] = v
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=3.0)) as cl:
                r = await cl.post(f"http://127.0.0.1:{int(CFG['포트']['목소리'])}/tts", json=req)
        except httpx.HTTPError:
            return JSONResponse({"ok": False, "오류": "목소리 서버가 꺼져 있어요."}, status_code=503)
        if r.status_code != 200:
            return JSONResponse({"ok": False, "오류": f"목소리를 만들지 못했어요({r.status_code})."}, status_code=502)
        return Response(r.content, media_type="audio/wav")

    @app.get("/api/voice/status")
    async def voice_status():
        import httpx
        out = {"ok": True, "목소리": None, "귀": False}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=2.0)) as cl:
                r = await cl.get(f"http://127.0.0.1:{int(CFG['포트']['목소리'])}/status")
                j = r.json()
                out["목소리"] = {k: j.get(k) for k in ("engine", "device", "ready", "fallback_reason", "voice", "voice_fallback") if k in j}
        except Exception:  # noqa: BLE001
            pass
        try:
            rd, wr = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", int(CFG["포트"]["귀"])), 2)
            wr.write(b'{"op":"ping"}\n')
            await wr.drain()
            out["귀"] = b"pong" in (await asyncio.wait_for(rd.readline(), 3))
            wr.close()
        except Exception:  # noqa: BLE001
            pass
        return out

    @app.post("/api/client")
    async def client_report(request: Request):
        b = await request.json()
        st = (b or {}).get("마이크") or {}
        if not isinstance(st, dict):
            st = {}
        CLIENT_AUDIO.clear()
        CLIENT_AUDIO.update({
            "메아리지우기": st.get("echoCancellation"), "잡음줄이기": st.get("noiseSuppression"),
            "소리크기자동": st.get("autoGainControl"), "장치": str((b or {}).get("장치") or "")[:120],
            "지원": {k: bool(v) for k, v in ((b or {}).get("지원") or {}).items()
                    if k in ("echoCancellation", "noiseSuppression", "autoGainControl")},
            "때": time.strftime("%H:%M:%S")})
        ok = CLIENT_AUDIO["메아리지우기"] is True
        (logger.info if ok else logger.warning)(
            f"화면 마이크 처리: 메아리 지우기 {CLIENT_AUDIO['메아리지우기']} · 잡음 줄이기 {CLIENT_AUDIO['잡음줄이기']}"
            f" · 소리 크기 자동 {CLIENT_AUDIO['소리크기자동']}" + ("" if ok else " — 메아리 지우기가 꺼져 있어 거짓 끼어들기가 생길 수 있음"))
        broadcast({"type": "client_audio", **CLIENT_AUDIO})
        return {"ok": True, "메아리지우기": ok}

    # ---------------------------------------------------------------- 기억
    @app.get("/api/memory")
    async def memory_list():
        if MEM is None:
            return {"ok": False, "오류": "기억이 꺼져 있어요"}
        return {"ok": True, "지식": MEM.list_facts(),
                "일기": [{"날짜": d["날짜"], "내용": d["내용"][-1500:]} for d in MEM.diary_list(60)]}

    @app.post("/api/memory/delete")
    async def memory_delete(request: Request):
        if MEM is None:
            return {"ok": False}
        b = await request.json()
        if b.get("all") is True:
            MEM.clear_all()
            logger.info("기억 전부 지움(화면)")
            return {"ok": True, "지움": "전부"}
        if b.get("id"):
            return {"ok": MEM.delete(str(b["id"]))}
        if b.get("day"):
            return {"ok": MEM.diary_delete(str(b["day"]))}
        return JSONResponse({"ok": False, "오류": "id·day·all 중 하나"}, status_code=400)

    # ---------------------------------------------------------------- 업데이트
    def _upd_err(ex, code=400):
        return JSONResponse({"ok": False, "오류": str(ex), **upd.view()}, status_code=code)

    @app.get("/api/update")
    async def update_view():
        return upd.view()

    @app.post("/api/update/check")
    async def update_check():
        try:
            v = await asyncio.to_thread(upd.check)
            logger.info(f"업데이트 확인: 지금 {v['지금_판']} · 새 판 {(v['새판'] or {}).get('판') or '없음'}")
            return v
        except UpdateError as ex:
            return _upd_err(ex)

    @app.post("/api/update/download")
    async def update_download():
        if upd.busy:
            return _upd_err("지금 " + upd.busy + "이에요.", 409)

        def run():
            try:
                upd.download()
                logger.info(f"업데이트 받음·확인됨: {upd.ready}")
                broadcast({"type": "update", **upd.view()})
            except UpdateError as ex:
                upd.error = str(ex)
                logger.warning(f"업데이트 받기 실패: {ex}")
                broadcast({"type": "update", **upd.view()})
        if not upd.latest:
            return _upd_err("'업데이트 확인'을 먼저 눌러 주세요.")
        threading.Thread(target=run, name="update-download", daemon=True).start()
        return {"ok": True, "시작": True}

    @app.post("/api/update/apply")
    async def update_apply():
        try:
            r = await asyncio.to_thread(upd.apply)
            logger.info(f"업데이트 바꾸기 시작: {r['판']}")
            broadcast({"type": "update", "바꾸는중": True, **upd.view()})
            return r
        except UpdateError as ex:
            return _upd_err(ex)

    @app.post("/api/update/seen")
    async def update_seen():
        return {"ok": upd.mark_seen()}

    @app.post("/api/update/page")
    async def update_page():
        new = upd.view().get("새판") or {}
        url = new.get("안내주소") or ""
        if not url:
            return JSONResponse({"ok": False, "오류": "안내 주소가 없어요"}, status_code=400)
        await asyncio.to_thread(os.startfile, url)
        return {"ok": True}

    @app.post("/api/shutdown")
    async def shutdown():
        from .core import cli_brain
        asyncio.get_running_loop().call_later(0.3, lambda: (cli_brain.kill_all_sync(), os._exit(0)))
        return {"ok": True}

    return app


def _watch_parent(pid):
    """실행기(부모)가 사라지면 본체도 끝냄 — 실행기가 비정상으로 꺼져도 본체가 홀로 남지 않게."""
    import ctypes
    import threading

    def run():
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, int(pid))   # SYNCHRONIZE
        if not h:
            logger.warning(f"부모 PID {pid} 를 못 엶 — 부모 감시 안 함")
            return
        k.WaitForSingleObject(h, 0xFFFFFFFF)
        logger.info(f"부모(실행기) PID {pid} 가 끝남 → 본체 끝냄")
        try:
            from .core import cli_brain
            cli_brain.kill_all_sync()
        except Exception:  # noqa: BLE001
            pass
        os._exit(0)
    if sys.platform == "win32":
        threading.Thread(target=run, name="parent-watch", daemon=True).start()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kimbiseo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("serve")
    a1.add_argument("--settings")
    a1.add_argument("--parent_pid", type=int, default=0)   # 실행기가 켬: 그 프로세스가 끝나면 본체도 끝남
    a2 = sub.add_parser("script")
    a2.add_argument("script")
    a2.add_argument("--out", required=True)
    a2.add_argument("--settings")
    a = ap.parse_args(argv)
    _setup(a.settings)
    _mark_running()
    if a.cmd == "script":
        rep = asyncio.run(run_script(a.script, a.out))
        print(json.dumps({k: rep[k] for k in ("초", "두뇌", "건짐", "캐시가드", "이어받은_차례", "이름")}, ensure_ascii=False))
        return 0
    if getattr(a, "parent_pid", 0):
        _watch_parent(a.parent_pid)
    import uvicorn
    uvicorn.run(make_app(), host="127.0.0.1", port=int(CFG["포트"]["본체"]), log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
