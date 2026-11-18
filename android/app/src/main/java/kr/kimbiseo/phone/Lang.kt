package kr.kimbiseo.phone

import android.content.Context
import android.content.res.Configuration
import android.os.Build
import java.util.Locale

/**
 * 앱 언어 — 한국어·English·日本語·中文 만 쓴다(화면 values-*, 지시문, 받아쓰기, 목소리).
 *  폰 언어가 이 넷 중 하나면 그 언어, 아니면 English. 설정에서 직접 고르면 그 언어(Store "lang").
 *  화면은 attachBaseContext 에서 이 언어로 리소스를 고정해, 폰 언어가 프랑스어여도 English 가 나오게 한다.
 */
object Lang {
    val CODES = listOf("ko", "en", "ja", "zh")

    fun resolve(tag: String?): String {
        val t = (tag ?: "").lowercase(Locale.ROOT)
        return when {
            t.startsWith("ko") -> "ko"
            t.startsWith("ja") -> "ja"
            t.startsWith("zh") -> "zh"
            t.startsWith("en") -> "en"
            else -> "en"
        }
    }

    /** 설정에서 고른 언어("auto" 면 폰 언어). */
    fun app(c: Context): String {
        val pref = Store.str(c, "lang", "auto")
        if (pref in CODES) return pref
        return resolve(sysTag(c))
    }

    fun sysTag(c: Context): String {
        val loc = if (Build.VERSION.SDK_INT >= 24) c.resources.configuration.locales[0]
                  else @Suppress("DEPRECATION") c.resources.configuration.locale
        return loc.language ?: "en"
    }

    fun locale(code: String): Locale = when (code) {
        "ko" -> Locale.KOREAN
        "ja" -> Locale.JAPANESE
        "zh" -> Locale.SIMPLIFIED_CHINESE
        else -> Locale.ENGLISH
    }

    /** 받아쓰기·목소리에 넘기는 언어 꼬리표 */
    fun bcp47(code: String): String = when (code) {
        "ko" -> "ko-KR"
        "ja" -> "ja-JP"
        "zh" -> "zh-CN"
        else -> "en-US"
    }

    /** 화면 리소스 언어를 고정한 Context. (지원하지 않는 폰 언어 → English) */
    fun wrap(base: Context): Context {
        val code = app(base)
        val cfg = Configuration(base.resources.configuration)
        cfg.setLocale(locale(code))
        return base.createConfigurationContext(cfg)
    }
}