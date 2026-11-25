// Dump the piece's chase camera for every frame (world frame of the splats) -> out/reality-data/chase_cams.json
// usage: node pieces/reality/prep/camdump.mjs     (plate mode: no HUD/cars, splats skipped for speed)
import { writeFile } from 'node:fs/promises';
import { open } from '../../../harness/session.mjs';
const s = await open('reality', { quiet: true, query: '&plate&nosplat' });
const cams = [];
for (let f = 0; f < s.info.frames; f++) {
  const t = f / s.info.fps;
  await s.page.evaluate(`window.rv.seek(${t}, ${t})`);
  cams.push(await s.page.evaluate('window.__cam'));
}
await writeFile('out/reality-data/chase_cams.json', JSON.stringify(cams));
console.log('cameras', cams.length);
await s.close(); process.exit(0);
