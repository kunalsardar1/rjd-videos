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
const FPS = 30, SUB = parseInt(process.env.SUB, 10) || 3;
const MIN = { hook: 1.4, title: 1.8, pay: 2.0, needs: 2.0, cta: 3.0 };
const NAMES = ['hook', 'title', 'pay', 'needs', 'cta'];
const env = process.env;
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

/* A plain HTTPS request that waits as long as Apps Script may take (up to 6 minutes; Node's fetch gives up after 5)
   and follows the web app's redirect to its answer. */
function request(url, method, body, ms, hops) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const mod = u.protocol === 'http:' ? require('http') : require('https');
    const headers = body ? { 'Content-Type': 'text/plain;charset=utf-8', 'Content-Length': Buffer.byteLength(body) } : {};
    const req = mod.request(u, { method, headers }, res => {
      if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location && (hops || 0) < 5) {
        res.resume();
        const keep = res.statusCode === 307 || res.statusCode === 308;
        return resolve(request(new URL(res.headers.location, url).toString(), keep ? method : 'GET', keep ? body : null, ms, (hops || 0) + 1));
      }
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, text: Buffer.concat(chunks).toString('utf8') }));
    });
    req.setTimeout(ms, () => req.destroy(new Error('the web app did not answer within ' + Math.round(ms / 1000) + ' seconds')));
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

async function webApp(body, ms) {
  const url = (env.RJD_URL || '').trim();
  if (!/^https?:\/\/[^\s]+\/exec$/.test(url)) {
    throw new Error('The RJD_URL secret must be the Web app URL from Apps Script (https://script.google.com/macros/s/.../exec)');
  }
  const res = await request(url, 'POST', JSON.stringify(Object.assign({ key: (env.RJD_KEY || '').trim() }, body)), ms || 420000);
  let j; try { j = JSON.parse(res.text); } catch (e) {
    const t = res.text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    throw new Error('Web app answered ' + res.status + ' (check the deployment: Web app, Execute as Me, Who has access: Anyone): ' + t.slice(0, 200));
  }
  if (!j.ok) {
    if (j.error === 'wrong key') throw new Error('Web app: wrong key. The RJD_KEY secret must be the RJD_KEY that setupVideo shows');
    if (j.error === 'unknown action') throw new Error('Web app runs old code: Apps Script > Deploy > Manage deployments > pencil > Version: New version > Deploy');
    throw new Error('Web app: ' + (j.error || 'failed'));
  }
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

/** Scene times from the voice (or fixed times without a voice).
    The voice is never cut: it plays as one piece, exactly as it was spoken, and each scene starts just before its
    line is heard. A cut in the wrong place can then only move a scene change, never break a word.
    Returns the scenes, the one voice piece for the mix, and when each line is spoken (for the words on screen). */
function timeline(segs) {
  const scenes = [], pieces = [], speak = [];
  if (!segs) {
    let t = 0;
    NAMES.forEach(n => { const d = { hook: 2.8, title: 3.4, pay: 3.0, needs: 3.4, cta: 4.4 }[n]; scenes.push({ name: n, s: +t.toFixed(3), e: +(t + d).toFixed(3) }); t += d; });
    return { scenes, pieces, speak, end: t };
  }
  const LEAD = 0.25;                       // the first word is heard this long after the video starts
  const shift = LEAD - segs[0].s;
  pieces.push({ from: segs[0].s, to: segs[segs.length - 1].e, at: LEAD });
  segs.forEach(g => speak.push({ s: +(g.s + shift).toFixed(3), e: +(g.e + shift).toFixed(3) }));
  NAMES.forEach((n, i) => {
    const s = i === 0 ? 0 : Math.max(speak[i - 1].e + 0.02, speak[i].s - 0.15);
    scenes.push({ name: n, s: +s.toFixed(3), e: 0 });
  });
  scenes.forEach((sc, i) => {
    sc.e = i < scenes.length - 1 ? scenes[i + 1].s : +Math.max(speak[i].e + 1.0, sc.s + MIN.cta).toFixed(3);
  });
  return { scenes, pieces, speak, end: scenes[scenes.length - 1].e };
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
  if (!env.FIXTURE) {
    const ping = await webApp({ action: 'ping' }, 90000);   // quick check of the address, the key and the code version
    log('Web app OK, video mode:', ping.mode);
  }
  const t0 = Date.now();
  const next = env.FIXTURE ? JSON.parse(fs.readFileSync(env.FIXTURE, 'utf8')) :
    await webApp({ action: 'next', trigger: manual ? 'manual' : 'schedule', bucket: env.KIND || null, test: /^(true|yes|1)$/i.test(env.TEST || '') || undefined });
  if (next.skip) { log('Nothing to make:', next.skip); saveResult({ skip: next.skip }); return; }
  log('Job:', next.job.title, '|', next.bucket, '| voice:', next.voice || (next.wav ? 'yes' : 'no'), next.test ? '| TEST' : '', '| web app took', Math.round((Date.now() - t0) / 1000), 's');
  let segs = null;
  const voice = path.join(OUT, 'voice.wav');
  if (next.wav) {
    fs.writeFileSync(voice, Buffer.from(next.wav, 'base64'));
    // cut the voice into one piece per line, at the pauses that fit where each line should end
    const found = JSON.parse(execFileSync('python3', [path.join(DIR, 'audio.py'), 'split', voice, String(NAMES.length), JSON.stringify(next.lines || [])]).toString());
    log('Voice pieces:', found.map(p => p.s.toFixed(2) + '-' + p.e.toFixed(2)).join(' | '));
    if (found.length === NAMES.length) segs = found;
    else log('Voice pauses not found (' + found.length + ' pieces); using the voice as one piece.');
    if (!segs && found.length) {
      /* Fallback: share the voice between the scenes by the length of each line. */
      const s0 = found[0].s, e1 = found[found.length - 1].e, lens = next.lines.map(l => Math.max(4, l.length)), tot = lens.reduce((a, b) => a + b, 0);
      let t = s0; segs = lens.map(l => { const d = (e1 - s0) * l / tot; const r = { s: t, e: t + d }; t += d; return r; });
    }
  }
  const tl = timeline(segs);
  const cfg = Object.assign({}, next.render, { job: next.job, scenes: tl.scenes, speak: tl.speak, lines: next.lines || [], emojiDir: 'file://' + path.join(DIR, 'node_modules/@twemoji/svg') });
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
})().catch(e => {
  console.error(e);
  try { saveResult({ error: String(e && e.message ? e.message : e).slice(0, 300) }); } catch (x) { /* nothing to save */ }
  process.exit(1);
});
