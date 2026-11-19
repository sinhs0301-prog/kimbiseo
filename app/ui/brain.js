// 두뇌 바꾸기 — 처음 화면(3단계)과 설정 '두뇌'가 같이 씀.
//   구독 클로드 / 구독 GPT : 이 PC 의 claude·codex 설치·로그인 상태(/api/brain/options) · '로그인 창 열기' · 설치 안내 · 연결 시험
//   내 PC(Gemma)          : 설치됨·크기·판 · 판 고르기(E4B 보통 / E2B 가벼움) · 'Gemma 설치·다시 설치·이 판으로 바꾸기'(받는 중 진행) · 'Gemma 삭제'
//   내 로컬 AI 주소 / API 열쇠 GPT·클로드 : 주소·모델·열쇠(이 PC 에만 암호로 저장)
//   OpenAI 호환 API(compat)  : 바깥 서비스 주소·모델·내 API 열쇠 · '모델 목록 불러오기' · 대화가 그 서비스로 간다는 알림
"use strict";

function brainDraftFrom(c) {
  const kind = get(c, "두뇌.방식", "local");
  return {방식: kind, 주소: kind === "url" ? get(c, "두뇌.주소", "") : "", 모델: get(c, "두뇌.모델", ""), 모드: get(c, "두뇌.모드", "빠른"),
    호환_주소: get(c, "두뇌.호환_주소", ""), 호환_모델: get(c, "두뇌.호환_모델", ""),
    openai_모델: get(c, "두뇌.openai_모델", ""), claude_모델: get(c, "두뇌.claude_모델", "claude-opus-5-5"),
    구독_클로드_모델: get(c, "두뇌.구독_클로드_모델", "haiku"), 구독_GPT_생각: get(c, "두뇌.구독_GPT_생각", "")};
}

// 저장할 두뇌 값(그 방식에 맞는 것만)
function brainPack(d) {
  const o = {방식: d.방식};
  if (d.모드) o.모드 = d.모드;
  if (d.방식 === "url") { o.주소 = d.주소 || ""; o.모델 = d.모델 || ""; }
  if (d.방식 === "compat") { o.호환_주소 = d.호환_주소 || ""; o.호환_모델 = d.호환_모델 || ""; }
  if (d.방식 === "openai" && d.openai_모델) o.openai_모델 = d.openai_모델;
  if (d.방식 === "claude") o.claude_모델 = d.claude_모델;
  if (d.방식 === "claude_cli") o.구독_클로드_모델 = d.구독_클로드_모델 || "haiku";
  if (d.방식 === "codex_cli") o.구독_GPT_생각 = d.구독_GPT_생각 || "";
  return o;
}

// 실행 관리(창)에 알림: Gemma 면 두뇌 프로그램을 켜고, 아니면 끔
async function brainApplyLauncher(restart) {
  const py = window.pywebview && window.pywebview.api;
  if (!py || typeof py.apply_brain !== "function") return null;
  try { return await py.apply_brain(!!restart); } catch (_) { return null; }
}

// d = 고르는 중인 두뇌 값(바꾸면 그 자리에서 바뀜) · opts.idp = 단추 id 앞글자 · opts.onPick(방식)
function BrainPanel(d, opts) {
  const ch = K.choices, idp = (opts && opts.idp) || "brain";
  const box = h("div", {class: "brain-panel", id: idp + "-panel"});
  const detail = h("div", {id: idp + "-detail"}), result = h("div", {id: idp + "-result"});
  let opt = null, poll = null, gemmaSize = null;   // gemmaSize = 고른 Gemma 판(E4B·E2B)
  const loadOpt = async (fresh) => {
    try { opt = await api("/api/brain/options" + (fresh ? "?fresh=1" : "")); } catch (_) { opt = null; }
    return opt;
  };
  const keyRow = (name, label) => {
    const inp = h("input", {type: "password", id: idp + "-key-" + name, autocomplete: "off",
      placeholder: get(K.cfg, "열쇠." + name) ? "저장된 열쇠가 있어요(바꾸려면 새로 넣기)" : "열쇠를 붙여 넣으세요"});
    return h("div", {}, field(label, inp, "열쇠는 이 PC 에만 암호로 저장되고, 화면·기록에 보이지 않아요."), h("div", {class: "row"},
      h("button", {class: "btn", type: "button", id: idp + "-key-save-" + name, text: "열쇠 저장", onclick: async () => {
        try {
          const r = await api("/api/secret", {"이름": name, "값": inp.value}); inp.value = "";
          K.cfg.열쇠 = K.cfg.열쇠 || {}; K.cfg.열쇠[name] = r["있음"];
          toast(r["있음"] ? "열쇠를 이 PC 에만 저장했어요." : "열쇠를 지웠어요.");
        } catch (e) { toast("저장하지 못했어요: " + e.message); }
      }})));
  };
  const subRow = (name) => {     // name = "claude" | "codex"
    const st = opt && opt["구독"] ? opt["구독"][name] : null;
    const wrap = h("div", {id: idp + "-sub-" + name});
    if (!st) { wrap.appendChild(h("p", {class: "hint", text: "이 PC 의 로그인 상태를 살펴보는 중이에요."})); return wrap; }
    const label = name === "claude" ? "클로드 코드" : "Codex(GPT)";
    const kind = !st["있음"] ? "bad" : st["로그인"] === true ? "ok" : "warn";
    const title = !st["있음"] ? `${label} 설치 안 됨` : st["로그인"] === true ? `${label} 로그인됨` + (st["판"] ? ` · ${st["판"]}` : "")
      : `${label} 로그인이 필요해요`;
    wrap.appendChild(notice(kind, title, st["안내"] || ""));
    const row = h("div", {class: "row"});
    if (st["있음"] && st["로그인"] !== true) {
      row.appendChild(h("button", {class: "btn primary", type: "button", id: idp + "-login-" + name, text: "로그인 창 열기", onclick: async () => {
        try { const r = await api("/api/brain/login", {"이름": name}); toast(r["안내"], 8000); } catch (e) { toast(e.message, 8000); }
      }}));
    }
    row.appendChild(h("button", {class: "btn", type: "button", id: idp + "-recheck-" + name, text: "다시 확인", onclick: async () => {
      await loadOpt(true); draw();
    }}));
    wrap.appendChild(row);
    return wrap;
  };
  const gemmaRow = () => {
    const wrap = h("div", {id: idp + "-gemma"});
    const g = opt && opt["Gemma"];
    if (!g) { wrap.appendChild(h("p", {class: "hint", text: "Gemma 상태를 살펴보는 중이에요."})); return wrap; }
    const pr = g["진행"];
    if (g["설치중"] || (pr && !pr["끝"])) {
      wrap.appendChild(notice("", tr("Gemma 받는 중") + (pr && pr["전체"] != null ? ` · ${pr["전체"]}%` : ""), (pr && pr["글"]) || tr("준비하는 중이에요.")));
      if (!poll) poll = setInterval(async () => {
        try { const s = await api("/api/brain/gemma/status"); opt["Gemma"] = s; } catch (_) { /* 다음에 */ }
        const p2 = opt["Gemma"]["진행"];
        if (!opt["Gemma"]["설치중"] && (!p2 || p2["끝"])) {
          clearInterval(poll); poll = null;
          if (p2 && p2["성공"]) { toast("Gemma 설치가 끝났어요.", 6000); if (d.방식 === "local") brainApplyLauncher(true); }
          else if (p2 && p2["오류"]) toast("Gemma 를 받지 못했어요: " + (p2["오류"]["이유"] || ""), 9000);
        }
        if (d.방식 === "local") draw();
      }, 1500);
      return wrap;
    }
    if (g["있음"]) {
      wrap.appendChild(notice("ok", tr("Gemma 설치됨") + ` · ${g["판"] ? g["판"] + " · " : ""}${g["크기_GB"]}GB` + (g["무검열"] ? " · " + tr("무검열 판") : ""),
        tr("이 PC 에서 돌아요. 대화가 밖으로 나가지 않아요.") + (g["무검열"] ? " " + tr("무검열 판이라 거르지 않은 답이 나올 수 있어요.") : "")));
    } else {
      wrap.appendChild(notice("warn", "Gemma 가 설치돼 있지 않아요", "'Gemma 설치'를 누르면 원래 배포처(허깅페이스)에서 고른 판을 받아요."));
    }
    const sizes = ch["Gemma_판"] || [];
    const size = gemmaSize || g["판"] || (sizes[0] || {}).id || "E4B";
    const sz = sizes.find((x) => x.id === size) || {};
    if (sizes.length) {
      wrap.appendChild(h("p", {class: "big-q", text: "Gemma 판"}));
      wrap.appendChild(choiceGroup(sizes.map((x) => ({값: x.id, 이름: x["이름"] + (g["있음"] && g["판"] === x.id ? " (설치됨)" : ""), 설명: x["설명"]})),
        size, (v) => { gemmaSize = v; draw(); }, {wide: true, idp: idp + "-gemma-size"}));
    }
    const change = g["있음"] && g["판"] && g["판"] !== size;
    if (pr && pr["끝"] && !pr["성공"] && pr["오류"]) wrap.appendChild(notice("bad", "지난번 설치가 멈췄어요", pr["오류"]["이유"] || ""));
    const row = h("div", {class: "row"});
    row.appendChild(h("button", {class: "btn" + (g["있음"] ? "" : " primary"), type: "button", id: idp + "-gemma-install",
      text: change ? `${size} 판으로 바꾸기` : g["있음"] ? "Gemma 다시 설치" : "Gemma 설치", onclick: async () => {
        if (g["있음"] && !(await confirmBox(`Gemma ${size} 판을 ${change ? "받을" : "다시 받을"}까요? 약 ${sz["크기_GB"] || 5}GB 를 받고, 다 받으면 다른 Gemma 파일은 지워요.`,
          change ? "바꾸기" : "다시 받기"))) return;
        try { await api("/api/brain/gemma/install", {"판": size}); opt["Gemma"]["설치중"] = true; opt["Gemma"]["진행"] = {끝: false}; draw(); }
        catch (e) { toast("시작하지 못했어요: " + e.message, 8000); }
      }}));
    if (g["폴더"] && g["폴더"].length) {
      row.appendChild(h("button", {class: "btn", type: "button", id: idp + "-gemma-remove", text: "Gemma 삭제", onclick: async () => {
        if (get(K.cfg, "두뇌.방식") === "local") { toast("지금 두뇌가 Gemma 예요. 먼저 다른 두뇌를 고르고 저장한 뒤 지워 주세요.", 8000); return; }
        if (!(await confirmBox(`Gemma 파일(약 ${g["크기_GB"]}GB)과 두뇌 프로그램을 지울까요? 다시 쓰려면 다시 받아야 해요.`, "지우기"))) return;
        try {
          await brainApplyLauncher(false);
          const r = await api("/api/brain/gemma/remove", {});
          opt["Gemma"] = r["Gemma"];
          toast(r.ok ? `지웠어요. ${r["돌려준"]} 를 돌려받았어요.` : `일부를 못 지웠어요(${(r["못지움"] || []).join(", ")}). 김비서를 껐다 켠 뒤 다시 해 주세요.`, 8000);
          draw();
        } catch (e) { toast(e.message, 8000); }
      }}));
    }
    wrap.appendChild(row);
    return wrap;
  };
  const draw = () => {
    detail.replaceChildren();
    const k = d.방식;
    if (k === "claude_cli") {
      detail.append(subRow("claude"), h("p", {class: "big-q", text: "모델"}),
        choiceGroup(ch["구독_클로드_모델"].map((x) => ({값: x.id, 이름: x["이름"], 설명: x["설명"]})), d.구독_클로드_모델 || "haiku",
          (v) => { d.구독_클로드_모델 = v; }, {wide: true, idp: idp + "-cmodel"}));
    } else if (k === "codex_cli") {
      detail.append(subRow("codex"), h("p", {class: "big-q", text: "생각 정도"}),
        choiceGroup(ch["구독_GPT_생각"].map((x) => ({값: x.id, 이름: x["이름"], 설명: x["설명"]})), d.구독_GPT_생각 || "",
          (v) => { d.구독_GPT_생각 = v; }, {wide: true, idp: idp + "-geffort"}));
    } else if (k === "url") {
      const a = h("input", {type: "url", id: idp + "-addr", value: d.주소 || "", placeholder: "예: http://127.0.0.1:1234/v1"});
      const m = h("input", {type: "text", id: idp + "-model", value: d.모델 || "", placeholder: "모델 이름"});
      a.addEventListener("input", () => { d.주소 = a.value.trim(); });
      m.addEventListener("input", () => { d.모델 = m.value.trim(); });
      detail.append(field("주소(OpenAI 호환)", a), field("모델 이름", m), keyRow("url", "열쇠(필요할 때만)"));
    } else if (k === "compat") {
      // OpenAI 호환 API: 주소 · 모델(직접 넣거나 목록에서 고름) · 내 API 열쇠
      const a = h("input", {type: "url", id: idp + "-compat-addr", value: d.호환_주소 || "", placeholder: "예: https://api.서비스이름.com/v1", autocomplete: "off"});
      const m = h("input", {type: "text", id: idp + "-compat-model", value: d.호환_모델 || "", placeholder: "모델 이름(그 서비스의 안내에 나온 이름)", autocomplete: "off"});
      const list = h("div", {class: "tags", id: idp + "-compat-models"});
      const note = h("p", {class: "hint", id: idp + "-compat-note"});
      a.addEventListener("input", () => { d.호환_주소 = a.value.trim(); });
      m.addEventListener("input", () => { d.호환_모델 = m.value.trim(); });
      const load = h("button", {class: "btn", type: "button", id: idp + "-compat-load", text: "모델 목록 불러오기", onclick: async () => {
        note.textContent = "불러오는 중이에요."; list.replaceChildren();
        try {
          const r = await api("/api/brain/models", {"두뇌": {방식: "compat", 호환_주소: d.호환_주소 || ""}});
          if (!r.ok) { note.textContent = r["오류"] || "불러오지 못했어요."; return; }
          const all = r["모델"] || [];
          note.textContent = tr("모델 {0}개 — 눌러서 고르세요.", {0: all.length}) + (all.length > 40 ? " " + tr("(많아서 앞의 40개만 보여요. 이름을 직접 넣어도 돼요)") : "");
          for (const id of all.slice(0, 40)) {
            list.appendChild(h("button", {class: "tag pick", type: "button", text: id, onclick: () => { m.value = id; d.호환_모델 = id; }}));
          }
        } catch (e) { note.textContent = e.message; }
      }});
      detail.append(field("주소(OpenAI 호환)", a, "그 서비스가 알려 주는 'OpenAI 호환 주소(base URL)'를 넣어요. 보통 /v1 로 끝나요."),
        keyRow("compat", "API 열쇠"), field("모델 이름", m), h("div", {class: "row"}, load), note, list);
    } else if (k === "openai") {
      const m = h("input", {type: "text", id: idp + "-gpt-model", value: d.openai_모델 || "", placeholder: "모델 이름(예: gpt-5.6-luna)"});
      m.addEventListener("input", () => { d.openai_모델 = m.value.trim(); });
      detail.append(field("GPT 모델 이름", m), keyRow("openai", "OpenAI API 열쇠"));
    } else if (k === "claude") {
      detail.append(h("p", {class: "big-q", text: "클로드 모델"}),
        choiceGroup(ch["클로드_모델"].map((x) => ({값: x, 이름: x})), d.claude_모델, (v) => { d.claude_모델 = v; }, {idp: idp + "-claude"}),
        keyRow("claude", "Anthropic API 열쇠"));
    }
    if (k === "local" || (opts && opts.showGemma)) detail.appendChild(gemmaRow());
    if (k === "compat") detail.appendChild(notice("warn", "알아 두세요", "이 방식을 고르면 대화 글(묻는 말·김비서의 답·도구가 찾아온 내용)이 그 주소의 서비스로 보내져요. "
      + "요금과 대화 보관 방식은 그 서비스의 약관을 따라요. 열쇠는 이 PC 에만 암호화해서 저장하고(윈도우 계정으로만 풀 수 있어요), 화면·기록에는 남기지 않아요."));
    else if (k !== "local") detail.appendChild(notice("warn", "알아 두세요", "이 방식을 고르면 대화 글이 그 회사나 그 서버로 보내져요."));
  };
  const group = h("div", {});
  const drawGroup = () => group.replaceChildren(choiceGroup(ch["두뇌"].map((x) => ({값: x.id,
    이름: tr(x["이름"]) + (opt && opt["제안"] === x.id ? " " + tr("(로그인됨 · 추천)") : ""), 설명: x["설명"]})), d.방식, (v) => {
    d.방식 = v; result.replaceChildren(); draw(); if (opts && opts.onPick) opts.onPick(v);
  }, {wide: true, idp}));
  drawGroup();
  box.append(group, detail, h("div", {class: "row"}, h("button", {class: "btn primary", type: "button", id: idp + "-test", text: "연결 시험", onclick: async () => {
    result.replaceChildren(h("p", {class: "hint", text: d.방식.endsWith("_cli") ? "구독 두뇌에 물어보는 중이에요(처음엔 몇 초 걸려요)." : "물어보는 중이에요."}));
    try {
      const r = await api("/api/brain/test", {"두뇌": brainPack(d)});
      if (opts && opts.onTest) opts.onTest(r);
      const extra = r["첫글자_ms"] ? ` · 첫 글자 ${(r["첫글자_ms"] / 1000).toFixed(1)}초` : "";
      result.replaceChildren(r.ok ? notice("ok", `연결됐어요 (${(r.ms / 1000).toFixed(1)}초${extra})`, `답: "${r["답"]}"` + (r["도구"] === true ? " · 도구 부르기도 돼요." : ""))
        : notice("bad", "연결이 안 돼요", r["오류"] || ""));
    } catch (e) { result.replaceChildren(notice("bad", "연결이 안 돼요", e.message)); }
  }})), result);
  draw();
  loadOpt(false).then(() => { drawGroup(); draw(); });
  box.stop = () => { if (poll) { clearInterval(poll); poll = null; } };
  box.options = () => opt;
  return box;
}
