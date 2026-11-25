#!/usr/bin/env node
// rv: the motion design harness CLI. Run `rv help`.
import { parseArgs } from '../harness/args.mjs';
const [cmd, ...rest] = process.argv.slice(2);
const { pos, opt } = parseArgs(rest);
const commands = {
  render: async () => (await import('../harness/render.mjs')).render(pos[0], opt),
  stills: async () => (await import('../harness/qa.mjs')).stills(pos[0], opt),
  sheet: async () => (await import('../harness/qa.mjs')).sheet(pos[0], opt),
  beats: async () => (await import('../harness/qa.mjs')).beatSheet(pos[0], opt),
  onion: async () => (await import('../harness/qa.mjs')).onion(pos[0], opt),
  trace: async () => (await import('../harness/qa.mjs')).trace(pos[0], opt),
  motion: async () => (await import('../harness/qa.mjs')).motion(pos[0], opt),
  taste: async () => (await import('../harness/qa.mjs')).taste(pos[0], opt),
  plan: async () => (await import('../harness/qa.mjs')).plan(pos[0], opt),
  review: async () => (await import('../harness/qa.mjs')).review(pos[0], opt),
  check: async () => (await import('../harness/qa.mjs')).check(pos[0], opt),
  audio: async () => (await import('../harness/qa.mjs')).audio(pos[0], opt),
  study: async () => (await import('../harness/qa.mjs')).study(pos[0], opt),
  compare: async () => (await import('../harness/qa.mjs')).compare(pos[0], pos[1], opt),
  analyze: async () => (await import('../harness/qa.mjs')).analyzeSong(pos[0], opt),
  gif: async () => (await import('../harness/render.mjs')).toGif(pos[0], pos[1] || pos[0].replace(/\.mp4$/, '.gif'), { width: +opt.width || 960, fps: +opt.fps || 30 }),
  share: async () => (await import('../harness/render.mjs')).share(pos[0], { maxMb: opt.maxMb || 25, out: pos[1] }),
  new: async () => (await import('../harness/scaffold.mjs')).scaffold(pos[0], opt),
  preview: async () => (await import('../harness/qa.mjs')).preview(pos[0], opt),
  list: async () => (await import('../harness/scaffold.mjs')).list(),
  help: async () => console.log((await import('node:fs')).readFileSync(new URL('../harness/help.txt', import.meta.url), 'utf8')),
};
const run = commands[cmd] || commands.help;
try { await run(); process.exit(0); } catch (e) { console.error('[rv]', e.message || e); if (process.env.RV_DEBUG) console.error(e.stack); process.exit(1); }
