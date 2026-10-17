"""Endpoints, the container <-> share path bridge, and tunables.

Defaults are derived from where this package lives (``<share>/scripts/tdeforum``),
so a different drive letter needs no edits. Machine-specific overrides go in
``scripts/tdeforum.local.json`` (git-ignored), for example::

    {"server_host": "10.0.10.42", "poll_interval_s": 1.0}
"""

import json
import os

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    # Linux GPU host running the A1111 container (7865) and ComfyUI (8188).
    "server_host": "192.168.1.42",
    "deforum_port": 7865,
    "comfy_port": 8188,
    # How TouchDesigner talks to ComfyUI: "urllib" (Python, real error messages) or "webclient"
    # (the webclient_comfyui Web Client DAT).
    "comfy_transport": "urllib",
    # Container path prefix -> path relative to the share root (T:/).
    # Mirrors the volume list in docker-compose.yml; longest prefix wins.
    # NOTE: /opt/a1111/outputs is ./td_outputs on the host, not ./outputs.
    "path_map": [
        ["/opt/a1111/outputs/", "td_outputs/"],
        ["/opt/a1111/td_masks/", "td_masks/"],
        ["/opt/a1111/td_inputs/", "td_inputs/"],
    ],
    # ComfyUI reads td_inputs/comfy_videos as its own input/ folder.
    "comfy_input_map": [
        ["/opt/a1111/td_inputs/comfy_videos/", "input/"],
    ],
    # ComfyUI output subfolder -> where the A1111 container sees that folder.
    "comfy_output_map": {
        "preprocessed_vids": "/opt/a1111/td_masks/preprocessed_vids",
    },
    "comfy_output_node": "21",
    # ComfyUI's input/ and output/ folders live outside the share on the GPU host (the A1111
    # container sees them through its own volume mounts, TouchDesigner does not). Files TD
    # must read itself (the Sweep Depth video) are downloaded from ComfyUI's /view endpoint
    # into this folder (container path; must be under path_map).
    "comfy_fetch_dir": "/opt/a1111/td_masks/comfy_fetch",
    # Sweep Depth renders: give up waiting for the background render after this long.
    "sweep_timeout_s": 600.0,
    "comfy_client_id": "tdeforum",
    # Where TouchDesigner writes ControlNet guide feeds (container path; must be under
    # path_map so both sides see it) and their container format (.mov for ProRes/Animation).
    "cn_feed_dir": "/opt/a1111/td_masks/feeds",
    "cn_feed_ext": ".mp4",
    # Model used when an index in Sdmodelcheckpoint is missing from available_models.
    "default_checkpoint": "angraRealflexLCMV6_v10.safetensors",
    # Pipeline timing.
    "poll_interval_s": 2.0,
    "submit_timeout_s": 30.0,
    "file_wait_timeout_s": 180.0,
    # Re-import the tdeforum package on every button press (VS Code edit loop).
    "dev_reload": True,
}


def _norm(path):
    return str(path).replace("\\", "/")


def load(local_file=None):
    """Return the effective config dict (defaults + derived paths + local overrides)."""
    scripts_dir = _norm(os.path.dirname(_PKG_DIR))
    share_root = _norm(os.path.dirname(scripts_dir.rstrip("/")))
    if not share_root.endswith("/"):
        share_root += "/"

    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    cfg.update({
        "scripts_dir": scripts_dir,
        "share_root": share_root,
        "prompt_file": scripts_dir + "/prompt.json",
        "comfy_template": scripts_dir + "/templates/TD_CN_PreProc.json",
        "runtime_dir": share_root + "runtime",
        "local_file": local_file or scripts_dir + "/tdeforum.local.json",
    })

    # Tests point the whole share somewhere else (no machine overrides, no real share).
    test_share = os.environ.get("TDEFORUM_TEST_SHARE")
    if test_share:
        root = _norm(test_share).rstrip("/") + "/"
        cfg.update(share_root=root, runtime_dir=root + "runtime", local_file=root + "no-local.json")
    if os.path.isfile(cfg["local_file"]):
        with open(cfg["local_file"], "r", encoding="utf-8") as fh:
            overrides = json.load(fh)
        if isinstance(overrides, dict):
            cfg.update(overrides)
    return cfg


def deforum_url(cfg, path=""):
    return "http://%s:%s%s" % (cfg["server_host"], cfg["deforum_port"], path)


def comfy_url(cfg, path=""):
    return "http://%s:%s%s" % (cfg["server_host"], cfg["comfy_port"], path)


def _map_prefix(path, pairs):
    """Replace the longest matching prefix; return None when nothing matches."""
    path = _norm(path)
    best = None
    for src, dst in pairs:
        if path.startswith(src) and (best is None or len(src) > len(best[0])):
            best = (src, dst)
    if best is None:
        return None
    return best[1] + path[len(best[0]):]


def to_share(cfg, container_path):
    """'/opt/a1111/outputs/x.mp4' -> 'T:/td_outputs/x.mp4' (None if not on the share)."""
    rel = _map_prefix(container_path, cfg["path_map"])
    return None if rel is None else cfg["share_root"] + rel


def to_container(cfg, share_path):
    """Inverse of to_share for paths under the share root."""
    share_path = _norm(share_path)
    root = cfg["share_root"]
    if share_path.lower().startswith(root.lower()):
        share_path = share_path[len(root):]
    reverse = [[dst, src] for src, dst in cfg["path_map"]]
    return _map_prefix(share_path, reverse)


def to_comfy_input(cfg, container_path):
    """Container path of an init video -> path ComfyUI's VHS loader understands."""
    mapped = _map_prefix(container_path, cfg["comfy_input_map"])
    return mapped if mapped is not None else _norm(container_path)


def comfy_view(cfg, container_path):
    """(type, subfolder, filename) to ask ComfyUI's /view for a container path, or None.

    Outputs: comfy_output_map ("preprocessed_vids" -> /opt/a1111/td_masks/preprocessed_vids).
    Inputs: comfy_input_map (/opt/a1111/td_inputs/comfy_videos/ -> input/).
    """
    path = _norm(container_path)
    for subfolder, base in cfg["comfy_output_map"].items():
        base = base.rstrip("/") + "/"
        if path.startswith(base):
            rest = path[len(base):]
            sub, _, name = rest.rpartition("/")
            return "output", (subfolder.strip("/") + ("/" + sub if sub else "")), name
    mapped = _map_prefix(path, cfg["comfy_input_map"])
    if mapped is not None and mapped.startswith("input/"):
        sub, _, name = mapped[len("input/"):].rpartition("/")
        return "input", sub, name
    return None


def comfy_view_url(cfg, kind, subfolder, filename):
    from urllib.parse import urlencode
    return comfy_url(cfg, "/view?" + urlencode({"filename": filename, "subfolder": subfolder, "type": kind}))


def fetch_paths(cfg, container_path):
    """(share path, container path) of the downloaded copy of a ComfyUI file."""
    name = _norm(container_path).rsplit("/", 1)[-1]
    container = cfg["comfy_fetch_dir"].rstrip("/") + "/" + name
    return to_share(cfg, container), container


def comfy_output_to_container(cfg, subfolder, filename):
    base = cfg["comfy_output_map"].get(subfolder.strip("/"))
    if base is None:
        return None
    return base.rstrip("/") + "/" + filename
