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
    want = {"en": ("Kimmy", "Seoul", "Yes, this is Kimmy. How can I help you?"),
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
            ("en", "Kimmy", "KimBiseo", ["YouTube", "Google Maps", "Wikipedia"]),
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


def test_wake_names_four_languages():
    """호출어(0.1.18 7단계) — 한국어·영어·일본어·중국어 이름·별칭을 실제로 알아듣는지.
    예전 wake.compact 는 [0-9a-z가-힣] 만 남겨 キム秘書·金秘书가 빈 글이 되어 깨우지 못했다."""
    from app.core.wake import NameMatcher
    cases = {
        "ko": ("김비서", ["김비서", "김 비서", "김비서야", "김비서!"]),
        "en": ("Kimmy", ["Kimmy", "Hey Kimmy", "Kimmy, turn on the light", "KimBiseo", "Kim Biseo", "Kimmy!"]),
        "ja": ("キム秘書", ["キム秘書", "キム秘書さん", "キミー", "キム秘書、電気をつけて", "Kimmy"]),
        "zh": ("金秘书", ["金秘书", "金秘书呀", "金祕書", "金秘书，开灯", "Kimmy"]),
    }
    for code, (name, calls) in cases.items():
        d = C.defaults(code)
        n, al = C.names(d)
        assert n == name, (code, n)
        m = NameMatcher(n, al)
        for text in calls:
            assert m.call(text) == name, (code, text, m.call(text), m.words)
        assert m.only_name(calls[0] + "!") in (True, False)  # 터지지 않으면 됨
    # 이름 뒤에 조사·다른 말이 붙은 '말한 것'은 부름이 아님
    assert NameMatcher("김비서", []).call("김비서한테 물어봐") is None
    assert NameMatcher("Kimmy", []).call("I asked Kimmy about it") is None


def test_wake_aliases_include_brand_names():
    """영어 기본 이름은 Kimmy, 별칭에 KimBiseo·Kim Biseo 유지. 일본어·중국어 별칭에 Kimmy."""
    from app.core.wake import compact
    for code, want in (("en", ["kimbiseo", "kimbiseo"]), ("ja", ["キミー", "kimmy"]), ("zh", ["kimmy"])):
        d = C.defaults(code)
        n, al = C.names(d)
        al_c = [compact(x) for x in al]
        for w in want:
            assert w in al_c, (code, w, al_c)


def test_prompt_and_memory_follow_app_language():
    """두뇌 지시문(0.1.18 5단계) — 앱 언어가 ko 가 아니면 영어 지시문 + 'Reply only in …'.
    기억 자동 추출·일기 프롬프트도 같은 언어로."""
    from app.core import prompt
    from app.core.memory import Memory
    spec = [{"type": "function", "function": {"name": "get_weather", "description": "날씨를 알려 준다",
                                              "parameters": {"type": "object", "properties": {"place": {"type": "string", "description": "장소"}}}}}]
    old = i18n.current()
    try:
        for code, reply in (("en", "Reply only in English."), ("ja", "Reply only in Japanese."), ("zh", "Reply only in Chinese.")):
            i18n.set_lang(code)
            cfg = C.defaults(code)
            text = prompt.base_prompt(cfg, spec)
            assert "You are a voice assistant" in text and reply in text, (code, text[:300])
            assert "너는" not in text, code
            assert "weather" in text.lower()
            assert prompt.now_tag(lang=code).startswith("(Current time:")
        i18n.set_lang("ko")
        ko = prompt.base_prompt(C.defaults("ko"), spec)
        assert "너는" in ko and "Reply only in" not in ko
        i18n.set_lang("en")
        m = Memory(tempfile.mkdtemp())
        m.add("The user likes coffee.")
        assert "Things remembered about" in m.prompt_block("the user")
        req = m.auto_request([{"role": "user", "content": "I like coffee."}])
        assert "in English" in req[0]["content"]
        dreq = m.diary_request([{"role": "user", "content": "I like coffee."}, {"role": "assistant", "content": "Okay."}])
        assert "in English" in dreq[0]["content"]
    finally:
        i18n.set_lang(old)


def test_existing_settings_stay_korean():
    """0.1.17 까지 쓰던 사람(설정에 '언어' 없음)은 한국어 그대로 — 완료 기준 ②."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "settings.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"비서": {"이름": "김비서"}, "화면": {"글자": "크게"}}, f, ensure_ascii=False)
    c = C.load(p, warn=lambda m: None)
    assert c["언어"] == "ko" and c["비서"]["이름"] == "김비서"
    # 화면 사전은 고른 언어 것만 내려간다(한국어는 빈 사전)
    assert i18n.table("ko") == {}
    en = i18n.table("en")
    assert en["김비서"] == "Kimmy (KimBiseo)" and len(en) > 1000
    assert i18n.table("ja")["김비서"] == "キム秘書" and i18n.table("zh")["김비서"] == "金秘书"


def test_tr_and_lookup_with_filled_placeholders():
    """tr(틀) 과 lookup(이미 채워진 글) — 자리 {n}·{이름} 를 살려 바꾸고, ko 면 원문 그대로."""
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "en.json"), "w", encoding="utf-8") as f:
        json.dump({"오류": "Error", "{n}개 받음": "Received {n}", "{0}개 받음": "Received {0}",
                   "{이름}입니다": "This is {이름}"}, f, ensure_ascii=False)
    old = i18n.I18N_DIR
    try:
        i18n.I18N_DIR = d
        i18n._CACHE.clear()
        assert i18n.tr("오류", lang="en") == "Error"
        assert i18n.tr("{n}개 받음", lang="en", n=3) == "Received 3"
        assert i18n.tr("{m}개 받음", lang="en", m=4) == "Received 4"   # 이름이 다른 틀({0})도 대조
        assert i18n.lookup("5개 받음", "en") == "Received 5"
        assert i18n.lookup("김비서입니다", "en") == "This is 김비서"    # 안쪽 이름은 다시 lookup(사전에 없으면 원문)
        assert i18n.tr("오류", lang="ko") == "오류"
        assert i18n.lookup("오류", "ko") == "오류"
    finally:
        i18n.I18N_DIR = old
        i18n._CACHE.clear()


def test_screen_dictionaries_cover_scan():
    """화면 사전(en·ja·zh)이 i18n_scan 이 찾은 원문을 모두 덮고, 자리·한글이 맞는지(tools/i18n_scan.py check 와 같은 규칙)."""
    import re
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    try:
        import i18n_scan
    finally:
        sys.path.pop(0)
    found = i18n_scan.collect()
    assert len(found) > 1000, len(found)
    for code in ("en", "ja", "zh"):
        d = i18n_scan.load_dict(code)
        assert set(found) <= set(d), (code, sorted(set(found) - set(d))[:3])
        bad = [k for k, v in d.items() if i18n_scan.placeholders(k) != i18n_scan.placeholders(v)]
        assert not bad, (code, bad[:3])
        hangul = [k for k, v in d.items()
                  if re.search(r"[가-힣]", re.sub(r"\{[^{}\s]{1,40}\}", "", v)) and not re.search(r"한국어|한글", v)]
        assert not hangul, (code, hangul[:3])
        assert d["김비서"] == {"en": "Kimmy (KimBiseo)", "ja": "キム秘書", "zh": "金秘书"}[code]
        assert d["설정"] == {"en": "Settings", "ja": "設定", "zh": "设置"}[code]


def test_installer_language():
    """설치기(installer/setup_core.py)도 같은 사전 — 영어로 고르면 단계 이름·진행 글이 영어가 되고, 조각을 이어 붙여도 한글이 남지 않는다."""
    import re
    sys.path.insert(0, os.path.join(ROOT, "installer"))
    try:
        import setup_core as SC
    finally:
        sys.path.pop(0)
    old = SC.LANG
    try:
        assert SC.set_lang("en") == "en"
        assert not re.search(r"[가-힣]", SC.L(dict(SC.STEPS)["python"]))
        assert SC.L("프로그램 파일을 설치 폴더에 복사해요.") == "Copying program files to the install folder."
        label = SC.T("{0} 부품 {1}/{2} {3}", SC.L("본체"), 51, 81, "packaging")
        assert label == "Main app component 51/81 packaging", label
        assert not re.search(r"[가-힣]", SC.T("{0} 확인 중(원본과 같은지)", label))
        assert SC.L(SC.took(75)) == "1 min 15 sec"
    finally:
        SC.set_lang(old)


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