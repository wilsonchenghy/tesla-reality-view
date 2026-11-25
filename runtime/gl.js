// gl.js: a full-screen fragment shader stage. Choreography lives in JS (springs, cues); the shader only
// draws what the uniforms say, so every frame stays a pure function of t.
//
//   const fx = shader(stage, FRAG, { uniforms: { uBlob: [0,0,0,0.6] } });
//   render(t) { fx.draw({ uT: t, uBlob: [...] }); }
//
// FRAG is GLSL ES 3.00 without the #version line; it gets `uniform vec2 uRes;` and `out vec4 o;`.
export function shader(stage, frag, { dpr = stage.dpr, scale = 1 } = {}) {
  const c = stage.canvas({ dpr: dpr * scale });
  const gl = c.getContext('webgl2', { preserveDrawingBuffer: true, antialias: false, premultipliedAlpha: false });
  if (!gl) throw new Error('WebGL2 unavailable');
  const src = (type, s) => {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, s); gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(sh);
      const lines = s.split('\n').map((l, i) => `${String(i + 1).padStart(4)} ${l}`);
      const m = /0:(\d+)/.exec(log); const at = m ? +m[1] : 0;
      throw new Error('shader compile error:\n' + log + '\n' + lines.slice(Math.max(0, at - 4), at + 2).join('\n'));
    }
    return sh;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, src(gl.VERTEX_SHADER, '#version 300 es\nin vec2 p;void main(){gl_Position=vec4(p,0.,1.);}'));
  gl.attachShader(prog, src(gl.FRAGMENT_SHADER, '#version 300 es\nprecision highp float;\nuniform vec2 uRes;\nout vec4 o;\n' + frag));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'p');
  gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const locs = {};
  const n = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < n; i++) { const u = gl.getActiveUniform(prog, i); locs[u.name.replace(/\[0\]$/, '')] = { loc: gl.getUniformLocation(prog, u.name), type: u.type, size: u.size }; }
  const set = (name, v) => {
    const u = locs[name]; if (!u) return;
    const a = typeof v === 'number' ? [v] : v.flat ? v.flat(2) : v;
    switch (u.type) {
      case gl.FLOAT: gl.uniform1fv(u.loc, a); break;
      case gl.FLOAT_VEC2: gl.uniform2fv(u.loc, a); break;
      case gl.FLOAT_VEC3: gl.uniform3fv(u.loc, a); break;
      case gl.FLOAT_VEC4: gl.uniform4fv(u.loc, a); break;
      case gl.INT: case gl.BOOL: gl.uniform1iv(u.loc, a.map((x) => x | 0)); break;
      case gl.FLOAT_MAT3: gl.uniformMatrix3fv(u.loc, false, a); break;
      case gl.FLOAT_MAT4: gl.uniformMatrix4fv(u.loc, false, a); break;
    }
  };
  return {
    gl, canvas: c, uniforms: locs,
    draw(uniforms = {}) {
      gl.viewport(0, 0, c.width, c.height);
      set('uRes', [c.width, c.height]);
      for (const k in uniforms) set(k, uniforms[k]);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.finish();
    },
  };
}
