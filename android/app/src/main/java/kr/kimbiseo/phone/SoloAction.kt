package kr.kimbiseo.phone

import org.json.JSONObject

/**
 * 폰 안 AI 의 대답에서 '폰 일' 한 줄을 뽑는다(순수 규칙 — 단위 시험).
 *  모델이 답 끝에 붙인 `PHONE {"do":"navigate","destination":"강남역","app":"naver"}` 을 읽어 Doer 로 넘기고,
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
     * 모델 PHONE 줄에 app 칸이 없는데 사용자가 앱을 말했으면 사용자 말로 채운다(사용자 말 우선).
     *  목적지에 앱 이름이 섞였으면("강남역 카카오내비") 목적지에서도 뺀다.
     */
    fun enrich(action: JSONObject?, userText: String): JSONObject? {
        if (action == null || action.optString("do") != "navigate") return action
        val hit = NavAppRules.find(userText)
        if (action.optString("app").isBlank() && hit != null) action.put("app", hit.key)
        val dest = action.optString("destination")
        if (dest.isNotBlank()) {
            val d = NavAppRules.destWithout(dest)
            if (d.isNotBlank()) action.put("destination", d)
        }
        return action
    }

    /**
     * 모델이 PHONE 줄을 안 붙였을 때를 위한 안전망 — 사용자가 쓴 말에서 흔한 폰 부탁을 직접 알아본다(순수 규칙).
     *  한국어·English·日本語·中文의 짧은 명령만. 길안내는 앱 이름(카카오내비·네이버 지도 등)을 떼어 app 칸으로.
     *  애매하면 null(모델 답만 보여 줌).
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

        // 길안내 — 앱 이름이 섞여 있으면 먼저 떼어 내고 목적지만 남긴다("카카오내비로 천안역" → "천안역", app=kakaonavi)
        val hit = NavAppRules.find(t)
        val body = if (hit != null) NavAppRules.strip(t, hit) else t
        val app = hit?.key

        Regex("^(.+?)\\s*(?:가는\\s*)?길\\s*(?:안내|알려|찾아|가이드)").find(body)?.let { return nav(it.groupValues[1], app) }
        Regex("^(.+?)\\s*(?:까지|한테|으로|로)\\s*(?:안내|가\\s*줘|가줘|데려다)").find(body)?.let { return nav(it.groupValues[1], app) }
        Regex("^(.+?)\\s*(?:까지|으로|로|에)?\\s*(?:가자|가\\s*줘|가줘|가\\s*주세요|가주세요)$").find(body)?.let { return nav(it.groupValues[1], app) }
        if (app != null) {
            // 앱을 말했을 때만 — 조사 없이 "천안역 안내해줘" 처럼 짧게 말한 경우
            Regex("^(.+?)\\s*(?:까지|으로|로|에)?\\s*(?:안내|가이드)(?:해|해\\s*줘|해줘|해주세요|해\\s*주세요)?$").find(body)?.let {
                return nav(it.groupValues[1], app)
            }
            Regex("^(.+?)\\s*(?:가는\\s*)?길$").find(body)?.let { return nav(it.groupValues[1], app) }
        }
        Regex("^(?:navigate|directions?|route|take me)\\s+to\\s+(.+)$", RegexOption.IGNORE_CASE).find(body)?.let { return nav(it.groupValues[1], app) }
        Regex("^(?:go|head)\\s+to\\s+(.+)$", RegexOption.IGNORE_CASE).find(body)?.let { return nav(it.groupValues[1], app) }
        Regex("^(.+?)(?:へ|に)(?:行きたい|案内して|案内してください|行って)$").find(body)?.let { return nav(it.groupValues[1], app) }
        Regex("^(.+?)まで案内(?:して|してください)?$").find(body)?.let { return nav(it.groupValues[1], app) }
        Regex("^(?:导航到|去|到)(.+?)(?:怎么走|导航)?$").find(body)?.let { return nav(it.groupValues[1], app) }

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

    private fun nav(dest: String, app: String? = null): JSONObject? {
        val d = clean(dest).removeSuffix("까지").removeSuffix("으로").removeSuffix("로").removeSuffix("에서").trim()
        if (d.isEmpty()) return null
        val o = JSONObject().put("do", "navigate").put("destination", NavAppRules.destWithout(d))
        if (app != null) o.put("app", app)
        return o
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