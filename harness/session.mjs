// session.mjs: serve the repo, open a piece in headless Chromium, wait until it is ready.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { launch } from './browser.mjs';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.otf': 'font/otf', '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json', '.hdr': 'application/octet-stream', '.glsl': 'text/plain', '.txt': 'text/plain', '.mp4': 'video/mp4' };

let server = null;
export async function serve(port = 0) {
  if (server) return server;
  server = createServer(async (req, res) => {
    try {
      const u = new URL(req.url, 'http://x');
      let p = path.join(ROOT, decodeURIComponent(u.pathname));
      if (!p.startsWith(ROOT)) { res.writeHead(403).end(); return; }
      if ((await stat(p).catch(() => null))?.isDirectory()) p = path.join(p, 'index.html');
      const body = await readFile(p);
      res.writeHead(200, { 'content-type': MIME[path.extname(p).toLowerCase()] || 'application/octet-stream', 'cache-control': 'no-store', 'access-control-allow-origin': '*' });
      res.end(body);
    } catch { res.writeHead(404).end(); }
  });
  await new Promise((r) => server.listen(port, '127.0.0.1', r));
  server.unref();
  server.base = `http://127.0.0.1:${server.address().port}`;
  return server;
}

// Resolve "morph", "pieces/morph", "pieces/morph/index.html" -> { dir, html, url path, name }
export function resolvePiece(arg) {
  if (!arg) throw new Error('which piece? e.g. rv render pieces/morph');
  const cands = [arg, path.join('pieces', arg)].map((a) => path.resolve(a));
  for (let c of cands) {
    if (existsSync(c) && !c.endsWith('.html')) c = path.join(c, 'index.html');
    if (existsSync(c)) {
      if (!c.startsWith(ROOT)) throw new Error(`pieces must live inside the rv repo (${ROOT}) so they can import runtime/`);
      const dir = path.dirname(c);
      return { dir, html: c, urlPath: '/' + path.relative(ROOT, c).split(path.sep).join('/'), name: path.basename(dir) };
    }
  }
  throw new Error(`piece not found: ${arg}`);
}

export const outDir = (name) => path.join(ROOT, 'out', name);

// Open a piece; returns { browser, page, info, close }
export async function open(pieceArg, { scale = 1, gpu = false, browser = null, quiet = false, query = '' } = {}) {
  const pc = resolvePiece(pieceArg);
  const srv = await serve();
  const own = !browser;
  browser ||= await launch({ gpu });
  // first open at a guess size, then resize to the piece's real size
  const page = await browser.newPage({ width: 1080, height: 1080, scale, onConsole: quiet ? null : (type, text) => { if (type === 'error' || type === 'warning' || type === 'warn') console.log(`[page ${type}]`, text); } });
  await page.goto(`${srv.base}${pc.urlPath}?render=1${query}`);
  const t0 = Date.now();
  while (!(await page.evaluate('!!window.rv').catch(() => false))) {
    if (Date.now() - t0 > 20000) throw new Error('piece never defined window.rv (did it call piece({...})?)\n' + page.errors.join('\n'));
    await new Promise((r) => setTimeout(r, 50));
  }
  await page.evaluate('window.rv.ready');
  const info = await page.evaluate('window.rv.info()');
  await page.S('Emulation.setDeviceMetricsOverride', { width: info.width, height: info.height, deviceScaleFactor: scale, mobile: false });
  await page.evaluate('window.rv.seek(0)');
  if (page.errors.length && !quiet) console.log('[rv] page errors:\n  ' + page.errors.join('\n  '));
  return { piece: pc, browser, page, info, close: async () => { if (own) await browser.close(); } };
}
