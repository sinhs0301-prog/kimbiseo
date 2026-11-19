'use strict';
// 화면(펫·메뉴·옷 창) ↔ 본체 연결: 정해 둔 통로 이름만 열어 줌
const { contextBridge, ipcRenderer, webUtils } = require('electron');
const SEND = new Set(['hit', 'drag-start', 'context-menu', 'speak-started', 'speak-done', 'pet-log', 'menu-pick', 'menu-height', 'draw-state', 'ward-close', 'none-click', 'clip-play']);
const INVOKE = new Set(['drag-end', 'menu-state', 'move-by', 'dance-music', 'dance-music-bytes', 'ward-state', 'ward-remote', 'ward-get', 'ward-delete', 'ward-wear', 'ward-file', 'ward-answer']);
const ON = new Set(['cursor', 'moved', 'skin', 'speak', 'expr', 'react', 'menu-open', 'state', 'mouth', 'bubble', 'motion', 'emotion', 'draw', 'talk', 'music-volume', 'idle-sit', 'play-stats',
  'packs-changed', 'ward-progress', 'ward-ask', 'ward-msg', 'ward-tab']);
// 옷 꾸러미(.hipcpet) 끌어 놓기 — 펫·메뉴·옷 창 어디든 파일을 놓으면 본체가 받음(경로만 보냄, 본체가 .hipcpet 인지·안전한지 검사)
window.addEventListener('dragover', e => { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'; });
window.addEventListener('drop', e => {
  e.preventDefault();
  const files = [...((e.dataTransfer && e.dataTransfer.files) || [])].map(f => { try { return webUtils.getPathForFile(f); } catch (err) { return ''; } }).filter(Boolean);
  if (files.length) ipcRenderer.send('drop-files', files);
});
contextBridge.exposeInMainWorld('petApi', {
  send(ch, d) { if (SEND.has(ch)) ipcRenderer.send(ch, d); },
  invoke(ch, d) { return INVOKE.has(ch) ? ipcRenderer.invoke(ch, d) : Promise.reject(new Error('막힌 통로 ' + ch)); },
  on(ch, fn) { if (ON.has(ch)) ipcRenderer.on(ch, (e, d) => fn(d)); },
  realData() { return ipcRenderer.sendSync('real-data'); },   // 설치된 옷 목록·클립
});
