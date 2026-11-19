# 대화 한 번(연결 하나) — 파이프라인을 만들어 돌리고, 끝나면 기억을 정리한다.
#   전송부 → 귀(EarSTT) → 사용자 차례 모음(VAD·끼어들기·한국어 말끝) → 문맥 줄이기 → 두뇌(BrainLLM + 도구) → 목소리(VoiceTTS)
#   → 전송부 내보내기 → 비서 차례 모음.  관찰자가 상태·자막·지연·소리 크기 모양을 기록하고 펫에 신호를 보낸다.
#   시작: 지시문(고정) + 기억 블록 + 지난 대화(문맥.이어가기_시간 안이면 최근 문맥.이어가기_차례 차례) → 두뇌 앞부분 미리 읽히기(로컬)
#         → 연결 인사(대화.연결인사, 문구 = 비서.인사).
#   글 입력(send_text): 같은 두뇌로. 비서가 말하는 중이면 끊고 답한다. 대기 중이어도 글은 바로 받는다.
#   도중: 문맥을 2초마다(바뀌었을 때만) 자료 폴더 context.json 에 저장 — 갑자기 꺼져도 이어 가기.
#   끝: 대화 원문 보관 → 일기 요약(두뇌) → 자동 기억(두뇌가 고른 사실) → 이어가기 저장(최근 차례 + 요약).
import asyncio
import json
import time
import uuid

import httpx
from loguru import logger
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMMessagesAppendFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from . import config as C
from . import debate, interp, prompt, turns
from .i18n import tr
from .audio_smooth import Ducker
from .brain import NoBrain, make_llm, simple_text
from .prompt import CLI_KINDS
from .memory import plain_turns
from .observer import ContextTrim, Observer
from .state import SessionState
from .stt import EarSTT
from .tts import VoiceTTS
from ..tools.registry import ToolContext, load_packs, register, tools_schema


class Session:
    def __init__(self, cfg, transport_factory, memory=None, guards=None, pet=None, sid=None, send_ui=None,
                 opts=None, ear=None, voice=None):
        self.cfg = cfg
        self.sid = sid or uuid.uuid4().hex[:10]
        self.memory = memory
        self.guards = guards if guards is not None else {}
        self.opts = dict(opts or {})
        self.ducker = Ducker(24000)
        self.transport = transport_factory(self.ducker)
        self._ui = send_ui or (lambda ev: None)
        self.state = SessionState(cfg, self._send_ui, pet=pet)
        self.ear, self.voice = ear, voice
        self.worker = None
        self.pipeline = None
        self.context = None
        self.llm = None
        self.handlers = {}
        self.tool_ctx = None
        self._retired = []          # 두뇌를 바꿔 파이프라인에서 뺀 옛 두뇌(끝날 때 정리)
        self.observer = None
        self.end_report = {}
        self.restored_n = 0
        self.summary_in = ""
        self._saved_sig = None

    # ---- 화면·소리 줄이기
    def _send_ui(self, ev):
        k = ev.get("type")
        if k == "duck":
            self.ducker.set(float(ev.get("volume", 0.3)))
        elif k in ("unduck", "interrupted"):
            self.ducker.set(1.0)
        self._ui(ev)

    def save_settings(self, changes):
        try:
            C.save_user(self.cfg, changes)
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"설정 저장 실패: {ex.__class__.__name__}")

    # ---- 만들기
    def build(self):
        cfg, st = self.cfg, self.state
        dc = cfg["대화"]
        turns.WIDE.update(dict(dc.get("말끝_넓게") or {}))
        link = self.opts.get("phone")          # 폰 앱으로 대화(core/phone.PhoneLink) — 폰 도구 묶음을 더 붙임
        st.debate_memory = self.memory
        st.debate_adult_allowed = link is None     # 폰 앱(전체 이용가)은 성인 말싸움 항상 끔 — PC 판만
        st.on_debate_change = self._refresh_system
        if link is not None:                   # 폰은 앱의 마이크 단추가 부르는 몫 — 이름을 불러야 대답하는 모드는 끔
            st.always_name = False
            st.set_wake(False, why="폰 대화")
        specs, handlers = load_packs(cfg, extra=("phone",) if link is not None else (), phone=link is not None)
        self.cli = str(cfg["두뇌"].get("방식") or "") in CLI_KINDS
        if self.cli and not cfg["두뇌"].get("구독_도구", True):
            # 구독 두뇌는 그 프로그램 자체의 도구·파일 권한은 늘 끔. 김비서 도구(날씨·계산·기억 등)는 글 약속
            # (<<도구 {인자}>> 한 줄 → 본체가 실행 → 결과를 다음 차례로)으로 붙인다 — 두뇌.구독_도구 = false 면 대화 전용
            specs, handlers = [], {}
        self.specs = specs
        names = [s["function"]["name"] for s in specs]
        restored, summary = [], ""
        rc = cfg.get("문맥") or {}
        if self.memory is not None and rc.get("이어가기", True) and not self.opts.get("새대화"):
            restored, summary = self.memory.load_context(float(rc.get("이어가기_시간", 6)))
        self.restored_n, self.summary_in = len(restored), summary
        sysmsg = prompt.system_prompt(cfg, specs, memory=self.memory, summary=summary,
                                      debate=debate.on(st), adult=debate.adult(st))
        self.context = LLMContext(messages=[{"role": "system", "content": sysmsg}] + list(restored),
                                  tools=tools_schema(specs))
        try:
            self.llm = make_llm(st, cfg, names, self.guards, session_key=self.sid)
        except RuntimeError as ex:   # 열쇠 없음·꾸러미 없음 — 본체는 켜 두고 말로 알려 줌
            logger.warning(f"두뇌를 만들 수 없음: {ex}")
            st.event("brain_error", reason=str(ex)[:200])
            self.llm = NoBrain(str(ex))
        acts = {"save_settings": self.save_settings}
        if link is not None:
            acts.update(phone=link, confirm=link.confirm)      # 위험한 도구의 '실행할까요?' = 폰 화면 단추
        elif self.opts.get("confirm") is not None:
            acts["confirm"] = self.opts["confirm"]             # PC 창의 확인 단추
        self.handlers = handlers
        self.tool_ctx = ToolContext(st, cfg, self.memory, actions=acts)
        self.tool_guard = register(self.llm, specs, handlers, self.tool_ctx)
        stt = EarSTT(st, cfg["포트"]["귀"], ear=self.ear, voiceprint=self.opts.get("voiceprint"))
        tts = VoiceTTS(st, voice=self.voice)
        self._tts = tts
        self._stt = stt
        vad_stop = float(dc.get("말끝_무음_초", 0.2))
        vad_an = SileroVADAnalyzer(params=VADParams(stop_secs=vad_stop))
        turn_an = LocalSmartTurnAnalyzerV3()
        st.vad, st.vad_stop_base = vad_an, vad_stop      # 말싸움: 켜면 말 끝 기다림을 늘리고 끄면 원래 값
        st.smart_turn = turn_an
        st.smart_stop_base = float(getattr(getattr(turn_an, "params", None), "stop_secs", 3.0) or 3.0)
        pair = LLMContextAggregatorPair(
            self.context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=vad_an,
                user_turn_strategies=UserTurnStrategies(
                    start=[turns.BargeStrategy(st)],
                    stop=[turns.KoreanEndStrategy(state=st, turn_analyzer=turn_an)]),
                empty_user_turn=None))
        self.pair = pair
        self._asst_stopped = asyncio.Event()

        @pair.assistant().event_handler("on_assistant_turn_stopped")
        async def _on_asst_stopped(_agg, _msg):
            self._asst_stopped.set()
        trim = ContextTrim(turns=int(cfg["두뇌"].get("기억_차례", 12)), keep_head=1)
        pipeline = Pipeline([self.transport.input(), stt, pair.user(), trim, self.llm, tts,
                             self.transport.output(), pair.assistant()])
        self.pipeline = pipeline
        self.observer = Observer(st, vad_stop)
        self.worker = PipelineWorker(pipeline, params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=24000,
                                                                     enable_metrics=True),
                                     observers=[self.observer], enable_rtvi=False, idle_timeout_secs=None)
        st.event("session", sid=self.sid, brain=self.llm.kind, restored=len(restored), summary=bool(summary),
                 tools=names, name=st.names.name)
        return self

    # ---- 말싸움 켜기/끄기·성인 단계 — 지시문을 지금 대화에 바로 바꾼다(구독 두뇌는 세션도 다시)
    def _refresh_system(self):
        if self.context is None:
            return
        msgs = list(self.context.messages)
        if not msgs or not isinstance(msgs[0], dict) or msgs[0].get("role") != "system":
            return
        msgs[0] = {**msgs[0], "content": prompt.system_prompt(
            self.cfg, getattr(self, "specs", ()), memory=self.memory, summary=self.summary_in,
            debate=debate.on(self.state), adult=debate.adult(self.state))}
        self.context.set_messages(msgs)
        if getattr(self, "cli", False) and hasattr(self.llm, "prepare"):
            try:
                asyncio.ensure_future(self.llm.prepare(msgs[0]["content"], list(self.llm.be.history)))
            except Exception as ex:  # noqa: BLE001
                logger.warning(f"말싸움 지시문으로 구독 두뇌 다시 띄우기 실패: {ex.__class__.__name__}")

    # ---- 화면에서 설정을 바꿨을 때(self.cfg 는 이미 새 값) — '즉시' 항목만 지금 대화에 반영
    async def apply_settings(self, keys):
        """keys = 바뀐 설정 경로들('비서.이름' 등). 반영한 것의 이름 목록을 돌려줌.
        두뇌(방식·주소·모델·열쇠)가 바뀌면 지금 대화의 두뇌 부품을 새로 만들어 파이프라인에서 갈아 끼운다 —
        다음 말부터 새 두뇌가 답한다(대화를 다시 연결하지 않아도 됨)."""
        st, cfg, done = self.state, self.cfg, []
        keys = set(keys)
        brain_keys = {k for k in keys if k.startswith("두뇌.") and k != "두뇌.모드"}
        if brain_keys and self.llm is not None:
            kind = await self._rebuild_brain()
            if kind:
                done.append("두뇌")
        if keys & {"비서.이름", "비서.별칭"}:
            st.refresh_names()
            if st.pet is not None:
                st.pet.names = [st.names.name] + [a for a in C.names(cfg)[1]]
            done.append("깨우는 이름")
        if self.context is not None and keys & {"비서.이름", "비서.말투", "비서.성격", "비서.답길이", "사용자.호칭", "사용자.기본장소", "화면.얼굴", "말싸움.성인"}:
            # 지시문(자기소개·호칭·말투·성격·답 길이·말싸움 단계)을 새로 — 앞부분이 바뀌므로 두뇌 캐시는 한 번 다시 읽음
            self._refresh_system()
            done.append("자기소개·호칭·말투")
        if "목소리.말속도" in keys:
            st.speed = float((cfg.get("목소리") or {}).get("말속도", 1.0) or 1.0)
            done.append("말 빠르기")
        if "목소리.문장_쉼_초" in keys:
            done.append("문장 사이 쉼")       # 목소리 부품이 문장마다 설정을 다시 읽음(tts.VoiceTTS.run_tts)
        if "대화.이름부르기" in keys and self.opts.get("phone") is None:     # 폰 대화는 마이크 단추로 부르므로 이름 부르기 안 씀
            st.always_name = bool((cfg.get("대화") or {}).get("이름부르기", False))
            st.set_wake(st.always_name, why="설정")
            done.append("이름 부르기")
        if "대화.끼어들기_감도" in keys and getattr(self, "_stt", None) is not None:
            self._stt.corr_need = float(cfg["대화"].get("메아리_상관_기준", 0.9))
            done.append("끼어들기 감도")
        if "두뇌.모드" in keys and self.llm is not None and hasattr(self.llm, "mode"):
            self.llm.mode = str(cfg["두뇌"].get("모드") or "빠른")
            done.append("두뇌 모드")
        if keys & {"목소리.목소리", "펫.성별"} and getattr(self, "_tts", None) is not None:
            # 목소리 서버는 요청마다 "voice" 를 받으므로(ensure_voice) 서버를 다시 켜지 않아도
            # 다음 문장부터 새 목소리로 말한다. 자산이 없으면 서버가 기본 목소리로 대체하고 로그를 남긴다.
            m = getattr(self._tts, "mouth", None)
            if m is not None and hasattr(m, "voice"):
                m.voice = (cfg.get("목소리") or {}).get("목소리") or None
                done.append("목소리 견본")
        if done:
            st.event("settings_applied", what=done)
        return done

    # ---- 두뇌 바꾸기(설정 저장 직후 — 대화를 다시 연결하지 않고 다음 말부터 새 두뇌)
    async def _rebuild_brain(self):
        """지금 대화의 두뇌 부품을 지금 설정으로 새로 만들어 파이프라인에서 갈아 끼운다.
        도구도 새 두뇌에 다시 달고, 지시문(구독·로컬 두뇌의 말투 차이)도 새로 만든다. 실패해도 대화는 살아 있게 NoBrain."""
        old = self.llm
        names = [s["function"]["name"] for s in (self.specs or ())]
        try:
            new = make_llm(self.state, self.cfg, names, self.guards, session_key=self.sid)
        except RuntimeError as ex:      # 열쇠 없음·꾸러미 없음 — 다음 말에 까닭을 말해 준다
            logger.warning(f"두뇌를 바꿀 수 없음: {ex}")
            msg = tr(str(ex))[:300]
            self.state.event("brain_error", reason=msg, text=msg)
            new = NoBrain(str(ex))
        self.cli = str((self.cfg.get("두뇌") or {}).get("방식") or "") in CLI_KINDS
        try:
            self.tool_guard = register(new, self.specs or [], self.handlers, self.tool_ctx)
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"새 두뇌에 도구를 달지 못함: {ex.__class__.__name__}")
        if self.pipeline is not None and old is not None:
            await self._swap_llm(old, new)
        else:
            self.llm = new
        self._refresh_system()
        logger.info(f"두뇌 바꿈: {getattr(old, 'kind', '?')} → {getattr(self.llm, 'kind', '?')} (다음 말부터)")
        return getattr(self.llm, "kind", "")

    async def _swap_llm(self, old, new):
        """파이프라인에서 옛 두뇌 부품 자리에 새 두뇌를 넣는다(앞뒤 연결·설정 그대로).
        옛 두뇌는 이미 흐르는 답을 마칠 수 있게 연결을 그대로 두고, 대화가 끝날 때 정리한다."""
        try:
            setup = getattr(old, "_setup", None)
            if setup is not None:
                new._setup_started()
                await new.setup(setup)
                new._setup_finished()
                from pipecat.frames.frames import StartFrame
                await new.queue_frame(StartFrame())      # 새 부품의 입력 처리 시작(이미 흐르던 StartFrame 대신)
            prev, nxt = old._prev, old._next
            if prev is not None:
                prev.link(new)
            if nxt is not None:
                new.link(nxt)
            procs = self.pipeline._processors
            i = procs.index(old)
            procs[i] = new
            self.llm = new
            self._retired.append(old)
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"두뇌 갈아 끼우기 실패({ex.__class__.__name__}) — 다음 연결부터 새 두뇌")
            self.llm = new if getattr(new, "_setup", None) is None else old

    async def _cleanup_retired(self):
        for p in self._retired:
            try:
                await p.cleanup()
            except Exception as ex:  # noqa: BLE001
                logger.debug(f"옛 두뇌 정리: {ex.__class__.__name__}")
        self._retired.clear()

    # ---- 시작 인사·앞부분 미리 읽히기
    def _pairs(self, msgs):
        out = []
        for m in msgs:
            if not isinstance(m, dict) or not isinstance(m.get("content"), str):
                continue
            if m.get("role") == "user":
                out.append([m["content"], ""])
            elif m.get("role") == "assistant" and out and not m.get("tool_calls"):
                out[-1][1] = (out[-1][1] + " " + m["content"]).strip()
        return [tuple(x) for x in out]

    async def warmup(self):
        """로컬 두뇌: 지시문·도구·이어 온 차례를 미리 읽혀 둔다(첫 답이 빨라짐). 처음 한 번은 캐시 없이(서버 칸 상태를 모르니).
        구독 두뇌: 이번 대화용 세션(클로드 프로세스·codex 스레드)을 지금 띄워 둔다(인사하는 동안)."""
        llm = self.llm
        if llm is not None and getattr(llm, "kind", "") in CLI_KINDS:
            msgs = list(self.context.messages)
            info = await llm.prepare(msgs[0]["content"], self._pairs(msgs[1:]))
            self.state.event("warmup", **info)
            logger.info(f"구독 두뇌 미리 띄움 {info}")
            return info
        if llm is None or llm.kind != "local":
            return None
        t0 = time.perf_counter()
        try:
            ad = llm.get_llm_adapter()
            ctx = LLMContext(messages=list(self.context.messages) + [{"role": "user", "content": "."}], tools=self.context.tools)
            pfc = await ad.get_llm_invocation_params(ctx, system_instruction=llm._settings.system_instruction,
                                                     convert_developer_to_user=True)
            params = llm.build_chat_completion_params(pfc)
            g = llm.guard
            first = g is not None and not g.hist
            body = {"model": params.get("model"), "messages": params["messages"], "max_tokens": 1, "temperature": 0,
                    "stream": False, **(params.get("extra_body") or {})}
            if params.get("tools"):
                body["tools"] = params["tools"]
            body.pop("timings_per_token", None)
            if first:
                body["cache_prompt"] = False
            base = self.cfg["두뇌"].get("주소") or f"http://127.0.0.1:{self.cfg['포트']['두뇌']}/v1"
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=3.0)) as cl:
                r = await cl.post(base.rstrip("/") + "/chat/completions", json=json.loads(json.dumps(body, default=str)))
                r.raise_for_status()
                j = r.json()
            if g is not None and g.ok:
                try:
                    g.remember(await g.render(params), "", 1)
                except Exception:  # noqa: BLE001
                    g.ok = False
            tm = j.get("timings") or {}
            info = {"초": round(time.perf_counter() - t0, 2), "prompt_n": tm.get("prompt_n"), "cache_n": tm.get("cache_n"),
                    "캐시없이": first}
            self.state.event("warmup", **info)
            logger.info(f"두뇌 앞부분 미리 읽힘 {info}")
            return info
        except Exception as ex:  # noqa: BLE001
            logger.info(f"두뇌 미리 읽히기 건너뜀: {ex.__class__.__name__}")
            return None

    async def greet(self):
        st = self.state
        st.event("status", state="듣는 중")
        if self.cfg["대화"].get("연결인사", True) and self.opts.get("greeting", True):
            text = C.fill(self.cfg, (self.cfg.get("비서") or {}).get("인사") or "네, {이름}입니다. 말씀하세요.")
            # 인사는 두뇌 문맥에 넣지 않음 — 작은 두뇌(Gemma)가 첫 차례에 인사 말투를 따라 하며 도구 없이 날씨를 지어내는 일이 늘었음(17단계 실측)
            await self.worker.queue_frame(TTSSpeakFrame(text, append_to_context=False))
        st.event("wake", on=st.wake)

    # ---- 글 입력
    async def send_text(self, text):
        text = str(text or "").strip()[:2000]
        if not text or self.worker is None:
            return False
        st = self.state
        st.event("typed", text=text)
        st.last_typed = (text, time.time())
        if interp.enabled(self.cfg) and interp.active(self.cfg):
            await self._interp_text(text)    # 통역 중 글 = 말소리와 같은 규칙(번역만 · 두뇌 대화·도구로 안 넘김)
            return True
        say = debate.command(st, text, typed=True)    # 말싸움 켜기/끄기 — 두뇌로 안 넘기고 바로 바꿈
        if say:
            await self.worker.queue_frame(TTSSpeakFrame(say, append_to_context=False))
            return True
        if st.wake and not st.always_name:
            st.set_wake(False, why="글 입력")
        if st.bot_speaking or st.thinking:
            # 끊긴 비서 말은 맨 끝 정리 칸(assistant 모음)이 끊김을 받은 뒤에야 문맥에 들어간다. 그 전에 글을 넣으면
            #   [새 질문, 끊긴 비서 말] 순서가 되어 두뇌가 '이미 답했다'로 볼 수 있음 → 끊김 정리를 잠깐(최대 1초) 기다림.
            asst = self.pair.assistant()
            started = bool(getattr(asst, "_assistant_turn_start_timestamp", None))
            self._asst_stopped.clear()
            try:
                await self.pair.user().push_interruption_task_frame_and_wait()
                if started:
                    await asyncio.wait_for(self._asst_stopped.wait(), 1.0)
            except asyncio.TimeoutError:
                logger.info("글 입력: 끊긴 비서 말 정리를 1초 기다렸지만 안 옴 — 그대로 넣음")
            except Exception as ex:  # noqa: BLE001
                logger.warning(f"글 입력 끼어들기 실패: {ex}")
        debate.touch(st)     # 말싸움 중 사용자 말 = 30분 자동 끔 기준 갱신
        st.turn_no += 1
        st.thinking, st.thinking_t = True, time.time()
        st.event("status", state="생각 중")
        await self.worker.queue_frame(LLMMessagesAppendFrame(messages=[{"role": "user", "content": text}], run_llm=True))
        return True

    async def _interp_text(self, text):
        """통역 중 글 입력(0.1.17): 말소리(stt._interp_turn)와 같은 규칙 — 한국어면 상대 언어로, 외국 글이면 한국어로 번역만 하고 그 언어 목소리로 읽음.
        '통역 그만'·'영어 통역해 줘' 같은 켜기·끄기 글만 받음(글은 이 기기 사용자가 친 것). 두뇌 대화·도구로는 절대 안 넘김."""
        st, cfg = self.state, self.cfg
        s = interp._STATE
        home = interp.L.home_of(cfg)
        hint = s["mode"] if s["mode"] != "auto" else (s["last"] or interp.default_peer(cfg))
        src = interp.L.script_lang(text, hint=hint)
        cmd = interp.L.parse_command(cfg, text) if src == home else None
        if cmd and cmd[0] == "off":
            interp.turn_off("글로 끔")
            st.event("interp", state="off", **interp.view(cfg))
            await self.worker.queue_frame(TTSSpeakFrame(tr("네, 통역 마칠게요."), append_to_context=False))
            return
        if cmd and cmd[0] == "on":
            code = interp.turn_on(cfg, cmd[1])
            interp.warm_voice(cfg, code)
            st.event("interp", state="on", **interp.view(cfg))
            await self.worker.queue_frame(TTSSpeakFrame(tr(f"네, {interp.L.name_of(cfg, code)}로 바꿀게요."), append_to_context=False))
            return
        interp.touch()
        dst = interp.plan(cfg, src)
        sn, dn = interp.L.name_of(cfg, src), interp.L.name_of(cfg, dst)
        st.event("interp", state="translating", src_lang=src, dst_lang=dst, src=text, src_name=sn, dst_name=dn)
        out, who, sec = await interp.translate(cfg, text, src, dst, interp.history())
        if not out:
            logger.warning(f"통역(글) 실패 {src}→{dst}: {who} ({sec:.1f}초)")
            st.event("interp", state="error", src_lang=src, dst_lang=dst, src=text, why=who)
            return
        item = interp.remember(text, out, src, dst)
        logger.info(f"통역(글) {src}→{dst} ({who} {sec:.2f}초, 원문 {len(text)}자 → {len(out)}자)")
        st.event("interp", state="done", src_lang=src, dst_lang=dst, src=text, dst=item["dst"], money=item.get("money"),
                 src_name=sn, dst_name=dn, sec=round(sec, 2), asr_ms=0, voice=bool(interp.L.voice_of(cfg, dst)) or dst == "ko")   # ko = 김비서 목소리
        await self.worker.queue_frame(TTSSpeakFrame(out, append_to_context=False))

    # ---- 도중 저장
    def _conv(self):
        return [m for m in (self.context.messages if self.context else [])[1:] if isinstance(m, dict)]

    def autosave(self, force=False):
        if self.memory is None or not (self.cfg.get("문맥") or {}).get("이어가기", True):
            return
        msgs = self._conv()
        sig = (len(msgs), str(msgs[-1].get("content"))[:80] if msgs else "")
        if not force and sig == self._saved_sig:
            return
        self._saved_sig = sig
        try:
            self.memory.save_context(msgs, self.summary_in, int((self.cfg.get("문맥") or {}).get("이어가기_차례", 6)))
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"이어가기 저장 실패: {ex.__class__.__name__}")

    async def _autosave_loop(self):
        while True:
            await asyncio.sleep(2.0)
            debate.tick(self.state)      # 말싸움: 30분 사용자 말이 없으면 자동 끔
            self.autosave()

    # ---- 끝 정리
    async def finish(self):
        """대화 원문 보관 → 일기 → 자동 기억 → 이어가기(요약 포함). 두뇌가 없거나 실패해도 원문·이어가기는 남김."""
        rep = {}
        await self._cleanup_retired()
        mem = self.memory
        if mem is None:
            return rep
        msgs = self._conv()
        new = msgs[self.restored_n:]
        if not plain_turns(new):
            self.autosave(force=True)
            return rep
        honor = C.honorific(self.cfg) or "사용자"
        try:
            rep["보관"] = mem.archive_append(new, self.sid)
        except OSError as ex:
            rep["보관"] = f"실패 {ex.__class__.__name__}"
        diary = ""
        mc = self.cfg.get("기억") or {}
        if mc.get("일기", True):
            req = mem.diary_request(new)
            if req:
                diary = await simple_text(self.cfg, req, 300, 0.3)
                if diary:
                    mem.diary_add(diary)
                rep["일기"] = diary
        if mc.get("켜기", True) and mc.get("자동", True):
            req = mem.auto_request(new, honor)
            if req:
                out = await simple_text(self.cfg, req, 300, 0.2)
                rep["자동기억"] = mem.auto_apply(out)
                rep["자동기억_원답"] = out[:300]
        summ = self.summary_in
        if diary:
            summ = (summ + "\n" + diary).strip()[-2500:]
        try:
            mem.save_context(msgs, summ, int((self.cfg.get("문맥") or {}).get("이어가기_차례", 6)))
        except Exception as ex:  # noqa: BLE001
            rep["이어가기"] = f"실패 {ex.__class__.__name__}"
        self.end_report = rep
        logger.info(f"대화 끝 정리: 보관 {rep.get('보관')} · 일기 {len(rep.get('일기') or '')}자 · 자동 기억 {rep.get('자동기억')}")
        return rep
