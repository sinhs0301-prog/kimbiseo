package kr.kimbiseo.phone

import android.app.Activity
import android.content.Intent
import android.widget.LinearLayout

/** 플레이판 — 김비서 GH 기능 없음(전부 no-op). 접근성 클래스·문자열·화면이 플레이 APK/AAB 에 안 들어간다. */
object GhBridge {
    val available: Boolean = false
    fun handles(text: String): Boolean = false
    fun maybeRun(a: Activity, text: String): Boolean = false
    fun addModeCard(a: Activity, parent: LinearLayout) {}
    fun addSettings(a: Activity, parent: LinearLayout) {}
    fun testHooks(a: Activity, i: Intent?) {}
}