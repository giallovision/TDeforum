# deforum COMP: parameter reference

Every custom parameter of the `deforum` Base COMP, page by page, as built by `build_master_ui` (tdeforum 0.11.0). **TD name** is the parameter's name in TouchDesigner (`op('deforum').par.<name>`); **default** is the baseline value.

Parameters marked **MOD** (their label on the COMP starts with `~`) are the driveable (keyframeable) ones: a float base value plus a `<name>raw` override. Type a Deforum schedule into the raw one (e.g. `0:(1), 30:(1.04)`) and it is sent as written, ignoring the base and any modulation; leave it empty to use the base + CHOP link + Mod Matrix + Mod CHOP.

## Driving a parameter with a CHOP (CHOP links)

Drag a channel from any CHOP (Pattern, LFO, Noise, Animation, a math chain ...) onto a MOD parameter's **float base** and choose **CHOP Reference** (`op('pattern1')['chan1']`) or **Export CHOP**. The parameter shows the channel live and its label gets `[CHOP]` (and *Mod Matrix > CHOP-linked Parameters* lists it); at Queue the *whole* channel is baked into that parameter's Deforum schedule, and Mod Matrix slots / the Mod CHOP still add on top.

- **Base, not raw.** A channel dropped on `<name>raw` is treated the same way, but typed text in raw always beats a CHOP on the base (Queue warns).
- **Maths is fine:** `op('pattern1')['chan1'] * 2 + 1` or a sum of channels is evaluated over the whole arrays. An expression that cannot be (`math.sin(...)`) falls back to its first channel, as-is, with a warning.
- **Length:** with *CHOP Link Timing* = Timeline (default), a Pattern CHOP with Length `me.time.end` renders exactly what you see from *Feed Loop Start* for one loop (it wraps past its end). With *Whole channel = one loop* any length is stretched to the loop.
- **Check it:** *Mod Matrix > CHOP-linked Parameters*, the Textport at Queue / bake / `doctor()`, and the `schedule_preview` table (mode `chop`).

Driveable parameters: `Zoom`, `Angle`, `Transformcenterx`, `Transformcentery`, `Translationx`, `Translationy`, `Translationz`, `Rotation3dx`, `Rotation3dy`, `Rotation3dz`, `Fovschedule`, `Nearschedule`, `Farschedule`, `Aspectratioschedule`, `Perspectivefliptheta`, `Perspectiveflipphi`, `Perspectiveflipgamma`, `Perspectiveflipfv`, `Strengthschedule`, `Noiseschedule`, `Contrastschedule`, `Cfgscaleschedule`, `Stepsschedule`, `Noisemultiplierschedule`, `Subseedstrengthschedule`, `Ddimetaschedule`, `Ancestraletaschedule`, `Clipskipschedule`, `Hybridflowfactorschedule`, `Hybridcompalphaschedule`, `Cadenceflowfactorschedule`, `Redoflowfactorschedule`, `Amountschedule`, `Sigmaschedule`, `Thresholdschedule`.

## Contents

- [Tempo](#tempo)
- [Globals](#globals)
- [Prompts](#prompts)
- [Motion 2D](#motion-2d)
- [Motion 3D](#motion-3d)
- [Camera & Depth](#camera--depth)
- [Diffusion](#diffusion)
- [Noise & Color](#noise--color)
- [Flow & Anti-blur](#flow--anti-blur)
- [Hybrid Video](#hybrid-video)
- [Mod Matrix](#mod-matrix)
- [Sweep Depth](#sweep-depth)
- [ControlNet Unit 1](#controlnet-unit-1)
- [Pipeline](#pipeline)

## Tempo

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Preset` | Example Preset (applied when picked) | none | Lays one of the 31 example configurations over the COMP as soon as you pick it. None puts back every value the example (and any Page Preset) replaced. |
| `Presetapply` | Re-apply Preset | (button) | Lays the selected example over the COMP again after you have changed things; also resets every Page Preset to None. |
| `Presetinfo` | Preset | (read-only) | Read-only: which example is applied and how many parameters it set. |
| `Pagepresettempo` | Page Preset (Tempo) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Bpm` | BPM | 120.0 | Tempo of the loop. Together with Beats per Bar and Loop Length it decides how many frames are rendered and the period of every Mod Matrix slot. |
| `Beatsperbar` | Beats per Bar | 4 | Beats in one bar (4 for 4/4). Used for the loop length and bar-based modulation. |
| `Loopbars` | Loop Length (bars) | 2 | Length of the loop in bars; at 120 bpm, 4/4 and 60 fps, 2 bars = 240 frames. |
| `Outfps` | Output FPS | 60 | Frame rate of the finished video and of TouchDesigner's timeline maths. |
| `Renderstrategy` | Render Strategy | cadence | Cadence: Deforum renders every output frame (with diffusion cadence). Interpolate: Deforum renders at Render FPS and RIFE/FILM fills the frames in between. |
| `Renderfps` | Render FPS (interpolate) | 30 | With Render Strategy = Interpolate, the rate Deforum actually renders at (15/20/30); the interpolator multiplies it up to Output FPS. |
| `Interpengine` | Interpolation Engine | RIFE v4.6 | RIFE (fast, crisp) or FILM (smoother on big motion) for the Interpolate strategy. |
| `Diffusioncadence` | Diffusion Cadence (diffuse every Nth frame) | 4 | Only every Nth frame is diffused; the frames between are warped/blended from it. Higher = smoother and faster, lower = more detail and more flicker. Use 1 in Video Input. |
| `Seamlessloop` | Seamless Loop | On | Renders a little past the loop and crossfades the overlap in the loop player so the end flows into the start. |
| `Loopoverlapbeats` | Loop Overlap (beats, crossfaded) | 1.0 | How many beats past the loop are rendered and crossfaded at the seam. |
| `Loopseeds` | Loop Seeds (schedule seeds to repeat per loop; off = Iterate +1) | Off | Schedules the seed so frame f and f + loop share a seed (helps the seam). Off = plain Iterate +1, the smoother baseline. |
| `Lengthsource` | Length Source | tempo | Tempo: length comes from BPM / bars. Manual: length is Max Frames. |
| `Maxframes` | Max Frames (manual) | 240 | Number of frames to render when Length Source is Manual. |
| `Tempoinfo` | Plan | (read-only) | Read-only: the render plan (frames, fps, cadence or interpolation). |

## Globals

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Sdmodelcheckpoint` | Model (index / schedule) | 0 | The Stable Diffusion checkpoint: an index into available_models, a filename, or a checkpoint schedule. |
| `Sdvae` | VAE | Automatic | VAE used to decode images; Automatic uses the checkpoint's own. |
| `Width` | Width | 1024 | Render width in pixels. |
| `Height` | Height | 576 | Render height in pixels. |
| `Steps` | Steps (LCM: 4) | 4 | Sampling steps per diffused frame. LCM checkpoints want 4. |
| `Img2imgfixsteps` | Exact Steps on every frame (A1111 img2img_fix_steps) | On | Makes A1111 run exactly Steps on every img2img frame; without it it runs only int(steps x (1 - Strength)), often a single step. |
| `Sampler` | Sampler | LCM | Sampler name (LCM for LCM checkpoints). |
| `Scheduler` | Scheduler | Automatic | Noise scheduler; Automatic picks the sampler's default. |
| `Animationmode` | Animation Mode | 3D | 2D (flat transforms), 3D (camera through a depth map), Video Input (restyle each video frame) or Interpolation (every frame from noise, morphing between prompts/seeds). |
| `Seedbehavior` | Seed Behavior | iter | How the seed changes per frame: Iterate (+1, the smooth baseline), Fixed (same noise every frame, best for Video Input), Random, Ladder, Alternate or Schedule. |
| `Seed` | Seed | 424242 | Starting seed (424242 by default). |
| `Nprompt` | Negative Prompt | worst quality, low quality, glitch, d... | Negative prompt applied to every frame: what the image should avoid. |
| `Strength` | Init Strength (first frame) | 0.8 | How much of the init image the very first frame keeps (only when an init image or video is used). |
| `Usemaskvideo` | Use Mask Video | Off | Uses Video Mask Path as a per-frame inpainting mask. |
| `Invertmask` | Invert Mask (diffuse the black areas instead) | Off | Diffuses the black parts of the mask instead of the white parts. |
| `Overlaymask` | Overlay Mask (keep the original outside the mask) | Off | Pastes the un-diffused original back outside the mask, so only the masked area changes. |
| `Videoinitpath` | Video Init Path | /opt/a1111/td_inputs/comfy_videos/arc... | The input video (container path): the source for Video Input, Hybrid Video and Sweep Depth. |
| `Videomaskpath` | Video Mask Path | /opt/a1111/td_masks/mask_01.mov | Mask video (container path) used when Use Mask Video is on; Sweep Depth can fill it in. |
| `Videoframemode` | Video Frame Mode | trim | Trim: use the video's first frames at normal speed. Stride: skip frames so the whole video fits the render (timelapse). |

## Prompts

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Promptsource` | Prompt Source | sequence | Sequence: prompts from the beat-indexed prompt_seq table inside the COMP. prompt.json: frame-keyed prompts from scripts/prompt.json. A picked Prompt Preset overrides either. |
| `Promptpreset` | Prompt Preset (writes prompt_seq) | none | Writes one of ten visionary prompts into prompt_seq and changes nothing else; while one is picked it is the prompt whatever Prompt Source says. None restores your rows (and prompt.json, if that is your source). |
| `Promptedit` | Edit prompt_seq (opens deforum/prompt_seq) | (button) | Opens deforum/prompt_seq in a floating editor. |
| `Promptxfadebeats` | Default Crossfade (beats) | 1.0 | Default crossfade length between prompt_seq rows when a row has no xfade of its own. |

## Motion 2D

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Pagepresetmotion2d` | Page Preset (Motion 2D) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Border` | Border | replicate | What fills the edges revealed by 2D motion: Replicate (stretch the edge pixels) or Wrap (tile the image). |
| `Zoom` | ~ Zoom (2D, 1 = still) | 1.0 | 2D zoom factor per frame (1 = still, 1.003 = slow zoom in, below 1 = zoom out). **MOD** (raw: `Zoomraw`) |
| `Angle` | ~ Angle (2D, deg/frame) | 0.0 | 2D rotation in degrees per frame. **MOD** (raw: `Angleraw`) |
| `Transformcenterx` | ~ Transform Center X (2D) | 0.5 | Horizontal pivot for 2D zoom and rotation (0 = left, 1 = right). **MOD** (raw: `Transformcenterxraw`) |
| `Transformcentery` | ~ Transform Center Y (2D) | 0.5 | Vertical pivot for 2D zoom and rotation (0 = top, 1 = bottom). **MOD** (raw: `Transformcenteryraw`) |
| `Translationx` | ~ Translation X (2D + 3D) | 0.0 | Sideways movement per frame (pixels in 2D, camera units in 3D). **MOD** (raw: `Translationxraw`) |
| `Translationy` | ~ Translation Y (2D + 3D) | 0.0 | Vertical movement per frame (pixels in 2D, camera units in 3D). **MOD** (raw: `Translationyraw`) |

## Motion 3D

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Pagepresetmotion3d` | Page Preset (Motion 3D) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Paddingmode` | Padding Mode | border | What fills areas the 3D camera reveals: Border (smear), Reflection (mirror) or Zeros (black). |
| `Samplingmode` | Sampling Mode | bicubic | Pixel interpolation for 3D warps: bicubic (sharp), bilinear or nearest. |
| `Translationz` | ~ Translation Z (3D push) | 0.0 | Camera push per frame (positive = forward into the image). **MOD** (raw: `Translationzraw`) |
| `Rotation3dx` | ~ Rotation 3D X (tilt, deg/frame) | 0.0 | Camera tilt in degrees per frame. **MOD** (raw: `Rotation3dxraw`) |
| `Rotation3dy` | ~ Rotation 3D Y (pan, deg/frame) | 0.0 | Camera pan in degrees per frame. **MOD** (raw: `Rotation3dyraw`) |
| `Rotation3dz` | ~ Rotation 3D Z (roll, deg/frame) | 0.0 | Camera roll in degrees per frame. **MOD** (raw: `Rotation3dzraw`) |

## Camera & Depth

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Pagepresetcamera` | Page Preset (Camera & Depth) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Usedepthwarping` | Use Depth Warping | On | 3D: warp the previous frame through its depth map (real parallax) instead of a flat transform. |
| `Depthalgorithm` | Depth Algorithm | Midas-3-Hybrid | Depth model Deforum uses for 3D warping (MiDaS hybrid by default; Zoe/AdaBins/LeReS alternatives). |
| `Midasweight` | Midas Weight | 0.2 | Blend weight of MiDaS in the hybrid depth algorithms; higher = stronger depth relief. |
| `Enableperspectiveflip` | Enable Perspective Flip | Off | Turns on the perspective flip schedules (theta, phi, gamma, fv); without it they do nothing. |
| `Fovschedule` | ~ FOV (3D) | 70.0 | 3D camera field of view in degrees; wider = more parallax and stretching. **MOD** (raw: `Fovscheduleraw`) |
| `Nearschedule` | ~ Near (3D) | 200.0 | 3D near clipping distance of the depth warp. **MOD** (raw: `Nearscheduleraw`) |
| `Farschedule` | ~ Far (3D) | 10000.0 | 3D far clipping distance of the depth warp. **MOD** (raw: `Farscheduleraw`) |
| `Aspectratioschedule` | ~ Aspect Ratio (3D) | 1.0 | 3D aspect ratio of the camera; changing it squeezes or stretches space. **MOD** (raw: `Aspectratioscheduleraw`) |
| `Perspectivefliptheta` | ~ Flip Theta | 0.0 | Perspective flip: tilt of the picture plane around the horizontal axis (degrees). **MOD** (raw: `Perspectiveflipthetaraw`) |
| `Perspectiveflipphi` | ~ Flip Phi | 0.0 | Perspective flip: tilt around the vertical axis (degrees). **MOD** (raw: `Perspectiveflipphiraw`) |
| `Perspectiveflipgamma` | ~ Flip Gamma | 0.0 | Perspective flip: rotation in the picture plane (degrees). **MOD** (raw: `Perspectiveflipgammaraw`) |
| `Perspectiveflipfv` | ~ Flip FV | 53.0 | Perspective flip: field of view of the virtual camera looking at the plane. **MOD** (raw: `Perspectiveflipfvraw`) |

## Diffusion

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Pagepresetdiffusion` | Page Preset (Diffusion) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Enablestepsscheduling` | Enable Steps Scheduling | Off | Lets Steps follow the Steps schedule instead of the fixed Steps value. |
| `Enablenoisemultiplierscheduling` | Enable Noise Multiplier Scheduling | On | Lets the Noise Multiplier schedule apply. |
| `Enablesubseedscheduling` | Enable Subseed Scheduling | Off | Turns on Subseed / Subseed Strength: blends the noise towards a second seed. |
| `Subseedschedule` | Subseed | 0:(1) | The second seed (as a schedule) that Subseed Strength blends towards. |
| `Enableddimetascheduling` | Enable DDIM Eta Scheduling | Off | Lets the DDIM Eta schedule apply (DDIM samplers only). |
| `Enableancestraletascheduling` | Enable Ancestral Eta Scheduling | Off | Lets the Ancestral Eta schedule apply (ancestral samplers only). |
| `Enableclipskipscheduling` | Enable CLIP Skip Scheduling | Off | Lets the CLIP Skip schedule apply. |
| `Strengthschedule` | ~ Strength (keep of previous frame) | 0.65 | How much of the previous frame is kept (0.8 = keep 80 %, re-imagine 20 %). The main smoothness vs. change control. **MOD** (raw: `Strengthscheduleraw`) |
| `Noiseschedule` | ~ Noise | 0.02 | Fresh noise added to each frame before diffusing; more = more new detail and more flicker. **MOD** (raw: `Noisescheduleraw`) |
| `Contrastschedule` | ~ Contrast | 1.0 | Contrast applied to each frame before diffusing (1 = unchanged); above 1 builds up contrast over time. **MOD** (raw: `Contrastscheduleraw`) |
| `Cfgscaleschedule` | ~ CFG Scale (LCM: 1.5-2) | 1.8 | How strongly the prompt is followed. LCM checkpoints want 1.5-2; higher burns. **MOD** (raw: `Cfgscalescheduleraw`) |
| `Stepsschedule` | ~ Steps (needs Enable Steps Scheduling) | 25.0 | Steps per frame over time (needs Enable Steps Scheduling). **MOD** (raw: `Stepsscheduleraw`) |
| `Noisemultiplierschedule` | ~ Noise Multiplier | 1.0 | Multiplier on the sampler's own noise; 1 = unchanged. **MOD** (raw: `Noisemultiplierscheduleraw`) |
| `Subseedstrengthschedule` | ~ Subseed Strength (needs Enable Subseed) | 0.0 | 0..1 blend from the seed's noise to the subseed's noise (needs Enable Subseed). **MOD** (raw: `Subseedstrengthscheduleraw`) |
| `Ddimetaschedule` | ~ DDIM Eta (needs Enable) | 0.0 | DDIM eta: randomness of DDIM sampling (needs Enable). **MOD** (raw: `Ddimetascheduleraw`) |
| `Ancestraletaschedule` | ~ Ancestral Eta (needs Enable) | 1.0 | Ancestral eta: randomness of ancestral samplers (needs Enable). **MOD** (raw: `Ancestraletascheduleraw`) |
| `Clipskipschedule` | ~ CLIP Skip (needs Enable) | 2.0 | How many final CLIP layers to skip when encoding the prompt (needs Enable). **MOD** (raw: `Clipskipscheduleraw`) |

## Noise & Color

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Pagepresetnoise` | Page Preset (Noise & Color) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Noisetype` | Noise Type | perlin | Shape of the added noise: Perlin (smooth, cloudy) or Uniform (fine grain). |
| `Perlinw` | Perlin W | 8 | Perlin noise cells across the width; lower = bigger blobs. |
| `Perlinh` | Perlin H | 8 | Perlin noise cells down the height. |
| `Perlinoctaves` | Perlin Octaves | 4 | Layers of Perlin detail; more = finer texture on top of the blobs. |
| `Perlinpersistence` | Perlin Persistence | 0.5 | How strong each finer Perlin octave is relative to the previous one. |
| `Colorcoherence` | Color Coherence | LAB | Keeps colours from drifting by matching each frame to a reference: LAB/HSV/RGB (first frame), Video Input (the video frame), Image, or None. |
| `Colorforcegrayscale` | Color Force Grayscale | Off | Converts every frame to greyscale before diffusing. |
| `Legacycolormatch` | Legacy Colormatch (earlier renders used it) | On | Uses Deforum's older colour-matching method (what earlier renders used). |

## Flow & Anti-blur

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Pagepresetflow` | Page Preset (Flow & Anti-blur) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Opticalflowcadence` | Optical Flow Cadence | RAFT | How the in-between (cadence) frames are made: None (plain blend) or an optical-flow method (RAFT is best) that moves pixels along the motion. |
| `Opticalflowredogeneration` | Optical Flow Redo Generation | None | Renders each diffused frame twice and uses optical flow between them to stabilise it (less flicker, about 2x slower). |
| `Kernelschedule` | Anti-blur Kernel (odd) | 5 | Anti-blur sharpening kernel size (odd number). |
| `Cadenceflowfactorschedule` | ~ Cadence Flow Factor | 1.0 | Strength of the optical flow applied to cadence frames (1 = full). **MOD** (raw: `Cadenceflowfactorscheduleraw`) |
| `Redoflowfactorschedule` | ~ Redo Flow Factor | 1.0 | Strength of the flow used by Redo Generation. **MOD** (raw: `Redoflowfactorscheduleraw`) |
| `Amountschedule` | ~ Anti-blur Amount | 0.1 | Anti-blur sharpening amount, fights the softening that accumulates over many frames. **MOD** (raw: `Amountscheduleraw`) |
| `Sigmaschedule` | ~ Anti-blur Sigma | 1.0 | Anti-blur blur radius used to build the sharpening mask. **MOD** (raw: `Sigmascheduleraw`) |
| `Thresholdschedule` | ~ Anti-blur Threshold | 0.0 | Anti-blur threshold: only edges above it are sharpened. **MOD** (raw: `Thresholdscheduleraw`) |

## Hybrid Video

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Pagepresethybrid` | Page Preset (Hybrid Video) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Hybridmotion` | Hybrid Motion | None | 2D/3D: borrow motion from the init video: Optical Flow (local, per pixel), Perspective or Affine (the video's camera only). |
| `Hybridflowmethod` | Hybrid Flow Method | RAFT | Optical-flow method for Hybrid Motion (RAFT most accurate, Farneback fastest). |
| `Hybridmotionuseprevimg` | Flow from the previous generated image | Off | Measures flow between the previous generated frame and the video frame, which pulls the image towards the video's layout. |
| `Hybridflowconsistency` | Hybrid Flow Consistency | Off | Masks out pixels where the flow is unreliable (occlusions) to reduce tearing. |
| `Hybridconsistencyblur` | Hybrid Consistency Blur | 2 | Softens the flow-consistency mask. |
| `Hybridflowfactorschedule` | ~ Hybrid Flow Factor | 1.0 | Scales the borrowed motion (0.5 = half the video's motion, 2 = exaggerated). **MOD** (raw: `Hybridflowfactorscheduleraw`) |
| `Hybridcomposite` | Hybrid Composite (mix the video in) | None | Blends the video's pixels into each frame before diffusion: Normal, Before Motion or After Generation; None = motion only. |
| `Hybridcompalphaschedule` | ~ Composite Alpha | 0.5 | How much of the video frame is blended in by Hybrid Composite (0..1). **MOD** (raw: `Hybridcompalphascheduleraw`) |

## Mod Matrix

Slots 1-8 each have the same seven parameters (`Mod1active` ... `Mod8sharpness`). Each slot adds a beat-locked shape to one parameter on top of its base value.

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Pagepresetmods` | Page Preset (Mod Matrix) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Chopmode` | Mod CHOP Mode | add | How Mod CHOP channels combine with the base values: Add (offset) or Replace. |
| `Choppath` | Mod CHOP (empty = COMP input 1) | (empty) | A CHOP whose channels are named after parameters (translation_z, zoom, ...), one loop long; empty = COMP input 1. |
| `Bakepoints` | CHOP Bake Points (0 = every frame) | 0 | Keyframes per loop when baking the Mod CHOP or a CHOP link into Deforum schedules (0 = every frame). |
| `Choptiming` | CHOP Link Timing | timeline | How a CHOP link is read. Timeline (default): what the parameter shows while the timeline plays, one loop from Feed Loop Start. Whole channel = one loop: the channel is stretched over the loop whatever its length. |
| `Choplinksinfo` | CHOP-linked Parameters | (read-only) | Read-only: which parameters have a CHOP channel dropped on them, and from where (updated at Queue / bake). |
| `Mod1active` ... `Mod8active` | Slot N On | Off | Turns this modulation slot on. |
| `Mod1target` ... `Mod8target` | Slot N Target | zoom | The parameter this slot modulates. |
| `Mod1shape` ... `Mod8shape` | Slot N Shape | sine | Waveform: sine, triangle, saw up/down, square, kick decay or bump. |
| `Mod1beats` ... `Mod8beats` | Slot N Cycle (beats) | 1.0 | Length of one cycle in beats (1 = every beat, 4 = once a bar). |
| `Mod1depth` ... `Mod8depth` | Slot N Depth | 0.0 | Amplitude, in the target's own units, added on top of its base value (negative flips it). |
| `Mod1phase` ... `Mod8phase` | Slot N Phase (cycles) | 0.0 | Offset of the cycle (0..1) to shift the slot against the beat. |
| `Mod1sharpness` ... `Mod8sharpness` | Slot N Sharpness | 4.0 | Edge sharpness for square, decay speed for kick decay, narrowness for bump. |

## Sweep Depth

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Pagepresetsweep` | Page Preset (Sweep Depth) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Sweepenabled` | Sweep Depth On | Off | Turns Sweep Depth on: a band of the init video's depth becomes a guide/mask video. |
| `Sweepmode` | Mode | max | Max: starts on the nearest depth (white) and sweeps away. Min: starts far and rushes toward you. |
| `Sweepcycles` | Cycles (sweeps over the render) | 1.0 | How many sweeps over the render. |
| `Sweepshape` | Shape | ramp | Ramp: each cycle restarts. Ping-pong: each cycle goes out and back. |
| `Sweepdirection` | Direction | forward | Reverse swaps the start and end of the sweep. |
| `Sweepwidth` | Band Width (grey levels of 255) | 10 | Width of the white band in grey levels (of 255); 255 = the whole depth map. |
| `Sweepsoftness` | Edge Softness (grey levels) | 0 | Feathers the band's edges by this many grey levels. |
| `Sweepgrow` | Grow (px, widens the band shapes) | 0 | Widens the band shapes by this many pixels. |
| `Sweepblur` | Blur (px, soft glow for ControlNet) | 0.0 | Blurs the band (Gaussian, pixels) into a soft glow; QR Monster reads it better than a hard stencil. |
| `Sweeptrail` | Trail (frames the band glows on, 0 = off) | 0 | Frames the band keeps glowing after it has passed (fades to 5 %). |
| `Sweepsmooth` | Depth Smoothing (steadier band, 0 = off) | 0.0 | Blends each depth frame with the previous ones so depth flicker does not make the band jitter. |
| `Sweepfill` | Band Fill | white | White: a flat white band. Depth: keep the depth shading inside the band. |
| `Sweepasmask` | Also use as Video Mask | Off | Also sets the sweep as the Video Mask (Use Mask Video on), so only the band is re-diffused. |
| `Sweepmodel` | Depth Model (ComfyUI) | depth_anything_v2_vits | Depth model ComfyUI uses for the depth video (Depth Anything V2 small is the fast default). |
| `Sweepdepthvideo` | Pre-made Depth Video (container path; empty = make it from Video Init Path) | (empty) | A depth video you made yourself (container path); ComfyUI is skipped. |
| `Sweepprepareonly` | Queue only prepares the sweep (depth + mask video, no render) | Off | Queue stops after the depth and sweep videos exist, so you can preview before rendering. |
| `Sweepforce` | Force Re-render Sweep (ignore the sweep cache; depth video kept) | Off | Renders the sweep mask again at the next Queue even if the same one is cached (the depth video is reused). Turn it off again afterwards, or every Queue re-renders. |
| `Sweepdepthpath` | Depth Video | (read-only) | Read-only: the depth video in use. |
| `Sweepinfo` | Sweep Plan | (read-only) | Read-only: the sweep plan (bands at start/end, frames, render time). |
| `Sweepshowlatest` | Show Latest Sweep (sweep_preview / COMP output 2) | (button) | Points sweep_preview (COMP output 2) at the newest sweep video. |

## ControlNet Unit 1

Units 2 and 3 have their own pages with the same parameters (`Cn2...`, `Feed2...`, `Cn3...`, `Feed3...`); the two ComfyUI rows are Unit 1 only.

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Pagepresetcn1val` | Page Preset (ControlNet Unit 1) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Cn1enabled` | Enabled | Off | Turns this ControlNet unit on. |
| `Feed1mode` | Guide Source | file | Where the guide video comes from: File (Vid Path), a TOP recorded as a loop or as a still, or Sweep Depth. |
| `Feed1top` | Source TOP (path, e.g. /project1/final_out) | /project1/final_out | The TOP to record as the guide when Guide Source is a TOP (default /project1/final_out on every unit). |
| `Feed1info` | Last Feed | (read-only) | Read-only: when and how the last guide was made. |
| `Cn1module` | Module | none | ControlNet preprocessor run inside A1111 (none = use the guide as-is, right for QR Monster and ready-made maps). |
| `Cn1model` | Model | ctrl_v1p_qr_monster_v2 | ControlNet model, e.g. ctrl_v1p_qr_monster_v2. |
| `Cn1vidpath` | Vid Path | /opt/a1111/td_masks/mask_01.mov | Guide video/image (container path); set automatically by TOP feeds, ComfyUI preprocessing and Sweep Depth. |
| `Cn1maskvidpath` | Mask Vid Path | (empty) | Optional mask limiting where this unit acts. |
| `Cn1weight` | Weight | 1.0 | Strength of this unit's guidance. |
| `Cn1guidancestart` | Guidance Start | 0.0 | Fraction of the sampling steps after which the unit starts guiding. |
| `Cn1guidanceend` | Guidance End | 1.0 | Fraction of the steps after which it stops (below 1 lets the last steps add free detail). |
| `Cn1processorres` | Processor Res | 512 | Resolution the preprocessor works at. |
| `Cn1thresholda` | Threshold A | 0.5 | First preprocessor-specific threshold (e.g. Canny low). |
| `Cn1thresholdb` | Threshold B | 0.5 | Second preprocessor-specific threshold (e.g. Canny high). |
| `Cn1resizemode` | Resize Mode | Inner Fit (Scale to Fit) | How the guide is fitted to the render size: Inner Fit, Outer Fit or Just Resize. |
| `Cn1controlmode` | Control Mode | Balanced | Balanced, My prompt is more important, or ControlNet is more important. |
| `Cn1lowvram` | Low Vram | Off | Lower VRAM use at some speed cost. |
| `Cn1pixelperfect` | Pixel Perfect | On | Lets ControlNet choose the preprocessor resolution from the render size. |
| `Cn1overwriteframes` | Overwrite Frames | On | Re-extracts the guide video's frames every run instead of reusing old ones. |
| `Cn1loopbackmode` | Loopback Mode | Off | Feeds the previous generated frame back in as this unit's guide. |
| `Comfypreprocenable` | Preprocess via ComfyUI | Off | At Queue, ComfyUI preprocesses the init video (Comfy Preprocessor) into Unit 1's guide video (cached). |
| `Comfypreprocessor` | Comfy Preprocessor | PiDiNetPreprocessor | The ComfyUI preprocessor used for Unit 1 (depth, lineart, pose, edges ...). |

## Pipeline

| TD name | Label | Default | What it does |
|---|---|---|---|
| `Pagepresetpipeline` | Page Preset (Pipeline) | none | Quick presets that change only this page's parameters; they stack with other pages. None puts this page's values back. |
| `Pipelinestatus` | Status | (read-only) | Read-only: what the pipeline is doing right now (preprocessing, sweep, render %, idle). |
| `Autoload` | Auto-load finished render | On | Loads the finished render into moviefilein1 and the loop player automatically. |
| `Forcepreprocess` | Force ComfyUI re-preprocess | Off | Ignores cached ComfyUI results (Unit 1 preprocessing and the Sweep depth video) and the sweep mask cache, and makes them all again. |
| `Loopoutframes` | Loaded loop length (frames) | (read-only) | Read-only: loop length of the loaded render (frames). |
| `Loopoutoverlap` | Loaded loop overlap (frames) | (read-only) | Read-only: seam overlap of the loaded render (frames). |
| `Loopoutrate` | Loaded file frames per output frame | (read-only) | Read-only: file frames per output frame (0.5 when an un-interpolated render plays at half speed). |
| `Loopoffset` | Loop Player Offset (frames) | 0 | Shifts the loop player's start against the timeline. |
| `Feedloopstart` | Feed: loop start frame (0 = timeline start) | 0 | Timeline frame where TOP feeds and beat_clock start counting (0 = timeline start). |
| `Feedmethod` | Feed: recording method | addframe | Add Frame: the recorder steps the timeline frame by frame. Continuous: records every cooked frame. |
| `Reloadoutputs` | Reload Render + Input (outputs 1 and 3) | (button) | Loads the last render (output 1) and its input video (output 3) again; with nothing loaded yet, the newest render with the current settings' loop plan. |
| `Loopinstart` | Input loop: first video frame | (read-only) | Read-only: first init-video frame the render used (output 3 starts there). |
| `Loopinstride` | Input loop: video frames per render frame | (read-only) | Read-only: init-video frames per render frame (more than 1 with Video Frame Mode = Stride). |
| `Loopinrate` | Input loop: render frames per output frame | (read-only) | Read-only: render frames per output frame (0.5 when the render is interpolated x2); keeps output 3 in step with output 1. |
| `Snapshotname` | Snapshot Name (optional) | (empty) | Optional name for the next snapshot; the file is <name>_<date_time>.json. |
| `Snapshottake` | Take Snapshot (saves every parameter) | (button) | Saves every parameter (values, expressions, binds), prompt_seq and the preset state to T:/snapshots and puts the file in Snapshot File. |
| `Snapshotpath` | Snapshot File (path, or a name in T:/snapshots) | (empty) | The snapshot to load: a full path, or just a file name from T:/snapshots. |
| `Snapshotload` | Load Snapshot | (button) | Puts back everything the snapshot saved (CHOP-exported parameters keep their export). |
| `Snapshotinfo` | Snapshot | (read-only) | Read-only: the last snapshot taken or loaded. |
