# 두뇌 글 거르기 — 소리로 읽기 전에 막아야 할 것들(운영판과 같은 규칙).
#   HanziFilter : 한국어 답 중간에 섞인 중국어 낱말을 한국어로 바꾸거나 지움(흘러나오는 조각 단위)
#   ThinkFilter : <think …</think 생각 블록(꺾쇠가 깨진 꼴 포함)을 통째로 버림
#   lang_request: '영어로 말해 줘' 같은 요청이면 잠깐 외국어 모드(영어 문장을 막지 않음)
#   mostly_english: 한글 없는 긴 영어 문장(생각 글이 새어 나온 것) 판정 — 외국어 모드가 아니면 말하지 않음
#   tts_clean   : 목소리에 넣기 직전 정리(하품·마크다운·그림문자·한자 → voice/text_norm 읽기 변환)
#   app_clean   : 앱 언어가 ko 가 아닐 때(en·ja·zh) — 한자·가나·숫자를 그대로 두고 기호만 정리(0.1.18)
import re
import time

from .voice_link import text_norm

_HANJA_RUN = re.compile("[\u2e80-\u2fdf\u31c0-\u31ef\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003ffff\u3040-\u30ff\u31f0-\u31ff]+")
_CJK_PUNCT = {"，": ", ", "。": ". ", "、": ", ", "！": "! ", "？": "? ", "：": ": ", "；": ", ", "（": " (", "）": ") ",
              "「": " '", "」": "' ", "『": " '", "』": "' ", "《": " '", "》": "' ", "～": "~"}
# 자주 섞여 나오는 중국어 낱말 → 자연스러운 한국어(긴 것부터 맞춤). 모르는 한자는 지운다.
HANZI_KO = {
    "随时随地": "언제 어디서든", "随时": "언제든", "随便": "편하게", "立即": "바로", "马上": "바로", "立刻": "바로",
    "相关信息": "관련 정보", "相关": "관련", "信息": "정보", "资料": "자료", "内容": "내용", "结果": "결과", "情况": "상황",
    "问题": "문제", "方法": "방법", "原因": "원인", "时间": "시간", "地址": "주소", "电话": "전화", "营业时间": "영업시간",
    "价格": "가격", "评价": "평가", "评论": "후기", "推荐": "추천", "店铺": "매장", "门店": "매장", "商店": "가게",
    "网页": "웹페이지", "网站": "웹사이트", "浏览器": "브라우저", "搜索": "검색", "打开": "열기", "页面": "페이지", "链接": "링크",
    "电脑": "컴퓨터", "屏幕": "화면", "窗口": "창", "文件": "파일", "设置": "설정", "程序": "프로그램", "手机": "휴대폰",
    "确认": "확인", "检查": "확인", "需要": "필요", "帮助": "도움", "帮忙": "도움", "注意": "주의", "完成": "완료",
    "准备": "준비", "继续": "계속", "开始": "시작", "结束": "끝", "成功": "성공", "失败": "실패", "错误": "오류",
    "谢谢": "감사합니다", "抱歉": "죄송합니다", "对不起": "죄송합니다", "当然": "물론", "已经": "이미", "正在": "지금",
    "现在": "지금", "今天": "오늘", "明天": "내일", "昨天": "어제", "以后": "나중에", "之前": "전에", "最近": "최근",
    "一起": "함께", "其他": "다른", "可能": "아마", "应该": "아마", "比较": "비교적", "非常": "아주", "特别": "특히",
    "首先": "먼저", "然后": "그다음", "最后": "마지막으로", "所以": "그래서", "但是": "하지만", "因为": "왜냐하면",
    "如果": "만약", "比如": "예를 들어", "而且": "게다가", "一般": "보통", "一直": "계속", "一定": "꼭", "经常": "자주",
    "方便": "편하게", "简单": "간단히", "详细": "자세히", "具体": "구체적으로", "主要": "주로", "重要": "중요한",
    "大概": "대략", "左右": "정도", "多少": "얼마", "怎么样": "어때요", "什么": "무엇", "为什么": "왜", "怎么": "어떻게",
    "隨時": "언제든", "網頁": "웹페이지", "網站": "웹사이트", "資料": "자료", "資訊": "정보", "相關": "관련", "問題": "문제",
    "時間": "시간", "電腦": "컴퓨터", "檢查": "확인", "確認": "확인", "謝謝": "감사합니다", "內容": "내용", "結果": "결과",
    "情況": "상황", "價格": "가격", "評價": "평가", "推薦": "추천", "搜尋": "검색", "瀏覽器": "브라우저", "頁面": "페이지",
    "设备": "기기", "設備": "기기", "功能": "기능", "系统": "시스템", "系統": "시스템", "服务": "서비스", "服務": "서비스",
    "好评": "호평", "好評": "호평", "差评": "혹평", "口碑": "평판", "味道": "맛", "好吃": "맛있는", "环境": "분위기", "環境": "분위기",
    "性价比": "가성비", "人气": "인기", "人氣": "인기", "热门": "인기", "招牌": "대표", "菜单": "메뉴", "餐厅": "식당", "咖啡": "커피",
    "客户": "손님", "顾客": "손님", "老板": "사장님", "员工": "직원", "质量": "품질", "品质": "품질", "速度": "속도", "性能": "성능",
    "显卡": "그래픽카드", "主板": "메인보드", "内存": "메모리", "硬盘": "저장장치", "电源": "파워", "散热": "쿨링", "组装": "조립",
    "维修": "수리", "售后": "에이에스", "保修": "보증", "库存": "재고", "订单": "주문", "销售": "판매", "购买": "구매",
    "没问题": "문제없어요", "好的": "네", "可以": "가능", "不错": "괜찮", "一下": " 좀", "一些": "몇몇", "很多": "많은",
}
_HANZI_KEYS = sorted(HANZI_KO, key=len, reverse=True)
_HANJA_TAIL = re.compile(_HANJA_RUN.pattern + "$")


def hanzi_fix(run):
    """한자·가나 덩어리 하나 → 한국어 낱말(아는 것) 또는 빈 글."""
    out, i = [], 0
    while i < len(run):
        for k in _HANZI_KEYS:
            if run.startswith(k, i):
                out.append(HANZI_KO[k])
                i += len(k)
                break
        else:
            i += 1  # 모르는 글자는 버림
    return " ".join(x.strip() for x in out if x.strip())


def strip_hanzi(text):
    """글 전체에서 한자·가나를 한국어로 바꾸거나 지우고, 중국식 문장부호를 바꾼다."""
    if not text:
        return text
    for a, b in _CJK_PUNCT.items():
        if a in text:
            text = text.replace(a, b)
    if not _HANJA_RUN.search(text):
        return text
    def rep(m):
        w = hanzi_fix(m.group(0))
        before = text[m.start() - 1] if m.start() > 0 else " "
        return (" " if w and not before.isspace() else "") + w  # 앞말에 붙지 않게 띄우고, 뒤 조사는 붙임
    t = _HANJA_RUN.sub(rep, text)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return re.sub(r" +([,.!?])", r"\1", t)


class HanziFilter:
    """흘러나오는(스트리밍) 두뇌 글에서 한자 덩어리를 막는다. 덩어리가 조각 끝에 걸리면 다음 조각까지 잡아 두었다가
    한꺼번에 바꾼다('随'+'时' → '언제든'). feed(조각) → 내보낼 글, flush() → 남은 글."""

    def __init__(self):
        self.hold = ""
        self.last = " "  # 이미 내보낸 글의 마지막 글자(앞말과 띄어쓰기 판단용)
        self.last_raw = ""
        self.hits = 0

    def _clean(self, s):
        if not s:
            return s
        if _HANJA_RUN.search(s) or any(p in s for p in _CJK_PUNCT):
            if _HANJA_RUN.search(s):
                self.hits += 1
                self.last_raw = s
            s = strip_hanzi(self.last + s)[1:]
        if s:
            self.last = s[-1]
        return s

    def feed(self, text):
        s = self.hold + (text or "")
        self.hold = ""
        m = _HANJA_TAIL.search(s)
        if m:  # 끝이 한자면 다음 조각에 이어질 수 있어 잡아 둠
            self.hold = s[m.start():]
            s = s[:m.start()]
        return self._clean(s)

    def flush(self):
        s, self.hold = self.hold, ""
        return self._clean(s)



# ---------------------------------------------------------------- 생각 글 거르기(두뇌가 '<think The user is…'를 본문에 섞어 영어로 말하는 것 막기)
_THINK_OPEN = re.compile(r"<\s*think\b\s*>?", re.I)
_THINK_CLOSE = re.compile(r"<\s*/\s*think\b\s*>?", re.I)
_TAG_PREFIX = re.compile(r"<\s*/?\s*t?h?i?n?k?\s*$", re.I)  # 조각 끝에 걸린 '<', '<th', '</thi' 같은 태그 앞부분


class ThinkFilter:
    """흘러나오는 두뇌 글에서 <think …</think 블록(꺾쇠가 깨진 '<think The user…'·'</think' 포함, 대소문자 무관,
    조각으로 쪼개져 와도)을 통째로 버린다. 닫는 태그가 끝내 안 오면 그 응답의 태그 뒤는 말하지 않는다.
    feed(조각) → 내보낼 글, flush() → 남은 글(생각 안이면 버림). dropped = 버린 글자 수(로그용)."""

    def __init__(self):
        self.buf = ""
        self.inside = False
        self.dropped = 0
        self.unclosed = False
        self.eat_gt = False  # 태그가 '>' 없이 조각 끝에서 끝났으면 다음 조각 맨 앞 '>' 를 버림

    def _tag_end(self, m):
        if not m.group(0).rstrip().endswith(">") and m.end() >= len(self.buf):
            self.eat_gt = True

    def _run(self, final=False):
        out = []
        if self.eat_gt and self.buf:
            stripped = self.buf.lstrip()
            if stripped.startswith(">"):
                self.dropped += len(self.buf) - len(stripped) + 1
                self.buf = stripped[1:]
            if self.buf.strip():
                self.eat_gt = False
        while self.buf:
            if not self.inside:
                m = _THINK_OPEN.search(self.buf)
                c = _THINK_CLOSE.search(self.buf)
                if c and (not m or c.start() < m.start()):  # 여는 태그 없이 닫는 태그만 → 태그만 지움
                    out.append(self.buf[:c.start()])
                    self.dropped += c.end() - c.start()
                    self._tag_end(c)
                    self.buf = self.buf[c.end():]
                    continue
                if m:
                    out.append(self.buf[:m.start()])
                    self.dropped += m.end() - m.start()
                    self.buf = self.buf[m.end():]
                    self.inside = True
                    continue
                if not final:
                    t = _TAG_PREFIX.search(self.buf)
                    if t and t.start() >= len(self.buf) - 9:  # 끝의 '<thi' 는 다음 조각까지 잡아 둠
                        out.append(self.buf[:t.start()])
                        self.buf = self.buf[t.start():]
                        break
                out.append(self.buf)
                self.buf = ""
            else:
                c = _THINK_CLOSE.search(self.buf)
                if c:
                    self.dropped += c.end()
                    self._tag_end(c)
                    self.buf = self.buf[c.end():]
                    self.inside = False
                    continue
                if final:
                    self.dropped += len(self.buf)
                    self.unclosed = True
                    self.buf = ""
                    break
                t = _TAG_PREFIX.search(self.buf)
                keep = self.buf[t.start():] if t and t.start() >= len(self.buf) - 9 else ""
                self.dropped += len(self.buf) - len(keep)
                self.buf = keep
                break
        return "".join(out)

    def feed(self, text):
        self.buf += text or ""
        return self._run(False)

    def flush(self):
        return self._run(True)


_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]+")
_LANG_ON = re.compile(r"(영어|영문|잉글리시|english|일본어|중국어|스페인어|프랑스어|독일어)\s*(로|으로)?\s*(말|대답|답|얘기|이야기|대화|해|읽|번역|말해|speak|talk|reply)", re.I)
_LANG_OFF = re.compile(r"(한국어|한글|우리말|korean)\s*(로|으로)?\s*(말|대답|답|해|돌아|바꿔)|영어\s*(그만|말고|하지\s*마)", re.I)


def lang_request(state, text):
    """사용자 말로 언어 모드를 켜고 끔. 켜지면 10턴 또는 30분 동안 영어 문장을 그대로 읽는다."""
    t = str(text or "")
    if _LANG_OFF.search(t):
        state.lang_mode, state.lang_until, state.lang_turns = None, 0.0, 0
        return "off"
    if _LANG_ON.search(t) or re.search(r"(speak|talk|answer|reply)\s+(to\s+me\s+)?(in\s+)?english|english\s+please", t, re.I):
        state.lang_mode, state.lang_until, state.lang_turns = "외국어", time.time() + 1800, 10
        return "on"
    if state.lang_mode:
        state.lang_turns -= 1
        if state.lang_turns <= 0 or time.time() > state.lang_until:
            state.lang_mode = None
            return "expired"
    return None


def lang_active(state):
    return bool(getattr(state, "lang_mode", None)) and time.time() <= getattr(state, "lang_until", 0)


def mostly_english(text):
    """한글 없이 영어 낱말로 된 긴 문장(생각 글이 새어 나온 것) — 제품·모델 이름 같은 짧은 말은 아님."""
    t = str(text or "")
    if re.search(r"[가-힣]", t):
        return False
    words = _LATIN_WORD.findall(t)
    if len(words) < 6:
        return False
    lower = sum(1 for w in words if w[0].islower())
    letters = sum(len(w) for w in words)
    body = len(re.sub(r"\s", "", t)) or 1
    return lower >= len(words) * 0.4 and letters / body >= 0.6


_MD = re.compile(r"[*#`_>|]+|https?://\S+")


def tts_clean(text):
    t = text_norm.drop_yawn(text or "")
    t = _MD.sub(" ", t)
    t = re.sub(r"[🀀-🫿☀-➿]", "", t)   # 그림문자
    t = strip_hanzi(t)
    t = re.sub(r"\s*[×✕]\s*", " 곱하기 ", t)
    if not mostly_english(t):
        t = text_norm.normalize(t)
    return re.sub(r"\s{2,}", " ", t).strip()


def app_clean(text):
    """앱 언어가 한국어가 아닐 때(en·ja·zh): 한자·가나를 지우지 않고 숫자를 한국어로 읽지 않는다.
    기호(마크다운·그림문자)와 하품만 정리 — 목소리 서버가 그 언어 그대로 읽는다(0.1.18)."""
    t = _MD.sub(" ", text_norm.drop_yawn(text or ""))
    t = re.sub(r"[🀀-🫿☀-➿]", "", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def foreign_clean(text):
    """외국어 모드의 영어 문장: 숫자를 한국어로 바꾸지 않고 기호만 정리(한국어 앱 — 한자는 지움)."""
    return strip_hanzi(app_clean(text)).strip()
