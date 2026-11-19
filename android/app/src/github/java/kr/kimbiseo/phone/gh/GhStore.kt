package kr.kimbiseo.phone.gh

import android.content.Context

/** 김비서 GH 설정 — 이 폰 안에만. 접근성 조작은 기본 꺼짐, 동의는 처음 한 번. (열쇠 값은 기록·로그에 안 남김) */
object GhStore {
    private const val P = "gh"

    private fun sp(c: Context) = c.getSharedPreferences(P, Context.MODE_PRIVATE)

    fun on(c: Context) = sp(c).getBoolean("on", false)
    fun setOn(c: Context, v: Boolean) = sp(c).edit().putBoolean("on", v).apply()

    fun consent(c: Context) = sp(c).getBoolean("consent", false)
    fun setConsent(c: Context, v: Boolean) = sp(c).edit().putBoolean("consent", v).apply()

    fun brainBase(c: Context) = sp(c).getString("brain_base", "") ?: ""
    fun brainModel(c: Context) = sp(c).getString("brain_model", "") ?: ""
    fun brainKey(c: Context) = sp(c).getString("brain_key", "") ?: ""

    fun setBrain(c: Context, base: String, model: String, key: String) {
        sp(c).edit().putString("brain_base", base.trim()).putString("brain_model", model.trim())
            .putString("brain_key", key.trim()).apply()
    }

    /** 풀어야 할 까닭 — 설정 화면에 한 줄로 보여 준다. */
    fun ready(c: Context): String = when {
        !consent(c) -> "consent"
        !on(c) -> "off"
        !GhAccessibilityService.connected() -> "service"
        brainBase(c).isBlank() -> "brain"
        else -> ""
    }
}