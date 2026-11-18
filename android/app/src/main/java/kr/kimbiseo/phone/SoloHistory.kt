package kr.kimbiseo.phone

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * 폰 단독 대화 기록 — 이 폰의 앱 저장소에만. 서버·PC 로 보내지 않는다.
 *  화면에 보여 줄 최근 200줄을 남기고, 모델에는 최근 8줄만 문맥으로 준다.
 */
class SoloHistory(private val c: Context) {
    data class Line(val who: String, val text: String, val t: Long)

    private val file = File(File(c.filesDir, "solo"), "history.json")
    val lines = ArrayList<Line>()

    init { load() }

    private fun load() {
        try {
            if (!file.isFile) return
            val a = JSONArray(file.readText())
            for (i in 0 until a.length()) {
                val o = a.optJSONObject(i) ?: continue
                val who = o.optString("who"); val text = o.optString("text")
                if ((who == "me" || who == "bot") && text.isNotEmpty()) lines.add(Line(who, text, o.optLong("t")))
            }
            while (lines.size > 200) lines.removeAt(0)
        } catch (_: Throwable) {}
    }

    fun add(who: String, text: String) {
        lines.add(Line(who, text, System.currentTimeMillis()))
        while (lines.size > 200) lines.removeAt(0)
        save()
    }

    fun clear() { lines.clear(); save() }

    /** 모델에 줄 문맥(사용자·비서 말만) */
    fun context(): List<Pair<String, String>> = lines.filter { it.who == "me" || it.who == "bot" }.map { it.who to it.text }

    private fun save() {
        try {
            file.parentFile?.mkdirs()
            val a = JSONArray()
            for (l in lines) a.put(JSONObject().put("who", l.who).put("text", l.text).put("t", l.t))
            val tmp = File(file.parentFile, "history.tmp")
            tmp.writeText(a.toString())
            if (!tmp.renameTo(file)) { file.writeText(a.toString()); tmp.delete() }
        } catch (_: Throwable) {}
    }
}