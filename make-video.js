/**
 * One Remote Job Drop video, start to finish:
 *  1. asks the RJD Autopilot web app (Apps Script) for the next job, its Hinglish script, captions and voice;
 *  2. cuts the voice at its pauses and times the five scenes to it;
 *  3. draws every frame of template.html in Chromium (3 frames blended per video frame, for smooth motion);
 *  4. mixes slow music, sound effects and the voice, and makes the MP4 (1080x1920, H.264/AAC);
 *  5. sends the MP4 back to the web app, which posts it to Telegram, Facebook, YouTube, Instagram and Threads
 *     (in test mode it only sends it to you on Telegram).
 *
 * Settings (GitHub > Settings > Secrets and variables > Actions): RJD_URL (web app URL) and RJD_KEY (VIDEO_KEY).
 * Optional when started by hand: KIND (hindi, fast, indian, specialist, english) and TEST=true.
 * Local test: FIXTURE=fixture.json SKIP_POST=1 node make-video.js
 */
'use strict';
const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const { chromium } = require('playwright-core');

const DIR = __dirname, OUT = path.join(DIR, 'out');
const FPS = 30, SUB = 3;
const MIN = { hook: 2.0, title: 2.4, pay: 2.3, needs: 2.4, cta: 3.4 };
const NAMES = ['hook', 'title', 'pay', 'needs', 'cta'];
const env = process.env;
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

async function webApp(body) {
  const res = await fetch(env.RJD_URL, { method: 'POST', headers: { 'Content-Type': 'text/plain;charset=utf-8' }, body: JSON.stringify(Object.assign({ key: env.RJD_KEY }, body)), redirect: 'follow' });
  const text = await res.text();
  let j; try { j = JSON.parse(text); } catch (e) { throw new Error('Web app answered ' + res.status + ': ' + text.slice(0, 300)); }
  if (!j.ok) throw new Error('Web app: ' + (j.error || 'failed'));
  return j;
}

function fontsCss() {
  const fam = [['inter', 'Inter', 'latin'], ['noto-sans-devanagari', 'Noto Sans Devanagari', 'devanagari'], ['noto-sans-bengali', 'Noto Sans Bengali', 'bengali'],
    ['noto-sans-tamil', 'Noto Sans Tamil', 'tamil'], ['noto-sans-telugu', 'Noto Sans Telugu', 'telugu'], ['noto-sans-gujarati', 'Noto Sans Gujarati', 'gujarati'],
    ['noto-sans-gurmukhi', 'Noto Sans Gurmukhi', 'gurmukhi'], ['noto-sans-kannada', 'Noto Sans Kannada', 'kannada'], ['noto-sans-malayalam', 'Noto Sans Malayalam', 'malayalam'],
    ['noto-sans-oriya', 'Noto Sans Oriya', 'oriya']];
  let css = '';
  fam.forEach(([pkg, name, sub]) => {
    const dir = path.join(DIR, 'node_modules/@fontsource', pkg, 'files');
    if (!fs.existsSync(dir)) return;
    [700, 800, 900].forEach(w => {
      const f = path.join(dir, `${pkg}-${sub}-${w}-normal.woff2`);
      if (fs.existsSync(f)) css += `@font-face{font-family:'${name}';font-weight:${w};src:url('file://${f}') format('woff2');}\n`;
    });
    const latin = path.join(dir, `${pkg}-latin-700-normal.woff2`);
    if (pkg !== 'inter' && fs.existsSync(latin)) css += `@font-face{font-family:'${name}';font-weight:700;src:url('file://${latin}') format('woff2');}\n`;
  });
  return css;
}

/** Scene times from the voice pieces (or fixed times without a voice). */
function timeline(segs) {
  const scenes = [], pieces = [];
  if (!segs) {
    let t = 0;
    NAMES.forEach(n => { const d = { hook: 2.4, title: 2.9, pay: 2.6, needs: 2.8, cta: 3.8 }[n]; scenes.push({ name: n, s: +t.toFixed(3), e: +(t + d).toFixed(3) }); t += d; });
    return { scenes, pieces, end: t };
  }
  let t = 0;
  NAMES.forEach((n, i) => {
    const seg = segs[i], dur = seg.e - seg.s;
    const at = t + (i === 0 ? 0.35 : 0.3);
    pieces.push({ from: seg.s, to: seg.e, at: +at.toFixed(3) });
    const s = t, e = i === NAMES.length - 1 ? Math.max(at + dur + 1.0, s + MIN[n]) : Math.max(at + dur + 0.12, s + MIN[n]);
    scenes.push({ name: n, s: +s.toFixed(3), e: +e.toFixed(3) });
    t = e;
  });
  return { scenes, pieces, end: t };
}

async function render(cfg, frameDir) {
  let html = fs.readFileSync(path.join(DIR, 'template.html'), 'utf8').replace('/*FONTS*/', fontsCss()).replace('/*CFG*/{}', JSON.stringify(cfg));
  const page = path.join(OUT, 'page.html');
  fs.writeFileSync(page, html);
  const browser = await chromium.launch(env.CHROME_PATH ? { executablePath: env.CHROME_PATH } : {});
  const p = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
  const errors = [];
  p.on('pageerror', e => errors.push(e.message));
  await p.goto('file://' + page);
  await p.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map(i => i.complete ? 1 : new Promise(r => { i.onload = r; i.onerror = r; }))); });
  await p.waitForTimeout(300);
  if (errors.length) throw new Error('Template error: ' + errors.join(' | '));
  const meta = await p.evaluate(() => ({ END: window.TL.END, SFX: window.SFX }));
  fs.rmSync(frameDir, { recursive: true, force: true });
  fs.mkdirSync(frameDir, { recursive: true });
  const n = Math.round(meta.END * FPS) * SUB;
  for (let i = 0; i < n; i++) {
    await p.evaluate(t => window.render(t), i / (FPS * SUB));
    await p.screenshot({ path: path.join(frameDir, 'f' + String(i).padStart(5, '0') + '.jpg'), type: 'jpeg', quality: 90 });
    if (i % 300 === 0) log('frame', i, 'of', n);
  }
  await browser.close();
  return meta;
}

function saveResult(r) { fs.writeFileSync(path.join(OUT, 'result.json'), JSON.stringify(r)); }

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  // 1. the job, script, captions and voice
  const manual = env.GITHUB_EVENT_NAME ? env.GITHUB_EVENT_NAME !== 'schedule' : true;
  const next = env.FIXTURE ? JSON.parse(fs.readFileSync(env.FIXTURE, 'utf8')) :
    await webApp({ action: 'next', trigger: manual ? 'manual' : 'schedule', bucket: env.KIND || null, test: /^(true|yes|1)$/i.test(env.TEST || '') || undefined });
  if (next.skip) { log('Nothing to make:', next.skip); saveResult({ skip: next.skip }); return; }
  log('Job:', next.job.title, '|', next.bucket, '| voice:', next.voice || (next.wav ? 'yes' : 'no'), next.test ? '| TEST' : '');
  let segs = null;
  const voice = path.join(OUT, 'voice.wav');
  if (next.wav) {
    fs.writeFileSync(voice, Buffer.from(next.wav, 'base64'));
    const found = JSON.parse(execFileSync('python3', [path.join(DIR, 'audio.py'), 'split', voice, String(NAMES.length)]).toString());
    if (found.length === NAMES.length) segs = found;
    else log('Voice pauses not found (' + found.length + ' pieces); using the voice as one piece.');
    if (!segs && found.length) {
      /* Fallback: share the voice between the scenes by the length of each line. */
      const s0 = found[0].s, e1 = found[found.length - 1].e, lens = next.lines.map(l => Math.max(4, l.length)), tot = lens.reduce((a, b) => a + b, 0);
      let t = s0; segs = lens.map(l => { const d = (e1 - s0) * l / tot; const r = { s: t, e: t + d }; t += d; return r; });
    }
  }
  const tl = timeline(segs);
  const cfg = Object.assign({}, next.render, { job: next.job, scenes: tl.scenes, emojiDir: 'file://' + path.join(DIR, 'node_modules/@twemoji/svg') });
  // 2-3. frames
  const frames = path.join(OUT, 'frames');
  const meta = await render(cfg, frames);
  log('Frames done:', meta.END.toFixed(1), 's');
  // 4. sound and video
  const plan = path.join(OUT, 'plan.json'), track = path.join(OUT, 'track.wav');
  fs.writeFileSync(plan, JSON.stringify({ end: meta.END, sfx: meta.SFX, voice: segs ? voice : null, pieces: tl.pieces }));
  execFileSync('python3', [path.join(DIR, 'audio.py'), 'mix', plan, track]);
  const mp4 = path.join(OUT, 'video.mp4');
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(FPS * SUB), '-i', path.join(frames, 'f%05d.jpg'), '-i', track,
    '-filter_complex', `[0:v]tmix=frames=${SUB},framestep=${SUB},setpts=N/${FPS}/TB,format=yuv420p[v];[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]`,
    '-map', '[v]', '-map', '[a]', '-r', String(FPS), '-c:v', 'libx264', '-profile:v', 'high', '-crf', '20', '-maxrate', '8M', '-bufsize', '16M', '-preset', 'medium',
    '-g', String(FPS * 2), '-keyint_min', String(FPS * 2), '-sc_threshold', '0',
    '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-shortest', '-movflags', '+faststart', mp4]);
  log('Video:', (fs.statSync(mp4).size / 1e6).toFixed(1), 'MB');
  if (env.SKIP_POST) { log('SKIP_POST set: not posted. File:', mp4); saveResult({ id: next.id, skipPost: true }); return; }
  // 5. post: one network or two per call, so each call stays well inside the web app's time limit.
  //    Threads takes the video from Instagram's (or Facebook's) copy, so it goes last and needs no upload.
  const b64 = fs.readFileSync(mp4).toString('base64');
  const results = {};
  const rounds = next.test ? [['preview']] : [['telegram', 'facebook'], ['youtube'], ['instagram'], ['threads']];
  for (const nets of rounds) {
    try { Object.assign(results, (await webApp({ action: 'post', id: next.id, mp4: nets[0] === 'threads' ? undefined : b64, networks: nets })).results); }
    catch (e) { nets.forEach(n => { results[n] = 'failed: ' + e.message; }); }
    log(nets.join(' + ') + ':', nets.map(n => n + ' ' + results[n]).join(' | '));
  }
  saveResult({ id: next.id, kind: next.bucket, job: next.job.title, test: !!next.test, results });
  if (Object.values(results).every(v => /^failed|^off/.test(String(v)))) process.exit(1);
})().catch(e => { console.error(e); process.exit(1); });
