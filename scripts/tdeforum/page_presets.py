"""Per-page presets: a "Page Preset" menu at the top of every deforum COMP page except Globals
(and Prompts, whose Prompt Preset menu plays that role).

A page preset only touches parameters on its own page, so they stack: e.g. Motion 3D "Orbit" +
Camera "Wide lens" + Flow "Deflicker". Like the Example Preset, the values a page preset
replaces are remembered and come back when you pick None on that page; the Example Preset
(Tempo page) puts every page preset back to None before it applies anything, so a page preset's
remembered values can never overwrite an example.
"""

NONE = "none"


class PagePreset(object):
    __slots__ = ("id", "label", "values")

    def __init__(self, id, label, values):
        self.id, self.label, self.values = id, label, values


P = PagePreset


def _slot(n, target, shape, beats, depth, sharpness=4.0, phase=0.0):
    p = "mod%d_" % n
    return {p + "active": True, p + "target": target, p + "shape": shape, p + "beats": beats,
            p + "depth": depth, p + "sharpness": sharpness, p + "phase": phase}


def _slots_off():
    return dict(("mod%d_active" % n, False) for n in range(1, 9))


def _cn(n, **values):
    return dict(("cn_%d_%s" % (n, k) if not k.startswith("feed_") else "feed_%d_%s" % (n, k[5:]), v)
                for k, v in values.items())


_SWEEP_GLOW = {"sweep_enabled": True, "sweep_cycles": 1.0, "sweep_shape": "ramp", "sweep_direction": "forward",
               "sweep_width": 18, "sweep_softness": 8, "sweep_grow": 6, "sweep_blur": 4.0, "sweep_trail": 8,
               "sweep_smooth": 0.4, "sweep_fill": "white", "sweep_as_mask": False,
               "sweep_model": "depth_anything_v2_vits"}


def _cn_presets(n):
    qr = {"enabled": True, "module": "none", "model": "ctrl_v1p_qr_monster_v2"}
    return [
        P("off", "Off", _cn(n, enabled=False)),
        P("qr_sweep_glow", "QR Monster glow from Sweep Depth (0.75, ends 80 %)",
          _cn(n, feed_mode="sweep", weight=0.75, guidance_start=0.0, guidance_end=0.8,
              control_mode="Balanced", **qr)),
        P("qr_sweep_strong", "QR Monster leads from Sweep Depth (1.1, ControlNet first)",
          _cn(n, feed_mode="sweep", weight=1.1, guidance_start=0.0, guidance_end=1.0,
              control_mode="ControlNet is more important", **qr)),
        P("qr_top_loop", "QR Monster from a TOP loop (Source TOP below)",
          _cn(n, feed_mode="top_loop", weight=0.8, guidance_start=0.0, guidance_end=0.9,
              control_mode="Balanced", **qr)),
        P("qr_late", "QR Monster late (starts at 30 %: detail, not layout)",
          _cn(n, weight=0.9, guidance_start=0.3, guidance_end=1.0, control_mode="Balanced", **qr)),
    ]


# page name -> (slug, [presets]). Slugs name the menu parameter: pagepreset_<slug>.
PAGES = {
    "Tempo": ("tempo", [
        P("smooth_cadence", "Smooth: 60 fps, cadence 4, 2-beat seam",
          {"render_strategy": "cadence", "diffusion_cadence": 4, "seamless_loop": True,
           "loop_overlap_beats": 2.0}),
        P("detailed_cadence", "Detailed: 60 fps, cadence 2",
          {"render_strategy": "cadence", "diffusion_cadence": 2, "seamless_loop": True,
           "loop_overlap_beats": 1.0}),
        P("fast_rife", "Fast: 30 fps + RIFE x2",
          {"render_strategy": "interpolate", "render_fps": "30", "interp_engine": "RIFE v4.6",
           "diffusion_cadence": 2}),
        P("dreamy_rife", "Dreamy: 15 fps + RIFE x4",
          {"render_strategy": "interpolate", "render_fps": "15", "interp_engine": "RIFE v4.6",
           "diffusion_cadence": 1}),
        P("long_loop", "Long loop: 4 bars",
          {"loop_bars": 4, "loop_overlap_beats": 2.0}),
    ]),
    "Motion 2D": ("motion2d", [
        P("still", "Still",
          {"zoom": 1.0, "angle": 0.0, "translation_x": 0.0, "translation_y": 0.0,
           "transform_center_x": 0.5, "transform_center_y": 0.5}),
        P("slow_zoom", "Slow zoom in", {"zoom": 1.003, "angle": 0.1}),
        P("zoom_out_wrap", "Zoom out into tiles (wrap)", {"zoom": 0.99, "border": "wrap"}),
        P("drift", "Sideways drift (wrap)", {"translation_x": 1.0, "border": "wrap"}),
        P("offcenter_spiral", "Off-centre spiral",
          {"angle": 0.5, "zoom": 1.004, "transform_center_x": 0.3, "transform_center_y": 0.35}),
    ]),
    "Motion 3D": ("motion3d", [
        P("still", "Still",
          {"translation_z": 0.0, "rotation_3d_x": 0.0, "rotation_3d_y": 0.0, "rotation_3d_z": 0.0}),
        P("push", "Forward push", {"translation_z": 0.6}),
        P("orbit", "Orbit", {"rotation_3d_y": 0.15, "translation_z": 0.2, "padding_mode": "reflection"}),
        P("roll", "Push and roll", {"rotation_3d_z": 0.3, "translation_z": 0.4}),
        P("pull_back", "Pull back (mirrored edges)", {"translation_z": -0.6, "padding_mode": "reflection"}),
    ]),
    "Camera & Depth": ("camera", [
        P("standard", "Standard lens 70 degrees",
          {"fov_schedule": 70.0, "midas_weight": 0.2, "use_depth_warping": True,
           "enable_perspective_flip": False}),
        P("wide", "Wide lens 100 degrees (more parallax)", {"fov_schedule": 100.0}),
        P("tele", "Telephoto 35 degrees (flat, slow)", {"fov_schedule": 35.0}),
        P("deep", "Deep relief (depth weight 0.5)", {"midas_weight": 0.5, "use_depth_warping": True}),
        P("flip_tilt", "Perspective tilt 12 degrees",
          {"enable_perspective_flip": True, "perspective_flip_theta": 12.0, "perspective_flip_fv": 53.0}),
    ]),
    "Diffusion": ("diffusion", [
        P("steady", "Steady (keep 0.8, no noise): least flicker",
          {"strength_schedule": 0.8, "noise_schedule": 0.0, "contrast_schedule": 1.0}),
        P("balanced", "Balanced (keep 0.72, noise 0.015)",
          {"strength_schedule": 0.72, "noise_schedule": 0.015, "contrast_schedule": 1.0}),
        P("loose", "Loose (keep 0.55, noise 0.04): keeps reinventing",
          {"strength_schedule": 0.55, "noise_schedule": 0.04}),
        P("crisp", "Crisp LCM (CFG 2.0)", {"cfg_scale_schedule": 2.0}),
        P("soft_dream", "Soft dream LCM (CFG 1.4, keep 0.78)",
          {"cfg_scale_schedule": 1.4, "strength_schedule": 0.78}),
    ]),
    "Noise & Color": ("noise", [
        P("fine_perlin", "Fine perlin noise",
          {"noise_type": "perlin", "perlin_w": 8, "perlin_h": 8, "perlin_octaves": 4, "perlin_persistence": 0.5}),
        P("coarse_perlin", "Coarse perlin (big soft blobs)",
          {"noise_type": "perlin", "perlin_w": 2, "perlin_h": 2, "perlin_octaves": 2, "perlin_persistence": 0.6}),
        P("uniform", "Uniform noise", {"noise_type": "uniform"}),
        P("lock_lab", "Colour locked (LAB)", {"color_coherence": "LAB", "color_force_grayscale": False}),
        P("free_colour", "Colour free to drift", {"color_coherence": "None", "color_force_grayscale": False}),
    ]),
    "Flow & Anti-blur": ("flow", [
        P("deflicker", "Deflicker: RAFT cadence + RAFT redo (2x slower)",
          {"optical_flow_cadence": "RAFT", "cadence_flow_factor_schedule": 1.0,
           "optical_flow_redo_generation": "RAFT", "redo_flow_factor_schedule": 1.0}),
        P("standard", "Standard: RAFT between cadence frames",
          {"optical_flow_cadence": "RAFT", "optical_flow_redo_generation": "None"}),
        P("fast", "Fast: DIS Medium", {"optical_flow_cadence": "DIS Medium", "optical_flow_redo_generation": "None"}),
        P("off", "Off (plain blend between cadence frames)",
          {"optical_flow_cadence": "None", "optical_flow_redo_generation": "None"}),
        P("crisp", "Crisper (anti-blur 0.2)", {"amount_schedule": 0.2, "kernel_schedule": 5, "sigma_schedule": 1.0}),
    ]),
    "Hybrid Video": ("hybrid", [
        P("off", "Off", {"hybrid_motion": "None", "hybrid_composite": "None"}),
        P("flow_puppet", "Move like the video (optical flow)",
          {"hybrid_motion": "Optical Flow", "hybrid_flow_method": "RAFT", "hybrid_composite": "None",
           "hybrid_motion_use_prev_img": False, "hybrid_flow_factor_schedule": 1.0}),
        P("camera_copy", "Copy the video's camera (perspective)",
          {"hybrid_motion": "Perspective", "hybrid_composite": "None"}),
        P("ghost", "Flow + 25 % video ghost",
          {"hybrid_motion": "Optical Flow", "hybrid_flow_method": "RAFT", "hybrid_composite": "Normal",
           "hybrid_comp_alpha_schedule": 0.25}),
        P("sticky", "Sticky flow (from the generated image, consistency masked)",
          {"hybrid_motion": "Optical Flow", "hybrid_flow_method": "RAFT", "hybrid_motion_use_prev_img": True,
           "hybrid_flow_consistency": True, "hybrid_consistency_blur": 2}),
    ]),
    "Mod Matrix": ("mods", [
        P("off", "All slots off", _slots_off()),
        P("kick_push", "Kick push (slot 1: translation Z decay each beat)",
          _slot(1, "translation_z", "decay", 1.0, 1.2, 5.0)),
        P("breathing_zoom", "Breathing zoom (slot 1: zoom sine over a bar)", _slot(1, "zoom", "sine", 4.0, 0.004)),
        P("wobble", "Wobble (slot 1: pan sine over 2 beats)", _slot(1, "rotation_3d_y", "sine", 2.0, 0.3)),
        P("hit_regenerate", "Regenerate on the beat (slot 2: Strength dip)",
          _slot(2, "strength_schedule", "decay", 1.0, -0.15, 5.0)),
    ]),
    "Sweep Depth": ("sweep", [
        P("off", "Off", {"sweep_enabled": False}),
        P("glow_away", "Glow travelling away", dict(_SWEEP_GLOW, sweep_mode="max")),
        P("glow_toward", "Glow rushing toward", dict(_SWEEP_GLOW, sweep_mode="min")),
        P("pulses", "Ping-pong pulses (4 cycles, depth shaded)",
          dict(_SWEEP_GLOW, sweep_mode="min", sweep_cycles=4.0, sweep_shape="pingpong", sweep_width=28,
               sweep_fill="depth", sweep_softness=12, sweep_grow=10, sweep_blur=6.0, sweep_trail=16,
               sweep_smooth=0.3)),
        P("strobe", "Depth strobe (8 hard cycles)",
          dict(_SWEEP_GLOW, sweep_cycles=8.0, sweep_width=12, sweep_softness=2, sweep_grow=2, sweep_blur=1.0,
               sweep_trail=0, sweep_smooth=0.3)),
        P("relief", "Full depth relief (whole depth map)",
          dict(_SWEEP_GLOW, sweep_width=255, sweep_fill="depth", sweep_softness=0, sweep_grow=0,
               sweep_blur=2.0, sweep_trail=0, sweep_smooth=0.5)),
        P("peel_mask", "Peel mask (sweep drives the video mask)",
          dict(_SWEEP_GLOW, sweep_as_mask=True, sweep_width=40, sweep_softness=16, sweep_grow=10,
               sweep_blur=8.0, sweep_trail=20)),
    ]),
    "ControlNet Unit 1": ("cn1", _cn_presets(1)),
    "ControlNet Unit 2": ("cn2", _cn_presets(2)),
    "ControlNet Unit 3": ("cn3", _cn_presets(3)),
    "Pipeline": ("pipeline", [
        P("performance", "Performance (auto-load, reuse ComfyUI results)",
          {"auto_load": True, "force_preprocess": False}),
        P("fresh", "Fresh ComfyUI results every Queue", {"force_preprocess": True}),
        P("continuous_feed", "Record TOP feeds continuously", {"feed_method": "continuous"}),
    ]),
}


def api(page):
    return "pagepreset_" + PAGES[page][0]


def presets_for(page):
    return PAGES[page][1]


def get(page, name):
    for preset in presets_for(page):
        if preset.id == str(name or "").strip():
            return preset
    return None


def names(page):
    return [NONE] + [p.id for p in presets_for(page)]


def labels(page):
    return ["None"] + [p.label for p in presets_for(page)]
