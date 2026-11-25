# reality

A recreation of Tesla FSD v15 "Reality View" (a third-person view of the car generated live
from its cameras), built only from the public dataset `cfahlgren1/tesla-fsd-drive-5min` (clip_00:
six cameras and per-frame telemetry). Reference: @ryanvogel's recreation (Jacksonville, 6-cam column
on the left, reconstructed chase view on the right).

## Divergence
A: Faithful split screen (vogel's layout): 6 raw feeds on the left, reconstructed chase view on the right with HUD. Structure: one continuous drive.
B: Full-frame Reality View only, as the in-car display; the raw feeds never appear.
C: Explainer: the splats assemble keyframe by keyframe from depth maps, camera orbits the point cloud.
Picked: A, with C's honesty folded in: the opening shot starts *inside the front camera* (the reconstruction
is pixel-exact there) and pulls back through the windshield to the chase view, which shows the view
really is 3D. B loses the proof (raw feeds); C becomes a tech demo instead of the product moment.

## Brief
GOAL:     "that's the car's own cameras, rebuilt as a world": photoreal, live, plausible as the v15 display.
CONCEPT:  the pull-out. t=0 the virtual camera sits at the front camera's pose (the splats equal the video);
          over 3 s it rises over the roof and settles behind the car, revealing the 3D world and the ego car.
OUTPUT:   three (custom EWA Gaussian-splat shader) + DOM HUD, 1920x1080, no loop.
TIME:     20 s x 30 fps = 600 frames, drive time 6.0 to 26.0 s of clip_00, no music grid (telemetry is the clock).
LOOK:     page #050505; panes radius 14; footage colors as recorded (overcast teal-grey);
          ego car #F2F2EF satin white; path #2F6BFF (the one accent, as in Tesla's UI); blinker #3FD25A;
          type Geist 300 for the speed (72 px, tracking -2), Geist 500 11-13 px for labels, Geist Mono 10 px for data.
MOTION:   pull-out: position along a 3-point curve, ease.inOutCubic over 90 frames (t 0.4 to 3.4);
          chase cam follows the ego pose with yaw lag (critically damped, 0.6 s);
          HUD values are telemetry, never animated for decoration.
SHOTS:    0-3.4 pull-out (hero: camera move) | 3.4-8 left turn through the intersection, chevrons in the sky |
          8-15 accelerate on the straight (speed climbs 19 to 44 mph) | 15-20 right lane change, blinker, path swings.
SOUND:    road-noise bed rising with speed (bandpassed noise, gain by v); blinker tick/tock at 1.5 Hz while a signal is on;
          a soft chime when the pull-out lands.
BANNED:   glow/bloom, lens flares, purple gradients, invented street names or clock times, Tesla logos,
          decorative particles, HUD values that are not in the telemetry.
QA:       frames 0, 45, 102 (pull-out end), 150 (mid-turn), 330, 480 (lane change), 599.
