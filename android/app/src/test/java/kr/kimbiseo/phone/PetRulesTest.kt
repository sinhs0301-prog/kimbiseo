package kr.kimbiseo.phone

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PetRulesTest {
    @Test fun cleanOutfitKeepsKnownIds() {
        assertEquals("kimbiseo_f", PetRules.cleanOutfit(" kimbiseo_f "))
        assertEquals("김비서_옷", PetRules.cleanOutfit("김비서_옷"))
        assertEquals("", PetRules.cleanOutfit(""))
        assertEquals("", PetRules.cleanOutfit(null))
        assertEquals("", PetRules.cleanOutfit("../pet"))          // 경로 꼴
        assertEquals("", PetRules.cleanOutfit("a/b"))
        assertEquals("", PetRules.cleanOutfit("x".repeat(41)))
    }

    @Test fun onlyFourMotions() {
        assertEquals("idle", PetRules.motion(null))
        assertEquals("idle", PetRules.motion("dance"))
        assertEquals("talk", PetRules.motion("talk"))
        assertEquals("hello", PetRules.motion("hello"))
        assertEquals("wave", PetRules.motion("wave"))
    }

    @Test fun fileNamesShareOneFilePerSha() {
        val a = PetRules.fileName("ABCDEF0123456789ABCDEF", "hello.webm")
        val b = PetRules.fileName("abcdef0123456789abcdef", "wave.mp4")   // 같은 sha, 다른 동작·확장자
        assertEquals("abcdef0123456789.webm", a)
        assertEquals("abcdef0123456789.mp4", b)
        assertEquals("unknown.webm", PetRules.fileName("short", null))    // 모자란 sha
        assertEquals("unknown.mp4", PetRules.fileName("zzzzzzzzzzzzzzzz", "x.mp4"))   // 16진수가 아님
        assertEquals("aaaaaaaaaaaaaaaa.mp4", PetRules.fileName("aaaaaaaaaaaaaaaa", "x.mp4"))
        assertEquals("abcdef0123456789.webm", PetRules.fileName("abcdef0123456789", "x.exe"))  // 모르는 확장자 → webm
    }

    @Test fun shaCompareIgnoresCase() {
        assertTrue(PetRules.shaOk("abcdef", "ABCDEF"))
        assertTrue(PetRules.shaOk(" ABCDEF ", "abcdef"))
        assertFalse(PetRules.shaOk("", "abcdef"))
        assertFalse(PetRules.shaOk(null, "abcdef"))
        assertFalse(PetRules.shaOk("abcdef", "abcdee"))
    }

    @Test fun allAgesOnlyWhenMarkedAllAndNotAdultId() {
        assertTrue(PetRules.isAllAges("all", "kimbiseo_f"))
        assertTrue(PetRules.isAllAges(" ALL ", "kimbiseo_mix"))
        assertFalse(PetRules.isAllAges("19", "kimbiseo_f"))
        assertFalse(PetRules.isAllAges("", "kimbiseo_f"))            // 표시 못 읽음 → 숨김
        assertFalse(PetRules.isAllAges(null, "kimbiseo_f"))
        assertFalse(PetRules.isAllAges("adult", "kimbiseo_f"))       // 모르는 표시 → 숨김
        assertFalse(PetRules.isAllAges("all", "kimbiseo_bikini"))    // 옛 꾸러미도 id 로 거름
        assertFalse(PetRules.isAllAges("all", "kimbiseo_bikini "))   // 앞뒤 빈칸
        assertFalse(PetRules.isAllAges("all", ""))
        assertFalse(PetRules.isAllAges("all", null))
    }
}