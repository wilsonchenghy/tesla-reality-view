// fonts.js: load vendored fonts (runtime/fonts/fonts.json) before the first frame.
// Add more with: node tools/fetch-font.mjs "<Google Font family>" "<axes>"
const base = new URL('./fonts/', import.meta.url);
let registry = null;

export async function loadFonts(families = []) {
  if (!families.length) return;
  registry ||= await (await fetch(new URL('fonts.json', base))).json();
  const loads = [];
  for (const fam of families) {
    const faces = registry[fam];
    if (!faces) { console.warn(`rv: font "${fam}" is not vendored. Run: node tools/fetch-font.mjs "${fam}"`); continue; }
    for (const f of faces) {
      const ff = new FontFace(fam, `url(${new URL(f.file, base)}) format('woff2')`, { style: f.style, weight: f.weight, ...(f.stretch ? { stretch: f.stretch } : {}), display: 'block' });
      loads.push(ff.load().then((x) => document.fonts.add(x)));
    }
  }
  await Promise.all(loads);
  await document.fonts.ready;
}
export const vendoredFonts = async () => Object.keys(registry ||= await (await fetch(new URL('fonts.json', base))).json());
