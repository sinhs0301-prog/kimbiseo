package kr.kimbiseo.phone

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 폰 펫 클립 받기·보관 — PC 관문의 /phone/api/pet(목록)·/phone/api/pet/clip(파일)에서
 *  대화 화면에 필요한 네 동작(대기·말하기·인사)만 받아 앱 저장소(filesDir/pet)에 둔다.
 *  · 처음 한 번 받고, 목록의 sha256 이 바뀌면 그 클립만 다시 받는다.
 *  · '와이파이에서만 받기'(기본 켬)면 와이파이·유선일 때만 클립을 받는다. 목록(작은 JSON)은 언제든 읽는다.
 *  · 받은 파일은 모두 sha256·크기를 확인한 뒤에만 쓴다.
 *  · 펫이 꺼져 있거나 PC 에 옷이 없으면 조용히 아무것도 보여 주지 않는다.
 */
object PetStore {
    private val exec = Executors.newSingleThreadExecutor { r -> Thread(r, "kb-pet").apply { isDaemon = true } }
    private val busy = AtomicBoolean(false)
    @Volatile private var lastAt = 0L
    @Volatile private var manifest: JSONObject? = null
    @Volatile private var loaded = false
    @Volatile var status: String = ""
        private set

    // ---------------------------------------------------------------- 저장 설정(비밀 아님)
    fun selected(c: Context): String = Store.str(c, "pet_outfit", "")
    fun setSelected(c: Context, id: String) { Store.setStr(c, "pet_outfit", PetRules.cleanOutfit(id)) }
    fun show(c: Context): Boolean = Store.flag(c, "pet_show", true)
    fun setShow(c: Context, on: Boolean) { Store.setFlag(c, "pet_show", on) }
    fun wifiOnly(c: Context): Boolean = Store.flag(c, "pet_wifi", true)
    fun setWifiOnly(c: Context, on: Boolean) { Store.setFlag(c, "pet_wifi", on) }

    private fun dir(c: Context) = File(c.filesDir, "pet")
    private fun manifestFile(c: Context) = File(dir(c), "manifest.json")

    @Synchronized
    private fun load(c: Context) {
        if (loaded) return
        loaded = true
        manifest = try { JSONObject(manifestFile(c).readText(Charsets.UTF_8)) } catch (_: Throwable) { null }
    }

    /** PC 에서 고른 옷 id(폰 선택이 없을 때 화면에 알려 주기용). */
    fun currentPcId(c: Context): String {
        load(c)
        return PetRules.cleanOutfit(manifest?.optString("지금옷"))
    }

    /** 폰에서 따로 고를 수 있는 옷 목록 — (id, 이름, 성별) */
    fun outfits(c: Context): List<Triple<String, String, String>> {
        load(c)
        val a = manifest?.optJSONArray("옷목록") ?: return emptyList()
        val out = ArrayList<Triple<String, String, String>>()
        for (i in 0 until a.length()) {
            val o = a.optJSONObject(i) ?: continue
            val id = PetRules.cleanOutfit(o.optString("id"))
            if (id.isEmpty()) continue
            out.add(Triple(id, o.optString("name").ifEmpty { id }, o.optString("성별")))
        }
        return out
    }

    /** 지금 캐시에 있는 동작 → 파일. 파일이 없거나 크기가 목록과 다르면 그 동작은 뺀다. */
    fun clips(c: Context): Map<String, File> {
        load(c)
        val m = manifest ?: return emptyMap()
        val outfit = m.optJSONObject("옷") ?: return emptyMap()
        val id = PetRules.cleanOutfit(outfit.optString("id"))
        if (id.isEmpty()) return emptyMap()
        val arr = m.optJSONArray("동작") ?: return emptyMap()
        val out = LinkedHashMap<String, File>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val name = PetRules.motion(o.optString("이름"))
            val sha = o.optString("sha256")
            val size = o.optLong("바이트", -1)
            val f = clipFile(c, id, sha, o.optString("파일"))
            if (f.isFile && (size < 0 || f.length() == size)) out[name] = f
        }
        if (!out.containsKey("idle") && out.isNotEmpty()) out["idle"] = out.values.first()
        return out
    }

    fun cachedBytes(c: Context): Long = clips(c).values.distinct().sumOf { it.length() }

    fun statusText(c: Context): String {
        if (status.isNotEmpty()) return status
        val m = clips(c)
        return if (m.isEmpty()) L.s(R.string.pet_status_wait)
        else L.s(R.string.pet_status_cached, m.values.distinct().size, mb(cachedBytes(c)))
    }

    private fun clipDir(c: Context, outfit: String) = File(File(dir(c), "clips"), outfit)
    private fun clipFile(c: Context, outfit: String, sha: String, file: String) =
        File(clipDir(c, outfit), PetRules.fileName(sha, file))

    // ---------------------------------------------------------------- 받기
    /** 목록을 읽고(필요하면) 클립을 받는다. force=false 면 3초 안의 잦은 부름은 건너뛴다. 여러 번 불러도 한 번에 하나만 돈다. */
    fun sync(c: Context, force: Boolean = false) {
        val now = System.currentTimeMillis()
        if (!force && now - lastAt < 3000) return
        if (!busy.compareAndSet(false, true)) return
        lastAt = now
        val app = c.applicationContext
        exec.execute {
            try { doSync(app) } catch (_: Throwable) { status = L.s(R.string.pet_status_fail) }
            finally {
                busy.set(false)
                Bus.post(Bus.Ev.Pet(clips(app).isNotEmpty()))
            }
        }
    }

    private fun doSync(c: Context) {
        val pc = Store.pc(c) ?: return
        val sel = selected(c)
        val path = "/phone/api/pet" + if (sel.isNotEmpty()) "?outfit=" + enc(sel) else ""
        val client = Net.fileClient(pc.fp)
        var json: JSONObject? = null
        var host = ""
        for (h in pc.hosts) {
            try {
                val req = Request.Builder().url(PairRules.baseUrl(h, pc.port) + path)
                    .header("X-Phone-Token", pc.token).build()
                client.newCall(req).execute().use { r ->
                    val j = try { JSONObject(r.body?.string() ?: "{}") } catch (_: Throwable) { JSONObject() }
                    if (r.code == 200 && j.optBoolean("ok")) { json = j; host = h }
                }
            } catch (_: Throwable) { /* 다음 주소 */ }
            if (json != null) break
        }
        val j = json ?: run { status = L.s(R.string.pet_status_fail); return }
        Store.setLast(c, host)
        manifest = j
        saveManifest(c, j)
        val outfit = j.optJSONObject("옷")
        if (outfit == null) { status = L.s(R.string.pet_status_none); return }
        val id = PetRules.cleanOutfit(outfit.optString("id"))
        val arr = j.optJSONArray("동작") ?: JSONArray()
        if (id.isEmpty() || arr.length() == 0) { status = L.s(R.string.pet_status_none); return }

        // 같은 파일을 가리키는 동작은 한 번만 받는다(sha 기준).
        val items = LinkedHashMap<String, JSONObject>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val sha = o.optString("sha256")
            if (sha.isNotEmpty()) items.putIfAbsent(sha.lowercase(), o)
        }
        if (items.isEmpty()) { status = L.s(R.string.pet_status_none); return }
        val totalBytes = items.values.sumOf { it.optLong("바이트", 0) }
        val canGet = !wifiOnly(c) || unmetered(c)
        if (!canGet) {
            status = L.s(R.string.pet_status_wifi)
            return
        }
        var have = 0
        var fail = 0
        for ((sha, o) in items) {
            val target = clipFile(c, id, sha, o.optString("파일"))
            val size = o.optLong("바이트", -1)
            if (target.isFile && (size < 0 || target.length() == size)) { have++; continue }
            if (download(c, pc, client, host, id, PetRules.motion(o.optString("이름")), sha, size, target)) have++ else fail++
        }
        cleanStale(c, id, items)
        status = if (fail == 0) L.s(R.string.pet_status_ok, have, mb(totalBytes))
        else L.s(R.string.pet_status_partial, have, items.size)
    }

    private fun download(c: Context, pc: Store.Pc, client: okhttp3.OkHttpClient, host0: String, outfit: String,
                         motion: String, sha: String, size: Long, target: File): Boolean {
        val hosts = listOf(host0) + pc.hosts.filter { it != host0 }
        val urlPath = "/phone/api/pet/clip?outfit=" + enc(outfit) + "&motion=" + enc(motion)
        for (h in hosts) {
            try {
                val req = Request.Builder().url(PairRules.baseUrl(h, pc.port) + urlPath)
                    .header("X-Phone-Token", pc.token).build()
                val bytes = client.newCall(req).execute().use { r ->
                    if (r.code != 200) null else r.body?.bytes()
                } ?: continue
                if (size >= 0 && bytes.size.toLong() != size) continue
                if (!PetRules.shaOk(Net.sha256(bytes), sha)) continue
                target.parentFile?.mkdirs()
                val tmp = File(target.parentFile, target.name + ".part")
                tmp.writeBytes(bytes)
                if (!tmp.renameTo(target)) { target.delete(); if (!tmp.renameTo(target)) { tmp.delete(); continue } }
                Store.setLast(c, h)
                return true
            } catch (_: Throwable) { /* 다음 주소 */ }
        }
        return false
    }

    /** 이 옷 폴더에서 지금 목록에 없는 옛 파일을 지운다(옷을 바꿔 받아도 저장소가 쌓이지 않게). */
    private fun cleanStale(c: Context, outfit: String, items: Map<String, JSONObject>) {
        val d = clipDir(c, outfit)
        val files = d.listFiles() ?: return
        val keep = items.entries.map { (sha, o) -> PetRules.fileName(sha, o.optString("파일")) }.toSet()
        for (f in files) {
            if (f.isFile && !keep.contains(f.name) && !f.name.endsWith(".part")) {
                try { f.delete() } catch (_: Throwable) { /* 다음에 */ }
            }
        }
    }

    private fun saveManifest(c: Context, j: JSONObject) {
        try {
            val f = manifestFile(c)
            f.parentFile?.mkdirs()
            val tmp = File(f.parentFile, f.name + ".tmp")
            tmp.writeText(j.toString(), Charsets.UTF_8)
            if (!tmp.renameTo(f)) { f.delete(); tmp.renameTo(f) }
        } catch (_: Throwable) { /* 다음에 다시 */ }
    }

    private fun unmetered(c: Context): Boolean {
        return try {
            val cm = c.getSystemService(ConnectivityManager::class.java) ?: return false
            val n = cm.activeNetwork ?: return false
            val cap = cm.getNetworkCapabilities(n) ?: return false
            cap.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
        } catch (_: Throwable) { false }
    }

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
    private fun mb(n: Long) = String.format(Locale.US, "%.1f MB", n / 1_000_000.0)
}