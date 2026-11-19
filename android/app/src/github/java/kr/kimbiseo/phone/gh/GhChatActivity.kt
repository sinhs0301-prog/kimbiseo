package kr.kimbiseo.phone.gh

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ScrollView
import android.widget.TextView
import kr.kimbiseo.phone.Bus
import kr.kimbiseo.phone.BuildConfig
import kr.kimbiseo.phone.Doer
import kr.kimbiseo.phone.L
import kr.kimbiseo.phone.Lang
import kr.kimbiseo.phone.R
import kr.kimbiseo.phone.Store
import kr.kimbiseo.phone.Ui
import kr.kimbiseo.phone.Ui.dp
import kr.kimbiseo.phone.Ui.lp
import org.json.JSONObject

/**
 * 김비서 GH — "쿠팡에서 삼다수 2L 장바구니 담아줘"라고 하면 검색 화면을 열고,
 * 접근성으로 화면을 읽어 두뇌가 고른 곳을 한 걸음씩 눌러 장바구니에 담는다.
 * 결제·주문은 코드가 막는다(GhSafety). 성공하면 "장바구니에 담았어요, 결제는 직접 해 주세요".
 */
class GhChatActivity : Activity() {
    private lateinit var root: FrameLayout
    private lateinit var input: EditText
    private lateinit var status: TextView
    private lateinit var logView: TextView
    private var pending = ""
    private var slowMs = 0L
    private var maxSteps = GhRunner.MAX_STEPS
    private var direct = false
    private var auto = false
    private var openedUrl = ""
    private val main = Handler(Looper.getMainLooper())

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(Lang.wrap(newBase))
    }

    private fun dp(v: Int) = dp(this, v)

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        L.init(this)
        window.statusBarColor = Ui.BG; window.navigationBarColor = Ui.BG
        root = FrameLayout(this).apply { setBackgroundColor(Ui.BG) }
        val scroll = ScrollView(this)
        val p = Ui.col(this, 12).apply { setPadding(dp(22), dp(36), dp(22), dp(28)) }
        p.addView(Ui.text(this, getString(R.string.gh_title), 24f, Ui.TEXT, true))
        p.addView(Ui.text(this, getString(R.string.gh_intro), 14f, Ui.TEXT2))
        input = Ui.field(this, getString(R.string.gh_input_hint)).apply {
            setText(getString(R.string.gh_example)); imeOptions = EditorInfo.IME_ACTION_DONE
            setOnEditorActionListener { _, a, _ -> if (a == EditorInfo.IME_ACTION_DONE) { start(input.text.toString()); true } else false }
        }
        p.addView(input, lp())
        val row = Ui.row(this, 8)
        row.addView(Ui.button(this, getString(R.string.gh_start), Ui.Kind.PRIMARY) { start(input.text.toString()) }, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1.4f))
        row.addView(Ui.button(this, getString(R.string.gh_stop), Ui.Kind.SECONDARY) { GhRunner.stop(); render(getString(R.string.gh_stopping)) }, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        p.addView(row, lp())
        status = Ui.text(this, "", 15f, Ui.TEXT2)
        p.addView(status, lp())
        logView = Ui.text(this, "", 12f, Ui.MUTED).apply { typeface = android.graphics.Typeface.MONOSPACE; maxLines = 12 }
        p.addView(logView, lp())
        val row2 = Ui.row(this, 8)
        row2.addView(Ui.button(this, getString(R.string.gh_settings_btn), Ui.Kind.SECONDARY) {
            startActivity(Intent(this, GhSettingsActivity::class.java))
        }, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row2.addView(Ui.button(this, getString(R.string.gh_close), Ui.Kind.QUIET) { finish() }, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        p.addView(row2, lp())
        p.addView(Ui.text(this, getString(R.string.gh_footer, BuildConfig.VERSION_NAME), 12f, Ui.MUTED))
        scroll.addView(p, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        root.addView(scroll, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)

        GhRunner.listener = { s -> runOnUiThread { render(s) } }
        if (GhRunner.running) render(GhRunner.last)
        handleTest(intent)
        // 끝났을 때 알림도 보이게(안드로이드 13+).
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 91)
    }

    override fun onNewIntent(i: Intent) {
        super.onNewIntent(i); setIntent(i); handleTest(i)
    }

    override fun onResume() {
        super.onResume()
        Bus.visible = true
        render(GhRunner.last)
    }

    override fun onPause() { Bus.visible = false; super.onPause() }

    override fun onDestroy() {
        GhRunner.listener = null
        super.onDestroy()
    }

    /** 시험판/배포판 모두: adb 시험 값. (앱 화면에서도 그대로 씀) */
    private fun handleTest(i: Intent?) {
        if (i == null) return
        // 이 번 실행 값만 쓰도록 지난 시험 값을 지운다.
        direct = false; auto = false; openedUrl = ""; slowMs = 0L; maxSteps = GhRunner.MAX_STEPS; pending = ""
        i.getStringExtra("test_gh_lang")?.let { code ->
            i.removeExtra("test_gh_lang")
            Store.setStr(this, "lang", code)
            recreate()
            return
        }
        if (tb(i, "test_gh_no_consent")) GhStore.setConsent(this, false)
        if (tb(i, "test_gh_on")) GhStore.setOn(this, true)
        if (tb(i, "test_gh_consent")) GhStore.setConsent(this, true)
        i.getStringExtra("test_gh_brain")?.let { u ->
            GhStore.setBrain(this, u, i.getStringExtra("test_gh_model") ?: "test", i.getStringExtra("test_gh_key") ?: "")
        }
        i.getStringExtra("test_gh_goal")?.let { pending = it }
        i.getStringExtra("gh_text")?.let { pending = it }
        if (tb(i, "gh_auto")) auto = true
        (i.getStringExtra("test_gh_slow") ?: "").toLongOrNull()?.let { slowMs = it }
        (i.getStringExtra("test_gh_max") ?: "").toIntOrNull()?.let { maxSteps = it }
        if (tb(i, "test_gh_direct")) { direct = true; auto = true }
        if (tb(i, "test_gh_auto")) auto = true
        i.getStringExtra("test_gh_url")?.let { openedUrl = it; direct = true; auto = true }
        if (pending.isNotBlank()) input.setText(pending)

        if (openedUrl.isNotBlank()) {
            main.postDelayed({ openChrome(openedUrl) }, 600)
            main.postDelayed({ runDirect() }, 4500)
        } else if (auto) {
            main.postDelayed({ start(pending.ifBlank { input.text.toString() }) }, 700)
        }
    }

    private fun tb(i: Intent, k: String): Boolean =
        i.getBooleanExtra(k, false) || (i.getStringExtra(k) ?: "").lowercase() in listOf("1", "true", "yes")

    private fun render(s: String) {
        if (s.isBlank()) return
        status.text = s
        val old = logView.text.toString()
        val next = (if (old.isBlank()) "" else old + "\n") + s
        logView.text = next.lines().takeLast(12).joinToString("\n")
    }

    private fun start(text: String) {
        if (GhRunner.running) { render(getString(R.string.gh_busy)); return }
        // 시험/직접 실행: 문장 해석 없이 지금 화면에서 바로.
        if (direct) { runDirect(); return }
        val ask = GhPhrase.parse(text)
        if (ask == null) { render(getString(R.string.gh_need_cart)); return }
        if (!GhStore.consent(this)) {
            pending = text
            startActivityForResult(Intent(this, GhConsentActivity::class.java), 72)
            return
        }
        val reason = GhStore.ready(this)
        if (reason.isNotEmpty()) { showNeed(reason); return }

        render(getString(R.string.gh_opening, ask.query))
        // 동의 화면에서 돌아온 직후(onActivityResult)에는 아직 onResume 전이라, 열기 알림 대신 바로 열도록.
        Bus.visible = true
        val r = try { Doer(this).run(JSONObject().put("do", "search").put("app", ask.app).put("query", ask.query)) }
                catch (t: Throwable) { JSONObject().put("ok", false).put("말", t.message ?: t.javaClass.simpleName) }
        if (!r.optBoolean("ok")) { render(r.optString("말")); return }
        val goal = ask.query
        main.postDelayed({ startRunner(goal) }, 3500)
    }

    private fun runDirect() {
        val goal = pending.ifBlank { input.text.toString() }.ifBlank { getString(R.string.gh_example) }
        if (!GhStore.consent(this)) { startActivityForResult(Intent(this, GhConsentActivity::class.java), 72); return }
        val reason = GhStore.ready(this)
        if (reason.isNotEmpty()) { showNeed(reason); return }
        startRunner(goal)
    }

    private fun startRunner(goal: String) {
        val svc = GhAccessibilityService.inst ?: run { showNeed("service"); return }
        Log.i("KimbiseoGh", "start goal=$goal slow=$slowMs max=$maxSteps")
        GhRunner.start(svc, goal, slowMs, maxSteps)
    }

    private fun openChrome(url: String) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).setPackage("com.android.chrome")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            render(getString(R.string.gh_opening_test))
        } catch (t: Throwable) { render(getString(R.string.gh_error, t.javaClass.simpleName)) }
    }

    private fun showNeed(reason: String) {
        val msg = getString(when (reason) {
            "consent" -> R.string.gh_need_consent
            "off" -> R.string.gh_need_switch
            "service" -> R.string.gh_need_service
            "brain" -> R.string.gh_need_brain
            else -> R.string.gh_need_switch
        })
        render(msg)
        AlertDialog.Builder(this).setMessage(msg)
            .setPositiveButton(getString(R.string.gh_open_settings)) { _, _ -> startActivity(Intent(this, GhSettingsActivity::class.java)) }
            .setNegativeButton(android.R.string.cancel, null).show()
    }

    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        if (req == 72 && res == RESULT_OK) start(pending.ifBlank { input.text.toString() })
    }
}