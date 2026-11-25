// browser.mjs: headless Chromium over the DevTools protocol, no npm dependencies (Node 22 WebSocket).
import { spawn } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir, homedir } from 'node:os';
import path from 'node:path';

export function findChrome() {
  if (process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH)) return process.env.CHROME_PATH;
  // Prefer Playwright's headless shell: no auto-updater that can kill long renders.
  const caches = [process.env.PLAYWRIGHT_BROWSERS_PATH, '/opt/pw-browsers', path.join(homedir(), '.cache/ms-playwright'), path.join(homedir(), 'Library/Caches/ms-playwright'), path.join(homedir(), 'AppData/Local/ms-playwright')].filter(Boolean);
  const rel = [
    ['chromium_headless_shell-', ['chrome-linux/headless_shell', 'chrome-headless-shell-linux64/chrome-headless-shell', 'chrome-headless-shell-mac-arm64/chrome-headless-shell', 'chrome-headless-shell-mac-x64/chrome-headless-shell', 'chrome-headless-shell-win64/chrome-headless-shell.exe']],
    ['chromium-', ['chrome-linux/chrome', 'chrome-mac/Chromium.app/Contents/MacOS/Chromium', 'chrome-win/chrome.exe']],
  ];
  for (const [prefix, bins] of rel) for (const c of caches) {
    let dirs = [];
    try { dirs = readdirSync(c).filter((d) => d.startsWith(prefix)).sort().reverse(); } catch {}
    for (const d of dirs) for (const b of bins) { const p = path.join(c, d, b); if (existsSync(p)) return p; }
  }
  const sys = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome', 'C:/Program Files/Google/Chrome/Application/chrome.exe'];
  return sys.find((p) => existsSync(p)) || 'chromium';
}

// every browser this process launched; killed if the CLI is interrupted, so renders never orphan Chromium
const live = new Set();
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(sig, () => { for (const p of live) { try { p.kill('SIGKILL'); } catch {} } process.exit(130); });
process.on('exit', () => { for (const p of live) { try { p.kill('SIGKILL'); } catch {} } });

export async function launch({ gpu = false, verbose = false } = {}) {
  const bin = findChrome();
  const userDir = await mkdtemp(path.join(tmpdir(), 'rv-chrome-'));
  const shell = /headless[_-]shell/.test(bin);
  const args = [
    ...(shell ? [] : ['--headless=new']),
    '--remote-debugging-port=0', `--user-data-dir=${userDir}`,
    '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-default-apps',
    '--disable-features=Translate,OptimizationHints,MediaRouter,BackForwardCache', '--no-service-autorun', '--disable-crash-reporter',
    '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--mute-audio', '--no-sandbox',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows',
    '--autoplay-policy=no-user-gesture-required', '--font-render-hinting=none', '--force-color-profile=srgb',
    ...(gpu ? ['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=default'] : ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']),
    'about:blank',
  ];
  const proc = spawn(bin, args, { stdio: ['ignore', 'ignore', 'pipe'] });
  live.add(proc);
  proc.on('exit', () => live.delete(proc));
  let errTail = '';
  const wsUrl = await new Promise((resolve, reject) => {
    proc.stderr.on('data', (d) => {
      errTail = (errTail + d).slice(-6000);
      const m = errTail.match(/DevTools listening on (ws:\/\/\S+)/);
      if (m) resolve(m[1]);
    });
    proc.once('exit', (c) => reject(new Error(`chrome exited ${c}\n${errTail}`)));
    setTimeout(() => reject(new Error('chrome did not start in 20s\n' + errTail)), 20000);
  });
  if (verbose) proc.stderr.on('data', (d) => process.stderr.write(d));
  const conn = await connect(wsUrl);
  let closing = false;
  proc.on('exit', (code, sig) => { if (!closing) { console.error(`\n[rv] chrome exited unexpectedly (code ${code}, signal ${sig})\n${errTail}`); process.exit(2); } });
  return {
    conn, bin,
    async newPage(opts) { return openPage(conn, opts); },
    async close() { closing = true; try { conn.close(); } catch {} proc.kill('SIGKILL'); await rm(userDir, { recursive: true, force: true }).catch(() => {}); },
  };
}

async function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 0;
  const pending = new Map(), listeners = new Set();
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const { res, rej } = pending.get(m.id); pending.delete(m.id); m.error ? rej(new Error(m.error.message)) : res(m.result); }
    else if (m.method) for (const l of listeners) l(m);
  };
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  return {
    send: (method, params = {}, sessionId) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params, sessionId })); }),
    on: (f) => { listeners.add(f); return () => listeners.delete(f); },
    close: () => ws.close(),
  };
}

async function openPage(conn, { width = 1080, height = 1080, scale = 1, onConsole = null } = {}) {
  const { targetId } = await conn.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await conn.send('Target.attachToTarget', { targetId, flatten: true });
  const S = (m, p) => conn.send(m, p, sessionId);
  const errors = [], logs = [], requests = [];
  conn.on((m) => {
    if (m.sessionId !== sessionId) return;
    if (m.method === 'Runtime.consoleAPICalled') {
      const text = m.params.args.map((a) => a.value ?? a.description).join(' ');
      logs.push({ type: m.params.type, text });
      if (onConsole) onConsole(m.params.type, text);
    }
    if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.method === 'Network.requestWillBeSent') requests.push(m.params.request.url);
    if (m.method === 'Network.loadingFailed' && !m.params.canceled) errors.push('network: ' + m.params.errorText + ' ' + (m.params.blockedReason || ''));
  });
  await S('Runtime.enable');
  await S('Page.enable');
  await S('Network.enable');
  await S('Network.setCacheDisabled', { cacheDisabled: true });
  await S('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: scale, mobile: false });
  await S('Emulation.setDefaultBackgroundColorOverride', { color: { r: 0, g: 0, b: 0, a: 1 } });
  const evaluate = async (expression) => {
    const r = await S('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  return {
    S, evaluate, errors, logs, requests,
    async goto(url) {
      const loaded = new Promise((res) => { const off = conn.on((m) => { if (m.sessionId === sessionId && m.method === 'Page.loadEventFired') { off(); res(); } }); });
      await S('Page.navigate', { url });
      await loaded;
    },
    async screenshot({ format = 'png', quality } = {}) {
      const r = await S('Page.captureScreenshot', { format, ...(quality ? { quality } : {}), optimizeForSpeed: true, fromSurface: true, captureBeyondViewport: false });
      return Buffer.from(r.data, 'base64');
    },
  };
}
