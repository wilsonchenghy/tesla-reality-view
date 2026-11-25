// --flag value, --flag (true), --no-flag (false), --kebab-case -> camelCase
export function parseArgs(argv) {
  const pos = [], opt = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) { pos.push(a); continue; }
    let k = a.slice(2), v = true;
    if (k.includes('=')) [k, v] = [k.slice(0, k.indexOf('=')), k.slice(k.indexOf('=') + 1)];
    else if (argv[i + 1] !== undefined && !argv[i + 1].startsWith('--')) v = argv[++i];
    if (k.startsWith('no-')) { k = k.slice(3); v = false; }
    opt[k.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
  }
  return { pos, opt };
}
