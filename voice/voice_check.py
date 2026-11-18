# 목소리 흔들림 막기(선택 기능, 기본 꺼짐) — 만든 문장이 참고음성 목소리와 덜 닮으면 다른 시드로 다시 만들어 가장 닮은 것을 쓴다.
# 왜: 같은 참고음성이라도 시드에 따라 10번에 1번꼴로 음높이가 확 올라가거나 다른 사람처럼 들리는 문장이 나옴.
# 닮음 = 화자 임베딩 모델 TitaNet-small(sherpa-onnx)의 코사인 유사도. 사람 목소리 등록·확인과는 관계없고,
#        '김비서 참고음성 ↔ 방금 만든 소리' 만 비교한다.
# 도는 방식(설정 '목소리.닮음검사')
#   - 이 환경에 sherpa_onnx 가 있으면 프로세스 안에서 바로
#   - 없고 '도우미_파이썬' 이 있으면 그 파이썬으로 이 파일을 --serve 로 띄워 표준입출력으로 주고받음
#   - 둘 다 아니거나 모델 파일이 없으면 검사 없이 첫 결과를 씀(서버는 계속 동작)
# 도우미 실행: <파이썬> voice_check.py --serve <기준.wav> --model <titanet.onnx>
import base64
import json
import os
import subprocess
import sys
import threading

import numpy as np

THRESHOLD = 0.75      # 이보다 낮으면 다시 만듦(같은 참고음성의 정상 문장 0.80~0.91, 다른 목소리 0.49~0.73 에서 정함)
TRIES = 3             # 처음 포함 최대 3번
SEED_STEP = 7919      # 다시 만들 때 시드 간격(정해진 값 → 같은 글이면 늘 같은 결과)
MIN_SEC = 2.0         # 이보다 짧은 소리는 검사 안 함(1초 안팎 말은 점수가 들쭉날쭉해 헛되이 다시 만듦)


def ascii_path(p):
    """onnx 같은 C++ 라이브러리가 한글 경로를 못 여는 경우 대비: 윈도우 8.3 짧은 경로(있으면)로."""
    try:
        p.encode("ascii")
        return p
    except UnicodeEncodeError:
        pass
    if os.name == "nt":
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024)
        if 0 < n < 1024:
            try:
                buf.value.encode("ascii")
                return buf.value
            except UnicodeEncodeError:
                pass
    return p


def load16(path_or_array, sr=None):
    if isinstance(path_or_array, str):
        import soundfile as sf
        w, sr = sf.read(path_or_array, dtype="float32")
    else:
        w = np.asarray(path_or_array, np.float32)
    if w.ndim > 1:
        w = w.mean(1)
    if sr and sr != 16000:
        n = int(len(w) * 16000 / sr)
        w = np.interp(np.linspace(0, len(w) - 1, n), np.arange(len(w)), w).astype(np.float32)
    return w


class Embedder:
    def __init__(self, model):
        import sherpa_onnx
        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=ascii_path(model), num_threads=2)
        self.ex = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)

    def embed(self, w, seg=6.0):
        """16kHz float → 정규화된 임베딩. 긴 소리는 6초 조각 평균."""
        n = int(seg * 16000)
        pieces = [w[i:i + n] for i in range(0, len(w), n)]
        pieces = [p for p in pieces if len(p) >= 16000 * 1.5] or [w]
        es = []
        for p in pieces:
            s = self.ex.create_stream()
            s.accept_waveform(16000, p)
            s.input_finished()
            e = np.asarray(self.ex.compute(s), dtype=np.float32)
            es.append(e / (np.linalg.norm(e) + 1e-9))
        e = np.mean(es, 0)
        return e / (np.linalg.norm(e) + 1e-9)


class VoiceCheck:
    def __init__(self, ref_wav, model, helper_python="", log=print):
        self.ref, self.model, self.helper, self.log = ref_wav, model, helper_python, log
        self.lock, self.p, self.emb, self.ref_e, self.mode = threading.Lock(), None, None, None, "off"
        if not (model and os.path.isfile(model) and os.path.isfile(ref_wav)):
            log("[닮음검사] 꺼짐(모델 파일 또는 기준 음성 없음)")
        else:
            try:
                import sherpa_onnx  # noqa: F401
                self.emb = Embedder(model)
                self.ref_e = self.emb.embed(load16(ref_wav))
                self.mode = "inproc"
            except ImportError:
                if helper_python and os.path.isfile(helper_python):
                    self.mode = "helper"
                else:
                    log("[닮음검사] 꺼짐(sherpa_onnx 없음, 도우미 파이썬도 없음)")
            except Exception as ex:  # noqa: BLE001
                log(f"[닮음검사] 꺼짐(모델을 못 엶: {ex})")
        self.ok = self.mode != "off"

    def _start(self):
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.p = subprocess.Popen([self.helper, os.path.abspath(__file__), "--serve", self.ref, "--model", self.model],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, encoding="utf-8", env=env, creationflags=flags)
        first = json.loads(self.p.stdout.readline())
        if not first.get("ready"):
            raise RuntimeError("도우미 준비 실패: " + str(first.get("error", ""))[:200])
        self.log(f"[닮음검사] 도우미 준비(PID {self.p.pid}), 기준값 {THRESHOLD}")

    def sim(self, pcm16, sr=24000):
        """PCM16(np.int16) → 닮음(0~1) 또는 None(검사 불가)."""
        if not self.ok:
            return None
        with self.lock:
            if self.mode == "inproc":
                try:
                    w = load16(np.asarray(pcm16, np.int16).astype(np.float32) / 32768.0, sr)
                    return round(float(self.ref_e @ self.emb.embed(w)), 4)
                except Exception as ex:  # noqa: BLE001
                    self.log(f"[닮음검사] 오류 → 검사 끔: {ex}")
                    self.ok = False
                    return None
            for attempt in range(2):
                try:
                    if self.p is None or self.p.poll() is not None:
                        self._start()
                    msg = json.dumps({"pcm16": base64.b64encode(np.asarray(pcm16, np.int16).tobytes()).decode("ascii"), "sr": sr})
                    self.p.stdin.write(msg + "\n")
                    self.p.stdin.flush()
                    return json.loads(self.p.stdout.readline()).get("sim")
                except Exception as ex:  # noqa: BLE001
                    self.log(f"[닮음검사] 오류({attempt + 1}번째): {ex}")
                    self.close()
            self.ok = False
            self.log("[닮음검사] 두 번 실패 → 검사 끔")
            return None

    def close(self):
        if self.p is not None:
            try:
                self.p.stdin.close()
                self.p.wait(5)
            except Exception:  # noqa: BLE001
                try:
                    self.p.kill()     # 자기가 띄운 도우미만
                except Exception:  # noqa: BLE001
                    pass
            self.p = None


def pick_best(eng, judge, text, emotion, seed, tries=TRIES, threshold=THRESHOLD, voice=None, **kw):
    """한 문장을 만들고, 닮음이 기준값보다 낮으면 시드를 바꿔 다시. → (PCM16, 정보)"""
    best, info = None, dict(tries=[], seed=seed)
    for k in range(tries if judge is not None else 1):
        sd = seed + k * SEED_STEP
        pcm = eng.to_int16(eng.speak(text, emotion, seed=sd, voice=voice, **kw))
        s = judge.sim(pcm) if (judge is not None and len(pcm) >= MIN_SEC * 24000) else None
        info["tries"].append(dict(seed=sd, sim=s))
        if best is None or (s is not None and s > best[1]):
            best = (pcm, s if s is not None else -1.0, sd)
        if s is None or s >= threshold:
            break
    info.update(seed=best[2], sim=best[1] if best[1] >= 0 else None)
    return best[0], info


def serve(ref_path, model):
    """도우미: 한 줄 JSON {"pcm16": base64, "sr": 24000} → 한 줄 JSON {"sim": 값}."""
    try:
        emb = Embedder(model)
        ref = emb.embed(load16(ref_path))
    except Exception as ex:  # noqa: BLE001
        print(json.dumps({"ready": False, "error": str(ex)[:200]}), flush=True)
        return
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            j = json.loads(line)
            w = np.frombuffer(base64.b64decode(j["pcm16"]), np.int16).astype(np.float32) / 32768.0
            print(json.dumps({"sim": round(float(ref @ emb.embed(load16(w, int(j.get("sr", 24000))))), 4)}), flush=True)
        except Exception as ex:  # noqa: BLE001  (한 건 실패해도 도우미는 계속)
            print(json.dumps({"error": str(ex)[:200]}), flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", required=True, help="기준 wav")
    ap.add_argument("--model", required=True, help="TitaNet-small onnx")
    a = ap.parse_args()
    serve(a.serve, a.model)
