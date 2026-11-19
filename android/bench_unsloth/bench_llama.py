# Unsloth 모바일 GGUF(llama.cpp, 안드로이드 x86_64) 시험 — 앱과 같은 지시문·질문으로.
#   python bench_llama.py <serial> <lang> <질문파일>
import json, os, re, subprocess, sys, time

ADB = r"C:\android-sdk\platform-tools\adb.exe"
BENCH = "/data/local/tmp/bench"
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app", "src", "main", "java", "kr", "kimbiseo", "phone", "SoloBrain.kt")


def adb(serial, *args, timeout=300):
    return subprocess.run([ADB, "-s", serial, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout).stdout


def prompts():
    s = open(SRC, encoding="utf-8").read()
    body = s[s.index("object SoloPrompt"):]
    out = {}
    for key in ["ko", "ja", "zh", "en"]:
        pat = '"ko" ->' if key == "ko" else ('"ja" ->' if key == "ja" else ('"zh" ->' if key == "zh" else "else ->"))
        i = body.index(pat)
        a = body.index('"""', i) + 3
        b = body.index('"""', a)
        lines = body[a:b].splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        ind = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
        out[key] = "\n".join(l[ind:] for l in lines)
    return out


DIRECTIVE = {
    "ko": "다음 답변은 한국어로만 하세요. 다른 언어를 섞지 마세요.",
    "ja": "次の返事は日本語だけでしてください。中国語や英語を混ぜないでください。",
    "zh": "请只用简体中文回答，不要夹杂日语或英语。",
    "en": "Answer only in English. Do not mix other languages.",
}


def shq(t):
    return "'" + t.replace("'", "'\\''") + "'"


def pss(serial, pid):
    out = adb(serial, "shell", "dumpsys meminfo " + pid)
    m = re.search(r"TOTAL PSS:\s+(\d+)", out)
    return int(m.group(1)) if m else 0


def main():
    serial, lang, qfile = sys.argv[1], sys.argv[2], sys.argv[3]
    qs = [q.strip() for q in open(qfile, encoding="utf-8") if q.strip()]
    sysmsg = prompts()[lang]
    rec = {"engine": "gguf-q2", "lang": lang, "qa": []}
    for n, q in enumerate(qs):
        prompt = q + "\n\n" + DIRECTIVE[lang]
        tag = "q%d" % n
        cmd = ("cd %s; rm -f %s/%s.mem %s/%s.done; "
               "( while [ ! -f %s/%s.done ]; do p=$(pidof llama-completion); "
               "if [ -n \"$p\" ]; then dumpsys meminfo $p 2>/dev/null | grep 'TOTAL PSS' >> %s/%s.mem; fi; "
               "sleep 0.5; done ) & S=$!; "
               "LD_LIBRARY_PATH=. ./llama-completion -m model-q2.gguf -c 4096 -n 640 -t 4 "
               "-st --no-warmup --jinja --reasoning-budget 0 --no-display-prompt -p %s -sys %s "
               "--temp 1.0 --top-p 0.95 --top-k 64 > %s/%s.txt 2> %s/%s.log; "
               "touch %s/%s.done; wait $S") % (
            BENCH, BENCH, tag, BENCH, tag, BENCH, tag, BENCH, tag,
            shq(prompt), shq(sysmsg), BENCH, tag, BENCH, tag, BENCH, tag)
        adb(serial, "shell", "rm -f %s/%s.txt %s/%s.log %s/%s.mem %s/%s.done" % (BENCH, tag, BENCH, tag, BENCH, tag, BENCH, tag))
        adb(serial, "shell", cmd, timeout=400)
        mem = adb(serial, "shell", "cat %s/%s.mem 2>/dev/null" % (BENCH, tag))
        vals = [int(x) for x in re.findall(r"TOTAL PSS:\s+(\d+)", mem)]
        mx = max(vals) if vals else 0
        log = adb(serial, "shell", "cat %s/%s.log" % (BENCH, tag))
        raw = adb(serial, "shell", "cat %s/%s.txt" % (BENCH, tag)).strip()
        ans = raw.split("<channel|>")[-1].strip() if "<channel|>" in raw else raw
        ans = ans.replace("[end of text]", "").strip()
        def num(pat):
            m = re.search(pat, log)
            return float(m.group(1)) if m else None
        rec["qa"].append({
            "q": q, "first_ms": None,
            "load_ms": num(r"load time =\s+([\d.]+) ms"),
            "prompt_ms": num(r"prompt eval time =\s+([\d.]+) ms"),
            "prompt_tokens": num(r"prompt eval time =\s+[\d.]+ ms /\s+(\d+) tokens"),
            "eval_ms": num(r"(?<!prompt )eval time =\s+([\d.]+) ms"),
            "eval_tokens": num(r"(?<!prompt )eval time =\s+[\d.]+ ms /\s+(\d+) runs"),
            "tps": num(r"(?<!prompt )eval time =.*?([\d.]+) tokens per second"),
            "pss_max_kb": mx,
            "reply": ans, "raw": raw,
            "log_tail": log[-600:] if not ans else "",
        })
        time.sleep(0.3)
    print(json.dumps(rec, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()