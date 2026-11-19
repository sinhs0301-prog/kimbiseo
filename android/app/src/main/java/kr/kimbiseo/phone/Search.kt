package kr.kimbiseo.phone

import java.net.URLEncoder

/**
 * 쇼핑·배달·검색 앱의 '검색 화면' 열기 — 안드로이드 API 를 안 쓰는 순수 규칙(단위 시험).
 *  공개·공식 주소만 쓴다. 장바구니·주문·결제는 하지 않는다(검색 화면까지만).
 *
 *  바로 검색 화면을 여는 앱
 *   - 쿠팡: https://www.coupang.com/np/search?q= — 공식 App Link(assetlinks handle_all_urls 확인)
 *   - 유튜브: https://www.youtube.com/results?search_query= — 공식 App Link(assetlinks handle_all_urls 확인)
 *   - 네이버: naversearchapp://inappbrowser?url=... — 네이버 공개 앱 스킴 문서(인앱 브라우저로 검색 결과)
 *            검색 결과 주소는 https://m.search.naver.com/search.naver?query=
 *   - 크롬: https://www.google.com/search?q= 를 크롬 패키지로 연다.
 *  공개 검색 딥링크가 없는 앱(배민·쿠팡이츠): 검색어를 복사하고 앱을 연 뒤 '검색창에 붙여 넣어 주세요' 안내.
 *  앱이 없으면 웹 검색 — 쿠팡은 쿠팡 웹, 네이버는 네이버 웹, 유튜브는 유튜브 웹, 나머지는 구글 검색.
 */
object SearchRules {
    const val COUPANG = "coupang"
    const val EATS = "coupangeats"
    const val BAEMIN = "baemin"
    const val CHROME = "chrome"
    const val NAVER = "naver"
    const val YOUTUBE = "youtube"

    const val PKG_COUPANG = "com.coupang.mobile"
    const val PKG_EATS = "com.coupang.eats"
    const val PKG_BAEMIN = "com.sampleapp"
    const val PKG_CHROME = "com.android.chrome"
    const val PKG_NAVER = "com.nhn.android.search"
    const val PKG_YOUTUBE = "com.google.android.youtube"

    val ORDER = listOf(COUPANG, EATS, BAEMIN, CHROME, NAVER, YOUTUBE)

    /** 말로 부른 앱 이름 → 키. 띄어쓰기·대소문자·영문/한글·일본어·중국어를 같은 키로 본다. */
    private val ALIAS: List<Pair<String, String>> = listOf(
        "쿠팡" to COUPANG, "coupang" to COUPANG, "クーパン" to COUPANG, "クパン" to COUPANG, "酷澎" to COUPANG,
        "쿠팡이츠" to EATS, "coupangeats" to EATS, "クーパンイーツ" to EATS, "クパンイーツ" to EATS,
        "酷澎eats" to EATS, "酷澎外送" to EATS,
        "배민" to BAEMIN, "배달의민족" to BAEMIN, "baemin" to BAEMIN, "ペミン" to BAEMIN,
        "ペダルの民族" to BAEMIN, "外卖民族" to BAEMIN, "百民" to BAEMIN, "白民" to BAEMIN,
        "크롬" to CHROME, "chrome" to CHROME, "クローム" to CHROME, "谷歌浏览器" to CHROME, "浏览器" to CHROME,
        "네이버" to NAVER, "naver" to NAVER, "ネイバー" to NAVER, "纳ver" to NAVER, "奈弗" to NAVER,
        "유튜브" to YOUTUBE, "유투브" to YOUTUBE, "youtube" to YOUTUBE, "ユーチューブ" to YOUTUBE,
        "油管" to YOUTUBE, "优兔" to YOUTUBE,
    )

    data class Hit(val key: String, val start: Int, val end: Int)
    data class Ask(val app: String, val query: String)

    fun enc(s: String): String = URLEncoder.encode(s, "UTF-8").replace("+", "%20")

    fun pkg(key: String): String? = when (key) {
        COUPANG -> PKG_COUPANG
        EATS -> PKG_EATS
        BAEMIN -> PKG_BAEMIN
        CHROME -> PKG_CHROME
        NAVER -> PKG_NAVER
        YOUTUBE -> PKG_YOUTUBE
        else -> null
    }

    /** 앱 이름만 따로 준 경우("쿠팡 앱"·"Coupang") → 키. 아니면 null. */
    fun canonical(name: String): String? {
        val n = NameRules.normName(name).removeSuffix("앱").removeSuffix("어플").removeSuffix("アプリ").removeSuffix("应用")
        if (n.isEmpty()) return null
        return ALIAS.firstOrNull { it.first == n }?.second
    }

    /** 앱에서 바로 여는 검색 주소(공개·공식). 없으면 null(복사 + 앱 열기 안내). */
    fun direct(key: String, q: String): String? = when (key) {
        COUPANG -> "https://www.coupang.com/np/search?q=${enc(q)}"
        YOUTUBE -> "https://www.youtube.com/results?search_query=${enc(q)}"
        // 네이버 공개 스킴: 인앱 브라우저로 검색 결과 주소를 연다.
        NAVER -> {
            val page = "https://m.search.naver.com/search.naver?query=" + enc(q)
            "naversearchapp://inappbrowser?url=" + enc(page) + "&target=new&version=6"
        }
        else -> null
    }

    /** 크롬 검색 주소(구글). */
    fun chrome(q: String): String = "https://www.google.com/search?q=${enc(q)}"

    /** 앱이 없을 때 여는 웹 검색 주소. */
    fun web(key: String, q: String): String = when (key) {
        COUPANG -> "https://www.coupang.com/np/search?q=${enc(q)}"
        NAVER -> "https://search.naver.com/search.naver?query=${enc(q)}"
        YOUTUBE -> "https://www.youtube.com/results?search_query=${enc(q)}"
        EATS -> "https://www.google.com/search?q=" + enc("Coupang Eats $q")
        BAEMIN -> "https://www.google.com/search?q=" + enc("Baemin $q")
        CHROME -> chrome(q)
        else -> "https://www.google.com/search?q=" + enc(q)   // 알 수 없는 앱도 구글에서 찾는다
    }

    /** 쇼핑·배달 앱 — 답에 '담기·주문은 직접'을 붙인다. */
    fun shopping(key: String): Boolean = key == COUPANG || key == EATS || key == BAEMIN

    /** 공개 검색 딥링크가 없어 '검색어 복사 + 앱 열기'로 안내하는 앱. */
    fun copyOnly(key: String): Boolean = key == EATS || key == BAEMIN

    /** 문장 안에서 쇼핑·배달·검색 앱 이름을 찾는다(띄어쓰기 무시). 없으면 null. */
    fun find(text: String): Hit? {
        val norm = StringBuilder()
        val at = ArrayList<Int>()
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            if (Character.isLetterOrDigit(cp)) { norm.appendCodePoint(Character.toLowerCase(cp)); at.add(i) }
            i += Character.charCount(cp)
        }
        val n = norm.toString()
        var best: Hit? = null
        for ((alias, key) in ALIAS) {
            if (alias.length > n.length) continue
            var from = 0
            while (from <= n.length - alias.length) {
                val k = n.indexOf(alias, from)
                if (k < 0) break
                // "네이버 지도"는 지도 앱이지 검색 앱이 아니다(길안내 규칙이 받게 둔다).
                val rest = n.substring(k + alias.length)
                if ((alias == "네이버" && (rest.startsWith("지도") || rest.startsWith("맵"))) ||
                    (alias == "naver" && rest.startsWith("map"))) { from = k + 1; continue }
                val lastAt = at[k + alias.length - 1]
                val h = Hit(key, at[k], lastAt + Character.charCount(text.codePointAt(lastAt)))
                val b = best
                if (b == null || h.start < b.start || (h.start == b.start && h.end - h.start > b.end - b.start)) best = h
                from = k + 1
            }
        }
        return best
    }

    /** 앱 이름과 붙은 조사·연결말을 함께 떼어 낸 나머지 문장. */
    fun strip(text: String, h: Hit): String {
        var s = h.start
        var e = h.end
        val after = listOf("어플로", "앱으로", "어플", "앱", "アプリ", "应用", "으로", "로", "에서", "で", "に", "へ", "の", "은", "는", "이", "가", "을", "를")
        val tail = text.substring(e)
        var cut = tail.takeWhile { it.isWhitespace() }.length
        for (t in after) if (tail.startsWith(t, cut)) { cut += t.length; break }
        e += cut
        val before = listOf("with", "via", "using", "through", "on", "in", "at", "from", "用", "使用", "在")
        val head = text.substring(0, s)
        val h2 = head.trimEnd()
        var cut2 = 0
        for (t in before) {
            if (!h2.endsWith(t, ignoreCase = true)) continue
            val at = h2.length - t.length
            if (at == 0 || h2[at - 1].isWhitespace()) { cut2 = head.length - at; break }
        }
        s -= cut2
        return text.removeRange(s, e).replace(Regex("\\s{2,}"), " ").trim()
    }

    /** 검색어에 섞인 앱 이름을 뺀다("쿠팡 생수" → "생수"). */
    fun queryWithout(q: String): String {
        val h = find(q) ?: return q
        return strip(q, h).ifBlank { q }
    }

    private val KO_TAIL = Regex("\\s*(?:을|를|좀|의)?\\s*(?:검색(?:해|해\\s*줘|해줘|해\\s*주세요|해주세요)?|찾아(?:\\s*줘|\\s*주세요|줘|주세요)?|찾아서|시켜(?:\\s*줘|\\s*주세요|줘|주세요)?|주문(?:해|해\\s*줘|해줘|해\\s*주세요|해주세요)?|골라(?:\\s*줘|\\s*주세요|줘|주세요)?|보여(?:\\s*줘|\\s*주세요|줘|주세요)?|알려(?:\\s*줘|\\s*주세요|줘|주세요)?|주세요|줘|줘요)\\s*$")
    private val JA_TAIL = Regex("\\s*(?:を)?(?:探して|検索して|注文して|頼んで|買って|見せて|教えて)(?:ください)?\\s*$")
    private val ZH_TAIL = Regex("\\s*(?:一下|看看|吧|好吗|谢谢)\\s*$")
    private val EN_TAIL = Regex("\\s*(?:please|for me)\\s*$", RegexOption.IGNORE_CASE)

    private fun once(r: Regex, s: String): String = s.replace(r, "").trim()

    fun cleanQuery(s0: String): String {
        var s = s0.trim().trim('"', '\'', '“', '”', '‘', '’', '「', '」').trim()
        for (n in 0..2) {
            val t = once(EN_TAIL, once(ZH_TAIL, once(JA_TAIL, once(KO_TAIL, s))))
            if (t == s) break
            s = t
        }
        s = s.replace(Regex("^(?:the|a|an)\\s+", RegexOption.IGNORE_CASE), "").trim()
        s = s.trimStart('을', '를', '의', '좀', 'を').trim()
        s = s.trimEnd('을', '를', '의', '좀', 'を').trim()
        return s.take(60)
    }

    /**
     * 사용자가 쓴 말에서 검색 부탁을 직접 알아본다(모델 PHONE 줄이 없을 때 안전망).
     *  "쿠팡에서 생수 찾아줘" · "배민에서 치킨 시켜줘" · "쿠팡이츠 떡볶이" · "크롬에서 날씨 검색" ·
     *  "Search for water on Coupang" · "ペミンでチキンを注文して" · "在酷澎搜矿泉水"
     *  애매하면 null.
     */
    fun parse(text: String): Ask? {
        val raw = text.trim().replace(Regex("[.!?。！？]+$"), "").trim()
        if (raw.isEmpty() || raw.length > 120) return null

        // 한국어: "<앱>에서 <검색어> <부탁>"
        Regex("^(.{1,20}?)\\s*(?:에서|에)\\s+(.+)$").find(raw)?.let { m ->
            canonical(m.groupValues[1])?.let { app ->
                val q = cleanQuery(m.groupValues[2])
                if (q.isNotEmpty()) return Ask(app, q)
            }
        }
        // 일본어: "<앱>で <검색어>を<부탁>"
        Regex("^(.{1,20}?)で\\s*(.+)$").find(raw)?.let { m ->
            canonical(m.groupValues[1])?.let { app ->
                val q = cleanQuery(m.groupValues[2])
                if (q.isNotEmpty()) return Ask(app, q)
            }
        }
        // 중국어: "在<앱>搜<검색어>" · "用<앱>搜索<검색어>"
        Regex("^(?:在|用)\\s*(.{1,20}?)(?:上|里|中)?\\s*(?:搜索|搜|查找|找|买|点|叫)\\s*(.+)$").find(raw)?.let { m ->
            canonical(m.groupValues[1])?.let { app ->
                val q = cleanQuery(m.groupValues[2])
                if (q.isNotEmpty()) return Ask(app, q)
            }
        }
        // 영어: "search (for) <검색어> on <앱>"
        Regex("^(?:search(?:\\s+for)?|find|look\\s+for|order|buy|get)\\s+(.+?)\\s+(?:on|in|at|from)\\s+(?:the\\s+)?(.+)$", RegexOption.IGNORE_CASE).find(raw)?.let { m ->
            canonical(m.groupValues[2])?.let { app ->
                val q = cleanQuery(m.groupValues[1])
                if (q.isNotEmpty()) return Ask(app, q)
            }
        }
        // 영어: "search <앱> for <검색어>"
        Regex("^(?:search(?:\\s+for)?|find|look\\s+for)\\s+(?:the\\s+)?(.{1,20}?)\\s+for\\s+(.+)$", RegexOption.IGNORE_CASE).find(raw)?.let { m ->
            canonical(m.groupValues[1])?.let { app ->
                val q = cleanQuery(m.groupValues[2])
                if (q.isNotEmpty()) return Ask(app, q)
            }
        }
        // 영어: "on <앱> search <검색어>"
        Regex("^(?:on|in)\\s+(?:the\\s+)?(.{1,20}?)[,:]?\\s+(?:search(?:\\s+for)?|find|look\\s+for|order)\\s+(.+)$", RegexOption.IGNORE_CASE).find(raw)?.let { m ->
            canonical(m.groupValues[1])?.let { app ->
                val q = cleanQuery(m.groupValues[2])
                if (q.isNotEmpty()) return Ask(app, q)
            }
        }
        // 영어: "<앱> search <검색어>" ("Chrome search weather", "Coupang search water")
        Regex("^(.{1,20}?)\\s+(?:search(?:\\s+for)?|find|look\\s+for)\\s+(.+)$", RegexOption.IGNORE_CASE).find(raw)?.let { m ->
            canonical(m.groupValues[1])?.let { app ->
                val q = cleanQuery(m.groupValues[2])
                if (q.isNotEmpty()) return Ask(app, q)
            }
        }

        // 앱 이름이 문장 안에 있고 남은 말이 짧은 검색어뿐: "쿠팡이츠 떡볶이", "ペミンでチキン", "酷澎Eats 辣炒年糕"
        val hit = find(raw) ?: return null
        val rest = strip(raw, hit)
        val q = cleanQuery(rest)
        if (q.isNotEmpty() && q.length <= 30 && !q.endsWith("다") && !q.endsWith("요") && !q.endsWith("까")) return Ask(hit.key, q)
        return null
    }
}