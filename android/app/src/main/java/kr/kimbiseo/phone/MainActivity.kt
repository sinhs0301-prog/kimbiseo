package kr.kimbiseo.phone

import android.Manifest
import android.app.Activity
import android.app.Dialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Rect
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.google.zxing.integration.android.IntentIntegrator
import org.json.JSONObject
import kr.kimbiseo.phone.Ui.dp
import kr.kimbiseo.phone.Ui.lp

/**
 * 화면 셋: 짝짓기(처음) · 대화(자막·글로 말하기·마이크·통역) · 설정(짝 지우기·인사).
 *  '실행할까요?' 단추는 대화 화면 위에 뜬다(PC 김비서가 위험한 일을 하기 전에 물을 때).
 */
class MainActivity : Activity() {
    private lateinit var root: FrameLayout
    private var pending: PairInfo? = null
    private var screen = ""
    private var log: LinearLayout? = null
    private var logScroll: ScrollView? = null
    private var stateText: TextView? = null
    private var stateDot: View? = null
    private var talkBtn: android.widget.Button? = null
    private var micBtn: android.widget.Button? = null
    private var level: View? = null
    private var interpBox: LinearLayout? = null
    private var interpOpen = false
    private var askDialog: Dialog? = null
    private var askId = ""
    private var afterMic: (() -> Unit)? = null
    private var petView: PetView? = null
    private var petMotion = ""
    private var petGreeted = false
    private var petStatusText: TextView? = null

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(Lang.wrap(newBase))
    }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        L.init(this)
        window.statusBarColor = Ui.BG; window.navigationBarColor = Ui.BG
        root = FrameLayout(this).apply { setBackgroundColor(Ui.BG) }
        setContentView(root)
        fitKeyboard()
        handle(intent)
        if (screen.isEmpty()) {
            if (pending == null && Store.mode(this) == "solo") { openSolo(); return }
            show()
        }
    }

    private fun openSolo() {
        val i = Intent(this, SoloActivity::class.java)
        val test = intent?.extras?.keySet()?.any { it.startsWith("test_solo_") } == true
        intent?.extras?.let { i.putExtras(it) }    // 시험용 adb 값(test_solo_*)을 그대로 넘김
        if (test) {
            // 시험: 항상 새 화면으로(엔진을 다시 올림)
            startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        } else {
            // 평소: 이미 떠 있는 폰 단독 화면을 앞으로 — 모델을 다시 올리지 않는다.
            startActivity(i.addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
        }
        finish()
    }

    override fun onNewIntent(i: Intent) { super.onNewIntent(i); setIntent(i); handle(i) }

    override fun onResume() {
        super.onResume()
        Bus.visible = true
        Bus.listener = ::onEv
        if (screen == "talk") { redrawLog(); onEv(Bus.state); Bus.ask?.let { showAsk(it) }; petView?.resume(); drawPet(false); PetStore.sync(this) }
    }

    override fun onPause() { Bus.visible = false; Bus.listener = null; petView?.pause(); super.onPause() }

    private fun handle(i: Intent?) {
        val d = i?.dataString
        if (d != null && d.startsWith("kimbiseo://")) {
            val p = PairRules.parse(d)
            pending = p
            screen = ""; show(if (p == null) getString(R.string.pair_qr_invalid) else null)
            return
        }
        if (BuildConfig.TEST_HOOKS && i != null) testHooks(i)
    }

    /** 시험판만: adb 로 짝짓기·말 넣기·글 보내기·확인 답 */
    private fun testHooks(i: Intent) {
        if (i.getBooleanExtra("test_mode_solo", false)) Store.setMode(this, "solo")
        i.getStringExtra("test_pair")?.let { u -> PairRules.parse(u)?.let { p -> pending = p; if (i.getBooleanExtra("test_pair_auto", false)) doPair(p) else show() } }
        if (i.getBooleanExtra("test_start", false)) startTalk()
        i.getStringExtra("test_feed")?.let { TalkService.me?.testFeed(it) }
        i.getStringExtra("test_text")?.let { TalkService.me?.sendText(it) }
        i.getStringExtra("test_answer")?.let { a -> Bus.ask?.let { TalkService.me?.answer(it.id, a == "yes"); askDialog?.dismiss() } }
        if (i.getBooleanExtra("test_interp", false)) { interpOpen = true; show() }
        i.getStringExtra("test_interp_lang")?.let { TalkService.me?.interp(it != "off", if (it == "off") "" else it) }
        if (i.getBooleanExtra("test_settings", false)) { screen = "settings"; show() }
        if (i.getBooleanExtra("test_talk", false)) { screen = ""; show() }
        if (i.getBooleanExtra("test_stop", false)) TalkService.me?.stopTalk()
        // 폰 일 바로 해 보기(PC 없이): {"do":"navigate","destination":"강남역","app":"google"} → 결과 한 줄을 화면 기록·logcat 에
        //  (새 intent 를 받는 동안은 잠깐 '뒤'로 보여서, 화면이 다시 앞에 온 뒤에 함 — 실제처럼 바로 열기)
        // 폰 단독 말 풀이 시험 — 사용자 말 → SoloAction → Doer(앱 고르기 로그). 모델 없이 확인.
        i.getStringExtra("test_solo_do")?.let { t ->
            root.postDelayed({
                val a = SoloAction.fromUser(t)
                android.util.Log.i("KimbiseoTest", "test_solo_do '$t' -> $a")
                if (a != null) {
                    val r = Doer(this).run(a)
                    android.util.Log.i("KimbiseoTest", "test_solo_do result ok=${r.optBoolean("ok")} ${r.optString("말")}")
                }
            }, 1500)
        }
        i.getStringExtra("test_solo_line")?.let { line ->
            val user = i.getStringExtra("test_solo_user") ?: ""
            val p = SoloAction.parse(line)
            val a = SoloAction.enrich(p.action, user)
            android.util.Log.i("KimbiseoTest", "test_solo_line user='$user' -> action=$a text='${p.text}'")
        }
        GhBridge.testHooks(this, i)
        i.getStringExtra("test_do")?.let { j ->
            root.postDelayed({
                val r = Doer(this).run(org.json.JSONObject(j))
                android.util.Log.i("KimbiseoTest", "test_do " + r)
                Bus.line("sys", getString(R.string.test_do_prefix) + " " + r.optString("말"))
            }, 800)
        }
    }

    private fun show(msg: String? = null) {
        root.removeAllViews()
        when {
            pending != null -> pairConfirm(pending!!)
            Store.mode(this).isEmpty() -> modeScreen(msg)
            Store.mode(this) == "solo" -> openSolo()
            Store.pc(this) == null -> pairScreen(msg)
            screen == "settings" -> settingsScreen()
            else -> talkScreen()
        }
    }

    /** 첫 화면 — PC 와 연결할지, 폰 혼자 쓸지. (2026-11-18 결정) */
    private fun modeScreen(msg: String?) {
        screen = "mode"
        val p = page()
        p.addView(Ui.text(this, getString(R.string.app_name), 14f, Ui.TEXT2, true))
        p.addView(Ui.text(this, getString(R.string.mode_title), 26f, Ui.TEXT, true))
        p.addView(Ui.text(this, getString(R.string.mode_intro), 15f, Ui.TEXT2))
        if (msg != null) p.addView(Ui.text(this, msg, 14f, Ui.BAD))

        val pc = Ui.card(this, 10)
        pc.addView(Ui.text(this, getString(R.string.mode_pc_title), 19f, Ui.TEXT, true))
        pc.addView(Ui.text(this, getString(R.string.mode_pc_desc), 14f, Ui.TEXT2))
        pc.addView(Ui.button(this, getString(R.string.mode_pc_btn), Ui.Kind.PRIMARY) {
            Store.setMode(this, "pc"); show()
        }, lp())
        p.addView(pc, lp())

        val dev = SoloModel.device(this)
        val solo = Ui.card(this, 10)
        solo.addView(Ui.text(this, getString(R.string.mode_solo_title), 19f, Ui.TEXT, true))
        solo.addView(Ui.text(this, getString(R.string.mode_solo_desc), 14f, Ui.TEXT2))
        solo.addView(Ui.text(this, getString(R.string.mode_solo_req), 13f, Ui.MUTED))
        if (dev.ok) {
            solo.addView(Ui.button(this, getString(R.string.mode_solo_btn), Ui.Kind.PRIMARY) {
                Store.setMode(this, "solo"); openSolo()
            }, lp())
        } else {
            solo.addView(Ui.text(this, getString(R.string.mode_solo_no, dev.reasons.joinToString(" · ") { reason(it) }), 14f, Ui.BAD))
            solo.addView(Ui.button(this, getString(R.string.mode_solo_btn), Ui.Kind.SECONDARY) {} .apply { isEnabled = false; alpha = 0.5f }, lp())
        }
        p.addView(solo, lp())
        GhBridge.addModeCard(this, p)
        p.addView(Ui.text(this, getString(R.string.mode_change_later), 13f, Ui.MUTED))
    }

    private fun reason(code: String): String = getString(when (code) {
        "ram" -> R.string.mode_solo_reason_ram
        "abi" -> R.string.mode_solo_reason_abi
        "android" -> R.string.mode_solo_reason_android
        "storage" -> R.string.mode_solo_reason_storage
        else -> R.string.mode_solo_reason_ram
    })

    /**
     * 키보드·상태 표시줄·아래 막대에 화면이 가려지지 않게(모든 화면 공통).
     *  안드로이드 15(targetSdk 35+)는 앱이 화면 끝까지 그려져 windowSoftInputMode=adjustResize 가 안 먹음 → 안드로이드 11 이상은
     *  직접 inset(막대·키보드 높이)만큼 root 아래쪽을 띄움. 그러면 스크롤 화면이 줄어들고, 고르고 있는 입력 칸을 키보드 위로 올려 보여 줌.
     *  안드로이드 8~10 은 매니페스트의 adjustResize 가 그대로 함.
     */
    private fun fitKeyboard() {
        if (Build.VERSION.SDK_INT < 30) return
        window.setDecorFitsSystemWindows(false)
        root.setOnApplyWindowInsetsListener { v, ins ->
            val bars = ins.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            val ime = ins.getInsets(WindowInsets.Type.ime())
            val bottom = maxOf(bars.bottom, ime.bottom)
            if (v.paddingBottom != bottom || v.paddingTop != bars.top) {
                v.setPadding(bars.left, bars.top, bars.right, bottom)
                v.post { showFocused() }
            }
            WindowInsets.CONSUMED
        }
    }

    /** 고르고 있는 입력 칸이 보이게 스크롤 + 대화 화면이면 자막 마지막 줄로 */
    private fun showFocused() {
        currentFocus?.let { f -> val r = Rect(); f.getDrawingRect(r); r.bottom += dp(this, 72); f.requestRectangleOnScreen(r, true) }
        if (screen == "talk") logScroll?.let { sv -> sv.scrollTo(0, (log?.height ?: 0)) }
    }

    private fun page(): LinearLayout {
        val sv = ScrollView(this).apply { isFillViewport = true }
        val col = Ui.col(this, 16).apply { setPadding(dp(this@MainActivity, 20), dp(this@MainActivity, 32), dp(this@MainActivity, 20), dp(this@MainActivity, 24)) }
        sv.addView(col)
        root.addView(sv)
        return col
    }

    // ---------------------------------------------------------------- 짝짓기
    private fun pairScreen(msg: String?) {
        screen = "pair"
        val p = page()
        p.addView(Ui.text(this, getString(R.string.app_name), 14f, Ui.TEXT2, true))
        p.addView(Ui.text(this, getString(R.string.pair_title), 26f, Ui.TEXT, true))
        p.addView(Ui.text(this, getString(R.string.pair_intro), 15f, Ui.TEXT2))
        p.addView(Ui.button(this, getString(R.string.pair_scan_qr), Ui.Kind.PRIMARY) { scan() }, lp())
        if (msg != null) p.addView(Ui.text(this, msg, 14f, Ui.BAD))
        val c = Ui.card(this)
        c.addView(Ui.text(this, getString(R.string.pair_manual_title), 16f, Ui.TEXT, true))
        val host = Ui.field(this, getString(R.string.pair_host_hint), value = typed[0], kind = Ui.In.HOST)
        val port = Ui.field(this, getString(R.string.pair_port_hint), true, typed[1].ifEmpty { "8874" })
        val code = Ui.field(this, getString(R.string.pair_code_hint), true, typed[2])
        val fp = Ui.field(this, getString(R.string.pair_fp_hint), value = typed[3], kind = Ui.In.HEX)
        val fields = listOf(host, port, code, fp)
        for (f in fields) c.addView(f, lp())
        val err = Ui.text(this, "", 14f, Ui.BAD)
        c.addView(Ui.button(this, getString(R.string.pair_connect)) {
            for ((i, f) in fields.withIndex()) typed[i] = f.text.toString()   // 오류가 나도 넣은 값은 그대로 둠
            val h = PairRules.cleanHost(host.text.toString()); val pt = port.text.toString().trim().toIntOrNull() ?: 0
            if (h != host.text.toString()) { host.setText(h); typed[0] = h }
            val cd = PairRules.cleanCode(code.text.toString()); val f = PairRules.cleanFp(fp.text.toString())
            err.setTextColor(Ui.BAD)
            err.text = when {
                h.isEmpty() -> getString(R.string.pair_err_host_empty)
                !PairRules.lanHost(h) -> if (PairRules.publicV4(h))
                    getString(R.string.pair_err_public)
                    else getString(R.string.pair_err_host_shape)
                pt !in 1..65535 -> getString(R.string.pair_err_port)
                cd == null -> getString(R.string.pair_err_code)
                f == null -> getString(R.string.pair_err_fp)
                else -> { err.setTextColor(Ui.TEXT2); doPair(PairInfo(listOf(h), pt, cd, f, ""), err); getString(R.string.pair_connecting) }
            }
            if (err.text.isNotEmpty()) err.post { val r = Rect(); err.getDrawingRect(r); err.requestRectangleOnScreen(r, false) }
        }, lp())
        c.addView(err)
        p.addView(c, lp())
        p.addView(Ui.text(this, getString(R.string.pair_footer), 13f, Ui.MUTED))
        p.addView(Ui.button(this, getString(R.string.mode_solo_btn), Ui.Kind.QUIET) {
            Store.setMode(this, "solo"); openSolo()
        }, lp())
    }

    private fun pairConfirm(info: PairInfo) {
        screen = "confirm"
        val p = page()
        p.addView(Ui.text(this, getString(R.string.pair_confirm_title), 26f, Ui.TEXT, true))
        val c = Ui.card(this, 8)
        c.addView(Ui.text(this, if (info.pcName.isNotEmpty()) info.pcName else getString(R.string.common_pc), 17f, Ui.TEXT, true))
        c.addView(Ui.text(this, getString(R.string.pair_address, info.hosts.joinToString(" · "), info.port), 13f, Ui.TEXT2))
        c.addView(Ui.text(this, getString(R.string.pair_fp_label), 13f, Ui.TEXT2))
        c.addView(Ui.mono(this, PairRules.words(info.fp), 22f, Ui.TEXT))
        p.addView(c, lp())
        p.addView(Ui.text(this, getString(R.string.pair_confirm_help), 14f, Ui.TEXT2))
        val st = Ui.text(this, "", 14f, Ui.TEXT2)
        p.addView(Ui.button(this, getString(R.string.pair_confirm_yes), Ui.Kind.PRIMARY) { st.text = getString(R.string.pair_connecting); doPair(info, st) }, lp())
        p.addView(Ui.button(this, getString(R.string.common_cancel), Ui.Kind.QUIET) { pending = null; show() }, lp())
        p.addView(st)
    }

    private fun doPair(info: PairInfo, st: TextView? = null) {
        Thread {
            val r = Net.pair(info)
            runOnUiThread {
                if (r.ok) {
                    Store.save(this, listOf(r.host) + info.hosts.filter { it != r.host }, info.port, r.fp.ifEmpty { info.fp }, r.device, r.pcName, r.token)
                    Store.setMode(this, "pc")     // QR 로 연결했으면 PC 모드로
                    pending = null; Bus.lines.clear(); typed[2] = ""
                    Bus.line("sys", getString(R.string.pair_connected, r.pcName.ifEmpty { getString(R.string.common_pc) }))
                    show()
                } else if (st != null) { st.setTextColor(Ui.BAD); st.text = r.msg } else { pending = null; show(r.msg) }
            }
        }.start()
    }

    private fun scan() {
        IntentIntegrator(this).setDesiredBarcodeFormats(IntentIntegrator.QR_CODE).setPrompt(getString(R.string.pair_scan_prompt))
            .setBeepEnabled(false).setOrientationLocked(false).initiateScan()
    }

    @Deprecated("Activity 결과")
    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        val r = IntentIntegrator.parseActivityResult(req, res, data)
        if (r == null) { super.onActivityResult(req, res, data); return }
        val c = r.contents ?: return
        val p = PairRules.parse(c)
        pending = p
        show(if (p == null) getString(R.string.pair_qr_invalid) else null)
    }

    // ---------------------------------------------------------------- 대화
    private fun talkScreen() {
        screen = "talk"
        val c = this
        val pc = Store.pc(this)
        val whole = Ui.col(this).apply { setPadding(0, dp(c, 12), 0, 0) }
        // 위: 연결 점 · PC 이름 · 설정
        val top = Ui.row(this, 8).apply { setPadding(dp(c, 20), dp(c, 8), dp(c, 8), dp(c, 8)) }
        stateDot = Ui.dot(this, Ui.MUTED)
        top.addView(stateDot)
        val names = Ui.col(this)
        val bot = Bus.pc?.optString("비서")?.ifEmpty { null } ?: getString(R.string.app_name)
        names.addView(Ui.text(this, "$bot · ${pc?.name?.ifEmpty { getString(R.string.common_pc) } ?: getString(R.string.common_pc)}", 16f, Ui.TEXT, true).apply {
            maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END })
        stateText = Ui.text(this, Bus.state.text.ifEmpty { getString(R.string.state_idle) }, 13f, Ui.TEXT2)
        names.addView(stateText)
        top.addView(names, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        top.addView(Ui.button(this, getString(if (interpOpen) R.string.talk_interp_close else R.string.talk_interp_open), Ui.Kind.QUIET) { interpOpen = !interpOpen; show() }.apply { setPadding(dp(c, 12), 0, dp(c, 12), 0) })
        top.addView(Ui.button(this, getString(R.string.settings_title), Ui.Kind.QUIET) { screen = "settings"; show() }.apply { setPadding(dp(c, 12), 0, dp(c, 12), 0) })
        whole.addView(top, lp())
        // 내 말소리 크기(듣는 중일 때만 분홍 막대가 움직임)
        val bar = FrameLayout(this).apply { setBackgroundColor(Ui.LINE) }
        level = View(this).apply { setBackgroundColor(Ui.ACCENT); pivotX = 0f; scaleX = 0f }
        bar.addView(level, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(c, 2)))
        whole.addView(bar, lp(h = dp(c, 2)))
        // 대화 화면 위쪽의 펫 — 앱 저장소에 받아 둔 클립만으로 돈다(설정에서 숨길 수 있음).
        if (PetStore.show(this)) {
            petView = PetView(this).apply { background = Ui.bg(Ui.CARD, 14, c) }
            whole.addView(petView, lp(h = dp(c, 188)).apply { leftMargin = dp(c, 16); rightMargin = dp(c, 16); topMargin = dp(c, 8) })
            drawPet(greet = true)
            PetStore.sync(this)
        } else petView = null
        if (interpOpen) { interpBox = Ui.col(this, 12).apply { setPadding(dp(c, 20), dp(c, 16), dp(c, 20), dp(c, 4)) }; whole.addView(interpBox, lp()); drawInterp() }
        else interpBox = null
        // 자막
        logScroll = ScrollView(this)
        log = Ui.col(this, 12).apply { setPadding(dp(c, 20), dp(c, 16), dp(c, 20), dp(c, 16)) }
        logScroll!!.addView(log)
        logScroll!!.addOnLayoutChangeListener { v, _, t, _, b, _, ot, _, ob -> if (b - t != ob - ot) v.post { v.scrollTo(0, log?.height ?: 0) } }
        whole.addView(logScroll, lp(h = 0, weight = 1f))
        // 아래: 글로 말하기 · 마이크 · 대화 시작/끝
        val bottom = Ui.col(this, 12).apply { setPadding(dp(c, 16), dp(c, 12), dp(c, 16), dp(c, 16)); background = Ui.bg(Ui.CARD, 0, c) }
        val tr = Ui.row(this, 8)
        val input = Ui.field(this, getString(R.string.talk_input_hint)).apply { imeOptions = EditorInfo.IME_ACTION_SEND }
        val sendIt = {
            val t = input.text.toString().trim()
            if (t.isNotEmpty()) {
                input.setText("")
                // 김비서 GH(깃허브판)에서 장바구니 문장이면 모델 대화 대신 조작 화면으로 넘긴다.
                if (!GhBridge.maybeRun(this, t)) {
                    val s = TalkService.me
                    if (s != null && Bus.state.talking) s.sendText(t) else { pendingText = t; startTalk() }
                }
            }
        }
        input.setOnEditorActionListener { _, a, _ -> if (a == EditorInfo.IME_ACTION_SEND) { sendIt(); true } else false }
        tr.addView(input, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        tr.addView(Ui.button(this, getString(R.string.talk_send)) { sendIt() })
        bottom.addView(tr, lp())
        val br = Ui.row(this, 8)
        micBtn = Ui.button(this, getString(if (Bus.state.mic || TalkService.me == null) R.string.talk_mic_off else R.string.talk_mic_on)) {
            val s = TalkService.me ?: return@button
            s.setMic(!s.micOn)
        }
        talkBtn = Ui.button(this, getString(R.string.talk_start), Ui.Kind.PRIMARY) { if (TalkService.me != null) TalkService.me?.stopTalk() else startTalk() }
        br.addView(micBtn, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        br.addView(talkBtn, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1.4f))
        bottom.addView(br, lp())
        whole.addView(bottom, lp())
        root.addView(whole, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        redrawLog(); onEv(Bus.state)
    }

    private var pendingText: String? = null
    /** 직접 넣기 칸에 넣은 값(주소·포트·코드·확인 글자) — 화면을 다시 그려도 남김 */
    private val typed = arrayOf("", "", "", "")

    private fun startTalk() {
        val need = ArrayList<String>()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) need.add(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            need.add(Manifest.permission.POST_NOTIFICATIONS)
        if (need.isNotEmpty()) { afterMic = { startTalk() }; requestPermissions(need.toTypedArray(), 1); return }
        TalkService.start(this)
    }

    override fun onRequestPermissionsResult(req: Int, perms: Array<out String>, res: IntArray) {
        super.onRequestPermissionsResult(req, perms, res)
        if (req == 1) {
            val i = perms.indexOf(Manifest.permission.RECORD_AUDIO)
            if (i >= 0 && res.getOrNull(i) != PackageManager.PERMISSION_GRANTED) { Bus.line("sys", getString(R.string.talk_perm_mic)); afterMic = null; return }
            afterMic?.invoke(); afterMic = null
        }
    }

    private fun lineView(l: Bus.Ev.Line): View {
        val c = this
        return when (l.who) {
            "me" -> Ui.text(this, l.text, 16f, Ui.TEXT).apply {
                background = Ui.bg(Ui.RAISED, 14, c); setPadding(dp(c, 12), dp(c, 8), dp(c, 12), dp(c, 8))
                layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { gravity = Gravity.END; leftMargin = dp(c, 48) }
            }
            "bot" -> Ui.text(this, l.text, 17f, Ui.TEXT).apply { layoutParams = lp().apply { rightMargin = dp(c, 24) } }
            "gate" -> Ui.text(this, l.text, 13f, Ui.MUTED).apply {
                background = Ui.bg(Color.TRANSPARENT, 8, c, 1); setPadding(dp(c, 12), dp(c, 8), dp(c, 12), dp(c, 8)); layoutParams = lp()
            }
            else -> Ui.text(this, l.text, 13f, Ui.MUTED).apply { layoutParams = lp() }
        }
    }

    private fun redrawLog() {
        val lg = log ?: return
        lg.removeAllViews()
        if (Bus.lines.isEmpty()) lg.addView(Ui.text(this, getString(R.string.talk_empty_hint), 14f, Ui.MUTED))
        for (l in Bus.lines) lg.addView(lineView(l))
        logScroll?.post { logScroll?.fullScroll(View.FOCUS_DOWN) }
    }

    private fun onEv(e: Bus.Ev) {
        when (e) {
            is Bus.Ev.Line -> if (screen == "talk") {
                val lg = log ?: return
                if (lg.childCount == 1 && Bus.lines.size == 1) lg.removeAllViews()
                lg.addView(lineView(e)); logScroll?.post { logScroll?.fullScroll(View.FOCUS_DOWN) }
            }
            is Bus.Ev.State -> {
                stateText?.text = e.text.ifEmpty { getString(R.string.state_idle) }
                val color = when { !e.talking -> Ui.MUTED; e.mic && e.text == getString(R.string.state_listening) -> Ui.ACCENT; else -> Ui.OK }
                (stateDot?.background as? android.graphics.drawable.GradientDrawable)?.setColor(color)
                val running = TalkService.me != null
                talkBtn?.text = getString(if (running) R.string.talk_stop else R.string.talk_start)
                micBtn?.text = getString(if (e.mic) R.string.talk_mic_off else R.string.talk_mic_on)
                micBtn?.isEnabled = running
                micBtn?.alpha = if (running) 1f else 0.5f
                if (!e.talking) level?.scaleX = 0f
                if (e.talking) pendingText?.let { t -> pendingText = null; TalkService.me?.sendText(t) }
                if (screen == "talk") drawPet(false)     // 말하는 중 = 말하기 동작, 끝나면 대기로
            }
            is Bus.Ev.Level -> {
                // 작은 잡음은 0 으로, 나머지는 10단계로 — 조용할 때 화면을 계속 다시 그리지 않음(배터리·화면 읽기 도구)
                val v = if (Bus.state.talking && Bus.state.mic && e.v >= 0.06f) Math.round(e.v * 10) / 10f else 0f
                level?.let { if (it.scaleX != v) it.scaleX = v }
            }
            is Bus.Ev.Interp -> drawInterp()
            is Bus.Ev.Ask -> showAsk(e)
            is Bus.Ev.AskDone -> if (askId == e.id) { askDialog?.dismiss(); askDialog = null; askId = "" }
            is Bus.Ev.Pet -> {
                if (screen == "talk") drawPet(greet = !petGreeted)
                else if (screen == "settings") petStatusText?.text = PetStore.statusText(this)
            }
            is Bus.Ev.NeedPerm -> { Bus.line("sys", e.why); requestPermissions(arrayOf(e.perm), 2) }
            is Bus.Ev.Pc -> if (screen == "talk") show()
        }
    }

    // ---------------------------------------------------------------- 펫
    /** 캐시에 있는 클립으로만 그린다. 인사(hello)는 처음 한 번, 그 뒤 대기/말하기를 반복. */
    private fun drawPet(greet: Boolean) {
        val pv = petView ?: return
        if (!PetStore.show(this)) { pv.visibility = View.GONE; petMotion = ""; return }
        val clips = PetStore.clips(this)
        if (clips.isEmpty()) { pv.visibility = View.GONE; petMotion = ""; return }
        pv.visibility = View.VISIBLE
        if (!greet && petMotion == "hello" && !Bus.state.speaking) return   // 인사는 끝까지
        if (greet && !petGreeted) {
            val hello = clips["hello"] ?: clips["wave"]
            if (hello != null) {
                petGreeted = true; petMotion = "hello"
                pv.onEnded = { pv.onEnded = null; petMotion = ""; drawPet(false) }
                pv.play(hello, false)
                return
            }
        }
        pv.onEnded = null
        val want = if (Bus.state.speaking) "talk" else "idle"
        val f = clips[want] ?: clips["idle"] ?: return
        petMotion = want
        pv.play(f, true)
    }

    private fun petSwitch(label: String, checked: Boolean, onChange: (Boolean) -> Unit): android.widget.Switch =
        android.widget.Switch(this).apply {
            text = label; setTextColor(Ui.TEXT); textSize = 15f; isChecked = checked
            val st = arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf())
            thumbTintList = android.content.res.ColorStateList(st, intArrayOf(Ui.TEXT, Ui.TEXT2))
            trackTintList = android.content.res.ColorStateList(st, intArrayOf(Ui.ACCENT_FILL, Ui.RAISED))
            setOnCheckedChangeListener { _, v -> onChange(v) }
        }

    private fun petOption(list: LinearLayout, id: String, label: String) {
        val sel = PetStore.selected(this) == id
        list.addView(TextView(this).apply {
            text = label; setTextColor(if (sel) Ui.TEXT else Ui.TEXT2); textSize = 15f
            setPadding(dp(this@MainActivity, 14), dp(this@MainActivity, 12), dp(this@MainActivity, 14), dp(this@MainActivity, 12))
            background = Ui.bg(if (sel) Ui.RAISED else Color.TRANSPARENT, 10, this@MainActivity, 1, if (sel) Ui.ACCENT else Ui.LINE)
            setOnClickListener {
                PetStore.setSelected(this@MainActivity, id)
                PetStore.sync(this@MainActivity, true)
                screen = "settings"; show()
            }
        }, lp())
    }

    private fun petSettingsCard(): LinearLayout {
        val c = Ui.card(this, 12)
        c.addView(Ui.text(this, getString(R.string.pet_section), 16f, Ui.TEXT, true))
        c.addView(petSwitch(getString(R.string.pet_show), PetStore.show(this)) { v ->
            PetStore.setShow(this, v)
            if (!v) { petView?.clear(); petView?.visibility = View.GONE }
        }, lp())
        c.addView(Ui.text(this, getString(R.string.pet_show_help), 13f, Ui.MUTED))
        c.addView(petSwitch(getString(R.string.pet_wifi), PetStore.wifiOnly(this)) { v ->
            PetStore.setWifiOnly(this, v)
            if (!v) PetStore.sync(this, true)
        }, lp())
        c.addView(Ui.text(this, getString(R.string.pet_wifi_help), 13f, Ui.MUTED))
        c.addView(Ui.text(this, getString(R.string.pet_pick_title), 15f, Ui.TEXT, true))
        c.addView(Ui.text(this, getString(R.string.pet_pick_help), 13f, Ui.MUTED))
        val list = Ui.col(this, 8)
        val outfits = PetStore.outfits(this)
        val pcId = PetStore.currentPcId(this)
        val pcName = outfits.firstOrNull { it.first == pcId }?.second ?: ""
        petOption(list, "", getString(R.string.pet_follow_pc) + (if (pcName.isNotEmpty()) " · $pcName" else ""))
        for ((id, name, gender) in outfits) petOption(list, id, if (gender.isEmpty()) name else "$name · $gender")
        c.addView(list, lp())
        if (outfits.isEmpty()) c.addView(Ui.button(this, getString(R.string.pet_refresh), Ui.Kind.SECONDARY) {
            PetStore.sync(this, true); screen = "settings"; show()
        }, lp())
        val st = Ui.text(this, PetStore.statusText(this), 13f, Ui.MUTED)
        petStatusText = st
        c.addView(st, lp())
        PetStore.sync(this)
        return c
    }

    // ---------------------------------------------------------------- 통역
    private fun drawInterp() {
        val box = interpBox ?: return
        box.removeAllViews()
        val m = Bus.interp
        if (TalkService.me == null || !Bus.state.talking) {
            box.addView(Ui.text(this, getString(R.string.interp_help_not_talking), 14f, Ui.TEXT2)); return
        }
        if (Bus.pc?.optBoolean("통역", true) == false) { box.addView(Ui.text(this, getString(R.string.interp_pc_off), 14f, Ui.TEXT2)); return }
        val on = m?.optBoolean("켜짐") == true
        val other = m?.optString("상대이름")?.ifEmpty { getString(R.string.common_auto) } ?: getString(R.string.common_auto)
        val head = Ui.row(this, 8)
        head.addView(Ui.text(this, if (on) getString(R.string.interp_on, other) else getString(R.string.interp_off), 16f, Ui.TEXT, true),
            lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(Ui.button(this, getString(if (on) R.string.interp_disable else R.string.interp_enable), if (on) Ui.Kind.SECONDARY else Ui.Kind.PRIMARY) { TalkService.me?.interp(!on, "") })
        box.addView(head, lp())
        val langs = m?.optJSONObject("언어")
        if (langs != null && langs.length() > 0) {
            val hs = HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false }
            val r = Ui.row(this, 8)
            val cur = m.optString("방식", "auto")
            val all = listOf("auto" to getString(R.string.common_auto)) + langs.keys().asSequence().map { it to (langs.optJSONObject(it)?.optString("이름") ?: it) }.toList()
            for ((code, name) in all) {
                val sel = code == cur
                r.addView(TextView(this).apply {
                    text = name; setTextColor(if (sel) Ui.TEXT else Ui.TEXT2); textSize = 14f
                    setPadding(dp(context, 12), dp(context, 8), dp(context, 12), dp(context, 8))
                    background = Ui.bg(if (sel) Ui.RAISED else Color.TRANSPARENT, 8, context, 1, if (sel) Ui.ACCENT else Ui.LINE)
                    setOnClickListener { TalkService.me?.interp(true, code) }
                })
            }
            hs.addView(r); box.addView(hs, lp())
        }
        val st = m?.optString("state") ?: ""
        if (st == "translating") box.addView(Ui.text(this, getString(R.string.interp_translating,
            m?.optString("src_name") ?: "", m?.optString("dst_name") ?: "", m?.optString("src") ?: ""), 14f, Ui.TEXT2))
        if (st == "done") {
            val c = Ui.card(this, 8)
            c.addView(Ui.text(this, "${m?.optString("src_name")} · ${m?.optString("src")}", 14f, Ui.TEXT2))
            c.addView(Ui.text(this, m?.optString("dst") ?: "", 22f, Ui.TEXT))
            m?.optString("money")?.takeIf { it.isNotEmpty() && it != "null" }?.let { c.addView(Ui.text(this, it, 13f, Ui.MUTED)) }
            box.addView(c, lp())
        }
        if (st == "error") box.addView(Ui.text(this, getString(R.string.interp_error, m?.optString("why") ?: ""), 14f, Ui.BAD))
        if (on) box.addView(Ui.text(this, getString(R.string.interp_footer) +
            if (Bus.pc?.optBoolean("목소리확인") == true) " " + getString(R.string.interp_footer_voice) else "", 13f, Ui.MUTED))
    }

    // ---------------------------------------------------------------- 실행할까요?
    private fun showAsk(a: Bus.Ev.Ask) {
        if (askId == a.id && askDialog?.isShowing == true) return
        askDialog?.dismiss()
        askId = a.id
        val d = Dialog(this)
        val c = Ui.col(this, 16).apply { background = Ui.bg(Ui.CARD, 16, context, 1); setPadding(dp(context, 20), dp(context, 20), dp(context, 20), dp(context, 16)) }
        c.addView(Ui.text(this, getString(R.string.ask_title), 20f, Ui.TEXT, true))
        c.addView(Ui.text(this, a.text, 16f, Ui.TEXT2))
        val r = Ui.row(this, 8)
        r.addView(Ui.button(this, getString(R.string.common_cancel)) { TalkService.me?.answer(a.id, false); d.dismiss() }, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        r.addView(Ui.button(this, getString(R.string.ask_run), Ui.Kind.PRIMARY) { TalkService.me?.answer(a.id, true); d.dismiss() }, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        c.addView(r, lp())
        d.setContentView(c)
        d.setCancelable(false)
        d.window?.setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
        d.window?.setLayout((resources.displayMetrics.widthPixels * 0.88).toInt(), WindowManager.LayoutParams.WRAP_CONTENT)
        d.setOnDismissListener { if (askId == a.id) askId = "" }
        askDialog = d
        d.show()
    }

    // ---------------------------------------------------------------- 설정
    private fun settingsScreen() {
        val pc = Store.pc(this) ?: run { show(); return }
        val p = page()
        p.addView(Ui.button(this, getString(R.string.settings_back), Ui.Kind.QUIET) { screen = ""; show() }.apply { gravity = Gravity.START or Gravity.CENTER_VERTICAL; setPadding(0, 0, 0, 0) })
        p.addView(Ui.text(this, getString(R.string.settings_title), 26f, Ui.TEXT, true))
        val c = Ui.card(this, 8)
        c.addView(Ui.text(this, getString(R.string.settings_connected_pc), 13f, Ui.TEXT2))
        c.addView(Ui.text(this, pc.name.ifEmpty { getString(R.string.common_pc) }, 17f, Ui.TEXT, true))
        c.addView(Ui.text(this, getString(R.string.pair_address, pc.hosts.joinToString(" · "), pc.port), 13f, Ui.TEXT2))
        c.addView(Ui.text(this, getString(R.string.pair_fp_label), 13f, Ui.TEXT2))
        c.addView(Ui.mono(this, PairRules.words(pc.fp), 18f, Ui.TEXT))
        Bus.pc?.let { s ->
            c.addView(Ui.text(this, getString(R.string.settings_pc_flags, s.optString("판"),
                getString(if (s.optBoolean("PC조작")) R.string.common_on else R.string.common_off),
                getString(if (s.optBoolean("목소리확인")) R.string.common_on else R.string.common_off)), 13f, Ui.MUTED))
        }
        p.addView(c, lp())
        val g = Ui.card(this, 8)
        val greet = android.widget.Switch(this).apply {
            text = getString(R.string.settings_greet); setTextColor(Ui.TEXT); textSize = 15f
            isChecked = Store.flag(context, "greet", true)
            val st = arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf())
            thumbTintList = android.content.res.ColorStateList(st, intArrayOf(Ui.TEXT, Ui.TEXT2))
            trackTintList = android.content.res.ColorStateList(st, intArrayOf(Ui.ACCENT_FILL, Ui.RAISED))
            setOnCheckedChangeListener { _, v -> Store.setFlag(context, "greet", v) }
        }
        g.addView(greet, lp())
        p.addView(g, lp())
        p.addView(petSettingsCard(), lp())
        GhBridge.addSettings(this, p)
        p.addView(Ui.button(this, getString(R.string.main_mode_solo), Ui.Kind.SECONDARY) {
            android.app.AlertDialog.Builder(this).setMessage(getString(R.string.main_mode_solo_confirm))
                .setPositiveButton(android.R.string.ok) { _, _ -> Store.setMode(this, "solo"); openSolo() }
                .setNegativeButton(android.R.string.cancel, null).show()
        }, lp())
        p.addView(Ui.text(this, getString(R.string.main_mode_solo_help), 13f, Ui.MUTED))
        p.addView(Ui.text(this, getString(R.string.settings_pc_help), 13f, Ui.MUTED))
        p.addView(Ui.button(this, getString(R.string.settings_disconnect), Ui.Kind.DANGER) {
            TalkService.me?.stopTalk()
            Store.clear(this); Bus.lines.clear(); Bus.pc = null; screen = ""; show()
        }, lp())
        p.addView(Ui.text(this, getString(R.string.settings_disconnect_help), 13f, Ui.MUTED))
        p.addView(Ui.text(this, getString(R.string.settings_version, BuildConfig.VERSION_NAME), 12f, Ui.MUTED))
    }
}
