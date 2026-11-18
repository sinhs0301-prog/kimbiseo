# 귀(8872)·목소리(8871) 서버 연결 + 저장소 voice/ 의 글 정리·말 빠르기 모듈 불러오기.
#   voice/ 폴더를 sys.path 에 넣지 않고 파일 경로로 불러온다(voice/config.py 가 다른 'config' 를 가리지 않게).
import asyncio
import importlib.util
import json
import os
import time
import uuid

from loguru import logger

from . import config as C

VOICE_DIR = os.path.join(C.REPO, "voice")


def _load(name):
    spec = importlib.util.spec_from_file_location("kimbiseo_voice_" + name, os.path.join(VOICE_DIR, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


text_norm = _load("text_norm")
speech_rate = _load("speech_rate")


class EarLink:
    """귀 서버(127.0.0.1:포트.귀) — 한 줄 JSON + int16 16kHz PCM. 연결 하나를 잠금으로 나눠 씀."""

    def __init__(self, port, lang=None):
        self.port = int(port)
        self.reader = self.writer = None
        self.lock = asyncio.Lock()
        self.n = 0
        self.lang = lang      # 받아쓰기 언어(0.1.18): None = 귀 서버가 켤 때 정한 언어 · 'auto' · 'en' 같은 코드

    async def _ensure(self):
        if self.writer is None or self.writer.is_closing():
            self.reader, self.writer = await asyncio.open_connection("127.0.0.1", self.port)

    async def transcribe(self, pcm16: bytes, max_tokens=None, quiet=False, langs=None):
        """max_tokens: 받아쓰기 길이 상한(대기 중 이름 확인처럼 짧은 조각이 반복 환각으로 귀를 오래 붙잡지 않게).
        quiet: 귀 서버가 받아쓴 글을 제 기록에 남기지 않음(대기 중 주변 말).
        langs: 통역 중 {"langs":[...], "fixed", "last", "need"} — 그 언어들 안에서 감지해 받아씀(답에 lang·lang_conf·lang_p)."""
        async with self.lock:
            for attempt in range(2):
                try:
                    await self._ensure()
                    self.n += 1
                    req = {"op": "asr", "id": self.n, "n": len(pcm16)}
                    if max_tokens:
                        req["max_tokens"] = int(max_tokens)
                    if quiet:
                        req["quiet"] = True
                    if self.lang and not langs:
                        req["lang"] = self.lang
                    if langs:
                        req.update({k: v for k, v in langs.items() if k in ("langs", "fixed", "last", "need")})
                    self.writer.write((json.dumps(req) + "\n").encode())
                    self.writer.write(pcm16)
                    await self.writer.drain()
                    line = await self.reader.readline()
                    if not line:
                        raise ConnectionError("귀 서버 연결 끊김")
                    r = json.loads(line)
                    if r.get("error"):
                        raise ConnectionError(r["error"])
                    return r
                except (OSError, ConnectionError):
                    self.writer = None
                    if attempt:
                        raise

    async def say(self, voice, text):
        """통역 원어민 목소리(귀 서버가 자식 프로그램에 맡김) → (int16 PCM, 표본율). 실패하면 RuntimeError."""
        async with self.lock:
            for attempt in range(2):
                try:
                    await self._ensure()
                    self.n += 1
                    self.writer.write((json.dumps({"op": "say", "id": self.n, "voice": voice, "text": text}, ensure_ascii=False) + "\n").encode("utf-8"))
                    await self.writer.drain()
                    line = await self.reader.readline()
                    if not line:
                        raise ConnectionError("귀 서버 연결 끊김")
                    r = json.loads(line)
                    if r.get("error"):
                        raise RuntimeError(r["error"])
                    return await self.reader.readexactly(int(r["n"])), int(r["sr"])
                except (OSError, ConnectionError, asyncio.IncompleteReadError):
                    self.writer = None
                    if attempt:
                        raise

    async def close(self):
        if self.writer:
            self.writer.close()


class VoiceLink:
    """목소리 서버(127.0.0.1:포트.목소리) POST /tts_stream raw — 글 정리는 본체가 이미 함(두 번 바꾸지 않게).
    session·pace = 재생 시계(앞서가기_초 넘게 앞서 만들면 서버가 쉼 → 귀 서버와 그래픽카드를 나눠 씀).
    끼어들기·취소 = 연결을 닫으면 서버가 바로 멈춤. reset() 뒤 다음 요청은 재생 시계 0 부터.
    speak() 은 ({"type":"audio"|"end", ...}, pcm bytes) 를 차례로 내놓는다. 첫 메시지 {"type":"head"} 에 speed_applied·yawn."""

    def __init__(self, cfg, on_yawn=None):
        self.cfg = cfg
        self.port = int(cfg["포트"]["목소리"])
        self.session = "kimbiseo-" + uuid.uuid4().hex[:10]
        self.pace = float((cfg.get("목소리") or {}).get("앞서가기_초", 2.5))
        self.voice = (cfg.get("목소리") or {}).get("목소리") or None   # 문장마다 tts.VoiceTTS 가 다시 정함(옷·성별)
        self._bad = {}          # 목소리 서버가 거절한 voice 이름 → 다시 써 볼 시각(5분 뒤)
        self._reset = True
        self.on_yawn = on_yawn

    def bad_voices(self):
        now = time.time()
        return {n for n, t in self._bad.items() if t > now}

    async def speak(self, text, speed=1.0, lang=None):
        """lang: 앱 언어(0.1.18) — ko 가 아니면 요청에 실어 그 언어로 읽게 함(ko 는 예전 그대로 안 보냄)."""
        # 앱을 막 켰을 때 목소리 서버는 떠 있어도 엔진(Qwen)을 아직 읽는 중이면 503 '엔진 준비 중' → 오류 대신 기다렸다 다시(최대 목소리.엔진_기다림_초).
        wait = float((self.cfg.get("목소리") or {}).get("엔진_기다림_초", 90) or 90)
        t_end = asyncio.get_running_loop().time() + wait
        reset = self._reset
        voice = self.voice if self.voice not in self.bad_voices() else None
        while True:
            agen = self._speak_once(text, speed, voice, lang)
            retry = False
            try:
                first = True
                async for ev, pcm in agen:
                    if first:
                        first = False
                        err = str(ev.get("error") or "")
                        if (ev.get("type") == "end" and "503" in err and "엔진 준비 중" in err
                                and asyncio.get_running_loop().time() < t_end):
                            retry = "wait"
                            break
                        if ev.get("type") == "end" and voice and (ev.get("code") == 500 or (ev.get("code") == 400 and "voice" in err)):
                            # 서버가 그 목소리를 모르거나 못 올림 → 그 이름은 5분 쉬고 이 문장은 기본 목소리로 다시(말이 빠지지 않게)
                            self._bad[voice] = time.time() + 300
                            logger.warning(f"목소리 서버가 voice {voice} 거절({err[:80]}) → 기본 목소리로 다시")
                            voice = None
                            retry = "voice"
                            break
                    yield ev, pcm
            finally:
                await agen.aclose()
            if not retry:
                return
            self._reset = reset
            if retry == "wait":
                logger.info("목소리 엔진 준비 중 — 1초 뒤 다시")
                await asyncio.sleep(1.0)

    async def _speak_once(self, text, speed=1.0, voice=None, lang=None):
        req = {"text": text, "raw": True, "session": self.session, "pace": self.pace, "emotion": "기본"}
        if voice:
            req["voice"] = voice
        if lang and lang != "ko":
            req["lang"] = lang          # 앱 언어(0.1.18) — 한국어는 예전과 같은 요청 그대로
        if speed and abs(float(speed) - 1.0) > 1e-3:
            req["speed"] = float(speed)
            req["apply_speed"] = True
        if self._reset:
            req["reset"] = True
            self._reset = False
        body = json.dumps(req, ensure_ascii=False).encode("utf-8")
        writer = None
        done = False
        try:
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
            except OSError as ex:
                done = True
                yield {"type": "end", "error": f"목소리 서버 연결 안 됨({ex.__class__.__name__})"}, None
                return
            writer.write(b"POST /tts_stream HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\n"
                         b"Content-Length: %d\r\nConnection: close\r\n\r\n" % (self.port, len(body)) + body)
            await writer.drain()
            status_line = await reader.readline()
            try:
                code = int(status_line.split()[1])
            except (IndexError, ValueError):
                code = 0
            headers = {}
            while True:
                ln = await reader.readline()
                if not ln or ln in (b"\r\n", b"\n"):
                    break
                k, _, v = ln.decode("latin-1").partition(":")
                headers[k.strip().lower()] = v.strip()
            if headers.get("x-yawn") == "1" and self.on_yawn:
                self.on_yawn()
            if code != 200:
                raw = await reader.read(4096)
                writer.close()
                writer = None
                try:
                    j = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    j = {}
                done = True
                if j.get("yawn") and self.on_yawn:
                    self.on_yawn()
                if code == 400 and "읽을 글" in str(j.get("error", "")):
                    yield {"type": "end"}, None
                else:
                    yield {"type": "end", "code": code, "error": f"목소리 서버 {code}: {j.get('error') or raw[:80]!r}"}, None
                return
            yield {"type": "head", "speed_applied": headers.get("x-speed-applied") == "1",
                   "engine": headers.get("x-engine", "")}, None
            skip = 44   # WAV 머리
            odd = b""
            while True:
                sz = await reader.readline()
                if not sz:
                    break
                n = int(sz.split(b";")[0].strip() or b"0", 16)
                if n == 0:
                    break
                data = await reader.readexactly(n)
                await reader.readexactly(2)
                if skip:
                    cut = min(skip, len(data))
                    data, skip = data[cut:], skip - cut
                data = odd + data
                if len(data) % 2:
                    odd, data = data[-1:], data[:-1]
                else:
                    odd = b""
                if data:
                    yield {"type": "audio", "n": len(data)}, data
            done = True
            writer.close()
            writer = None
            yield {"type": "end"}, None
        except (OSError, asyncio.IncompleteReadError, ConnectionError) as ex:
            if not done:
                done = True
                yield {"type": "end", "error": f"목소리 서버 연결 끊김({ex.__class__.__name__})"}, None
        finally:
            if writer is not None:
                try:
                    writer.close()   # 중간에 닫히면(끼어들기) 서버가 알아채고 멈춤
                except Exception:  # noqa: BLE001
                    pass

    async def reset(self):
        self._reset = True

    async def close(self):
        pass


def log_unreachable(what, port, ex):
    logger.warning(f"{what} 서버(127.0.0.1:{port})에 못 붙음: {ex.__class__.__name__}")
