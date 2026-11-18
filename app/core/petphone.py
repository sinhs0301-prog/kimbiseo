# 폰 펫 — PC 펫이 지금 입은 옷(또는 폰에서 따로 고른 옷)의 클립 가운데 대화 화면에 필요한 몇 개만 폰에 건넨다.
#   폰은 같은 와이파이·테일스케일 안에서, 연결한 기기 토큰으로만 받는다(입구 = core/phone.py 관문).
#   보내는 것: 대기(idle)·말하기(talk)·인사(hello/wave) — 꾸러미 전체(337개, 150~170MB)가 아니라 4개(약 4MB)만.
#   작은 판: ffmpeg 가 있으면 가로 360 으로 줄여 <자료>\폰펫\작은판\ 에 한 번 만들어 두고 그것을 보낸다(없으면 원본 그대로).
#   파일마다 sha256 을 함께 알려 주어 폰이 받은 파일을 확인하고, sha 가 바뀌면 다시 받는다.
#   옷 폴더 = <자료>\pet\옷\<id> (실행기가 펫에 --profile=<자료>\pet 로 넘기는 그 폴더).
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading

from loguru import logger

from . import config as C

ID_RE = re.compile(r"^[0-9A-Za-z가-힣_-]{1,40}$")
MOTIONS = ("idle", "talk", "hello", "wave")
# 화면이 쓰는 이름 → 꾸러미 안 클립 이름 후보(없으면 다음 것, 그래도 없으면 idle)
CANDIDATES = {
    "idle": ("idle",),
    "talk": ("talk", "talk_smile", "idle"),
    "hello": ("hello", "wave", "idle"),
    "wave": ("wave", "hello", "idle"),
}
MEDIA = {".webm": "video/webm", ".mp4": "video/mp4"}
SMALL_W = 360


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _inside(base, rel):
    """꾸러미 안 상대 경로 → base 아래 진짜 파일 경로. ../·절대 경로·역슬래시·드라이브는 거부."""
    s = str(rel or "")
    if not s or len(s) > 200 or s.startswith(("/", "\\")) or "\\" in s or ":" in s:
        return None
    r = os.path.normpath(s)
    if r == ".." or r.startswith(".." + os.sep) or os.path.isabs(r):
        return None
    p = os.path.abspath(os.path.join(base, r))
    return p if p.startswith(os.path.abspath(base) + os.sep) else None


class PetPhone:
    """폰에 보여 줄 펫 정보·클립. 여러 스레드(폰 요청)에서 불러도 되게 잠금을 쓴다."""

    def __init__(self, cfg, ffmpeg=None):
        self.cfg = cfg
        self._ffmpeg = ffmpeg              # None = PATH 에서 찾기 · "" = 작은 판 안 만듦(시험)
        self._lock = threading.Lock()
        self._shas = {}                     # (경로, 크기, mtime) → sha256

    # ---------------------------------------------------------------- 길
    def profile(self):
        return os.path.join(C.path(self.cfg, "자료"), "pet")

    def outfits_dir(self):
        return os.path.join(self.profile(), "옷")

    def small_dir(self):
        return os.path.join(C.path(self.cfg, "자료"), "폰펫", "작은판")

    # ---------------------------------------------------------------- 옷 읽기
    def outfits(self):
        """설치된 옷 목록 — [{id, name, 성별, 판, 폴더, clips}]. 읽을 수 없는 폴더는 건너뛴다."""
        d = self.outfits_dir()
        out = []
        try:
            names = os.listdir(d)
        except OSError:
            return out
        for name in names:
            if not ID_RE.match(name) or not os.path.isdir(os.path.join(d, name)):
                continue
            p = os.path.join(d, name)
            try:
                with open(os.path.join(p, "pack.json"), encoding="utf-8") as f:
                    pj = json.load(f)
            except (OSError, ValueError):
                continue
            clips = pj.get("clips") if isinstance(pj, dict) else None
            if not isinstance(clips, dict) or not isinstance(clips.get("idle"), dict) or pj.get("id") != name:
                continue
            out.append({"id": name, "name": str(pj.get("name") or name)[:60], "성별": str(pj.get("gender") or "")[:10],
                        "판": str(pj.get("version") or "")[:40], "폴더": p, "clips": clips})
        out.sort(key=lambda o: o["id"])
        return out

    def current_id(self, outfits=None):
        """PC 펫이 지금 입은 옷 id. 펫이 꺼져 있으면 펫 프로필 설정(settings.json)의 skin, 그것도 없으면 PC 설정의 옷."""
        outfits = outfits if outfits is not None else self.outfits()
        ids = {o["id"] for o in outfits}
        try:
            from ..pet_link import face as F
            v = F.pet_outfit(self.cfg, max_age=0.5)
            if isinstance(v, dict) and str(v.get("id") or "") in ids:
                return str(v["id"])
        except Exception as ex:  # noqa: BLE001 — 펫이 꺼져 있으면 HTTP 실패가 정상
            logger.debug(f"펫 옷 물어보기 실패: {ex.__class__.__name__}")
        try:
            with open(os.path.join(self.profile(), "settings.json"), encoding="utf-8") as f:
                skin = str((json.load(f) or {}).get("skin") or "")
            if skin in ids:
                return skin
        except (OSError, ValueError, AttributeError):
            pass
        want = str(((self.cfg.get("펫") or {}).get("옷")) or "")
        if want in ids:
            return want
        return outfits[0]["id"] if outfits else ""

    def _pick(self, outfits, selected):
        ids = {o["id"]: o for o in outfits}
        sel = str(selected or "")
        if ID_RE.match(sel) and sel in ids:
            return ids[sel]
        cur = self.current_id(outfits)
        return ids.get(cur) or (outfits[0] if outfits else None)

    # ---------------------------------------------------------------- 클립 → 폰용 파일
    def _sha(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return ""
        key = (path, st.st_size, st.st_mtime_ns)
        with self._lock:
            hit = self._shas.get(key)
        if hit:
            return hit
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for b in iter(lambda: f.read(1 << 20), b""):
                    h.update(b)
        except OSError:
            return ""
        val = h.hexdigest()
        with self._lock:
            if len(self._shas) > 500:
                self._shas.clear()
            self._shas[key] = val
        return val

    def _ffmpeg_path(self):
        if self._ffmpeg is not None:
            return self._ffmpeg
        return os.environ.get("KIMBISEO_FFMPEG") or shutil.which("ffmpeg") or ""

    def _small(self, src, outfit_id, motion, sha, meta_w):
        """가로 360 짜리 작은 판(있으면). (경로, 작은판인가). ffmpeg 가 없거나 실패하면 원본."""
        if meta_w and meta_w <= SMALL_W:
            return src, False
        ff = self._ffmpeg_path()
        if not ff:
            return src, False
        d = self.small_dir()
        dst = os.path.join(d, f"{outfit_id}_{motion}_{sha[:16]}.webm")
        with self._lock:
            try:
                if os.path.getsize(dst) > 1000:
                    return dst, True
            except OSError:
                pass
            tmp = dst + f".{os.getpid()}.part.webm"
            try:
                os.makedirs(d, exist_ok=True)
                cmd = [ff, "-v", "error", "-y", "-i", src, "-vf", f"scale={SMALL_W}:-2",
                       "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "36", "-an",
                       "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1", "-f", "webm", tmp]
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                subprocess.run(cmd, timeout=60, check=True, creationflags=flags,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                if os.path.getsize(tmp) > 1000:
                    os.replace(tmp, dst)
                    return dst, True
                os.remove(tmp)
            except (OSError, subprocess.SubprocessError, ValueError) as ex:
                err = getattr(ex, "stderr", b"") or b""
                logger.info(f"폰 펫 작은 판을 만들지 못해 원본을 보냅니다({motion}): {ex.__class__.__name__} "
                            f"{err[:200].decode('utf-8', 'replace')}")
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return src, False

    def _clip(self, outfit, motion):
        """(폰에 보낼 파일 경로, 종류, sha256, 작은판인가) 또는 None."""
        clips = outfit["clips"]
        found = None
        for name in CANDIDATES[motion]:
            c = clips.get(name)
            if not isinstance(c, dict):
                continue
            src = _inside(outfit["폴더"], c.get("file"))
            if not src or not os.path.isfile(src):
                continue
            ext = os.path.splitext(src)[1].lower()
            if ext not in MEDIA:
                continue
            sha = self._sha(src)
            if not sha:
                continue
            found = (name, c, src, ext, sha)
            break
        if found is None:
            return None
        name, c, src, ext, sha = found
        path, small = self._small(src, outfit["id"], motion, sha, _num(c.get("w")))
        if small:
            sha = self._sha(path)
            return path, MEDIA[".webm"], sha, True, c
        return path, MEDIA[ext], sha, False, c

    # ---------------------------------------------------------------- 폰에 줄 것
    def manifest(self, selected=""):
        """폰이 받을 목록. 옷이 없어도 ok=true(옷=null)로 답해 폰이 '아직 없음'을 알게 한다."""
        outfits = self.outfits()
        cur = self.current_id(outfits)
        outfit = self._pick(outfits, selected)
        lst = [{"id": o["id"], "name": o["name"], "성별": o["성별"], "판": o["판"]} for o in outfits]
        if outfit is None:
            return {"옷": None, "고른옷": "", "지금옷": cur, "옷목록": lst, "동작": []}
        motions = []
        seen = {}
        for m in MOTIONS:
            r = self._clip(outfit, m)
            if r is None:
                continue
            path, media, sha, small, c = r
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            ext = os.path.splitext(path)[1].lower().lstrip(".")
            w = _num(c.get("w")) or 0.0
            h = _num(c.get("h")) or 0.0
            if small and w > 0:
                h = h * SMALL_W / w
                w = float(SMALL_W)
            item = {"이름": m, "파일": f"{m}.{ext}", "sha256": sha, "바이트": size,
                    "가로": int(round(w)), "세로": int(round(h)), "초": round(_num(c.get("dur")), 2),
                    "작은판": bool(small)}
            # 같은 파일을 여러 이름이 가리키면 폰이 한 번만 받게 sha 로 알려 준다(항목은 그대로).
            seen.setdefault(sha, item)
            motions.append(item)
        logger.debug(f"폰 펫 목록: {outfit['id']} · {len(motions)}개 · "
                     f"{sum(x['바이트'] for x in seen.values()) / 1e6:.1f}MB")
        return {"옷": {"id": outfit["id"], "name": outfit["name"], "성별": outfit["성별"], "판": outfit["판"]},
                "고른옷": outfit["id"], "지금옷": cur, "옷목록": lst, "동작": motions}

    def clip(self, selected, motion):
        """(파일 경로, 미디어 종류, sha256) 또는 None. motion 은 idle·talk·hello·wave 만."""
        m = str(motion or "")
        if m not in MOTIONS:
            return None
        outfit = self._pick(self.outfits(), selected)
        if outfit is None:
            return None
        r = self._clip(outfit, m)
        if r is None:
            return None
        path, media, sha, _small, _c = r
        return path, media, sha