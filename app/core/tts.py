# 목소리 부품 — 목소리 서버(8871)에 문장씩 보내 받은 소리를 이음새 다듬기(audio_smooth) 뒤 내보낸다.
#   - 글 정리(filters.tts_clean)는 여기서 한 번만 하고 서버에는 raw 로 보낸다.
#   - 첫 조각은 첫 쉼표에서 먼저 읽기(설정 목소리.첫쉼표_먼저읽기), 긴 문장(20글자+)은 쉼표에서 끊기(숫자 쉼표 제외).
#   - 영어 문장(생각 글이 새어 나온 것)은 외국어 모드가 아니면 읽지 않음. 답 대부분이 막히면 한마디 안내.
#     (0.1.18~ 앱 언어가 en·ja·zh 면 그 언어 답이 정상이므로 막지 않음 — 막기는 앱 언어가 ko 일 때만.)
#   - 앱 언어(설정 "언어")가 ko 가 아니면 한자·가나를 지우지 않고(filters.app_clean) 숫자도 한국어로 읽지 않으며,
#     요청마다 "lang" 을 목소리 서버에 보내 그 언어로 읽게 한다. ko 면 0.1.17 과 똑같이 돈다.
#   - 말 빠르기(목소리.말속도 1.0/1.2/1.4): 서버가 줄였으면(X-Speed-Applied 1) 그대로, 아니면 여기서 줄임(PyAV 있을 때).
#   - 목소리: 문장마다 다시 고름(voice_choice.voice_now) — 직접 고른 목소리 > 펫이 지금 입은 옷 > 펫 성별 설정.
#     펫 옷을 갈아입으면 다음 문장부터 그 옷의 목소리. 서버가 그 이름을 거절하면 기본 목소리로 다시 말함(voice_link).
#   - 통역 중 외국어 번역문(core/interp.speak_lang)은 김비서 목소리 대신 그 언어 원어민 목소리(귀 서버 say → voice/interp_voice.py).
#     원어민 목소리가 없는 언어(인도네시아어·베트남어)이거나 설정 통역.목소리_엔진 = '글자만' 이면 화면 글만.
import asyncio
import re

import numpy as np

from loguru import logger
from pipecat.frames.frames import ErrorFrame, InterruptionFrame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.text.base_text_aggregator import Aggregation, TextType
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator

from .audio_smooth import SeamSmoother
from . import i18n, interp, voice_choice
from .filters import app_clean, foreign_clean, lang_active, mostly_english, tts_clean
from .voice_link import EarLink, VoiceLink, speech_rate, text_norm

SR = 24000


NUM_DOT = chr(0xE000)                               # 숫자 바로 뒤 마침표 자리(문장 끝으로 보지 않게 잠깐 바꿔 둠 — 내보낼 때 '.' 로 되돌림)
_NUM_TAIL = re.compile(r"(?:^|[\s(\[])\d{1,4}$")     # '2026' · '1' · '16' 처럼 숫자만으로 된 낱말의 끝


def _undot(a):
    """문장 모음 결과의 숫자 마침표 자리를 '.' 로 되돌림."""
    if a is None or NUM_DOT not in a.text:
        return a
    return Aggregation(text=a.text.replace(NUM_DOT, "."), type=a.type)


class FirstCommaAggregator(SimpleTextAggregator):
    """문장 모으기 + 첫 쉼표에서 먼저 읽기.
    숫자 바로 뒤 마침표('2026. 11. 16.' · '1. 사과 2. 배' · '0.1.12')는 문장 끝으로 보지 않는다 — 날짜·목록 번호·판 번호가
    '이천이십육.' '십일.' 처럼 토막 나 따로 읽히던 것을 막음(읽기 변환이 통째로 받아야 '이천이십육 년 십일월 십육 일'로 읽음)."""

    def __init__(self, min_chars=1, long_chars=20, first_comma=True, **kw):
        super().__init__(**kw)
        self._first = True
        self._min = min_chars if first_comma else long_chars
        self._long = long_chars

    @property
    def text(self):
        return _undot(super().text)

    async def aggregate(self, text):
        if self._aggregation_type == TextType.TOKEN:
            async for a in super().aggregate(text):
                self._first = False
                yield a
            return
        for ch in text:
            if ch in ",，" and not self._text[-1:].isdigit() and \
                    len(re.sub(r"[^가-힣A-Za-z0-9぀-ヿ一-鿿]", "", self._text)) >= (self._min if self._first else self._long):
                out = (self._text + ch).strip(" ").replace(NUM_DOT, ".")
                self._text = ""
                self._first = False
                yield Aggregation(text=out, type=TextType.SENTENCE)
                continue
            if ch == "." and _NUM_TAIL.search(self._text):
                ch = NUM_DOT
            async for a in super().aggregate(ch):
                self._first = False
                yield _undot(a)

    async def flush(self):
        self._first = True
        return _undot(await super().flush())

    async def handle_interruption(self):
        self._first = True
        await super().handle_interruption()

    async def reset(self):
        self._first = True
        await super().reset()


class VoiceTTS(TTSService):
    def __init__(self, state, voice=None, **kw):
        async def _norm(text, _type):
            if interp.speak_lang(text):      # 통역 번역문 — 그 언어 글자 그대로(한자·가나·태국 글자를 지우지 않음)
                return re.sub(r"[*_#`~]+", " ", text).strip()
            if text_norm.has_yawn(text):
                state.event("yawn", text=text[:60])
            if i18n.lang_of(state.cfg) != "ko":   # 앱 언어가 외국어 — 그 언어 글자를 지우지 않음(한자·가나·숫자 그대로)
                return app_clean(text)
            if lang_active(state) and not re.search(r"[가-힣]", text):
                return foreign_clean(text)
            return tts_clean(text)

        vc = state.cfg.get("목소리") or {}
        app_lang = i18n.lang_of(state.cfg)
        # 첫 소리 기다림: 파이프캣 기본은 3초 안에 소리가 없으면 '소리 없음'으로 치고, 3번 이어지면 목소리를 못 쓰게 막는다.
        #   김비서 목소리가 그래픽 메모리 부족으로 CPU 로 돌면 첫 소리가 13~15초 걸려 대화 중 목소리가 끊겼음(0.1.3 실측)
        #   → 기다림을 늘리고(목소리.첫소리_기다림_초, 기본 20초) 막기는 끔. 느린 목소리는 목소리 서버가 윈도우 음성으로 바꿈.
        super().__init__(push_start_frame=True, push_stop_frames=True, sample_rate=SR,
                         stop_frame_timeout_s=float(vc.get("첫소리_기다림_초", 20) or 20), max_consecutive_zero_audio_contexts=0,
                         text_transforms=[("*", _norm)],
                         settings=TTSSettings(model=None, voice=str(vc.get("목소리") or "기본"),
                                               language=i18n.pipecat_lang(app_lang)), **kw)
        self.state = state
        self.mouth = voice or VoiceLink(state.cfg, on_yawn=lambda: state.event("yawn", text="(서버 표시)"))
        old = self._text_aggregator
        self._text_aggregator = FirstCommaAggregator(aggregation_type=old._aggregation_type, language=old.language,
                                                     first_comma=bool(vc.get("첫쉼표_먼저읽기", False)))
        self.smooth_on = bool(vc.get("이음새_다듬기", True))
        self.smoother = SeamSmoother(SR, seam_ms=float(vc.get("이음새_ms", 3)), fade_in_ms=float(vc.get("시작_페이드_ms", 4)),
                                     fade_out_ms=float(vc.get("끝_페이드_ms", 12)))
        self._turn_seen = None
        self._spoken_n = self._blocked_n = 0
        self._noticed = False
        self._voice_said = None
        self._ear = None

    async def _pick_voice(self):
        """이 문장을 말할 목소리 이름. 펫(얼굴 = 펫)이 켜져 있고 목소리를 직접 고르지 않았으면 지금 입은 옷으로."""
        cfg = self.state.cfg
        outfit = None
        if getattr(self.state, "pet", None) is not None and not (cfg.get("_voice_choice") or {}).get("고정"):
            try:
                from ..pet_link.face import pet_outfit
                outfit = await asyncio.to_thread(pet_outfit, cfg)
            except Exception:  # noqa: BLE001
                outfit = None
        bad = getattr(self.mouth, "bad_voices", None)
        name, why = voice_choice.voice_now(cfg, outfit, skip=bad() if callable(bad) else ())
        if (name, why) != self._voice_said:
            self._voice_said = (name, why)
            logger.info(f"목소리: {name or '기본'} ({why}{' ' + outfit['id'] if why == '옷' and outfit else ''})")
        return name

    def _gap_after(self, text):
        """이 문장 뒤에 더 넣을 쉼(초). 설정 목소리.문장_쉼_초(0~1) — 문장이 끝나는 곳(. ! ? …)에만, 쉼표에서 끊은 조각 뒤에는 넣지 않음.
        설정을 문장마다 다시 읽으므로 화면에서 바꾸면 다음 문장부터 바로 바뀐다."""
        try:
            g = float((self.state.cfg.get("목소리") or {}).get("문장_쉼_초", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        if not g > 0 or not re.search(r"[.!?。…~]['\")\]]?\s*$", text):
            return 0.0
        return min(g, 1.0)

    @staticmethod
    def _hush(context_id):
        """읽지 않은 문장 자리의 아주 짧은 무음(10ms) — 소리 없이 끝난 문장이 다음 문장을 첫소리_기다림_초 만큼 붙잡지 않게."""
        return TTSAudioRawFrame(audio=bytes(2 * (SR // 100)), sample_rate=SR, num_channels=1, context_id=context_id)

    def can_generate_metrics(self) -> bool:
        return True

    async def _interp_say(self, text, lang, context_id):
        """통역 번역문을 그 언어 원어민 목소리로. 목소리가 없거나 실패하면 화면 글만(무음 한 조각)."""
        st = self.state
        voice = interp.L.voice_of(st.cfg, lang)
        st.add_spoken(text)
        if not voice:
            logger.info(f"통역: {lang} 원어민 목소리 없음 → 화면 글만(글 {len(text)}자)")
            st.event("interp", state="no_voice", lang=lang)
            yield self._hush(context_id)
            return
        await self.start_tts_usage_metrics(text)
        if self._ear is None:
            self._ear = EarLink(st.cfg["포트"]["귀"])
        try:
            pcm, sr = await self._ear.say(voice, text)
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"통역 원어민 목소리({voice}) 실패: {str(ex)[:160]}")
            st.event("interp", state="no_voice", lang=lang, why=str(ex)[:160])
            yield self._hush(context_id)
            return
        finally:
            await self.stop_ttfb_metrics()
        if sr != SR and pcm:
            x = np.frombuffer(pcm, "<i2").astype(np.float32)
            n = int(len(x) * SR / sr)
            pcm = np.clip(np.interp(np.arange(n) * (sr / SR), np.arange(len(x)), x), -32768, 32767).astype("<i2").tobytes()
        step = SR * 2 // 5
        for i in range(0, len(pcm), step):
            yield TTSAudioRawFrame(audio=pcm[i:i + step], sample_rate=SR, num_channels=1, context_id=context_id)
        if not pcm:
            yield self._hush(context_id)

    async def run_tts(self, text: str, context_id: str):
        text = text.strip()
        lang = interp.speak_lang(text)
        if lang:
            async for fr in self._interp_say(text, lang, context_id):
                yield fr
            return
        if not re.search(r"[0-9A-Za-z가-힣぀-ヿ一-鿿]", text):
            yield self._hush(context_id)
            return
        st = self.state
        app_lang = i18n.lang_of(st.cfg)
        if self._turn_seen != st.turn_no:
            self._turn_seen, self._spoken_n, self._blocked_n, self._noticed = st.turn_no, 0, 0, False
        if app_lang == "ko" and mostly_english(text) and not lang_active(st):
            logger.warning(f"영어 문장이라 말하지 않음({len(text)}자)")
            self._blocked_n += 1
            if self._noticed or self._blocked_n < max(1, self._spoken_n):
                yield self._hush(context_id)
                return
            self._noticed = True
            text = "영어로 된 답이라 소리로는 읽지 않았어요. 화면을 봐 주세요."
        else:
            self._spoken_n += 1
        st.add_spoken(text)
        await self.start_tts_usage_metrics(text)
        speed = speech_rate.clamp_speed(st.speed)       # 0.7~1.6(설정 화면) — 1.0/1.2/1.4 말고도 됨
        gap = self._gap_after(text)
        stretch = None
        sm = self.smoother if self.smooth_on else None
        if sm is not None:
            sm.start()
        first = True
        if hasattr(self.mouth, "voice"):
            self.mouth.voice = await self._pick_voice()
        try:
            async for msg, pcm in self.mouth.speak(text, speed, lang=app_lang):
                kind = msg.get("type")
                if kind == "head":
                    if speed != 1.0 and not msg.get("speed_applied"):
                        try:
                            stretch = speech_rate.TimeStretch(speed, SR)
                            if not getattr(stretch, "ok", True):
                                stretch = None
                        except Exception as ex:  # noqa: BLE001
                            logger.warning(f"말 빠르기 처리기를 못 만들어 원래 속도로: {ex.__class__.__name__}")
                            stretch = None
                    continue
                if kind == "end":
                    if msg.get("error"):
                        yield ErrorFrame(error=msg["error"])
                        if first:
                            yield self._hush(context_id)
                    tail = stretch.flush() if stretch is not None else b""
                    if sm is not None:
                        tail = (sm.feed(tail) if tail else b"") + sm.end()
                    if tail:
                        yield TTSAudioRawFrame(audio=tail, sample_rate=SR, num_channels=1, context_id=context_id)
                    if gap > 0 and not first and not msg.get("error"):     # 문장 사이 쉼(설정 목소리.문장_쉼_초) — 소리가 난 문장 뒤에만
                        yield TTSAudioRawFrame(audio=bytes(2 * int(SR * gap)), sample_rate=SR, num_channels=1, context_id=context_id)
                    break
                if stretch is not None:
                    pcm = stretch.feed(pcm)
                if sm is not None and pcm:
                    pcm = sm.feed(pcm)
                if not pcm:
                    continue
                if first:
                    await self.stop_ttfb_metrics()
                    first = False
                yield TTSAudioRawFrame(audio=pcm, sample_rate=SR, num_channels=1, context_id=context_id)
        finally:
            await self.stop_ttfb_metrics()

    async def process_frame(self, frame, direction):
        if isinstance(frame, InterruptionFrame):
            await self.mouth.reset()
            self.smoother.drop()
        await super().process_frame(frame, direction)

    async def cleanup(self):
        await super().cleanup()
        await self.mouth.close()
        if self._ear is not None:
            await self._ear.close()
