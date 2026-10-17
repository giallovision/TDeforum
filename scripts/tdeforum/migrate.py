"""Carry parameter values from the old Deforum_UI (or a previous build) into the COMP.

Pure Python so the rules are unit-tested; build_master_ui.py applies the result.

``saved`` is what build_master_ui.snapshot() records per TD parameter name:
    {"mode": "CONSTANT" | "EXPRESSION" | "EXPORT" | "BIND", "expr": str, "bind": str, "val": value}

plan() returns a list of actions:
    ("set", td_name, saved_entry)   restore value / expression / bind as saved
    ("note", text)                  something the user has to redo by hand
"""

from . import schema
from . import schedules


def split_schedule(text):
    """'0:(1.05)' / '1.05' -> (1.05, ''); anything else -> (None, text)."""
    text = str(text).strip()
    if text == "":
        return None, ""
    body = schedules.as_schedule(text)
    if "," not in body and body.count(":") == 1:
        try:
            return float(body.split(":", 1)[1].strip().strip("()").strip()), ""
        except ValueError:
            pass
    return None, text


def _const(value):
    return {"mode": "CONSTANT", "expr": "", "bind": "", "val": value}


# Baselines that changed: api -> (baseline version, old default, new default). A saved value
# equal to the OLD default is not carried over, so the COMP picks up the new baseline; anything
# you set to something else is kept. Each bump applies once: build_master_ui stores the version
# it built with in the COMP, so setting an old value again on purpose survives later rebuilds.
BASELINE_VERSION = 4
BASELINE_BUMPS = {
    "seed": (1, "-1", "424242"),
    "loop_seeds": (1, True, False),
    # 2: LCM checkpoints (4 steps, CFG 1.5-2, little noise) and the fast depth model.
    "steps": (2, 10, 4),
    "cfg_scale_schedule": (2, 7.0, 1.8),
    "noise_schedule": (2, 0.065, 0.02),
    "noise_multiplier_schedule": (2, 1.05, 1.0),
    "sweep_model": (2, "DepthAnythingV2Preprocessor", "depth_anything_v2_vits"),
    # 3: every ControlNet unit's Source TOP defaults to final_out (empty ones pick it up).
    "feed_1_top": (3, "", "/project1/final_out"),
    "feed_2_top": (3, "", "/project1/final_out"),
    "feed_3_top": (3, "", "/project1/final_out"),
    # 4: from the 2026-10-17 pass (docs/passes/): Deforum's current colour match, softer perlin
    # noise, ControlNet guidance 0.2..0.8 so the guide blends instead of stamping.
    "legacy_colormatch": (4, True, False),
    "perlin_w": (4, 8, 4),
    "perlin_h": (4, 8, 4),
    "cn_1_guidance_start": (4, 0.0, 0.2),
    "cn_1_guidance_end": (4, 1.0, 0.8),
    "cn_2_guidance_start": (4, 0.0, 0.2),
    "cn_2_guidance_end": (4, 1.0, 0.8),
    "cn_3_guidance_start": (4, 0.0, 0.2),
    "cn_3_guidance_end": (4, 1.0, 0.8),
}


def _is_old_default(field, entry, since=0):
    bump = BASELINE_BUMPS.get(field.api)
    if bump is None or bump[0] <= since or entry.get("mode", "CONSTANT") != "CONSTANT":
        return False
    old, value = bump[1], entry.get("val")
    if isinstance(old, bool):
        return str(value).strip().lower() in ("1", "1.0", "true", "on") if old else \
            str(value).strip().lower() in ("0", "0.0", "false", "off", "")
    if isinstance(old, (int, float)):
        try:
            return abs(float(value) - float(old)) < 1e-9
        except (TypeError, ValueError):
            return False
    return str(value).strip() == old


def plan(saved, from_old_ui, since=0):
    """Actions that move ``saved`` onto the new COMP's parameters.

    ``since``: the baseline version the COMP was last built with (bumps newer than it apply)."""
    actions = []
    for field in schema.FIELDS:
        name = field.td_name
        if field.kind in (schema.STATUS, schema.PULSE) or name not in saved:
            continue
        entry = saved[name]
        mode = entry.get("mode", "CONSTANT")

        if _is_old_default(field, entry, since):
            bump = BASELINE_BUMPS[field.api]
            actions.append(("note", "%s was the old baseline (%s); now %s" % (name, bump[1], bump[2])))
            continue

        if field.kind == schema.MOD and from_old_ui:
            # Old schedules were string pars; the new base is a float + a raw override.
            if mode == "EXPRESSION" and entry.get("expr"):
                actions.append(("set", field.raw_td_name, entry))
                continue
            if mode == "EXPORT":
                actions.append(("note", "%s was CHOP-exported on Deforum_UI; feed that channel into the "
                                        "deforum COMP's Mod CHOP input as '%s' instead" % (name, field.api)))
                continue
            base, raw = split_schedule(entry.get("val", ""))
            if base is not None:
                actions.append(("set", name, _const(base)))
            elif raw:
                actions.append(("set", field.raw_td_name, _const(raw)))
            continue

        if field.api == "border" and from_old_ui and str(entry.get("val")) == "zeros":
            actions.append(("set", name, _const("replicate")))
            if "Paddingmode" not in saved:
                actions.append(("set", "Paddingmode", _const("zeros")))
            continue

        if mode == "EXPORT" and from_old_ui:
            actions.append(("note", "%s was CHOP-exported on Deforum_UI; re-point the export to the deforum COMP"
                                    % name))
        actions.append(("set", name, entry))

    if not from_old_ui:
        for field in schema.MOD_FIELDS:
            if field.raw_td_name in saved:
                actions.append(("set", field.raw_td_name, saved[field.raw_td_name]))
    return actions


def dropped(saved):
    """Saved names the new COMP has no parameter for."""
    known = set(schema.all_td_names())
    return sorted(n for n in saved if n not in known)
