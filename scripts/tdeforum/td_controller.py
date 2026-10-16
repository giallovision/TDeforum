"""TouchDesigner glue: Queue -> (ComfyUI preprocess) -> Deforum render -> auto-load.

Entry points (each called from a thin DAT in scripts/):

    queue(root)             Queue button            deforum_payload_exec.py
    tick(root)              timer1 cycle pulse      chopexec_poll.py
    on_response(root, ...)  all three webclients    webclient2_callbacks.py
    bake(root) / preview    bake button             bake_exec.py  (schedule preview, no POST)
    load_latest(root)       LoadVideo button        loadvideo_exec.py
    export_payload(root)    dry run, no POST        export_deforum_payload.py
    preprocess_only(root)   ComfyUI only            comfy_preprocessor_payload_exec.py
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
import time
import traceback

from . import comfy
from . import config
from . import payload
from . import schema
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
BUSY = (COMFY_SUBMITTED, COMFY_RUNNING, DEFORUM_SUBMITTED, DEFORUM_RUNNING, WAITING_FILE)
LOST_CONTACT_S = 120.0

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
}
# Inside the Deforum COMP
INNER = {
    "prompt_seq": "prompt_seq",       # table: beat | prompt | xfade
    "mod_in": "in_mod",               # In CHOP = COMP input 1 (the Mod CHOP)
    "preview": "schedule_preview",    # table written by preview()
    "head": "loop_head",              # loop player: Movie File In at the playhead
    "tail": "loop_tail",              # loop player: Movie File In one loop later
}

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
    st = _state(root)
    if st.get("state") in BUSY and time.time() - st.get("updated", 0) < LOST_CONTACT_S:
        log("busy (%s). Wait, or op('deforum_payload_exec').module.cancel()" % st["state"])
        return
    try:
        values, result = build(root, cfg)
        for warning in result["warnings"]:
            log("warning: " + warning)
        if _wants_preprocess(values):
            if _start_preprocess(root, cfg, values, result, st, then_render=True):
                return
            values, result = build(root, cfg)  # cache hit changed Cn1vidpath
        _submit_deforum(root, cfg, result, st)
    except Exception as exc:
        traceback.print_exc()
        _fail(root, st, "queue failed: %s" % exc)


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
    return True


def _start_preprocess(root, cfg, values, result, st, then_render):
    """Submit the ComfyUI job. Returns False if nothing was submitted."""
    try:
        with open(cfg["comfy_template"], "r", encoding="utf-8") as fh:
            template = json.load(fh)
    except Exception as exc:
        log("ComfyUI template unreadable (%s); skipping preprocess" % exc)
        return False

    force = payload._as_bool(values.get("force_preprocess", False))
    job = comfy.build_prompt(template, cfg, values, result["plan"], force=force,
                             stamp=time.strftime("%Y%m%d%H%M%S"))
    cache = dict(root.fetch(CACHE_KEY, {}, search=False) or {})
    if not force and job["cache_key"] in cache:
        _set_cn_video(root, cache[job["cache_key"]])
        log("preprocess cache hit: %s" % cache[job["cache_key"]])
        return False

    _op(root, "comfy").request(config.comfy_url(cfg, "/prompt"), "POST",
                               header=JSON_HEADERS, data=json.dumps(job["body"]))
    now = time.time()
    st = {"state": COMFY_SUBMITTED, "submitted": now, "updated": now,
          "cache_key": job["cache_key"], "then_render": then_render}
    _save(root, st)
    _set_status(root, "preprocessing: submitted")
    log("ComfyUI preprocess submitted: %s (%s frames)" % (job["cache_key"], result["plan"]["source_frames"]))
    return True


def _submit_deforum(root, cfg, result, st):
    _write_runtime_json(cfg, "last_deforum_payload.json", result["request"])
    _op(root, "deforum").request(config.deforum_url(cfg, "/deforum_api/batches"), "POST",
                                 header=JSON_HEADERS, data=json.dumps(result["request"]))
    now = time.time()
    _save(root, {"state": DEFORUM_SUBMITTED, "submitted": now, "updated": now,
                 "expect": _expectation(result)})
    _set_status(root, "render: submitted")
    log("render submitted: " + payload.summary(result))


def _set_cn_video(root, container_path):
    par = getattr(_op(root, "ui").par, "Cn1vidpath", None)
    if par is not None:
        _set_constant(par, container_path)


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
    log("%s request error: %s" % (dat.name, error))


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
    _set_cn_video(root, container_path)
    log("preprocess done: %s" % container_path)

    if st.get("then_render"):
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
    _values, result = build(root, cfg)
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
    log("preview: " + payload.summary(result))
    return result


def bake(root):
    """Bake button: the CHOP bake now happens at Queue time, so this previews it."""
    return preview(root)


# --------------------------------------------------------------------------- diagnostics

def doctor(root):
    """Print what the pipeline can and cannot see. Safe to run any time."""
    cfg = config.load()
    log("share root %s | scripts %s | runtime %s" % (cfg["share_root"], cfg["scripts_dir"], cfg["runtime_dir"]))
    log("Deforum %s | ComfyUI %s" % (config.deforum_url(cfg), config.comfy_url(cfg)))
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
