"""ComfyUI preprocessing: build the /prompt request and read /history results.

The workflow template (scripts/templates/TD_CN_PreProc.json) has four nodes:
10 VHS_LoadVideoPath -> 11 ImageResizeKJv2 -> 19 AIO_Preprocessor -> 21 VHS_VideoCombine
"""

import copy
import posixpath

from . import config


def cache_name(init_path, width, height, preprocessor, frames):
    base = posixpath.splitext(posixpath.basename(str(init_path).replace("\\", "/")))[0]
    return "%s_%dx%d_%s_%df" % (base, int(width), int(height), preprocessor, int(frames))


def build_prompt(template, cfg, values, plan, force=False, stamp=""):
    """Return {"cache_key", "body"} for POST /prompt.

    frame_load_cap uses plan["source_frames"]: the raw frame range Deforum will
    read from the guide video. In stride mode Deforum strides the ControlNet
    video itself, so the preprocess must cover the whole range, not max_frames.
    """
    width, height = int(values["W"]), int(values["H"])
    preprocessor = str(values["comfy_preprocessor"])
    frames = int(plan["source_frames"])
    key = cache_name(values["video_init_path"], width, height, preprocessor, frames)

    workflow = copy.deepcopy(template)
    load = workflow["10"]["inputs"]
    load["video"] = config.to_comfy_input(cfg, values["video_init_path"])
    load["frame_load_cap"] = frames
    load["skip_first_frames"] = 0
    load["select_every_nth"] = 1
    workflow["11"]["inputs"]["width"] = width
    workflow["11"]["inputs"]["height"] = height
    resolution = int(values.get("comfy_resolution") or 0) or min(width, height)
    if preprocessor.startswith("depth_anything_v2_vit"):
        from . import sweep           # a dedicated node: the AIO one always loads the large model
        workflow["19"] = sweep.comfy_depth_node(preprocessor, workflow["19"]["inputs"]["image"],
                                                min(resolution, min(width, height)))
    else:
        workflow["19"]["inputs"]["preprocessor"] = preprocessor
        workflow["19"]["inputs"]["resolution"] = min(resolution, min(width, height))
    # A new prefix changes the output node's inputs, so ComfyUI's cache can't
    # skip writing the file when a re-preprocess is forced.
    prefix = "preprocessed_vids/" + key + ("_" + stamp if force and stamp else "")
    workflow[cfg["comfy_output_node"]]["inputs"]["filename_prefix"] = prefix

    return {"cache_key": key,
            "body": {"prompt": workflow, "client_id": cfg.get("comfy_client_id", "tdeforum")}}


VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".gif")


def parse_history(history, prompt_id, output_node="21"):
    """Read GET /history/<id>. Returns (state, subfolder, filename, message).

    state is "pending", "done" or "error".
    """
    entry = history.get(prompt_id) if isinstance(history, dict) else None
    if not entry:
        return "pending", None, None, None

    status = entry.get("status") or {}
    if status.get("status_str") == "error":
        return "error", None, None, _status_error(status) or "ComfyUI reported an error"

    outputs = entry.get("outputs") or {}
    ordered = [outputs.get(output_node)] + [v for k, v in outputs.items() if k != output_node]
    for node_out in ordered:
        if not isinstance(node_out, dict):
            continue
        for key in ("gifs", "videos", "images"):
            for item in node_out.get(key) or []:
                name = str(item.get("filename", ""))
                if name.lower().endswith(VIDEO_EXTS):
                    return "done", str(item.get("subfolder", "")), name, None

    if status.get("completed") is False:
        return "pending", None, None, None
    return "error", None, None, "ComfyUI finished without a video output (check node %s)" % output_node


def _status_error(status):
    for message in status.get("messages") or []:
        if isinstance(message, (list, tuple)) and len(message) == 2 and message[0] == "execution_error":
            info = message[1] or {}
            return "%s in node %s: %s" % (info.get("exception_type", "error"),
                                          info.get("node_id", "?"),
                                          info.get("exception_message", "").strip())
    return None


def error_text(body, raw_text=""):
    """Human summary of a rejected POST /prompt."""
    if isinstance(body, dict):
        err = body.get("error")
        parts = []
        if isinstance(err, dict):
            parts.append(err.get("message") or err.get("type") or "")
        node_errors = body.get("node_errors") or {}
        for node_id, info in node_errors.items():
            for e in (info or {}).get("errors", []):
                parts.append("node %s: %s %s" % (node_id, e.get("message", ""), e.get("details", "")))
        text = "; ".join(p.strip() for p in parts if p and p.strip())
        if text:
            return text
    return (raw_text or "").strip()[:300]
