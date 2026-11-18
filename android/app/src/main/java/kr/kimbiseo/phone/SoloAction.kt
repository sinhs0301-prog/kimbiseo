package kr.kimbiseo.phone

import org.json.JSONObject

/**
 * 폰 안 AI 의 대답에서 '폰 일' 한 줄을 뽑는다(순수 규칙 — 단위 시험).
 *  모델이 답 끝에 붙인 `PHONE {"do":"navigate","destination":"강남역"}` 을 읽어 Doer 로 넘기고,
 *  화면·목소리에는 그 줄을 뺀 나머지만 보여 준다. 모델이 안 붙이면 아무 일도 안 한다.
 */
object SoloAction {
    data class Parsed(val text: String, val action: JSONObject?)

    private val LINE = Regex("^[ \t]*`?PHONE`?[ \t]*(\\{[^\\n]*\\})`?[ \t]*$", RegexOption.MULTILINE)

    fun parse(reply: String): Parsed {
        val all = LINE.findAll(reply).toList()
        if (all.isEmpty()) return Parsed(reply.trim(), null)
        val action = all.mapNotNull { m ->
            try { JSONObject(m.groupValues[1]) } catch (_: Throwable) { null }
        }.lastOrNull { valid(it) }
        var text = reply
        for (m in all.reversed()) text = text.removeRange(m.range)
        text = text.replace(Regex("\\n{3,}"), "\n\n").trim()
        return Parsed(text, action)
    }

    private fun valid(o: JSONObject): Boolean = when (o.optString("do")) {
        "navigate" -> o.optString("destination").isNotBlank()
        "dial" -> o.optString("contact").isNotBlank() || o.optString("number").isNotBlank()
        "sms" -> (o.optString("contact").isNotBlank() || o.optString("number").isNotBlank())
        "open_app" -> o.optString("app").isNotBlank()
        else -> false
    }

    /**
     * 모델이 PHONE 줄을 안 붙였을 때를 위한 안전망 — 사용자가 쓴 말에서 흔한 폰 부탁을 직접 알아본다(순수 규칙).
     *  한국어·English·日本語·中文의 짧은 명령만. 애매하면 null(모델 답만 보여 줌).
     */
    fun fromUser(text: String): JSONObject? {
        val t = text.trim().replace(Regex("[.!?。！？]+$"), "").trim()
        if (t.isEmpty() || t.length > 120) return null

        // 앱 열기
        koreanOpen(t)?.let { return openApp(it) }
        Regex("^(?:open|launch|start)\\s+(?:the\\s+)?(.+?)(?:\\s+app)?$", RegexOption.IGNORE_CASE).find(t)?.let {
            return openApp(it.groupValues[1].trim())
        }
        Regex("^(.+?)(?:アプリ)?を?(?:開いて|起動して|開けて)(?:ください)?$").find(t)?.let { return openApp(it.groupValues[1].trim()) }
        Regex("^打开(.+?)(?:应用|app)?$", RegexOption.IGNORE_CASE).find(t)?.let { return openApp(it.groupValues[1].trim()) }

        // 길안내
        Regex("^(.+?)\\s*(?:가는\\s*)?길\\s*(?:안내|알려|찾아|가이드)").find(t)?.let { return nav(it.groupValues[1]) }
        Regex("^(.+?)\\s*(?:까지|한테|으로|로)\\s*(?:안내|가\\s*줘|가줘|데려다)").find(t)?.let { return nav(it.groupValues[1]) }
        Regex("^(?:navigate|directions?|route|take me)\\s+to\\s+(.+)$", RegexOption.IGNORE_CASE).find(t)?.let { return nav(it.groupValues[1]) }
        Regex("^(.+?)(?:へ|に)(?:行きたい|案内して|案内してください)$").find(t)?.let { return nav(it.groupValues[1]) }
        Regex("^(.+?)まで案内(?:して|してください)?$").find(t)?.let { return nav(it.groupValues[1]) }
        Regex("^(?:导航到|去|到)(.+?)(?:怎么走|导航)?$").find(t)?.let { return nav(it.groupValues[1]) }

        // 문자(전화보다 먼저 — '문자' 안에 '전화'는 없지만 순서를 분명히)
        Regex("^(.+?)(?:한테|에게|께)\\s*(?:문자|메시지|톡)\\s*(?:해|보내|보내줘)?\\s*(?:줘|줘요|주세요)?$").find(t)?.let { return sms(it.groupValues[1]) }
        Regex("^(?:text|message|send a text to|send a message to)\\s+(.+)$", RegexOption.IGNORE_CASE).find(t)?.let { return sms(it.groupValues[1]) }
        Regex("^(.+?)に(?:メッセージ|短信|SMS)(?:を送って|して)?$", RegexOption.IGNORE_CASE).find(t)?.let { return sms(it.groupValues[1]) }
        Regex("^给(.+?)(?:发短信|发消息|发个短信)$").find(t)?.let { return sms(it.groupValues[1]) }

        // 전화
        Regex("^(.+?)(?:한테|에게|께)\\s*전화\\s*(?:해|걸어|걸어줘|해줘)?\\s*(?:줘|줘요|주세요)?$").find(t)?.let { return dial(it.groupValues[1]) }
        Regex("^(.+?)\\s*전화\\s*(?:걸어|해)\\s*(?:줘|줘요|주세요)?$").find(t)?.let { return dial(it.groupValues[1]) }
        Regex("^(?:call|phone|dial)\\s+(.+)$", RegexOption.IGNORE_CASE).find(t)?.let { return dial(it.groupValues[1]) }
        Regex("^(.+?)に電話(?:して|してください)?$").find(t)?.let { return dial(it.groupValues[1]) }
        Regex("^给(.+?)打电话$").find(t)?.let { return dial(it.groupValues[1]) }
        return null
    }

    private fun koreanOpen(t: String): String? {
        val m = Regex("^(.+?)\\s*(?:앱|어플)?\\s*(?:을|를|좀)?\\s*(?:열어|켜|실행해|실행)\\s*(?:줘|줘요|주세요|봐)?$").find(t) ?: return null
        return m.groupValues[1].trim().removeSuffix("앱").removeSuffix("어플").trim().ifEmpty { null }
    }

    private fun clean(s: String): String = s.trim().trim('"', '\'', '“', '”', '‘', '’', '「', '」').trim()

    private fun openApp(app: String): JSONObject? {
        val a = clean(app).removeSuffix("앱").removeSuffix("어플").trim()
        if (a.isEmpty()) return null
        return JSONObject().put("do", "open_app").put("app", a)
    }

    private fun nav(dest: String): JSONObject? {
        val d = clean(dest).removeSuffix("까지").removeSuffix("으로").removeSuffix("로").trim()
        if (d.isEmpty()) return null
        return JSONObject().put("do", "navigate").put("destination", d)
    }

    private fun dial(who: String): JSONObject? {
        val w = clean(who).removeSuffix("한테").removeSuffix("에게").removeSuffix("께").trim()
        if (w.isEmpty()) return null
        return JSONObject().put("do", "dial").put("contact", w)
    }

    private fun sms(who: String): JSONObject? {
        val w = clean(who).removeSuffix("한테").removeSuffix("에게").removeSuffix("께").trim()
        if (w.isEmpty()) return null
        return JSONObject().put("do", "sms").put("contact", w)
    }
}