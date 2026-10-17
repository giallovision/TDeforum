# TDeforum-A1111 Integrated Workflow Environment

An interactive **TouchDesigner** control surface driving a containerized **AUTOMATIC1111 + Deforum + ControlNet** API, with optional **ComfyUI** preprocessing of ControlNet guide videos.

---

## 🏗️ Architecture

| Layer | Runs | Does |
|---|---|---|
| **Host (Windows)** | TouchDesigner | the `deforum` COMP (all parameters, tempo, mod matrix, prompt sequence), CHOP modulation, submits jobs, polls progress, loops results |
| **GPU host (Linux, `gvispc1`)** | Docker: `tdeforum-a1111` (port 7865), ComfyUI (port 8188) | Stable Diffusion, Deforum rendering, ControlNet, FFmpeg stitching |
| **Share** | Repo root exported as `T:/` | The data bridge both sides read and write |

### Path bridge

The same file has three names. `scripts/tdeforum/config.py` (`path_map`) converts between them; keep it in sync with the volumes in `docker-compose.yml`.

| Inside the container | On the Linux host (repo) | From TouchDesigner |
|---|---|---|
| `/opt/a1111/outputs/...` | `td_outputs/...` | `T:/td_outputs/...` |
| `/opt/a1111/td_masks/...` | `td_masks/...` | `T:/td_masks/...` |
| `/opt/a1111/td_inputs/comfy_videos/...` | `td_inputs/comfy_videos/...` (→ ComfyUI `input/`) | `T:/td_inputs/comfy_videos/...` |
| `/opt/a1111/td_masks/preprocessed_vids/...` | `~/Codebase/comfyui/output/preprocessed_vids/...` | only if that folder is also bind-mounted into `td_masks/` on the host (see Gotchas) |

---

## 🚀 Quick start (GPU host)

```bash
cp .env.example .env          # set HOST_USER_DIR, SHARED_NVME_MOUNT, PROXY_DOMAIN
make build                    # -> tdeforum-a1111:local
make up                      # starts it and waits until the API answers
make doctor                   # GPU, A1111 API, Deforum API, volumes
```

Once a build renders correctly, freeze it:

```bash
make lock                     # pin Dockerfile refs to the exact commits running now (commit the diff)
make bake                     # tag :local as :stable (+ stable-YYYYMMDD-HHMM)
# set A1111_TAG=stable in .env
make save                     # optional: tarball on NVMe for a no-build, no-download restore
```

## 🐳 Container lifecycle

| Goal | Command | What it costs |
|---|---|---|
| Give VRAM to ComfyUI, keep A1111 up | `make unload` / `make reload` | seconds, no restart |
| Pause / resume | `make stop` / `make start` | exits on SIGINT immediately; start = A1111 boot only |
| Recreate the container | `make down` / `make up` | settings, hash cache, HF/torch caches, Deforum depth models and ControlNet annotators persist on named volumes |
| Rebuild after a Dockerfile change | `make build` | only changed layers; pip/apt downloads come from the BuildKit cache |
| Roll back | `make rollback TO=stable-...` then `make up` | instant |
| Restore on a fresh machine / after `docker system prune` | `make load` | no build, no downloads |

`make versions` prints torch / torchvision / xformers and the three source commits inside the running container. `docker builder prune` clears the download cache mounts; avoid it if you want fast rebuilds.

---

## 🎛️ TouchDesigner

### One-time setup after pulling this version

1. **`setup_network.py`**: make a Text DAT in `/project1` with *File* `T:/scripts/setup_network.py`, then right-click › *Run Script* (or in the textport: `exec(open('T:/scripts/setup_network.py', encoding='utf-8').read())`). It points all three Web Client DATs at `webclient2_callbacks`, fixes the prompt file path, creates `loadvideo_exec` for the LoadVideo button, switches `moviefilein1` to a constant path, and prints notes about the CHOP chain. It is idempotent and prints every change.
2. **`builder_master_ui`** › *Run Script*: builds the **`deforum` Base COMP** from `scripts/tdeforum/schema.py`. On the first run it migrates every value, expression and bind from the old `Deforum_UI` (which is then no longer read; delete it when you are happy). Later runs keep the COMP's values (`RESET_TO_DEFAULTS = True` goes back to the baselines).
3. Textport: `op('deforum_payload_exec').module.doctor()` reports which paths TouchDesigner can see, the server URLs, the tempo plan, active mod slots and the Mod CHOP channels.

### The `deforum` COMP

Every Deforum parameter worth driving lives on one COMP, at Deforum's own baseline (motion neutral). Pages (the first one has the *Example Preset* drop-down): **Tempo · Globals · Prompts · Motion 2D · Motion 3D · Camera & Depth · Diffusion · Noise & Color · Flow & Anti-blur · Mod Matrix · ControlNet Unit 1 · ControlNet Unit 2 · ControlNet Unit 3 · Pipeline**.

Each schedulable parameter (zoom, translation, rotation, FOV, perspective flip, strength, noise, contrast, CFG, steps, noise multiplier, subseed strength, eta, CLIP skip, cadence/redo flow factor, anti-blur amount/sigma/threshold) has:

* a **float base** (`Translationz`, `Strengthschedule`, …): keyframe it in TD, export a CHOP to it or bind it; the value at Queue time is the base;
* a **`…raw`** string (`Translationzraw`): a hand-written Deforum schedule; when not empty it is sent verbatim and base + modulation are ignored.

On top of the base, three modulation sources, all tempo-locked:

| Source | Where | Sent to Deforum as |
|---|---|---|
| **Mod Matrix** (8 slots) | *Mod Matrix* page: target, shape (sine, triangle, saw up/down, soft square, kick decay, bump), cycle in beats, depth, phase, sharpness | one math expression Deforum evaluates every frame, e.g. `0:(1 + 0.04*exp(-6*((t/30.0) % 1)))` |
| **Mod CHOP** | COMP input 1 (or *Mod CHOP* path). One loop long, any sample rate; channels named after the parameter (`translation_z` or `Translationz`) | baked: every render frame sampled (base + CHOP + slots) |
| **Prompt sequence** | `deforum/prompt_seq` table, columns *beat*, *prompt*, *xfade* | held prompt keys + beat-length crossfades written as weighted `AND` prompts |

Press **bake** (or `td_controller.preview(op('/project1'))`) to see exactly what Queue would send in `deforum/schedule_preview`, with warnings (seam jumps, 2D-only parameters in 3D, values leaving Deforum's sane range).

### ControlNet from a TOP (`final_out`)

Deforum can only read a *file* for ControlNet, so TouchDesigner records the TOP into one. On each *ControlNet Unit* page set **Guide Source**:

* **Existing file**: the unit's *Vid Path* as before.
* **TOP: record the loop**: Queue records *Source TOP* (for example `/project1/final_out`) into `T:/td_masks/feeds/cnN_feed.mp4` and points the unit's Vid Path at it.
* **TOP: one still frame**: saves the current frame as a PNG; Deforum uses it for every frame.

How a loop feed is made: Deforum frame k is guided by video frame k, so the recording has exactly *max_frames* frames. Queue pauses the timeline, steps it to the planned frame for each render frame (wrapping around the loop for the overlap), and records one video frame per step. At 60 fps + cadence that is every timeline frame; with RIFE/FILM it is every 2nd/3rd/4th. *Pipeline › Feed Loop Start* is the timeline frame the loop begins on (0 = the timeline start). *Pipeline › Feed Method* chooses Add Frame (exact) or "record every cooked frame" (fallback).

Notes:

* `final_out` must be driven by the **project timeline** (`me.time.frame`, Timeline CHOP, ...), not `absTime` or real-time clocks, or the recording will not match the loop.
* Feedback networks (Feedback TOP, Cache) depend on stepping through every frame; they are not reproducible by jumping, so keep the guide source feed-forward.
* Preview (**bake**) logs the plan ("feed 1: 270 frames, timeline 1..240 ...") without recording.
* ComfyUI preprocessing is skipped for TOP feeds; use ControlNet's own module (`depth_midas`, `canny`, ...) or leave it at `none` for ready-made masks or QR images.
* `cn_feed_dir` and `cn_feed_ext` (`.mov` for ProRes/Animation) can be changed in `scripts/tdeforum.local.json`.
* Units 1-3 have pages; units 4-5 stay available through the payload only.

### Example presets

*Tempo › Example Preset* (first page of the COMP) lays one of 15 example configurations over the COMP when you press **bake** (or Queue). The baselines in `schema.py` never change; the presets live in `scripts/tdeforum/presets.py`.

* Only constant parameters are set; anything you have bound, exported or given an expression keeps its driver (the log lists them).
* A MOD parameter's *raw schedule* is cleared while a preset is on, otherwise it would beat the preset's base value.
* Motion (2D/3D camera) and the Mod Matrix slots a preset does not mention are set to the baseline, so each example starts from a neutral camera.
* The values a preset replaced are remembered: pick another preset, or **None**, and press bake to get them back first. Your own tweaks after applying stay until the selection changes.
* Seed, seed behaviour (baseline: **Iterate +1, seed 424242**), sampler, steps, CFG, size, model, prompts are never touched. ControlNet is left alone too, except by the three *Depth sweep* examples (below), which take over unit 1.

| id | name | what it does |
|---|---|---|
| `3d_tunnel_roll` | 3D - Tunnel roll (good) | Steady forward push with a slow roll; high keep so it flows like a QR tunnel. |
| `3d_slow_orbit` | 3D - Slow orbit (good) | Gentle pan around the scene with mirrored edges so nothing smears at the border. |
| `3d_kick_push` | 3D - Kick push (good) | Slow drift forward plus a push on every beat (Mod slot 1) that also loosens Strength on the hit (slot 2), so the kick regenerates detail. |
| `3d_warp_drive` | 3D - Warp drive (extreme) | Fast push, wide FOV and a surge every 4 beats. Expect stretching; cadence 2 keeps up. |
| `3d_vortex` | 3D - Vortex (extreme) | Fast roll while pushing in and tilting; the picture spirals and re-forms. |
| `3d_strobe_push` | 3D - Strobe push (extreme) | Hard pushes on every half beat, a contrast flash and a Strength dip on the beat. |
| `2d_zoom_drift` | 2D - Zoom drift (good) | Slow zoom in with a hint of rotation; the classic smooth Deforum roll. |
| `2d_scroll` | 2D - Scroll (good) | Sideways scroll with wrapped edges, so the picture tiles instead of smearing. |
| `2d_spiral_crash` | 2D - Spiral crash (extreme) | Fast zoom and spin with low keep: the image keeps collapsing into new structure. |
| `2d_twirl` | 2D - Twirl (extreme) | Spin swings left and right over 4 beats (slot 1) while every beat pulses the zoom (slot 2). |
| `video_soft_restyle` | Video Input - Soft restyle (good) | Keeps most of the init video's structure and colour; frames follow the video (needs Globals > Video Init Path). |
| `video_melt` | Video Input - Melt (extreme) | Loose hold on the video: heavy restyle, extra noise, no colour matching. |
| `video_depth_sweep_away` | Video Input - Depth sweep away (good) | One slow sweep, nearest levels (245-255) to farthest (0-10): the white band seems to travel away from you. |
| `video_depth_sweep_toward` | Video Input - Depth sweep toward (good) | The same the other way: farthest levels first, ending on the nearest. |
| `video_depth_sweep_pulses` | Video Input - Depth sweep pulses (extreme) | Four out-and-back sweeps, wide band that keeps the depth shading, strong ControlNet, loose hold. |

### Sweep Depth (Animation Mode = Video Input)

A moving band through the depth of your init video, recorded as a ControlNet guide (and optionally the mask video).

1. **Sweep Depth** page: switch it **On**, pick a depth preprocessor, then on *ControlNet Unit N* set **Guide Source = Sweep Depth** (and the unit on). Needs Animation Mode = Video Input and Globals > Video Init Path.
2. At Queue, ComfyUI depth-maps the init video for the frames being rendered (`max_frames`, 240 in a 240-frame project) through the same workflow as *Preprocess via ComfyUI*; the result is cached like it.
3. TouchDesigner plays that depth video through `sweep_depth` -> the Script TOP `sweep_mask`, which keeps only the grey band for the frame being recorded (white inside the band, black elsewhere) and records one frame per render frame, exactly like the TOP feeds. The finished movie becomes the unit's `vid_path`.

The depth video is made from the **Video Init Path** itself (not from unit 1's preprocessed video), named after the init video, size, model and frame count, so the same settings reuse it (*Force ComfyUI re-preprocess* remakes it). To prepare it beforehand switch on *Queue only makes the depth video*: Queue stops once it exists and the *Depth Video* field shows its path. To use a depth video you made yourself, put its container path in *Pre-made Depth Video*; ComfyUI is then skipped.

Depth maps are white = near. **Max** starts on the nearest levels (245-255 for a width of 10) and ends on 0-10, so the white sweep seems to move away from you; **Min** does the reverse. *Cycles* repeats it over the render, *Shape* = ping-pong goes out and back, *Direction* = reverse swaps start and end, *Band Width* / *Edge Softness* are in grey levels (of 255), *Band Fill* = Depth keeps the depth shading inside the band, *Also use as Video Mask* sets `video_mask_path` / `use_mask_video` to the same movie (the unit may then stay off). The log and the *Sweep Plan* field show the band at the first and last frame.

Render frame k shows source frame `extract_from + k * nth`, and the sweep position follows k, so the sweep is recorded sequentially (the timeline is lengthened for the recording and restored, as for any feed).

### Tempo

At 60 fps one beat is **40 frames at 90 bpm, 30 at 120, 24 at 150**. *Tempo* sets BPM, beats per bar and loop length in bars; the render length follows (plus an overlap for the seam). Two render strategies:

* **60 fps + cadence**: every frame on your 60 fps beat grid; *Diffusion Cadence* N diffuses every Nth frame and warps between (cost ≈ 60/N diffusions per second).
* **Low fps + RIFE/FILM**: render at 15/20/30 fps and let Deforum interpolate to 60 (x4/x3/x2). Cheaper; 30 fps gives whole-frame loops at all three tempos, 20 fps does not at 90 bpm (warned).

### Seamless loops

With *Seamless Loop* on:

1. Mod slots whose cycle divides the loop return to their start (others are warned about).
2. The prompt sequence fades its last prompt back into the first at the loop point.
3. Deforum renders an extra *Loop Overlap* (beats) past the loop. With *Loop Seeds*, seeds follow `s + t % loop`, so the tail re-diffuses the head's noise.
4. The **loop player** inside the COMP (`loop_head`, `loop_tail` → `loop_cross` → COMP output 1) plays the loop and crossfades the tail into the head over the overlap, so the wrap is the render's own continuation. *Loop Player Offset* shifts it against your timeline.

Deforum is feed-forward, so the last frame never equals the first; the overlap crossfade is what closes the loop. Measured on a 270-frame test render the head and tail frames differ about four times more than neighbouring frames, even with a perfectly periodic ControlNet guide, so the crossfade is a dissolve between two different images: raise *Loop Overlap* to 2-4 beats to make it a slow morph (costs that many extra render frames). The crossfade is eased (smoothstep).

### Writing your own schedules (`…raw`)

Deforum splits a schedule on `,` and `:` before evaluating it, and evaluates with numexpr (`t` = frame, `max_f`, `s` = seed):

* no commas inside an expression (no `where(a,b,c)`, `min`, `max`);
* **write divisors as floats**: numexpr floor-divides `int / int` inside Deforum, so `t/30` steps; use `t/30.0`;
* in prompt weights (backticks) every letter `t` is replaced by the frame number, so avoid functions containing a `t` (`tanh`, `sqrt`); `sin`, `cos`, `exp`, `abs` are fine;
* the anti-blur *kernel* must be odd (OpenCV), so it is a plain integer, not modulatable.

### Network map

| Trigger | DAT | File | Calls |
|---|---|---|---|
| **Queue** button (`null1`) | `deforum_payload_exec` | `deforum_payload_exec.py` | `td_controller.queue` |
| `timer1` cycle pulse | `chopexec_poll` | `chopexec_poll.py` | `td_controller.tick` |
| All Web Client DATs | `webclient2_callbacks` | `webclient2_callbacks.py` | `td_controller.on_response` |
| **bake** button (`null2`) | `bake_exec` | `bake_exec.py` | `td_controller.preview` (no POST) |
| **LoadVideo** button (`null3`) | `loadvideo_exec` | `loadvideo_exec.py` | `td_controller.load_latest` |
| Run Script | `export_deforum_payload` | `export_deforum_payload.py` | dry run → `runtime/last_deforum_payload.json` |
| Run Script | `preproc_payload_exec` | `comfy_preprocessor_payload_exec.py` | ComfyUI preprocess only |
| Run Script | `builder_master_ui` | `build_master_ui.py` | build / rebuild the `deforum` COMP |
| Run Script | `export_toe` | `export_toe.py` | save + copy the `.toe` to `T:/` |

### What Queue does

1. Reads the `deforum` COMP (parameters, `prompt_seq`, Mod CHOP), `T:/scripts/prompt.json` (when *Prompt Source* is json) and the `available_models` table, and builds **one** batch request (`scripts/tdeforum/payload.py`). Frame counts are capped by the real length of the init / mask videos read through the share.
2. If *ControlNet Unit 1 › Preprocess via ComfyUI* and CN1 are on: posts `scripts/templates/TD_CN_PreProc.json` to ComfyUI, polls `/history`, sets `Cn1vidpath` to the result and caches it per settings (*Pipeline › Force ComfyUI re-preprocess* bypasses the cache).
3. Posts the batch to `/deforum_api/batches`, then polls **that job** (`/deforum_api/jobs/<id>`) on each `timer1` cycle. Idle means no polling.
4. When the job finishes and the video (`<ts>_RIFE_xN.mp4` / `<ts>_FILM_xN.mp4` when interpolating, else `<ts>.mp4`) has stopped growing on the share, loads it into `moviefilein1` **and** the loop player (*Pipeline › Auto-load*). If the interpolated file never appears, the plain render is loaded after 30 s and played at the right speed.

*Pipeline › Status* shows the current step. Textport helpers:

```python
op('deforum_payload_exec').module.status()   # state of the current job
op('deforum_payload_exec').module.cancel()   # cancel Deforum job / interrupt ComfyUI
op('deforum_payload_exec').module.doctor()   # paths, URLs, tempo, mods, wiring
```

---

## 💻 Code layout

```
scripts/
  tdeforum/            # all logic; plain Python, unit-tested (make test)
    config.py          # endpoints, path bridge, timings (+ scripts/tdeforum.local.json overrides)
    schema.py          # deforum COMP fields: drives build_master_ui AND the payload
    tempo.py           # bpm / bars / fps -> render plan (cadence or interpolation)
    modulation.py      # beat-locked shapes -> Deforum expressions / baked keyframes
    prompt_seq.py      # beat-indexed prompts -> held keys + AND crossfades
    feed.py            # TOP -> ControlNet guide video: frame plan, paths, checks
    sweep.py           # Sweep Depth: band maths + numpy mask for the depth video
    presets.py         # 15 example configurations (Example Preset drop-down)
    migrate.py         # Deforum_UI -> deforum COMP value migration
    payload.py         # batch request + frame plan
    comfy.py           # ComfyUI request / history parsing
    schedules.py       # keyframe strings, checkpoint schedules
    td_controller.py   # TouchDesigner glue and the job state machine
  *.py                 # thin DAT entry points (file-synced from the .toe)
  templates/TD_CN_PreProc.json
  prompt.json
tests/                 # make test; no TouchDesigner needed
docker/tools/          # versions / lock / wait helpers used by the Makefile
runtime/               # git-ignored: last payload, td_console.log
```

DAT scripts put `T:/scripts` on `sys.path` and call `tdeforum.reload_all()` on button presses, so edits made in VS Code apply on the next click without restarting TouchDesigner. `vscode_console_stream.py` mirrors the textport to `T:/runtime/td_console.log`.

---

## 🏗️ Architecture notes & gotchas

### Docker volume mounts vs. symlinks
Never use host-level absolute symlinks to bridge files into a container: the container cannot resolve host paths. Use volume mounts in `docker-compose.yml` instead (e.g. `- /home/gvispc1/Codebase/comfyui/output/preprocessed_vids:/opt/a1111/td_masks/preprocessed_vids`).

The same applies to the Samba share: a symlink or container-only mount is invisible from `T:/`. `td_masks/preprocessed_vids` on the host is just the empty mount point docker created; for TouchDesigner to see ComfyUI's output there, bind-mount it on the host too, e.g. in `/etc/fstab`:

```
/home/gvispc1/Codebase/comfyui/output/preprocessed_vids  /home/gvispc1/Codebase/TDeforum/td_masks/preprocessed_vids  none  bind  0  0
```

`doctor()` reports what TouchDesigner can actually see. Rendering does not depend on it; only frame-count capping and browsing do.

### Deforum only reads keys it knows
Deforum's settings loader silently ignores unknown keys. `tests/data/deforum_keys_5d63a339.json` lists the keys of the pinned Deforum commit, and `make test` fails if the payload sends anything else. `tests/_deforum_sim.py` replicates how Deforum parses schedules and prompt weights (including numexpr's integer division), so the tests check the values Deforum will compute, not just the strings. Notable mappings: negative prompt → `animation_prompts_negative`; A1111 options → top-level `options_overrides`.

### TouchDesigner payload execution
* Avoid `run(..., delayFrames=X)` for critical state; the controller keeps job state in `/project1` storage and is driven by button edges, the timer pulse and HTTP callbacks.
* One Queue press sends exactly one batch; a second press while a job is in flight is ignored (cancel first).

### Line endings
TouchDesigner writes CRLF and Linux tools write LF; `.gitattributes` stores LF so diffs only show real changes.
