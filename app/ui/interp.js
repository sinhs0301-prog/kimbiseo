// 통역 — 대화 화면 위 통역 칸(#interp-box) + 설정 → 통역 탭.
//   켜기: 말("영어 통역해 줘"·"통역해 줘") 또는 이 칸의 '통역 켜기'. 끄기: "통역 그만" 또는 '끄기'. 말이 없으면 설정한 분 뒤 저절로 꺼짐.
//   통역 중 말은 번역만 해요(두뇌 대화·도구로 안 넘김). 번역은 큰 글씨, 원문은 작게, 외국 돈은 원화로 한 줄 더(≈ 14,000원).
//   번역 글은 화면에만(메모리) — 기록 파일에 남기지 않아요.
"use strict";
const Interp = {
  v: null,
  rt: null,
  items: [],
  last: 0,
  timer: null,

  async load() {
    try { this.v = await api("/api/interp?after=" + this.last); } catch (_) { return; }
    for (const it of this.v["최근"] || []) { this.items.push(it); this.last = Math.max(this.last, it.n); }
    this.items = this.items.slice(-6);
    this.draw();
  },

  onEvent(ev) {
    if (ev.state === "done" || ev.state === "on" || ev.state === "off") this.load();
    else if (ev.state === "translating") this.busy(ev);
    else if (ev.state === "error") { this.busy(null); toast("번역이 안 됐어요: " + (ev.why || ""), 5000); }
    else if (ev.state === "no_voice" && ev.why) toast("통역 목소리를 못 냈어요 — 화면 글을 보여 주세요. " + ev.why, 6000);
  },

  busy(ev) {
    const el = document.getElementById("interp-busy");
    if (!el) return;
    el.hidden = !ev;
    if (ev) el.textContent = `${ev.src_name || ""} → ${ev.dst_name || ""} 옮기는 중 · ${ev.src || ""}`;
  },

  langOptions(sel) {
    const L = (this.v && this.v["언어"]) || {};
    sel.replaceChildren(h("option", {value: "auto", text: "자동(말한 언어 알아듣기)"}),
      ...Object.entries(L).map(([k, x]) => h("option", {value: k, text: x["이름"] + (x["목소리"] ? "" : " (글자만)")})));
    sel.value = this.v && this.v["방식"] && this.v["켜짐"] ? this.v["방식"] : "auto";
  },

  draw() {
    const box = document.getElementById("interp-box");
    if (!box || !this.v) return;
    box.replaceChildren();
    const on = !!this.v["켜짐"];
    box.hidden = !on;
    clearInterval(this.timer);
    if (!on) return;
    this.timer = setInterval(() => this.load(), 20000);
    const sel = h("select", {id: "interp-lang", "aria-label": "상대 언어"});
    this.langOptions(sel);
    sel.addEventListener("change", async () => {
      try { this.v = Object.assign(this.v, await api("/api/interp", {"언어": sel.value})); this.draw(); } catch (e) { toast(e.message, 5000); }
    });
    const who = this.v["상대이름"] ? `상대: ${this.v["상대이름"]}` : "상대 말을 기다려요";
    box.append(h("div", {class: "row between interp-head"},
      h("strong", {text: "통역 중"}), h("span", {class: "hint", id: "interp-who", text: who + (this.v["두뇌"] ? ` · 번역: ${this.v["두뇌"]}` : "")}),
      h("div", {class: "row"}, sel, h("button", {class: "btn", type: "button", id: "interp-off", text: "끄기", onclick: () => this.turn(false)}))),
    h("p", {class: "hint", id: "interp-busy", hidden: true}));
    const list = h("ol", {class: "interp-list", id: "interp-list"});
    for (const it of this.items.slice(-3).reverse()) {          // 방금 번역이 맨 위(가장 크게)
      list.appendChild(h("li", {"data-dst": it.dst_lang || ""},
        h("p", {class: "interp-src", text: it.src}),
        h("p", {class: "interp-dst", lang: it.dst_lang || null, text: it.dst}),
        it.money ? h("p", {class: "interp-krw", text: it.money}) : null));
    }
    if (!this.items.length) list.appendChild(h("li", {}, h("p", {class: "hint", text: "내 언어로 말하면 상대 언어로, 상대가 말하면 내 언어로 옮겨요. 끝낼 땐 '통역 그만'."})));
    box.append(list);
  },

  async turn(on, lang) {
    try {
      this.v = Object.assign(this.v || {}, await api("/api/interp", on ? {"켜기": true, "언어": lang || "auto"} : {"켜기": false}));
    } catch (e) { toast("통역을 바꾸지 못했어요: " + e.message, 6000); return; }
    if (!on) this.items = [];
    this.draw();
  },

  // ---------------------------------------------------------------- 설정 → 통역
  async settings(card) {
    const ch = K.choices, c = K.cfg;
    card.appendChild(h("h1", {text: "통역"}));
    const s1 = Settings.section(card, "통역 모드", ["통역.켜기", "통역.자동끔_분"]);
    const on = h("input", {type: "checkbox", id: "set-interp-on"}); on.checked = get(c, "통역.켜기", true) !== false;
    const mins = h("input", {type: "number", id: "set-interp-min", min: "1", max: "60", step: "1", value: String(get(c, "통역.자동끔_분", 10))});
    s1.append(h("p", {class: "hint", text: "\"태국어 통역해 줘\"·\"통역해 줘\"(자동)라고 말하면 켜져요. 통역 중 말은 번역만 하고, 김비서에게 하는 부탁으로 받지 않아요(다른 사람 말로 김비서가 움직이지 않게)."}),
      h("label", {class: "toggle", for: "set-interp-on"}, on, "통역 모드 쓰기"),
      field("말이 없으면 저절로 끄기(분)", mins),
      h("div", {class: "row"}, h("button", {class: "btn", type: "button", id: "set-interp-start", text: "지금 통역 켜기", onclick: () => { this.turn(true); show("main"); }})),
      Settings.saveRow("set-interp-save", () => ({통역: {켜기: on.checked, 자동끔_분: Math.max(1, Math.min(60, parseInt(mins.value, 10) || 10))}})));

    const s2 = Settings.section(card, "통역 목소리", ["통역.목소리_엔진"]);
    let eng = get(c, "통역.목소리_엔진", "원어민");
    const rtBox = h("div", {id: "set-interp-rt"}, h("p", {class: "hint", text: "살펴보는 중이에요."}));
    s2.append(h("p", {class: "hint", text: "외국어 번역을 그 나라 목소리로 읽을지, 화면 글자로만 보여 줄지 골라요. 내 언어 번역은 늘 김비서 목소리로 읽어요."}),
      choiceGroup((ch["통역_목소리"] || []).map((x) => ({값: x.id, 이름: x["이름"], 설명: x["설명"]})), eng, (v) => { eng = v; }, {wide: true, idp: "set-interp-eng"}),
      rtBox, Settings.saveRow("set-interp-eng-save", () => ({통역: {목소리_엔진: eng}})));
    this.loadRuntime(rtBox);

    const s3 = Settings.section(card, "환율", ["통역.환율_켜기"]);
    const fx = h("input", {type: "checkbox", id: "set-interp-fx"}); fx.checked = get(c, "통역.환율_켜기", true) !== false;
    s3.append(h("p", {class: "hint", text: "상대가 말한 외국 돈(바트·엔·동·리라·유로·달러 …)을 한국 돈(원)으로 바꿔 '(약 14,000원)'으로 덧붙여요. 환율은 통역을 쓸 때 하루 한 번만 공개 환율에서 받아요(내 정보는 안 보냄). 인터넷이 안 되면 마지막에 받은 값을 써요."}),
      h("label", {class: "toggle", for: "set-interp-fx"}, fx, "외국 돈을 원화로 보여 주기"),
      h("p", {class: "hint", id: "set-interp-fx-src", text: "환율 출처: 유럽중앙은행 기준환율(frankfurter.dev) · Rates By Exchange Rate API(open.er-api.com, 위에 없는 통화)"}),
      Settings.saveRow("set-interp-fx-save", () => ({통역: {환율_켜기: fx.checked}})));

    const s4 = Settings.section(card, "번역 두뇌(선택)", ["통역.두뇌_주소", "통역.두뇌_모델"]);
    const url = h("input", {type: "url", id: "set-interp-url", placeholder: "비우면 지금 두뇌(이 PC 의 AI)로 번역", value: get(c, "통역.두뇌_주소", "") || ""});
    const model = h("input", {type: "text", id: "set-interp-model", placeholder: "모델 이름(비우면 default)", value: get(c, "통역.두뇌_모델", "") || ""});
    s4.append(h("p", {class: "hint", text: "보통은 비워 두세요 — 지금 쓰는 두뇌(이 PC 의 Gemma 등)로 번역해요. 다른 OpenAI 호환 AI 로 번역하고 싶을 때만 주소를 적어요. 구독 두뇌(클로드·GPT 로그인)도 되지만 한 마디마다 몇 초 걸려요 — 빠르게 하려면 여기에 로컬 AI 주소를 적어 주세요."}),
      field("통역용 AI 주소", url), field("모델 이름", model),
      Settings.saveRow("set-interp-url-save", () => ({통역: {두뇌_주소: url.value.trim(), 두뇌_모델: model.value.trim()}})));
  },

  async loadRuntime(box) {
    try { this.rt = await api("/api/interp/runtime"); } catch (_) { box.replaceChildren(h("p", {class: "hint", text: "통역 목소리 상태를 읽지 못했어요."})); return; }
    this.drawRuntime(box);
    if (this.rt["설치중"]) this.pollRuntime(box);
  },

  drawRuntime(box) {
    const r = this.rt;
    box.replaceChildren();
    const ready = r["부품"] && r["언어"].filter((x) => x["목소리"]).every((x) => x["받음"]);
    const rows = r["언어"].map((x) => h("li", {"data-lang": x["코드"]}, x["이름"] + " — " +
      (!x["목소리"] ? "글자만(상업용으로 쓸 수 있는 목소리 없음)" : (r["부품"] && x["받음"]) ? "원어민 목소리" : "아직 안 받음")));
    box.append(h("ul", {class: "hint interp-langs", id: "set-interp-langs"}, ...rows));
    const st = h("p", {class: "hint", id: "set-interp-rt-state"});
    const prog = r["진행"];
    if (prog && prog["끝"] && !prog["성공"] && prog["오류"]) {
      const e = prog["오류"];
      box.append(notice("bad", "통역 목소리를 받지 못했어요", "까닭: " + (e["까닭"] || e["이유"] || "") + " 인터넷을 확인하고 다시 눌러 주세요(받은 만큼은 이어서 받아요)."));
    }
    const btn = h("button", {class: "btn" + (ready ? "" : " primary"), type: "button", id: "set-interp-get", text: ready ? "통역 목소리 다시 받기" : "통역 목소리 받기(약 800MB)",
      onclick: async () => {
        try { await api("/api/interp/install", {}); } catch (e) { toast("받기를 시작하지 못했어요: " + e.message, 7000); return; }
        await this.loadRuntime(box); this.pollRuntime(box);
      }});
    if (r["설치중"]) { btn.disabled = true; st.textContent = (prog && prog["글"]) || "통역 목소리를 받는 중이에요."; }
    else if (ready) st.textContent = "원어민 목소리를 받아 두었어요.";
    box.append(h("div", {class: "row"}, btn), st,
      h("p", {class: "hint", text: "목소리: Kokoro-82M(Apache-2.0) · Piper 목소리(독일어 thorsten·그리스어 rapunzelina·러시아어 denis = CC0 자료, 터키어 antalia = CC-BY-4.0 ozgurguler) · 태국어 MrJMThaiTTS(가중치 Apache-2.0, 학습 자료가 비상업 모델의 합성음이라 상업 사용은 회색 — 걱정되면 '글자만'). 읽기 프로그램 Piper(GPL-3.0)는 이 PC 가 공식 배포처에서 직접 받아 따로 돌려요. 합성 목소리예요 — 듣는 사람이 헷갈리면 기계 목소리라고 알려 주세요."}));
  },

  pollRuntime(box) {
    clearInterval(this.rtTimer);
    this.rtTimer = setInterval(async () => {
      const was = this.rt && this.rt["설치중"];
      try { this.rt = await api("/api/interp/runtime"); } catch (_) { return; }
      if (box.isConnected) this.drawRuntime(box);
      if (!this.rt["설치중"]) {
        clearInterval(this.rtTimer);
        const p = this.rt["진행"];
        if (was && p && p["끝"] && p["성공"]) toast("통역 목소리를 설치했어요.", 5000);
      }
    }, 1000);
  },
};
