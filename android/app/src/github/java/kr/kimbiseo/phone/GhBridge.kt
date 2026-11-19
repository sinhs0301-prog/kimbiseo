package kr.kimbiseo.phone

import android.app.Activity
import android.content.Intent
import android.widget.LinearLayout
import kr.kimbiseo.phone.gh.GhChatActivity
import kr.kimbiseo.phone.gh.GhPhrase
import kr.kimbiseo.phone.gh.GhSettingsActivity
import kr.kimbiseo.phone.gh.GhStore

/**
 * 깃허브판(김비서 GH) — main 화면이 부르는 작은 창구.
 *  플레이판의 같은 이름 GhBridge 는 no-op 이라, 플레이 빌드에는 gh 패키지·접근성 문자열이 안 들어간다.
 */
object GhBridge {
    val available: Boolean = true

    fun handles(text: String): Boolean = GhPhrase.parse(text) != null

    /** 대화창에 장바구니 문장이 들어오면 GH 화면으로 넘긴다(모델·PC 대화는 하지 않음). */
    fun maybeRun(a: Activity, text: String): Boolean {
        if (!handles(text)) return false
        a.startActivity(Intent(a, GhChatActivity::class.java).putExtra("gh_text", text).putExtra("gh_auto", true))
        return true
    }

    fun addModeCard(a: Activity, parent: LinearLayout) {
        val c = Ui.card(a, 8)
        c.addView(Ui.text(a, a.getString(R.string.gh_card_title), 19f, Ui.TEXT, true))
        c.addView(Ui.text(a, a.getString(R.string.gh_card_desc), 14f, Ui.TEXT2))
        c.addView(Ui.text(a, state(a), 13f, Ui.MUTED))
        c.addView(Ui.button(a, a.getString(R.string.gh_card_btn), Ui.Kind.PRIMARY) {
            a.startActivity(Intent(a, GhChatActivity::class.java))
        }, Ui.lp())
        parent.addView(c, Ui.lp())
    }

    fun addSettings(a: Activity, parent: LinearLayout) {
        val c = Ui.card(a, 8)
        c.addView(Ui.text(a, a.getString(R.string.gh_card_title), 16f, Ui.TEXT, true))
        c.addView(Ui.text(a, a.getString(R.string.gh_card_desc), 13f, Ui.TEXT2))
        c.addView(Ui.text(a, state(a), 13f, Ui.MUTED))
        val row = Ui.row(a, 8)
        row.addView(Ui.button(a, a.getString(R.string.gh_settings_btn), Ui.Kind.SECONDARY) {
            a.startActivity(Intent(a, GhSettingsActivity::class.java))
        }, Ui.lp(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(Ui.button(a, a.getString(R.string.gh_card_btn), Ui.Kind.PRIMARY) {
            a.startActivity(Intent(a, GhChatActivity::class.java))
        }, Ui.lp(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        c.addView(row, Ui.lp())
        parent.addView(c, Ui.lp())
    }

    fun testHooks(a: Activity, i: Intent?) {}

    private fun state(a: Activity): String = a.getString(when (GhStore.ready(a)) {
        "consent" -> R.string.gh_need_consent
        "off" -> R.string.gh_need_switch
        "service" -> R.string.gh_need_service
        "brain" -> R.string.gh_need_brain
        else -> R.string.gh_ready
    })
}