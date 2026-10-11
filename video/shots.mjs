// The submission video, shot by shot. Every action is timed to the voice-over words (build/tts/<shot>.json).
// Run after tts.py:  node video/shots.mjs [shotId ...]   (from the video folder)
// Output: build/clips/<shot>.mp4 and build/clips/<shot>.json (length, clicks, chapter, voice placement)
import fs from 'node:fs'
import { launch, FPS } from './rec.mjs'

const APP = 'http://localhost:8765/app/'
const SCAN = 'C:\\hackathon\\drone_data\\IIT_Gandhinagar_campus.laz'   // public drone survey (see video/README.md)
const LEAD = 0.45, TAIL = 0.75
const TTS = process.env.TTS_DIR || 'build/tts', CLIPS = process.env.CLIPS_DIR || 'build/clips'   // test runs can use other folders
const NARR = JSON.parse(fs.readFileSync('narration.json', 'utf8'))
const only = process.argv.slice(2)
const sleep = ms => new Promise(r => setTimeout(r, ms))
const norm = s => s.toLowerCase().replace(/[^a-z0-9 ]+/g, '').split(/\s+/).filter(Boolean)

const STYLE = `(() => {
  const s = document.createElement('style'); s.id = '__vidcss'
  s.textContent = \`
    .pointer-events-none.bottom-\\\\[78px\\\\] { display: none !important }
    body.__ui nav, body.__ui .glass, body.__ui .ann-layer { opacity: var(--ui-a, 1) !important }
    #__card { position: fixed; inset: 0; z-index: 2147483600; pointer-events: none; display: grid; place-items: center;
      background: radial-gradient(ellipse at 50% 45%, rgba(3,8,14,.35), rgba(3,8,14,.86) 70%); opacity: 0; font-family: Inter, 'Segoe UI', sans-serif }
    #__card.on { animation: __fin 1.1s ease forwards } #__card.off { animation: __fout .9s ease forwards }
    @keyframes __fin { from { opacity: 0 } to { opacity: 1 } } @keyframes __fout { from { opacity: 1 } to { opacity: 0 } }
    #__card .in { text-align: center; max-width: 1200px }
    #__card .up { opacity: 0; animation: __up .9s cubic-bezier(.2,.8,.2,1) forwards }
    @keyframes __up { from { opacity: 0; transform: translateY(16px); filter: blur(4px) } to { opacity: 1; transform: none; filter: none } }
    #__card .brand { display: flex; align-items: center; justify-content: center; gap: 22px }
    #__card .name { font-size: 84px; font-weight: 700; letter-spacing: -.02em; color: #fff; text-shadow: 0 0 40px rgba(34,211,238,.35) }
    #__card .name b { color: #22d3ee; font-weight: 700 }
    #__card .tag { margin-top: 14px; font-size: 25px; color: #cfe8f3; font-weight: 500 }
    #__card .line { height: 2px; width: 0; margin: 26px auto 18px; background: linear-gradient(90deg, transparent, #22d3ee, #34d399, transparent); animation: __w 1.4s .6s cubic-bezier(.2,.8,.2,1) forwards }
    @keyframes __w { to { width: 620px } }
    #__card .mono { font: 600 13px 'JetBrains Mono', ui-monospace, monospace; letter-spacing: .2em; color: #8fb3c4; text-transform: uppercase }
    #__card .chips { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin-top: 14px; max-width: 1060px }
    #__card .chip { padding: 8px 14px; border-radius: 999px; border: 1px solid rgba(148,178,210,.28); background: rgba(8,16,26,.7); color: #dbeafe; font-size: 14.5px }
    #__card .chip i { font-style: normal; color: #67e8f9; margin-right: 6px }
    #__card .repo { margin-top: 30px; display: inline-flex; gap: 12px; align-items: center; padding: 12px 22px; border-radius: 14px; border: 1px solid rgba(34,211,238,.5);
      background: rgba(6,20,28,.75); color: #fff; font: 600 22px 'JetBrains Mono', ui-monospace, monospace; box-shadow: 0 0 30px rgba(34,211,238,.25) }
    #__card .fine { margin-top: 18px; font-size: 13px; color: #7f97a8 }
  \`
  document.head.appendChild(s)
  window.__ui = a => { document.body.classList.add('__ui'); document.body.style.setProperty('--ui-a', a); if (a >= 1) document.body.classList.remove('__ui') }
  window.__card = (html, on) => {
    let c = document.getElementById('__card')
    if (!c) { c = document.createElement('div'); c.id = '__card'; document.body.appendChild(c) }
    if (html != null) c.innerHTML = html
    c.className = on ? 'on' : 'off'
  }
})()`

const LOGO = '<svg width="86" height="86" viewBox="0 0 32 32"><defs><linearGradient id="lgv" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#34d399"/></linearGradient></defs><path d="M16 3 28 10v12L16 29 4 22V10z" fill="none" stroke="url(#lgv)" stroke-width="1.6"/><path d="M16 9v14M10 12.5v8M22 12.5v8" stroke="url(#lgv)" stroke-width="1.6" stroke-linecap="round"/><circle cx="16" cy="9" r="1.8" fill="#34d399"/></svg>'

class Shot {
  constructor(rec, s) {
    this.rec = rec; this.s = s; this.id = s.id
    this.tts = JSON.parse(fs.readFileSync(`${TTS}/${s.id}.json`, 'utf8'))
    this.lead = s.lead ?? LEAD
    this.len = this.lead + this.tts.duration + TAIL
    this.clicks = []; this.extra = 0; this.voice = [{ from: 0, to: this.tts.duration, at: this.lead }]
    const toks = []
    this.tts.words.forEach(w => norm(w.w).forEach(t => toks.push({ t, t0: w.t0 })))
    this.toks = toks
  }
  cue(phrase) {
    const p = norm(phrase)
    for (let i = 0; i + p.length <= this.toks.length; i++) if (p.every((t, k) => this.toks[i + k].t === t)) return this.lead + this.extra + this.toks[i].t0
    throw new Error(`cue "${phrase}" not in ${this.id}`)
  }
  async until(t) { while (this.rec.t < t) await this.rec.frame() }
  async at(phrase, off = 0) { await this.until(this.cue(phrase) + off) }
  // the press shows in the frame two frames back (press, frame, release, frame), so the sound goes there
  async click(sel, text, sec = .65) { await this.rec.click(sel, text, sec); this.clicks.push(this.rec.t - 2 / FPS) }
  async clickAt(x, y, sec = .65) { await this.rec.clickAt(x, y, sec); this.clicks.push(this.rec.t - 2 / FPS) }
  /* let the voice from `phrase` on start no earlier than clip time t (the picture needs a moment) */
  holdVoice(phrase, t) {
    const planned = this.cue(phrase), audioT = planned - this.extra - this.lead
    this.voice[this.voice.length - 1].to = audioT
    this.extra += Math.max(0, t - planned)
    this.voice.push({ from: audioT, to: this.tts.duration, at: this.lead + this.extra + audioT })
  }
  async finish(extraTail = 0) { await this.until(this.len + this.extra + extraTail) }
}

async function ringJs(rec, id, expr, pad = 6) {
  const r = await rec.eval(`(() => { const el = ${expr}; if (!el) return null; const b = el.getBoundingClientRect(); return [b.left, b.top, b.width, b.height] })()`)
  if (r) await rec.eval(`__ov.ring('${id}', ${r[0] - pad}, ${r[1] - pad}, ${r[2] + 2 * pad}, ${r[3] + 2 * pad})`)
  return r
}
const byText = (sel, text) => `[...document.querySelectorAll(${JSON.stringify(sel)})].find(e => e.textContent.trim().toLowerCase().includes(${JSON.stringify(text.toLowerCase())}))`
const smallest = (sel, ...res) => `[...document.querySelectorAll(${JSON.stringify(sel)})].filter(e => { const b = e.getBoundingClientRect(); return b.width > 0 && ${JSON.stringify(res)}.every(r => new RegExp(r, 'i').test(e.textContent)) }).sort((a, b) => { const p = a.getBoundingClientRect(), q = b.getBoundingClientRect(); return p.width * p.height - q.width * q.height })[0]`
const metricBox = label => `${byText('.label', label)}?.parentElement`
const screenOf = async (rec, x, z, up = 2) => rec.eval(`(() => { const c = __gc.viewer.scene.cartesianToCanvasCoordinates(__gc.pos(${x}, ${z}, ${up})); return c ? [c.x, c.y] : null })()`)

async function setHour(shot, k, sec = 1.2) {
  // drag the hour slider thumb like a person would
  const rec = shot.rec
  const [l, t, w, h] = await rec.rect('input.hour')
  const cur = await rec.eval(`+document.querySelector('input.hour').value`)
  const x = i => l + 8 + (w - 16) * i / 12, y = t + h / 2
  await rec.moveTo(x(cur), y, .5)
  await rec.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: x(cur), y, button: 'left', clickCount: 1 })
  shot.clicks.push(rec.t)
  const n = Math.round(sec * FPS)
  for (let i = 1; i <= n; i++) {
    const e = i / n, px = x(cur) + (x(k) - x(cur)) * (e < .5 ? 2 * e * e : 1 - Math.pow(-2 * e + 2, 2) / 2)
    await rec.eval(`__ov.cursor(${px}, ${y})`)
    await rec.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: px, y, button: 'left', buttons: 1 })
    await rec.frame()
  }
  await rec.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x(k), y, button: 'left', clickCount: 1 })
  rec.mouse = [x(k), y]
  const v = await rec.eval(`+document.querySelector('input.hour').value`)
  if (v !== k) await rec.eval(`(() => { const el = document.querySelector('input.hour'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, ${k}); el.dispatchEvent(new Event('input', { bubbles: true })) })()`)
}

/* ---------------------------------------------------------------- shots */
const SHOTS = {
  async s0_intro(sh, rec) {
    await rec.eval(`__ui(0); __gc.stopOrbit(); __gc.fly(0, 0, 5600, -0.5, -1.32, false, 0)`)
    await rec.settle(2500)
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__gc.fly(0, 0, 2500, 0.45, -0.98, false, ${sh.len.toFixed(2)})`)
    await rec.hold(.3)
    await rec.eval(`__card(${JSON.stringify(`<div class="in"><div class="brand up">${LOGO}<div class="name">GreenCity<b>AI</b></div></div>
      <div class="tag up" style="animation-delay:.35s">A 3D digital twin that finds the heat on every street, and tests the fix.</div>
      <div class="line"></div></div>`)}, true)`)
    await sh.until(sh.len - 1.1)
    await rec.eval(`__card(null, false)`)
    await sh.finish()
  },

  async s1_twin(sh, rec) {
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__gc.fly(0, 0, 1350, 0.9, -0.62, true, 5.5)`)
    await rec.hold(.9, (k) => rec.eval(`__ui(${Math.min(1, k * 1.05)})`))
    await rec.eval(`__ui(1); __ov.chapter('01', 'A digital twin from open data', 'Connaught Place · New Delhi')`)
    const X = 1196
    await sh.at('the tiles are only', -.1)
    if (await rec.eval(`!!__gc.tilesOn`)) await rec.eval(`__ov.callout('g', ${X}, 92, '3D base · display only', 'Google Photorealistic 3D Tiles', 'never measured: every number comes from the twin', 'cyan')`)
    await sh.at('212 buildings', -.15)
    await rec.eval(`__ov.off('g')`)
    await rec.eval(`__ov.callout('a', ${X}, 92, 'OpenStreetMap · observed', '212 buildings', 'roads, crossings, signals, bus stops', 'cyan')`)
    await sh.at('936 trees', -.15)
    await rec.eval(`__ov.callout('b', ${X}, 184, 'Canopy map · AWS Open Data', '936 trees', 'Meta + WRI 1 m canopy height · 26.2% cover', 'green')`)
    await sh.at('the true sun', -.1)
    await rec.eval(`__ov.callout('c', ${X}, 276, 'Sun position · computed', '15 May', 'noon elevation 79° · shade every hour')`)
    await rec.eval(`__ov.chapterOff()`)
    await sh.until(sh.len - .5)
    await rec.eval(`__ov.off('a'); __ov.off('b'); __ov.off('c')`)
    await sh.finish()
  },

  async s2_heat(sh, rec) {
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__ov.chapter('02', 'Heat on every footpath', '15 May · hourly sun')`)
    await rec.eval(`__gc.fly(20, -40, 640, 1.35, -0.74, true, 3.6)`)
    await sh.click('button', 'area intelligence')                       // fold the side panel away
    await sh.click('button', 'layers')
    await sh.click('button', 'sun & shade on walkways')
    await rec.hold(.3)
    await sh.click('button', 'layers')
    await rec.eval(`__ov.chapterOff()`)
    await sh.at('7 am', -.6)
    await setHour(sh, 1, 1.1)
    await ringJs(rec, 'sh', `document.querySelector('input.hour').closest('.glass')`, 4)
    await sh.at('by noon', -.3)
    await setHour(sh, 6, 1.0)
    await sh.at('the hex map', -.3)
    await rec.eval(`__ov.off('sh')`)
    await sh.click('button', 'layers')
    await sh.click('button', 'sun-exposure hex map')
    await sh.click('button', 'sun & shade on walkways')
    await sh.click('button', 'layers')
    await rec.eval(`__gc.fly(0, 0, 1050, 1.9, -0.95, true, 3.2)`)
    await sh.finish()
  },

  async s3_city(sh, rec) {
    await rec.eval(`(() => { const el = document.querySelector('input.hour'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, 9); el.dispatchEvent(new Event('input', { bubbles: true })) })()`)   // back to 15:00 between shots
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__ov.chapter('03', 'The city around it', '900 m of OpenStreetMap')`)
    await rec.eval(`__gc.fly(0, 0, 2700, 2.45, -0.64, true, 4.2)`)
    await rec.hold(.4)
    await sh.click('button', 'area intelligence')
    await rec.eval(`__ov.chapterOff()`)
    await sh.at('a kilometre', -.2)
    await ringJs(rec, 'big', `${byText('.label', 'area intelligence')}?.closest('section')?.querySelector('.flex.items-center.gap-3')`, 6)
    await sh.at('every number', -.1)
    await rec.eval(`__ov.off('big')`)
    await ringJs(rec, 'legend', smallest('div', 'observed', 'computed', 'simulated', 'proposed'), 5)
    await sh.until(sh.len - .4)
    await rec.eval(`__ov.off('legend')`)
    await sh.finish()
  },

  async s4_analyze(sh, rec) {
    await rec.eval(`__gc.setLayer('transit', false); __gc.setLayer('hexmap', false)`)
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__ov.chapter('04', 'Overloaded roads', 'Simulated peak hour · Middle Circle × Radial Road 2')`)
    await rec.eval(`__gc.fly(40, -10, 1150, 2.75, -0.82, false, 3.0)`)
    await sh.at('20 road links', -.2)
    await rec.eval(`__ov.chapterOff(); __ov.callout('ov', 1196, 92, 'Simulated peak hour · assumed demand', '20 links over capacity', 'drawn thick and red · worst 1.87× capacity', '')`)
    await sh.at('analyze scans', -1.7)
    await rec.eval(`__ov.off('ov'); __gc.fly(85, -36, 560, 2.9, -0.62, false, 1.5)`)
    await rec.hold(1.6)
    const p = await screenOf(rec, 85.4, -36.5, 2)
    await sh.clickAt(p[0], p[1], .7)
    await rec.hold(.4)
    await sh.click('button', 'analyze area', .6)
    await sh.at('1.57', -.25)
    await ringJs(rec, 'f1', `[...document.querySelectorAll('button')].find(b => b.textContent.includes('Approach over capacity'))`, 2)
    await sh.at('85 percent', -.35)
    await rec.eval(`__ov.off('f1')`)
    await ringJs(rec, 'f2', `[...document.querySelectorAll('button')].find(b => b.textContent.includes('Walkways exposed') || b.textContent.includes('Walkways partly'))`, 2)
    await sh.until(sh.len - .3)
    await rec.eval(`__ov.off('f2')`)
    await sh.finish()
  },

  async s5_doctor(sh, rec) {
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__ov.chapter('05', 'AI street doctor', 'Claude Sonnet 5.5')`)
    const scroller = `document.querySelector('.max-h-\\\\[calc\\\\(100vh-330px\\\\)\\\\]')`
    await rec.hold(.25, () => rec.eval(`(() => { const s = ${scroller}; if (s) s.scrollTop += 60 })()`))
    await rec.hold(.35)
    await sh.click('button', 'explain with claude', .7)
    await rec.hold(1.1)
    // real time passes while Claude calls the tools; page time stays frozen, so nothing jumps
    const t0 = Date.now()
    await rec.waitFor(`/all numbers checked|[0-9]+ unchecked|offline templates|not running/i.test(document.body.innerText)`, 240000, 500)
    console.log('  doctor answered in', ((Date.now() - t0) / 1000).toFixed(1), 's')
    await rec.eval(`__ov.chapterOff()`)
    // bring the answer's header (model name and the checker's badge) to the top of the panel
    await rec.hold(1.4, (k) => rec.eval(`(() => { const s = ${scroller}; const box = s && [...s.querySelectorAll('.rounded-xl.border')].pop(); if (!box) return
      const target = Math.min(s.scrollHeight - s.clientHeight, box.getBoundingClientRect().top - s.getBoundingClientRect().top + s.scrollTop - 8); s.scrollTop += (target - s.scrollTop) * 0.16 })()`))
    await sh.at('a checker', -.2)
    await ringJs(rec, 'chk', `[...document.querySelectorAll('.chip')].find(c => /checked|unchecked/i.test(c.textContent))`, 4)
    await sh.until(sh.len - .3)
    await rec.eval(`__ov.off('chk')`)
    await sh.finish()
  },

  async s6_simulate(sh, rec) {
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__ov.chapter('06', 'Test the fix', 'Current vs proposed')`)
    await sh.click('button[role=tab]', 'simulate', .6)
    await rec.eval(`__gc.fly(70, -20, 420, __gc.viewer.camera.heading + 0.3, -0.72, true, 2.6)`)
    await rec.hold(.5)
    await sh.click('button', 'current', .5)
    await rec.eval(`__ov.chapterOff()`)
    await sh.at('diverting', -.3)
    await sh.click('button', 'proposed', .5)
    await sh.at('1.57 to', -.1)
    await ringJs(rec, 'm1', metricBox('peak load'), 4)
    await sh.at('200 street', -.2)
    await rec.eval(`__ov.off('m1')`)
    await ringJs(rec, 'm2', metricBox('walkway shade'), 4)
    await sh.at('costs are', -.1)
    await rec.eval(`__ov.off('m2')`)
    await ringJs(rec, 'm3', metricBox('cost'), 4)
    await sh.until(sh.len - .3)
    await rec.eval(`__ov.off('m3')`)
    await sh.finish()
  },

  async s7_anywhere(sh, rec) {
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__ov.chapter('07', 'Anywhere in India', 'Search · build · analyse')`)
    await sh.click('button[role=tab]', 'explore', .6)
    await sh.at('search for', -.5)
    await sh.click('input[aria-label="Search location"]', null, .6)
    await rec.type('Charminar', 13)
    await rec.eval(`__ov.chapterOff()`)
    const found = await rec.holdUntil(`[...document.querySelectorAll('button')].some(b => b.textContent.includes('Charminar Circle'))`, 15)
    if (!found) throw new Error('place search returned nothing')
    await rec.hold(.3)
    await sh.click('button', 'charminar circle', .6)
    sh.holdVoice('and the city map', rec.t + 2.4)   // the camera flies across India first
    await sh.at('press build', -.35)
    await rec.holdUntil(`document.body.innerText.includes('Build a twin here') && !document.body.innerText.includes('Loading map detail')`, 20)
    await sh.click('button', 'build a twin here', .6)
    // time-lapse while the real build runs: page time runs free, one frame every 0.8 s of real time
    const tl0 = rec.t
    await rec.eval(`__vt.setFree(true); __ov.hideCursor(); __ov.callout('tl', 1220, 92, 'Time-lapse · real build', 'Sped up', 'OpenStreetMap · canopy map · hourly sun · traffic', 'cyan')`)
    await rec.hold(.25)
    const realStart = Date.now()
    for (;;) {
      await sleep(800)
      await rec.snap()
      const done = await rec.eval(`!!window.__gc?.site && window.__gc.site.twin.meta.name !== 'connaught' && document.body.innerText.includes('AREA INTELLIGENCE') && !document.body.innerText.includes('Building the twin…') && !document.body.innerText.includes('Loading map detail')`)
      if (done) break
      if (Date.now() - realStart > 240000) throw new Error('build took too long')
    }
    console.log('  build took', ((Date.now() - realStart) / 1000).toFixed(0), 's real')
    await rec.eval(`__ov.off('tl'); __vt.setFree(false)`)
    sh.holdVoice('and in under', rec.t + .15)
    sh.timelapse = [tl0, rec.t]
    await rec.eval(`__gc.fly(0, 0, 1250, 0.7, -0.62, true, 3.2)`)
    await sh.finish(.6)
  },

  async s8_drone(sh, rec) {
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__ov.chapter('08', 'Your own drone scan', 'Upload LAS · LAZ · PLY')`)
    await sh.at('upload its', -.7)
    await rec.chooseFiles([SCAN])
    await sh.click('button', 'upload scan', .6)
    if (!await rec.holdUntil(`!!document.querySelector('[data-testid=upload-card]')`, 6)) throw new Error('upload card did not open')
    await rec.eval(`__ov.chapterOff()`)
    await sh.at('this public', -.5)
    await sh.click('button', 'build a twin from this scan', .6)
    await rec.eval(`__ov.callout('cr', 1196, 92, 'Public data · Mendeley Data', 'IIT Gandhinagar campus', 'Drone survey: IIT Gandhinagar students, 2024 · CC BY-NC 3.0 · doi:10.17632/nmxysw8ybx.1', 'cyan')`)
    await sh.at('12.6 million', -.3)
    await ringJs(rec, 'info', `document.querySelector('[data-testid=upload-card] .num')`, 5)
    await sh.at('finds its own', .2)
    // time-lapse while the real build runs (page time runs free, one frame every 0.8 s of real time)
    const tl0 = rec.t
    await rec.eval(`__ov.off('info'); __ov.off('cr'); __vt.setFree(true); __ov.hideCursor(); __ov.callout('tl', 1220, 92, 'Time-lapse · real build', 'Sped up', 'ground · trees · roofs · OpenStreetMap · hourly sun', 'cyan')`)
    await rec.hold(.25)
    const realStart = Date.now()
    for (;;) {
      await sleep(800)
      await rec.snap()
      const done = await rec.eval(`!!window.__gc?.site && /iit_gandhinagar/.test(window.__gc.site.twin.meta.name) && document.body.innerText.includes('AREA INTELLIGENCE') && !document.body.innerText.includes('Building the twin…') && !document.body.innerText.includes('Loading map detail')`)
      if (done) break
      if (Date.now() - realStart > 420000) throw new Error('drone build took too long')
    }
    console.log('  drone build took', ((Date.now() - realStart) / 1000).toFixed(0), 's real')
    await rec.eval(`__ov.off('tl'); __vt.setFree(false)`)
    sh.timelapse = [tl0, rec.t]
    sh.holdVoice('the scan measures', rec.t + .5)
    await rec.eval(`__gc.fly(-60, -60, 1150, 0.75, -0.6, true, 3.6)`)
    await sh.at('71 of 73', -.2)
    await rec.eval(`__ov.callout('m', 1196, 92, 'Measured from the drone points', '71 of 73 buildings', 'height = 90th percentile of roof points', 'cyan')`)
    await sh.at('2,380', -.2)
    await rec.eval(`__ov.callout('t', 1196, 184, 'Tree tops in the scan', '2,380 trees', 'raised green points, 3 m and taller', 'green')`)
    await sh.until(sh.len + sh.extra - .4)
    await rec.eval(`__ov.off('m'); __ov.off('t')`)
    await sh.finish(.2)
  },

  async s9_points(sh, rec) {
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__ov.chapter('09', 'Every point, measured', 'IIT Gandhinagar · drone survey')`)
    await sh.click('nav button', 'point cloud', .6)
    if (!await rec.holdUntil(`!!window.__pc && document.querySelector('[data-testid=pc-panel]')?.innerText.includes('Photo')`, 25)) throw new Error('point cloud did not open')
    await rec.eval(`__pc.cam.position.set(470, 330, 470); __pc.ctl.target.set(-40, 0, 20); __pc.replay(); __pc.fly([60, 230, 330], [-110, 0, 40], 5.5)`)
    await rec.eval(`__ov.callout('cr', 1196, 92, 'Drone survey · photogrammetry', '12.6 M points', 'Drone survey: IIT Gandhinagar students, 2024 · CC BY-NC 3.0 · doi:10.17632/nmxysw8ybx.1', 'cyan')`)
    await rec.hold(1.2)
    await rec.eval(`__ov.chapterOff()`)
    await sh.at('or by class', -.4)
    await rec.eval(`__ov.off('cr')`)
    await sh.click('[data-testid=pc-panel] button', 'class', .5)
    await sh.at('ground roofs', -.2)
    await ringJs(rec, 'cls', `document.querySelector('[data-testid=pc-panel] .mt-2:has(> button)')`, 5)
    await rec.eval(`__pc.fly([-10, 120, 210], [-165, 8, 60], 4.2)`)
    await sh.until(sh.len - .4)
    await rec.eval(`__ov.off('cls')`)
    await sh.finish()
  },

  async s10_splats(sh, rec) {
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__ov.chapter('10', 'Gaussian splats', 'Our own WebGL2 renderer')`)
    await sh.click('[data-testid=pc-panel] button', 'gaussian splats', .6)
    if (!await rec.holdUntil(`!!window.__pc?.gsr`, 20)) throw new Error('splats did not open')
    await rec.eval(`__ov.hideCursor()`)
    await rec.eval(`__pc.cam.position.set(150, 260, 420); __pc.ctl.target.set(-60, 0, -120); __pc.replay(); __pc.fly([170, 120, -170], [-60, 6, -380], 7)`)
    await rec.hold(1.4)
    await rec.eval(`__ov.chapterOff(); __ov.callout('g', 1196, 92, 'Real 3D gaussian splatting', '2.0 M splats', 'one per measured point · not trained from photos', 'cyan')`)
    await sh.until(sh.len - .4)
    await rec.eval(`__ov.off('g')`)
    await sh.finish()
  },

  async s11_outro(sh, rec) {
    await rec.start(`${CLIPS}/${sh.id}.mp4`)
    await rec.eval(`__ov.hideCursor(); __pc.ctl.autoRotate = true; __pc.ctl.autoRotateSpeed = 0.35`)
    await rec.hold(1.0, (k) => rec.eval(`__ui(${(1 - k).toFixed(3)})`))
    await rec.eval(`__ui(0)`)
    await rec.eval(`__card(${JSON.stringify(`<div class="in"><div class="brand up">${LOGO}<div class="name">GreenCity<b>AI</b></div></div>
      <div class="tag up" style="animation-delay:.3s">Open data and drone scans in. Cooler streets out.</div><div class="line"></div>
      <div class="chips up" style="animation-delay:.7s"><span class="chip"><i>data</i>OpenStreetMap (ODbL)</span><span class="chip"><i>data</i>Meta + WRI canopy height · AWS Open Data</span><span class="chip"><i>data</i>IIT Gandhinagar drone survey (CC BY-NC 3.0)</span><span class="chip"><i>data</i>NOAA sun · Open-Meteo weather</span></div>
      <div class="chips up" style="animation-delay:1.0s"><span class="chip"><i>engine</i>Python twin pipeline · LAS/LAZ/PLY</span><span class="chip"><i>3D</i>CesiumJS · React · own WebGL2 gaussian splats</span><span class="chip"><i>AI</i>Claude Sonnet 5.5 · Claude Code or Amazon Bedrock</span><span class="chip"><i>voice</i>Gemini 3.8 Flash TTS</span></div>
      <div class="repo up" style="animation-delay:1.5s">greencityai.shaileshyadav.in</div>
      <div class="fine up" style="animation-delay:1.7s">Code: github.com/yshail/streetscope</div>
      <div class="fine up" style="animation-delay:1.9s">Traffic is simulated from assumed demand. Costs are assumptions, not quotes.</div></div>`)}, true)`)
    await sh.finish(2.2)
  },
}

/* Google Photorealistic 3D Tiles key (Google Maps key or Cesium ion token): video/.env "gkey=..." or video/gkey.txt.
   Both are git-ignored. The key is only put in the headless browser's storage, never printed. */
function readKey() {
  if (fs.existsSync('.env')) {
    const m = fs.readFileSync('.env', 'utf8').match(/^\s*gkey\s*=\s*["']?([^"'\r\n]+)/im)
    if (m) return m[1].trim()
  }
  return fs.existsSync('gkey.txt') ? fs.readFileSync('gkey.txt', 'utf8').trim() : ''
}

/* ---------------------------------------------------------------- run */
const rec = await launch({ dsf: 1.25, tag: 'video' })
rec.snap = async function () {
  const r = await this.send('Page.captureScreenshot', { format: 'jpeg', quality: 94, optimizeForSpeed: true })
  const buf = Buffer.from(r.result.data, 'base64')
  if (!this.ff.stdin.write(buf)) await new Promise(res => this.ff.stdin.once('drain', res))
  this.frames++
}
try {
  const GKEY = readKey()
  if (GKEY) await rec.send('Page.addScriptToEvaluateOnNewDocument', { source: `try { localStorage.setItem('gkey', ${JSON.stringify(GKEY)}) } catch (e) {}` })
  console.log(GKEY ? 'Google Photorealistic 3D Tiles: on' : 'Google tiles: no video/gkey.txt, dark open-data city')
  await rec.goto(APP + '?site=' + (process.env.START_SITE || 'connaught'), `window.__gc && document.body.innerText.includes('AREA INTELLIGENCE')`)
  await rec.eval(STYLE)
  await rec.eval(`__gc.viewer.useBrowserRecommendedResolution = false; __gc.setQuality('high')`)
  await rec.settle(4000)
  fs.mkdirSync(CLIPS, { recursive: true })
  if (only.length && !only.includes('s2_heat')) {   // match the full take's layer state (hex map on, shown again on the next site)
    await rec.eval(`(() => { const b = t => [...document.querySelectorAll('button')].find(x => x.textContent.toLowerCase().includes(t)); b('layers').click(); setTimeout(() => { b('sun-exposure hex map').click(); b('layers').click() }, 0) })()`)
    await rec.settle(800)
    await rec.eval(`__gc.setLayer('hexmap', false)`)
  }
  for (const s of NARR.shots) {
    if (only.length && !only.includes(s.id)) { continue }
    const sh = new Shot(rec, s)
    const t0 = Date.now()
    console.log(s.id, 'planned', sh.len.toFixed(1), 's')
    await SHOTS[s.id](sh, rec)
    const len = await rec.stop()
    fs.writeFileSync(`${CLIPS}/${s.id}.json`, JSON.stringify({ id: s.id, len, clicks: sh.clicks, voice: sh.voice, chapter: s.chapter, timelapse: sh.timelapse || null }, null, 1))
    console.log('  ->', len.toFixed(2), 's of video in', ((Date.now() - t0) / 1000).toFixed(0), 's')
  }
} catch (e) {
  console.error('FAILED:', e.message)
  if (rec.ff) await rec.stop().catch(() => { })
  process.exitCode = 1
}
console.log(rec.log.slice(0, 12).join('\n'))
await rec.close()
process.exit()
