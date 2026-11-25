# Creativity: how to make pieces that do not look like each other

The harness removes every technical reason for a piece to look generic. What is left is the
decisions. A model left alone decides the same way every time: centered text, a dark gradient, a
glow, everything fading up from below, a soft sine wobble. That is the default look, and it reads
as "AI made this" from across the room. This file is how you leave it.

The rule under all of it: **every adjective you replace with a number is a decision you take
back from the default.** "Premium" is not a direction. "Satin ceramic F4F1EC, roughness 0.38, one
D97757 accent on the deck only, springs at damping 0.8" is.

## 1. Diverge before you build (mandatory for any open brief)

Before writing code, write **three** concepts that differ on at least three of these axes:

| Axis | Options (not exhaustive) |
| --- | --- |
| Rendering model | DOM/UI, flat vector, line drawing, type only, canvas generative, pixel grid, 2.5D paper layers, 3D studio, raymarched SDF, photographic-feel shader |
| Visual language | see section 3 |
| Structure | one continuous morph, hard cuts on the beat, a single camera move, a loop with no beginning, a story with a turn, a system that builds itself, a reveal |
| Camera | locked off, constant drift, push-ins on hits, top-down, isometric, through-the-object |
| Color | monochrome + one accent, 2-3 spot inks, full palette with roles, black only, inverted per section |
| Sound | percussive UI foley, melodic plucks, one drone + hits, silence + one sound, beat-driven bed |

Each concept: a one-line logline, the **one signature move** (the moment people will remember), a
palette in hex, the typeface, the structure in beats. Then pick the one that is most *specific* to
the subject and least like your last piece. Say which you picked and why. If the user asked for
options, show the three.

**The test of a concept:** could this concept only exist for *this* subject? A showreel concept
that fits any brand is a template. A concept where the product's own behavior *is* the motion
(the button's loader is the clock; the chart line is the cursor's path; the toast's timer drains
into the next button) is a piece.

## 2. The signature move

Every piece needs one move that is its own. Some that have worked, as patterns to invent from, not
to copy:

- **One shape, never cut.** Every state is the same element morphing size, radius and color while
  its content swaps with a blur. (`pieces/morph`)
- **Two edges on different springs.** A pill whose leading edge runs ahead and trailing edge
  catches up reads as liquid. The same trick makes a toggle knob stretch.
- **Direct manipulation.** While the cursor holds, the value is computed from the cursor; on
  release it springs from wherever it was, with the velocity it had (`dragRelease`).
- **Rubber band past the limit.** Overdrag stretches the container, release snaps back (`rubber`).
- **Type as a material.** A variable font's width and weight axes driven by springs, letters
  that squash on landing, a word that pours into a glyph.
- **The object is the explanation.** Don't draw boxes and arrows: invent a real machine whose
  working is the concept (a lock for a cache key, a plotter for a shared context).
- **A system that draws itself.** The chart line is drawn by the thing it measures.
- **Match cut.** The last shape of one idea is the first shape of the next: a circle loader
  becomes a planet becomes a period.
- **Scale jump.** Zoom through a detail into the next scene; the dot on the i is the next world.
- **Constraint as style.** Only circles. Only one line. Only the letter O. Never a cut. Three seconds.

When you write the brief, name the signature move in one sentence. If you cannot, the piece does
not have one yet.

## 3. Visual languages with numbers

Each of these is a starting point with concrete parameters. Combine two (Swiss grid + risograph
inks) for something less expected. Never use one as a costume; use its *principles*.

| Language | Principles in numbers |
| --- | --- |
| Swiss / International | 12-col grid, flush-left ragged-right, one grotesque (Geist / Archivo) at 2-3 sizes in a 1:2.6 ratio, black + one red (#E8402A), asymmetric layouts, motion snaps to grid lines, hard cuts |
| Editorial serif | Instrument Serif or Fraunces at display sizes (120-300 px) with tight leading (0.9), italic for emphasis, warm paper (#F3EFE6), ink (#1B1A17), slow eases (outQuint, 700-900 ms), lots of air |
| Risograph | 2-3 spot inks (fluoro pink #FF48B0, blue #0078BF, yellow #FFE800), multiply blending, 2-4 px misregistration per ink, coarse grain 4-6%, halftone dots, hand-cut shapes |
| Bauhaus / constructivist | primaries (#E63027 #1E4FA0 #F2C230) + black on cream, circles/squares/triangles only, diagonals at 15°/45°, Big Shoulders or Archivo condensed, mechanical linear rotations |
| Product UI (Dribbble-grade) | warm-gray canvas (#E9E7E2), black/white components, one accent, Geist, springs zeta 0.75-0.85, blur swaps 6-8 px, cursor-driven, camera zooms so each state fills the frame |
| Technical / blueprint | navy (#0F2A4A) or white, 1 px lines, Geist Mono labels at 12-14 px, dimension lines, construction circles, draw-on strokes, isometric 30° |
| Brutal terminal | black, one phosphor color, mono type, hard cuts at 1-2 frame precision, no easing on text (typewriter), scanline/grain optional, glitch only as punctuation |
| Kinetic type | one word per beat, variable width 62-125 and weight 100-900 animated on springs, letters staggered 1-2 frames, type fills 70-90% of the frame |
| Paper / 2.5D | flat colors in 4-6 layers, soft long shadows (offset 8-20 px, blur 20-40, 20% ink), parallax 1.0 / 0.5 / 0.2, slight wobble from loop noise |
| 3D studio | one hero object, key/fill/rim with color temperatures, PMREM reflections built in code, 30° lens, camera never parked, materials named by roughness/clearcoat |
| Op art / generative | high-contrast black/white, moiré and interference from 2 overlapping periodic fields, loop noise, every motion periodic in T |
| Pixel | one grid, integer positions only, palette of 8-16, animate on 2s or 3s (holds), no blur, no motion blur (`--sub 1`) |
| Ink / brush | variable-width strokes from pressure noise, wet edges (darker rim), paper texture, draw-on along the stroke, no geometric easing |

## 4. The default look: the ban list (extend it per piece)

Ban by name in every brief, then check the first render for which ones crept in and ban those too:

- purple/blue gradients, glow, bloom on UI, lens flares, neon
- floating particles as decoration (particles are fine when they *are* the subject)
- everything fading in at once; fade-and-slide-up on every element
- centered-everything layouts; text in the dead middle at 48 px
- linear easing on moves; bouncy easing on UI chrome (overshoot ≤ 5%)
- soft sine wobble on everything ("breathing" as filler)
- dark navy space backgrounds with a halo ring
- made-up taglines nobody asked for, lorem ipsum, "Welcome to the future"
- mismatched icon stroke widths; emoji as icons
- dead time: a beat where nothing changes
- text that moves while it is being read

## 5. Composition and hierarchy

- **One hero per moment.** Everything else waits, dims to 40%, or holds still. Secondary moves
  travel 50-70% as far and start 100-200 ms later. Ambient motion stays under 5% of the hero's travel.
- **Scale contrast.** Huge against tiny reads as designed; medium against medium reads as a slide.
  A title at 280 px next to a 14 px mono label is a composition.
- **Negative space is a shape.** Put the subject off-center on a grid line; let the empty side
  carry the motion's direction.
- **Depth:** foreground / midground / background, even in flat work (scale, value, parallax, blur).
- **Frame 0 is a poster.** It is the thumbnail. Make it a finished composition.

## 6. Rhythm

- Cut or change on the beat; change the layout on the bar (every 4 beats). Changing everything on
  every beat wears the viewer out: on beats, change *one thing*.
- Something happens on every beat (`rv motion` shows quiet beats; `rv beats` shows a frame per beat).
- Anticipation 3-6 frames before the hit, the hit on the beat frame, settle after.
- Hold text 0.3 s per word + 0.5 s before it moves.
- Contrast speeds: a fast move lands better after a hold. Stillness is a tool.

## 7. Iterate toward specificity

After each review round, ask: *what here could be in any other piece?* Replace it with something
that could only be in this one. That is the creative version of the lab loop in `review.md`.
