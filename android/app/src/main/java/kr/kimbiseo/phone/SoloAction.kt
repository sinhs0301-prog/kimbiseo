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
}