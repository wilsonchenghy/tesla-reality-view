#!/usr/bin/env node
// Vendor a Google Font (latin subset, woff2, variable axes when available) into runtime/fonts/
// and register it in runtime/fonts/fonts.json, so renders never touch the network.
//   node tools/fetch-font.mjs "Instrument Serif" "ital@0;1"
//   node tools/fetch-font.mjs "Archivo" "wdth,wght@62..125,100..900"
import { writeFile, readFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dir = path.join(root, 'runtime', 'fonts');
const [family, axes] = process.argv.slice(2);
if (!family) { console.error('usage: fetch-font.mjs "<Family>" ["axes spec"]'); process.exit(1); }
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';
const url = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(family).replace(/%20/g, '+')}${axes ? ':' + axes : ''}&display=block`;
const cssText = await (await fetch(url, { headers: { 'user-agent': UA } })).text();
if (!cssText.includes('@font-face')) { console.error('no font-face for', url, '\n', cssText.slice(0, 300)); process.exit(1); }
await mkdir(dir, { recursive: true });
const regPath = path.join(dir, 'fonts.json');
let reg = {};
try { reg = JSON.parse(await readFile(regPath, 'utf8')); } catch {}
const faces = [];
for (const block of cssText.split('@font-face').slice(1)) {
  if (!/\/\* latin \*\//.test(cssText) || block.includes('U+0000-00FF') || !cssText.includes('/* latin */')) {
    const src = block.match(/url\((https:[^)]+\.woff2)\)/)?.[1];
    if (!src) continue;
    const style = block.match(/font-style:\s*(\w+)/)?.[1] || 'normal';
    const weight = block.match(/font-weight:\s*([\d ]+)/)?.[1].trim() || '400';
    const stretch = block.match(/font-stretch:\s*([\d% ]+)/)?.[1].trim();
    const file = `${family.replace(/\s+/g, '')}-${style}-${weight.replace(' ', '_')}.woff2`;
    const buf = Buffer.from(await (await fetch(src)).arrayBuffer());
    await writeFile(path.join(dir, file), buf);
    faces.push({ file, style, weight, ...(stretch ? { stretch } : {}) });
    console.log('saved', file, (buf.length / 1024).toFixed(0) + ' KB');
  }
}
reg[family] = faces;
await writeFile(regPath, JSON.stringify(reg, null, 2) + '\n');
