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

    @Test fun device_rejects_four_gb() {
        val d = SoloModel.check(listOf("arm64-v8a"), 3_800_000_000L, 34)
        assertFalse(d.ok)
        assertEquals(listOf("ram"), d.reasons)
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