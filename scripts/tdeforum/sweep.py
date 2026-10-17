"""Sweep Depth: a moving band through a depth video, recorded as a ControlNet / mask video.

The idea (Animation Mode = Video Input): ComfyUI turns the init video into a depth video
(white = near, black = far, the DepthAnything / MiDaS convention). Frame by frame a *band*
of grey levels is kept white and everything outside it goes black. The band slides through
the whole 0-255 range over the length of the render, so the white sweep seems to travel
away from the viewer (mode ``max``: starts on the nearest levels 245-255 and ends on 0-10)
or towards the viewer (mode ``min``: the opposite).

This module is the pure part: settings, the position of the band for each render frame, and
the mask itself (numpy). td_controller.py records the result through the same timeline-stepped
capture as the TOP feeds (the Script TOP ``sweep_mask`` inside the deforum COMP calls
:func:`cook`; ``sweep_depth`` is the Movie File In TOP that plays the depth video).
"""

MAX, MIN = "max", "min"
MODES = [MAX, MIN]
MODE_LABELS = ["Max: nearest (white) levels first, sweeps away from the viewer",
               "Min: farthest (black) levels first, sweeps toward the viewer"]
RAMP, PINGPONG = "ramp", "pingpong"
SHAPES = [RAMP, PINGPONG]
SHAPE_LABELS = ["Ramp (every cycle restarts)", "Ping-pong (every cycle goes out and back)"]
FORWARD, REVERSE = "forward", "reverse"
DIRECTIONS = [FORWARD, REVERSE]
DIRECTION_LABELS = ["Forward (as the mode says)", "Reverse (swap start and end)"]
WHITE, DEPTH = "white", "depth"
FILLS = [WHITE, DEPTH]
FILL_LABELS = ["White (a flat white band)", "Depth (keep the depth shading inside the band)"]
# ComfyUI AIO_Preprocessor names that make a depth map (comfyui_controlnet_aux).
MODELS = ["DepthAnythingV2Preprocessor", "MiDaS-DepthMapPreprocessor", "Zoe-DepthMapPreprocessor"]
VIDEO_INPUT = "Video Input"
SCRIPT_BAND_KEY = "sweep_band"     # Script TOP storage: (lo, hi, softness, fill)
_EPS = 1e-9


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _num(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class Settings(object):
    __slots__ = ("mode", "cycles", "shape", "direction", "width", "softness", "fill", "model")

    def __init__(self, mode=MAX, cycles=1.0, shape=RAMP, direction=FORWARD, width=10,
                 softness=0, fill=WHITE, model=MODELS[0]):
        self.mode = mode if mode in MODES else MAX
        self.cycles = max(0.05, float(cycles))
        self.shape = shape if shape in SHAPES else RAMP
        self.direction = direction if direction in DIRECTIONS else FORWARD
        self.width = min(255.0, max(1.0, float(width)))
        self.softness = min(128.0, max(0.0, float(softness)))
        self.fill = fill if fill in FILLS else WHITE
        self.model = model if model else MODELS[0]


def from_values(values):
    """Settings from COMP values (the sweep_* fields); missing keys use the defaults."""
    get = values.get
    return Settings(
        mode=str(get("sweep_mode", MAX)), cycles=_num(get("sweep_cycles", 1), 1),
        shape=str(get("sweep_shape", RAMP)), direction=str(get("sweep_direction", FORWARD)),
        width=_num(get("sweep_width", 10), 10), softness=_num(get("sweep_softness", 0), 0),
        fill=str(get("sweep_fill", WHITE)), model=str(get("sweep_model", MODELS[0]) or MODELS[0]))


def enabled(values):
    return _truthy(values.get("sweep_enabled", False))


def check(values):
    """None when Sweep Depth can run, else why not (shown to the user)."""
    if not enabled(values):
        return "Guide Source is Sweep Depth but Sweep Depth is switched off (Sweep Depth page > On)"
    if str(values.get("animation_mode", "")) != VIDEO_INPUT:
        return "Sweep Depth needs Animation Mode = Video Input (it sweeps the depth of the init video)"
    if not str(values.get("video_init_path", "") or "").strip():
        return "Sweep Depth needs a Video Init Path (Globals page)"
    return None


def position(k, total, s):
    """Where the band is at render frame k: 0 = the start band, 1 = the end band.

    ``ramp``: one sweep per cycle, restarting each cycle; the very last frame of a whole number
    of cycles lands on 1 so a single cycle really ends on the far band.
    ``pingpong``: a cycle goes 0 -> 1 -> 0.
    """
    total = max(1, int(total))
    u = k / float(total - 1) if total > 1 else 0.0
    phase = u * s.cycles
    if s.shape == PINGPONG:
        x = (phase * 2.0) % 2.0
        p = x if x <= 1.0 else 2.0 - x
    else:
        p = phase % 1.0
        if u >= 1.0 - _EPS and phase > 0 and abs(phase - round(phase)) < 1e-6:
            p = 1.0
    if s.direction == REVERSE:
        p = 1.0 - p
    return min(1.0, max(0.0, p))


def band(p, mode, width):
    """(lo, hi) of the white band in 0..1 grey for position p (width in 0-255 levels)."""
    w = min(1.0, max(1.0 / 255.0, float(width) / 255.0))
    top = (1.0 - p * (1.0 - w)) if mode == MAX else (w + p * (1.0 - w))
    return top - w, top


def levels(lo, hi):
    return "%d-%d" % (round(lo * 255), round(hi * 255))


def plan(values, total, extract_from=0, nth=1, depth_frames=None):
    """Per render frame: depth-video index and band.

    Returns {"settings", "indices", "bands": [(lo, hi, softness_0_1, fill)], "warnings"}.
    ``extract_from`` / ``nth`` are Deforum's Video Input frame window (render frame k plays
    source frame extract_from + k * nth); indices are clamped to the depth video's length.
    """
    s = from_values(values)
    total = max(1, int(total))
    extract_from, nth = max(0, int(extract_from or 0)), max(1, int(nth or 1))
    indices, bands, warnings = [], [], []
    clipped = 0
    for k in range(total):
        i = extract_from + k * nth
        if depth_frames and i > depth_frames - 1:
            i, clipped = depth_frames - 1, clipped + 1
        indices.append(i)
        lo, hi = band(position(k, total, s), s.mode, s.width)
        bands.append((lo, hi, s.softness / 255.0, s.fill))
    if clipped:
        warnings.append("the depth video has %d frames; the last %d render frames repeat its final frame"
                        % (depth_frames, clipped))
    return {"settings": s, "indices": indices, "bands": bands, "warnings": warnings}


def describe(sweep_plan):
    s, bands = sweep_plan["settings"], sweep_plan["bands"]
    first, last = bands[0], bands[-1]
    return "%s sweep, %g cycle%s (%s), band %d levels wide: %s at the start, %s at the end of %d frames" % (
        s.mode, s.cycles, "" if s.cycles == 1 else "s", s.shape, round(s.width),
        levels(first[0], first[1]), levels(last[0], last[1]), len(bands))


def mask(depth, lo, hi, softness=0.0, fill=WHITE):
    """Band mask of a grey image (numpy float array, 0..1): 1 inside [lo, hi], 0 outside.

    ``softness`` (0..1 grey) feathers both edges with a smoothstep; ``fill`` DEPTH multiplies
    the mask by the depth so the band keeps its shading. Half a grey level of tolerance
    keeps 8-bit values on the band edges inside it.
    """
    import numpy as np
    half = 0.5 / 255.0
    d = np.asarray(depth, dtype=np.float32)
    if softness <= _EPS:
        inside = ((d >= lo - half) & (d <= hi + half)).astype(np.float32)
    else:
        def smooth(x):
            x = np.clip(x, 0.0, 1.0)
            return x * x * (3.0 - 2.0 * x)
        rise = smooth((d - (lo - softness - half)) / (softness + half))
        fall = smooth(((hi + softness + half) - d) / (softness + half))
        inside = (rise * fall).astype(np.float32)
    return inside * d if fill == DEPTH else inside


def mask_rgba(rgba, lo, hi, softness=0.0, fill=WHITE):
    """(h, w, 4+) float image in, grey (h, w, 4) float32 mask image out (alpha 1)."""
    import numpy as np
    rgba = np.asarray(rgba, dtype=np.float32)
    grey = rgba[..., :3].mean(axis=2) if rgba.ndim == 3 and rgba.shape[2] >= 3 else rgba.reshape(rgba.shape[:2])
    out = mask(grey, lo, hi, softness, fill)
    result = np.empty(out.shape + (4,), dtype=np.float32)
    result[..., 0] = result[..., 1] = result[..., 2] = out
    result[..., 3] = 1.0
    return result


def cook(script_op):
    """Script TOP callback body: band-mask the first input using the stored band."""
    sources = list(script_op.inputs)
    if not sources:
        return
    lo, hi, softness, fill = script_op.fetch(SCRIPT_BAND_KEY, (1.0 - 10.0 / 255.0, 1.0, 0.0, WHITE))
    script_op.copyNumpyArray(mask_rgba(sources[0].numpyArray(delayed=False), lo, hi, softness, fill))
