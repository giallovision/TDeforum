"""Single source of truth for the Deforum_UI custom parameters.

build_master_ui.py builds the TouchDesigner pages from FIELDS, and payload.py
reads the same FIELDS to decide what is sent to Deforum and under which key.
Add a field here once and it appears in both places.

Field.target:
    "deforum"  -> deforum_settings[<key>]          (Deforum only reads keys it knows)
    "options"  -> options_overrides[<key>]         (A1111 opts for the batch)
    None       -> TouchDesigner-only (pipeline controls, status, ...)

TD parameter names are derived from the API name exactly as the original
build_master_ui.py did (``translation_z`` -> ``Translationz``), so existing
CHOP exports and expressions keep working.
"""

PAGE_GLOBALS = "Globals"
PAGE_MOTION = "Motion (2D/3D)"
PAGE_SCHEDULES = "Schedules"
PAGE_PERSPECTIVE = "Perspective 3D"
PAGE_CN1 = "ControlNet Unit 1"
PAGE_ADVANCED = "Advanced Setup"
PAGE_PIPELINE = "Pipeline"

PAGE_ORDER = [PAGE_GLOBALS, PAGE_MOTION, PAGE_SCHEDULES, PAGE_PERSPECTIVE,
              PAGE_CN1, PAGE_ADVANCED, PAGE_PIPELINE]

# Kinds understood by build_master_ui.py and payload.py
STR, INT, FLOAT, TOGGLE, MENU = "str", "int", "float", "toggle", "menu"
SCHEDULE = "schedule"      # string par; plain numbers are wrapped as 0:(v)
SEED = "seed"              # string par (seeds overflow TD int pars); sent as int
CHECKPOINT = "checkpoint"  # index / filename / schedule -> checkpoint_schedule
STATUS = "status"          # read-only string written by the controller


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
    label = api_name.replace("_", " ").title()
    if label.startswith("Cn 1 "):
        label = label[len("Cn 1 "):]
    return label


class Field(object):
    __slots__ = ("api", "default", "page", "kind", "menu", "labels", "label",
                 "target", "key", "expr", "norm", "as_schedule")

    def __init__(self, api, default, page, kind, menu=None, labels=None, label=None,
                 target="deforum", key=None, expr=None, norm=None, as_schedule=False):
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

    @property
    def td_name(self):
        return td_name(self.api)

    def __repr__(self):
        return "Field(%s -> %s)" % (self.api, self.td_name)


F = Field
G, MO, SC, PE, CN, AD, PL = (PAGE_GLOBALS, PAGE_MOTION, PAGE_SCHEDULES,
                             PAGE_PERSPECTIVE, PAGE_CN1, PAGE_ADVANCED, PAGE_PIPELINE)

COMFY_PREPROCESSORS = [
    "DWPreprocessor", "DepthAnythingV2Preprocessor", "SAMPreprocessor",
    "LineArtPreprocessor", "CannyEdgePreprocessor", "HEDPreprocessor",
    "PiDiNetPreprocessor", "M-LSDPreprocessor",
]

_SCHEDULE_FIELDS = [
    # (api, default, page)
    ("zoom", "0:(1.0)", MO), ("angle", "0:(0)", MO),
    ("translation_x", "0:(0)", MO), ("translation_y", "0:(0)", MO), ("translation_z", "0:(0)", MO),
    ("rotation_3d_x", "0:(0)", MO), ("rotation_3d_y", "0:(0)", MO), ("rotation_3d_z", "0:(0)", MO),
    ("transform_center_x", "0:(0.5)", MO), ("transform_center_y", "0:(0.5)", MO),
    ("noise_schedule", "0: (0.065)", SC), ("strength_schedule", "0: (0.8)", SC),
    ("contrast_schedule", "0: (1.0)", SC), ("cfg_scale_schedule", "0: (2.0)", SC),
    ("perspective_flip_theta", "0:(0)", PE), ("perspective_flip_phi", "0:(0)", PE),
    ("perspective_flip_gamma", "0:(0)", PE), ("perspective_flip_fv", "0:(50)", PE),
    ("fov_schedule", "0: (70)", PE), ("near_schedule", "0: (200)", PE),
    ("far_schedule", "0: (10000)", PE),
]
SCHEDULE_APIS = [api for api, _d, _p in _SCHEDULE_FIELDS]

FIELDS = [
    # --- Globals --------------------------------------------------------------
    F("sd_model_checkpoint", "0", G, CHECKPOINT, label="Model (index / schedule)"),
    F("sd_vae", "Automatic", G, STR, label="VAE", target="options"),
    F("W", 1024, G, INT, norm=(0, 1920)),
    F("H", 576, G, INT, norm=(0, 1920)),
    F("steps", 10, G, INT, norm=(1, 50)),
    F("max_frames", 240, G, INT, norm=(0, 1000), expr="me.time.end"),
    F("sampler", "LCM", G, STR),
    F("animation_mode", "Video Input", G, MENU, menu=["2D", "3D", "Video Input", "Interpolation"]),
    F("seed_behavior", "fixed", G, MENU,
      menu=["iter", "fixed", "random", "ladder", "alternate", "schedule"],
      labels=["Iterate (+1)", "Fixed", "Random", "Ladder", "Alternate", "Schedule"]),
    F("seed", "8675309", G, SEED),
    # Deforum ignores "n_prompt"; the API reads animation_prompts_negative.
    F("n_prompt", "worst quality, low quality, glitch, deformed, mutated, ugly, messy, text, watermark",
      G, STR, label="Negative Prompt", key="animation_prompts_negative"),
    F("use_mask_video", True, G, TOGGLE),
    F("video_init_path", "/opt/a1111/td_inputs/comfy_videos/archive/taichi_portrait.mp4", G, STR),
    F("video_mask_path", "/opt/a1111/td_masks/mask_01.mov", G, STR),
    F("video_frame_mode", "trim", G, MENU, menu=["trim", "stride"],
      labels=["Trim (Normal Speed)", "Stride (Timelapse)"], target=None),

    # --- Motion -------------------------------------------------------------------
    F("border", "replicate", MO, MENU, menu=["replicate", "wrap", "zeros"],
      labels=["Clamp / Hold (Replicate)", "Wrap / Tile", "Black (Zeros)"]),
] + [F(api, d, p, SCHEDULE) for api, d, p in _SCHEDULE_FIELDS if p == MO] + [

    # --- Schedules -----------------------------------------------------------------
] + [F(api, d, p, SCHEDULE) for api, d, p in _SCHEDULE_FIELDS if p == SC] + [

    # --- Perspective 3D ----------------------------------------------------------
    # Without this toggle Deforum ignores every perspective_flip_* schedule.
    F("enable_perspective_flip", False, PE, TOGGLE),
] + [F(api, d, p, SCHEDULE) for api, d, p in _SCHEDULE_FIELDS if p == PE] + [

    # --- ControlNet Unit 1 ---------------------------------------------------------
    F("cn_1_enabled", False, CN, TOGGLE),
    F("cn_1_module", "none", CN, STR),
    F("cn_1_model", "ctrl_v1p_qr_monster_v2", CN, STR),
    F("cn_1_vid_path", "/opt/a1111/td_masks/mask_01.mov", CN, STR),
    F("cn_1_mask_vid_path", "", CN, STR),
    F("cn_1_weight", 1.0, CN, FLOAT, norm=(0, 2), as_schedule=True),
    F("cn_1_guidance_start", 0.0, CN, FLOAT, norm=(0, 1), as_schedule=True),
    F("cn_1_guidance_end", 1.0, CN, FLOAT, norm=(0, 1), as_schedule=True),
    F("cn_1_processor_res", 512, CN, INT, norm=(64, 2048)),
    F("cn_1_threshold_a", 0.5, CN, FLOAT, norm=(0, 255)),
    F("cn_1_threshold_b", 0.5, CN, FLOAT, norm=(0, 255)),
    F("cn_1_resize_mode", "Inner Fit (Scale to Fit)", CN, MENU,
      menu=["Inner Fit (Scale to Fit)", "Outer Fit (Shrink to Fit)", "Just Resize"]),
    F("cn_1_control_mode", "Balanced", CN, MENU,
      menu=["Balanced", "My prompt is more important", "ControlNet is more important"]),
    F("cn_1_low_vram", False, CN, TOGGLE),
    F("cn_1_pixel_perfect", True, CN, TOGGLE),
    F("cn_1_overwrite_frames", True, CN, TOGGLE),
    F("cn_1_loopback_mode", False, CN, TOGGLE),
    # ComfyUI preprocessing of the init video into the CN1 guide video.
    F("comfy_preproc_enable", False, CN, TOGGLE, label="Preprocess via ComfyUI", target=None),
    F("comfy_preprocessor", "PiDiNetPreprocessor", CN, MENU, menu=COMFY_PREPROCESSORS, target=None),

    # --- Advanced -------------------------------------------------------------------
    F("strength", 0.8, AD, FLOAT, norm=(0, 1)),
    F("diffusion_cadence", 2, AD, INT, norm=(1, 8)),
    F("optical_flow_cadence", "RAFT", AD, MENU,
      menu=["None", "RAFT", "DIS Medium", "DIS Fine", "Farneback"]),

    # --- Pipeline (TouchDesigner only) ----------------------------------------------
    F("pipeline_status", "idle", PL, STATUS, label="Status", target=None),
    F("auto_load", True, PL, TOGGLE, label="Auto-load finished render", target=None),
    F("force_preprocess", False, PL, TOGGLE, label="Force ComfyUI re-preprocess", target=None),
    F("bake_points", 32, PL, INT, label="Bake points (0 = every frame)", norm=(0, 256), target=None),
    F("bake_target", "none", PL, MENU, label="Bake into",
      menu=["none"] + SCHEDULE_APIS,
      labels=["bake_out DAT only"] + [a.replace("_", " ").title() for a in SCHEDULE_APIS],
      target=None),
]

BY_API = dict((f.api, f) for f in FIELDS)
BY_TD = dict((f.td_name, f) for f in FIELDS)

# TD parameter names that older builds created but which do nothing in Deforum.
# build_master_ui.py drops them; listed so the rebuild report can mention them.
RETIRED_TD_NAMES = {
    "Scale": "not a Deforum key (CFG comes from cfg_scale_schedule)",
    "Cfgscale": "not a Deforum key (CFG comes from cfg_scale_schedule)",
}


def cn_fields(unit):
    prefix = "cn_%d_" % unit
    return [f for f in FIELDS if f.api.startswith(prefix)]
