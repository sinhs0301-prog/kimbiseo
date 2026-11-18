// 처음 화면(마법사) — 단추로만. 0 사양 → 1 펫 → 2 이름·호칭 → 3 두뇌 → 4 목소리 → 5 마이크·스피커 → 6 부르는 방식·이름 연습 → 7 끝
//   고른 값은 draft 에 모았다가 마지막에 한 번에 저장(/api/settings). 열쇠만 넣는 즉시 따로 저장(/api/secret — 설정 파일에 안 씀).
"use strict";

// ---------------------------------------------------------------- 이름 세 번 불러 보기(처음 화면·설정이 같이 씀)
function NamePractice(getName, onAliases, opts) {
  const o = Object.assign({times: 3}, opts || {});
  const heard = [];
  const box = h("div", {class: "practice"});
  const list = h("ul", {class: "heard", id: "np-heard"});
  const meter = h("div", {class: "meter"}, h("i"));
  const tags = h("div", {class: "tags", id: "np-aliases"});
  const msg = h("p", {class: "hint", id: "np-msg"});
  let aliases = [];
  const btn = h("button", {class: "btn primary big", type: "button", id: "np-rec"});
  const label = () => { btn.textContent = heard.length < o.times ? `이름 부르기 (${heard.length + 1}/${o.times})` : "한 번 더 부르기"; };
  const drawTags = () => {
    tags.replaceChildren();
    if (!aliases.length) { tags.appendChild(h("span", {class: "hint", text: "따로 저장할 비슷한 이름이 없어요(잘 알아들었다는 뜻이에요)."})); return; }
    aliases.forEach((a) => tags.appendChild(h("span", {class: "tag"}, a,
      h("button", {type: "button", "aria-label": a + " 빼기", text: "×", onclick: () => { aliases = aliases.filter((x) => x !== a); drawTags(); onAliases(aliases); }}))));
  };
  async function learn() {
    try {
      const r = await api("/api/name/learn", {"이름": getName(), "들은것": heard, "기존": o.keep ? o.keep() : []});
      aliases = r["별칭"] || [];
      msg.textContent = `${r["들은수"]}번 중 ${r["알아들음"]}번 이름으로 알아들었어요.` + (r["경고"] ? " " + r["경고"] : "");
      drawTags();
      onAliases(aliases);
    } catch (e) { msg.textContent = "비슷한 이름을 만들지 못했어요: " + e.message; }
  }
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    msg.textContent = `'${getName()}' 하고 불러 주세요. 듣고 있어요.`;
    let stream = null;
    try {
      stream = (await KAudio.openMic(get(K.cfg, "화면.마이크", ""))).stream;
      const r = await KAudio.recordUtterance(stream, {maxSec: 4, waitSec: 9, onLevel: (v) => { meter.firstChild.style.width = Math.round(v * 100) + "%"; }});
      if (!r.speech) { msg.textContent = "소리가 들리지 않았어요. 마이크 가까이에서 다시 불러 주세요."; return; }
      msg.textContent = "알아듣는 중이에요.";
      const q = "/api/ear/hear?name=" + encodeURIComponent(getName());
      const res = await api(q, r.pcm.buffer, true);
      const text = res["글"] || "(못 알아들음)";
      heard.push(res["글"] || "");
      const ok = res["부름"] || res["비슷"];
      list.appendChild(h("li", {class: ok ? "good" : "bad"}, `${heard.length}번째: "${text}"`, ok ? " — 이름으로 알아들었어요" : " — 비슷한 이름으로 저장해 둘게요"));
      msg.textContent = heard.length >= o.times ? "다 됐어요." : "좋아요. 한 번 더 불러 주세요.";
      if (heard.length >= o.times) await learn();
    } catch (e) {
      msg.textContent = (e.status === 503 ? "받아쓰기 서버가 꺼져 있어요. 이 단계는 건너뛰어도 돼요." : "녹음하지 못했어요: " + e.message);
    } finally {
      KAudio.stop(stream);
      meter.firstChild.style.width = "0%";
      btn.disabled = false;
      label();
    }
  });
  label();
  box.append(btn, meter, msg, list, h("p", {class: "big-q", text: "비슷한 이름(이렇게 들려도 깨어나요)"}), tags);
  box.reset = () => { heard.length = 0; aliases = []; list.replaceChildren(); tags.replaceChildren(); msg.textContent = ""; label(); };
  return box;
}

// 0단계에 보이는 '구독 두뇌' 한 줄
function subText(st) {
  if (!st) return "확인 못 함";
  const one = (n, label) => { const x = st[n] || {}; return label + " " + (!x["있음"] ? "없음" : x["로그인"] === true ? "로그인됨" : "로그인 필요"); };
  return one("claude", "클로드 코드") + " · " + one("codex", "Codex(GPT)");
}

// ---------------------------------------------------------------- 마법사
const Wizard = {
  i: 0, d: null, sys: null, brainTest: null,
  steps: ["언어·사양 보기", "펫", "이름·호칭", "두뇌", "목소리", "마이크·스피커", "부르는 방식", "끝"],

  start() {
    const c = K.cfg;
    this.d = {
      펫: {성별: get(c, "펫.성별", "여"), 옷: get(c, "펫.옷", "kimbiseo_f"), 옷_받기: get(c, "처음설정.끝", false) ? get(c, "펫.옷_받기", false) : null},
      비서: {이름: get(c, "비서.이름", "김비서"), 별칭: get(c, "비서.별칭", [])},
      사용자: {호칭: get(c, "사용자.호칭", ""), 기본장소: get(c, "사용자.기본장소", "서울")},
      두뇌: brainDraftFrom(c),
      목소리: {엔진: get(c, "목소리.엔진", "qwen"), 목소리: get(c, "목소리.목소리", "auto"), 말속도: get(c, "목소리.말속도", 1.0)},
      화면: {마이크: get(c, "화면.마이크", ""), 마이크_이름: get(c, "화면.마이크_이름", ""), 스피커: get(c, "화면.스피커", ""), 스피커_이름: get(c, "화면.스피커_이름", "")},
      대화: {이름부르기: get(c, "대화.이름부르기", false)},
      귀: {},
    };
    this.honorPicked = !!get(c, "처음설정.끝", false);
    this.i = 0;
    show("wizard");
    this.render();
  },

  render() {
    const v = document.getElementById("view-wizard");
    v.replaceChildren();
    const card = h("section", {class: "card", id: "wz-card", "data-step": String(this.i)});
    const bar = h("div", {class: "steps", "aria-hidden": "true"});
    this.steps.forEach((_, k) => bar.appendChild(h("span", {class: k < this.i ? "done" : k === this.i ? "now" : ""})));
    card.append(bar, h("p", {class: "step-no", text: `${this.i + 1} / ${this.steps.length} · ${this.steps[this.i]}`}));
    const body = h("div", {id: "wz-body"});
    card.appendChild(body);
    const prev = h("button", {class: "btn", type: "button", id: "wz-prev", text: "이전", disabled: this.i === 0, onclick: () => this.go(-1)});
    const next = h("button", {class: "btn primary big", type: "button", id: "wz-next",
      text: this.i === this.steps.length - 1 ? "시작하기" : "다음", onclick: () => this.go(1)});
    card.appendChild(h("div", {class: "row between"}, prev, next));
    v.appendChild(card);
    this["s" + this.i](body);
  },

  async go(step) {
    if (step > 0 && this.check && !this.check()) return;
    this.check = null;
    if (this.cleanup) { this.cleanup(); this.cleanup = null; }
    if (step > 0 && this.i === this.steps.length - 1) return this.finish();
    this.i = Math.max(0, Math.min(this.steps.length - 1, this.i + step));
    this.render();
  },

  // 0. 언어 → 사양
  async s0(b) {
    const cur = get(K.cfg, "언어", "ko");
    b.append(h("h1", {text: "언어를 골라 주세요"}),
      h("p", {text: "화면과 대화에 쓸 언어예요. 고르면 저장하고 화면을 다시 불러옵니다. 나중에 설정의 '일반'에서 바꿀 수 있어요."}),
      choiceGroup(Object.entries(I18N.NAMES).map(([code, name]) => ({값: code, 이름: name})), cur, async (v) => {
        if (v === cur) return;
        try { await saveSettings({언어: v}); location.reload(); }
        catch (e) { toast("저장하지 못했어요: " + e.message, 7000); }
      }, {wide: true, idp: "wz-lang"}));
    b.append(h("h1", {text: "반가워요. 김비서를 준비할게요"}),
      h("p", {text: "몇 가지만 고르면 바로 쓸 수 있어요. 모든 것은 나중에 설정에서 바꿀 수 있어요."}),
      h("p", {class: "big-q", text: "이 PC 를 살펴봤어요"}));
    const out = h("div", {id: "wz-sys"}, h("p", {class: "hint", text: "살펴보는 중이에요."}));
    b.appendChild(out);
    try {
      const s = this.sys || await api("/api/system");
      this.sys = s;
      const g = (s["그래픽카드"] || [])[0];
      const rec = s["추천"] || {};
      out.replaceChildren(h("dl", {class: "kv"},
        h("dt", {text: "그래픽카드"}), h("dd", {text: g ? `${g["이름"]} (${(g["전체_MiB"] / 1024).toFixed(0)}GB)` : "엔비디아 그래픽카드 없음"}),
        h("dt", {text: "메모리"}), h("dd", {text: s["메모리_GB"] ? s["메모리_GB"] + "GB" : "알 수 없음"}),
        h("dt", {text: "남은 디스크"}), h("dd", {text: s["디스크_여유_GB"] ? s["디스크_여유_GB"] + "GB" : "알 수 없음"}),
        h("dt", {text: "구독 두뇌"}), h("dd", {text: subText(s["구독"])})),
      notice("ok", "추천 구성: " + (rec["구성"] || ""), (rec["안내"] || []).join(" ")));
      if (!this.recApplied) {
        const st = rec["설정"] || {};
        if (st["목소리.엔진"]) this.d.목소리.엔진 = st["목소리.엔진"];
        if (st["두뇌.방식"]) this.d.두뇌.방식 = st["두뇌.방식"];
        if (st["귀.장치"]) this.d.귀.장치 = st["귀.장치"];
        if (st["목소리.장치"]) this.d.목소리.장치 = st["목소리.장치"];
        this.recApplied = true;
      }
    } catch (e) { out.replaceChildren(notice("warn", "사양을 보지 못했어요", e.message)); }
  },

  // 1. 펫
  s1(b) {
    const ch = K.choices;
    b.append(h("h1", {text: "화면에 나올 펫을 골라 주세요"}), h("p", {class: "big-q", text: "펫 성별"}));
    const pets = h("div", {id: "wz-pets"});
    const info = h("div", {id: "wz-pet-info"});
    const draw = () => {
      pets.replaceChildren(h("p", {class: "big-q", text: "캐릭터"}),
        choiceGroup(ch["펫"].filter((p) => p["성별"] === this.d.펫.성별).map((p) => ({값: p.id, 이름: p["이름"] + (p["준비"] ? "" : " (준비 중)"), 설명: p["설명"]})),
          this.d.펫.옷, (v) => { this.d.펫.옷 = v; }, {wide: true, idp: "wz-pet"}));
      const p = ch["펫"].find((x) => x.id === this.d.펫.옷);
      info.replaceChildren();
      if (p && !p["준비"]) info.appendChild(notice("warn", "이 캐릭터는 아직 준비 중이에요", "준비되면 펫 메뉴의 '옷 더 받기'에서 받을 수 있어요. 그 전까지는 준비된 기본 펫이 화면에 나와요."));
      const vRec = (ch["성별_추천"][this.d.펫.성별] || {})["목소리"];
      const vInfo = ch["목소리"].find((x) => x.id === vRec);
      if (vInfo && !vInfo["준비"]) info.appendChild(notice("warn", "어울리는 목소리도 준비 중이에요", `준비되기 전까지는 '${(ch["목소리"].find((x) => x["준비"]) || {})["이름"] || "기본 목소리"}'로 말해요.`));
    };
    b.appendChild(choiceGroup([{값: "여", 이름: "여자"}, {값: "남", 이름: "남자"}], this.d.펫.성별, (v) => {
      this.d.펫.성별 = v;
      const r = ch["성별_추천"][v] || {};
      if (r["펫"]) this.d.펫.옷 = r["펫"];
      draw();
    }, {idp: "wz-gender", label: "펫 성별"}));
    b.append(pets, info, h("p", {class: "hint", text: "목소리는 펫이 입은 옷에 맞춰 자동으로 바뀌어요(목소리 화면에서 직접 고를 수도 있어요). 나를 부르는 말(호칭)은 다음 화면에서 직접 골라요."}));
    draw();
    // 옷 받기 동의 — 펫의 옷(영상 꾸러미)은 프로그램 안에 없어서 인터넷에서 받아야 함. 고르기 전에는 다음으로 못 감.
    const src = get(K.cfg, "펫.옷목록_주소", "");
    b.append(h("p", {class: "big-q", text: "펫 옷을 지금 받을까요?"}),
      choiceGroup([{값: true, 이름: "받을게요", 설명: "고른 캐릭터의 기본 옷(춤은 소리 없이) 약 150~170MB 를 인터넷에서 받아요"},
        {값: false, 이름: "나중에", 설명: "펫 메뉴의 '옷 더 받기'에서 언제든 받을 수 있어요"}],
      this.d.펫.옷_받기, (v) => { this.d.펫.옷_받기 = v; }, {wide: true, idp: "wz-pack"}),
      src ? h("p", {class: "hint", text: "받는 곳: " + src}) : notice("warn", "옷 받는 곳이 아직 정해지지 않았어요", "'받을게요'를 골라 두면 받는 곳이 정해진 뒤 펫이 저절로 받아요. 옷 파일이 있으면 펫 메뉴에서 '파일로 옷 추가'로 넣을 수 있어요."));
    this.check = () => {
      if (this.d.펫.옷_받기 === null) { toast("펫 옷을 지금 받을지 골라 주세요."); return false; }
      return true;
    };
  },

  // 2. 이름·호칭
  s2(b) {
    const ch = K.choices;
    b.append(h("h1", {text: "이름과 호칭을 정해 주세요"}));
    const nameIn = h("input", {type: "text", id: "wz-name", maxlength: "12", value: this.d.비서.이름});
    const warn = h("div", {id: "wz-name-warn"});
    let t = null;
    nameIn.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        const v = nameIn.value.trim();
        warn.replaceChildren();
        if (!v) return;
        try { const r = await api("/api/name/check", {"이름": v}); if (r["경고"]) warn.appendChild(notice("warn", "이 이름은 조심하세요", r["경고"])); } catch (_) { /* 검사 실패는 넘어감 */ }
      }, 300);
    });
    b.append(field("비서 이름", nameIn, "아무 이름이나 돼요(예: 김비서, 엘리스). 부르면 깨어나는 이름이자 자기소개 이름이에요."), warn);
    b.appendChild(h("p", {class: "big-q", text: "나를 뭐라고 부를까요?"}));
    const custom = h("input", {type: "text", id: "wz-honor-custom", maxlength: String(ch["호칭_최대_글자"] || 10), placeholder: "직접 입력(예: 선생님)"});
    // 호칭은 미리 골라 두지 않음(성별로 짐작하지 않음) — 단추를 누르거나 직접 넣어야 다음으로 감. 처음 설정을 이미 끝낸 뒤 다시 열면 저장된 값이 고른 것.
    const btns = ch["호칭_단추"] || [];
    const isBtn = btns.includes(this.d.사용자.호칭) || !this.d.사용자.호칭;
    if (this.honorPicked && !isBtn) custom.value = this.d.사용자.호칭;
    const grp = choiceGroup(btns.map((x) => ({값: x, 이름: x})).concat([{값: "", 이름: "부르지 않기"}]), this.honorPicked && isBtn ? this.d.사용자.호칭 : null,
      (v) => { this.d.사용자.호칭 = v; this.honorPicked = true; custom.value = ""; }, {idp: "wz-honor", label: "호칭"});
    custom.addEventListener("input", () => { this.d.사용자.호칭 = custom.value.trim(); this.honorPicked = !!this.d.사용자.호칭; grp.select("\u0000"); });
    b.append(grp, field("직접 입력", custom));
    const place = h("input", {type: "text", id: "wz-place", maxlength: "30", value: this.d.사용자.기본장소});
    b.appendChild(field("사는 곳(날씨를 물을 때 기본 장소)", place));
    this.check = () => {
      const n = nameIn.value.trim();
      if (!n) { toast("비서 이름을 넣어 주세요."); return false; }
      if (!this.honorPicked) { toast("나를 뭐라고 부를지 골라 주세요. 부르지 않기도 고를 수 있어요."); return false; }
      if (n !== this.d.비서.이름) this.d.비서.별칭 = [];
      this.d.비서.이름 = n;
      this.d.사용자.기본장소 = place.value.trim();
      return true;
    };
  },

  // 3. 두뇌 — 이 PC 에 로그인된 구독 두뇌가 있으면 0단계에서 이미 골라 둠(추천)
  s3(b) {
    const ch = K.choices;
    b.append(h("h1", {text: "두뇌(대답하는 AI)를 골라 주세요"}));
    if (this.brainPanel) this.brainPanel.stop();
    this.brainPanel = BrainPanel(this.d.두뇌, {idp: "wz-brain", onTest: (r) => { this.brainTest = r; }});
    b.append(this.brainPanel, h("p", {class: "big-q", text: "대답 방식"}),
      choiceGroup(ch["두뇌_모드"].map((x) => ({값: x.id, 이름: x["이름"], 설명: x["설명"]})), this.d.두뇌.모드, (v) => { this.d.두뇌.모드 = v; }, {wide: true, idp: "wz-mode"}),
      h("p", {class: "hint", text: "연결이 안 돼도 다음으로 갈 수 있어요. 나중에 설정의 '두뇌'에서 언제든 바꿀 수 있어요."}));
    this.cleanup = () => { if (this.brainPanel) { this.brainPanel.stop(); this.brainPanel = null; } };
  },

  brainDraft() {
    return brainPack(this.d.두뇌);
  },

  // '들어 보기'에 쓸 목소리 — '옷에 맞춤(자동)'이면 아직 저장 전이라 지금 고른 펫 성별에 어울리는 목소리로 들려줌
  sampleVoice() {
    const v = this.d.목소리.목소리;
    return v === "auto" ? ((K.choices["성별_추천"][this.d.펫.성별] || {})["목소리"] || "kimbiseo") : v;
  },

  // 4. 목소리
  s4(b) {
    const ch = K.choices;
    const rec = (this.sys && this.sys["추천"]) || {};
    b.append(h("h1", {text: "목소리를 골라 주세요"}));
    const warn = h("div", {id: "wz-voice-warn"});
    const drawWarn = () => {
      warn.replaceChildren();
      if (this.d.목소리.엔진 === "qwen" && rec["목소리_경고"]) warn.appendChild(notice("warn", "이 PC 에서는 무거울 수 있어요", rec["목소리_경고"]));
    };
    b.appendChild(choiceGroup(ch["목소리_엔진"].map((x) => ({값: x.id, 이름: x["이름"] + ((rec["설정"] || {})["목소리.엔진"] === x.id ? " (추천)" : ""), 설명: x["설명"]})),
      this.d.목소리.엔진, (v) => { this.d.목소리.엔진 = v; drawWarn(); }, {wide: true, idp: "wz-engine"}));
    b.appendChild(warn);
    b.append(h("p", {class: "big-q", text: "목소리 견본"}),
      choiceGroup(ch["목소리"].map((x) => ({값: x.id, 이름: x["이름"] + (x["준비"] ? "" : " (준비 중)"), 설명: x["설명"], 막음: !x["준비"]})), this.d.목소리.목소리,
        (v) => { this.d.목소리.목소리 = v; }, {wide: true, idp: "wz-voice"}));
    b.append(h("p", {class: "big-q", text: "말 빠르기"}),
      choiceGroup(ch["말속도"].map((x) => ({값: x, 이름: x === 1 ? "보통" : x + "배"})), this.d.목소리.말속도, (v) => { this.d.목소리.말속도 = v; }, {idp: "wz-speed"}));
    const st = h("p", {class: "hint", id: "wz-voice-status"});
    b.append(h("div", {class: "row"}, h("button", {class: "btn primary", type: "button", id: "wz-voice-play", text: "들어 보기", onclick: () => playSample(this.sampleVoice(), st)})), st);
    drawWarn();
  },

  // 5. 마이크·스피커
  s5(b) {
    b.append(h("h1", {text: "마이크와 스피커를 확인해요"}),
      h("p", {text: "'마이크 켜기'를 누르면 마이크를 쓸지 물어볼 수 있어요. '허용'을 눌러 주세요."}));
    const micSel = h("select", {id: "wz-mic"}), spkSel = h("select", {id: "wz-spk"});
    const meter = h("div", {class: "meter", id: "wz-meter"}, h("i"));
    const aec = h("div", {id: "wz-aec"});
    const heard = h("p", {class: "hint", id: "wz-heard"});
    let stream = null, stopMeter = null;
    const close = () => { if (stopMeter) stopMeter(); stopMeter = null; KAudio.stop(stream); stream = null; };
    this.cleanup = close;
    const fill = async () => {
      const dv = await KAudio.devices();
      micSel.replaceChildren(h("option", {value: "", text: "기본 마이크"}), ...dv.mics.filter((m) => m.id !== "default" && m.id !== "communications").map((m) => h("option", {value: m.id, text: m.label})));
      spkSel.replaceChildren(h("option", {value: "", text: "기본 스피커"}), ...dv.spks.filter((m) => m.id !== "default" && m.id !== "communications").map((m) => h("option", {value: m.id, text: m.label})));
      micSel.value = this.d.화면.마이크 || ""; if (micSel.value !== (this.d.화면.마이크 || "")) micSel.value = "";
      spkSel.value = this.d.화면.스피커 || ""; if (spkSel.value !== (this.d.화면.스피커 || "")) spkSel.value = "";
    };
    const open = async () => {
      close();
      try {
        const m = await KAudio.openMic(micSel.value);
        stream = m.stream;
        const d = KAudio.describe(m.info);
        aec.replaceChildren(d.aec ? notice("ok", "메아리 지우기가 켜졌어요", d.lines.join(" · "))
          : notice("bad", "메아리 지우기가 꺼져 있어요", d.lines.join(" · ") + ". 스피커 소리를 비서가 자기 말로 잘못 들을 수 있어요. 이어폰을 쓰시거나 다른 마이크를 골라 주세요."));
        aec.dataset.aec = String(d.aec);
        stopMeter = KAudio.meter(stream, (v) => { meter.firstChild.style.width = Math.round(v * 100) + "%"; });
        await fill();
      } catch (e) {
        aec.replaceChildren(notice("bad", "마이크를 열지 못했어요", e.name === "NotAllowedError" ? "마이크 사용을 허용해 주세요." : e.message));
      }
    };
    micSel.addEventListener("change", () => { this.d.화면.마이크 = micSel.value; this.d.화면.마이크_이름 = micSel.value ? micSel.selectedOptions[0].textContent : ""; open(); });
    spkSel.addEventListener("change", () => { this.d.화면.스피커 = spkSel.value; this.d.화면.스피커_이름 = spkSel.value ? spkSel.selectedOptions[0].textContent : ""; });
    const test = async () => {
      if (!stream) await open();
      if (!stream) return;
      heard.textContent = "아무 말이나 한 마디 해 보세요. 듣고 있어요.";
      const r = await KAudio.recordUtterance(stream, {maxSec: 5, waitSec: 9});
      if (!r.speech) { heard.textContent = "소리가 들리지 않았어요."; return; }
      try { const res = await api("/api/ear/hear", r.pcm.buffer, true); heard.textContent = `알아들은 말: "${res["글"] || "(없음)"}"`; }
      catch (e) { heard.textContent = e.status === 503 ? "소리는 들려요. 받아쓰기 서버가 아직 꺼져 있어 글로 바꾸지는 못했어요." : "받아쓰지 못했어요: " + e.message; }
    };
    const st = h("p", {class: "hint", id: "wz-spk-status"});
    b.append(h("div", {class: "row"}, h("button", {class: "btn primary", type: "button", id: "wz-mic-open", text: "마이크 켜기", onclick: open})),
      aec, meter, field("마이크", micSel), h("div", {class: "row"}, h("button", {class: "btn", type: "button", id: "wz-mic-test", text: "마이크 시험(말해 보기)", onclick: test})), heard,
      field("스피커", spkSel), h("div", {class: "row"}, h("button", {class: "btn", type: "button", id: "wz-spk-test", text: "스피커 시험", onclick: () => playSample(this.sampleVoice(), st, spkSel.value)})), st);
    fill();
    open();
  },

  // 6. 부르는 방식·이름 연습
  s6(b) {
    const name = this.d.비서.이름;
    b.append(h("h1", {text: "어떻게 부를까요?"}),
      choiceGroup([{값: true, 이름: `'${name}' 하고 이름을 불러야 대답`, 설명: "TV·주변 말에 끼어들지 않아요(추천)"},
        {값: false, 이름: "마이크 단추를 누르면 바로 대답", 설명: "이름 없이도 들리는 말에 대답해요"}],
      this.d.대화.이름부르기, (v) => { this.d.대화.이름부르기 = v; }, {wide: true, idp: "wz-wake"}),
      h("p", {class: "big-q", text: `'${name}' 하고 세 번 불러 보세요`}),
      h("p", {class: "hint", text: "받아쓰기가 이름을 어떻게 적는지 보고, 비슷하게 적힌 이름도 알아듣게 해 둬요."}));
    const keep = (this.d.비서.별칭 || []).slice();
    b.appendChild(NamePractice(() => this.d.비서.이름, (al) => { this.d.비서.별칭 = al; }, {keep: () => keep}));
    if ((this.d.비서.별칭 || []).length) b.appendChild(h("p", {class: "hint", text: "지금 저장된 비슷한 이름: " + this.d.비서.별칭.join(", ")}));
  },

  // 7. 끝
  s7(b) {
    const ch = K.choices, d = this.d;
    const brain = (ch["두뇌"].find((x) => x.id === d.두뇌.방식) || {})["이름"] || d.두뇌.방식;
    const eng = (ch["목소리_엔진"].find((x) => x.id === d.목소리.엔진) || {})["이름"] || d.목소리.엔진;
    const pet = (ch["펫"].find((x) => x.id === d.펫.옷) || {})["이름"] || d.펫.옷;
    b.append(h("h1", {text: "준비가 끝났어요"}), h("dl", {class: "kv", id: "wz-summary"},
      h("dt", {text: "비서 이름"}), h("dd", {text: d.비서.이름}),
      h("dt", {text: "나를 부르는 말"}), h("dd", {text: d.사용자.호칭 || "(부르지 않음)"}),
      h("dt", {text: "펫"}), h("dd", {text: `${pet} · ${d.펫.성별 === "남" ? "남자" : "여자"}`}),
      h("dt", {text: "펫 옷 받기"}), h("dd", {text: d.펫.옷_받기 ? "지금 받아요" : "나중에"}),
      h("dt", {text: "두뇌"}), h("dd", {text: `${brain} · ${d.두뇌.모드 === "꼼꼼" ? "꼼꼼 모드" : "빠른 모드"}`}),
      h("dt", {text: "목소리"}), h("dd", {text: `${eng} · ${d.목소리.말속도 === 1 ? "보통 빠르기" : d.목소리.말속도 + "배"}`}),
      h("dt", {text: "부르는 방식"}), h("dd", {text: d.대화.이름부르기 ? "이름을 불러야 대답" : "단추를 누르면 바로"}),
      h("dt", {text: "비슷한 이름"}), h("dd", {text: (d.비서.별칭 || []).join(", ") || "(없음)"})),
    notice("", "나중에 할 수 있는 것", "내 목소리 등록(내 목소리에만 대답)과 폰 연결은 다음 판에서 설정 화면에 생겨요."),
    h("p", {text: "'시작하기'를 누르면 저장하고 대화 화면으로 가요."}));
  },

  async finish() {
    const d = JSON.parse(JSON.stringify(this.d));
    delete d.목소리.원하는;
    d.두뇌 = this.brainDraft();
    if (!Object.keys(d.귀).length) delete d.귀;
    if (d.펫.옷_받기 === null) d.펫.옷_받기 = false;
    d.처음설정 = {끝: true};
    const btn = document.getElementById("wz-next");
    btn.disabled = true;
    try {
      await saveSettings(d);
      await brainApplyLauncher(false);
      show("main");
      Chat.sys(`${d.비서.이름} 준비가 끝났어요. 마이크 단추를 눌러 말을 걸어 보세요.`);
    } catch (e) {
      toast("저장하지 못했어요: " + e.message, 8000);
      btn.disabled = false;
    }
  },
};

async function playSample(voice, statusEl, sinkId) {
  const el = document.getElementById("sample");
  if (statusEl) statusEl.textContent = "목소리를 만드는 중이에요.";
  await KAudio.setSink(el, sinkId === undefined ? get(K.cfg, "화면.스피커", "") : sinkId);
  try {
    const blob = await api("/api/voice/sample", {"목소리": voice});
    el.src = URL.createObjectURL(blob);
    if (statusEl) statusEl.textContent = "들리시나요?";
  } catch (e) {
    el.src = KAudio.beepUrl();
    if (statusEl) statusEl.textContent = e.status === 503 ? "목소리 서버가 아직 꺼져 있어 '삐' 소리로 스피커만 확인해요." : "목소리를 만들지 못했어요: " + e.message;
  }
  el.play().catch(() => { if (statusEl) statusEl.textContent = "소리를 틀지 못했어요. 스피커를 확인해 주세요."; });
}
