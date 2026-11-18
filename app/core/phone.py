# 폰 연결(선택, 기본 꺼짐) — 내 폰의 '김비서' 앱이 이 PC 김비서와 말·글로 대화한다.
#   켜는 곳: 설정 → 폰 연결 → '폰 연결 켜기'(설정 폰.켜기). 꺼져 있으면 아무 포트도 열지 않는다.
#   듣는 곳: 0.0.0.0:포트.폰(기본 8874) — 그러나 집 안 네트워크(사설 주소 10.x·172.16~31.x·192.168.x, IPv6 fc00::/7·fe80::/10)와
#            이 PC 자신(127.0.0.1)에서 온 연결만 받는다. 테일스케일(100.64.0.0/10·fd7a:115c:a1e0::/48)은 '테일스케일도 허용'을 켰을 때만.
#   암호화: 이 PC 가 처음 켤 때 만든 자체 인증서(EC P-256)로 HTTPS·WSS. 폰은 짝지을 때 QR 에 든 인증서 지문(sha256)을 저장해 두고
#           그 지문이 아니면 연결하지 않는다(가짜 PC 막기). 개인 열쇠 파일은 암호를 걸어 두고, 그 암호는 윈도우 계정 암호화(keystore).
#   짝짓기: PC 화면에서 '짝 코드 만들기' → 8자리 숫자(10분, 한 번만, 마지막에 만든 것 하나만) + QR. 폰이 코드를 넣으면 기기 토큰(256비트)을
#           받고, PC 에는 토큰의 해시만 저장(자료 폴더 secrets\phones.json). 등록 기기 목록에서 언제든 지울 수 있음.
#   막기(운영판과 같은 규칙): 틀린 코드·토큰은 IP 별로 세고 5번째부터 30초×2^(n-5)(최대 1시간) 그 IP 만 막음. 맞는 토큰은 잠금과 상관없이 통과.
#           코드 틀림이 전체 30번/15분이면 짝짓기만 15분 막음. 잠긴 동안의 요청은 실패로 안 셈.
#   소리: 폰→PC 16kHz 16비트 PCM(바이너리), PC→폰 24kHz 16비트 PCM(바이너리), 나머지는 JSON 글(자막·상태·통역·확인 단추·폰 동작).
import asyncio
import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse

from loguru import logger

from . import config as C

CODE_TTL = 600
PRIVATE_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
                                                   "fc00::/7", "fe80::/10")]
LOOP_NETS = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "::1/128")]
TAILSCALE_NETS = [ipaddress.ip_network(n) for n in ("100.64.0.0/10", "fd7a:115c:a1e0::/48")]
TOKEN_HEADER = "x-phone-token"


def conf(cfg):
    return dict(cfg.get("폰") or {})


def enabled(cfg):
    return bool(conf(cfg).get("켜기"))


def port(cfg):
    return int((cfg.get("포트") or {}).get("폰") or 8874)


def secret_dir(cfg):
    return os.path.join(C.path(cfg, "자료"), "secrets")


def allowed_ip(ip, tailscale=False):
    """집 안 네트워크·이 PC·(켰으면) 테일스케일만 True."""
    try:
        a = ipaddress.ip_address(str(ip or "").split("%")[0])
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    if any(a in n for n in TAILSCALE_NETS):      # 테일스케일 IPv6(fd7a:…)는 사설 범위(fc00::/7) 안이라 먼저 가림
        return bool(tailscale)
    return any(a in n for n in LOOP_NETS + PRIVATE_NETS)


def lan_addresses(cfg=None):
    """폰이 찾아올 이 PC 주소들(QR 에 넣음) — 192.168 → 10 → 172 → (켰으면) 테일스케일 순."""
    ts = bool(conf(cfg or {}).get("테일스케일_허용"))
    seen = []
    cands = []
    try:
        cands += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    try:   # 기본 경로 주소(실제로 패킷을 보내지는 않음)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))
        cands.insert(0, s.getsockname()[0])
        s.close()
    except OSError:
        pass
    for ip in cands:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.is_loopback or ip in seen:
            continue
        if any(a in n for n in PRIVATE_NETS[:3]) or (ts and any(a in n for n in TAILSCALE_NETS)):
            seen.append(ip)

    def rank(ip):
        return (0 if ip.startswith("192.168.") else 1 if ip.startswith("10.") else 2 if ip.startswith("172.") else 3)
    return sorted(seen, key=rank)[:4]


# ---------------------------------------------------------------- 인증서(자체 서명)
def tls_files(cfg):
    """(인증서 경로, 열쇠 경로, 열쇠 암호, 지문 hex) — 없으면 만든다."""
    from . import keystore
    d = os.path.join(secret_dir(cfg), "phone_tls")
    cert, key = os.path.join(d, "cert.pem"), os.path.join(d, "key.pem")
    pw = keystore.get("phone_tls", cfg)
    if not (os.path.isfile(cert) and os.path.isfile(key) and pw):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        os.makedirs(d, exist_ok=True)
        pw = secrets.token_urlsafe(24)
        k = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "KimBiseo PC")])
        now = datetime.datetime.now(datetime.timezone.utc)
        c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
             .not_valid_after(now + datetime.timedelta(days=3650))
             .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
             .sign(k, hashes.SHA256()))
        keystore.put("phone_tls", pw, cfg)
        with open(key, "wb") as f:
            f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.BestAvailableEncryption(pw.encode("utf-8"))))
        with open(cert, "wb") as f:
            f.write(c.public_bytes(serialization.Encoding.PEM))
        logger.info("폰 연결용 인증서를 새로 만들었어요")
    return cert, key, pw, fingerprint(cert)


def fingerprint(cert_path):
    import ssl
    with open(cert_path, encoding="ascii") as f:
        der = ssl.PEM_cert_to_DER_cert(f.read())
    return hashlib.sha256(der).hexdigest().upper()


def fp_words(fp):
    """사람이 눈으로 맞춰 볼 짧은 꼴(앞 16자리, 4자씩)."""
    return " ".join(fp[i:i + 4] for i in range(0, 16, 4))


# ---------------------------------------------------------------- 기기 등록·인증(운영판 폰인증 규칙)
class PhoneAuth:
    WINDOW = 900
    IP_LIMIT = 5
    BASE_LOCK = 30.0
    MAX_LOCK = 3600.0
    PAIR_GLOBAL = 30
    GOOD_IP_S = 86400
    GOOD_IP_WEIGHT = 1 / 3

    def __init__(self, store, log_path=None, now=time.time):
        self.store = store
        self.log_path = log_path
        self.now = now
        self.lock = threading.Lock()
        self.code = None          # (해시, 만료) — 마지막에 만든 것 하나만
        self.ipst = {}
        self.good_ips = {}
        self.pair_fails = []
        self.lock_noted = {}
        self.devices = self._load()

    def _load(self):
        try:
            with open(self.store, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        os.makedirs(os.path.dirname(self.store), exist_ok=True)
        tmp = self.store + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.devices, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.store)

    @staticmethod
    def _h(s):
        return hashlib.sha256(("kimbiseo-phone:" + str(s)).encode("utf-8")).hexdigest()

    def record(self, kind, ip, **kw):
        if not self.log_path:
            return
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"시각": time.strftime("%Y-%m-%d %H:%M:%S"), "일": kind, "ip": ip, **kw}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def lock_left(self, ip):
        with self.lock:
            st = self.ipst.get(ip)
            return max(0.0, st["until"] - self.now()) if st else 0.0

    def blocked(self, ip):
        return self.lock_left(ip) > 0

    def pair_blocked(self):
        now = self.now()
        with self.lock:
            self.pair_fails = [t for t in self.pair_fails if now - t < self.WINDOW]
            return len(self.pair_fails) >= self.PAIR_GLOBAL

    def _locked_hit(self, ip, kind):
        now = self.now()
        with self.lock:
            noted = now - self.lock_noted.get(ip, 0) >= 60
            if noted:
                self.lock_noted[ip] = now
        if noted:
            self.record(kind, ip, 결과="거절(잠김)", 남은초=round(self.lock_left(ip)))

    def _success(self, ip):
        with self.lock:
            self.good_ips[ip] = self.now()
            self.ipst.pop(ip, None)

    def _fail(self, ip, kind, pair=False):
        now = self.now()
        with self.lock:
            st = self.ipst.get(ip)
            if not st or now - max(st["last"], st["until"]) > self.WINDOW:
                st = self.ipst[ip] = {"n": 0.0, "last": 0.0, "until": 0.0}
            good = now - self.good_ips.get(ip, -1e18) < self.GOOD_IP_S
            st["n"] += self.GOOD_IP_WEIGHT if good else 1.0
            st["last"] = now
            lock_s = 0.0
            if st["n"] >= self.IP_LIMIT - 1e-9:
                lock_s = min(self.MAX_LOCK, self.BASE_LOCK * 2 ** (int(st["n"] + 1e-9) - self.IP_LIMIT))
                st["until"] = now + lock_s
            if pair:
                self.pair_fails.append(now)
            if len(self.ipst) > 5000:
                self.ipst = {k: v for k, v in self.ipst.items() if now - max(v["last"], v["until"]) <= self.WINDOW}
        self.record(kind, ip, 결과="거절", **({"잠금초": round(lock_s)} if lock_s else {}))
        logger.info(f"폰 접속 거절({kind}) {ip}" + (f" → 이 주소 {lock_s:.0f}초 잠금" if lock_s else ""))

    def new_code(self):
        code = "".join(secrets.choice("0123456789") for _ in range(8))
        with self.lock:
            self.code = (self._h(code), self.now() + CODE_TTL)
        self.record("짝 코드 만듦", "-")
        return code, CODE_TTL

    def code_left(self):
        with self.lock:
            return max(0, int(self.code[1] - self.now())) if self.code else 0

    def pair(self, code, name, ip):
        return self.pair_why(code, name, ip)[0]

    def pair_why(self, code, name, ip):
        """(등록 결과 또는 None, 까닭). 까닭 = 잠김(이 주소)·잠김_전체·없음(만든 코드 없음/이미 씀)·만료·틀림 — 폰 앱이 알맞은 문구를 고르게.
        틀린 코드는 코드를 없애지 않음(맞는 코드가 오면 그때 한 번 씀). 까닭은 코드가 있는지만 알려 줄 뿐 코드 값은 새지 않음."""
        if self.blocked(ip):
            self._locked_hit(ip, "짝짓기(이 주소 잠김)")
            return None, "잠김"
        if self.pair_blocked():
            self._locked_hit(ip, "짝짓기(전체 잠김)")
            return None, "잠김_전체"
        k = self._h(str(code or "").strip())
        with self.lock:
            cur = self.code
            match = cur is not None and hmac.compare_digest(k, cur[0])
            fresh = cur is not None and cur[1] >= self.now()
            ok = match and fresh
            if ok:
                self.code = None     # 한 번만
        if not ok:
            why = "없음" if cur is None else ("만료" if not fresh else "틀림")
            self._fail(ip, {"없음": "짝 코드 없음", "만료": "짝 코드 만료", "틀림": "짝 코드 틀림"}[why], pair=True)
            return None, why
        self._success(ip)
        token = secrets.token_urlsafe(32)
        did = secrets.token_hex(4)
        name = "".join(ch for ch in str(name or "폰") if ch.isprintable())[:30] or "폰"
        with self.lock:
            self.devices[did] = {"이름": name, "토큰해시": self._h(token), "등록": time.strftime("%Y-%m-%d %H:%M"), "마지막": None}
            self._save()
        self.record("기기 등록", ip, 기기=did)
        logger.info(f"폰 기기 등록: {did}")
        return {"기기": did, "토큰": token, "이름": name}, ""

    def check(self, token, ip, what="api"):
        h = self._h(str(token or ""))
        for did, d in list(self.devices.items()):
            if hmac.compare_digest(h, d.get("토큰해시", "")):
                d["마지막"] = time.strftime("%Y-%m-%d %H:%M")
                self._success(ip)
                return did
        if self.blocked(ip):
            self._locked_hit(ip, f"{what}(잠김)")
            return None
        self._fail(ip, f"{what} 토큰 틀림")
        return None

    def touch_save(self):
        with self.lock:
            try:
                self._save()
            except OSError:
                pass

    def remove(self, did=None):
        with self.lock:
            if did is None:
                n = len(self.devices)
                self.devices = {}
            else:
                n = 1 if self.devices.pop(str(did), None) else 0
            self._save()
        self.record("기기 지움", "-", 기기=did or "전부", 개수=n)
        return n

    def list(self):
        return [{"기기": k, "이름": v.get("이름"), "등록": v.get("등록"), "마지막": v.get("마지막")} for k, v in self.devices.items()]


def pair_url(addrs, port_, code, fp, pc_name=""):
    """QR 에 넣는 글: kimbiseo://pair?v=1&h=<주소들>&p=<포트>&c=<코드>&f=<인증서 지문>&n=<PC 이름>"""
    q = {"v": "1", "h": ",".join(addrs), "p": str(port_), "c": code, "f": fp}
    if pc_name:
        q["n"] = pc_name[:30]
    return "kimbiseo://pair?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


def qr_svg(text, scale=6, border=4):
    """QR 그림(SVG 글). 오류 고침 단계 M."""
    from .qrcodegen import QrCode
    q = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
    n = q.get_size()
    parts = []
    for y in range(n):
        x = 0
        while x < n:
            if q.get_module(x, y):
                x0 = x
                while x < n and q.get_module(x, y):
                    x += 1
                parts.append(f"M{x0 + border},{y + border}h{x - x0}v1h-{x - x0}z")
            else:
                x += 1
    size = n + 2 * border
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size * scale}" height="{size * scale}" '
            f'shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/>'
            f'<path d="{"".join(parts)}" fill="#000"/></svg>')


# ---------------------------------------------------------------- WebSocket 소리·메시지(운영판 폰연결 + 폰 요청 기다리기)
# 연결하기 실패 문구(옛 폰 앱 0.1.0 은 '오류' 글을 그대로 보여 줌 — 새 앱은 '왜' 로 고름)
PAIR_FAIL_TEXT = {
    "틀림": "연결 코드가 PC 화면의 숫자와 달라요. 8자리를 다시 확인해 주세요.",
    "만료": "연결 코드 시간(10분)이 지났어요. PC 화면에서 '연결 코드 만들기'를 다시 눌러 주세요.",
    "없음": "PC 에 지금 쓸 수 있는 연결 코드가 없어요(이미 썼거나 만들지 않았어요). PC 화면에서 '연결 코드 만들기'를 눌러 주세요.",
    "잠김": "틀린 코드가 여러 번 들어와 잠깐 막혔어요. 잠시 뒤에 다시 해 주세요.",
    "잠김_전체": "틀린 코드가 너무 많이 들어와 연결하기를 잠깐(최대 15분) 막았어요. 조금 뒤에 다시 해 주세요.",
}


def make_transport(websocket, link, lead=1.5, hold=1.0):
    """pipecat FastAPI WebSocket 전송 — 소리는 폰에 최대 lead 초 앞서 보냄, 말 한 덩이 시작은 hold 초 모아서(끊김 줄이기)."""
    from pipecat.frames.frames import (InputAudioRawFrame, InterruptionFrame, OutputAudioRawFrame, OutputTransportMessageFrame,
                                       OutputTransportMessageUrgentFrame)
    from pipecat.serializers.base_serializer import FrameSerializer
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

    class Ser(FrameSerializer):
        async def serialize(self, frame):
            if isinstance(frame, OutputAudioRawFrame):
                return bytes(frame.audio)
            if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
                return json.dumps(frame.message, ensure_ascii=False)
            if isinstance(frame, InterruptionFrame):
                return json.dumps({"type": "clear_audio"})
            return None

        async def deserialize(self, data):
            if isinstance(data, (bytes, bytearray)):
                if len(data) < 2 or len(data) % 2:
                    return None
                return InputAudioRawFrame(audio=bytes(data), sample_rate=16000, num_channels=1)
            try:
                msg = json.loads(data)
            except ValueError:
                return None
            if isinstance(msg, dict):
                link.on_message(msg)
            return None

    params = FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True, add_wav_header=False, serializer=Ser(),
                                    audio_in_sample_rate=16000, audio_out_sample_rate=24000)
    tr = FastAPIWebsocketTransport(websocket, params)
    out = tr.output()
    if lead > 0:
        def _sleep_factory():
            async def _sleep():
                now = time.monotonic()
                base = out._next_send_time if out._next_send_time > now else now
                out._next_send_time = base + out._send_interval
                ahead = out._next_send_time - now
                if ahead > lead:
                    await asyncio.sleep(ahead - lead)
            return _sleep
        out._write_audio_sleep = _sleep_factory()
    if hold > 0:
        _Holder(out, hold, InterruptionFrame)
    link.transport = tr
    return tr


class _Holder:
    """말 한 덩이의 첫 hold 초를 모아 한 번에 보냄(폰이 처음부터 여유를 두고 재생). 짧은 말은 0.25초 조용하면 바로."""

    def __init__(self, out, hold, interruption, idle=0.25):
        self.out, self.hold, self.idle, self.IF = out, float(hold), float(idle), interruption
        self.orig_write, self.orig_process = out.write_audio_frame, out.process_frame
        self.buf, self.buf_s, self.first_t, self.last_in = [], 0.0, 0.0, 0.0
        self.lock = asyncio.Lock()
        self.timer = None
        out.write_audio_frame = self.write
        out.process_frame = self.process

    @staticmethod
    def _dur(frame):
        sr = getattr(frame, "sample_rate", 24000) or 24000
        ch = getattr(frame, "num_channels", 1) or 1
        return len(frame.audio) / 2 / ch / sr

    async def write(self, frame):
        now = time.monotonic()
        async with self.lock:
            idle_client = self.out._next_send_time <= now + 0.05
            if not self.buf and not idle_client:
                return await self.orig_write(frame)
            if not self.buf:
                self.first_t = now
            self.buf.append(frame)
            self.buf_s += self._dur(frame)
            self.last_in = now
            if self.buf_s >= self.hold:
                await self._flush()
            elif self.timer is None or self.timer.done():
                self.timer = asyncio.get_running_loop().create_task(self._watch())
        return True

    async def _watch(self):
        try:
            while True:
                await asyncio.sleep(0.05)
                async with self.lock:
                    if not self.buf:
                        return
                    now = time.monotonic()
                    if now - self.last_in >= self.idle or now - self.first_t >= self.hold:
                        await self._flush()
                        return
        except asyncio.CancelledError:
            pass

    async def _flush(self):
        frames, self.buf, self.buf_s = self.buf, [], 0.0
        for f in frames:
            await self.orig_write(f)

    async def process(self, frame, direction):
        if isinstance(frame, self.IF):
            self.buf, self.buf_s = [], 0.0
            if self.timer is not None and not self.timer.done():
                self.timer.cancel()
        return await self.orig_process(frame, direction)


PHONE_EVENTS = {"status", "user", "bot", "typed", "interp", "interrupted", "brain_error", "tool", "standby", "settings_applied",
                "voice_gate"}


class PhoneLink:
    """폰 하나와의 대화 연결 — 본체가 폰에 사건을 보내고(send), 폰 동작·확인 단추 답을 기다린다(request)."""

    def __init__(self, websocket, did, name="폰", caps=None):
        self.ws = websocket
        self.did = did
        self.name = name
        self.caps = dict(caps or {})
        self.transport = None
        self.loop = None
        self.n = 0
        self.wait = {}            # id → Future
        self.handlers = {}        # 'text' 등 폰이 먼저 보내는 것 → 함수(msg)
        self.closed = False

    def send(self, msg):
        t = self.transport
        if t is None or self.closed:
            return
        from pipecat.frames.frames import OutputTransportMessageUrgentFrame
        coro = t.output().send_message(OutputTransportMessageUrgentFrame(message=msg))
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:          # 다른 스레드(설정 저장 등)에서 부름 → 대화가 도는 고리로 넘김
            if self.loop is not None and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(coro, self.loop)
            else:
                coro.close()

    def ui(self, ev):
        """화면 사건 중 폰이 쓰는 것만(자막·상태·통역·도구 이름)."""
        if not isinstance(ev, dict) or ev.get("type") not in PHONE_EVENTS:
            return
        if ev.get("type") == "interp":       # 통역 상태·번역은 통째로(폰 통역 화면이 같은 꼴을 씀)
            self.send(json.loads(json.dumps(ev, ensure_ascii=False, default=str)))
            return
        out = {k: v for k, v in ev.items() if k in ("type", "text", "state", "name", "src", "dst", "src_lang", "dst_lang", "src_name",
                                                   "dst_name", "money", "on", "lang", "mode", "items", "why", "reason", "voice")}
        self.send(out)

    async def request(self, msg, timeout=20.0):
        """폰에 일을 시키고 답({"type": "..._result", "id", "result": {...}})을 기다림 → result(dict) 또는 None(시간 넘김·끊김)."""
        if self.closed:
            return None
        self.n += 1
        rid = f"{self.did}-{self.n}"
        fut = asyncio.get_running_loop().create_future()
        self.wait[rid] = fut
        self.send(dict(msg, id=rid))
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self.wait.pop(rid, None)

    def on_message(self, msg):
        rid = msg.get("id")
        if str(msg.get("type") or "").endswith("_result") and rid in self.wait:
            fut = self.wait.get(rid)
            if fut is not None and not fut.done():
                res = msg.get("result")
                fut.get_loop().call_soon_threadsafe(lambda: (not fut.done()) and fut.set_result(res if isinstance(res, dict) else {}))
            return
        h = self.handlers.get(str(msg.get("type") or ""))
        if h is not None:
            try:
                r = h(msg)
                if asyncio.iscoroutine(r):
                    asyncio.get_running_loop().create_task(r)
            except Exception as ex:  # noqa: BLE001
                logger.warning(f"폰 메시지 처리 오류({msg.get('type')}): {ex.__class__.__name__}")

    async def confirm(self, text, timeout=45.0):
        """폰 화면에 '실행할까요?' 단추 → True(예)/False(아니오·시간 넘김)."""
        r = await self.request({"type": "confirm", "text": str(text)[:300]}, timeout=timeout)
        return bool(r and r.get("ok") is True)

    def close(self):
        self.closed = True
        for fut in list(self.wait.values()):
            if not fut.done():
                fut.get_loop().call_soon_threadsafe(lambda f=fut: (not f.done()) and f.set_result(None))


# ---------------------------------------------------------------- 폰 관문(따로 도는 HTTPS·WSS 서버, 본체와 같은 이벤트 고리)
PAIR_MAX_BYTES = 2048


def make_gateway_app(cfg, auth, on_ws, status, pet=None):
    """폰 관문 앱. on_ws(websocket, 기기, 첫 메시지) = 대화 시작(본체가 줌), status(기기) = 폰에 보여 줄 상태 dict.
    pet = core/petphone.PetPhone(있으면 폰 대화 화면의 펫 클립을 건넨다).
    길: POST /phone/pair · GET /phone/api/status(토큰) · GET /phone/api/pet(토큰) · GET /phone/api/pet/clip(토큰)
        · WS /phone/ws(첫 메시지에 토큰). 나머지는 404."""
    from fastapi import FastAPI, Request, WebSocket
    from fastapi.responses import FileResponse, JSONResponse
    from starlette.websockets import WebSocketDisconnect

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def ts_ok():
        return bool(conf(cfg).get("테일스케일_허용"))

    P = ("/phone/pair", "/phone/api/status", "/phone/api/pet", "/phone/api/pet/clip")

    @app.middleware("http")
    async def gate(request: Request, call_next):
        ip = request.client.host if request.client else ""
        if not allowed_ip(ip, ts_ok()):
            return JSONResponse({"ok": False, "왜": "주소_거절", "오류": "집 안 네트워크에서만 연결돼요. 테일스케일로 연결하려면 PC 김비서 설정 → "
                                 "폰 연결 → '테일스케일로도 연결 받기'를 켜 주세요."}, status_code=403)
        if request.url.path not in P:
            return JSONResponse({"ok": False}, status_code=404)
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.post("/phone/pair")
    async def pair(request: Request):
        ip = request.client.host if request.client else ""
        body = await request.body()
        if len(body) > PAIR_MAX_BYTES:
            return JSONResponse({"ok": False, "오류": "요청이 너무 커요"}, status_code=413)
        try:
            b = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            b = None
        if not isinstance(b, dict):
            return JSONResponse({"ok": False, "오류": "연결 코드를 보내 주세요"}, status_code=400)
        r, why = await asyncio.to_thread(auth.pair_why, str(b.get("code") or "")[:16], str(b.get("name") or "폰"), ip)
        if not r:
            left = auth.lock_left(ip)
            msg = PAIR_FAIL_TEXT.get(why) or PAIR_FAIL_TEXT["틀림"]
            return JSONResponse({"ok": False, "왜": why, "오류": msg, **({"잠금초": round(left)} if left else {})}, status_code=403)
        return {"ok": True, "기기": r["기기"], "토큰": r["토큰"], "이름": r["이름"], **status(r["기기"])}

    @app.get("/phone/api/status")
    async def phone_status(request: Request):
        ip = request.client.host if request.client else ""
        did = auth.check(request.headers.get(TOKEN_HEADER), ip, "상태")
        if not did:
            return JSONResponse({"ok": False, "오류": "등록되지 않은 기기예요. 다시 연결해 주세요."}, status_code=401)
        return {"ok": True, "기기": did, **status(did)}

    def pet_auth(request):
        ip = request.client.host if request.client else ""
        did = auth.check(request.headers.get(TOKEN_HEADER), ip, "펫")
        if not did:
            return None, JSONResponse({"ok": False, "오류": "등록되지 않은 기기예요. 다시 연결해 주세요."}, status_code=401)
        return did, None

    @app.get("/phone/api/pet")
    async def phone_pet(request: Request):
        """지금 펫(옷) 정보 + 폰에 필요한 클립 목록(이름·sha256·크기). outfit= 이 있으면 그 옷(폰에서 따로 고르기)."""
        _did, err = pet_auth(request)
        if err is not None:
            return err
        if pet is None:
            return {"ok": True, "옷": None, "고른옷": "", "지금옷": "", "옷목록": [], "동작": []}
        selected = str(request.query_params.get("outfit") or "")[:40]
        try:
            data = await asyncio.to_thread(pet.manifest, selected)
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"폰 펫 목록 오류: {ex.__class__.__name__}")
            return JSONResponse({"ok": False, "오류": "펫 정보를 읽지 못했어요"}, status_code=500)
        return {"ok": True, **data}

    @app.get("/phone/api/pet/clip")
    async def phone_pet_clip(request: Request):
        """클립 한 개(작은 판이 있으면 그것). motion = idle·talk·hello·wave. sha256 은 머리글에도 넣는다."""
        _did, err = pet_auth(request)
        if err is not None:
            return err
        selected = str(request.query_params.get("outfit") or "")[:40]
        motion = str(request.query_params.get("motion") or "")[:20]
        if pet is None:
            return JSONResponse({"ok": False, "오류": "펫이 없어요"}, status_code=404)
        try:
            r = await asyncio.to_thread(pet.clip, selected, motion)
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"폰 펫 클립 오류: {ex.__class__.__name__}")
            r = None
        if r is None:
            return JSONResponse({"ok": False, "오류": "그 클립이 없어요"}, status_code=404)
        path, media, sha = r
        resp = FileResponse(path, media_type=media)
        resp.headers["X-Content-SHA256"] = sha
        return resp

    @app.websocket("/phone/ws")
    async def phone_ws(websocket: WebSocket):
        ip = websocket.client.host if websocket.client else ""
        if not allowed_ip(ip, ts_ok()):
            await websocket.close(code=4403)
            return
        await websocket.accept()
        try:
            hello = json.loads(await asyncio.wait_for(websocket.receive_text(), timeout=10))
        except (asyncio.TimeoutError, ValueError, KeyError, WebSocketDisconnect, RuntimeError):
            await websocket.close(code=4400)
            return
        did = auth.check(str((hello or {}).get("auth") or "") if isinstance(hello, dict) else "", ip, "대화")
        if not did:
            try:
                await websocket.send_text(json.dumps({"type": "auth_fail"}))
            except Exception:  # noqa: BLE001
                pass
            await websocket.close(code=4401)
            return
        auth.touch_save()
        auth.record("대화 연결", ip, 기기=did)
        await websocket.send_text(json.dumps({"type": "auth_ok", "기기": did, **status(did)}, ensure_ascii=False))
        await on_ws(websocket, did, hello)

    return app


class Gateway:
    """폰 관문 켜기·끄기(설정 폰.켜기 를 바꾸면 본체가 restart). 끄면 포트를 닫는다."""

    def __init__(self, cfg, auth, on_ws, status, pet=None):
        self.cfg, self.auth, self.on_ws, self.status, self.pet = cfg, auth, on_ws, status, pet
        self.server = None
        self.task = None
        self.error = ""
        self.fp = ""

    def running(self):
        return self.task is not None and not self.task.done() and self.server is not None and self.server.started

    async def start(self):
        import contextlib

        import uvicorn

        class _Server(uvicorn.Server):
            @contextlib.contextmanager
            def capture_signals(self):       # 본체(uvicorn)의 Ctrl+C·종료 신호 처리를 가로채지 않게
                yield

        await self.stop()
        self.error = ""
        if not enabled(self.cfg):
            return False
        try:
            cert, key, pw, self.fp = await asyncio.to_thread(tls_files, self.cfg)
        except Exception as ex:  # noqa: BLE001
            self.error = f"인증서를 만들지 못했어요({ex.__class__.__name__})"
            logger.warning(f"폰 관문: {self.error}")
            return False
        app = make_gateway_app(self.cfg, self.auth, self.on_ws, self.status, self.pet)
        conf_ = uvicorn.Config(app, host="0.0.0.0", port=port(self.cfg), log_level="warning", lifespan="off",
                               ssl_certfile=cert, ssl_keyfile=key, ssl_keyfile_password=pw,
                               ws_ping_interval=20, ws_ping_timeout=20, ws_max_size=1 << 20)
        self.server = _Server(conf_)
        self.task = asyncio.get_running_loop().create_task(self.server.serve())
        for _ in range(50):
            if self.server.started or self.task.done():
                break
            await asyncio.sleep(0.1)
        if not self.server.started:
            self.error = f"포트 {port(self.cfg)} 을(를) 열지 못했어요(다른 프로그램이 쓰는 중일 수 있어요)"
            logger.warning(f"폰 관문: {self.error}")
            await self.stop()
            return False
        logger.info(f"폰 관문 켬: 0.0.0.0:{port(self.cfg)} (HTTPS·WSS, 집 안 네트워크" +
                    (" + 테일스케일" if conf(self.cfg).get("테일스케일_허용") else "") + ", 등록 기기만)")
        return True

    async def stop(self):
        if self.server is not None:
            self.server.should_exit = True
        if self.task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self.task), 5)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                if not self.task.done():
                    self.server.force_exit = True
            logger.info("폰 관문 끔")
        self.server, self.task = None, None

    def info(self):
        return {"켜짐": enabled(self.cfg), "듣는중": self.running(), "포트": port(self.cfg), "오류": self.error,
                "지문": fp_words(self.fp) if self.fp else "", "주소": lan_addresses(self.cfg) if self.running() else []}
