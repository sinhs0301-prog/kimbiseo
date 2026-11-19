/* 김비서 펫 — 화면 쪽(실사 옷 꾸러미 재생)
   투명 영상 클립(VP9 알파 webm)을 상태에 따라 이어 재생한다. 본체(main.js)와 주고받는 통로:
   받음 cursor·moved·speak·expr·mouth·bubble·react·menu-open·skin·motion·emotion·talk·draw·music-volume
   보냄 hit·drag-start·drag-end·context-menu·speak-started·speak-done·pet-log·move-by·dance-music
   클립 목록 = 본체가 주는 설치된 옷 꾸러미(realData). 무대 = 960x960 좌표, 서기 클립(544x960)은 가운데.
   자세: stand·sideL·sideR·back·diag·sit·lie·desk·deskup. 자세 사이 이동은 아래 EDGES 로 길 찾기.
   자세별 동작: 지금 자세에 맞는 클립(<자세>_<동작>)이 있으면 그 자세 그대로, 없으면 일어나서 한다(gestureAt). */
(function () {
  'use strict';
  const api = window.petApi || { send() {}, invoke: async () => 0, on() {} };
  const PD = api.realData ? api.realData() : null;
  const M = PD && PD.outfits && Object.keys(PD.outfits).length ? PD : { stage: { w: 960, h: 960 }, fps: 24, clips: {}, outfits: {} };
  const Q = new URLSearchParams(location.search);
  const DEMO = Q.get('petrec') === '1' || Q.get('demo') === '1';
  const log = m => api.send('pet-log', '실사: ' + m);
  window.addEventListener('error', e => log('error: ' + e.message + ' @' + e.lineno));
  window.addEventListener('unhandledrejection', e => log('rejection: ' + (e.reason && e.reason.message || e.reason)));

  const stage = document.getElementById('stage');
  const bubble = document.getElementById('bubble');
  const SW = M.stage.w, SH = M.stage.h;
  const SKIN = Q.get('skin') || '';
  const CL = M.outfits && M.outfits[SKIN] ? M.outfits[SKIN].clips : (M.clips || {});

  // ---------------------------------------------------------------- 0.1.7 앉아 대기·재생 기록·좌석 (대표님 11-20 02:27)
  // 대화가 없으면 IDLE_MIN 분 뒤 앉아 대기(0 = 끔). 앉은 뒤엔 말해도 앉은 채, "일어나"·걷기·춤이면 sit_out.
  let IDLE_MIN = PD && Number.isFinite(PD.idleSit) ? PD.idleSit : 3;
  // 재생 기록: 클립 이름별 횟수·누적 초(대화 내용 없음). 이 판은 기본 꺼짐 — 본체가 켜져 있다고 알릴 때만 보냄.
  const STAT = { on: !!(PD && PD.playStats), name: '', at: 0 };
  function statPoint(name, sec, plays) {
    if (!STAT.on || !name) return;
    api.send('clip-play', { name, sec, plays });
  }
  function notePlay(name) {
    const now = performance.now();
    if (STAT.name) statPoint(STAT.name, (now - STAT.at) / 1000, 0);
    STAT.name = name; STAT.at = now;
    statPoint(name, 0, 1);
  }
  setInterval(() => { if (STAT.on && STAT.name) { const now = performance.now(); statPoint(STAT.name, (now - STAT.at) / 1000, 0); STAT.at = now; } }, 30000);
  window.addEventListener('pagehide', () => { if (STAT.on && STAT.name) { statPoint(STAT.name, (performance.now() - STAT.at) / 1000, 0); STAT.name = ''; } });
  // 좌석(seat): 꾸러미 pack.json 이나 sit 클립에 "seat":"desk" 가 있으면 사무실 책상 의자용 클립.
  //   새 클립 5종이 오면 SEAT_ADJ 의 desk 값(dx·dy·scale)만 채우면 됨 — 지금은 0 이라 화면 그대로.
  const SEAT = (CL.sit_loop && CL.sit_loop.seat) || (CL.sit_in && CL.sit_in.seat) || (M.outfits && M.outfits[SKIN] && M.outfits[SKIN].seat) || (PD && PD.seat) || '';
  const SEAT_ADJ = { desk: { dx: 0, dy: 0, scale: 1 } };
  const seatAdj = name => {
    const s = (CL[name] && CL[name].seat) || (/^sit_/.test(name) ? SEAT : '');
    return (s && SEAT_ADJ[s]) || null;
  };

  // ---------------------------------------------------------------- 무대 크기(창에 맞춤: 서 있는 클립 폭이 들어가고 높이를 꽉)
  let scale = 1, offX = 0, offY = 0;
  function layout() {
    const W = window.innerWidth, H = window.innerHeight;
    scale = Math.min(H / SH, W / 544);
    offX = (W - SW * scale) / 2;
    offY = H - SH * scale;
    stage.style.transform = `translate(${offX}px, ${offY}px) scale(${scale})`;
    DRAW.dirty = true;
  }

  //     캔버스 2D 에 imageSmoothingQuality='high' 로 창 픽셀 크기에 딱 맞춰 그리면 GPU 가 있든 없든 부드럽게 줄어듦(화면 합성은 1:1 이라 다시 안 줄임).
  // 어떻게: 영상은 그대로 재생하되 화면에는 안 올림(body.cv → #stage display none). 화면 그릴 때마다(rAF) 보이는 클립의 '지금 장'을 new VideoFrame(영상) 으로 꺼내
  //     겹쳐 바꾸기(새 클립이 앞 클립 위로 서서히)는 CSS opacity 대신 globalAlpha 로 같은 시간·같은 순서. 캔버스가 안 되면 옛 방식으로 돌아감.
  const view = document.getElementById('view');
  const DRAW = { mode: 'video', ctx: null, dirty: true, raf: 0, fails: 0, paints: 0, vf: typeof VideoFrame === 'function', lastPoll: 0 };
  const LAYERS = [];   // 지금 보이는 클립(아래 → 위): { v, c, t0, fade, ts, a } — show() 가 올리고 retire() 가 내림(두 방식 공통으로 적어 둠)
  //   그 영상이 장을 못 내는데 캔버스를 지우고 아무것도 안 그려 빈 장이 됐음(시험 펫 실측: 되감을 때마다 35~38ms, 바쁜 PC 에서는 더 김).
  //   → 맨 위 클립이 장을 못 내는 동안은 캔버스를 그대로 둠(앞 그림 유지 — <video> 가 원래 하던 것과 같게). 겹쳐 바꾸기 시계도 새 클립 첫 장이 나온 때부터(started).
  const alphaOf = (l, now) => (!l.started ? 0 : l.fade > 0 ? Math.max(0, Math.min(1, (now - l.t0) / (l.fade * 1000))) : 1);
  function layerOn(v, c, fade) {
    const i = LAYERS.findIndex(l => l.v === v);
    const l = i >= 0 ? LAYERS.splice(i, 1)[0] : { v, c, t0: performance.now(), fade: fade || 0, ts: -1, k: -1, a: -1, started: DRAW.mode !== 'canvas' };   // 이미 보이던 클립이면 맨 위로만(다시 서서히 X — CSS 와 같음)
    LAYERS.push(l);
    DRAW.dirty = true;
  }
  function layerOff(v) {
    const i = LAYERS.findIndex(l => l.v === v);
    if (i >= 0) { LAYERS.splice(i, 1); DRAW.dirty = true; }
  }
  function paint(now, frames) {
    const ctx = DRAW.ctx, dpr = window.devicePixelRatio || 1;
    const W = window.innerWidth, H = window.innerHeight;
    const bw = Math.max(1, Math.round(W * dpr)), bh = Math.max(1, Math.round(H * dpr));
    if (view.width !== bw || view.height !== bh) { view.width = bw; view.height = bh; view.style.width = W + 'px'; view.style.height = H + 'px'; }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, bw, bh);
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    const k = dpr * scale;
    ctx.setTransform(k, 0, 0, k, dpr * offX, dpr * offY);
    for (let i = 0; i < LAYERS.length; i++) {
      const l = LAYERS[i], a = alphaOf(l, now);
      l.a = a;
      const src = frames[i] || (l.v.readyState >= 2 && !l.v.seeking ? l.v : null);
      if (a <= 0 || !src) continue;
      ctx.globalAlpha = a;
      const adj = seatAdj(l.v.dataset.name);   // 0.1.7 좌석 보정(지금 값 = 0 → 그대로)
      if (adj) ctx.drawImage(src, l.c.x + adj.dx, l.c.y + adj.dy, l.c.w * adj.scale, l.c.h * adj.scale);
      else ctx.drawImage(src, l.c.x, l.c.y, l.c.w, l.c.h);
    }
    ctx.globalAlpha = 1;
    DRAW.dirty = false; DRAW.paints++;
  }
  function drawTick(now) {
    DRAW.raf = 0;
    if (DRAW.mode !== 'canvas') return;
    DRAW.raf = requestAnimationFrame(drawTick);
    // 주사율이 높은 화면(120·144Hz)에서도 장 확인은 초당 70번쯤까지만(영상은 초당 24장) — 겹쳐 바꾸는 중·다시 그려야 할 때는 바로
    const fading = LAYERS.some(l => l.a < 1);
    if (!DRAW.dirty && !fading && now - DRAW.lastPoll < 14) return;
    DRAW.lastPoll = now;
    const frames = [];
    let need = DRAW.dirty || fading;
    try {
      let hold = false;
      const topI = LAYERS.length - 1;
      for (let i = 0; i < LAYERS.length; i++) {
        const l = LAYERS[i];
        let f = null;
        if (DRAW.vf && l.v.readyState >= 2 && !l.v.seeking) { try { f = new VideoFrame(l.v); } catch (e) { f = null; } }
        const has = !!f || (l.v.readyState >= 2 && !l.v.seeking);
        if (has && !l.started) { l.started = true; l.t0 = now; need = true; }
        if (f) {
          if (f.timestamp !== l.ts) { l.ts = f.timestamp; need = true; if (l.v._onPaint) l.v._onPaint(f.timestamp / 1e6); }
        } else if (has) {   // VideoFrame 을 못 쓰는 환경: 재생 시각으로 장 번호를 따져 바뀔 때 영상에서 바로 그림
          const kf = Math.floor(l.v.currentTime * FPS + 0.01);
          if (kf !== l.k) { l.k = kf; need = true; }
        }
        if (!has && (i === topI || alphaOf(LAYERS[topI], now) < 1)) hold = true;   // 맨 위가 못 냄, 또는 아래 클립이 못 내는데 위가 아직 반투명
        frames.push(f);
      }
      if (hold) { DRAW.dirty = true; DRAW.holds = (DRAW.holds || 0) + 1; }
      else if (need) paint(now, frames);
      DRAW.fails = 0;
    } catch (e) {
      if (++DRAW.fails >= 5) setDraw('video', '캔버스 그리기 오류 ' + (e && e.message));
    } finally {
      for (const f of frames) if (f) { try { f.close(); } catch (e) { /* 무시 */ } }
    }
  }
  function setDraw(mode, why) {
    if (mode === 'canvas' && !DRAW.ctx) {
      try { DRAW.ctx = view.getContext('2d'); } catch (e) { DRAW.ctx = null; }
      if (!DRAW.ctx) { mode = 'video'; why = '캔버스를 못 만듦'; }
    }
    if (mode !== 'canvas') mode = 'video';
    const changed = mode !== DRAW.mode;
    DRAW.mode = mode;
    document.body.classList.toggle('cv', mode === 'canvas');
    if (mode !== 'canvas') for (const l of LAYERS) l.started = true;
    if (mode === 'canvas') { DRAW.dirty = true; DRAW.fails = 0; if (!DRAW.raf) DRAW.raf = requestAnimationFrame(drawTick); }
    if (changed || why) log('그리기 방식 = ' + (mode === 'canvas' ? '캔버스(고화질 줄이기' + (DRAW.vf ? '' : ', VideoFrame 없음') + ')' : '영상 그대로(옛 방식)') + (why ? ' — ' + why : ''));
    api.send('draw-state', { mode, why: why || '' });
  }
  view.addEventListener('contextrestored', () => { DRAW.dirty = true; });
  window.addEventListener('resize', layout);
  layout();

  // ---------------------------------------------------------------- 클립 영상(미리 다 불러 둠 → 바꿀 때 끊김 없게)
  const V = {};
  for (const [name, c] of Object.entries(CL)) {
    const v = document.createElement('video');
    v.src = c.url || 'real/' + c.file;
    // 꾸러미 추가 동작(motion 칸 — 자세별 감정 등)은 미리 다 불러 두지 않음(부를 때 prep 이 첫 장까지 기다림).
    //   운영 펫 0.6.14 와 같은 고침: 클립 403개 꾸러미를 처음부터 켜면 화면이 메모리 부족(oom)으로 몇 초마다 죽었음(337개는 괜찮음)
    v.muted = true; v.playsInline = true; v.preload = c.motion ? 'metadata' : 'auto'; v.disablePictureInPicture = true;
    Object.assign(v.style, { left: c.x + 'px', top: c.y + 'px', width: c.w + 'px', height: c.h + 'px' });
    v.dataset.name = name;
    stage.appendChild(v);
    V[name] = v;
  }
  const has = n => !!CL[n];
  //   메타가 있는 말하기 클립은 소리가 날 때만 입 벌린 구간을 재생하고(다문 구간은 빨리 지나감), 조용하면 다문 장으로 가서 멈춤. 없으면 예전처럼 그냥 돌림.
  const MOUTH = {};
  for (const [n, c] of Object.entries(CL)) {
    const h = c.mouth;
    if (typeof h !== 'string' || h.length !== c.frames * 2 || !/^[0-9a-f]+$/i.test(h)) continue;
    const a = new Float32Array(c.frames);
    for (let k = 0; k < c.frames; k++) a[k] = parseInt(h.substr(k * 2, 2), 16) / 255 * 0.2;
    MOUTH[n] = a;
  }
  const M_REST = 0.03, M_OPEN = 0.045;   // 이보다 작으면 다문 것으로(쉬는 자리), 이보다 크면 벌린 것으로
  const restShare = n => { const a = MOUTH[n]; if (!a) return null; let k = 0; for (const x of a) if (x < M_REST) k++; return k / a.length; };

  let cur = null, curName = '', z = 1, showSeq = 0;
  const HIST = [];   // 점검용: 최근 보인 클립 50개 { ms, name }
  const FPS = M.fps || 24;
  const FADE = 0.14;      // 클립 바꿀 때 겹쳐 바꾸는 시간(초) — 새 클립이 앞 클립 위로 서서히(앞 클립은 끝까지 불투명 → 비침 없음)
  // 안 보이는 영상을 시작 장에 미리 맞춰 둠(멈춘 채 그 장이 이미 디코드돼 있음 → 바꿀 때 기다림·빈 장·깜빡임 없음)
  function prep(v, t) {
    return new Promise(res => {
      if (Math.abs(v.currentTime - t) < 0.5 / FPS && v.readyState >= 2) return res();
      let done = false;
      const EV = ['seeked', 'loadeddata', 'canplay'];
      const end = () => { if (done) return; done = true; for (const e of EV) v.removeEventListener(e, f); res(); };
      //   그동안 앞 클립이 그대로 보여 빈 장이 없음(실측: 불러오는 데 0.03초쯤). 이미 불러온 클립은 예전처럼 옮기기가 끝나면 바로, 늦어도 0.4초.
      const f = () => { if (v.readyState >= 2 || v.error) end(); };
      for (const e of EV) v.addEventListener(e, f);
      try { v.currentTime = t; } catch (e) { end(); }
      setTimeout(f, 400);
      setTimeout(end, 1500);
    });
  }
  function retire(v) {   // 안 쓰게 된 영상: 바로 숨기고 처음 장으로 되감아 둠(다음에 바로 쓸 수 있게)
    v.style.setProperty('--fade', '0s');
    v.classList.remove('on');
    layerOff(v);
    v.pause();
    setTimeout(() => { if (v !== cur && !v.classList.contains('on')) { try { v.currentTime = 0; } catch (e) { /* 무시 */ } } }, 30);
  }
  async function show(name, { loop = false, fade = FADE, from = 0 } = {}) {
    const v = V[name];
    if (!v) { log('클립 없음 ' + name); return; }
    v.loop = loop;
    const seq = ++showSeq;   // 늦게 끝난 앞 show() 가 새 클립을 덮지 않게
    if (v !== cur) {
      v.pause();
      await prep(v, from / FPS);
      if (seq !== showSeq) return;
      v.style.setProperty('--fade', fade ? fade + 's' : '0s');
      v.style.zIndex = ++z;
      v.classList.add('on');
      layerOn(v, CL[name], fade);
      const cc = CL[name], adj = seatAdj(name);   // 0.1.7 좌석 보정(영상 그대로 방식에서도 같은 자리)
      Object.assign(v.style, { left: (cc.x + (adj ? adj.dx : 0)) + 'px', top: (cc.y + (adj ? adj.dy : 0)) + 'px',
        width: (cc.w * (adj ? adj.scale : 1)) + 'px', height: (cc.h * (adj ? adj.scale : 1)) + 'px' });
      v.play().catch(e => log('재생 실패 ' + name + ' ' + e.message));
      const old = cur;
      cur = v; curName = name;
      HIST.push({ ms: Math.round(performance.now()), name }); if (HIST.length > 50) HIST.shift();
      notePlay(name);   // 0.1.7 재생 기록(클립이 실제로 바뀔 때 한 번)
      if (old) {
        const tShow = performance.now();
        const drop = () => {
          if (old === cur) return;
          const l = LAYERS.find(x => x.v === v), now = performance.now();
          if (DRAW.mode !== 'canvas' || v !== cur || !l || (l.started && now - l.t0 >= fade * 1000 + 40) || now - tShow > 4000) retire(old);
          else setTimeout(drop, 30);
        };
        setTimeout(drop, fade * 1000 + 40);
      }
    } else {
      v.loop = loop;
      if (!loop) { try { v.currentTime = from / FPS; } catch (e) { /* 무시 */ } v.play().catch(() => {}); }
    }
  }
  const ended = v => new Promise(res => {
    if (v.ended) return res();
    const f = () => { v.removeEventListener('ended', f); res(); };
    v.addEventListener('ended', f);
    setTimeout(f, (v.duration || 6) * 1000 + 1500);   // 혹시 ended 가 안 오면
  });

  // ---------------------------------------------------------------- 자세 길(자세 → 자세, 클립)
  const EDGES = [
    ['stand', 'sideL', 'sideL_in'], ['sideL', 'stand', 'sideL_out'],
    ['stand', 'sideR', 'sideR_in'], ['sideR', 'stand', 'sideR_out'],
    ['stand', 'back', 'back_in'], ['back', 'stand', 'back_out'],
    ['stand', 'diag', 'diag_in'], ['diag', 'stand', 'diag_out'],
    ['stand', 'sit', 'sit_in'], ['sit', 'stand', 'sit_out'],
    ['sit', 'lie', 'lie_in'], ['lie', 'sit', 'lie_out'],
    ['sideL', 'sideR', 'sideL_turn'], ['sideR', 'sideL', 'sideR_turn'],   // 돌아서기(옆 → 반대 옆)
    ['stand', 'w3L', 'w3L_in'], ['w3L', 'stand', 'w3L_out'], ['stand', 'w3R', 'w3R_in'], ['w3R', 'stand', 'w3R_out'],
    ['w3L', 'w3R', 'w3L_turn'], ['w3R', 'w3L', 'w3R_turn'],
    ['stand', 'desk', 'search_in'], ['desk', 'deskup', 'search_up'], ['deskup', 'desk', 'search_down'],
    ['deskup', 'stand', 'search_out'],
  ].filter(e => has(e[2]));
  const PARK = { stand: 'idle', sideL: 'sideL_hold', sideR: 'sideR_hold', back: 'back_hold', diag: 'diag_hold', sit: 'sit_loop', lie: 'lie_loop',
    w3L: 'w3L_hold', w3R: 'w3R_hold', desk: 'search_loop', deskup: 'search_look' };
  function path(from, to) {
    if (from === to) return [];
    const prev = { [from]: null }, q = [from];
    while (q.length) {
      const p = q.shift();
      for (const e of EDGES) if (e[0] === p && !(e[1] in prev)) { prev[e[1]] = e; q.push(e[1]); }
    }
    if (!(to in prev)) return null;
    const out = [];
    for (let p = to; prev[p]; p = prev[p][0]) out.unshift(prev[p]);
    return out;
  }

  // ---------------------------------------------------------------- 연출 줄: 새 명령이 오면 앞 명령은 다음 클립 경계에서 멈춤
  const st = { pose: 'stand', token: 0, onceP: null, busy: 0, talking: false, live: false, liveTimer: null, speaking: false,
    dragging: false, over: false, hitBusy: false, menuOpen: false, lastCursor: 0, lastAct: performance.now(), sleeping: false,
    nextIdle: 15000, busyUntil: 0, walkDir: 0, exprName: null, exprT: 0, exprUntil: 0,
    mood: null, moodAt: 0, moodTalked: false, emoTalkK: null, emoT: 0, emoOut: false,
    lastConv: performance.now(), autoSat: 0 };   // 0.1.7 마지막 대화 시각 — 앉아 대기 판단
  const alive = t => t === st.token;

  async function once(name, t) {
    if (!alive(t)) return false;
    if (!has(name)) { log('클립 없음(이 옷) → 건너뜀 ' + name); return alive(t); }
    await show(name, { loop: false });
    const p = ended(V[name]);
    st.onceP = p;
    await p;
    if (st.onceP === p) st.onceP = null;
    return alive(t);
  }
  async function goPose(target, t) {
    const pth = path(st.pose, target);
    if (!pth) return alive(t);
    for (const e of pth) {
      const ok = await once(e[2], t);
      if (has(e[2]) && cur === V[e[2]] && V[e[2]].ended) st.pose = e[1];
      if (!ok) return false;
      st.pose = e[1];
    }
    return alive(t);
  }
  const TALK_AT = { stand: 'talk', sit: 'sit_talk', deskup: 'search_talk', lie: 'lie_talk' };
  const talkClip = () => (TALK_AT[st.pose] && has(TALK_AT[st.pose]) ? TALK_AT[st.pose] : null);
  const EMO_AT = { stand: '', sit: 'sit_', lie: 'lie_' };
  const emoTalkClip = () => {
    if (!st.mood || !(st.pose in EMO_AT)) return null;
    const k = EMO_AT[st.pose] + 'talk_' + st.mood;
    return has(k + '_in') && has(k + '_hold') && has(k + '_out') ? k : null;
  };
  function park(fade = FADE) {
    const n = (st.talking && talkClip()) || PARK[st.pose];
    if (has(n)) show(n, { loop: true, fade });
    setTimeout(primeTalk, 400);
  }
  function primeTalk() {
    const n = talkClip(), v = n && V[n];
    if (!v || v === cur || st.talking || st.busy) return;
    const t = lipStart(n) / FPS;
    if (v.readyState >= 2 && Math.abs(v.currentTime - t) < 0.5 / FPS) return;
    prep(v, t);
  }
  // 명령 시작: urgent 가 아니면 지금 하는 한 번짜리 클립이 끝날 때까지 기다림
  async function begin(urgent) {
    const t = ++st.token;
    st.lastAct = performance.now();
    st.walkDir = 0;
    if (!urgent && st.onceP) await st.onceP;
    return t;
  }
  const wait = (ms, t) => new Promise(r => setTimeout(() => r(alive(t)), ms));

  // ---------------------------------------------------------------- 동작
  const MOTIONS = {
    idle: async t => { if (await goPose('stand', t)) park(0.2); },
    stand: async t => { if (await goPose('stand', t)) park(); },
    talk: async t => { if (await goPose('stand', t)) show('talk', { loop: true, fade: 0.2 }); },
    bow: t => gestureAt('bow', t),
    wave: t => gestureAt(has('hello') || poseClip('hello') ? 'hello' : 'wave', t),
    walk_left: t => walk(-1, t), walk_right: t => walk(1, t),
    turn_back: async t => { if (await goPose('back', t)) { park(); if (await wait(2600, t) && await goPose('stand', t)) park(); } },
    diag: async t => { if (await goPose('diag', t)) { park(); if (await wait(3500, t) && await goPose('stand', t)) park(); } },
    // 앉으면 "일어나"(stand) 전까지 앉아 있음(표정·말하기·인사도 앉은 채)
    sit: async t => { if (await goPose('sit', t)) park(); },
    lie: async t => { if (await goPose('lie', t)) park(); },
    search_start: async t => { if (!has('search_in') || !has('search_loop')) { log('책상 클립 없음(이 옷) → 검색 자세 건너뜀'); return; } if (st.pose === 'desk' || st.pose === 'deskup') { park(); return; } if (await goPose('desk', t)) park(); },
    search_look: async t => { if (await goPose('deskup', t)) park(); },
    search_end: async t => { if (st.pose !== 'desk' && st.pose !== 'deskup') return; if (await goPose('stand', t)) park(); },
    dance1: t => dance('dance1', t), dance2: t => dance('dance2', t), dance3: t => dance('dance3', t),
    dance_estella: t => dance('dance_estella', t),
    dance_bad: t => dance('dance_bad', t),
    dance_zerotwo: t => dance('dance_zerotwo', t),
    dance: t => { const pool = ['dance1', 'dance2', 'dance3'].filter(has); return dance(pool[Math.floor(Math.random() * pool.length)] || 'dance1', t); },
  };
  // ---------------------------------------------------------------- 자세별 동작
  // 서서 하는 동작 g 가 왔을 때: 지금 자세(앉기·눕기·책상)에 맞는 클립이 이 옷에 있으면 그 자세 그대로 하고 그 자세 대기로.
  //   없으면 일어나서(서기 자세로 가서) 서서 하는 클립으로 하고 서 있음. 자세별 클립 = 이름 <자세>_<g> 또는 꾸러미 motion 칸의 of·pose(VARIANT).
  //   표정(expr)은 다름: 자동으로 자주 오므로 그 자세 클립이 없으면 일어나지 않고 건너뜀.
  const VARIANT = MOTION_NAMES.variants ? MOTION_NAMES.variants(CL) : {};
  const POSE_GROUP = { sit: 'sit', lie: 'lie', desk: 'desk', deskup: 'desk' };
  function poseClip(g) {
    const p = POSE_GROUP[st.pose], v = p && VARIANT[g] && VARIANT[g][p];
    return v && has(v) ? v : null;
  }
  async function gestureAt(g, t) {
    const pc = poseClip(g);
    if (pc) {
      if (st.pose === 'desk' && !(await goPose('deskup', t))) return;
      if (await once(pc, t)) park();
      return;
    }
    if (!has(g)) { log('이 옷엔 ' + g + ' 클립 없음(서서·' + st.pose + ' 둘 다) → 건너뜀'); return; }
    if (st.pose !== 'stand') log('지금 자세(' + st.pose + ')엔 ' + g + ' 클립 없음 → 일어나서 함');
    if (await goPose('stand', t) && await once(g, t)) park();
  }
  const GESTURES = MOTION_NAMES.GESTURES;
  for (const g of GESTURES) MOTIONS[g] = t => gestureAt(g, t);
  const MOTION_ALIAS = MOTION_NAMES.ALIAS;
  // 꾸러미의 추가 동작(once): 그 자세(서기·앉기·눕기)로 가서 한 번 하고 그 자세 대기로. 서서 하는 추가 동작도 자세별 클립이 있으면 그것, 없으면 일어나서.
  //   추가 춤(dance): 춤과 같은 길(dance()).
  const EXTRA = MOTION_NAMES.extras ? MOTION_NAMES.extras(CL) : { motions: [], dances: [], skipped: [] };
  const EX_DANCE = {}, EX_ALIAS = {};
  const exKey = s => String(s).replace(/\s+/g, '').toLowerCase();
  for (const m of EXTRA.motions) {
    if (MOTIONS[m.name] || !has(m.name)) continue;
    MOTIONS[m.name] = async t => {
      if (m.pose === 'stand') return gestureAt(m.name, t);
      if (await goPose(m.pose, t) && await once(m.name, t)) park();
    };
    for (const c of [m.ko].concat(m.calls)) { const k = exKey(c); if (!(k in EX_ALIAS) && !MOTION_ALIAS[c] && !MOTIONS[c]) EX_ALIAS[k] = m.name; }
  }
  for (const d of EXTRA.dances) {
    if (MOTIONS[d.name] || !has(d.name)) continue;
    EX_DANCE[d.name] = d;
    MOTIONS[d.name] = t => dance(d.name, t);
    for (const c of [d.ko].concat(d.calls)) { const k = exKey(c); if (!(k in EX_ALIAS) && !MOTION_ALIAS[c] && !MOTIONS[c]) EX_ALIAS[k] = d.name; }
  }
  if (EXTRA.motions.length || EXTRA.dances.length || EXTRA.skipped.length) log('추가 동작 ' + (EXTRA.motions.map(m => m.name).join(',') || '없음') + ' · 추가 춤 ' + (EXTRA.dances.map(d => d.name).join(',') || '없음')
    + (EXTRA.skipped.length ? ' · 버린 것 ' + EXTRA.skipped.map(x => x[0] + '(' + x[1] + ')').join(', ') : ''));

  let danceAudio = null;
  function stopDanceMusic(fadeMs = 600) {
    const a = danceAudio; danceAudio = null;
    if (!a) return;
    fadeAudio(a, 0, fadeMs, true);
  }
  function fadeAudio(a, to, ms, stop) {   // 음량을 ms 동안 to 까지(끝나면 stop 이면 멈춤)
    clearInterval(a._fade);
    const v0 = a.volume, t0 = performance.now();
    if (ms <= 0) { a.volume = to; if (stop) { a.pause(); a.src = ''; } return; }
    a._fade = setInterval(() => {
      const k = Math.min(1, (performance.now() - t0) / ms);
      a.volume = Math.max(0, Math.min(1, v0 + (to - v0) * k));
      if (k >= 1) { clearInterval(a._fade); if (stop) { a.pause(); a.src = ''; } }
    }, 40);
  }
  //   김비서 목소리(-16~-20 LUFS)보다 5~10dB 컸음. 이제 곡마다 실제 크기(전체 RMS)를 재서 목표 크기에 맞춤 — 작게 -32 / 보통 -27(기본) / 크게 -21 dBFS
  //   (보통 = 목소리보다 8dB쯤 작게). 설정 = 메뉴 '춤 노래 크기' 또는 settings.json "musicVolume". 크기를 못 재면 크게 녹음된 곡으로 보고 낮춤.
  const MUSIC_DB = { 끔: -200, 작게: -32, 보통: -27, 크게: -21 };
  let musicLevel = (PD && MUSIC_DB[PD.musicVolume] !== undefined) ? PD.musicVolume : '보통';
  const LOUD = {};   // 노래 주소 → 전체 RMS(dBFS)
  async function musicLoudness(url) {
    if (url in LOUD) return LOUD[url];
    let db = null;
    try {
      const bytes = await api.invoke('dance-music-bytes', { url });
      if (bytes && bytes.byteLength) {
        const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
        const buf = await new OfflineAudioContext(1, 2, 44100).decodeAudioData(ab);
        const d = buf.getChannelData(0);
        let sum = 0, n = 0;
        for (let k = 0; k < d.length; k += 4) { sum += d[k] * d[k]; n++; }
        db = 10 * Math.log10(sum / Math.max(1, n) + 1e-12);
      }
    } catch (e) { log('춤 노래 크기 못 잼(' + (e && e.message) + ') → 큰 곡으로 보고 낮춤'); }
    LOUD[url] = db;
    return db;
  }
  const musicGain = db => Math.max(0, Math.min(1, Math.pow(10, (MUSIC_DB[musicLevel] - (db === null ? -11 : db)) / 20)));
  window.__danceAudioProbe = () => (danceAudio ? { t: danceAudio.currentTime, vol: danceAudio.volume, paused: danceAudio.paused, dur: danceAudio.duration, gain: danceAudio._gain } : null);   // 점검용
  api.on('music-volume', v => {
    if (MUSIC_DB[v] === undefined) return;
    musicLevel = v;
    if (danceAudio) { danceAudio._gain = musicGain(danceAudio._db); fadeAudio(danceAudio, danceAudio._gain, 200, false); }
  });
  // 0.1.7 메뉴에서 바꾸면 바로 적용(앉아 대기 분 / 재생 기록)
  api.on('idle-sit', v => {
    const n = Number(v);
    if (!(Number.isFinite(n) && n >= 0 && n <= 120)) return;
    IDLE_MIN = n; st.lastConv = performance.now();
    log('대화 없으면 앉기 = ' + (n ? (Math.round(n * 10) / 10) + '분' : '끔'));
  });
  api.on('play-stats', on => {
    if (!on && STAT.name) statPoint(STAT.name, (performance.now() - STAT.at) / 1000, 0);
    STAT.on = !!on; STAT.name = ''; STAT.at = performance.now();
    log('클립 재생 기록 ' + (STAT.on ? '켬' : '끔'));
  });
  async function dance(name, t) {
    if (!has(name)) { log('춤 클립 없음(이 옷) → 건너뜀 ' + name); return; }
    if (st.pose !== 'stand') log('춤 ' + name + ' — 지금 자세(' + st.pose + ')에서 일어나서 춤');
    // 노래 고르기·크기 재기는 서는 동안 같이(춤 시작이 늦어지지 않게, 길어야 0.4초만 기다림)
    const prepMusic = (async () => {
      let url = null;
      try { url = await api.invoke('dance-music', { dance: name }); } catch (e) { /* 노래 없이 */ }
      st.lastMusic = { dance: name, url: url || null };
      if (!url || musicLevel === '끔') return null;
      const a = new Audio(); a.preload = 'auto'; a.src = url;
      const meta = new Promise(r => { a.addEventListener('loadedmetadata', r, { once: true }); a.addEventListener('error', r, { once: true }); setTimeout(r, 400); });
      const [db] = await Promise.all([Promise.race([musicLoudness(url), new Promise(r => setTimeout(() => r(undefined), 400))]), meta]);
      a._db = db === undefined ? null : db; a._gain = musicGain(a._db); a.volume = a._gain;
      if (db === undefined) musicLoudness(url).then(d => { a._db = d; a._gain = musicGain(d); if (danceAudio === a) fadeAudio(a, a._gain, 300, false); });   // 늦게 재지면 그때 맞춤
      return a;
    })();
    if (!(await goPose('stand', t))) return;
    prep(V[name], 0);
    const a = await prepMusic;
    if (!alive(t)) return;
    const exd = (typeof EX_DANCE !== 'undefined' && EX_DANCE[name]) || null;
    const loops = (exd && exd.loops) || (CL[name] && CL[name].loops) || (exd && ((CL[name].frames || 0) / FPS || CL[name].dur || 0) >= 12 ? 1 : 2);
    const clipDur = (CL[name].frames || 0) / FPS || CL[name].dur || 8, total = loops * clipDur;
    //   규칙: ①노래가 춤 한 바퀴와 비슷한 길이(0.6~1.3배)면 바퀴마다 노래를 처음부터 ②노래가 전체 춤보다 짧으면 노래가 끝날 때 춤도 끝냄(대기로 겹쳐 넘김)
    //         ③노래가 더 길면 춤이 끝나기 0.9초 전부터 줄여 같이 끝냄.
    const S = a && isFinite(a.duration) && a.duration > 1 ? a.duration : null;
    const mode = !a ? 'none' : S === null ? 'long' : (S >= clipDur * 0.6 && S <= clipDur * 1.3 && loops > 1) ? 'perloop' : S < total - 0.6 ? 'short' : 'long';
    let cutTimer = null, fadeTimer = null, cutHit = false;
    const cut = new Promise(r => { if (mode === 'short') cutTimer = setTimeout(() => { cutHit = true; r('cut'); }, Math.max(1000, (S - 0.35) * 1000)); });
    if (a) {
      stopDanceMusic(0);
      danceAudio = a;
      a.play().catch(e => log('춤 노래 재생 안 됨 ' + e.message));
      if (mode === 'long') fadeTimer = setTimeout(() => { if (danceAudio === a) fadeAudio(a, 0, 850, false); }, Math.max(0, (total - 0.9) * 1000));
      log('춤 노래 ' + (S === null ? '길이 모름' : S.toFixed(1) + '초') + ' · 춤 ' + clipDur.toFixed(1) + '초×' + loops + ' · ' + ({ perloop: '바퀴마다 처음부터', short: '노래 끝에 맞춰 춤 끝냄', long: '춤 끝에 맞춰 줄임' })[mode]
        + ' · 크기 ' + musicLevel + '(' + (a._db === null ? '못 잼' : a._db.toFixed(1) + 'dB') + ' → ×' + a._gain.toFixed(3) + ')');
    }
    st.dancing = true;
    try {
      for (let k = 0; k < loops; k++) {
        if (k > 0 && mode === 'perloop' && danceAudio === a) { try { a.currentTime = 0; a.volume = a._gain; a.play().catch(() => {}); } catch (e) { /* 무시 */ } }
        const r = await Promise.race([once(name, t), cut]);
        if (r === 'cut') { st.onceP = null; break; }
        if (!r) return;
      }
      park(cutHit ? 0.45 : FADE);
    } finally {
      st.dancing = false;
      clearTimeout(cutTimer); clearTimeout(fadeTimer);
      if (danceAudio === a) stopDanceMusic(mode === 'short' && cutHit ? 350 : mode === 'long' ? 250 : 600);
    }
  }
  //   세 클립 모두 카메라가 따라가며 찍은 것 → 화면에 보이는 장마다 manifest rootDx(디딘 발이 밀린 거리)만큼 창을 옮겨 발이 바닥에 붙어 보이게.
  //   클립끼리 잇는 장이 원본에서 바로 이어지는 장이라 장면이 툭 바뀌지 않음.
  //   화면 끝에 닿아 창이 더 안 가면(본체 move-by 답) 멈추기 → 돌아서기(turn: 옆→반대 옆, 정면을 거쳐 반 바퀴) → 반대쪽으로 다시 걷기(제자리걸음 없음).
  //   wstart/wstop 이 없는 옛 클립 묶음이면 예전처럼 반복 클립만 씀(enter 장에서 시작·멈춤).
  const WL = has('w3L_walk') ? 'w3L' : 'sideL', WR = has('w3R_walk') ? 'w3R' : 'sideR';
  async function walk(dir, t, ms) {
    let left = ms || (4000 + Math.random() * 5000);
    try {   // 걷기 전에 남은 거리 확인: 가려는 쪽이 너무 좁으면(시작+멈추기 거리보다 작으면) 반대쪽으로
      const side0 = dir < 0 ? WL : WR, run = n => (CL[n] && CL[n].rootDx || []).reduce((a, b) => a + b, 0);
      const rm = await api.invoke('move-by', { dx: 0, dy: 0 });
      const room = rm && (dir < 0 ? rm.roomL : rm.roomR);
      if (typeof room === 'number' && room < (run(side0 + '_wstart') + run(side0 + '_wstop')) * scale + 10) dir = -dir;
    } catch (e) { /* 무시 */ }
    for (let turns = 0; turns < 4 && left > 500; turns++) {
      const side = dir < 0 ? WL : WR;
      //   → 옆 자세로 따로 돌아서지 않음(정면에서 바로), 끝에 닿으면 정면에서 반대쪽 걷기 시작(돌아서기 클립 안 씀)
      const one = CL[side + '_walk'] && CL[side + '_walk'].oneVideo && has(side + '_wstart') && has(side + '_wstop');
      if (!(await goPose(one ? 'stand' : side, t))) return;
      if (!has(side + '_walk')) break;
      const t0 = performance.now();
      const r = await walkLeg(side, dir, t, left);
      if (!r.ok) return;
      left -= performance.now() - t0;
      if (!r.edge) break;
      dir = -dir;                     // 끝에 닿음 → 반대로(돌아서기 클립, 없으면 정면 거쳐)
    }
    if (await goPose('stand', t)) park();
  }
  async function walkLeg(side, dir, t, ms) {
    const n = side + '_walk', c = CL[n];
    const cyc = c.cycle || c.frames, newStyle = has(side + '_wstart') && has(side + '_wstop') && c.stopAt != null;
    const S = { blocked: 0, frame: 0 }, t0 = performance.now();
    st.walking = true;
    try {
      if (newStyle) {
        if (c.oneVideo) st.pose = side;               // 걷는 도중 끊기면 옆(3/4) 자세에서 정면으로 돌아오게(w3L_out)
        if (!(await drive(side + '_wstart', dir, t, S, c.oneVideo ? { fade: 0.1 } : {})).ok) return { ok: false };
        let primed = false;
        const stopAt = c.stopAt % cyc, root = c.rootDx || [], N = c.frames;
        // 화면 끝 전에 멈추기: (지금 장 → 다음 멈춤 장까지 걷는 거리 + 멈추기 클립이 가는 거리) 보다 남은 거리가 작으면 이번 멈춤 장에서 멈춤
        const stopRun = (CL[side + '_wstop'].rootDx || []).reduce((a, b) => a + b, 0);
        const cycRun = root.slice(0, cyc).reduce((a, b) => a + b, 0);   // 한 바퀴(두 걸음) 거리
        const toStop = f => { let d = 0; for (let k = 1, j = (f + 1) % N; k <= cyc + 1; k++, j = (j + 1) % N) { d += root[j] || 0; if (j % cyc === stopAt) break; } return d; };
        const r = await drive(n, dir, t, S, { loop: true, fade: 0.06, until: s => {
          const off = (s.frame % cyc - stopAt + cyc) % cyc;   // 멈춤 장 바로 앞(cyc-1)~2장 뒤까지 받음(그리기가 장을 건너뛰어도 한 바퀴 더 돌지 않게)
          const inWin = off === cyc - 1 || off <= 2;
          const room = dir < 0 ? s.roomL : s.roomR;
          // 멈춤 자리에서만 정함: 한 바퀴 더 걷고(다음 멈춤 자리까지) 멈추면 끝을 넘는가? 넘으면 지금 멈춤(너무 일찍도, 끝에 부딪히지도 않게)
          if (inWin && room != null) {
            const cont = toStop(s.frame) + (off === cyc - 1 ? cycRun : 0);
            if (room <= (cont + stopRun) * scale + 4) s.edge = true;
          }
          const want = performance.now() - t0 > ms || s.blocked >= 3 || s.edge;
          if (want && !primed) { primed = true; prep(V[side + '_wstop'], 0); }   // 멈추기 첫 장을 미리 디코드
          s.stopOff = off === cyc - 1 ? 0 : off;           // 늦게 잡았으면 멈추기 클립도 그만큼 뒤 장부터
          return want && inWin;
        } });
        if (!r.ok) return { ok: false };
        if (!(await drive(side + '_wstop', dir, t, S, { fade: 0.06, from: S.stopOff || 0 })).ok) return { ok: false };
        if (c.oneVideo) st.pose = 'stand';            // 한 영상 걷기의 멈추기는 정면으로 돌아와 끝남
        park(0.14);
        return { ok: true, edge: S.blocked >= 3 || !!S.edge };
      }
      const enter = c.enter || 0;   // 옛 묶음
      const r = await drive(n, dir, t, S, { loop: true, from: enter, fade: 0.2, until: s => {
        const want = performance.now() - t0 > ms || s.blocked >= 3;
        return want && s.frame % cyc === enter && s.moved > 0;
      } });
      if (!r.ok) return { ok: false };
      park(0.2);
      return { ok: true, edge: S.blocked >= 3 };
    } finally { st.walking = false; }
  }
  // 클립 하나를 재생하며 장마다 rootDx 만큼 창을 옮김. loop 면 until(S) 가 참일 때, 아니면 끝 장에서 끝남. S.blocked = 창이 못 간 횟수(연속)
  function drive(name, dir, t, S, { loop = false, from = 0, fade = FADE, until = null } = {}) {
    const c = CL[name], v = V[name];
    const N = c.frames, root = c.rootDx || [];
    return new Promise(async res => {
      await show(name, { loop, fade, from });
      if (!alive(t) || cur !== v) return res({ ok: false });
      let last = from, pend = 0, done = false;
      S.frame = from; S.moved = 0;
      let poll = null;
      const finish = ok => { if (done) return; done = true; if (poll) clearInterval(poll); if (v._onPaint === step1) v._onPaint = null; res({ ok }); };
      if (!loop) ended(v).then(() => setTimeout(() => finish(alive(t) && cur === v), 50));   // 끝 장 알림이 안 와도 끝냄
      // 장 알림(requestVideoFrameCallback)은 화면에 그릴 때만 옴 → 창이 가려지거나 원격 화면이 꺼져 있으면 안 옴.
      // 그래서 0.1초마다 currentTime 으로도 같은 일을 함(먼저 온 쪽이 처리, 같은 장이면 아무것도 안 함). 멈춘 채 끝나지 않는 일 막음.
      const step1 = mt => {
        if (done) return;
        if (!alive(t) || cur !== v) return finish(false);
        const f = Math.min(N - 1, Math.round(mt * FPS));
        let steps = loop ? (f - last + N) % N : Math.max(0, f - last);
        if (steps > N / 2) steps = 0;                  // 되감긴 것처럼 보이면 무시
        let d = 0;
        for (let k = 0; k < steps; k++) { last = loop ? (last + 1) % N : last + 1; d += root[last] || 0; }
        S.frame = last; S.moved += steps;
        if (d && !st.dragging) {
          pend += d * scale * dir;
          const step = Math.trunc(pend);
          if (step) {
            pend -= step;
            api.invoke('move-by', { dx: step, dy: 0 })
              .then(r => {
                if (!r || typeof r.dx !== 'number') return;
                S.blocked = Math.abs(r.dx) < Math.abs(step) * 0.4 ? S.blocked + 1 : 0;
                if (typeof r.roomL === 'number') { S.roomL = r.roomL; S.roomR = r.roomR; }
              })
              .catch(() => {});
          }
        }
        if (!loop && last >= N - 1) return finish(true);
        if (until && until(S)) return finish(true);
      };
      const onFrame = (now, meta) => { step1(meta.mediaTime); if (!done) v.requestVideoFrameCallback(onFrame); };
      poll = setInterval(() => step1(v.currentTime), 100);
      v._onPaint = step1;
      v.requestVideoFrameCallback(onFrame);
    });
  }

  // ---------------------------------------------------------------- 표정(몸짓 포함 클립): 들어가기 → 유지(반복) → 나오기
  const EXPR_CLIP = { 기쁨: 'joy', 생각: 'think', 놀람: 'surprise', 졸림: 'sleepy', 걱정: 'worry', 웃음: 'laugh', 부끄러움: 'shy', 윙크: 'wink',
    화남: 'worry', happy: 'joy', thinking: 'think', surprised: 'surprise', sleepy: 'sleepy', worried: 'worry', laugh: 'laugh', shy: 'shy', wink: 'wink' };
  const EXPR_SET = new Set(Object.values(EXPR_CLIP));
  async function expr(name, sec, urgent) {
    const c = EXPR_CLIP[name] || EXPR_CLIP[String(name).toLowerCase()] || (EXPR_SET.has(name) && has(name) ? name : null);
    const now = performance.now();
    if (!c) {   // 보통·기본 등: 지금 표정이 있으면 바로 나오기, 없으면 대기
      if (st.exprName) { st.exprUntil = 0; return; }
      if (st.pose === 'stand' && !st.onceP && !st.talking) park(0.2);
      return;
    }
    if (st.talking) return;                                 // 말하는 중엔 말하기 클립 유지(한 영상이라 표정과 겹칠 수 없음)
    if (st.busy) return;
    if (st.exprName === c) { st.exprUntil = Math.max(st.exprUntil, now + (sec || 4) * 1000); return; }
    if (st.pose === 'desk' || st.pose === 'deskup') return;   // 책상에 있을 때는 일어나지 않음
    const seated = st.pose === 'sit' || st.pose === 'lie';
    const lying = st.pose === 'lie';
    const k = (seated ? (lying ? 'lie_' : 'sit_') : '') + c;
    if (!has(k + '_in') && !has(k)) return;
    const t = await begin(urgent);
    if (seated ? st.pose !== (lying ? 'lie' : 'sit') : !(await goPose('stand', t))) return;
    st.exprName = c; st.exprT = t; st.exprUntil = performance.now() + (sec || 4) * 1000;
    try {
      if (has(k + '_in') && has(k + '_hold') && has(k + '_out')) {
        if (!(await once(k + '_in', t))) return;
        // 유지 = 들어가기가 끝난 뒤 sec 초(같은 표정이 다시 오면 그때부터 sec 초 더). 나오기 시작하면 새 요청은 새로 시작
        st.exprUntil = Math.max(st.exprUntil, performance.now() + (sec || 4) * 1000);
        const minEnd = performance.now() + 600;
        show(k + '_hold', { loop: true });
        for (;;) {
          const left = Math.max(st.exprUntil, minEnd) - performance.now();
          if (left <= 0) break;
          if (!(await wait(Math.min(left, 400), t))) return;
        }
        const hc = CL[k + '_hold'], hv = V[k + '_hold'];
        if (hc && hc.seamOut && hv && cur === hv) {
          prep(V[k + '_out'], 0);
          const N = hc.frames, tEnd = performance.now() + (N / FPS) * 1000 + 300;
          while (performance.now() < tEnd && cur === hv && Math.round(hv.currentTime * FPS) < N - 2) {
            if (!(await wait(12, t))) return;
          }
        }
        if (st.exprT === t) st.exprName = null;
        if (!(await once(k + '_out', t))) return;
      } else if (has(k)) {
        if (!(await once(k, t))) return;
      }
      park();
    } finally {
      if (st.exprT === t) st.exprName = null;
    }
  }

  async function motion(name) {
    st.lastConv = performance.now();   // 0.1.7 동작 명령도 '대화'로 봄(앉아 대기 시계를 되돌림)
    let r = MOTION_NAMES.resolve(name, n => has(n) || !!poseClip(n), n => !!MOTIONS[n]);   // 지금 자세 클립만 있어도 '있음'
    if (r.unknown && EX_ALIAS[exKey(name)]) r = { name: EX_ALIAS[exKey(name)], asked: EX_ALIAS[exKey(name)], unknown: false, missing: false, fallback: null };
    if (r.unknown) {
      const em = MOTION_NAMES.emotionOf(name);
      if (em && em !== 'neutral') setMood(em, '/motion');
      if (EXPR_CLIP[name] || EXPR_SET.has(name)) return expr(name, 4);
      if (em) return;
      log('모르는 동작 ' + name); return;
    }
    if (r.missing) log('이 옷엔 ' + r.asked + ' 클립 없음 → ' + (r.fallback ? r.fallback + ' 로 대신' : '대신할 것 없음(가만히, 말풍선만)'));
    if (!r.name) return;
    const k = r.name;
    //   동작이 끝났을 때 아직 말하는 중이면 그 자세의 말하기 클립(앉아 있으면 sit_talk)으로.
    log('동작 ' + k);
    st.busy++;
    try {
      const t = await begin(false);
      await MOTIONS[k](t);
    } finally {
      st.busy--;
      if (!st.busy) {
        // 말하는 중이면 그 자세의 말하기로(책상 = 고개 들어 search_talk, 누움 = 앉아서) — setTalking 의 자세별 길을 그대로 씀
        if (st.talking && curName !== talkClip() && !st.onceP) { st.talking = false; setTalking(true); }
        log('동작 끝 ' + k + ' → 자세 ' + st.pose + (st.talking ? ' (말하는 중)' : ''));
      }
    }
  }

  // ---------------------------------------------------------------- 말하기(소리 재생 동안 말하기 클립 반복)
  const KEEP_ON_TALK = new Set(['hello', 'sit_hello', 'lie_hello', 'desk_hello']);   // 인사 클립은 입모양이 "안녕하세요" → 끝까지 두고 이어서 말하기(park 가 말하기로)
  //   소리 남 + 입 다문 장 = 다음 입 벌린 장까지 빨리(최대 3배) / 소리 남 + 입 벌린 장 = 1배 / 조용함 + 입 벌린 장 = 다문 장까지 빨리 / 조용함 + 다문 장 = 멈춤.
  //   모의 시험(진짜 목소리 32초): 소리 크기와 입 벌림의 상관 0.00 → 0.46~0.54, 조용할 때 입 벌린 비율 0.7 → 0.14~0.31.
  const LIP = { on: !(PD && PD.lip === 'off') && Q.get('lip') !== 'off', level: 0, at: -1e9, v: null, ticks: 0, idle: false, voicedAt: 0, wait: false };
  const lipClip = n => !!MOUTH[n] && (n === TALK_AT.stand || n === TALK_AT.sit || n === TALK_AT.deskup || n === TALK_AT.lie || /^(sit_|lie_)?talk_[a-z]+_hold$/.test(n));
  // 말하기 클립을 올릴 때 시작 장: 입이 열리기 바로 앞의 다문 장(앞쪽 12장 안에서) → 소리가 나면 다음 장에 바로 열림
  const lipStart = n => { const a = MOUTH[n]; if (!a || !LIP.on) return 0; let f = 0; while (f < 12 && f + 1 < a.length && a[f + 1] < M_REST) f++; return f < 12 ? f : 0; };
  function lipRelease() {
    const v = LIP.v;
    LIP.v = null;
    if (!st.talking) LIP.wait = false;
    if (!v) return;
    try { v.playbackRate = 1; if (v === cur && v.paused && !v.ended) v.play().catch(() => {}); } catch (e) { /* 무시 */ }
  }
  const LIP_SLOW = 0.0625;   // 쉬는 자리에서의 빠르기(크롬이 받는 가장 느린 값 = 0.67초에 한 장). 멈추지(pause) 않는 까닭: 멈추면 화면에 남는 장이 재생 위치와 어긋나 입 벌린 장에서 굳었음
  function lipTick() {
    const now = performance.now();
    const voiced = now - LIP.at < 170 && LIP.level > 0.06;
    if (voiced) LIP.voicedAt = now;
    if (LIP.idle) {   // 말 사이 쉼 동안 대기 클립으로 내려와 있는 중(아래) → 소리가 다시 나면 말하기 클립으로, 말이 끝났으면 그대로 둠
      if (!st.talking || st.busy || st.dancing || curName !== PARK[st.pose]) { LIP.idle = false; return; }
      if (voiced) { LIP.idle = false; const n = talkClip(); if (n) show(n, { loop: true, fade: 0.1, from: lipStart(n) }); }
      return;
    }
    const mo = MOUTH[curName];
    if (!LIP.on || !cur || !mo || !st.talking || st.dancing || !lipClip(curName)) { lipRelease(); return; }
    if (LIP.v && LIP.v !== cur) lipRelease();
    const v = cur;
    LIP.v = v; LIP.ticks++;
    if (LIP.wait) {   // 말하기 준비(/talk)로 미리 올려 둔 상태: 첫 소리가 올 때까지 시작 장에서 기다림 → 소리가 오면 바로 3배로 입을 엶
      if (!voiced) { try { if (!v.paused) v.pause(); } catch (e) { /* 무시 */ } return; }
      LIP.wait = false;
      try { v.playbackRate = 3; if (v.paused && !v.ended) v.play().catch(() => {}); } catch (e) { /* 무시 */ }
      return;
    }
    const N = mo.length, f = Math.max(0, Math.min(N - 1, Math.floor(v.currentTime * FPS + 0.01)));   // 재생 위치의 장(화면은 한두 장 뒤따라옴 — 느리게 돌리면 곧 같아짐)
    const o = mo[f];
    let r;
    if (voiced) {
      if (o >= M_OPEN) r = 1;
      else { let k = 1; while (k < 12 && mo[(f + k) % N] < M_OPEN) k++; r = Math.min(3, 1 + 0.5 * k); }
    } else if (o < M_REST) {   // 조용함 + 재생 위치가 다문 장: 화면에 보이는 장도 다문 장이 되면 거의 멈춤(화면은 한 장쯤 뒤따라옴 — 바로 멈추면 입 벌린 장에서 굳음)
      const l = DRAW.mode === 'canvas' ? LAYERS.find(x => x.v === v) : null;
      const fd = l && l.ts >= 0 ? Math.max(0, Math.min(N - 1, Math.round(l.ts / 1e6 * FPS))) : f;
      r = mo[fd] < M_REST ? LIP_SLOW : (mo[(f + 1) % N] < M_REST ? 1 : 0.5);
    } else {   // 조용함 + 입 벌린 장: 다음 다문 장까지 — 멀면 4배, 가까우면 천천히(다문 장을 지나치지 않게)
      let d = 1; while (d < 48 && mo[(f + d) % N] >= M_REST) d++;
      // 다문 장이 멀면(6장 넘게) 빨리 돌리는 대신 대기 클립으로 겹쳐 내림(몸이 빨리 감기듯 튀지 않게) — 보통 말하기 클립만, 0.08초 넘게 조용할 때
      if (d > 5 && Object.values(TALK_AT).includes(curName) && has(PARK[st.pose]) && now - (LIP.voicedAt || 0) > 80 && !st.onceP) {
        lipRelease();
        LIP.idle = true;
        show(PARK[st.pose], { loop: true, fade: 0.15 });
        return;
      }
      r = Math.max(1, Math.min(4, d / (FPS * 0.03)));
    }
    try { if (v.playbackRate !== r) v.playbackRate = r; if (v.paused && v === cur && !v.ended) v.play().catch(() => {}); } catch (e) { /* 무시 */ }
  }
  setInterval(lipTick, 25);
  async function setTalking(on) {
    if (on === st.talking) return;
    st.talking = on;
    const now = performance.now();
    if (on) {
      if (now - (st.talkOffAt || 0) > 2500) { st.talkSince = now; st.talkWalkRolled = false; }   // 문장 사이 짧은 쉼은 같은 답으로 봄
      if (st.onceP && KEEP_ON_TALK.has(curName)) return;
      if (st.busy) return;
      if (st.walking && st.walkForTalk) return;               // 말하다 잠깐 걷는 중이면 걷기 끝나고 말하기로
      if (st.mood) st.moodTalked = true;
      if (st.emoTalkK && st.emoTalkK === emoTalkClip() && !st.emoOut) return;
      if (st.pose === 'desk') {                               // 검색 중 답하기 시작 → 고개 들어 정면
        const t = await begin(true);
        if (!(await goPose('deskup', t))) return;
      } else if (st.pose === 'lie' && !has('lie_talk') && !emoTalkClip()) {
        return;
      } else if (!TALK_AT[st.pose]) {
        const t = await begin(true);
        if (!(await goPose('stand', t))) return;
      } else {                  // 인사·표정·걷기 등 하던 것 끊고 바로 말하기(겹쳐 전환)
        ++st.token; st.onceP = null; st.walkDir = 0;
      }
      st.exprName = null;
      let ek = st.talking ? emoTalkClip() : null;
      if (ek && restShare(ek + '_hold') !== null && restShare(ek + '_hold') > 0.75) { log('감정 말하기 ' + ek + ' 는 입이 거의 안 움직임(다문 장 ' + Math.round(restShare(ek + '_hold') * 100) + '%) → 보통 말하기'); ek = null; }
      if (ek) { emoTalk(ek); return; }
      if (st.talking && st.mood && st.pose in EMO_AT) log('이 옷·자세엔 ' + EMO_AT[st.pose] + 'talk_' + st.mood + ' 없음 → 보통 말하기');
      const n = talkClip();
      if (st.talking && n && (st.pose === 'sit' || st.pose === 'lie')) log('앉아·누운 채 말하기 → ' + n);   // 0.1.7 확인용
      if (st.talking && n) show(n, { loop: true, fade: MOUTH[n] && LIP.on ? 0.1 : 0.18, from: lipStart(n) });
      else if (!st.talking && !st.busy && !st.onceP) park(0.25);
    } else {
      st.talkOffAt = now;
      if (Object.values(TALK_AT).includes(curName)) {
        ++st.token; st.onceP = null;
        park(0.25);
      }
    }
  }
  async function emoTalk(k) {
    const t = ++st.token; st.onceP = null; st.walkDir = 0;
    st.emoTalkK = k; st.emoT = t; st.emoOut = false;
    log('감정 말하기 ' + k);
    try {
      const skipIn = LIP.on && st.live && !!MOUTH[k + '_hold'];
      if (!skipIn && !(await once(k + '_in', t))) return;
      if (st.talking) {
        show(k + '_hold', { loop: true, fade: skipIn ? 0.2 : FADE });
        let off = null;
        for (;;) {
          const now = performance.now();
          if (st.talking) off = null; else if (off === null) off = now; else if (now - off > 700) break;
          if (!(await wait(100, t))) return;
        }
        const hc = CL[k + '_hold'], hv = V[k + '_hold'];   // 유지 끝 장까지 가서 나오기(표정 클립과 같은 이음)
        if (hc && hc.seamOut && hv && cur === hv) {
          prep(V[k + '_out'], 0);
          const N = hc.frames, tEnd = performance.now() + (N / FPS) * 1000 + 300;
          while (performance.now() < tEnd && cur === hv && Math.round(hv.currentTime * FPS) < N - 2) {
            if (!(await wait(12, t))) return;
          }
        }
      }
      st.emoOut = true;
      if (!(await once(k + '_out', t))) return;
      park();
    } finally {
      if (st.emoT === t) { st.emoTalkK = null; st.emoOut = false; }
    }
  }
  // 감정 정하기: 이름 = motion_names.js EMOTIONS 정식 이름 | 'neutral'. 말하는 중이면 바로 그 감정 말하기로 바꿈.
  //   감정은 말이 끝나고 4초 뒤(말을 아직 안 했으면 12초 뒤) 또는 neutral(보통) 이 오면 꺼짐
  function setMood(name, from) {
    if (!name) return;
    if (name === 'neutral') {
      if (!st.mood) return;
      st.mood = null; log('감정 끔' + (from ? ' (' + from + ')' : ''));
      if (st.emoTalkK && st.talking && !st.busy) { st.talking = false; setTalking(true); }
      return;
    }
    if (st.mood !== name) log('감정 ' + name + (from ? ' (' + from + ')' : ''));
    st.mood = name; st.moodAt = performance.now(); st.moodTalked = st.talking;
    if (st.talking && !st.busy && !st.walking) {
      const k = emoTalkClip();
      if (k ? st.emoTalkK !== k : st.emoTalkK) { st.talking = false; setTalking(true); }
    }
  }
  async function talkWalk() {
    st.talkWalkRolled = true;
    if (Math.random() > 0.5 || !has(WL + '_walk') || !has(WR + '_walk')) return;
    st.lastTalkWalk = performance.now();
    let dir = Math.random() < 0.5 ? -1 : 1;
    try {
      const rm = await api.invoke('move-by', { dx: 0, dy: 0 });
      if (rm && typeof rm.roomL === 'number') dir = rm.roomL > rm.roomR ? -1 : 1;
    } catch (e) { /* 무시 */ }
    st.walkForTalk = true;
    try {
      const t = await begin(true);
      await walk(dir, t, 1600 + Math.random() * 1200);
    } finally { st.walkForTalk = false; }
  }

  // ---------------------------------------------------------------- 말풍선(머리 위)
  let bubbleTimer = null;
  function sayBubble(text, sec) {
    bubble.textContent = text;
    bubble.classList.add('show');
    placeBubble();
    clearTimeout(bubbleTimer);
    if (sec) bubbleTimer = setTimeout(() => bubble.classList.remove('show'), sec * 1000);
  }
  function placeBubble() {
    if (!bubble.classList.contains('show')) return;
    const c = CL[curName] || CL.idle;
    const hx = offX + (c.headX != null ? c.headX : SW / 2) * scale, hy = offY + (c.headY != null ? c.headY : 130) * scale;
    const W = window.innerWidth;
    bubble.style.fontSize = Math.max(12, Math.min(22, window.innerHeight / 33)) + 'px';
    const bw = bubble.offsetWidth, bh = bubble.offsetHeight;
    const left = Math.max(6, Math.min(W - bw - 6, hx - bw / 2));
    const top = Math.max(4, hy - bh - 14);
    bubble.style.left = left + 'px'; bubble.style.top = top + 'px';
    bubble.style.setProperty('--tail', Math.max(16, Math.min(bw - 16, hx - left)) + 'px');
  }
  setInterval(placeBubble, 100);

  // ---------------------------------------------------------------- 클릭 판정: 지금 보이는 영상 프레임의 알파
  const hc = document.createElement('canvas'); hc.width = hc.height = 1;
  const hctx = hc.getContext('2d', { willReadFrequently: true });
  function alphaAt(px, py) {
    if (!cur) return 0;
    const c = CL[cur.dataset.name];
    const sx = (px - offX) / scale - c.x, sy = (py - offY) / scale - c.y;
    if (sx < 0 || sy < 0 || sx >= c.w || sy >= c.h) return 0;
    const vx = sx * cur.videoWidth / c.w, vy = sy * cur.videoHeight / c.h;
    try {
      hctx.clearRect(0, 0, 1, 1);
      hctx.drawImage(cur, vx, vy, 1, 1, 0, 0, 1, 1);
      return hctx.getImageData(0, 0, 1, 1).data[3];
    } catch (e) { return 0; }
  }
  window.realAlphaAt = alphaAt;   // 점검용
  function setOver(o) {
    if (o === st.over) return;
    st.over = o;
    document.body.classList.toggle('grab', o);
    api.send('hit', o);
  }
  api.on('cursor', c => {
    st.lastCursor = performance.now();
    if (st.sleeping) wake();
    if (st.dragging) return;
    if (!c.inside) { setOver(false); return; }
    // 손가락 끝 근처도 잡히게 3x3 중 하나라도 진하면 위
    let a = 0;
    for (const [dx, dy] of [[0, 0], [-4, 0], [4, 0], [0, -4], [0, 4]]) a = Math.max(a, alphaAt(c.x + dx, c.y + dy));
    setOver(a > 40);
  });

  // ---------------------------------------------------------------- 누르기·끌기·클릭
  // 포인터 이벤트 + 포인터 잡기: 끄는 중 커서가 창 밖으로 나가도 놓을 때를 받음
  window.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    try { document.body.setPointerCapture(e.pointerId); } catch (err) { /* 무시 */ }
    st.dragging = true; st.dragMoved = false;
    document.body.classList.add('dragging');
    api.send('drag-start');
  });
  const endDrag = async e => {
    const cancel = e.type === 'pointercancel';
    if ((!cancel && e.button !== 0) || !st.dragging) return;
    try { document.body.releasePointerCapture(e.pointerId); } catch (err) { /* 무시 */ }
    const moved = await api.invoke('drag-end');
    st.dragging = false;
    document.body.classList.remove('dragging');
    if (cancel) return;
    if (moved < 5) clickReact(e.clientX, e.clientY);
    else if (st.pose === 'stand') expr('기쁨', 3, false);
  };
  window.addEventListener('pointerup', endDrag);
  window.addEventListener('pointercancel', endDrag);
  api.on('moved', () => {
    st.lastCursor = performance.now();
    if (st.dragging && !st.dragMoved) { st.dragMoved = true; if (st.pose === 'stand') expr('놀람', 2.5, true); }
  });
  window.addEventListener('contextmenu', e => { e.preventDefault(); api.send('context-menu'); });

  let clickN = 0;
  function clickReact(px, py) {
    st.lastConv = performance.now();   // 0.1.7 클릭도 대화로 봄
    if (st.pose === 'sit') { const l = ['기쁨', 'wave', '부끄러움', '웃음']; const k = l[clickN++ % l.length]; if (k === 'wave') motion(k); else expr(k, 3, true); return; }
    if (st.pose !== 'stand') return;                              // 누워·책상·걷는 중엔 클릭으로 일어나지 않음("일어나" 로만)
    const sy = (py - offY) / scale;
    if (sy < 300) { expr('부끄러움', 3, true); return; }          // 머리 쪽
    const list = ['wave', '기쁨', '윙크', '웃음', 'bow'];
    const k = list[clickN++ % list.length];
    if (MOTIONS[k]) motion(k); else expr(k, 3, true);
  }

  // 평소 = 지금 자세의 대기 클립(숨쉬기·눈깜빡임) 반복만. 걷기는 말하는 중 긴 답일 때 가끔 짧게(talkWalk).
  // 앉으면 "일어나"(stand) 전까지 앉은 채. (옛 혼자 움직이기·2분 뒤 눕기는 껐음)
  function wake() { st.sleeping = false; }
  setInterval(() => {
    if (!st.talking && !st.busy && !st.onceP) primeTalk();
    if (DEMO) return;
    const now = performance.now();
    if (st.mood && !st.talking && !st.emoTalkK &&
        (st.moodTalked ? now - Math.max(st.talkOffAt || 0, st.moodAt) > 4000 : now - st.moodAt > 12000)) { st.mood = null; log('감정 끝(시간)'); }
    // 0.1.7(대표님 11-20 02:27): 대화가 없으면 N분 뒤 앉아 대기(서 있을 때만). 돌아다니기·눕기 자동은 계속 끔
    if (IDLE_MIN > 0 && st.pose === 'stand' && !st.busy && !st.onceP && !st.talking && !st.speaking && !st.walking &&
        !st.dancing && !st.dragging && !st.menuOpen && now - st.lastConv >= IDLE_MIN * 60000) {
      log('대화 없음 ' + (Math.round(IDLE_MIN * 10) / 10) + '분 → 앉아 대기');
      st.lastConv = now; st.autoSat = now;
      motion('sit');
    }
    if (st.talking && st.pose === 'stand' && !(LIP.on && MOUTH[TALK_AT.stand]) && !st.busy && !st.talkWalkRolled && !st.onceP && !st.walking && !st.dragging && !st.menuOpen && !st.emoTalkK &&
        now - (st.talkSince || now) > 7000 && now - (st.lastTalkWalk || -1e9) > 45000) talkWalk();
  }, 1000);

  // ---------------------------------------------------------------- 본체 명령
  function clockAudio(dur) {
    let t0 = null; const ls = { ended: [] };
    return { play() { t0 = performance.now(); setTimeout(() => ls.ended.forEach(f => f()), dur * 1000); return Promise.resolve(); },
      addEventListener(n, f) { (ls[n] || (ls[n] = [])).push(f); } };
  }
  api.on('speak', async m => {
    st.speaking = true; st.sleeping = false; st.lastConv = performance.now();   // 0.1.7 대화 시각
    const url = URL.createObjectURL(new Blob([m.wav], { type: 'audio/wav' }));
    sayBubble(m.text, 0);
    const playIt = a => new Promise(res => { a.addEventListener('ended', res); a.addEventListener('error', res); a.play().catch(res); });
    try {
      setTalking(true);
      api.send('speak-started', m.id);
      let a;
      try { a = new Audio(url); await playIt(a); } catch (e) { log('소리 재생 안 됨 → 시계: ' + e.message); await playIt(clockAudio(m.data.dur)); }
    } finally {
      URL.revokeObjectURL(url);
      st.speaking = false;
      if (!st.live) setTalking(false);
      if (m.expr && m.expr !== '보통') expr(m.expr, 3, false);
      bubbleTimer = setTimeout(() => bubble.classList.remove('show'), 1400);
      api.send('speak-done', m.id);
    }
  });
  // 점검용: 본체 신호를 받은 수·최근 값(REAL.sig)
  const SIG = { expr: [], motion: [], emotion: [], mouth: 0, mouthMax: 0, talk: 0, bubble: 0 };
  const sigPush = (k, v) => { SIG[k].push(v); if (SIG[k].length > 30) SIG[k].shift(); };
  api.on('expr', m => {
    sigPush('expr', m.raw || m.name);
    const em = MOTION_NAMES.emotionOf(m.raw || m.name);
    if (em && em !== 'neutral') setMood(em, '/expr');
    expr(m.raw || m.name, m.sec, false);
  });
  api.on('emotion', m => { const n = typeof m === 'string' ? m : m && m.name; sigPush('emotion', n); setMood(MOTION_NAMES.emotionOf(n), '/emotion'); });
  api.on('motion', m => { const n = typeof m === 'string' ? m : m && m.name; sigPush('motion', n); motion(n); });
  //   입 메타가 있는 말하기 클립일 때만(없으면 클립을 올리는 순간 입이 움직여 소리보다 먼저 움직이게 됨). 1.5초 안에 소리가 안 오면 대기로.
  api.on('talk', m => {
    SIG.talk++;
    if (m && m.on === false) return;
    st.lastConv = performance.now();   // 0.1.7 대화 시각
    const n = talkClip();
    if (!LIP.on || !n || !MOUTH[n] || st.busy || st.dancing || st.speaking || st.mood) return;
    if (!st.live) log('말하기 준비 → 말하기 클립을 미리 올림');
    st.live = true; st.sleeping = false;
    LIP.wait = !st.talking;   // 새로 올리는 경우에만(이미 말하는 중이면 그대로)
    setTalking(true);
    clearTimeout(st.liveTimer);
    st.liveTimer = setTimeout(() => { st.live = false; if (!st.speaking) setTalking(false); }, 1500);
  });
  api.on('mouth', m => {
    const lv = +(m && m.level) || 0;
    SIG.mouth++; SIG.mouthMax = Math.max(SIG.mouthMax, lv);
    LIP.level = lv; LIP.at = performance.now();
    if (LIP.v) lipTick();   // 0.025초 박자를 기다리지 않고 바로 반영
    if (lv > 0.06) {
      if (!st.live) log('바깥 목소리 → 말하기 클립');
      st.live = true; st.sleeping = false; st.lastConv = performance.now();   // 0.1.7 대화 시각
      setTalking(true);
      clearTimeout(st.liveTimer);
      st.liveTimer = setTimeout(() => { st.live = false; if (!st.speaking) setTalking(false); }, 900);
    }
  });
  api.on('bubble', m => { SIG.bubble++; if (m.text) sayBubble(m.text, m.sec); else bubble.classList.remove('show'); });
  api.on('react', k => { if (k === 'hello') { motion('wave'); sayBubble('여기 있어요!', 2.4); } });
  api.on('menu-open', o => { st.menuOpen = !!o; if (o && st.pose === 'stand' && !st.talking) expr('생각', 3, false); });
  api.on('skin', sk => {
    if (!sk || sk === SKIN) return;
    if (!(M.outfits && M.outfits[sk])) { log('옷 클립 없음 ' + sk); return; }
    const q = new URLSearchParams(location.search); q.set('skin', sk);
    stopDanceMusic(0);
    stage.classList.add('out'); view.classList.add('out'); bubble.classList.remove('show');
    setTimeout(() => location.replace(location.pathname + '?' + q.toString()), 260);
  });
  window.petFadeOut = () => new Promise(res => { stage.classList.add('out'); view.classList.add('out'); bubble.classList.remove('show'); setTimeout(res, 240); });
  api.on('draw', m => setDraw(typeof m === 'string' ? m : m && m.mode, (m && m.why) || '본체 알림'));

  // 점검·시연용 손잡이
  window.REAL = { skin: SKIN, motion, expr, setTalking, setMood, sayBubble, extra: EXTRA, get lip() { return { on: LIP.on, clips: Object.keys(MOUTH).length, level: LIP.level, ticks: LIP.ticks, rate: cur ? cur.playbackRate : 1, holds: DRAW.holds || 0 }; }, get music() { return musicLevel; }, walk: async (dir, ms) => { const t = await begin(false); await walk(dir, t, ms); }, get pose() { return st.pose; }, get clip() { return curName; }, get idleMin() { return IDLE_MIN; }, get stats() { return { on: STAT.on, name: STAT.name }; }, get seat() { return SEAT; }, hist: HIST, sig: SIG, variants: VARIANT, alphaAt, st,
    setDraw, get draw() { return { mode: DRAW.mode, paints: DRAW.paints, vf: DRAW.vf, fails: DRAW.fails, layers: LAYERS.map(l => ({ name: l.v.dataset.name, a: +l.a.toFixed(2), ts: l.ts })), canvas: [view.width, view.height], dpr: window.devicePixelRatio, scale }; } };

  setDraw(Q.get('draw') || (PD && PD.draw) || 'canvas');
  park();
  log('준비됨 클립 ' + Object.keys(CL).length + '개, 창 ' + window.innerWidth + 'x' + window.innerHeight + ' · 입 맞추기 ' + (LIP.on ? '켬' : '끔') + '(입 메타 ' + Object.keys(MOUTH).length + '개) · 춤 노래 크기 ' + musicLevel
    + ' · 앉아 대기 ' + (IDLE_MIN ? (Math.round(IDLE_MIN * 10) / 10) + '분' : '끔') + ' · 재생 기록 ' + (STAT.on ? '켬' : '끔') + (SEAT ? ' · 좌석 ' + SEAT : ''));
  window.dispatchEvent(new Event('pet-ready'));
})();
