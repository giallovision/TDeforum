# 🗺️ TDeforum & ComfyUI Pipeline Roadmap

This document outlines the macro-architecture for our generative visual performance pipeline. The objective is to utilize a localized, containerized AI backend (Linux) driven by an audio-reactive, procedural front-end (Windows/TouchDesigner), culminating in a live-performance VJ compositing environment.

---

## 🏗️ Phase 1: Procedural Generation & Control (TouchDesigner)
**Role:** The Director and Data Generator.
* **Audio-Reactive Drivers:** CHOP networks (`wave_generator`, `math`, `quantize`) convert live or pre-recorded audio into usable mathematical matrices.
* **Asset Generation:** TouchDesigner generates precision driving assets—specifically **Init Videos** and high-contrast **Mask Videos** (e.g., silhouettes, geometric gates).
* **Network Handoff:** These assets are dumped directly into the shared networked drive (`T:/td_inputs` and `T:/td_masks`), making them instantly accessible to the Linux backend.

## 🧠 Phase 2: Core Inference & Tracking (ComfyUI)
**Role:** The Stable Diffusion Engine.
* **The Pivot:** While Deforum is retained for chaotic, optical-flow feedback loops, the primary engine for high-fidelity photorealism shifts to a containerized **ComfyUI** environment.
* **Volume Mapping:** ComfyUI is dockerized on the same Linux host, natively mounting the `td_outputs` and `td_masks` directories. Zero network transfer time.
* **Advanced Guidance:** ComfyUI utilizes the TD-generated Init Videos and Masks to drive **ControlNet** and **OpenPose** networks, ensuring temporal consistency and preventing the structural "melting" associated with recursive Deforum loops.

## 🔬 Phase 3: Post-Processing & Upscaling (ComfyUI Refiner)
**Role:** The Polish.
* **Separation of Concerns:** A completely isolated ComfyUI workflow dedicated strictly to resolution enhancement and detail refinement.
* **Execution:** Takes the 960x544 raw LCM renders from Phase 2 and pushes them through a latent upscaler/refiner pipeline, delivering pristine HD/4K aspect ratios ready for large-scale projection.

## 🎛️ Phase 4: Live Compositing & Performance (Resolume + TD + OSC)
**Role:** The Stage.
* **Content Economy:** The HD/4K renders from Phase 3 are loaded into **Resolume Arena**. The original black-and-white masks generated in Phase 1 are repurposed here as alpha channels and luma mattes to isolate the AI subjects from their backgrounds.
* **Live Control:** TouchDesigner bridges via **OSC (Open Sound Control)** to trigger clips, modulate effects, and sync Resolume parameters to the live audio tempo. 
* **The Result:** A highly optimized, modular performance environment where generative AI assets are manipulated in real-time without the latency of live inference.

---

## 🚀 Current Status & Task Tracking

### ✅ Completed
- [x] Integrate ComfyUI API for automated preprocessor video generation.
- [x] Fix container boundary path leaks (Replaced symlinks with Docker volume mounts).
- [x] Lock down TouchDesigner JSON payload serialization to explicitly enforce container paths.
- [x] Eliminate `delayFrames` cache-clearing bugs in the master execution button.

### 🚧 In Progress
- [ ] Analyze cross-pollination of models (e.g., applying geometric/QR Monster ControlNets to gradient Depth Maps).
- [ ] Container Networking: Spin up the ComfyUI Docker container and verify volume mounts to `/opt/a1111/td_inputs` and `/td_masks`.
- [ ] Workflow Drafting: Build the base video-to-video + OpenPose JSON workflow in ComfyUI.

### 🔮 Future Implementations
- [ ] Expand TouchDesigner UI to support dynamically toggling ControlNet Units 2-5.
- [ ] OSC Architecture: Map TouchDesigner's `bake_out` data points to Resolume's OSC routing addresses.
- [ ] Implement an explicit "Force Re-Render" toggle to bypass ComfyUI's native execution cache.
- [ ] Route Deforum image sequence outputs back into TouchDesigner for real-time playback monitoring.