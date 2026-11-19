#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""옷 꾸러미 다시 묶기(pack_make) — 김비서 공개판

이미 있는 옷 꾸러미(.hipcpet)를 공개용으로 다시 묶고 공개판 키로 서명합니다.
  - pack.json 은 정해 둔 칸만 남김(그 밖의 칸·클립 칸은 버림). 이름·id·성별·체형·버전·만든 곳은 인자로.
  - 미리보기 PNG 의 글자 칸(tEXt·zTXt·iTXt·tIME·eXIf)을 지움.
  - 노래: keep = 춤 노래를 영어 이름(music/<춤 이름>.mp3)으로 넣음, none = 노래를 뺌.
  - --drop-clip 으로 뺄 클립(쉼표로 여럿). 빠진 클립을 부르는 다른 클립 칸은 없음(클립마다 독립).
  - 파일마다 크기·sha256 을 pack.json files 에 적고, pack.json 바이트에 ed25519 서명(tools/pack_sign.js, node 필요).
  - 압축: 영상·노래·그림은 그대로 담기(stored), json 은 deflate. zip 안 이름은 영어·숫자만.
  - 끝나면 같은 이름 .manifest.json(압축 안 파일별 sha256)도 씀 → release_check.py artifact --manifest 로 대조.

사용법
  python tools/pack_make.py --src <원본.hipcpet> --out <새.hipcpet> --key <비밀키.pem> --key-id kimbiseo-pack-1
         --id kimbiseo_f --name 김비서 --gender 여성 --body 7.5등신 --version 2026.11.11.2 --maker <만든 곳>
         [--music keep|none] [--drop-clip a,b] [--note 한 줄 설명] [--voice 목소리 이름]
표준 라이브러리만 씁니다(서명만 node).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

TOP_KEYS = ("format", "id", "name", "version", "character", "body", "gender", "voice", "preview", "maker", "made", "note",
            "rating", "pc_only", "stage", "fps", "walkSpeed", "clips", "music", "files")
VOICE_RE = re.compile(r"^[a-z0-9_]{1,40}$")
CLIP_KEYS = {"w", "h", "x", "y", "frames", "dur", "file", "headX", "headY", "loops", "enter", "cycle", "stopAt",
             "seamOut", "oneVideo", "music", "rootDx", "mouth", "px", "motion"}
ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,40}$")
CLIP_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")
PNG_DROP = {b"tEXt", b"zTXt", b"iTXt", b"tIME", b"eXIf"}


def clean_png(data: bytes) -> bytes:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit("미리보기가 PNG 가 아님")
    out = [data[:8]]
    i = 8
    while i + 8 <= len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        chunk = data[i:i + 12 + n]
        if typ not in PNG_DROP:
            out.append(chunk)
        i += 12 + n
        if typ == b"IEND":
            break
    return b"".join(out)


def sign(key: Path, data: bytes, tool: Path) -> str:
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "pack.json"
        f.write_bytes(data)
        r = subprocess.run(["node", str(tool), "sign", str(key), str(f)], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("서명 실패: " + (r.stderr or "").strip()[:200])
        return r.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="옷 꾸러미 공개용 다시 묶기")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--key", required=True, help="비밀키 pem(저장소 밖)")
    ap.add_argument("--key-id", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--gender", required=True)
    ap.add_argument("--body", default="")
    ap.add_argument("--version", required=True)
    ap.add_argument("--maker", required=True)
    ap.add_argument("--music", choices=("keep", "none"), default="keep")
    ap.add_argument("--drop-clip", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--voice", default="", help="이 옷만의 목소리 이름(voice/voices.json 목록의 이름). 비우면 칸을 안 넣음 = 성별 규칙")
    ap.add_argument("--rating", choices=("all", "19"), default="", help="전체이용가 all · 성인 19(폰 플레이 판에서 숨김). 비우면 칸 없음 = 모름")
    ap.add_argument("--pc-only", action="store_true", help="PC 전용 표시(pc_only=true)")
    a = ap.parse_args()
    if not ID_RE.match(a.id):
        raise SystemExit("id 는 영어·숫자·_·- 40자까지")
    if a.voice and not VOICE_RE.match(a.voice):
        raise SystemExit("voice 는 영어 소문자·숫자·_ 40자까지(voice/voices.json 목록의 이름)")
    src, out, key = Path(a.src), Path(a.out), Path(a.key)
    tool = Path(__file__).resolve().parent / "pack_sign.js"
    if out.exists():
        raise SystemExit("만들 파일이 이미 있음(덮지 않음): " + str(out))
    drop = {x.strip() for x in a.drop_clip.split(",") if x.strip()}

    zin = zipfile.ZipFile(src)
    names = {i.filename for i in zin.infolist() if not i.is_dir()}
    old = json.loads(zin.read("pack.json").decode("utf-8"))
    if old.get("format") != "hipcpet/1":
        raise SystemExit("모르는 꾸러미 형식")

    blobs: dict[str, bytes] = {}   # zip 안 이름 → 내용
    clips = {}
    for cname, c in old["clips"].items():
        if cname in drop:
            continue
        if not CLIP_RE.match(cname) or not isinstance(c, dict):
            raise SystemExit("클립 이름이 이상함: " + cname)
        f = str(c.get("file", ""))
        if f not in names:
            raise SystemExit("클립 파일 없음: " + cname)
        newf = "clips/" + cname + os.path.splitext(f)[1].lower()
        if newf in blobs:
            raise SystemExit("같은 클립 파일 이름: " + newf)
        blobs[newf] = zin.read(f)
        nc = {k: v for k, v in c.items() if k in CLIP_KEYS}
        nc["file"] = newf
        clips[cname] = nc
    if "idle" not in clips:
        raise SystemExit("idle 클립이 빠지면 안 됨")
    unknown_clip_keys = sorted({k for c in old["clips"].values() for k in c} - CLIP_KEYS)

    prev = str(old.get("preview", ""))
    if prev not in names:
        raise SystemExit("미리보기 없음")
    blobs["preview.png"] = clean_png(zin.read(prev))

    music = []
    if a.music == "keep":
        for m in old.get("music") or []:
            dance = str(m.get("dance", ""))
            if not CLIP_RE.match(dance) or dance not in clips:
                print("  노래 건너뜀(그 춤 클립이 없음): " + dance)
                continue
            newf = "music/" + dance + ".mp3"
            blobs[newf] = zin.read(m["file"])
            music.append({"file": newf, "dance": dance})

    files = {n: {"size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for n, b in sorted(blobs.items())}
    pj = {"format": "hipcpet/1", "id": a.id, "name": a.name, "version": a.version, "character": "실사",
          "body": a.body, "gender": a.gender, "preview": "preview.png", "maker": a.maker,
          "made": _dt.datetime.now().replace(microsecond=0).isoformat()}
    if a.note:
        pj["note"] = a.note
    if a.voice:      # 원본 꾸러미의 voice 는 옮기지 않음(이 저장소 목록에 없는 이름일 수 있음) — 인자로 준 것만
        pj["voice"] = a.voice
    if a.rating:     # 전체이용가 표시 — 폰 플레이 판이 이 칸을 보고 성인 옷을 숨긴다(없으면 숨김 = 안전한 쪽)
        pj["rating"] = a.rating
    if a.pc_only:
        pj["pc_only"] = True
    for k in ("stage", "fps", "walkSpeed"):
        if k in old:
            pj[k] = old[k]
    pj["clips"] = clips
    pj["music"] = music
    pj["files"] = files
    pj_bytes = (json.dumps(pj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    sig = sign(key, pj_bytes, tool)
    sig_bytes = (json.dumps({"alg": "ed25519", "key": a.key_id, "sig": sig}) + "\n").encode("utf-8")

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".만드는중")
    stamp = (2026, 1, 1, 0, 0, 0)   # zip 안 시각은 고정(만든 PC 의 시각대를 남기지 않음)
    with zipfile.ZipFile(tmp, "w") as zo:
        for n, b in [("pack.json", pj_bytes), ("signature.json", sig_bytes)] + sorted(blobs.items()):
            zi = zipfile.ZipInfo(n, date_time=stamp)
            zi.compress_type = zipfile.ZIP_DEFLATED if n.endswith(".json") else zipfile.ZIP_STORED
            zi.external_attr = 0o644 << 16
            zo.writestr(zi, b)
    os.replace(tmp, out)
    man = {"files": {"pack.json": hashlib.sha256(pj_bytes).hexdigest(), "signature.json": hashlib.sha256(sig_bytes).hexdigest(),
                     **{n: v["sha256"] for n, v in files.items()}}, "allow_extra": False}
    man_path = out.with_name(out.stem + ".manifest.json")
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    info = {"file": out.name, "id": a.id, "name": a.name, "version": a.version, "size": out.stat().st_size, "sha256": sha,
            "clips": len(clips), "music": len(music), "dropped_clips": sorted(drop & set(old["clips"])),
            "dropped_clip_keys": unknown_clip_keys, "key": a.key_id}
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
