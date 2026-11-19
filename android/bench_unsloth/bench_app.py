# 김비서 폰 앱(LiteRT-LM) 시험 — adb 로 대화를 보내고 BENCH 로그·PSS 를 모은다.
#   python bench_app.py <serial> <lang> <질문파일>
#   질문파일: 한 줄에 질문 하나. 각 질문 앞에 새 대화(test_solo_new).
import json, re, subprocess, sys, threading, time

ADB = r"C:\android-sdk\platform-tools\adb.exe"
PKG = "kr.kimbiseo.phone"


def adb(serial, *args, timeout=60):
    return subprocess.run([ADB, "-s", serial, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout).stdout


def logcat(serial):
    return adb(serial, "logcat", "-d", "-s", "KimbiseoSoloBrain", "KimbiseoSolo")


def shq(t):
    return "'" + t.replace("'", "'\\''") + "'"


class Sampler(threading.Thread):
    def __init__(self, serial):
        super().__init__(daemon=True)
        self.serial = serial
        self.stop = False
        self.max_pss = 0
        self.samples = []

    def run(self):
        while not self.stop:
            out = adb(self.serial, "shell", "dumpsys meminfo " + PKG)
            m = re.search(r"TOTAL PSS:\s+(\d+)", out)
            if m:
                v = int(m.group(1)); self.samples.append(v); self.max_pss = max(self.max_pss, v)
            time.sleep(0.7)


def main():
    serial, lang, qfile = sys.argv[1], sys.argv[2], sys.argv[3]
    qs = [q.strip() for q in open(qfile, encoding="utf-8") if q.strip()]
    adb(serial, "shell", "am", "force-stop", PKG)
    adb(serial, "logcat", "-c")
    adb(serial, "shell", "am", "start", "-n", PKG + "/.SoloActivity", "--es", "test_solo_lang", lang)
    t0 = time.time()
    while time.time() - t0 < 120:
        if "BENCH load done" in logcat(serial):
            break
        time.sleep(1)
    load = re.findall(r"BENCH load done ms=(\d+)", logcat(serial))
    rec = {"engine": "litertlm", "lang": lang, "load_ms": int(load[-1]) if load else None, "qa": []}
    for q in qs:
        adb(serial, "shell", "am", "start", "-n", PKG + "/.SoloActivity", "--es", "test_solo_new", "true")
        time.sleep(0.8)
        adb(serial, "logcat", "-c"); time.sleep(0.6)
        base = logcat(serial)
        gens = [int(x) for x in re.findall(r"send\(\) called busy=\S+ gen=(\d+)", base)]
        base_gen = max(gens) if gens else 0
        s = Sampler(serial); s.start()
        adb(serial, "shell", "am start -n %s/.SoloActivity --es test_solo_text %s" % (PKG, shq(q)))
        t1 = time.time()
        while time.time() - t1 < 180:
            L = logcat(serial)
            dones = [int(m) for m in re.findall(r"BENCH done .*gen=(\d+)", L)]
            if any(d > base_gen for d in dones):
                break
            time.sleep(1)
        s.stop = True; s.join()
        t2 = time.time()
        reply = ""
        while time.time() - t2 < 15:
            L = logcat(serial)
            lines = L.splitlines()
            didx = None
            gen = None
            for i, ln in enumerate(lines):
                m = re.search(r"BENCH done .*chars=(\d+) chunks=(\d+) gen=(\d+)", ln)
                if m and int(m.group(3)) > base_gen:
                    didx = i; gen = int(m.group(3))
            if didx is not None:
                after = [ln for ln in lines[didx + 1:] if "reply lang=" in ln]
                if after:
                    reply = after[-1].split("text=", 1)[1]
                    break
            time.sleep(0.5)
        L = logcat(serial)
        lines = L.splitlines()
        first = None; done = None
        for i, ln in enumerate(lines):
            m = re.search(r"BENCH first token ms=(\d+) gen=(\d+)", ln)
            if m and int(m.group(2)) > base_gen:
                first = int(m.group(1))
            m = re.search(r"BENCH done ms=(\d+) first=(\d+) chars=(\d+) chunks=(\d+) gen=(\d+)", ln)
            if m and int(m.group(5)) > base_gen:
                done = (int(m.group(1)), int(m.group(3)), int(m.group(4)))
        rec["qa"].append({
            "q": q,
            "first_ms": first,
            "done_ms": done[0] if done else None,
            "chars": done[1] if done else None,
            "chunks": done[2] if done else None,
            "pss_max_kb": s.max_pss,
            "reply": reply,
        })
        time.sleep(0.5)
    print(json.dumps(rec, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()