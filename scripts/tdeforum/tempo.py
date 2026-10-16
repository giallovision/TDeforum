"""Tempo -> frame plan for beat-locked Deforum renders.

Everything is expressed in *render frames* (the frames Deforum diffuses or
warps), because that is the ``t`` Deforum puts into schedule expressions.

Two strategies (Tempo page, *Render strategy*):

``cadence``      render at the output rate (60 fps). ``diffusion_cadence`` diffuses
                 every Nth frame and warps the frames in between, so the cost is
                 ~60/N diffusions per second while motion stays on the 60 fps grid.
``interpolate``  render at a lower rate (15/20/30 fps) and let Deforum's RIFE or FILM
                 interpolation bring it up to the output rate (x = out / render).

At 60 fps one beat is 40 frames at 90 bpm, 30 at 120 and 24 at 150. Lower
render rates must still give a whole number of frames per *loop*, otherwise the
seam drifts; plan() reports that as a warning (e.g. 90 bpm at 20 fps).
"""

STRATEGIES = ["cadence", "interpolate"]
STRATEGY_LABELS = ["60 fps + cadence (every frame on the beat grid)",
                   "Low fps + RIFE/FILM interpolation"]
RENDER_FPS_CHOICES = ["15", "20", "30"]
INTERP_ENGINES = ["RIFE v4.6", "FILM"]
_EPS = 1e-6


def frames_per_beat(bpm, fps):
    """Frames per beat (float). 120 bpm at 60 fps -> 30.0."""
    bpm = float(bpm)
    if bpm <= 0:
        raise ValueError("bpm must be > 0")
    return float(fps) * 60.0 / bpm


def beats_to_frames(beats, bpm, fps):
    return float(beats) * frames_per_beat(bpm, fps)


def _whole(value):
    return abs(value - round(value)) < _EPS


def plan(bpm=120.0, beats_per_bar=4, bars=1, out_fps=60, strategy="cadence",
         render_fps=15, engine="RIFE v4.6", seamless=True, overlap_beats=1.0):
    """Return the render plan for a tempo-locked loop.

    Keys:
      bpm, loop_beats, out_fps, render_fps, interp_x, engine (None when cadence)
      fpb            render frames per beat (float)
      loop_frames    render frames in one loop (int)
      overlap_frames extra render frames rendered past the loop for the seam crossfade
      max_frames     loop_frames + overlap_frames (what Deforum renders)
      out_loop_frames  loop length in output frames (what the loop player wraps at)
      warnings       list of str
    """
    warnings = []
    bpm = float(bpm)
    beats_per_bar = max(1, int(beats_per_bar))
    bars = max(1, int(bars))
    out_fps = int(out_fps)
    loop_beats = beats_per_bar * bars

    if strategy == "interpolate":
        render_fps = int(render_fps)
        if render_fps <= 0 or out_fps % render_fps:
            raise ValueError("output fps %d is not a whole multiple of render fps %d" % (out_fps, render_fps))
        interp_x = out_fps // render_fps
        if not 2 <= interp_x <= 10:
            raise ValueError("interpolation x%d out of Deforum's 2..10 range" % interp_x)
        if engine not in INTERP_ENGINES:
            raise ValueError("unknown interpolation engine %r" % engine)
    else:
        strategy, render_fps, interp_x, engine = "cadence", out_fps, 1, None

    fpb = frames_per_beat(bpm, render_fps)
    exact_loop = loop_beats * fpb
    loop_frames = int(round(exact_loop))
    if not _whole(exact_loop):
        warnings.append(
            "%g bpm x %d beats at %d fps is %.3f frames, rounded to %d; the loop will drift. "
            "Use a render fps where one loop is a whole number of frames (30 fps works for 90/120/150 bpm)."
            % (bpm, loop_beats, render_fps, exact_loop, loop_frames))
    loop_frames = max(1, loop_frames)

    overlap_frames = 0
    if seamless:
        overlap_frames = int(round(max(0.0, float(overlap_beats)) * fpb))
        overlap_frames = min(overlap_frames, loop_frames)

    out_exact = loop_beats * frames_per_beat(bpm, out_fps)
    if not _whole(out_exact):
        warnings.append("%g bpm does not give a whole number of %d fps frames per loop (%.3f)"
                        % (bpm, out_fps, out_exact))

    return {
        "bpm": bpm, "beats_per_bar": beats_per_bar, "bars": bars, "loop_beats": loop_beats,
        "strategy": strategy, "out_fps": out_fps, "render_fps": render_fps,
        "interp_x": interp_x, "engine": engine, "fpb": fpb,
        "loop_frames": loop_frames, "overlap_frames": overlap_frames,
        "max_frames": loop_frames + overlap_frames,
        "out_loop_frames": int(round(out_exact)), "seamless": bool(seamless),
        "warnings": warnings,
    }


def describe(p):
    """One-line summary for the Tempo page status field."""
    text = "%g bpm | %d beats | loop %d f @ %d fps" % (p["bpm"], p["loop_beats"], p["loop_frames"], p["render_fps"])
    if p["overlap_frames"]:
        text += " + %d overlap" % p["overlap_frames"]
    if p["strategy"] == "interpolate":
        text += " | %s x%d -> %d fps" % (p["engine"], p["interp_x"], p["out_fps"])
    return text
