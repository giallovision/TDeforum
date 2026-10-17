"""Beat-locked modulation for Deforum schedules.

Each modulatable parameter has a *base* value. Modulation slots add
``depth * shape(t / period + phase)`` on top, where period = beats * frames per
beat. Two ways to hand that to Deforum:

* **Expression** (no CHOP input for the field): one keyframe ``0:(base + ...)``
  that Deforum evaluates with numexpr at every frame ``t``. Exact and tiny.
* **Bake** (a CHOP channel named after the field is present): every frame is
  sampled here (base + CHOP + the same slot shapes in Python) and sent as
  ``0:(v), 1:(v), ...``.

Deforum's keyframe parser splits on ``,`` and ``:`` *before* evaluating, so the
expressions below never use a comma (no where(), min(), max(), arctan2()).
numexpr has no ``pi`` constant, so it is written out. numexpr.evaluate() only
does true division when the *calling* module imported __future__.division,
which Deforum's do not, so ``t/30`` would floor-divide: every divisor is
written as a float literal (``t/30.0``). The Python twin of every
shape uses the same arithmetic so the tests can check expression == sample.
"""

import math

from . import schedules

PI = "3.141592653589793"

# name -> (label, unipolar, default sharpness)
SHAPES = [
    ("sine", "Sine", False),
    ("triangle", "Triangle", False),
    ("saw_up", "Saw up (ramp)", False),
    ("saw_down", "Saw down", False),
    ("square", "Square (soft, Sharpness = edge)", False),
    ("decay", "Kick decay 1 -> 0 (Sharpness = speed)", True),
    ("bump", "Bump 0 -> 1 -> 0 (Sharpness = narrowness)", True),
]
SHAPE_NAMES = [s[0] for s in SHAPES]
SHAPE_LABELS = [s[1] for s in SHAPES]
UNIPOLAR = set(s[0] for s in SHAPES if s[2])
BEAT_CHOICES = ["0.25", "0.5", "1", "2", "4", "8", "16", "32", "64"]
BEAT_LABELS = ["1/16 note", "1/8 note", "1 beat", "2 beats", "1 bar (4)", "2 bars", "4 bars",
               "8 bars", "16 bars"]
CHOP_MODES = ["add", "replace"]


def fmt(value):
    """Compact number for an expression; never scientific for normal ranges."""
    value = float(value)
    if value == int(value) and abs(value) < 1e12:
        return "%d" % int(value)
    text = "%.10f" % value
    return text.rstrip("0").rstrip(".")


def fmt_float(value):
    """Like fmt() but always a float literal ("30.0"): numexpr floor-divides int / int."""
    text = fmt(value)
    return text if ("." in text or "e" in text) else text + ".0"


def _shape_expr(shape, x, k):
    two_pi_x = "2*%s*%s" % (PI, x)
    if shape == "sine":
        return "sin(%s)" % two_pi_x
    if shape == "triangle":
        return "(4*abs(((%s + 0.75) %% 1) - 0.5) - 1)" % x
    if shape == "saw_up":
        return "(2*(%s %% 1) - 1)" % x
    if shape == "saw_down":
        return "(1 - 2*(%s %% 1))" % x
    if shape == "square":
        return "tanh(%s*sin(%s))" % (fmt(k), two_pi_x)
    if shape == "decay":
        return "exp(-%s*(%s %% 1))" % (fmt(k), x)
    if shape == "bump":
        return "abs(0.5 - 0.5*cos(%s))**%s" % (two_pi_x, fmt(k))
    raise ValueError("unknown shape %r" % shape)


def _shape_value(shape, x, k):
    two_pi_x = 2 * math.pi * x
    if shape == "sine":
        return math.sin(two_pi_x)
    if shape == "triangle":
        return 4 * abs(((x + 0.75) % 1) - 0.5) - 1
    if shape == "saw_up":
        return 2 * (x % 1) - 1
    if shape == "saw_down":
        return 1 - 2 * (x % 1)
    if shape == "square":
        return math.tanh(k * math.sin(two_pi_x))
    if shape == "decay":
        return math.exp(-k * (x % 1))
    if shape == "bump":
        return abs(0.5 - 0.5 * math.cos(two_pi_x)) ** k
    raise ValueError("unknown shape %r" % shape)


class Slot(object):
    """One row of the modulation matrix."""
    __slots__ = ("index", "target", "shape", "beats", "depth", "phase", "sharpness")

    def __init__(self, target, shape="sine", beats=1.0, depth=0.0, phase=0.0,
                 sharpness=4.0, index=0):
        if shape not in SHAPE_NAMES:
            raise ValueError("unknown shape %r" % shape)
        beats = float(beats)
        if beats <= 0:
            raise ValueError("slot %d: beats must be > 0" % index)
        self.index = index
        self.target = target
        self.shape = shape
        self.beats = beats
        self.depth = float(depth)
        self.phase = float(phase) % 1.0
        self.sharpness = max(0.01, float(sharpness))

    def period(self, fpb):
        return self.beats * fpb

    def _x_expr(self, fpb):
        period = fmt_float(self.period(fpb))
        if self.phase:
            return "(t/%s + %s)" % (period, fmt(self.phase))
        return "(t/%s)" % period

    def term_expr(self, fpb):
        return "%s*%s" % (fmt(abs(self.depth)), _shape_expr(self.shape, self._x_expr(fpb), self.sharpness))

    def value(self, t, fpb):
        x = t / self.period(fpb) + self.phase
        return self.depth * _shape_value(self.shape, x, self.sharpness)


def expression(base, slots, fpb):
    """Deforum expression (without the 0: key) for base + slots."""
    text = fmt(base)
    for slot in slots:
        if slot.depth == 0:
            continue
        sign = "-" if slot.depth < 0 else "+"
        text += " %s %s" % (sign, slot.term_expr(fpb))
    return text


def evaluate(base, slots, fpb, t, chop_value=None, chop_mode="add"):
    """Python value at render frame t (what the expression / bake produces)."""
    value = float(base)
    if chop_value is not None:
        value = chop_value if chop_mode == "replace" else value + chop_value
    for slot in slots:
        if slot.depth:
            value += slot.value(t, fpb)
    return value


def resample_loop(samples, loop_frames, total_frames):
    """Map a CHOP that describes ONE loop onto render frames 0..total-1.

    The CHOP may have any sample count (e.g. recorded at 60 fps while rendering
    at 15); it is stretched to loop_frames and wraps for the overlap tail, with
    linear interpolation that also wraps last -> first sample.
    """
    samples = [float(v) for v in samples]
    n = len(samples)
    if n == 0:
        return None
    if n == 1:
        return [samples[0]] * total_frames
    out = []
    for f in range(total_frames):
        pos = (f % loop_frames) * n / float(loop_frames)
        i = int(math.floor(pos))
        frac = pos - i
        a, b = samples[i % n], samples[(i + 1) % n]
        out.append(a + (b - a) * frac)
    return out


def compile_field(base, slots, fpb, total_frames, chop=None, chop_mode="add",
                  raw="", points=0, precision=5, base_curve=None):
    """Return (schedule string, (min, max) over the render, mode).

    mode is "raw", "constant", "expression", "baked" (Mod CHOP) or "chop" (a CHOP channel
    linked to the parameter itself: ``base_curve`` gives the base per render frame).
    """
    raw = str(raw or "").strip()
    if raw:
        return schedules.as_schedule(raw), None, "raw"
    active = [s for s in slots if s.depth]
    if base_curve is not None:
        values = [evaluate(base_curve[t], active, fpb, t, chop[t] if chop is not None else None, chop_mode)
                  for t in range(total_frames)]
        return schedules.keyframe_string(values, points, precision), (min(values), max(values)), "chop"
    if chop is None:
        values = [evaluate(base, active, fpb, t) for t in range(total_frames)] or [float(base)]
        bounds = (min(values), max(values))
        if not active:
            return "0:(%s)" % fmt(base), bounds, "constant"
        return "0:(%s)" % expression(base, active, fpb), bounds, "expression"
    values = [evaluate(base, active, fpb, t, chop[t], chop_mode) for t in range(total_frames)]
    return schedules.keyframe_string(values, points, precision), (min(values), max(values)), "baked"


def loop_warnings(slots, loop_beats):
    """Slots whose period does not divide the loop jump at the seam."""
    out = []
    for slot in slots:
        if not slot.depth:
            continue
        cycles = loop_beats / slot.beats
        if abs(cycles - round(cycles)) > 1e-6:
            out.append("slot %d (%s, %g beats) does not divide the %d-beat loop; it will jump at the seam"
                       % (slot.index, slot.target, slot.beats, loop_beats))
    return out
