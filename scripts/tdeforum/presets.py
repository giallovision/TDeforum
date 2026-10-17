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

Never touched: seed and seed behaviour (the baseline is Iterate +1, seed 424242), sampler,
steps, CFG, size, model, prompts. ControlNet is left alone too, except by the "Depth sweep"
examples, which switch Sweep Depth on and take over ControlNet unit 1 as its guide (they need
Globals > Video Init Path and are put back like everything else when you choose None).

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


# Shared by the "good" examples: carry most of the previous frame, almost no fresh noise, the
# depth warp helps the camera move. Extremes override what they push.
_SMOOTH = {
    "strength_schedule": 0.78, "noise_schedule": 0.02, "noise_multiplier_schedule": 1.0,
    "contrast_schedule": 1.0, "diffusion_cadence": 4, "optical_flow_cadence": "RAFT",
    "color_coherence": "LAB", "loop_overlap_beats": 2.0,
}
_3D = {"animation_mode": "3D", "use_depth_warping": True, "fov_schedule": 70.0, "midas_weight": 0.3,
       "padding_mode": "border"}
_2D = {"animation_mode": "2D", "border": "replicate"}
_VIDEO = {"animation_mode": "Video Input", "seamless_loop": False, "diffusion_cadence": 1,
          "optical_flow_cadence": "None", "noise_multiplier_schedule": 1.0, "contrast_schedule": 1.0}
# Sweep Depth: the depth video's band is recorded as ControlNet unit 1's guide (QR Monster).
_SWEEP = {"sweep_enabled": True, "sweep_as_mask": False, "sweep_model": "DepthAnythingV2Preprocessor",
          "sweep_softness": 6, "sweep_fill": "white", "sweep_shape": "ramp", "sweep_direction": "forward",
          "feed_1_mode": "sweep", "cn_1_enabled": True, "cn_1_module": "none",
          "cn_1_model": "ctrl_v1p_qr_monster_v2", "cn_1_guidance_start": 0.0, "cn_1_guidance_end": 1.0,
          "cn_1_control_mode": "Balanced"}

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
           _merge(_SMOOTH, _3D, {"translation_z": 0.25, "strength_schedule": 0.8},
                  _slot(1, "translation_z", "decay", 1.0, 1.2, 5.0),
                  _slot(2, "strength_schedule", "decay", 1.0, -0.15, 5.0))),
    Preset("3d_warp_drive", "3D - Warp drive (extreme)", "3D", EXTREME,
           "Fast push, wide FOV and a surge every 4 beats. Expect stretching; cadence 2 keeps up.",
           _merge(_SMOOTH, _3D, {"translation_z": 3.0, "rotation_3d_z": 0.15, "fov_schedule": 95.0,
                                 "midas_weight": 0.5, "strength_schedule": 0.6, "noise_schedule": 0.04,
                                 "diffusion_cadence": 2, "contrast_schedule": 1.04},
                  _slot(1, "translation_z", "sine", 4.0, 1.5))),
    Preset("3d_vortex", "3D - Vortex (extreme)", "3D", EXTREME,
           "Fast roll while pushing in and tilting; the picture spirals and re-forms.",
           _merge(_SMOOTH, _3D, {"rotation_3d_z": 0.9, "rotation_3d_x": 0.2, "translation_z": 1.2,
                                 "fov_schedule": 80.0, "strength_schedule": 0.55, "noise_schedule": 0.06,
                                 "diffusion_cadence": 2, "padding_mode": "reflection"})),
    Preset("3d_strobe_push", "3D - Strobe push (extreme)", "3D", EXTREME,
           "Hard pushes on every half beat, a contrast flash and a Strength dip on the beat.",
           _merge(_SMOOTH, _3D, {"strength_schedule": 0.7, "noise_schedule": 0.05, "diffusion_cadence": 2},
                  _slot(1, "translation_z", "square", 0.5, 2.0, 8.0),
                  _slot(2, "contrast_schedule", "decay", 0.5, 0.08, 6.0),
                  _slot(3, "strength_schedule", "decay", 1.0, -0.3, 5.0))),
    # ------------------------------------------------------------------ 2D
    Preset("2d_zoom_drift", "2D - Zoom drift (good)", "2D", GOOD,
           "Slow zoom in with a hint of rotation; the classic smooth Deforum roll.",
           _merge(_SMOOTH, _2D, {"zoom": 1.003, "angle": 0.1})),
    Preset("2d_scroll", "2D - Scroll (good)", "2D", GOOD,
           "Sideways scroll with wrapped edges, so the picture tiles instead of smearing.",
           _merge(_SMOOTH, _2D, {"translation_x": 1.2, "strength_schedule": 0.8, "border": "wrap"})),
    Preset("2d_spiral_crash", "2D - Spiral crash (extreme)", "2D", EXTREME,
           "Fast zoom and spin with low keep: the image keeps collapsing into new structure.",
           _merge(_SMOOTH, _2D, {"zoom": 1.02, "angle": 1.2, "strength_schedule": 0.5,
                                 "noise_schedule": 0.08, "diffusion_cadence": 2, "contrast_schedule": 1.02})),
    Preset("2d_twirl", "2D - Twirl (extreme)", "2D", EXTREME,
           "Spin swings left and right over 4 beats (slot 1) while every beat pulses the zoom (slot 2).",
           _merge(_SMOOTH, _2D, {"zoom": 1.008, "strength_schedule": 0.6, "noise_schedule": 0.05,
                                 "diffusion_cadence": 2, "border": "wrap"},
                  _slot(1, "angle", "sine", 4.0, 2.5),
                  _slot(2, "zoom", "decay", 1.0, 0.02, 5.0))),
    # ------------------------------------------------------------------ Video Input
    Preset("video_soft_restyle", "Video Input - Soft restyle (good)", "Video Input", GOOD,
           "Keeps most of the init video's structure and colour; frames follow the video (needs "
           "Globals > Video Init Path).",
           _merge(_VIDEO, {"strength_schedule": 0.55, "noise_schedule": 0.0, "color_coherence": "Video Input"})),
    Preset("video_melt", "Video Input - Melt (extreme)", "Video Input", EXTREME,
           "Loose hold on the video: heavy restyle, extra noise, no colour matching.",
           _merge(_VIDEO, {"strength_schedule": 0.3, "noise_schedule": 0.1, "noise_multiplier_schedule": 1.1,
                           "color_coherence": "None"})),
    Preset("video_depth_sweep_away", "Video Input - Depth sweep away (good)", "Video Input", GOOD,
           "One slow sweep: a white band starts on the nearest levels (245-255) of the video's depth and "
           "ends on the farthest (0-10), so the glow seems to travel away from you. Needs Globals > "
           "Video Init Path; uses ControlNet unit 1.",
           _merge(_VIDEO, _SWEEP, {"strength_schedule": 0.6, "noise_schedule": 0.0, "color_coherence": "Video Input",
                                   "sweep_mode": "max", "sweep_cycles": 1.0, "sweep_width": 14,
                                   "cn_1_weight": 0.9})),
    Preset("video_depth_sweep_toward", "Video Input - Depth sweep toward (good)", "Video Input", GOOD,
           "The same, the other way: the band starts on the farthest levels and ends on the nearest, so it "
           "seems to rush toward you.",
           _merge(_VIDEO, _SWEEP, {"strength_schedule": 0.6, "noise_schedule": 0.0, "color_coherence": "Video Input",
                                   "sweep_mode": "min", "sweep_cycles": 1.0, "sweep_width": 14,
                                   "cn_1_weight": 0.9})),
    Preset("video_depth_sweep_pulses", "Video Input - Depth sweep pulses (extreme)", "Video Input", EXTREME,
           "Four out-and-back sweeps with a wide band that keeps the depth shading, strong ControlNet, "
           "loose hold on the video: the picture pulses through the depth layers.",
           _merge(_VIDEO, _SWEEP, {"strength_schedule": 0.4, "noise_schedule": 0.08, "color_coherence": "None",
                                   "sweep_mode": "min", "sweep_cycles": 4.0, "sweep_shape": "pingpong",
                                   "sweep_width": 28, "sweep_fill": "depth", "sweep_softness": 10,
                                   "cn_1_weight": 1.3, "cn_1_control_mode": "ControlNet is more important"})),
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
