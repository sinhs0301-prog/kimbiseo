# 말싸움(토론) 모드 단위 시험 — 소리·두뇌 없이 도는 것만.
#   켜기/끄기 말(ko·en·ja·zh) · 끄기 확인 · 30분 자동 끔 · 도구 거르기 · 금지어 빼기(설정·기억에서 실행 때 만듦) ·
#   꺼짐 지시문이 바꾸기 전과 글자 하나 다르지 않음(sha256) · 켜짐/성인 지시문 · 말 끝 기다림 늘리기 · 폰은 성인 항상 끔.
#   python tests/unit/test_debate.py   (저장소 뿌리에서 · pytest 가 있으면 pytest tests/unit 로도 됨)
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C            # noqa: E402
from app.core import debate, i18n, prompt   # noqa: E402
from app.core.memory import Memory          # noqa: E402
from app.core.state import SessionState      # noqa: E402
from app.tools.registry import load_packs   # noqa: E402

# 0.1.18 말싸움 넣기 전에 찍은 지시문(언어별, 말싸움 꺼짐). 이 글자가 달라지면 캐시·기존 대화가 흔들린다.
OFF_PROMPT_SHA = {
    "ko": "b78d2f24c76c69ca" "133de738382ca521" "413526fe8f833883" "a152f8d275da1be2",
    "en": "4f30e3c15be47bb4" "ccee05db3bd64deb" "f35639801520082f" "e576115b014c5fe9",
    "ja": "54f11657cedef32e" "7943a0476c26dafa" "9d6fcef1c2297e95" "f3f1e3e677f4365e",
    "zh": "27a30360fce5fea8" "e6e91e2e39a1c1e3" "ede625ae676cee39" "e4094d22a2d48f50",
}
PHONE = "-".join(["010", "9876", "5432"])      # 시험용 번호 꼴(글자 그대로의 번호를 피하려고 조립)


def cfg(lang="ko", **over):
    i18n.set_lang(lang)
    return C.deep_merge(C.defaults(lang), over)


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class Params:
    def __init__(self, sec):
        self.stop_secs = sec


class Vad:
    def __init__(self, sec):
        self.params = Params(sec)
        self.calls = 0

    def set_params(self, p):
        self.calls += 1


class Turn:
    def __init__(self, sec):
        self.params = Params(sec)
        self._stop_ms = sec * 1000


def test_toggle_words_four_languages():
    c = cfg()
    on_cases = ["말싸움 하자", "토론하자", "말싸움 모드", "김비서, 말싸움 하자!", "이제 말싸움 시작"]
    off_cases = ["말싸움 그만", "말싸움 끝", "평소로", "이제 평소로 돌아가", "말싸움 그만해"]
    for t in on_cases:
        assert debate.intent(c, t) == "on", (t, debate.intent(c, t))
    for t in off_cases:
        assert debate.intent(c, t) == "off", (t, debate.intent(c, t))
    for t in ("오늘 말싸움 하자고 했잖아", "말싸움은 재밌어", "토론 주제 뭐야", "평소로는 안 그렇지"):
        assert debate.intent(c, t) is None, (t, debate.intent(c, t))
    for lang, on, off in (("en", "let's argue", "stop arguing"),
                          ("ja", "口論しよう", "やめよう"),
                          ("zh", "来吵架", "别吵了")):
        c2 = cfg(lang)
        assert debate.intent(c2, on) == "on", (lang, on, debate.intent(c2, on))
        assert debate.intent(c2, off) == "off", (lang, off, debate.intent(c2, off))
        assert debate.intent(c2, "그냥 잡담") is None


def test_off_needs_confirmation_without_voice_gate():
    st = SessionState(cfg())
    say = debate.command(st, "말싸움 하자")
    assert st.debate and say
    say = debate.command(st, "말싸움 그만")
    assert st.debate and "정말" in say, say                 # 등록 안 했으면 한 번 묻는다
    say = debate.command(st, "네")
    assert not st.debate and say                              # 확인하면 꺼짐
    st2 = SessionState(cfg())
    assert debate.command(st2, "말싸움 하자") and st2.debate
    debate.command(st2, "말싸움 그만")
    assert st2.debate
    assert debate.command(st2, "말싸움 그만") and not st2.debate   # 두 번째 끄기 말도 확인으로 봄


def test_registered_voice_only_can_toggle():
    st = SessionState(cfg())
    debate.set_on(st)
    say = debate.command(st, "말싸움 그만", voice_ok=False, gate_on=True)
    assert st.debate and "목소리" in say, say
    say = debate.command(st, "말싸움 그만", voice_ok=True, gate_on=True)
    assert not st.debate and say
    st2 = SessionState(cfg())
    assert debate.command(st2, "말싸움 하자", typed=True) and st2.debate    # 글로 쓴 말은 사용자 것
    assert debate.command(st2, "말싸움 그만", typed=True) and not st2.debate


def test_adult_only_on_pc():
    c = cfg(말싸움={"성인": True})
    st = SessionState(c)
    assert debate.adult(st) is True
    st.debate_adult_allowed = False
    assert debate.adult(st) is False     # 폰 앱 대화에서는 항상 끔
    st.debate_adult_allowed = True
    st.cfg["말싸움"]["성인"] = False
    assert debate.adult(st) is False


def test_auto_off_and_touch():
    st = SessionState(cfg())
    debate.set_on(st)
    st.debate_t = time.time() - 31 * 60
    assert debate.tick(st) is True and not st.debate
    st2 = SessionState(cfg())
    debate.set_on(st2)
    st2.debate_t = time.time() - 31 * 60
    debate.touch(st2)
    assert debate.tick(st2) is False and st2.debate


def test_timers_stretch_and_restore():
    st = SessionState(cfg())
    st.vad, st.vad_stop_base = Vad(0.2), 0.2
    st.smart_turn, st.smart_stop_base = Turn(3.0), 3.0
    debate.set_on(st)
    assert abs(st.vad.params.stop_secs - 0.5) < 1e-9, st.vad.params.stop_secs
    assert abs(st.smart_turn.params.stop_secs - 4.5) < 1e-9, st.smart_turn.params.stop_secs
    assert abs(st.smart_turn._stop_ms - 4500) < 1e-6
    assert st.vad.calls == 1
    debate.set_off(st)
    assert abs(st.vad.params.stop_secs - 0.2) < 1e-9
    assert abs(st.smart_turn.params.stop_secs - 3.0) < 1e-9
    assert abs(st.smart_turn._stop_ms - 3000) < 1e-6
    assert abs(debate.silence(0.4, cfg()) - 0.6) < 1e-9 and abs(debate.silence(0.1, cfg()) - 0.5) < 1e-9


def test_tools_filtered_to_outside_info():
    c = cfg()
    tools = [{"type": "function", "function": {"name": n}} for n in
             ("web_search", "read_page", "get_weather", "calc", "remember", "recall", "forget",
              "pc_action", "type_text", "speech_speed", "standby", "phone_action")]
    kept = [t["function"]["name"] for t in debate.filter_tools(tools, c)]
    assert kept == ["web_search", "read_page", "get_weather", "calc"], kept
    flat = [{"name": "web_search"}, {"name": "remember"}, {"name": "calc"}]
    assert [t["name"] for t in debate.filter_tools(flat, c)] == ["web_search", "calc"]


def test_banned_values_from_settings_and_memory():
    d = tempfile.mkdtemp()
    try:
        m = Memory(d)
        m.add("사용자는 김치찌개를 제일 좋아한다")
        c = cfg(사용자={"호칭": "철수", "기본장소": "부산"}, 화면={"마이크_이름": "거실 마이크"})
        st = SessionState(c)
        st.debate_memory = m
        words, pats = debate.banned_rules(c, m)
        assert any("철수" in w for w in words) and any("부산" in w for w in words), words
        assert any("김치찌개" in w for w in words), words
        assert not any(w == "사용자" for w in words), "흔한 낱말은 금지어로 쓰지 않음"
        assert pats, "전화·주소 꼴은 정규식으로 막음"

        debate.set_on(st)
        clean = "그건 네 주장이 약해. 근거가 부족해."
        assert debate.filter_text(clean, st) == clean
        dirty = "철수는 부산에 살아. 그건 논점이 아니야."
        got = debate.filter_text(dirty, st)
        assert "철수" not in got and "부산" not in got and "논점" in got, got
        phone = f"내 번호는 {PHONE}야. 그건 논점이 아니지."
        got2 = debate.filter_text(phone, st)
        assert PHONE not in got2 and "논점" in got2, got2
        assert debate.filter_text("철수 얘기만 하자.", st) == ""

        msgs = [{"role": "system", "content": "SYSTEM"},
                {"role": "user", "content": "철수 얘기야. 논점은 다르지."},
                {"role": "assistant", "content": "좋아, 반박한다."},
                {"role": "tool", "content": f'{{"전화": "{PHONE}"}}'}]
        fm = debate.filter_messages(msgs, st)
        assert fm[0]["content"] == "SYSTEM"
        assert "철수" not in fm[1]["content"] and "논점" in fm[1]["content"]
        assert fm[2]["content"] == "좋아, 반박한다."
        assert PHONE not in fm[3]["content"]
        tagged = [{"role": "user", "content": "[자동 정보: 기기 안내]\n[지난 대화 요약 — 예전]\n주장은 이래."}]
        ft = debate.filter_messages(tagged, st)[0]["content"]
        assert "현재 시각" not in ft and "기기 안내" not in ft and "지난 대화 요약" not in ft and "주장은 이래" in ft, ft

        debate.set_off(st)
        assert debate.filter_text(dirty, st) == dirty       # 꺼짐이면 그대로
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_off_prompt_identical_to_before():
    for lang in ("ko", "en", "ja", "zh"):
        c = cfg(lang)
        specs, _ = load_packs(c)
        s = prompt.system_prompt(c, specs)
        assert sha(s) == OFF_PROMPT_SHA[lang], (lang, sha(s))
        assert prompt.system_prompt(c, specs, debate=False) == s
        st = SessionState(c)
        debate.set_on(st)
        assert prompt.system_prompt(c, specs, debate=True, adult=False) != s
        debate.set_off(st)
        assert prompt.system_prompt(c, specs, debate=debate.on(st), adult=debate.adult(st)) == s


def test_debate_prompt_rules_four_languages():
    for lang in ("ko", "en", "ja", "zh"):
        c = cfg(lang)
        base = prompt.system_prompt(c, (), debate=True, adult=False)
        head = prompt.system_prompt(c, (), debate=True, adult=True)
        bl, hl = base.lower(), head.lower()
        assert len(head) > len(base)
        # 세 가지 금지(미성년·실제 인물·집단 혐오)는 두 단계 모두 들어 있고, 나머지는 막지 않는다고 적음
        for text, lt in ((base, bl), (head, hl)):
            assert "미성년자" in text or "minor" in lt or "未成年" in text, (lang, text[:120])
        assert "욕설" in head or "profanity" in hl or "悪口" in head or "脏话" in head
        assert "섹드립" in head or "sexual joke" in hl or "下ネタ" in head or "黄段子" in head
        assert "반말" in base or "casual" in bl or "タメ口" in base or "平语" in base
        # 개인 기억·비서 지시문은 안 들어감
        assert "사용자를 부를 때는" not in base and "Things remembered about" not in base


def test_interrupt_only_registered_voice():
    st = SessionState(cfg())
    debate.set_on(st)
    assert debate.may_interrupt(st, gate_on=True, owner=True) is True
    assert debate.may_interrupt(st, gate_on=True, owner=False) is False
    assert debate.may_interrupt(st, gate_on=False, owner=True) is False
    debate.set_off(st)
    assert debate.may_interrupt(st, gate_on=True, owner=True) is False


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