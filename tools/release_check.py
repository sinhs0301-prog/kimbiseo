#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""공개 전 검사 도구 (release_check) — 김비서 공개 배포판

저장소를 공개하기 전에, 실수로 들어간 비밀·내부 주소·개인정보·허용 목록 밖 파일을 찾습니다.
표준 라이브러리만 씁니다(파이썬 3.11 이상). 다른 프로그램을 띄우지 않습니다.

사용법 (저장소 뿌리에서)
  python tools/release_check.py check
      저장소 전체 검사: 허용 목록 대조 + 낱말·꼴 검색 + 파일 종류 + 이진 파일 속 글자 + 압축 파일 속
  python tools/release_check.py scan <경로>...
      허용 목록 없이 낱말·꼴·파일 종류만 검사(저장소 밖 폴더·시험용)
  python tools/release_check.py artifact <압축파일>... [--manifest 목록.json] [--forbid-ext mp3,m4a]
      나눠 줄 산출물(zip 꼴: zip·꾸러미·apk 등)을 풀어서 같은 검사
  python tools/release_check.py allowlist-verify
      허용 목록 대조만
  python tools/release_check.py allowlist-rehash (--all | <경로>...)
      이미 목록에 있는 줄의 sha256 을 다시 계산해 씀(새 줄은 더하지 않음)
  python tools/release_check.py allowlist-add <경로> --origin new --treatment new [--note 설명]
      목록에 한 줄 더하기(사람이 직접 고른 파일 하나씩)
  python tools/release_check.py privatelist-selftest
      비공개 금지 낱말 목록이 제대로 읽히는지 확인(낱말 자체는 화면에 내지 않음)

공통 선택
  --root <폴더>          저장소 뿌리(기본: 이 파일의 한 단계 위)
  --private-list <파일>  비공개 금지 낱말 목록(저장소 밖에 둠). 안 주면 환경변수 KIMBISEO_PRIVATE_WORDS,
                         그다음 <저장소>/../자료/금지낱말_비공개.json 을 찾습니다. 없으면 일반 꼴만 검사하고 경고.
  --require-private      비공개 목록이 없으면 실패로 봄(공개 직전 최종 검사용)
  --json-out <파일>      결과 JSON 저장
  --max-show <n>         화면에 보여 줄 찾은 것 수(기본 200)

종료 코드: 0 = 통과, 1 = 실패(오류 1건 이상 또는 검사 불가), 2 = 사용법 오류
찾은 글자는 화면·JSON 에 앞 몇 글자만 보이고 나머지는 가립니다.
"""
from __future__ import annotations

import argparse
import bisect
import codecs
import datetime as _dt
import hashlib
import io
import json
import math
import os
import re
import stat
import struct
import subprocess
import sys
import unicodedata
import zipfile
import zlib
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

TOOL_VERSION = "0.1.0"
ALLOWLIST_SCHEMA = "kimbiseo-allowlist/1"
PRIVATE_SCHEMA = "kimbiseo-private-words/1"
ALLOWLIST_REL = "tools/allowlist.json"
PRIVATE_ENV = "KIMBISEO_PRIVATE_WORDS"
DEFAULT_PRIVATE_PARTS = ("..", "자료", "금지낱말_비공개.json")

TREATMENTS = {
    "new": "새로 씀",
    "copy": "그대로 옮김(내용 같음)",
    "modified": "고쳐서 옮김",
    "standard": "표준 문서(예: 라이선스 전문)",
}

MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_TOTAL = 4 * 1024 * 1024 * 1024
MAX_ARCHIVE_DEPTH = 3
MAX_RATIO = 200
BIG_BOMB_BYTES = 64 * 1024 * 1024
BINARY_WINDOW = 16 * 1024 * 1024
BINARY_OVERLAP = 4096

# ── 파일 종류 규칙 ──────────────────────────────────────────────
FORBIDDEN_EXT = {
    ".pem", ".key", ".jks", ".keystore", ".p12", ".pfx", ".kdbx", ".ppk",
    ".apk", ".aab", ".npz", ".jsonl", ".log", ".db", ".sqlite", ".sqlite3",
}
FORBIDDEN_NAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".pypirc", ".git-credentials",
}
NEEDS_ALLOW_EXT = {
    ".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".wma",
    ".mp4", ".webm", ".mov", ".mkv", ".avi",
    ".onnx", ".bin", ".safetensors", ".gguf", ".pt", ".pth", ".ckpt", ".npy", ".pkl", ".tflite",
    ".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".xz", ".asar",
    ".exe", ".dll", ".msi", ".pyd", ".so", ".dylib", ".sys",
}
FORBIDDEN_DIRS = {
    ".venv", "node_modules", "__pycache__", "ebwebview", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".git",
}
FORBIDDEN_DIR_PREFIX = ("venv", ".playwright")
ARTIFACT_FORBIDDEN_DIRS = FORBIDDEN_DIRS - {"node_modules"}
SUSPICIOUS_NAME = re.compile(r"(?i)(secret|token|credential|passw|비밀|열쇠|암호)")

# ── 글자 꼴 규칙 ────────────────────────────────────────────────
NB = r"(?<![0-9A-Za-z_])"
NA = r"(?![0-9A-Za-z_])"
HANGUL_WORD = "0-9A-Za-z_가-힣ㄱ-ㆎ"


@dataclass
class Rule:
    rid: str
    category: str
    severity: str
    label: str
    regex: re.Pattern
    check: Callable[[re.Match, str], bool] | None = None
    hashlike: bool = False


def _octets(m: re.Match) -> list[int] | None:
    try:
        o = [int(m.group(i)) for i in range(1, 5)]
    except (TypeError, ValueError, IndexError):
        return None
    return o if all(0 <= x <= 255 for x in o) else None


def _net_notation(m: re.Match, t: str) -> bool:
    return t[m.end():m.end() + 1] == "/" and m.group(4) == "0"


def v_private_ip(m, t):
    o = _octets(m)
    if not o or _net_notation(m, t):
        return False
    a, b = o[0], o[1]
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)


def v_linklocal_ip(m, t):
    o = _octets(m)
    return bool(o) and not _net_notation(m, t) and o[0] == 169 and o[1] == 254


def v_cgnat_ip(m, t):
    o = _octets(m)
    return bool(o) and not _net_notation(m, t) and o[0] == 100 and 64 <= o[1] <= 127


def v_hostname(m, t):
    tail = m.group(0).split("-", 1)[1]
    return any(c.isdigit() for c in tail) and any(c.isalpha() for c in tail)


SKIP_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "localhost"}
SKIP_EMAIL_TLDS = {"example", "invalid", "test", "localhost", "png", "jpg", "jpeg", "gif", "svg",
                   "webp", "js", "css", "json", "py", "md", "txt", "ts"}


def v_email(m, t):
    s = m.group(0)
    local, _, dom = s.rpartition("@")
    dom = dom.lower()
    if local.lower() == "git":
        return False
    if dom in SKIP_EMAIL_DOMAINS or dom.rsplit(".", 1)[-1] in SKIP_EMAIL_TLDS:
        return False
    return True


def v_luhn(m, t):
    d = [int(c) for c in m.group(0) if c.isdigit()]
    if len(d) < 13 or len(set(d)) == 1:
        return False
    s = 0
    for i, x in enumerate(reversed(d)):
        if i % 2 == 1:
            x *= 2
            if x > 9:
                x -= 9
        s += x
    return s % 10 == 0


PLACEHOLDER_RX = re.compile(r"(?i)(<|>|\$\{|%[a-z_]+%|your|xxx|changeme|example|placeholder|redacted|\*\*\*)")


def v_assign(m, t):
    v = m.group(1)
    if PLACEHOLDER_RX.search(v):
        return False
    if re.fullmatch(r"[A-Z0-9_]+", v):
        return False
    return True


def v_hexmix(m, t):
    s = m.group(0)
    return any(c.isdigit() for c in s) and any(c.isalpha() for c in s)


def _entropy(s: str) -> float:
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def v_random(m, t):
    s = m.group(0)
    if re.fullmatch(r"[0-9a-fA-F]+", s):
        return False
    digits = sum(c.isdigit() for c in s)
    return (digits >= 4 and any(c.isupper() for c in s) and any(c.islower() for c in s)
            and _entropy(s) >= 4.2)


def R(p: str, flags: int = 0) -> re.Pattern:
    return re.compile(p, flags)


IPV4 = R(r"(?<![0-9A-Za-z_.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![0-9A-Za-z_]|\.\d)")

GENERIC_RULES: list[Rule] = [
    # 주소
    Rule("net.private_ipv4", "network", "error", "사설 IP 주소", IPV4, v_private_ip),
    Rule("net.linklocal_ipv4", "network", "error", "링크 로컬 IP 주소", IPV4, v_linklocal_ip),
    Rule("net.cgnat_ipv4", "network", "error", "테일스케일 대역(100.64.0.0/10) 주소", IPV4, v_cgnat_ip),
    Rule("net.tailscale_ipv6", "network", "error", "테일스케일 IPv6 주소",
         R(r"(?i)(?<![0-9a-f:])fd7a:115c:a1e[0]:[0-9a-f:]*")),
    Rule("net.ts_net", "network", "error", "테일스케일 기기 이름(.ts.net)",
         R(r"(?i)(?<![0-9a-z_-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.ts\.net(?![0-9a-z_-])")),
    Rule("net.win_hostname", "network", "error", "윈도우 기본 PC 이름 꼴",
         R(r"(?i)(?<![0-9a-z_-])(?:desktop|laptop)-[a-z0-9]{7,8}(?![0-9a-z_-])"), v_hostname),
    Rule("net.lan_url", "network", "warn", "집 안 이름 주소(.lan/.local 등)",
         R(r"(?i)://[a-z0-9.-]+\.(?:lan|local|internal|corp|home\.arpa)(?![0-9a-z.-])")),
    Rule("net.mac", "network", "warn", "MAC 주소 꼴",
         R(NB + r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}" + NA)),
    # 경로
    Rule("path.unc", "path", "error", "공유 폴더(UNC) 경로",
         R(r"(?<![\\])(?:\\\\){1,2}[A-Za-z0-9_.$-]{2,}\\+[^\\\s\"'<>|]{2,}")),
    Rule("path.win_user", "path", "error", "윈도우 사용자 폴더 경로",
         R(r"(?i)(?<![a-z])[a-z]:(?:\\|/)+users(?:\\|/)+(?!(?:public|default|all users)(?![a-z0-9_.-]))"
           r"[^\\/\s\"'<>|*?%{}$]+")),
    Rule("path.unix_home", "path", "warn", "리눅스·맥 사용자 폴더 경로",
         R(r"(?<![:A-Za-z0-9_/\\])/(?:home|Users)/(?!user/|shared/|Shared/)[A-Za-z_][A-Za-z0-9_.-]*/")),
    # 개인정보
    Rule("pii.email", "personal", "error", "이메일 주소",
         R(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![A-Za-z0-9-])"),
         v_email),
    Rule("pii.phone_mobile", "personal", "error", "휴대폰 번호",
         R(NB + r"01[016789][-. ]?\d{3,4}[-. ]?\d{4}" + NA)),
    Rule("pii.phone_landline", "personal", "error", "일반 전화번호",
         R(NB + r"0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70)[-. )]{1,2}\d{3,4}[-. ]\d{4}" + NA)),
    Rule("pii.phone_050", "personal", "error", "050 안심·대표 번호",
         R(NB + r"050\d[-. ]?\d{3,4}[-. ]?\d{4}" + NA)),
    Rule("pii.phone_rep", "personal", "warn", "대표번호(15xx·16xx·18xx)",
         R(NB + r"1(?:5[4-9]\d|6\d\d|8\d\d)-\d{4}" + NA)),
    Rule("pii.phone_intl_kr", "personal", "error", "국제 표기 한국 전화번호",
         R(r"\+82[- ]?\(?0?\d{1,2}\)?[- ]?\d{3,4}[- ]?\d{4}" + NA)),
    Rule("pii.rrn", "personal", "error", "주민등록번호 꼴",
         R(NB + r"\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])-[1-8]\d{6}" + NA)),
    Rule("pii.card", "personal", "error", "카드 번호 꼴(Luhn 맞음)",
         R(NB + r"(?:\d{4}[- ]){3}\d{4}" + NA + "|" + NB + r"\d{16}" + NA), v_luhn),
    # 열쇠
    Rule("key.pem_private", "key", "error", "개인키(PEM) 머리글",
         R(r"-----BEGIN[ A-Z0-9]*PRIVATE[ ]KEY[ A-Z]*-----")),
    Rule("key.putty", "key", "error", "PuTTY 개인키", R(r"PuTTY-User-Key-File-[0-9]")),
    Rule("key.minisign_secret", "key", "error", "minisign 비밀키",
         R(r"untrusted comment: minisign (?:encrypted )?secret key")),
    Rule("key.service_account", "key", "error", "구글 서비스 계정 열쇠 파일",
         R(r'"type"\s*:\s*"service[_]account"')),
    Rule("key.openai_like", "key", "error", "sk- 꼴 API 열쇠(OpenAI·Anthropic 등)",
         R(r"(?<![A-Za-z0-9])sk-(?:proj-|ant-(?:api\d\d-)?|live-)?[A-Za-z0-9_-]{20,}")),
    Rule("key.github", "key", "error", "깃허브 토큰",
         R(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    Rule("key.aws", "key", "error", "AWS 접근 열쇠", R(r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])")),
    Rule("key.google", "key", "error", "구글 API 열쇠", R(r"AIza[0-9A-Za-z_-]{35}")),
    Rule("key.slack", "key", "error", "슬랙 토큰", R(r"xox[abposr]-[A-Za-z0-9-]{10,}")),
    Rule("key.huggingface", "key", "error", "허깅페이스 토큰", R(r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{30,}")),
    Rule("key.stripe", "key", "error", "결제 서비스 열쇠",
         R(r"(?<![A-Za-z0-9])(?:sk|rk|pk)_(?:live|test)_[0-9A-Za-z]{16,}")),
    Rule("key.tailscale", "key", "error", "테일스케일 인증 열쇠", R(r"tskey-[a-z]+-[A-Za-z0-9]{8,}")),
    Rule("key.npm", "key", "error", "npm 토큰", R(r"npm_[A-Za-z0-9]{36}")),
    Rule("key.jwt", "key", "error", "JWT 토큰",
         R(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]{8,})?")),
    Rule("key.b64json", "key", "error", "base64 로 감싼 JSON(터널 토큰 등)", R(r"eyJ[A-Za-z0-9+/=_-]{30,}")),
    Rule("key.telegram", "key", "error", "텔레그램 봇 토큰",
         R(r"(?<![0-9])[0-9]{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")),
    Rule("key.discord", "key", "error", "디스코드 봇 토큰",
         R(r"(?<![A-Za-z0-9_-])[MNO][A-Za-z0-9_-]{23,27}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,40}(?![A-Za-z0-9_-])")),
    Rule("key.webhook", "key", "error", "웹훅 주소",
         R(r"(?i)(?:hooks\.slack\.com/services/|discord(?:app)?\.com/api/webhooks/)[A-Za-z0-9/_-]{10,}")),
    Rule("key.bearer", "key", "error", "Bearer 토큰", R(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{20,}=*")),
    Rule("key.url_credential", "key", "error", "주소 안 계정·비밀번호",
         R(r"(?i)[a-z][a-z0-9+.-]*://[^/\s:@\"']+:[^/\s@\"']+@[^\s/\"']+")),
    Rule("key.assignment", "key", "error", "비밀번호·열쇠 대입",
         R(r"(?i)(?<![A-Za-z0-9])(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token"
           r"|client[_-]?secret|private[_-]?key|token)[\"']?\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']"), v_assign),
    Rule("key.hex32", "key", "error", "32자리 16진수(앱 키 꼴)",
         R(r"(?<![0-9A-Za-z_])[0-9a-fA-F]{32}(?![0-9A-Za-z_])"), v_hexmix, hashlike=True),
    Rule("key.hex_long", "key", "error", "40자리 이상 16진수(열쇠 또는 해시)",
         R(r"(?<![0-9A-Za-z_])[0-9a-fA-F]{40,}(?![0-9A-Za-z_])"), v_hexmix, hashlike=True),
    Rule("key.random40", "key", "error", "40자 이상 무작위 글자",
         R(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_=-]{40,}(?![A-Za-z0-9+/_=-])"), v_random, hashlike=True),
    # 기록
    Rule("rec.dated_note", "record", "error", "날짜가 붙은 지시·사고 기록",
         R(r"20\d\d[-./]\d{1,2}[-./]\d{1,2}[^\n]{0,20}?(?:지시|사고)")),
]


# ── 결과 모음 ──────────────────────────────────────────────────
@dataclass
class Finding:
    severity: str
    category: str
    rule: str
    label: str
    file: str
    line: int | None = None
    col: int | None = None
    masked: str = ""
    view: str = "text"
    note: str = ""


def mask(s: str) -> str:
    s = s.replace("\r", " ").replace("\n", " ")
    n = len(s)
    if n <= 3:
        return "*" * n + f"(len {n})"
    keep = 3 if n >= 8 else 1
    return s[:keep] + "*" * min(n - keep, 10) + f"(len {n})"


def _key_norm(s: str) -> str:
    return ZW_RX.sub("", unicodedata.normalize("NFKC", s))


class Ctx:
    def __init__(self, mode: str, rules: list[Rule]):
        self.mode = mode
        self.rules = rules
        self.findings: list[Finding] = []
        self.suppressed: list[dict] = []
        self.notices: list[dict] = []
        self.private = {"loaded": False, "entries": 0, "path": None}
        self.private_data: dict = {}
        self.allowlist_stats: dict = {}
        self.stats = Counter()
        self._seen: set = set()

    def add(self, f: Finding, raw: str | None = None) -> None:
        key = (f.file, f.line, f.rule, _key_norm(raw) if raw is not None else f.masked)
        if key in self._seen:
            return
        self._seen.add(key)
        self.findings.append(f)

    def suppress(self, f: Finding, reason: str) -> None:
        d = asdict(f)
        d["reason"] = reason
        self.suppressed.append(d)

    def notice(self, severity: str, code: str, message: str) -> None:
        self.notices.append({"severity": severity, "code": code, "message": message})

    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error") + \
            sum(1 for n in self.notices if n["severity"] == "error")

    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warn") + \
            sum(1 for n in self.notices if n["severity"] == "warn")


# ── 비공개 낱말 목록 ────────────────────────────────────────────
def compile_private(entry: dict) -> re.Pattern:
    pat = entry["pattern"]
    body = re.escape(pat) if entry.get("kind", "literal") == "literal" else pat
    b = entry.get("boundary", "none")
    if b == "left":
        body = f"(?<![{HANGUL_WORD}])(?:{body})"
    elif b == "word":
        body = f"(?<![0-9A-Za-z_])(?:{body})(?![0-9A-Za-z_])"
    elif b == "both":
        body = f"(?<![{HANGUL_WORD}])(?:{body})(?![{HANGUL_WORD}])"
    elif b != "none":
        raise ValueError(f"boundary 값이 이상함: {b}")
    flags = re.IGNORECASE if entry.get("ignore_case", True) else 0
    return re.compile(body, flags)


def resolve_private_path(args, root: Path | None) -> Path | None:
    if getattr(args, "private_list", None):
        return Path(args.private_list)
    env = os.environ.get(PRIVATE_ENV)
    if env:
        return Path(env)
    if root is not None:
        return root.joinpath(*DEFAULT_PRIVATE_PARTS)
    return None


def load_private(ctx: Ctx, args, root: Path | None) -> list[Rule]:
    path = resolve_private_path(args, root)
    require = bool(getattr(args, "require_private", False))
    if path is None or not path.is_file():
        ctx.notice("error" if require else "warn", "private.missing",
                   "비공개 금지 낱말 목록이 없어 일반 꼴만 검사했습니다"
                   + (f" (찾은 곳: {path})" if path else ""))
        return []
    if root is not None:
        try:
            path.resolve().relative_to(root.resolve())
            ctx.notice("error", "private.inside_repo", "비공개 금지 낱말 목록이 저장소 안에 있습니다 — 저장소 밖으로 옮기세요")
        except ValueError:
            pass
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        ctx.notice("error", "private.invalid", f"비공개 금지 낱말 목록을 읽지 못했습니다: {type(e).__name__}")
        return []
    if data.get("schema") != PRIVATE_SCHEMA:
        ctx.notice("error", "private.invalid", f"비공개 목록 schema 가 {PRIVATE_SCHEMA} 가 아닙니다")
        return []
    rules: list[Rule] = []
    bad = 0
    for i, e in enumerate(data.get("entries", [])):
        eid = str(e.get("id") or f"p{i + 1:03d}")
        try:
            rx = compile_private(e)
        except (KeyError, ValueError, re.error):
            bad += 1
            ctx.notice("error", "private.bad_entry", f"비공개 목록의 {eid} 항목을 쓸 수 없습니다(꼴 오류)")
            continue
        sev = e.get("severity", "error")
        if sev not in ("error", "warn"):
            sev = "error"
        rules.append(Rule(f"private.{eid}", "private", sev, str(e.get("label") or "비공개 낱말"), rx))
    ctx.private = {"loaded": True, "entries": len(rules), "bad": bad, "path": str(path)}
    ctx.private_data = data
    return rules


# ── 글 읽기 ────────────────────────────────────────────────────
ZW_RX = re.compile("[​-‏⁠-⁤﻿­]")


def decode_text(ctx: Ctx, data: bytes, display: str) -> str | None:
    if data.startswith(codecs.BOM_UTF8):
        try:
            return data[len(codecs.BOM_UTF8):].decode("utf-8")
        except UnicodeDecodeError:
            return None
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp949")
        except UnicodeDecodeError:
            return None
        if not re.search("[가-힣]", text):
            return None
        ctx.notice("warn", "text.not_utf8", f"{display}: UTF-8 이 아닌 글 파일(cp949 로 읽음)")
    ctrl = sum(1 for c in text if ord(c) < 32 and c not in "\t\r\n\f\v")
    if text and ctrl / len(text) > 0.01:
        return None
    return text


def _walk_strings(obj, out: list[str]) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            _walk_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_strings(v, out)


def _collect_hash_values(obj, keys: set[str], out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str):
                out.add(v)
            else:
                _collect_hash_values(v, keys, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_hash_values(v, keys, out)


def text_views(text: str, is_json: bool) -> list[tuple[str, str]]:
    views = [("text", text)]
    alt = ZW_RX.sub("", unicodedata.normalize("NFKC", text))
    if alt != text:
        views.append(("normalized", alt))
    if is_json and "\\u" in text:
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            obj = None
        if obj is not None:
            vals: list[str] = []
            _walk_strings(obj, vals)
            views.append(("json-values", "\n".join(vals)))
    return views


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(m.end() for m in re.finditer("\n", text))
    return starts


def _exception_hit(exceptions, line, line_text, col0, matched, whole) -> dict | None:
    for ex in exceptions:
        allow = ex["allow"]
        if ex.get("line") is None:
            if matched in allow and allow in whole:
                return ex
            continue
        if line is None or line_text is None or ex["line"] != line:
            continue
        start = 0
        while True:
            i = line_text.find(allow, start)
            if i < 0:
                break
            if i <= col0 and col0 + len(matched) <= i + len(allow):
                return ex
            start = i + 1
    return None


def scan_text(ctx: Ctx, display: str, text: str, *, exceptions=(), hash_values=frozenset(),
              is_json=False) -> None:
    for vname, vtext in text_views(text, is_json):
        starts = _line_starts(vtext)
        for rule in ctx.rules:
            for m in rule.regex.finditer(vtext):
                if rule.check is not None and not rule.check(m, vtext):
                    continue
                s, e = m.span()
                matched = m.group(0)
                if vname == "json-values":
                    line = col = None
                    line_text = None
                    col0 = None
                else:
                    li = bisect.bisect_right(starts, s) - 1
                    line = li + 1
                    col0 = s - starts[li]
                    col = col0 + 1
                    end = starts[li + 1] - 1 if li + 1 < len(starts) else len(vtext)
                    line_text = vtext[starts[li]:end]
                f = Finding(rule.severity, rule.category, rule.rid, rule.label, display, line, col,
                            mask(matched), vname)
                if rule.hashlike and any(matched in hv for hv in hash_values):
                    ctx.suppress(f, "해시 칸(json_hash_keys) 값")
                    continue
                ex = _exception_hit(exceptions, line, line_text, col0 or 0, matched, vtext)
                if ex is not None:
                    ctx.suppress(f, "허용 목록 예외: " + str(ex.get("reason", "")))
                    continue
                ctx.add(f, matched)


# ── 이진 파일 ──────────────────────────────────────────────────
def _png_text(data: bytes) -> list[str]:
    out: list[str] = []
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return out
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        try:
            if ctype == b"tEXt":
                k, _, v = body.partition(b"\x00")
                out.append(k.decode("latin-1") + " " + v.decode("latin-1"))
            elif ctype == b"zTXt":
                k, _, rest = body.partition(b"\x00")
                out.append(k.decode("latin-1") + " " + zlib.decompress(rest[1:]).decode("latin-1"))
            elif ctype == b"iTXt":
                k, _, rest = body.partition(b"\x00")
                flag = rest[0:1]
                rest = rest[2:]
                _lang, _, rest = rest.partition(b"\x00")
                _tk, _, txt = rest.partition(b"\x00")
                if flag == b"\x01":
                    txt = zlib.decompress(txt)
                out.append(k.decode("latin-1") + " " + txt.decode("utf-8", "replace"))
            elif ctype == b"IEND":
                break
        except (zlib.error, IndexError, UnicodeDecodeError):
            continue
    return out


def binary_views(data: bytes) -> list[tuple[str, str]]:
    views: list[tuple[str, str]] = []
    a = [x.decode("ascii") for x in re.findall(rb"[\x20-\x7e\t]{4,}", data)]
    if a:
        views.append(("binary-ascii", "\n".join(a)))
    u16 = [x.decode("utf-16-le", "ignore")
           for x in re.findall(rb"(?:[\x20-\x7e]\x00|[\x00-\xff][\xac-\xd7]){4,}", data)]
    if u16:
        views.append(("binary-utf16", "\n".join(u16)))
    u8 = [x.decode("utf-8", "ignore")
          for x in re.findall(rb"(?:[\x20-\x7e]|[\xea-\xed][\x80-\xbf]{2}){3,}", data)
          if re.search(rb"[\xea-\xed]", x)]
    if u8:
        views.append(("binary-utf8", "\n".join(u8)))
    p = _png_text(data)
    if p:
        views.append(("png-text", "\n".join(p)))
    return views


def scan_binary(ctx: Ctx, display: str, data: bytes, exceptions=()) -> None:
    if len(data) <= BINARY_WINDOW:
        windows = [data]
    else:
        windows = [data[i:i + BINARY_WINDOW + BINARY_OVERLAP]
                   for i in range(0, len(data), BINARY_WINDOW)]
    file_exc = [ex for ex in exceptions if ex.get("line") is None]
    for w in windows:
        for vname, vtext in binary_views(w):
            for rule in ctx.rules:
                for m in rule.regex.finditer(vtext):
                    if rule.check is not None and not rule.check(m, vtext):
                        continue
                    matched = m.group(0)
                    f = Finding(rule.severity, rule.category, rule.rid, rule.label, display, None, None,
                                mask(matched), vname, "이진 파일 속 글자")
                    ex = _exception_hit(file_exc, None, None, 0, matched, vtext)
                    if ex is not None:
                        ctx.suppress(f, "허용 목록 예외: " + str(ex.get("reason", "")))
                        continue
                    ctx.add(f, matched)


# ── 파일 종류 ──────────────────────────────────────────────────
def check_types(ctx: Ctx, rel: str, display: str, profile: str, entry: dict | None = None,
                extra_forbid: tuple = ()) -> None:
    parts = PurePosixPath(rel).parts
    if not parts:
        return
    name = parts[-1]
    low = name.lower()
    ext = os.path.splitext(low)[1]
    fdirs = FORBIDDEN_DIRS if profile != "artifact" else ARTIFACT_FORBIDDEN_DIRS
    for d in parts[:-1]:
        dl = d.lower()
        if dl in fdirs or dl.startswith(FORBIDDEN_DIR_PREFIX):
            ctx.add(Finding("error", "filetype", "type.forbidden_dir", "금지 폴더", display,
                            masked=d, note=f"폴더 '{d}' 안의 파일"))
            break
    if ext in FORBIDDEN_EXT or low in FORBIDDEN_NAMES or (
            low.startswith(".env") and not low.endswith(".example")):
        ctx.add(Finding("error", "filetype", "type.forbidden", "금지 파일 종류", display,
                        masked=ext or low, note="열쇠·서명된 앱·기록·자료 파일"))
    if ext and ext.lstrip(".") in extra_forbid:
        ctx.add(Finding("error", "filetype", "type.forbidden_extra", "이번 산출물에서 뺀 종류", display,
                        masked=ext, note="--forbid-ext"))
    if profile != "artifact" and ext in NEEDS_ALLOW_EXT and not (entry and entry.get("allow_type")):
        ctx.add(Finding("error", "filetype", "type.needs_allow", "허용 목록 예외가 필요한 종류", display,
                        masked=ext, note="소리·모델·압축·실행 파일은 허용 목록에 allow_type 으로 적힌 것만"))
    if SUSPICIOUS_NAME.search(name):
        ctx.add(Finding("warn", "filetype", "type.suspicious_name", "비밀처럼 보이는 파일 이름", display,
                        masked=mask(name)))
    if profile == "repo" and any(ord(c) > 127 for c in rel) and not (entry and entry.get("nonascii_name_ok")):
        ctx.add(Finding("warn", "filetype", "type.nonascii_name", "영어가 아닌 파일 이름", display,
                        note="설계 2-2: 파일·폴더 이름은 영어(단추 .bat 만 한글) — 예외는 nonascii_name_ok"))


# ── 압축 ───────────────────────────────────────────────────────
def is_zip(data: bytes) -> bool:
    try:
        return zipfile.is_zipfile(io.BytesIO(data))
    except Exception:
        return False


def scan_archive(ctx: Ctx, data: bytes, display: str, depth: int, forbid_ext: tuple = (),
                 manifest: dict | None = None) -> None:
    ctx.stats["archives"] += 1
    if depth >= MAX_ARCHIVE_DEPTH:
        ctx.add(Finding("error", "archive", "archive.too_deep", "압축이 너무 깊게 겹침", display,
                        note=f"{MAX_ARCHIVE_DEPTH}단 넘게 겹친 압축은 검사하지 않음"))
        return
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError) as e:
        ctx.add(Finding("error", "archive", "archive.unreadable", "압축을 열 수 없음", display, note=type(e).__name__))
        return
    members: dict[str, str] = {}
    total = 0
    hipcpet = False   # 옷 꾸러미(pack.json format hipcpet/1)면 해시 칸을 알아봄
    try:
        pinfo = zf.getinfo("pack.json")
        if pinfo.file_size <= 4_000_000:
            hipcpet = json.loads(zf.read(pinfo).decode("utf-8-sig")).get("format") == "hipcpet/1"
    except (KeyError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, AttributeError, OSError, ValueError):
        hipcpet = False
    with zf:
        for info in zf.infolist():
            norm = info.filename.replace("\\", "/")
            mdisp = f"{display}!{norm}"
            pp = PurePosixPath(norm)
            if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or ".." in pp.parts:
                ctx.add(Finding("error", "archive", "archive.path_escape", "풀 때 밖으로 나가는 이름", mdisp))
            if info.is_dir():
                continue
            if info.flag_bits & 0x1:
                ctx.add(Finding("error", "archive", "archive.encrypted", "암호 걸린 항목(검사 못 함)", mdisp))
                continue
            if info.file_size > MAX_FILE_BYTES:
                ctx.add(Finding("error", "archive", "archive.member_too_big", "너무 큰 항목(검사 못 함)", mdisp))
                continue
            if info.file_size > BIG_BOMB_BYTES and info.file_size / max(info.compress_size, 1) > MAX_RATIO:
                ctx.add(Finding("error", "archive", "archive.bomb", "압축 폭탄 의심", mdisp))
                continue
            total += info.file_size
            if total > MAX_ARCHIVE_TOTAL:
                ctx.add(Finding("error", "archive", "archive.total_too_big", "풀린 크기가 너무 큼(검사 중단)", display))
                break
            check_types(ctx, norm, mdisp, "artifact", None, forbid_ext)
            try:
                member = zf.read(info)
            except Exception as e:  # noqa: BLE001 — 손상된 항목도 결과로 남김
                ctx.add(Finding("error", "archive", "archive.member_unreadable", "항목을 읽을 수 없음", mdisp,
                                note=type(e).__name__))
                continue
            ctx.stats["archive_members"] += 1
            members[norm] = hashlib.sha256(member).hexdigest()
            hv: set[str] = set()
            keys = HIPCPET_HASH_KEYS.get(norm) if hipcpet else None
            if keys:
                try:
                    _collect_hash_values(json.loads(member.decode("utf-8-sig")), set(keys), hv)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
            scan_blob(ctx, member, mdisp, norm, depth + 1, forbid_ext=forbid_ext, hash_values=frozenset(hv))
    if manifest is not None:
        compare_manifest(ctx, display, members, manifest)


# 옷 꾸러미 안 json 의 해시 칸: pack.json 파일 목록 sha256 · 입 맞추기 장별 값(16진수 글자열) · signature.json 서명
HIPCPET_HASH_KEYS = {"pack.json": ("sha256", "mouth"), "signature.json": ("sig",)}


def compare_manifest(ctx: Ctx, display: str, members: dict[str, str], manifest: dict) -> None:
    want = manifest.get("files", {})
    for name, sha in want.items():
        if name not in members:
            ctx.add(Finding("error", "archive", "archive.manifest_missing", "목록에 있는데 압축에 없음",
                            f"{display}!{name}"))
        elif sha and sha.lower() != members[name]:
            ctx.add(Finding("error", "archive", "archive.manifest_sha256", "목록과 sha256 다름", f"{display}!{name}"))
    if not manifest.get("allow_extra", False):
        for name in members:
            if name not in want:
                ctx.add(Finding("error", "archive", "archive.manifest_extra", "목록에 없는 항목이 압축에 있음",
                                f"{display}!{name}"))


# ── 영상·소리 파일: 글이 들어갈 수 있는 곳만 ────────────────────
# 압축된 영상 장면(webm Cluster)·색인(Cues)·mp3 소리 프레임은 무작위 바이트라 짧은 낱말·이메일 꼴이 우연히 걸림(6단계 실측: 영상 337개에서 38건).
# 그래서 그 부분만 빼고 머리·정보·트랙 이름·태그·첨부(webm), ID3·APE 태그(mp3)를 검사한다. 모양이 조금이라도 이상하면 None → 파일 통째 검사(엄격한 쪽).
_EBML_PAYLOAD = {0x1F43B675, 0x1C53BB6B}   # Cluster(장면), Cues(색인)
_EBML_CONTAINERS = {0x18538067}            # Segment(안을 더 걸음)


def _ebml_vint(data: bytes, pos: int, keep_marker: bool) -> tuple[int, int, bool]:
    b = data[pos]
    if b == 0:
        raise ValueError("vint")
    n, m = 1, 0x80
    while not (b & m):
        m >>= 1
        n += 1
    if pos + n > len(data):
        raise ValueError("vint")
    v = b if keep_marker else (b & (m - 1))
    for i in range(1, n):
        v = (v << 8) | data[pos + i]
    unknown = (not keep_marker) and v == (1 << (7 * n)) - 1
    return v, n, unknown


def ebml_meta(data: bytes) -> bytes | None:
    if data[:4] != b"\x1a\x45\xdf\xa3":
        return None
    out: list[bytes] = []
    skipped = 0

    def walk(pos: int, end: int) -> None:
        nonlocal skipped
        while pos < end:
            eid, n1, _ = _ebml_vint(data, pos, True)
            size, n2, unk = _ebml_vint(data, pos + n1, False)
            body = pos + n1 + n2
            if eid in _EBML_CONTAINERS:
                out.append(data[pos:body])
                stop = end if unk else body + size
                if stop > end:
                    raise ValueError("size")
                walk(body, stop)
                pos = stop
                continue
            if unk or body + size > end:
                raise ValueError("size")     # 크기 모르는 장면 묶음 등 → 통째 검사
            if eid in _EBML_PAYLOAD:
                out.append(data[pos:body])
                skipped += size
            else:
                out.append(data[pos:body + size])
            pos = body + size

    try:
        walk(0, len(data))
    except (ValueError, IndexError, RecursionError):
        return None
    if not skipped:
        return None
    return b"\x00".join(out)


def mp3_meta(data: bytes) -> bytes | None:
    pos = 0
    out: list[bytes] = []
    if data[:3] == b"ID3" and len(data) >= 10:
        sz = data[6:10]
        if any(x & 0x80 for x in sz):
            return None
        n = (sz[0] << 21) | (sz[1] << 14) | (sz[2] << 7) | sz[3]
        pos = 10 + n + (10 if data[5] & 0x10 else 0)
        out.append(data[:pos])
    if pos + 2 > len(data) or data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
        return None                          # ID3 바로 뒤가 mp3 프레임이 아님 → 통째 검사
    tail_from = len(data)
    if data[-128:-125] == b"TAG":
        tail_from = len(data) - 128
    ape = data.rfind(b"APETAGEX", max(0, len(data) - 65536))
    if ape >= 0:
        tail_from = min(tail_from, ape)
    out.append(data[tail_from:])
    return b"\x00".join(out)


def media_meta(ext: str, data: bytes) -> bytes | None:
    if ext in (".webm", ".mkv"):
        return ebml_meta(data)
    if ext == ".mp3":
        return mp3_meta(data)
    return None


def zip_skeleton(data: bytes) -> bytes:
    """zip 에서 각 항목의 내용(압축된 바이트)을 뺀 뼈대: 이름·여분 칸·주석·목록. 항목 내용은 따로 풀어서 검사한다."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        spans = []
        for info in zf.infolist():
            h = info.header_offset
            if data[h:h + 4] != b"PK\x03\x04":
                return data
            n, x = struct.unpack("<HH", data[h + 26:h + 30])
            start = h + 30 + n + x
            spans.append((start, start + info.compress_size))
    except Exception:  # noqa: BLE001 — 못 읽으면 통째 검사
        return data
    spans.sort()
    out, last = [], 0
    for s, e in spans:
        if s < last:
            return data
        out.append(data[last:s])
        last = e
    out.append(data[last:])
    return b"\x00".join(out)


def scan_blob(ctx: Ctx, data: bytes, display: str, name: str, depth: int, *, forbid_ext: tuple = (),
              exceptions=(), hash_values=frozenset()) -> None:
    ext = os.path.splitext(name.lower())[1]
    text = decode_text(ctx, data, display)
    if text is not None:
        ctx.stats["text"] += 1
        scan_text(ctx, display, text, exceptions=exceptions, hash_values=hash_values,
                  is_json=ext in (".json", ".webmanifest"))
        return
    ctx.stats["binary"] += 1
    meta = media_meta(ext, data)
    if meta is not None:
        ctx.stats["media_meta_only"] += 1
        scan_binary(ctx, display, meta, exceptions)
        return
    scan_binary(ctx, display, data, exceptions)
    if is_zip(data):
        scan_archive(ctx, data, display, depth, forbid_ext)


# ── 저장소 걷기 ────────────────────────────────────────────────
def _is_link(p: Path) -> bool:
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & 0x400)


def walk_tree(ctx: Ctx, root: Path, skip_top_git: bool = True) -> list[str]:
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        rel_dir = here.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if skip_top_git and rel == ".git":
                continue
            if _is_link(here / d):
                ctx.add(Finding("error", "filetype", "type.link", "바로가기 연결(심볼릭 링크·정션)", rel))
                continue
            if d == ".git":
                ctx.add(Finding("error", "filetype", "type.nested_git", "저장소 안의 다른 git 저장소", rel))
                continue
            keep.append(d)
        dirnames[:] = keep
        if not filenames and not keep and rel_dir:
            ctx.add(Finding("warn", "filetype", "type.empty_dir", "빈 폴더(git 에 남지 않음)", rel_dir))
        for fn in sorted(filenames):
            rel = f"{rel_dir}/{fn}" if rel_dir else fn
            if _is_link(here / fn):
                ctx.add(Finding("error", "filetype", "type.link", "바로가기 연결(심볼릭 링크)", rel))
                continue
            out.append(rel)
    return out


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 허용 목록 ──────────────────────────────────────────────────
ORIGIN_RX = re.compile(r"^(?:new|standard:[A-Za-z0-9._-]+|[a-z][a-z0-9_-]*:[^\\:]+)$")
ABS_PATH_RX = re.compile(r"^(?:[A-Za-z]:|/|\\\\)")


def load_allowlist(ctx: Ctx, root: Path) -> dict | None:
    p = root / ALLOWLIST_REL
    if not p.is_file():
        ctx.notice("error", "allowlist.absent", f"허용 목록이 없습니다: {ALLOWLIST_REL}")
        return None
    try:
        data = json.loads(p.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        ctx.notice("error", "allowlist.invalid", f"허용 목록을 읽지 못했습니다: {type(e).__name__}: {e}")
        return None
    if data.get("schema") != ALLOWLIST_SCHEMA:
        ctx.notice("error", "allowlist.invalid", f"허용 목록 schema 가 {ALLOWLIST_SCHEMA} 가 아닙니다")
        return None
    return data


def _entry_problems(e: dict) -> list[str]:
    probs = []
    path = e.get("path")
    if not isinstance(path, str) or not path:
        return ["path 없음"]
    if "\\" in path or ABS_PATH_RX.match(path) or ".." in PurePosixPath(path).parts:
        probs.append("path 는 저장소 안 상대 경로(/ 구분)여야 함")
    if e.get("treatment") not in TREATMENTS:
        probs.append("treatment 는 " + "/".join(TREATMENTS) + " 중 하나")
    origin = e.get("origin")
    if not isinstance(origin, str) or not ORIGIN_RX.match(origin) or ABS_PATH_RX.match(origin.split(":", 1)[-1]):
        probs.append("origin 은 new / standard:<이름> / <별칭>:<상대경로> (절대 경로 금지)")
    if not e.get("self"):
        sha = e.get("sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            probs.append("sha256 은 소문자 16진수 64자리")
    for ex in e.get("exceptions", []) or []:
        if not isinstance(ex, dict) or not isinstance(ex.get("allow"), str) or not ex["allow"]:
            probs.append("exceptions 항목에 allow(허용 글자)가 없음")
        elif ex.get("line") is not None and (not isinstance(ex["line"], int) or ex["line"] < 1):
            probs.append("exceptions.line 은 1 이상 정수 또는 null(파일 전체)")
        elif not str(ex.get("reason", "")).strip():
            probs.append("exceptions 항목에 reason(이유)이 없음")
    return probs


def compare_allowlist(ctx: Ctx, root: Path, files: list[str], data: dict) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    st = Counter()
    for e in data.get("files", []):
        if not isinstance(e, dict):
            ctx.notice("error", "allowlist.invalid", "허용 목록 files 안에 객체가 아닌 줄이 있습니다")
            continue
        path = e.get("path", "?")
        for prob in _entry_problems(e):
            ctx.add(Finding("error", "allowlist", "allowlist.bad_entry", "허용 목록 줄 형식 오류", str(path), note=prob))
        if path in entries:
            ctx.add(Finding("error", "allowlist", "allowlist.duplicate", "허용 목록에 같은 경로가 두 번", str(path)))
        entries[path] = e
    st["entries"] = len(entries)
    self_entry = entries.get(ALLOWLIST_REL)
    if not self_entry or not self_entry.get("self"):
        ctx.add(Finding("error", "allowlist", "allowlist.self", "허용 목록 자신이 self:true 로 적혀 있지 않음",
                        ALLOWLIST_REL))
    fileset = set(files)
    lower_map = Counter(f.lower() for f in files)
    for f in files:
        if lower_map[f.lower()] > 1:
            ctx.add(Finding("error", "allowlist", "allowlist.case_clash", "대소문자만 다른 파일 이름", f))
        if f not in entries:
            st["unlisted"] += 1
            ctx.add(Finding("error", "allowlist", "allowlist.unlisted", "허용 목록에 없는 파일", f))
    for path, e in entries.items():
        if path not in fileset:
            st["missing"] += 1
            ctx.add(Finding("error", "allowlist", "allowlist.missing", "허용 목록에 있는데 파일이 없음", path))
            continue
        if e.get("self"):
            continue
        actual = sha256_file(root / path)
        if e.get("sha256") != actual:
            st["sha256_mismatch"] += 1
            ctx.add(Finding("error", "allowlist", "allowlist.sha256", "sha256 이 허용 목록과 다름", path,
                            note=f"목록 {str(e.get('sha256'))[:12]}… / 실제 {actual[:12]}…"))
        else:
            st["sha256_ok"] += 1
        _check_origin(ctx, root, e, actual)
        _check_stale_exceptions(ctx, root, path, e)
    ctx.allowlist_stats = dict(st)
    return entries


def _check_origin(ctx: Ctx, root: Path, e: dict, actual: str) -> None:
    roots = ctx.private_data.get("origin_roots") or {}
    origin = str(e.get("origin", ""))
    if e.get("treatment") != "copy" or ":" not in origin or origin.startswith(("new", "standard:")):
        return
    alias, rel = origin.split(":", 1)
    base = roots.get(alias)
    if not base:
        return
    src = Path(base) / rel
    if not src.is_file():
        ctx.add(Finding("warn", "allowlist", "allowlist.origin_missing", "원본 파일을 찾지 못함(그대로 옮김)", e["path"]))
    elif sha256_file(src) != actual:
        ctx.add(Finding("warn", "allowlist", "allowlist.origin_differs", "'그대로 옮김'인데 원본과 내용이 다름",
                        e["path"]))


def _check_stale_exceptions(ctx: Ctx, root: Path, path: str, e: dict) -> None:
    exs = e.get("exceptions") or []
    if not exs:
        return
    try:
        text = decode_text(Ctx("tmp", []), (root / path).read_bytes(), path)
    except OSError:
        return
    lines = text.split("\n") if text is not None else None
    for ex in exs:
        allow = ex.get("allow", "")
        ln = ex.get("line")
        if ln is None:
            ok = text is not None and allow in text
        else:
            ok = lines is not None and 1 <= ln <= len(lines) and allow in lines[ln - 1]
        if not ok:
            ctx.add(Finding("error", "allowlist", "allowlist.stale_exception", "예외가 가리키는 줄에 그 글자가 없음",
                            path, ln, note="줄이 밀렸거나 글이 바뀜 — 예외를 다시 확인"))


def allowlist_self_exceptions(raw: str) -> list[dict]:
    """허용 목록 파일 안의 "allow" 값(예외로 허락한 글자) 자리는 그 줄에서만 넘긴다."""
    out = []
    for i, line in enumerate(raw.split("\n"), 1):
        m = re.search(r'"allow"\s*:\s*("(?:[^"\\]|\\.)*")', line)
        if m:
            try:
                out.append({"line": i, "allow": json.loads(m.group(1)), "reason": "허용 목록의 예외 글자"})
            except json.JSONDecodeError:
                pass
    return out


def scan_repo_file(ctx: Ctx, root: Path, rel: str, entry: dict | None) -> None:
    p = root / rel
    try:
        size = p.stat().st_size
    except OSError as e:
        ctx.add(Finding("error", "filetype", "type.unreadable", "파일을 읽을 수 없음", rel, note=type(e).__name__))
        return
    if size > MAX_FILE_BYTES:
        ctx.add(Finding("error", "filetype", "type.too_big", "너무 큰 파일(검사 못 함)", rel))
        return
    data = p.read_bytes()
    ctx.stats["files"] += 1
    exceptions = list((entry or {}).get("exceptions") or [])
    hash_values: set[str] = set()
    hash_keys = set((entry or {}).get("json_hash_keys") or [])
    if rel == ALLOWLIST_REL:
        raw = data.decode("utf-8", "replace")
        exceptions = allowlist_self_exceptions(raw)
        hash_keys.add("sha256")
    if hash_keys:
        try:
            _collect_hash_values(json.loads(data.decode("utf-8-sig")), hash_keys, hash_values)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    scan_blob(ctx, data, rel, rel, 0, exceptions=exceptions, hash_values=frozenset(hash_values))


def check_git_remote(ctx: Ctx, root: Path) -> None:
    cfg = root / ".git" / "config"
    if cfg.is_file():
        try:
            txt = cfg.read_text("utf-8", "replace")
        except OSError:
            return
        if re.search(r"^\s*\[remote\s", txt, re.M):
            ctx.notice("warn", "git.remote", "git 원격 연결이 있습니다 — 공개 승인 전에는 올리지 마세요")


# ── 결과 내기 ──────────────────────────────────────────────────
def finish(ctx: Ctx, args, root: Path | None, targets: list[str]) -> int:
    ok = ctx.errors() == 0
    res = {
        "tool": "release_check",
        "version": TOOL_VERSION,
        "mode": ctx.mode,
        "time": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": str(root) if root else None,
        "targets": targets,
        "private_list": ctx.private,
        "result": "PASS" if ok else "FAIL",
        "counts": {
            "files": ctx.stats["files"], "text": ctx.stats["text"], "binary": ctx.stats["binary"],
            "archives": ctx.stats["archives"], "archive_members": ctx.stats["archive_members"],
            "media_meta_only": ctx.stats["media_meta_only"],
            "errors": ctx.errors(), "warnings": ctx.warnings(), "suppressed": len(ctx.suppressed),
            "rules": len(ctx.rules),
        },
        "allowlist": ctx.allowlist_stats,
        "by_rule": dict(Counter(f.rule for f in ctx.findings)),
        "notices": ctx.notices,
        "findings": [asdict(f) for f in ctx.findings],
        "suppressed": ctx.suppressed,
    }
    print_summary(res, getattr(args, "max_show", 200))
    out = getattr(args, "json_out", None)
    if out:
        op = Path(out)
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_bytes((json.dumps(res, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return 0 if ok else 1


def print_summary(res: dict, max_show: int) -> None:
    c = res["counts"]
    pl = res["private_list"]
    lines = [
        f"공개 전 검사 release_check {res['version']} — 모드: {res['mode']}",
        f"대상: {res['root'] or ', '.join(res['targets'])}",
        "비공개 낱말 목록: " + (f"읽음({pl.get('entries', 0)}개)" if pl.get("loaded") else "없음 — 일반 꼴만 검사"),
        f"파일 {c['files']}개 (글 {c['text']} · 이진 {c['binary']} · 압축 {c['archives']}, 압축 속 항목 {c['archive_members']}) · 규칙 {c['rules']}개",
    ]
    al = res.get("allowlist") or {}
    if al:
        lines.append(f"허용 목록: {al.get('entries', 0)}줄 · 목록 밖 {al.get('unlisted', 0)} · 빠짐 {al.get('missing', 0)}"
                     f" · sha256 다름 {al.get('sha256_mismatch', 0)} · 맞음 {al.get('sha256_ok', 0)}")
    lines.append(f"찾은 것: 오류 {c['errors']} · 경고 {c['warnings']} · 예외로 넘김 {c['suppressed']}")
    for n in res["notices"]:
        lines.append(f"  [{'오류' if n['severity'] == 'error' else '경고'}] {n['code']}: {n['message']}")
    fs = sorted(res["findings"], key=lambda f: (f["severity"] != "error", f["file"], f["line"] or 0))
    for f in fs[:max_show]:
        where = f["file"] + (f":{f['line']}" if f["line"] else "") + (f" ({f['view']})" if f["view"] != "text" else "")
        sev = "오류" if f["severity"] == "error" else "경고"
        extra = f" — {f['note']}" if f["note"] else ""
        lines.append(f"  [{sev}] {where}  {f['rule']} {f['label']}  {f['masked']}{extra}")
    if len(fs) > max_show:
        lines.append(f"  … 그 밖 {len(fs) - max_show}건(JSON 에 전부)")
    lines.append("결과: " + ("통과" if res["result"] == "PASS" else "실패"))
    print("\n".join(lines))


# ── 명령 ───────────────────────────────────────────────────────
def default_root() -> Path:
    return Path(__file__).resolve().parent.parent


def make_ctx(mode: str, args, root: Path | None) -> Ctx:
    ctx = Ctx(mode, [])
    ctx.rules = list(GENERIC_RULES) + load_private(ctx, args, root)
    return ctx


def cmd_check(args, only_allowlist: bool = False) -> int:
    root = Path(args.root).resolve() if args.root else default_root()
    ctx = make_ctx("allowlist-verify" if only_allowlist else "check", args, root)
    files = walk_tree(ctx, root)
    data = load_allowlist(ctx, root)
    entries = compare_allowlist(ctx, root, files, data) if data is not None else {}
    if not only_allowlist:
        for rel in files:
            entry = entries.get(rel)
            check_types(ctx, rel, rel, "repo", entry)
            scan_repo_file(ctx, root, rel, entry)
        check_git_remote(ctx, root)
    else:
        ctx.stats["files"] = len(files)
    rc = finish(ctx, args, root, [])
    if rc == 0 and getattr(args, "ui", False):
        rc = run_ui_hangul(args, root)
    return rc


def run_ui_hangul(args, root) -> int:
    """실제 크롬으로 en/ja/zh 화면의 남은 한글을 센다(tools/ui_hangul_check.py)."""
    tool = Path(root) / "tools" / "ui_hangul_check.py"
    if not tool.is_file():
        print("[ui-hangul] 도구가 없음:", tool)
        return 2
    py = getattr(args, "python", None) or sys.executable
    cmd = [py, "-B", "-X", "utf8", str(tool), "--repo", str(root), "--python", py,
           "--langs", getattr(args, "langs", None) or "en,ja,zh"]
    if getattr(args, "chrome", None):
        cmd += ["--chrome", args.chrome]
    if getattr(args, "out", None):
        cmd += ["--out", args.out]
    if getattr(args, "shots", None):
        cmd += ["--shots", args.shots]
    if getattr(args, "keep_profile", False):
        cmd += ["--keep-profile"]
    print("[ui-hangul] 실제 크롬 화면 한글 검사:", " ".join(cmd[2:]))
    return subprocess.run(cmd, cwd=str(root)).returncode


def cmd_scan(args) -> int:
    root = Path(args.root).resolve() if args.root else default_root()
    ctx = make_ctx("scan", args, root)
    for t in args.paths:
        tp = Path(t)
        if tp.is_dir():
            for rel in walk_tree(ctx, tp, skip_top_git=False):
                disp = f"{tp.name}/{rel}"
                check_types(ctx, rel, disp, "scan")
                data = (tp / rel).read_bytes()
                ctx.stats["files"] += 1
                scan_blob(ctx, data, disp, rel, 0)
        elif tp.is_file():
            check_types(ctx, tp.name, tp.name, "scan")
            ctx.stats["files"] += 1
            scan_blob(ctx, tp.read_bytes(), tp.name, tp.name, 0)
        else:
            ctx.notice("error", "scan.missing", f"검사할 경로가 없습니다: {t}")
    return finish(ctx, args, None, [str(p) for p in args.paths])


def cmd_artifact(args) -> int:
    root = Path(args.root).resolve() if args.root else default_root()
    ctx = make_ctx("artifact", args, root)
    manifest = None
    if args.manifest:
        try:
            manifest = json.loads(Path(args.manifest).read_bytes().decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            ctx.notice("error", "artifact.manifest", f"목록 파일을 읽지 못했습니다: {type(e).__name__}")
    forbid = tuple(x.strip().lower().lstrip(".") for x in (args.forbid_ext or "").split(",") if x.strip())
    for t in args.paths:
        tp = Path(t)
        if not tp.is_file():
            ctx.notice("error", "artifact.missing", f"산출물 파일이 없습니다: {t}")
            continue
        data = tp.read_bytes()
        ctx.stats["files"] += 1
        if not is_zip(data):
            ctx.notice("error", "artifact.not_zip", f"zip 꼴이 아니라 풀 수 없습니다: {tp.name}")
            continue
        scan_binary(ctx, tp.name, zip_skeleton(data))
        scan_archive(ctx, data, tp.name, 0, forbid, manifest)
    return finish(ctx, args, None, [str(p) for p in args.paths])


def _write_allowlist(root: Path, data: dict) -> None:
    data["files"] = sorted(data.get("files", []), key=lambda e: e.get("path", ""))
    (root / ALLOWLIST_REL).write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def cmd_rehash(args) -> int:
    root = Path(args.root).resolve() if args.root else default_root()
    ctx = Ctx("rehash", [])
    data = load_allowlist(ctx, root)
    if data is None:
        print(ctx.notices[-1]["message"])
        return 1
    if not args.all and not args.paths:
        print("--all 또는 다시 계산할 경로를 주세요")
        return 2
    want = None if args.all else {p.replace("\\", "/") for p in args.paths}
    known = {e.get("path") for e in data.get("files", [])}
    if want:
        unknown = sorted(want - known)
        if unknown:
            print("허용 목록에 없는 경로는 다시 계산하지 않습니다(allowlist-add 로 먼저 더하기): " + ", ".join(unknown))
            return 1
    changed = 0
    for e in data.get("files", []):
        if e.get("self") or (want is not None and e.get("path") not in want):
            continue
        p = root / e["path"]
        if not p.is_file():
            print(f"  파일 없음(그대로 둠): {e['path']}")
            continue
        new = sha256_file(p)
        if e.get("sha256") != new:
            print(f"  바뀜: {e['path']}  {str(e.get('sha256'))[:12]}… → {new[:12]}…")
            e["sha256"] = new
            changed += 1
    _write_allowlist(root, data)
    print(f"sha256 다시 계산: {changed}줄 바뀜")
    return 0


def cmd_add(args) -> int:
    root = Path(args.root).resolve() if args.root else default_root()
    ctx = Ctx("add", [])
    data = load_allowlist(ctx, root)
    if data is None:
        print(ctx.notices[-1]["message"])
        return 1
    rel = args.path.replace("\\", "/")
    p = (root / rel)
    try:
        p.resolve().relative_to(root)
    except ValueError:
        print("저장소 밖 경로는 더할 수 없습니다")
        return 1
    if not p.is_file() or _is_link(p):
        print(f"파일이 없거나 바로가기입니다: {rel}")
        return 1
    if any(e.get("path") == rel for e in data.get("files", [])):
        print(f"이미 목록에 있습니다: {rel} (sha256 만 바꾸려면 allowlist-rehash)")
        return 1
    entry = {"path": rel, "origin": args.origin, "treatment": args.treatment, "sha256": sha256_file(p)}
    if args.note:
        entry["note"] = args.note
    probs = _entry_problems(entry)
    if probs:
        print("더하지 않음: " + "; ".join(probs))
        return 1
    data.setdefault("files", []).append(entry)
    _write_allowlist(root, data)
    print(f"더함: {rel} ({TREATMENTS[args.treatment]})")
    return 0


def cmd_selftest(args) -> int:
    root = Path(args.root).resolve() if args.root else default_root()
    ctx = Ctx("privatelist-selftest", [])
    rules = load_private(ctx, args, root)
    entries = ctx.private_data.get("entries", []) if ctx.private.get("loaded") else []
    lit_ok = lit_fail = rx_only = 0
    failed_ids = []
    by_id = {r.rid: r for r in rules}
    for i, e in enumerate(entries):
        eid = str(e.get("id") or f"p{i + 1:03d}")
        r = by_id.get(f"private.{eid}")
        if r is None:
            continue
        if e.get("kind", "literal") == "literal":
            if r.regex.search(" " + e["pattern"] + " "):
                lit_ok += 1
            else:
                lit_fail += 1
                failed_ids.append(eid)
        else:
            rx_only += 1
    print(f"비공개 목록 자체 시험: 읽음={ctx.private.get('loaded')} 항목 {len(entries)}개 · 규칙 {len(rules)}개"
          f" · 낱말 자기 찾기 성공 {lit_ok} · 실패 {lit_fail} · 꼴(정규식) {rx_only}개는 문법만 확인")
    for n in ctx.notices:
        print(f"  [{n['severity']}] {n['code']}: {n['message']}")
    if failed_ids:
        print("  자기 찾기 실패 id: " + ", ".join(failed_ids))
    bad = lit_fail + sum(1 for n in ctx.notices if n["severity"] == "error")
    if not ctx.private.get("loaded"):
        bad += 1
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_bytes(json.dumps({
            "mode": "privatelist-selftest", "loaded": ctx.private.get("loaded"), "entries": len(entries),
            "rules": len(rules), "literal_ok": lit_ok, "literal_fail": lit_fail, "regex_compiled": rx_only,
            "failed_ids": failed_ids, "notices": ctx.notices, "result": "PASS" if bad == 0 else "FAIL",
        }, ensure_ascii=False, indent=2).encode("utf-8"))
    return 0 if bad == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root")
    common.add_argument("--private-list")
    common.add_argument("--require-private", action="store_true")
    common.add_argument("--json-out")
    common.add_argument("--max-show", type=int, default=200)
    ap = argparse.ArgumentParser(prog="release_check", description="공개 전 검사 도구")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", parents=[common])
    c.add_argument("--ui", action="store_true", help="검사를 통과하면 실제 크롬으로 화면 한글 남음도 검사")
    sub.add_parser("allowlist-verify", parents=[common])
    s = sub.add_parser("scan", parents=[common])
    s.add_argument("paths", nargs="+")
    a = sub.add_parser("artifact", parents=[common])
    a.add_argument("paths", nargs="+")
    a.add_argument("--manifest")
    a.add_argument("--forbid-ext")
    r = sub.add_parser("allowlist-rehash", parents=[common])
    r.add_argument("paths", nargs="*")
    r.add_argument("--all", action="store_true")
    d = sub.add_parser("allowlist-add", parents=[common])
    d.add_argument("path")
    d.add_argument("--origin", required=True)
    d.add_argument("--treatment", required=True, choices=sorted(TREATMENTS))
    d.add_argument("--note")
    sub.add_parser("privatelist-selftest", parents=[common])
    u = sub.add_parser("ui-hangul", parents=[common])
    u.add_argument("--langs", default="en,ja,zh")
    u.add_argument("--chrome")
    u.add_argument("--python")
    u.add_argument("--out")
    u.add_argument("--shots")
    u.add_argument("--keep-profile", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    if not sys.stdout.isatty():
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "allowlist-verify":
        return cmd_check(args, only_allowlist=True)
    if args.cmd == "scan":
        return cmd_scan(args)
    if args.cmd == "artifact":
        return cmd_artifact(args)
    if args.cmd == "allowlist-rehash":
        return cmd_rehash(args)
    if args.cmd == "allowlist-add":
        return cmd_add(args)
    if args.cmd == "privatelist-selftest":
        return cmd_selftest(args)
    if args.cmd == "ui-hangul":
        root = Path(args.root).resolve() if args.root else default_root()
        return run_ui_hangul(args, root)
    return 2


if __name__ == "__main__":
    sys.exit(main())
