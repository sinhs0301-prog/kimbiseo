package kr.kimbiseo.phone

/**
 * 폰 펫 규칙 — 화면이 쓰는 동작 이름·옷 이름·캐시 파일 이름만 다룬다(순수 함수라 단위 시험으로 확인).
 *  서버(PC 김비서)는 대기(idle)·말하기(talk)·인사(hello/wave) 네 동작만 준다.
 */
object PetRules {
    val motions = listOf("idle", "talk", "hello", "wave")
    private val idRe = Regex("^[0-9A-Za-z가-힣_-]{1,40}$")

    /** 폰이 저장/전송하는 옷 id — 모양이 다르면 빈 글(PC 따라가기). */
    fun cleanOutfit(s: String?): String {
        val t = (s ?: "").trim()
        return if (idRe.matches(t)) t else ""
    }

    /** 모르는 동작 이름은 대기로. */
    fun motion(s: String?): String {
        val t = (s ?: "").trim()
        return if (t in motions) t else "idle"
    }

    /** 받은 파일의 확장자 — webm·mp4 만, 나머지는 webm. */
    fun ext(file: String?): String {
        val e = (file ?: "").substringAfterLast('.', "").lowercase()
        return if (e == "webm" || e == "mp4") e else "webm"
    }

    /** 캐시 파일 이름 = sha 앞 16자리 + 확장자(같은 파일을 가리키는 동작끼리 한 번만 받게). */
    fun fileName(sha: String?, file: String?): String {
        val s = (sha ?: "").trim().lowercase()
        val safe = s.filter { it in "0123456789abcdef" }
        return (if (safe.length >= 16) safe.substring(0, 16) else "unknown") + "." + ext(file)
    }

    /** sha256 비교(서버는 소문자, 폰은 대문자로 계산) — 둘 다 있어야 참. */
    fun shaOk(a: String?, b: String?): Boolean =
        !a.isNullOrBlank() && !b.isNullOrBlank() && a.trim().equals(b.trim(), ignoreCase = true)
}