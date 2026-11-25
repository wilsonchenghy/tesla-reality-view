# reality / prep: dashcam → Gaussian splats

1. `bash pieces/reality/prep/fetch.sh`: clip_00 (6 cams + telemetry) and Depth Anything V2 small (ONNX).
2. `python3 pieces/reality/prep/prep.py`: about 9 min on 4 CPUs. Writes `out/reality-data/` (kf/*.bin, cams/*, index.json, ~450 MB).
3. `node bin/rv.mjs render reality`

Files:
- `rig.json`: the calibrated 6-camera rig (car frame: x right, y up, -z forward; origin on the ground under the car's centre).
  `f`/`k1`/`k2` are a Kannala-Brandt lens model (r = f(θ + k1θ³ + k2θ⁵), r in image widths).
- (`fit.py`, `overlay.py`, `bev.py` are the calibration workbench: run from `out/fsd-data`, reading frames grabbed to `cal/<cam>_648.png`.)
- `fit.py`: least-squares fit of yaw/pitch/roll/f/k1 to lane lines marked by hand on one synced frame (seq 648). Lines whose
  lateral offset is unknown are fitted too; the front camera was set from the vanishing point plus a 3.5 m lane.
  `overlay.py` draws the predicted lane lines over all six images; `bev.py` makes a bird's-eye check.
- `prep.py`: trajectory (speed + heading at 36 Hz) → frames → depth → metric scale against the ground plane → splats.
- `preview.py`: quick numpy point preview of one keyframe from a chase camera.

Splat record (20 bytes): f32 x,y,z | u8 r,g,b | u8 kind (bit0 road, bits1-3 camera, bits4-7 road elongation e=1.25^n) |
i8 nx,ny,nz (disk normal; for road, the horizontal ray direction the splat stretches along) | u8 scale (0.01·1.04^n m).
