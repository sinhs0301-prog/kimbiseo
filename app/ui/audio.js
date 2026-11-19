// 소리 엔진 — 마이크를 열 때 메아리 지우기(echoCancellation)·잡음 줄이기(noiseSuppression)·소리 크기 자동(autoGainControl)을
//   반드시 켜 달라고 하고, 실제로 켜졌는지 track.getSettings() 로 확인해 화면과 본체 기록(/api/client)에 남긴다.
//   (메아리 지우기가 없으면 스피커로 나온 비서 말을 사람 말로 잘못 듣는다 — 4단계 시험 결과)
//   비서 목소리는 <audio> 로 재생한다 — 브라우저 메아리 지우기가 스피커 소리를 기준으로 쓰는 길.
//   주소에 ?aec=off 를 붙이면 일부러 끈 채로 열어 경고 화면을 확인할 수 있다.
"use strict";
const KAudio = (() => {
  const KEYS = ["echoCancellation", "noiseSuppression", "autoGainControl"];
  let last = null;

  function wanted() {
    const off = /[?&]aec=off\b/.test(location.search);
    return {echoCancellation: !off, noiseSuppression: !off, autoGainControl: !off, channelCount: 1};
  }

  async function openMic(deviceId) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw Object.assign(new Error("이 화면에서는 마이크를 쓸 수 없어요."), {name: "NotSupported"});
    }
    const c = wanted();
    if (deviceId) c.deviceId = {exact: deviceId};
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: c});
    } catch (e) {
      if (deviceId && (e.name === "OverconstrainedError" || e.name === "NotFoundError")) {
        delete c.deviceId;   // 골라 둔 마이크가 빠졌으면 기본 마이크로
        stream = await navigator.mediaDevices.getUserMedia({audio: c});
      } else {
        throw e;
      }
    }
    const tr = stream.getAudioTracks()[0];
    const st = (tr && tr.getSettings) ? tr.getSettings() : {};
    const sup = navigator.mediaDevices.getSupportedConstraints ? navigator.mediaDevices.getSupportedConstraints() : {};
    const settings = {}, supported = {};
    KEYS.forEach((k) => { settings[k] = (k in st) ? st[k] : null; supported[k] = !!sup[k]; });
    const info = {
      label: tr ? tr.label : "", deviceId: st.deviceId || "", settings, supported,
      requested: {echoCancellation: c.echoCancellation, noiseSuppression: c.noiseSuppression, autoGainControl: c.autoGainControl},
      aec: settings.echoCancellation === true,
    };
    last = info;
    try { console.info("[마이크 처리]", JSON.stringify(info)); } catch (_) { /* 기록만 */ }
    report(info);
    return {stream, info};
  }

  function report(info) {
    fetch("/api/client", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({"마이크": info.settings, "지원": info.supported, "장치": info.label})}).catch(() => {});
  }

  function stop(stream) {
    if (stream) stream.getTracks().forEach((t) => { try { t.stop(); } catch (_) { /* 이미 꺼짐 */ } });
  }

  async function devices() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return {mics: [], spks: []};
    const all = await navigator.mediaDevices.enumerateDevices();
    const name = (d, i, kind) => d.label || `${kind} ${i + 1}`;
    const mics = all.filter((d) => d.kind === "audioinput").map((d, i) => ({id: d.deviceId, label: name(d, i, "마이크")}));
    const spks = all.filter((d) => d.kind === "audiooutput").map((d, i) => ({id: d.deviceId, label: name(d, i, "스피커")}));
    return {mics, spks};
  }

  async function setSink(el, id) {
    if (!el || typeof el.setSinkId !== "function") return false;
    try { await el.setSinkId(id || ""); return true; } catch (_) { return false; }
  }

  // 소리 크기 막대 — stop 함수를 돌려줌
  function meter(stream, onLevel) {
    const ctx = new AudioContext();
    const src = ctx.createMediaStreamSource(stream);
    const an = ctx.createAnalyser();
    an.fftSize = 1024;
    src.connect(an);
    const buf = new Float32Array(an.fftSize);
    let on = true;
    const tick = () => {
      if (!on) return;
      an.getFloatTimeDomainData(buf);
      let s = 0;
      for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
      onLevel(Math.min(1, Math.sqrt(s / buf.length) * 6));
      setTimeout(tick, 80);
    };
    ctx.resume().catch(() => {});
    tick();
    return () => { on = false; try { src.disconnect(); ctx.close(); } catch (_) { /* 이미 닫힘 */ } };
  }

  // 말 한 마디 녹음 — 말소리가 시작되면 모으고, 0.8초 조용하면 끝. → {pcm: 16kHz int16 바이트, sec, speech}
  function recordUtterance(stream, opts) {
    const o = Object.assign({maxSec: 6, waitSec: 9, onLevel: null}, opts || {});
    return new Promise((resolve) => {
      const ctx = new AudioContext();
      const src = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      const rate = ctx.sampleRate, blockSec = 4096 / rate;
      const pre = [], got = [];
      let floor = null, n = 0, speaking = false, speechSec = 0, quiet = 0, done = false;
      const finish = (speech) => {
        if (done) return;
        done = true;
        try { proc.disconnect(); src.disconnect(); ctx.close(); } catch (_) { /* 이미 닫힘 */ }
        const all = speech ? pre.concat(got) : [];
        const pcm = to16k(all, rate);
        resolve({pcm, sec: pcm.length / 16000, speech});
      };
      proc.onaudioprocess = (ev) => {
        const x = new Float32Array(ev.inputBuffer.getChannelData(0));
        let s = 0;
        for (let i = 0; i < x.length; i++) s += x[i] * x[i];
        const rms = Math.sqrt(s / x.length);
        if (o.onLevel) o.onLevel(Math.min(1, rms * 6));
        n++;
        if (floor === null) floor = rms; else if (!speaking) floor = floor * 0.9 + rms * 0.1;
        const thr = Math.max(0.012, floor * 2.5);
        if (!speaking) {
          pre.push(x);
          if (pre.length > 4) pre.shift();
          if (n > 3 && rms > thr) { speaking = true; got.push(x); speechSec = blockSec; }
          else if (n * blockSec > o.waitSec) finish(false);
          return;
        }
        got.push(x);
        speechSec += blockSec;
        quiet = rms < thr * 0.6 ? quiet + blockSec : 0;
        if ((quiet >= 0.8 && speechSec >= 0.4) || speechSec >= o.maxSec) finish(true);
      };
      src.connect(proc);
      proc.connect(ctx.destination);   // 이어 줘야 처리가 돎(출력은 0)
      ctx.resume().catch(() => {});
    });
  }

  function to16k(chunks, rate) {
    let len = 0;
    chunks.forEach((c) => { len += c.length; });
    const x = new Float32Array(len);
    let off = 0;
    chunks.forEach((c) => { x.set(c, off); off += c.length; });
    const ratio = rate / 16000;
    const outLen = Math.floor(x.length / ratio);
    const out = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const a = Math.floor(i * ratio), b = Math.min(x.length, Math.floor((i + 1) * ratio));
      let s = 0;
      for (let j = a; j < b; j++) s += x[j];
      const v = b > a ? s / (b - a) : x[a] || 0;
      out[i] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)));
    }
    return out;
  }

  // 스피커 시험용 짧은 소리(목소리 서버가 없을 때)
  function beepUrl() {
    const sr = 24000, n = Math.floor(sr * 0.7), buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
    const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    w(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true);
    v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true);
    v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, n * 2, true);
    for (let i = 0; i < n; i++) {
      const env = Math.min(1, i / 800, (n - i) / 800);
      v.setInt16(44 + i * 2, Math.round(Math.sin(2 * Math.PI * 660 * i / sr) * 9000 * env), true);
    }
    return URL.createObjectURL(new Blob([buf], {type: "audio/wav"}));
  }

  function describe(info) {
    if (!info) return null;
    const s = info.settings || {};
    const T = (x, v) => (window.tr ? tr(x, v) : x);
    const word = (x) => T(x === true ? "켜짐" : x === false ? "꺼짐" : "알 수 없음");
    return {aec: info.aec, lines: [T("메아리 지우기: {0}", {0: word(s.echoCancellation)}), T("잡음 줄이기: {0}", {0: word(s.noiseSuppression)}),
      T("소리 크기 자동: {0}", {0: word(s.autoGainControl)})], label: info.label};
  }

  return {openMic, stop, devices, setSink, meter, recordUtterance, beepUrl, describe, last: () => last};
})();
