// node preview.mjs [models...] : renders previews/<m>_<view>.png with three.js in headless Chromium, prints the
// three.js-side report (bbox, part centroids) so loading in the real scene library is checked too
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';
const here = new URL('.', import.meta.url).pathname;
const models = process.argv.slice(2).length ? process.argv.slice(2) : ['ego', 'sedan', 'suv', 'pickup', 'boxtruck'];
const views = (process.env.VIEWS || 'rear34,side').split(',');
const port = 8765 + Math.floor(Math.random() * 200);
const srv = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1'], { cwd: '/', stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 800));
const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const page = await b.newPage({ viewport: { width: 1200, height: 750 } });
const out = {};
try {
  for (const m of models) for (const v of views) {
    await page.goto(`http://127.0.0.1:${port}${here}preview.html?m=${m}&v=${v}`);
    await page.waitForFunction(() => window.__done, null, { timeout: 120000 });
    out[m] = await page.evaluate(() => window.__report);
    await page.screenshot({ path: `${here}previews/${m}_${v}.png` });
  }
} finally { await b.close(); srv.kill(); }
writeFileSync(`${here}previews/report.json`, JSON.stringify(out, null, 1));
for (const [m, r] of Object.entries(out)) console.log(m, JSON.stringify({ size: r.size?.map((x) => +x.toFixed(3)), min: r.bbox_min?.map((x) => +x.toFixed(3)), err: r.error,
  front_z: r.parts?.light_front?.center[2], rear_z: r.parts?.light_rear?.center[2] }));
