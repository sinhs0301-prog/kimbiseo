package kr.kimbiseo.phone

import android.os.Handler
import android.os.Looper
import org.json.JSONObject

/** 서비스(대화) → 화면 소식. 화면이 닫혀 있어도 최근 줄은 남겨 두고, 다시 열면 그대로 그린다. 모든 호출은 주 스레드로 넘김. */
object Bus {
    sealed class Ev {
        data class Line(val who: String, val text: String) : Ev()          // me · bot · sys · gate
        data class State(val talking: Boolean, val text: String, val mic: Boolean) : Ev()
        data class Level(val v: Float) : Ev()                                // 내 말소리 크기 0~1
        data class Interp(val m: JSONObject) : Ev()
        data class Ask(val id: String, val text: String) : Ev()             // 실행할까요?
        data class AskDone(val id: String) : Ev()
        data class NeedPerm(val perm: String, val why: String) : Ev()
        data class Pc(val info: JSONObject) : Ev()                           // auth_ok 때 받은 PC 상태(비서 이름·판·PC 이름·통역·목소리확인·PC조작)
    }

    private val main = Handler(Looper.getMainLooper())
    @Volatile var visible = false
    var listener: ((Ev) -> Unit)? = null
    val lines = ArrayList<Ev.Line>()
    var state = Ev.State(false, "", false)
    var pc: JSONObject? = null
    var interp: JSONObject? = null
    var ask: Ev.Ask? = null

    fun post(e: Ev) {
        main.post {
            when (e) {
                is Ev.Line -> { lines.add(e); while (lines.size > 120) lines.removeAt(0) }
                is Ev.State -> state = e
                is Ev.Pc -> pc = e.info
                is Ev.Interp -> {   // 번역 사건엔 켜짐·언어 목록이 없어서 앞 상태에 덧씌움
                    val o = JSONObject((interp ?: JSONObject()).toString())
                    for (k in e.m.keys()) o.put(k, e.m.get(k))
                    interp = o
                }
                is Ev.Ask -> ask = e
                is Ev.AskDone -> if (ask?.id == e.id) ask = null
                else -> {}
            }
            listener?.invoke(e)
        }
    }

    fun line(who: String, text: String) = post(Ev.Line(who, text))
}
