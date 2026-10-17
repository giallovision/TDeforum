"""Sweep Depth: a moving band through a depth video, rendered as a ControlNet / mask video.

The idea (Animation Mode = Video Input): ComfyUI turns the init video into a depth video
(white = near, black = far, the DepthAnything / MiDaS convention). For every render frame a
*band* of grey levels is kept white and everything outside it goes black. The band slides
through the whole 0-255 range over the length of the render, so the white sweep seems to travel
away from the viewer (mode ``max``: starts on the nearest levels 245-255 and ends on 0-10) or
towards the viewer (mode ``min``: the opposite).

Everything here is plain Python + numpy + OpenCV (both ship with TouchDesigner), so the whole
render runs in a background thread (:func:`run_job`) and is unit-tested outside TD:

1. get a readable copy of the depth video (the share, or a download from ComfyUI's /view);
2. count its frames; if it is shorter than the frames the render needs, the init video is
   shorter too, and the render is re-planned to the frames that exist;
3. read the depth frames the render uses (``extract_from + k * nth``), optionally smooth them
   over time, band-mask them, optionally leave a fading trail, and write an .mp4;
4. read the result back, check the frame count and write a small JSON next to it, which
   td_controller polls (the file also makes the result a cache: same inputs, no re-render).
"""

import hashlib
import json
import math
import os
import time

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
# Depth models. depth_anything_v2_* run comfyui_controlnet_aux's DepthAnythingV2Preprocessor node
# with that checkpoint (vits ~25M parameters: several times faster than vitl, plenty for a mask);
# the others are AIO_Preprocessor names (the AIO DepthAnythingV2 entry always loads vitl).
MODELS = ["depth_anything_v2_vits", "depth_anything_v2_vitb", "depth_anything_v2_vitl",
          "DepthAnythingV2Preprocessor", "MiDaS-DepthMapPreprocessor", "Zoe-DepthMapPreprocessor"]
MODEL_LABELS = ["Depth Anything V2 small (vits, fast)", "Depth Anything V2 base (vitb)",
                "Depth Anything V2 large (vitl, slow)", "Depth Anything V2 via AIO (vitl, old default)",
                "MiDaS", "Zoe"]
DEPTH_RESOLUTION = 512      # ComfyUI detect resolution for the sweep depth (the mask is resized anyway)
VIDEO_INPUT = "Video Input"
# 2D / 3D: the init video is the Hybrid Video source; render frame k shows its frame k too.
SWEEP_MODES = (VIDEO_INPUT, "2D", "3D")
RENDER_VERSION = 3          # bump when the pixels a job produces change
FOURCCS = ("mp4v", "avc1")  # first one the OpenCV build can open wins
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
    __slots__ = ("mode", "cycles", "shape", "direction", "width", "softness", "fill", "model",
                 "trail", "smooth", "grow", "blur")

    def __init__(self, mode=MAX, cycles=1.0, shape=RAMP, direction=FORWARD, width=10,
                 softness=0, fill=WHITE, model=MODELS[0], trail=0, smooth=0.0, grow=0, blur=0.0):
        self.mode = mode if mode in MODES else MAX
        self.cycles = max(0.05, float(cycles))
        self.shape = shape if shape in SHAPES else RAMP
        self.direction = direction if direction in DIRECTIONS else FORWARD
        self.width = min(255.0, max(1.0, float(width)))
        self.softness = min(128.0, max(0.0, float(softness)))
        self.fill = fill if fill in FILLS else WHITE
        self.model = model if model else MODELS[0]
        self.trail = min(240.0, max(0.0, float(trail)))
        self.smooth = min(0.95, max(0.0, float(smooth)))
        self.grow = int(min(64, max(0, round(float(grow)))))
        self.blur = min(48.0, max(0.0, float(blur)))

    def as_dict(self):
        return dict((name, getattr(self, name)) for name in self.__slots__)


def from_values(values):
    """Settings from COMP values (the sweep_* fields); missing keys use the defaults."""
    get = values.get
    return Settings(
        mode=str(get("sweep_mode", MAX)), cycles=_num(get("sweep_cycles", 1), 1),
        shape=str(get("sweep_shape", RAMP)), direction=str(get("sweep_direction", FORWARD)),
        width=_num(get("sweep_width", 10), 10), softness=_num(get("sweep_softness", 0), 0),
        fill=str(get("sweep_fill", WHITE)), model=str(get("sweep_model", MODELS[0]) or MODELS[0]),
        trail=_num(get("sweep_trail", 0), 0), smooth=_num(get("sweep_smooth", 0), 0),
        grow=_num(get("sweep_grow", 0), 0), blur=_num(get("sweep_blur", 0), 0))


def enabled(values):
    return _truthy(values.get("sweep_enabled", False))


def prepare_only(values):
    return _truthy(values.get("sweep_prepare_only", False))


def check(values):
    """None when Sweep Depth can run, else why not (shown to the user)."""
    if not enabled(values):
        return "Guide Source is Sweep Depth but Sweep Depth is switched off (Sweep Depth page > On)"
    if str(values.get("animation_mode", "")) not in SWEEP_MODES:
        return ("Sweep Depth needs Animation Mode = Video Input, or 2D / 3D with a Video Init Path "
                "(Hybrid Video): it sweeps the depth of the init video")
    if not str(values.get("video_init_path", "") or "").strip():
        return "Sweep Depth needs a Video Init Path (Globals page)"
    return None


# --------------------------------------------------------------------------- the band

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
    text = "%s sweep, %g cycle%s (%s), band %d levels wide: %s at the start, %s at the end of %d frames" % (
        s.mode, s.cycles, "" if s.cycles == 1 else "s", s.shape, round(s.width),
        levels(first[0], first[1]), levels(last[0], last[1]), len(bands))
    extras = []
    if s.grow:
        extras.append("grow %dpx" % s.grow)
    if s.blur:
        extras.append("blur %gpx" % s.blur)
    if s.trail:
        extras.append("trail %g frames" % s.trail)
    if s.smooth:
        extras.append("depth smoothing %g" % s.smooth)
    return text + (" (%s)" % ", ".join(extras) if extras else "")


def trail_decay(trail_frames):
    """Per-frame multiplier so a trail has faded to ~5 % after ``trail_frames`` frames."""
    return math.exp(-3.0 / trail_frames) if trail_frames > 0 else 0.0


def comfy_depth_node(model, image_link, resolution=DEPTH_RESOLUTION):
    """The ComfyUI node that makes the depth map for ``model`` (replaces the AIO node)."""
    if str(model).startswith("depth_anything_v2_vit"):
        return {"class_type": "DepthAnythingV2Preprocessor",
                "inputs": {"ckpt_name": "%s.pth" % model, "resolution": int(resolution), "image": image_link},
                "_meta": {"title": "TD_PREPROCESSOR"}}
    return {"class_type": "AIO_Preprocessor",
            "inputs": {"preprocessor": model, "resolution": int(resolution), "image": image_link},
            "_meta": {"title": "TD_PREPROCESSOR"}}


def shape_mask(m, grow=0, blur=0.0):
    """Widen (dilate by ``grow`` px) and soften (Gaussian, sigma ``blur`` px) a float mask."""
    if not grow and not blur:
        return m
    import cv2
    if grow:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
        m = cv2.dilate(m, kernel)
    if blur:
        m = cv2.GaussianBlur(m, (0, 0), blur)
    return m


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


# --------------------------------------------------------------------------- the render job

def job_key(depth_container, values, plan_info, size):
    """Short hash of everything that changes the rendered pixels."""
    blob = json.dumps({"v": RENDER_VERSION, "depth": depth_container, "s": from_values(values).as_dict(),
                       "plan": [plan_info.get(k) for k in ("max_frames", "extract_from_frame",
                                                           "extract_nth_frame", "source_frames")],
                       "size": list(size)}, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]


def read_result(sidecar):
    """The JSON a finished job wrote, or None while it is still running."""
    try:
        with open(sidecar, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def video_frames(path):
    import cv2
    capture = cv2.VideoCapture(path)
    try:
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()
    return frames if frames > 0 else None


def download(url, path, timeout=60.0):
    """Stream ``url`` to ``path`` (written as path.part, then renamed). Returns bytes written."""
    import urllib.request
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = path + ".part"
    written = 0
    with urllib.request.urlopen(url, timeout=timeout) as reply, open(part, "wb") as fh:
        while True:
            chunk = reply.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            written += len(chunk)
    if not written:
        os.remove(part)
        raise IOError("ComfyUI sent an empty file for %s" % url)
    os.replace(part, path)
    return written


def _open_writer(cv2, path, fps, size):
    for code in FOURCCS:
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*code), float(fps), size, True)
        if writer.isOpened():
            return writer, code
        writer.release()
    raise RuntimeError("OpenCV cannot write .mp4 here (tried %s)" % ", ".join(FOURCCS))


def render(depth_path, out_path, sweep_plan, size, fps=30.0):
    """Write the band-masked video. Returns {"frames", "codec"}."""
    import cv2
    import numpy as np
    s = sweep_plan["settings"]
    width, height = int(size[0]), int(size[1])
    capture = cv2.VideoCapture(depth_path)
    if not capture.isOpened():
        raise RuntimeError("OpenCV cannot open the depth video %s" % depth_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path[:-4] + ".tmp" + out_path[-4:]
    writer, codec = _open_writer(cv2, tmp, fps, (width, height))
    decay = trail_decay(s.trail)
    current, frame, ema, acc, written = -1, None, None, None, 0
    try:
        for index, (lo, hi, soft, fill) in zip(sweep_plan["indices"], sweep_plan["bands"]):
            while current < index:
                ok, got = capture.read()
                if not ok:
                    break
                frame, current = got, current + 1
            if frame is None:
                raise RuntimeError("could not read any frame from %s" % depth_path)
            grey = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if grey.shape[1] != width or grey.shape[0] != height:
                grey = cv2.resize(grey, (width, height), interpolation=cv2.INTER_AREA)
            depth = grey.astype(np.float32) * (1.0 / 255.0)
            if s.smooth and ema is not None:
                ema = s.smooth * ema + (1.0 - s.smooth) * depth
            else:
                ema = depth
            m = shape_mask(mask(ema, lo, hi, soft, fill), s.grow, s.blur)
            acc = m if (acc is None or not decay) else np.maximum(m, acc * decay)
            pixels = np.clip(acc * 255.0 + 0.5, 0, 255).astype(np.uint8)
            writer.write(cv2.cvtColor(pixels, cv2.COLOR_GRAY2BGR))
            written += 1
    finally:
        writer.release()
        capture.release()
    check = video_frames(tmp)
    if check is not None and check != written:
        raise RuntimeError("wrote %d frames but the file reads back as %d" % (written, check))
    os.replace(tmp, out_path)
    return {"frames": written, "codec": codec}


def run_job(job):
    """Background-thread body. Never raises: the outcome goes to job["sidecar"]."""
    started = time.time()
    result = {"ok": False, "key": job.get("key")}
    try:
        os.makedirs(os.path.dirname(job["sidecar"]), exist_ok=True)
    except OSError:
        pass
    try:
        depth = job["depth_local"]
        if not os.path.isfile(depth):
            if not job.get("fetch_url"):
                raise RuntimeError("the depth video is not readable from TouchDesigner: %s" % depth)
            size = download(job["fetch_url"], depth)
            result["fetched"] = size
        depth_frames = video_frames(depth)
        plan_info = dict(job["plan"])
        values = job["values"]
        if depth_frames and depth_frames < int(plan_info.get("source_frames") or 0):
            from . import payload        # the init video is shorter: plan the frames that exist
            short = payload.plan_frames(plan_info["mode"], job["ui_max"], plan_info.get("frame_mode", "trim"),
                                        False, init_frames=depth_frames)
            plan_info.update(dict((k, short[k]) for k in ("max_frames", "extract_from_frame",
                                                           "extract_nth_frame", "source_frames")))
            result["init_frames"] = depth_frames
        sweep_plan = plan(values, plan_info["max_frames"], plan_info.get("extract_from_frame") or 0,
                          plan_info.get("extract_nth_frame") or 1, depth_frames)
        out = render(depth, job["out_share"], sweep_plan, job["size"], job.get("fps", 30.0))
        result.update(ok=True, frames=out["frames"], codec=out["codec"], depth_frames=depth_frames,
                      describe=describe(sweep_plan), warnings=sweep_plan["warnings"],
                      out_share=job["out_share"], out_container=job.get("out_container"))
        if result.get("init_frames") and job.get("depth"):
            # The next Queue plans the shorter length from the start, so its key differs: let
            # that key find this same video instead of rendering it again.
            alias = job_key(job["depth"], values, plan_info, job["size"])
            if alias != job.get("key"):
                result["alias_sidecar"] = os.path.join(os.path.dirname(job["sidecar"]),
                                                       "cn_sweep_%s.mp4.json" % alias)
    except Exception as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
    result["seconds"] = round(time.time() - started, 2)
    try:
        if result.get("alias_sidecar"):
            _write_json(result["alias_sidecar"], result)
        _write_json(job["sidecar"], result)
    except Exception:
        pass
    return result
