package kr.kimbiseo.phone

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import kr.kimbiseo.phone.Ui.dp
import kr.kimbiseo.phone.Ui.lp
import org.json.JSONObject
import java.util.Locale

/**
 * PC 없이 폰 혼자 쓰기 — 폰 안 AI(Gemma 4 E2B)로 대화한다.
 *  모델은 처음 한 번 공식 배포처에서 받아 앱 저장소에 두고, 그 뒤엔 인터넷 없이 대화한다.
 *  말하기 = 안드로이드 기본 음성 인식(RecognizerIntent), 읽기 = 안드로이드 기본 TTS. 대화 기록은 이 폰에만.
 *  PC 조작은 없고, 길안내·전화/문자 화면·앱 열기는 Doer 로 그대로 한다(모델이 PHONE 한 줄로 부탁).
 */
class SoloActivity : Activity() {
    private lateinit var root: FrameLayout
    private var screen = ""
    private var lang = "ko"
    private var history: SoloHistory? = null
    private var log: LinearLayout? = null
    private var logScroll: ScrollView? = null
    private var stateText: TextView? = null
    private var stateDot: View? = null
    private var input: android.widget.EditText? = null
    private var sendBtn: android.widget.Button? = null
    private var micBtn: android.widget.Button? = null
    private var speakBtn: android.widget.Button? = null
    private var stopBtn: android.widget.Button? = null
    private var dlBar: ProgressBar? = null
    private var dlText: TextView? = null
    private var consent = false
    private var downloading = false
    private var download: SoloDownload? = null
    private var brainReady = false
    private var brainLoading = false
    private var brainError = ""
    private var retryBtn: android.widget.Button? = null
    private var generating = false
    private var sendGen = 0
    private var liveView: TextView? = null
    private var liveBuf = ""
    private var pendingText: String? = null
    private var userAction: JSONObject? = null
    private var userText = ""
    private var tts: TextToSpeech? = null
    private var ttsOk = false
    private var ttsLang = ""
    private var ttsTried = false

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(Lang.wrap(newBase))
    }

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        L.init(this)
        lang = Lang.app(this)
        consent = Store.flag(this, "solo_consent", false)
        window.statusBarColor = Ui.BG; window.navigationBarColor = Ui.BG
        root = FrameLayout(this).apply { setBackgroundColor(Ui.BG) }
        setContentView(root)
        fitKeyboard()
        history = SoloHistory(this)
        initTts()
        screen = if (SoloModel.ready(this)) "chat" else "model"
        testHooks(intent)
        if (screen.isEmpty()) screen = if (SoloModel.ready(this)) "chat" else "model"
        show()
    }

    override fun onNewIntent(i: Intent) {
        super.onNewIntent(i); setIntent(i); testHooks(i)
    }

    override fun onResume() {
        super.onResume()
        Bus.visible = true
        Bus.listener = { e ->
            when (e) {
                is Bus.Ev.NeedPerm -> requestPermissions(arrayOf(e.perm), 30)
                is Bus.Ev.Line -> if (screen == "chat" && e.who == "sys") addSys(e.text)
                else -> {}
            }
        }
        if (screen == "chat") { drawState(); if (!generating) drawPetlessLog() }
    }

    override fun onPause() {
        Bus.visible = false; Bus.listener = null
        super.onPause()
    }

    override fun onDestroy() {
        sendGen++
        download?.stop()
        try { tts?.stop(); tts?.shutdown() } catch (_: Throwable) {}
        tts = null
        SoloBrain.close()
        super.onDestroy()
    }

    // ---------------------------------------------------------------- 시험용(adbd)
    private fun testHooks(i: Intent?) {
        if (!BuildConfig.TEST_HOOKS || i == null) return
        i.getStringExtra("test_solo_lang")?.let { code ->
            i.removeExtra("test_solo_lang")
            Store.setStr(this, "lang", code)
            recreate(); return
        }
        i.getStringExtra("test_solo_text")?.let { t -> i.removeExtra("test_solo_text"); pendingText = t; if (screen == "chat") sendText(t) }
        // 시험용 — 모델을 안 올리고 사용자 말 해석 + Doer 실행 로그만 본다(앱 고르기 확인).
        i.getStringExtra("test_solo_do")?.let { t ->
            i.removeExtra("test_solo_do")
            android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
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
            i.removeExtra("test_solo_line"); i.removeExtra("test_solo_user")
            val p = SoloAction.parse(line)
            val a = SoloAction.enrich(p.action, user)
            android.util.Log.i("KimbiseoTest", "test_solo_line user='$user' -> action=$a text='${p.text}'")
        }
        if (tb(i, "test_solo_settings")) { i.removeExtra("test_solo_settings"); screen = "settings"; show() }
        if (tb(i, "test_solo_chat")) { i.removeExtra("test_solo_chat"); screen = "chat"; show() }
        if (tb(i, "test_solo_model")) { i.removeExtra("test_solo_model"); screen = "model"; show() }
        if (tb(i, "test_solo_delete")) { i.removeExtra("test_solo_delete"); SoloModel.delete(this); screen = "model"; show() }
        if (tb(i, "test_solo_download")) {
            i.removeExtra("test_solo_download")
            Store.setFlag(this, "solo_consent", true); consent = true; screen = "model"; show(); startDownload()
        }
        if (tb(i, "test_solo_new")) { i.removeExtra("test_solo_new"); newChat() }
        // 시험용 — 램 부족으로 모델 올리기가 실패한 상황을 그대로 만든다(실기에서 OOM 을 일부러 내기 어려움).
        if (tb(i, "test_solo_nomem")) { i.removeExtra("test_solo_nomem"); loadFailed(SoloBrain.NO_MEM) }
    }

    /** adb `--es key 1`(문자)과 `--ez key true`(참/거짓) 둘 다 알아듣는다. */
    private fun tb(i: Intent, k: String): Boolean =
        i.getBooleanExtra(k, false) || (i.getStringExtra(k) ?: "").lowercase() in listOf("1", "true", "yes")

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

    private fun showFocused() {
        currentFocus?.let { f -> val r = Rect(); f.getDrawingRect(r); r.bottom += dp(this, 72); f.requestRectangleOnScreen(r, true) }
        if (screen == "chat") logScroll?.let { sv -> sv.scrollTo(0, (log?.height ?: 0)) }
    }

    private fun page(): LinearLayout {
        root.removeAllViews()
        val sv = ScrollView(this).apply { isFillViewport = true }
        val col = Ui.col(this, 16).apply { setPadding(dp(this@SoloActivity, 20), dp(this@SoloActivity, 28), dp(this@SoloActivity, 20), dp(this@SoloActivity, 24)) }
        sv.addView(col); root.addView(sv)
        return col
    }

    private fun show() {
        when (screen) {
            "chat" -> if (SoloModel.ready(this)) chatScreen() else { screen = "model"; modelScreen() }
            "settings" -> settingsScreen()
            else -> modelScreen()
        }
    }

    // ---------------------------------------------------------------- 모델 받기
    private fun modelScreen() {
        screen = "model"
        val p = page()
        val dev = SoloModel.device(this)
        p.addView(Ui.text(this, getString(R.string.app_name), 14f, Ui.TEXT2, true))
        p.addView(Ui.text(this, getString(R.string.solo_title), 26f, Ui.TEXT, true))
        if (!dev.ok) {
            p.addView(Ui.text(this, getString(R.string.mode_solo_no, dev.reasons.joinToString(" · ") { reason(it) }), 14f, Ui.BAD))
            p.addView(Ui.button(this, getString(R.string.solo_mode_pc), Ui.Kind.PRIMARY) { switchToPc() }, lp())
            return
        }
        // 램 4GB 폰 — 쓸 수는 있지만 빠듯하다. 모델을 올리기 전에 다른 앱을 닫으라고 미리 알린다.
        if (SoloModel.tight(this)) {
            val t = Ui.card(this, 8)
            t.addView(Ui.text(this, getString(R.string.solo_ram_tight), 14f, Ui.TEXT2))
            p.addView(t, lp())
        }
        val c = Ui.card(this, 10)
        c.addView(Ui.text(this, getString(R.string.solo_model_title), 16f, Ui.TEXT, true))
        c.addView(Ui.text(this, getString(R.string.solo_model_name), 18f, Ui.TEXT))
        c.addView(Ui.text(this, getString(R.string.solo_model_size), 14f, Ui.TEXT2))
        c.addView(Ui.text(this, getString(R.string.solo_model_desc), 14f, Ui.TEXT2))
        c.addView(Ui.text(this, getString(R.string.solo_model_license), 13f, Ui.TEXT2))
        c.addView(Ui.text(this, getString(R.string.solo_model_source), 12f, Ui.MUTED))
        p.addView(c, lp())

        if (SoloModel.ready(this)) {
            val r = Ui.card(this, 8)
            r.addView(Ui.text(this, getString(R.string.solo_ready), 17f, Ui.OK, true))
            r.addView(Ui.text(this, getString(R.string.solo_ready_help), 14f, Ui.TEXT2))
            r.addView(Ui.text(this, getString(R.string.solo_model_ready_short, SoloModel.human(SoloModel.SIZE)), 13f, Ui.MUTED))
            p.addView(r, lp())
            p.addView(Ui.button(this, getString(R.string.solo_start_chat), Ui.Kind.PRIMARY) { screen = "chat"; show() }, lp())
            p.addView(Ui.button(this, getString(R.string.solo_delete), Ui.Kind.DANGER) { askDelete() }, lp())
            return
        }

        // 받기 전 — 와이파이·동의·남은 공간
        val free = SoloModel.freeBytes(this)
        val need = SoloModel.SIZE + SoloModel.EXTRA_SPACE
        if (free < need) p.addView(Ui.text(this, getString(R.string.solo_storage_need, SoloModel.human(need - free)), 14f, Ui.BAD))
        val w = Ui.card(this, 8)
        w.addView(switchRow(getString(R.string.solo_wifi_only), Store.flag(this, "solo_wifi", true)) { v ->
            Store.setFlag(this, "solo_wifi", v)
        }, lp())
        if (!SoloDownload(this).wifi() && Store.flag(this, "solo_wifi", true))
            w.addView(Ui.text(this, getString(R.string.solo_wifi_wait), 13f, Ui.MUTED))
        w.addView(switchRow(getString(R.string.solo_consent), consent) { v ->
            consent = v; Store.setFlag(this, "solo_consent", v)
            if (!downloading) show()
        }, lp())
        p.addView(w, lp())

        if (downloading) {
            dlBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { max = 1000 }
            p.addView(dlBar, lp())
            dlText = Ui.text(this, getString(R.string.solo_downloading, 0, "0 MB", SoloModel.human(SoloModel.SIZE)), 14f, Ui.TEXT2)
            p.addView(dlText, lp())
            p.addView(Ui.button(this, getString(R.string.solo_download_stop), Ui.Kind.DANGER) { download?.stop() }, lp())
            if (SoloModel.part(this).isFile) {
                val have = SoloModel.part(this).length()
                dlBar?.progress = ((have * 1000) / SoloModel.SIZE).toInt()
                dlText?.text = getString(R.string.solo_downloading, ((have * 100) / SoloModel.SIZE).toInt(), SoloModel.human(have), SoloModel.human(SoloModel.SIZE))
            }
        } else {
            val resume = SoloModel.part(this).isFile && SoloModel.part(this).length() > 0
            p.addView(Ui.button(this, getString(if (resume) R.string.solo_resume else R.string.solo_download), Ui.Kind.PRIMARY) { startDownload() }, lp())
        }
    }

    private fun startDownload() {
        if (downloading) return
        if (!consent) { toast(getString(R.string.solo_consent_first)); return }
        val wifiOnly = Store.flag(this, "solo_wifi", true)
        downloading = true
        screen = "model"; show()
        val d = SoloDownload(this).also { download = it }
        d.start(wifiOnly,
            onProgress = { done, total ->
                if (downloading) {
                    dlBar?.progress = ((done * 1000) / maxOf(total, 1L)).toInt()
                    dlText?.text = getString(R.string.solo_downloading, ((done * 100) / maxOf(total, 1L)).toInt(),
                        SoloModel.human(done), SoloModel.human(SoloModel.SIZE))
                }
            },
            onState = { st -> if (st == "verify") dlText?.text = getString(R.string.solo_verifying) },
            onDone = { ok, why ->
                downloading = false; download = null
                if (ok) { screen = "model"; show(); toast(getString(R.string.solo_ready)) }
                else if (why == SoloDownload.CANCEL) { screen = "model"; show(); toast(getString(R.string.solo_download_stopped)) }
                else { screen = "model"; show(); val m = when (why) {
                    SoloDownload.WIFI -> getString(R.string.solo_wifi_wait)
                    SoloDownload.STORAGE -> getString(R.string.solo_storage_need, SoloModel.human(SoloModel.SIZE + SoloModel.EXTRA_SPACE - SoloModel.freeBytes(this)))
                    SoloDownload.SHA -> getString(R.string.solo_hash_fail)
                    else -> getString(R.string.solo_download_fail, why ?: "?")
                }; toast(m) }
            })
    }

    private fun askDelete() {
        AlertDialog.Builder(this).setMessage(getString(R.string.solo_delete_confirm))
            .setPositiveButton(android.R.string.ok) { _, _ ->
                download?.stop(); downloading = false
                SoloModel.delete(this); screen = "model"; show(); toast(getString(R.string.solo_delete_done))
            }.setNegativeButton(android.R.string.cancel, null).show()
    }

    private fun reason(code: String): String = getString(when (code) {
        "ram" -> R.string.mode_solo_reason_ram
        "abi" -> R.string.mode_solo_reason_abi
        "android" -> R.string.mode_solo_reason_android
        "storage" -> R.string.mode_solo_reason_storage
        else -> R.string.mode_solo_reason_ram
    })

    // ---------------------------------------------------------------- 대화
    private fun chatScreen() {
        screen = "chat"
        val c = this
        root.removeAllViews()
        val whole = Ui.col(this).apply { setPadding(0, dp(c, 12), 0, 0) }
        val top = Ui.row(this, 8).apply { setPadding(dp(c, 20), dp(c, 6), dp(c, 8), dp(c, 6)) }
        stateDot = Ui.dot(this, Ui.ACCENT)
        top.addView(stateDot)
        val names = Ui.col(this)
        names.addView(Ui.text(this, getString(R.string.solo_title), 16f, Ui.TEXT, true).apply { maxLines = 1 })
        stateText = Ui.text(this, getString(R.string.solo_ready_state), 13f, Ui.TEXT2)
        names.addView(stateText)
        top.addView(names, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        top.addView(Ui.button(this, getString(R.string.solo_new_chat), Ui.Kind.QUIET) { askNewChat() }.apply { setPadding(dp(c, 10), 0, dp(c, 10), 0) })
        top.addView(Ui.button(this, getString(R.string.solo_settings), Ui.Kind.QUIET) { screen = "settings"; show() }.apply { setPadding(dp(c, 10), 0, dp(c, 10), 0) })
        whole.addView(top, lp())
        whole.addView(Ui.text(this, getString(R.string.solo_offline), 12f, Ui.MUTED).apply { setPadding(dp(c, 22), 0, dp(c, 20), 6) }, lp())

        logScroll = ScrollView(this)
        log = Ui.col(this, 12).apply { setPadding(dp(c, 20), dp(c, 10), dp(c, 20), dp(c, 14)) }
        logScroll!!.addView(log)
        logScroll!!.addOnLayoutChangeListener { v, _, t, _, b, _, ot, _, ob -> if (b - t != ot - ob) v.post { v.scrollTo(0, log?.height ?: 0) } }
        whole.addView(logScroll, lp(h = 0, weight = 1f))

        val bottom = Ui.col(this, 10).apply { setPadding(dp(c, 16), dp(c, 10), dp(c, 16), dp(c, 14)); background = Ui.bg(Ui.CARD, 0, c) }
        val tr = Ui.row(this, 8)
        input = Ui.field(this, getString(R.string.solo_input_hint)).apply { imeOptions = EditorInfo.IME_ACTION_SEND }
        input!!.setOnEditorActionListener { _, a, _ -> if (a == EditorInfo.IME_ACTION_SEND) { sendInput(); true } else false }
        tr.addView(input, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        sendBtn = Ui.button(this, getString(R.string.solo_send)) { sendInput() }
        tr.addView(sendBtn)
        bottom.addView(tr, lp())
        val br = Ui.row(this, 8)
        micBtn = Ui.button(this, getString(R.string.solo_mic)) { listen() }
        speakBtn = Ui.button(this, getString(if (Store.flag(this, "solo_speak", true)) R.string.solo_speak_on else R.string.solo_speak_off)) {
            val on = !Store.flag(this, "solo_speak", true); Store.setFlag(this, "solo_speak", on)
            speakBtn?.text = getString(if (on) R.string.solo_speak_on else R.string.solo_speak_off)
            if (!on) try { tts?.stop() } catch (_: Throwable) {}
        }
        stopBtn = Ui.button(this, getString(R.string.solo_stop), Ui.Kind.DANGER) { stopReply() }
        retryBtn = Ui.button(this, getString(R.string.solo_retry), Ui.Kind.SECONDARY) { retryLoad() }
        br.addView(micBtn, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        br.addView(speakBtn, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        br.addView(stopBtn, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        br.addView(retryBtn, lp(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        bottom.addView(br, lp())
        whole.addView(bottom, lp())
        root.addView(whole, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        drawPetlessLog(); drawState()
        Log.i(TAG, "recognizer available=${recognizerAvailable()}")
        ensureBrain()
    }

    private fun ensureBrain() {
        Log.i(TAG, "ensureBrain ready=$brainReady loading=$brainLoading lang=$lang/${brainLang} pending=${pendingText != null}")
        if (SoloModel.present(this) == null) { screen = "model"; show(); return }
        if (brainReady && lang == brainLang) { flushPending(); return }
        if (brainLoading) return
        brainLoading = true; brainError = ""; drawState()
        SoloBrain.load(this, lang, history?.context() ?: emptyList(), onReady = {
            Log.i(TAG, "brain ready lang=$lang pending=${pendingText != null}")
            brainLoading = false; brainReady = true; brainLang = lang; brainError = ""; drawState(); flushPending()
        }, onError = { e -> loadFailed(e) })
    }

    /** 모델 올리기 실패 — 램 부족이면 까닭을 말하고 PC 연결 모드로 돌아갈 길을 준다(앱은 안 죽는다). */
    private fun loadFailed(e: String) {
        brainLoading = false; brainReady = false
        if (SoloBrain.isNoMem(e)) {
            brainError = getString(R.string.solo_nomem_title)
            Bus.line("sys", getString(R.string.solo_nomem_msg)); drawState(); showNoMem()
        } else {
            brainError = e
            Bus.line("sys", getString(R.string.solo_load_fail, e)); drawState()
        }
    }

    private fun showNoMem() {
        if (isFinishing || isDestroyed) return
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.solo_nomem_title))
            .setMessage(getString(R.string.solo_nomem_msg))
            .setPositiveButton(getString(R.string.solo_mode_pc)) { _, _ -> switchToPc() }
            .setNegativeButton(getString(R.string.solo_retry)) { _, _ -> retryLoad() }
            .show()
    }

    /** 램 부족으로 실패한 뒤 '다시 해 보기' — 엔진을 닫고 다시 올린다(닫기·올리기가 같은 줄에서 차례로). */
    private fun retryLoad() {
        brainError = ""; brainReady = false; drawState()
        SoloBrain.close()
        ensureBrain()
    }

    private var brainLang = ""
    private fun flushPending() {
        val t = pendingText
        Log.i(TAG, "flush pending=${t != null} ready=$brainReady")
        if (t != null) { pendingText = null; sendText(t) }
    }

    private fun sendInput() {
        val t = input?.text?.toString()?.trim() ?: return
        if (t.isEmpty()) return
        input?.setText("")
        sendText(t)
    }

    private fun sendText(t: String) {
        Log.i(TAG, "sendText ready=$brainReady loading=$brainLoading gen=$generating: $t")
        if (t.isBlank()) return
        if (!brainReady) {
            pendingText = t
            if (!brainLoading) ensureBrain()
            toast(getString(R.string.solo_loading)); return
        }
        if (generating) { toast(getString(R.string.solo_busy)); return }
        generating = true
        val my = ++sendGen
        userAction = SoloAction.fromUser(t)   // 모델이 PHONE 줄을 빠뜨려도 폰 일은 되게(안전망)
        userText = t
        liveBuf = ""
        history?.add("me", t)
        addLineView("me", t)
        liveView = Ui.text(this, "", 17f, Ui.TEXT).apply { layoutParams = lp().apply { rightMargin = dp(this@SoloActivity, 24) } }
        log?.addView(liveView); scrollDown()
        try { tts?.stop() } catch (_: Throwable) {}
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        drawState()
        SoloBrain.send(t, onDelta = { d ->
            if (my != sendGen) return@send
            liveBuf += d
            liveView?.text = visible(liveBuf).ifEmpty { "…" }
            scrollDown()
        }, onDone = { full ->
            if (my != sendGen) return@send
            finishReply(full)
        }, onError = { e ->
            if (my != sendGen) return@send
            generating = false; userAction = null; userText = ""; window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            val nomem = SoloBrain.isNoMem(e)
            val m = if (nomem) getString(R.string.solo_nomem_title) else getString(R.string.solo_error, e)
            liveView?.text = m
            liveView = null
            Bus.line("sys", if (nomem) getString(R.string.solo_nomem_msg) else m); drawState()
            if (nomem) { brainError = getString(R.string.solo_nomem_title); drawState(); showNoMem() }
            Log.i(TAG, "error lang=$lang $e")
        })
    }

    private fun finishReply(full: String) {
        val p = SoloAction.parse(full)
        // 모델이 app 칸을 빼먹었으면 사용자가 말한 앱 이름으로 채운다(사용자 말 우선).
        val act = SoloAction.enrich(p.action, userText)
        val fallback = userAction
        userAction = null
        userText = ""
        var text = p.text
        if (p.action == null && fallback != null) {
            // 모델이 PHONE 줄을 안 붙였어도 사용자가 부탁한 폰 일은 한다. 답도 폰이 한 결과로 바꾼다.
            try {
                val r = Doer(this).run(fallback)
                text = r.optString("말").ifBlank { p.text }
                Log.i(TAG, "fallback action ${fallback.optString("do")} ok=${r.optBoolean("ok")} $text")
            } catch (t: Throwable) {
                Log.w(TAG, "fallback action failed", t)
            }
        }
        if (liveView != null) {
            liveView?.text = text.ifBlank { "…" }
            liveView = null
        }
        if (text.isNotBlank()) { history?.add("bot", text); speak(text) }
        scrollDown()
        if (act != null) runAction(act)
        generating = false
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        drawState()
        Log.i(TAG, "reply lang=$lang text=${text.replace('\n', ' ')}")
    }

    private fun stopReply() {
        if (!generating) return
        sendGen++
        generating = false
        userAction = null
        userText = ""
        SoloBrain.stop()
        liveView?.text = visible(liveBuf).ifBlank { getString(R.string.solo_stopped) }
        liveView = null
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        Bus.line("sys", getString(R.string.solo_stopped)); drawState()
    }

    private fun runAction(a: JSONObject) {
        try {
            val r = Doer(this).run(a)
            val said = r.optString("말")
            Bus.line("sys", if (r.optBoolean("ok")) getString(R.string.solo_action_result, said)
                else getString(R.string.solo_action_fail, said))
            Log.i(TAG, "action ${a.optString("do")} ok=${r.optBoolean("ok")} $said")
        } catch (t: Throwable) {
            Bus.line("sys", getString(R.string.solo_action_fail, t.message ?: t.javaClass.simpleName))
        }
    }

    private fun askNewChat() {
        AlertDialog.Builder(this).setMessage(getString(R.string.solo_new_chat_confirm))
            .setPositiveButton(android.R.string.ok) { _, _ -> newChat() }
            .setNegativeButton(android.R.string.cancel, null).show()
    }

    private fun newChat() {
        sendGen++
        generating = false
        userAction = null
        userText = ""
        SoloBrain.stop()
        history?.clear()
        if (brainReady) {
            SoloBrain.reset(lang, emptyList(), onReady = {
                brainReady = true; brainLoading = false; screen = "chat"; show()
            }, onError = { e ->
                brainReady = false; brainLoading = false
                Bus.line("sys", getString(R.string.solo_load_fail, e)); screen = "chat"; show()
            })
        } else {
            brainReady = false
            screen = "chat"; show()
        }
    }

    private fun addLineView(who: String, text: String) {
        log?.let { lg -> if (lg.childCount == 1 && history?.lines?.size == 1) lg.removeAllViews() }
        log?.addView(lineView(who, text)); scrollDown()
    }

    private fun addSys(text: String) {
        log?.addView(lineView("sys", text)); scrollDown()
    }

    private fun lineView(who: String, text: String): View = when (who) {
        "me" -> Ui.text(this, text, 16f, Ui.TEXT).apply {
            background = Ui.bg(Ui.RAISED, 14, this@SoloActivity); setPadding(dp(this@SoloActivity, 12), dp(this@SoloActivity, 8), dp(this@SoloActivity, 12), dp(this@SoloActivity, 8))
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                gravity = Gravity.END; leftMargin = dp(this@SoloActivity, 48) }
        }
        "bot" -> Ui.text(this, text, 17f, Ui.TEXT).apply { layoutParams = lp().apply { rightMargin = dp(this@SoloActivity, 24) } }
        else -> Ui.text(this, text, 13f, Ui.MUTED).apply { layoutParams = lp() }
    }

    private fun drawPetlessLog() {
        val lg = log ?: return
        lg.removeAllViews()
        val h = history?.lines ?: emptyList()
        if (h.isEmpty()) lg.addView(Ui.text(this, getString(R.string.solo_greeting), 14f, Ui.MUTED))
        for (l in h) lg.addView(lineView(l.who, l.text))
        scrollDown()
    }

    private fun scrollDown() { logScroll?.post { logScroll?.fullScroll(View.FOCUS_DOWN) } }

    private fun drawState() {
        val st = when {
            brainLoading -> getString(R.string.solo_loading)
            generating -> getString(R.string.solo_thinking)
            brainReady -> getString(R.string.solo_ready_state)
            brainError.isNotEmpty() -> getString(R.string.solo_load_fail, brainError)
            else -> getString(R.string.solo_loading)
        }
        stateText?.text = st
        (stateDot?.background as? android.graphics.drawable.GradientDrawable)?.setColor(
            when { brainLoading || generating -> Ui.ACCENT; brainReady -> Ui.OK; else -> Ui.MUTED })
        sendBtn?.isEnabled = brainReady && !generating
        micBtn?.isEnabled = brainReady && !generating && recognizerAvailable()
        sendBtn?.alpha = if (sendBtn?.isEnabled == true) 1f else 0.5f
        micBtn?.alpha = if (micBtn?.isEnabled == true) 1f else 0.5f
        stopBtn?.visibility = if (generating) View.VISIBLE else View.GONE
        retryBtn?.visibility = if (brainError.isNotEmpty()) View.VISIBLE else View.GONE
    }

    private val phoneLine = Regex("(?m)^[ \t]*`?PHONE.*$")
    private fun visible(s: String) = s.replace(phoneLine, "").trimEnd()

    // ---------------------------------------------------------------- 말하기·읽기
    private fun recognizerAvailable(): Boolean =
        try { Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).resolveActivity(packageManager) != null } catch (_: Throwable) { false }

    private fun listen() {
        if (generating) return
        val i = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, Lang.bcp47(lang))
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, Lang.bcp47(lang))
            .putExtra(RecognizerIntent.EXTRA_PROMPT, getString(R.string.solo_mic))
        try {
            if (i.resolveActivity(packageManager) == null) { toast(getString(R.string.solo_unavailable)); return }
            startActivityForResult(i, 20)
        } catch (_: Throwable) { toast(getString(R.string.solo_unavailable)) }
    }

    private fun initTts() {
        try {
            tts = TextToSpeech(this) { st ->
                Log.i(TAG, "tts init status=$st")
                if (st == TextToSpeech.SUCCESS) { ttsOk = true; applyTtsLang() }
            }
        } catch (_: Throwable) { tts = null; Log.w(TAG, "tts create failed") }
    }

    private fun applyTtsLang(): Boolean {
        val t = tts ?: return false
        if (!ttsOk) return false
        if (ttsLang == lang && !ttsTried) return true
        ttsTried = true
        val r = try { t.setLanguage(Lang.locale(lang)) } catch (_: Throwable) { TextToSpeech.LANG_NOT_SUPPORTED }
        ttsLang = lang
        Log.i(TAG, "tts lang=$lang result=$r")
        if (r == TextToSpeech.LANG_MISSING_DATA || r == TextToSpeech.LANG_NOT_SUPPORTED) {
            val r2 = try { t.setLanguage(Locale.getDefault()) } catch (_: Throwable) { TextToSpeech.LANG_NOT_SUPPORTED }
            if (r2 == TextToSpeech.LANG_MISSING_DATA || r2 == TextToSpeech.LANG_NOT_SUPPORTED) { ttsOk = false; return false }
        }
        return true
    }

    private fun speak(s: String) {
        if (!Store.flag(this, "solo_speak", true)) return
        val t = tts ?: return
        if (!applyTtsLang()) { if (!ttsTried) toast(getString(R.string.solo_tts_unavailable)); return }
        val clean = s.replace(Regex("[*#`>]"), "").replace(Regex("\\s+"), " ").trim().take(1200)
        if (clean.isEmpty()) return
        try { t.speak(clean, TextToSpeech.QUEUE_FLUSH, null, "solo") } catch (_: Throwable) {}
    }

    @Deprecated("Activity 결과")
    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        if (req == 20 && res == RESULT_OK) {
            val t = data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.trim()
            if (!t.isNullOrEmpty()) { input?.setText(t); sendText(t) }
        }
    }

    override fun onRequestPermissionsResult(req: Int, perms: Array<out String>, res: IntArray) {
        super.onRequestPermissionsResult(req, perms, res)
        // 연락처 권한을 허용하면 다음에 같은 부탁을 하면 된다(모델이 다시 부른다).
    }

    // ---------------------------------------------------------------- 설정
    private fun settingsScreen() {
        screen = "settings"
        val p = page()
        p.addView(Ui.button(this, getString(R.string.solo_settings_back), Ui.Kind.QUIET) { screen = "chat"; show() }.apply {
            gravity = Gravity.START or Gravity.CENTER_VERTICAL; setPadding(0, 0, 0, 0) })
        p.addView(Ui.text(this, getString(R.string.solo_settings), 26f, Ui.TEXT, true))
        val c = Ui.card(this, 8)
        c.addView(Ui.text(this, getString(R.string.solo_lang_title), 16f, Ui.TEXT, true))
        val cur = Store.str(this, "lang", "auto")
        val opts = listOf("auto" to getString(R.string.solo_lang_auto), "ko" to "한국어", "en" to "English", "ja" to "日本語", "zh" to "中文")
        for ((code, name) in opts) {
            val sel = cur == code
            c.addView(TextView(this).apply {
                text = name; setTextColor(if (sel) Ui.TEXT else Ui.TEXT2); textSize = 15f
                setPadding(dp(this@SoloActivity, 14), dp(this@SoloActivity, 12), dp(this@SoloActivity, 14), dp(this@SoloActivity, 12))
                background = Ui.bg(if (sel) Ui.RAISED else android.graphics.Color.TRANSPARENT, 10, this@SoloActivity, 1, if (sel) Ui.ACCENT else Ui.LINE)
                setOnClickListener {
                    if (code != cur) { Store.setStr(this@SoloActivity, "lang", code); recreate() }
                }
            }, lp())
        }
        c.addView(Ui.text(this, getString(R.string.solo_lang_help), 13f, Ui.MUTED))
        p.addView(c, lp())

        val s = Ui.card(this, 8)
        s.addView(switchRow(getString(R.string.solo_speak_switch), Store.flag(this, "solo_speak", true)) { v ->
            Store.setFlag(this, "solo_speak", v)
            if (!v) try { tts?.stop() } catch (_: Throwable) {}
        }, lp())
        s.addView(Ui.text(this, getString(R.string.solo_speak_help), 13f, Ui.MUTED))
        s.addView(Ui.text(this, getString(R.string.solo_mic_help), 13f, Ui.MUTED))
        p.addView(s, lp())

        val m = Ui.card(this, 8)
        m.addView(Ui.text(this, getString(R.string.solo_model_section), 16f, Ui.TEXT, true))
        if (SoloModel.ready(this)) {
            m.addView(Ui.text(this, getString(R.string.solo_model_ready_short, SoloModel.human(SoloModel.SIZE)), 14f, Ui.TEXT2))
            m.addView(Ui.button(this, getString(R.string.solo_delete), Ui.Kind.DANGER) { askDelete() }, lp())
            m.addView(Ui.button(this, getString(R.string.solo_model_title), Ui.Kind.SECONDARY) { screen = "model"; show() }, lp())
        } else {
            m.addView(Ui.text(this, getString(R.string.solo_model_missing_short), 14f, Ui.TEXT2))
            m.addView(Ui.button(this, getString(R.string.solo_model_title), Ui.Kind.SECONDARY) { screen = "model"; show() }, lp())
        }
        p.addView(m, lp())

        p.addView(Ui.button(this, getString(R.string.solo_clear_history), Ui.Kind.DANGER) {
            AlertDialog.Builder(this).setMessage(getString(R.string.solo_new_chat_confirm))
                .setPositiveButton(android.R.string.ok) { _, _ ->
                    history?.clear(); toast(getString(R.string.solo_clear_done))
                    if (brainReady) SoloBrain.reset(lang, emptyList(), onReady = {}, onError = {})
                }.setNegativeButton(android.R.string.cancel, null).show()
        }, lp())
        p.addView(Ui.text(this, getString(R.string.solo_notice), 13f, Ui.MUTED))
        p.addView(Ui.button(this, getString(R.string.solo_mode_pc), Ui.Kind.SECONDARY) {
            AlertDialog.Builder(this).setMessage(getString(R.string.solo_mode_pc_confirm))
                .setPositiveButton(android.R.string.ok) { _, _ -> switchToPc() }
                .setNegativeButton(android.R.string.cancel, null).show()
        }, lp())
        p.addView(Ui.text(this, getString(R.string.solo_mode_pc_help), 13f, Ui.MUTED))
        p.addView(Ui.text(this, getString(R.string.solo_license_body), 12f, Ui.MUTED))
        p.addView(Ui.text(this, getString(R.string.solo_settings_version, BuildConfig.VERSION_NAME), 12f, Ui.MUTED))
    }

    private fun switchToPc() {
        Store.setMode(this, "pc")
        startActivity(Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        finish()
    }

    private fun switchRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit): android.widget.Switch =
        android.widget.Switch(this).apply {
            text = label; setTextColor(Ui.TEXT); textSize = 15f; isChecked = checked
            val st = arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf())
            thumbTintList = android.content.res.ColorStateList(st, intArrayOf(Ui.TEXT, Ui.TEXT2))
            trackTintList = android.content.res.ColorStateList(st, intArrayOf(Ui.ACCENT_FILL, Ui.RAISED))
            setOnCheckedChangeListener { _, v -> onChange(v) }
        }

    private fun toast(s: String) = android.widget.Toast.makeText(this, s, android.widget.Toast.LENGTH_SHORT).show()

    companion object { const val TAG = "KimbiseoSolo" }
}