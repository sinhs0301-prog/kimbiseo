package kr.kimbiseo.phone

import android.content.Context
import android.os.Handler
import android.os.Looper
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Conversation
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.LogSeverity
import com.google.ai.edge.litertlm.Message
import com.google.ai.edge.litertlm.MessageCallback
import com.google.ai.edge.litertlm.SamplerConfig
import java.util.concurrent.Executors

/**
 * 폰 안 AI(LiteRT-LM · Gemma 4 E2B) — 한 번에 한 대답. 화면이 부르고, 실제 계산은 전용 스레드에서.
 *  모델은 앱 저장소의 파일을 그대로 메모리에 매핑한다(인터넷 없음). 대화는 이 앱 안에만 있고 어디로도 안 보낸다.
 */
object SoloBrain {
    private val main = Handler(Looper.getMainLooper())
    private val exec = Executors.newSingleThreadExecutor { r -> Thread(r, "solo-brain").apply { isDaemon = true } }

    @Volatile private var engine: Engine? = null
    @Volatile private var conv: Conversation? = null
    @Volatile private var convLang = ""
    @Volatile private var gen = 0
    @Volatile var busy = false
        private set
    @Volatile var loaded = false
        private set

    fun load(c: Context, lang: String, history: List<Pair<String, String>>, onReady: () -> Unit, onError: (String) -> Unit) {
        val path = SoloModel.present(c)?.absolutePath
        if (path == null) { main.post { onError("missing") }; return }
        exec.execute {
            try {
                if (engine == null) {
                    try { Engine.setNativeMinLogSeverity(LogSeverity.ERROR) } catch (_: Throwable) {}
                    val cfg = EngineConfig(
                        modelPath = path,
                        backend = Backend.CPU(),
                        maxNumTokens = 4096,
                        cacheDir = c.cacheDir.absolutePath,
                    )
                    val e = Engine(cfg)
                    e.initialize()
                    engine = e
                }
                val e = engine
                if (conv == null || convLang != lang) {
                    try { conv?.close() } catch (_: Throwable) {}
                    conv = e?.createConversation(config(lang, history))
                    convLang = lang
                    gen++
                }
                loaded = true
                main.post { onReady() }
            } catch (t: Throwable) {
                loaded = false
                val msg = t.message ?: t.javaClass.simpleName
                main.post { onError(msg) }
            }
        }
    }

    /** 새 대화(지난 대화를 모델 문맥에서 뺌). 화면 기록은 화면이 지운다. */
    fun reset(lang: String, onReady: () -> Unit, onError: (String) -> Unit) {
        exec.execute {
            try {
                try { conv?.close() } catch (_: Throwable) {}
                conv = engine?.createConversation(config(lang, emptyList()))
                convLang = lang; gen++
                main.post { onReady() }
            } catch (t: Throwable) {
                main.post { onError(t.message ?: t.javaClass.simpleName) }
            }
        }
    }

    /** 대답을 흘려 보낸다. onDelta 는 새로 나온 조각. 끝나면 onDone(전체). */
    fun send(text: String, onDelta: (String) -> Unit, onDone: (String) -> Unit, onError: (String) -> Unit) {
        if (busy) { main.post { onError("busy") }; return }
        busy = true
        val my = ++gen
        exec.execute {
            val acc = StringBuilder()
            try {
                val cv = conv ?: throw IllegalStateException("not loaded")
                cv.sendMessageAsync(text, object : MessageCallback {
                    override fun onMessage(message: Message) {
                        if (my != gen) return
                        val t = message.toString()
                        if (t.isEmpty()) return
                        acc.append(t)
                        main.post { if (my == gen) onDelta(t) }
                    }
                    override fun onDone() {
                        busy = false
                        if (my != gen) return
                        val all = acc.toString()
                        main.post { if (my == gen) onDone(all) }
                    }
                    override fun onError(t: Throwable) {
                        busy = false
                        val m = t.message ?: t.javaClass.simpleName
                        main.post { if (my == gen) onError(m) }
                    }
                })
            } catch (t: Throwable) {
                busy = false
                val m = t.message ?: t.javaClass.simpleName
                main.post { if (my == gen) onError(m) }
            }
        }
    }

    fun stop() {
        gen++
        busy = false
        try { conv?.cancelProcess() } catch (_: Throwable) {}
    }

    /** 화면을 떠날 때 엔진을 닫아 메모리를 돌려준다. 다음에 다시 열면 모델을 다시 올린다(10초 안팎). */
    fun close() {
        exec.execute {
            try { conv?.close() } catch (_: Throwable) {}
            try { engine?.close() } catch (_: Throwable) {}
            conv = null; engine = null; convLang = ""; loaded = false; busy = false; gen++
        }
    }

    private fun config(lang: String, history: List<Pair<String, String>>): ConversationConfig {
        val msgs = ArrayList<Message>()
        for ((who, text) in history.takeLast(8)) {
            if (text.isBlank()) continue
            val t = text.take(600)
            if (who == "me") msgs.add(Message.user(t)) else msgs.add(Message.model(t))
        }
        while (msgs.isNotEmpty() && msgs[0].role == com.google.ai.edge.litertlm.Role.MODEL) msgs.removeAt(0)
        return ConversationConfig(
            systemInstruction = com.google.ai.edge.litertlm.Contents.of(SoloPrompt.system(lang)),
            initialMessages = msgs,
            samplerConfig = SamplerConfig(topK = 40, topP = 0.95, temperature = 0.7),
            maxOutputToken = 768,
        )
    }
}

/** 폰 안 비서 지시문 — 앱 언어에 맞춰. 답도 사용자가 말한 언어로. 폰 일은 마지막 PHONE 한 줄로. */
object SoloPrompt {
    fun system(lang: String): String = when (lang) {
        "ko" -> """
            너는 '김비서'야. 이 폰 안에서만 돌아가는 작은 AI 비서야.
            - 사용자가 말한 언어로 짧고 다정하게 2~3문장으로 답해.
            - 아는 것만 말하고, 모르면 모른다고 해. PC 조작은 못 한다고 해.
            - 길안내·전화·문자·앱 열기를 부탁하면 답의 맨 마지막 줄에 정확히 한 줄을 붙여.
              PHONE {"do":"navigate","destination":"목적지"}
              PHONE {"do":"dial","contact":"이름"}
              PHONE {"do":"sms","contact":"이름","message":"내용"}
              PHONE {"do":"open_app","app":"앱 이름"}
            - 그 밖에는 PHONE 줄을 쓰지 마. 목록·마크다운 없이 자연스러운 말로 답해.
        """.trimIndent()
        "ja" -> """
            あなたは「キム秘書」です。このスマートフォンの中だけで動く小さな AI 秘書です。
            - ユーザーが使った言語で、短くやさしく 2〜3 文で答えてください。
            - 知っていることだけを言い、わからなければわからないと言ってください。PC の操作はできません。
            - 道案内・電話・メッセージ・アプリを開くことを頼まれたら、返事の最後の行に次の形を 1 行だけ付けてください。
              PHONE {"do":"navigate","destination":"目的地"}
              PHONE {"do":"dial","contact":"名前"}
              PHONE {"do":"sms","contact":"名前","message":"内容"}
              PHONE {"do":"open_app","app":"アプリ名"}
            - それ以外では PHONE の行を書かないでください。箇条書きやマークダウンは使わず、自然な話し言葉で。
        """.trimIndent()
        "zh" -> """
            你是「金秘书」，一个只在这部手机里运行的小型 AI 助手。
            - 用用户所说的语言，简短亲切地回答 2~3 句。
            - 只说你确定的事，不知道就说不知道。你不能操作电脑。
            - 当用户要求导航、打电话、发短信或打开应用时，在回答的最后一行准确加上一行：
              PHONE {"do":"navigate","destination":"目的地"}
              PHONE {"do":"dial","contact":"姓名"}
              PHONE {"do":"sms","contact":"姓名","message":"内容"}
              PHONE {"do":"open_app","app":"应用名"}
            - 其他情况不要写 PHONE 行。不要用列表或 Markdown，用自然的口语回答。
        """.trimIndent()
        else -> """
            You are Kim Biseo, a small assistant that runs entirely on this phone.
            - Reply in the language the user used, in 2-3 short and friendly sentences.
            - Say only what you know; say you do not know otherwise. You cannot control a PC.
            - When the user asks for directions, a call, a text, or to open an app, end your reply with exactly one line:
              PHONE {"do":"navigate","destination":"place"}
              PHONE {"do":"dial","contact":"name"}
              PHONE {"do":"sms","contact":"name","message":"text"}
              PHONE {"do":"open_app","app":"app name"}
            - Otherwise do not write a PHONE line. No lists or markdown.
        """.trimIndent()
    }
}