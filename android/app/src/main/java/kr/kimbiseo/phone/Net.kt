package kr.kimbiseo.phone

import android.os.Build
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/**
 * PC 와의 연결 — 내 PC 가 만든 자체 인증서만 믿는다(인증서 지문 고정).
 *  인증 기관 확인 대신 '짝지을 때 받은 지문과 똑같은 인증서인가'만 본다 → 같은 와이파이의 다른 기기가 PC 인 척해도 연결 안 됨.
 *  주소(IP) 이름 확인은 끈다: 인증서가 정확히 그 PC 의 것인지 지문으로 이미 확인했기 때문(PC 주소는 공유기가 바꿀 수 있음).
 */
class Pinned(private val pin: String) : X509TrustManager {
    @Volatile var seen: String = ""
    override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) { throw CertificateException("client") }
    override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
        if (chain.isEmpty()) throw CertificateException("인증서 없음")
        val fp = Net.sha256(chain[0].encoded)
        if (!PairRules.fpMatches(pin, fp)) throw CertificateException("인증서 지문이 달라요")
        seen = fp
    }
    override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
}

object Net {
    fun sha256(b: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02X".format(it) }

    fun client(pin: String, ws: Boolean = false): Pair<OkHttpClient, Pinned> {
        val tm = Pinned(pin)
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf(tm), null)
        val b = OkHttpClient.Builder().sslSocketFactory(ctx.socketFactory, tm).hostnameVerifier { _, _ -> true }
            .connectTimeout(4, TimeUnit.SECONDS).retryOnConnectionFailure(false)
        if (ws) b.readTimeout(0, TimeUnit.MILLISECONDS).pingInterval(15, TimeUnit.SECONDS) else b.readTimeout(10, TimeUnit.SECONDS)
        return Pair(b.build(), tm)
    }

    class PairResult(val ok: Boolean, val msg: String, val host: String = "", val device: String = "", val token: String = "",
                     val fp: String = "", val pcName: String = "")

    /** 연결하기: 주소들을 차례로 — 연결되는 곳에서 코드 보내기. 코드가 틀리면(403) 다른 주소로 다시 보내지 않음(코드는 한 번만). 네트워크 스레드에서 부름.
     *  실패 문구는 까닭별로(PairRules 없이 여기서 고름): 코드 틀림·코드 없음/시간 지남·잠김(PC 가 '왜'·'잠금초'로 알려 줌) /
     *  PC 가 이 주소에서 오는 연결을 안 받음 / 닿지 않음(와이파이·테일스케일 안내) / 인증서 다름. */
    fun pair(info: PairInfo, phoneName: String = deviceName()): PairResult {
        val (http, tm) = client(info.fp)
        var last = unreachable(info.hosts)
        for (h in info.hosts) {
            val body = JSONObject().put("code", info.code).put("name", phoneName).toString().toRequestBody("application/json".toMediaType())
            val req = Request.Builder().url(PairRules.baseUrl(h, info.port) + "/phone/pair").post(body).build()
            try {
                http.newCall(req).execute().use { r ->
                    val j = try { JSONObject(r.body?.string() ?: "{}") } catch (_: Throwable) { JSONObject() }
                    if (r.code == 200 && j.optBoolean("ok")) {
                        return PairResult(true, L.s(R.string.net_pair_ok), h, j.optString("기기"), j.optString("토큰"), tm.seen, j.optString("PC", info.pcName))
                    }
                    return PairResult(false, pairError(r.code, j, h))
                }
            } catch (e: javax.net.ssl.SSLException) {
                last = L.s(R.string.net_cert_mismatch)
            } catch (e: Throwable) { /* 다음 주소 */ }
        }
        return PairResult(false, last)
    }

    /** PC 가 답은 했지만 연결이 안 된 까닭 → 사용자 문구 */
    fun pairError(code: Int, j: JSONObject, host: String): String {
        val why = j.optString("왜"); val lock = j.optInt("잠금초", 0); val said = j.optString("오류")
        fun wait(s: Int) = if (s >= 90) L.s(R.string.net_wait_min, (s + 59) / 60) else L.s(R.string.net_wait_sec, s)
        return when {
            why == "잠김" || (code == 403 && lock > 0 && why.isEmpty()) ->
                L.s(R.string.net_locked, wait(maxOf(lock, 1)))
            why == "잠김_전체" -> L.s(R.string.net_locked_all)
            why == "틀림" -> L.s(R.string.net_wrong_code) + if (lock > 0) " " + L.s(R.string.net_wrong_code_suffix, wait(lock)) else ""
            why == "만료" -> L.s(R.string.net_expired)
            why == "없음" -> L.s(R.string.net_none)
            why == "주소_거절" || (code == 403 && said.contains("집 안 네트워크")) ->
                if (host.startsWith("100.")) L.s(R.string.net_tailscale_off)
                else L.s(R.string.net_address_rejected)
            code == 403 -> said.ifEmpty { L.s(R.string.net_403) }
            else -> said.ifEmpty { L.s(R.string.net_generic, code) }
        }
    }

    /** 어느 주소에도 닿지 않았을 때 — 테일스케일 주소(100.x)면 테일스케일 안내 */
    fun unreachable(hosts: List<String>): String =
        if (hosts.isNotEmpty() && hosts.all { it.startsWith("100.") || it.lowercase().startsWith("fd7a:") })
            L.s(R.string.net_unreachable_ts, hosts.first())
        else L.s(R.string.net_unreachable_lan)

    fun deviceName(): String = ((Build.MANUFACTURER ?: "") + " " + (Build.MODEL ?: "")).trim().take(30).ifEmpty { L.s(R.string.device_phone) }
}
