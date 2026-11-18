package kr.kimbiseo.phone

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Handler
import android.os.Looper
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.TimeUnit

/**
 * 모델 받기 — 처음 한 번, 와이파이에서(기본). 이어받기(HTTP Range) · 진행률 · 크기·sha256 확인.
 *  APK 밖(앱 저장소)에만 두고, 다 받은 뒤에만 모델로 쓴다. 화면이 사라져도 받던 곳까지 남아 다음에 이어받는다.
 */
class SoloDownload(private val c: Context) {
    companion object {
        const val WIFI = "wifi"
        const val STORAGE = "storage"
        const val HTTP = "http"
        const val SHA = "sha"
        const val IO = "io"
        const val CANCEL = "cancel"
        const val OK = "ok"
    }

    private val main = Handler(Looper.getMainLooper())
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(90, TimeUnit.SECONDS).callTimeout(0, TimeUnit.MILLISECONDS)
        .retryOnConnectionFailure(true).build()

    @Volatile private var call: Call? = null
    @Volatile var cancelled = false
        private set

    fun stop() { cancelled = true; try { call?.cancel() } catch (_: Throwable) {} }

    fun wifi(c: Context = this.c): Boolean {
        val cm = c.getSystemService(ConnectivityManager::class.java) ?: return false
        val n = cm.activeNetwork ?: return false
        val cap = cm.getNetworkCapabilities(n) ?: return false
        return cap.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || cap.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
    }

    /** 네트워크·계산 스레드에서 부름. onProgress(done,total) · onState(code) · onDone(ok,why) 는 주 스레드로. */
    fun start(wifiOnly: Boolean, onProgress: (Long, Long) -> Unit, onState: (String) -> Unit, onDone: (Boolean, String?) -> Unit) {
        cancelled = false
        Thread {
            var ok = false; var why: String? = null
            try {
                ok = run(wifiOnly, onProgress, onState); why = if (ok) null else lastWhy
            } catch (e: Throwable) {
                why = if (cancelled) CANCEL else IO
            }
            main.post { onDone(ok, why) }
        }.apply { name = "solo-download"; start() }
    }

    @Volatile private var lastWhy: String? = null

    private fun run(wifiOnly: Boolean, onProgress: (Long, Long) -> Unit, onState: (String) -> Unit): Boolean {
        val f = SoloModel.file(c)
        val part = SoloModel.part(c)
        f.parentFile?.mkdirs()
        if (wifiOnly && !wifi()) { lastWhy = WIFI; return false }
        if (SoloModel.freeBytes(c) < SoloModel.SIZE + SoloModel.EXTRA_SPACE) { lastWhy = STORAGE; return false }
        if (part.length() > SoloModel.SIZE) part.delete()
        var have = if (part.isFile) part.length() else 0L

        if (have < SoloModel.SIZE) {
            main.post { onState("download") }
            val req = Request.Builder().url(SoloModel.URL)
                .header("Range", "bytes=$have-")
                .header("User-Agent", "KimBiseo-phone/" + BuildConfig.VERSION_NAME)
                .build()
            val cl = http.newCall(req); call = cl
            cl.execute().use { r ->
                if (r.code != 200 && r.code != 206 && r.code != 416) { lastWhy = HTTP; return false }
                if (r.code == 200 && have > 0) { part.delete(); have = 0 }   // Range 를 무시한 서버 → 처음부터
                if (r.code == 416 && have == SoloModel.SIZE) {
                    // 이미 다 받았고 확인만 남음
                } else if (r.code != 416) {
                    val body = r.body ?: run { lastWhy = HTTP; return false }
                    val total = have + (body.contentLength().coerceAtLeast(0L))
                    FileOutputStream(part, have > 0).use { out ->
                        body.byteStream().use { ins ->
                            val b = ByteArray(256 * 1024)
                            var since = System.currentTimeMillis()
                            var n: Int
                            while (ins.read(b).also { n = it } > 0) {
                                if (cancelled) { lastWhy = CANCEL; return false }
                                out.write(b, 0, n); have += n
                                val now = System.currentTimeMillis()
                                if (now - since >= 350) {
                                    since = now
                                    val d = have
                                    main.post { onProgress(d, if (total > 0) total else SoloModel.SIZE) }
                                    if (wifiOnly && !wifi()) { lastWhy = WIFI; return false }
                                }
                            }
                            out.flush()
                        }
                    }
                    val d = have
                    main.post { onProgress(d, SoloModel.SIZE) }
                }
            }
            call = null
        }
        if (cancelled) { lastWhy = CANCEL; return false }
        if (part.length() != SoloModel.SIZE) {
            // 서버가 조용히 끊었으면 다음에 이어받는다.
            lastWhy = if (part.length() < SoloModel.SIZE) HTTP else IO
            return false
        }
        main.post { onState("verify") }
        val sha = SoloModel.sha256(part)
        if (sha != SoloModel.SHA256) { part.delete(); lastWhy = SHA; return false }
        if (!part.renameTo(f)) {
            // 이름 바꾸기가 안 되면 복사
            try { part.copyTo(f, overwrite = true); part.delete() } catch (_: Throwable) { lastWhy = IO; return false }
        }
        try { SoloModel.marker(c).writeText(sha) } catch (_: Throwable) {}
        main.post { onState("ok") }
        return true
    }
}