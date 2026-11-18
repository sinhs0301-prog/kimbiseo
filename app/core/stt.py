# 귀(받아쓰기) 부품 — VAD 로 자른 말 조각을 귀 서버로 보내 받아쓴다(운영판 귀STT 를 옮김, 목소리 인증·녹음 학습은 뺌).
#   - 비서가 말하는 중 사람 말소리가 들리면 '엿듣기_초'(0.4초)만 듣고 미리 받아써 자기 목소리인지 본다.
#     사람 말이면 InterimTranscriptionFrame 으로 끼어들기를 일으키고, 아니면 줄인 소리를 되돌린다(unduck).
#   - 받아쓴 글이 방금 비서 말과 거의 같으면(3층) 또는 소리 크기 모양이 비서 소리를 따라가면(4층) 메아리로 버린다.
#   - 환각 문구(설정 귀.환각문구)·반복 환각은 버린다. 받아쓰기 교정 사전(설정 받아쓰기_교정)을 적용한다.
#   - 이름 부르기 모드(설정 '대화.이름부르기' 또는 대기 도구): 이어듣기 창 밖의 말은 앞 '대기_귀_상한.짧은_초'만
#     짧게(최대 '귀.이름부르기_최대토큰') 조용히 받아써 이름을 불렀는지만 본다. 부르지 않은 말은 메모리에만 잠깐(주변기억_초) 두고
#     기록·화면에 남기지 않는다. 1분에 짧은 조각 30번·긴 조각 12번까지만 귀를 부른다(대기 중 그래픽카드 아끼기).
#     이름만 부르면('김비서!') 두뇌를 거치지 않고 '비서.부름_대답' 을 말하고 이어듣기를 연다.
#   - 통역 모드(core/interp.py): "태국어 통역해 줘"로 켜면 그 뒤의 말은 '한국어 + 통역 언어' 안에서 감지해 받아쓰고 번역만 한다
#     (두뇌 대화·도구·기억으로 넘기지 않음 — 다른 사람 말로 김비서를 조작하지 못하게). 이름 부르기 문도 거치지 않음.
import asyncio
import time

import numpy as np
from loguru import logger
from pipecat.frames.frames import (
    ErrorFrame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

from . import config as C
from . import interp
from .i18n import ear_request_lang, lang_of, pipecat_lang, tr
from .state import approx_substring_similarity, apply_fixes, is_hallucination, is_repeat_junk, norm_text
from .turns import confirm_barge
from .voice_link import EarLink

NAME_ONLY_WAIT = 0.7   # 이름만 부른 뒤 이어 말하는지 기다리는 초
from .wake import hallucination as name_hallucination
from .speech_gate import SpeechGate


class EarSTT(SegmentedSTTService):
    def __init__(self, state, port, ear=None, voiceprint=None, **kw):
        self._plang = pipecat_lang(lang_of(state.cfg))
        super().__init__(sample_rate=16000, ttfs_p99_latency=0.6, trailing_silence_secs=0.3,
                         settings=STTSettings(model=None, language=self._plang), **kw)
        self.state = state
        self.cfg = state.cfg
        self.ear = ear or EarLink(port, lang=ear_request_lang(state.cfg))
        self._utt = 0
        self._utt_meta = {}
        self._meta_by_seg = {}
        self._speech_t0 = 0.0
        self._peeked = False
        self._last_peek = 0.0
        self._peek_task = None
        self.corr_need = float(self.cfg["대화"].get("메아리_상관_기준", 0.9))
        self.vp = voiceprint     # core/voiceprint.VoicePrint — '등록한 목소리만 명령 받기'(켰을 때만 씀)
        self.gate = SpeechGate(self.cfg)   # 말소리 문(무음·잡음 헛받아쓰기 막기) — core/speech_gate

    def _spk_start(self, audio):
        """등록한 목소리 문이 켜져 있으면 받아쓰기와 같이 목소리 점수를 계산(기다리는 시간 안 늘림)."""
        vp = self.vp
        if vp is None or not vp.gate_on():
            return None
        t = asyncio.ensure_future(asyncio.to_thread(vp.score_pcm, audio))
        t.add_done_callback(lambda f: f.cancelled() or f.exception())    # 잡음·주변 말로 일찍 끝나 안 기다린 경우에도 오류 기록이 남지 않게
        return t

    async def _spk_is_me(self, task):
        """→ (등록한 사람인가, 점수 결과). 문이 꺼져 있으면 (True, None)."""
        if task is None:
            return True, None
        try:
            r = await task
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"목소리 확인 실패: {ex.__class__.__name__}")
            return False, {"오류": ex.__class__.__name__}
        return self.vp.is_me(r), r

    def _stop(self, text):
        return self.state.has_stop_word(text)

    def _combine(self, text, verdict, corr, active):
        """글 비교(3층) + 소리 크기 모양 상관(4층)."""
        if verdict == "noise" or not active:
            return verdict
        if corr >= (0.97 if self._stop(text) else self.corr_need):
            return "echo"
        if verdict == "echo" and corr < 0.5:
            return "pass"   # 글은 같아도 소리 모양은 따로 놂 → 사람이 같은 말을 함
        return verdict

    @property
    def wants_wav_segments(self) -> bool:
        return False

    def can_generate_metrics(self) -> bool:
        return True

    async def process_audio_frame(self, frame: InputAudioRawFrame, direction: FrameDirection):
        a = np.frombuffer(frame.audio, dtype=np.int16).astype(np.float32) / 32768.0
        if len(a):
            now = time.time()
            self.state.mic.append((now, 20 * np.log10(max(float(np.sqrt(np.mean(a * a))), 1e-9))))
            self.state.mic_env.add(now, a, 16000)
        await super().process_audio_frame(frame, direction)
        if (self._user_speaking and self.state.bot_speaking and confirm_barge(self.cfg)
                and (self._peek_task is None or self._peek_task.done())):
            now = time.time()
            first = float(self.cfg["대화"].get("엿듣기_초", 0.4))
            # 처음엔 말 시작 0.4초 뒤, 그 뒤로도 비서가 말하는 동안 0.6초마다 다시 엿듣는다
            if (not self._peeked and now - self._speech_t0 >= first) or (self._peeked and now - self._last_peek >= 0.6):
                self._peeked = True
                self._last_peek = now
                span = min(now - self._speech_t0 + 0.2, 1.2) + 0.15
                pcm = bytes(self._audio_buffer[-int(span * 16000) * 2:])
                self._peek_task = self.create_task(self._peek(self._utt, pcm))

    async def _handle_user_started_speaking(self, frame):
        await super()._handle_user_started_speaking(frame)
        self._utt += 1
        self._speech_t0 = time.time()
        self._peeked = False
        self._utt_meta[self._utt] = {"echo_window": self.state.in_echo_window(), "t0": self._speech_t0,
                                     "bot_speaking": self.state.bot_speaking, "decided": None}
        for k in [k for k in self._utt_meta if k < self._utt - 20]:
            self._utt_meta.pop(k, None)

    async def _handle_user_stopped_speaking(self, frame):
        now = time.time()
        n_bytes = len(self._audio_buffer)
        meta = dict(self._utt_meta.get(self._utt) or {})
        t_start = now - n_bytes / 32000 + 1.0    # 버퍼 = 앞 1초 여유 + 말
        meta["echo_window"] = bool(meta.get("echo_window")) or self.state.in_echo_window(t_start)
        meta["bot_speaking"] = bool(meta.get("bot_speaking")) or self.state.bot_spoke_between(t_start, now)
        meta["t_stop"] = now
        meta["t_start"] = t_start
        await super()._handle_user_stopped_speaking(frame)
        q = getattr(self._segment_queue, "_queue", None)
        if q:
            self._meta_by_seg[id(q[-1])] = meta

    def _judge(self, text, meta, peek=False):
        """('pass'|'echo'|'noise'|'wait', 유사도). 짧은 말일수록 더 비슷해야 메아리로 본다."""
        if is_hallucination(text, self.cfg):
            return "noise", 0.0
        n = norm_text(text)
        if self._stop(text):
            return "pass", 0.0
        if meta and meta.get("echo_window"):
            ref = self.state.recent_bot_text(last=4 if peek else None)
            sim = approx_substring_similarity(n, ref) if ref else 0.0
            if peek and len(n) > 6:
                sim = max(sim, approx_substring_similarity(n[:-2], ref))   # 엿듣기는 마지막 낱말이 틀리기 쉬움
            base = float(self.cfg["대화"].get("자기목소리_유사도", 0.6))
            need = base if len(n) >= 8 else (0.75 if len(n) >= 4 else 0.99)
            if len(n) < 4 and not meta.get("bot_speaking"):
                need = 2.0
            if sim >= need:
                return "echo", sim
            if len(n) <= 1 and meta.get("bot_speaking"):
                return "noise", sim
            if peek and len(n) <= 2 and meta.get("bot_speaking"):
                return "wait", sim
            return "pass", sim
        return "pass", 0.0

    def _interp_on(self):
        return interp.enabled(self.cfg) and interp.active(self.cfg)

    async def _peek(self, utt, pcm):
        try:
            r = await self.ear.transcribe(pcm, quiet=self.state.wake,
                                          langs=interp.ear_args(self.cfg) if self._interp_on() else None)
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"엿듣기 실패: {ex}")
            return
        meta = self._utt_meta.get(utt, {})
        verdict, sim = self._judge(r["text"], meta, peek=True)
        now = time.time()
        corr, active = self.state.echo_corr(now - 0.8, now)
        verdict = self._combine(r["text"], verdict, corr, active)
        shown = r["text"]
        st = self.state
        if st.wake and verdict == "pass" and not (st.addressed(r["text"]) or self._stop(r["text"])) and not st.in_follow():
            verdict, shown = "ambient", "(주변 말)"
        import re
        if (verdict == "pass" and st.bot_speaking and not self._stop(r["text"])
                and len(re.sub(r"[^가-힣A-Za-z0-9぀-ヿ一-鿿]", "", r["text"] or "")) < 2):
            verdict = "wait"   # 숨소리·바람이 한 글자로 받아써진 것 — 끊지 않고 더 들어 봄
        st.event("peek", text=shown, verdict=verdict, sim=round(sim, 2), corr=round(corr, 2), asr_ms=round(r["sec"] * 1000))
        if verdict == "pass" and st.bot_speaking:
            meta["decided"] = "barge"
            await self.push_frame(InterimTranscriptionFrame(text=r["text"], user_id="", timestamp=time_now_iso8601(),
                                                            language=self._plang))
        elif verdict == "wait":
            pass
        elif verdict != "pass":
            meta["decided"] = verdict
            st.event("unduck")

    async def _standby_probe(self, audio):
        """대기(이름 부르기, 이어듣기 밖): 앞부분만 짧게 받아써 이름을 불렀는지. → (불렀나, 받아쓴 글|None, 귀 결과|None)"""
        st = self.state
        cap = (self.cfg["대화"].get("대기_귀_상한") or {})
        short_s = float(cap.get("짧은_초", 2.4))
        sec = max(0.0, len(audio) / 32000 - 1.0)   # 앞 1초 여유 빼고
        kind = "짧은" if sec <= short_s else "긴"
        if not st.ear_cap_ok(kind):
            st.event("asr", text="(대기 — 귀 부름 상한)", verdict="ear_cap", kind=kind)
            return False, None, None
        n = int((1.0 + short_s) * 32000) // 2 * 2
        probe = audio[:n]
        mt = int((self.cfg.get("귀") or {}).get("이름부르기_최대토큰", 16))
        r = await self.ear.transcribe(probe, max_tokens=mt, quiet=True)
        text = (r.get("text") or "").strip()
        if name_hallucination(text) or is_hallucination(text, self.cfg):
            return False, None, r
        called = bool(st.names.call(text) or st.names.near(text))
        if not called:
            st.ambient.append((time.time(), text))
            st.event("asr", text="(주변 말)", verdict="ambient", asr_ms=round(r["sec"] * 1000))
            return False, None, r
        return True, text, r

    async def run_stt(self, audio: bytes):
        meta = self._meta_by_seg.pop(id(audio), None)
        if meta is None:
            now = time.time()
            t_start = now - len(audio) / 32000 + 1.0
            meta = {"echo_window": self.state.in_echo_window(t_start),
                    "bot_speaking": self.state.bot_spoke_between(t_start, now), "t_stop": now, "t_start": t_start}
        st = self.state
        try:
            gm = await asyncio.to_thread(self.gate.measure, audio, 0.3)
        except Exception as ex:  # noqa: BLE001 — 문이 고장 나도 받아쓰기는 계속
            logger.warning(f"말소리 문 재기 실패: {ex}")
            gm = None
        if gm is not None:
            why = self.gate.before(gm)
            self.gate.save(audio, gm, "버림" if why else "")
            if why:
                logger.info(f"말소리 문: 위스퍼 전 버림 — {why} {gm}")
                st.event("asr", text="(잡음)", verdict="noise", asr_ms=0)
                st.event("unduck")
                return
        if self._interp_on():
            async for f in self._interp_turn(audio, meta):
                yield f
            return
        standby = st.wake and not st.in_follow(meta.get("t_start"))
        spk = self._spk_start(audio)
        await self.start_processing_metrics()
        try:
            if standby:
                called, probe_text, r = await self._standby_probe(audio)
                if not called:
                    await self.stop_processing_metrics()
                    st.event("unduck")
                    return
                cap = (self.cfg["대화"].get("대기_귀_상한") or {})
                if len(audio) / 32000 - 1.0 > float(cap.get("짧은_초", 2.4)):
                    r = await self.ear.transcribe(audio)   # 이름을 불렀으니 말 전체를 받아씀
                else:
                    r = dict(r, text=probe_text)
            else:
                r = await self.ear.transcribe(audio)
        except Exception as ex:  # noqa: BLE001
            yield ErrorFrame(error=f"귀 서버 오류: {ex}")
            return
        await self.stop_processing_metrics()
        text = (r.get("text") or "").strip()
        why = self.gate.after(text, gm) if gm is not None else ""
        logger.info(f"말소리 문: {gm} → {len(text)}자" + (f" · 버림 — {why}" if why else ""))
        if why:
            st.event("asr", text="(잡음)", verdict="noise", asr_ms=round(r["sec"] * 1000))
            st.event("unduck")
            return
        if is_repeat_junk(text, r.get("audio_sec")):
            logger.info(f"받아쓰기 반복 환각 버림({r.get('audio_sec', 0):.1f}초, {len(text)}자)")
            st.event("asr", text="(잡음)", verdict="noise", asr_ms=round(r["sec"] * 1000))
            st.event("unduck")
            return
        verdict, sim = self._judge(text, meta)
        corr, active = 0.0, False
        if meta.get("bot_speaking"):
            t1 = meta["t_stop"]
            dur = max(0.0, t1 - meta["t_start"])
            corr, active = st.echo_corr(t1 - max(0.8, min(3.0, dur)), t1)
            verdict = self._combine(text, verdict, corr, active)
        st.last_asr_t = time.time()
        if st.wake and verdict == "pass" and not standby and not st.in_follow(meta.get("t_start")) \
                and not (st.names.call(text) or st.names.near(text)):
            st.ambient.append((time.time(), text))
            st.event("asr", text="(주변 말)", verdict="ambient", asr_ms=round(r["sec"] * 1000))
            st.event("unduck")
            return
        st.event("asr", text=text, verdict=verdict, sim=round(sim, 2), corr=round(corr, 2),
                 win=bool(meta.get("echo_window")), asr_ms=round(r["sec"] * 1000), audio_sec=round(r.get("audio_sec", 0), 2))
        if verdict == "echo":
            st.event("echo", text=text, sim=round(sim, 2))
            st.event("unduck")
            return
        if verdict == "noise":
            st.event("unduck")
            return
        me, sr = await self._spk_is_me(spk)
        if not me:
            # 등록한 목소리만 명령 받기: 다른 사람 말(또는 점수를 못 낸 아주 짧은 말)은 두뇌로 안 넘김. 화면엔 '안 들음' 표시만.
            logger.info(f"등록한 목소리가 아니라 안 받음(점수 {None if not sr else sr.get('점수')}, {len(text)}자)")
            st.event("voice_gate", text=text[:60], score=(sr or {}).get("점수"), short=bool((sr or {}).get("짧음")))
            st.event("unduck")
            return
        text = apply_fixes(text, st.fixes)
        called = st.wake and (st.names.call(text) or st.names.near(text))
        if called:
            st.wake_until = time.time() + 8.0   # 부른 뒤 8초는 이어지는 말도 사용자 말로
            st.follow_block = False
            if not st.always_name:
                st.set_wake(False, why="이름을 부름")
        if st.names.only_name(text) or (called and st.names.near(text)):
            # 이름만 들림(대기 중이든 아니든): '김비서, (쉼) 내일 날씨…'처럼 쉼표 뒤에 말이 이어지는 일이 많아 NAME_ONLY_WAIT 초
            #   기다렸다가 그동안 다시 말하기 시작하지 않았을 때만 두뇌 없이 부름_대답을 한다(이어 말하면 그 말로 바로 답함).
            say = C.fill(self.cfg, (self.cfg.get("비서") or {}).get("부름_대답") or "네, 말씀하세요.")
            st.event("name_call", only=True)
            st.wake_until = time.time() + 8.0
            mark = st.last_asr_t = time.time()

            async def later():
                await asyncio.sleep(NAME_ONLY_WAIT)
                if st.user_speaking or st.last_asr_t > mark:
                    st.event("name_call_wait", said=False)
                    return
                await self.push_frame(TTSSpeakFrame(say))

            self.create_task(later(), "name_only_reply")
            return
        if called:
            amb = st.ambient_text()
            st.ambient.clear()
            st.event("name_call", only=False)
            if amb:
                text = (f"[주변 대화(최근 {int(st.ambient_keep // 60)}분, 참고용 — 사용자가 비서에게 한 말이 아님): {amb}]\n"
                        + text)
        cmd = interp.L.parse_command(self.cfg, text) if interp.enabled(self.cfg) else None
        if cmd and cmd[0] == "on":   # "태국어 통역해 줘" → 통역 모드(두뇌로 안 넘김)
            code = interp.turn_on(self.cfg, cmd[1])
            interp.warm_voice(self.cfg, code)
            nm = interp.L.name_of(self.cfg, code)
            st.event("user", text=text)
            st.event("interp", state="on", **interp.view(self.cfg))
            yield TTSSpeakFrame(tr(f"네, 지금부터 {nm} 통역할게요. 한국어로 말씀하시면 {nm}로, 상대가 말하면 한국어로 옮겨 드려요. "
                                   "끝내실 땐 통역 그만, 이라고 해 주세요."), append_to_context=False)
            return
        yield TranscriptionFrame(text=text, user_id="", timestamp=time_now_iso8601(), language=self._plang, finalized=True)

    async def _interp_turn(self, audio, meta):
        """통역 모드 한 마디: 감지한 언어로 받아씀 → 번역(도구·대화 기록 없는 번역 전용 요청) → 그 언어 목소리로 말함(tts.py).
        한국어 '통역 그만'·화면 '끄기'로 끔. 다른 사람 말은 절대 두뇌 대화·도구로 넘기지 않는다(번역만)."""
        st, cfg = self.state, self.cfg
        spk = self._spk_start(audio)
        await self.start_processing_metrics()
        try:
            r = await self.ear.transcribe(audio, langs=interp.ear_args(cfg))
        except Exception as ex:  # noqa: BLE001
            yield ErrorFrame(error=f"귀 서버 오류: {ex}")
            return
        await self.stop_processing_metrics()
        text = (r.get("text") or "").strip()
        asr_ms = round(r.get("sec", 0) * 1000)
        if not text or is_repeat_junk(text, r.get("audio_sec")):
            st.event("unduck")
            return
        verdict, sim = self._judge(text, meta)
        if meta.get("bot_speaking"):
            t1 = meta["t_stop"]
            dur = max(0.0, t1 - meta["t_start"])
            corr, active = st.echo_corr(t1 - max(0.8, min(3.0, dur)), t1)
            verdict = self._combine(text, verdict, corr, active)
        if verdict in ("echo", "noise"):
            if verdict == "echo":
                st.event("echo", text=text, sim=round(sim, 2))
            st.event("unduck")
            return
        src = r.get("lang") or "ko"
        st.last_asr_t = time.time()
        st.event("asr", text=text, verdict="interp", lang=src, asr_ms=asr_ms, audio_sec=round(r.get("audio_sec", 0), 2))
        cmd = interp.L.parse_command(cfg, text) if src == "ko" else None
        if cmd:
            me, sr = await self._spk_is_me(spk)
            if not me:   # 등록한 목소리만 명령 받기: 상대가 '통역 그만'이라고 해도 끄지 않고 번역만
                logger.info(f"통역 켜기·끄기 말이지만 등록한 목소리가 아님(점수 {None if not sr else sr.get('점수')}) → 번역만")
                st.event("voice_gate", text=text[:60], score=(sr or {}).get("점수"), interp=True)
                cmd = None
        elif spk is not None:
            spk.cancel()
        if cmd and cmd[0] == "off":
            interp.turn_off("말로 끔")
            st.event("user", text=text)
            st.event("interp", state="off", **interp.view(cfg))
            yield TTSSpeakFrame(tr("네, 통역 마칠게요."), append_to_context=False)
            return
        if cmd and cmd[0] == "on":
            code = interp.turn_on(cfg, cmd[1])
            interp.warm_voice(cfg, code)
            st.event("user", text=text)
            st.event("interp", state="on", **interp.view(cfg))
            yield TTSSpeakFrame(tr(f"네, {interp.L.name_of(cfg, code)}로 바꿀게요."), append_to_context=False)
            return
        interp.touch()
        dst = interp.plan(cfg, src)
        sn, dn = interp.L.name_of(cfg, src), interp.L.name_of(cfg, dst)
        st.event("interp", state="translating", src_lang=src, dst_lang=dst, src=text, src_name=sn, dst_name=dn)
        out, who, sec = await interp.translate(cfg, text, src, dst, interp.history())
        if not out:
            logger.warning(f"통역 실패 {src}→{dst}: {who} ({sec:.1f}초)")
            st.event("interp", state="error", src_lang=src, dst_lang=dst, src=text, why=who)
            yield TTSSpeakFrame(tr("번역이 안 됐어요. 한 번 더 말씀해 주세요."), append_to_context=False)
            return
        item = interp.remember(text, out, src, dst)
        logger.info(f"통역 {src}→{dst} ({who} {sec:.2f}초, 감지 {src} {r.get('lang_conf')}, 원문 {len(text)}자 → {len(out)}자)")
        st.event("interp", state="done", src_lang=src, dst_lang=dst, src=text, dst=item["dst"], money=item.get("money"),
                 src_name=sn, dst_name=dn, sec=round(sec, 2), asr_ms=asr_ms, voice=bool(interp.L.voice_of(cfg, dst)) or dst == "ko")
        yield TTSSpeakFrame(out, append_to_context=False)

    async def cleanup(self):
        await super().cleanup()
        await self.ear.close()
