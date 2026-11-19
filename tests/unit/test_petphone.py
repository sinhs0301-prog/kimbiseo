# 폰 펫 단위 시험 — PC 펫 옷 폴더에서 대화 화면용 클립(대기·말하기·인사)만 골라 sha256·크기와 함께 내주는지,
#   폰에서 고른 옷·없는 옷·위험한 경로·파일이 바뀌었을 때, 관문의 /phone/api/pet·/pet/clip(토큰 필요)까지.
#   소리·두뇌·인터넷 없이 돈다.   python -m tests.unit.test_petphone
import hashlib
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import config as C            # noqa: E402
from app.core import petphone as PP        # noqa: E402
from app.core import phone as PH            # noqa: E402


def fresh_cfg(user=None):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "settings.json")
    u = {"경로": {"자료": os.path.join(d, "data"), "모델": os.path.join(d, "models"), "캐시": os.path.join(d, "cache"),
                 "로그": os.path.join(d, "logs")}}
    u.update(user or {})
    with open(p, "w", encoding="utf-8") as f:
        json.dump(u, f, ensure_ascii=False)
    cfg = C.load(p, warn=lambda m: None)
    cfg["_settings_path"] = p
    return cfg


def make_outfit(cfg, oid, clips=("idle", "talk", "hello", "wave"), name=None, body=b"video", rating=None, pc_only=None):
    """<자료>\pet\옷\<oid> 에 pack.json 과 가짜 클립 파일을 만든다. → 옷 폴더"""
    data = C.path(cfg, "자료")
    d = os.path.join(data, "pet", "옷", oid)
    os.makedirs(os.path.join(d, "clips"), exist_ok=True)
    meta = {}
    for i, n in enumerate(clips):
        rel = f"clips/{n}.webm"
        with open(os.path.join(d, "clips", n + ".webm"), "wb") as f:
            f.write(body + n.encode("ascii"))
        meta[n] = {"file": rel, "w": 541.54, "h": 960.0, "x": 0, "y": 0, "frames": 123, "dur": 5.12}
    pj = {"format": "hipcpet/1", "id": oid, "name": name or oid, "version": "1", "character": "실사",
          "gender": "여", "clips": meta}
    if rating is not None:
        pj["rating"] = rating
    if pc_only is not None:
        pj["pc_only"] = pc_only
    with open(os.path.join(d, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(pj, f, ensure_ascii=False)
    return d


def set_skin(cfg, skin):
    os.makedirs(os.path.join(C.path(cfg, "자료"), "pet"), exist_ok=True)
    with open(os.path.join(C.path(cfg, "자료"), "pet", "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"skin": skin}, f)


def test_manifest_and_clip():
    cfg = fresh_cfg()
    d = make_outfit(cfg, "kimbiseo_f", name="김비서(여)")
    set_skin(cfg, "kimbiseo_f")
    p = PP.PetPhone(cfg, ffmpeg="")          # 작은 판 없이(가짜 webm 은 인코딩 못 함)
    m = p.manifest()
    assert m["옷"]["id"] == "kimbiseo_f" and m["지금옷"] == "kimbiseo_f" and m["고른옷"] == "kimbiseo_f"
    names = [x["이름"] for x in m["동작"]]
    assert names == ["idle", "talk", "hello", "wave"], names
    idle = next(x for x in m["동작"] if x["이름"] == "idle")
    raw = open(os.path.join(d, "clips", "idle.webm"), "rb").read()
    assert idle["sha256"] == hashlib.sha256(raw).hexdigest()
    assert idle["바이트"] == len(raw) and idle["파일"] == "idle.webm" and idle["작은판"] is False
    assert idle["가로"] == 542 and idle["세로"] == 960 and idle["초"] == 5.12
    r = p.clip("", "idle")
    assert r and r[0].endswith("idle.webm") and r[1] == "video/webm" and r[2] == idle["sha256"]
    assert p.clip("", "dance") is None       # 화면이 쓰는 네 동작만
    assert p.clip("", "talk")[0].endswith("talk.webm")


def test_selected_outfit_and_fallback():
    cfg = fresh_cfg()
    make_outfit(cfg, "kimbiseo_f", name="여")
    make_outfit(cfg, "kimbiseo_m", name="남")
    set_skin(cfg, "kimbiseo_f")
    p = PP.PetPhone(cfg, ffmpeg="")
    assert p.manifest("kimbiseo_m")["옷"]["id"] == "kimbiseo_m"
    assert [o["id"] for o in p.manifest("kimbiseo_m")["옷목록"]] == ["kimbiseo_f", "kimbiseo_m"]
    assert p.manifest("없는옷")["옷"]["id"] == "kimbiseo_f"       # 모르는 값은 PC 옷으로
    assert p.manifest("../pet")["옷"]["id"] == "kimbiseo_f"       # 경로 꼴도 무시
    assert p.clip("kimbiseo_m", "talk")[0].startswith(os.path.join(C.path(cfg, "자료"), "pet", "옷", "kimbiseo_m"))


def test_missing_motions_fall_back_to_idle():
    cfg = fresh_cfg()
    make_outfit(cfg, "only_idle", clips=("idle",))
    set_skin(cfg, "only_idle")
    p = PP.PetPhone(cfg, ffmpeg="")
    m = p.manifest()
    assert [x["이름"] for x in m["동작"]] == ["idle", "talk", "hello", "wave"]
    shas = {x["sha256"] for x in m["동작"]}
    assert len(shas) == 1                     # 넷 다 같은 파일 → 폰은 한 번만 받는다


def test_bad_relative_path_is_skipped():
    cfg = fresh_cfg()
    d = make_outfit(cfg, "kimbiseo_f", clips=("idle",))
    with open(os.path.join(d, "pack.json"), encoding="utf-8") as f:
        pj = json.load(f)
    pj["clips"]["talk"] = {"file": "../evil.webm", "w": 1, "h": 1, "x": 0, "y": 0, "frames": 1, "dur": 1}
    with open(os.path.join(d, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(pj, f, ensure_ascii=False)
    p = PP.PetPhone(cfg, ffmpeg="")
    m = p.manifest()
    # 위험한 talk 파일은 버리고 idle 로 대신한다
    talk = next(x for x in m["동작"] if x["이름"] == "talk")
    idle = next(x for x in m["동작"] if x["이름"] == "idle")
    assert talk["sha256"] == idle["sha256"]
    assert not any("evil" in x["파일"] for x in m["동작"])


def test_sha_changes_when_file_changes():
    cfg = fresh_cfg()
    d = make_outfit(cfg, "kimbiseo_f")
    p = PP.PetPhone(cfg, ffmpeg="")
    a = next(x for x in p.manifest()["동작"] if x["이름"] == "idle")["sha256"]
    with open(os.path.join(d, "clips", "idle.webm"), "ab") as f:
        f.write(b"more")
    b = next(x for x in p.manifest()["동작"] if x["이름"] == "idle")["sha256"]
    assert a != b


def test_no_pet_installed():
    cfg = fresh_cfg()
    p = PP.PetPhone(cfg, ffmpeg="")
    m = p.manifest()
    assert m["옷"] is None and m["동작"] == [] and p.clip("", "idle") is None


def test_rating_all_ages_hides_adult_and_unknown():
    cfg = fresh_cfg()
    make_outfit(cfg, "kimbiseo_f", name="여")                     # 표시 없음 → id 로 전체이용가
    make_outfit(cfg, "kimbiseo_bikini", name="비키니")            # 표시 없음(옛 꾸러미) → id 로 성인
    make_outfit(cfg, "kimbiseo_mix", name="혼혈", rating="all")
    make_outfit(cfg, "my_custom", name="내 옷")                    # 표시 없음·모르는 id → 모름(숨김)
    set_skin(cfg, "kimbiseo_bikini")
    p = PP.PetPhone(cfg, ffmpeg="")
    ratings = {o["id"]: o["rating"] for o in p.outfits()}
    assert ratings == {"kimbiseo_f": "all", "kimbiseo_bikini": "19", "kimbiseo_mix": "all", "my_custom": ""}, ratings
    full = p.manifest()
    assert [o["id"] for o in full["옷목록"]] == ["kimbiseo_bikini", "kimbiseo_f", "kimbiseo_mix", "my_custom"]
    assert full["옷"]["id"] == "kimbiseo_bikini"
    safe = p.manifest(all_ages_only=True)
    assert [o["id"] for o in safe["옷목록"]] == ["kimbiseo_f", "kimbiseo_mix"], safe["옷목록"]
    assert safe["옷"]["id"] == "kimbiseo_f" and safe["옷"]["rating"] == "all", "성인 옷을 입고 있으면 안전한 옷으로"
    assert all(o["rating"] == "all" for o in safe["옷목록"])
    assert p.manifest("kimbiseo_bikini", all_ages_only=True)["옷"]["id"] == "kimbiseo_f", "고른 옷이 성인이면 대신"
    assert p.manifest("kimbiseo_mix", all_ages_only=True)["옷"]["id"] == "kimbiseo_mix"
    assert p.clip("kimbiseo_bikini", "idle", all_ages_only=True)[0].startswith(
        os.path.join(C.path(cfg, "자료"), "pet", "옷", "kimbiseo_f"))
    only_adult = fresh_cfg()
    make_outfit(only_adult, "kimbiseo_bikini")
    set_skin(only_adult, "kimbiseo_bikini")
    p2 = PP.PetPhone(only_adult, ffmpeg="")
    assert p2.manifest(all_ages_only=True)["옷"] is None and p2.clip("", "idle", all_ages_only=True) is None


def test_gateway_pet_paths_need_token():
    from starlette.testclient import TestClient

    cfg = fresh_cfg({"폰": {"켜기": True}})
    d = make_outfit(cfg, "kimbiseo_f")
    auth = PH.PhoneAuth(os.path.join(tempfile.mkdtemp(), "phones.json"))
    code, _ = auth.new_code()
    reg = auth.pair(code, "시험 폰", "192.168.1.5")
    tok = reg["토큰"]
    pet = PP.PetPhone(cfg, ffmpeg="")
    old = PH.allowed_ip
    PH.allowed_ip = lambda ip, ts=False: True       # 시험 손님(testclient)도 사설 주소처럼
    try:
        app = PH.make_gateway_app(cfg, auth, lambda *a: None, lambda did: {}, pet=pet)
        with TestClient(app) as cl:
            r = cl.get("/phone/api/pet", headers={"X-Phone-Token": tok})
            assert r.status_code == 200, r.text
            j = r.json()
            assert j["ok"] and j["옷"]["id"] == "kimbiseo_f" and len(j["동작"]) == 4
            assert j["옷"]["rating"] == "all" and j["옷목록"][0]["rating"] == "all"
            j = cl.get("/phone/api/pet", params={"all": "1"}, headers={"X-Phone-Token": tok}).json()
            assert j["ok"] and j["옷"]["id"] == "kimbiseo_f", "전체이용가 요청도 같은 옷"
            idle = next(x for x in j["동작"] if x["이름"] == "idle")
            r = cl.get("/phone/api/pet/clip", params={"outfit": "kimbiseo_f", "motion": "idle"},
                       headers={"X-Phone-Token": tok})
            assert r.status_code == 200 and r.content == open(os.path.join(d, "clips", "idle.webm"), "rb").read()
            assert r.headers["content-type"].startswith("video/webm")
            assert r.headers["x-content-sha256"] == idle["sha256"]
            assert r.headers["cache-control"] == "no-store"
            r = cl.get("/phone/api/pet/clip", params={"motion": "../idle"}, headers={"X-Phone-Token": tok})
            assert r.status_code == 404
            r = cl.get("/phone/api/pet", headers={"X-Phone-Token": "bad"})
            assert r.status_code == 401
            r = cl.get("/api/settings")
            assert r.status_code == 404             # 본체 길은 폰 관문에 없음
    finally:
        PH.allowed_ip = old


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    fails = 0
    for k, f in list(globals().items()):
        if k.startswith("test_") and callable(f):
            try:
                f()
                print("됨  ", k)
            except Exception as ex:  # noqa: BLE001
                fails += 1
                print("실패", k, "—", ex)
    print("통과" if not fails else f"{fails}개 실패")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()