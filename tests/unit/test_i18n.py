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


def test_language_defaults_ko_unchanged():
    """언어별 기본값 파일이 한국어 기본값을 바꾸지 않는다(0.1.17 까지와 같은 설정)."""
    d = C.defaults("ko")
    assert d["언어"] == "ko"
    assert d["비서"]["이름"] == "김비서" and d["비서"]["인사"] == "네, {이름}입니다. 말씀하세요."
    assert d["대화"]["멈춤말"][:3] == ["잠깐", "그만", "멈춰"]
    assert d["통역"]["기본상대"] == "en" and d["사용자"]["기본장소"] == "서울"


def test_language_defaults_en_ja_zh():
    want = {"en": ("KimBiseo", "Seoul", "Yes, this is KimBiseo. How can I help you?"),
            "ja": ("キム秘書", "ソウル", "はい、キム秘書です。どうぞ。"),
            "zh": ("金秘书", "首尔", "在，我是金秘书。请讲。")}
    for code, (name, place, hello) in want.items():
        d = C.defaults(code)
        assert d["언어"] == code
        assert d["비서"]["이름"] == name and d["사용자"]["기본장소"] == place
        assert C.fill(d, d["비서"]["인사"]) == hello
        assert d["통역"]["기본상대"] == "ko", "외국어 앱은 통역 기본 상대가 한국어"
        assert d["대화"]["멈춤말"] and d["귀"]["환각문구"] and d["도구"]["먼저할말"]
        assert set(d["도구"]["먼저할말"]) == {"web_search", "read_page", "get_weather"}


def test_language_defaults_use_by_name_and_sites():
    from app.core.wake import NameMatcher
    from app.tools.basic import pc_action
    for code, name, alias, sites in (
            ("en", "KimBiseo", "Kim Biseo", ["YouTube", "Google Maps", "Wikipedia"]),
            ("ja", "キム秘書", "キムヒショ", ["ユーチューブ", "グーグルマップ"]),
            ("zh", "金秘书", "金祕書", ["百度", "谷歌地图"])):
        d = C.defaults(code)
        names, aliases = C.names(d)
        assert names == name and alias in aliases, (code, names, aliases)
        if code == "en":   # 가나·한자 호출어 인식은 7단계(wake.compact)에서 — 지금은 영어 이름만 확인
            assert "kimbiseo" in NameMatcher(names, aliases).words
        table = d["도구"]["컴퓨터조작"]
        for site in sites:
            url, why = pc_action.resolve_site(site, table["사이트"], table["별명"])
            assert url and url.startswith("https://"), (code, site, why)


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