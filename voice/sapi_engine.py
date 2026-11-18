# 윈도우 기본 음성(SAPI) 예비 목소리 — 그래픽카드가 없거나 Qwen3-TTS 를 못 띄운 PC 용.
#
# - 윈도우에 들어 있는 System.Speech(파워셸 5.1)를 도우미 프로세스 하나로 띄워 두고 표준입출력으로 주고받는다.
#   새 패키지·모델 내려받기가 없고, torch 도 쓰지 않는다(그래픽카드와 무관).
# - 소리는 24kHz 16bit 모노로 만들어 Qwen 엔진과 같은 모양(float32 조각)으로 내놓는다 → 목소리 서버의
#   /tts·/tts_stream·/tts_lip 가 엔진만 바꿔 그대로 동작.
# - 한 문장을 다 만든 뒤 0.5초 조각으로 나눠 내보낸다(문장 단위 스트리밍).
# - 목소리: 설정 '목소리.윈도우_목소리'(이름 일부) → 없으면 한국어(ko-KR) 음성 중 첫째 → 없으면 윈도우 기본 음성.
# - 빠르기: SAPI Rate(-10~10)로 직접(1.2배 ≈ +2, 1.4배 ≈ +4).
# 주고받는 형식(도우미): 요청 "<rate> <글 UTF-8 base64>\n" → 응답 "OK <PCM base64>\n" 또는 "ERR <메시지 base64>\n"
import base64
import os
import subprocess
import threading
import time
import zlib

import numpy as np

SR = 24000

_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.Encoding]::ASCII
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$want = $env:KB_SAPI_VOICE
$voices = @($s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo })
$pick = $null
if ($want) { $pick = $voices | Where-Object { $_.Name -like ('*' + $want + '*') } | Select-Object -First 1 }
$cul = $env:KB_SAPI_CULTURE
if (-not $cul) { $cul = 'ko-KR' }
if (-not $pick) { $pick = $voices | Where-Object { $_.Culture.Name -eq $cul } | Select-Object -First 1 }
if (-not $pick) { $pre = $cul.Split('-')[0]; $pick = $voices | Where-Object { $_.Culture.Name -like ($pre + '-*') } | Select-Object -First 1 }
if ($pick) { $s.SelectVoice($pick.Name) }
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$out = [Console]::Out
$name = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($s.Voice.Name))
$out.WriteLine('READY ' + $name + ' ' + $s.Voice.Culture.Name + ' ' + $voices.Count)
$out.Flush()
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null) { break }
  try {
    $p = $line.Split(' ')
    $s.Rate = [Math]::Max(-10, [Math]::Min(10, [int]$p[0]))
    $text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($p[1]))
    $ms = New-Object System.IO.MemoryStream
    $s.SetOutputToAudioStream($ms, $fmt)
    $s.Speak($text)
    $s.SetOutputToNull()
    $out.WriteLine('OK ' + [Convert]::ToBase64String($ms.ToArray()))
  } catch {
    $out.WriteLine('ERR ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($_.Exception.Message)))
  }
  $out.Flush()
}
"""


def speed_to_rate(speed):
    try:
        sp = float(speed or 1.0)
    except (TypeError, ValueError):
        sp = 1.0
    return int(round(max(-10.0, min(10.0, (sp - 1.0) * 10.0))))


class SapiVoice:
    """Qwen 엔진(tts_engine.QwenVoice)과 같은 쪽 모양 — 목소리 서버가 엔진만 바꿔 씀."""
    cuda = False
    temp = "sapi"
    native_speed = True

    CULTURES = {"ko": "ko-KR", "en": "en-US", "ja": "ja-JP", "zh": "zh-CN"}

    def __init__(self, voice_hint="", piece_sec=0.5, log=print, timeout=60, lang="ko"):
        t0 = time.time()
        self.log = log
        self.hint = voice_hint or ""
        self.want_culture = self.CULTURES.get(str(lang or "ko")[:2], "ko-KR")
        self.piece = int(piece_sec * SR)
        self.timeout = timeout
        self.lock = threading.Lock()
        self.p = None
        self.voice_name, self.culture, self.n_voices = "", "", 0
        self.prompts = {"기본": None}   # 감정은 없음 — 모든 감정을 '기본'으로
        self.voices = {}
        self._start()
        if self.culture.split("-")[0] != self.want_culture.split("-")[0]:
            log(f"[윈도우 음성] {self.want_culture} 음성이 없음 → '{self.voice_name}'({self.culture}) 로 읽음. "
                "설정 > 시간 및 언어 > 음성에서 그 언어 음성을 추가하세요.")
        self.load_sec = time.time() - t0
        log(f"[윈도우 음성] 준비 {self.load_sec:.1f}초: {self.voice_name} ({self.culture}, 설치된 음성 {self.n_voices}개)")

    def _start(self):
        enc = base64.b64encode(_PS.encode("utf-16-le")).decode("ascii")
        env = {**os.environ, "KB_SAPI_VOICE": self.hint, "KB_SAPI_CULTURE": self.want_culture}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if not os.path.isfile(exe):
            exe = "powershell.exe"
        self.p = subprocess.Popen([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  env=env, creationflags=flags)
        first = self._readline()
        parts = first.split(" ")
        if not first.startswith("READY") or len(parts) < 3:
            self.close()
            raise RuntimeError(f"윈도우 음성 도우미 준비 실패: {first[:120]!r}")
        self.voice_name = base64.b64decode(parts[1]).decode("utf-8", "replace")
        self.culture = parts[2]
        self.n_voices = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

    def _readline(self):
        box = {}

        def rd():
            box["line"] = self.p.stdout.readline()
        t = threading.Thread(target=rd, daemon=True)
        t.start()
        t.join(self.timeout)
        if t.is_alive():
            self.close()
            raise TimeoutError("윈도우 음성 도우미 응답 없음")
        return (box.get("line") or b"").decode("ascii", "replace").strip()

    def close(self):
        if self.p is not None:
            try:
                self.p.stdin.close()
                self.p.wait(3)
            except Exception:  # noqa: BLE001
                try:
                    self.p.kill()   # 자기가 띄운 도우미만
                except Exception:  # noqa: BLE001
                    pass
            self.p = None

    def synth_pcm16(self, text, speed=1.0):
        """글 한 덩어리 → int16 24kHz numpy."""
        msg = f"{speed_to_rate(speed)} {base64.b64encode(text.encode('utf-8')).decode('ascii')}\n".encode("ascii")
        with self.lock:
            for attempt in range(2):
                try:
                    if self.p is None or self.p.poll() is not None:
                        self._start()
                    self.p.stdin.write(msg)
                    self.p.stdin.flush()
                    line = self._readline()
                    if line.startswith("OK"):
                        b = base64.b64decode(line[3:]) if len(line) > 3 else b""
                        return np.frombuffer(b[: len(b) - len(b) % 2], dtype="<i2").copy()
                    if line.startswith("ERR"):
                        raise RuntimeError(base64.b64decode(line[4:]).decode("utf-8", "replace"))
                    raise RuntimeError(f"알 수 없는 응답: {line[:80]!r}")
                except (OSError, TimeoutError, ValueError) as ex:
                    self.log(f"[윈도우 음성] 도우미 오류({attempt + 1}번째): {ex}")
                    self.close()
            raise RuntimeError("윈도우 음성 도우미가 두 번 실패")

    # ---- Qwen 엔진과 같은 모양 ----
    def voice_tag(self, voice=None):
        return "sapi-" + zlib.crc32(self.voice_name.encode("utf-8")).to_bytes(4, "big").hex()

    def seed_for(self, text, emotion):
        return 0

    def stream(self, text, emotion="기본", seed=None, stats=None, voice=None, speed=1.0, **_):
        t0 = time.perf_counter()
        pcm = self.synth_pcm16(text, speed).astype(np.float32) / 32768.0
        first = time.perf_counter() - t0
        for i in range(0, len(pcm), self.piece):
            yield pcm[i:i + self.piece]
        if stats is not None:
            stats.update(audio_sec=len(pcm) / SR, first_chunk_sec=first, total_sec=time.perf_counter() - t0, emotion="기본")

    def speak(self, text, emotion="기본", seed=None, stats=None, **kw):
        parts = list(self.stream(text, emotion, seed=seed, stats=stats, **kw))
        return np.concatenate(parts) if parts else np.zeros(0, np.float32)

    @staticmethod
    def to_int16(pcm):
        return (np.clip(pcm, -1, 1) * 32767).astype(np.int16)
