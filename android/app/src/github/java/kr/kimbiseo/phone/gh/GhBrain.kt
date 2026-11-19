package kr.kimbiseo.phone.gh

import android.content.Context
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * 화면 판단 두뇌 — PC(또는 사용자가 넣은) OpenAI 호환 주소에 화면 글자와 목표를 보내 다음 한 걸음을 받는다.
 *  데스크톱 코드는 안 건드린다. 주소·모델·열쇠는 폰 설정(GhSettingsActivity)에서 사용자가 넣는다.
 *  폰 혼자 모드의 작은 모델(2B)은 쓰지 않는다(GhRunner 가 안내).
 */
object GhBrain {
    data class Reply(val decision: GhBrainReply.Decision?, val error: String = "", val raw: String = "")

    private val http = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS).readTimeout(25, TimeUnit.SECONDS).writeTimeout(10, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false).build()

    private const val SYSTEM = """You control one Android phone screen for a user. Choose exactly ONE next step.
Reply with ONLY one JSON object, no prose:
{"action":"tap","i":N} - tap element N
{"action":"type","i":N,"text":"..."} - type into editable element N
{"action":"back"} - Android back
{"action":"wait"} - wait for the screen to load
{"action":"done"} - the cart-add confirmation is visible
Rules:
- The goal is to put one product in the shopping cart. Stop when you see a cart-added confirmation.
- NEVER choose a payment/order/buy button: 결제, 주문, 구매, pay, checkout, place order, 支払, 注文, 決済, 購入, 支付, 结算, 下单, 购买.
- Prefer the search box first, then search, then the matching product, then "장바구니 담기"/"add to cart".
- Do not invent element numbers. Use only the numbers shown.
- If a popup blocks the screen, close it or press back.
- Do not log in, do not enter passwords or card numbers."""

    fun url(base0: String): String {
        val base = base0.trim().trimEnd('/')
        return if (base.endsWith("/chat/completions")) base else base + "/chat/completions"
    }

    fun ask(c: Context, goal: String, pkg: String, nodes: List<GhAccessibilityService.Node>): Reply {
        // 잠깐 끊긴 연결(keep-alive 재사용 실패 등)은 한 번 더.
        var last = askOnce(c, goal, pkg, nodes)
        if (last.decision == null && last.error != "brain") {
            try { Thread.sleep(300) } catch (_: InterruptedException) {}
            last = askOnce(c, goal, pkg, nodes)
        }
        return last
    }

    private fun askOnce(c: Context, goal: String, pkg: String, nodes: List<GhAccessibilityService.Node>): Reply {
        val base = GhStore.brainBase(c)
        if (base.isBlank()) return Reply(null, "brain")
        val model = GhStore.brainModel(c).ifBlank { "local" }
        val key = GhStore.brainKey(c)

        val lines = nodes.take(60).map { n ->
            val kind = when { n.editable -> "input"; n.clickable -> "tap"; else -> "text" }
            "${n.i}. [$kind] ${n.label.take(90)}"
        }
        val screen = nodes.take(60).joinToString("\n") { n -> "${n.i}. ${n.label.take(90)}" }
        val user = "Goal: $goal\nThe phone is on screen of package ${nodes.firstOrNull()?.let { "" } ?: ""}" +
            "\nElements (number. label):\n" + lines.joinToString("\n") +
            "\n\nFull element text:\n" + screen + "\n\nJSON only."
        val body = JSONObject().apply {
            put("model", model)
            put("temperature", 0.0)
            put("max_tokens", 120)
            put("stream", false)
            put("messages", JSONArray().apply {
                put(JSONObject().put("role", "system").put("content", SYSTEM))
                put(JSONObject().put("role", "user").put("content", user))
            })
        }
        val rb = Request.Builder().url(url(base))
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .header("Accept", "application/json")
        if (key.isNotBlank()) rb.header("Authorization", "Bearer $key")
        return try {
            http.newCall(rb.build()).execute().use { r ->
                val txt = r.body?.string() ?: ""
                if (r.code !in 200..299) return Reply(null, "http ${r.code}", txt.take(200))
                val j = JSONObject(txt)
                val content = j.optJSONArray("choices")?.optJSONObject(0)?.optJSONObject("message")?.optString("content")
                    ?: j.optJSONArray("choices")?.optJSONObject(0)?.optString("text") ?: ""
                val d = GhBrainReply.parse(content)
                Reply(d, if (d == null) "parse" else "", content.take(300))
            }
        } catch (e: Throwable) {
            Reply(null, e.javaClass.simpleName + ": " + (e.message ?: "").take(120))
        }
    }
}