"""ControlNet guide feeds taken from TouchDesigner TOPs.

Deforum cannot read a TOP. It reads a *file*: ``cn_N_vid_path`` is either one
still image (.png/.jpg/.bmp, used for every frame) or a video (mov/mp4/avi/webm/
mpg...). For a video, Deforum unpacks frames ``0 .. max_frames-1`` to JPEG and
frame k of the video guides Deforum frame k (at 5d63a339, deforum_controlnet.py,
``process_controlnet_input_frames`` / ``read_cn_data``). Consequences:

* the video's own frame rate is irrelevant; its *frame count* must be at least
  ``max_frames`` or the tail of the render gets no guidance;
* with a low render rate (RIFE/FILM mode) frame k is one render step, so the
  feed has to be sampled at the render rate, not recorded at 60 fps;
* image sequences are rejected (the path must end in a video extension).

So the TouchDesigner side records exactly ``max_frames`` frames: frame k shows
the source TOP at loop time k / render_fps, wrapping around the loop for the
seamless-loop overlap. This module is the pure planning part (no TouchDesigner
objects); td_controller.py drives the recording.
"""

import posixpath

from . import config
from . import tempo

FILE, TOP_LOOP, TOP_STILL, SWEEP = "file", "top_loop", "top_still", "sweep"
MODES = [FILE, TOP_LOOP, TOP_STILL, SWEEP]
MODE_LABELS = ["Existing file (Vid Path)", "TOP: record the loop", "TOP: one still frame",
               "Sweep Depth (Video Input: sweeping band of the depth video)"]
ADD_FRAME, CONTINUOUS = "addframe", "continuous"
METHODS = [ADD_FRAME, CONTINUOUS]
METHOD_LABELS = ["Add Frame, one pulse per planned frame (exact)",
                 "Record every cooked frame (fallback if Add Frame does nothing)"]
UNITS = 3                      # ControlNet units that have a page on the COMP
STILL_EXT = ".png"
_EPS = 1e-6


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


DEFAULT_TOP = "/project1/final_out"   # Source TOP of every unit until you set another

class Request(object):
    """One ControlNet unit whose guide comes from a TOP."""
    __slots__ = ("unit", "mode", "top")

    def __init__(self, unit, mode, top):
        self.unit, self.mode, self.top = unit, mode, top

    def __repr__(self):
        return "Request(unit=%d, mode=%s, top=%r)" % (self.unit, self.mode, self.top)


def mode_of(values, unit):
    mode = str(values.get("feed_%d_mode" % unit, FILE) or FILE).strip()
    return mode if mode in MODES else FILE


def requests(values, units=UNITS):
    """Units whose guide must be captured from a TOP before rendering.

    Enabled units whose Guide Source is not "file". A Sweep Depth unit is also recorded while
    it is switched off when *Sweep Depth > Also use as mask video* is on (mask-only use).
    """
    mask_only = _truthy(values.get("sweep_as_mask", False)) and _truthy(values.get("sweep_enabled", False))
    out = []
    for unit in range(1, units + 1):
        mode = mode_of(values, unit)
        if mode == FILE:
            continue
        if _truthy(values.get("cn_%d_enabled" % unit, False)) or (mode == SWEEP and mask_only):
            out.append(Request(unit, mode, str(values.get("feed_%d_top" % unit, "") or "").strip()))
    return out


def method_of(values):
    method = str(values.get("feed_method", ADD_FRAME) or ADD_FRAME).strip()
    return method if method in METHODS else ADD_FRAME


def extension(cfg, mode):
    return STILL_EXT if mode == TOP_STILL else str(cfg.get("cn_feed_ext", ".mp4"))


def container_path(cfg, unit, mode):
    """Where the Deforum container will read the feed (the cn_N_vid_path value)."""
    return "%s/cn%d_feed%s" % (str(cfg["cn_feed_dir"]).rstrip("/"), unit, extension(cfg, mode))


def share_path(cfg, unit, mode):
    """Where TouchDesigner writes the feed (None if cn_feed_dir is not on the share)."""
    return config.to_share(cfg, container_path(cfg, unit, mode))


def project_frames_per_loop(tp, project_rate):
    """Timeline frames in one loop at the project's own frame rate (float)."""
    return tp["loop_beats"] * tempo.frames_per_beat(tp["bpm"], project_rate)


def frame_plan(tp, total, project_rate, loop_start, wrap=True):
    """Timeline frame to show for every render frame.

    tp            tempo.plan() dict, or None when the length is manual
    total         number of render frames Deforum will render (max_frames)
    project_rate  the timeline's frame rate (usually 60)
    loop_start    timeline frame where the loop starts (usually 1)
    wrap          False: frames run on past the loop (Sweep Depth needs each render frame
                  to be its own timeline frame; the recorder lengthens the timeline)

    Returns {"frames": [timeline frame per render frame], "step": project frames
    per render frame, "loop": project frames per loop or None, "warnings": [...]}.
    With a tempo plan the frames wrap around the loop, so the overlap tail shows
    the start of the loop again (the same periodicity the prompt and modulation
    schedules have). Raises ValueError when the render rate cannot be sampled
    from the timeline.
    """
    total = max(1, int(total))
    project_rate = float(project_rate)
    render_fps = float(tp["render_fps"]) if tp else project_rate
    step = project_rate / render_fps
    if step < 1.0 - _EPS:
        raise ValueError("the timeline runs at %g fps, below the %g fps render rate, so it cannot be sampled"
                         % (project_rate, render_fps))
    if abs(step - round(step)) > _EPS:
        raise ValueError("timeline rate %g fps is not a whole multiple of the %g fps render rate"
                         % (project_rate, render_fps))
    step = int(round(step))
    warnings = []

    loop = None
    if tp:
        exact = project_frames_per_loop(tp, project_rate)
        loop = max(1, int(round(exact)))
        if abs(exact - round(exact)) > _EPS:
            warnings.append("one loop is %.3f timeline frames at %g fps; the feed loop will drift"
                            % (exact, project_rate))
    frames = []
    for k in range(total):
        offset = k * step
        if loop and wrap:
            offset %= loop
        frames.append(int(loop_start) + offset)
    return {"frames": frames, "step": step, "loop": loop, "wrap": bool(wrap), "warnings": warnings}


def describe(plan):
    frames = plan["frames"]
    text = "%d frames, timeline %d..%d" % (len(frames), min(frames), max(frames))
    if plan["step"] > 1:
        text += " every %d" % plan["step"]
    if plan["loop"] and plan.get("wrap", True) and len(frames) * plan["step"] > plan["loop"]:
        text += ", wrapping at %d" % plan["loop"]
    return text


def verify(expected, actual):
    """(ok, message) for a recorded file's frame count."""
    if actual is None:
        return True, "frame count not checked (cv2 or the file is unavailable)"
    if actual < expected:
        return False, "recorded %d frames, expected %d" % (actual, expected)
    if actual > expected:
        return True, "recorded %d frames, expected %d; the extra frames are ignored by Deforum" % (actual, expected)
    return True, "%d frames" % actual


def is_video(path):
    return posixpath.splitext(str(path).replace("\\", "/"))[1].lower() in (
        ".mov", ".mpeg", ".mp4", ".m4v", ".avi", ".mpg", ".webm")
