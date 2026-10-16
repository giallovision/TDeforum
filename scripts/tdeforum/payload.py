"""Build the Deforum batch request from Deforum_UI values.

Pure Python: TouchDesigner reads the UI and calls build_request(); tests call
it with plain dicts. Notes from checking Deforum's source (commit 5d63a339):

* The settings loader only applies keys Deforum knows. ``n_prompt`` is not
  one, so the negative prompt is sent as ``animation_prompts_negative``.
* The batch body has two keys: ``deforum_settings`` and ``options_overrides``.
  A1111 options such as ``sd_vae`` go in ``options_overrides``.
* ``extract_to_frame`` is inclusive, and in Video Input mode Deforum also applies
  extract_nth_frame / extract_to_frame to ControlNet guide videos.
* 2D ``border`` only knows replicate|wrap; 3D ``padding_mode`` knows
  border|reflection|zeros.
"""

import math

from . import schedules
from . import schema

DEFAULT_PROMPTS = {"0": "A cinematic macro shot of liquid gold morphing, biomorphic shapes"}
DEFAULT_CHECKPOINT = "angraRealflexLCMV6_v10.safetensors"
CN_UNITS = 5


def _text(value):
    return str(value).strip()


def _as_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes")
    return bool(value)


def _as_number(value, cast):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return cast(float(_text(value)))


def coerce(field, value):
    """Convert a TD parameter value into what Deforum expects for this field."""
    kind = field.kind
    if kind == schema.TOGGLE:
        return _as_bool(value)
    if field.as_schedule:
        return schedules.as_schedule(_text(value))
    if kind == schema.SCHEDULE:
        return schedules.as_schedule(value)
    if kind == schema.INT:
        return int(round(_as_number(value, float)))
    if kind == schema.FLOAT:
        return _as_number(value, float)
    if kind == schema.SEED:
        text = _text(value)
        return int(text) if text.lstrip("-").isdigit() else text
    return _text(value)


def border_modes(choice):
    """UI border choice -> (2D border, 3D padding_mode)."""
    if choice == "zeros":
        return "replicate", "zeros"
    if choice == "wrap":
        return "wrap", "reflection"
    return "replicate", "border"


def plan_frames(mode, ui_max_frames, frame_mode="trim", use_mask_video=False,
                init_frames=None, mask_frames=None):
    """Work out max_frames and the frame-extraction window.

    Returns a dict with max_frames, extract_* settings (or None when Deforum's
    defaults are fine) and source_frames: how many raw frames Deforum reads
    from the init / ControlNet videos (what a ComfyUI preprocess must cover).
    """
    ui_max_frames = max(1, int(ui_max_frames))
    plan = {"mode": mode, "frame_mode": frame_mode, "max_frames": ui_max_frames,
            "extract_from_frame": None, "extract_to_frame": None,
            "extract_nth_frame": None, "source_frames": ui_max_frames, "limited_by": "ui"}

    if mode == "Video Input":
        if frame_mode == "stride":
            asset = init_frames or ui_max_frames
            nth = max(1, asset // ui_max_frames)
            available = int(math.ceil(asset / float(nth)))
            max_frames = min(ui_max_frames, available)
            limited = "init video" if available < ui_max_frames else "ui"
            if use_mask_video and mask_frames:
                mask_available = int(math.ceil(min(mask_frames, asset) / float(nth)))
                if mask_available < max_frames:
                    max_frames, limited = mask_available, "mask video"
            plan.update(max_frames=max_frames, extract_from_frame=0,
                        extract_to_frame=asset - 1, extract_nth_frame=nth,
                        source_frames=asset, limited_by=limited)
        else:
            cap, limited = ui_max_frames, "ui"
            if init_frames and init_frames < cap:
                cap, limited = init_frames, "init video"
            if use_mask_video and mask_frames and mask_frames < cap:
                cap, limited = mask_frames, "mask video"
            plan.update(max_frames=cap, extract_from_frame=0, extract_to_frame=cap - 1,
                        extract_nth_frame=1, source_frames=cap, limited_by=limited)
        return plan

    if mode in ("2D", "3D"):
        cap, limited = ui_max_frames, "ui"
        if use_mask_video and mask_frames and mask_frames < cap:
            cap, limited = mask_frames, "mask video"
        plan.update(max_frames=cap, source_frames=cap, limited_by=limited)
        if use_mask_video:
            plan.update(extract_from_frame=0, extract_to_frame=cap - 1, extract_nth_frame=1)
    return plan


def build_request(values, prompts=None, models=None, frame_counter=None,
                  default_checkpoint=DEFAULT_CHECKPOINT):
    """Return {"request": body, "plan": frame plan, "warnings": [str]}.

    values         {api_name: value} as read from Deforum_UI (missing keys = not on the UI)
    prompts        {"frame": "prompt"} timeline
    models         {"index": "file.safetensors"} from the available_models table
    frame_counter  callable(container_path) -> int | None, used to cap frame counts
    """
    models = models or {}
    warnings = []
    settings = {"prompts": dict(prompts or DEFAULT_PROMPTS)}
    options = {}

    for field in schema.FIELDS:
        if field.target is None or field.api.startswith("cn_") or field.api not in values:
            continue
        raw = values[field.api]
        text = _text(raw)
        if text == "" and field.kind != schema.TOGGLE:
            continue

        if field.kind == schema.CHECKPOINT:
            settings["enable_checkpoint_scheduling"] = True
            settings["checkpoint_schedule"] = schedules.checkpoint_schedule(
                text, models, default_checkpoint)
            continue
        if field.api == "border":
            settings["border"], settings["padding_mode"] = border_modes(text)
            continue

        try:
            value = coerce(field, raw)
        except (TypeError, ValueError):
            warnings.append("%s: could not read %r, left at Deforum default" % (field.td_name, raw))
            continue
        (options if field.target == "options" else settings)[field.key] = value

    # ControlNet: unit 1 from the UI (empty strings are meaningful here), 2-5 off.
    for field in schema.cn_fields(1):
        raw = values.get(field.api, field.default)
        try:
            settings[field.key] = coerce(field, raw)
        except (TypeError, ValueError):
            settings[field.key] = coerce(field, field.default)
            warnings.append("%s: could not read %r, used %r" % (field.td_name, raw, field.default))
    # Deforum parses every unit's schedules even when the unit is off, so units 2-5
    # get unit 1's defaults with the unit number swapped; only `enabled` is False.
    for unit in range(2, CN_UNITS + 1):
        for field in schema.cn_fields(1):
            if field.api == "cn_1_enabled":
                continue
            key = field.key.replace("cn_1_", "cn_%d_" % unit, 1)
            settings[key] = coerce(field, field.default)
        settings["cn_%d_enabled" % unit] = False

    # Output handling the TD side relies on (auto-load expects <outdir>/<timestring>.mp4).
    use_mask_video = _as_bool(values.get("use_mask_video", False))
    settings.update(store_frames_in_ram=True, skip_video_creation=False,
                    use_mask=use_mask_video, overlay_mask=False)

    # Frame plan, capped by the real length of the videos on the share.
    mode = _text(values.get("animation_mode", "2D"))
    frame_mode = _text(values.get("video_frame_mode", "trim")) or "trim"
    ui_max = values.get("max_frames", 240)
    init_frames = mask_frames = None
    if frame_counter is not None:
        if mode == "Video Input":
            init_frames = _count(frame_counter, values.get("video_init_path"), "init video", warnings)
        if use_mask_video:
            mask_frames = _count(frame_counter, values.get("video_mask_path"), "mask video", warnings)
    plan = plan_frames(mode, ui_max, frame_mode, use_mask_video, init_frames, mask_frames)
    settings["max_frames"] = plan["max_frames"]
    for key in ("extract_from_frame", "extract_to_frame", "extract_nth_frame"):
        if plan[key] is not None:
            settings[key] = plan[key]

    request = {"deforum_settings": settings}
    if options:
        request["options_overrides"] = options
    return {"request": request, "plan": plan, "warnings": warnings}


def _count(counter, path, label, warnings):
    path = _text(path or "")
    if not path:
        return None
    try:
        frames = counter(path)
    except Exception as exc:  # cv2 / share errors must not block a render
        frames = None
        warnings.append("%s: frame count failed (%s)" % (label, exc))
    if frames is None:
        warnings.append("%s %s not readable from TouchDesigner; frame cap not applied" % (label, path))
    return frames


def summary(result):
    s = result["request"]["deforum_settings"]
    plan = result["plan"]
    parts = [s.get("animation_mode", "?"), "%s frames" % s.get("max_frames")]
    if plan.get("extract_nth_frame", 1) not in (None, 1):
        parts.append("stride %d" % plan["extract_nth_frame"])
    if plan.get("limited_by") not in (None, "ui"):
        parts.append("capped by %s" % plan["limited_by"])
    parts.append("%sx%s" % (s.get("W"), s.get("H")))
    parts.append("CN1 %s" % ("on: " + str(s.get("cn_1_model")) if s.get("cn_1_enabled") else "off"))
    return " | ".join(parts)
