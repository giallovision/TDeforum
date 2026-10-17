"""Example configurations for the ``deforum`` COMP (the "Example Preset" drop-down, Tempo page).

A preset is a plain ``{api name: value}`` dict that is laid over the COMP's current values when
*bake* is pressed. It never edits the baselines in schema.py. td_controller.apply_preset() does
the TouchDesigner side:

* only constant parameters are changed (anything you have bound, exported or given an
  expression keeps its driver and is listed in the log);
* the values it replaces are remembered, so choosing another preset or **None** and pressing
  bake puts your previous values back first;
* motion parameters and Mod Matrix slots a preset does not mention are set to the baseline
  (RESET_KEYS), so an example always starts from a neutral camera, not from the last one;
* a MOD parameter's ``Raw`` override is cleared while the preset is on (a raw schedule would
  beat the preset's base value).

Never touched: the seed itself (424242), sampler, steps, CFG, size, model, prompts. Seed
*behaviour* stays Iterate (+1) except in the Video Input examples, which use Fixed (one seed for
every video frame is what stops video-to-video from boiling). ControlNet is left alone too,
except by the "Depth sweep" examples, which switch Sweep Depth on and take over ControlNet unit 1
as its guide (they need Globals > Video Init Path and are put back like everything else when you
choose None).

Units, at the 60 fps default: translation is Deforum units per frame (``translate_xyz`` =
-translation / 200, positive Z = forward), rotation is degrees per frame, 2D zoom is a factor per
frame (1.003 = +20 % per second), Strength is how much of the previous frame is kept.
"""

NONE = "none"

GOOD, EXTREME = "good", "extreme"


class Preset(object):
    __slots__ = ("id", "label", "mode", "level", "notes", "values")

    def __init__(self, id, label, mode, level, notes, values):
        self.id, self.label, self.mode, self.level, self.notes = id, label, mode, level, notes
        self.values = values

    def __repr__(self):
        return "Preset(%s)" % self.id


# Motion that every example resets to the baseline unless it sets it. The Mod Matrix slots are
# switched off the same way (their ``modN_active`` toggles).
RESET_KEYS = [
    "zoom", "angle", "transform_center_x", "transform_center_y",
    "translation_x", "translation_y", "translation_z",
    "rotation_3d_x", "rotation_3d_y", "rotation_3d_z",
] + ["mod%d_active" % n for n in range(1, 9)]


def _slot(n, target, shape, beats, depth, sharpness=4.0, phase=0.0):
    p = "mod%d_" % n
    return {p + "active": True, p + "target": target, p + "shape": shape, p + "beats": beats,
            p + "depth": depth, p + "sharpness": sharpness, p + "phase": phase}


def _merge(*parts):
    out = {}
    for part in parts:
        out.update(part)
    return out


# Tuned for the LCM baseline: 4 steps run exactly on every frame (Globals > Exact Steps), CFG 1.8,
# sampler LCM. LCM resolves detail in very few steps, so fresh noise is kept low (it would show as
# grain that four steps cannot clean) and Strength does the work.
#
# Shared by the 2D / 3D "good" examples: keep most of the previous frame, a little perlin noise
# so detail keeps regenerating, cadence 4 with RAFT flow between diffused frames, LAB colour lock.
_SMOOTH = {
    "strength_schedule": 0.75, "noise_schedule": 0.015, "noise_multiplier_schedule": 1.0,
    "contrast_schedule": 1.0, "diffusion_cadence": 4, "optical_flow_cadence": "RAFT",
    "color_coherence": "LAB", "loop_overlap_beats": 2.0,
}
_3D = {"animation_mode": "3D", "use_depth_warping": True, "fov_schedule": 70.0, "midas_weight": 0.3,
       "padding_mode": "border"}
_2D = {"animation_mode": "2D", "border": "replicate"}
# Video Input restyles every video frame (cadence 1). A FIXED seed puts the same noise on every
# frame, which is what keeps a video-to-video render from boiling; Iterate (the 2D/3D baseline)
# gives each frame new noise and flickers here.
_VIDEO = {"animation_mode": "Video Input", "seamless_loop": False, "diffusion_cadence": 1,
          "optical_flow_cadence": "None", "noise_schedule": 0.0, "noise_multiplier_schedule": 1.0,
          "contrast_schedule": 1.0, "seed_behavior": "fixed"}
# Sweep Depth: the band video becomes ControlNet unit 1's guide (QR Monster). A widened, blurred
# band with a short trail reads as a glow to QR Monster instead of a hard stencil; guidance ends
# at 80 % so the last steps can put detail back over the shapes.
_SWEEP = {"sweep_enabled": True, "sweep_as_mask": False, "sweep_model": "depth_anything_v2_vits",
          "sweep_width": 18, "sweep_softness": 8, "sweep_grow": 6, "sweep_blur": 4.0, "sweep_fill": "white",
          "sweep_shape": "ramp", "sweep_direction": "forward", "sweep_cycles": 1.0,
          "sweep_trail": 8, "sweep_smooth": 0.4,
          "feed_1_mode": "sweep", "cn_1_enabled": True, "cn_1_module": "none",
          "cn_1_model": "ctrl_v1p_qr_monster_v2", "cn_1_weight": 0.75, "cn_1_guidance_start": 0.0,
          "cn_1_guidance_end": 0.8, "cn_1_control_mode": "Balanced",
          "strength_schedule": 0.55, "color_coherence": "LAB"}

PRESETS = [
    # ------------------------------------------------------------------ 3D
    Preset("3d_tunnel_roll", "3D - Tunnel roll (good)", "3D", GOOD,
           "Steady forward push with a slow roll; high keep so it flows like a QR tunnel.",
           _merge(_SMOOTH, _3D, {"translation_z": 0.6, "rotation_3d_z": 0.04})),
    Preset("3d_slow_orbit", "3D - Slow orbit (good)", "3D", GOOD,
           "Gentle pan around the scene with mirrored edges so nothing smears at the border.",
           _merge(_SMOOTH, _3D, {"rotation_3d_y": 0.12, "translation_x": 0.15, "translation_z": 0.2,
                                 "fov_schedule": 60.0, "padding_mode": "reflection"})),
    Preset("3d_kick_push", "3D - Kick push (good)", "3D", GOOD,
           "Slow drift forward plus a push on every beat (Mod slot 1) that also loosens Strength "
           "on the hit (slot 2), so the kick regenerates detail.",
           _merge(_SMOOTH, _3D, {"translation_z": 0.25, "strength_schedule": 0.78},
                  _slot(1, "translation_z", "decay", 1.0, 1.2, 5.0),
                  _slot(2, "strength_schedule", "decay", 1.0, -0.15, 5.0))),
    Preset("3d_warp_drive", "3D - Warp drive (extreme)", "3D", EXTREME,
           "Fast push, wide FOV and a surge every 4 beats. Expect stretching; cadence 2 keeps up.",
           _merge(_SMOOTH, _3D, {"translation_z": 3.0, "rotation_3d_z": 0.15, "fov_schedule": 95.0,
                                 "midas_weight": 0.5, "strength_schedule": 0.6, "noise_schedule": 0.03,
                                 "diffusion_cadence": 2, "contrast_schedule": 1.02},
                  _slot(1, "translation_z", "sine", 4.0, 1.5))),
    Preset("3d_vortex", "3D - Vortex (extreme)", "3D", EXTREME,
           "Fast roll while pushing in and tilting; the picture spirals and re-forms.",
           _merge(_SMOOTH, _3D, {"rotation_3d_z": 0.9, "rotation_3d_x": 0.2, "translation_z": 1.2,
                                 "fov_schedule": 80.0, "strength_schedule": 0.55, "noise_schedule": 0.04,
                                 "diffusion_cadence": 2, "padding_mode": "reflection"})),
    Preset("3d_strobe_push", "3D - Strobe push (extreme)", "3D", EXTREME,
           "Hard pushes on every half beat, a contrast flash and a Strength dip on the beat.",
           _merge(_SMOOTH, _3D, {"strength_schedule": 0.7, "noise_schedule": 0.03, "diffusion_cadence": 2},
                  _slot(1, "translation_z", "square", 0.5, 2.0, 8.0),
                  _slot(2, "contrast_schedule", "decay", 0.5, 0.06, 6.0),
                  _slot(3, "strength_schedule", "decay", 1.0, -0.3, 5.0))),
    # ------------------------------------------------------------------ 2D
    Preset("2d_zoom_drift", "2D - Zoom drift (good)", "2D", GOOD,
           "Slow zoom in with a hint of rotation; the classic smooth Deforum roll.",
           _merge(_SMOOTH, _2D, {"zoom": 1.003, "angle": 0.1})),
    Preset("2d_scroll", "2D - Scroll (good)", "2D", GOOD,
           "Sideways scroll with wrapped edges, so the picture tiles instead of smearing.",
           _merge(_SMOOTH, _2D, {"translation_x": 1.2, "strength_schedule": 0.78, "border": "wrap"})),
    Preset("2d_spiral_crash", "2D - Spiral crash (extreme)", "2D", EXTREME,
           "Fast zoom and spin with low keep: the image keeps collapsing into new structure.",
           _merge(_SMOOTH, _2D, {"zoom": 1.02, "angle": 1.2, "strength_schedule": 0.5,
                                 "noise_schedule": 0.05, "diffusion_cadence": 2, "contrast_schedule": 1.01})),
    Preset("2d_twirl", "2D - Twirl (extreme)", "2D", EXTREME,
           "Spin swings left and right over 4 beats (slot 1) while every beat pulses the zoom (slot 2).",
           _merge(_SMOOTH, _2D, {"zoom": 1.008, "strength_schedule": 0.6, "noise_schedule": 0.03,
                                 "diffusion_cadence": 2, "border": "wrap"},
                  _slot(1, "angle", "sine", 4.0, 2.5),
                  _slot(2, "zoom", "decay", 1.0, 0.02, 5.0))),
    # ------------------------------------------------------------------ Video Input
    Preset("video_soft_restyle", "Video Input - Soft restyle (good)", "Video Input", GOOD,
           "Every video frame restyled with the same seed: keeps the video's structure and colour, no "
           "boiling (needs Globals > Video Init Path).",
           _merge(_VIDEO, {"strength_schedule": 0.6, "color_coherence": "Video Input"})),
    Preset("video_melt", "Video Input - Melt (extreme)", "Video Input", EXTREME,
           "Loose hold on the video and a new seed every frame: heavy restyle that boils on purpose.",
           _merge(_VIDEO, {"strength_schedule": 0.35, "noise_schedule": 0.05, "seed_behavior": "iter",
                           "color_coherence": "None"})),
    Preset("video_depth_sweep_away", "Video Input - Depth sweep away (good)", "Video Input", GOOD,
           "One slow sweep: a soft glowing band starts on the nearest depth (white) and travels to the "
           "farthest, so it seems to move away from you. Needs Globals > Video Init Path; takes over "
           "ControlNet unit 1.",
           _merge(_VIDEO, _SWEEP, {"sweep_mode": "max"})),
    Preset("video_depth_sweep_toward", "Video Input - Depth sweep toward (good)", "Video Input", GOOD,
           "The same, the other way: the band starts on the farthest depth and ends on the nearest, so it "
           "seems to rush toward you.",
           _merge(_VIDEO, _SWEEP, {"sweep_mode": "min"})),
    Preset("video_depth_sweep_pulses", "Video Input - Depth sweep pulses (extreme)", "Video Input", EXTREME,
           "Four out-and-back sweeps of a wide band that keeps the depth shading and leaves long trails; "
           "ControlNet leads, so the picture pulses through the depth layers.",
           _merge(_VIDEO, _SWEEP, {"strength_schedule": 0.42, "noise_schedule": 0.03,
                                   "sweep_mode": "min", "sweep_cycles": 4.0, "sweep_shape": "pingpong",
                                   "sweep_width": 28, "sweep_fill": "depth", "sweep_softness": 12,
                                   "sweep_grow": 10, "sweep_blur": 6.0, "sweep_trail": 16, "sweep_smooth": 0.3,
                                   "cn_1_weight": 1.1, "cn_1_guidance_end": 1.0,
                                   "cn_1_control_mode": "ControlNet is more important"})),
]

BY_ID = dict((p.id, p) for p in PRESETS)
NAMES = [NONE] + [p.id for p in PRESETS]
LABELS = ["None"] + [p.label for p in PRESETS]


def get(name):
    """The Preset for a menu value; None for "none" / unknown names."""
    return BY_ID.get(str(name or "").strip())


def resolve(preset, defaults):
    """{api: value} to apply: the preset's values over the baseline for every RESET key.

    ``defaults`` maps api name -> baseline value (schema defaults). Only RESET_KEYS fall back
    to the baseline; everything else is touched only when the preset names it.
    """
    out = {}
    for key in RESET_KEYS:
        if key in defaults:
            out[key] = defaults[key]
    out.update(preset.values)
    return out
