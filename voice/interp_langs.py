# 통역 언어 목록·켜기 끄기 말·언어 감지(귀 서버와 본체가 같이 씀 — 표준 라이브러리만, torch 는 detect() 안에서만).
#   언어 목록은 사용자 설정 "통역"."언어" 로 고치거나 더할 수 있음(여기 DEFAULT 는 설정이 비었을 때).
#   목소리 = 통역 원어민 목소리(voice/interp_voice.py — 선택 부품 '통역 목소리 받기'):
#     kokoro:<언어글자>:<목소리>  Kokoro-82M(Apache-2.0)
#     piper:<목소리 이름>          Piper(학습 자료 CC0·CC-BY 인 목소리만)
#     thai:<목소리 묶음>            태국어(0.1.17~) — MrJMThaiTTS(Kokoro 태국어 판, 가중치 Apache-2.0 · 학습 자료는 회색) + FastThaiG2P(글자 → 발음)
#     ""(빈 칸)                    원어민 목소리가 없는 언어 — 글자만 보여 줌(인도네시아어·베트남어)
import re

DEFAULT_LANGS = {
    "en": {"이름": "영어", "부르는말": ["영어", "영문", "잉글리시", "english"], "목소리": "kokoro:a:af_heart"},
    "th": {"이름": "태국어", "부르는말": ["태국어", "태국말", "타이어", "태국"], "목소리": "thai:thai_som",
           "번역지시": "태국어는 공손한 말끝(남성 ครับ, 여성 ค่ะ)을 쓰세요. 말하는 사람의 성별을 모르면 ครับ."},
    "ja": {"이름": "일본어", "부르는말": ["일본어", "일본말", "일어", "일본"], "목소리": "kokoro:j:jf_alpha"},
    "zh": {"이름": "중국어", "부르는말": ["중국어", "중국말", "보통화", "만다린", "중국"], "목소리": "kokoro:z:zf_xiaobei",
           "번역지시": "중국어는 보통화 간체자로."},
    "id": {"이름": "인도네시아어", "부르는말": ["인도네시아어", "인도네시아말", "인니어", "인도네시아", "발리"], "목소리": ""},
    "vi": {"이름": "베트남어", "부르는말": ["베트남어", "베트남말", "베트남"], "목소리": ""},
    "de": {"이름": "독일어", "부르는말": ["독일어", "독일말", "독일"], "목소리": "piper:de_DE-thorsten-medium"},
    "el": {"이름": "그리스어", "부르는말": ["그리스어", "그리스말", "그리스"], "목소리": "piper:el_GR-rapunzelina-medium"},
    "tr": {"이름": "터키어", "부르는말": ["터키어", "튀르키예어", "터키말", "터키", "튀르키예"], "목소리": "piper:tr_TR-antalia-medium"},
    "ru": {"이름": "러시아어", "부르는말": ["러시아어", "러시아말", "러시아"], "목소리": "piper:ru_RU-denis-medium"},
    "fr": {"이름": "프랑스어", "부르는말": ["프랑스어", "불어", "프랑스말", "프랑스"], "목소리": "kokoro:f:ff_siwis"},
    "es": {"이름": "스페인어", "부르는말": ["스페인어", "스페인말", "스페인"], "목소리": "kokoro:e:ef_dora"},
    "it": {"이름": "이탈리아어", "부르는말": ["이탈리아어", "이태리어", "이탈리아말", "이탈리아", "이태리"], "목소리": "kokoro:i:if_sara"},
}
KO = "ko"
# 앱 언어(내 언어) — 통역은 '내 언어 ↔ 상대 언어'. 설정 '언어'가 없으면 ko(0.1.17 그대로).
HOME_LANGS = ("ko", "en", "ja", "zh")
# 언어 이름을 앱 언어로 — 이름 표는 화면·말에 그대로 쓴다.
NAMES = {
    "ko": {"ko": "한국어", "en": "영어", "th": "태국어", "ja": "일본어", "zh": "중국어", "id": "인도네시아어",
           "vi": "베트남어", "de": "독일어", "el": "그리스어", "tr": "터키어", "ru": "러시아어", "fr": "프랑스어",
           "es": "스페인어", "it": "이탈리아어"},
    "en": {"ko": "Korean", "en": "English", "th": "Thai", "ja": "Japanese", "zh": "Chinese", "id": "Indonesian",
           "vi": "Vietnamese", "de": "German", "el": "Greek", "tr": "Turkish", "ru": "Russian", "fr": "French",
           "es": "Spanish", "it": "Italian"},
    "ja": {"ko": "韓国語", "en": "英語", "th": "タイ語", "ja": "日本語", "zh": "中国語", "id": "インドネシア語",
           "vi": "ベトナム語", "de": "ドイツ語", "el": "ギリシャ語", "tr": "トルコ語", "ru": "ロシア語",
           "fr": "フランス語", "es": "スペイン語", "it": "イタリア語"},
    "zh": {"ko": "韩语", "en": "英语", "th": "泰语", "ja": "日语", "zh": "中文", "id": "印尼语",
           "vi": "越南语", "de": "德语", "el": "希腊语", "tr": "土耳其语", "ru": "俄语", "fr": "法语",
           "es": "西班牙语", "it": "意大利语"},
}
# 목소리 → 받아야 할 모델 이름(installer/interp/models.json) — 화면에서 '받은 목소리'를 보여 줄 때
VOICE_MODEL = {"kokoro": "kokoro-82m", "piper": "piper-{}", "thai": "thai-mrjm"}
THAI_G2P = "fastthaig2p"   # 태국어 목소리가 같이 쓰는 글자 → 발음 바꾸기(코드·사전) 모델 폴더


def home_of(cfg):
    """내 언어(앱 언어) — 통역의 한쪽. 설정 '언어'가 없거나 모르는 값이면 ko(0.1.17 그대로)."""
    v = str((cfg or {}).get("언어") or "ko").strip().lower()[:2]
    return v if v in HOME_LANGS else KO


def _name(home, code):
    return (NAMES.get(home) or NAMES["ko"]).get(code) or code


def _call_words(home, code):
    """그 앱 언어에서 그 언어를 부르는 말 — 내 언어 이름(그 언어로) + 한국어 기본 목록(한국어앱)."""
    info = DEFAULT_LANGS.get(code) or {}
    if home == KO:
        return [str(x) for x in (info.get("부르는말") or [])]
    words = [_name(home, code).lower()] + [str(x) for x in (info.get("부르는말") or [])]
    return list(dict.fromkeys(w for w in words if w))


def langs(cfg):
    """상대 언어 목록 — 내 언어는 빼고, 내 언어가 ko 가 아니면 ko 를 상대로 넣는다."""
    t = (cfg or {}).get("통역") or {}
    got = t.get("언어") or {}
    src = got if got else DEFAULT_LANGS
    home = home_of(cfg)
    out = {k: dict(v) for k, v in src.items() if isinstance(v, dict) and not str(k).startswith("_")}
    if home != KO:
        out.pop(home, None)
        out[KO] = {"이름": _name(home, KO), "부르는말": [], "목소리": ""}   # 한국어 = 김비서 목소리
    for k, v in out.items():
        v["이름"] = _name(home, k)
        v["부르는말"] = _call_words(home, k)
    return out


def name_of(cfg, code):
    return _name(home_of(cfg), code)


def voice_of(cfg, code):
    """그 언어 원어민 목소리 이름. 설정 통역.목소리_엔진 = '글자만' 이면 늘 빈 칸."""
    if str(((cfg or {}).get("통역") or {}).get("목소리_엔진") or "원어민") == "글자만":
        return ""
    return str((langs(cfg).get(code) or {}).get("목소리") or "")


def model_of(voice):
    """목소리 이름 → 모델 폴더 이름(installer/interp/models.json). 모르면 ''."""
    kind, _, rest = str(voice or "").partition(":")
    if kind == "kokoro":
        return VOICE_MODEL["kokoro"]
    if kind == "piper" and rest:
        return VOICE_MODEL["piper"].format(rest)
    if kind == "thai" and rest:
        return VOICE_MODEL["thai"]
    return ""


def models_of(voice):
    """목소리에 필요한 모델 폴더 전부(태국어 = 목소리 + 글자 → 발음). 모르면 []."""
    m = model_of(voice)
    if not m:
        return []
    return [m, THAI_G2P] if m == VOICE_MODEL["thai"] else [m]


def whisper_codes(codes, home=KO):
    out = [home_of({"언어": home})]
    for c in codes:
        if c and c not in out:
            out.append(c)
    return out


# ---------------------------------------------------------------- 켜기·끄기 말
# 켜기 = '통역'에 시키는 말이 붙은 것만("영어 통역해 줘·통역 모드 켜·통역 시작"). "이거 영어로 번역해 줘"(한 번 번역 = 평소 두뇌)는 아님
#   받아쓰기가 '해 줘'를 '해져·해조·해주'로 적는 일이 많음(작은 귀 + 윈도우 음성 시험 2026-11-18) → '해' 뒤 줘·져·저·조·쥬·주·줄·봐·요 와 문장 끝 '통역해'도 켜기.
#   '통역했어·통역해서'는 아님.
_ON = re.compile(r"통역\s*(을|좀)?\s*(해\s*(줘|져|저|조|죠|쥬|주|줄|봐|요)|해(?=[\s.!?~]*$)|하자|모드|시작|켜|부탁)")
_OFF = re.compile(r"(통역|번역)\s*(그만|끝|종료|멈춰|중지|꺼|끄|마쳐|안\s*해|하지\s*마|필요\s*없)|"
                  r"(그만|끝|종료)\s*(통역|번역)|통역\s*모드\s*(끄|꺼|해제)", re.I)
# 내 언어가 ko 가 아닐 때 — 영어·일본어·중국어로 통역 켜기·끄기
_ON_EXTRA = re.compile(r"\binterpret(?:ing|ation)?\b|\btranslate for me\b|\bstart (?:interpreting|translation)\b|"
                       r"通訳|口译|同声传译|翻译模式", re.I)
_OFF_EXTRA = re.compile(r"\bstop (?:interpreting|translating|translation)\b|\b(?:end|finish|quit|turn off) "
                        r"(?:interpreting|translating|translation)\b|"
                        r"通訳\s*(?:やめて|終了|止めて|ストップ|オフ)|(?:停止|结束|关闭)(?:口译|翻译)|别翻译了", re.I)


def parse_command(cfg, text):
    """내 언어(한국어·영어·일본어·중국어) 말 → ("off",None) / ("on", 코드 또는 "auto") / None."""
    t = str(text or "").strip()
    if not t:
        return None
    if _OFF.search(t) or (home_of(cfg) != KO and _OFF_EXTRA.search(t)):
        return ("off", None)
    m = _ON.search(t) or (home_of(cfg) != KO and _ON_EXTRA.search(t))
    if not m:
        return None
    low = t.lower()
    before, after = None, None  # '통역' 바로 앞에 가까운 언어 이름(“태국 가서 영어 통역해 줘” → 영어)
    for code, info in langs(cfg).items():
        for w in info.get("부르는말") or []:
            w = str(w).lower()
            for mm in re.finditer(re.escape(w), low):
                end = mm.end()
                if end <= m.start():
                    if before is None or end > before[0] or (end == before[0] and len(w) > before[2]):
                        before = (end, code, len(w))
                elif after is None or mm.start() < after[0]:
                    after = (mm.start(), code, len(w))
    pick = before or after
    return ("on", pick[1] if pick else "auto")


# ---------------------------------------------------------------- 글자로 언어 짐작(목소리 고르기)
_SCRIPTS = [
    ("th", re.compile(r"[฀-๿]")),
    ("el", re.compile(r"[Ͱ-Ͽἀ-῿]")),
    ("ja", re.compile(r"[぀-ヿ]")),
    ("ru", re.compile(r"[Ѐ-ӿ]")),
    ("ko", re.compile(r"[가-힣]")),
    ("zh", re.compile(r"[一-鿿]")),
]


def script_lang(text, hint=None):
    """번역문 글자 → 언어. 라틴 글자는 hint(번역 목표 언어)를 믿음."""
    t = str(text or "")
    for code, rx in _SCRIPTS:
        if len(rx.findall(t)) >= 2:
            return "ja" if code == "zh" and hint == "ja" else code   # 한자만 있는 일본어 문장
    if re.search(r"[A-Za-zÀ-ɏḀ-ỿ]", t):
        return hint if hint and hint not in ("ko", "th", "el", "ja", "zh", "ru") else "en"
    return hint


# ---------------------------------------------------------------- 언어 감지(귀 서버)
def detect(pipe, x, cands):
    """whisper 첫 토큰(언어 토큰) 확률을 '후보 언어 안에서만' 나눠 봄 → {코드: 확률}. 목록에 없는 언어로 새지 않음."""
    import torch

    model = pipe.model
    fe = pipe.feature_extractor(x, sampling_rate=16000, return_tensors="pt")
    feats = fe.input_features.to(model.device, dtype=model.dtype)
    gc = model.generation_config
    l2i = getattr(gc, "lang_to_id", None) or {}
    ids, keep = [], []
    for c in cands:
        i = l2i.get(f"<|{c}|>")
        if i is not None:
            ids.append(i)
            keep.append(c)
    if not ids:
        return {KO: 1.0}
    with torch.inference_mode():
        enc = model.get_encoder()(feats)
        sot = torch.tensor([[gc.decoder_start_token_id]], device=model.device)
        logits = model(encoder_outputs=enc, decoder_input_ids=sot).logits[0, -1].float()
    p = torch.softmax(logits[ids], dim=-1).cpu().tolist()
    return dict(zip(keep, p))


def choose(probs, last=None, need=0.9, fixed=None, audio_sec=None, short=1.5, unsure=0.7, home=KO):
    """감지 확률 → (고른 언어, 신뢰도). home = 내 언어(기본 ko — 0.1.17 그대로).
    - 내 언어가 가장 높으면 내 언어. 고정 언어(fixed)면 내 언어 아니면 그 언어.
    - 자동: 가장 높은 외국어. 직전 상대 언어(last)와 다른 언어로 바꾸려면 신뢰도 need 이상 — 아니면 직전 언어.
      짧은 말(short 초 미만)은 감지가 못 미더워 직전 언어 그대로. 긴 말은 직전 언어 가능성이 0.03 미만이면 고집하지 않음.
    - 헷갈림(제3 언어가 unsure 미만)인데 내 언어 가능성이 직전 언어보다 크면 내 언어 — 작은 귀(CPU)가 짧은 내 말을
      다른 언어로 잘못 듣는 일(설치 시험 2026-11-18)."""
    home = home_of({"언어": home})
    if not probs:
        return home, 0.0
    top = max(probs, key=probs.get)
    if top == home:
        return home, probs[home]
    if fixed:
        return fixed, probs.get(fixed, 0.0)
    if last and last != top and probs[top] < unsure and probs.get(home, 0.0) >= max(0.03, probs.get(last, 0.0)):
        return home, probs.get(home, 0.0)
    if last and last != top and probs[top] < need:
        if (audio_sec is not None and audio_sec < short) or probs.get(last, 0.0) >= 0.03:
            return last, probs.get(last, 0.0)
    return top, probs[top]
