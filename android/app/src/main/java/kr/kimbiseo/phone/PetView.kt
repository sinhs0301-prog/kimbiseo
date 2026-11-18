package kr.kimbiseo.phone

import android.content.Context
import android.graphics.Color
import android.media.MediaPlayer
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.VideoView
import java.io.File

/**
 * 대화 화면 위쪽의 펫 — 앱 저장소에 받아 둔 webm/mp4 클립을 안드로이드 기본 VideoView 로 튼다.
 *  · 대기(idle)는 반복, 말하기(talk)도 반복(말이 끝나면 화면이 다시 대기로 바꿈), 인사(hello)는 한 번.
 *  · 소리는 없다(클립에 소리 트랙이 없고, 있어도 볼륨 0 — 김비서 목소리는 대화 소리가 낸다).
 *  · 새 영상 라이브러리를 넣지 않는다(ExoPlayer/Media3 없이 기본 재생기).
 */
class PetView(c: Context) : FrameLayout(c) {
    private val video = VideoView(c)
    private var curPath = ""
    private var looping = true
    var onEnded: (() -> Unit)? = null

    init {
        setBackgroundColor(Color.TRANSPARENT)
        addView(video, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        video.setOnPreparedListener { mp ->
            try { mp.setVolume(0f, 0f) } catch (_: Throwable) {}
            try { mp.isLooping = looping } catch (_: Throwable) {}
            try { mp.setVideoScalingMode(MediaPlayer.VIDEO_SCALING_MODE_SCALE_TO_FIT) } catch (_: Throwable) {}
            fit(mp)
            try { video.start() } catch (_: Throwable) {}
        }
        video.setOnCompletionListener { if (!looping) onEnded?.invoke() }
        video.setOnErrorListener { _, _, _ -> true }     // 깨진 클립 하나로 화면이 멈추지 않게
    }

    /** 영상 비율을 지키며 칸 가운데에 놓는다(VideoView 는 기본이 왼쪽 위). */
    private fun fit(mp: MediaPlayer) {
        val vw = mp.videoWidth
        val vh = mp.videoHeight
        val pw = width
        val ph = height
        if (vw <= 0 || vh <= 0 || pw <= 0 || ph <= 0) return
        val s = minOf(pw.toFloat() / vw, ph.toFloat() / vh)
        val lp = video.layoutParams as LayoutParams
        lp.width = (vw * s).toInt()
        lp.height = (vh * s).toInt()
        lp.gravity = Gravity.CENTER
        video.layoutParams = lp
    }

    fun play(file: File, loop: Boolean) {
        val path = file.absolutePath
        if (path == curPath && looping == loop && video.isPlaying) return
        curPath = path
        looping = loop
        try {
            video.stopPlayback()
            video.setVideoURI(android.net.Uri.fromFile(file))     // file:// 로 넘겨야 안드로이드 15 에서도 연다
            video.start()
        } catch (_: Throwable) { /* 다음 그리기에서 다시 */ }
    }

    fun pause() { try { video.pause() } catch (_: Throwable) {} }

    fun resume() { if (curPath.isNotEmpty()) try { video.start() } catch (_: Throwable) {} }

    fun clear() {
        curPath = ""
        try { video.stopPlayback() } catch (_: Throwable) {}
    }
}