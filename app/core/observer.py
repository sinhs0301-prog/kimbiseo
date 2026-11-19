# 관찰자 — 파이프라인을 지나는 프레임을 보고 상태(듣는 중·생각 중·말하는 중)·자막·지연시간·소리 크기 모양을 기록한다.
#   ContextTrim: 두뇌에 보내는 문맥을 최근 사용자 차례 N 개로 줄인다(설정 두뇌.기억_차례). 맨 앞 지시문과
#                이어 온 앞부분(고정 머리)은 남겨 캐시 앞부분이 그대로이게 한다.
import time
from collections import deque

import numpy as np
from loguru import logger
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from . import debate


class ContextTrim(FrameProcessor):
    def __init__(self, turns=12, keep_head=1, **kw):
        super().__init__(**kw)
        self.turns = turns
        self.keep_head = keep_head   # 맨 앞에서 늘 남길 메시지 수(지시문)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.DOWNSTREAM:
            ctx = frame.context
            msgs = list(ctx.messages)
            head = msgs[:self.keep_head]
            body = msgs[self.keep_head:]
            users = [i for i, m in enumerate(body) if isinstance(m, dict) and m.get("role") == "user"]
            if len(users) > self.turns:
                ctx.set_messages(head + body[users[-self.turns]:])
        await self.push_frame(frame, direction)


class Observer(BaseObserver):
    def __init__(self, state, vad_stop_secs: float):
        super().__init__(observe_every_push=True)
        self.state = state
        self.vad_stop = vad_stop_secs
        self.t = {}
        self.last_vad_stop = None
        self.waiting = False
        self.status = None
        self._seen = deque(maxlen=2000)
        self._seen_set = set()
        self.out_audio = []          # 시험용: 실제로 내보낸 소리(int16 bytes)

    def _status(self, s):
        if s != self.status:
            self.status = s
            self.state.event("status", state=s)

    async def on_push_frame(self, data: FramePushed):
        f = data.frame
        now = time.time()
        st = self.state
        if isinstance(f, OutputAudioRawFrame):
            if isinstance(data.source, BaseOutputTransport):   # 실제로 내보낸(재생 시계에 맞춘) 소리만
                a = np.frombuffer(f.audio, dtype=np.int16).astype(np.float32) / 32768.0
                st.bot_env.add(now, a, f.sample_rate)
                if st.pet is not None:
                    try:
                        st.pet.on_audio(st, now, a, f.sample_rate)
                    except Exception as ex:  # noqa: BLE001
                        logger.debug(f"펫 입 오류: {ex}")
            if isinstance(f, TTSAudioRawFrame):
                self.t.setdefault("tts_first", now)
            return
        if isinstance(f, InputAudioRawFrame):
            return
        sib = getattr(f, "broadcast_sibling_id", None)
        if f.id in self._seen_set or (sib is not None and sib in self._seen_set):
            return
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(f.id)
        self._seen_set.add(f.id)
        if isinstance(f, VADUserStartedSpeakingFrame):
            st.user_speaking = True
            st.event("vad_start")
            if not st.bot_speaking:
                self._status("듣는 중")
        elif isinstance(f, VADUserStoppedSpeakingFrame):
            st.user_speaking = False
            if self.last_vad_stop and abs((now - self.vad_stop) - self.last_vad_stop) < 0.05:
                return
            self.last_vad_stop = now - self.vad_stop
            st.event("vad_stop", eos=self.last_vad_stop)
        elif isinstance(f, TranscriptionFrame):
            self.t["asr"] = now
            st.event("user", text=f.text)
        elif isinstance(f, UserStartedSpeakingFrame):
            self._status("듣는 중")
        elif isinstance(f, UserStoppedSpeakingFrame):
            st.thinking = True
            st.thinking_t = now
            st.turn_no += 1
            self.t = {"eos": self.last_vad_stop or now, "turn_end": now, "asr": self.t.get("asr")}
            self.waiting = True
            self._status("생각 중")
        elif isinstance(f, LLMFullResponseStartFrame):
            self.t.setdefault("llm_start", now)
        elif isinstance(f, LLMTextFrame):
            self.t.setdefault("llm_first", now)
        elif isinstance(f, FunctionCallInProgressFrame):
            self.t.setdefault("tool", now)
            st.tool_busy += 1
            st.event("tool", name=f.function_name, state="start", args=_short(f.arguments))
            self._status("도구 사용 중")
        elif isinstance(f, FunctionCallResultFrame):
            st.tool_busy = max(0, st.tool_busy - 1)
            st.event("tool", name=f.function_name, state="done")
        elif isinstance(f, TTSTextFrame):
            st.event("bot", text=debate.filter_text(f.text, st) if debate.on(st) else f.text)
        elif isinstance(f, BotStartedSpeakingFrame):
            st.thinking = False
            st.bot_speaking = True
            st.bot_interrupted = False
            st.bot_started_at = now
            st.bot_spans.append((now, None))
            self._status("말하는 중")
            if self.waiting:
                self.waiting = False
                e = self.t.get("eos", now)
                part = {k: round((v - e) * 1000) for k, v in self.t.items() if v and k != "eos"}
                part["first_audio"] = round((now - e) * 1000)
                st.event("latency", turn=st.turn_no, total_ms=part["first_audio"], parts=part)
        elif isinstance(f, BotStoppedSpeakingFrame):
            st.bot_speaking = False
            st.bot_stopped_at = now
            if st.bot_spans and st.bot_spans[-1][1] is None:
                st.bot_spans[-1] = (st.bot_spans[-1][0], now)
            self._status("도구 사용 중" if st.tool_busy else "듣는 중")
            st.event("unduck")
        elif isinstance(f, InterruptionFrame):
            if st.bot_speaking or self.status == "생각 중":
                st.bot_interrupted = True
                st.event("interrupted")
            st.event("unduck")


def _short(args):
    try:
        s = str(args)
    except Exception:  # noqa: BLE001
        return ""
    return s[:120]
