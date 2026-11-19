package kr.kimbiseo.phone.gh

import android.app.Activity
import android.content.Context
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ScrollView
import kr.kimbiseo.phone.L
import kr.kimbiseo.phone.Lang
import kr.kimbiseo.phone.R
import kr.kimbiseo.phone.Ui
import kr.kimbiseo.phone.Ui.dp
import kr.kimbiseo.phone.Ui.lp

/** 첫 사용 동의 — "화면을 읽고 대신 누릅니다. 결제·주문은 절대 안 누름" (한·영·일·중). */
class GhConsentActivity : Activity() {
    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(Lang.wrap(newBase))
    }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        L.init(this)
        window.statusBarColor = Ui.BG; window.navigationBarColor = Ui.BG
        val root = FrameLayout(this).apply { setBackgroundColor(Ui.BG) }
        val scroll = ScrollView(this)
        val p = Ui.col(this, 14).apply { setPadding(dp(this@GhConsentActivity, 24), dp(this@GhConsentActivity, 40),
            dp(this@GhConsentActivity, 24), dp(this@GhConsentActivity, 32)) }
        p.addView(Ui.text(this, getString(R.string.gh_consent_title), 24f, Ui.TEXT, true))
        p.addView(Ui.text(this, getString(R.string.gh_consent_body), 16f, Ui.TEXT2))
        p.addView(Ui.text(this, getString(R.string.gh_consent_safe), 14f, Ui.ACCENT))
        p.addView(Ui.text(this, getString(R.string.gh_consent_targets), 13f, Ui.MUTED))
        p.addView(Ui.button(this, getString(R.string.gh_consent_yes), Ui.Kind.PRIMARY) {
            GhStore.setConsent(this, true)
            setResult(RESULT_OK); finish()
        }, lp())
        p.addView(Ui.button(this, getString(R.string.common_cancel), Ui.Kind.QUIET) {
            setResult(RESULT_CANCELED); finish()
        }, lp())
        scroll.addView(p, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        root.addView(scroll, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)
    }
}