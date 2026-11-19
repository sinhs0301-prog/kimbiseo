package kr.kimbiseo.phone.gh
import kr.kimbiseo.phone.SearchRules

/**
 * "쿠팡에서 삼다수 2L 장바구니 담아줘" → 앱 키 + 검색어 (순수 규칙 · 단위 시험).
 *  0.1.3 의 SearchRules(앱 이름 찾기·떼기·검색어 다듬기)를 그대로 쓰고, 여기서는 '장바구니에 담아' 의도와
 *  담기 말(장바구니·담아·cart·カート·购物车 …)을 걷어 낸다. 담기 의도가 없으면 null → 평소 대화.
 */
object GhPhrase {
    data class Ask(val app: String, val query: String)

    private val CART_WORDS: List<String> = listOf(
        "장바구니에", "장바구니", "카트에", "카트", "담아줘", "담아", "담기", "넣어줘", "넣어", "추가해줘", "추가해",
        "addtocart", "addtobasket", "cart", "basket",
        "カートに入れて", "カートに追加して", "カート", "に入れて", "追加して",
        "加入购物车", "加入購物車", "购物车", "購物車", "放进购物车", "放入购物车", "加入",
    )

    /** 담기 의도가 있는 말인가(앱 이름이 없어도). */
    fun wantsCart(text: String): Boolean {
        val n = GhSafety.norm(text)
        return CART_WORDS.any { n.contains(it) }
    }

    fun parse(text: String): Ask? {
        val raw = text.trim().replace(Regex("[.!?。！？]+$"), "").trim()
        if (raw.isEmpty() || raw.length > 120) return null
        if (!wantsCart(raw)) return null

        // 앱 이름 찾기 — 못 찾으면 null(평소 대화/검색).
        val hit = SearchRules.find(raw) ?: return null
        val app = hit.key
        // 대상 앱(쿠팡·쿠팡이츠·배민·크롬·네이버)만 — 유튜브 같은 앱은 평소 대화/검색 그대로.
        if (SearchRules.pkg(app) !in GhSafety.TARGET_APPS) return null
        var body = SearchRules.strip(raw, hit)

        // 앱 이름이 남아 있으면 걷어 낸다(문장 안에 두 번 나온 경우).
        SearchRules.find(body)?.let { body = SearchRules.strip(body, it) }

        // 담기 말을 걷어 낸 검색어(띄어쓰기가 달라도 같은 말로 본다).
        var q = SearchRules.cleanQuery(body)
        for (w in CART_WORDS) {
            val pat = w.map { Regex.escape(it.toString()) }.joinToString("\\s*")
            q = q.replace(Regex(pat, RegexOption.IGNORE_CASE), " ")
        }
        q = q.replace(Regex("\\s+"), " ").trim()
        // "add" 같은 영어 동작말·"to"·"를" 꼬리 정리
        q = q.replace(Regex("^(?:please\\s+)?(?:add|put|place)\\s+", RegexOption.IGNORE_CASE), "")
            .replace(Regex("\\s+(?:to|into|in)(?:\\s+the)?\\s*$", RegexOption.IGNORE_CASE), "")
            .trim()
        q = SearchRules.cleanQuery(q)
        q = q.trimStart('把', '将', '을', '를', '의', '좀', 'を', ' ').trimEnd('을', '를', '의', '좀', 'を', 'に', ' ').trim()

        if (q.isEmpty() || q.length > 60) return null
        // 아직 부탁말이 남아 있으면 검색어로 보기 어렵다.
        if (q.endsWith("다") || q.endsWith("요") || q.endsWith("까") || q.endsWith("줘")) return null
        return Ask(app, q)
    }
}