package kr.kimbiseo.phone.gh

/**
 * 김비서 GH 안전 규칙 — 두뇌(모델) 판단에 맡기지 않고 코드가 먼저 막는다(순수 규칙 · 단위 시험).
 *  · 결제·주문·구매·송금 글자가 있는 단추는 누르기 전에 멈춘다(한국어·영어·일본어·중국어).
 *  · 비밀번호·카드번호 칸에는 글자를 넣지 않는다.
 *  · 대상 앱(쿠팡·쿠팡이츠·배민·크롬·네이버) 밖에서는 아무것도 하지 않는다.
 *  · 걸음은 최대 15.
 */
object GhSafety {
    const val MAX_STEPS = 15

    /** 대상 앱 — 패키지 → 검색 키(SearchRules). */
    val TARGET_APPS: Map<String, String> = mapOf(
        "com.coupang.mobile" to "coupang",
        "com.coupang.eats" to "coupangeats",
        "com.sampleapp" to "baemin",
        "com.android.chrome" to "chrome",
        "com.nhn.android.search" to "naver",
    )

    /** 배달 앱 — 장바구니 담기까지만. */
    private val DELIVERY = setOf("com.coupang.eats", "com.sampleapp")

    /** 누르면 안 되는 단추 글자. 정규화(소문자·공백 제거) 뒤 부분 문자열로 본다. */
    private val BLOCK_TAP: List<String> = listOf(
        // 한국어
        "결제", "주문", "구매", "바로구매", "송금", "이체",
        // English
        "pay", "payment", "checkout", "placeorder", "ordernow", "buynow", "confirmorder",
        // 日本語
        "支払", "決済", "注文", "購入", "レジ",
        // 中文
        "支付", "付款", "结算", "结账", "下单", "购买", "立即购买", "去结算", "购物车结算",
    )

    /** 글자를 넣으면 안 되는 칸(비밀번호·카드번호). */
    private val SECRET_FIELD: List<String> = listOf(
        "password", "passwd", "비밀번호", "카드번호", "cardnumber", "cvv", "cvc",
        "パスワード", "カード番号", "密码", "密碼", "卡号", "卡號", "安全码",
    )

    fun norm(s: String): String = s.lowercase().replace(Regex("\\s+"), "")

    /** 누르면 안 되는 글자면 그 글자를 돌려준다(없으면 null). */
    fun blockedTap(label: String): String? {
        val n = norm(label)
        if (n.isEmpty()) return null
        return BLOCK_TAP.firstOrNull { n.contains(it) }
    }

    /** 비밀번호·카드번호 칸인가. */
    fun secretField(label: String): Boolean {
        val n = norm(label)
        if (n.isEmpty()) return false
        return SECRET_FIELD.any { n.contains(it) }
    }

    fun targetOk(pkg: String): Boolean = pkg in TARGET_APPS

    fun delivery(pkg: String): Boolean = pkg in DELIVERY

    /** 걸음 번호가 상한 안인가(1..15). */
    fun stepAllowed(step: Int): Boolean = step in 1..MAX_STEPS

    /** 화면 글자에 '장바구니에 담았다'는 확인이 있는가. */
    private val SUCCESS: List<String> = listOf(
        "장바구니에담았", "장바구니에추가", "장바구니로이동", "장바구니보기", "장바구니확인",
        "addedtocart", "addedtoyourcart", "gotocart", "viewcart",
        "カートに追加しました", "カートに入れました", "カートを見る",
        "已加入购物车", "已添加至购物车", "已添加到购物车", "去购物车", "查看购物车",
    )

    fun cartAdded(labels: List<String>): Boolean {
        val all = labels.joinToString(" ") { norm(it) }
        if (all.isEmpty()) return false
        return SUCCESS.any { all.contains(it) }
    }
}