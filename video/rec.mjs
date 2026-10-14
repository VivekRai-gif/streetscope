// Frame-exact screen recorder for the submission video.
// Chrome runs headless on the real GPU. Page time is virtual: every video frame advances the page clock by exactly
// 1/30 s (requestAnimationFrame, performance.now, Date.now, timers and CSS animations), so camera flights and
// animations come out smooth however long a frame takes to render. Frames are piped straight into ffmpeg.
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

export const FPS = 30
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const sleep = ms => new Promise(r => setTimeout(r, ms))

// injected before any page script runs
const VIRTUAL_TIME = `(() => {
  if (window.__vt) return
  const RAF = window.requestAnimationFrame.bind(window), pnow = performance.now.bind(performance)
  const ST = window.setTimeout.bind(window), CT = window.clearTimeout.bind(window), SI = window.setInterval.bind(window), CI = window.clearInterval.bind(window)
  const dateOff = Date.now() - pnow()
  let vt = pnow(), free = true, lastReal = pnow(), rafId = 0, tid = 1e7
  const rafs = new Map(), timers = new Map()
  performance.now = () => vt
  Date.now = () => Math.floor(dateOff + vt)
  window.requestAnimationFrame = cb => { const id = ++rafId; rafs.set(id, cb); return id }
  window.cancelAnimationFrame = id => { rafs.delete(id) }
  window.setTimeout = (fn, d, ...a) => { if (typeof fn !== 'function' || !(d > 0)) return ST(fn, d, ...a); const id = ++tid; timers.set(id, { at: vt + d, fn, a }); return id }
  window.clearTimeout = id => { if (id > 1e7) timers.delete(id); else CT(id) }
  window.setInterval = (fn, d, ...a) => { if (typeof fn !== 'function') return SI(fn, d, ...a); const e = Math.max(d || 0, 4), id = ++tid; timers.set(id, { at: vt + e, fn, a, every: e }); return id }
  window.clearInterval = id => { if (id > 1e7) timers.delete(id); else CI(id) }
  function step(dt) {
    vt += dt
    for (let g = 0; g < 2000; g++) {
      let best = null, bid = 0
      for (const [id, t] of timers) if (t.at <= vt && (!best || t.at < best.at)) { best = t; bid = id }
      if (!best) break
      if (best.every) best.at += best.every; else timers.delete(bid)
      try { best.fn(...best.a) } catch (e) { console.error(e) }
    }
    if (document.getAnimations) for (const a of document.getAnimations()) {
      try { if (!a.__vt) { a.__vt = 1; a.pause(); a.currentTime = 0 } else { a.currentTime = (a.currentTime || 0) + dt } } catch (e) {}
    }
    const list = [...rafs.values()]; rafs.clear()
    for (const cb of list) { try { cb(vt) } catch (e) { console.error(e) } }
  }
  function loop() { const n = pnow(); if (free) step(Math.min(100, n - lastReal)); lastReal = n; RAF(loop) }
  RAF(loop)
  window.__vt = {
    setFree(v) { free = v; lastReal = pnow() },
    frame: dt => new Promise(r => RAF(() => { step(dt); RAF(() => r(vt)) })),
    now: () => vt,
  }
})()`

// cursor, click ripple, chapter chip and callouts drawn into the page so they are part of the frame
const OVERLAY = `(() => {
  if (window.__ov) return
  const css = document.createElement('style')
  css.textContent = \`
  #__cur{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;width:26px;height:26px;transform:translate(-3px,-2px);filter:drop-shadow(0 2px 6px rgba(0,0,0,.55));transition:none}
  .__rip{position:fixed;z-index:2147483646;pointer-events:none;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;border:2px solid #67e8f9;box-shadow:0 0 18px #22d3ee;animation:__rip .65s ease-out forwards}
  @keyframes __rip{from{transform:scale(.25);opacity:1}to{transform:scale(1.6);opacity:0}}
  #__chap{position:fixed;left:50%;top:76px;z-index:2147483640;pointer-events:none;transform:translateX(-50%);display:flex;align-items:center;gap:12px;
    padding:9px 18px;border-radius:999px;background:rgba(6,12,20,.78);backdrop-filter:blur(14px);border:1px solid rgba(103,232,249,.35);
    box-shadow:0 0 0 1px rgba(255,255,255,.03),0 10px 40px rgba(0,0,0,.45),0 0 28px rgba(34,211,238,.18);font-family:Inter,'Segoe UI',sans-serif;opacity:0}
  #__chap.on{animation:__chin .7s cubic-bezier(.2,.8,.2,1) forwards}
  #__chap.off{animation:__chout .45s ease-in forwards}
  #__chap b{font:600 11px 'JetBrains Mono',ui-monospace,monospace;color:#03131a;background:linear-gradient(90deg,#22d3ee,#34d399);border-radius:999px;padding:4px 9px;letter-spacing:.08em}
  #__chap span{font-size:15px;font-weight:600;color:#ecfeff;letter-spacing:.01em}
  #__chap i{font-style:normal;font:500 11px 'JetBrains Mono',ui-monospace,monospace;color:#8fb3c4;letter-spacing:.12em;text-transform:uppercase}
  @keyframes __chin{from{opacity:0;transform:translate(-50%,-12px)}to{opacity:1;transform:translate(-50%,0)}}
  @keyframes __chout{from{opacity:1}to{opacity:0;transform:translate(-50%,-8px)}}
  .__call{position:fixed;z-index:2147483641;pointer-events:none;font-family:Inter,'Segoe UI',sans-serif;opacity:0;animation:__cin .6s cubic-bezier(.2,.8,.2,1) forwards}
  .__call .box{padding:10px 14px;border-radius:12px;background:rgba(6,12,20,.82);backdrop-filter:blur(12px);border:1px solid rgba(251,191,36,.45);box-shadow:0 0 24px rgba(251,191,36,.2)}
  .__call .k{font:600 10px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.14em;text-transform:uppercase;color:#fbbf24}
  .__call .v{font-size:26px;font-weight:700;color:#fff;line-height:1.1;margin-top:3px}
  .__call .s{font-size:12px;color:#a5b8c8;margin-top:2px}
  .__call.cyan .box{border-color:rgba(34,211,238,.5);box-shadow:0 0 24px rgba(34,211,238,.22)} .__call.cyan .k{color:#67e8f9}
  .__call.green .box{border-color:rgba(52,211,153,.5);box-shadow:0 0 24px rgba(52,211,153,.22)} .__call.green .k{color:#6ee7b7}
  .__call.off{animation:__cout .4s ease-in forwards}
  @keyframes __cin{from{opacity:0;transform:translateY(10px) scale(.97)}to{opacity:1;transform:none}}
  @keyframes __cout{from{opacity:1}to{opacity:0}}
  .__ring{position:fixed;z-index:2147483639;pointer-events:none;border:2px solid #fbbf24;border-radius:14px;box-shadow:0 0 22px rgba(251,191,36,.45),inset 0 0 22px rgba(251,191,36,.12);opacity:0;animation:__rin .6s ease-out forwards}
  @keyframes __rin{from{opacity:0;transform:scale(1.06)}to{opacity:1;transform:none}}
  .__ring.off{animation:__cout .4s ease-in forwards}
  \`
  document.head.appendChild(css)
  const cur = document.createElement('div'); cur.id = '__cur'
  cur.innerHTML = '<svg width="26" height="26" viewBox="0 0 26 26"><path d="M3 2 L3 21 L8.2 16.4 L11.6 24 L15 22.5 L11.7 15 L19 15 Z" fill="#fff" stroke="#0b1220" stroke-width="1.4" stroke-linejoin="round"/></svg>'
  document.body.appendChild(cur)
  const chap = document.createElement('div'); chap.id = '__chap'; document.body.appendChild(chap)
  let cx = -100, cy = -100
  const put = () => { cur.style.left = cx + 'px'; cur.style.top = cy + 'px' }
  put()
  window.__ov = {
    cursor(x, y) { cx = x; cy = y; put() },
    hideCursor() { cx = -100; cy = -100; put() },
    ripple(x, y) { const r = document.createElement('div'); r.className = '__rip'; r.style.left = x + 'px'; r.style.top = y + 'px'; document.body.appendChild(r); setTimeout(() => r.remove(), 900) },
    chapter(n, title, sub) { chap.innerHTML = '<span>' + title + '</span>' + (sub ? '<i>' + sub + '</i>' : ''); chap.className = ''; void chap.offsetWidth; chap.className = 'on' },
    chapterOff() { chap.className = 'off' },
    callout(id, x, y, k, v, s, tone) {
      let el = document.getElementById('__c_' + id); if (el) el.remove()
      el = document.createElement('div'); el.id = '__c_' + id; el.className = '__call ' + (tone || '')
      el.style.left = x + 'px'; el.style.top = y + 'px'
      el.innerHTML = '<div class="box"><div class="k">' + k + '</div><div class="v">' + v + '</div>' + (s ? '<div class="s">' + s + '</div>' : '') + '</div>'
      document.body.appendChild(el)
    },
    ring(id, x, y, w, h) { let el = document.getElementById('__r_' + id); if (el) el.remove(); el = document.createElement('div'); el.id = '__r_' + id; el.className = '__ring'; Object.assign(el.style, { left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px' }); document.body.appendChild(el) },
    off(id) { const el = document.getElementById('__c_' + id) || document.getElementById('__r_' + id); if (el) { el.classList.add('off'); setTimeout(() => el.remove(), 500) } },
    clear() { document.querySelectorAll('.__call,.__ring').forEach(e => e.remove()); chap.className = '' },
  }
})()`

export async function launch({ W = 1920, H = 1080, dsf = 1, tag = 'rec' } = {}) {
  const prof = path.resolve('build', 'prof_' + tag)
  fs.rmSync(prof, { recursive: true, force: true })
  const port = 9500 + Math.floor(Math.random() * 400)
  const chrome = spawn(CHROME, ['--headless=new', '--use-angle=d3d11', '--ignore-gpu-blocklist', '--enable-gpu', '--hide-scrollbars', '--mute-audio',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--force-color-profile=srgb',
    `--user-data-dir=${prof}`, `--window-size=${Math.round(W / dsf)},${Math.round(H / dsf)}`, `--remote-debugging-port=${port}`, '--no-first-run', 'about:blank'], { stdio: 'ignore' })
  let targets
  for (let i = 0; i < 60; i++) { try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); if (targets.find(t => t.type === 'page')) break } catch { } await sleep(300) }
  const page = targets.find(t => t.type === 'page')
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise(r => ws.onopen = r)
  let id = 0
  const pend = new Map(), log = [], on = {}
  ws.onmessage = e => {
    const m = JSON.parse(e.data)
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id) }
    else if (m.method && on[m.method]) on[m.method](m.params)
    else if (m.method === 'Runtime.exceptionThrown') log.push('EXC ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text).slice(0, 300))
    else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') log.push('ERR ' + m.params.args.map(a => a.value || a.description).join(' ').slice(0, 300))
  }
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
  await send('Runtime.enable'); await send('Page.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: Math.round(W / dsf), height: Math.round(H / dsf), deviceScaleFactor: dsf, mobile: false })
  await send('Page.addScriptToEvaluateOnNewDocument', { source: VIRTUAL_TIME })
  return new Rec({ chrome, ws, send, log, on, W, H, dsf })
}

class Rec {
  constructor(o) { Object.assign(this, o); this.ff = null; this.frames = 0; this.mouse = [this.W / this.dsf / 2, this.H / this.dsf / 2] }

  async eval(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
    if (r.result?.exceptionDetails) throw new Error('eval failed: ' + (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text) + '\n  in: ' + expr.slice(0, 200))
    return r.result?.result?.value
  }
  async goto(url, ready, timeout = 90000) {
    await this.send('Page.navigate', { url })
    await sleep(800)
    await this.waitFor(`document.readyState === 'complete'`, 30000)
    await this.eval(OVERLAY)
    if (ready) await this.waitFor(ready, timeout)
  }
  async waitFor(expr, timeout = 60000, every = 250) {
    const t0 = Date.now()
    for (;;) {
      let ok = false
      try { ok = await this.eval(`(() => { try { return !!(${expr}) } catch (e) { return false } })()`) } catch { }
      if (ok) return true
      if (Date.now() - t0 > timeout) throw new Error('timed out waiting for: ' + expr)
      await sleep(every)
    }
  }
  /* real time passes (loading, network); nothing is recorded */
  async settle(ms) { await this.eval('__vt.setFree(true)'); await sleep(ms) }

  start(file) {
    fs.mkdirSync(path.dirname(file), { recursive: true })
    this.ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
      '-vf', `scale=${this.W}:${this.H}:flags=lanczos,format=yuv420p`, '-c:v', 'libx264', '-preset', 'medium', '-crf', '12', '-r', String(FPS), file], { stdio: ['pipe', 'inherit', 'inherit'] })
    this.ffDone = new Promise(r => this.ff.on('close', r))
    this.frames = 0
    this.file = file
    return this.eval('__vt.setFree(false)')
  }
  async stop() {
    this.ff.stdin.end(); await this.ffDone; this.ff = null
    await this.eval('__vt.setFree(true)')
    return this.frames / FPS
  }
  get t() { return this.frames / FPS }
  /* one video frame: advance page time by 1/30 s, then grab the screen */
  async frame() {
    await this.eval(`__vt.frame(${1000 / FPS})`)
    const r = await this.send('Page.captureScreenshot', { format: 'jpeg', quality: 94, optimizeForSpeed: true })
    const buf = Buffer.from(r.result.data, 'base64')
    if (!this.ff.stdin.write(buf)) await new Promise(res => this.ff.stdin.once('drain', res))
    this.frames++
  }
  /* real time passes but page time does not: the page keeps drawing (tiles stream in), nothing is recorded */
  async warmUntil(expr, minSec = 0, maxSec = 60) {
    const t0 = Date.now()
    for (;;) {
      await this.eval(`__vt.frame(0)`)
      const el = (Date.now() - t0) / 1000
      if (el >= minSec && (!expr || await this.eval(`(() => { try { return !!(${expr}) } catch (e) { return false } })()`))) return true
      if (el > maxSec) return false
    }
  }
  async hold(sec, each) { const n = Math.round(sec * FPS); for (let i = 0; i < n; i++) { if (each) await each(i / n, i); await this.frame() } }
  /* record until a condition holds in the page (for things that take real time, such as a fetch) */
  async holdUntil(expr, maxSec = 20) { const n = maxSec * FPS; for (let i = 0; i < n; i++) { if (await this.eval(`(() => { try { return !!(${expr}) } catch (e) { return false } })()`)) return true; await this.frame() } return false }

  /* ---------- pointer ---------- */
  async rect(sel, text) {
    const r = await this.eval(`(() => { const els = [...document.querySelectorAll(${JSON.stringify(sel)})].filter(e => e.offsetParent !== null || e.getClientRects().length)
      const el = ${text ? `els.find(e => e.textContent.trim().toLowerCase().includes(${JSON.stringify((text || '').toLowerCase())}))` : 'els[0]'}
      if (!el) return null; el.scrollIntoView({ block: 'nearest' }); const b = el.getBoundingClientRect(); return [b.left, b.top, b.width, b.height] })()`)
    if (!r) throw new Error(`no element ${sel} ${text || ''}`)
    return r
  }
  async moveTo(x, y, sec = .7) {
    const [x0, y0] = this.mouse, n = Math.max(1, Math.round(sec * FPS))
    const bend = (Math.hypot(x - x0, y - y0) * .12) * (x > x0 ? 1 : -1)
    for (let i = 1; i <= n; i++) {
      const k = i / n, e = k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2
      const px = x0 + (x - x0) * e, py = y0 + (y - y0) * e - Math.sin(Math.PI * e) * bend
      await this.eval(`__ov.cursor(${px},${py})`)
      if (i % 3 === 0 || i === n) await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: px, y: py })
      await this.frame()
    }
    this.mouse = [x, y]
  }
  async clickAt(x, y, sec = .7) {
    await this.moveTo(x, y, sec)
    await this.eval(`__ov.ripple(${x},${y})`)
    await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 })
    await this.frame()
    await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 })
    await this.frame()
  }
  async click(sel, text, sec = .7, dx = .5, dy = .5) { const [l, t, w, h] = await this.rect(sel, text); await this.clickAt(l + w * dx, t + h * dy, sec) }
  async type(text, cps = 14) {
    for (const ch of text) { await this.send('Input.insertText', { text: ch }); await this.hold(1 / cps) }
  }
  async key(k, code = k, vk = 13) {
    await this.send('Input.dispatchKeyEvent', { type: 'keyDown', key: k, code, windowsVirtualKeyCode: vk })
    await this.send('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code, windowsVirtualKeyCode: vk })
  }
  /* the next file chooser the page opens gets these files (absolute paths), as if the user picked them */
  async chooseFiles(files) {
    await this.send('Page.setInterceptFileChooserDialog', { enabled: true })
    this.on['Page.fileChooserOpened'] = async p => {
      delete this.on['Page.fileChooserOpened']
      await this.send('DOM.setFileInputFiles', { files, backendNodeId: p.backendNodeId })
      await this.send('Page.setInterceptFileChooserDialog', { enabled: false })
    }
  }
  async close() { try { this.ws.close() } catch { } this.chrome.kill() }
}
