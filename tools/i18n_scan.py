# 다국어 사전 검사 도구 — 화면·설치·말에 나오는 한국어 글을 소스에서 뽑아 사전(app/i18n/<언어>.json)과 맞춰 본다.
#   사전 = {한국어 원문: 번역}. 숫자·이름이 끼는 글은 {0}·{n} 자리로 적는다(화면 번역기·tr() 가 그 틀로 대조).
#   python -B -X utf8 tools/i18n_scan.py scan [--out 목록.json]        뽑은 원문(파일:줄)
#   python -B -X utf8 tools/i18n_scan.py check [--lang en,ja,zh]       빠진 것·자리 안 맞음·번역에 한글 남음 → 하나라도 있으면 종료 코드 1
#   python -B -X utf8 tools/i18n_scan.py missing <언어> --out 빠진것.json [--context]   번역할 것만
#   python -B -X utf8 tools/i18n_scan.py merge <언어> <번역.json>      번역을 사전에 넣음(원문 순서로 정렬, 이미 있는 것은 덮음)
#   python -B -X utf8 tools/i18n_scan.py unused <언어>                  소스에 없는 사전 줄(지워도 되는 것)
#   표준 라이브러리만.
import argparse
import io
import json
import os
import re
import sys
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I18N_DIR = os.path.join(ROOT, "app", "i18n")
LANGS = ("en", "ja", "zh")
HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")
PH = re.compile(r"\{[^{}\s]{1,40}\}")

# 화면에 보이는 글이 나오는 소스(전부 훑음)
UI_FILES = ["app/ui/*.js", "app/ui/index.html", "pet/renderer/*.js", "pet/renderer/*.html", "pet/renderer/real/*.js",
            "pet/main.js", "pet/speech.js", "pet/packs.js", "pet/server.js"]
# 화면·말로 나가는 글이 있는 파이썬(로그·키·비교·정규식은 빼고 훑음)
PY_FILES = ["app/main.py", "app/launcher.py", "app/shell.py", "app/winbox.py",
            "app/core/settings_api.py", "app/core/sysinfo.py", "app/core/update.py", "app/core/phone.py",
            "app/core/voiceprint.py", "app/core/interp.py", "app/core/cli_detect.py", "app/core/cli_brain.py",
            "app/core/brain.py", "app/core/session.py", "app/core/stt.py", "app/core/tts.py", "app/core/memory.py",
            "app/core/voice_choice.py", "app/core/fx.py", "app/core/guard.py", "app/core/keystore.py",
            "app/tools/registry.py", "app/tools/basic/*.py", "app/tools/phone/*.py", "app/pet_link/face.py",
            "installer/setup_core.py", "installer/updater.py", "installer/plan.py", "installer/get_models.py",
            "voice/tts_server.py", "voice/ear_server.py", "voice/interp_langs.py"]
# tr("…") 로 부른 글은 어느 파이썬 파일이든 모음
TR_FILES = ["app/**/*.py", "voice/*.py", "installer/*.py"]
PS_FILES = ["installer/install.ps1", "installer/worker.ps1", "installer/uninstall.ps1"]
JSON_FILES = {"app/config/choices.json": "values", "app/tools/basic/tools.json": "tooldesc", "app/tools/phone/tools.json": "tooldesc"}

# 잡음 많은 파일은 tr()/T() 로 부른 글만 모은다(사전 열쇠·정규식·로그가 섞이는 곳)
TR_ONLY_PY = {"app/tools/basic/web.py", "app/tools/basic/pc_action.py", "app/core/memory.py", "voice/interp_langs.py"}
TR_ONLY_JS = {"pet/renderer/real/motion_names.js", "pet/main.js"}
LOG_CALLS = {"log", "warn", "print", "info", "debug", "warning", "error", "exception", "critical", "_log", "logw", "say_log",
             "compile", "sub", "search", "match", "fullmatch", "findall", "finditer", "split", "join", "escape", "event",
             "startswith", "endswith", "replace", "get", "pop", "setdefault", "strip", "rstrip", "lstrip", "count", "index",
             "find", "rfind", "_read", "open", "makedirs", "join_path", "getenv"}
KEYLIKE = re.compile(r"^[\w가-힣]+(\.[\w가-힣]+)+$|^[\w가-힣]*_[\w가-힣_]*$")


def _glob(pats):
    import glob
    out = []
    for p in pats:
        for f in sorted(glob.glob(os.path.join(ROOT, p), recursive=True)):
            if os.path.isfile(f) and "__pycache__" not in f and f not in out:
                out.append(f)
    return out


def rel(f):
    return os.path.relpath(f, ROOT).replace("\\", "/")


# ---------------------------------------------------------------- 조각 나누기(화면 글자 노드 단위)
_TAG = re.compile(r"<[^<>]*>")
_ATTR = re.compile(r"""\b(?:title|placeholder|aria-label|alt|value)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def segments(s):
    """한 문자열 → 화면 글자 노드가 될 조각들(태그로 나눔, 태그 속 title 등 속성 글도)."""
    out = []
    if "<" in s and _TAG.search(s):
        for m in _TAG.finditer(s):
            for a in _ATTR.finditer(m.group(0)):
                out.append(a.group(1) if a.group(1) is not None else a.group(2))
        parts = _TAG.split(s)
    else:
        parts = [s]
    for p in parts:
        for line in p.split("\n"):
            out.append(line)
    res = []
    for x in out:
        x = x.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        x = re.sub(r"[ \t\r]+", " ", x).strip()
        if x and HANGUL.search(x):
            res.append(x)
    return res


# ---------------------------------------------------------------- JS
def _js_caller(src, i):
    """문자열 바로 앞이 '이름(' 꼴이면 그 이름(T·tr·log …), 아니면 ''."""
    j = i - 1
    while j >= 0 and src[j] in " \t\r\n":
        j -= 1
    if j < 0 or src[j] != "(":
        return ""
    j -= 1
    while j >= 0 and src[j] in " \t\r\n":
        j -= 1
    k = j
    while k >= 0 and (src[k].isalnum() or src[k] in "_$"):
        k -= 1
    return src[k + 1:j + 1]


def _js_literals(src):
    """JS 소스 → [(줄, 문자열 내용, 부르는 함수 이름)] — 주석·정규식은 건너뜀. 템플릿의 ${…} 는 {0}{1}… 로."""
    out = []
    i, n, line = 0, len(src), 1
    prev = ""   # 마지막 의미 있는 글자(정규식 판정)
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += src.count("\n", i, j)
            i = j
            continue
        if c == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^"):
            j, cls = i + 1, False
            while j < n and src[j] != "\n":
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    cls = True
                elif ch == "]":
                    cls = False
                elif ch == "/" and not cls:
                    break
                j += 1
            i = j + 1
            while i < n and src[i].isalpha():
                i += 1
            prev = "x"
            continue
        if c in "'\"":
            j, buf = i + 1, []
            while j < n and src[j] != c and src[j] != "\n":
                if src[j] == "\\" and j + 1 < n:
                    e = src[j + 1]
                    buf.append({"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"'}.get(e, e))
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            out.append((line, "".join(buf), _js_caller(src, i)))
            i = j + 1
            prev = "x"
            continue
        if c == "`":
            j, buf, k, start_line = i + 1, [], 0, line
            while j < n and src[j] != "`":
                if src[j] == "\\" and j + 1 < n:
                    e = src[j + 1]
                    buf.append({"n": "\n", "t": "\t", "\\": "\\", "`": "`", "$": "$"}.get(e, e))
                    j += 2
                    continue
                if src.startswith("${", j):
                    depth, j = 1, j + 2
                    while j < n and depth:
                        if src[j] == "{":
                            depth += 1
                        elif src[j] == "}":
                            depth -= 1
                        elif src[j] in "'\"`":   # 안쪽 문자열은 따로 모으지 않고 건너뜀(짧은 것뿐)
                            q = src[j]
                            j += 1
                            while j < n and src[j] != q:
                                j += 2 if src[j] == "\\" else 1
                        j += 1
                    buf.append("{%d}" % k)
                    k += 1
                    continue
                if src[j] == "\n":
                    line += 1
                buf.append(src[j])
                j += 1
            out.append((start_line, "".join(buf), _js_caller(src, i)))
            i = j + 1
            prev = "x"
            continue
        prev = c
        i += 1
    return out


_JS_LOG_LINE = re.compile(r"\bconsole\s*\.|\blog\s*\(")
_TR_CALLS = {"T", "tr", "_t", "tr_lazy"}


def _js_line_ok(lines, line):
    """console./log( 줄은 기록·디버그 글 — 화면에 안 나오므로 뺀다."""
    return not (0 < line <= len(lines) and _JS_LOG_LINE.search(lines[line - 1]))


def scan_js(path, tr_only=False):
    src = open(path, encoding="utf-8").read()
    lines = src.split("\n")
    res = []
    for line, s, caller in _js_literals(src):
        if not HANGUL.search(s):
            continue
        if tr_only and caller not in _TR_CALLS:   # T("…")·tr("…") 로 부른 글만(동작 별명 같은 사전 열쇠는 뺌)
            continue
        if not _js_line_ok(lines, line):
            continue
        if KEYLIKE.match(s.strip()):
            continue
        for seg in segments(s):
            res.append((seg, line))
    return res


def scan_html(path):
    src = open(path, encoding="utf-8").read()
    res = []
    body = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S | re.I)
    lines = src.split("\n")
    for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", src, flags=re.S | re.I):
        base = src.count("\n", 0, m.start(1))
        for line, s, _caller in _js_literals(m.group(1)):
            if HANGUL.search(s) and not KEYLIKE.match(s.strip()) and _js_line_ok(lines, base + line):
                for seg in segments(s):
                    res.append((seg, base + line))
    pos = 0
    for ln, text in enumerate(body.split("\n"), 1):
        pass
    for seg_src, line in _html_chunks(body):
        for seg in segments(seg_src):
            res.append((seg, line))
    return res


def _html_chunks(body):
    """HTML 본문을 태그 사이 글과 태그(속성용) 조각으로, 줄 번호와 함께."""
    out = []
    for m in re.finditer(r"<[^<>]*>|[^<]+", body):
        line = body.count("\n", 0, m.start()) + 1
        out.append((m.group(0), line))
    return out


# ---------------------------------------------------------------- 파이썬
def _fstring_body(tok):
    m = re.match(r"(?i)^([rbuf]*)('''|\"\"\"|'|\")", tok)
    pre, q = m.group(1).lower(), m.group(2)
    body = tok[len(m.group(0)):-len(q)]
    return pre, body


def _py_value(tok, k0=0):
    """STRING 토큰 → (글, 다음 자리 번호). f-문자열의 {…} 는 {k} 로. 못 읽으면 None."""
    import ast
    pre, body = _fstring_body(tok)
    if "b" in pre:
        return None, k0
    if "f" not in pre:
        try:
            return ast.literal_eval(tok), k0
        except Exception:  # noqa: BLE001
            return None, k0
    raw = body.replace("{{", "\x00").replace("}}", "\x01")
    out, i, k = [], 0, k0
    while i < len(raw):
        if raw[i] == "{":
            depth, j = 1, i + 1
            while j < len(raw) and depth:
                depth += {"{": 1, "}": -1}.get(raw[j], 0)
                j += 1
            out.append("{%d}" % k)
            k += 1
            i = j
            continue
        out.append(raw[i])
        i += 1
    s = "".join(out)
    if "r" not in pre:
        try:
            s = s.encode("latin-1", "backslashreplace").decode("unicode_escape").encode("latin-1").decode("utf-8")
        except Exception:  # noqa: BLE001
            s = s.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
    return s.replace("\x00", "{").replace("\x01", "}"), k


def _py_tokens(path):
    src = open(path, encoding="utf-8").read()
    try:
        return list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []


_SKIP_T = {tokenize.NL, tokenize.COMMENT}


def py_string_groups(path):
    """[(줄, 글, 앞 토큰, 뒤 토큰, 부르는 함수 이름들)] — 이어 붙은 문자열은 하나로."""
    toks = _py_tokens(path)
    out = []
    calls = []   # (괄호 종류, 함수 이름)
    i = 0
    sig = [t for t in toks if t.type not in _SKIP_T]
    idx = 0
    while idx < len(sig):
        t = sig[idx]
        if t.type == tokenize.OP and t.string in "([{":
            name = sig[idx - 1].string if idx and sig[idx - 1].type == tokenize.NAME and t.string == "(" else ""
            calls.append((t.string, name))
        elif t.type == tokenize.OP and t.string in ")]}":
            if calls:
                calls.pop()
        if t.type == tokenize.STRING:
            j, parts, k = idx, [], 0
            ok = True
            while j < len(sig) and sig[j].type == tokenize.STRING:
                v, k = _py_value(sig[j].string, k)
                if v is None:
                    ok = False
                parts.append(v or "")
                j += 1
            prev_t = sig[idx - 1] if idx else None
            next_t = sig[j] if j < len(sig) else None
            if ok:
                out.append((t.start[0], "".join(parts), prev_t, next_t, [c[1] for c in calls], calls[-1][0] if calls else ""))
            idx = j
            continue
        idx += 1
    return out


def scan_py(path, tr_only=False):
    res = []
    for line, s, prev_t, next_t, names, bracket in py_string_groups(path):
        if not HANGUL.search(s):
            continue
        is_tr = bool(names) and names[-1] in ("tr", "_t", "T", "tr_lazy")
        if tr_only and not is_tr:
            continue
        if not is_tr:
            if prev_t is None or (prev_t.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)
                                  and next_t is not None and next_t.type in (tokenize.NEWLINE, tokenize.ENDMARKER)):
                continue   # 독스트링·떠 있는 글
            if next_t is not None and next_t.string == ":" and bracket == "{":
                continue   # 사전 열쇠
            if prev_t is not None and prev_t.string == "[" and next_t is not None and next_t.string == "]":
                continue   # 첨자
            if prev_t is not None and prev_t.string in ("==", "!=", "in", "not", "is"):
                continue
            if next_t is not None and next_t.string in ("==", "!=", "in"):
                continue
            if any(nm in LOG_CALLS for nm in names):
                continue
            if KEYLIKE.match(s.strip()):
                continue
            if re.search(r"[\\^$*+?\[\]|()]{3,}|\(\?[:=!<]", s):
                continue   # 정규식 모양
        for seg in (segments(s) if "<" in s else [x.strip() for x in s.split("\n")]):
            seg = re.sub(r"[ \t]+", " ", seg).strip()
            if seg and HANGUL.search(seg):
                res.append((seg, line))
    return res


# ---------------------------------------------------------------- PowerShell(T "…" 로 부른 글만) · JSON
def scan_ps(path):
    src = open(path, encoding="utf-8-sig").read()
    res = []
    pats = (r"""\bT\s+(?:'((?:[^']|'')*)'|"((?:[^"`]|`.)*)")""",                 # T "…"
            r"""\bSet-K\s+\S+\s+(?:'((?:[^']|'')*)'|"((?:[^"`]|`.)*)")""")         # Set-K $ctl "…"(화면 글 등록)
    for rx in pats:
        for m in re.finditer(rx, src):
            s = m.group(1).replace("''", "'") if m.group(1) is not None else m.group(2)
            if HANGUL.search(s):
                res.append((s.strip(), src.count("\n", 0, m.start()) + 1))
    return res


def scan_json(path, mode):
    data = json.load(open(path, encoding="utf-8"))
    res = []

    def walk(x, key=""):
        if isinstance(x, dict):
            for k, v in x.items():
                if mode == "tooldesc" and k not in ("description", "확인", "안내", "먼저할말", "properties", "parameters", "items", "function") and not isinstance(v, (dict, list)):
                    continue
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, str) and HANGUL.search(x) and not str(key).startswith("_"):
            if mode == "values" and KEYLIKE.match(x):
                return
            for seg in segments(x):
                res.append((seg, 0))
    walk(data)
    return res


# ---------------------------------------------------------------- 모으기
def collect():
    found = {}

    def add(items, f):
        for s, line in items:
            found.setdefault(s, []).append(f"{rel(f)}:{line}")
    for f in _glob(UI_FILES):
        if f.endswith(".html"):
            add(scan_html(f), f)
        else:
            add(scan_js(f, tr_only=rel(f) in TR_ONLY_JS), f)
    pyset = set(_glob(PY_FILES))
    for f in pyset:
        add(scan_py(f, tr_only=rel(f) in TR_ONLY_PY), f)
    for f in _glob(TR_FILES):
        if f not in pyset:
            add(scan_py(f, tr_only=True), f)
    for f in _glob(PS_FILES):
        add(scan_ps(f), f)
    for p, mode in JSON_FILES.items():
        f = os.path.join(ROOT, p)
        if os.path.isfile(f):
            add(scan_json(f, mode), f)
    for s in list(found):
        if s in IGNORE:
            del found[s]
    return found


IGNORE_FILE = os.path.join(I18N_DIR, "_ignore.json")
try:
    IGNORE = set(json.load(open(IGNORE_FILE, encoding="utf-8")).get("ignore") or [])
except (OSError, ValueError):
    IGNORE = set()


def load_dict(lang):
    p = os.path.join(I18N_DIR, f"{lang}.json")
    if not os.path.isfile(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))
    return {k: v for k, v in d.items() if not k.startswith("_")}


def save_dict(lang, d, keep_meta=True):
    p = os.path.join(I18N_DIR, f"{lang}.json")
    meta = {}
    if keep_meta and os.path.isfile(p):
        meta = {k: v for k, v in json.load(open(p, encoding="utf-8")).items() if k.startswith("_")}
    out = dict(meta)
    for k in sorted(d):
        out[k] = d[k]
    os.makedirs(I18N_DIR, exist_ok=True)
    data = json.dumps(out, ensure_ascii=False, indent=0).replace('\n"', '\n "')
    with open(p, "wb") as f:
        f.write((data + "\n").encode("utf-8"))


def placeholders(s):
    return sorted(PH.findall(s))


def cmd_check(langs):
    found = collect()
    bad = 0
    for lang in langs:
        d = load_dict(lang)
        miss = [k for k in found if k not in d]
        ph = [k for k, v in d.items() if placeholders(k) != placeholders(v)]
        left = [k for k, v in d.items() if HANGUL.search(PH.sub("", v)) and not re.search(r"한국어|한글", v)]   # {이름} 같은 자리 안의 한글은 뺌
        empty = [k for k, v in d.items() if not str(v).strip()]
        print(f"[{lang}] 원문 {len(found)} · 사전 {len(d)} · 빠짐 {len(miss)} · 자리 안 맞음 {len(ph)} · 번역에 한글 {len(left)} · 빈 번역 {len(empty)}")
        for k in miss[:15]:
            print("   빠짐:", k[:80], "←", found[k][0])
        for k in ph[:10]:
            print("   자리:", k[:60], "→", d[k][:60])
        for k in left[:10]:
            print("   한글:", k[:40], "→", d[k][:60])
        bad += len(miss) + len(ph) + len(left) + len(empty)
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--out")
    c = sub.add_parser("check")
    c.add_argument("--lang", default=",".join(LANGS))
    m = sub.add_parser("missing")
    m.add_argument("lang")
    m.add_argument("--out", required=True)
    m.add_argument("--context", action="store_true")
    g = sub.add_parser("merge")
    g.add_argument("lang")
    g.add_argument("file")
    u = sub.add_parser("unused")
    u.add_argument("lang")
    u.add_argument("--drop", action="store_true")
    a = ap.parse_args()
    if a.cmd == "scan":
        found = collect()
        if a.out:
            json.dump(found, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        by = {}
        for k, where in found.items():
            by.setdefault(where[0].split(":")[0], 0)
            by[where[0].split(":")[0]] += 1
        for f, n in sorted(by.items(), key=lambda x: -x[1]):
            print(f"{n:5d} {f}")
        print("합계", len(found), "· 글자", sum(len(k) for k in found))
        return 0
    if a.cmd == "check":
        return cmd_check([x for x in a.lang.split(",") if x])
    if a.cmd == "missing":
        found = collect()
        d = load_dict(a.lang)
        miss = {k: (found[k][:3] if a.context else "") for k in found if k not in d}
        json.dump(miss, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"[{a.lang}] 빠짐 {len(miss)} → {a.out}")
        return 0
    if a.cmd == "merge":
        d = load_dict(a.lang)
        new = json.load(open(a.file, encoding="utf-8"))
        new = {k: v for k, v in new.items() if not k.startswith("_")}
        bad = [k for k, v in new.items() if not isinstance(v, str) or placeholders(k) != placeholders(v)]
        for k in bad:
            print("   자리 안 맞아 건너뜀:", k[:60], "→", str(new[k])[:60])
        d.update({k: v for k, v in new.items() if k not in bad and isinstance(v, str) and v.strip()})
        save_dict(a.lang, d)
        print(f"[{a.lang}] 넣음 {len(new) - len(bad)} · 사전 {len(d)}")
        return 0
    if a.cmd == "unused":
        found = collect()
        d = load_dict(a.lang)
        extra = sorted(k for k in d if k not in found and not k.startswith("@"))
        for k in extra:
            print("  ", k[:90])
        print(f"[{a.lang}] 소스에 없는 줄 {len(extra)}")
        if a.drop:
            save_dict(a.lang, {k: v for k, v in d.items() if k not in extra})
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
