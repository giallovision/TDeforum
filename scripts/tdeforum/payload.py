"""Build the Deforum batch request from the Deforum COMP's values.

Pure Python: TouchDesigner reads the COMP and calls build_request(); tests call
it with plain dicts. Notes from checking Deforum's source (commit 5d63a339):

* The settings loader only applies keys Deforum knows. ``n_prompt`` is not
  one, so the negative prompt is sent as ``animation_prompts_negative``.
* The batch body has two keys: ``deforum_settings`` and ``options_overrides``.
  A1111 options such as ``sd_vae`` go in ``options_overrides``.
* ``extract_to_frame`` is inclusive, and in Video Input mode Deforum also applies
  extract_nth_frame / extract_to_frame to ControlNet guide videos.
* 2D ``border`` only knows replicate|wrap; 3D ``padding_mode`` knows
  border|reflection|zeros.
* Every ControlNet unit's schedules are parsed even when the unit is off.
* Frame interpolation (RIFE/FILM) only runs with store_frames_in_ram off.
* The anti-blur kernel goes to cv2.GaussianBlur, which rejects even sizes.

Tempo mode (the COMP has a BPM and Length Source = tempo): the render length,
fps, interpolation, seed schedule, prompt sequence and every MOD schedule come
from tempo.plan(); see tempo.py, modulation.py and prompt_seq.py.
"""

import math

from . import chop_link, feed
from . import modulation
from . import prompt_seq
from . import schedules
from . import schema
from . import tempo

DEFAULT_PROMPTS = {"0": "A cinematic macro shot of liquid gold morphing, biomorphic shapes"}
DEFAULT_CHECKPOINT = "angraRealflexLCMV6_v10.safetensors"
CN_UNITS = 5


def raw_key(api):
    """values[] key holding a MOD field's <Name>raw override."""
    return api + ":raw"


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
    if kind in (schema.FLOAT, schema.MOD):
        return _as_number(value, float)
    if kind == schema.SEED:
        text = _text(value)
        return int(text) if text.lstrip("-").isdigit() else text
    return _text(value)


def border_modes(choice):
    """Legacy single border menu -> (2D border, 3D padding_mode)."""
    if choice == "zeros":
        return "replicate", "zeros"
    if choice == "wrap":
        return "wrap", "reflection"
    return "replicate", "border"


def hybrid_active(values):
    """Hybrid Video drives a 2D / 3D render from the init video's motion or pixels."""
    return _text(values.get("animation_mode", "")) in ("2D", "3D") and (
        _text(values.get("hybrid_motion", "None")) not in ("", "None")
        or _text(values.get("hybrid_composite", "None")) not in ("", "None"))


def plan_frames(mode, ui_max_frames, frame_mode="trim", use_mask_video=False,
                init_frames=None, mask_frames=None, hybrid=False):
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
        if hybrid and init_frames and init_frames < cap:
            cap, limited = init_frames, "init video"
        if use_mask_video and mask_frames and mask_frames < cap:
            cap, limited = mask_frames, "mask video"
        plan.update(max_frames=cap, source_frames=cap, limited_by=limited)
        if use_mask_video or hybrid:
            plan.update(extract_from_frame=0, extract_to_frame=cap - 1, extract_nth_frame=1)
    return plan


def tempo_plan(values):
    """tempo.plan() from COMP values, or None when the length is manual / no Tempo page."""
    if "bpm" not in values or _text(values.get("length_source", "tempo")) != "tempo":
        return None
    return tempo.plan(
        bpm=_as_number(values.get("bpm", 120), float),
        beats_per_bar=_as_number(values.get("beats_per_bar", 4), float),
        bars=_as_number(values.get("loop_bars", 1), float),
        out_fps=_as_number(values.get("out_fps", 60), float),
        strategy=_text(values.get("render_strategy", "cadence")),
        render_fps=_as_number(values.get("render_fps", 30), float),
        engine=_text(values.get("interp_engine", tempo.INTERP_ENGINES[0])),
        seamless=_as_bool(values.get("seamless_loop", True)),
        overlap_beats=_as_number(values.get("loop_overlap_beats", 1.0), float),
    )


def fit_bars(values, init_frames):
    """Most whole bars (plus the seam overlap) that fit in ``init_frames`` render frames, or None.

    For Tempo > Fit Loop to Init Video with Video Frame Mode = Trim (Stride already stretches
    the whole video over the loop)."""
    if not init_frames or _text(values.get("video_frame_mode", "trim")) == "stride":
        return None
    try:
        one = tempo_plan(dict(values, loop_bars=1))
    except (TypeError, ValueError):
        return None
    if not one:
        return None
    per_bar = one["fpb"] * one["beats_per_bar"]
    overlap = int(round(max(0.0, _as_number(values.get("loop_overlap_beats", 1.0), float)) * one["fpb"])) \
        if one["seamless"] else 0
    return max(1, int((int(init_frames) - overlap) // per_bar))


def read_slots(values, warnings):
    """Active Mod Matrix rows -> [modulation.Slot]."""
    slots = []
    for n in range(1, schema.MOD_SLOTS + 1):
        p = "mod%d_" % n
        if not _as_bool(values.get(p + "active", False)):
            continue
        target = _text(values.get(p + "target", ""))
        if target not in schema.MOD_APIS:
            warnings.append("slot %d: %r is not a modulatable parameter" % (n, target))
            continue
        try:
            slot = modulation.Slot(
                target, _text(values.get(p + "shape", "sine")),
                _as_number(values.get(p + "beats", 1), float),
                _as_number(values.get(p + "depth", 0), float),
                _as_number(values.get(p + "phase", 0), float),
                _as_number(values.get(p + "sharpness", 4), float), index=n)
        except (TypeError, ValueError) as exc:
            warnings.append("slot %d ignored: %s" % (n, exc))
            continue
        if slot.depth:
            slots.append(slot)
    return slots


def _sample_loop(samples, loop_frames, t):
    """One value of a CHOP describing one loop, at render frame t (wraps, linear)."""
    n = len(samples)
    if n == 1:
        return float(samples[0])
    pos = (t % loop_frames) * n / float(loop_frames)
    i = int(math.floor(pos))
    a, b = float(samples[i % n]), float(samples[(i + 1) % n])
    return a + (b - a) * (pos - i)


def live_values(values, chop, loop_timeline_frame, project_rate, links=None):
    """{api: value} the render uses at the loop position ``loop_timeline_frame``.

    For the ``mod_live`` Script CHOP: every MOD parameter that a Mod Matrix slot or a Mod CHOP
    channel moves (raw overrides are Deforum's own schedules and are left out), evaluated the
    way the render evaluates it, so live TouchDesigner visuals can follow the same curves.
    Also ``render_frame``: the render frame at this timeline position.
    """
    warnings = []
    tp = tempo_plan(values)
    render_fps = float(tp["render_fps"]) if tp else 15.0
    fpb = tp["fpb"] if tp else tempo.frames_per_beat(_as_number(values.get("bpm", 120), float), 15)
    t = float(loop_timeline_frame) * render_fps / float(project_rate or 60.0)
    loop_frames = float(tp["loop_frames"]) if tp else None
    slots = read_slots(values, warnings)
    chop_fields = _chop_by_field(chop, warnings)
    chop_mode = _text(values.get("chop_mode", "add")) or "add"
    timing = _text(values.get("chop_timing", chop_link.TIMELINE)) or chop_link.TIMELINE
    links = links or {}
    loop_seconds = _loop_seconds(tp, values, loop_frames or 1)
    out = {"render_frame": t}
    for field in schema.MOD_FIELDS:
        if field.api not in values or _text(values.get(raw_key(field.api), "")):
            continue
        field_slots = [s for s in slots if s.target == field.api and s.depth]
        samples = chop_fields.get(field.api)
        link = links.get(field.api)
        if link is not None and not link.get("samples"):
            link = None
        if not field_slots and not samples and link is None:
            continue
        try:
            base = coerce(field, values[field.api])
        except (TypeError, ValueError):
            base = float(field.default)
        if link is not None:
            one_loop = chop_link.loop_samples(link, timing, loop_seconds, link.get("loop_start_seconds", 0.0))
            base = _sample_loop(one_loop, loop_frames or len(one_loop), t)
        chop_value = _sample_loop(samples, loop_frames or len(samples), t) if samples else None
        out[field.api] = modulation.evaluate(base, field_slots, fpb, t, chop_value, chop_mode)
    return out


def _loop_seconds(tp, values, total):
    """Seconds of one loop on the timeline (render frames / render fps)."""
    if tp:
        return float(tp["loop_frames"]) / float(tp["render_fps"] or 15)
    fps = _as_number(values.get("out_fps", 15), float) or 15.0
    return float(total) / float(fps)


def _link_curve(field, link, override, timing, loop_seconds, loop_frames, total):
    """(base curve over render frames 0..total-1 or None, warning or None) for a CHOP link."""
    source = link.get("source") or "a CHOP"
    if override:
        return None, ("%s: the raw schedule is set, so %s on the base is ignored (clear raw to use it)"
                      % (field.td_name, source))
    if not link.get("samples"):
        return None, "%s: %s gave no samples%s; base value used" % (
            field.td_name, source, " (%s)" % link["note"] if link.get("note") else "")
    one_loop = chop_link.loop_samples(link, timing, loop_seconds, link.get("loop_start_seconds", 0.0))
    note = "%s: %s" % (field.td_name, link["note"]) if link.get("note") else None
    return modulation.resample_loop(one_loop, loop_frames, total), note


def _chop_by_field(chop, warnings):
    """{channel name: samples} -> {api: samples}; names may be api or TD names."""
    lookup = {}
    for field in schema.MOD_FIELDS:
        lookup[field.api.lower()] = field.api
        lookup[field.td_name.lower()] = field.api
    out, ignored = {}, []
    for name, samples in (chop or {}).items():
        api = lookup.get(str(name).lower())
        if api is None:
            ignored.append(str(name))
        elif samples:
            out[api] = samples
    if ignored:
        warnings.append("Mod CHOP channels not named after a parameter, ignored: %s" % ", ".join(sorted(ignored)))
    return out


def build_request(values, prompts=None, models=None, frame_counter=None,
                  default_checkpoint=DEFAULT_CHECKPOINT, prompt_rows=None, chop=None, links=None):
    """Return {"request", "plan", "tempo", "schedules", "warnings"}.

    values         {api_name: value} as read from the COMP (missing keys = not on the COMP);
                   MOD overrides under raw_key(api)
    prompts        {"frame": "prompt"} timeline (prompt.json); used unless a beat sequence applies
    models         {"index": "file.safetensors"} from the available_models table
    frame_counter  callable(container_path) -> int | None, used to cap frame counts
    prompt_rows    [(beat, prompt, xfade)] from the COMP's prompt_seq table
    chop           {channel name: [samples]} describing one loop (the Mod CHOP)
    links          {api: chop_link dict} CHOP channels dropped onto a MOD parameter (base or raw);
                   the channel becomes the parameter's base curve (see chop_link.py)
    """
    models = models or {}
    warnings = []
    settings = {}
    options = {}

    # --- length: tempo or manual, then capped by the videos -------------------------
    tp = tempo_plan(values)
    if tp:
        warnings.extend(tp["warnings"])
    mode = _text(values.get("animation_mode", "2D"))
    use_mask_video = _as_bool(values.get("use_mask_video", False))
    frame_mode = _text(values.get("video_frame_mode", "trim")) or "trim"
    ui_max = tp["max_frames"] if tp else values.get("max_frames", 240)
    init_frames = mask_frames = None
    if frame_counter is not None:
        if mode == "Video Input" or hybrid_active(values):
            init_frames = _count(frame_counter, values.get("video_init_path"), "init video", warnings)
        if use_mask_video:
            mask_frames = _count(frame_counter, values.get("video_mask_path"), "mask video", warnings)
    hybrid = hybrid_active(values)
    plan = plan_frames(mode, ui_max, frame_mode, use_mask_video, init_frames, mask_frames, hybrid)
    total = plan["max_frames"]
    if tp and total < tp["max_frames"]:
        warnings.append("the %s is shorter than the loop (%d < %d frames); the loop will not close"
                        % (plan["limited_by"], total, tp["max_frames"]))

    # --- modulation sources ----------------------------------------------------------
    slots = read_slots(values, warnings)
    fpb = tp["fpb"] if tp else tempo.frames_per_beat(_as_number(values.get("bpm", 120), float), 15)
    loop_frames = tp["loop_frames"] if tp else total
    chop_fields = _chop_by_field(chop, warnings)
    timing = _text(values.get("chop_timing", chop_link.TIMELINE)) or chop_link.TIMELINE
    loop_seconds = _loop_seconds(tp, values, total)
    links = links or {}
    if tp and tp["seamless"]:
        warnings.extend(modulation.loop_warnings(slots, tp["loop_beats"]))
    compiled = {}
    ranges = {}

    for field in schema.FIELDS:
        if field.target is None or field.api.startswith("cn_") or field.api not in values:
            continue
        raw = values[field.api]
        text = _text(raw)

        if field.kind == schema.MOD:
            override = _text(values.get(raw_key(field.api), ""))
            if not override and ":" in text:          # legacy string schedule par
                override = text
            field_slots = [s for s in slots if s.target == field.api]
            samples = chop_fields.get(field.api)
            chop_values = modulation.resample_loop(samples, loop_frames, total) if samples else None
            base_curve = None
            link = links.get(field.api)
            if link is not None:
                base_curve, link_note = _link_curve(field, link, override, timing, loop_seconds,
                                                    loop_frames, total)
                if link_note:
                    warnings.append(link_note)
            try:
                base = float(field.default) if override or text == "" else coerce(field, raw)
            except (TypeError, ValueError):
                warnings.append("%s: could not read %r, used %r" % (field.td_name, raw, field.default))
                base = float(field.default)
            sched, bounds, how = modulation.compile_field(
                base, field_slots, fpb, total, chop_values,
                _text(values.get("chop_mode", "add")), override,
                int(_as_number(values.get("bake_points", 0), float)), base_curve=base_curve)
            settings[field.key] = sched
            compiled[field.api] = (how, sched)
            ranges[field.api] = bounds if bounds else None
            _check_field(field, how, bounds, mode, field_slots, override, warnings)
            continue

        if text == "" and field.kind != schema.TOGGLE:
            continue
        if field.kind == schema.CHECKPOINT:
            settings["enable_checkpoint_scheduling"] = True
            settings["checkpoint_schedule"] = schedules.checkpoint_schedule(
                text, models, default_checkpoint)
            continue
        if field.api == "border" and text == "zeros":   # legacy menu value
            settings["border"], legacy_padding = border_modes(text)
            settings.setdefault("padding_mode", legacy_padding)
            continue
        if field.api == "kernel_schedule":
            asked = int(round(_as_number(text.split("(")[-1].rstrip(")"), float)))
            kernel = max(1, asked)
            if kernel % 2 == 0:
                kernel += 1
            if kernel != asked:
                warnings.append("anti-blur kernel %d sent as %d (OpenCV needs a positive odd size)"
                                % (asked, kernel))
            settings["kernel_schedule"] = "0:(%d)" % kernel
            continue

        try:
            value = coerce(field, raw)
        except (TypeError, ValueError):
            warnings.append("%s: could not read %r, left at Deforum default" % (field.td_name, raw))
            continue
        (options if field.target == "options" else settings)[field.key] = value
    if "border" in settings and "padding_mode" not in settings and "border" in values \
            and "padding_mode" not in values:
        settings["padding_mode"] = border_modes(_text(values["border"]))[1]

    _check_sampling(values, settings, options, ranges, mode, warnings)
    if hybrid:
        # Deforum reads the video's frames from <outdir>/hybridframes; extract them every run.
        settings["hybrid_generate_inputframes"] = True
        if not _text(values.get("video_init_path", "")):
            warnings.append("Hybrid Video is on but Globals > Video Init Path is empty")

    # --- ControlNet: units 1..CN_UI_UNITS from the UI, the rest off ------------------
    # Deforum parses every unit's schedules even when the unit is off, so a unit the
    # UI does not have (or an old UI without it) gets unit 1's defaults with the unit
    # number swapped; only `enabled` is False. Empty strings are meaningful here.
    for unit in range(1, CN_UNITS + 1):
        for field in schema.cn_fields(1):
            api = field.api.replace("cn_1_", "cn_%d_" % unit, 1)
            key = field.key.replace("cn_1_", "cn_%d_" % unit, 1)
            known = unit == 1 or api in values
            if field.api == "cn_1_enabled" and not known:
                settings[key] = False
                continue
            raw = values.get(api, field.default) if known else field.default
            try:
                settings[key] = coerce(field, raw)
            except (TypeError, ValueError):
                settings[key] = coerce(field, field.default)
                warnings.append("%s: could not read %r, used %r" % (field.td_name.replace("Cn1", "Cn%d" % unit),
                                                                  raw, field.default))
        if _as_bool(settings.get("cn_%d_enabled" % unit, False)):
            _check_cn_guide(values, unit, settings, total, frame_counter, warnings)

    # --- prompts ------------------------------------------------------------------------
    # A Prompt Preset (Prompts page) wins over Prompt Source: picking one changes the prompt and
    # nothing else, so it is used whatever the source and whether or not the length is tempo-based.
    sequence = None
    preset_on = _text(values.get("prompt_preset", "none")) not in ("", "none")
    if prompt_rows and (preset_on or _text(values.get("prompt_source", "sequence")) == "sequence"):
        if tp:
            sequence, prompt_warnings = prompt_seq.compile_sequence(
                prompt_rows, tp, _as_number(values.get("prompt_xfade_beats", 1.0), float))
            warnings.extend(prompt_warnings)
        elif preset_on:
            first = [r for r in prompt_rows[1:] if len(r) > 1 and str(r[1]).strip()]
            sequence = {"0": str(first[0][1]).strip()} if first else None
    settings["prompts"] = sequence or dict(prompts or DEFAULT_PROMPTS)

    # --- output: fps / interpolation, and what the TD side relies on -----------------------
    settings.update(skip_video_creation=False, use_mask=use_mask_video,
                    overlay_mask=use_mask_video and _as_bool(values.get("overlay_mask", False)),
                    store_frames_in_ram=True)
    if tp:
        settings["fps"] = tp["render_fps"]
        if tp["strategy"] == "interpolate":
            # Deforum only interpolates when frames are written to disk.
            settings.update(frame_interpolation_engine=tp["engine"],
                            frame_interpolation_x_amount=tp["interp_x"],
                            frame_interpolation_keep_imgs=False,
                            frame_interpolation_slow_mo_enabled=False,
                            store_frames_in_ram=False)
        else:
            settings["frame_interpolation_engine"] = "None"
        _loop_seeds(values, settings, tp, warnings)

    settings["max_frames"] = total
    for key in ("extract_from_frame", "extract_to_frame", "extract_nth_frame"):
        if plan[key] is not None:
            settings[key] = plan[key]

    request = {"deforum_settings": settings}
    if options:
        request["options_overrides"] = options
    return {"request": request, "plan": plan, "tempo": tp, "schedules": compiled,
            "warnings": warnings}


def _check_sampling(values, settings, options, ranges, mode, warnings):
    """Settings that quietly ruin renders with LCM checkpoints (and Video Input)."""
    sampler = _text(settings.get("sampler", ""))
    cfg = ranges.get("cfg_scale_schedule")
    if "lcm" in sampler.lower() and cfg and cfg[1] > 3.0:
        warnings.append("CFG reaches %g with the LCM sampler: LCM checkpoints burn and smear above ~2 "
                        "(use 1.5-2)" % cfg[1])
    keep = ranges.get("strength_schedule")
    steps = settings.get("steps")
    if keep and isinstance(steps, int) and mode != "Interpolation" \
            and not _as_bool(options.get("img2img_fix_steps", False)):
        actual = int(steps * (1.0 - min(0.999, keep[1])))
        if actual < 3:
            warnings.append("A1111 runs int(steps x (1 - Strength)) steps on img2img frames: %d step(s) at "
                            "Strength %g; switch on Globals > Exact Steps" % (actual, keep[1]))
    cadence = _as_number(settings.get("diffusion_cadence", 1), int)
    if mode == "Video Input" and cadence > 1:
        warnings.append("Video Input with Diffusion Cadence %d: only every %s video frame is diffused and the "
                        "frames between are warped from it; use 1 to restyle every frame"
                        % (cadence, {2: "2nd", 3: "3rd"}.get(cadence, "%dth" % cadence)))


def _loop_seeds(values, settings, tp, warnings):
    if not (tp["seamless"] and _as_bool(values.get("loop_seeds", False))):
        return
    behavior = settings.get("seed_behavior", "iter")
    if behavior == "iter":
        # Same seed for frame f and f + loop, so the overlap tail re-diffuses the head's noise.
        settings["seed_behavior"] = "schedule"
        settings["seed_schedule"] = "0:(s + t%%%d)" % tp["loop_frames"]
    elif behavior in ("random", "ladder", "alternate"):
        warnings.append("seed behaviour %r does not repeat per loop; use Iterate or Fixed for seamless loops"
                        % behavior)


def _is_constant_schedule(text):
    body = schedules.as_schedule(text)
    if "," in body or ":" not in body:
        return False
    try:
        float(body.split(":", 1)[1].strip().strip("()"))
        return True
    except ValueError:
        return False


def _check_field(field, how, bounds, mode, slots, override, warnings):
    moving = how in ("expression", "baked", "chop") or (bool(override) and not _is_constant_schedule(override))
    if moving and field.dims and mode in ("2D", "3D") and field.dims != mode:
        warnings.append("%s is %s-only; Deforum ignores it in %s mode" % (field.api, field.dims, mode))
    if bounds and field.safe:
        lo, hi = field.safe
        if (lo is not None and bounds[0] < lo - 1e-9) or (hi is not None and bounds[1] > hi + 1e-9):
            warnings.append("%s swings %.4g..%.4g, outside %s..%s" % (
                field.api, bounds[0], bounds[1], "-inf" if lo is None else lo, "inf" if hi is None else hi))


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


def _check_cn_guide(values, unit, settings, total, frame_counter, warnings):
    """Warn when an enabled unit's guide video is shorter than the render.

    Deforum reads video frame k for render frame k; past the end of the video the
    unit gets no image. TOP feeds are verified when they are recorded, so only
    plain files are checked here.
    """
    if feed.mode_of(values, unit) != feed.FILE or frame_counter is None:
        return
    path = _text(settings.get("cn_%d_vid_path" % unit, ""))
    if not feed.is_video(path):
        return
    try:
        frames = frame_counter(path)
    except Exception as exc:
        warnings.append("ControlNet %d guide %s: frame count failed (%s)" % (unit, path, exc))
        return
    if frames is None:
        warnings.append("ControlNet %d guide %s is not readable from TouchDesigner; length not checked"
                        % (unit, path))
    elif frames < total:
        warnings.append("ControlNet %d guide has %d frames but the render needs %d; the last %d frames "
                        "get no guidance (record a longer feed or use Guide Source: TOP)"
                        % (unit, frames, total, total - frames))


def summary(result):
    s = result["request"]["deforum_settings"]
    plan = result["plan"]
    parts = [s.get("animation_mode", "?"), "%s frames" % s.get("max_frames")]
    tp = result.get("tempo")
    if tp:
        parts.append("%g bpm %d beats @ %d fps" % (tp["bpm"], tp["loop_beats"], tp["render_fps"]))
        if tp["strategy"] == "interpolate":
            parts.append("%s x%d" % (tp["engine"], tp["interp_x"]))
    if plan.get("extract_nth_frame", 1) not in (None, 1):
        parts.append("stride %d" % plan["extract_nth_frame"])
    if plan.get("limited_by") not in (None, "ui"):
        parts.append("capped by %s" % plan["limited_by"])
    parts.append("%sx%s" % (s.get("W"), s.get("H")))
    moving = sorted(api for api, (how, sched) in result.get("schedules", {}).items()
                    if how in ("expression", "baked", "chop") or (how == "raw" and not _is_constant_schedule(sched)))
    if moving:
        parts.append("mod: " + ", ".join(moving))
    active = ["CN%d %s" % (u, s.get("cn_%d_model" % u)) for u in range(1, CN_UNITS + 1)
              if s.get("cn_%d_enabled" % u)]
    parts.append(", ".join(active) if active else "CN off")
    return " | ".join(parts)
