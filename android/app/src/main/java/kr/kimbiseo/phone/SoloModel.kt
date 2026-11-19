package kr.kimbiseo.phone

import android.content.Context
import android.os.Build
import java.io.File
import java.io.InputStream
import java.security.MessageDigest

/**
 * 폰 안 AI 모델 — Gemma 4 E2B(LiteRT-LM). APK 에 넣지 않고 처음 쓸 때 구글 공식 배포처에서 받는다.
 *  받는 곳: Hugging Face litert-community(비공개·가입 없음) · 라이선스: Apache License 2.0.
 *  크기는 공식 파일 그대로이고, 받은 뒤 sha256 이 같아야 쓴다. 앱 저장소(filesDir/models)에만 둔다.
 */
object SoloModel {
    const val FILE = "gemma-4-E2B-it.litertlm"
    const val URL = "https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/main/" + FILE
    const val SIZE = 2_588_147_712L
    const val SHA256 = "181938105e0eefd105961417e8da75903eacda102c4fce9ce90f50b97139a63c"

    /**
     * 최소 램. 4GB 폰은 totalMem 이 보통 3.5~3.9GB 로 보고된다 → 3.3GB 아래(3GB 이하 폰)만 막는다.
     * (2026-11-19: 4GB AVD 에서 크래시 없이 돌아 문턱을 5GB → 3.3GB 로 낮춤. 6GB 폰은 5.5~5.9GB 로 보고된다.)
     */
    const val MIN_RAM = 3_300_000_000L

    /** 4GB 폰(3.5~3.9GB)은 6GB 폰(5.5~5.9GB)보다 빠듯하다 — 받기 화면에서 '다른 앱을 닫으면 더 안정적' 안내. */
    const val TIGHT_RAM = 5_000_000_000L
    const val MIN_ANDROID = 26                 // 안드로이드 8.0 — LiteRT-LM AAR minSdk 24, 앱 minSdk 26
    const val EXTRA_SPACE = 320L * 1024 * 1024 // 받는 동안 임시 여유

    data class Device(val ok: Boolean, val reasons: List<String>)

    /** 순수 기기 확인 — 단위 시험(SoloRulesTest). reasons: abi · ram · android · storage */
    fun check(abis: List<String>, totalMem: Long, sdk: Int, freeBytes: Long? = null): Device {
        val r = ArrayList<String>(4)
        if (abis.none { it == "arm64-v8a" || it == "x86_64" }) r.add("abi")
        if (totalMem in 1..(MIN_RAM - 1)) r.add("ram")
        if (sdk < MIN_ANDROID) r.add("android")
        if (freeBytes != null && freeBytes < SIZE + EXTRA_SPACE) r.add("storage")
        return Device(r.isEmpty(), r)
    }

    fun device(c: Context): Device {
        return check(Build.SUPPORTED_ABIS?.toList() ?: emptyList(), totalRam(c), Build.VERSION.SDK_INT)
    }

    /** 전체 램(바이트). ActivityManager 가 못 주면 0. */
    fun totalRam(c: Context): Long {
        @Suppress("DEPRECATION")
        val am = c.getSystemService(android.app.ActivityManager::class.java)
        val mi = android.app.ActivityManager.MemoryInfo()
        am?.getMemoryInfo(mi)
        return mi?.totalMem ?: 0L
    }

    /** 쓸 수는 있지만 빠듯한 램(4GB 폰) — 받기 화면 안내용. 순수 규칙(단위 시험). */
    fun tight(totalMem: Long): Boolean = totalMem >= MIN_RAM && totalMem < TIGHT_RAM

    fun tight(c: Context): Boolean = tight(totalRam(c))

    fun freeBytes(c: Context): Long = try { c.filesDir.usableSpace } catch (_: Throwable) { 0L }

    /** 앱 저장소의 모델 파일(다운로드는 여기). 없으면 시험용으로 앱 외부 저장소도 본다. */
    fun file(c: Context): File = File(File(c.filesDir, "models"), FILE)
    fun testFile(c: Context): File? = c.getExternalFilesDir(null)?.let { File(File(it, "models"), FILE) }

    fun present(c: Context): File? {
        val f = file(c)
        if (f.isFile && f.length() == SIZE) return f
        val t = testFile(c)
        if (t != null && t.isFile && t.length() == SIZE) return t
        return null
    }

    fun ready(c: Context): Boolean = present(c) != null

    fun part(c: Context): File = File(File(c.filesDir, "models"), FILE + ".part")
    fun marker(c: Context): File = File(File(c.filesDir, "models"), FILE + ".ok")

    fun delete(c: Context) {
        try { file(c).delete() } catch (_: Throwable) {}
        try { part(c).delete() } catch (_: Throwable) {}
        try { marker(c).delete() } catch (_: Throwable) {}
        try { testFile(c)?.delete() } catch (_: Throwable) {}
    }

    fun human(bytes: Long): String {
        val mb = bytes / (1024.0 * 1024.0)
        return if (mb >= 1024) "%.1f GB".format(mb / 1024.0) else "%.0f MB".format(mb)
    }

    /** 파일 sha256(소문자). 2.6GB 라 오래 걸리므로 네트워크·계산 스레드에서 부른다. */
    fun sha256(f: File, onProgress: ((Long) -> Unit)? = null): String {
        val md = MessageDigest.getInstance("SHA-256")
        var done = 0L
        f.inputStream().use { ins: InputStream ->
            val b = ByteArray(1024 * 1024)
            while (true) {
                val n = ins.read(b)
                if (n <= 0) break
                md.update(b, 0, n); done += n
                if (onProgress != null && done % (64L * 1024 * 1024) < n) onProgress(done)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }
}