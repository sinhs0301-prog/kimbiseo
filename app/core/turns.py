# 차례 판단 — 끼어들기(사람 차례 시작)와 한국어 말끝(사람 차례 끝). 운영판과 같은 규칙·같은 값.
#   끼어들기(BargeStrategy):
#     비서가 조용할 때: 말소리(VAD) 시작 = 차례 시작. 단 이름 부르기 모드(대기)면 이름을 부른 받아쓰기가 와야 시작,
#                      생각·도구 중이면(소음막기) 받아쓰기가 와야 시작(만들던 답이 잡음에 버려지지 않게).
#     비서가 말할 때 : 첫 '첫소리_무시_초' 안의 말소리는 '큰소리_기준_dBFS' 보다 작으면 무시(자기 목소리 2층).
#                      확인 모드: 소리를 '줄일_볼륨' 으로 줄이고(duck) 귀의 엿듣기 결과가 사람 말이면 끊음.
#                      즉시 모드: 바로 끊음('즉시도_확인' 이 켜져 있으면 즉시 모드도 확인 절차).
#   말끝(KoreanEndStrategy): Smart Turn 이 '덜 끝남'이라 해도 받아쓰기가 완결된 한국어 문장이면 조금만 더 기다렸다 끝냄.
#     마침표 있는 문장 0.4초 · 마침표 없는 짧은 대답 0.7초 · 시키는 말 끝 0.5초 · (넓게) 그 밖의 부호 끝 0.6초 · 반말·물음 끝 1.0초.
import asyncio
import re
import time

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.turns.types import ProcessFrameResult
from pipecat.turns.user_start.base_user_turn_start_strategy import BaseUserTurnStartStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import TurnAnalyzerUserTurnStopStrategy

from . import debate


def confirm_barge(cfg):
    dc = cfg["대화"]
    m = dc.get("끼어들기")
    return m == "확인" or (m == "즉시" and dc.get("즉시도_확인", True))


class BargeStrategy(BaseUserTurnStartStrategy):
    def __init__(self, state, **kw):
        super().__init__(**kw)
        self.state = state
        self.cfg = state.cfg
        self.cand = False

    @property
    def resolves_proposed_turn_start_frames(self) -> bool:
        return False

    async def handle_user_turn_started(self):
        self.cand = False

    def _busy_hold(self):
        st = self.state
        nm = self.cfg["대화"].get("소음막기") or {}
        if not nm.get("켜기", True) or not nm.get("바쁠때_받아쓰기_확인", True) or not confirm_barge(self.cfg):
            return False
        thinking = st.thinking and time.time() - float(st.thinking_t or 0) < 45
        return bool(thinking or st.tool_busy > 0)

    async def process_frame(self, frame: Frame):
        st = self.state
        if isinstance(frame, VADUserStartedSpeakingFrame):
            if not st.bot_speaking:
                if st.wake and not st.in_follow():
                    return ProcessFrameResult.STOP   # 이름을 부른 받아쓰기가 오면 그때 차례 시작
                if self._busy_hold():
                    st.event("vad_hold", reason="생각·도구 중 — 받아쓰기 확인 뒤 차례")
                    return ProcessFrameResult.STOP
                await self.trigger_user_turn_started()
                return ProcessFrameResult.STOP
            dc = self.cfg["대화"]
            since = time.time() - st.bot_started_at
            if since < float(dc.get("첫소리_무시_초", 0.3)) and st.mic_db() < float(dc.get("큰소리_기준_dBFS", -18)):
                st.event("vad_ignored", reason="비서 첫소리 안", since=round(since, 2), mic_db=round(st.mic_db(), 1))
                return ProcessFrameResult.STOP
            if not confirm_barge(self.cfg) and not debate.on(st):
                st.event("barge", how="즉시")
                await self.trigger_user_turn_started()
                return ProcessFrameResult.STOP
            # 말싸움: 바로 끊지 않고 엿듣기(확인) 길로 — 등록한 목소리일 때만 끊는다(stt._peek).
            self.cand = True
            st.event("duck", volume=float(dc.get("줄일_볼륨", 0.3)))
            return ProcessFrameResult.STOP
        if isinstance(frame, InterimTranscriptionFrame):
            if st.bot_speaking or self.cand:
                st.event("barge", how="확인", text=frame.text)
            await self.trigger_user_turn_started()
            return ProcessFrameResult.STOP
        if isinstance(frame, TranscriptionFrame):
            await self.trigger_user_turn_started()
            return ProcessFrameResult.STOP
        return ProcessFrameResult.CONTINUE


_FINAL_END = re.compile(r"[요다까죠줘봐때니네지래게자야어아해라세오나가냐군걸]\s*[.?!。]+\s*$")
_SHORT_END = re.compile(r"[요다죠줘봐네지래게자야어아해라세오군걸]$")
_CMD_END = re.compile(r"(?:줘|봐|주세요|줄래|해라)$")
_WIDE_END = re.compile(r"(?:[어아야지해돼냐니래다요까네군걸게자라줘봐워와죠대데녕때]|잖아|구나|냐고|다고|라고|라니까|는지|은지|건지|케이|기)$")
_PUNCT_END = re.compile(r"[가-힣A-Za-z0-9぀-ヿ一-鿿]\s*[.?!。？！]+\s*$")
# 운영판과 다른 점 하나: _WIDE_END 에 '때'(어때·언제 때)를 더함 — 받아쓰기에 물음표가 빠지면 '어때'가 3초 기다리던 것을 1초로.
WIDE = {"켜기": True, "초": 1.0, "부호_초": 0.6}   # 설정 대화.말끝_넓게 로 덮어씀(session.py)


def looks_final(text):
    """받아쓰기가 완결된 한국어 문장처럼 끝나는가 → 더 기다릴 초(None = 완결 아님)."""
    t = (text or "").strip()
    if _FINAL_END.search(t):
        return 0.4
    n = re.sub(r"[^가-힣]", "", t)
    if 0 < len(n) <= 8 and _SHORT_END.search(n):
        return 0.7
    if len(n) >= 3 and _CMD_END.search(n):
        return 0.5
    if WIDE.get("켜기") and n and not t.endswith(("...", "…")):
        if _PUNCT_END.search(t):
            return float(WIDE.get("부호_초", 0.6))
        if len(n) >= 2 and _WIDE_END.search(n):
            return float(WIDE.get("초", 1.0))
    return None


class KoreanEndStrategy(TurnAnalyzerUserTurnStopStrategy):
    def __init__(self, *, fallback_secs=0.4, state=None, **kw):
        super().__init__(**kw)
        self.fallback_secs = fallback_secs
        self.state = state
        self._fb_task = None
        self._gen = 0

    async def _discard_pending_end_of_turn(self):
        self._gen += 1
        if self._fb_task:
            await self.task_manager.cancel_task(self._fb_task)
            self._fb_task = None
        await super()._discard_pending_end_of_turn()

    async def _handle_transcription(self, frame):
        await super()._handle_transcription(frame)
        wait = looks_final(frame.text)
        if wait is not None and debate.on(self.state):   # 말싸움: 말 끝을 더 기다린다(상대 말을 끊지 않게)
            wait = debate.silence(wait, getattr(self.state, "cfg", None))
        if (self._vad_stopped and not self._vad_user_speaking and not self._turn_complete
                and wait is not None and self._fb_task is None):
            gen = self._gen

            async def fb():
                await asyncio.sleep(wait)
                self._fb_task = None
                if gen == self._gen and not self._vad_user_speaking and not self._turn_complete:
                    logger.debug(f"{self}: 한국어 말끝 보조로 차례 끝냄")
                    self._turn_complete = True
                    await self._maybe_trigger_user_turn_stopped()

            self._fb_task = self.task_manager.create_task(fb(), f"{self}::korean_fallback")
