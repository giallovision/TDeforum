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

GOOD, EXTREME, UNORTHODOX = "good", "extreme", "unorthodox"


class Preset(object):
    __slots__ = ("id", "label", "mode", "level", "notes", "values", "raws")

    def __init__(self, id, label, mode, level, notes, values, raws=None):
        self.id, self.label, self.mode, self.level, self.notes = id, label, mode, level, notes
        self.values = values
        self.raws = dict(raws or {})      # {MOD api: Deforum schedule} written to <Name>raw

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

# Hybrid Video base: flow from the init video, cadence 2 with RAFT between diffusions, no loop
# (the video does not loop); the sweep keys come from _SWEEP.
_HYBRID_FLOW = {"hybrid_motion": "Optical Flow", "hybrid_flow_method": "RAFT", "hybrid_composite": "None",
                "hybrid_motion_use_prev_img": False, "hybrid_flow_consistency": False,
                "hybrid_flow_factor_schedule": 1.0, "seamless_loop": False, "diffusion_cadence": 2,
                "optical_flow_cadence": "RAFT"}

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

    # ================================================================== unorthodox
    # Things that only a generative feedback loop can do: the picture is re-imagined every frame,
    # so geometry, depth, noise and even the seed become animation channels.
    # ------------------------------------------------------------------ 2D
    Preset("2d_ouroboros", "2D - Ouroboros (unorthodox)", "2D", UNORTHODOX,
           "Zoom OUT with wrapped edges: the frame shrinks into tiled copies of itself and every pass "
           "fuses the seams into one ever-growing mandala that never runs out of picture.",
           _merge(_SMOOTH, _2D, {"zoom": 0.985, "angle": 0.15, "border": "wrap", "strength_schedule": 0.72,
                                 "noise_schedule": 0.02, "diffusion_cadence": 2})),
    Preset("2d_folding_plane", "2D - Folding plane (unorthodox)", "2D", UNORTHODOX,
           "Perspective flip on three beat-locked axes: the picture plane folds and unfolds like paper and "
           "diffusion paints whatever the fold reveals beyond the edges.",
           _merge(_SMOOTH, _2D, {"enable_perspective_flip": True, "perspective_flip_fv": 53.0, "zoom": 1.002,
                                 "strength_schedule": 0.72},
                  _slot(1, "perspective_flip_theta", "sine", 8.0, 20.0),
                  _slot(2, "perspective_flip_phi", "sine", 4.0, 12.0, phase=0.25),
                  _slot(3, "perspective_flip_gamma", "triangle", 8.0, 6.0))),
    Preset("2d_flow_puppet", "2D - Flow puppet (unorthodox)", "2D", UNORTHODOX,
           "Hybrid Video optical flow: the hallucination moves exactly like your init video (every sway, "
           "every step) without a single pixel of the video showing. Needs Globals > Video Init Path.",
           _merge(_SMOOTH, _2D, {"hybrid_motion": "Optical Flow", "hybrid_flow_method": "RAFT",
                                 "hybrid_motion_use_prev_img": False, "hybrid_composite": "None",
                                 "hybrid_flow_factor_schedule": 1.0, "seamless_loop": False,
                                 "strength_schedule": 0.68, "diffusion_cadence": 1,
                                 "optical_flow_cadence": "None"})),
    # ------------------------------------------------------------------ 3D
    Preset("3d_endless_vertigo", "3D - Endless vertigo (unorthodox)", "3D", UNORTHODOX,
           "A dolly zoom that never ends: the camera pushes forward while the FOV breathes 45-95 degrees "
           "over the loop, so space stretches and collapses around a subject that keeps being re-made.",
           _merge(_SMOOTH, _3D, {"translation_z": 1.0, "midas_weight": 0.4, "strength_schedule": 0.72},
                  _slot(1, "fov_schedule", "sine", 8.0, 25.0))),
    Preset("3d_escher_descent", "3D - Escher descent (unorthodox)", "3D", UNORTHODOX,
           "Sink and tilt at once with mirrored padding: every frame is a step down an impossible staircase "
           "that the depth model keeps folding back into itself.",
           _merge(_SMOOTH, _3D, {"translation_y": -0.8, "rotation_3d_x": 0.35, "translation_z": 0.4,
                                 "padding_mode": "reflection", "strength_schedule": 0.74})),
    Preset("3d_breathing_space", "3D - Breathing space (unorthodox)", "3D", UNORTHODOX,
           "The geometry itself breathes on the bar: aspect ratio and FOV swing in opposite phase, an "
           "anamorphic inhale the depth warp re-paints instead of stretching.",
           _merge(_SMOOTH, _3D, {"translation_z": 0.3, "strength_schedule": 0.74},
                  _slot(1, "aspect_ratio_schedule", "sine", 4.0, 0.25),
                  _slot(2, "fov_schedule", "sine", 4.0, 12.0, phase=0.5))),
    # ------------------------------------------------------------------ Video Input
    Preset("video_depth_peel", "Video Input - Depth peel (unorthodox)", "Video Input", UNORTHODOX,
           "The sweep becomes the MASK, not the guide: only the glowing band is re-dreamed, the rest stays "
           "the real video, so the restyle peels through the scene layer by layer (Invert Mask flips it).",
           _merge(_VIDEO, _SWEEP, {"cn_1_enabled": False, "sweep_as_mask": True, "sweep_mode": "max",
                                   "sweep_width": 40, "sweep_softness": 16, "sweep_grow": 10,
                                   "sweep_blur": 8.0, "sweep_trail": 20, "strength_schedule": 0.35,
                                   "color_coherence": "Video Input", "overlay_mask": True,
                                   "invert_mask": False})),
    Preset("video_depth_puppet", "Video Input - Depth puppet (unorthodox)", "Video Input", UNORTHODOX,
           "The whole depth map (a band 255 levels wide, depth-shaded) drives QR Monster while the video is "
           "barely kept: the prompt becomes a new world that moves with the performer's depth.",
           _merge(_VIDEO, _SWEEP, {"sweep_width": 255, "sweep_fill": "depth", "sweep_softness": 0,
                                   "sweep_grow": 0, "sweep_blur": 2.0, "sweep_trail": 0, "sweep_smooth": 0.5,
                                   "strength_schedule": 0.25, "cn_1_weight": 0.95, "cn_1_guidance_end": 0.7})),
    Preset("video_depth_strobe", "Video Input - Depth strobe (unorthodox)", "Video Input", UNORTHODOX,
           "A thin hard band races through the depth once per beat (8 cycles over an 8-beat loop): the scene "
           "is sliced into strobing depth layers locked to the tempo.",
           _merge(_VIDEO, _SWEEP, {"sweep_cycles": 8.0, "sweep_width": 12, "sweep_softness": 2,
                                   "sweep_grow": 2, "sweep_blur": 1.0, "sweep_trail": 0, "sweep_smooth": 0.3,
                                   "strength_schedule": 0.5, "cn_1_weight": 1.0, "cn_1_guidance_end": 0.9,
                                   "cn_1_control_mode": "ControlNet is more important"})),
    # ------------------------------------------------------------------ Hybrid Video
    # 2D / 3D feedback loop steered by the init video (Hybrid Video page), with Sweep Depth of the
    # same video as a QR Monster guide or as the mask. Cadence 2 + RAFT: half the diffusions, flow
    # in between, which is where most of the smoothness comes from.
    Preset("hybrid_flow_glow", "Hybrid - Flow glow (good)", "2D", GOOD,
           "The dream moves with the video's optical flow while a soft depth band travels away through the "
           "performer as a QR Monster glow. Needs Globals > Video Init Path.",
           _merge(_SMOOTH, _2D, _HYBRID_FLOW, _SWEEP, {"sweep_mode": "max", "strength_schedule": 0.7,
                                                      "noise_schedule": 0.01, "color_coherence": "LAB"})),
    # From a pass that worked (2026-10-17, ballet + Haeckel prompt; docs/passes/): one 10-frame
    # saw drives the camera push, the lens and Strength together, so every pulse pushes in,
    # narrows the FOV and re-imagines more at the same moment; the video is composited in at 80 %
    # before the warp, so the dancer stays; only a soft depth band (the mask) is re-diffused;
    # cadence 8 + RAFT, then RIFE x3, keeps it fluid.
    Preset("hybrid_ballet_pulse", "Hybrid - Pulse composite (good)", "3D", GOOD,
           "3D push + lens + Strength on one 10-frame saw, the video composited in at 80 % before motion, "
           "a soft depth band as the mask and your TD visual (final_out) as the QR guide. Cadence 8, RIFE x3. "
           "Needs Globals > Video Init Path.",
           _merge(_3D, _HYBRID_FLOW, _SWEEP, {
               "fov_schedule": 127.0, "midas_weight": 0.2, "padding_mode": "zeros",
               "translation_z": 1.0, "strength_schedule": 0.7,
               "hybrid_composite": "Before Motion", "hybrid_comp_alpha_schedule": 0.8,
               "diffusion_cadence": 8, "optical_flow_cadence": "RAFT", "optical_flow_redo_generation": "None",
               "noise_schedule": 0.01, "noise_multiplier_schedule": 1.0, "contrast_schedule": 1.0,
               "color_coherence": "LAB", "legacy_colormatch": False, "noise_type": "perlin",
               "perlin_w": 4, "perlin_h": 4, "perlin_octaves": 3, "perlin_persistence": 0.5,
               "seamless_loop": False, "loop_overlap_beats": 2.0, "fit_loop_to_video": True,
               "render_strategy": "interpolate", "render_fps": "20", "interp_engine": "RIFE v4.6",
               "feed_1_mode": "top_loop", "cn_1_weight": 1.0, "cn_1_guidance_start": 0.2,
               "cn_1_guidance_end": 0.8, "cn_1_processor_res": 576,
               "sweep_as_mask": True, "sweep_mode": "max", "sweep_cycles": 1.0, "sweep_shape": "ramp",
               "sweep_width": 40, "sweep_softness": 16, "sweep_grow": 10, "sweep_blur": 8.0, "sweep_trail": 20,
               "sweep_smooth": 0.4, "sweep_fill": "white"}),
           raws={"translation_z": "0:(1.3 - 0.0620689*(t%10))",
                 "strength_schedule": "0:(0.91 - 0.0434483*(t%10))",
                 "fov_schedule": "0:(138.6 - 2.6069*(t%10))"}),
    Preset("hybrid_ghost_peel", "Hybrid - Ghost peel (good)", "3D", GOOD,
           "Slow 3D push, the video's flow plus a 25 % ghost of it, and the depth sweep as the MASK: only the "
           "band re-diffuses, so the scene is re-dreamed layer by layer toward you.",
           _merge(_SMOOTH, _3D, _HYBRID_FLOW, _SWEEP,
                  {"translation_z": 0.3, "hybrid_composite": "Normal", "hybrid_comp_alpha_schedule": 0.25,
                   "cn_1_enabled": False, "sweep_as_mask": True, "sweep_mode": "min", "sweep_width": 36,
                   "sweep_softness": 14, "sweep_grow": 10, "sweep_blur": 8.0, "sweep_trail": 16,
                   "overlay_mask": True, "invert_mask": False, "strength_schedule": 0.6,
                   "noise_schedule": 0.015})),
    Preset("hybrid_camera_tide", "Hybrid - Camera tide (extreme)", "3D", EXTREME,
           "Copies the video's CAMERA (perspective), not its subject, while four ping-pong depth pulses drive "
           "QR Monster hard: the space surges like a tide through the video's own depth.",
           _merge(_SMOOTH, _3D, _HYBRID_FLOW, _SWEEP,
                  {"hybrid_motion": "Perspective", "translation_z": 0.2, "sweep_mode": "min", "sweep_cycles": 4.0,
                   "sweep_shape": "pingpong", "sweep_width": 28, "sweep_fill": "depth", "sweep_softness": 12,
                   "sweep_grow": 10, "sweep_blur": 6.0, "sweep_trail": 16, "strength_schedule": 0.6,
                   "noise_schedule": 0.03, "cn_1_weight": 1.0, "cn_1_guidance_end": 1.0,
                   "cn_1_control_mode": "ControlNet is more important"})),
    Preset("hybrid_possession", "Hybrid - Possession (unorthodox)", "2D", UNORTHODOX,
           "Sticky flow measured from the generated image, a faint after-generation echo of the video and the "
           "whole depth map as relief: something else is wearing the performer's shape and movement.",
           _merge(_SMOOTH, _2D, _HYBRID_FLOW, _SWEEP,
                  {"hybrid_motion_use_prev_img": True, "hybrid_flow_consistency": True,
                   "hybrid_consistency_blur": 2, "hybrid_composite": "After Generation",
                   "hybrid_comp_alpha_schedule": 0.15, "sweep_width": 255, "sweep_fill": "depth",
                   "sweep_softness": 0, "sweep_grow": 0, "sweep_blur": 2.0, "sweep_trail": 0,
                   "sweep_smooth": 0.5, "cn_1_weight": 0.9, "cn_1_guidance_end": 0.7,
                   "strength_schedule": 0.65})),
    # ------------------------------------------------------------------ Interpolation
    # Every frame is drawn from noise (no previous frame), so with a fixed seed a frame is a pure
    # function of its settings: modulate the seed itself and the loop closes perfectly.
    Preset("interp_seed_walk", "Interpolation - Seed walk (unorthodox)", "Interpolation", UNORTHODOX,
           "A walk through latent space: the noise blends from seed 424242 to its neighbour and back over "
           "the loop (subseed strength 0 -> 1 -> 0), so one image morphs into its sibling and returns. "
           "Perfectly seamless.",
           {"animation_mode": "Interpolation", "seed_behavior": "fixed", "enable_subseed_scheduling": True,
            "subseed_schedule": "0:(424243)", "subseed_strength_schedule": 0.5, "seamless_loop": True,
            "loop_overlap_beats": 0.0, "diffusion_cadence": 1,
            "mod1_active": True, "mod1_target": "subseed_strength_schedule", "mod1_shape": "triangle",
            "mod1_beats": 8.0, "mod1_depth": 0.5, "mod1_sharpness": 4.0, "mod1_phase": 0.0}),
    Preset("interp_beat_jolt", "Interpolation - Beat jolt (unorthodox)", "Interpolation", UNORTHODOX,
           "On every beat the noise jumps towards another seed and relaxes back: the image flinches into a "
           "sibling version on the kick and settles, with no motion at all.",
           _merge({"animation_mode": "Interpolation", "seed_behavior": "fixed",
                   "enable_subseed_scheduling": True, "subseed_schedule": "0:(424299)",
                   "subseed_strength_schedule": 0.0, "seamless_loop": True, "loop_overlap_beats": 0.0,
                   "diffusion_cadence": 1},
                  _slot(1, "subseed_strength_schedule", "decay", 1.0, 0.55, 6.0))),
    Preset("interp_guidance_bloom", "Interpolation - Guidance bloom (unorthodox)", "Interpolation", UNORTHODOX,
           "CFG swings 0.9 -> 2.7 over the loop: the picture dissolves into a soft dream, then blooms into "
           "over-defined detail and back, while a slow seed drift keeps it alive.",
           _merge({"animation_mode": "Interpolation", "seed_behavior": "fixed",
                   "enable_subseed_scheduling": True, "subseed_schedule": "0:(424243)",
                   "subseed_strength_schedule": 0.15, "seamless_loop": True, "loop_overlap_beats": 0.0,
                   "diffusion_cadence": 1},
                  _slot(1, "cfg_scale_schedule", "sine", 8.0, 0.9),
                  _slot(2, "subseed_strength_schedule", "triangle", 8.0, 0.15))),
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
