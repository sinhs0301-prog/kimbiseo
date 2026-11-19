package kr.kimbiseo.phone

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** 폰 단독 모드의 순수 규칙 — 기기 확인·모델 크기 글·PHONE 줄 해석·지시문. */
class SoloRulesTest {
    @Test fun device_ok_on_six_gb_arm64() {
        val d = SoloModel.check(listOf("arm64-v8a"), 5_800_000_000L, 35, 4L * 1024 * 1024 * 1024)
        assertTrue(d.ok)
        assertTrue(d.reasons.isEmpty())
    }

    @Test fun device_ok_on_four_gb() {
        // 4GB 폰은 totalMem 이 3.5~3.9GB 로 보고된다 — 이제 받아 준다(2026-11-19 문턱 3.3GB).
        val d = SoloModel.check(listOf("arm64-v8a"), 3_800_000_000L, 34)
        assertTrue(d.ok)
        assertTrue(d.reasons.isEmpty())
    }

    @Test fun device_rejects_three_gb() {
        val d = SoloModel.check(listOf("arm64-v8a"), 2_800_000_000L, 34)
        assertFalse(d.ok)
        assertEquals(listOf("ram"), d.reasons)
    }

    @Test fun tight_ram_only_for_four_gb_class() {
        assertTrue(SoloModel.tight(3_500_000_000L))   // 4GB 폰
        assertTrue(SoloModel.tight(4_013_932_000L))   // 4GB AVD 보고값
        assertFalse(SoloModel.tight(5_500_000_000L))  // 6GB 폰
        assertFalse(SoloModel.tight(2_800_000_000L))  // 3GB 폰(대상 아님)
    }

    @Test fun memory_failure_is_classified() {
        assertTrue(SoloLoadFail.isNoMem(OutOfMemoryError("Failed to allocate a 2 byte allocation")))
        assertTrue(SoloLoadFail.isNoMem("failed to allocate memory"))
        assertTrue(SoloLoadFail.isNoMem(SoloLoadFail.NO_MEM))
        assertFalse(SoloLoadFail.isNoMem("Model file not found"))
        assertFalse(SoloLoadFail.isNoMem("busy"))
    }

    @Test fun device_rejects_32_bit() {
        val d = SoloModel.check(listOf("armeabi-v7a"), 8_000_000_000L, 34)
        assertFalse(d.ok)
        assertEquals(listOf("abi"), d.reasons)
    }

    @Test fun device_rejects_old_android() {
        val d = SoloModel.check(listOf("x86_64"), 8_000_000_000L, 25)
        assertEquals(listOf("android"), d.reasons)
    }

    @Test fun device_rejects_short_storage() {
        val d = SoloModel.check(listOf("arm64-v8a"), 8_000_000_000L, 34, SoloModel.SIZE)
        assertEquals(listOf("storage"), d.reasons)
    }

    @Test fun device_accepts_emulator_x86_64() {
        assertTrue(SoloModel.check(listOf("x86_64"), 6L * 1024 * 1024 * 1024, 35).ok)
    }

    @Test fun size_is_official_bytes() {
        assertEquals(2_588_147_712L, SoloModel.SIZE)
        assertEquals(64, SoloModel.SHA256.length)
        assertTrue(SoloModel.URL.endsWith("/gemma-4-E2B-it.litertlm"))
    }

    @Test fun human_readable_size() {
        assertEquals("2.4 GB", SoloModel.human(2_588_147_712L))
        assertEquals("300 MB", SoloModel.human(300L * 1024 * 1024))
    }

    @Test fun action_navigate_is_removed_from_text() {
        val p = SoloAction.parse("강남역으로 안내할게요.\nPHONE {\"do\":\"navigate\",\"destination\":\"강남역\"}")
        assertEquals("강남역으로 안내할게요.", p.text)
        assertNotNull(p.action)
        assertEquals("navigate", p.action?.optString("do"))
        assertEquals("강남역", p.action?.optString("destination"))
    }

    @Test fun action_dial_sms_open_app() {
        val d = SoloAction.parse("전화 화면을 열게요.\nPHONE {\"do\":\"dial\",\"contact\":\"엄마\"}")
        assertEquals("dial", d.action?.optString("do"))
        val s = SoloAction.parse("PHONE {\"do\":\"sms\",\"contact\":\"엄마\",\"message\":\"도착했어요\"}")
        assertEquals("sms", s.action?.optString("do"))
        assertEquals("", s.text)
        val a = SoloAction.parse("유튜브를 열게요.\n`PHONE {\"do\":\"open_app\",\"app\":\"유튜브\"}`")
        assertEquals("open_app", a.action?.optString("do"))
        assertEquals("유튜브를 열게요.", a.text)
    }

    @Test fun action_none_and_invalid() {
        assertNull(SoloAction.parse("오늘은 맑아요.").action)
        assertNull(SoloAction.parse("PHONE {\"do\":\"fly\"}").action)
        assertNull(SoloAction.parse("PHONE {\"do\":\"navigate\"}").action)
        assertNull(SoloAction.parse("PHONE not-json").action)
    }

    @Test fun action_uses_last_phone_line() {
        val p = SoloAction.parse("먼저 할게요.\nPHONE {\"do\":\"open_app\",\"app\":\"지도\"}\n그다음 갈게요.\nPHONE {\"do\":\"navigate\",\"destination\":\"서울역\"}")
        assertEquals("navigate", p.action?.optString("do"))
        assertFalse(p.text.contains("PHONE"))
    }

    @Test fun prompts_are_multilingual_and_ask_for_phone_line() {
        for (code in Lang.CODES) {
            val s = SoloPrompt.system(code)
            assertTrue(code, s.contains("PHONE"))
            assertTrue(code, s.contains("\"do\":\"navigate\""))
            assertTrue(code, s.contains("\"do\":\"search\""))
            assertTrue(code, s.contains("coupang"))
            assertTrue(code, s.contains("youtube"))
        }
        assertTrue(SoloPrompt.system("ko").contains("김비서"))
        assertTrue(SoloPrompt.system("en").contains("Kim Biseo"))
        assertTrue(SoloPrompt.system("ja").contains("キム秘書"))
        assertTrue(SoloPrompt.system("zh").contains("金秘书"))
    }

    @Test fun user_command_fallback_korean() {
        val open = SoloAction.fromUser("설정 앱을 열어 줘.")
        assertEquals("open_app", open?.optString("do"))
        assertEquals("설정", open?.optString("app"))
        val nav = SoloAction.fromUser("강남역 가는 길 안내해 줘.")
        assertEquals("navigate", nav?.optString("do"))
        assertEquals("강남역", nav?.optString("destination"))
        val dial = SoloAction.fromUser("엄마한테 전화해 줘.")
        assertEquals("dial", dial?.optString("do"))
        assertEquals("엄마", dial?.optString("contact"))
        val sms = SoloAction.fromUser("엄마한테 문자해 줘.")
        assertEquals("sms", sms?.optString("do"))
        assertEquals("엄마", sms?.optString("contact"))
    }

    @Test fun user_command_fallback_other_languages() {
        assertEquals("open_app", SoloAction.fromUser("Open Settings")?.optString("do"))
        assertEquals("navigate", SoloAction.fromUser("Navigate to Seoul Station")?.optString("do"))
        assertEquals("dial", SoloAction.fromUser("Call Mom")?.optString("do"))
        assertEquals("open_app", SoloAction.fromUser("設定アプリを開いて")?.optString("do"))
        assertEquals("navigate", SoloAction.fromUser("東京駅へ行きたい")?.optString("do"))
        assertEquals("open_app", SoloAction.fromUser("打开设置")?.optString("do"))
        assertEquals("navigate", SoloAction.fromUser("导航到首尔站")?.optString("do"))
        assertNull(SoloAction.fromUser("오늘 날씨 어때?"))
    }

    /** 실제로 말할 법한 문장 — 앱과 목적지가 정확히 나뉘는지(한국어). */
    @Test fun user_nav_with_app_korean() {
        val cases = listOf(
            "카카오내비로 천안역 안내해줘" to ("kakaonavi" to "천안역"),
            "강남역 카카오내비로 안내해줘" to ("kakaonavi" to "강남역"),
            "네이버지도로 강남역 가자" to ("naver" to "강남역"),
            "네이버 지도로 서울역까지 안내해줘" to ("naver" to "서울역"),
            "카카오맵으로 부산역 가는 길" to ("kakaomap" to "부산역"),
            "티맵으로 집 가는 길" to ("tmap" to "집"),
            "T맵으로 회사 가자" to ("tmap" to "회사"),
            "구글지도로 대전역 안내해줘" to ("google" to "대전역"),
            "카카오내비로 강남역에서 안내해줘" to ("kakaonavi" to "강남역"),
            "다음지도로 서면역 가자" to ("kakaomap" to "서면역"),
        )
        for ((said, want) in cases) {
            val a = SoloAction.fromUser(said)
            assertEquals(said, "navigate", a?.optString("do"))
            assertEquals(said, want.first, a?.optString("app"))
            assertEquals(said, want.second, a?.optString("destination"))
        }
    }

    @Test fun user_open_app_map_names() {
        val cases = listOf("네이버 지도 열어줘", "카카오내비 켜줘", "카카오맵 앱 열어줘", "티맵 실행해줘")
        for (said in cases) {
            val a = SoloAction.fromUser(said)
            assertEquals(said, "open_app", a?.optString("do"))
            assertTrue(said, a?.optString("app")?.isNotBlank() == true)
        }
        assertEquals("네이버 지도", SoloAction.fromUser("네이버 지도 열어줘")?.optString("app"))
    }

    /** English·日本語·中文 — 앱 이름이 영문·현지 이름이어도 app 칸으로. */
    @Test fun user_nav_with_app_other_languages() {
        val cases = listOf(
            "Take me to Seoul Station with KakaoNavi" to ("kakaonavi" to "Seoul Station"),
            "Navigate to Busan Station using Naver Map" to ("naver" to "Busan Station"),
            "カカオナビで天安駅まで案内して" to ("kakaonavi" to "天安駅"),
            "ティマップで東京駅へ行きたい" to ("tmap" to "東京駅"),
            "用卡卡奥导航去首尔站" to ("kakaonavi" to "首尔站"),
            "用T地图去釜山站" to ("tmap" to "釜山站"),
        )
        for ((said, want) in cases) {
            val a = SoloAction.fromUser(said)
            assertEquals(said, "navigate", a?.optString("do"))
            assertEquals(said, want.first, a?.optString("app"))
            assertEquals(said, want.second, a?.optString("destination"))
        }
        assertEquals("open_app", SoloAction.fromUser("Open Google Maps")?.optString("do"))
        assertEquals("open_app", SoloAction.fromUser("Open TMAP")?.optString("do"))
        assertEquals("open_app", SoloAction.fromUser("ネイバーマップを開いて")?.optString("do"))
        assertEquals("open_app", SoloAction.fromUser("打开谷歌地图")?.optString("do"))
    }

    /** 모델 PHONE 줄에 app 이 없으면 사용자 말로 채우고, 목적지에 섞인 앱 이름은 뺀다. */
    @Test fun enrich_fills_app_from_user_words() {
        val user = "강남역 카카오내비로 안내해줘"
        val p = SoloAction.parse("안내할게요.\nPHONE {\"do\":\"navigate\",\"destination\":\"강남역 카카오내비\"}")
        val a = SoloAction.enrich(p.action, user)
        assertEquals("navigate", a?.optString("do"))
        assertEquals("kakaonavi", a?.optString("app"))
        assertEquals("강남역", a?.optString("destination"))
        // 모델이 이미 app 을 넣었으면 그대로(사용자 말로 덮지 않음)
        val p2 = SoloAction.parse("PHONE {\"do\":\"navigate\",\"destination\":\"강남역\",\"app\":\"naver\"}")
        assertEquals("naver", SoloAction.enrich(p2.action, user)?.optString("app"))
        // 길안내가 아니면 손대지 않음
        val p3 = SoloAction.parse("PHONE {\"do\":\"dial\",\"contact\":\"엄마\"}")
        assertEquals("dial", SoloAction.enrich(p3.action, user)?.optString("do"))
        assertNull(SoloAction.enrich(null, user))
    }

    @Test fun nav_app_names_are_recognized() {
        assertEquals("naver", NavAppRules.canonical("네이버 지도"))
        assertEquals("naver", NavAppRules.canonical("NAVER Map"))
        assertEquals("kakaonavi", NavAppRules.canonical("카카오내비 앱"))
        assertEquals("tmap", NavAppRules.canonical("T맵"))
        assertEquals("google", NavAppRules.canonical("Google Maps"))
        assertEquals("kakaomap", NavAppRules.canonical("다음지도"))
        assertNull(NavAppRules.canonical("설정"))
        assertEquals(NavRules.NAVER, NavAppRules.pkg("naver"))
        assertEquals(NavRules.KAKAONAVI, NavAppRules.pkg("kakaonavi"))
        assertEquals("카카오내비", NavAppRules.display("kakaonavi"))
        // 목적지에서 앱 이름·조사 떼기
        assertEquals("강남역", NavAppRules.destWithout("강남역 카카오내비"))
        assertEquals("천안역", NavAppRules.destWithout("카카오내비로 천안역"))
        assertEquals("Seoul Station", NavAppRules.destWithout("Seoul Station with KakaoNavi"))
    }

    @Test fun action_search_is_parsed_and_needs_query() {
        val p = SoloAction.parse("쿠팡에서 찾아볼게요.\nPHONE {\"do\":\"search\",\"app\":\"coupang\",\"query\":\"생수\"}")
        assertEquals("search", p.action?.optString("do"))
        assertEquals("coupang", p.action?.optString("app"))
        assertEquals("생수", p.action?.optString("query"))
        assertEquals("쿠팡에서 찾아볼게요.", p.text)
        assertNull(SoloAction.parse("PHONE {\"do\":\"search\",\"app\":\"coupang\"}").action)
        // app 이 비어도 검색어가 있으면 받는다(폰이 사용자 말·웹 검색으로 채움).
        assertNotNull(SoloAction.parse("PHONE {\"do\":\"search\",\"query\":\"생수\"}").action)
    }

    /** 실제로 말할 법한 검색 문장 — 한국어. */
    @Test fun search_user_korean() {
        val cases = listOf(
            "쿠팡에서 생수 찾아줘" to ("coupang" to "생수"),
            "배민에서 치킨 시켜줘" to ("baemin" to "치킨"),
            "쿠팡이츠 떡볶이" to ("coupangeats" to "떡볶이"),
            "크롬에서 날씨 검색" to ("chrome" to "날씨"),
            "유튜브에서 고양이 영상 찾아줘" to ("youtube" to "고양이 영상"),
            "네이버에서 서울 날씨 검색해줘" to ("naver" to "서울 날씨"),
            "쿠팡에서 노트북 찾아 줘" to ("coupang" to "노트북"),
            "배민에서 짜장면 주문해줘" to ("baemin" to "짜장면"),
            "유튜브에서 강아지 영상 검색해줘" to ("youtube" to "강아지 영상"),
            "생수 쿠팡에서 찾아줘" to ("coupang" to "생수"),
        )
        for ((said, want) in cases) {
            val a = SoloAction.fromUser(said)
            assertEquals(said, "search", a?.optString("do"))
            assertEquals(said, want.first, a?.optString("app"))
            assertEquals(said, want.second, a?.optString("query"))
        }
    }

    /** English·日本語·中文 검색 문장. */
    @Test fun search_user_other_languages() {
        val cases = listOf(
            "Search for water on Coupang" to ("coupang" to "water"),
            "Find chicken on Baemin" to ("baemin" to "chicken"),
            "Order chicken on Baemin" to ("baemin" to "chicken"),
            "Search the weather in Chrome" to ("chrome" to "weather"),
            "Look for a movie on YouTube" to ("youtube" to "movie"),
            "Buy milk on Coupang Eats" to ("coupangeats" to "milk"),
            "Search for shoes on Coupang" to ("coupang" to "shoes"),
            "クーパンで水を探して" to ("coupang" to "水"),
            "ペミンでチキンを注文して" to ("baemin" to "チキン"),
            "クロームで天気を検索して" to ("chrome" to "天気"),
            "クーパンイーツのトッポッキ" to ("coupangeats" to "トッポッキ"),
            "在酷澎搜矿泉水" to ("coupang" to "矿泉水"),
            "用Chrome搜索天气" to ("chrome" to "天气"),
            "在배민点치킨" to ("baemin" to "치킨"),
            "酷澎Eats 辣炒年糕" to ("coupangeats" to "辣炒年糕"),
        )
        for ((said, want) in cases) {
            val a = SoloAction.fromUser(said)
            assertEquals(said, "search", a?.optString("do"))
            assertEquals(said, want.first, a?.optString("app"))
            assertEquals(said, want.second, a?.optString("query"))
        }
    }

    @Test fun search_does_not_steal_navigation_or_open() {
        assertNull(SoloAction.fromUser("카카오내비로 천안역 안내해줘")?.takeIf { it.optString("do") == "search" })
        assertEquals("open_app", SoloAction.fromUser("쿠팡 열어줘")?.optString("do"))
        assertEquals("open_app", SoloAction.fromUser("유튜브 열어줘")?.optString("do"))
        assertEquals("navigate", SoloAction.fromUser("네이버지도로 강남역 가자")?.optString("do"))
        assertNull(SoloAction.fromUser("오늘 날씨 어때?"))
    }

    @Test fun search_urls_are_public_and_encoded() {
        assertEquals("https://www.coupang.com/np/search?q=%EC%83%9D%EC%88%98", SearchRules.direct(SearchRules.COUPANG, "생수"))
        assertEquals("https://www.youtube.com/results?search_query=%EA%B0%95%EC%95%84%EC%A7%80", SearchRules.direct(SearchRules.YOUTUBE, "강아지"))
        val naver = SearchRules.direct(SearchRules.NAVER, "날씨")
        assertNotNull(naver)
        assertTrue(naver!!.startsWith("naversearchapp://inappbrowser?url="))
        assertTrue(naver.contains("version=6"))
        assertTrue(SearchRules.web(SearchRules.NAVER, "날씨").startsWith("https://search.naver.com/search.naver?query="))
        assertTrue(SearchRules.web(SearchRules.BAEMIN, "치킨").startsWith("https://www.google.com/search?q=Baemin%20"))
        assertTrue(SearchRules.web(SearchRules.EATS, "떡볶이").startsWith("https://www.google.com/search?q=Coupang%20Eats%20"))
        assertEquals("https://www.google.com/search?q=%EB%82%A0%EC%94%A8", SearchRules.chrome("날씨"))
        assertNull(SearchRules.direct(SearchRules.BAEMIN, "치킨"))
        assertNull(SearchRules.direct(SearchRules.EATS, "떡볶이"))
    }

    @Test fun search_packages_and_kinds() {
        assertEquals("com.coupang.mobile", SearchRules.pkg(SearchRules.COUPANG))
        assertEquals("com.coupang.eats", SearchRules.pkg(SearchRules.EATS))
        assertEquals("com.sampleapp", SearchRules.pkg(SearchRules.BAEMIN))
        assertEquals("com.android.chrome", SearchRules.pkg(SearchRules.CHROME))
        assertEquals("com.nhn.android.search", SearchRules.pkg(SearchRules.NAVER))
        assertEquals("com.google.android.youtube", SearchRules.pkg(SearchRules.YOUTUBE))
        assertTrue(SearchRules.shopping(SearchRules.COUPANG))
        assertTrue(SearchRules.shopping(SearchRules.EATS))
        assertTrue(SearchRules.shopping(SearchRules.BAEMIN))
        assertFalse(SearchRules.shopping(SearchRules.CHROME))
        assertTrue(SearchRules.copyOnly(SearchRules.EATS))
        assertTrue(SearchRules.copyOnly(SearchRules.BAEMIN))
        assertFalse(SearchRules.copyOnly(SearchRules.COUPANG))
    }

    @Test fun search_app_names_are_recognized() {
        assertEquals("coupang", SearchRules.canonical("쿠팡 앱"))
        assertEquals("coupang", SearchRules.canonical("Coupang"))
        assertEquals("coupangeats", SearchRules.canonical("Coupang Eats"))
        assertEquals("coupangeats", SearchRules.canonical("쿠팡이츠"))
        assertEquals("baemin", SearchRules.canonical("배달의민족"))
        assertEquals("baemin", SearchRules.canonical("Baemin"))
        assertEquals("chrome", SearchRules.canonical("크롬"))
        assertEquals("naver", SearchRules.canonical("NAVER"))
        assertEquals("youtube", SearchRules.canonical("유투브"))
        assertEquals("youtube", SearchRules.canonical("YouTube"))
        assertNull(SearchRules.canonical("설정"))
        assertEquals("생수", SearchRules.queryWithout("쿠팡 생수"))
        assertEquals("치킨", SearchRules.queryWithout("배민에서 치킨"))
    }

    @Test fun enrich_search_fills_app_and_strips_app_from_query() {
        val user = "쿠팡에서 생수 찾아줘"
        val p = SoloAction.parse("찾아볼게요.\nPHONE {\"do\":\"search\",\"app\":\"쿠팡\",\"query\":\"쿠팡 생수\"}")
        val a = SoloAction.enrich(p.action, user)
        assertEquals("search", a?.optString("do"))
        assertEquals("coupang", a?.optString("app"))
        assertEquals("생수", a?.optString("query"))
        // 모델이 app 을 비웠으면 사용자 말에서 채운다.
        val p2 = SoloAction.parse("PHONE {\"do\":\"search\",\"app\":\"\",\"query\":\"생수\"}")
        assertEquals("coupang", SoloAction.enrich(p2.action, user)?.optString("app"))
        // 검색이 아니면 손대지 않는다.
        val p3 = SoloAction.parse("PHONE {\"do\":\"open_app\",\"app\":\"쿠팡\"}")
        assertEquals("open_app", SoloAction.enrich(p3.action, user)?.optString("do"))
    }

    @Test fun detect_language_by_script() {
        assertEquals("ko", SoloLang.detect("안녕하세요"))
        assertEquals("ja", SoloLang.detect("こんにちは、元気ですか"))
        assertEquals("ja", SoloLang.detect("カタカナです"))
        assertEquals("zh", SoloLang.detect("你好，你是谁"))
        assertEquals("en", SoloLang.detect("Hello, how are you?"))
        assertEquals("ko", SoloLang.detect("2 더하기 2는?"))
    }

    @Test fun reply_directive_is_clear() {
        for (code in Lang.CODES) assertTrue(code, SoloLang.directive(code).isNotBlank())
        assertTrue(SoloLang.directive("en").contains("English"))
        assertTrue(SoloLang.directive("ko").contains("한국어"))
        assertTrue(SoloLang.directive("ja").contains("日本語"))
        assertTrue(SoloLang.directive("zh").contains("中文"))
    }

    @Test fun language_resolution() {
        assertEquals("ko", Lang.resolve("ko-KR"))
        assertEquals("ja", Lang.resolve("ja-JP"))
        assertEquals("zh", Lang.resolve("zh-Hant-TW"))
        assertEquals("en", Lang.resolve("en-GB"))
        assertEquals("en", Lang.resolve("fr-FR"))
        assertEquals("ko-KR", Lang.bcp47("ko"))
        assertEquals("zh-CN", Lang.bcp47("zh"))
    }
}