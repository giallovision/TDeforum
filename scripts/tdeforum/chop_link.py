"""CHOP links: a CHOP channel dropped straight onto a deforum parameter.

Drag a channel (from a Pattern / LFO / Animation / Script CHOP ...) onto a schedule
parameter, e.g. Motion 3D > Translation Z, and pick **CHOP Reference** (an expression
like ``op('pattern1')['chan1']``) or **Export CHOP**. The parameter then shows the
channel's value live in TouchDesigner, and at Queue the *whole* channel is read and baked
into the Deforum schedule, frame by frame, instead of the one value under the playhead.

Expressions may do maths on channels (``op('pattern1')['chan1'] * 2 + 1``,
``op('lfo1')[0] + op('noise1')['chan1']``): they are evaluated once with every channel
reference standing for the channel's whole array (numpy). An expression that cannot be
evaluated that way (``math.sin(...)``, ``me.time.frame``) falls back to its first channel
reference, used as-is, with a warning; an expression with no CHOP in it is an ordinary
expression and keeps its current value.

Timing (Mod Matrix > CHOP Link Timing):
    timeline  (default) the channel is read on the timeline: the samples under the loop's
              timeline span (Pipeline > Feed Loop Start, the same span beat_clock counts),
              so the render follows exactly what the parameter shows while the timeline
              plays (a Pattern CHOP with Length me.time.end; past its end it wraps)
    loop      the whole channel is one loop, stretched to the render (any length works;
              a Pattern CHOP with Cycles 4 = four cycles per loop)

This module has no TouchDesigner imports: the controller hands it parameter objects and a
``resolve(path)`` function; the tests hand it fakes.
"""

import math
import re

LOOP, TIMELINE = "loop", "timeline"
TIMINGS = [TIMELINE, LOOP]
TIMING_LABELS = ["Timeline (as it plays from Feed Loop Start)", "Whole channel = one loop (stretch)"]

# op('path')['chan'] / op("path")[0] / op('path').chan('chan')
_REF = re.compile(r"""op\(\s*(['"])(?P<path>.+?)\1\s*\)\s*"""
                  r"""(?:\[\s*(?:(['"])(?P<name>.+?)\3|(?P<index>\d+))\s*\]"""
                  r"""|\.chan\(\s*(['"])(?P<cname>.+?)\6\s*\))""")


class Link(object):
    """One linked parameter: the samples (one value per CHOP sample) and where they came from."""
    __slots__ = ("samples", "rate", "start", "source", "note")

    def __init__(self, samples, rate=None, start=0.0, source="", note=None):
        self.samples = [float(v) for v in samples]
        self.rate = float(rate) if rate else None
        self.start = float(start or 0.0)
        self.source = source
        self.note = note

    def as_dict(self):
        return {"samples": self.samples, "rate": self.rate, "start": self.start,
                "source": self.source, "note": self.note}


def mode_name(par):
    return getattr(getattr(par, "mode", None), "name", str(getattr(par, "mode", ""))).split(".")[-1].upper()


def _is_chop(o):
    return o is not None and hasattr(o, "numChans") and hasattr(o, "chans")


def _channel(chop, key):
    chans = list(chop.chans())
    if isinstance(key, int):
        return chans[key] if 0 <= key < len(chans) else None
    for chan in chans:
        if chan.name == key:
            return chan
    return None


def _vals(chan):
    return [float(v) for v in chan.vals]


def _meta(chop):
    rate = getattr(chop, "rate", None)
    try:
        rate = float(rate) if rate else None
    except (TypeError, ValueError):
        rate = None
    try:
        start = float(getattr(chop, "start", 0) or 0)
    except (TypeError, ValueError):
        start = 0.0
    return rate, start


def _label(chop, key):
    return "%s[%s]" % (getattr(chop, "path", getattr(chop, "name", "?")),
                       key if isinstance(key, int) else repr(str(key)))


class _ChopView(object):
    """What ``op('pattern1')`` evaluates to inside a linked expression."""

    def __init__(self, chop, used):
        self._chop, self._used = chop, used

    def _get(self, key):
        import numpy
        chan = _channel(self._chop, key)
        if chan is None:
            raise KeyError("%s has no channel %r" % (getattr(self._chop, "path", "CHOP"), key))
        self._used.append((self._chop, key))
        return numpy.asarray(_vals(chan), dtype=float)

    def __getitem__(self, key):
        return self._get(key)

    def chan(self, key):
        return self._get(key)

    def __getattr__(self, name):
        return getattr(self._chop, name)


def _from_expression(par, owner, resolve):
    expr = str(getattr(par, "expr", "") or "").strip()
    if not expr or "op(" not in expr:
        return None
    used = []

    def op(path):
        target = resolve(path)
        return _ChopView(target, used) if _is_chop(target) else target

    namespace = {"op": op, "me": owner, "math": math}
    if owner is not None and hasattr(owner, "parent"):
        namespace["parent"] = owner.parent
    try:
        import numpy
        namespace["np"] = namespace["numpy"] = numpy
        result = eval(expr, namespace)   # the parameter's own expression, as TD would run it
        if used:
            arr = numpy.asarray(result, dtype=float).reshape(-1)
            if arr.size:
                rate, start = _meta(used[0][0])
                return Link(arr.tolist(), rate, start, " + ".join(sorted(set(_label(c, k) for c, k in used)))
                            if len(used) > 1 else _label(*used[0]))
    except Exception:
        pass
    match = _REF.search(expr)       # fallback: the first channel reference, as-is
    if not match:
        return None
    chop = resolve(match.group("path"))
    if not _is_chop(chop):
        return None
    key = int(match.group("index")) if match.group("index") else (match.group("name") or match.group("cname"))
    chan = _channel(chop, key)
    if chan is None:
        return Link([], source=_label(chop, key), note="channel %r not found" % (key,))
    rate, start = _meta(chop)
    whole = match.group(0).strip() == expr
    return Link(_vals(chan), rate, start, _label(chop, key),
                None if whole else "expression %r could not be evaluated over the whole channel; "
                                   "used %s as-is" % (expr, _label(chop, key)))


def _from_export(par):
    chop = getattr(par, "exportOP", None)
    if not _is_chop(chop):
        return None
    source = getattr(par, "exportSource", None)
    name = getattr(source, "name", None)
    chan = _channel(chop, name) if name is not None else None
    if chan is None:
        return None
    rate, start = _meta(chop)
    return Link(_vals(chan), rate, start, _label(chop, name) + " (export)")


def link_of(par, owner=None, resolve=None):
    """The Link driving ``par``, or None when it is not driven by a CHOP channel."""
    if par is None:
        return None
    mode = mode_name(par)
    if mode == "EXPORT":
        return _from_export(par)
    if mode == "EXPRESSION":
        return _from_expression(par, owner, resolve or (lambda path: None))
    return None


def loop_samples(link, timing, loop_seconds, loop_start_seconds=0.0):
    """The samples that make up ONE loop (resample_loop stretches them to render frames)."""
    samples = link["samples"] if isinstance(link, dict) else link.samples
    rate = link["rate"] if isinstance(link, dict) else link.rate
    start = link["start"] if isinstance(link, dict) else link.start
    n = len(samples)
    if timing != TIMELINE or n < 2 or not rate or not loop_seconds or loop_seconds <= 0:
        return list(samples)
    count = max(2, int(round(loop_seconds * rate)))
    first = loop_start_seconds * rate - (start or 0.0)
    out = []
    for k in range(count):
        pos = first + k
        i = int(math.floor(pos))
        frac = pos - i
        a, b = samples[i % n], samples[(i + 1) % n]
        out.append(a + (b - a) * frac)
    return out
