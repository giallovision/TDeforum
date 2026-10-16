# TDeforum-A1111 Integrated Workflow Environment

An interactive **TouchDesigner** control surface driving a containerized **AUTOMATIC1111 + Deforum + ControlNet** API, with optional **ComfyUI** preprocessing of ControlNet guide videos.

---

## 🏗️ Architecture

| Layer | Runs | Does |
|---|---|---|
| **Host (Windows)** | TouchDesigner | UI (`Deforum_UI`), audio-reactive CHOP motion, bakes keyframes, submits jobs, polls progress, plays results |
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
2. **`builder_master_ui`** › *Run Script*: rebuilds the `Deforum_UI` pages from `scripts/tdeforum/schema.py`. Values, expressions and binds you already set are kept (`RESET_TO_DEFAULTS = True` discards them).
3. Textport: `op('deforum_payload_exec').module.doctor()` reports which paths TouchDesigner can see, the server URLs and the wiring.

### Network map

| Trigger | DAT | File | Calls |
|---|---|---|---|
| **Queue** button (`null1`) | `deforum_payload_exec` | `deforum_payload_exec.py` | `td_controller.queue` |
| `timer1` cycle pulse | `chopexec_poll` | `chopexec_poll.py` | `td_controller.tick` |
| All Web Client DATs | `webclient2_callbacks` | `webclient2_callbacks.py` | `td_controller.on_response` |
| **bake** button (`null2`) | `bake_exec` | `bake_exec.py` | `td_controller.bake` |
| **LoadVideo** button (`null3`) | `loadvideo_exec` | `loadvideo_exec.py` | `td_controller.load_latest` |
| Run Script | `export_deforum_payload` | `export_deforum_payload.py` | dry run → `runtime/last_deforum_payload.json` |
| Run Script | `preproc_payload_exec` | `comfy_preprocessor_payload_exec.py` | ComfyUI preprocess only |
| Run Script | `builder_master_ui` | `build_master_ui.py` | rebuild `Deforum_UI` |
| Run Script | `export_toe` | `export_toe.py` | save + copy the `.toe` to `T:/` |

### What Queue does

1. Reads `Deforum_UI`, `T:/scripts/prompt.json` and the `available_models` table, and builds **one** batch request (`scripts/tdeforum/payload.py`). Frame counts are capped by the real length of the init / mask videos read through the share.
2. If *ControlNet Unit 1 › Preprocess via ComfyUI* and CN1 are on: posts `scripts/templates/TD_CN_PreProc.json` to ComfyUI, polls `/history`, sets `Cn1vidpath` to the result and caches it per settings (*Pipeline › Force ComfyUI re-preprocess* bypasses the cache).
3. Posts the batch to `/deforum_api/batches`, then polls **that job** (`/deforum_api/jobs/<id>`) on each `timer1` cycle. Idle means no polling.
4. When the job finishes and the `.mp4` has stopped growing on the share, loads it into `moviefilein1` (*Pipeline › Auto-load*).

*Pipeline › Status* shows the current step. Textport helpers:

```python
op('deforum_payload_exec').module.status()   # state of the current job
op('deforum_payload_exec').module.cancel()   # cancel Deforum job / interrupt ComfyUI
op('deforum_payload_exec').module.doctor()   # paths, URLs, wiring
```

### Deforum_UI pages

* **Globals**: model (index into `available_models`, a filename, or a schedule such as `0: 0, 75: 1`), VAE (sent as an A1111 option override), size, steps, max frames (bound to the timeline end), sampler, animation mode, seed behaviour / seed, negative prompt, mask video, init / mask paths, frame mode (*Trim* = first N frames; *Stride* = every n-th frame across the whole clip).
* **Motion (2D/3D)**: border (2D `border` + 3D `padding_mode`), zoom, angle, translation, 3D rotation, transform centre. Plain numbers are sent as `0:(value)`.
* **Schedules**: noise, strength, contrast, CFG.
* **Perspective 3D**: *Enable Perspective Flip* (Deforum ignores the flip schedules without it), flip θ/φ/γ/fv, FOV, near, far.
* **ControlNet Unit 1**: every Deforum CN1 field (weight / guidance as schedules, resize and control mode as menus) plus the ComfyUI preprocess toggle and preprocessor.
* **Advanced Setup**: base strength, diffusion cadence, optical-flow cadence.
* **Pipeline**: status, auto-load, force re-preprocess, bake points and bake target.

### Bake

Bake samples every channel of `wave_generator` at *Bake points* equidistant frames (0 = every frame) into `frame:(value)` keys. A channel named after a schedule (`zoom`, `translation_z`, …) is written straight into that parameter; otherwise channel 0 goes to *Bake into*. `bake_out` always receives a copy. Parameters driven by an expression or CHOP export are never overwritten.

---

## 💻 Code layout

```
scripts/
  tdeforum/            # all logic; plain Python, unit-tested (make test)
    config.py          # endpoints, path bridge, timings (+ scripts/tdeforum.local.json overrides)
    schema.py          # Deforum_UI fields: drives build_master_ui AND the payload
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
Deforum's settings loader silently ignores unknown keys. `tests/data/deforum_keys_5d63a339.json` lists the keys of the pinned Deforum commit, and `make test` fails if the payload sends anything else. Notable mappings: negative prompt → `animation_prompts_negative`; A1111 options → top-level `options_overrides`.

### TouchDesigner payload execution
* Avoid `run(..., delayFrames=X)` for critical state; the controller keeps job state in `/project1` storage and is driven by button edges, the timer pulse and HTTP callbacks.
* One Queue press sends exactly one batch; a second press while a job is in flight is ignored (cancel first).

### Line endings
TouchDesigner writes CRLF and Linux tools write LF; `.gitattributes` stores LF so diffs only show real changes.
