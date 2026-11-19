package kr.kimbiseo.phone

import java.net.URLEncoder

/**
 * 폰 동작 규칙(안드로이드 API 를 안 쓰는 순수 규칙 — JVM 단위 시험 RulesTest).
 *  길안내 주소, 연락처 이름 너그럽게 찾기(운영 폰 앱과 같은 방식: 이모지·호칭·띄어쓰기·받아쓰기 모음 혼동), 앱 이름 찾기.
 */
object NavRules {
    data class Target(val app: String, val pkg: String, val uri: String, val note: String = "")

    const val KAKAOMAP = "net.daum.android.map"
    const val NAVER = "com.nhn.android.nmap"
    const val TMAP = "com.skt.tmap.ku"
    const val GOOGLE = "com.google.android.apps.maps"
    const val KAKAONAVI = "com.locnall.KimGiSa"

    fun enc(s: String): String = URLEncoder.encode(s, "UTF-8").replace("+", "%20")

    val ORDER = listOf("kakaomap", "naver", "tmap", "google", "kakaonavi")
    private val WANT = mapOf("kakaomap" to KAKAOMAP, "naver" to NAVER, "tmap" to TMAP, "google" to GOOGLE, "kakaonavi" to KAKAONAVI)

    /** 한국 안 길안내로 볼지: 목적지에 한글이 있거나, 폰이 잡은 망·유심 나라가 한국.
     *  구글지도는 한국 안 자동차 길찾기를 안 해서(google.navigation 이 "길을 찾을 수 없음"으로 끝남) 이때는 검색 화면으로 연다. */
    fun inKorea(dest: String, countries: List<String?>): Boolean =
        dest.any { it in '가'..'힣' || it in 'ㄱ'..'ㆎ' } || countries.any { it.equals("kr", ignoreCase = true) }

    /** 앱 하나의 길안내 주소(좌표 없이 이름으로 찾음 — 공개판은 지도 열쇠가 없음) */
    fun target(a: String, dest: String, appName: String, korea: Boolean): Target? {
        val d = enc(dest)
        return when (a) {
            "kakaomap" -> Target("카카오맵", KAKAOMAP, "kakaomap://search?q=$d", "검색 결과에서 '길찾기'를 눌러 주세요")
            "naver" -> Target("네이버지도", NAVER, "nmap://search?query=$d&appname=" + enc(appName), "검색 결과에서 '길찾기'를 눌러 주세요")
            "tmap" -> Target("티맵", TMAP, "tmap://search?name=$d", "검색 결과에서 목적지를 골라 주세요")
            "google" -> if (korea) Target("구글지도", GOOGLE, "geo:0,0?q=$d", "검색 결과에서 '경로'를 눌러 주세요")
                        else Target("구글지도", GOOGLE, "google.navigation:q=$d")
            "kakaonavi" -> Target("카카오내비", KAKAONAVI, "", "목적지 이름을 복사해 뒀어요 — 검색창에 붙여 넣어 주세요")
            else -> null
        }
    }

    fun web(dest: String) = Target("웹 카카오맵", "", "https://map.kakao.com/?q=${enc(dest)}", "")

    /** 열어 볼 차례: 고른 앱(있으면) → 깔린 순서 카카오맵 → 네이버지도 → 티맵 → 구글지도 → 카카오내비 → 웹 카카오맵.
     *  앞의 앱이 안 열리면(사용 중지·주소를 못 받음) 다음 것을 연다. installed 는 '깔려 있고 켜져 있음'. */
    fun candidates(dest: String, want: String, installed: (String) -> Boolean, appName: String, korea: Boolean = inKorea(dest, emptyList())): List<Target> {
        val order = if (want in ORDER) listOf(want) + ORDER.filter { it != want } else ORDER
        return order.filter { WANT[it]?.let(installed) == true }.mapNotNull { target(it, dest, appName, korea) } + web(dest)
    }

    fun pick(dest: String, want: String, installed: (String) -> Boolean, appName: String, korea: Boolean = inKorea(dest, emptyList())): Target =
        candidates(dest, want, installed, appName, korea).first()

    /** PC 쪽이 보낸 앱 이름(kakaomap…)을 사람이 읽는 이름으로 */
    fun label(want: String): String = target(want, "", "", true)?.app ?: ""
}

/**
 * 지도·내비 앱 이름 알아보기 — 말로 부른 이름을 다섯 가지 키로 바꾼다(순수 규칙 — 단위 시험).
 *  띄어쓰기·대소문자·영문/한글·일본어·중국어 이름을 같은 키로 본다.
 *  키 = kakaomap | naver | tmap | google | kakaonavi (PHONE 줄·PC 가 보내는 값과 같음).
 */
object NavAppRules {
    private val ALIAS: List<Pair<String, String>> = listOf(
        // 카카오내비
        "카카오내비" to "kakaonavi", "카카오내비게이션" to "kakaonavi", "카내비" to "kakaonavi",
        "kakaonavi" to "kakaonavi", "kakaonavigation" to "kakaonavi",
        "カカオナビ" to "kakaonavi", "カカオナビゲーション" to "kakaonavi",
        "卡卡奥导航" to "kakaonavi", "卡卡奥导航仪" to "kakaonavi",
        // 카카오맵
        "카카오맵" to "kakaomap", "다음지도" to "kakaomap", "다음맵" to "kakaomap",
        "kakaomap" to "kakaomap", "daummap" to "kakaomap",
        "カカオマップ" to "kakaomap", "カカオ地図" to "kakaomap", "ダウム地図" to "kakaomap",
        "卡卡奥地图" to "kakaomap", "daum地图" to "kakaomap",
        // 네이버지도
        "네이버지도" to "naver", "네이버맵" to "naver",
        "navermap" to "naver", "naver地图" to "naver", "naver地図" to "naver",
        "ネイバーマップ" to "naver", "ネイバー地図" to "naver",
        // 티맵
        "티맵" to "tmap", "t맵" to "tmap", "tmap" to "tmap", "t地图" to "tmap",
        "ティマップ" to "tmap", "tマップ" to "tmap",
        // 구글지도
        "구글지도" to "google", "구글맵" to "google", "googlemaps" to "google", "googlemap" to "google",
        "グーグルマップ" to "google", "グーグル地図" to "google",
        "谷歌地图" to "google",
    )
    private val PKG = mapOf(
        "kakaomap" to NavRules.KAKAOMAP, "naver" to NavRules.NAVER, "tmap" to NavRules.TMAP,
        "google" to NavRules.GOOGLE, "kakaonavi" to NavRules.KAKAONAVI,
    )

    data class Hit(val key: String, val start: Int, val end: Int)

    /** 앱 이름만 따로 준 경우("네이버 지도"·"카카오내비 앱") → 키. 아니면 null. */
    fun canonical(name: String): String? {
        val n = NameRules.normName(name).removeSuffix("앱").removeSuffix("어플")
        if (n.isEmpty()) return null
        return ALIAS.firstOrNull { it.first == n }?.second
    }

    fun pkg(key: String): String? = PKG[key]

    fun display(key: String): String = when (key) {
        "kakaomap" -> "카카오맵"; "naver" -> "네이버지도"; "tmap" -> "티맵"
        "google" -> "구글지도"; "kakaonavi" -> "카카오내비"; else -> key
    }

    /** 문장 안에서 지도·내비 앱 이름을 찾는다(띄어쓰기 무시). 없으면 null. */
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
                val lastAt = at[k + alias.length - 1]
                val h = Hit(key, at[k], lastAt + Character.charCount(text.codePointAt(lastAt)))
                val b = best
                if (b == null || h.start < b.start || (h.start == b.start && h.end - h.start > b.end - b.start)) best = h
                from = k + 1
            }
        }
        return best
    }

    /** 앱 이름과 붙은 조사·연결말을 함께 떼어 낸 나머지 문장("카카오내비로 천안역" → "천안역"). */
    fun strip(text: String, h: Hit): String {
        var s = h.start
        var e = h.end
        val after = listOf("어플로", "앱으로", "어플", "앱", "으로", "로", "에서", "で", "に", "へ", "の")
        val tail = text.substring(e)
        var cut = tail.takeWhile { it.isWhitespace() }.length
        for (t in after) if (tail.startsWith(t, cut)) { cut += t.length; break }
        e += cut
        val before = listOf("with", "via", "using", "through", "on", "用", "使用")
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

    /** 목적지 글에 섞인 앱 이름을 뺀다("강남역 카카오내비" → "강남역"). */
    fun destWithout(dest: String): String {
        val h = find(dest) ?: return dest
        return strip(dest, h).ifBlank { dest }
    }
}

object NameRules {
    const val STRONG = 75
    const val NEAR = 30
    private val TITLES = listOf("사장님", "대표님", "선생님", "고객님", "부장님", "과장님", "차장님", "실장님", "팀장님", "이사님", "회장님", "원장님",
        "교수님", "소장님", "주임님", "대리님", "기사님", "사모님", "형님", "누님", "사장", "대표", "선생", "손님", "쌤", "님", "씨", "형", "누나",
        "언니", "오빠", "이모", "삼촌", "선배")
    private val CHO_FOLD = intArrayOf(0, 0, 2, 3, 3, 5, 6, 7, 7, 9, 9, 11, 12, 12, 14, 15, 16, 17, 18)
    private val JUNG_FOLD = intArrayOf(0, 1, 0, 1, 4, 1, 4, 1, 8, 9, 10, 10, 8, 13, 14, 10, 16, 13, 18, 20, 20)

    fun digits(s: String?): String {
        var d = (s ?: "").filter { it.isDigit() || it == '+' }
        if (d.startsWith("+82")) d = "0" + d.removePrefix("+82").trimStart('0')
        return d.filter { it.isDigit() }
    }

    fun cleanName(q: String?): String {
        var t = (q ?: "").trim()
        t = t.replace(Regex("(한테|에게|께)$"), "").trim()
        return t.take(30)
    }

    fun normName(s: String?): String {
        val t = s ?: ""; val sb = StringBuilder(); var i = 0
        while (i < t.length) {
            val cp = t.codePointAt(i)
            if (Character.isLetterOrDigit(cp)) sb.appendCodePoint(Character.toLowerCase(cp))
            i += Character.charCount(cp)
        }
        return sb.toString()
    }

    fun stripTitles(n: String): String {
        var t = n
        while (true) {
            val hit = TITLES.firstOrNull { t.endsWith(it) && t.length > it.length } ?: return t
            t = t.dropLast(hit.length)
        }
    }

    fun variants(s: String?): Set<String> {
        val raw = s ?: ""
        val a = normName(raw)
        val b = normName(raw.replace(Regex("\\([^)]*\\)|\\[[^\\]]*\\]"), ""))
        return linkedSetOf(a, b, stripTitles(a), stripTitles(b)).filter { it.isNotEmpty() }.toSet()
    }

    private fun isSyl(c: Char) = c in '가'..'힣'

    fun foldSyl(s: String): String {
        val sb = StringBuilder()
        for (c in s) {
            if (!isSyl(c)) { sb.append(c); continue }
            val i = c - '가'
            sb.append('가' + (CHO_FOLD[i / 588] * 588 + JUNG_FOLD[(i % 588) / 28] * 28 + i % 28))
        }
        return sb.toString()
    }

    fun jamo(s: String): String {
        val sb = StringBuilder()
        for (c in foldSyl(s)) {
            if (!isSyl(c)) { sb.append(c); continue }
            val i = c - '가'
            sb.append('ᄀ' + i / 588).append('ᅡ' + (i % 588) / 28)
            if (i % 28 != 0) sb.append('ᆧ' + i % 28)
        }
        return sb.toString()
    }

    fun lev(a: String, b: String): Int {
        if (a.isEmpty()) return b.length
        if (b.isEmpty()) return a.length
        var prev = IntArray(b.length + 1) { it }; var cur = IntArray(b.length + 1)
        for (i in 1..a.length) {
            cur[0] = i
            for (j in 1..b.length) cur[j] = minOf(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + if (a[i - 1] == b[j - 1]) 0 else 1)
            val t = prev; prev = cur; cur = t
        }
        return prev[b.length]
    }

    private fun pairScore(q: String, d: String): Int {
        if (q.isEmpty() || d.isEmpty()) return 0
        if (q == d) return 100
        val fq = foldSyl(q); val fd = foldSyl(d)
        if (fq == fd) return 95
        if (q.length >= 2) {
            if (d.startsWith(q)) return 88
            if (fd.startsWith(fq)) return 85
            if (d.contains(q)) return 80
            if (fd.contains(fq)) return 78
        }
        if (d.length >= 2 && d.length * 2 >= q.length) {
            if (q.contains(d)) return 76
            if (fq.contains(fd)) return 75
        }
        val jq = jamo(q); val jd = jamo(d)
        var sim = 1.0 - lev(jq, jd).toDouble() / maxOf(jq.length, jd.length)
        if (q.length >= 3 && jd.length > jq.length) sim = maxOf(sim, 0.85 * (1.0 - lev(jq, jd.take(jq.length)).toDouble() / jq.length))
        return if (sim < 0.4) 0 else minOf(72, (sim * 80).toInt())
    }

    fun nameScore(query: String, display: String?): Int {
        var best = 0
        for (q in variants(query)) for (d in variants(display)) best = maxOf(best, pairScore(q, d))
        return best
    }

    data class Ranked(val list: List<Triple<String, String, Int>>, val near: List<Triple<String, String, Int>>)

    fun rank(query: String, contacts: List<Pair<String, String>>): Ranked {
        val all = ArrayList<Triple<String, String, Int>>()
        for ((name, num) in contacts) {
            if (digits(num).isEmpty()) continue
            val sc = nameScore(query, name)
            if (sc >= NEAR) all.add(Triple(name, num, sc))
        }
        val seen = HashSet<String>()
        val uniq = all.sortedByDescending { it.third }.filter { seen.add(digits(it.second)) }
        var strong = uniq.filter { it.third >= STRONG }.take(6)
        if (strong.size >= 2 && strong[0].third >= 95 && strong[1].third <= strong[0].third - 10) strong = strong.take(1)
        val used = strong.map { digits(it.second) }.toSet()
        val near = uniq.filter { it.third < STRONG && digits(it.second) !in used }.take(3)
        return Ranked(strong, near)
    }
}

object AppRules {
    /** 말로 부르는 이름 → 앱 서랍 이름 후보(한국어 폰에서도 영어 이름인 앱들) */
    private val ALIAS = mapOf(
        "유튜브" to listOf("youtube"), "유투브" to listOf("youtube"), "유튜브뮤직" to listOf("youtubemusic"),
        "카톡" to listOf("카카오톡", "kakaotalk"), "카카오톡" to listOf("kakaotalk"), "크롬" to listOf("chrome"),
        "지메일" to listOf("gmail"), "구글지도" to listOf("지도", "maps", "googlemaps", "구글맵"), "구글맵" to listOf("구글지도", "maps", "googlemaps"),
        // 지도·내비 — 서랍 이름이 영문이거나 띄어쓰기가 달라도 찾게
        "카카오맵" to listOf("kakaomap", "다음지도", "daummap"), "다음지도" to listOf("카카오맵", "kakaomap", "daummap"),
        "kakaomap" to listOf("카카오맵", "다음지도"), "daummap" to listOf("다음지도", "카카오맵"),
        "네이버지도" to listOf("navermap", "네이버맵"), "네이버맵" to listOf("네이버지도", "navermap"),
        "navermap" to listOf("네이버지도", "네이버맵"),
        "카카오내비" to listOf("kakaonavi", "카카오내비게이션", "카내비"), "카내비" to listOf("카카오내비", "kakaonavi"),
        "kakaonavi" to listOf("카카오내비", "카내비"),
        "티맵" to listOf("tmap", "t맵"), "t맵" to listOf("티맵", "tmap"), "tmap" to listOf("티맵", "t맵"),
        "googlemaps" to listOf("구글지도", "구글맵"), "googlemap" to listOf("구글지도", "구글맵"),
        "플레이스토어" to listOf("playstore", "play스토어"),
        "넷플릭스" to listOf("netflix"), "인스타" to listOf("instagram", "인스타그램"), "인스타그램" to listOf("instagram"),
        "페이스북" to listOf("facebook"), "왓츠앱" to listOf("whatsapp"), "텔레그램" to listOf("telegram"), "스포티파이" to listOf("spotify"),
        "설정" to listOf("settings"), "카메라" to listOf("camera"), "계산기" to listOf("calculator"), "시계" to listOf("clock"),
        "달력" to listOf("캘린더", "calendar"), "캘린더" to listOf("calendar"), "갤러리" to listOf("사진", "photos", "gallery"),
        "사진" to listOf("갤러리", "photos", "gallery"), "메시지" to listOf("문자", "messages"), "문자" to listOf("메시지", "messages"),
        "전화" to listOf("phone", "전화"), "연락처" to listOf("contacts"), "파일" to listOf("내파일", "files"), "녹음기" to listOf("음성녹음", "recorder"))

    /** 앱 이름(말) → (앱 서랍 이름, 패키지) 목록에서 가장 맞는 것의 위치(없으면 -1) */
    fun best(want: String, labels: List<String>): Int {
        val w = NameRules.normName(want).removeSuffix("앱").removeSuffix("어플")
        if (w.isEmpty()) return -1
        val keys = listOf(w) + (ALIAS[w] ?: emptyList()).map { NameRules.normName(it) }
        var bi = -1; var bs = 0
        for ((i, l) in labels.withIndex()) {
            val n = NameRules.normName(l)
            if (n.isEmpty()) continue
            var s = 0
            for ((k, key) in keys.withIndex()) {
                val base = when { n == key -> 100; n.startsWith(key) -> 85; key.length >= 2 && n.contains(key) -> 75; else -> 0 }
                s = maxOf(s, if (k == 0) base else base - 2)
            }
            if (s > bs || (s == bs && s > 0 && n.length < NameRules.normName(labels[bi]).length)) { bs = s; bi = i }
        }
        return if (bs >= 75) bi else -1
    }
}
