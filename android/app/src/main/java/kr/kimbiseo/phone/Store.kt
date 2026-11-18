package kr.kimbiseo.phone

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * 짝지은 PC 정보(이 폰 안에만). 기기 토큰은 안드로이드 키 저장소(AndroidKeyStore)의 AES 열쇠로 암호화해 둔다
 * (열쇠는 폰 밖으로 못 나감 · 앱을 지우면 같이 사라짐 · allowBackup=false 라 백업에도 안 들어감).
 */
object Store {
    private const val P = "pc"
    private const val KEY = "kimbiseo_token"

    data class Pc(val hosts: List<String>, val port: Int, val fp: String, val device: String, val name: String, val token: String)

    private fun sp(c: Context) = c.getSharedPreferences(P, Context.MODE_PRIVATE)

    fun pc(c: Context): Pc? {
        val s = sp(c)
        val enc = s.getString("token", "") ?: ""
        if (enc.isEmpty()) return null
        val tok = try { dec(enc) } catch (_: Throwable) { return null }
        val hosts = (s.getString("hosts", "") ?: "").split(',').filter { it.isNotEmpty() }
        val last = s.getString("last", "") ?: ""
        val ordered = if (last in hosts) listOf(last) + hosts.filter { it != last } else hosts
        return Pc(ordered, s.getInt("port", 8874), s.getString("fp", "") ?: "", s.getString("device", "") ?: "", s.getString("name", "") ?: "", tok)
    }

    fun save(c: Context, hosts: List<String>, port: Int, fp: String, device: String, name: String, token: String) {
        sp(c).edit().putString("hosts", hosts.joinToString(",")).putInt("port", port).putString("fp", fp).putString("device", device)
            .putString("name", name).putString("token", enc(token)).putString("last", hosts.firstOrNull() ?: "").apply()
    }

    fun setLast(c: Context, host: String) { sp(c).edit().putString("last", host).apply() }

    fun clear(c: Context) {
        sp(c).edit().clear().apply()
        try { KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.deleteEntry(KEY) } catch (_: Throwable) {}
    }

    // 간단한 화면 설정(비밀 아님)
    fun flag(c: Context, k: String, def: Boolean) = c.getSharedPreferences("ui", Context.MODE_PRIVATE).getBoolean(k, def)
    fun setFlag(c: Context, k: String, v: Boolean) { c.getSharedPreferences("ui", Context.MODE_PRIVATE).edit().putBoolean(k, v).apply() }
    fun str(c: Context, k: String, def: String) = c.getSharedPreferences("ui", Context.MODE_PRIVATE).getString(k, def) ?: def
    fun setStr(c: Context, k: String, v: String) { c.getSharedPreferences("ui", Context.MODE_PRIVATE).edit().putString(k, v).apply() }

    /** 쓰는 방식: "pc"(PC 연결) · "solo"(폰 단독). 비어 있으면 예전처럼 PC 가 있으면 pc, 없으면 첫 화면에서 고른다. */
    fun mode(c: Context): String {
        val m = str(c, "mode", "")
        if (m == "pc" || m == "solo") return m
        return if (pc(c) != null) "pc" else ""
    }

    fun setMode(c: Context, m: String) { setStr(c, "mode", m) }

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(KEY, null) as? SecretKey)?.let { return it }
        val g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        g.init(KeyGenParameterSpec.Builder(KEY, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build())
        return g.generateKey()
    }

    private fun enc(s: String): String {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key())
        val ct = c.doFinal(s.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(c.iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(ct, Base64.NO_WRAP)
    }

    private fun dec(s: String): String {
        val (iv, ct) = s.split(':', limit = 2).map { Base64.decode(it, Base64.NO_WRAP) }
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
        return String(c.doFinal(ct), Charsets.UTF_8)
    }
}
