package kr.kimbiseo.phone

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.ContactsContract
import org.json.JSONArray
import org.json.JSONObject

/**
 * PC 김비서가 보낸 폰 일(phone_do) 하기 — 다른 앱 화면을 '여는' 것까지만.
 *  navigate: 길안내 앱 검색 화면(안 열리면 다음 앱 → 웹 지도) · dial: 전화 앱에 번호 채우기(걸기는 사용자가) · sms: 문자 앱에 받는 사람·내용 채우기(보내기는 사용자가) · open_app: 앱 열기 ·
 *  search: 쇼핑·배달·검색 앱의 검색 화면 열기(앱이 없으면 웹 검색 · 장바구니·주문·결제는 사용자가).
 *  김비서 화면이 앞에 있으면 바로 열고, 뒤에 있으면(안드로이드가 뒤에서 다른 앱 열기를 막음) '눌러서 열기' 알림을 띄운다.
 *  연락처는 이 폰 안에서만 찾고 PC 로는 결과 한 줄(열었음·비슷한 이름)만 보낸다.
 */
class Doer(private val ctx: Context) {
    companion object { const val CH = "open"; private var nid = 100 }

    /** 깔려 있고 켜져 있음(설정에서 '사용 중지'한 앱은 깔려 있어도 안 열림) */
    private fun installed(pkg: String) = try { ctx.packageManager.getApplicationInfo(pkg, 0).enabled } catch (_: Throwable) { false }

    fun run(m: JSONObject): JSONObject = try {
        when (m.optString("do")) {
            "navigate" -> navigate(m.optString("destination").take(80), m.optString("app"))
            "dial", "sms" -> talk(m.optString("do"), m.optString("number"), m.optString("contact"), m.optString("message").take(500))
            "open_app" -> openApp(m.optString("app").take(40))
            "search" -> search(m.optString("app").take(40), m.optString("query").take(80))
            else -> res(false, ctx.getString(R.string.doer_unknown))
        }
    } catch (e: Throwable) { res(false, ctx.getString(R.string.doer_open_failed, e.javaClass.simpleName)) }

    private fun res(ok: Boolean, said: String) = JSONObject().put("ok", ok).put("말", said)

    /** 앞에 있으면 바로, 아니면 알림. 돌려주는 글은 PC 김비서가 그대로 읽음 */
    private fun open(i: Intent, title: String, done: String): String {
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Bus.visible) {
            ctx.startActivity(i)
            return done
        }
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CH, ctx.getString(R.string.notif_channel_open), NotificationManager.IMPORTANCE_HIGH))
        val id = ++nid
        val pi = PendingIntent.getActivity(ctx, id, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(id, Notification.Builder(ctx, CH).setSmallIcon(R.drawable.ic_note).setContentTitle(title)
            .setContentText(ctx.getString(R.string.notif_open_tap)).setContentIntent(pi).setAutoCancel(true).build())
        return ctx.getString(R.string.doer_tap_notification, done)
    }

    /** NavRules 의 한국어 앱 이름·안내 문구를 기기 언어로 */
    private fun appName(a: String): String = when (a) {
        "카카오맵" -> ctx.getString(R.string.nav_app_kakaomap)
        "네이버지도" -> ctx.getString(R.string.nav_app_naver)
        "티맵" -> ctx.getString(R.string.nav_app_tmap)
        "구글지도" -> ctx.getString(R.string.nav_app_google)
        "카카오내비" -> ctx.getString(R.string.nav_app_kakaonavi)
        "웹 카카오맵" -> ctx.getString(R.string.nav_app_web)
        else -> a
    }

    private fun note(n: String): String = when (n) {
        "검색 결과에서 '길찾기'를 눌러 주세요" -> ctx.getString(R.string.nav_note_route)
        "검색 결과에서 목적지를 골라 주세요" -> ctx.getString(R.string.nav_note_pick)
        "검색 결과에서 '경로'를 눌러 주세요" -> ctx.getString(R.string.nav_note_route_google)
        "목적지 이름을 복사해 뒀어요 — 검색창에 붙여 넣어 주세요" -> ctx.getString(R.string.nav_note_kakaonavi)
        else -> n
    }

    private fun navigate(dest: String, app: String): JSONObject {
        if (dest.isEmpty()) return res(false, ctx.getString(R.string.doer_no_destination))
        val tm = ctx.getSystemService(android.telephony.TelephonyManager::class.java)
        val korea = NavRules.inKorea(dest, listOf(tm?.networkCountryIso, tm?.simCountryIso))
        val pm = ctx.packageManager
        // 모델·PC 가 "카카오내비" 같은 이름을 보내도 키(kakaonavi)로 맞춘다.
        val want = NavAppRules.canonical(app) ?: app
        // 앞의 앱이 안 열리면(사용 중지·주소를 못 받음) 다음 깔린 앱 → 웹 카카오맵
        for (t in NavRules.candidates(dest, want, ::installed, ctx.packageName, korea)) {
            val i = if (t.pkg == NavRules.KAKAONAVI) pm.getLaunchIntentForPackage(t.pkg) ?: continue
                    else Intent(Intent.ACTION_VIEW, Uri.parse(t.uri)).also { if (t.pkg.isNotEmpty()) it.setPackage(t.pkg) }
            if (t.pkg.isNotEmpty() && i.resolveActivity(pm) == null) continue
            val instead = NavRules.label(want).let { if (it.isNotEmpty() && it != t.app) ctx.getString(R.string.doer_instead, appName(it)) + " " else "" }
            val said = try {
                if (t.pkg == NavRules.KAKAONAVI) {
                    ctx.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText(ctx.getString(R.string.clip_destination), dest))
                    open(i, ctx.getString(R.string.doer_kakaonavi_title, dest),
                        ctx.getString(R.string.doer_kakaonavi_opened, instead, note(t.note)))
                } else {
                    val noteText = if (t.note.isNotEmpty()) " " + ctx.getString(R.string.doer_nav_note, note(t.note)) else ""
                    open(i, ctx.getString(R.string.doer_nav_title, dest),
                        ctx.getString(R.string.doer_nav_opened, instead, appName(t.app), dest, noteText))
                }
            } catch (_: android.content.ActivityNotFoundException) { continue } catch (_: SecurityException) { continue }
            Bus.line("sys", ctx.getString(R.string.doer_nav_log, appName(t.app), dest))
            android.util.Log.i("KimbiseoDoer", "navigate dest=$dest want=${want.ifEmpty { "(none)" }} -> ${t.app} ${t.pkg}")
            return res(true, said)
        }
        android.util.Log.i("KimbiseoDoer", "navigate dest=$dest want=${want.ifEmpty { "(none)" }} -> no map")
        return res(false, ctx.getString(R.string.doer_no_map))
    }

    /** 쇼핑·배달·검색 앱의 검색 화면으로 연다. 앱이 없거나 검색 주소가 없으면 웹 검색 / 복사 안내. */
    private fun search(app: String, query: String): JSONObject {
        val q = query.trim()
        if (q.isEmpty()) return res(false, ctx.getString(R.string.doer_no_search_query))
        val key = SearchRules.canonical(app) ?: SearchRules.find(app)?.key
        val key2 = key ?: ""
        val label = if (key2.isEmpty()) ctx.getString(R.string.search_app_web) else searchName(key2)
        val shopping = SearchRules.shopping(key2)
        val pm = ctx.packageManager
        val pkg = SearchRules.pkg(key2)

        // 크롬: 구글 검색을 크롬으로. 크롬이 없으면 기본 브라우저.
        if (key2 == SearchRules.CHROME) {
            val i = Intent(Intent.ACTION_VIEW, Uri.parse(SearchRules.chrome(q)))
            val chrome = SearchRules.PKG_CHROME
            val hasChrome = installed(chrome)
            if (hasChrome) i.setPackage(chrome)
            return try {
                val said = if (hasChrome) ctx.getString(R.string.doer_search_chrome, q)
                            else ctx.getString(R.string.doer_search_browser, q)
                android.util.Log.i("KimbiseoDoer", "search app=chrome q=$q -> ${if (hasChrome) "chrome" else "browser"} ${SearchRules.chrome(q)}")
                Bus.line("sys", ctx.getString(R.string.doer_search_log, ctx.getString(R.string.search_app_chrome), q))
                res(true, open(i, ctx.getString(R.string.doer_search_title, q), said))
            } catch (_: Throwable) { res(false, ctx.getString(R.string.doer_no_search_app, label)) }
        }

        // 배민·쿠팡이츠: 공개 검색 딥링크가 없어 검색어 복사 + 앱 열기 + 붙여넣기 안내.
        if (SearchRules.copyOnly(key2)) {
            val launch = if (pkg != null && installed(pkg)) pm.getLaunchIntentForPackage(pkg) else null
            if (launch != null) {
                try {
                    ctx.getSystemService(ClipboardManager::class.java)
                        .setPrimaryClip(ClipData.newPlainText(ctx.getString(R.string.clip_search), q))
                    val said = open(launch, ctx.getString(R.string.doer_search_title, q), ctx.getString(R.string.doer_search_copy, label, q))
                    android.util.Log.i("KimbiseoDoer", "search app=$key2 q=$q -> copy+open $pkg")
                    Bus.line("sys", ctx.getString(R.string.doer_search_log, label, q))
                    return res(true, said)
                } catch (_: Throwable) {}
            }
            // 앱이 없으면 구글에서 앱 이름과 함께 찾는다.
            return openSearchWeb(key2, label, q, shopping)
        }

        // 쿠팡·유튜브·네이버: 앱이 있으면 그 앱의 검색 화면으로 바로.
        val direct = SearchRules.direct(key2, q)
        if (pkg != null && direct != null && installed(pkg)) {
            val i = Intent(Intent.ACTION_VIEW, Uri.parse(direct)).setPackage(pkg)
            if (i.resolveActivity(pm) != null) {
                return try {
                    val said = if (shopping) ctx.getString(R.string.doer_search_manual, label, q)
                                else ctx.getString(R.string.doer_search_done, label, q)
                    val r = open(i, ctx.getString(R.string.doer_search_title, q), said)
                    android.util.Log.i("KimbiseoDoer", "search app=$key2 q=$q -> app $pkg")
                    Bus.line("sys", ctx.getString(R.string.doer_search_log, label, q))
                    res(true, r)
                } catch (_: Throwable) { openSearchWeb(key2, label, q, shopping) }
            }
            android.util.Log.i("KimbiseoDoer", "search app=$key2 q=$q -> $pkg cannot open, web")
        }
        return openSearchWeb(key2, label, q, shopping)
    }

    /** 앱이 없거나 앱 검색 주소가 안 열릴 때 — 그 앱의 웹 검색(없으면 구글). */
    private fun openSearchWeb(key: String, label: String, q: String, shopping: Boolean): JSONObject {
        val web = SearchRules.web(key, q)
        return try {
            val browserLabel = if (key.isEmpty()) ctx.getString(R.string.search_app_web) else label
            val said = if (shopping) ctx.getString(R.string.doer_search_web_manual, browserLabel, q)
                        else ctx.getString(R.string.doer_search_web_done, browserLabel, q)
            val r = open(Intent(Intent.ACTION_VIEW, Uri.parse(web)), ctx.getString(R.string.doer_search_title, q), said)
            android.util.Log.i("KimbiseoDoer", "search app=${key.ifEmpty { "(google)" }} q=$q -> web $web")
            Bus.line("sys", ctx.getString(R.string.doer_search_log, browserLabel, q))
            res(true, r)
        } catch (_: Throwable) { res(false, ctx.getString(R.string.doer_no_search_app, label)) }
    }

    private fun searchName(key: String): String = when (key) {
        SearchRules.COUPANG -> ctx.getString(R.string.search_app_coupang)
        SearchRules.EATS -> ctx.getString(R.string.search_app_coupangeats)
        SearchRules.BAEMIN -> ctx.getString(R.string.search_app_baemin)
        SearchRules.CHROME -> ctx.getString(R.string.search_app_chrome)
        SearchRules.NAVER -> ctx.getString(R.string.search_app_naver)
        SearchRules.YOUTUBE -> ctx.getString(R.string.search_app_youtube)
        else -> key.ifEmpty { ctx.getString(R.string.search_app_web) }
    }

    private fun talk(kind: String, number: String, contact: String, msg: String): JSONObject {
        var num = NameRules.digits(number)
        var who = ""
        if (num.isEmpty()) {
            val q = NameRules.cleanName(contact)
            if (q.isEmpty()) return res(false, ctx.getString(R.string.doer_no_contact_name))
            if (ctx.checkSelfPermission(Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
                Bus.post(Bus.Ev.NeedPerm(Manifest.permission.READ_CONTACTS, ctx.getString(R.string.doer_contacts_perm_why)))
                return res(false, ctx.getString(R.string.doer_contacts_perm_help))
            }
            val rows = ArrayList<Pair<String, String>>()
            ctx.contentResolver.query(ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                arrayOf(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER), null, null, null)?.use { c ->
                while (c.moveToNext()) { val n = c.getString(0) ?: continue; val p = c.getString(1) ?: continue; rows.add(Pair(n, p)) }
            }
            val r = NameRules.rank(q, rows)
            if (r.list.size == 1) { who = r.list[0].first; num = NameRules.digits(r.list[0].second) }
            else {
                val cands = (if (r.list.isNotEmpty()) r.list else r.near).map { it.first }.take(3)
                if (cands.isEmpty()) return res(false, ctx.getString(R.string.doer_contact_not_found, q))
                return JSONObject().put("ok", false).put("near", JSONArray(cands)).put("말", ctx.getString(R.string.doer_contact_ambiguous, q))
            }
        }
        if (num.length !in 3..15) return res(false, ctx.getString(R.string.doer_bad_number))
        val label = if (who.isNotEmpty()) "$who($num)" else num
        return if (kind == "dial") {
            res(true, open(Intent(Intent.ACTION_DIAL, Uri.fromParts("tel", num, null)),
                ctx.getString(R.string.doer_dial_title, label), ctx.getString(R.string.doer_dial_done, label)))
        } else {
            val i = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:$num"))
            if (msg.isNotEmpty()) i.putExtra("sms_body", msg)
            res(true, open(i, ctx.getString(R.string.doer_sms_title, label), ctx.getString(R.string.doer_sms_done, label)))
        }
    }

    private fun openApp(name: String): JSONObject {
        if (name.isEmpty()) return res(false, ctx.getString(R.string.doer_no_app_name))
        val pm = ctx.packageManager
        // 지도·내비는 서랍 이름(언어·띄어쓰기)이 달라도 패키지로 바로 연다.
        val navKey = NavAppRules.canonical(name)
        if (navKey != null) {
            val pkg = NavAppRules.pkg(navKey)
            val i = if (pkg != null && installed(pkg)) pm.getLaunchIntentForPackage(pkg) else null
            if (i != null) {
                val shown = appName(NavAppRules.display(navKey))
                android.util.Log.i("KimbiseoDoer", "open_app $name -> $navKey $pkg")
                return res(true, open(i, shown, ctx.getString(R.string.doer_app_opened, shown)))
            }
            android.util.Log.i("KimbiseoDoer", "open_app $name -> $navKey $pkg not installed")
        }
        val acts = pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .filter { it.activityInfo.packageName != ctx.packageName }
        val labels = acts.map { it.loadLabel(pm).toString() }
        val k = AppRules.best(name, labels)
        if (k < 0) { android.util.Log.i("KimbiseoDoer", "open_app $name -> label not found"); return res(false, ctx.getString(R.string.doer_app_not_found, name)) }
        val ai = acts[k].activityInfo
        val i = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setClassName(ai.packageName, ai.name)
        android.util.Log.i("KimbiseoDoer", "open_app $name -> label ${labels[k]} ${ai.packageName}")
        return res(true, open(i, labels[k], ctx.getString(R.string.doer_app_opened, labels[k])))
    }
}
