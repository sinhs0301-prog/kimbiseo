# 통역 단위 시험 — 켜기·끄기 말, 언어 고르기, 숫자 지킴, 환율(고정 값), 번역 요청(가짜 두뇌), 설정 값 검사, 설치 목록(상업 OK·판 고정).
#   소리·두뇌·인터넷 없이 돈다.   python -m tests.unit.test_interp
import asyncio
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C            # noqa: E402
from app.core import fx, interp             # noqa: E402
from app.core import settings_api as S      # noqa: E402

L = interp.L
R = {"KRW당": {"THB": 1 / 39.485, "JPY": 1 / 8.389, "CNY": 1 / 200.449, "IDR": 1 / 0.07314, "TRY": 1 / 26.506, "EUR": 1 / 1468.364,
              "USD": 1 / 1336.202, "GBP": 1 / 1762.643, "VND": 1 / 0.05185, "RUB": 1 / 16.181},
     "기준일": "2026-11-17", "받은때": "2026-11-18 04:34"}


def fresh_cfg(user=None):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "settings.json")
    if user is not None:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(user, f, ensure_ascii=False)
    cfg = C.load(p, warn=lambda m: None)
    cfg["_settings_path"] = p
    return cfg


def test_commands():
    cfg = fresh_cfg()
    cases = {"태국어 통역해 줘": ("on", "th"), "통역해 줘": ("on", "auto"), "통역 모드 켜": ("on", "auto"),
             "태국 가서 영어 통역해 줘": ("on", "en"), "일본어 통역 부탁해": ("on", "ja"), "통역 그만": ("off", None),
             "이제 통역 끝": ("off", None), "그만 통역해": ("off", None), "이거 영어로 번역해 줘": None, "오늘 날씨 어때": None,
             "튀르키예어 통역 시작": ("on", "tr"), "베트남어 통역해 주세요": ("on", "vi")}
    for t, want in cases.items():
        assert L.parse_command(cfg, t) == want, (t, L.parse_command(cfg, t))


def test_on_command_asr_variants():
    cfg = fresh_cfg()
    for t in ("태국어 통역해져", "태국어 통역해조.", "태국어 통역 해주세요", "태국어 통역해", "태국어 통역하자", "태국어 통역해 줄래?"):
        assert L.parse_command(cfg, t) == ("on", "th"), t
    for t in ("어제 태국어 통역했어", "통역해서 알려 줬어", "이거 태국어로 번역해 줘"):
        assert L.parse_command(cfg, t) is None, t


def test_interp_home_language():
    """통역 일반화(0.1.18 6단계) — 앱 언어가 en 이면 'English ↔ Korean'으로. 목록에서 내 언어를 빼고 ko 를 넣는다."""
    cfg = fresh_cfg({"언어": "en"})
    assert L.home_of(cfg) == "en"
    langs = L.langs(cfg)
    assert "ko" in langs and "en" not in langs, langs
    assert L.name_of(cfg, "ko") == "Korean" and L.name_of(cfg, "en") == "English"
    assert L.name_of(cfg, "th") == "Thai"
    assert L.parse_command(cfg, "interpret Thai") == ("on", "th")
    assert L.parse_command(cfg, "start interpreting") == ("on", "auto")
    assert L.parse_command(cfg, "stop interpreting") == ("off", None)
    assert L.parse_command(cfg, "translate this to Thai") is None
    assert L.choose({"en": 0.8, "ko": 0.2}, home="en") == ("en", 0.8)
    assert L.choose({"ko": 0.7, "ja": 0.3}, home="en")[0] == "ko"
    # 내 언어(en)로 말하면 상대(ko)로, 상대(ko)가 말하면 내 언어(en)로
    interp._STATE.update(on=False, mode="auto", last=None, dst=None)
    interp.turn_on(cfg, "auto")
    assert interp.plan(cfg, "en") == "ko"
    assert interp.plan(cfg, "ko") == "en"
    a = interp.ear_args(cfg)
    assert a["langs"][0] == "en" and "ko" in a["langs"] and a["home"] == "en", a
    interp._STATE["dst"] = "ko"
    assert interp.speak_lang("안녕하세요", home="en") == "ko"     # 한국어 = 김비서 목소리
    interp._STATE["dst"] = "en"
    assert interp.speak_lang("Hello there", home="en") is None    # 내 언어 = 김비서 목소리
    pr = interp._prompt(cfg, "en", "ko")
    assert "interpreter from English to Korean" in pr, pr
    assert interp.money(cfg, "3,000円", "3,000엔이에요.", "ja", "ko") == "", "ko 앱이 아니면 환율 안 붙임"
    interp.turn_off()
    # 한국어 앱은 0.1.17 그대로 — 내 언어 ko, 목록에 ko 없음
    ko = fresh_cfg()
    assert L.home_of(ko) == "ko" and "ko" not in L.langs(ko)
    interp.turn_on(ko, "th")
    assert interp.plan(ko, "ko") == "th" and interp.plan(ko, "ja") == "ko"
    interp.turn_off()


def test_choose():
    assert L.choose({"ko": 0.7, "th": 0.3}) == ("ko", 0.7)
    assert L.choose({"ko": 0.1, "th": 0.85, "en": 0.05}, last="en", audio_sec=1.0) == ("en", 0.05)   # 짧은 말은 직전 언어
    assert L.choose({"ko": 0.01, "th": 0.95, "en": 0.04}, last="en", audio_sec=3.0) == ("th", 0.95)  # 확실하면 바꿈
    assert L.choose({"ko": 0.1, "th": 0.88, "en": 0.02}, last="en", audio_sec=3.0) == ("th", 0.88)   # 직전 언어가 거의 없으면 안 고집
    assert L.choose({"ko": 0.2, "ja": 0.8}, fixed="ja") == ("ja", 0.8)
    # 작은 귀가 짧은 한국말을 일본어로 헷갈림(설치 시험 실측 확률) → 직전 상대 언어(th)보다 한국어가 높으면 한국어
    assert L.choose({"ja": 0.63, "en": 0.091, "zh": 0.061, "it": 0.059, "ko": 0.04}, last="th", audio_sec=1.6)[0] == "ko"
    assert L.choose({"ja": 0.63, "en": 0.091, "zh": 0.061, "it": 0.059, "ko": 0.04}, last="en", audio_sec=1.6)[0] == "en"


def test_script_lang():
    assert L.script_lang("ห้องน้ำอยู่ที่ไหน") == "th"
    assert L.script_lang("Πού είναι η τουαλέτα;") == "el"
    assert L.script_lang("お手洗いはどこですか") == "ja"
    assert L.script_lang("東京駅", hint="ja") == "ja"
    assert L.script_lang("洗手间在哪里") == "zh"
    assert L.script_lang("Где туалет?") == "ru"
    assert L.script_lang("화장실이 어디예요?") == "ko"
    assert L.script_lang("Wo ist die Toilette?", hint="de") == "de"
    assert L.script_lang("Where is it?", hint="ko") == "en"


def test_voices():
    cfg = fresh_cfg()
    assert L.voice_of(cfg, "en").startswith("kokoro:") and L.voice_of(cfg, "de").startswith("piper:")
    for code in ("id", "vi"):
        assert L.voice_of(cfg, code) == "", code         # 상업용 원어민 목소리 없음 → 글자만
    assert L.voice_of(cfg, "th") == "thai:thai_som"     # 0.1.17~ 태국어 = MrJMThaiTTS
    assert L.model_of("thai:thai_som") == "thai-mrjm" and L.models_of("thai:thai_som") == ["thai-mrjm", "fastthaig2p"]
    assert L.models_of("kokoro:a:af_heart") == ["kokoro-82m"] and L.models_of("") == [] and L.models_of("thai:") == []
    cfg["통역"]["목소리_엔진"] = "글자만"
    assert L.voice_of(cfg, "en") == ""
    assert L.model_of("kokoro:a:af_heart") == "kokoro-82m" and L.model_of("piper:de_DE-thorsten-medium") == "piper-de_DE-thorsten-medium"
    names = json.load(open(os.path.join(ROOT, "installer", "interp", "models.json"), encoding="utf-8"))["models"]
    have = {m["name"] for m in names}
    for code, info in L.DEFAULT_LANGS.items():
        if info["목소리"]:
            assert L.model_of(info["목소리"]) in have, code
            assert set(L.models_of(info["목소리"])) <= have, code


def test_thai_chunks():
    sys.path.insert(0, os.path.join(ROOT, "voice"))
    import interp_voice as IV
    t = "สวัสดีค่ะ ไปสนามบินสุวรรณภูมิราคาเท่าไหร่คะ ประมาณสามร้อยห้าสิบบาทใช่ไหมคะ"
    assert IV.Thai.chunks(t) == [t]
    long = " ".join([t] * 6)
    parts = IV.Thai.chunks(long)
    assert len(parts) > 1 and all(len(x) <= IV.Thai.CHUNK for x in parts) and " ".join(parts) == long
    assert IV.Thai.chunks("ก" * 250, 100) == ["ก" * 100, "ก" * 100, "ก" * 50]
    assert IV.Thai.chunks("   ") == []


def test_numbers():
    for s, o, add in [("Το εισιτήριο κοστίζει 12,50 ευρώ.", "티켓 가격은 12.50유로입니다.", ""), ("1,5 km", "1.5km", ""),
                      ("It costs 1,500 baht at 3:30", "1500바트, 3시 30분", ""), ("택시비 1만 2천 원이고 3시 반", "12,000 won 3:30", ""),
                      ("ทั้งหมด ๓๕๐ บาท", "전부 35바트", " (350)"), ("Room 101, 2 nights", "101호, 2박", ""), ("10,000원", "10000 won", ""),
                      ("1,200,000동", "1.200.000 VND", ""), ("Das kostet 1.500 Euro", "1500유로예요", ""), ("1500원", "1.500 won", ""),
                      ("Giá 250.000 đồng", "25만 동", ""), ("350 บาทครับ", "350바트예요.", ""), ("2 tickets", "표 두 장", " (2)")]:
        assert interp.keep_numbers(s, o) == o + add, (s, interp.keep_numbers(s, o))


def test_money():
    for src, ko, lang, want in [
            ("ทั้งหมดสามร้อยห้าสิบบาทครับ", "전부 350바트입니다.", "th", " (약 13,800원)"),
            ("3,000円です", "3,000엔이에요.", "ja", " (약 25,200원)"),
            ("Tám trăm năm mươi nghìn đồng", "85만 동이에요.", "vi", " (약 44,100원)"),
            ("Toplam 450 lira", "총 450리라입니다.", "tr", " (약 11,900원)"),
            ("Το εισιτήριο κοστίζει 12,50 ευρώ.", "티켓 가격은 12.50유로입니다.", "el", " (약 18,400원)"),
            ("Harganya Rp 50.000", "가격은 5만 루피아예요.", "id", " (약 3,700원)"),
            ("Это стоит 500 рублей", "500루블이에요.", "ru", " (약 8,100원)"),
            ("ราคาสามร้อยครับ", "300입니다.", "th", " (바트라면 약 11,800원)"),
            ("ห้องน้ำอยู่ชั้นสอง", "화장실은 2층에 있어요.", "th", ""),
            ("รอสิบนาที", "10분 기다리세요.", "th", ""),
            ("Room 3, please", "3번 방이요", "en", "")]:
        assert fx.note(src, ko, lang, R)[0] == want, (ko, fx.note(src, ko, lang, R)[0])
    for v, w in [(13_816, 13_800), (987, 990), (44_123, 44_100), (123_456, 123_000), (1_234_567, 1_230_000)]:
        assert fx.won(v) == w


def test_fx_file_in_data_folder():
    d = tempfile.mkdtemp()
    fx.set_dir(d)
    assert fx.FILE == os.path.join(d, "fx_rates.json")
    fx._save(dict(R))
    assert fx.load()["기준일"] == "2026-11-17"
    assert "KimBiseo" in fx.UA and "@" not in fx.UA       # 사용자 정보 없는 User-Agent


class FakeResp:
    def __init__(self, content):
        self.content = content
        self.status_code = 400 if content is None else 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def post(self, url, json=None, headers=None):  # noqa: A002
        self.calls.append((url, dict(json)))
        return FakeResp(self.answers.pop(0))


def test_translate_local_brain_and_money():
    cfg = fresh_cfg()
    fx.set_dir(tempfile.mkdtemp())
    fx._save(dict(R, 받은때=__import__("time").strftime("%Y-%m-%d %H:%M"), 기준일=__import__("time").strftime("%Y-%m-%d")))
    base = f"http://127.0.0.1:{cfg['포트']['두뇌']}/v1"
    fake = FakeClient(["전부 35바트입니다."])
    interp._CLIENT.clear()
    interp._CLIENT[base] = fake
    out, who, _sec = asyncio.run(interp.translate(cfg, "ทั้งหมด ๓๕๐ บาท", "th", "ko"))
    assert who == "이 PC 의 AI", who
    assert out.startswith("전부 35바트입니다. (350)") and "원)" in out, out
    url, body = fake.calls[0]
    assert url == base + "/chat/completions" and body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "tools" not in body and body["messages"][0]["role"] == "system" and body["messages"][-1]["content"] == "ทั้งหมด ๓๕๐ บาท"
    item = interp.remember("ทั้งหมด ๓๕๐ บาท", out, "th", "ko")
    assert item["dst"] == "전부 35바트입니다. (350)" and item["money"].startswith("≈ "), item
    # 한국어 → 외국어: 환율 안 붙임, 그 나라 글자가 아니면 한 번 더 물음
    fake2 = FakeClient(["hong nam eo di", "ห้องน้ำอยู่ที่ไหนครับ"])
    interp._CLIENT[base] = fake2
    out, _w, _s = asyncio.run(interp.translate(cfg, "화장실 어디예요?", "ko", "th"))
    assert out == "ห้องน้ำอยู่ที่ไหนครับ" and len(fake2.calls) == 2, out
    interp._CLIENT.clear()


def test_interp_address_no_think_and_400_retry():
    """통역용 AI 주소(사용자가 적은 서버): 생각 끄기만 보냄(캐시 칸 없음) · 그 칸을 모르는 서버(400)면 빼고 한 번 더 — 설치 시험 2026-11-18:
    Gemma 4 가 생각만 하다 300 토큰을 다 써서 빈 답이 됨."""
    cfg = fresh_cfg()
    cfg["통역"]["두뇌_주소"] = "http://127.0.0.1:9999/v1"
    fake = FakeClient([None, "How much is it?"])
    interp._CLIENT.clear()
    interp._CLIENT["http://127.0.0.1:9999/v1"] = fake
    out, who, _ = asyncio.run(interp.translate(cfg, "얼마예요?", "ko", "en"))
    assert out == "How much is it?" and who == "통역용 AI 주소", (out, who)
    b1, b2 = fake.calls[0][1], fake.calls[1][1]
    assert b1.get("chat_template_kwargs") == {"enable_thinking": False} and "id_slot" not in b1 and "cache_prompt" not in b1
    assert "chat_template_kwargs" not in b2
    interp._CLIENT.clear()


def test_compat_brain_no_think_and_extras():
    """두뇌 = OpenAI 호환 API: 번역 요청에도 생각 끄기 + 사용자가 적은 추가 칸 — 0.1.17 홍보 캡처 시험에서 생각하는 모델이 한국어→태국어를 '빈 답'으로 냄."""
    cfg = fresh_cfg()
    cfg["두뇌"].update({"방식": "compat", "호환_주소": "http://127.0.0.1:9998/v1", "호환_모델": "m", "추가": {"top_k": 20, "model": "무시"}})
    fake = FakeClient(["ห้องน้ำอยู่ที่ไหนครับ"])
    interp._CLIENT.clear()
    interp._CLIENT["http://127.0.0.1:9998/v1"] = fake
    out, who, _ = asyncio.run(interp.translate(cfg, "화장실 어디예요?", "ko", "th"))
    assert out == "ห้องน้ำอยู่ที่ไหนครับ" and who == "OpenAI 호환 API", (out, who)
    b = fake.calls[0][1]
    assert b["chat_template_kwargs"] == {"enable_thinking": False} and b["top_k"] == 20 and b["model"] == "m", b
    assert "id_slot" not in b and "cache_prompt" not in b
    interp._CLIENT.clear()


def test_brain_choice():
    cfg = fresh_cfg()
    assert [b[0] for b in interp.brains(cfg)] == ["이 PC 의 AI"]
    cfg["통역"]["두뇌_주소"] = "http://127.0.0.1:9999/v1"
    assert [b[0] for b in interp.brains(cfg)] == ["통역용 AI 주소", "이 PC 의 AI"]
    cfg["통역"]["두뇌_주소"] = ""
    cfg["두뇌"]["방식"] = "claude_cli"
    assert [b[0] for b in interp.brains(cfg)] == ["구독 클로드"]   # 구독 두뇌도 됨(느림)
    cfg["두뇌"]["방식"] = "claude"
    assert interp.brains(cfg) == []          # 클로드 API 열쇠 두뇌는 통역에 안 씀
    out, why, _ = asyncio.run(interp.translate(cfg, "hello", "en", "ko"))
    assert out is None and "없어요" in why


def test_state_on_off():
    cfg = fresh_cfg()
    interp.turn_off()
    assert not interp.active(cfg)
    assert interp.turn_on(cfg, "th") == "th" and interp.active(cfg)
    assert interp.plan(cfg, "ko") == "th" and interp.plan(cfg, "ja") == "ko" and interp.plan(cfg, "ko") == "ja"
    a = interp.ear_args(cfg)
    assert a["langs"][0] == "ko" and "th" in a["langs"] and a["fixed"] is None
    interp.set_mode(cfg, "de")
    assert interp.ear_args(cfg)["langs"] == ["ko", "de"]
    interp._STATE["dst"] = "de"
    assert interp.speak_lang("Wo ist die Toilette?") == "de" and interp.speak_lang("네, 알겠어요.") is None
    interp._STATE["t"] -= 11 * 60
    assert not interp.active(cfg), "10분 말 없으면 저절로 꺼짐"
    assert interp.speak_lang("Wo ist die Toilette?") is None
    interp.turn_off()


def test_settings_fields():
    cfg = fresh_cfg()
    clean, err, _w = S.validate({"통역": {"목소리_엔진": "글자만", "환율_켜기": False, "자동끔_분": 15, "두뇌_주소": "http://127.0.0.1:1234/v1"}}, cfg)
    assert not err, err
    assert clean["통역.목소리_엔진"] == "글자만" and clean["통역.환율_켜기"] is False and clean["통역.자동끔_분"] == 15
    _c, err, _w = S.validate({"통역": {"목소리_엔진": "mms", "자동끔_분": 0}}, cfg)
    assert "통역.목소리_엔진" in err and "통역.자동끔_분" in err, err
    v = S.view(cfg)
    assert v["통역"]["목소리_엔진"] == "원어민" and v["통역"]["환율_켜기"] is True
    ids = [x["id"] for x in S.choices()["통역_목소리"]]
    assert ids == ["원어민", "글자만"]


def test_install_lists_commercial_ok():
    mf = {m["name"]: m for m in json.load(open(os.path.join(ROOT, "installer", "interp", "models.json"), encoding="utf-8"))["models"]}
    names = list(mf)
    base = json.load(open(os.path.join(ROOT, "installer", "models.json"), encoding="utf-8"))["models"]
    assert not [m for m in base if m.get("group") == "interp"], "통역 모델은 models.json(업데이트 DEPS) 밖에"
    assert sorted(names) == sorted(["kokoro-82m", "piper-de_DE-thorsten-medium", "piper-el_GR-rapunzelina-medium",
                                    "piper-ru_RU-denis-medium", "piper-tr_TR-antalia-medium", "thai-mrjm", "fastthaig2p"]), names
    for n in names:
        m = mf[n]
        # 목소리 모델은 허깅페이스 원 저장소, 태국어 글자 읽기 코드만 깃허브 원 저장소(고정 커밋 · raw)
        home = "https://raw.githubusercontent.com/awslabs/FastThaiG2P/" if n == "fastthaig2p" else "https://huggingface.co/"
        assert len(m["revision"]) == 40 and "{revision}" in m["base_url"] and m["base_url"].startswith(home), n
        assert not m["required"]
        for f in m["files"]:
            assert f.get("sha256") or f.get("git_sha1"), (n, f["path"])
        assert m["size_total"] == sum(f["size"] for f in m["files"])
    blob = json.dumps(mf, ensure_ascii=False).lower()
    for bad in ("facebook/mms", "lessac", "tsync", "news_tts", "xtts", "f5-tts", "fish-speech"):
        assert bad not in blob, bad
    lock = json.load(open(os.path.join(ROOT, "installer", "locks", "interp.json"), encoding="utf-8"))
    pk = {x["name"].lower().replace("_", "-"): x for x in lock["packages"]}
    assert {"kokoro", "misaki", "piper-tts", "torch", "onnxruntime", "tzdata"} <= set(pk), set(pk)
    th = json.load(open(os.path.join(ROOT, "installer", "locks", "interp-thai.json"), encoding="utf-8"))
    assert [x["name"] for x in th["packages"]] == ["pythainlp"] and len(th["packages"][0]["sha256"]) == 64
    assert th["python"] == lock["python"] and th["packages"][0]["url"].startswith("https://files.pythonhosted.org/")
    assert "회색" in mf["thai-mrjm"]["license"] and "OmniVoice" in mf["thai-mrjm"]["license"]   # 학습 자료 사실대로
    assert all(x["sha256"] and len(x["sha256"]) == 64 for x in lock["packages"])
    assert "+cpu" in pk["torch"]["version"] or "cpu" in pk["torch"]["url"], pk["torch"]["url"]


def test_no_mms_in_source():
    hits = []
    for d in ("app", "voice", "installer"):
        for dp, _dn, fn in os.walk(os.path.join(ROOT, d)):
            if "__pycache__" in dp:
                continue
            for f in fn:
                if f.endswith((".py", ".js", ".json", ".txt", ".html")):
                    t = open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read().lower()
                    if "mms-tts" in t or "vitsmodel" in t:
                        hits.append(os.path.relpath(os.path.join(dp, f), ROOT))
    assert not hits, hits


def main():
    sys.stdout.reconfigure(encoding="utf-8")
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
