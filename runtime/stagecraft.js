// stagecraft.js: reusable pieces of direction: presence (enter/exit with blur), a 2D camera, a cursor
// that clicks and drags, mask wipes. All pure functions of t.
import { clamp, ease, smoothstep, springTrack, loopTrack } from './motion.js';
import { el, set, svg, attrs } from './draw.js';

// ---------- presence: how visible a state is, with its own enter and exit ----------
// Exit finishes before enter is legible, so two contents in one container never overlap.
// period: pass the loop length so a window that wraps the seam works.
export function presence(t, tin, tout, { enterDelay = 0.08, enterDur = 0.26, exitLead = 0.06, exitDur = 0.1, period = 0 } = {}) {
  const one = (tt) => {
    const enter = ease.outCubic(clamp((tt - tin - enterDelay) / enterDur));
    const exit = 1 - ease.inCubic(clamp((tt - tout + exitLead) / exitDur));
    return Math.min(enter, exit);
  };
  return period ? Math.max(one(t), one(t + period), one(t - period)) : one(t);
}
// style for a presence value: opacity + blur + slight scale (the blur swap)
export const presenceStyle = (v, { blur = 7, scale = 0.06 } = {}) => ({
  opacity: v.toFixed(3),
  filter: v > 0.995 ? 'none' : `blur(${((1 - v) * blur).toFixed(2)}px)`,
  transform: `scale(${(1 - scale + scale * v).toFixed(4)})`,
  display: v < 0.002 ? 'none' : 'block',
});

// ---------- camera ----------
// A 2D camera over a world layer whose origin is the stage centre. Never put will-change on it.
//   const cam = camera(stage);  cam.set({ zoom, x, y, rotate });  cam.toScreen([wx, wy])
export function camera(stage, { origin = [stage.W / 2, stage.H / 2] } = {}) {
  const world = el('div', { left: origin[0], top: origin[1], width: 0, height: 0 }, stage);
  let cur = { zoom: 1, x: 0, y: 0, rotate: 0 };
  return {
    world,
    set(c) {
      cur = { ...cur, ...c };
      set(world, { transform: `rotate(${cur.rotate.toFixed(4)}deg) scale(${cur.zoom.toFixed(5)}) translate(${(-cur.x).toFixed(3)}px, ${(-cur.y).toFixed(3)}px)` });
    },
    toScreen([wx, wy]) {
      const a = (cur.rotate * Math.PI) / 180, x = (wx - cur.x) * cur.zoom, y = (wy - cur.y) * cur.zoom;
      return [origin[0] + x * Math.cos(a) - y * Math.sin(a), origin[1] + x * Math.sin(a) + y * Math.cos(a)];
    },
    get state() { return cur; },
  };
}
// zoom that makes a w x h box fill `fill` of the frame
export const fitZoom = (W, H, w, h, fill = 0.7, max = 3) => Math.min((fill * W) / w, (fill * H) / h, max);

// ---------- cursor ----------
// A macOS-style pointer that lives in screen space. Path: [[t, [x, y]], ...] in any space you map.
// clicks: [t, ...]; drags: [[tDown, tUp], ...]. press(t) is 0..1 (1 = held down).
export function cursorRig(stage, { path, clicks = [], drags = [], period = 0, spring = { zeta: 0.86, freq: 1.9 }, size = 1.25, color = '#0E0E0E', outline = '#FFFFFF' } = {}) {
  const pos = period ? loopTrack(path, period, spring) : springTrack(path, spring);
  const node = svg(stage, 40, 40);
  node.setAttribute('viewBox', '0 0 40 40');
  attrs(el('svg:path', {}, node), { d: 'M9 5.5v25.5l7.2-6.6 4.6 10.4 4.4-1.9-4.6-10.2 9.8-.6z', fill: color, stroke: outline, 'stroke-width': 2.2, 'stroke-linejoin': 'round' });
  node.style.zIndex = 50;
  const press = (t) => {
    let p = 0;
    const ts = (x) => (period ? [x, x - period, x + period] : [x]);
    for (const c of clicks) for (const tc of ts(c)) p = Math.max(p, smoothstep(tc - 0.08, tc - 0.01, t) * (1 - smoothstep(tc + 0.04, tc + 0.14, t)));
    for (const [a, z] of drags) for (const o of period ? [0, -period, period] : [0]) p = Math.max(p, smoothstep(a + o - 0.08, a + o - 0.01, t) * (1 - smoothstep(z + o + 0.02, z + o + 0.12, t)));
    return p;
  };
  return {
    node, pos, press,
    // draw at screen point (map world -> screen yourself, e.g. with camera.toScreen)
    draw(t, toScreen = (p) => p) {
      const [sx, sy] = toScreen(pos(t));
      const s = size * (1 - 0.14 * press(t));
      set(node, { left: sx - 9, top: sy - 5, transform: `scale(${s.toFixed(4)})`, transformOrigin: '9px 5px' });
    },
  };
}

// ---------- masks ----------
// CSS clip-path values for wipes; u: 0 hidden -> 1 shown.
export const wipe = {
  circle: (u, cx = '50%', cy = '50%', max = 150) => `circle(${(u * max).toFixed(3)}% at ${cx} ${cy})`,
  left: (u) => `inset(0 ${(100 - u * 100).toFixed(3)}% 0 0)`,
  right: (u) => `inset(0 0 0 ${(100 - u * 100).toFixed(3)}%)`,
  up: (u) => `inset(${(100 - u * 100).toFixed(3)}% 0 0 0)`,
  down: (u) => `inset(0 0 ${(100 - u * 100).toFixed(3)}% 0)`,
  diagonal: (u, angle = 20) => { const k = Math.tan((angle * Math.PI) / 180) * 100, x = -k + u * (100 + 2 * k); return `polygon(0 0, ${(x + k).toFixed(2)}% 0, ${(x - k).toFixed(2)}% 100%, 0 100%)`; },
  blinds: (u, n = 8) => `polygon(${Array.from({ length: n }, (_, i) => { const y0 = (i / n) * 100, y1 = y0 + (u * 100) / n; return `0 ${y0}%, 100% ${y0}%, 100% ${y1}%, 0 ${y1}%`; }).join(', ')})`,
};
