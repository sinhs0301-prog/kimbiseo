package kr.kimbiseo.phone.gh

import org.json.JSONObject

/**
 * 두뇌(OpenAI 호환)가 보낸 다음 동작 한 개를 읽는다(순수 규칙 · 단위 시험).
 *  여러 모델이 조금씩 다르게 답해도 받아 준다: {"action":"tap","i":3} · {"tap":3} · {"i":3} ·
 *  {"action":"type","i":2,"text":"삼다수"} · {"back":true} · {"wait":true} · {"done":true}
 *  JSON 이 없거나 못 읽으면 null — 그 걸음은 쉽니다.
 */
object GhBrainReply {
    sealed class Decision {
        data class Tap(val i: Int) : Decision()
        data class Type(val i: Int, val text: String) : Decision()
        object Back : Decision()
        object Wait : Decision()
        data class Done(val why: String = "") : Decision()
    }

    fun parse(reply: String): Decision? {
        val j = obj(reply) ?: return null
        val act = j.optString("action").lowercase().replace("_", "").replace("-", "")
        if (j.optBoolean("done", false) || act == "done" || act == "finish") return Decision.Done(j.optString("why", j.optString("reason")))
        if (j.optBoolean("back", false) || act == "back") return Decision.Back
        if (j.optBoolean("wait", false) || act == "wait" || act == "none") return Decision.Wait
        val i = when {
            j.has("i") -> j.optInt("i", -1)
            j.has("index") -> j.optInt("index", -1)
            j.has("tap") -> j.optInt("tap", -1)
            j.has("click") -> j.optInt("click", -1)
            else -> -1
        }
        if (i < 0) return null
        val text = j.optString("text").ifBlank { j.optString("value") }
        return if (act == "type" || act == "input" || act == "settext" || text.isNotBlank())
            Decision.Type(i, text.take(80))
        else Decision.Tap(i)
    }

    /** 답 글 안에서 첫 JSON 객체를 꺼낸다(```json 울타리·앞뒤 설명 허용). */
    fun obj(reply: String): JSONObject? {
        val s = reply.trim().removePrefix("```json").removePrefix("```").removeSuffix("```").trim()
        val a = s.indexOf('{'); val b = s.lastIndexOf('}')
        if (a < 0 || b <= a) return null
        return try { JSONObject(s.substring(a, b + 1)) } catch (_: Throwable) { null }
    }
}