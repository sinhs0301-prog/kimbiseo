# 다국어(0.1.18~) 단위 시험 — 언어 코드·글 정리·목소리 요청의 언어. 소리·두뇌 없이 돈다.
#   python tests/unit/test_i18n.py
import asyncio
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C            # noqa: E402
from app.core import i18n                   # noqa: E402
from app.core.filters import app_clean, tts_clean  # noqa: E402
from app.core.state import SessionState     # noqa: E402
from app.core.tts import VoiceTTS           # noqa: E402
from app.core.voice_link import VoiceLink, text_norm  # noqa: E402


def cfg(**over):
    c = C.load(os.path.join(tempfile.mkdtemp(), "없음.json"), warn=lambda m: None)
    return C.deep_merge(c, over)


def test_norm_lang_codes():
    assert i18n.norm("en-US") == "en" and i18n.norm("EN") == "en"
    assert i18n.norm("japanese") == "ja" and i18n.norm("zh-Hans") == "zh"
    assert i18n.norm("") == "ko" and i18n.norm("모르는말") == "ko"
    assert i18n.lang_of({}) == "ko" and i18n.lang_of({"언어": "ja"}) == "ja"


def test_app_clean_keeps_foreign_script():
    """앱 언어가 외국어일 때: 한자·가나를 지우지 않고 숫자를 한국어로 읽지 않는다(한국어 앱은 예전 그대로)."""
    zh = "你好，世界。2026年3時"
    assert app_clean(zh) == zh
    assert "你好" not in tts_clean(zh) and tts_clean(zh) != zh, "한국어 길은 한자를 지운다(0.1.17 그대로)"
    assert text_norm.normalize("2026년 3시") != "2026년 3시", "한국어 읽기 변환은 살아 있음"
    assert app_clean("  Hello *world*  ") == "Hello world"


class _Mouth:
    """목소리 서버 대신 — 받은 글·언어를 적고 소리 한 조각을 낸다."""

    def __init__(self):
        self.calls = []

    async def speak(self, text, speed=1.0, lang=None):
        self.calls.append((text, lang))
        yield {"type": "head", "speed_applied": True}, None
        yield {"type": "audio"}, b"\x00\x00" * 50
        yield {"type": "end"}, None

    async def close(self):
        pass


def _speak(code, text):
    async def run():
        st = SessionState(cfg(언어=code))
        m = _Mouth()
        vt = VoiceTTS(st, voice=m)
        await anext(vt.run_tts(text, "시험"))     # 첫 조각이면 충분(목소리 부름을 확인)
        got = list(m.calls)
        await vt.cleanup()
        return got
    return asyncio.run(run())


ENG = "This is a fairly long English answer that should be spoken aloud by the assistant."
ZH = "你好，世界。这是一个很长的中文回答。"


def test_tts_english_answer_is_spoken_when_app_en():
    """앱 언어 en 이면 영어 답을 막지 않고 그대로 읽는다 — 0.1.17 은 '영어라 안 읽음'으로 막았다."""
    assert _speak("en", ENG) == [(ENG, "en")]
    assert _speak("ja", "これは日本語の長い答えです。") == [("これは日本語の長い答えです。", "ja")]
    assert _speak("zh", ZH) == [(ZH, "zh")]


def test_tts_english_still_blocked_in_korean_app():
    got = _speak("ko", ENG)
    assert len(got) == 1 and got[0][1] == "ko"
    assert got[0][0].startswith("영어로 된 답이라"), got


def test_chinese_kept_when_app_zh():
    assert _speak("zh", ZH)[0][0] == ZH


def test_voice_link_sends_lang_only_outside_korean():
    """목소리 서버 요청: 앱 언어가 ko 면 예전과 똑같이 'lang' 없음, 아니면 그 언어를 실어 보냄."""
    async def run():
        seen = []

        async def handle(reader, writer):
            n = 0
            while True:
                ln = await reader.readline()
                if ln in (b"\r\n", b"\n", b""):
                    break
                if ln.lower().startswith(b"content-length:"):
                    n = int(ln.split(b":")[1])
            req = json.loads((await reader.readexactly(n)).decode("utf-8"))
            seen.append(req)
            pcm = bytes(44) + b"\x01\x00" * 50
            writer.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + b"%x\r\n" % len(pcm) + pcm + b"\r\n0\r\n\r\n")
            await writer.drain()
            writer.close()

        srv = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        link = VoiceLink(cfg(포트={"목소리": port}))
        link.voice = None
        for text, lang in (("안녕하세요", "ko"), ("Hello", "en"), ("你好", "zh")):
            [ev async for ev, _ in link.speak(text, lang=lang)]
        srv.close()
        return seen

    seen = asyncio.run(run())
    assert "lang" not in seen[0] and seen[0]["text"] == "안녕하세요"
    assert seen[1]["lang"] == "en" and seen[1]["text"] == "Hello"
    assert seen[2]["lang"] == "zh" and seen[2]["text"] == "你好"


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