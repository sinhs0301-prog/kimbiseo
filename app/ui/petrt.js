// 펫 프로그램 — 설치할 때 '펫' 단계를 받지 못했어도 김비서(대화)는 먼저 쓰고, 펫은 여기서 나중에 넣는다.
//   · 대화 화면 위 알림(#petrt-box): 펫을 쓰기로 했는데 펫 프로그램이 없을 때만 보임
//   · 설정 → 펫 의 '펫 프로그램' 칸: '펫 다시 받기' · '직접 넣기'(① 브라우저로 받기 → ② 받은 파일 고르기) — 설치 창과 같은 말·같은 순서
//   받기·확인·풀기는 본체가 설치 프로그램(installer/setup_core.py pet-install)을 따로 띄워서 한다. 화면은 1초마다 상태만 읽는다.
"use strict";
const PetRuntime = {
  v: null,
  timer: null,
  manualOpen: false,      // '직접 넣기' 순서 칸을 펼쳤는지

  winApi() { return (window.pywebview && window.pywebview.api) || null; },

  async load() {
    try { this.v = await api("/api/pet/runtime"); } catch (_) { return null; }
    this.drawBox();
    if (this.v["설치중"]) this.poll();
    return this.v;
  },

  missing() { return !!(this.v && this.v["얼굴_펫"] && !this.v["있음"]); },

  // 대화 화면 위 알림
  drawBox() {
    const box = document.getElementById("petrt-box");
    if (!box) return;
    box.replaceChildren();
    if (!this.missing()) { box.hidden = true; return; }
    box.hidden = false;
    box.append(h("strong", {text: "펫이 아직 설치되지 않았어요"}),
      h("p", {text: "설치할 때 펫 프로그램을 받지 못했어요. 대화는 지금도 쓸 수 있어요. 펫은 설정 → 펫 에서 다시 받을 수 있어요."}),
      h("div", {class: "row"}, h("button", {class: "btn primary", type: "button", id: "petrt-open", text: "펫 설치하러 가기",
        onclick: () => { Settings.tab = "pet"; show("settings"); }})));
  },

  // 설정 → 펫 의 칸
  section() {
    const s = h("div", {class: "set-sec", id: "set-petrt"}, h("h2", {text: "펫 프로그램"}));
    const body = h("div", {id: "set-petrt-body"}, h("p", {class: "hint", text: "살펴보는 중이에요."}));
    s.appendChild(body);
    this.load().then(() => this.drawSection(body));
    return s;
  },

  drawSection(body) {
    const v = this.v;
    body.replaceChildren();
    if (!v) { body.appendChild(h("p", {class: "hint", text: "펫 프로그램 상태를 읽지 못했어요."})); return; }
    const st = h("p", {class: "hint", id: "set-petrt-state"});
    const prog = v["진행"];
    if (v["있음"] && !v["설치중"]) {
      body.append(h("p", {class: "hint", id: "set-petrt-ok", text: tr("펫 프로그램이 설치돼 있어요.") + (v["얼굴_펫"] ? "" : " " + tr("(지금은 펫을 쓰지 않게 설정돼 있어요.)"))}));
      if (prog && prog["끝"] && prog["성공"]) body.append(this.startRow(st), st);
      return;
    }
    const help = v["직접받기"] || {};
    const a = this.winApi();
    const failed = !v["설치중"] && prog && prog["끝"] && !prog["성공"] && prog["오류"];
    if (failed) {
      const e = prog["오류"];
      body.append(notice("bad", "펫을 이번에도 받지 못했어요", "까닭: " + (e["까닭"] || e["이유"] || "") + " " + tr("다시 눌러 보거나 '직접 넣기'를 써 주세요.")));
    } else {
      body.append(notice("warn", "펫이 아직 없어요", "설치할 때 펫을 받지 못했어요. 대화는 그대로 쓸 수 있어요."));
    }
    const row = h("div", {class: "row"});
    const get = h("button", {class: "btn primary", type: "button", id: "set-petrt-get", text: "펫 다시 받기", onclick: () => this.install(null, body)});
    row.append(get);
    const man = h("button", {class: "btn", type: "button", id: "set-petrt-manual", text: "직접 넣기", onclick: () => { this.manualOpen = !this.manualOpen; this.drawSection(body); }});
    if (help["주소"]) row.append(man);
    if (failed && a && typeof a.open_logs === "function") row.appendChild(h("button", {class: "btn", type: "button", id: "set-petrt-logs", text: "기록 폴더 열기", onclick: () => a.open_logs()}));
    body.append(row, st);
    let b1 = null, file = null;
    if (help["주소"] && this.manualOpen) {
      // 직접 넣기: 두 단추를 차례로
      b1 = h("button", {class: "btn", type: "button", id: "set-petrt-browser", text: "① 브라우저로 펫 파일 받기", onclick: () => this.openBrowser(help["주소"], st)});
      file = h("button", {class: "btn", type: "button", id: "set-petrt-file", text: "② 받은 파일 고르기", onclick: () => this.pickFile(body)});
      body.append(h("div", {class: "set-sub", id: "set-petrt-how"},
        h("p", {class: "hint", text: "인터넷에서 펫 파일이 받아지지 않을 때 쓰는 방법이에요. 두 단추를 차례로 눌러 주세요."}),
        h("div", {class: "row"}, b1, file),
        h("p", {class: "hint", text: tr("①은 브라우저가 열리고 파일을 받아요{0}. 이름을 바꾸거나 압축을 풀지 마세요. ②는 보통 '다운로드' 폴더에 있어요({1}).",
          {0: help["크기_글"] ? tr("(약 {0})", {0: help["크기_글"]}) : "", 1: help["파일"] || ""})}),
        h("div", {class: "row"}, h("button", {class: "btn ghost", type: "button", id: "set-petrt-copy", text: "주소 복사", onclick: () => this.copy(help["주소"], st)}))));
    }
    if (v["설치중"]) {
      get.disabled = man.disabled = true;
      if (b1) b1.disabled = file.disabled = true;
      st.textContent = (prog && prog["글"]) || "펫을 받는 중이에요.";
    }
  },

  startRow(st) {
    return h("div", {class: "row"}, h("button", {class: "btn primary", type: "button", id: "set-petrt-start", text: "지금 펫 켜기", onclick: () => this.start(st)}));
  },

  async copy(url, st) {
    try { await navigator.clipboard.writeText(url); st.textContent = "주소를 복사했어요. 브라우저 주소창에 붙여 넣으면 받아져요(다른 PC 에서 받아 옮겨도 돼요)."; }
    catch (_) { st.textContent = url; }
  },

  async openBrowser(url, st) {
    const a = this.winApi();
    let ok = false;
    if (a && typeof a.open_pet_download === "function") { try { ok = await a.open_pet_download(url); } catch (_) { ok = false; } }
    if (ok) st.textContent = "브라우저에서 받는 중이에요. 다 받으면 ②를 눌러 주세요.";
    else this.copy(url, st);      // 브라우저를 못 열면 주소를 복사해 줌
  },

  async pickFile(body) {
    const a = this.winApi();
    if (!a || typeof a.pick_zip !== "function") { toast("이 창에서는 파일을 고를 수 없어요. 김비서 창에서 해 주세요.", 6000); return; }
    let f = "";
    try { f = await a.pick_zip(); } catch (_) { f = ""; }
    if (f) this.install(f, body);
  },

  async install(file, body) {
    try {
      await api("/api/pet/install", file ? {"파일": file} : {});
    } catch (e) { toast("펫 받기를 시작하지 못했어요: " + e.message, 7000); return; }
    await this.load();
    if (body && body.isConnected) this.drawSection(body);
    this.poll(body);
  },

  poll(body) {
    clearInterval(this.timer);
    this.timer = setInterval(async () => {
      const was = this.v && this.v["설치중"];
      await this.load();
      const b = body && body.isConnected ? body : document.getElementById("set-petrt-body");
      if (b) this.drawSection(b);
      if (this.v && !this.v["설치중"]) {
        clearInterval(this.timer);
        const p = this.v["진행"];
        if (was && p && p["끝"] && p["성공"]) { this.manualOpen = false; toast("펫을 설치했어요.", 5000); this.start(document.getElementById("set-petrt-state")); }
      }
    }, 1000);
  },

  async start(st) {
    const a = this.winApi();
    if (!a || typeof a.start_pet !== "function") { if (st) st.textContent = "김비서를 껐다 다시 켜면 펫이 나와요."; return; }
    if (st) st.textContent = "펫을 켜는 중이에요.";
    let r = null;
    try { r = await a.start_pet(); } catch (_) { r = null; }
    if (st) st.textContent = r && r.ok ? tr("펫을 켰어요.") : tr("펫을 켜지 못했어요") + (r && r["이유"] ? ": " + r["이유"] : "") + " — " + tr("김비서를 껐다 다시 켜 보세요.");
    this.load();
  },
};
