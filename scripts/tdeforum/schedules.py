"""Keyframe-string helpers shared by the payload builder and the bake button."""


def as_schedule(value):
    """'0.5' -> '0:(0.5)'. Strings that already contain a keyframe pass through."""
    text = str(value).strip()
    if text == "" or ":" in text:
        return text
    return "0:(%s)" % text


def quantize_indices(total, points):
    """Equidistant sample indices from 0 to total-1 (both ends included).

    points <= 0, or >= total, bakes every sample (the original bake behaviour).
    """
    if total <= 0:
        return []
    if points <= 0 or points >= total:
        return list(range(total))
    if points == 1:
        return [0]
    indices = []
    for i in range(points):
        idx = int(round(i * (total - 1) / float(points - 1)))
        if not indices or idx != indices[-1]:
            indices.append(idx)
    return indices


def keyframe_string(samples, points=0, precision=4):
    """Bake a list of per-frame samples into '0:(v), 10:(v), ...'."""
    samples = list(samples)
    return ", ".join(
        "%d:(%.*f)" % (i, precision, samples[i])
        for i in quantize_indices(len(samples), points)
    )


def checkpoint_schedule(raw, models, default_model):
    """Turn the Sdmodelcheckpoint field into Deforum's checkpoint_schedule.

    Accepts an index ('2'), a filename, or a schedule ('0: 0, 75: 1' or
    '{0: "a.safetensors"}'). Numeric values are looked up in ``models``
    (the available_models table: index -> filename).
    """
    def resolve(value):
        value = value.strip().strip('"').strip("'")
        if value.isdigit():
            return models.get(value, default_model)
        return value

    text = str(raw).strip()
    if ":" not in text:
        return '0: "%s"' % resolve(text)

    entries = []
    for pair in text.replace("{", "").replace("}", "").split(","):
        if ":" not in pair:
            continue
        frame, value = pair.split(":", 1)
        frame = frame.strip().strip('"').strip("'")
        entries.append('%s: "%s"' % (frame, resolve(value)))
    return ", ".join(entries)
