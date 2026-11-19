// 업데이트 — 새 판이 나오면 대화 화면 위에 쉬운 말로 알리고, 누르면 받기 → 바꾸기(김비서가 잠깐 꺼졌다 다시 켜짐).
//   확인은 본체가 함(켤 때 하루 한 번까지 + 설정 '정보'의 '업데이트 확인'). 화면은 바깥 주소를 직접 부르지 않음.
"use strict";
const Update = {
  v: null,
  timer: null,

  async load() {
    try { this.v = await api("/api/update"); } catch (_) { return; }
    this.draw();
    if (this.v["하는중"] === "받는 중") this.poll();
  },

  onEvent(ev) { this.v = ev; this.draw(); if (ev["바꾸는중"]) this.applying(); },

  size(n) { return n >= 1048576 ? (n / 1048576).toFixed(1) + "MB" : Math.max(1, Math.round(n / 1024)) + "KB"; },

  // 대화 화면 위 알림
  draw() {
    const box = document.getElementById("update-box");
    const v = this.v;
    if (!box || !v) return;
    box.replaceChildren();
    const last = v["지난결과"];
    if (last) {
      box.className = "notice " + (last.ok ? "ok" : "bad");
      box.appendChild(h("strong", {text: last.ok ? `${last.to} 판으로 업데이트했어요.` : (last.rolled_back ? "업데이트가 잘 안 돼서 예전 판으로 되돌렸어요." : "업데이트를 하지 못했어요.")}));
      if (!last.ok && last.why) box.appendChild(h("p", {text: "이유: " + last.why}));   // '이유' 머리말은 사전에서 번역됨
      if (!last.ok) box.appendChild(h("p", {text: "대화 기억·설정은 그대로예요. 나중에 다시 해 볼 수 있어요."}));
      box.appendChild(h("div", {class: "row"}, h("button", {class: "btn", type: "button", id: "update-seen", text: "알겠어요",
        onclick: async () => { try { await api("/api/update/seen", {}); } catch (_) { /* 넘어감 */ } this.load(); }})));
      box.hidden = false;
      return;
    }
    const n = v["새판"];
    if (!n) { box.hidden = true; return; }
    box.className = "notice warn";
    box.hidden = false;
    box.appendChild(h("strong", {id: "update-title", text: `새 판 ${n["판"]} 이 나왔어요 (지금 ${v["지금_판"]})`}));
    const notes = n["바뀐점"] || [];
    if (notes.length) box.appendChild(h("ul", {class: "update-notes"}, ...notes.map((x) => h("li", {text: x}))));
    if (n["새설치필요"]) {
      box.appendChild(h("p", {text: "이번 판은 부품이 바뀌어서 새 설치 파일로 설치해야 해요. 설치하면 대화 기억·설정은 그대로 남아요."}));
      if (n["안내주소"]) box.appendChild(h("div", {class: "row"}, h("button", {class: "btn primary", type: "button", id: "update-page", text: "받는 곳 열기",
        onclick: () => api("/api/update/page", {}).catch((e) => toast(e.message))})));
      return;
    }
    const st = h("p", {class: "hint", id: "update-state"});
    const row = h("div", {class: "row"});
    if (v["하는중"] === "받는 중") {
      st.textContent = `받는 중이에요 ${Math.round(v["진행"] || 0)}%`;
    } else if (v["하는중"] === "바꾸는 중") {
      st.textContent = "새 판으로 바꾸는 중이에요. 김비서가 잠깐 꺼졌다 다시 켜져요.";
    } else if (v["준비됨"]) {
      st.textContent = "받아서 확인까지 끝났어요(서명·파일 확인). 바꾸는 동안 1~3분 김비서가 꺼졌다가 다시 켜져요. 대화 기억·설정·펫 옷은 그대로예요.";
      row.appendChild(h("button", {class: "btn primary", type: "button", id: "update-apply", text: "지금 바꾸고 다시 켜기", onclick: () => this.apply()}));
    } else {
      st.textContent = tr("받는 양 {0} · 대화 기억·설정·펫 옷·모델은 그대로 두고 프로그램만 바꿔요.", {0: this.size(n["크기"] || 0)}) + (v["오류"] ? " " + tr("(지난번: {0})", {0: v["오류"]}) : "");
      row.appendChild(h("button", {class: "btn primary", type: "button", id: "update-download", text: "업데이트 하기", onclick: () => this.download()}));
    }
    box.append(st, row);
  },

  async check(out) {
    if (out) out.replaceChildren(h("p", {class: "hint", text: "새 판이 있는지 보는 중이에요."}));
    try {
      this.v = await api("/api/update/check", {});
      const n = this.v["새판"];
      if (out) out.replaceChildren(n ? notice("warn", `새 판 ${n["판"]} 이 있어요`, "대화 화면 위의 '업데이트 하기'를 눌러 주세요.") : notice("ok", "지금이 최신 판이에요", `지금 판 ${this.v["지금_판"]}`));
    } catch (e) {
      if (e.data && e.data["지금_판"]) this.v = e.data;
      if (out) out.replaceChildren(notice("bad", "확인하지 못했어요", e.message));
    }
    this.draw();
  },

  async download() {
    try { await api("/api/update/download", {}); } catch (e) { toast("받지 못했어요: " + e.message, 7000); return; }
    this.poll();
  },

  poll() {
    clearTimeout(this.timer);
    this.timer = setTimeout(async () => {
      try { this.v = await api("/api/update"); } catch (_) { /* 본체가 바쁨 */ }
      this.draw();
      if (this.v && this.v["하는중"] === "받는 중") this.poll();
      else if (this.v && this.v["오류"] && !this.v["준비됨"]) toast("업데이트를 받지 못했어요: " + this.v["오류"], 8000);
    }, 700);
  },

  async apply() {
    if (!(await confirmBox("김비서를 잠깐 끄고 새 판으로 바꾼 뒤 다시 켤까요? 1~3분 걸려요.", "네, 바꿀게요"))) return;
    try { await api("/api/update/apply", {}); } catch (e) { toast("바꾸지 못했어요: " + e.message, 8000); return; }
    this.applying();
  },

  applying() {
    const box = document.getElementById("update-box");
    if (!box) return;
    box.className = "notice warn";
    box.hidden = false;
    box.replaceChildren(h("strong", {id: "update-title", text: "새 판으로 바꾸는 중이에요"}),
      h("p", {text: "김비서가 잠깐 꺼졌다가 다시 켜져요. 이 창은 닫혀도 괜찮아요. 잘 안 되면 예전 판으로 저절로 되돌려요."}));
  },
};
