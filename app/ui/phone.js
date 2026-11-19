// 설정 → '폰 연결'(내 폰의 김비서 앱과 짝짓기) · '내 목소리'(목소리 등록·등록한 목소리만 명령 받기)
//   + 대화 화면: 위험한 도구의 '실행할까요?'(PC 창) · 등록한 목소리가 아니라 안 들은 말 표시
"use strict";

const Phone = {
  timer: null,

  stop() { if (this.timer) { clearInterval(this.timer); this.timer = null; } },

  async settings(card) {
    this.stop();
    const c = K.cfg;
    card.appendChild(h("h1", {text: "폰 연결"}));
    const s1 = Settings.section(card, "폰으로 김비서와 대화", ["폰.켜기"]);
    const box = (id, label, key, def) => {
      const i = h("input", {type: "checkbox", id});
      i.checked = !!get(c, key, def);
      return [h("label", {class: "toggle", for: id}, i, label), i];
    };
    const [l1, i1] = box("ph-on", "폰 연결 켜기", "폰.켜기", false);
    const [l2, i2] = box("ph-ts", "테일스케일로도 연결 받기(집 밖에서 쓸 때)", "폰.테일스케일_허용", false);
    const [l3, i3] = box("ph-pc", "폰으로 말해도 이 PC 조작하기(검색·사이트·프로그램 열기·메모장)", "폰.PC조작_허용", true);
    s1.append(h("p", {class: "hint", text: "내 폰에 '김비서' 앱을 깔고 이 PC 와 연결하면, 폰으로 말해도 이 PC 의 김비서가 대답해요. 같은 와이파이(집 안 네트워크)에서만 연결되고, 연결한 폰만 들어올 수 있어요. 쓰지 않으면 꺼 두세요(꺼져 있으면 아무 연결도 받지 않아요)."}),
    l1, l2, l3,
    h("p", {class: "hint", text: "처음 켤 때 윈도우 방화벽 창이 뜨면 '개인 네트워크'만 허용해 주세요. 테일스케일은 폰과 PC 에 둘 다 깔아 같은 계정으로 로그인했을 때만 켜세요."}),
    Settings.saveRow("ph-save", () => ({폰: {켜기: i1.checked, 테일스케일_허용: i2.checked, PC조작_허용: i3.checked}})));
    s1.querySelector("#ph-save").addEventListener("click", () => setTimeout(() => this.refresh(stat, list), 800));

    const stat = h("div", {id: "ph-status"});
    const s2 = h("div", {class: "set-sec", id: "ph-pair"}, h("h2", {text: "폰과 연결하기"}), stat);
    card.appendChild(s2);
    const qr = h("div", {id: "ph-qr", class: "qr-box"});
    s2.append(h("ol", {class: "howto"},
      h("li", {text: "폰에 '김비서' 앱을 깔아요(설치 파일 받는 곳은 README 의 '폰 앱' 칸)."}),
      h("li", {text: "아래 '연결 코드 만들기'를 누르면 QR 과 8자리 숫자가 나와요(10분 동안, 한 번만 쓸 수 있어요)."}),
      h("li", {text: "폰 앱에서 'QR 찍기'로 찍거나, 이 PC 주소와 숫자를 직접 넣어요."})),
    h("div", {class: "row"}, h("button", {class: "btn primary", type: "button", id: "ph-code", text: "연결 코드 만들기", onclick: () => this.code(qr)})), qr);

    const list = h("div", {id: "ph-devices"});
    const s3 = h("div", {class: "set-sec"}, h("h2", {text: "연결한 폰"}), list);
    card.appendChild(s3);
    await this.refresh(stat, list);
    this.timer = setInterval(() => { if (!document.getElementById("ph-status")) this.stop(); else this.refresh(stat, list); }, 5000);
  },

  async refresh(stat, list) {
    let j;
    try { j = await api("/api/phone"); } catch (e) { stat.replaceChildren(notice("bad", "상태를 읽지 못했어요", e.message)); return; }
    stat.replaceChildren();
    if (!j["켜짐"]) stat.appendChild(notice("", "폰 연결이 꺼져 있어요", "위에서 '폰 연결 켜기'를 켜고 저장하면 연결할 수 있어요."));
    else if (!j["듣는중"]) stat.appendChild(notice("bad", "폰 연결을 켜지 못했어요", j["오류"] || "김비서를 다시 켜 보세요."));
    else {
      const addr = (j["주소"] || []).map((a) => `${a}:${j["포트"]}`).join(" · ") || "(집 안 네트워크 주소를 못 찾음)";
      stat.appendChild(notice("ok", "폰 연결을 받고 있어요", `이 PC 주소: ${addr} · 인증서 확인 글자: ${j["지문"]}` +
        (j["대화중_폰"] ? ` · 지금 '${j["대화중_폰"]}' 로 대화 중` : "")));
    }
    const devs = j["기기"] || [];
    list.replaceChildren();
    if (!devs.length) { list.appendChild(h("p", {class: "hint", text: "아직 연결한 폰이 없어요."})); return; }
    const ul = h("ul", {class: "devices"});
    devs.forEach((d) => ul.appendChild(h("li", {}, h("span", {text: `${d["이름"]} — 등록 ${d["등록"] || ""}` + (d["마지막"] ? ` · 마지막 연결 ${d["마지막"]}` : "")}),
      h("button", {class: "btn ghost", type: "button", "data-dev": d["기기"], text: "지우기", onclick: async () => {
        if (!(await confirmBox(`'${d["이름"]}' 폰의 연결을 끊을까요? 그 폰은 다시 연결해야 써요.`, "네, 지울게요"))) return;
        await api("/api/phone/remove", {"기기": d["기기"]}).catch((e) => toast(e.message));
        this.refresh(document.getElementById("ph-status"), list);
      }}))));
    list.append(ul, h("div", {class: "row"}, h("button", {class: "btn ghost", type: "button", id: "ph-remove-all", text: "전부 지우기", onclick: async () => {
      if (!(await confirmBox("연결한 폰을 전부 지울까요?", "네, 지울게요"))) return;
      await api("/api/phone/remove", {"전부": true}).catch((e) => toast(e.message));
      this.refresh(document.getElementById("ph-status"), list);
    }})));
  },

  async code(qr) {
    let j;
    try { j = await api("/api/phone/code", {}); } catch (e) { qr.replaceChildren(notice("bad", "연결 코드를 만들지 못했어요", e.message)); return; }
    const img = h("img", {alt: "폰 앱으로 찍을 QR", id: "ph-qr-img", width: "240", height: "240", src: "data:image/svg+xml;utf8," + encodeURIComponent(j["QR"])});
    const left = h("span", {id: "ph-code-left"});
    const code = String(j["코드"]);
    qr.replaceChildren(img, h("p", {class: "big-code", id: "ph-code-text", text: code.slice(0, 4) + " " + code.slice(4)}),
      h("p", {class: "hint", text: `직접 넣을 때 PC 주소: ${(j["주소"] || []).join(" 또는 ")} · 포트 ${j["포트"]}`}),
      h("p", {class: "hint", text: "폰 앱에 나오는 인증서 확인 글자가 아래와 같은지 꼭 확인하세요."}),
      h("p", {class: "fp-words", text: String(j["지문"] || "")}), h("p", {class: "hint"}, left));
    const until = Date.now() + Number(j["초"] || 600) * 1000;
    const tick = () => {
      const s = Math.max(0, Math.round((until - Date.now()) / 1000));
      left.textContent = s ? `${Math.floor(s / 60)}분 ${s % 60}초 남음` : "시간이 지났어요. 다시 만들어 주세요.";
      if (!s) { img.remove(); clearInterval(t); }
    };
    const t = setInterval(() => { if (!document.getElementById("ph-code-left")) clearInterval(t); else tick(); }, 1000);
    tick();
  },
};

const MyVoice = {
  poll: null,

  stop() { if (this.poll) { clearInterval(this.poll); this.poll = null; } },

  async settings(card) {
    this.stop();
    card.appendChild(h("h1", {text: "내 목소리"}));
    const body = h("div", {id: "mv-body"});
    card.appendChild(body);
    await this.draw(body);
  },

  async draw(body) {
    let v;
    try { v = await api("/api/voiceprint"); } catch (e) { body.replaceChildren(notice("bad", "읽지 못했어요", e.message)); return; }
    body.replaceChildren();
    const c = K.cfg;
    body.appendChild(h("p", {class: "hint", text: "내 목소리를 등록해 두면, 김비서가 등록한 목소리의 말만 명령으로 받게 할 수 있어요(TV·다른 사람 말에 대답하지 않게). 목소리 특징(숫자 192개)만 이 PC 에 저장하고, 읽은 소리는 저장하지 않아요. 기본은 꺼져 있어요."}));

    // 1) 확인 모델
    const s0 = h("div", {class: "set-sec", id: "mv-model"}, h("h2", {text: "목소리 확인 모델"}));
    body.appendChild(s0);
    if (v["모델있음"]) s0.appendChild(notice("ok", "받아 두었어요", "TitaNet-small(Apache-2.0, 약 40MB) — 이 PC 안에서만 돌아요."));
    else {
      const out = h("div", {id: "mv-install-out"});
      const busy = v["받기"] && v["받기"]["설치중"];
      s0.append(h("p", {class: "hint", text: "처음 한 번 목소리 확인 모델(약 40MB)을 받아야 해요."}),
        h("div", {class: "row"}, h("button", {class: "btn primary", type: "button", id: "mv-install", text: busy ? "받는 중…" : "확인 모델 받기", disabled: !!busy,
          onclick: async (e) => {
            e.target.disabled = true; e.target.textContent = "받는 중…";
            try { await api("/api/voiceprint/install", {}); } catch (err) { out.replaceChildren(notice("bad", "받지 못했어요", err.message)); e.target.disabled = false; return; }
            this.watch(body, out);
          }})), out);
      if (busy) this.watch(body, out);
      return;
    }

    // 2) 등록
    const s1 = h("div", {class: "set-sec", id: "mv-enroll"}, h("h2", {text: v["등록됨"] ? `등록됨 (${v["등록"]}, 문장 ${v["문장"]}개)` : "내 목소리 등록"}));
    body.appendChild(s1);
    const sentences = v["읽을문장"] || [];
    const need = Number(v["최소문장"] || 3);
    let got = Number(v["모은문장"] || 0);
    const msg = h("p", {class: "hint", id: "mv-msg"});
    const meter = h("div", {class: "meter"}, h("i"));
    const ol = h("ol", {class: "read-list", id: "mv-sentences"}, sentences.map((t, i) => h("li", {"data-i": String(i), class: i < got ? "done" : ""}, t)));
    const finish = h("button", {class: "btn primary", type: "button", id: "mv-finish", text: "등록 끝내기", disabled: got < need});
    const rec = h("button", {class: "btn primary big", type: "button", id: "mv-rec"});
    const label = () => {
      rec.textContent = got < sentences.length ? `${got + 1}번 문장 읽기` : "한 문장 더 읽기";
      finish.disabled = got < need;
      finish.className = got < need ? "btn ghost" : "btn primary";   // 분홍은 지금 누를 단추 하나에만
      rec.className = got < need ? "btn primary big" : "btn ghost big";
      [...ol.children].forEach((li, i) => { li.className = i < got ? "done" : (i === got ? "now" : ""); });
    };
    rec.addEventListener("click", async () => {
      rec.disabled = true;
      msg.textContent = `'${sentences[Math.min(got, sentences.length - 1)]}' 를 평소 말투로 읽어 주세요. 듣고 있어요.`;
      let stream = null;
      try {
        stream = (await KAudio.openMic(get(c, "화면.마이크", ""))).stream;
        const r = await KAudio.recordUtterance(stream, {maxSec: 9, waitSec: 10, onLevel: (x) => { meter.firstChild.style.width = Math.round(x * 100) + "%"; }});
        if (!r.speech) { msg.textContent = "소리가 들리지 않았어요. 마이크 가까이에서 다시 읽어 주세요."; return; }
        const j = await api("/api/voiceprint/clip", r.pcm.buffer, true);
        if (j["받음"]) { got = j["모은문장"]; msg.textContent = got >= need ? `좋아요. ${got}개 모았어요. 더 읽으면 더 정확해져요(5개 권장). 다 되면 '등록 끝내기'.` : `좋아요(${got}/${need}). 다음 문장도 읽어 주세요.`; }
        else msg.textContent = j["안내"] || "다시 읽어 주세요.";
      } catch (e) { msg.textContent = "녹음하지 못했어요: " + e.message; }
      finally { KAudio.stop(stream); meter.firstChild.style.width = "0%"; rec.disabled = false; label(); }
    });
    finish.addEventListener("click", async () => {
      finish.disabled = true;
      try {
        const j = await api("/api/voiceprint/finish", {});
        toast(j["글"] || "등록했어요.", 6000);
        this.draw(body);
      } catch (e) { msg.textContent = e.message; label(); }
    });
    const work = h("div", {id: "mv-work"}, h("p", {class: "hint", text: `조용한 곳에서 아래 문장을 하나씩 읽어 주세요(${need}개 이상, 5개 권장). 다른 사람이 같이 읽으면 등록이 안 돼요.`}),
      ol, rec, meter, msg,
      h("div", {class: "row"}, finish, h("button", {class: "btn ghost", type: "button", id: "mv-reset", text: "처음부터", onclick: async () => {
        await api("/api/voiceprint/reset", {}).catch(() => {}); got = 0; msg.textContent = ""; label();
      }})));
    if (v["등록됨"] && !got) {   // 이미 등록했으면 읽기 화면은 접어 두고 '다시 등록하기'로만 엶
      work.hidden = true;
      const again = h("button", {class: "btn ghost", type: "button", id: "mv-again", text: "다시 등록하기", onclick: () => { work.hidden = false; again.remove(); }});
      s1.append(h("p", {class: "hint", text: "목소리가 바뀌었거나(감기 등) 명령이 자주 안 들리면 다시 등록해 주세요."}), h("div", {class: "row"}, again));
    }
    s1.append(work);
    label();
    if (!v["등록됨"]) return;

    // 3) 켜기·엄격함·확인해 보기·지우기
    const s2 = Settings.section(body, "등록한 목소리만 명령 받기", ["목소리등록.명령만"]);
    const on = h("input", {type: "checkbox", id: "mv-gate"});
    on.checked = !!get(c, "목소리등록.명령만", false);
    let th = Number(get(c, "목소리등록.문턱", 0.4));
    s2.append(h("label", {class: "toggle", for: "mv-gate"}, on, "등록한 목소리의 말만 명령으로 받기"),
      h("p", {class: "hint", text: "켜면 다른 사람·TV 말은 듣고도 대답하지 않아요(대화 화면에 '안 들음'으로 보여요). 폰 앱으로 말할 때도 같아요. " +
        "통역 중에는 상대 말은 그대로 번역하고, '통역 그만' 같은 켜기·끄기 말만 등록한 목소리일 때 받아요."}),
      h("p", {class: "big-q", text: "얼마나 엄격하게"}),
      choiceGroup([{값: 0.35, 이름: "느슨", 설명: "내 말이 가끔 안 들릴 때"}, {값: 0.4, 이름: "보통"}, {값: 0.48, 이름: "엄격", 설명: "비슷한 목소리의 가족이 있을 때"}], th,
        (x) => { th = x; }, {idp: "mv-th"}),
      Settings.saveRow("mv-save", () => ({목소리등록: {명령만: on.checked, 문턱: th}})));
    if (on.checked && !v["작동중"]) s2.appendChild(notice("warn", "지금은 막지 않고 있어요", v["오류"] || "확인 모델이나 등록이 없어서 모든 목소리를 받고 있어요."));
    const tout = h("p", {class: "hint", id: "mv-test-out"});
    const s3 = h("div", {class: "set-sec"}, h("h2", {text: "확인해 보기·지우기"}), h("p", {class: "hint", text: "아무 말이나 한 문장 하면 등록한 목소리와 얼마나 닮았는지 보여 줘요."}),
      h("div", {class: "row"}, h("button", {class: "btn", type: "button", id: "mv-test", text: "한 문장 말해 보기", onclick: async (e) => {
        e.target.disabled = true; tout.textContent = "듣고 있어요.";
        let stream = null;
        try {
          stream = (await KAudio.openMic(get(c, "화면.마이크", ""))).stream;
          const r = await KAudio.recordUtterance(stream, {maxSec: 8, waitSec: 9});
          if (!r.speech) { tout.textContent = "소리가 들리지 않았어요."; return; }
          const j = await api("/api/voiceprint/test", r.pcm.buffer, true);
          tout.textContent = j["점수"] === null ? "말이 너무 짧아요. 조금 더 길게 말해 주세요." :
            `닮음 ${Math.round(j["점수"] * 100)}점 (기준 ${Math.round(j["문턱"] * 100)}점) → ${j["같은사람"] ? "등록한 목소리로 알아들어요" : "다른 사람으로 봐요"}`;
        } catch (err) { tout.textContent = "확인하지 못했어요: " + err.message; }
        finally { KAudio.stop(stream); e.target.disabled = false; }
      }}),
      h("button", {class: "btn ghost", type: "button", id: "mv-forget", text: "등록 지우기", onclick: async () => {
        if (!(await confirmBox("등록한 목소리를 지울까요? '등록한 목소리만 명령 받기'도 더는 막지 않아요.", "네, 지울게요"))) return;
        await api("/api/voiceprint/forget", {}).catch((err) => toast(err.message));
        if (get(K.cfg, "목소리등록.명령만", false)) await saveSettings({목소리등록: {명령만: false}}).catch(() => {});
        this.draw(body);
      }})), tout);
    body.appendChild(s3);
  },

  watch(body, out) {
    this.stop();
    this.poll = setInterval(async () => {
      if (!document.getElementById("mv-body")) { this.stop(); return; }
      let j;
      try { j = await api("/api/voiceprint/install"); } catch (_) { return; }
      const p = j["진행"] || {};
      out.replaceChildren(h("p", {class: "hint", text: p["글"] || "받는 중이에요."}));
      if (j["모델있음"] || p["끝"]) {
        this.stop();
        if (p["끝"] && !p["성공"]) out.replaceChildren(notice("bad", "받지 못했어요", p["오류"] || p["글"] || "인터넷 연결을 확인하고 다시 눌러 주세요."));
        else this.draw(body);
      }
    }, 2000);
  },
};

// 대화 화면: 위험한 도구의 '실행할까요?'(PC 창) — 본체 confirm 사건 → 예/아니요 → /api/confirm
const ToolConfirm = {
  id: null,

  async ask(ev) {
    this.id = ev.id;
    Chat.sys("실행할지 물어보는 중이에요: " + ev.text);
    const ok = await confirmBox(ev.text, "네, 실행해요");
    if (this.id !== ev.id) return;          // 그사이 시간이 지나 본체가 거둠
    this.id = null;
    try { await api("/api/confirm", {id: ev.id, ok}); } catch (_) { /* 이미 끝남 */ }
    Chat.sys(ok ? "실행할게요." : "실행하지 않았어요.");
  },

  done(ev) {
    if (this.id !== ev.id) return;
    this.id = null;
    document.getElementById("dialog").hidden = true;
    Chat.sys("답을 기다리다 시간이 지나 실행하지 않았어요.");
  },
};
