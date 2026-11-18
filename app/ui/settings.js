// 설정 화면 — 칸마다 '저장'. 저장하면 본체가 바로 반영하고, 언제 바뀌는지(지금 / 다음 대화 / 다시 켜기 / 펫)를 알려 준다.
"use strict";
const Settings = {
  tab: "name",
  tabs: [["general", "일반"], ["name", "이름·호칭"], ["pet", "펫"], ["brain", "두뇌"], ["voice", "목소리"], ["mic", "마이크·스피커"], ["talk", "대화"], ["interp", "통역"], ["phone", "폰 연결"], ["myvoice", "내 목소리"], ["about", "정보"]],

  async render() {
    await loadSettings().catch(() => {});
    const v = document.getElementById("view-settings");
    v.replaceChildren();
    // 설정 판 머리줄: 제목 + 닫기(×)
    const x = h("button", {class: "hbtn", type: "button", id: "set-close", title: "닫기", onclick: () => show("main")}, h("span", {class: "sr", text: "닫기"}));
    x.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>');
    v.appendChild(h("h1", {class: "panel-head"}, "설정", x));
    const tabs = h("div", {class: "set-tabs", role: "tablist"});
    this.tabs.forEach(([id, label]) => tabs.appendChild(h("button", {class: "btn ghost" + (id === this.tab ? " active" : ""), type: "button", id: "set-tab-" + id,
      role: "tab", "aria-selected": String(id === this.tab), text: label, onclick: () => { this.tab = id; this.render(); }})));
    v.appendChild(tabs);
    const card = h("section", {class: "card", id: "set-card", "data-tab": this.tab});
    v.appendChild(card);
    if (this.stopMic) { this.stopMic(); this.stopMic = null; }
    Phone.stop(); MyVoice.stop();
    this["t_" + this.tab](card);
  },

  badge(keys) {
    const w = keys.map((k) => K.when[k]).filter(Boolean);
    if (w.some((x) => x.startsWith("다시켜기"))) return h("span", {class: "when restart", text: "다시 켜야 적용"});
    if (w.includes("다음대화")) return h("span", {class: "when next", text: "다음 대화부터"});
    if (w.includes("펫")) return h("span", {class: "when next", text: "펫을 다시 켜면"});
    return h("span", {class: "when now", text: "바로 적용"});
  },

  section(card, title, keys) {
    const s = h("div", {class: "set-sec"});
    s.appendChild(h("h2", {}, title, this.badge(keys)));
    card.appendChild(s);
    return s;
  },

  saveRow(id, collect) {
    return h("div", {class: "row end"}, h("button", {class: "btn primary", type: "button", id, text: "저장", onclick: async (e) => {
      e.target.disabled = true;
      try { const c = collect(); if (c) await saveSettings(c); } catch (err) { toast("저장하지 못했어요: " + err.message, 7000); }
      finally { e.target.disabled = false; }
    }}));
  },

  // 일반 — 언어(앱 화면·대화·받아쓰기). 바꾸면 저장한 뒤 화면을 다시 불러온다.
  t_general(card) {
    const c = K.cfg;
    card.appendChild(h("h1", {text: "일반"}));
    const s1 = this.section(card, "언어", ["언어"]);
    let lang = get(c, "언어", "ko");
    s1.append(h("p", {class: "hint", text: "화면과 대화에 쓰는 언어예요. 고르면 저장하고 화면을 다시 불러옵니다. 기존 사용자는 한국어 그대로예요."}),
      choiceGroup(Object.entries(I18N.NAMES).map(([code, name]) => ({값: code, 이름: name})), lang, async (v) => {
        if (v === lang) return;
        try { await saveSettings({언어: v}); location.reload(); }
        catch (err) { toast("저장하지 못했어요: " + err.message, 7000); }
      }, {wide: true, idp: "set-lang"}));
    const s2 = this.section(card, "받아쓰기 언어", ["귀.받아쓰기_언어"]);
    let ear = get(c, "귀.받아쓰기_언어", "");
    const items = [{값: "", 이름: "앱 언어 따름"}, {값: "auto", 이름: "자동 감지"}]
      .concat(Object.entries(I18N.NAMES).map(([code, name]) => ({값: code, 이름: name})));
    s2.append(h("p", {class: "hint", text: "말을 글로 바꿀 때 쓰는 언어예요. 보통은 '앱 언어 따름'이 좋아요."}),
      choiceGroup(items, ear, (v) => { ear = v; }, {wide: true, idp: "set-earlang"}),
      this.saveRow("set-earlang-save", () => ({귀: {받아쓰기_언어: ear}})));
  },

  // 이름·호칭
  t_name(card) {
    const ch = K.choices, c = K.cfg;
    card.appendChild(h("h1", {text: "이름·호칭"}));
    const s1 = this.section(card, "비서 이름", ["비서.이름"]);
    const nameIn = h("input", {type: "text", id: "set-name", maxlength: "12", value: get(c, "비서.이름", "김비서")});
    let aliases = (get(c, "비서.별칭", []) || []).slice();
    const tags = h("div", {class: "tags", id: "set-aliases"});
    const drawTags = () => {
      tags.replaceChildren();
      if (!aliases.length) tags.appendChild(h("span", {class: "hint", text: "(없음)"}));
      aliases.forEach((a) => tags.appendChild(h("span", {class: "tag"}, a, h("button", {type: "button", "aria-label": a + " 빼기", text: "×",
        onclick: () => { aliases = aliases.filter((x) => x !== a); drawTags(); }}))));
    };
    drawTags();
    const warn = h("div", {id: "set-name-warn"});
    nameIn.addEventListener("change", async () => {
      warn.replaceChildren();
      try { const r = await api("/api/name/check", {"이름": nameIn.value.trim()}); if (r["경고"]) warn.appendChild(notice("warn", "이 이름은 조심하세요", r["경고"])); } catch (_) { /* 넘어감 */ }
    });
    s1.append(field("비서 이름(깨우는 이름·자기소개)", nameIn), warn, h("p", {class: "big-q", text: "비슷한 이름(이렇게 들려도 깨어나요)"}), tags);
    const practiceBox = h("div", {});
    let practicedFor = null;
    s1.append(h("div", {class: "row"}, h("button", {class: "btn", type: "button", id: "set-practice", text: "이름 세 번 불러 보기", onclick: () => {
      practicedFor = nameIn.value.trim() || get(c, "비서.이름", "김비서");
      const keep = practicedFor === get(c, "비서.이름") ? aliases.slice() : [];
      practiceBox.replaceChildren(NamePractice(() => practicedFor, (al) => { aliases = al; drawTags(); }, {keep: () => keep}));
    }})), practiceBox);
    s1.appendChild(this.saveRow("set-name-save", () => {
      const n = nameIn.value.trim();
      if (!n) { toast("이름을 넣어 주세요."); return null; }
      if (n === get(c, "비서.이름")) return {비서: {이름: n, 별칭: aliases}};
      return {비서: {이름: n, 별칭: practicedFor === n ? aliases : []}};
    }));

    const s2 = this.section(card, "나를 부르는 말", ["사용자.호칭"]);
    let honor = get(c, "사용자.호칭", "");
    const btns = ch["호칭_단추"] || [];
    const custom = h("input", {type: "text", id: "set-honor-custom", maxlength: String(ch["호칭_최대_글자"] || 10), placeholder: "직접 입력",
      value: btns.includes(honor) ? "" : honor});
    const grp = choiceGroup(btns.map((x) => ({값: x, 이름: x})).concat([{값: "", 이름: "부르지 않기"}]), btns.includes(honor) || !honor ? honor : null,
      (v) => { honor = v; custom.value = ""; }, {idp: "set-honor"});
    custom.addEventListener("input", () => { honor = custom.value.trim(); grp.select("\u0000"); });
    const place = h("input", {type: "text", id: "set-place", maxlength: "30", value: get(c, "사용자.기본장소", "")});
    s2.append(grp, field("직접 입력", custom), field("사는 곳(날씨 기본 장소)", place));
    s2.appendChild(this.saveRow("set-honor-save", () => ({사용자: {호칭: honor, 기본장소: place.value.trim()}})));

    // 말투·성격·답 길이 — 두뇌 지시문에 들어감(지금 대화에도 바로)
    const s3 = this.section(card, "말투와 성격", ["비서.말투", "비서.성격", "비서.답길이"]);
    let tone = get(c, "비서.말투", "auto"), len = get(c, "비서.답길이", "보통");
    const toneNow = get(c, "비서.말투_해석", null);
    const toneHint = h("p", {class: "hint", id: "set-tone-now",
      text: toneNow && toneNow["자동"] ? `지금은 펫 성별(${toneNow["성별"]})에 맞춰 '${toneNow["말투"]}'로 말해요. 다른 말투를 골라 저장하면 그 말투로 고정돼요.`
        : "지금은 고른 말투로 고정돼 있어요. '자동'을 고르면 펫 성별에 맞춰 바뀌어요."});
    const maxLen = ch["성격_최대_글자"] || 200;
    const persona = h("textarea", {id: "set-persona", maxlength: String(maxLen), rows: "3",
      placeholder: "예: 밝고 장난기가 많아요. 칭찬을 자주 해 줘요."});
    persona.value = get(c, "비서.성격", "");
    const count = h("span", {class: "hint", id: "set-persona-count"});
    const drawCount = () => { count.textContent = `${persona.value.length} / ${maxLen}글자`; };
    persona.addEventListener("input", drawCount);
    drawCount();
    const chips = h("div", {class: "tags", id: "set-persona-examples"}, (ch["성격_예시"] || []).map((x) => h("button", {type: "button", class: "tag pick", text: x, onclick: () => {
      const cur = persona.value.trim();
      if (cur.includes(x)) return;
      persona.value = (cur ? cur.replace(/[.\s]*$/, ". ") : "") + x + ".";
      if (persona.value.length > maxLen) persona.value = persona.value.slice(0, maxLen);
      drawCount();
    }})));
    const dropBox = h("div", {id: "set-persona-warn"});
    const drawDrop = (list) => {
      dropBox.replaceChildren();
      if (list && list.length) dropBox.appendChild(notice("warn", "이 문장은 두뇌에 전달하지 않아요", list.map((x) => `'${x}'`).join(" · ") + " — 성격 설명에는 말투·분위기만 적어 주세요. 규칙을 바꾸는 말은 따르지 않아요."));
    };
    drawDrop(get(c, "비서.성격_빠짐", []));
    s3.append(h("p", {class: "big-q", text: "말투"}),
      choiceGroup((ch["말투"] || []).map((x) => ({값: x.id, 이름: x["이름"], 설명: x["설명"]})), tone, (v) => { tone = v; }, {wide: true, idp: "set-tone"}), toneHint,
      h("p", {class: "big-q", text: "답 길이"}),
      choiceGroup((ch["답길이"] || []).map((x) => ({값: x.id, 이름: x["이름"], 설명: x["설명"]})), len, (v) => { len = v; }, {idp: "set-length"}),
      h("p", {class: "big-q", text: "성격 설명(자유롭게)"}),
      h("p", {class: "hint", text: "어떤 분위기로 말하면 좋을지 적어 주세요. 말투와 분위기에만 반영돼요(도구 쓰는 법이나 기본 규칙은 바뀌지 않아요)."}),
      persona, h("div", {class: "row between"}, count), chips, dropBox);
    s3.appendChild(h("div", {class: "row end"}, h("button", {class: "btn primary", type: "button", id: "set-persona-save", text: "저장", onclick: async (e) => {
      e.target.disabled = true;
      try {
        const r = await saveSettings({비서: {말투: tone, 답길이: len, 성격: persona.value.trim()}});
        drawDrop(get(r["설정"], "비서.성격_빠짐", []));
      } catch (err) { toast("저장하지 못했어요: " + err.message, 7000); }
      finally { e.target.disabled = false; }
    }})));
  },

  // 펫
  t_pet(card) {
    const ch = K.choices, c = K.cfg;
    card.appendChild(h("h1", {text: "펫"}));
    const s = this.section(card, "펫 성별과 캐릭터", ["펫.성별"]);
    let sex = get(c, "펫.성별", "여"), pet = get(c, "펫.옷", "kimbiseo_f");
    const list = h("div", {});
    const draw = () => list.replaceChildren(choiceGroup(ch["펫"].filter((p) => p["성별"] === sex).map((p) => ({값: p.id, 이름: p["이름"] + (p["준비"] ? "" : " (준비 중)"), 설명: p["설명"]})),
      pet, (v) => { pet = v; }, {wide: true, idp: "set-pet"}));
    s.append(choiceGroup([{값: "여", 이름: "여자"}, {값: "남", 이름: "남자"}], sex, (v) => {
      sex = v; pet = ((ch["성별_추천"] || {})[v] || {})["펫"] || pet; draw();
    }, {idp: "set-gender"}), list, h("p", {class: "hint", text: "성별을 바꾸면 어울리는 말투로 바뀌고, 목소리는 펫이 입은 옷에 맞춰 자동으로 바뀌어요(직접 고른 경우는 그대로). 고른 캐릭터의 옷이 아직 없으면 펫이 받아 와요(옷 받기에 동의했을 때). 호칭은 '이름·호칭'에서 바꿔요."}));
    draw();
    s.appendChild(this.saveRow("set-pet-save", () => ({펫: {성별: sex, 옷: pet}})));

    // 펫 크기 — 펫이 제 설정에 기억함(펫 오른쪽 클릭 메뉴의 '크기'와 같은 값). 펫이 켜져 있을 때만 바꿀 수 있음.
    const s2 = h("div", {class: "set-sec", id: "set-petsize"}, h("h2", {}, "펫 크기", h("span", {class: "when now", text: "바로 적용"})));
    card.appendChild(s2);
    const box = h("div", {id: "set-petsize-box"}, h("p", {class: "hint", text: "펫을 살펴보는 중이에요."}));
    s2.appendChild(box);
    api("/api/pet/size").then((j) => {
      box.replaceChildren();
      if (!j.ok) { box.appendChild(h("p", {class: "hint", id: "set-petsize-off", text: j["오류"] || "펫이 꺼져 있어요."})); return; }
      const lo = (j["범위"] || [50, 200])[0], hi = (j["범위"] || [50, 200])[1];
      let pct = Number(j["퍼센트"] || 100);
      const label = (p) => `${p}%`;
      const out = h("output", {id: "set-petsize-out", for: "set-petsize-range", text: label(pct)});
      const range = h("input", {type: "range", id: "set-petsize-range", min: String(lo), max: String(hi), step: "5", value: String(pct), "aria-valuetext": label(pct)});
      const send = async (p) => {
        p = Math.min(hi, Math.max(lo, Math.round(Number(p) / 5) * 5));
        try {
          const r = await api("/api/pet/size", {"퍼센트": p});
          pct = Number(r["퍼센트"] || p);
          range.value = String(pct); out.textContent = label(pct); range.setAttribute("aria-valuetext", label(pct));
        } catch (e) { toast("펫 크기를 바꾸지 못했어요: " + e.message, 6000); }
      };
      range.addEventListener("input", () => { out.textContent = label(range.value); });
      range.addEventListener("change", () => send(range.value));
      box.append(h("div", {class: "slider"},
        h("div", {class: "slider-head"}, h("label", {for: "set-petsize-range", text: "펫 크기"}), out), range,
        h("div", {class: "slider-ends"}, h("span", {text: label(lo)}), h("span", {text: "보통 100%"}), h("span", {text: label(hi)}))),
      h("div", {class: "row"}, [["작게", 76], ["보통", 100], ["크게", 132], ["아주 크게", 172]].map(([n, p]) =>
        h("button", {class: "btn", type: "button", id: "set-petsize-" + p, text: n, onclick: () => send(p)}))),
      h("p", {class: "hint", text: "펫을 오른쪽 클릭하면 나오는 메뉴의 '크기'와 같은 설정이에요. 화면보다 크게는 커지지 않아요."}));
    }).catch(() => { box.replaceChildren(h("p", {class: "hint", text: "펫 크기를 읽지 못했어요."})); });
    card.appendChild(PetRuntime.section());
  },

  // 두뇌 — 두뇌 바꾸기(구독 클로드·구독 GPT·Gemma·내 로컬 AI·API 열쇠) — brain.js
  t_brain(card) {
    const ch = K.choices, c = K.cfg;
    card.appendChild(h("h1", {text: "두뇌"}));
    const s = this.section(card, "두뇌 바꾸기", ["두뇌.방식"]);
    const d = brainDraftFrom(c);
    if (this.brainPanel) this.brainPanel.stop();
    this.brainPanel = BrainPanel(d, {idp: "set-brain", showGemma: true});
    s.append(this.brainPanel, h("div", {class: "row end"}, h("button", {class: "btn primary", type: "button", id: "set-brain-save", text: "저장", onclick: async (e) => {
      e.target.disabled = true;
      try {
        const o = brainPack(d); delete o.모드;
        const r = await saveSettings({두뇌: o});
        if ((r["바뀜"] || []).includes("두뇌.방식")) {
          if (o.방식 === "local") toast("이 PC 의 Gemma 를 켜는 중이에요. 1~2분 걸릴 수 있어요.", 8000);
          const a = await brainApplyLauncher(false);
          if (a && a.ok && o.방식 === "local") toast("Gemma 가 켜졌어요.", 5000);
          if (a && a.ok === false && a["이유"]) toast("두뇌 프로그램을 켜지 못했어요: " + a["이유"], 9000);
        }
      } catch (err) { toast("저장하지 못했어요: " + err.message, 7000); }
      finally { e.target.disabled = false; }
    }})));
    const s2 = this.section(card, "대답 방식", ["두뇌.모드"]);
    let mode = get(c, "두뇌.모드", "빠른");
    s2.append(choiceGroup(ch["두뇌_모드"].map((x) => ({값: x.id, 이름: x["이름"], 설명: x["설명"]})), mode, (v) => { mode = v; }, {wide: true, idp: "set-mode"}),
      this.saveRow("set-mode-save", () => ({두뇌: {모드: mode}})));
  },

  // 목소리
  t_voice(card) {
    const ch = K.choices, c = K.cfg;
    card.appendChild(h("h1", {text: "목소리"}));
    const s1 = this.section(card, "목소리 종류", ["목소리.엔진"]);
    let eng = get(c, "목소리.엔진", "qwen");
    s1.append(choiceGroup(ch["목소리_엔진"].map((x) => ({값: x.id, 이름: x["이름"], 설명: x["설명"]})), eng, (v) => { eng = v; }, {wide: true, idp: "set-engine"}),
      this.saveRow("set-engine-save", () => ({목소리: {엔진: eng}})));
    const s2 = this.section(card, "목소리 견본과 빠르기", ["목소리.목소리", "목소리.말속도"]);
    let voice = get(c, "목소리.목소리", "auto"), speed = get(c, "목소리.말속도", 1.0);
    const st = h("p", {class: "hint", id: "set-voice-status"});
    let vdSpeedSet = null;      // 아래 '세부 설정'의 말 빠르기 슬라이더와 같은 값을 가리킴
    const speedGrp = choiceGroup(ch["말속도"].map((x) => ({값: x, 이름: x === 1 ? "보통" : x + "배"})), speed, (v) => { speed = v; if (vdSpeedSet) vdSpeedSet(v, true); }, {idp: "set-speed"});
    s2.append(choiceGroup(ch["목소리"].map((x) => ({값: x.id, 이름: x["이름"] + (x["준비"] ? "" : " (준비 중)"), 설명: x["설명"], 막음: !x["준비"]})), voice, (v) => { voice = v; }, {wide: true, idp: "set-voice"}),
      h("p", {class: "big-q", text: "말 빠르기"}),
      speedGrp,
      h("div", {class: "row"}, h("button", {class: "btn", type: "button", id: "set-voice-play", text: "들어 보기", onclick: () => playSample(voice, st)})), st);
    const vh = get(c, "목소리.해석", null);
    if (vh && vh["대체"] && vh["이유"]) s2.append(notice("warn", "목소리 참고음성이 아직 없어요", vh["이유"]));
    else if (vh && vh["자동"]) s2.append(h("p", {class: "hint", text: "지금은 펫이 입은 옷(펫이 꺼져 있으면 펫 성별)에 맞춰 목소리를 자동으로 고르고 있어요. 다른 목소리를 골라 저장하면 그 목소리로 고정돼요."}));
    else if (vh && vh["고정"]) s2.append(h("p", {class: "hint", text: "지금은 고른 목소리로 고정돼 있어요. '옷에 맞춤(자동)'을 고르면 펫 옷을 갈아입을 때 목소리도 같이 바뀌어요."}));
    s2.append(this.saveRow("set-voice-save", () => ({목소리: {목소리: voice, 말속도: speed}})));

    // 세부 설정 — 온도·쉼·빠르기. 슬라이더라 범위 밖 값은 넣을 수 없고, 본체·목소리 서버도 범위를 한 번 더 막는다.
    const rows = ch["목소리_세부"] || [];
    if (rows.length) {
      const s4 = this.section(card, "세부 설정", rows.filter((r) => r.key !== "top_k").map((r) => "목소리." + r.key));
      s4.id = "set-vd";
      const vals = {}, ctl = {};
      const fmt = (r, v) => (r["정수"] ? String(Math.round(v)) : Number(v).toFixed(2)) + (r["단위"] || "");
      s4.appendChild(h("p", {class: "hint", text: "김비서 목소리가 말하는 느낌을 조금씩 바꿀 수 있어요. 잘 모르겠으면 그대로 두세요 — '기본값으로'를 누르면 처음 값으로 돌아가요."}));
      rows.forEach((r) => {
        const key = r.key, cur = Number(get(c, "목소리." + key, r["기본"]));
        vals[key] = cur;
        const out = h("output", {id: `set-vd-${key}-out`, for: `set-vd-${key}`, text: fmt(r, cur)});
        const range = h("input", {type: "range", id: `set-vd-${key}`, min: String(r.min), max: String(r.max), step: String(r.step), value: String(cur),
          "aria-valuetext": fmt(r, cur)});
        const set = (v, fromPreset) => {
          v = Math.min(r.max, Math.max(r.min, Number(v)));          // 범위 밖 값은 받지 않음
          vals[key] = r["정수"] ? Math.round(v) : Math.round(v * 1000) / 1000;
          range.value = String(vals[key]); out.textContent = fmt(r, vals[key]); range.setAttribute("aria-valuetext", fmt(r, vals[key]));
          if (key === "말속도" && !fromPreset) { speed = vals[key]; speedGrp.select(vals[key]); }   // 위의 빠르기 단추와 맞춤
        };
        if (key === "말속도") vdSpeedSet = set;
        range.addEventListener("input", () => set(range.value));
        ctl[key] = {set, def: r["기본"]};
        const off = r["엔진"] === "qwen" && get(c, "목소리.엔진", "qwen") === "windows";
        s4.appendChild(h("div", {class: "slider" + (off ? " off" : ""), "data-key": key},
          h("div", {class: "slider-head"}, h("label", {for: range.id, text: r["이름"]}), out),
          range,
          h("div", {class: "slider-ends"}, h("span", {text: fmt(r, r.min)}), h("span", {text: window.tr ? tr("기본 {0}", {0: fmt(r, r["기본"])}) : "기본 " + fmt(r, r["기본"])}), h("span", {text: fmt(r, r.max)})),
          h("p", {class: "hint", text: (window.tr ? tr(r["설명"]) : r["설명"]) + (off ? (window.tr ? " " + tr("(지금 고른 윈도우 기본 음성에는 쓰이지 않아요.)") : " (지금 고른 윈도우 기본 음성에는 쓰이지 않아요.)") : "")})));
      });
      const st2 = h("p", {class: "hint", id: "set-vd-status"});
      const collect = () => { const o = {}; rows.forEach((r) => { o[r.key] = vals[r.key]; }); return {목소리: o}; };
      const save = async (btn, after) => {
        btn.disabled = true;
        try { await saveSettings(collect()); if (after) await after(); }
        catch (err) { toast("저장하지 못했어요: " + err.message, 7000); }
        finally { btn.disabled = false; }
      };
      const sample = async () => {
        const el = document.getElementById("sample");
        st2.textContent = "목소리를 만드는 중이에요.";
        try {
          await KAudio.setSink(el, get(K.cfg, "화면.스피커", ""));
          const blob = await api("/api/voice/sample", {"목소리": voice, "글": "안녕하세요. 지금은 오후 3시 30분이에요. 오늘 할 일은 2개, 내일은 12개월 만의 휴가예요."});
          el.src = URL.createObjectURL(blob);
          st2.textContent = "바꾼 값으로 말해 봤어요. 마음에 들지 않으면 '기본값으로'를 눌러 주세요.";
          el.play().catch(() => { st2.textContent = "소리를 틀지 못했어요. 스피커를 확인해 주세요."; });
        } catch (e) { st2.textContent = e.status === 503 ? "목소리 서버가 꺼져 있어요. 김비서를 다시 켠 뒤 들어 보세요." : "목소리를 만들지 못했어요: " + e.message; }
      };
      s4.append(h("div", {class: "row end"},
        h("button", {class: "btn", type: "button", id: "set-vd-reset", text: "기본값으로", onclick: (e) => { rows.forEach((r) => ctl[r.key].set(r["기본"])); save(e.target); }}),
        h("button", {class: "btn", type: "button", id: "set-vd-play", text: "저장하고 들어 보기", onclick: (e) => save(e.target, sample)}),
        h("button", {class: "btn primary", type: "button", id: "set-vd-save", text: "저장", onclick: (e) => save(e.target)})), st2);
    }
    const s3 = this.section(card, "받아쓰기(귀) 장치", ["귀.장치"]);
    let ear = get(c, "귀.장치", "auto");
    s3.append(h("p", {class: "hint", text: "보통은 '자동'이 가장 빨라요. CPU 로 하면 그래픽 메모리를 두뇌·김비서 목소리에 남기지만, 한 문장 받아쓰는 데 몇 초 더 걸려요."}),
      choiceGroup((ch["귀_장치"] || []).map((x) => ({값: x.id, 이름: x["이름"], 설명: x["설명"]})), ear, (v) => { ear = v; }, {wide: true, idp: "set-ear"}),
      this.saveRow("set-ear-save", () => ({귀: {장치: ear}})));
  },

  // 마이크·스피커
  t_mic(card) {
    const c = K.cfg;
    card.appendChild(h("h1", {text: "마이크·스피커"}));
    const s = this.section(card, "쓸 장치", ["화면.마이크"]);
    const micSel = h("select", {id: "set-mic"}), spkSel = h("select", {id: "set-spk"});
    const aec = h("div", {id: "set-aec"}), meter = h("div", {class: "meter"}, h("i"));
    let stream = null, stopM = null;
    this.stopMic = () => { if (stopM) stopM(); stopM = null; KAudio.stop(stream); stream = null; };
    const fill = async () => {
      const dv = await KAudio.devices();
      micSel.replaceChildren(h("option", {value: "", text: "기본 마이크"}), ...dv.mics.filter((m) => !["default", "communications"].includes(m.id)).map((m) => h("option", {value: m.id, text: m.label})));
      spkSel.replaceChildren(h("option", {value: "", text: "기본 스피커"}), ...dv.spks.filter((m) => !["default", "communications"].includes(m.id)).map((m) => h("option", {value: m.id, text: m.label})));
      micSel.value = get(c, "화면.마이크", ""); if (!micSel.value) micSel.value = "";
      spkSel.value = get(c, "화면.스피커", ""); if (!spkSel.value) spkSel.value = "";
    };
    const open = async () => {
      this.stopMic();
      try {
        const m = await KAudio.openMic(micSel.value);
        stream = m.stream;
        const d = KAudio.describe(m.info);
        aec.dataset.aec = String(d.aec);
        aec.replaceChildren(d.aec ? notice("ok", "메아리 지우기가 켜져 있어요", d.lines.join(" · ")) : notice("bad", "메아리 지우기가 꺼져 있어요", d.lines.join(" · ") + ". 이어폰을 쓰시거나 다른 마이크를 골라 주세요."));
        stopM = KAudio.meter(stream, (v) => { meter.firstChild.style.width = Math.round(v * 100) + "%"; });
        if (!micSel.options.length || micSel.options.length < 2) await fill();
      } catch (e) { aec.replaceChildren(notice("bad", "마이크를 열지 못했어요", e.message)); }
    };
    micSel.addEventListener("change", open);
    const st = h("p", {class: "hint", id: "set-spk-status"});
    s.append(h("div", {class: "row"}, h("button", {class: "btn", type: "button", id: "set-mic-open", text: "마이크 켜서 확인", onclick: open})), aec, meter,
      field("마이크", micSel), field("스피커", spkSel),
      h("div", {class: "row"}, h("button", {class: "btn", type: "button", id: "set-spk-test", text: "스피커 시험", onclick: () => playSample(get(c, "목소리.목소리", "kimbiseo"), st, spkSel.value)})), st,
      this.saveRow("set-mic-save", () => ({화면: {마이크: micSel.value, 마이크_이름: micSel.value ? micSel.selectedOptions[0].textContent : "",
        스피커: spkSel.value, 스피커_이름: spkSel.value ? spkSel.selectedOptions[0].textContent : ""}})));
    fill().then(open);
  },

  // 대화
  t_talk(card) {
    const ch = K.choices, c = K.cfg;
    card.appendChild(h("h1", {text: "대화"}));
    const s1 = this.section(card, "끼어들기 감도", ["대화.끼어들기_감도"]);
    let lv = get(c, "대화.끼어들기_감도", 0.3);
    s1.append(h("p", {class: "hint", text: "비서가 말할 때 내 말로 끊는 정도예요. 시끄러운 곳일수록 TV·주변 소리로 잘못 끊기지 않게 높여 주세요."}),
      choiceGroup(ch["끼어들기_감도"].map((x) => ({값: x["값"], 이름: `${x["값"]} ${x["이름"]}`, 설명: x["설명"]})), lv, (v) => { lv = v; }, {wide: true, idp: "set-barge"}),
      this.saveRow("set-barge-save", () => ({대화: {끼어들기_감도: lv}})));
    const s2 = this.section(card, "부르는 방식", ["대화.이름부르기"]);
    let wake = !!get(c, "대화.이름부르기", false);
    s2.append(choiceGroup([{값: true, 이름: "이름을 불러야 대답", 설명: "TV·주변 말에 끼어들지 않아요"}, {값: false, 이름: "단추를 누르면 바로 대답"}], wake, (v) => { wake = v; }, {wide: true, idp: "set-wake"}),
      this.saveRow("set-wake-save", () => ({대화: {이름부르기: wake}})));
    const s3 = this.section(card, "글자 크기", ["화면.글자"]);
    let font = get(c, "화면.글자", "크게");
    s3.append(choiceGroup(["보통", "크게", "아주 크게"].map((x) => ({값: x, 이름: x})), font, (v) => { font = v; setFont(v); }, {idp: "set-font"}),
      this.saveRow("set-font-save", () => ({화면: {글자: font}})));
    const s4 = this.section(card, "기억", ["기억.켜기"]);
    const box = (id, label, key) => { const i = h("input", {type: "checkbox", id}); i.checked = !!get(c, key, true); return [h("label", {class: "toggle", for: id}, i, label), i]; };
    const [l1, i1] = box("set-mem-on", "대화 내용을 기억하기", "기억.켜기");
    const [l2, i2] = box("set-mem-auto", "대화에서 중요한 사실을 저절로 기억하기", "기억.자동");
    const [l3, i3] = box("set-mem-diary", "대화가 끝나면 짧은 일기 남기기", "기억.일기");
    s4.append(l1, l2, l3, h("div", {class: "row"}, h("button", {class: "btn", type: "button", text: "기억 보기·지우기", onclick: () => show("memory")})),
      this.saveRow("set-mem-save", () => ({기억: {켜기: i1.checked, 자동: i2.checked, 일기: i3.checked}})));
    const s5 = this.section(card, "말싸움(토론)", ["말싸움.성인"]);
    const adultBox = h("input", {type: "checkbox", id: "set-debate-adult"});
    adultBox.checked = !!get(c, "말싸움.성인", false);
    adultBox.addEventListener("change", () => {
      if (adultBox.checked && !confirm("성인 말싸움은 19세 이상만 쓰세요. 욕설·막말·섹드립이 나옵니다. 켤까요?")) adultBox.checked = false;
    });
    s5.append(h("p", {class: "hint", text: "말로 '말싸움 하자'라고 하면 켜지고, '말싸움 그만'·'평소로'라고 하면 꺼져요. 켜진 동안에는 이름·주소·전화·기억 같은 개인 정보를 두뇌에 넘기지 않고, 검색·날씨·계산 도구만 써요. 30분 동안 말이 없으면 저절로 꺼져요."}),
      h("p", {class: "hint", text: "말싸움 중에는 반말·센 말·비꼬기·도발로 받아쳐요. 아래를 켜면 실제 욕설·막말·과장된 위협 드립·섹드립까지 허용해요(PC 판만, 폰 앱 대화에서는 항상 꺼져요)."}),
      h("label", {class: "toggle", for: "set-debate-adult"}, adultBox, "성인 말싸움(19세 이상)"),
      this.saveRow("set-debate-save", () => ({말싸움: {성인: adultBox.checked}})));
  },

  // 통역(interp.js)
  t_interp(card) { Interp.settings(card); },

  // 폰 연결·내 목소리(phone.js)
  t_phone(card) { Phone.settings(card); },
  t_myvoice(card) { MyVoice.settings(card); },

  // 정보
  t_about(card) {
    const info = K.choices["정보"] || {};
    card.append(h("h1", {text: "정보"}), h("dl", {class: "kv", id: "set-about"},
      h("dt", {text: "프로그램"}), h("dd", {text: info["프로그램"] || "김비서"}),
      h("dt", {text: "판"}), h("dd", {id: "set-version", text: (Update.v && Update.v["지금_판"]) || ""}),
      h("dt", {text: "만든 곳"}), h("dd", {text: info["만든_곳"] || ""}),
      h("dt", {text: "사용 조건"}), h("dd", {text: info["라이선스"] || ""}),
      h("dt", {text: "내 자료"}), h("dd", {text: "설정·기억·열쇠는 모두 이 PC 안에만 저장돼요."})),
    h("div", {class: "row"}, h("button", {class: "btn", type: "button", id: "set-wizard", text: "처음 화면 다시 하기", onclick: () => Wizard.start()})));
    const s = h("div", {class: "set-sec"}, h("h2", {text: "업데이트"}));
    card.appendChild(s);
    const out = h("div", {id: "set-update-result"});
    const last = Update.v && Update.v["마지막_확인"];
    s.append(h("p", {class: "hint", text: (window.tr ? tr("새 판이 나오면 김비서를 켤 때(하루 한 번) 알려 드려요. 대화 기억·설정·펫 옷·모델은 그대로 두고 프로그램만 바꿔요.") : "새 판이 나오면 김비서를 켤 때(하루 한 번) 알려 드려요. 대화 기억·설정·펫 옷·모델은 그대로 두고 프로그램만 바꿔요.")
      + (last ? (window.tr ? " " + tr("마지막 확인: {0}", {0: last}) : ` 마지막 확인: ${last}`) : "")}),
      h("div", {class: "row"}, h("button", {class: "btn", type: "button", id: "set-update-check", text: "업데이트 확인", onclick: () => Update.check(out)})), out);
    if (!Update.v) Update.load().then(() => { const e = document.getElementById("set-version"); if (e && Update.v) e.textContent = Update.v["지금_판"]; });
  },
};
