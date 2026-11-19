package kr.kimbiseo.phone

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
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
    private const val TAG = "KimbiseoSoloBrain"

    const val NO_MEM = SoloLoadFail.NO_MEM
    fun isNoMem(t: Throwable): Boolean = SoloLoadFail.isNoMem(t)
    fun isNoMem(s: String): Boolean = SoloLoadFail.isNoMem(s)
    private fun why(t: Throwable): String = SoloLoadFail.why(t)

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
                Log.i(TAG, "load start engine=${engine != null} conv=${conv != null} $lang")
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
                Log.i(TAG, "load done conv=${conv != null} alive=${conv?.isAlive}")
                main.post { onReady() }
            } catch (t: Throwable) {
                loaded = false
                Log.w(TAG, "load fail", t)
                val msg = why(t)
                main.post { onError(msg) }
            }
        }
    }

    /** 새 대화(지난 대화를 모델 문맥에서 뺌). 화면 기록은 화면이 지운다. */
    fun reset(lang: String, history: List<Pair<String, String>>, onReady: () -> Unit, onError: (String) -> Unit) {
        exec.execute {
            try {
                val e = engine ?: throw IllegalStateException("not loaded")
                try { conv?.close() } catch (_: Throwable) {}
                conv = e.createConversation(config(lang, history))
                convLang = lang; gen++
                main.post { onReady() }
            } catch (t: Throwable) {
                main.post { onError(why(t)) }
            }
        }
    }

    /** 대답을 흘려 보낸다. onDelta 는 새로 나온 조각. 끝나면 onDone(전체). */
    fun send(text: String, onDelta: (String) -> Unit, onDone: (String) -> Unit, onError: (String) -> Unit) {
        Log.i(TAG, "send() called busy=$busy gen=$gen")
        if (busy) { main.post { onError("busy") }; return }
        busy = true
        val my = ++gen
        val prompt = text + "\n\n" + SoloLang.directive(SoloLang.detect(text))
        exec.execute {
            Log.i(TAG, "send task gen=$my busy=$busy")
            val acc = StringBuilder()
            try {
                val cv = conv ?: throw IllegalStateException("not loaded")
                Log.i(TAG, "send start gen=$my alive=${cv.isAlive}")
                cv.sendMessageAsync(prompt, object : MessageCallback {
                    override fun onMessage(message: Message) {
                        if (my != gen) return
                        val t = message.toString()
                        if (t.isEmpty()) return
                        acc.append(t)
                        main.post { if (my == gen) onDelta(t) }
                    }
                    override fun onDone() {
                        busy = false
                        Log.i(TAG, "onDone gen=$my len=${acc.length}")
                        if (my != gen) return
                        val all = acc.toString()
                        main.post { if (my == gen) onDone(all) }
                    }
                    override fun onError(t: Throwable) {
                        busy = false
                        Log.w(TAG, "onError gen=$my", t)
                        val m = why(t)
                        main.post { if (my == gen) onError(m) }
                    }
                })
                Log.i(TAG, "send returned gen=$my")
            } catch (t: Throwable) {
                busy = false
                val m = why(t)
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
        Log.i(TAG, "close() queued")
        exec.execute {
            Log.i(TAG, "close() start")
            try { conv?.close() } catch (_: Throwable) {}
            try { engine?.close() } catch (_: Throwable) {}
            conv = null; engine = null; convLang = ""; loaded = false; busy = false; gen++
            Log.i(TAG, "close() done")
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

/** 모델을 올리다 난 실패의 분류 — 안드로이드 없이(단위 시험) 돌 수 있게 따로 둔다. */
object SoloLoadFail {
    /** 램이 모자란 실패를 화면이 알아보게 하는 표시(사람 글 대신). */
    const val NO_MEM = "nomem"
    private val memWords = Regex("(?i)out of memory|oom|failed to allocate|cannot allocate|insufficient memory|not enough memory|allocat")

    /** 램 부족 실패인가 — OutOfMemoryError 와 엔진이 '메모리 할당 실패'로 낸 오류. */
    fun isNoMem(t: Throwable): Boolean = t is OutOfMemoryError || memWords.containsMatchIn(t.message ?: "")

    fun isNoMem(s: String): Boolean = s == NO_MEM || memWords.containsMatchIn(s)

    fun why(t: Throwable): String = if (isNoMem(t)) NO_MEM else (t.message ?: t.javaClass.simpleName)
}

/** 폰 안 비서 지시문 — 앱 언어에 맞춰. 답도 사용자가 말한 언어로. 폰 일은 마지막 PHONE 한 줄로. */
object SoloPrompt {
    fun system(lang: String): String = when (lang) {
        "ko" -> """
            너는 '김비서'야. 이 폰 안에서만 돌아가는 작은 AI 비서야.
            - 사용자가 말한 언어로만, 짧고 다정하게 2~3문장으로 답해. 다른 언어를 섞지 마.
            - 아는 것만 말하고, 모르면 모른다고 해. PC(컴퓨터) 조작은 못 하지만, 이 폰에서 길안내·전화 화면·문자 화면·앱 열기는 할 수 있어.
            - 사용자가 길안내·전화·문자·앱 열기·검색을 부탁하면 반드시 답의 맨 마지막 줄에 정확히 한 줄을 붙여. (예: "설정 앱을 열어 줘" → PHONE {"do":"open_app","app":"설정"})
              PHONE {"do":"navigate","destination":"목적지","app":"kakaomap|naver|tmap|google|kakaonavi"}
              PHONE {"do":"dial","contact":"이름"}
              PHONE {"do":"sms","contact":"이름","message":"내용"}
              PHONE {"do":"open_app","app":"앱 이름"}
              PHONE {"do":"search","app":"coupang|coupangeats|baemin|chrome|naver|youtube","query":"검색어"}
            - app 칸은 사용자가 지도 앱을 말했을 때만 넣어(카카오맵=kakaomap, 네이버지도=naver, 티맵=tmap, 구글지도=google, 카카오내비=kakaonavi). 목적지 칸에는 앱 이름을 넣지 마.
            - 쇼핑·배달·검색 부탁은 search 로. 쿠팡=coupang, 쿠팡이츠=coupangeats, 배민=baemin, 크롬=chrome, 네이버=naver, 유튜브=youtube. "시켜줘"여도 검색 화면까지만 열고, 담기·주문·결제는 사용자가 직접 한다고 답해.
            - 그 밖에는 PHONE 줄을 쓰지 마. 목록·마크다운 없이 자연스러운 말로 답해.
        """.trimIndent()
        "ja" -> """
            あなたは「キム秘書」です。このスマートフォンの中だけで動く小さな AI 秘書です。
            - ユーザーが使った言語だけで、短くやさしく 2〜3 文で答えてください。ほかの言語を混ぜないでください。
            - 知っていることだけを言い、わからなければわからないと言ってください。PC の操作はできませんが、このスマホで道案内・電話画面・メッセージ画面・アプリを開くことはできます。
            - 道案内・電話・メッセージ・アプリを開くこと・検索を頼まれたら、必ず返事の最後の行に次の形を 1 行だけ付けてください。（例:「設定アプリを開いて」→ PHONE {"do":"open_app","app":"設定"}）
              PHONE {"do":"navigate","destination":"目的地","app":"kakaomap|naver|tmap|google|kakaonavi"}
              PHONE {"do":"dial","contact":"名前"}
              PHONE {"do":"sms","contact":"名前","message":"内容"}
              PHONE {"do":"open_app","app":"アプリ名"}
              PHONE {"do":"search","app":"coupang|coupangeats|baemin|chrome|naver|youtube","query":"検索語"}
            - app はユーザーが地図アプリを言ったときだけ入れてください（カカオマップ=kakaomap、ネイバー地図=naver、ティマップ=tmap、グーグルマップ=google、カカオナビ=kakaonavi）。目的地の欄にアプリ名を入れないでください。
            - 買い物・出前・検索の頼みは search で。クーパン=coupang、クーパンイーツ=coupangeats、ペミン=baemin、Chrome=chrome、ネイバー=naver、YouTube=youtube。「注文して」でも検索画面まで開き、カートに入れる・注文・支払いはご自身で押すと答えてください。
            - それ以外では PHONE の行を書かないでください。箇条書きやマークダウンは使わず、自然な話し言葉で。
        """.trimIndent()
        "zh" -> """
            你是「金秘书」，一个只在这部手机里运行的小型 AI 助手。
            - 只用用户所说的语言，简短亲切地回答 2~3 句。不要夹杂其他语言。
            - 只说你确定的事，不知道就说不知道。你不能操作电脑，但可以在这部手机上导航、打开电话/短信界面、打开应用。
            - 当用户要求导航、打电话、发短信、打开应用或搜索时，必须在回答的最后一行准确加上一行。（例如“打开设置”→ PHONE {"do":"open_app","app":"设置"}）
              PHONE {"do":"navigate","destination":"目的地","app":"kakaomap|naver|tmap|google|kakaonavi"}
              PHONE {"do":"dial","contact":"姓名"}
              PHONE {"do":"sms","contact":"姓名","message":"内容"}
              PHONE {"do":"open_app","app":"应用名"}
              PHONE {"do":"search","app":"coupang|coupangeats|baemin|chrome|naver|youtube","query":"搜索词"}
            - 只有用户提到地图应用时才填 app（卡卡奥地图=kakaomap、Naver地图=naver、T地图=tmap、谷歌地图=google、卡卡奥导航=kakaonavi）。目的地一栏不要写应用名。
            - 购物、外卖、搜索的请求用 search。酷澎=coupang、酷澎Eats=coupangeats、外卖民族=baemin、Chrome=chrome、Naver=naver、YouTube=youtube。即使说“下单”也只打开搜索画面，并回答加入购物车、下单、付款要自己按。
            - 其他情况不要写 PHONE 行。不要用列表或 Markdown，用自然的口语回答。
        """.trimIndent()
        else -> """
            You are Kim Biseo, a small assistant that runs entirely on this phone.
            - Reply only in the language the user used, in 2-3 short and friendly sentences. Do not mix languages.
            - Say only what you know; say you do not know otherwise. You cannot control a PC, but on this phone you can navigate, open the call/text screen, and open apps.
            - When the user asks for directions, a call, a text, to open an app, or a search, you MUST end your reply with exactly one line. (Example: "Open Settings" -> PHONE {"do":"open_app","app":"Settings"})
              PHONE {"do":"navigate","destination":"place","app":"kakaomap|naver|tmap|google|kakaonavi"}
              PHONE {"do":"dial","contact":"name"}
              PHONE {"do":"sms","contact":"name","message":"text"}
              PHONE {"do":"open_app","app":"app name"}
              PHONE {"do":"search","app":"coupang|coupangeats|baemin|chrome|naver|youtube","query":"search words"}
            - Put app only when the user named a map app (KakaoMap=kakaomap, Naver Map=naver, TMAP=tmap, Google Maps=google, KakaoNavi=kakaonavi). Do not put the app name in destination.
            - For shopping, delivery, or web/video searches use search. Coupang=coupang, Coupang Eats=coupangeats, Baemin=baemin, Chrome=chrome, Naver=naver, YouTube=youtube. Even for "order it", open only the search screen and say the user adds to cart, orders and pays.
            - Otherwise do not write a PHONE line. No lists or markdown.
        """.trimIndent()
    }
}