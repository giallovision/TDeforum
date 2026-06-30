# TDeforum-A1111 Integrated Workflow Environment

This repository details the unified, cross-platform pipeline connecting an interactive **TouchDesigner** motion graphics control engine to a containerized **Stable Diffusion AUTOMATIC1111 Deforum API** back-end.

---

## 🏗️ Core System Architecture

The pipeline divides responsibilities between two main operating layers:
1. **The Host Layer (Windows):** Powers the TouchDesigner UI, interprets timeline parameters, generates audio-reactive motion data, synchronizes prompt script files, and handles live logging visualization.
2. **The Virtualized Layer (Linux/Docker):** Executes the Stable Diffusion backend, manages CUDA processing nodes, extracts input video streams, and stitches the final frames together via FFmpeg.

A shared network file structure (`T:/` on Windows mapping directly to `/opt/a1111/` on Linux) acts as the high-speed data bridge between environments.

---

## 🎛️ TouchDesigner Custom Interface Specifications

The main user interface COMP (`Deforum_UI`) dynamically structures its parameters across six task-focused control panels:

### 1. Globals
* **Width / Height (W / H):** Dimensions of the generation canvas. Mapped optimally to 960x544 to maintain native aspect ratios.
* **Steps:** Denotes the processing density of each frame. Forged to 4 for high-velocity LCM inference cycles.
* **Max Frames:** Dictates the project length boundary. Binds directly to the TouchDesigner timeline limit.
* **Sampler:** Switched to LCM for accelerated visual throughput.
* **Animation Mode:** Locked onto Video Input for absolute frame-to-frame consistency during style transfers.
* **Video Init Path / Video Mask Path:** Mounted paths pointing straight to driving assets inside the container network.
* **Video Frame Mode:** An abstracted dropdown handling downsampling transformations:
    * Trim (Normal Speed): Employs scissors-style rendering, hard-clipping the source video sequence at your maximum frame boundary.
    * Stride (Timelapse): Employs comb-style sampling, calculating mathematical striding gaps to squeeze an entire long video timeline into a short frame budget.

### 2. Motion (2D/3D)
* **Zoom / Angle:** Controls basic canvas scaling transformations over time.
* **Translation X / Y / Z:** Manages horizontal, vertical, and deep spatial camera movements. Driven natively by audio-reactive CHOP data.
* **Rotation 3D X / Y / Z:** Manipulates structural pitch, yaw, and roll vectors.

### 3. Schedules
* **CFG Scale Schedule:** Handled autonomously by the script execution layer.
* **Strength Schedule:** Defines how much data from the previous frame is overwritten by new generations.
* **Noise Schedule:** Injects fresh static details between frames to give the AI textures to grab onto.
* **Contrast Schedule:** Keeps the luminance spectrum balanced across long, evolving loops.

### 4. Perspective 3D
* **Perspective Flip Theta / Phi / Gamma:** Simulates physical tilting and rotational warping of the master canvas space.
* **FOV Schedule:** Automates camera focal lens zooming profiles.

### 5. ControlNet Unit 1
* **Enabled / Module / Model:** Manages spatial structural guidance passes over the raw noise layout.
* **Weight:** Regulates how aggressively the structural reference shape governs the generation.

### 6. Advanced Setup
* **Scale:** Structural configuration bypass parameter.
* **Strength:** Base image-to-image denoise value. Hardcoded to 0.21 below the noise multiplier to keep your LCM generations locked to your input tracking data.

---

## 💻 Python Engine Scripts

The entire environment is driven by modular Python scripts located in the `scripts/` directory:

### 1. build_master_ui.py
* **Role:** The Layout Architect. Programmatically clears out stale custom tabs, builds a clean UI panel based on predefined dictionaries, docks helper tables, and aligns the open prompt viewer right below the controller COMP without destroying manual user inputs.

### 2. deforum_dispatch_exec.py
* **Role:** The Payload Dispatcher. Scrapes data from the UI tabs, pulls multi-keyframe prompt configurations from external text files (`prompt.txt`), handles mathematical overrides, constructs the master payload JSON, and fires it over to the server via a POST request. Features a Titanium model parser that safely handles both single indices and complex string-based timeline schedules.

### 3. bake_exec.py
* **Role:** The Motion Quantizer. Reads dense audio-reactive waveform data (60+ FPS) from CHOP networks, down-samples it based on user-defined UI parameters, and generates mathematically perfect, equidistant keyframe string schedules (`0:(0.5), 10:(1.2)...`) formatted exactly for the Deforum API.

### 4. export_toe.py
* **Role:** The Version Control Bridge. A highly localized utility script that bypasses Windows/Linux SMB metadata locks by executing a raw binary copy of the active `.toe` project file, pushing it directly to the root of the mapped network drive for Git tracking.

### 5. vscode_console_stream.py
* **Role:** The Infrastructure Umbilical Cord. Hooks directly into Python's core standard outputs (`sys.stdout`/`sys.stderr`). It mirrors all TouchDesigner internal textport messages out to `T:/scripts/td_console.log` for remote debugging inside VS Code.

---

## 🏗️ Architecture Notes & Gotchas

### Docker Volume Mounts vs. Symlinks
**Crucial Rule:** Never use host-level absolute symlinks to bridge files between the Linux host and a Docker container (like ComfyUI to Deforum). 
* When a Python script inside a container reads a symlink, it attempts to resolve the absolute host path. 
* Because the container is isolated, it cannot see the host's directory, causing a fatal `File Not Found` runtime error.
* **The Solution:** Always use native Docker volume mounts in the `docker-compose.yml` to project host folders directly into the container's internal filesystem (e.g., `- /home/gvispc1/Codebase/comfyui/output/preprocessed_vids:/opt/a1111/td_masks/preprocessed_vids`).

### TouchDesigner Payload Execution
* **Avoid `delayFrames` for critical state changes:** Using `run(string, delayFrames=X)` for toggling Developer DAT sync states causes race conditions where the script execution context is lost. Execute network payload dispatches directly in the `onOffToOn` function.
* **Explicit Payload Enforcement:** The `deforum_dispatch_exec.py` script intercepts the UI parameters right before JSON serialization to explicitly enforce container-native paths (`/opt/a1111/...`). This prevents UI parsing loops from accidentally leaking host paths into the Deforum API `video_mask_path` or `video_init_path` arguments.