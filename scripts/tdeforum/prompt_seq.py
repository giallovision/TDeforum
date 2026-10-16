"""Beat-indexed prompt sequence -> Deforum ``prompts`` dict.

Deforum (no Parseq) *holds* each prompt until the next keyframe; it does not
blend between them. A crossfade is therefore written as a composable-diffusion
prompt with frame-dependent weights, active only during the fade window:

    "<A> :`(E - t)/X.0` AND <B> :`(t - S)/X.0`"     for S <= t < E,  X = E - S

Deforum replaces every letter ``t`` inside backticks with the frame number and
evaluates the result, so these weights use only digits, t and + - * / ( ).
A1111 then reads "text :weight AND text :weight". During a fade each frame is
conditioned on both prompts (roughly doubles the UNet cost for those frames).

With a seamless loop the last prompt fades back into the first one at the loop
point, and the overlap tail past the loop repeats the head's keys, so the tail
the loop player crossfades from looks like the start it fades into.
"""

from . import modulation


def _clean(prompt, index, warnings):
    text = " ".join(str(prompt).split())
    if "`" in text:
        warnings.append("prompt row %d: backticks removed (Deforum evaluates them as math)" % index)
        text = text.replace("`", "")
    if " AND " in text:
        warnings.append("prompt row %d uses AND; crossfades into or out of it will misweight" % index)
    return text


def parse_rows(rows, default_xfade):
    """rows: iterable of (beat, prompt, xfade) with strings or numbers; header/blank rows skipped."""
    out, warnings = [], []
    for i, row in enumerate(rows):
        row = list(row) + ["", "", ""]
        beat, prompt, xfade = str(row[0]).strip(), str(row[1]).strip(), str(row[2]).strip()
        if not prompt:
            continue
        try:
            beat = float(beat)
        except ValueError:
            continue  # header row ("beat | prompt | xfade") or junk
        try:
            xfade = float(xfade) if xfade else float(default_xfade)
        except ValueError:
            warnings.append("prompt row %d: crossfade %r is not a number; using %g" % (i, xfade, default_xfade))
            xfade = float(default_xfade)
        out.append((beat, _clean(prompt, i, warnings), max(0.0, xfade)))
    out.sort(key=lambda r: r[0])
    return out, warnings


def _blend(a, b, start, end):
    width = end - start
    # %d.0: numexpr floor-divides int / int inside Deforum (see modulation.py).
    return "%s :`(%d - t)/%d.0` AND %s :`(t - %d)/%d.0`" % (a, end, width, b, start, width)


def compile_sequence(rows, plan, default_xfade=1.0):
    """Return (prompts dict, warnings). rows as for parse_rows; plan from tempo.plan()."""
    entries, warnings = parse_rows(rows, default_xfade)
    if not entries:
        return None, warnings
    fpb, loop = plan["fpb"], plan["loop_frames"]
    total, seamless = plan["max_frames"], plan["seamless"]

    keyed = []
    for beat, prompt, xfade in entries:
        frame = int(round(beat * fpb))
        if frame >= loop:
            warnings.append("prompt at beat %g starts after the %d-beat loop; ignored" % (beat, plan["loop_beats"]))
            continue
        if keyed and keyed[-1][0] == frame:
            warnings.append("two prompts on frame %d (beat %g); the later row wins" % (frame, beat))
            keyed[-1] = (frame, prompt, xfade)
            continue
        keyed.append((frame, prompt, xfade))
    if not keyed:
        return None, warnings
    if keyed[0][0] != 0:
        lead = keyed[-1] if seamless else keyed[0]
        keyed.insert(0, (0, lead[1], lead[2]))

    # One loop worth of keys: {frame: (prompt,) | (a, b, width)}
    head = {}
    for i, (start, prompt, xfade) in enumerate(keyed):
        head[start] = (prompt,)
        if i + 1 < len(keyed):
            end, nxt = keyed[i + 1][0], keyed[i + 1][1]
        elif seamless:
            end, nxt = loop, keyed[0][1]
        else:
            continue
        width = min(int(round(xfade * fpb)), end - start)
        if width > 0 and nxt != prompt:
            head[end - width] = (prompt, nxt, width)

    def render(frame, entry):
        if len(entry) == 1:
            return entry[0]
        a, b, width = entry
        return _blend(a, b, frame, frame + width)

    prompts = dict((f, render(f, e)) for f, e in head.items())
    if seamless:
        # The tail past the loop repeats the head (fade windows re-anchored).
        prompts[loop] = keyed[0][1]
        for frame, entry in sorted(head.items()):
            shifted = frame + loop
            if shifted >= total:
                break
            prompts[shifted] = render(shifted, entry)
    return dict((str(f), prompts[f]) for f in sorted(prompts)), warnings


def rows_from_prompts(prompts, fpb):
    """Seed rows from a legacy {"frame": "prompt"} dict (prompt.json)."""
    rows = []
    for key, prompt in sorted(prompts.items(), key=lambda kv: float(kv[0]) if _num(kv[0]) else 0):
        frame = float(key) if _num(key) else 0.0
        rows.append((modulation.fmt(round(frame / fpb * 4) / 4.0), prompt, ""))
    return rows


def _num(text):
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False
