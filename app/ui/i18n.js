// 다국어 화면 번역기(0.1.18~) — 화면에 붙는 한국어 글자를 고른 언어 사전으로 바꾼다.
//   사전 = /api/i18n.js 가 I18N.load({lang, dict}) 로 넣음(app/i18n/<언어>.json, {한국어 원문: 번역}). 한국어면 아무것도 안 함.
//   바꾸는 곳: 글자 노드, title·placeholder·aria-label·alt, 단추 value. 글이 붙는 즉시(MutationObserver) 바꿔서 한국어가 비치지 않음.
//   안 바꾸는 곳: translate="no" 가 붙은 칸(대화 내용·기억 글처럼 비서·사용자가 한 말), 입력 칸 글, script·style.
//   숫자·이름이 끼는 글: 사전 원문의 {0}·{n} 자리를 아무 글로 보고 대조(app/core/i18n.py lookup 과 같은 규칙).
//   코드에서 직접: t("{n}개 받음", {n: 3}).
"use strict";
const I18N = (() => {
  const HANGUL = /[가-힣]/;
  const PH = /\{([^{}\s]{1,40})\}/g;
  const ATTRS = ["title", "placeholder", "aria-label", "aria-valuetext", "alt"];
  let lang = "ko", exact = {}, pats = [], obs = null;
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  function load(o) {
    lang = (o && o.lang) || "ko";
    exact = (o && o.dict) || {};
    pats = [];
    for (const [k, v] of Object.entries(exact)) {
      if (!/\{[^{}\s]{1,40}\}/.test(k)) continue;
      const names = [];
      const rx = k.split(/(\{[^{}\s]{1,40}\})/).map((x, i) => {
        if (i % 2 === 0) return esc(x);
        names.push(x.slice(1, -1));
        return "(.+?)";
      }).join("");
      try { pats.push({rx: new RegExp("^" + rx + "$", "s"), names, v, n: k.length}); } catch (e) { /* 틀이 깨진 줄은 건너뜀 */ }
    }
    pats.sort((a, b) => b.n - a.n);
    document.documentElement.lang = lang === "zh" ? "zh-CN" : lang;
    setCssText();
  }

  // CSS 의사 요소(::before·::after)의 content 는 글자 노드가 아니라 번역기가 못 바꾼다.
  //   그래서 CSS 는 content: var(--chat-empty) 로 두고, 여기서 그 변수에 이 언어의 글을 넣는다.
  function cssString(s) {
    return '"' + String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"')
      .replace(/\r/g, "\\D ").replace(/\n/g, "\\A ") + '"';
  }

  function setCssText() {
    const k = "마이크 단추를 누르고 말씀하시거나\n아래에 글로 써서 보내세요.";
    document.documentElement.style.setProperty("--chat-empty", cssString(lookup(k)));
  }

  const fill = (s, vars) => !vars ? s : s.replace(PH, (m, n) => (n in vars ? String(vars[n]) : m));

  function lookup(s) {
    if (lang === "ko" || !s || !HANGUL.test(s)) return s;
    const core = s.trim();
    const lead = s.slice(0, s.indexOf(core));
    const tail = s.slice(lead.length + core.length);
    if (Object.prototype.hasOwnProperty.call(exact, core)) return lead + exact[core] + tail;
    for (const p of pats) {
      const m = p.rx.exec(core);
      if (m) {
        const vals = {};
        p.names.forEach((n, i) => { vals[n] = lookup(m[i + 1]); });
        return lead + fill(p.v, vals) + tail;
      }
    }
    for (const sep of [": ", ":", " — ", " - "]) {     // '앞말: 까닭' — 앞말만 사전에 있을 때
      const i = core.indexOf(sep);
      if (i > 0) {
        const head = core.slice(0, i), rest = core.slice(i + sep.length), key = head + sep.trimEnd();
        const hv = exact[key] !== undefined ? exact[key] : (exact[head] !== undefined ? exact[head] + sep.trimEnd() : null);
        if (hv !== null) return lead + hv + (sep.endsWith(" ") ? " " : "") + lookup(rest) + tail;
      }
    }
    return s;
  }

  function t(s, vars) {
    s = String(s);
    if (lang !== "ko") {
      if (Object.prototype.hasOwnProperty.call(exact, s)) s = exact[s];
      else s = lookup(s);      // 자리 이름이 달라도({n} ↔ {0}) 틀로 대조 — t("{n}개", {n:3})
    }
    return fill(s, vars);
  }

  const skip = (el) => !!(el && el.closest && el.closest('[translate="no"],script,style,textarea,[contenteditable="true"]'));

  function node(n) {
    if (n.nodeType === 3) {
      if (!HANGUL.test(n.data) || skip(n.parentElement)) return;
      const v = lookup(n.data);
      if (v !== n.data) n.data = v;
      return;
    }
    if (n.nodeType !== 1) return;
    if (n.tagName === "TEXTAREA") attrs(n);     // 입력 칸 글은 안 바꾸지만 placeholder 는 바꾼다
    if (skip(n)) return;
    attrs(n);
    const w = document.createTreeWalker(n, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: (x) => (x.nodeType === 1 && x.matches('[translate="no"],script,style,textarea') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT)});
    let x;
    while ((x = w.nextNode())) {
      if (x.nodeType === 3) {
        if (HANGUL.test(x.data)) { const v = lookup(x.data); if (v !== x.data) x.data = v; }
      } else attrs(x);
    }
  }

  function attrs(el) {
    for (const a of ATTRS) {
      const v = el.getAttribute && el.getAttribute(a);
      if (v && HANGUL.test(v)) { const nv = lookup(v); if (nv !== v) el.setAttribute(a, nv); }
    }
    if (el.tagName === "INPUT" && /^(button|submit|reset)$/i.test(el.type) && HANGUL.test(el.value)) el.value = lookup(el.value);
  }

  function apply(root) {
    if (lang === "ko") return;
    node(root || document.body);
    if (document.title && HANGUL.test(document.title)) document.title = lookup(document.title);
  }

  function watch() {
    if (lang === "ko" || obs || !window.MutationObserver) return;
    obs = new MutationObserver((list) => {
      for (const m of list) {
        if (m.type === "childList") m.addedNodes.forEach(node);
        else if (m.type === "characterData") node(m.target);
        else if (m.type === "attributes" && m.target.nodeType === 1 && !skip(m.target)) attrs(m.target);
      }
    });
    obs.observe(document.documentElement, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS});
  }

  function start() {
    if (lang === "ko") return;
    apply(document.documentElement);
    watch();
    const a = window.alert, c = window.confirm;    // 바로 뜨는 알림 창도
    window.alert = (m) => a.call(window, lookup(String(m)));
    window.confirm = (m) => c.call(window, lookup(String(m)));
  }

  // 화면에서 보이는 언어 이름(고르기 단추)
  const NAMES = {ko: "한국어", en: "English", ja: "日本語", zh: "中文"};
  return {load, t, lookup, apply, start, get lang() { return lang; }, NAMES};
})();
window.I18N = I18N;     // /api/i18n.js 가 window.I18N&&I18N.load(...) 로 부르므로(window 속성에도 올려 둠 — const 는 window 에 안 붙음)
const tr = I18N.t;
window.tr = tr;          // 화면 코드에서 window.tr 로도 부를 수 있게
