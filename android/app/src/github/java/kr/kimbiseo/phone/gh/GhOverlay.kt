package kr.kimbiseo.phone.gh
import kr.kimbiseo.phone.Lang
import kr.kimbiseo.phone.R

import android.accessibilityservice.AccessibilityService
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.TextView

/** 조작하는 동안 화면 위에 떠 있는 '김비서 조작 중 — 멈추기' 단추(접근성 오버레이). 누르면 즉시 멈춤. */
class GhOverlay(private val svc: AccessibilityService, private val onStop: () -> Unit) {
    private var view: View? = null

    private fun dp(v: Int) = (v * svc.resources.displayMetrics.density + 0.5f).toInt()

    fun show() {
        if (view != null) return
        val tv = TextView(svc).apply {
            text = Lang.wrap(svc).getString(R.string.gh_overlay)
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            setPadding(dp(16), dp(10), dp(16), dp(10))
            background = GradientDrawable().apply {
                setColor(0xF2D1004A.toInt()); cornerRadius = dp(22).toFloat()
            }
            isClickable = true
            setOnClickListener { onStop() }
        }
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply { gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL; y = dp(56) }
        try {
            svc.getSystemService(WindowManager::class.java).addView(tv, lp)
            view = tv
        } catch (_: Throwable) { view = null }
    }

    fun hide() {
        val v = view ?: return
        view = null
        try { svc.getSystemService(WindowManager::class.java).removeView(v) } catch (_: Throwable) {}
    }
}