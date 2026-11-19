/* 오른쪽 클릭 메뉴: 옷(바로 갈아입음, 메뉴는 열린 채) · 옷 관리·옷 더 받기·파일로 추가 · 크기 · 춤 노래 크기 · 항상 위 · 춤 추기 · 말하기 시험 · 끝내기 */
(function () {
  'use strict';
  const api = window.petApi;
  const $ = id => document.getElementById(id);
  const pick = (type, value) => api.send('menu-pick', { type, value });
  let S = null, toastTimer = null;
  // 화면 언어(0.1.18~) — 본체가 state 로 넘겨 주는 사전(한국어 원문이 열쇠). 한국어면 그대로.
  const D = k => (S && S.dict && S.dict[k]) || k;
  function T(s, ...a) { let t = D(s); a.forEach((v, i) => { t = t.split('{' + i + '}').join(String(v)); }); return t; }
  function applyStatic() {
    try { document.documentElement.lang = (S && S.lang) || 'ko'; } catch (e) { /* 무시 */ }
    if (!S || !S.lang || S.lang === 'ko' || !S.dict) return;
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = []; while (walk.nextNode()) nodes.push(walk.currentNode);
    for (const n of nodes) {
      const t = n.nodeValue, k = t.trim();
      if (k && S.dict[k]) n.nodeValue = t.replace(k, S.dict[k]);
    }
    document.querySelectorAll('[title]').forEach(e => { const v = e.getAttribute('title'); if (v && S.dict[v]) e.setAttribute('title', S.dict[v]); });
    document.querySelectorAll('[placeholder]').forEach(e => { const v = e.getAttribute('placeholder'); if (v && S.dict[v]) e.setAttribute('placeholder', S.dict[v]); });
  }

  function el(tag, cls, kids) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    for (const k of kids || []) e.appendChild(typeof k === 'string' ? document.createTextNode(k) : k);
    return e;
  }
  function img(src) { const i = document.createElement('img'); i.src = src; i.alt = ''; i.draggable = false; return i; }
  function toast(t) { $('toast').textContent = t; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').textContent = ''; }, 2600); }

  function render() {
    if (!S) return;
    applyStatic();
    const o = $('outfits'); o.textContent = ''; o.className = 'outfits' + (S.outfits.length === 1 ? ' one' : '');
    if (!S.outfits.length) o.appendChild(el('div', 'empty', [T('넣은 옷이 없어요 — 아래 「옷 더 받기」를 눌러 주세요')]));
    for (const f of S.outfits) {
      const b = el('button', 'outfit' + (S.skin === f.id ? ' on' : ''), [img(/^(file|data):/.test(f.img || '') ? f.img : 'img/icon.png'), el('span', '', [T(f.name) + (f.songs || S.danceMusic === false ? '' : ' · ' + T('노래 없음'))])]);
      b.dataset.skin = f.id;
      b.onclick = () => { pick('skin', f.id); toast(T('{0} 입었어요', T(f.name))); };
      o.appendChild(b);
    }
    const s = $('sizes'); s.textContent = '';
    for (const z of S.sizes) {
      const b = el('button', 'btn' + (S.size === z ? ' on' : ''), [T(z)]);
      b.dataset.size = z;
      b.onclick = () => pick('size', z);
      s.appendChild(b);
    }
    const fine = $('sizefine');   // 세밀 크기: 5%씩(50~200%) — 김비서 설정 → 펫 의 슬라이더와 같은 값
    if (fine) {
      fine.textContent = '';
      const pct = S.sizePct || 100, rng = S.sizeRange || [50, 200];
      const dn = el('button', 'btn', [T('조금 작게')]); dn.dataset.sizestep = 'down'; dn.disabled = pct <= rng[0]; dn.onclick = () => pick('size-step', 'down');
      const up = el('button', 'btn', [T('조금 크게')]); up.dataset.sizestep = 'up'; up.disabled = pct >= rng[1]; up.onclick = () => pick('size-step', 'up');
      const lab = el('span', 'pct', [pct + '%']); lab.id = 'sizepct';
      fine.append(dn, lab, up);
    }
    const mu = $('music'); mu.textContent = '';   // 춤 노래 크기(기본 보통 = 목소리보다 작게) — 춤 노래를 끈 판이면 칸째 숨김
    mu.style.display = $('music-h').style.display = (S.musicLevels || []).length ? '' : 'none';
    for (const z of S.musicLevels || []) {
      const b = el('button', 'btn' + (S.musicVolume === z ? ' on' : ''), [T(z)]);
      b.dataset.music = z;
      b.onclick = () => { pick('music', z); toast(T('춤 노래 크기: {0}', T(z))); };
      mu.appendChild(b);
    }
    const ids = $('idlesit');   // 0.1.7 대화가 없으면 앉아 대기(끔·1·3·5·10분)
    if (ids) {
      ids.textContent = '';
      for (const n of (S.idleLevels || [0, 1, 3, 5, 10])) {
        const b = el('button', 'btn' + (S.idleSit === n ? ' on' : ''), [n ? T('{0}분', n) : T('끔')]);
        b.dataset.idlesit = String(n);
        b.onclick = () => { pick('idle-sit', n); toast(n ? T('{0}분 동안 대화가 없으면 앉아 있어요', n) : T('앉아 대기 끔')); };
        ids.appendChild(b);
      }
    }
    const ps = $('playstats');
    if (ps) {
      ps.textContent = S.playStats ? T('켜짐') : T('꺼짐');
      ps.className = 'btn' + (S.playStats ? ' on' : '');
    }
    const t = $('ontop');
    t.textContent = S.onTop ? T('켜짐') : T('꺼짐');
    t.className = 'btn' + (S.onTop ? ' on' : '');
    $('ver').textContent = 'v' + S.version + (S.port ? ' · ' + T('펫 신호 입구') + ' 127.0.0.1:' + S.port : '');
    requestAnimationFrame(() => api.send('menu-height', Math.ceil(document.getElementById('card').scrollHeight + 14)));
  }
  $('x').onclick = () => pick('close');
  $('ontop').onclick = () => pick('ontop', !S.onTop);
  $('playstats').onclick = () => pick('play-stats', !S.playStats);
  $('dance').onclick = () => pick('dance');
  $('speak').onclick = () => pick('speak-test');
  $('home').onclick = () => { pick('home'); toast(T('화면 오른쪽 아래로 옮겼어요')); };
  $('ward').onclick = () => pick('wardrobe', 'mine');
  $('wardget').onclick = () => pick('wardrobe', 'get');
  $('packfile').onclick = () => pick('pack-file');
  $('quit').onclick = () => pick('quit');
  window.addEventListener('keydown', e => { if (e.key === 'Escape') pick('close'); });
  window.addEventListener('contextmenu', e => e.preventDefault());
  api.on('state', s => { S = s; render(); });
  api.invoke('menu-state').then(s => { S = s; render(); });
})();
