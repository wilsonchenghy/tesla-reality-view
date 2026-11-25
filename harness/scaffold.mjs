// scaffold: rv new <name> [--template dom|canvas|three]; rv list
import { mkdir, readFile, writeFile, readdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { ROOT } from './session.mjs';

export async function scaffold(name, o = {}) {
  if (!name || !/^[a-z0-9][a-z0-9-_]*$/i.test(name)) throw new Error('usage: rv new <name> [--template dom|canvas|three|song] [--size 1080x1920] [--no-loop]');
  const tpl = o.template || 'dom';
  const src = path.join(ROOT, 'templates', tpl, 'index.html');
  if (!existsSync(src)) throw new Error(`no template "${tpl}" (have: ${(await readdir(path.join(ROOT, 'templates'))).join(', ')})`);
  const dir = path.join(ROOT, 'pieces', name);
  if (existsSync(dir)) throw new Error(`pieces/${name} already exists`);
  await mkdir(dir, { recursive: true });
  // --size 1080x1920 (vertical), --no-loop (launch teasers, end cards)
  const [w, h] = String(o.size || '1080x1080').split('x').map(Number);
  let html = (await readFile(src, 'utf8')).replaceAll('__NAME__', name);
  html = html.replace(/const W = 1080, H = 1080/, `const W = ${w}, H = ${h}`).replace(/width: 1080, height: 1080/, `width: ${w}, height: ${h}`);
  if (o.loop === false) html = html.replace(/loop: true/, 'loop: false, holds: [] /* e.g. [[T - 1.5, T]] for an end card */');
  await writeFile(path.join(dir, 'index.html'), html);
  await writeFile(path.join(dir, 'BRIEF.md'), `# ${name}

## Divergence (open briefs: three concepts that differ on 3+ axes, docs/creativity.md section 1)
A:
B:
C:
Picked:      because:

## Brief
GOAL:     what the viewer should feel or do, one sentence
CONCEPT:  the one signature move
OUTPUT:   ${tpl}, ${w}x${h}${o.loop === false ? ', no loop (end card)' : ', loop'}
TIME:     seconds x fps = frames, BPM, loop yes/no
LOOK:     palette in hex with roles, one accent, typeface + weight + size + tracking
MOTION:   easings by token, springs as zeta/freq, durations in frames
SHOTS:    beat ranges, one hero move each, how each hands off
SOUND:    bed + hits, which event gets which sound
BANNED:   the defaults you will not use
QA:       the frames you will check
`);
  console.log(`pieces/${name}/index.html  (template: ${tpl})\npieces/${name}/BRIEF.md   fill this in before writing motion\nnext: rv check ${name} && rv beats ${name}`);
}

export async function list() {
  for (const d of (await readdir(path.join(ROOT, 'pieces'))).sort()) if (existsSync(path.join(ROOT, 'pieces', d, 'index.html'))) console.log(d);
}
