package kr.kimbiseo.phone.gh
import kr.kimbiseo.phone.Lang
import kr.kimbiseo.phone.R

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Toast
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * 장바구니 담기 조작 — 한 걸음씩(최대 15).
 *  화면 글자 읽기 → 두뇌에 다음 한 걸음 묻기 → 안전 검사(결제·주문·비밀번호 칸) → 누르기/글자 넣기 → 다시 읽기.
 *  담기 확인 문구가 보이면 멈추고 "장바구니에 담았어요, 결제는 직접 해 주세요".
 *  걸음마다 '김비서 조작 중 — 멈추기' 오버레이. 누르면 다음 차례에 멈춘다.
 */
object GhRunner {
    private const val TAG = "KimbiseoGh"
    const val MAX_STEPS = GhSafety.MAX_STEPS

    @Volatile var running = false; private set
    @Volatile var last = ""; private set
    @Volatile private var cancel = false
    private var overlay: GhOverlay? = null
    var listener: ((String) -> Unit)? = null
    private val main = Handler(Looper.getMainLooper())

    fun start(svc: GhAccessibilityService, goal: String, slowMs: Long = 0, maxSteps: Int = MAX_STEPS) {
        if (running) { say(s(svc, R.string.gh_busy)); return }
        running = true; cancel = false; last = ""
        overlay = GhOverlay(svc) { cancel = true; say(s(svc, R.string.gh_stopping)) }.also { it.show() }
        say(s(svc, R.string.gh_reading))
        Thread({ loop(svc, goal, slowMs, maxSteps) }, "kimbiseo-gh").start()
    }

    fun stop() { cancel = true }

    private fun loop(svc: GhAccessibilityService, goal: String, slowMs: Long, maxSteps: Int) {
        var success = false
        var finished = false
        try {
            var pkg = onMain("", svc) { svc.frontPackage() }
            val waitUntil = System.currentTimeMillis() + 12_000
            while (!GhSafety.targetOk(pkg) && System.currentTimeMillis() < waitUntil && !cancel) {
                Thread.sleep(400)
                pkg = onMain("", svc) { svc.frontPackage() }
            }
            if (cancel) { finish(svc, s(svc, R.string.gh_stopped)); finished = true; return }
            if (!GhSafety.targetOk(pkg)) {
                finish(svc, s(svc, R.string.gh_not_target)); finished = true; return
            }

            var brainErrors = 0
            for (step in 1..maxSteps) {
                if (cancel) { finish(svc, s(svc, R.string.gh_stopped)); finished = true; return }
                if (!GhSafety.stepAllowed(step)) break
                Thread.sleep(if (slowMs > 0) slowMs else 700)
                val nodes = onMain(emptyList<GhAccessibilityService.Node>(), svc) { svc.scan() }
                val labels = nodes.map { it.label }
                if (GhSafety.cartAdded(labels)) { success = true; break }
                val now = onMain("", svc) { svc.frontPackage() }
                if (!GhSafety.targetOk(now)) {
                    finish(svc, s(svc, R.string.gh_left_target)); finished = true; return
                }
                if (nodes.isEmpty()) continue

                val rep = GhBrain.ask(svc, goal, now, nodes)
                if (rep.decision == null) {
                    brainErrors++
                    Log.i(TAG, "step=$step brain error=${rep.error} raw=${rep.raw}")
                    if (rep.error == "brain") { finish(svc, s(svc, R.string.gh_no_brain)); finished = true; return }
                    if (brainErrors >= 5) { finish(svc, s(svc, R.string.gh_brain_fail)); finished = true; return }
                    continue
                }
                val d = rep.decision
                Log.i(TAG, "step=$step pkg=$now n=${nodes.size} decision=$d")
                when (d) {
                    is GhBrainReply.Decision.Done -> {
                        success = GhSafety.cartAdded(labels)
                        if (!success) {
                            finish(svc, s(svc, R.string.gh_done_check))
                            finished = true; return
                        }
                        break
                    }
                    is GhBrainReply.Decision.Back -> { onMain(false, svc) { svc.back() }; Thread.sleep(500) }
                    is GhBrainReply.Decision.Wait -> Thread.sleep(700)
                    is GhBrainReply.Decision.Tap -> {
                        val n = nodes.getOrNull(d.i)
                        if (n == null) continue
                        val blocked = GhSafety.blockedTap(n.label)
                        if (blocked != null) {
                            Log.i(TAG, "blocked tap i=${d.i} label=${n.label} word=$blocked")
                            finish(svc, s(svc, R.string.gh_blocked, n.label.ifBlank { blocked }))
                            finished = true; return
                        }
                        val ok = onMain(false, svc) { svc.tap(n) }
                        Log.i(TAG, "tap i=${d.i} ok=$ok label=${n.label}")
                        say(s(svc, R.string.gh_step_tap, n.label.take(40)))
                        Thread.sleep(500)
                    }
                    is GhBrainReply.Decision.Type -> {
                        val n = nodes.getOrNull(d.i)
                        if (n == null || !n.editable) continue
                        if (n.password || GhSafety.secretField(n.label)) {
                            Log.i(TAG, "secret field i=${d.i} label=${n.label}")
                            finish(svc, s(svc, R.string.gh_secret))
                            finished = true; return
                        }
                        val ok = onMain(false, svc) { svc.type(n, d.text) }
                        Log.i(TAG, "type i=${d.i} ok=$ok label=${n.label} text=${d.text}")
                        say(s(svc, R.string.gh_step_type, d.text.take(40)))
                        Thread.sleep(500)
                    }
                }
            }
            if (firstUnfinished(finished)) {
                finish(svc, if (success) s(svc, R.string.gh_done_cart)
                            else s(svc, R.string.gh_timeout, maxSteps))
                finished = true
            }
        } catch (t: Throwable) {
            Log.w(TAG, "runner failed", t)
            if (firstUnfinished(finished)) finish(svc, s(svc, R.string.gh_error, t.javaClass.simpleName))
        } finally {
            running = false
            overlay?.hide(); overlay = null
        }
    }

    /** finish 를 이미 했는지(성공 포함) — finally 전에 한 번만 알리기. */
    private fun firstUnfinished(finished: Boolean) = !finished

    private fun finish(svc: GhAccessibilityService, msg: String) {
        running = false
        overlay?.hide(); overlay = null
        say(msg)
        try { kr.kimbiseo.phone.Bus.line("bot", msg) } catch (_: Throwable) {}
        main.post { try { Toast.makeText(svc, msg, Toast.LENGTH_LONG).show() } catch (_: Throwable) {} }
        notify(svc, msg)
    }

    private fun notify(svc: GhAccessibilityService, msg: String) {
        try {
            val nm = svc.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel("gh", s(svc, R.string.gh_notif_channel), NotificationManager.IMPORTANCE_DEFAULT))
            val pi = PendingIntent.getActivity(svc, 0, Intent(svc, GhChatActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
            nm.notify(4101, Notification.Builder(svc, "gh")
                .setSmallIcon(kr.kimbiseo.phone.R.drawable.ic_note)
                .setContentTitle(s(svc, R.string.gh_notif_title))
                .setContentText(msg).setStyle(Notification.BigTextStyle().bigText(msg))
                .setContentIntent(pi).setAutoCancel(true).build())
        } catch (_: Throwable) {}
    }

    private fun say(s: String) {
        if (s.isBlank()) return
        last = s
        Log.i(TAG, "say: $s")
        main.post { listener?.invoke(s) }
    }

    /** 앱에서 고른 언어(한·영·일·중)로 서비스 문구를 꺼낸다 — 서비스는 폰 언어를 따르므로. */
    private fun s(c: android.content.Context, id: Int, vararg args: Any): String =
        if (args.isEmpty()) Lang.wrap(c).getString(id) else Lang.wrap(c).getString(id, *args)

    private fun <T> onMain(def: T, svc: GhAccessibilityService, block: () -> T): T {
        if (Looper.myLooper() == Looper.getMainLooper()) return try { block() } catch (_: Throwable) { def }
        val latch = CountDownLatch(1)
        var out: T = def
        main.post { try { out = block() } catch (_: Throwable) {} finally { latch.countDown() } }
        latch.await(4, TimeUnit.SECONDS)
        return out
    }
}