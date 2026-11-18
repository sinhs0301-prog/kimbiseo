package kr.kimbiseo.phone

/**
 * 사용자가 쓴 글의 언어를 글자로 알아낸다(순수 규칙 — 단위 시험).
 *  한글 → 한국어 · 가나 → 日本語 · 한자만 → 中文 · 그 밖(라틴 글) → English.
 *  대화 문맥에 다른 언어가 섞여 있어도 '이번 답'은 사용자가 쓴 언어로 하라고 한 줄 덧붙이는 데 쓴다.
 */
object SoloLang {
    fun detect(s: String): String {
        var hangul = false; var kana = false; var han = false
        for (c in s) {
            if (c in '가'..'힣' || c in 'ㄱ'..'ㆎ') hangul = true
            else if (c in 'ぁ'..'ゟ' || c in 'ァ'..'ヿ') kana = true
            else if (c in '一'..'鿿') han = true
        }
        return when {
            hangul -> "ko"
            kana -> "ja"
            han -> "zh"
            else -> "en"
        }
    }

    fun directive(code: String): String = when (code) {
        "ko" -> "다음 답변은 한국어로만 하세요. 다른 언어를 섞지 마세요."
        "ja" -> "次の返事は日本語だけでしてください。中国語や英語を混ぜないでください。"
        "zh" -> "请只用简体中文回答，不要夹杂日语或英语。"
        else -> "Answer only in English. Do not mix other languages."
    }
}