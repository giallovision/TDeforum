"""TouchDesigner glue: Queue -> (ComfyUI preprocess) -> Deforum render -> auto-load.

Entry points (each called from a thin DAT in scripts/):

    queue(root)             Queue button            deforum_payload_exec.py
    tick(root)              timer1 cycle pulse      chopexec_poll.py
    on_response(root, ...)  all three webclients    webclient2_callbacks.py
    bake(root)              bake button             bake_exec.py
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
from . import schedules
from . import schema

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
    "ui": "Deforum_UI",
    "deforum": "webclient_deforum",
    "progress": "webclient_progress",
    "comfy": "webclient_comfyui",
    "prompts": "deforum_prompts",
    "models": "available_models",
    "movie": "moviefilein1",
    "folder": "folder_monitor",
    "wave": "wave_generator",
    "bake_out": "bake_out",
    "quantize": "quantize_settings",
}

RENDER_NAME = re.compile(r"^(\d{14})\.mp4$")


def log(message):
    print("[TDeforum] " + message)


# --------------------------------------------------------------------------- state

def _op(root, key):
    return root.op(NAMES[key])


def _state(root):
    stored = root.fetch(STATE_KEY, None, search=False)
    return dict(stored) if isinstance(stored, dict) else {"state": IDLE}


def _save(root, st):
    root.store(STATE_KEY, st)


def _set_status(root, text):
    ui = _op(root, "ui")
    par = getattr(ui.par, "Pipelinestatus", None) if ui is not None else None
    if par is not None:
        try:
            par.val = text
        except Exception:
            pass


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
    return values


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
        raise RuntimeError("Deforum_UI not found in %s" % root.path)
    values = read_ui(ui)
    result = payload.build_request(values, read_prompts(root, cfg), read_models(root),
                                   _frame_counter(cfg), cfg.get("default_checkpoint",
                                                                payload.DEFAULT_CHECKPOINT))
    return values, result


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
    _save(root, {"state": DEFORUM_SUBMITTED, "submitted": now, "updated": now})
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
                     "updated": now, "last_phase": None, "last_pct": -100})
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
        video = "%s/%s.mp4" % (outdir.rstrip("/"), stamp)
        st.update(state=WAITING_FILE, video=video, video_share=config.to_share(cfg, video),
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


def _try_load(root, cfg, st):
    path = st.get("video_share")
    if not path:
        _finish(root, st, "render saved to %s (not on the share, not loaded)" % st.get("video"))
        return
    size = os.path.getsize(path) if os.path.isfile(path) else -1
    # Loaded once the file exists and its size held steady for one poll interval.
    if size > 0 and size == st.get("last_size"):
        ui = _op(root, "ui")
        auto = getattr(ui.par, "Autoload", None) if ui is not None else None
        if auto is None or auto.eval():
            _load_movie(root, path)
            _finish(root, st, "loaded " + os.path.basename(path))
        else:
            _finish(root, st, "render ready: " + path)
        return
    if time.time() - st.get("waiting_since", time.time()) > cfg["file_wait_timeout_s"]:
        _fail(root, st, "%s did not appear on the share within %ds" % (path, cfg["file_wait_timeout_s"]))
        return
    st["last_size"] = size
    _save(root, st)


def _load_movie(root, path):
    movie = _op(root, "movie")
    if movie is not None:
        _set_constant(movie.par.file, path)
        movie.par.reloadpulse.pulse()
    folder = _op(root, "folder")
    if folder is not None:
        folder.par.refresh.pulse()


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


def bake(root):
    """Bake wave_generator channels into keyframe strings.

    A channel named like a schedule (translation_z, zoom, ...) is written straight
    into that Deforum_UI parameter. Otherwise channel 0 goes to the 'Bake into'
    parameter (Pipeline page). bake_out always gets a copy.
    """
    src, out, ui = _op(root, "wave"), _op(root, "bake_out"), _op(root, "ui")
    if src is None or out is None or src.numChans == 0:
        log("bake: wave_generator / bake_out missing or empty")
        return
    values = read_ui(ui) if ui is not None else {}
    points = values.get("bake_points")
    if points is None:
        quant = _op(root, "quantize")
        points = quant[0][0] if quant is not None and quant.numChans else 0
    target = values.get("bake_target", "none")

    lines = []
    for index, chan in enumerate(src.chans()):
        keys = schedules.keyframe_string(chan.vals, int(points), 4)
        dest = chan.name if chan.name in schema.SCHEDULE_APIS else (
            target if index == 0 and target and target != "none" else None)
        note = ""
        par = getattr(ui.par, schema.BY_API[dest].td_name, None) if dest and ui is not None else None
        if dest and par is None:
            note = " (Deforum_UI has no %s; run build_master_ui)" % schema.BY_API[dest].td_name
        elif par is not None:
            if _is_constant(par):
                par.val = keys
                note = " -> %s" % par.name
            else:
                note = " (%s is driven by an expression/export; not overwritten)" % par.name
        lines.append((chan.name, keys))
        log("baked %s: %d keys%s" % (chan.name, keys.count(":"), note))
    out.text = lines[0][1] if len(lines) == 1 else "\n".join("%s: %s" % kv for kv in lines)


# --------------------------------------------------------------------------- diagnostics

def doctor(root):
    """Print what the pipeline can and cannot see. Safe to run any time."""
    cfg = config.load()
    log("share root %s | scripts %s | runtime %s" % (cfg["share_root"], cfg["scripts_dir"], cfg["runtime_dir"]))
    log("Deforum %s | ComfyUI %s" % (config.deforum_url(cfg), config.comfy_url(cfg)))
    ui = _op(root, "ui")
    values = read_ui(ui) if ui is not None else {}
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
