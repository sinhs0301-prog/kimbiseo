package kr.kimbiseo.phone.gh
import kr.kimbiseo.phone.BuildConfig

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import kr.kimbiseo.phone.L
import kr.kimbiseo.phone.Lang
import kr.kimbiseo.phone.R
import kr.kimbiseo.phone.Store
import kr.kimbiseo.phone.Ui
import kr.kimbiseo.phone.Ui.dp
import kr.kimbiseo.phone.Ui.lp

/**
 * 김비서 GH 설정 — 앱 안에서 직접 켠다(기본 꺼짐).
 *  켜면 동의(처음 한 번) → 안드로이드 접근성 설정 화면. 두뇌 주소(OpenAI 호환)·모델·열쇠도 여기서 넣는다.
 */
class GhSettingsActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var sw: android.widget.Switch
    private lateinit var baseField: EditText
    private lateinit var modelField: EditText
    private lateinit var keyField: EditText

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(Lang.wrap(newBase))
    }

    private fun dp(v: Int) = dp(this, v)

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        L.init(this)
        window.statusBarColor = Ui.BG; window.navigationBarColor = Ui.BG
        val root = FrameLayout(this).apply { setBackgroundColor(Ui.BG) }
        val scroll = ScrollView(this)
        val p = Ui.col(this, 12).apply { setPadding(dp(22), dp(36), dp(22), dp(28)) }
        p.addView(Ui.button(this, getString(R.string.gh_back), Ui.Kind.QUIET) { finish() }.apply { gravity = Gravity.START }, lp())
        p.addView(Ui.text(this, getString(R.string.gh_settings_title), 24f, Ui.TEXT, true))
        p.addView(Ui.text(this, getString(R.string.gh_settings_intro), 14f, Ui.TEXT2))

        // 켜기 — 기본 꺼짐.
        val c1 = Ui.card(this, 8)
        sw = android.widget.Switch(this).apply {
            text = getString(R.string.gh_switch); setTextColor(Ui.TEXT); textSize = 15f
            val st = arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf())
            thumbTintList = ColorStateList(st, intArrayOf(Ui.TEXT, Ui.TEXT2))
            trackTintList = ColorStateList(st, intArrayOf(Ui.ACCENT_FILL, Ui.RAISED))
            isChecked = GhStore.on(this@GhSettingsActivity)
            setOnCheckedChangeListener { _, v -> onToggle(v) }
        }
        c1.addView(sw, lp())
        c1.addView(Ui.text(this, getString(R.string.gh_switch_help), 13f, Ui.MUTED))
        status = Ui.text(this, "", 14f, Ui.TEXT2)
        c1.addView(status, lp())
        c1.addView(Ui.button(this, getString(R.string.gh_open_accessibility), Ui.Kind.SECONDARY) { openAccessibility() }, lp())
        c1.addView(Ui.button(this, getString(R.string.gh_consent_view), Ui.Kind.QUIET) {
            startActivityForResult(Intent(this, GhConsentActivity::class.java), 71)
        }, lp())
        p.addView(c1, lp())

        // 두뇌(OpenAI 호환)
        val c2 = Ui.card(this, 8)
        c2.addView(Ui.text(this, getString(R.string.gh_brain_title), 16f, Ui.TEXT, true))
        c2.addView(Ui.text(this, getString(R.string.gh_brain_help), 13f, Ui.MUTED))
        val pc = Store.pc(this)
        val hint = if (pc != null) getString(R.string.gh_brain_hint_pc, pc.hosts.firstOrNull() ?: "") else getString(R.string.gh_brain_hint)
        baseField = Ui.field(this, hint, value = GhStore.brainBase(this))
        modelField = Ui.field(this, getString(R.string.gh_brain_model_hint), value = GhStore.brainModel(this))
        keyField = Ui.field(this, getString(R.string.gh_brain_key_hint), value = GhStore.brainKey(this)).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        }
        c2.addView(baseField, lp())
        c2.addView(modelField, lp())
        c2.addView(keyField, lp())
        c2.addView(Ui.button(this, getString(R.string.gh_save), Ui.Kind.PRIMARY) {
            GhStore.setBrain(this, baseField.text.toString(), modelField.text.toString(), keyField.text.toString())
            Toast.makeText(this, getString(R.string.gh_saved), Toast.LENGTH_SHORT).show()
            refresh()
        }, lp())
        c2.addView(Ui.text(this, getString(R.string.gh_brain_note), 12f, Ui.MUTED))
        p.addView(c2, lp())

        val c3 = Ui.card(this, 8)
        c3.addView(Ui.text(this, getString(R.string.gh_targets_title), 16f, Ui.TEXT, true))
        c3.addView(Ui.text(this, getString(R.string.gh_targets), 14f, Ui.TEXT2))
        c3.addView(Ui.text(this, getString(R.string.gh_safety_title), 16f, Ui.TEXT, true))
        c3.addView(Ui.text(this, getString(R.string.gh_safety), 14f, Ui.TEXT2))
        c3.addView(Ui.text(this, getString(R.string.gh_solo_note), 13f, Ui.MUTED))
        p.addView(c3, lp())
        p.addView(Ui.text(this, getString(R.string.gh_version, BuildConfig.VERSION_NAME), 12f, Ui.MUTED))

        scroll.addView(p, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        root.addView(scroll, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)
        refresh()
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        if (!::status.isInitialized) return
        val reason = GhStore.ready(this)
        status.text = getString(when (reason) {
            "consent" -> R.string.gh_need_consent
            "off" -> R.string.gh_need_switch
            "service" -> R.string.gh_need_service
            "brain" -> R.string.gh_need_brain
            else -> R.string.gh_ready
        })
        val on = GhStore.on(this)
        if (sw.isChecked != on) {
            sw.setOnCheckedChangeListener(null); sw.isChecked = on
            sw.setOnCheckedChangeListener { _, v -> onToggle(v) }
        }
        status.setTextColor(if (reason.isEmpty()) Ui.OK else Ui.TEXT2)
    }

    private fun onToggle(v: Boolean) {
        if (v) {
            if (!GhStore.consent(this)) {
                startActivityForResult(Intent(this, GhConsentActivity::class.java), 71)
            } else {
                GhStore.setOn(this, true)
                if (!GhAccessibilityService.connected()) openAccessibility()
            }
        } else GhStore.setOn(this, false)
        refresh()
    }

    private fun openAccessibility() {
        try { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        catch (_: Throwable) { Toast.makeText(this, getString(R.string.gh_no_settings), Toast.LENGTH_SHORT).show() }
    }

    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        if (req == 71) {
            if (res == RESULT_OK) {
                GhStore.setOn(this, true)
                if (!GhAccessibilityService.connected()) openAccessibility()
            } else if (!GhStore.consent(this)) GhStore.setOn(this, false)
            refresh()
        }
    }
}