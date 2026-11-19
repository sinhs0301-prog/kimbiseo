'use strict';
/* 김비서 펫 — 윈도우 바탕화면 펫(Electron)
   - 투명·테두리 없는 창, 항상 위, 캐릭터 밖은 클릭이 아래 창으로 통과(그림의 픽셀 알파로 판정), 끌어서 옮기기, 오른쪽 클릭 = 한국어 메뉴
   - 옷 = 옷 꾸러미(.hipcpet). 프로그램 안에는 옷이 없음: 옷 목록(outfits.json — 옷 저장소)에서 고른 것만 받거나 파일로 넣음(<프로필>\옷\<id>\)
   - 김비서 본체가 표정·입·말풍선·동작 신호를 보냄: HTTP 입구 127.0.0.1:17961(쓰는 중이면 +1~+9, 실제 번호는 프로필 speak_port.txt)
   - 말하기 시험(메뉴)은 김비서 목소리 서버(config.json voice_url, 본체가 켬)가 있으면 그것, 없으면 윈도우 기본 음성
   - 옷 → 목소리: 지금 입은 옷에 맞는 목소리 이름을 목소리 서버 요청에 넣음(대응표 = voice/voices.json "옷목소리" — speech.js voiceFor).
     본체도 GET /extras 의 skin·gender·packVoice 로 같은 표를 봄 → 옷을 갈아입으면 다음 말부터 그 옷의 목소리
   실행 인자: --profile=<폴더>(설정·옷·로그를 그 폴더에) · --pack-source=<옷 목록 주소> · --add-pack=<파일> · --assoc(.hipcpet 파일 연결)
             --auto-pack(옷이 없으면 기본 옷 저절로 받기) · --want-pack=<옷 id>(본체 설정의 펫 캐릭터 — 옷이 하나도 없을 때 이 옷부터 받음)
             --draw=canvas|video · --gpu-unblock
             --virtual-screen=x,y,너비,높이(시험용: 진짜 화면 밖 좌표 → 창은 그려지지만 화면엔 안 보임, 가짜 커서, 소리 끔, 알림 영역 아이콘 없음) */
const { app, BrowserWindow, ipcMain, screen, Tray, Menu, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const { Tts, VoiceServer } = require('./speech');
const { startServer } = require('./server');
const packs = require('./packs');
const G = require('./geometry');   // 자리·크기 계산(화면 목록만 받아 계산 — 시험: tests/unit/test_pet_geometry.js)
const MOTION_NAMES = require('./renderer/real/motion_names.js');

const argVal = k => { const a = process.argv.find(x => x.startsWith('--' + k + '=')); return a ? a.slice(k.length + 3) : null; };
const PROFILE = argVal('profile');
const VS = (() => {
  const n = String(argVal('virtual-screen') || '').split(',').map(Number);
  return n.length === 4 && n.every(Number.isFinite) && n[2] >= 400 && n[3] >= 300 ? { x: n[0], y: n[1], width: n[2], height: n[3] } : null;
})();
const DRAW_ARG = argVal('draw');
const addPackArgs = argv => argv.filter(a => a.startsWith('--add-pack=')).map(a => a.slice(11).replace(/^"|"$/g, '')).filter(Boolean);

// 프로그램 설정(config.json): 옷 목록 주소·받아도 되는 호스트·목소리 서버 주소·포트
const CONFIG = (() => {
  const d = { packs_catalog: '', packs_catalog_backup: '', allowed_hosts: ['github.com', 'raw.githubusercontent.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com'],
    voice_url: 'http://127.0.0.1:8871', voices_file: '', port: 17961, default_pack: 'kimbiseo_f', dance_music: true };
  try { return { ...d, ...JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8')) }; } catch (e) { return d; }
})();

app.setName('KimBiseoPet');
app.setPath('userData', PROFILE ? path.resolve(PROFILE) : path.join(app.getPath('appData'), 'KimBiseo', 'pet'));
app.commandLine.appendSwitch('disable-renderer-backgrounding');
if (VS) app.commandLine.appendSwitch('disable-backgrounding-occluded-windows');
if (process.argv.includes('--gpu-unblock')) app.commandLine.appendSwitch('ignore-gpu-blocklist');

const VERSION = require('./package.json').version;
const SIZES = { 작게: 380, 보통: 500, 크게: 660, '아주 크게': 860 };
const MUSIC_LEVELS = ['끔', '작게', '보통', '크게'];
const TEST_LINE = '안녕하세요! 김비서예요. 이렇게 말로 알려 드릴게요.';

// ---------------------------------------------------------------- 화면 언어(0.1.18~)
//   본체가 --lang=으로 넘겨 줌(없으면 %APPDATA%\KimBiseo\settings.json 의 '언어'). 사전 = 본체와 같은 app\i18n\<언어>.json.
const LANG = (() => {
  const pick = code => { const c = String(code || '').trim().toLowerCase(); return c.startsWith('en') ? 'en' : c.startsWith('ja') ? 'ja' : c.startsWith('zh') ? 'zh' : c.startsWith('ko') ? 'ko' : ''; };
  const a = pick(argVal('lang'));
  if (a) return a;
  try {
    const b = JSON.parse(fs.readFileSync(path.join(app.getPath('appData'), 'KimBiseo', 'settings.json'), 'utf8'));
    const v = pick(b['언어']);
    if (v) return v;
  } catch (e) { /* 설정이 없거나 못 읽음 */ }
  return 'ko';
})();
const I18N = (() => {
  if (LANG === 'ko') return {};
  for (const p of [path.join(__dirname, '..', 'app', 'i18n', LANG + '.json'), path.join(app.getAppPath(), '..', 'app', 'i18n', LANG + '.json')]) {
    try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (e) { /* 다음 자리 */ }
  }
  return {};
})();
function T(s, ...a) {
  let t = (LANG !== 'ko' && I18N[s]) || s;
  a.forEach((v, i) => { t = t.split('{' + i + '}').join(String(v)); });
  return t;
}

// ---------------------------------------------------------------- 기록·설정
const USER = app.getPath('userData');
fs.mkdirSync(USER, { recursive: true });
const LOG = path.join(USER, '로그.txt');
function log(msg) {
  const line = new Date().toISOString() + ' ' + msg + '\n';
  try {
    if (fs.existsSync(LOG) && fs.statSync(LOG).size > 1e6) fs.renameSync(LOG, LOG.replace(/\.txt$/, '_이전.txt'));
    fs.appendFileSync(LOG, line, 'utf8');
  } catch (e) { /* 기록 실패는 무시 */ }
}
const SETTINGS = path.join(USER, 'settings.json');
// packSource = 옷 목록 주소(비우면 config.json) · autoPack = 옷이 없을 때 기본 옷 저절로 받기(처음 화면에서 동의했을 때만) · assoc = .hipcpet 파일 연결
// wantPack = 본체가 입으라고 한 옷(아직 없어서 받는 중일 때만 남김 — 받아서 입으면 지움)
// appliedWant = 마지막으로 반영한 본체 설정의 펫 캐릭터(--want-pack). 본체 설정이 바뀐 것을 알아보는 데만 씀(펫 메뉴에서 직접 갈아입은 옷은 그대로 둠)
const DEFAULTS = { skin: null, size: '보통', onTop: true, x: null, y: null, musicVolume: '보통', packSource: '', autoPack: false, assoc: false, wantPack: '', appliedWant: null };
let S = { ...DEFAULTS };
try { S = { ...DEFAULTS, ...JSON.parse(fs.readFileSync(SETTINGS, 'utf8')) }; } catch (e) { /* 처음 실행 */ }
if (!SIZES[S.size]) S.size = DEFAULTS.size;
if (!(Number.isFinite(S.sizePx) && S.sizePx >= G.pctToPx(G.PCT_MIN) && S.sizePx <= G.pctToPx(G.PCT_MAX))) S.sizePx = null;   // 세밀 크기(없으면 단계 크기)
if (!MUSIC_LEVELS.includes(S.musicVolume)) S.musicVolume = '보통';
const PACK_SOURCE = String(argVal('pack-source') || S.packSource || CONFIG.packs_catalog || '').trim();
const PACK_BACKUP = String(CONFIG.packs_catalog_backup || '').trim();   // 첫 주소가 안 될 때만(공개판 = 본 저장소 최신 릴리스의 옛 packs.json)
const ALLOWED = (Array.isArray(CONFIG.allowed_hosts) ? CONFIG.allowed_hosts : []).map(h => String(h).toLowerCase());
const ASSOC = process.argv.includes('--assoc') || S.assoc === true;
let AUTO_PACK = !process.argv.includes('--no-auto-pack') && (process.argv.includes('--auto-pack') || S.autoPack === true);   // 본체 처음 화면에서 동의하면 /packs/auto 로도 켬
let saveTimer = null;
function saveSettings() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try { fs.writeFileSync(SETTINGS + '.tmp', JSON.stringify(S, null, 1), 'utf8'); fs.renameSync(SETTINGS + '.tmp', SETTINGS); }
    catch (e) { log('설정 저장 실패 ' + e.message); }
  }, 400);
}

// ---------------------------------------------------------------- 옷 꾸러미 읽기(설치된 것 → 옷 목록·클립)
let PACKS = [];          // 설치된 옷 꾸러미(packs.list)
let REAL_DATA = null;    // 화면(real.js)에 주는 목록: { stage, fps, walkSpeed, outfits: { id: { clips } } }
const REAL_CLIPS = {};   // 옷 id → 클립 이름 Set
const REAL_EXTRA = {};   // 옷 id → 추가 동작·춤·자세별 판(motion_names.js extras)
function refreshPacks() {
  try { PACKS = packs.list(USER); } catch (e) { log('옷 목록 못 읽음 ' + e.message); PACKS = []; }
  for (const k of Object.keys(REAL_CLIPS)) delete REAL_CLIPS[k];
  for (const k of Object.keys(REAL_EXTRA)) delete REAL_EXTRA[k];
  const first = PACKS[0] || {};
  REAL_DATA = { version: 3, stage: first.stage || { w: 960, h: 960, floor: 948 }, fps: first.fps || 24, walkSpeed: first.walkSpeed || 90, clips: {}, outfits: {} };
  for (const p of PACKS) {
    REAL_DATA.outfits[p.id] = { clips: p.clips };
    REAL_CLIPS[p.id] = new Set(Object.keys(p.clips));
    REAL_EXTRA[p.id] = MOTION_NAMES.extras(p.clips);
    const ex = REAL_EXTRA[p.id], nv = Object.keys(ex.variants || {}).length;
    if (ex.motions.length || ex.dances.length || ex.skipped.length || nv) log('[옷 ' + p.id + '] 추가 동작 ' + ex.motions.map(m => m.name).join(',') + ' · 추가 춤 ' + ex.dances.map(m => m.name).join(',')
      + ' · 자세별 동작 ' + nv + '개' + (ex.skipped.length ? ' · 버린 것 ' + ex.skipped.map(x => x[0] + '(' + x[1] + ')').join(', ') : ''));
  }
  // 입을 옷: 저장한 옷이 있으면 그것, 없으면 기본 옷(config default_pack), 그것도 없으면 첫 옷
  if (!PACKS.some(p => p.id === S.skin)) S.skin = (PACKS.find(p => p.id === CONFIG.default_pack) || PACKS[0] || {}).id || null;
  return PACKS;
}
refreshPacks();
const hasOutfit = () => !!(S.skin && PACKS.some(p => p.id === S.skin));
const packOf = id => PACKS.find(p => p.id === id) || null;
const songsOf = p => (p && p.music ? p.music.length : 0);

// ---------------------------------------------------------------- 화면(시험 때는 가상 화면)
const env = {
  virtual: VS ? { cursor: { x: Math.round(VS.x + VS.width / 2), y: Math.round(VS.y + VS.height / 2) }, area: VS } : null,
  cursor() { return this.virtual ? { ...this.virtual.cursor } : screen.getCursorScreenPoint(); },
  workAreaAt(pt) { return this.virtual ? this.virtual.area : screen.getDisplayNearestPoint(pt).workArea; },
  // 화면(작업 영역) 목록 — 주 화면이 맨 앞. id·배율도 같이(자리 기억에 씀)
  allAreas() {
    if (this.virtual) return [{ id: 0, ...this.virtual.area, scale: 1, primary: true }];
    const pid = screen.getPrimaryDisplay().id;
    return G.primaryFirst(screen.getAllDisplays().map(d => ({ id: d.id, ...d.workArea, scale: d.scaleFactor, primary: d.id === pid })));
  },
};
const pos = { x: S.x, y: S.y };
function petSize() {
  const wa = env.workAreaAt(pos.x !== null ? { x: pos.x, y: pos.y } : env.cursor());
  const h = Math.min(S.sizePx || SIZES[S.size], wa.height);
  return { w: h, h };   // 정사각(눕기 클립 폭까지 들어가게)
}
const defaultPos = sz => G.defaultPos(sz, env.allAreas());
const visibleEnough = (x, y, sz) => G.visibleEnough(x, y, sz, env.allAreas());
const nearestArea = (cx, cy) => G.nearestArea(cx, cy, env.allAreas());
const clampPos = (x, y, sz) => G.clampPos(x, y, sz, env.allAreas());
// 지금 자리를 기억(좌표 + 어느 화면의 어디쯤) — 저장은 부르는 쪽이
function keepPos() {
  S.x = pos.x; S.y = pos.y;
  try { S.disp = G.remember(pos.x, pos.y, petSize(), env.allAreas()).disp; } catch (e) { /* 화면 목록을 못 읽으면 좌표만 */ }
}
// ---------------------------------------------------------------- GPU 상태·그리기 방식
// 그리기: 기본 = 캔버스(영상을 창 픽셀 크기로 고화질로 줄여 그림 — GPU 가속이 없는 PC 에서도 가장자리가 안 깨짐). settings.json "draw":"video" 또는 --draw=video 로 되돌림.
const GPU = { comp: null, soft: null, deaths: 0, lastDeath: '', drawNow: null };
function drawMode() {
  const want = ['canvas', 'video', 'auto'].includes(DRAW_ARG) ? DRAW_ARG : (['canvas', 'video'].includes(S.draw) ? S.draw : 'auto');
  return want === 'auto' ? 'canvas' : want;
}
function gpuLine() {
  const st = GPU.comp === null ? 'GPU 확인 전' : GPU.soft ? `소프트웨어 합성(GPU 가속 없음, ${GPU.comp})` : 'GPU 가속 켜짐';
  return [st, '그리기 ' + ((GPU.drawNow || drawMode()) === 'canvas' ? '캔버스(고화질)' : '영상 그대로'),
    'GPU 죽음 ' + GPU.deaths + '번' + (GPU.lastDeath ? '(마지막 ' + GPU.lastDeath + ')' : '')].join(' · ');
}
function gpuCheck(why) {
  let st = {};
  try { st = app.getGPUFeatureStatus() || {}; } catch (e) { /* 무시 */ }
  const comp = String(st.gpu_compositing || '모름');
  if (comp === GPU.comp) return;
  GPU.comp = comp; GPU.soft = !/^enabled/.test(comp);
  log(`GPU 상태(${why}): ${GPU.soft ? '소프트웨어 합성(GPU 가속 없음)' : 'GPU 가속 켜짐'} — gpu_compositing=${comp} video_decode=${st.video_decode}`);
}
app.on('child-process-gone', (e, d) => {
  if (!d || d.reason === 'clean-exit') return;
  log('프로세스 죽음 ' + JSON.stringify({ type: d.type, reason: d.reason, exitCode: d.exitCode, name: d.name || d.serviceName }));
  if (d.type === 'GPU') { GPU.deaths++; GPU.lastDeath = d.reason + ' ' + d.exitCode; setTimeout(() => gpuCheck('GPU 프로세스 죽은 뒤'), 2000); }
});
let gpuUpdTimer = null;
app.on('gpu-info-update', () => { clearTimeout(gpuUpdTimer); gpuUpdTimer = setTimeout(() => gpuCheck('GPU 정보 바뀜'), 300); });

// ---------------------------------------------------------------- 창
let pet = null, menu = null, tray = null, quitting = false;
const menuState = { visible: false, x: 0, y: 0, w: 400, h: 560 };
let ignoring = true;
const petSend = (ch, d) => { if (pet && !pet.isDestroyed()) pet.webContents.send(ch, d); };
const menuSend = (ch, d) => { if (menu && !menu.isDestroyed()) menu.webContents.send(ch, d); };
const ICON = path.join(__dirname, 'renderer', 'img', 'icon.png');
const WEB = { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true, spellcheck: false };

function setPetBounds(x, y, sz) {
  pos.x = x; pos.y = y;
  if (pet && !pet.isDestroyed()) pet.setBounds({ x, y, width: sz.w, height: sz.h });
}
function guardContents(wc, name) {
  wc.setWindowOpenHandler(() => ({ action: 'deny' }));
  wc.on('will-navigate', e => e.preventDefault());
  wc.on('console-message', e => { if (e.level === 'warning' || e.level === 'error') log(name + ' 콘솔: ' + String(e.message).slice(0, 300)); });
}
function createPet() {
  const sz = petSize();
  const at = G.restore({ x: pos.x, y: pos.y, disp: S.disp }, sz, env.allAreas());   // 기억한 화면이 없거나 배치가 바뀌었으면 보이는 곳으로
  pos.x = at.x; pos.y = at.y;
  log(`펫 자리: ${at.why} (${at.x},${at.y}) · 화면 ${env.allAreas().map(a => `${a.width}x${a.height}@${a.x},${a.y}×${a.scale}`).join(' | ')}`);
  pet = new BrowserWindow({
    x: pos.x, y: pos.y, width: sz.w, height: sz.h, useContentSize: true,
    show: false, frame: false, transparent: true, backgroundColor: '#00000000', hasShadow: false,
    resizable: false, maximizable: false, minimizable: false, fullscreenable: false, skipTaskbar: true,
    focusable: false, alwaysOnTop: S.onTop, title: '김비서 펫', icon: ICON,
    webPreferences: { ...WEB, backgroundThrottling: false },
  });
  pet.setMenu(null);
  if (S.onTop) pet.setAlwaysOnTop(true, 'floating');
  loadPet();
  pet.once('ready-to-show', () => { pet.showInactive(); pet.setIgnoreMouseEvents(true, { forward: true }); });
  let hung = false;
  pet.on('responsive', () => { if (hung) log('펫 화면 다시 응답'); hung = false; });
  pet.on('unresponsive', () => {
    hung = true; log('펫 화면 응답 없음');
    if (!quitting) setTimeout(() => { if (hung && pet && !pet.isDestroyed()) { log('펫 화면 계속 멈춤 → 다시 띄움'); pet.webContents.forcefullyCrashRenderer(); } }, 5000);
  });
  pet.webContents.on('render-process-gone', (e, d) => { log('펫 화면 죽음 ' + JSON.stringify(d)); if (!quitting) setTimeout(() => pet && !pet.isDestroyed() && pet.reload(), 1000); });
  guardContents(pet.webContents, '펫');
  if (VS) pet.webContents.setAudioMuted(true);
  pet.on('closed', () => { pet = null; });
}
let lastSkin = null;   // 지금 페이지에 실린 옷(같은 옷을 또 고르면 다시 안 불러옴)
function loadPet() {
  lastSkin = hasOutfit() ? S.skin : null;
  const page = lastSkin ? 'real.html' : 'none.html';
  return pet.loadFile(path.join(__dirname, 'renderer', page), { query: lastSkin ? { skin: lastSkin } : {} }).catch(() => {});
}
// 옷 바꾸기: 사라지는 효과 → 새 옷으로 다시 불러옴. 한 번에 하나씩, 그 사이 또 고르면 마지막 것만 한 번 더
let switching = null, switchAgain = false;
function reloadPet() {
  switchAgain = true;
  if (switching) return switching;
  switching = (async () => { while (switchAgain) { switchAgain = false; await reloadOnce(); } })().finally(() => { switching = null; });
  return switching;
}
async function reloadOnce() {
  if (!pet || pet.isDestroyed()) return;
  try { await Promise.race([pet.webContents.executeJavaScript('window.petFadeOut ? window.petFadeOut() : null'), new Promise(r => setTimeout(r, 1000))]); } catch (e) { /* 무시 */ }
  if (!pet || pet.isDestroyed()) return;
  ignoring = false; setOver(false);
  await Promise.race([loadPet(), new Promise(r => setTimeout(r, 5000))]);
}

function createMenu() {
  menu = new BrowserWindow({
    width: menuState.w, height: menuState.h, show: false, frame: false, transparent: true, backgroundColor: '#00000000',
    resizable: false, maximizable: false, minimizable: false, fullscreenable: false, skipTaskbar: true, alwaysOnTop: true,
    hasShadow: false, title: '김비서 펫 메뉴', webPreferences: WEB,
  });
  menu.setMenu(null);
  menu.setAlwaysOnTop(true, 'pop-up-menu');
  menu.loadFile(path.join(__dirname, 'renderer', 'menu.html'));
  menu.on('blur', () => { if (!VS) hideMenu(); });
  guardContents(menu.webContents, '메뉴');
  menu.on('closed', () => { menu = null; });
}

// 세밀 크기: 퍼센트(50~200, 100 = '보통'). 단계 크기와 같은 값이면 그 단계로 표시
function sizePctNow() { return G.pxToPct(S.sizePx || SIZES[S.size]); }
function applySizePct(pct) {
  const old = petSize();
  const px = G.pctToPx(pct);
  const named = Object.keys(SIZES).find(k => SIZES[k] === px);
  if (named) { S.size = named; S.sizePx = null; } else S.sizePx = px;
  const sz = petSize();
  const p = G.resizeKeepFeet(pos.x, pos.y, old, sz, env.allAreas());
  setPetBounds(p.x, p.y, sz);
  keepPos();
  saveSettings();
  menuSend('state', state());
  return { ok: true, sizePct: sizePctNow(), sizePx: sz.h, size: S.sizePx ? null : S.size };
}
function outfitsState() {
  return PACKS.map(p => ({ id: p.id, name: p.name, img: p.img, version: p.version, signed: p.signed, songs: songsOf(p) }));
}
function state() {
  return { version: VERSION, outfits: outfitsState(), sizes: Object.keys(SIZES), skin: hasOutfit() ? S.skin : null,
    size: S.sizePx ? null : S.size, sizePct: sizePctNow(), sizePx: S.sizePx || SIZES[S.size], sizeRange: [G.PCT_MIN, G.PCT_MAX], onTop: S.onTop, speaking: !!current, queue: speakQueue.length, port: httpPort,
    musicVolume: S.musicVolume, musicLevels: DANCE_MUSIC ? MUSIC_LEVELS : [], danceMusic: DANCE_MUSIC,
    lang: LANG, dict: LANG === 'ko' ? null : I18N };
}

function openMenu(at, nearPet = true) {
  if (!menu || menu.isDestroyed()) createMenu();
  const c = at || env.cursor();
  const wa = env.workAreaAt(c);
  const w = menuState.w, h = Math.min(menuState.h, wa.height - 8);
  const fits = x => x >= wa.x && x + w <= wa.x + wa.width;
  let x;
  if (nearPet) {   // 펫을 가리지 않게: 캐릭터(창 가운데) 바깥 옆에 붙임 — 커서 쪽을 먼저, 자리가 없으면 반대쪽
    const ps = petSize(), left = pos.x + ps.w * 0.22, right = pos.x + ps.w * 0.78;
    const R = Math.round(right + 8), L = Math.round(left - 8 - w);
    x = (c.x >= pos.x + ps.w / 2 ? [R, L] : [L, R]).find(fits);
  }
  if (x === undefined) { x = c.x + 14; if (!fits(x)) x = c.x - w - 14; }
  x = Math.max(wa.x, Math.min(x, wa.x + wa.width - w));
  const y = Math.max(wa.y + 4, Math.min(c.y - 60, wa.y + wa.height - h - 4));
  Object.assign(menuState, { visible: true, x: Math.round(x), y: Math.round(y) });
  menu.setBounds({ x: menuState.x, y: menuState.y, width: w, height: h });
  menuSend('state', state());
  if (VS) menu.showInactive(); else { menu.show(); menu.focus(); }
  petSend('menu-open', true);
}
function hideMenu() {
  if (!menuState.visible) return;
  menuState.visible = false;
  if (menu && !menu.isDestroyed()) menu.hide();
  petSend('menu-open', false);
}
function applySize(name) {
  if (!SIZES[name]) return;
  const old = petSize();
  S.size = name; S.sizePx = null;
  const sz = petSize();
  const p = G.resizeKeepFeet(pos.x, pos.y, old, sz, env.allAreas());   // 발 위치(아래 가운데) 그대로
  setPetBounds(p.x, p.y, sz);
  keepPos();
  saveSettings();
}
function wear(id, temp) {
  if (!PACKS.some(p => p.id === id)) return false;
  S.skin = id; if (!temp) saveSettings();
  if (id !== lastSkin) reloadPet();
  return true;
}
function pick(type, value, temp) {
  log('메뉴: ' + type + ' ' + (value ?? '') + (temp ? ' (잠깐, 저장 안 함)' : ''));
  if (type === 'skin') wear(value, temp);
  else if (type === 'size') applySize(value);
  else if (type === 'size-step') applySizePct(sizePctNow() + (value === 'up' ? 5 : -5));     // 메뉴의 '조금 작게/조금 크게'
  else if (type === 'music') { if (MUSIC_LEVELS.includes(value)) { S.musicVolume = value; saveSettings(); petSend('music-volume', value); } }
  else if (type === 'ontop') {
    S.onTop = !!value;
    if (pet && !pet.isDestroyed()) pet.setAlwaysOnTop(S.onTop, 'floating');
    saveSettings();
  } else if (type === 'dance') { hideMenu(); if (hasOutfit()) petSend('motion', { name: 'dance' }); }   // 메뉴 '춤 추기' — 입은 옷의 기본 춤 가운데 하나
  else if (type === 'speak-test') { hideMenu(); speak(TEST_LINE, 0, '기쁨', false).catch(e => log('말하기 시험 실패 ' + e.message)); }
  else if (type === 'wardrobe') { hideMenu(); openWardrobe(value === 'get' ? 'get' : 'mine'); }
  else if (type === 'pack-file') { hideMenu(); addPackByDialog(); }
  else if (type === 'home') { const sz = petSize(), p = defaultPos(sz); setPetBounds(p.x, p.y, sz); keepPos(); saveSettings(); }
  else if (type === 'close') hideMenu();
  else if (type === 'quit') { hideMenu(); app.quit(); return; }
  menuSend('state', state());
  updateTray();
}

// ---------------------------------------------------------------- 커서 따라보기·클릭 통과·끌기
let lastCur = { x: NaN, y: NaN, px: NaN, py: NaN };
function cursorTick() {
  if (!pet || pet.isDestroyed()) return;
  const c = env.cursor();
  if (c.x === lastCur.x && c.y === lastCur.y && pos.x === lastCur.px && pos.y === lastCur.py) return;
  lastCur = { x: c.x, y: c.y, px: pos.x, py: pos.y };
  const sz = petSize(), x = c.x - pos.x, y = c.y - pos.y;
  petSend('cursor', { x, y, inside: x >= 0 && y >= 0 && x < sz.w && y < sz.h && !menuCovers(c) });
}
function menuCovers(c) {
  return menuState.visible && c.x >= menuState.x && c.x < menuState.x + menuState.w && c.y >= menuState.y && c.y < menuState.y + menuState.h;
}
function setOver(over) {
  if (drag && !over) return;            // 끄는 중에는 계속 잡고 있음
  const ign = !over;
  if (ign === ignoring) return;
  ignoring = ign;
  if (pet && !pet.isDestroyed()) pet.setIgnoreMouseEvents(ign, { forward: true });
}
let drag = null;
function dragStart() {
  if (drag || !pet) return;
  const c = env.cursor();
  drag = { cx: c.x, cy: c.y, wx: pos.x, wy: pos.y, moved: 0, timer: setInterval(dragTick, 16) };
}
function dragTick() {
  if (!drag) return;
  const c = env.cursor(), sz = petSize();
  const p = clampPos(drag.wx + c.x - drag.cx, drag.wy + c.y - drag.cy, sz);
  drag.moved = Math.max(drag.moved, Math.hypot(c.x - drag.cx, c.y - drag.cy));
  if (p.x !== pos.x || p.y !== pos.y) { const dx = p.x - pos.x, dy = p.y - pos.y; setPetBounds(p.x, p.y, sz); petSend('moved', { dx, dy }); }
}
function dragEnd() {
  if (!drag) return 0;
  dragTick();
  clearInterval(drag.timer);
  const moved = drag.moved;
  drag = null;
  if (moved >= 5) { keepPos(); saveSettings(); }
  return moved;
}

// ---------------------------------------------------------------- 말하기 줄(메뉴 '말하기 시험'·/speak)
const tts = new Tts(path.join(app.getPath('temp'), 'KimBiseoPet_tts_' + process.pid), path.join(__dirname, 'tts.ps1'), log);
// 목소리 목록·옷→목소리 대응표: 펫 폴더 옆의 voice/voices.json(저장소·설치 폴더 모두 pet 과 voice 가 나란히 있음), config.json voices_file 로 바꿀 수 있음
const VOICES_FILE = CONFIG.voices_file ? path.resolve(__dirname, String(CONFIG.voices_file)) : path.join(__dirname, '..', 'voice', 'voices.json');
const voice = new VoiceServer(CONFIG.voice_url, log, VOICES_FILE);
// 지금 입은 옷(꾸러미) → 목소리 이름(남자 옷 = kimbiseo_m 등) 또는 null(서버 기본 목소리)
const wornPack = () => (hasOutfit() ? packOf(S.skin) : null);
const wornVoice = () => voice.voiceFor(wornPack());
const speakQueue = [];
let current = null, speakSeq = 0, httpPort = null;
const doneWait = new Map();
function speak(text, rate, expr, wait) {
  if (speakQueue.length >= 5) return Promise.reject(Object.assign(new Error('말하기 대기 줄이 꽉 참(5개)'), { code: 429 }));
  const item = { id: ++speakSeq, text, rate, expr };
  item.done = new Promise(r => { item.finish = r; });
  speakQueue.push(item);
  log('말하기 받음 #' + item.id + ' (' + [...text].length + '자)');
  setImmediate(pump);
  if (wait) return item.done.then(r => ({ id: item.id, ...r }));
  return Promise.resolve({ id: item.id, queued: speakQueue.length + (current ? 1 : 0) });
}
async function pump() {
  if (current || !speakQueue.length) return;
  current = speakQueue.shift();
  const it = current;
  try {
    const t0 = Date.now();
    let r;
    try { r = await voice.synth(it.text, it.rate, it.expr, wornVoice()); }
    catch (e) {
      if (e.code === 400) throw e;
      log('김비서 목소리 안 됨 → 윈도우 음성: ' + e.message);
      r = await tts.synth(it.text, it.rate);
    }
    if (r.yawn && !it.expr) it.expr = '졸림';
    log('음성 만듦 #' + it.id + ' ' + r.data.dur + '초, ' + (Date.now() - t0) + 'ms');
    const fin = new Promise(res => doneWait.set(it.id, res));
    petSend('speak', { id: it.id, text: it.text, wav: r.wav, data: r.data, expr: it.expr });
    const how = await Promise.race([fin, new Promise(res => setTimeout(() => res('시간 넘김'), (r.data.dur + 8) * 1000))]);
    doneWait.delete(it.id);
    it.finish({ dur: r.data.dur, spoken: how !== '시간 넘김' });
  } catch (e) {
    log('말하기 실패 #' + it.id + ' ' + e.message);
    it.finish({ error: e.message });
  } finally {
    current = null;
    setImmediate(pump);
  }
}

// ---------------------------------------------------------------- 알림 영역(트레이)
function updateTray() {
  if (!tray) return;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: T('메뉴 열기'), click: () => openMenu(null, false) },
    { type: 'separator' },
    { label: T('옷 고르기'), enabled: PACKS.length > 0, submenu: PACKS.length ? PACKS.map(p => ({ label: p.name, type: 'radio', checked: S.skin === p.id, click: () => pick('skin', p.id) })) : [{ label: T('(옷 없음)'), enabled: false }] },
    { label: T('옷 관리·옷 더 받기'), click: () => openWardrobe('mine') },
    { label: T('파일로 옷 추가'), click: () => addPackByDialog() },
    { label: T('크기'), submenu: Object.keys(SIZES).map(k => ({ label: T(k), type: 'radio', checked: S.size === k, click: () => pick('size', k) })) },
    ...(DANCE_MUSIC ? [{ label: T('춤 노래 크기'), submenu: MUSIC_LEVELS.map(k => ({ label: T(k), type: 'radio', checked: S.musicVolume === k, click: () => pick('music', k) })) }] : []),
    { label: T('항상 위에 두기'), type: 'checkbox', checked: S.onTop, click: mi => pick('ontop', mi.checked) },
    { label: T('말하기 시험'), click: () => pick('speak-test') },
    { label: T('펫을 화면 오른쪽 아래로'), click: () => pick('home') },
    { type: 'separator' },
    { label: T('끝내기'), click: () => app.quit() },
  ]));
}

// ---------------------------------------------------------------- IPC(펫·메뉴 화면)
const fromPet = e => pet && e.sender === pet.webContents;
ipcMain.on('hit', (e, over) => { if (fromPet(e)) setOver(!!over); });
ipcMain.on('drag-start', e => { if (fromPet(e)) dragStart(); });
ipcMain.handle('drag-end', e => (fromPet(e) ? dragEnd() : 0));
ipcMain.on('context-menu', e => { if (fromPet(e)) openMenu(); });
ipcMain.on('speak-started', () => {});
ipcMain.on('speak-done', (e, id) => { const f = doneWait.get(id); if (f) f('끝'); });
ipcMain.on('pet-log', (e, msg) => log('펫: ' + String(msg).slice(0, 500)));
ipcMain.on('draw-state', (e, d) => { if (fromPet(e) && d) GPU.drawNow = d.mode === 'canvas' ? 'canvas' : 'video'; });
ipcMain.on('none-click', e => { if (fromPet(e)) openWardrobe('get'); });   // 옷이 없을 때 펫 자리 안내를 누름
// 걷기 범위: 캐릭터 몸(창 가운데 약 30%)이 화면 안에 다 보이는 곳까지만. roomL/roomR = 그 끝까지 남은 거리
function walkBounds(sz) {
  const best = nearestArea(pos.x + sz.w / 2, pos.y + sz.h / 2);
  return { min: Math.round(best.x - sz.w * 0.35), max: Math.round(best.x + best.width - sz.w * 0.65) };
}
let moveSaveTimer = null;
ipcMain.handle('move-by', (e, d) => {
  if (!fromPet(e) || drag || !d) return { dx: 0, dy: 0, skip: true };
  const dx = Math.max(-40, Math.min(40, +d.dx || 0)), dy = Math.max(-40, Math.min(40, +d.dy || 0));
  const sz = petSize(), wb = walkBounds(sz);
  if (!dx && !dy) return { dx: 0, dy: 0, roomL: pos.x - wb.min, roomR: wb.max - pos.x };
  let nx = pos.x + dx;
  if (dx < 0) nx = Math.max(nx, Math.min(wb.min, pos.x)); else if (dx > 0) nx = Math.min(nx, Math.max(wb.max, pos.x));
  const p = clampPos(Math.round(nx), Math.round(pos.y + dy), sz);
  const mx = p.x - pos.x, my = p.y - pos.y;
  if (mx || my) { setPetBounds(p.x, p.y, sz); keepPos(); clearTimeout(moveSaveTimer); moveSaveTimer = setTimeout(saveSettings, 2000); }
  return { dx: mx, dy: my, roomL: pos.x - wb.min, roomR: wb.max - pos.x };
});
// 화면(모니터)을 꽂거나 빼거나 배율·배치를 바꿨을 때: 윈도우가 창을 옮기거나 크기를 바꿔 놓았을 수 있다.
//   ① 진짜 창 자리를 다시 읽어 pos 를 맞춤(안 맞으면 누르는 자리·말풍선이 어긋남) ② 기억한 화면이 다시 생겼으면 기억한 자리로, 화면 밖이면 보이는 곳으로
//   ③ 크기를 다시 정함(그 화면보다 크지 않게). 이때 옮긴 자리는 기억에 덮어쓰지 않는다 — 뺐던 모니터를 다시 꽂으면 원래 자리로 돌아가게.
let dispTimer = null, displaced = false;
function onDisplaysChanged(why) {
  if (!pet || pet.isDestroyed() || drag) return;
  const b = pet.getBounds();
  pos.x = b.x; pos.y = b.y;
  const sz = petSize(), areas = env.allAreas();
  const at = G.restore({ x: S.x, y: S.y, disp: S.disp }, sz, areas);
  const back = displaced && /그대로/.test(at.why);                       // 기억한 화면이 돌아옴
  let p = { x: pos.x, y: pos.y };
  if (back || !G.visibleEnough(pos.x, pos.y, sz, areas)) { p = { x: at.x, y: at.y }; displaced = !/그대로/.test(at.why); }
  else p = G.clampPos(pos.x, pos.y, sz, areas);
  log(`화면 바뀜(${why}): 창 (${b.x},${b.y} ${b.width}x${b.height}) → (${p.x},${p.y} ${sz.w}x${sz.h}) · ${at.why} · 화면 ${areas.length}개`);
  setPetBounds(p.x, p.y, sz);
  petSend('moved', { dx: p.x - b.x, dy: p.y - b.y });
}
// 3초마다 펫 창이 화면 안에 충분히 보이는지 보고, 아니면 보이는 곳으로 되돌림(끄는 중엔 안 함)
function ensureVisible() {
  if (!pet || pet.isDestroyed() || drag) return;
  const b = pet.getBounds(), cx = b.x + b.width / 2;
  if (b.x !== pos.x || b.y !== pos.y) { log(`창 자리가 기억과 다름 (${pos.x},${pos.y}) → 진짜 자리 (${b.x},${b.y}) 로 맞춤`); pos.x = b.x; pos.y = b.y; }
  const ok = env.allAreas().some(a => cx >= a.x && cx < a.x + a.width && (Math.min(b.y + b.height, a.y + a.height) - Math.max(b.y, a.y)) >= b.height * 0.85);
  if (ok) return;
  const best = nearestArea(cx, b.y + b.height / 2);
  const x = Math.round(Math.min(Math.max(b.x, best.x - b.width * 0.3), best.x + best.width - b.width * 0.7));
  const y = Math.round(Math.min(Math.max(b.y, best.y), best.y + best.height - b.height));
  log(`창이 화면 밖(${b.x},${b.y} ${b.width}x${b.height}) → 보이는 곳(${x},${y})으로`);
  setPetBounds(x, y, { w: b.width, h: b.height });
  keepPos(); saveSettings();
}

// ---------------------------------------------------------------- 춤 노래
// 고르는 순서: ①사용자 '춤노래' 폴더(<프로필>\춤노래\)에서 이름이 그 춤으로 시작하는 파일 ②지금 입은 옷 꾸러미에 그 춤 노래가 있으면 그것
//   ③기본 춤(dance1~3)만: 춤노래 폴더의 다른 노래(아무 춤 이름으로도 시작하지 않는 것) 무작위, 없으면 프로그램에 든 합성 배경음(renderer\real\music\dance1~3.mp3)
//   ④그 밖에는 노래 없이 춤만. → 노래를 뺀 꾸러미를 입으면 그 춤들은 조용함.
// 공개판(config.json dance_music:false) = 춤은 추되 소리 없이: 노래를 고르지 않고, 춤노래 폴더·'춤 노래 크기' 칸도 만들지 않음
const DANCE_MUSIC = CONFIG.dance_music !== false;
const MUSIC_DIR = path.join(USER, '춤노래');
const MUSIC_EXT = /\.(mp3|m4a|wav|ogg)$/i;
function ensureMusicDir() {
  if (!DANCE_MUSIC) return;
  try {
    fs.mkdirSync(MUSIC_DIR, { recursive: true });
    const how = path.join(MUSIC_DIR, '넣는 법.txt');
    if (!fs.existsSync(how)) {
      fs.writeFileSync(how, '이 폴더에 춤출 때 틀 노래 파일(mp3·m4a·wav·ogg)을 넣으세요.\r\n' +
        '- 파일 이름을 춤 이름으로 시작하면 그 춤에만 씁니다(예: dance1_신나는노래.mp3, dance_bad_내노래.mp3).\r\n' +
        '- 춤 이름으로 시작하지 않는 파일은 기본 춤(dance1~3)을 출 때 무작위로 틉니다.\r\n' +
        '- 넣은 노래의 권리는 넣은 사람에게 있습니다. 펫은 이 PC 안에서만 재생합니다.\r\n' +
        '- 넣고 나서 펫을 다시 켤 필요 없습니다(춤출 때마다 폴더를 새로 봅니다).\r\n', 'utf8');
    }
  } catch (e) { log('춤노래 폴더 못 만듦: ' + e.message); }
}
const fileUrl = packs.fileUrl;
const norm = s => String(s || '').toLowerCase().replace(/[^0-9a-z가-힣]/g, '');
let lastMusic = null;   // { url, path } — 화면이 노래 크기를 잴 수 있게 방금 고른 그 파일의 내용만 내줌
function danceMusic(dance) {
  if (!DANCE_MUSIC) return null;
  let files = [];
  try { files = fs.readdirSync(MUSIC_DIR).filter(f => MUSIC_EXT.test(f)); } catch (err) { /* 없음 */ }
  const ex = (REAL_EXTRA[S.skin] || { dances: [] }).dances;
  const exMe = ex.find(x => x.name === dance);
  const allDances = MOTION_NAMES.DANCES.map(d => d.name).concat(ex.map(x => x.name));
  const prefOf = n => {
    const x = ex.find(k => k.name === n);
    return [n, n.replace(/^dance_?/, '')].concat(x ? [x.music, x.ko, String(x.ko || '').replace(/\s*춤$/, '')] : []).map(norm).filter(v => v.length >= 2);
  };
  const mine = prefOf(dance);
  const own = files.filter(f => mine.some(p => norm(f).startsWith(p)));
  if (own.length) return { why: '춤노래 폴더', path: path.join(MUSIC_DIR, own[Math.floor(Math.random() * own.length)]) };
  const pk = packOf(S.skin);
  const pm = pk && (pk.music || []).find(m => m.dance === dance && MUSIC_EXT.test(m.path));
  if (pm) return { why: '옷 꾸러미', path: pm.path };
  if (exMe || !/^dance\d$/.test(dance)) return null;
  const all = allDances.reduce((a, n) => a.concat(prefOf(n)), []);
  const free = files.filter(f => !all.some(p => norm(f).startsWith(p)));
  if (free.length) return { why: '춤노래 폴더(아무 춤)', path: path.join(MUSIC_DIR, free[Math.floor(Math.random() * free.length)]) };
  const b = path.join(__dirname, 'renderer', 'real', 'music', dance + '.mp3');
  return fs.existsSync(b) ? { why: '기본 배경음', path: b } : null;
}
ipcMain.handle('dance-music', (e, d) => {
  if (!fromPet(e)) return null;
  const dance = d && typeof d.dance === 'string' ? d.dance.replace(/[^a-z0-9_]/gi, '').slice(0, 40) : '';
  const m = dance ? danceMusic(dance) : null;
  log('춤 노래(' + dance + '): ' + (m ? m.why + ' ' + path.basename(m.path) : (DANCE_MUSIC ? '없음 → 노래 없이' : '이 판은 춤 노래 끔 → 소리 없이')));
  lastMusic = m ? { url: fileUrl(m.path), path: m.path } : null;
  return lastMusic ? lastMusic.url : null;
});
ipcMain.handle('dance-music-bytes', (e, d) => {
  if (!fromPet(e) || !lastMusic || !d || d.url !== lastMusic.url) return null;
  try { if (fs.statSync(lastMusic.path).size > 40 * 1024 * 1024) return null; return fs.readFileSync(lastMusic.path); } catch (err) { return null; }
});
ipcMain.handle('menu-state', () => state());
ipcMain.on('menu-pick', (e, d) => { if (menu && e.sender === menu.webContents && d && typeof d.type === 'string') pick(d.type, d.value); });
ipcMain.on('menu-height', (e, h) => {
  if (!menu || e.sender !== menu.webContents) return;
  const nh = Math.max(200, Math.min(900, Math.round(+h || 0)));
  if (nh === menuState.h) return;
  menuState.h = nh;
  // 화면(작업 표시줄 제외)보다 길면 창은 화면 높이까지만, 나머지는 메뉴 안에서 스크롤
  const wa = env.workAreaAt({ x: menuState.x, y: menuState.y });
  const vh = Math.min(nh, wa.height - 8);
  if (menuState.visible) menuState.y = Math.max(wa.y + 4, Math.min(menuState.y, wa.y + wa.height - vh - 4));
  menu.setBounds({ x: menuState.x, y: menuState.y, width: menuState.w, height: vh });
});

// ---------------------------------------------------------------- 옷 관리·옷 더 받기 창, 파일로 추가·끌어 놓기·두 번 누르기
let wardrobe = null, wardTab = 'mine';
const wardSend = (ch, d) => { if (wardrobe && !wardrobe.isDestroyed()) wardrobe.webContents.send(ch, d); };
const fromWard = e => wardrobe && e.sender === wardrobe.webContents;
function openWardrobe(tab) {
  wardTab = tab || wardTab;
  if (wardrobe && !wardrobe.isDestroyed()) { wardSend('ward-tab', wardTab); if (VS) wardrobe.showInactive(); else { wardrobe.show(); wardrobe.focus(); } return wardrobe; }
  const wa = env.workAreaAt(env.cursor()), w = 470, h = Math.min(680, wa.height - 16);
  wardrobe = new BrowserWindow({
    x: Math.round(wa.x + (wa.width - w) / 2), y: Math.round(wa.y + (wa.height - h) / 2), width: w, height: h, show: false, frame: false,
    transparent: true, backgroundColor: '#00000000', resizable: false, maximizable: false, minimizable: false, fullscreenable: false,
    skipTaskbar: false, alwaysOnTop: true, hasShadow: false, title: '김비서 펫 옷 관리', icon: ICON, webPreferences: WEB,
  });
  wardrobe.setMenu(null);
  wardrobe.loadFile(path.join(__dirname, 'renderer', 'packs.html'), { query: { tab: wardTab } });
  wardrobe.once('ready-to-show', () => { if (VS) wardrobe.showInactive(); else { wardrobe.show(); wardrobe.focus(); } });
  guardContents(wardrobe.webContents, '옷 창');
  wardrobe.on('closed', () => { wardrobe = null; });
  return wardrobe;
}
function packsState() {
  return { version: VERSION, source: PACK_SOURCE, worn: hasOutfit() ? S.skin : null,
    packs: PACKS.map(p => ({ id: p.id, name: p.name, version: p.version, body: p.body, gender: p.gender, signed: p.signed, img: p.img,
      clips: Object.keys(p.clips).length, music: songsOf(p) })) };
}
function packsChanged() { wardSend('packs-changed', packsState()); menuSend('state', state()); updateTray(); }
function notify(text, sec = 5) { petSend('bubble', { text, sec }); wardSend('ward-msg', text); log('옷: ' + text); }

// 새 옷이 들어온 뒤: 목록 다시 읽기 → (wear 면) 그 옷 입기. 같은 옷을 다시 넣었고 지금 입고 있으면 화면을 다시 불러옴(파일이 바뀜)
function afterInstall(r, wearIt) {
  const before = lastSkin;
  refreshPacks();
  if (wearIt || !before) { S.skin = r.id; saveSettings(); lastSkin = null; reloadPet(); }
  else if (S.skin === r.id && r.replaced) { lastSkin = null; reloadPet(); }
  packsChanged();
}
const asks = new Map();   // 서명 없는 꾸러미: 옷 창에서 '그래도 넣기' 기다림
let askSeq = 0;
let installing = Promise.resolve();
/** 꾸러미 파일 넣기(파일 고르기·끌어 놓기·두 번 누르기·옷 받기 공통). how = 기록용 */
function requestInstall(file, how, opts = {}) {
  const job = installing.then(async () => {
    log('옷 넣기(' + how + '): ' + file);
    try {
      const r = packs.install(USER, file, { allowUnsigned: !!opts.allowUnsigned, requireSigned: !!opts.requireSigned, sha256: opts.sha256 });
      notify(`'${r.name}' 옷을 넣었어요` + (r.signed ? '' : ' (정품 서명 없음)'));
      afterInstall(r, opts.wear !== false);
      return r;
    } catch (e) {
      if (e.code === 'unsigned' && !opts.noAsk) {
        const token = String(++askSeq);
        asks.set(token, { file, how, opts });
        const w = openWardrobe();
        const send = () => wardSend('ward-ask', { token, name: e.pack.name, id: e.pack.id, file: path.basename(file) });
        if (w.webContents.isLoading()) w.webContents.once('did-finish-load', send); else send();
        log('서명 없는 꾸러미 → 옷 창에서 물어봄 ' + path.basename(file));
        return { ok: false, asked: true, token };
      }
      notify('옷을 넣지 못했어요: ' + e.message, 7);
      return { ok: false, error: e.message, code: e.code || 'bad' };
    }
  });
  installing = job.catch(() => {});
  return job;
}
const RECV_DIR = path.join(USER, '옷', '_받은파일');
ipcMain.handle('ward-answer', (e, d) => {
  if (!fromWard(e) || !d) return null;
  const a = asks.get(String(d.token)); asks.delete(String(d.token));
  if (!a) return null;
  const tidy = () => { const c = a.opts && a.opts.cleanup; if (c && path.dirname(path.resolve(c)) === RECV_DIR) try { fs.rmSync(c, { force: true }); } catch (err) { /* 무시 */ } };
  if (!d.yes) { log('서명 없는 꾸러미 안 넣음 ' + path.basename(a.file)); wardSend('ward-msg', '넣지 않았어요'); tidy(); return { ok: false, cancelled: true }; }
  return requestInstall(a.file, a.how + '·경고 후', { ...a.opts, allowUnsigned: true, noAsk: true }).finally(tidy);
});
async function addPackByDialog() {
  const { dialog } = require('electron');
  const win = wardrobe && !wardrobe.isDestroyed() ? wardrobe : null;
  const r = await dialog.showOpenDialog(win, { title: '옷 꾸러미 파일 고르기', properties: ['openFile', 'multiSelections'],
    filters: [{ name: '옷 꾸러미(.hipcpet)', extensions: ['hipcpet'] }] });
  if (r.canceled) return [];
  const out = [];
  for (const f of r.filePaths) out.push(await requestInstall(f, '파일로 옷 추가'));
  return out;
}
// 지우기: 마지막 한 벌은 안 지움 · 입고 있던 옷이면 남은 옷으로 먼저 갈아입고(화면이 그 영상 파일을 놓도록) 지움
let deleting = false;
async function deletePack(id) {
  if (deleting) return { ok: false, error: '지우는 중이에요' };
  if (!PACKS.some(p => p.id === id)) return { ok: false, error: '그 옷이 없어요' };
  if (PACKS.length <= 1) return { ok: false, error: '마지막 한 벌은 지울 수 없어요', last: true };
  deleting = true;
  try {
    const rest = PACKS.filter(p => p.id !== id);
    const next = rest.find(p => p.id === CONFIG.default_pack) || rest[0];
    let switched = null;
    if (S.skin === id) { S.skin = next.id; saveSettings(); await reloadPet(); switched = next.id; await new Promise(r => setTimeout(r, 600)); }
    let err = null;
    for (let k = 0; k < 6; k++) {   // 영상 파일을 아직 잡고 있으면 조금 뒤 다시
      try { packs.remove(USER, id); err = null; break; } catch (e) { err = e; await new Promise(r => setTimeout(r, 800)); }
    }
    if (err) { log('옷 지우기 실패 ' + id + ' ' + err.message); return { ok: false, error: '지우지 못했어요: ' + err.message }; }
    refreshPacks();
    log('옷 지움 ' + id + (switched ? ' → ' + switched + ' 로 갈아입음' : ''));
    packsChanged();
    return { ok: true, id, switched };
  } finally { deleting = false; }
}

// ---------------------------------------------------------------- 옷 더 받기: 옷 목록(outfits.json · 옛 packs.json) → 고른 옷만 받기
// 목록 모양: { "format": "kimbiseo-outfits/1", "outfits": [ { id, name, version, body, gender, description, size, sha256, signed, url, preview, default, songs, soon } ] }
//   옛 모양 { "format": "kimbiseo-packs/1", "packs": [ … note … ] } 도 그대로 읽음(옛 판 설정·예비 주소).
//   url·preview 는 목록 주소 기준 상대 주소도 됨. soon = 준비 중(받기 단추 없이 보여만 줌). 미리보기는 펫이 받아 data: 로(창은 바깥 주소를 직접 안 부름)
const str = (v, n) => String(v == null ? '' : v).slice(0, n);
function catalogItems(r) {   // 두 모양 다 → 항목 배열(모르는 모양 = null)
  if (r && r.format === 'kimbiseo-outfits/1' && Array.isArray(r.outfits)) return r.outfits;
  if (r && r.format === 'kimbiseo-packs/1' && Array.isArray(r.packs)) return r.packs;
  return null;
}
async function remoteList() {
  if (!PACK_SOURCE) throw new packs.PackError('옷 목록 주소가 아직 정해지지 않았어요. 「파일로 옷 추가」로 넣어 주세요.', 'nosource');
  let base = null, r = null, lastErr = null;
  for (const src of [PACK_SOURCE, PACK_BACKUP].filter((x, i, a) => x && a.indexOf(x) === i)) {
    try {
      base = packs.checkUrl(src, ALLOWED);
      r = catalogItems(await packs.getJson(base, ALLOWED));
      if (r) break;
      lastErr = new packs.PackError('옷 목록 모양이 달라요', 'net');
    } catch (e) { r = null; lastErr = e; log('옷 목록 못 받음(' + String(src).slice(0, 80) + '): ' + (e && e.message)); }
  }
  if (!r) throw lastErr || new packs.PackError('옷 목록을 받지 못했어요', 'net');
  const out = [];
  for (const p of r.slice(0, 50)) {
    if (!p || !packs.ID_RE.test(String(p.id))) continue;
    const soon = p.soon === true;
    let url = null, prev = null;
    try { if (!soon) url = packs.checkUrl(new URL(String(p.url), base), ALLOWED).href; } catch (e) { continue; }
    try { if (p.preview) prev = packs.checkUrl(new URL(String(p.preview), base), ALLOWED); } catch (e) { prev = null; }
    const sha = typeof p.sha256 === 'string' && /^[0-9a-f]{64}$/.test(p.sha256) ? p.sha256 : null;
    if (!soon && !sha) continue;   // sha256 없는 항목은 받지 않음
    let img = null;
    if (prev) {
      try {
        const b = await packs.getBytes(prev, ALLOWED);
        const t = b.t.split(';')[0].trim();
        if (/^image\/(png|webp|jpeg)$/.test(t)) img = 'data:' + t + ';base64,' + b.b.toString('base64');
      } catch (e) { /* 미리보기 없이 */ }
    }
    const mine = packOf(String(p.id));
    out.push({ key: String(p.id) + '@' + str(p.version, 40), id: String(p.id), name: str(p.name || p.id, 60), version: str(p.version, 40), size: +p.size || 0,
      sha256: sha, url, signed: p.signed === true, body: str(p.body, 30), gender: str(p.gender, 10), def: p.default === true, songs: p.songs === true, soon,
      note: str(p.description || p.note, 160), img, installed: !!mine, sameVersion: !!mine && mine.version === str(p.version, 40) });
  }
  return out;
}
let fetching = null;
async function fetchPack(p, how = '옷 받기', wearIt = true) {
  if (p.soon || !p.url) return { ok: false, error: '아직 준비 중인 옷이에요' };
  if (fetching) return { ok: false, error: '다른 옷을 받는 중이에요' };
  fetching = p.id;
  fs.mkdirSync(RECV_DIR, { recursive: true });
  // 받는 파일 이름은 옷·판마다 같게 — 받다가 끊겨도 다음에(1분 뒤 저절로 · 다시 눌렀을 때 · 펫을 다시 켰을 때) 받은 만큼 이어서 받음
  const dest = path.join(RECV_DIR, p.id + '_' + String(p.version || '0').replace(/[^0-9A-Za-z._-]/g, '_').slice(0, 40) + '.hipcpet');
  let keep = false, keepPart = false;
  try {
    let lastPct = -1;
    const d = await packs.download(p.url, ALLOWED, dest, (got, total) => {
      const pct = total ? Math.floor(100 * got / total) : 0;
      wardSend('ward-progress', { id: p.id, key: p.key, got, total, pct });
      if (pct >= lastPct + 10 || pct === 100) { lastPct = pct; petSend('bubble', { text: `옷 '${p.name}' 받는 중 ${pct}%`, sec: 4 }); }
    }, p.sha256, { onRetry: (n, e, got) => log(`옷 받기 ${n}번째 끊김(${e && e.message}) — 받은 것 ${(got / 1e6).toFixed(1)}MB, 이어서 받음`) });
    log(`옷 받음 ${p.id} ${p.version} ${(d.size / 1e6).toFixed(1)}MB` + (d.attempts > 1 ? ` (${d.attempts}번에 나눠 받음)` : ''));
    // 목록과 꾸러미가 같은 옷인지(id) 먼저 확인
    let info = null;
    try { info = packs.inspect(dest); } catch (e) { throw e; } finally { if (info) fs.closeSync(info.z.fd); }
    if (info.pack.id !== p.id) throw new packs.PackError('받은 꾸러미가 목록의 옷과 달라요(id)');
    const r = await requestInstall(dest, how, { sha256: d.sha256, wear: wearIt, cleanup: dest, requireSigned: p.signed });
    if (r && r.asked) keep = true;   // 서명 없는 꾸러미: 옷 창에서 답할 때까지 받은 파일을 둠
    return r;
  } catch (e) {
    keepPart = e.code === 'net' && !e.fatal;      // 연결 문제로 멈춤 → 받은 만큼은 남겨 다음에 이어 받음
    notify('옷을 받지 못했어요: ' + e.message + (keepPart ? ' — 받은 만큼은 남겨 두었어요. 「옷 더 받기」에서 다시 누르면 이어서 받아요(「파일로 옷 추가」로 직접 넣을 수도 있어요).' : ''), 9);
    return { ok: false, error: e.message, code: e.code || 'net' };
  } finally {
    fetching = null;
    try { if (!keep) fs.rmSync(dest, { force: true }); if (!keepPart) fs.rmSync(dest + '.받는중', { force: true }); } catch (e) { /* 무시 */ }
  }
}
// 첫 실행(옷이 하나도 없음) + 동의(autoPack)했을 때만: 목록의 기본 옷(default·정품)을 저절로 받음. 연결이 안 되면 1분마다 다시(조용히)
let autoTimer = null;
async function autoFirstPack() {
  clearTimeout(autoTimer);
  if (PACKS.length || !AUTO_PACK) return;
  try {
    const list = await remoteList();
    const want = wantedPack();   // 본체 설정에서 고른 펫 캐릭터(예: 남자 김비서)가 있으면 그 옷부터
    const p = (want && list.find(x => x.id === want && x.signed && !x.soon))
      || list.find(x => x.def && x.signed && !x.soon && x.id === CONFIG.default_pack) || list.find(x => x.def && x.signed && !x.soon);
    if (!p) { log('첫 옷 자동 받기: 목록에 기본 옷 없음'); return; }
    if (fetching || PACKS.length) return;   // 목록을 읽는 사이 다른 길(본체가 고른 옷 받기)이 먼저 받기 시작함
    log('첫 옷 자동 받기: ' + p.id + ' ' + p.version);
    const r = await fetchPack(p, '첫 실행 자동 받기', true);
    if (!r || !r.ok) autoTimer = setTimeout(autoFirstPack, 60000);
  } catch (e) {
    log('첫 옷 자동 받기 못 함(1분 뒤 다시): ' + e.message);
    if (e.code !== 'nosource') autoTimer = setTimeout(autoFirstPack, 60000);
  }
}
// 본체가 '이 옷을 입어'(/skin)라고 했는데 그 옷이 아직 없을 때: 옷 받기에 동의했으면 옷 목록에서 받아서 입음(정품 서명만)
function wantedPack() {   // 본체가 방금 고른 옷(/skin — 처음 화면에서 고른 것)이 켤 때 받은 값(--want-pack)보다 새것
  const w = String(S.wantPack || argVal('want-pack') || '').trim();
  return packs.ID_RE.test(w) ? w : '';
}
// 켤 때: 본체 설정의 펫 캐릭터(--want-pack)가 지난번과 달라졌으면 그 옷을 입음(없으면 옷 받기에 동의했을 때 받아서).
//   이 기능이 생긴 뒤 처음 켤 때(appliedWant 없음): 이미 있는 옷은 갈아입히지 않음(펫 메뉴에서 고른 옷을 그대로 둠).
//   다만 설정에서 기본 옷이 아닌 캐릭터(예: 남자 김비서 — 예전 판에서는 '준비 중'이었음)를 골라 두었는데 그 옷이 아직 없으면 받아서 입음.
function applyWantArg() {
  const w = String(argVal('want-pack') || '').trim();
  if (!packs.ID_RE.test(w) || S.appliedWant === w) return;
  const first = S.appliedWant === null || S.appliedWant === undefined;
  if (!PACKS.length) { S.appliedWant = w; saveSettings(); return; }   // 옷이 하나도 없으면 autoFirstPack 이 이 옷부터 받음
  if (PACKS.some(p => p.id === w)) {
    S.appliedWant = w; saveSettings();
    if (!first && S.skin !== w) { log('본체 설정의 펫 캐릭터로 갈아입음: ' + w); wear(w); }
    return;
  }
  if (AUTO_PACK && PACK_SOURCE && (!first || w !== CONFIG.default_pack)) { S.wantPack = w; saveSettings(); setTimeout(() => fetchWanted(w), 4000); }
  else if (first) { S.appliedWant = w; saveSettings(); }
}
async function fetchWanted(id) {
  try {
    const list = await remoteList();
    const p = list.find(x => x.id === id && x.signed && !x.soon);
    if (!p) {   // 옷 목록에 없거나 아직 준비 중 → 켤 때마다 다시 묻지 않게 적어 둠
      S.wantPack = ''; S.appliedWant = id; saveSettings();
      notify('그 옷은 아직 받을 수 없어요. 펫 메뉴 「옷 더 받기」를 봐 주세요.', 7); return;
    }
    if (PACKS.some(x => x.id === id)) { S.wantPack = ''; S.appliedWant = id; saveSettings(); if (S.skin !== id) wear(id); return; }   // 그 사이 이미 들어옴
    if (fetching) { if (fetching !== id) setTimeout(() => fetchWanted(id), 5000); return; }   // 다른 옷을 받는 중이면 끝난 뒤 다시, 같은 옷이면 그 받기에 맡김
    log('본체가 고른 옷 받기: ' + p.id + ' ' + p.version);
    const r = await fetchPack(p, '본체 설정', true);
    if (r && r.ok) { S.wantPack = ''; S.appliedWant = id; saveSettings(); }
  } catch (e) { log('본체가 고른 옷 받기 못 함: ' + e.message); notify('옷을 받지 못했어요: ' + e.message, 7); }
}
ipcMain.handle('ward-state', e => (fromWard(e) ? packsState() : null));
ipcMain.handle('ward-remote', async e => {
  if (!fromWard(e)) return null;
  try { return { ok: true, packs: await remoteList() }; } catch (err) { return { ok: false, error: err.message, code: err.code || '' }; }
});
ipcMain.handle('ward-get', async (e, d) => {
  if (!fromWard(e) || !d) return null;
  let list; try { list = await remoteList(); } catch (err) { return { ok: false, error: err.message }; }
  const p = list.find(x => x.key === String(d.key));
  return p ? fetchPack(p) : { ok: false, error: '옷 목록에 없는 옷이에요' };
});
ipcMain.handle('ward-delete', (e, d) => (fromWard(e) && d ? deletePack(String(d.id)) : null));
ipcMain.handle('ward-wear', (e, d) => {
  if (!fromWard(e) || !d) return null;
  const ok = wear(String(d.id));
  packsChanged();
  return { ok };
});
ipcMain.handle('ward-file', e => (fromWard(e) ? addPackByDialog() : null));
ipcMain.on('ward-close', e => { if (fromWard(e)) wardrobe.close(); });
// 끌어 놓기(펫·메뉴·옷 창 어디든): 화면이 놓인 파일 경로를 보냄 → .hipcpet 만
ipcMain.on('drop-files', (e, list) => {
  const okSender = [pet, menu, wardrobe].some(w => w && !w.isDestroyed() && e.sender === w.webContents);
  if (!okSender || !Array.isArray(list)) return;
  const files = list.filter(f => typeof f === 'string' && /\.hipcpet$/i.test(f)).slice(0, 10);
  if (!files.length) { if (list.length) notify('옷 꾸러미(.hipcpet) 파일만 넣을 수 있어요'); return; }
  for (const f of files) requestInstall(f, '끌어 놓기');
});
// 화면이 켤 때 한 번 받는 옷 목록(동기)
ipcMain.on('real-data', e => { e.returnValue = REAL_DATA ? { ...REAL_DATA, draw: drawMode(), musicVolume: S.musicVolume, lip: S.lip === 'off' || process.argv.includes('--lip=off') ? 'off' : 'gate' } : null; });

// ---------------------------------------------------------------- 펫 신호 입구(본체 → 펫)
function signalHandlers() {
  const clipsNow = () => REAL_CLIPS[S.skin] || new Set();
  const exNow = () => REAL_EXTRA[S.skin] || { motions: [], dances: [], variants: {} };
  return {
    speak, log, packs: () => packsState(),
    status: () => ({ app: '김비서 펫', ...state(), outfits: undefined, packs: PACKS.map(p => p.id + ' ' + p.version + (songsOf(p) ? '' : ' (노래 없음)')),
      source: PACK_SOURCE || null, gpu: gpuLine(), gender: (wornPack() || {}).gender || '', voiceWant: wornVoice() || '',
      voice: voice.down ? (tts.voice || '윈도우 음성') : (voice.voiceName || '김비서 목소리') }),
    expr: (name, sec, raw) => petSend('expr', { name, sec, raw }),
    dances: () => {   // 지금 입은 옷에서 출 수 있는 춤 [{name, ko}]
      const set = clipsNow();
      return MOTION_NAMES.DANCES.filter(d => set.has(d.name)).map(d => ({ name: d.name, ko: d.ko })).concat(exNow().dances.map(d => ({ name: d.name, ko: d.ko, extra: true })));
    },
    extras: () => {   // 지금 옷의 추가 동작·춤 + 앱 기본 동작 가운데 이 옷으로 되는 것(have) + 자세별 동작(variants)
      if (!hasOutfit()) return { skin: null, motions: [], dances: [], have: [], variants: {} };
      const set = clipsNow(), ex = exNow();
      const have = Object.keys(MOTION_NAMES.NEED).filter(k => !MOTION_NAMES.resolve(k, n => set.has(n), () => true).missing);
      const pk = packOf(S.skin);
      // gender·packVoice = 본체가 옷에 맞는 목소리를 고르는 데 씀(app/pet_link/face.py pet_outfit) · voice = 펫이 같은 표로 고른 이름
      return { skin: S.skin, version: pk ? pk.version : '', gender: pk ? pk.gender : '', packVoice: pk ? pk.voice : '', voice: wornVoice() || '',
        motions: ex.motions.map(m => ({ name: m.name, ko: m.ko, calls: m.calls, pose: m.pose })),
        dances: ex.dances.map(d => ({ name: d.name, ko: d.ko, calls: d.calls })), have, variants: ex.variants || {} };
    },
    motion: name => {
      petSend('motion', { name });
      if (!hasOutfit()) return { missing: true, noOutfit: true };
      const set = clipsNow();
      const r = MOTION_NAMES.resolve(name, n => set.has(n), n => n in MOTION_NAMES.NEED || ['idle', 'stand', 'talk', 'walk_left', 'walk_right', 'search_end'].includes(n));
      if (r.unknown) {   // 지금 옷의 추가 동작·춤(클립 이름·표시 이름·부르는 말)이면 그것, 아니면 모르는 동작
        const ex = exNow(), key = String(name).replace(/\s+/g, '').toLowerCase();
        const hit = ex.motions.concat(ex.dances).find(m => m.name === name || [m.ko].concat(m.calls).some(c => String(c).replace(/\s+/g, '').toLowerCase() === key));
        return hit ? { asked: hit.name, extra: true } : { unknown: true };
      }
      return r.missing ? { missing: true, asked: r.asked, fallback: r.fallback, skin: S.skin } : { asked: r.asked };
    },
    autoPack: () => {   // 본체 처음 화면에서 '옷 받기'에 동의함 → 이제부터 옷이 없으면 기본 옷을 저절로 받음(설정에 남김)
      if (process.argv.includes('--no-auto-pack')) return { ok: false, error: '--no-auto-pack 으로 켜져 있음' };
      AUTO_PACK = true;
      if (S.autoPack !== true) { S.autoPack = true; saveSettings(); log('옷 받기 동의(본체) → 첫 옷 자동 받기 켬'); }
      if (PACKS.length) return { ok: true, already: true, worn: hasOutfit() ? S.skin : null };
      if (!PACK_SOURCE) return { ok: false, error: '옷 목록 주소가 정해지지 않았어요', code: 'nosource' };
      if (!fetching) setTimeout(autoFirstPack, 100);
      return { ok: true, started: true, source: PACK_SOURCE };
    },
    size: pct => applySizePct(pct),
    skin: (id, temp) => {
      const list = PACKS.map(p => p.id);
      if (!list.includes(id)) {
        // 아직 없는 옷: 옷 받기에 동의했고 옷 목록 주소가 있으면 받아서 입음(본체 처음 화면·설정에서 남자 김비서를 골랐을 때)
        if (temp || !packs.ID_RE.test(id)) return { ok: false, error: '옷 id: ' + list.join(', ') };
        if (!AUTO_PACK || !PACK_SOURCE) return { ok: false, missing: true, error: '그 옷이 아직 없어요. 펫 메뉴 「옷 더 받기」에서 받아 주세요.' };
        if (S.wantPack !== id) { S.wantPack = id; saveSettings(); }
        if (!fetching) setTimeout(() => fetchWanted(id), 50);
        return { ok: true, id, fetching: true };
      }
      if (!temp && (S.wantPack || S.appliedWant !== id)) { S.wantPack = ''; S.appliedWant = id; saveSettings(); }
      pick('skin', id, temp); return { ok: true, id, saved: !temp };
    },
    mouth: (level, shape) => petSend('mouth', { level, shape }),
    talk: on => petSend('talk', { on }),
    bubble: (text, sec) => petSend('bubble', { text, sec }),
    emotionOf: n => MOTION_NAMES.emotionOf(n),
    emotion: name => {
      petSend('emotion', { name });
      if (!hasOutfit() || name === 'neutral') return {};
      const set = clipsNow();
      const poses = ['stand', 'sit', 'lie'].filter(p => set.has({ stand: '', sit: 'sit_', lie: 'lie_' }[p] + 'talk_' + name + '_hold'));
      return poses.length ? { poses } : { missing: true, poses, skin: S.skin };
    },
    emotions: () => {
      const set = hasOutfit() ? clipsNow() : new Set();
      return MOTION_NAMES.EMOTIONS.map(e => ({ name: e.name, ko: e.ko,
        poses: ['stand', 'sit', 'lie'].filter(p => set.has({ stand: '', sit: 'sit_', lie: 'lie_' }[p] + 'talk_' + e.name + '_hold')) }));
    },
  };
}

// ---------------------------------------------------------------- 시작
process.on('unhandledRejection', e => log('처리 안 된 오류: ' + (e && e.stack || e)));
let cursorTimer = null;
const ctx = {   // 시험 도구가 쓰는 안쪽 손잡이(시험용 화면 자리일 때만 열림)
  env, pos, S, menuState, petSize, setPetBounds, openMenu, hideMenu, openWardrobe, pick, speak, log, state, packsState,
  get pet() { return pet; }, get menu() { return menu; }, get wardrobe() { return wardrobe; }, get port() { return httpPort; },
};
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', (ev, argv) => {
    const adds = addPackArgs(argv || []);   // .hipcpet 두 번 누르기 = --add-pack=<파일> 로 또 실행됨 → 지금 펫이 그 옷을 넣음
    if (adds.length) { for (const f of adds) requestInstall(f, '두 번 누르기'); return; }
    const sz = petSize();   // 또 실행하면 새로 띄우지 않고 지금 펫이 손을 흔듦(화면 밖이면 오른쪽 아래로)
    if (!visibleEnough(pos.x, pos.y, sz)) { const p = defaultPos(sz); setPetBounds(p.x, p.y, sz); }
    petSend('react', 'hello');
  });
  app.whenReady().then(async () => {
    Menu.setApplicationMenu(null);
    log('시작 v' + VERSION + (VS ? ' (시험용 화면 자리 ' + [VS.x, VS.y, VS.width, VS.height].join(',') + ')' : '') + ' · 프로필 ' + USER);
    for (const ms of [2500, 8000, 30000]) setTimeout(() => gpuCheck('켠 뒤 ' + ms / 1000 + '초'), ms);
    if (VS) globalThis.__petTest = ctx;
    ensureMusicDir();
    createPet();
    createMenu();
    if (!VS) {
      tray = new Tray(nativeImage.createFromPath(ICON).resize({ width: 32, height: 32 }));
      tray.setToolTip('김비서 펫 — 오른쪽 클릭: 메뉴');
      tray.on('click', () => openMenu(null, false));
      updateTray();
      for (const ev of ['display-added', 'display-removed', 'display-metrics-changed']) screen.on(ev, () => { clearTimeout(dispTimer); dispTimer = setTimeout(() => onDisplaysChanged(ev), 400); });
    }
    cursorTimer = setInterval(cursorTick, 40);
    setTimeout(ensureVisible, 1500); setInterval(ensureVisible, 3000);
    log('옷 꾸러미 ' + PACKS.length + '벌(' + PACKS.map(p => p.id + ' ' + p.version).join(', ') + ') · 옷 목록 ' + (PACK_SOURCE || '(정해지지 않음)'));
    if (ASSOC) setTimeout(() => { try { packs.registerAssoc(process.execPath, PROFILE ? path.resolve(PROFILE) : null, log, app.isPackaged ? null : app.getAppPath()); } catch (e) { log('파일 연결 오류 ' + e.message); } }, 2000);
    try {   // 지난번 임시 파일 치움(<프로필>\옷\_받은파일\ 바로 아래): 다 받은 .hipcpet 은 지우고, 받다 만 .받는중 은 사흘 안 것이면 남겨 이어 받음
      for (const n of fs.existsSync(RECV_DIR) ? fs.readdirSync(RECV_DIR) : []) {
        const f = path.join(RECV_DIR, n);
        if (/\.hipcpet$/.test(n) || (/\.받는중$/.test(n) && Date.now() - fs.statSync(f).mtimeMs > 3 * 86400e3)) fs.rmSync(f, { force: true });
      }
    } catch (e) { /* 무시 */ }
    for (const f of addPackArgs(process.argv)) requestInstall(f, '두 번 누르기(켜면서)');
    if (!PACKS.length) setTimeout(autoFirstPack, 3000);
    applyWantArg();
    try {
      const r = await startServer(signalHandlers(), +CONFIG.port || 17961);
      httpPort = r.port;
      fs.writeFileSync(path.join(USER, 'speak_port.txt'), String(r.port), 'utf8');
      log('펫 신호 입구 127.0.0.1:' + r.port);
    } catch (e) { log('펫 신호 입구 못 엶: ' + e.message); }
  });
  app.on('before-quit', () => {
    quitting = true; clearInterval(cursorTimer); tts.stop(); voice.stop();
    if (!displaced) keepPos();          // 모니터를 빼서 임시로 옮겨 둔 자리는 기억에 덮어쓰지 않음
    try { fs.writeFileSync(SETTINGS, JSON.stringify(S, null, 1), 'utf8'); } catch (e) { /* 무시 */ }
  });
  app.on('window-all-closed', () => app.quit());
}
