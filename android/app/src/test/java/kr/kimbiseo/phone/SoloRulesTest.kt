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