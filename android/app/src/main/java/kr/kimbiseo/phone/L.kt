package kr.kimbiseo.phone

import android.content.Context

/** 화면·서비스 어디서나 앱 문구를 꺼내는 작은 도움. 화면/서비스가 처음 뜰 때 app context 를 넣는다. */
object L {
    @Volatile private var app: Context? = null

    fun init(c: Context) { if (app == null) app = c.applicationContext }

    fun s(id: Int, vararg args: Any): String {
        val c = app ?: return ""
        return if (args.isEmpty()) c.getString(id) else c.getString(id, *args)
    }
}