"""Single source of truth for the Deforum COMP's custom parameters.

build_master_ui.py builds the TouchDesigner pages of the ``deforum`` Base COMP
from FIELDS, and payload.py reads the same FIELDS to decide what is sent to
Deforum and under which key. Add a field here once and it appears in both.

Field.target:
    "deforum"  -> deforum_settings[<key>]          (Deforum only reads keys it knows)
    "options"  -> options_overrides[<key>]         (A1111 opts for the batch)
    None       -> TouchDesigner-only (tempo, pipeline controls, mod matrix, ...)

Kinds:
    MOD       modulatable schedule. TD gets a float <Name> (the base value, which
              you can keyframe, export to or bind) and a string <Name>raw (a
              hand-written Deforum schedule that, when not empty, is sent verbatim).
              payload.py adds the Mod Matrix and the Mod CHOP on top of the base.
    SCHEDULE  plain string schedule; numbers are wrapped as 0:(v).

TD parameter names are derived from the API name exactly as the original
build_master_ui.py did (``translation_z`` -> ``Translationz``), so values and
expressions from the old Deforum_UI migrate by name.

Defaults ("baselines"): motion is neutral (no camera movement); seed behaviour is Iterate
(+1) with seed 424242; every other value is Deforum 5d63a339's own default unless noted.
presets.py holds example configurations laid over these on bake (the baselines never change). An LCM checkpoint wants
CFG ~1.5-2 and ~8-10 steps; set those once and they persist.
"""

import re

from . import feed, modulation, page_presets, presets, prompt_presets, sweep, tempo

PAGE_TEMPO = "Tempo"
PAGE_GLOBALS = "Globals"
PAGE_PROMPTS = "Prompts"
PAGE_MOTION2D = "Motion 2D"
PAGE_MOTION3D = "Motion 3D"
PAGE_CAMERA = "Camera & Depth"
PAGE_DIFFUSION = "Diffusion"
PAGE_NOISE = "Noise & Color"
PAGE_FLOW = "Flow & Anti-blur"
PAGE_HYBRID = "Hybrid Video"
PAGE_MODS = "Mod Matrix"
PAGE_SWEEP = "Sweep Depth"
CN_UI_UNITS = feed.UNITS          # ControlNet units with their own page (payload sends 5)
PAGE_CNS = ["ControlNet Unit %d" % n for n in range(1, CN_UI_UNITS + 1)]
PAGE_CN1 = PAGE_CNS[0]
PAGE_PIPELINE = "Pipeline"

PAGE_ORDER = [PAGE_TEMPO, PAGE_GLOBALS, PAGE_PROMPTS, PAGE_MOTION2D, PAGE_MOTION3D,
              PAGE_CAMERA, PAGE_DIFFUSION, PAGE_NOISE, PAGE_FLOW, PAGE_HYBRID, PAGE_MODS,
              PAGE_SWEEP] + PAGE_CNS + [PAGE_PIPELINE]

# Kinds understood by build_master_ui.py and payload.py
STR, INT, FLOAT, TOGGLE, MENU = "str", "int", "float", "toggle", "menu"
SCHEDULE = "schedule"      # string par; plain numbers are wrapped as 0:(v)
MOD = "mod"                # float base + <Name>raw override; modulated by the Mod Matrix / CHOP
SEED = "seed"              # string par (seeds overflow TD int pars); sent as int
CHECKPOINT = "checkpoint"  # index / filename / schedule -> checkpoint_schedule
STATUS = "status"          # read-only string written by the controller
PULSE = "pulse"            # button handled by the COMP's ui_exec DAT (never sent anywhere)

RAW_SUFFIX = "raw"         # TD name of a MOD field's override: <Name>raw
MOD_SLOTS = 8


def td_name(api_name):
    """API name -> TouchDesigner custom parameter name (original naming rule)."""
    if api_name == "W":
        return "Width"
    if api_name == "H":
        return "Height"
    clean = "".join(c for c in api_name if c.isalnum())
    name = clean[0].upper() + clean[1:].lower() if clean else ""
    if name and name[-1].isdigit():
        name += "val"
    return name


def _default_label(api_name):
    if api_name == "W":
        return "Width"
    if api_name == "H":
        return "Height"
    label = api_name.replace("_schedule", "").replace("_", " ").title()
    return re.sub(r"^Cn \d ", "", label)


class Field(object):
    __slots__ = ("api", "default", "page", "kind", "menu", "labels", "label",
                 "target", "key", "expr", "norm", "as_schedule", "safe", "dims")

    def __init__(self, api, default, page, kind, menu=None, labels=None, label=None,
                 target="deforum", key=None, expr=None, norm=None, as_schedule=False,
                 safe=None, dims=None):
        self.api = api
        self.default = default
        self.page = page
        self.kind = kind
        self.menu = list(menu) if menu else None
        self.labels = list(labels) if labels else (list(menu) if menu else None)
        self.label = label or _default_label(api)
        self.target = target
        self.key = key or api
        self.expr = expr
        self.norm = norm
        self.as_schedule = as_schedule   # numeric par sent as a 0:(v) schedule
        self.safe = safe                 # (lo, hi) Deforum-sane range for warnings; None = open
        self.dims = dims                 # "2D" / "3D" when Deforum only uses it in that mode

    @property
    def td_name(self):
        return td_name(self.api)

    @property
    def raw_td_name(self):
        return self.td_name + RAW_SUFFIX

    def __repr__(self):
        return "Field(%s -> %s)" % (self.api, self.td_name)


F = Field
TE, G, PR, M2, M3, CA, DI, NO, FL, MM, CN, PL = (
    PAGE_TEMPO, PAGE_GLOBALS, PAGE_PROMPTS, PAGE_MOTION2D, PAGE_MOTION3D, PAGE_CAMERA,
    PAGE_DIFFUSION, PAGE_NOISE, PAGE_FLOW, PAGE_MODS, PAGE_CN1, PAGE_PIPELINE)
SW = PAGE_SWEEP
HY = PAGE_HYBRID
HYBRID_MOTIONS = ["None", "Optical Flow", "Perspective", "Affine"]
HYBRID_COMPOSITES = ["None", "Normal", "Before Motion", "After Generation"]

COMFY_PREPROCESSORS = [
    "DWPreprocessor", "DepthAnythingV2Preprocessor", "SAMPreprocessor",
    "LineArtPreprocessor", "CannyEdgePreprocessor", "HEDPreprocessor",
    "PiDiNetPreprocessor", "M-LSDPreprocessor",
]
FLOW_METHODS = ["None", "RAFT", "DIS Medium", "DIS Fine", "Farneback"]
DEPTH_ALGORITHMS = ["Midas-3-Hybrid", "Midas+AdaBins (old)", "Zoe+AdaBins (old)", "AdaBins", "Zoe", "Leres"]


def _mod(api, default, page, norm, label=None, safe=None, dims=None):
    return F(api, default, page, MOD, norm=norm, label=label, safe=safe, dims=dims)


# (api, baseline, page, slider range, label, safe range, dims)
_MODS = [
    # Motion 2D (zoom/angle/centre are 2D-only; translation x/y move the camera in 2D and 3D)
    _mod("zoom", 1.0, M2, (0.9, 1.1), "Zoom (2D, 1 = still)", (0.01, None), "2D"),
    _mod("angle", 0.0, M2, (-10, 10), "Angle (2D, deg/frame)", None, "2D"),
    _mod("transform_center_x", 0.5, M2, (0, 1), "Transform Center X (2D)", None, "2D"),
    _mod("transform_center_y", 0.5, M2, (0, 1), "Transform Center Y (2D)", None, "2D"),
    _mod("translation_x", 0.0, M2, (-10, 10), "Translation X (2D + 3D)"),
    _mod("translation_y", 0.0, M2, (-10, 10), "Translation Y (2D + 3D)"),
    # Motion 3D
    _mod("translation_z", 0.0, M3, (-10, 10), "Translation Z (3D push)", None, "3D"),
    _mod("rotation_3d_x", 0.0, M3, (-3, 3), "Rotation 3D X (tilt, deg/frame)", None, "3D"),
    _mod("rotation_3d_y", 0.0, M3, (-3, 3), "Rotation 3D Y (pan, deg/frame)", None, "3D"),
    _mod("rotation_3d_z", 0.0, M3, (-3, 3), "Rotation 3D Z (roll, deg/frame)", None, "3D"),
    # Camera & Depth
    _mod("fov_schedule", 70.0, CA, (20, 120), "FOV (3D)", (1, 179), "3D"),
    _mod("near_schedule", 200.0, CA, (1, 1000), "Near (3D)", (0.001, None), "3D"),
    _mod("far_schedule", 10000.0, CA, (1000, 20000), "Far (3D)", (0.001, None), "3D"),
    _mod("aspect_ratio_schedule", 1.0, CA, (0.5, 2), "Aspect Ratio (3D)", (0.01, None), "3D"),
    _mod("perspective_flip_theta", 0.0, CA, (-90, 90), "Flip Theta"),
    _mod("perspective_flip_phi", 0.0, CA, (-90, 90), "Flip Phi"),
    _mod("perspective_flip_gamma", 0.0, CA, (-90, 90), "Flip Gamma"),
    _mod("perspective_flip_fv", 53.0, CA, (10, 120), "Flip FV", (0.001, None)),
    # Diffusion
    _mod("strength_schedule", 0.65, DI, (0, 1), "Strength (keep of previous frame)", (0, 1)),
    _mod("noise_schedule", 0.02, DI, (0, 0.2), "Noise", (0, 1)),
    _mod("contrast_schedule", 1.0, DI, (0.8, 1.2), "Contrast", (0, None)),
    _mod("cfg_scale_schedule", 1.8, DI, (1, 15), "CFG Scale (LCM: 1.5-2)", (0, None)),
    _mod("steps_schedule", 25.0, DI, (1, 50), "Steps (needs Enable Steps Scheduling)", (1, None)),
    _mod("noise_multiplier_schedule", 1.0, DI, (0.9, 1.2), "Noise Multiplier", (0, None)),
    _mod("subseed_strength_schedule", 0.0, DI, (0, 1), "Subseed Strength (needs Enable Subseed)", (0, 1)),
    _mod("ddim_eta_schedule", 0.0, DI, (0, 1), "DDIM Eta (needs Enable)", (0, None)),
    _mod("ancestral_eta_schedule", 1.0, DI, (0, 1.5), "Ancestral Eta (needs Enable)", (0, None)),
    _mod("clipskip_schedule", 2.0, DI, (1, 4), "CLIP Skip (needs Enable)", (1, 12)),
    # Flow & anti-blur (kernel is a plain odd INT: OpenCV rejects even blur sizes)
    _mod("cadence_flow_factor_schedule", 1.0, FL, (0, 2), "Cadence Flow Factor", (0, None)),
    _mod("redo_flow_factor_schedule", 1.0, FL, (0, 2), "Redo Flow Factor", (0, None)),
    _mod("amount_schedule", 0.1, FL, (0, 1), "Anti-blur Amount", (0, None)),
    _mod("sigma_schedule", 1.0, FL, (0.1, 5), "Anti-blur Sigma", (0, None)),
    _mod("threshold_schedule", 0.0, FL, (0, 1), "Anti-blur Threshold", (0, None)),
]
MOD_APIS = [f.api for f in _MODS]
MOD_LABELS = [f.label for f in _MODS]
SCHEDULE_APIS = MOD_APIS   # bake / preview targets (kept for older callers)

_SLOT_TARGETS = ["zoom", "translation_z", "strength_schedule", "noise_schedule",
                 "rotation_3d_y", "angle", "cfg_scale_schedule", "translation_x"]


def _slot_fields(n):
    p = "mod%d_" % n
    return [
        F(p + "active", False, MM, TOGGLE, label="Slot %d On" % n, target=None),
        F(p + "target", _SLOT_TARGETS[(n - 1) % len(_SLOT_TARGETS)], MM, MENU, menu=MOD_APIS,
          labels=MOD_LABELS, label="Slot %d Target" % n, target=None),
        F(p + "shape", "sine", MM, MENU, menu=modulation.SHAPE_NAMES, labels=modulation.SHAPE_LABELS,
          label="Slot %d Shape" % n, target=None),
        F(p + "beats", 1.0, MM, FLOAT, norm=(0.25, 16), label="Slot %d Cycle (beats)" % n, target=None),
        F(p + "depth", 0.0, MM, FLOAT, norm=(-1, 1), label="Slot %d Depth" % n, target=None),
        F(p + "phase", 0.0, MM, FLOAT, norm=(0, 1), label="Slot %d Phase (cycles)" % n, target=None),
        F(p + "sharpness", 4.0, MM, FLOAT, norm=(0.5, 16), label="Slot %d Sharpness" % n, target=None),
    ]


def _cn_unit_fields(n):
    """ControlNet unit n: the Deforum cn_n_* keys, plus the TD-only feed_n_* guide source."""
    p, page = "cn_%d_" % n, PAGE_CNS[n - 1]
    f = "feed_%d_" % n
    return [
        F(p + "enabled", False, page, TOGGLE),
        F(f + "mode", feed.FILE, page, MENU, menu=feed.MODES, labels=feed.MODE_LABELS,
          label="Guide Source", target=None),
        F(f + "top", "", page, STR, label="Source TOP (path, e.g. /project1/final_out)", target=None),
        F(f + "info", "", page, STATUS, label="Last Feed", target=None),
        F(p + "module", "none", page, STR),
        F(p + "model", "ctrl_v1p_qr_monster_v2", page, STR),
        F(p + "vid_path", "/opt/a1111/td_masks/mask_01.mov", page, STR),
        F(p + "mask_vid_path", "", page, STR),
        F(p + "weight", 1.0, page, FLOAT, norm=(0, 2), as_schedule=True),
        F(p + "guidance_start", 0.0, page, FLOAT, norm=(0, 1), as_schedule=True),
        F(p + "guidance_end", 1.0, page, FLOAT, norm=(0, 1), as_schedule=True),
        F(p + "processor_res", 512, page, INT, norm=(64, 2048)),
        F(p + "threshold_a", 0.5, page, FLOAT, norm=(0, 255)),
        F(p + "threshold_b", 0.5, page, FLOAT, norm=(0, 255)),
        F(p + "resize_mode", "Inner Fit (Scale to Fit)", page, MENU,
          menu=["Inner Fit (Scale to Fit)", "Outer Fit (Shrink to Fit)", "Just Resize"]),
        F(p + "control_mode", "Balanced", page, MENU,
          menu=["Balanced", "My prompt is more important", "ControlNet is more important"]),
        F(p + "low_vram", False, page, TOGGLE),
        F(p + "pixel_perfect", True, page, TOGGLE),
        F(p + "overwrite_frames", True, page, TOGGLE),
        F(p + "loopback_mode", False, page, TOGGLE),
    ]


FIELDS = [
    # --- Tempo -----------------------------------------------------------------
    F("preset", presets.NONE, TE, MENU, menu=presets.NAMES, labels=presets.LABELS,
      label="Example Preset (applied when picked)", target=None),
    F("preset_apply", 0, TE, PULSE, label="Re-apply Preset", target=None),
    F("preset_info", "", TE, STATUS, label="Preset", target=None),
    F("bpm", 120.0, TE, FLOAT, norm=(60, 200), label="BPM", target=None),
    F("beats_per_bar", 4, TE, INT, norm=(1, 8), label="Beats per Bar", target=None),
    F("loop_bars", 2, TE, INT, norm=(1, 16), label="Loop Length (bars)", target=None),
    F("out_fps", 60, TE, INT, norm=(24, 60), label="Output FPS", target=None),
    F("render_strategy", "cadence", TE, MENU, menu=tempo.STRATEGIES, labels=tempo.STRATEGY_LABELS,
      label="Render Strategy", target=None),
    F("render_fps", "30", TE, MENU, menu=tempo.RENDER_FPS_CHOICES, label="Render FPS (interpolate)",
      target=None),
    F("interp_engine", "RIFE v4.6", TE, MENU, menu=tempo.INTERP_ENGINES, label="Interpolation Engine",
      target=None),
    F("diffusion_cadence", 4, TE, INT, norm=(1, 8), label="Diffusion Cadence (diffuse every Nth frame)"),
    F("seamless_loop", True, TE, TOGGLE, label="Seamless Loop", target=None),
    F("loop_overlap_beats", 1.0, TE, FLOAT, norm=(0, 4), label="Loop Overlap (beats, crossfaded)", target=None),
    F("loop_seeds", False, TE, TOGGLE, label="Loop Seeds (schedule seeds to repeat per loop; off = Iterate +1)",
      target=None),
    F("length_source", "tempo", TE, MENU, menu=["tempo", "manual"],
      labels=["Tempo (loop length)", "Manual (Max Frames)"], target=None),
    F("max_frames", 240, TE, INT, norm=(1, 1000), label="Max Frames (manual)"),
    F("tempo_info", "", TE, STATUS, label="Plan", target=None),

    # --- Globals ---------------------------------------------------------------
    F("sd_model_checkpoint", "0", G, CHECKPOINT, label="Model (index / schedule)"),
    F("sd_vae", "Automatic", G, STR, label="VAE", target="options"),
    F("W", 1024, G, INT, norm=(0, 1920)),
    F("H", 576, G, INT, norm=(0, 1920)),
    F("steps", 4, G, INT, norm=(1, 50), label="Steps (LCM: 4)"),
    # A1111 runs only int(steps x denoise) steps on img2img frames (4 steps at Strength 0.65 = 1
    # step); with this on it runs exactly `steps`, which is what LCM checkpoints need.
    F("img2img_fix_steps", True, G, TOGGLE, label="Exact Steps on every frame (A1111 img2img_fix_steps)",
      target="options"),
    F("sampler", "LCM", G, STR),
    F("scheduler", "Automatic", G, STR),
    F("animation_mode", "3D", G, MENU, menu=["2D", "3D", "Video Input", "Interpolation"]),
    F("seed_behavior", "iter", G, MENU,
      menu=["iter", "fixed", "random", "ladder", "alternate", "schedule"],
      labels=["Iterate (+1)", "Fixed", "Random", "Ladder", "Alternate", "Schedule"]),
    F("seed", "424242", G, SEED),
    # Deforum ignores "n_prompt"; the API reads animation_prompts_negative.
    F("n_prompt", "worst quality, low quality, glitch, deformed, mutated, ugly, messy, text, watermark",
      G, STR, label="Negative Prompt", key="animation_prompts_negative"),
    F("strength", 0.8, G, FLOAT, norm=(0, 1), label="Init Strength (first frame)"),
    F("use_mask_video", False, G, TOGGLE),
    F("invert_mask", False, G, TOGGLE, label="Invert Mask (diffuse the black areas instead)"),
    F("overlay_mask", False, G, TOGGLE, label="Overlay Mask (keep the original outside the mask)"),
    F("video_init_path", "/opt/a1111/td_inputs/comfy_videos/archive/taichi_portrait.mp4", G, STR),
    F("video_mask_path", "/opt/a1111/td_masks/mask_01.mov", G, STR),
    F("video_frame_mode", "trim", G, MENU, menu=["trim", "stride"],
      labels=["Trim (Normal Speed)", "Stride (Timelapse)"], target=None),

    # --- Prompts ---------------------------------------------------------------
    F("prompt_source", "sequence", PR, MENU, menu=["sequence", "json"],
      labels=["Beat sequence (prompt_seq table)", "prompt.json (frame keys)"], target=None),
    F("prompt_preset", prompt_presets.NONE, PR, MENU, menu=prompt_presets.NAMES, labels=prompt_presets.LABELS,
      label="Prompt Preset (writes prompt_seq)", target=None),
    F("prompt_edit", 0, PR, PULSE, label="Edit prompt_seq (opens deforum/prompt_seq)", target=None),
    F("prompt_xfade_beats", 1.0, PR, FLOAT, norm=(0, 8), label="Default Crossfade (beats)", target=None),

    # --- Motion 2D -------------------------------------------------------------
    F("border", "replicate", M2, MENU, menu=["replicate", "wrap"],
      labels=["Clamp / Hold (Replicate)", "Wrap / Tile"]),
] + [f for f in _MODS if f.page == M2] + [

    # --- Motion 3D -------------------------------------------------------------
    F("padding_mode", "border", M3, MENU, menu=["border", "reflection", "zeros"],
      labels=["Border (smear)", "Reflection (mirror)", "Zeros (black)"]),
    F("sampling_mode", "bicubic", M3, MENU, menu=["bicubic", "bilinear", "nearest"]),
] + [f for f in _MODS if f.page == M3] + [

    # --- Camera & Depth ---------------------------------------------------------
    F("use_depth_warping", True, CA, TOGGLE),
    F("depth_algorithm", "Midas-3-Hybrid", CA, MENU, menu=DEPTH_ALGORITHMS),
    F("midas_weight", 0.2, CA, FLOAT, norm=(0, 1)),
    # Without this toggle Deforum ignores every perspective_flip_* schedule (2D and 3D).
    F("enable_perspective_flip", False, CA, TOGGLE),
] + [f for f in _MODS if f.page == CA] + [

    # --- Diffusion ---------------------------------------------------------------
    F("enable_steps_scheduling", False, DI, TOGGLE),
    F("enable_noise_multiplier_scheduling", True, DI, TOGGLE),
    F("enable_subseed_scheduling", False, DI, TOGGLE),
    F("subseed_schedule", "0:(1)", DI, SCHEDULE),
    F("enable_ddim_eta_scheduling", False, DI, TOGGLE, label="Enable DDIM Eta Scheduling"),
    F("enable_ancestral_eta_scheduling", False, DI, TOGGLE),
    F("enable_clipskip_scheduling", False, DI, TOGGLE, label="Enable CLIP Skip Scheduling"),
] + [f for f in _MODS if f.page == DI] + [

    # --- Noise & Color -----------------------------------------------------------
    F("noise_type", "perlin", NO, MENU, menu=["perlin", "uniform"]),
    F("perlin_w", 8, NO, INT, norm=(1, 16), label="Perlin W"),
    F("perlin_h", 8, NO, INT, norm=(1, 16), label="Perlin H"),
    F("perlin_octaves", 4, NO, INT, norm=(1, 7)),
    F("perlin_persistence", 0.5, NO, FLOAT, norm=(0, 1)),
    F("color_coherence", "LAB", NO, MENU, menu=["None", "HSV", "LAB", "RGB", "Video Input", "Image"]),
    F("color_force_grayscale", False, NO, TOGGLE),
    # Deforum's API turns this ON whenever the key is missing (deprecation_utils), which it
    # was in every earlier payload; kept on so existing looks don't shift. Deforum's UI
    # default (and recommendation for coherence) is off.
    F("legacy_colormatch", True, NO, TOGGLE, label="Legacy Colormatch (earlier renders used it)"),

    # --- Flow & Anti-blur ----------------------------------------------------------
    F("optical_flow_cadence", "RAFT", FL, MENU, menu=FLOW_METHODS),
    F("optical_flow_redo_generation", "None", FL, MENU, menu=FLOW_METHODS),
    F("kernel_schedule", 5, FL, INT, norm=(1, 15), label="Anti-blur Kernel (odd)", as_schedule=True),

    # --- Hybrid Video (2D / 3D driven by the Video Init Path) -------------------------
    F("hybrid_motion", "None", HY, MENU, menu=HYBRID_MOTIONS,
      labels=["None", "Optical Flow (move like the video)", "Perspective (camera of the video)",
              "Affine (camera of the video)"], label="Hybrid Motion"),
    F("hybrid_flow_method", "RAFT", HY, MENU, menu=["RAFT", "DIS Medium", "DIS Fine", "Farneback"]),
    F("hybrid_motion_use_prev_img", False, HY, TOGGLE, label="Flow from the previous generated image"),
    F("hybrid_flow_consistency", False, HY, TOGGLE),
    F("hybrid_consistency_blur", 2, HY, INT, norm=(0, 16)),
    F("hybrid_flow_factor_schedule", 1.0, HY, FLOAT, norm=(0, 2), as_schedule=True, label="Hybrid Flow Factor"),
    F("hybrid_composite", "None", HY, MENU, menu=HYBRID_COMPOSITES, label="Hybrid Composite (mix the video in)"),
    F("hybrid_comp_alpha_schedule", 0.5, HY, FLOAT, norm=(0, 1), as_schedule=True, label="Composite Alpha"),
] + [f for f in _MODS if f.page == FL] + [

    # --- Mod Matrix ----------------------------------------------------------------
    F("chop_mode", "add", MM, MENU, menu=modulation.CHOP_MODES,
      labels=["Add to base", "Replace base"], label="Mod CHOP Mode", target=None),
    F("chop_path", "", MM, STR, label="Mod CHOP (empty = COMP input 1)", target=None),
    F("bake_points", 0, MM, INT, norm=(0, 256), label="CHOP Bake Points (0 = every frame)", target=None),
] + [f for n in range(1, MOD_SLOTS + 1) for f in _slot_fields(n)] + [

    # --- Sweep Depth (Animation Mode = Video Input) -----------------------------------
    F("sweep_enabled", False, SW, TOGGLE, label="Sweep Depth On", target=None),
    F("sweep_mode", sweep.MAX, SW, MENU, menu=sweep.MODES, labels=sweep.MODE_LABELS, label="Mode", target=None),
    F("sweep_cycles", 1.0, SW, FLOAT, norm=(0.25, 16), label="Cycles (sweeps over the render)", target=None),
    F("sweep_shape", sweep.RAMP, SW, MENU, menu=sweep.SHAPES, labels=sweep.SHAPE_LABELS, label="Shape",
      target=None),
    F("sweep_direction", sweep.FORWARD, SW, MENU, menu=sweep.DIRECTIONS, labels=sweep.DIRECTION_LABELS,
      label="Direction", target=None),
    F("sweep_width", 10, SW, INT, norm=(1, 128), label="Band Width (grey levels of 255)", target=None),
    F("sweep_softness", 0, SW, INT, norm=(0, 64), label="Edge Softness (grey levels)", target=None),
    F("sweep_grow", 0, SW, INT, norm=(0, 48), label="Grow (px, widens the band shapes)", target=None),
    F("sweep_blur", 0.0, SW, FLOAT, norm=(0, 24), label="Blur (px, soft glow for ControlNet)", target=None),
    F("sweep_trail", 0, SW, INT, norm=(0, 60), label="Trail (frames the band glows on, 0 = off)",
      target=None),
    F("sweep_smooth", 0.0, SW, FLOAT, norm=(0, 0.9), label="Depth Smoothing (steadier band, 0 = off)",
      target=None),
    F("sweep_fill", sweep.WHITE, SW, MENU, menu=sweep.FILLS, labels=sweep.FILL_LABELS, label="Band Fill",
      target=None),
    F("sweep_as_mask", False, SW, TOGGLE, label="Also use as Video Mask", target=None),
    F("sweep_model", sweep.MODELS[0], SW, MENU, menu=sweep.MODELS, labels=sweep.MODEL_LABELS,
      label="Depth Model (ComfyUI)", target=None),
    F("sweep_depth_video", "", SW, STR,
      label="Pre-made Depth Video (container path; empty = make it from Video Init Path)", target=None),
    F("sweep_prepare_only", False, SW, TOGGLE,
      label="Queue only prepares the sweep (depth + mask video, no render)", target=None),
    F("sweep_depth_path", "", SW, STATUS, label="Depth Video", target=None),
    F("sweep_info", "", SW, STATUS, label="Sweep Plan", target=None),
    F("sweep_show_latest", 0, SW, PULSE, label="Show Latest Sweep (sweep_preview / COMP output 2)", target=None),
] \
  + [f for n in range(1, CN_UI_UNITS + 1) for f in _cn_unit_fields(n)] + [
    # --- ControlNet Unit 1: ComfyUI preprocessing of the init video ----------------
    F("comfy_preproc_enable", False, CN, TOGGLE, label="Preprocess via ComfyUI", target=None),
    F("comfy_preprocessor", "PiDiNetPreprocessor", CN, MENU, menu=COMFY_PREPROCESSORS, target=None),

    # --- Pipeline (TouchDesigner only) ----------------------------------------------
    F("pipeline_status", "idle", PL, STATUS, label="Status", target=None),
    F("auto_load", True, PL, TOGGLE, label="Auto-load finished render", target=None),
    F("force_preprocess", False, PL, TOGGLE, label="Force ComfyUI re-preprocess", target=None),
    F("loop_out_frames", "0", PL, STATUS, label="Loaded loop length (frames)", target=None),
    F("loop_out_overlap", "0", PL, STATUS, label="Loaded loop overlap (frames)", target=None),
    F("loop_out_rate", "1", PL, STATUS, label="Loaded file frames per output frame", target=None),
    F("loop_offset", 0, PL, INT, norm=(0, 480), label="Loop Player Offset (frames)", target=None),
    F("feed_loop_start", 0, PL, INT, norm=(0, 1000),
      label="Feed: loop start frame (0 = timeline start)", target=None),
    F("feed_method", feed.ADD_FRAME, PL, MENU, menu=feed.METHODS, labels=feed.METHOD_LABELS,
      label="Feed: recording method", target=None),
]

def _with_page_presets(fields):
    """A Page Preset menu at the top of each page that has presets (Tempo: below the Example Preset)."""
    out, done = [], set()
    for f in fields:
        page = f.page
        if page in page_presets.PAGES and page not in done and not (page == PAGE_TEMPO and f.api.startswith("preset")):
            done.add(page)
            out.append(F(page_presets.api(page), page_presets.NONE, page, MENU, menu=page_presets.names(page),
                         labels=page_presets.labels(page), label="Page Preset (%s)" % page, target=None))
        out.append(f)
    return out


FIELDS = _with_page_presets(FIELDS)
PAGE_PRESET_APIS = [page_presets.api(p) for p in PAGE_ORDER if p in page_presets.PAGES]

BY_API = dict((f.api, f) for f in FIELDS)
BY_TD = dict((f.td_name, f) for f in FIELDS)
MOD_FIELDS = [f for f in FIELDS if f.kind == MOD]

# TD parameter names that older builds created but which do nothing now.
# build_master_ui.py drops them; listed so the rebuild report can mention them.
RETIRED_TD_NAMES = {
    "Scale": "not a Deforum key (CFG comes from cfg_scale_schedule)",
    "Cfgscale": "not a Deforum key (CFG comes from cfg_scale_schedule)",
    "Baketarget": "replaced by the Mod CHOP: a channel named after a parameter modulates it",
}


def cn_fields(unit):
    prefix = "cn_%d_" % unit
    return [f for f in FIELDS if f.api.startswith(prefix)]


def slot_fields(n):
    prefix = "mod%d_" % n
    return [f for f in FIELDS if f.api.startswith(prefix)]


def all_td_names():
    """Every TD parameter the COMP has (MOD fields contribute two)."""
    names = []
    for f in FIELDS:
        names.append(f.td_name)
        if f.kind == MOD:
            names.append(f.raw_td_name)
    return names
