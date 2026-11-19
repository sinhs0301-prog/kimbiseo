package kr.kimbiseo.phone.gh

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * 김비서 GH 의 손 — 화면 글자를 읽고(rootInActiveWindow), 한 걸음씩 누르거나 글자를 넣는다.
 *  서비스 자체가 켜져 있는 동안 살아 있으므로, 대상 앱이 앞에 있어도 조작을 이어 갈 수 있다.
 *  이 파일·서비스·설정 XML 은 github 플레이버에만 있다(플레이판에는 없음).
 */
class GhAccessibilityService : AccessibilityService() {
    companion object {
        private const val TAG = "KimbiseoGh"
        @Volatile var inst: GhAccessibilityService? = null
        fun connected(): Boolean = inst != null
    }

    data class Node(
        val i: Int, val text: String, val desc: String, val cls: String,
        val clickable: Boolean, val editable: Boolean, val password: Boolean, val bounds: Rect, val raw: AccessibilityNodeInfo
    ) {
        val label: String get() = listOf(text, desc).filter { it.isNotBlank() }.joinToString(" ").ifBlank { cls.substringAfterLast('.') }
    }

    @Volatile private var lastPkg = ""

    override fun onServiceConnected() {
        super.onServiceConnected()
        inst = this
        Log.i(TAG, "accessibility connected")
    }

    override fun onAccessibilityEvent(e: AccessibilityEvent?) {
        if (e == null) return
        if (e.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED ||
            e.eventType == AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED) {
            val p = e.packageName?.toString().orEmpty()
            if (p.isNotBlank()) lastPkg = p
        }
    }

    override fun onInterrupt() {}

    override fun onDestroy() {
        if (inst === this) inst = null
        Log.i(TAG, "accessibility destroyed")
        super.onDestroy()
    }

    /** 지금 앞 창의 패키지(없으면 최근 창 상태). */
    fun frontPackage(): String = try { rootInActiveWindow?.packageName?.toString() ?: lastPkg } catch (_: Throwable) { lastPkg }

    /** 화면 글자 트리 — 깊이 25, 80개까지. 글자·설명·누를 수 있음·글자 넣을 수 있음만. */
    fun scan(): List<Node> {
        val root = try { rootInActiveWindow } catch (_: Throwable) { null } ?: return emptyList()
        val out = ArrayList<Node>(80)
        fun walk(n: AccessibilityNodeInfo, depth: Int) {
            if (depth > 25 || out.size >= 80) return
            val t = n.text?.toString()?.trim().orEmpty().take(120)
            val d = n.contentDescription?.toString()?.trim().orEmpty().take(120)
            val cls = n.className?.toString().orEmpty()
            val r = Rect(); n.getBoundsInScreen(r)
            val shown = try { n.isVisibleToUser } catch (_: Throwable) { true }
            if (shown && r.width() > 0 && r.height() > 0 && (t.isNotEmpty() || d.isNotEmpty() || n.isClickable || n.isEditable))
                out.add(Node(out.size, t, d, cls, n.isClickable, n.isEditable, try { n.isPassword } catch (_: Throwable) { false }, r, n))
            for (k in 0 until n.childCount) {
                val ch = try { n.getChild(k) } catch (_: Throwable) { null } ?: continue
                walk(ch, depth + 1)
            }
        }
        walk(root, 0)
        return out
    }

    /** 누르기 — ACTION_CLICK, 안 되면 그 자리를 손가락으로 한 번. */
    fun tap(n: Node): Boolean {
        val ok = try { n.raw.performAction(AccessibilityNodeInfo.ACTION_CLICK) } catch (_: Throwable) { false }
        if (ok) return true
        val cx = n.bounds.centerX().toFloat(); val cy = n.bounds.centerY().toFloat()
        if (cx <= 0f || cy <= 0f) return false
        return try {
            val path = Path().apply { moveTo(cx, cy) }
            val g = GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, 60)).build()
            dispatchGesture(g, null, null)
        } catch (_: Throwable) { false }
    }

    /** 글자 넣기 — ACTION_SET_TEXT(포커스 준 뒤 한 번 더). */
    fun type(n: Node, text: String): Boolean {
        val args = Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) }
        return try {
            if (n.raw.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) true
            else { n.raw.performAction(AccessibilityNodeInfo.ACTION_FOCUS); n.raw.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args) }
        } catch (_: Throwable) { false }
    }

    fun back(): Boolean = try { performGlobalAction(GLOBAL_ACTION_BACK) } catch (_: Throwable) { false }

    fun swipeDown(): Boolean = try {
        val w = resources.displayMetrics.widthPixels.toFloat(); val h = resources.displayMetrics.heightPixels.toFloat()
        val path = Path().apply { moveTo(w * 0.5f, h * 0.75f); lineTo(w * 0.5f, h * 0.30f) }
        val g = GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, 300)).build()
        dispatchGesture(g, null, null)
    } catch (_: Throwable) { false }
}