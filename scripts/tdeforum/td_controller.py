"""TouchDesigner glue: Queue -> (ComfyUI preprocess) -> Deforum render -> auto-load.

Entry points (each called from a thin DAT in scripts/):

    queue(root)             Queue button            deforum_payload_exec.py
    tick(root)              timer1 cycle pulse      chopexec_poll.py
    on_response(root, ...)  all three webclients    webclient2_callbacks.py
    bake(root) / preview    bake button             bake_exec.py  (schedule preview, no POST)
    load_latest(root)       LoadVideo button        loadvideo_exec.py
    export_payload(root)    dry run, no POST        export_deforum_payload.py
    preprocess_only(root)   ComfyUI only            comfy_preprocessor_payload_exec.py
    capture_tick(root)      every frame             feed_capture_exec.py  (records TOP guide feeds)
    cancel / status / doctor                        textport helpers

``root`` is the COMP holding the network (/project1). Pipeline state lives in
root.storage, so reloading this module (or saving the .toe) never loses an
in-flight job. Nothing here imports TouchDesigner modules at import time, so
the file also imports cleanly in unit tests.
"""

import glob
import json
import os
import re
import sys
import time
import traceback

from . import comfy
from . import config
from . import feed
from . import payload
from . import presets
from . import schema
from . import sweep
from . import tempo

STATE_KEY = "tdeforum_pipeline"
CACHE_KEY = "tdeforum_preproc_cache"
JSON_HEADERS = {"Content-Type": "application/json"}

IDLE = "idle"
COMFY_SUBMITTED = "comfy_submitted"
COMFY_RUNNING = "comfy_running"
DEFORUM_SUBMITTED = "deforum_submitted"
DEFORUM_RUNNING = "deforum_running"
WAITING_FILE = "waiting_for_file"
CAPTURING = "capturing"            # stepping the timeline and recording TOP guide feeds
WAITING_FEED = "waiting_for_feed"  # recorded; waiting for the movie files to be finalised
BUSY = (COMFY_SUBMITTED, COMFY_RUNNING, DEFORUM_SUBMITTED, DEFORUM_RUNNING, WAITING_FILE,
        CAPTURING, WAITING_FEED)
LOST_CONTACT_S = 120.0
FEED_FINALIZE_TIMEOUT_S = 60.0
PRESET_KEY = "tdeforum_preset"   # root storage: {applied: preset id, backup: {TD par: value}}
CAPTURE_STALL_S = 4.0        # no Frame End callback this long -> drive the capture with run() instead

# Operators this controller talks to, relative to root.
NAMES = {
    "ui": "deforum",              # the Deforum Base COMP (build_master_ui.py)
    "legacy_ui": "Deforum_UI",    # read only when the COMP has not been built yet
    "deforum": "webclient_deforum",
    "progress": "webclient_progress",
    "comfy": "webclient_comfyui",
    "prompts": "deforum_prompts",
    "models": "available_models",
    "movie": "moviefilein1",
    "folder": "folder_monitor",
    "feed_exec": "feed_capture_exec",   # Execute DAT, Frame End -> capture_tick()
}
# Inside the Deforum COMP
INNER = {
    "prompt_seq": "prompt_seq",       # table: beat | prompt | xfade
    "mod_in": "in_mod",               # In CHOP = COMP input 1 (the Mod CHOP)
    "preview": "schedule_preview",    # table written by preview()
    "head": "loop_head",              # loop player: Movie File In at the playhead
    "tail": "loop_tail",              # loop player: Movie File In one loop later
    "sweep_depth": "sweep_depth",     # Sweep Depth: Movie File In playing the depth video
    "sweep_mask": "sweep_mask",       # Sweep Depth: Script TOP that band-masks it
}
FEED_SELECT = "feed%d_sel"            # Select TOP per ControlNet unit (set to the source TOP)
FEED_OUT = "feed%d_out"               # Movie File Out TOP per unit (records the guide movie)
SWEEP_DEPTH, SWEEP_MASK = "sweep_depth", "sweep_mask"   # Movie File In + Script TOP inside the COMP

RENDER_NAME = re.compile(r"^(\d{14})\.mp4$")
INTERP_FALLBACK_S = 30.0


def log(message):
    print("[TDeforum] " + message)


# --------------------------------------------------------------------------- state

def _op(root, key):
    found = root.op(NAMES[key])
    if found is None and key == "ui":
        found = root.op(NAMES["legacy_ui"])
    return found


def _inner(ui, key):
    return ui.op(INNER[key]) if ui is not None and hasattr(ui, "op") else None


def _set_par(op_, name, value):
    par = getattr(op_.par, name, None) if op_ is not None else None
    if par is not None:
        try:
            par.val = value
        except Exception:
            pass


def _state(root):
    stored = root.fetch(STATE_KEY, None, search=False)
    return dict(stored) if isinstance(stored, dict) else {"state": IDLE}


def _save(root, st):
    root.store(STATE_KEY, st)


def _set_status(root, text):
    _set_par(_op(root, "ui"), "Pipelinestatus", text)


def _finish(root, st, message, error=False):
    now = time.time()
    _save(root, {"state": IDLE, "updated": now,
                 "last_result": ("error: " if error else "") + message,
                 "last_job_id": st.get("job_id")})
    _set_status(root, ("error: " if error else "idle: ") + message)
    log(("ERROR " if error else "") + message)


def _fail(root, st, message):
    _finish(root, st, message, error=True)


def _is_constant(par):
    return getattr(par.mode, "name", str(par.mode)).upper().endswith("CONSTANT")


def _constant_mode(par):
    try:
        import td  # TouchDesigner's own module
        return td.ParMode.CONSTANT
    except Exception:
        return type(par.mode).CONSTANT


def _set_constant(par, value):
    """Set a parameter value, switching it to constant mode if needed."""
    if not _is_constant(par):
        par.mode = _constant_mode(par)
    par.val = value


# --------------------------------------------------------------------------- reading TD

def _coerce_par(field, value):
    if field.kind == schema.INT:
        return int(round(float(value)))
    if field.kind == schema.FLOAT:
        return float(value)
    if field.kind == schema.TOGGLE:
        return 1 if value else 0
    return value


def _apply_preset_safely(root):
    try:
        apply_preset(root)
    except Exception as exc:
        traceback.print_exc()
        log("preset could not be applied: %s" % exc)


def apply_preset(root):
    """Lay the selected Example Preset over the deforum COMP (see presets.py). True if it changed anything.

    Does nothing while the selection equals what was last applied, so your tweaks after applying
    stay. Picking another preset or None first puts back the values the last preset replaced.
    Only constant parameters are touched; driven ones (expression / bind / export) keep their driver.
    """
    ui = _op(root, "ui")
    menu = getattr(ui.par, "Preset", None) if ui is not None else None
    if menu is None:
        return False
    selected = str(menu.eval() or presets.NONE).strip() or presets.NONE
    stored = root.fetch(PRESET_KEY, None, search=False)
    stored = dict(stored) if isinstance(stored, dict) else {}
    if selected == stored.get("applied", presets.NONE):
        return False

    restored = 0
    for name, value in (stored.get("backup") or {}).items():
        par = getattr(ui.par, name, None)
        if par is not None and _is_constant(par):
            par.val = value
            restored += 1

    preset, backup, changed, kept = presets.get(selected), {}, 0, []
    if preset is not None:
        defaults = dict((f.api, f.default) for f in schema.FIELDS)
        for api, value in presets.resolve(preset, defaults).items():
            field = schema.BY_API.get(api)
            if field is None:
                log("preset %s: unknown parameter %r skipped" % (preset.id, api))
                continue
            targets = [(field.td_name, _coerce_par(field, value))]
            if field.kind == schema.MOD:
                targets.append((field.raw_td_name, ""))          # a raw schedule would beat the base
            for name, new in targets:
                par = getattr(ui.par, name, None)
                if par is None:
                    continue
                if not _is_constant(par):
                    kept.append(name)
                    continue
                if field.menu and name == field.td_name and new not in field.menu:
                    log("preset %s: %r is not a choice for %s, skipped" % (preset.id, new, name))
                    continue
                if par.val != new:
                    backup[name] = par.val
                    par.val = new
                    changed += 1
    root.store(PRESET_KEY, {"applied": selected if preset else presets.NONE, "backup": backup})
    if preset is None:
        text = "None (restored %d parameters)" % restored
    else:
        text = "%s: %d parameters set%s" % (preset.label, changed,
                                             ", %d driven kept" % len(kept) if kept else "")
    _set_par(ui, "Presetinfo", text)
    log("preset %s" % text)
    if preset is not None:
        log("  " + preset.notes)
    if kept:
        log("  driven (expression / bind / export) and left alone: %s" % ", ".join(sorted(kept)))
    return True


def read_ui(ui):
    values = {}
    for field in schema.FIELDS:
        par = getattr(ui.par, field.td_name, None)
        if par is not None:
            values[field.api] = par.eval()
        if field.kind == schema.MOD:
            raw = getattr(ui.par, field.raw_td_name, None)
            if raw is not None:
                values[payload.raw_key(field.api)] = raw.eval()
    return values


def read_prompt_rows(ui):
    """prompt_seq table -> [[beat, prompt, xfade], ...] (None when the COMP has no table)."""
    table = _inner(ui, "prompt_seq")
    if table is None:
        return None
    rows = []
    for r in range(table.numRows):
        rows.append([str(table[r, c].val) for c in range(table.numCols)])
    return rows


def read_mod_chop(ui, values):
    """Mod CHOP channels -> {name: [samples]} (None when there is no CHOP or no channels)."""
    if ui is None:
        return None
    path = str(values.get("chop_path", "") or "").strip()
    chop = ui.op(path) if path else _inner(ui, "mod_in")
    if path and chop is None:
        log("Mod CHOP %s not found" % path)
    if chop is None or not getattr(chop, "numChans", 0):
        return None
    return dict((chan.name, [float(v) for v in chan.vals]) for chan in chop.chans())


def read_models(root):
    table = _op(root, "models")
    models = {}
    if table is None or table.numCols < 2:
        return models
    for row in range(table.numRows):
        key, name = table[row, 0].val.strip(), table[row, 1].val.strip()
        if key and name:
            models[key] = name
    return models


def read_prompts(root, cfg):
    try:
        with open(cfg["prompt_file"], "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data:
            return dict((str(k), str(v)) for k, v in data.items())
    except Exception as exc:
        log("prompt file %s unreadable (%s); using the deforum_prompts DAT" % (cfg["prompt_file"], exc))
    dat = _op(root, "prompts")
    try:
        data = json.loads(dat.text)
        if isinstance(data, dict) and data:
            return dict((str(k), str(v)) for k, v in data.items())
    except Exception as exc:
        log("deforum_prompts DAT is not valid JSON (%s); using a fallback prompt" % exc)
    return dict(payload.DEFAULT_PROMPTS)


def _frame_counter(cfg):
    def count(container_path):
        share_path = config.to_share(cfg, container_path)
        if not share_path or not os.path.isfile(share_path):
            return None
        import cv2  # bundled with TouchDesigner's Python
        capture = cv2.VideoCapture(share_path)
        try:
            frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            capture.release()
        return frames if frames > 0 else None
    return count


def build(root, cfg):
    ui = _op(root, "ui")
    if ui is None:
        raise RuntimeError("no 'deforum' COMP in %s; run builder_master_ui" % root.path)
    values = read_ui(ui)
    result = payload.build_request(values, read_prompts(root, cfg), read_models(root),
                                   _frame_counter(cfg), cfg.get("default_checkpoint",
                                                                payload.DEFAULT_CHECKPOINT),
                                   prompt_rows=read_prompt_rows(ui),
                                   chop=read_mod_chop(ui, values))
    if result.get("tempo"):
        _set_par(ui, "Tempoinfo", tempo.describe(result["tempo"]))
    return values, result


def _expectation(result):
    """What the finished render will look like on disk / how to loop it (kept in state)."""
    tp = result.get("tempo")
    if not tp:
        return None
    return {"engine": tp["engine"], "x": tp["interp_x"], "out_loop": tp["out_loop_frames"],
            "overlap_out": tp["overlap_frames"] * tp["interp_x"]}


def _write_runtime_json(cfg, name, data):
    try:
        os.makedirs(cfg["runtime_dir"], exist_ok=True)
        path = cfg["runtime_dir"] + "/" + name
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4)
        os.replace(path + ".tmp", path)
        return path
    except Exception as exc:
        log("could not write %s: %s" % (name, exc))
        return None


# --------------------------------------------------------------------------- actions

def queue(root):
    """Queue button: preprocess (optional) then render."""
    cfg = config.load()
    resync(root, cfg)
    _apply_preset_safely(root)
    st = _state(root)
    if st.get("state") in BUSY and time.time() - st.get("updated", 0) < LOST_CONTACT_S:
        log("busy (%s). Wait, or op('deforum_payload_exec').module.cancel()" % st["state"])
        return
    if st.get("state") == CAPTURING:
        _abort_capture(root, st)          # stale capture: put the timeline back first
    try:
        values, result = build(root, cfg)
        for warning in result["warnings"]:
            log("warning: " + warning)
        if _start_sweep_depth(root, cfg, values, result, st):
            return                        # resumes in _on_comfy() once the depth video exists
        if sweep.enabled(values):
            values, result = build(root, cfg)   # a cache hit just stored the depth video path
        _feed_and_render(root, cfg, st, values, result)
    except Exception as exc:
        traceback.print_exc()
        _fail(root, st, "queue failed: %s" % exc)


def _feed_and_render(root, cfg, st, values, result):
    """TOP guide feeds (recorded first), then the ComfyUI preprocess of unit 1, then Deforum."""
    if feed.requests(values):
        if _start_feed(root, cfg, values, result, st):
            return                        # resumes in _after_feed() once the movies are ready
        values, result = build(root, cfg)   # stills changed the Vid Path pars
    _render_stage(root, cfg, st, values, result)


def _start_sweep_depth(root, cfg, values, result, st):
    """Sweep Depth needs a depth video of the init video.

    Normally ComfyUI makes it from Video Init Path (cached). A Pre-made Depth Video path skips
    ComfyUI. "Queue only makes the depth video" stops after this stage.

    True when the pipeline should stop here (a ComfyUI job was submitted and resumes in
    _on_comfy(), or the depth video was all that was asked for)."""
    wants = [w for w in feed.requests(values) if w.mode == feed.SWEEP]
    prepare = sweep.enabled(values) and sweep.prepare_only(values)
    if not wants and not prepare:
        return False
    problem = sweep.check(values)
    if problem:
        raise RuntimeError(problem)
    premade = str(values.get("sweep_depth_video", "") or "").strip()
    if premade:
        _store_preprocessed(root, premade, "sweep")
        log("Sweep Depth uses the pre-made depth video %s" % premade)
    elif _start_preprocess(root, cfg, values, result, st, then_render=False, purpose="sweep"):
        return True
    if prepare:
        _finish(root, st, "depth video ready: %s" % (premade or _op(root, "ui").par.Sweepdepthpath.eval()))
        return True
    return False


def _render_stage(root, cfg, st, values, result):
    """ComfyUI preprocess (optional), then the Deforum batch."""
    if _wants_preprocess(values):
        if _start_preprocess(root, cfg, values, result, st, then_render=True):
            return
        values, result = build(root, cfg)  # cache hit changed Cn1vidpath
    _submit_deforum(root, cfg, result, st)


def preprocess_only(root):
    cfg = config.load()
    st = _state(root)
    values, result = build(root, cfg)
    if not _start_preprocess(root, cfg, values, result, st, then_render=False):
        log("nothing to preprocess (cache hit or template missing)")


def export_payload(root):
    """Dry run: write runtime/last_deforum_payload.json without sending anything."""
    cfg = config.load()
    _values, result = build(root, cfg)
    for warning in result["warnings"]:
        log("warning: " + warning)
    path = _write_runtime_json(cfg, "last_deforum_payload.json", result["request"])
    log("payload written to %s (%s)" % (path, payload.summary(result)))
    return result


def cancel(root):
    cfg = config.load()
    st = _state(root)
    if st.get("state") == DEFORUM_RUNNING and st.get("job_id"):
        _op(root, "progress").request(
            config.deforum_url(cfg, "/deforum_api/jobs/%s" % st["job_id"]), "DELETE")
    elif st.get("state") in (COMFY_SUBMITTED, COMFY_RUNNING):
        _op(root, "comfy").request(config.comfy_url(cfg, "/interrupt"), "POST",
                                   header=JSON_HEADERS, data="{}")
    elif st.get("state") in (CAPTURING, WAITING_FEED):
        _abort_capture(root, st)
    _finish(root, st, "cancelled (was %s)" % st.get("state", IDLE))


def status(root):
    st = _state(root)
    log(json.dumps(st, indent=2, sort_keys=True))
    return st


def _wants_preprocess(values):
    if not payload._as_bool(values.get("comfy_preproc_enable", False)):
        return False
    if not payload._as_bool(values.get("cn_1_enabled", False)):
        log("ComfyUI preprocess is on but ControlNet unit 1 is off; skipping preprocess")
        return False
    if feed.mode_of(values, 1) != feed.FILE:
        log("ComfyUI preprocess reads video_init_path, not a TOP feed; skipping it for unit 1 "
            "(use ControlNet's own module, e.g. depth_midas, on the feed instead)")
        return False
    return True


def _start_preprocess(root, cfg, values, result, st, then_render, purpose="cn1"):
    """Submit the ComfyUI job. Returns False if nothing was submitted."""
    try:
        with open(cfg["comfy_template"], "r", encoding="utf-8") as fh:
            template = json.load(fh)
    except Exception as exc:
        log("ComfyUI template unreadable (%s); skipping preprocess" % exc)
        return False

    force = payload._as_bool(values.get("force_preprocess", False))
    job_values = values
    if purpose == "sweep":        # same workflow, a depth preprocessor instead of unit 1's
        job_values = dict(values, comfy_preprocessor=sweep.from_values(values).model)
    job = comfy.build_prompt(template, cfg, job_values, result["plan"], force=force,
                             stamp=time.strftime("%Y%m%d%H%M%S"))
    cache = dict(root.fetch(CACHE_KEY, {}, search=False) or {})
    if not force and job["cache_key"] in cache:
        _store_preprocessed(root, cache[job["cache_key"]], purpose)
        log("preprocess cache hit: %s" % cache[job["cache_key"]])
        return False

    _op(root, "comfy").request(config.comfy_url(cfg, "/prompt"), "POST",
                               header=JSON_HEADERS, data=json.dumps(job["body"]))
    now = time.time()
    st = {"state": COMFY_SUBMITTED, "submitted": now, "updated": now,
          "cache_key": job["cache_key"], "then_render": then_render, "purpose": purpose}
    _save(root, st)
    _set_status(root, "preprocessing: submitted")
    log("ComfyUI %s submitted: %s (%s frames)" % ("depth preprocess" if purpose == "sweep" else "preprocess",
                                                  job["cache_key"], result["plan"]["source_frames"]))
    return True


def _store_preprocessed(root, container_path, purpose):
    if purpose == "sweep":
        _set_par(_op(root, "ui"), "Sweepdepthpath", container_path)
    else:
        _set_cn_video(root, container_path)


def _submit_deforum(root, cfg, result, st):
    _write_runtime_json(cfg, "last_deforum_payload.json", result["request"])
    _op(root, "deforum").request(config.deforum_url(cfg, "/deforum_api/batches"), "POST",
                                 header=JSON_HEADERS, data=json.dumps(result["request"]))
    now = time.time()
    _save(root, {"state": DEFORUM_SUBMITTED, "submitted": now, "updated": now,
                 "expect": _expectation(result)})
    _set_status(root, "render: submitted")
    log("render submitted: " + payload.summary(result))


def _set_cn_video(root, container_path, unit=1):
    par = getattr(_op(root, "ui").par, "Cn%dvidpath" % unit, None)
    if par is not None:
        _set_constant(par, container_path)


# --------------------------------------------------------------------------- ControlNet feeds
#
# Guide movies recorded from TOPs (feed.py explains what Deforum needs). The timeline
# keeps PLAYING (a paused TouchDesigner cooks nothing, so no Frame End would ever fire);
# every Frame End the recorder looks at the frame shown and only records the planned one:
#
#   settle   a few frames so the Select / Movie File Out TOPs cook; then arm record + pause
#            and jump to the first planned frame
#   record   every Frame End: if the timeline shows the planned frame pulse Add Frame and
#            line up the next one (a jump if it is not simply +1); otherwise jump and retry
#   (WAITING_FEED) the movie files are finalised, counted and handed to the CN units
#
# Sweep Depth units are recorded the same way, from the Script TOP sweep_mask; before each
# frame cooks, _sweep_apply() sets the depth video index and the band for that render frame.
#
# Built-in TouchDesigner API used: op('/').time.{frame, play, rate, start},
# project.realTime, Select TOP .top, Movie File Out TOP .file/.record/.pause/.addframe,
# TOP.save(). Anything missing raises a message naming it. Pipeline > "Feed: recording
# method" = continuous skips pause/Add Frame and records every cooked frame instead.

def resync(root, cfg=None):
    """Reload every DAT in `root` whose File points into the scripts folder (Load File pulse).

    TouchDesigner only notices a changed file on its own sometimes; this makes Queue, bake and
    doctor pick up edits made in VS Code. Uses the DAT's Load File pulse when it has one."""
    cfg = cfg or config.load()
    base = str(cfg["scripts_dir"]).replace("\\", "/").lower().rstrip("/") + "/"
    find = getattr(root, "findChildren", None)
    if find is None:
        return 0
    count = 0
    for dat in find(depth=1):
        par = getattr(dat.par, "file", None)
        pulse = getattr(dat.par, "loadonstartpulse", None)
        if par is None or pulse is None:
            continue
        try:
            path = str(par.eval()).replace("\\", "/").lower()
            if path.startswith(base):
                pulse.pulse()
                count += 1
        except Exception as exc:
            log("resync %s failed: %s" % (getattr(dat, "name", "?"), exc))
    return count


def _timeline(root):
    top = root.op("/")
    timeline = getattr(top, "time", None)
    if timeline is None:
        raise RuntimeError("cannot reach the project timeline (op('/').time)")
    return timeline


def _realtime(value=None):
    """Return project.realTime; set it first when `value` is given. None outside TouchDesigner."""
    try:
        import td
        project = td.project
        previous = getattr(project, "realTime", None)
    except Exception:
        return None
    if value is not None:
        try:
            project.realTime = value
        except Exception:
            pass
    return previous


def _resolve_top(root, path, unit):
    if not path:
        raise RuntimeError("ControlNet %d: Source TOP is empty (e.g. /project1/final_out)" % unit)
    found = root.op(path)
    if found is None:
        raise RuntimeError("ControlNet %d: Source TOP %r not found" % (unit, path))
    return found


def _par(op_, name):
    par = getattr(op_.par, name, None) if op_ is not None else None
    if par is None:
        raise RuntimeError("%s has no parameter %r; set the feed up by hand or tell the maintainer which "
                           "TouchDesigner build this is" % (getattr(op_, "name", op_), name))
    return par


def _feed_plan(root, values, result, wrap=True):
    """(feed.frame_plan(...), timeline rate) for the render in `result`."""
    timeline = _timeline(root)
    rate = float(getattr(timeline, "rate", 60.0) or 60.0)
    start = int(float(values.get("feed_loop_start", 0) or 0)) or int(getattr(timeline, "start", 1) or 1)
    return feed.frame_plan(result.get("tempo"), result["plan"]["max_frames"], rate, start, wrap), rate


def _feed_ops(ui, unit):
    sel, out = ui.op(FEED_SELECT % unit), ui.op(FEED_OUT % unit)
    if sel is None or out is None:
        raise RuntimeError("the deforum COMP has no %s / %s; run builder_master_ui"
                           % (FEED_SELECT % unit, FEED_OUT % unit))
    return sel, out


def _set_feed_info(root, unit, text):
    _set_par(_op(root, "ui"), "Feed%dinfo" % unit, text)


def _start_feed(root, cfg, values, result, st):
    """Capture every TOP-sourced guide. True when a recording is now running."""
    wants = feed.requests(values)
    for want in wants:
        if want.mode == feed.TOP_STILL:
            _capture_still(root, cfg, want)
    loops = [w for w in wants if w.mode in (feed.TOP_LOOP, feed.SWEEP)]
    return bool(loops) and _begin_loop_capture(root, cfg, values, result, loops)


def _feed_target(cfg, want):
    share = feed.share_path(cfg, want.unit, want.mode)
    if share is None:
        raise RuntimeError("cn_feed_dir %s is not under config path_map; TouchDesigner cannot write there"
                           % cfg["cn_feed_dir"])
    os.makedirs(os.path.dirname(share), exist_ok=True)
    return share, feed.container_path(cfg, want.unit, want.mode)


def _capture_still(root, cfg, want):
    top = _resolve_top(root, want.top, want.unit)
    share, container = _feed_target(cfg, want)
    top.save(share)
    if not os.path.isfile(share):
        raise RuntimeError("ControlNet %d: %s.save() wrote nothing to %s" % (want.unit, want.top, share))
    _set_cn_video(root, container, want.unit)
    _set_feed_info(root, want.unit, "still %s" % time.strftime("%H:%M:%S"))
    log("ControlNet %d guide: still from %s -> %s" % (want.unit, want.top, container))


def _sweep_setup(root, cfg, values, result, ui):
    """Point the depth player at the ComfyUI depth video; return the per-frame plan to store."""
    problem = sweep.check(values)
    if problem:
        raise RuntimeError(problem)
    mfi, script = _inner(ui, SWEEP_DEPTH), _inner(ui, SWEEP_MASK)
    if mfi is None or script is None:
        raise RuntimeError("the deforum COMP has no %s / %s; run builder_master_ui" % (SWEEP_DEPTH, SWEEP_MASK))
    depth = str(values.get("sweep_depth_path", "") or "").strip()
    share = config.to_share(cfg, depth) if depth else None
    if not share or not os.path.isfile(share):
        raise RuntimeError("the depth video %r is not on the share (ComfyUI preprocess did not run?)" % depth)
    _set_constant(_par(mfi, "file"), share)
    reload_ = getattr(mfi.par, "reloadpulse", None)
    if reload_ is not None:
        reload_.pulse()
    p = result["plan"]
    plan = sweep.plan(values, p["max_frames"], p.get("extract_from_frame") or 0,
                      p.get("extract_nth_frame") or 1, _video_frames(share))
    for warning in plan["warnings"]:
        log("warning: " + warning)
    log("sweep: " + sweep.describe(plan))
    _set_par(ui, "Sweepinfo", sweep.describe(plan))
    return {"indices": plan["indices"], "bands": [list(b) for b in plan["bands"]]}


def _sweep_apply(root, st, j):
    """Show render frame j's depth frame and band (called before the frame that cooks it)."""
    state = st.get("sweep")
    if not state:
        return
    ui = _op(root, "ui")
    mfi, script = _inner(ui, SWEEP_DEPTH), _inner(ui, SWEEP_MASK)
    _set_constant(_par(mfi, "index"), int(state["indices"][j]))
    lo, hi, soft, fill = state["bands"][j]
    script.store(sweep.SCRIPT_BAND_KEY, (lo, hi, soft, fill))
    cook = getattr(script, "cook", None)
    if cook is not None:
        try:
            cook(force=True)
        except Exception:
            pass


def _begin_loop_capture(root, cfg, values, result, loops):
    ui = _op(root, "ui")
    exec_dat = root.op(NAMES["feed_exec"])
    if exec_dat is None:
        raise RuntimeError("no %s DAT: run setup_network" % NAMES["feed_exec"])
    for name in ("active", "frameend"):
        par = getattr(exec_dat.par, name, None)
        if par is not None and not par.eval():
            raise RuntimeError("%s.%s is off, so the capture would never advance" % (exec_dat.name, name))

    timeline = _timeline(root)
    sweeping = any(w.mode == feed.SWEEP for w in loops)
    plan, rate = _feed_plan(root, values, result, wrap=not sweeping)   # a sweep never wraps
    for warning in plan["warnings"]:
        log("warning: " + warning)
    sweep_state = _sweep_setup(root, cfg, values, result, ui) if sweeping else None

    method = feed.method_of(values)
    units = []
    for want in loops:
        sel, out = _feed_ops(ui, want.unit)
        if want.mode == feed.SWEEP:
            want = feed.Request(want.unit, want.mode, _inner(ui, "sweep_mask").path)
        else:
            _resolve_top(root, want.top, want.unit)
        share, container = _feed_target(cfg, want)
        if os.path.isfile(share):
            os.remove(share)                  # so "file exists" below means "this recording"
        _set_constant(_par(sel, "top"), want.top)
        _set_constant(_par(out, "file"), share)
        for name, value in (("type", "movie"), ("pause", 0), ("record", 0)):
            par = getattr(out.par, name, None)
            if par is not None:
                _set_constant(par, value)
        _par(out, "record")
        if method == feed.ADD_FRAME:
            _par(out, "addframe")
            _par(out, "pause")
        units.append({"unit": want.unit, "top": want.top, "share": share, "container": container,
                      "mode": want.mode})

    now = time.time()
    st = {"state": CAPTURING, "phase": "settle", "method": method, "units": units, "frames": plan["frames"],
          "sweep": sweep_state, "as_mask": payload._as_bool(values.get("sweep_as_mask", False)),
          "j": 0, "since_set": 0, "submitted": now, "updated": now,
          "restore": {"frame": int(timeline.frame), "play": bool(timeline.play), "realtime": _realtime(False)}}
    # The timeline wraps at its end (a 120 frame project would jump back to 1 at frame 121),
    # so lengthen it for the recording and give it back afterwards.
    need = max(plan["frames"])
    for name in ("end", "rangeEnd"):
        have = getattr(timeline, name, None)
        if have is not None and have < need:
            st["restore"][name] = have
            setattr(timeline, name, need)
            log("timeline %s %s -> %d for the recording (restored afterwards)" % (name, have, need))
    _save(root, st)
    # The timeline keeps PLAYING: a paused TouchDesigner cooks no frames, so no Frame End
    # callback (or timer) would ever arrive. realTime is off, so every cooked frame is one
    # timeline step, and the stepper only records when the timeline shows the planned frame.
    timeline.frame = plan["frames"][0]
    timeline.play = True
    _set_status(root, "feed: recording 0/%d" % len(plan["frames"]))
    log("recording ControlNet feed%s %s from %s: %s (timeline %g fps, method %s)" % (
        "s" if len(units) > 1 else "", ",".join(str(u["unit"]) for u in units),
        ", ".join(sorted(set(u["top"] for u in units))), feed.describe(plan), rate, method))
    return True


def capture_tick(root, source="frameend"):
    """Frame End callback (feed_capture_exec). Does nothing unless a capture is running.

    A capture is driven by one source at a time: "frameend", or "run" (a td.run() chain) when
    no Frame End callback arrived for CAPTURE_STALL_S seconds (see tick())."""
    st = _state(root)
    if st.get("state") != CAPTURING:
        return
    if source != st.get("driver", "frameend"):
        return
    try:
        if not st.get("seen_cb"):
            st["seen_cb"] = True
            tl = _timeline(root)
            log("capture: first %s callback (timeline frame %s, playing %s)"
                % (source, tl.frame, tl.play))
        _capture_step(root, st)
    except Exception as exc:
        traceback.print_exc()
        _abort_capture(root, st)
        _fail(root, st, "feed capture failed: %s" % exc)
        return
    if source == "run" and _state(root).get("state") == CAPTURING:
        _schedule_run(root)


def _schedule_run(root):
    """Call capture_tick(root, 'run') again two frames from now (a whole frame cooks in between)."""
    script = ("import sys; sys.path.insert(0, %r); from tdeforum import td_controller; "
              "td_controller.capture_tick(op(%r), 'run')" % (config.load()["scripts_dir"], root.path))
    import td
    td.run(script, delayFrames=2)


def _stall_diagnostic(root, st):
    tl = _timeline(root)
    dat = root.op(NAMES["feed_exec"])
    pars = ", ".join("%s=%s" % (n, getattr(dat.par, n).eval()) for n in ("active", "frameend")
                     if dat is not None and getattr(dat.par, n, None) is not None)
    return ("no Frame End callback for %.0fs while recording (phase %s, frame %d/%d, timeline at %s, "
            "playing %s, %s: %s)" % (time.time() - st.get("updated", time.time()), st.get("phase"),
                                      st.get("j", 0), len(st.get("frames", [])), tl.frame, tl.play,
                                      NAMES["feed_exec"], pars or "DAT not found"))


def _capture_step(root, st):
    """One Frame End while recording (the timeline is playing, one step per callback).

    settle   a few frames so the Select/Movie File Out TOPs cook; then arm record (+pause) and
             jump the timeline to the first planned frame
    record   when the timeline shows frames[j]: pulse Add Frame (or, for the continuous
             method, that cooked frame is recorded by itself), then, unless the timeline is
             going to reach frames[j+1] by itself, jump there. Setting the frame inside a
             callback may land on the target or one past it; `off` learns which."""
    ui = _op(root, "ui")
    timeline = _timeline(root)
    frames = st["frames"]
    outs = [_feed_ops(ui, u["unit"])[1] for u in st["units"]]
    st["updated"] = time.time()
    st["since_set"] = st.get("since_set", 0) + 1
    add_frame = st.get("method", feed.ADD_FRAME) == feed.ADD_FRAME

    if st["phase"] == "settle":
        if st["since_set"] >= 3:
            for out in outs:
                if add_frame:
                    _set_constant(out.par.pause, 1)
                _set_constant(out.par.record, 1)
            _sweep_apply(root, st, 0)
            timeline.frame = frames[0]
            st.update(phase="record", off=0, just_set=True, misses=0)
        _save(root, st)
        return

    j, f = st["j"], int(timeline.frame)
    if not timeline.play:
        timeline.play = True
    if f != frames[j]:
        if not add_frame:
            raise RuntimeError("recording frame %d: the timeline is at %s, expected %d; the continuous "
                               "method cannot skip frames, use Feed Method = Add Frame" % (j, f, frames[j]))
        st["misses"] = st.get("misses", 0) + 1
        if st["misses"] > 30:
            raise RuntimeError("recording frame %d: the timeline shows %s, expected %d, after %d tries "
                               "(playing %s); is something else driving the timeline?"
                               % (j, f, frames[j], st["misses"] - 1, timeline.play))
        if st.get("just_set") and f == frames[j] + 1 and st.get("off", 0) == 0:
            st["off"] = 1
            log("capture: setting the frame lands one past the target, compensating")
        timeline.frame = frames[j] - st.get("off", 0)
        st["just_set"] = True
        _save(root, st)
        return

    if add_frame:
        for out in outs:
            out.par.addframe.pulse()
    j += 1
    st.update(j=j, misses=0, just_set=False)
    if j <= 3 or j == len(frames):
        log("feed frame %d/%d recorded at timeline frame %d" % (j, len(frames), f))
    if j < len(frames):
        _sweep_apply(root, st, j)         # takes effect on the frame that cooks next
        if frames[j] != f + 1:
            timeline.frame = frames[j] - st.get("off", 0)
            st["just_set"] = True
        if j % 30 == 0:
            _set_status(root, "feed: recording %d/%d" % (j, len(frames)))
        _save(root, st)
        return

    for out in outs:
        _set_constant(out.par.record, 0)
    _restore_timeline(root, st.get("restore"))
    now = time.time()
    st.update(state=WAITING_FEED, waiting_since=now, updated=now, sizes={}, restore=None)
    _save(root, st)
    _set_status(root, "feed: finalising")
    log("feed recorded (%d frames); waiting for the movie files" % len(frames))


def _restore_timeline(root, restore):
    if not restore:
        return
    try:
        timeline = _timeline(root)
        for name in ("end", "rangeEnd"):
            if name in restore:
                setattr(timeline, name, restore[name])
        timeline.frame = restore["frame"]
        timeline.play = restore["play"]
    except Exception as exc:
        log("could not restore the timeline: %s" % exc)
    if restore.get("realtime") is not None:
        _realtime(restore["realtime"])


def _abort_capture(root, st):
    """Stop recording and give the timeline back. Safe to call twice."""
    ui = _op(root, "ui")
    for u in st.get("units", []):
        try:
            out = ui.op(FEED_OUT % u["unit"])
            if out is not None and getattr(out.par, "record", None) is not None:
                _set_constant(out.par.record, 0)
        except Exception as exc:
            log("could not stop feed %s: %s" % (u.get("unit"), exc))
    _restore_timeline(root, st.get("restore"))
    st["restore"] = None
    _save(root, st)


def _poll_feed(root, cfg, st):
    """Wait for the recorded movies to settle, check their length, then render."""
    now = time.time()
    sizes, stable = dict(st.get("sizes") or {}), True
    for u in st["units"]:
        size = os.path.getsize(u["share"]) if os.path.isfile(u["share"]) else -1
        if size <= 0 or sizes.get(str(u["unit"])) != size:
            stable = False
        sizes[str(u["unit"])] = size
    st["sizes"] = sizes
    if not stable:
        if now - st.get("waiting_since", now) > FEED_FINALIZE_TIMEOUT_S:
            _fail(root, st, "the recorded feed %s did not appear within %ds (is the Movie File Out codec "
                            "available on this licence?)" % (st["units"][0]["share"], FEED_FINALIZE_TIMEOUT_S))
            return
        _save(root, st)
        return

    expected, counter = len(st["frames"]), _frame_counter(cfg)
    for u in st["units"]:
        try:
            actual = counter(u["container"])
        except Exception as exc:
            log("ControlNet %d feed: frame count failed (%s)" % (u["unit"], exc))
            actual = None
        ok, message = feed.verify(expected, actual)
        if not ok:
            _fail(root, st, "ControlNet %d feed: %s (%s)" % (u["unit"], message, u["share"]))
            return
        log("ControlNet %d feed ready: %s (%s)" % (u["unit"], u["container"], message))
        _set_cn_video(root, u["container"], u["unit"])
        if u.get("mode") == feed.SWEEP and st.get("as_mask") and not st.get("mask_set"):
            ui = _op(root, "ui")
            _set_par(ui, "Videomaskpath", u["container"])
            _set_par(ui, "Usemaskvideo", 1)
            st["mask_set"] = True
            log("Sweep Depth is also the mask video: video_mask_path = %s, use_mask_video on" % u["container"])
        _set_feed_info(root, u["unit"], "%d frames @ %s" % (expected, time.strftime("%H:%M:%S")))
    _after_feed(root, cfg, st)


def _after_feed(root, cfg, st):
    try:
        values, result = build(root, cfg)
        _render_stage(root, cfg, st, values, result)
    except Exception as exc:
        traceback.print_exc()
        _fail(root, st, "render after the feed failed: %s" % exc)


# --------------------------------------------------------------------------- polling

def tick(root):
    """Timer pulse: poll whatever the pipeline is waiting on."""
    st = _state(root)
    current = st.get("state", IDLE)
    if current == IDLE:
        return
    cfg = config.load()
    now = time.time()
    if now - st.get("last_tick", 0) < cfg["poll_interval_s"] * 0.5:
        return  # chopexec_poll may fire on both offToOn and whileOn
    st["last_tick"] = now

    if current in (COMFY_SUBMITTED, DEFORUM_SUBMITTED):
        if now - st.get("submitted", now) > cfg["submit_timeout_s"]:
            _fail(root, st, "no answer to the %s request after %ds; is the server up?"
                  % ("ComfyUI" if current == COMFY_SUBMITTED else "Deforum", cfg["submit_timeout_s"]))
            return
    elif current in (COMFY_RUNNING, DEFORUM_RUNNING) and now - st.get("updated", now) > LOST_CONTACT_S:
        _fail(root, st, "lost contact while %s (no response for %ds)" % (current, LOST_CONTACT_S))
        return
    elif current == COMFY_RUNNING:
        _op(root, "comfy").request(config.comfy_url(cfg, "/history/%s" % st["comfy_prompt_id"]), "GET")
    elif current == DEFORUM_RUNNING:
        _op(root, "progress").request(
            config.deforum_url(cfg, "/deforum_api/jobs/%s" % st["job_id"]), "GET")
    elif current == WAITING_FILE:
        _try_load(root, cfg, st)
        return
    elif current == WAITING_FEED:
        _poll_feed(root, cfg, st)
        return
    elif current == CAPTURING:
        # Driven every frame by feed_capture_exec; cancel() aborts it. If its callbacks do not
        # arrive (paused timelines may not call Frame End), fall back to a run() chain.
        if now - st.get("updated", now) > CAPTURE_STALL_S and st.get("driver", "frameend") != "run":
            try:
                log("warning: " + _stall_diagnostic(root, st))
                log("switching the capture to a run() chain")
                st["driver"] = "run"
                _save(root, st)
                capture_tick(root, "run")
            except Exception as exc:
                traceback.print_exc()
                _abort_capture(root, st)
                _fail(root, st, "feed capture could not start: %s" % exc)
        return
    _save(root, st)


def on_response(root, dat, status_code, data):
    code = status_code.get("code") if isinstance(status_code, dict) else status_code
    text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else (data or "")
    try:
        body = json.loads(text) if text.strip() else None
    except ValueError:
        body = None
    try:
        cfg = config.load()
        st = _state(root)
        if dat.name == NAMES["comfy"]:
            _on_comfy(root, cfg, st, code, body, text)
        elif dat.name == NAMES["deforum"]:
            _on_deforum_submit(root, st, code, body, text)
        elif dat.name == NAMES["progress"]:
            _on_progress(root, cfg, st, code, body)
    except Exception as exc:
        traceback.print_exc()
        log("response handling failed for %s: %s" % (dat.name, exc))


def on_error(root, dat, error):
    """A Web Client DAT could not complete a request (no answer at all, unlike an HTTP error)."""
    log("%s request error: %s" % (dat.name, error))
    st = _state(root)
    cfg = config.load()
    if dat.name == NAMES["comfy"] and st.get("state") == COMFY_SUBMITTED:
        _fail(root, st, "could not reach ComfyUI at %s (%s). Open that address in a browser on this "
                        "computer; if it does not load, the container port is not published or a firewall "
                        "blocks it. Set server_host / comfy_port in %s if it lives elsewhere."
              % (config.comfy_url(cfg), error, cfg["local_file"]))
    elif dat.name == NAMES["deforum"] and st.get("state") == DEFORUM_SUBMITTED:
        _fail(root, st, "could not reach Deforum at %s (%s)" % (config.deforum_url(cfg), error))


def _reachable(host, port, timeout=2.0):
    """'open' / the reason a TCP connection to host:port failed (checked from this computer)."""
    import socket
    try:
        socket.create_connection((host, int(port)), timeout).close()
        return "open"
    except Exception as exc:
        return "NOT reachable (%s)" % (exc,)


def _on_deforum_submit(root, st, code, body, text):
    if st.get("state") != DEFORUM_SUBMITTED:
        log("Deforum answered while %s: %s" % (st.get("state"), text[:200]))
        return
    if code in (200, 202) and isinstance(body, dict) and body.get("job_ids"):
        now = time.time()
        _save(root, {"state": DEFORUM_RUNNING, "job_id": body["job_ids"][0],
                     "batch_id": body.get("batch_id"), "submitted": st.get("submitted", now),
                     "updated": now, "last_phase": None, "last_pct": -100,
                     "expect": st.get("expect")})
        _set_status(root, "render: queued")
        log("Deforum accepted job %s" % body["job_ids"][0])
    else:
        _fail(root, st, "Deforum rejected the batch (HTTP %s): %s" % (code, text[:300]))


def _on_progress(root, cfg, st, code, body):
    if st.get("state") != DEFORUM_RUNNING:
        if isinstance(body, dict) and body.get("message"):
            log("Deforum: %s" % body["message"])  # e.g. cancel acknowledgement
        return
    if code == 404:
        _fail(root, st, "Deforum no longer knows job %s (A1111 restarted?)" % st.get("job_id"))
        return
    if not isinstance(body, dict) or body.get("id") != st.get("job_id"):
        return

    job_status, phase = body.get("status"), body.get("phase")
    pct = int(round(100 * float(body.get("phase_progress") or 0)))
    st["updated"] = time.time()

    if job_status in ("FAILED", "CANCELLED"):
        _fail(root, st, "Deforum job %s %s: %s" % (st["job_id"], job_status.lower(),
                                                   body.get("message") or body.get("error_type")))
        return
    if job_status == "SUCCEEDED" or phase == "DONE":
        outdir, stamp = body.get("outdir"), body.get("timestring")
        if not outdir or not stamp:
            _fail(root, st, "Deforum finished but reported no outdir/timestring")
            return
        plain = "%s/%s.mp4" % (outdir.rstrip("/"), stamp)
        video = render_path(outdir, stamp, st.get("expect"))
        st.update(state=WAITING_FILE, video=video, video_share=config.to_share(cfg, video),
                  fallback_share=config.to_share(cfg, plain) if video != plain else None,
                  waiting_since=time.time(), last_size=-1)
        _save(root, st)
        log("render done in %.0fs: %s" % (float(body.get("execution_time") or 0),
                                         st["video_share"] or video))
        _try_load(root, cfg, st)
        return

    if phase != st.get("last_phase") or pct >= st.get("last_pct", -100) + 10:
        log("render %s %d%%" % (phase, pct))
        st["last_phase"], st["last_pct"] = phase, pct
    _set_status(root, "render: %s %d%%" % (str(phase).lower(), pct))
    _save(root, st)


def _on_comfy(root, cfg, st, code, body, text):
    current = st.get("state")
    if isinstance(body, dict) and "prompt_id" in body and "number" in body:
        if current == COMFY_SUBMITTED:
            st.update(state=COMFY_RUNNING, comfy_prompt_id=body["prompt_id"], updated=time.time())
            _save(root, st)
            _set_status(root, "preprocessing: queued")
            log("ComfyUI accepted prompt %s" % body["prompt_id"])
        return
    if code is not None and code >= 400:
        if current in (COMFY_SUBMITTED, COMFY_RUNNING):
            _fail(root, st, "ComfyUI rejected the workflow (HTTP %s): %s"
                  % (code, comfy.error_text(body, text)))
        return
    if current != COMFY_RUNNING or not isinstance(body, dict):
        return

    state, subfolder, filename, message = comfy.parse_history(
        body, st.get("comfy_prompt_id"), cfg["comfy_output_node"])
    if state == "pending":
        st["updated"] = time.time()
        _save(root, st)
        _set_status(root, "preprocessing: running")
        return
    if state == "error":
        _fail(root, st, "ComfyUI preprocess failed: %s" % message)
        return

    container_path = config.comfy_output_to_container(cfg, subfolder, filename)
    if container_path is None:
        _fail(root, st, "ComfyUI wrote %s/%s but config comfy_output_map has no mount for it"
              % (subfolder, filename))
        return
    cache = dict(root.fetch(CACHE_KEY, {}, search=False) or {})
    cache[st.get("cache_key")] = container_path
    root.store(CACHE_KEY, cache)
    _store_preprocessed(root, container_path, st.get("purpose"))
    log("preprocess done: %s" % container_path)

    if st.get("purpose") == "sweep":
        try:
            values, result = build(root, cfg)
            if sweep.prepare_only(values):
                _finish(root, st, "depth video ready: %s" % container_path)
                return
            _feed_and_render(root, cfg, st, values, result)
        except Exception as exc:
            traceback.print_exc()
            _fail(root, st, "after the depth video: %s" % exc)
    elif st.get("then_render"):
        _values, result = build(root, cfg)
        _submit_deforum(root, cfg, result, st)
    else:
        _finish(root, st, "preprocessed %s" % filename)


def render_path(outdir, stamp, expect):
    """Container path of the file to load: <ts>_RIFE_xN.mp4 / <ts>_FILM_xN.mp4 or <ts>.mp4.

    Deforum writes interpolated videos next to the plain one in the batch outdir
    (frame_interpolation.py / rife inference_video.py at 5d63a339).
    """
    outdir = outdir.rstrip("/")
    if expect and expect.get("engine"):
        tag = "RIFE" if expect["engine"].startswith("RIFE") else "FILM"
        return "%s/%s_%s_x%d.mp4" % (outdir, stamp, tag, expect["x"])
    return "%s/%s.mp4" % (outdir, stamp)


def _try_load(root, cfg, st):
    path = st.get("video_share")
    if not path:
        _finish(root, st, "render saved to %s (not on the share, not loaded)" % st.get("video"))
        return
    waited = time.time() - st.get("waiting_since", time.time())
    fallback = st.get("fallback_share")
    if fallback and not os.path.isfile(path) and waited > INTERP_FALLBACK_S and os.path.isfile(fallback):
        log("no interpolated file after %ds; loading the un-interpolated render "
            "(check the container log for RIFE/FILM errors)" % waited)
        st.update(video_share=fallback, fallback_share=None, last_size=-1, interp_missing=True)
        path = fallback
    size = os.path.getsize(path) if os.path.isfile(path) else -1
    # Loaded once the file exists and its size held steady for one poll interval.
    if size > 0 and size == st.get("last_size"):
        ui = _op(root, "ui")
        auto = getattr(ui.par, "Autoload", None) if ui is not None else None
        if auto is None or auto.eval():
            expect = st.get("expect")
            if expect and st.get("interp_missing"):
                # Plain render: x times fewer frames for the same loop -> play slower.
                expect = dict(expect, rate=1.0 / max(1, expect["x"]))
            _load_movie(root, path, expect)
            _finish(root, st, "loaded " + os.path.basename(path))
        else:
            _finish(root, st, "render ready: " + path)
        return
    if waited > cfg["file_wait_timeout_s"]:
        _fail(root, st, "%s did not appear on the share within %ds" % (path, cfg["file_wait_timeout_s"]))
        return
    st["last_size"] = size
    _save(root, st)


def _video_frames(path):
    try:
        import cv2  # bundled with TouchDesigner's Python
    except Exception:
        return None
    capture = cv2.VideoCapture(path)
    try:
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()
    return frames if frames > 0 else None


def _load_movie(root, path, expect=None):
    movie = _op(root, "movie")
    if movie is not None:
        _set_constant(movie.par.file, path)
        movie.par.reloadpulse.pulse()
    folder = _op(root, "folder")
    if folder is not None:
        folder.par.refresh.pulse()
    ui = _op(root, "ui")
    for key in ("head", "tail"):
        player = _inner(ui, key)
        if player is not None:
            _set_constant(player.par.file, path)
            reload_ = getattr(player.par, "reloadpulse", None)
            if reload_ is not None:
                reload_.pulse()
    if expect and expect.get("out_loop"):
        loop = int(expect["out_loop"])                 # output frames per loop
        rate = float(expect.get("rate", 1.0))          # file frames per output frame
        frames = _video_frames(path)
        if frames:
            overlap = int((frames - loop * rate) / rate)
        else:
            overlap = int(expect.get("overlap_out", 0))
        overlap = max(0, min(overlap, loop))
        _set_par(ui, "Loopoutframes", str(loop))
        _set_par(ui, "Loopoutoverlap", str(overlap))
        _set_par(ui, "Loopoutrate", "%g" % rate)
        log("loop player: %d-frame loop, %d-frame seam crossfade%s%s"
            % (loop, overlap, "" if rate == 1 else ", file played at %gx" % rate,
               "" if frames else " (file length unknown, used the plan)"))


# --------------------------------------------------------------------------- buttons

def latest_render(paths):
    """Newest <timestring>.mp4 among paths (ignores _depth / interpolated variants)."""
    best = None
    for path in paths:
        match = RENDER_NAME.match(os.path.basename(path))
        if match and (best is None or match.group(1) > best[0]):
            best = (match.group(1), path)
    return best[1] if best else None


def load_latest(root):
    cfg = config.load()
    outputs = config.to_share(cfg, "/opt/a1111/outputs/img2img-images/")
    path = latest_render(glob.glob(outputs + "Deforum_*/*.mp4"))
    if path is None:
        log("no Deforum renders found under %s" % outputs)
        return
    _load_movie(root, path.replace("\\", "/"))
    log("loaded latest render %s" % path)


def preview(root):
    """Compile everything Queue would send, without sending it.

    Writes the COMP's schedule_preview table (parameter | mode | schedule, moving
    parameters first, then the prompt keys) and logs the summary and warnings.
    """
    cfg = config.load()
    resync(root, cfg)
    _apply_preset_safely(root)
    values, result = build(root, cfg)
    for warning in result["warnings"]:
        log("warning: " + warning)
    order = {"expression": 0, "baked": 1, "raw": 2, "constant": 3}
    rows = sorted(result["schedules"].items(), key=lambda kv: (order.get(kv[1][0], 9), kv[0]))
    table = _inner(_op(root, "ui"), "preview")
    if table is not None:
        table.clear()
        table.appendRow(["parameter", "mode", "schedule"])
        for api, (how, sched) in rows:
            table.appendRow([api, how, sched])
        prompts = result["request"]["deforum_settings"].get("prompts", {})
        for frame in sorted(prompts, key=lambda k: int(k) if str(k).lstrip("-").isdigit() else 0):
            table.appendRow(["prompt @%s" % frame, "prompt", prompts[frame]])
    for api, (how, sched) in rows:
        if how != "constant":
            log("%-28s %-10s %s" % (api, how, sched if len(sched) < 160 else sched[:157] + "..."))
    held = ["%s %s" % (api.replace("_schedule", ""), result["schedules"][api][1])
            for api in ("strength_schedule", "cfg_scale_schedule", "noise_schedule")
            if api in result["schedules"] and result["schedules"][api][0] == "constant"]
    if held:
        log("held (also in schedule_preview): " + " | ".join(held))
    _log_feed_plan(root, values, result)
    log("preview: " + payload.summary(result))
    return result


def _log_feed_plan(root, values, result):
    wants = feed.requests(values)
    for want in wants:
        if want.mode == feed.TOP_STILL:
            log("feed: ControlNet %d takes one still from %s at Queue" % (want.unit, want.top or "(no TOP set)"))
    loops = [w for w in wants if w.mode in (feed.TOP_LOOP, feed.SWEEP)]
    if loops:
        try:
            sweeping = any(w.mode == feed.SWEEP for w in loops)
            plan, rate = _feed_plan(root, values, result, wrap=not sweeping)
            log("feed: ControlNet %s record %s from %s at Queue (timeline %g fps)" % (
                ",".join(str(w.unit) for w in loops), feed.describe(plan),
                ", ".join(sorted(set("Sweep Depth" if w.mode == feed.SWEEP else (w.top or "(no TOP set)")
                                     for w in loops))), rate))
            if sweeping:
                problem = sweep.check(values)
                if problem:
                    log("feed: WARNING " + problem)
                else:
                    p = result["plan"]
                    log("sweep: " + sweep.describe(sweep.plan(
                        values, p["max_frames"], p.get("extract_from_frame") or 0,
                        p.get("extract_nth_frame") or 1)))
        except Exception as exc:
            log("feed: cannot plan the recording: %s" % exc)


def bake(root):
    """Bake button: the CHOP bake now happens at Queue time, so this previews it."""
    return preview(root)


# --------------------------------------------------------------------------- diagnostics

def _doctor_feeds(root, cfg, ui, values):
    """TOP guide feeds: which units use them, whether the pieces they need exist."""
    wants = feed.requests(values)
    for unit in range(1, feed.UNITS + 1):
        mode = feed.mode_of(values, unit)
        if mode == feed.FILE:
            continue
        want = [w for w in wants if w.unit == unit]
        top = str(values.get("feed_%d_top" % unit, "") or "")
        found = root.op(top) is not None if top else False
        if mode == feed.SWEEP:
            top, found = "Sweep Depth", True
        log("ControlNet %d guide: %s from %s [%s]%s" % (
            unit, mode, top or "(no Source TOP)", "TOP found" if found else "TOP NOT FOUND",
            "" if want else " (unit is off, so it will not be recorded)"))
        sel, out = ui.op(FEED_SELECT % unit), ui.op(FEED_OUT % unit)
        if mode == feed.SWEEP:
            problem = sweep.check(values)
            log("  Sweep Depth: %s" % (problem or "settings OK (%s)" % sweep.describe(sweep.plan(values, 240)).split(":")[0]))
            depth, script = ui.op(SWEEP_DEPTH), ui.op(SWEEP_MASK)
            if depth is None or script is None:
                log("  %s / %s missing from the COMP: run builder_master_ui" % (SWEEP_DEPTH, SWEEP_MASK))
            path = str(values.get("sweep_depth_path", "") or "")
            log("  depth video: %s" % (path or "(none yet; ComfyUI makes it at Queue)"))
        if mode in (feed.TOP_LOOP, feed.SWEEP) and (sel is None or out is None):
            log("  %s / %s missing from the COMP: run builder_master_ui" % (FEED_SELECT % unit, FEED_OUT % unit))
    if any(w.mode in (feed.TOP_LOOP, feed.SWEEP) for w in wants):
        exec_dat = root.op(NAMES["feed_exec"])
        if exec_dat is None:
            log("%s missing: run setup_network (the loop recorder steps on its Frame End)" % NAMES["feed_exec"])
        try:
            timeline = _timeline(root)
            log("timeline: %g fps, starts at frame %s, frame %s" % (
                float(getattr(timeline, "rate", 0) or 0), getattr(timeline, "start", "?"), timeline.frame))
        except Exception as exc:
            log("timeline unreadable: %s" % exc)
    if wants:
        folder = config.to_share(cfg, cfg["cn_feed_dir"] + "/")
        log("feeds are written to %s (container %s)" % (folder, cfg["cn_feed_dir"]))


def doctor(root):
    """Print what the pipeline can and cannot see. Safe to run any time."""
    cfg = config.load()
    resync(root, cfg)
    log("share root %s | scripts %s | runtime %s" % (cfg["share_root"], cfg["scripts_dir"], cfg["runtime_dir"]))
    log("tdeforum %s | %d example presets | sweep depth page %s" % (
        getattr(sys.modules.get("tdeforum"), "__version__", "?"), len(presets.PRESETS),
        "yes" if schema.PAGE_SWEEP in schema.PAGE_ORDER else "no"))
    log("Deforum %s | ComfyUI %s" % (config.deforum_url(cfg), config.comfy_url(cfg)))
    log("port check from this computer: Deforum %s:%s %s | ComfyUI %s:%s %s" % (
        cfg["server_host"], cfg["deforum_port"], _reachable(cfg["server_host"], cfg["deforum_port"]),
        cfg["server_host"], cfg["comfy_port"], _reachable(cfg["server_host"], cfg["comfy_port"])))
    ui = _op(root, "ui")
    values = read_ui(ui) if ui is not None else {}
    if ui is None:
        log("no 'deforum' COMP: run builder_master_ui")
    elif ui.name != NAMES["ui"]:
        log("using the old %s; run builder_master_ui to build the 'deforum' COMP" % ui.name)
    else:
        try:
            tp = payload.tempo_plan(values)
            log("tempo: " + (tempo.describe(tp) if tp else "manual length (%s frames)" % values.get("max_frames")))
            for warning in (tp or {}).get("warnings", []):
                log("tempo warning: " + warning)
        except ValueError as exc:
            log("tempo settings invalid: %s" % exc)
        slots = payload.read_slots(values, [])
        log("mod slots active: %s" % (", ".join("%d->%s" % (s.index, s.target) for s in slots) or "none"))
        chop = read_mod_chop(ui, values)
        known = set(a.lower() for a in schema.MOD_APIS) | set(f.td_name.lower() for f in schema.MOD_FIELDS)
        if chop:
            used = sorted(n for n in chop if n.lower() in known)
            log("Mod CHOP channels used: %s%s" % (", ".join(used) or "none", "" if len(used) == len(chop)
                                                 else " (others ignored: %s)" % ", ".join(sorted(set(chop) - set(used)))))
        rows = read_prompt_rows(ui)
        log("prompt_seq rows: %d (source: %s)" % (max(0, len(rows or []) - 1), values.get("prompt_source")))
        _doctor_feeds(root, cfg, ui, values)
    for api in ("video_init_path", "video_mask_path", "cn_1_vid_path"):
        container_path = str(values.get(api, "") or "")
        if not container_path:
            continue
        share = config.to_share(cfg, container_path)
        seen = "OK" if share and os.path.isfile(share) else "NOT VISIBLE from TD"
        log("%-16s %s -> %s [%s]" % (api, container_path, share, seen))
    preproc = config.to_share(cfg, cfg["comfy_output_map"].get("preprocessed_vids", "") + "/")
    if preproc:
        found = len(glob.glob(preproc + "*.mp4"))
        log("ComfyUI preprocessed_vids on the share: %s (%d mp4)" % (preproc, found))
    cb = root.op("webclient2_callbacks")
    for key in ("deforum", "progress", "comfy"):
        dat = _op(root, key)
        if dat is None:
            log("%s missing" % NAMES[key])
        elif cb is None or dat.par.callbacks.eval() != cb:
            log("%s callbacks -> %s (run setup_network.py)" % (dat.name, dat.par.callbacks.eval()))
    movie = _op(root, "movie")
    if movie is not None and not _is_constant(movie.par.file):
        log("moviefilein1.file is expression-driven; auto-load will switch it to constant")
    log("pipeline state: %s" % _state(root).get("state"))
