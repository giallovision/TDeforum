"""Snapshots of the deforum COMP: every parameter (value, expression, bind), prompt_seq and
the preset bookkeeping, saved as JSON on the share and loaded back with one pulse.

Pipeline page:
    Take Snapshot   writes <share>/snapshots/<name or timestamp>.json and puts its path in
                    Snapshot File, ready to load later
    Snapshot File   a snapshot to load (a full path, or just a name from the snapshots folder)
    Load Snapshot   puts every saved parameter back

Read-only parameters (status lines), buttons and the snapshot fields themselves are not
saved. Expressions and binds come back as expressions and binds (so a CHOP Reference link
is restored too); an Export CHOP re-attaches by itself and its parameter is left alone.
"""

import json
import os
import re
import time

from . import schema

VERSION = 1
FOLDER = "snapshots"
SKIP_KINDS = (schema.STATUS, schema.PULSE)
SKIP_APIS = ("snapshot_name", "snapshot_path")


def folder(cfg):
    return (cfg.get("snapshot_dir") or (cfg["share_root"].rstrip("/") + "/" + FOLDER)).rstrip("/")


def safe_name(text):
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "").strip()).strip("._")
    return text[:80]


def new_path(cfg, name="", now=None):
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
    base = safe_name(name)
    return "%s/%s.json" % (folder(cfg), ("%s_%s" % (base, stamp)) if base else "snapshot_" + stamp)


def resolve(cfg, text):
    """Snapshot File -> a path: full paths as given, bare names from the snapshots folder."""
    text = str(text or "").strip().strip('"')
    if not text:
        return None
    if "/" in text.replace("\\", "/") or re.match(r"^[A-Za-z]:", text):
        return text.replace("\\", "/")
    return "%s/%s%s" % (folder(cfg), text, "" if text.lower().endswith(".json") else ".json")


def par_names():
    """TD names a snapshot covers, in schema order."""
    names = []
    for field in schema.FIELDS:
        if field.kind in SKIP_KINDS or field.api in SKIP_APIS:
            continue
        names.append(field.td_name)
        if field.kind == schema.MOD:
            names.append(field.raw_td_name)
    return names


def mode_name(par):
    return getattr(getattr(par, "mode", None), "name", str(getattr(par, "mode", ""))).split(".")[-1].upper()


def capture_par(par):
    entry = {"mode": mode_name(par) or "CONSTANT", "val": par.val}
    expr = str(getattr(par, "expr", "") or "")
    bind = str(getattr(par, "bindExpr", "") or "")
    if entry["mode"] == "EXPRESSION" and expr:
        entry["expr"] = expr
    if entry["mode"] == "BIND" and bind:
        entry["bind"] = bind
    if not isinstance(entry["val"], (str, int, float, bool)) and entry["val"] is not None:
        entry["val"] = str(entry["val"])
    return entry


def build(pars, prompt_rows, presets, name="", version="", now=None):
    """The snapshot dict. pars {TD name: par}, presets {storage key: stored value}."""
    return {
        "tdeforum_snapshot": VERSION,
        "tdeforum": version,
        "name": name,
        "taken": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "pars": dict((n, capture_par(p)) for n, p in pars.items()),
        "prompt_seq": [list(map(str, r)) for r in (prompt_rows or [])],
        "presets": presets or {},
    }


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.replace(path + ".tmp", path)
    return path


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "pars" not in data:
        raise ValueError("%s is not a deforum snapshot" % path)
    return data
