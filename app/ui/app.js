// 김비서 화면 — 공통 도구·화면 바꾸기·사건 받기(/api/events)·대화 연결(WebRTC)·기억 화면
"use strict";
const K = {cfg: null, choices: null, pending: {}, when: {}, talk: null, view: "", lastStatus: ""};

// ---------------------------------------------------------------- 공통
async function api(path, body, raw) {
  const opt = {method: body === undefined ? "GET" : "POST", headers: {}};
  if (body !== undefined) {
    if (raw) { opt.headers["Content-Type"] = "application/octet-stream"; opt.body = body; }
    else { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  }
  const r = await fetch(path, opt);
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json().catch(() => null) : await r.blob();
  if (!r.ok) {
    const msg = data && data["오류"] ? (typeof data["오류"] === "string" ? data["오류"] : Object.values(data["오류"]).join(" ")) : `오류 ${r.status}`;
    throw Object.assign(new Error(msg), {status: r.status, data});
  }
  return data;
}

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of kids.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return el;
}

let toastT = null;
function toast(msg, ms) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastT);
  toastT = setTimeout(() => { t.hidden = true; }, ms || 4200);
}

function confirmBox(text, yes) {
  const d = document.getElementById("dialog");
  document.getElementById("dialog-text").textContent = text;
  document.getElementById("dialog-yes").textContent = yes || tr("네");
  d.hidden = false;
  return new Promise((res) => {
    const done = (v) => { d.hidden = true; res(v); };
    document.getElementById("dialog-yes").onclick = () => done(true);
    document.getElementById("dialog-no").onclick = () => done(false);
  });
}

// 고르기 단추 묶음: items = [{값, 이름, 설명, 막음}] → 고르면 onPick(값)
function choiceGroup(items, value, onPick, opts) {
  const box = h("div", {class: "choices" + (opts && opts.wide ? " wide" : ""), role: "group", "aria-label": (opts && opts.label) || null});
  const btns = items.map((it) => {
    const b = h("button", {type: "button", class: "choice", "aria-pressed": String(it.값 === value), disabled: !!it.막음,
      "data-value": String(it.값), id: opts && opts.idp ? `${opts.idp}-${String(it.값).replace(/[^0-9A-Za-z가-힣]/g, "_")}` : null},
    it.이름, it.설명 ? h("small", {text: it.설명}) : null);
    b.addEventListener("click", () => {
      if (it.막음) return;
      btns.forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      onPick(it.값);
    });
    return b;
  });
  btns.forEach((b) => box.appendChild(b));
  box.select = (v) => btns.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === String(v))));
  return box;
}

function notice(kind, title, text) {
  return h("div", {class: "notice " + (kind || "")}, title ? h("strong", {text: title}) : null, text ? h("p", {text}) : null);
}

function field(label, input, hint) {
  const id = input.id || ("f" + Math.random().toString(36).slice(2, 8));
  input.id = id;
  return h("div", {}, h("label", {class: "field", for: id, text: label}), input, hint ? h("p", {class: "hint", text: hint}) : null);
}

function get(obj, path, def) {
  let cur = obj;
  for (const p of path.split(".")) { if (cur && typeof cur === "object" && p in cur) cur = cur[p]; else return def; }
  return cur;
}

function setFont(v) { document.documentElement.dataset.font = v || "크게"; }

async function loadSettings() {
  const j = await api("/api/settings");
  K.cfg = j["설정"]; K.choices = j["선택지"]; K.pending = j["다시켜기_필요"] || {}; K.when = j["반영시점"] || {};
  setFont(get(K.cfg, "화면.글자"));
  setName(get(K.cfg, "비서.이름", "김비서"));
  showPending();
  return j;
}

function setName(name) {
  // 영어 화면의 기본 이름은 'Kimmy (KimBiseo)' 로 보여 준다(사용자가 다른 이름을 넣으면 그대로).
  const shown = (window.I18N && I18N.lang === "en" && name === "Kimmy") ? "Kimmy (KimBiseo)" : name;
  document.getElementById("top-name").textContent = shown;
  document.getElementById("talk-title").textContent = shown;
  document.getElementById("talk-initial").textContent = (name || "김").slice(0, 1);
  document.title = shown;
}

// 저장 결과 → 쉬운 안내 한 줄
function savedMessage(r) {
  if (!r || !r["바뀜"] || !r["바뀜"].length) return tr("바뀐 것이 없어요.");
  const g = r["반영"] || {}, out = [];
  if ((g["즉시"] || []).length) out.push(tr("지금 바로 바뀌었어요"));
  if ((g["다음대화"] || []).length) out.push(tr("{0}은(는) 다음 대화부터 바뀌어요", {0: g["다음대화"].join("·")}));
  const rs = g["다시켜기"] || {};
  Object.keys(rs).forEach((k) => out.push(tr("{0}은(는) {1}를 다시 켜야 바뀌어요",
    {0: rs[k].join("·"), 1: tr(k === "귀" ? "받아쓰기 서버" : "목소리 서버")})));
  if ((g["펫"] || []).length) {
    const po = (r["펫"] || {})["옷"];      // 켜져 있는 펫이 '옷 갈아입기'에 한 대답(펫이 꺼져 있으면 코드 없음)
    if (po && po["받는중"]) out.push(tr("펫이 새 옷을 받는 중이에요(다 받으면 갈아입어요)"));
    else if (po && po["ok"]) out.push(tr("펫 옷을 바꿨어요"));
    else if (po && po["코드"] && po["error"]) out.push(tr("펫: {0}", {0: po["error"]}));
    else out.push(tr("펫은 다음에 켜질 때 바뀌어요"));
  }
  return tr("저장했어요.") + " " + out.join(". ") + ".";
}

async function saveSettings(changes) {
  const r = await api("/api/settings", {"바꿀것": changes});
  K.cfg = r["설정"]; K.pending = r["다시켜기_필요"] || {};
  setFont(get(K.cfg, "화면.글자"));
  setName(get(K.cfg, "비서.이름", "김비서"));
  showPending();
  toast(savedMessage(r) + ((r["경고"] || []).length ? " " + r["경고"].join(" ") : ""), 6000);
  return r;
}

function showPending() {
  const box = document.getElementById("pending-box");
  const p = K.pending || {};
  const keys = Object.keys(p);
  box.replaceChildren();
  if (!keys.length) { box.hidden = true; return; }
  box.hidden = false;
  const names = keys.map((k) => tr(k === "귀" ? "받아쓰기 서버" : "목소리 서버") + "(" + p[k].join("·") + ")");
  box.appendChild(h("strong", {text: tr("다시 켜야 적용되는 설정이 있어요")}));
  box.appendChild(h("p", {text: tr("{0} — 김비서를 껐다 다시 켜면 적용돼요.", {0: names.join(", ")})}));
  const py = window.pywebview && window.pywebview.api;
  if (py && typeof py.restart_services === "function") {
    box.appendChild(h("button", {class: "btn primary", type: "button", id: "pending-restart", text: tr("지금 다시 켜기"),
      onclick: async () => { toast(tr("다시 켜는 중이에요. 잠시만 기다려 주세요.")); try { await py.restart_services(keys); } catch (_) { /* 창 쪽 오류 */ } setTimeout(loadSettings, 1500); }}));
  }
}

function show(view) {
  K.view = view;
  // 기억·설정은 대화 화면 위에 뜨는 판 — 대화 화면은 밑에 그대로 둔다
  ["wizard", "main", "memory", "settings"].forEach((v) => {
    document.getElementById("view-" + v).hidden = v === "main" ? !["main", "memory", "settings"].includes(view) : v !== view;
  });
  document.getElementById("top-nav").hidden = view === "wizard";
  ["main", "memory", "settings"].forEach((v) => document.getElementById("nav-" + v).classList.toggle("active", v === view));
  if (view === "memory") Memory.load();
  if (view === "settings") Settings.render();
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------- 사건 받기
const STATE_TEXT = {"듣는 중": "듣고 있어요. 편하게 말씀하세요.", "생각 중": "생각하고 있어요.", "말하는 중": "말하고 있어요.",
  "도구 사용 중": "찾아보고 있어요."};
const TOOL_TEXT = {get_weather: "날씨를 보고 있어요", web_search: "검색하고 있어요", read_page: "페이지를 읽고 있어요",
  remember: "기억하고 있어요", recall: "예전 기억을 찾고 있어요", forget: "기억을 지우고 있어요", pc_action: "프로그램을 여는 중이에요",
  type_text: "메모장에 적고 있어요", phone_action: "폰에서 여는 중이에요",
  calc: "계산하고 있어요", speech_speed: "말 빠르기를 바꿔요", standby: "쉬는 중으로 바꿔요"};

function startEvents() {
  const es = new EventSource("/api/events");
  K.es = es;
  es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch (_) { /* 깨진 사건 무시 */ } };
  es.onerror = () => { setTop("본체와 연결이 끊겼어요", ""); };
  es.onopen = () => { if (!Talk.on) setTop("준비됨", "on"); };
}

function setTop(text, cls) {
  document.getElementById("top-state").textContent = text;
  const dot = document.getElementById("top-dot");
  dot.className = "dot" + (cls ? " " + cls : "");
}

function onEvent(ev) {
  const t = ev.type;
  if (t === "hello") {
    setName(ev["이름"]);
    const db = document.getElementById("debate-badge");
    if (db) { db.hidden = true; db.dataset.adult = "0"; }
    return;
  }
  if (t === "status") {
    K.lastStatus = ev.state;
    const face = document.getElementById("talk-face");
    face.classList.toggle("speaking", ev.state === "말하는 중");
    face.classList.toggle("listening", ev.state === "듣는 중");
    if (Talk.on) {
      document.getElementById("talk-state").textContent = STATE_TEXT[ev.state] || ev.state;
      setTop(ev.state, ev.state === "듣는 중" ? "on" : "busy");
    }
    return;
  }
  if (t === "user" || t === "typed") { Chat.add("user", ev.text); return; }
  if (t === "bot") { Chat.bot(ev.text); return; }
  if (t === "interrupted") { Chat.cut(); return; }
  if (t === "tool" && ev.state === "start") { Chat.sys(tr(TOOL_TEXT[ev.name] || "도구를 쓰고 있어요") + "."); return; }
  if (t === "tool_halt") { Chat.sys(tr("도구를 너무 많이 불러서 멈췄어요.")); return; }
  if (t === "brain_error") { Chat.sys(ev.text || ev.reason || tr("두뇌 연결에 문제가 있어요.")); return; }
  if (t === "brain_prepare" || t === "brain_ready") {
    // 두뇌를 바꾼 직후 로컬 두뇌를 켜고 모델을 읽는 동안 — '두뇌 준비 중(n초)'을 아래 줄에 보여 준다.
    const el = document.getElementById("talk-state");
    if (t === "brain_prepare") {
      const txt = tr("두뇌 준비 중({0}초)", {0: ev["초"] == null ? 0 : ev["초"]});
      if (Talk.on) el.textContent = txt;
      setTop(txt, "busy");
    } else if (Talk.on) {
      el.textContent = STATE_TEXT[K.lastStatus] || K.lastStatus || "";
      setTop(K.lastStatus || "준비됨", K.lastStatus === "듣는 중" ? "on" : "busy");
    }
    return;
  }
  if (t === "wake_mode") { Chat.sys(ev.on ? tr("이름({0})을 부르면 대답해요.", {0: get(K.cfg, "비서.이름", "김비서")}) : tr("지금은 이름 없이도 대답해요.")); return; }
  if (t === "names") { setName(ev.name); return; }
  if (t === "settings") { loadSettings().catch(() => {}); return; }
  if (t === "update") { Update.onEvent(ev); return; }
  if (t === "debate") {
    const db = document.getElementById("debate-badge");
    if (db) { db.hidden = !ev.on; db.dataset.adult = ev.adult ? "1" : "0"; }
    return;
  }
  if (t === "interp") { Interp.onEvent(ev); return; }
  if (t === "confirm") { ToolConfirm.ask(ev); return; }
  if (t === "confirm_done") { ToolConfirm.done(ev); return; }
  if (t === "voice_gate") { Chat.sys(tr("(안 들음 — 등록한 목소리가 아니에요{0})", {0: ev.text ? ": " + ev.text : ""})); return; }
  if (t === "phone") { Chat.sys(ev.state === "on" ? tr("폰({0})으로 대화 중이에요. 이 창의 대화는 쉬어요.", {0: ev.name || ""}) : tr("폰 대화가 끝났어요.")); return; }
  if (t === "conn" && !ev.on && Talk.on) { Talk.stop(tr("대화가 끝났어요.")); }
}

// ---------------------------------------------------------------- 대화 내용
const hhmmss = (d) => [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, "0")).join(":");

// 아래 안내 줄(쉬는 때) — 키 모양 안내
function idleHint(msg) {
  const el = document.getElementById("talk-state");
  if (msg) { el.textContent = msg; return; }
  el.replaceChildren(h("kbd", {text: "Enter"}), " 보내기 · 마이크 단추로 말 걸기");
}

const Chat = {
  cur: null,
  list() { return document.getElementById("chat"); },
  add(kind, text) {
    if (!text) return;
    this.cur = null;
    const who = kind === "user" ? tr("나") : get(K.cfg, "비서.이름", "김비서");
    // 말한 내용(사용자·비서 글)은 번역하지 않고, 화면 안내(시스템 줄)만 번역한다.
    const li = h("li", {class: kind, "data-time": kind === "sys" ? null : hhmmss(new Date())},
      kind === "sys" ? null : h("span", {class: "who", text: who}),
      h("span", {class: "txt", text, translate: kind === "sys" ? null : "no"}));
    this.list().appendChild(li);
    this.list().scrollTop = this.list().scrollHeight;
    return li;
  },
  bot(text) {
    if (!text) return;
    if (!this.cur) { this.cur = this.add("bot", text); return; }
    const s = this.cur.querySelector(".txt");
    s.textContent = (s.textContent + " " + text).trim();
    this.list().scrollTop = this.list().scrollHeight;
  },
  cut() { this.cur = null; },
  sys(text) { this.add("sys", text); },
};

// ---------------------------------------------------------------- 대화 연결(WebRTC)
const Talk = {
  on: false, busy: false, pc: null, dc: null, mic: null, ping: null,
  async start() {
    if (this.on || this.busy) return;
    this.busy = true;
    const btn = document.getElementById("talk-btn");
    btn.disabled = true;
    document.getElementById("talk-state").textContent = "연결하고 있어요.";
    try {
      let info = null;
      try {
        const m = await KAudio.openMic(get(K.cfg, "화면.마이크", ""));
        this.mic = m.stream; info = m.info;
      } catch (e) {
        Chat.sys(e.name === "NotFoundError" ? tr("마이크를 찾을 수 없어요. 글로만 대화해요.")
          : tr("마이크를 쓸 수 없어요({0}). 글로만 대화해요.", {0: e.message}));
        this.mic = new AudioContext().createMediaStreamDestination().stream;
      }
      showAec(info);
      const pc = new RTCPeerConnection({iceServers: []});
      this.pc = pc;
      pc.addTransceiver(this.mic.getAudioTracks()[0], {direction: "sendrecv", streams: [this.mic]});
      const dc = pc.createDataChannel("chat", {ordered: true});
      this.dc = dc;
      dc.onopen = () => { this.ping = setInterval(() => { try { if (dc.readyState === "open") dc.send("ping: " + Date.now()); } catch (_) { /* 끊김 */ } }, 1000); };
      const spk = document.getElementById("spk");
      pc.ontrack = (e) => {
        spk.srcObject = e.streams[0] || new MediaStream([e.track]);
        KAudio.setSink(spk, get(K.cfg, "화면.스피커", "")).then(() => spk.play().catch(() => {}));
      };
      pc.onconnectionstatechange = () => {
        if (this.pc !== pc) return;
        if (["failed", "closed"].includes(pc.connectionState)) this.stop("연결이 끊겼어요. 다시 눌러 주세요.");
      };
      await pc.setLocalDescription(await pc.createOffer());
      await new Promise((res) => {
        if (pc.iceGatheringState === "complete") return res();
        const f = () => { if (pc.iceGatheringState === "complete") { pc.removeEventListener("icegatheringstatechange", f); res(); } };
        pc.addEventListener("icegatheringstatechange", f);
        setTimeout(res, 2000);
      });
      const ans = await api("/api/offer", {sdp: pc.localDescription.sdp, type: pc.localDescription.type, request_data: {greeting: true}});
      await pc.setRemoteDescription(ans);
      this.on = true;
      talkBtn(true);
      document.getElementById("talk-state").textContent = STATE_TEXT["듣는 중"];
      setTop("대화 중", "on");
    } catch (e) {
      Chat.sys(tr("연결하지 못했어요: {0}", {0: e.message}));
      this.stop();
    } finally {
      this.busy = false;
      btn.disabled = false;
    }
  },
  stop(msg) {
    clearInterval(this.ping); this.ping = null;
    try { this.dc && this.dc.close(); } catch (_) { /* 이미 닫힘 */ }
    try { this.pc && this.pc.close(); } catch (_) { /* 이미 닫힘 */ }
    KAudio.stop(this.mic);
    this.pc = this.dc = this.mic = null;
    const was = this.on;
    this.on = false;
    talkBtn(false);
    idleHint(msg);
    document.getElementById("talk-face").className = "talk-face";
    if (!K.es || K.es.readyState === 1) setTop("준비됨", "on"); else setTop("본체와 연결이 끊겼어요", "");
    if (was && msg) Chat.sys(msg);
  },
  async sendText(text) {
    if (!text) return;
    if (!this.on) {
      await this.start();
      for (let i = 0; i < 40 && this.on; i++) {     // 연결 인사가 끝날 때까지 잠깐
        if (K.lastStatus === "듣는 중") break;
        await new Promise((r) => setTimeout(r, 150));
      }
    }
    try { await api("/api/text", {text}); } catch (e) { Chat.sys(tr("보내지 못했어요: {0}", {0: e.message})); }
  },
};

// 마이크 단추(동그란 단추): 글자는 화면 읽기용으로만 두고, 켜짐은 .on 으로
function talkBtn(on) {
  const btn = document.getElementById("talk-btn");
  document.getElementById("talk-label").textContent = on ? "대화 끝내기" : "대화 시작";
  btn.title = on ? "말로 대화 끄기" : "말로 대화 켜기";
  btn.classList.toggle("on", on);
}

function showAec(info) {
  const box = document.getElementById("aec-box");
  box.replaceChildren();
  const d = KAudio.describe(info);
  if (!d) { box.hidden = true; return; }
  box.hidden = false;
  box.id = "aec-box";
  box.className = "notice " + (d.aec ? "ok" : "bad");
  box.dataset.aec = String(d.aec);
  box.appendChild(h("strong", {text: d.aec ? "메아리 지우기가 켜져 있어요" : "메아리 지우기가 꺼져 있어요"}));
  box.appendChild(h("p", {text: d.lines.join(" · ") + (d.label ? ` (${d.label})` : "")}));
  if (!d.aec) box.appendChild(h("p", {text: "스피커로 나온 비서 말을 사람 말로 잘못 들을 수 있어요. 이어폰을 쓰시거나 설정에서 다른 마이크를 골라 주세요."}));
}

// ---------------------------------------------------------------- 기억 화면
const Memory = {
  async load() {
    const facts = document.getElementById("mem-facts"), diary = document.getElementById("mem-diary");
    facts.replaceChildren(); diary.replaceChildren();
    let j;
    try { j = await api("/api/memory"); } catch (e) { facts.appendChild(h("li", {class: "mem-empty", text: "기억을 불러오지 못했어요."})); return; }
    if (!j.ok) { facts.appendChild(h("li", {class: "mem-empty", text: j["오류"] || "기억이 꺼져 있어요."})); return; }
    const fl = (j["지식"] || []).slice().reverse();
    if (!fl.length) facts.appendChild(h("li", {class: "mem-empty", text: "아직 기억하는 것이 없어요."}));
    fl.forEach((f) => facts.appendChild(h("li", {"data-id": f.id},
      h("span", {class: "mem-text"}, h("span", {"translate": "no", text: f["내용"]}),
        h("span", {class: "mem-when", text: `${f["만든때"] || ""} · ${tr(f["출처"] === "자동" ? "대화에서 저절로" : "말해서")}`})),
      h("button", {class: "btn", type: "button", text: "지우기", onclick: () => this.del({id: f.id}, f["내용"])}))));
    const dl = j["일기"] || [];
    if (!dl.length) diary.appendChild(h("li", {class: "mem-empty", text: "아직 일기가 없어요."}));
    dl.forEach((d) => diary.appendChild(h("li", {"data-day": d["날짜"]},
      h("span", {class: "mem-text", "translate": "no"}, h("strong", {text: d["날짜"]}), "\n" + (d["내용"] || "").replace(/^# .*\n/, "").replace(/^#+ */gm, "").trim()),
      h("button", {class: "btn", type: "button", text: "지우기", onclick: () => this.del({day: d["날짜"]}, tr("{0} 일기", {0: d["날짜"]}))}))));
  },
  async del(what, label) {
    if (!(await confirmBox(tr("'{0}' 기억을 지울까요?", {0: String(label).slice(0, 40)}), tr("네, 지울게요")))) return;
    try { await api("/api/memory/delete", what); toast(tr("지웠어요.")); } catch (e) { toast(tr("지우지 못했어요: {0}", {0: e.message})); }
    this.load();
  },
  async clearAll() {
    if (!(await confirmBox(tr("기억하는 사실·일기·지난 대화를 모두 지울까요? 되돌릴 수 없어요."), tr("네, 모두 지울게요")))) return;
    try { await api("/api/memory/delete", {all: true}); toast(tr("기억을 모두 지웠어요.")); } catch (e) { toast(tr("지우지 못했어요: {0}", {0: e.message})); }
    this.load();
  },
};
