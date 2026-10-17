# Reference pass: ballet pulse composite (2026-10-17)

The render: `Deforum_20261017051421/20261017051421_RIFE_x3.mp4`. It is 1126 frames at 60 fps and 1024×576: 380 render frames at 20 fps, interpolated ×3 by RIFE.
* **Snapshot:** `docs/passes/2026-10-17_ballet_pulse.snapshot.json`. To load it, put `T:/docs/passes/2026-10-17_ballet_pulse.snapshot.json` in *Pipeline › Snapshot File* and pulse *Load Snapshot*. The two Force toggles were taken out.
* **Example Preset:** the look is now *Hybrid - Pulse composite (good)* (`hybrid_ballet_pulse`). It reproduces the three CHOP curves as raw schedules.

## What was on

| Area | Setting | Value |
|---|---|---|
| Mode | Animation Mode | 3D, Use Depth Warping, MiDaS-3-Hybrid, MiDaS weight 0.2, Padding Zeros |
| Init | Video Init Path | `ballet1.mp4` (380 frames), Trim |
| Hybrid | Motion, flow method | Optical Flow, RAFT, flow factor 1 |
| Hybrid | Composite | **Before Motion, alpha 0.8** |
| Motion | Translation Z | CHOP `wave1 × 1`: a saw from 1.30 down to 0.74 every **10 render frames** |
| Camera | FOV | CHOP `wave1 × 42 + 84`: 138.6° down to 115.1°, on the same saw |
| Diffusion | Strength | CHOP `wave1 × 0.7`: 0.91 down to 0.52, on the same saw |
| Diffusion | LCM | 4 steps, Exact Steps on, **CFG 1.5**, noise **0.01**, noise multiplier 1.0 |
| Noise / colour | Perlin, colour coherence | Perlin **4 × 4**, octaves 3, persistence 0.5; LAB, **legacy colormatch off** |
| Cadence | Cadence + flow | **8** + RAFT |
| Interpolation | Render rate | 20 fps, RIFE ×3 to 60 |
| ControlNet 1 | Guide | QR Monster v2, weight 1.0, guidance **0.2 … 0.8**, preprocessor none, processor res 576 |
| ControlNet 1 | Feed | **TOP loop from `/project1/final_out`** (your live TD visual) |
| Sweep Depth | Use | Depth Anything V2 S; **as the mask** (Use Mask Video on) |
| Sweep Depth | Band | max mode, 1 ramp cycle, width 40, softness 16, grow 10, blur 8, trail 20, smooth 0.4, fill white |
| Prompt | Prompt Preset | *Haeckel abyss*, plus the global negative prompt |
| Tempo | Loop | 150 bpm, 16 bars, seamless off. The loop wanted 512 frames, so the video capped it at 380 |

## Why it worked

**1. The video holds the structure.**
* *Hybrid Composite: Before Motion* at alpha 0.8 blends 80 % of the real video frame into the image before the frame is warped and diffused.
* The dancer, the sky and the set therefore come back as photographic anchors on every diffused frame. The diffusion can't drift into abstraction.
* Optical-flow hybrid motion moves the existing pixels the way the dancer moves, so whatever the diffusion adds travels with the body.

**2. Only a soft band is re-dreamed.**
* The Sweep video is the inpainting mask, so Deforum only re-diffuses where the band is. Everything outside the band keeps the composited video and the warp.
* Width 40, softness 16, grow 10, blur 8 and trail 20 make the band a wide, feathered, lingering zone instead of a hard slice.
* In the contact sheet, the diffused "feather / fin" structures (the Haeckel radial forms) grow along the arms and torso where the band crosses the dancer. The face, hands and sky stay clean.
* That contrast between real and dreamed regions is what reads as intentional rather than a filter.

**3. One curve drives push, lens and Strength together.** All three CHOP links come from one channel, so every 10 render frames the camera pushes in, the FOV narrows from 139° to 115°, and Strength falls from 0.91 to 0.52.
* **Deforum only diffuses every 8th frame** (cadence 8), so Strength only matters on frames 0, 8, 16, 24, 32, …
* **The pattern:** on a 10-frame saw those frames land at phases 0, 8, 6, 4, 2, 0, …, giving Strength 0.91, 0.56, 0.65, 0.74, 0.82 and repeat.
* **The rhythm:** that is one deep re-imagining followed by progressively lighter ones, cycling every 40 frames (2 s, exactly 5 beats at 150 bpm). The 10 against 8 polyrhythm is a large part of the "breathing".
* **Every frame:** the push and the lens act on every frame (they are warps, not diffusions), so the motion pulse is felt every 0.5 s.
* **In the numbers:** the frame-to-frame change of the render correlates about equally at the cadence period (lag 24 output frames: 0.67) and at the saw period (lag 30: 0.65). Both rhythms are visible.

**4. Cadence 8 + RAFT + RIFE ×3 keeps it fluid and fast.**
* Only about 48 of the 380 frames are diffused. RAFT carries the frames between them along the motion, and RIFE triples the frame rate afterwards.
* The mean frame-to-frame change is 2.7 / 255 (95th percentile 6.2), which is very calm for a hybrid render. It took 573 s.
* High cadence is usually mushy, but here the 80 % composite keeps re-sharpening the base. Use cadence 8 only with a strong composite or another anchor.

**5. LCM with little noise.**
* 4 exact steps at CFG 1.5 reach full detail on every diffusion even at Strength 0.91.
* Noise 0.01 with 4 × 4 Perlin adds only large, soft variation. With so few diffusions, fine noise would show as grain the 4 steps can't clean.
* LAB coherence with the current (non-legacy) colour match holds the blue palette of the video across the whole render.

**6. The QR guide is your own visual, blended rather than stamped.**
* ControlNet 1 records `final_out` as a loop and uses it with QR Monster at weight 1.
* Guidance 0.2–0.8 lets the first steps compose freely and the last steps add detail over the pattern, so the TD visual shapes the textures without printing itself onto them.

## What could be better (seen in this pass)

* **Edge streaks:** a 139° FOV with a forward push and Zeros padding stretches the frame edges into vertical banded columns, visible in the later frames. If they bother you, try Padding Reflection or an FOV range of about 95–120°.
* **The loop didn't close:** 16 bars at 150 bpm is 512 render frames, but the video has 380. The loop player also wrapped at 1536 output frames over an 1126-frame file, so it held its last frame for about 7 s each loop. Fixed: the loop player now loops what was rendered, and *Tempo › Fit Loop to Init Video* sets 11 bars (352 frames) for this video.
* **Force toggles were left on:** Force Preprocess and Force Re-render Sweep were on, so every Queue redid ComfyUI and the sweep. Snapshots no longer save those two switches.
* **The saw isn't beat-locked:** 10 frames at 20 fps is 1.25 beats at 150 bpm. Keep it if you like the drift against the music. For a locked version, use a period of 8 frames (1 beat), but then every diffusion lands on the same phase and the breathing goes away, so 16 frames (2 beats) is the more interesting choice.

## What went into the defaults and presets

* **Baseline 4** (a rebuild moves values still at the old defaults; values you set are kept):
  * *Legacy Colormatch* off;
  * Perlin W/H 8 → 4;
  * ControlNet guidance start/end 0/1 → **0.2/0.8** on every unit.
* **New Example Preset** *Hybrid - Pulse composite (good)* writes this look. The three saws go to the `…raw` schedules; a raw whose base is CHOP-linked is left alone, so your `wave1` keeps driving it.
* **Kept as they were:**
  * **CFG default 1.8:** 1.5 worked here, and both are inside the LCM range.
  * **Noise 0.015–0.02 in the 2D/3D presets:** 0.01 suits high cadence with a composite, not cadence 2–4 without one.
  * **Cadence 2 in the other hybrid presets:** they have no composite anchor.
