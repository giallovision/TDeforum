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


# Baselines that changed: a saved value equal to the OLD default is not carried over, so the COMP
# picks up the new baseline. Anything you set to something else is kept.
BASELINE_BUMPS = {
    "seed": ("-1", "424242"),
    "loop_seeds": (True, False),
}


def _is_old_default(field, entry):
    bump = BASELINE_BUMPS.get(field.api)
    if bump is None or entry.get("mode", "CONSTANT") != "CONSTANT":
        return False
    value = entry.get("val")
    if isinstance(bump[0], bool):
        return str(value).strip().lower() in ("1", "1.0", "true", "on") if bump[0] else \
            str(value).strip().lower() in ("0", "0.0", "false", "off", "")
    return str(value).strip() == bump[0]


def plan(saved, from_old_ui):
    """Actions that move ``saved`` onto the new COMP's parameters."""
    actions = []
    for field in schema.FIELDS:
        name = field.td_name
        if field.kind == schema.STATUS or name not in saved:
            continue
        entry = saved[name]
        mode = entry.get("mode", "CONSTANT")

        if _is_old_default(field, entry):
            bump = BASELINE_BUMPS[field.api]
            actions.append(("note", "%s was the old baseline (%s); now %s" % (name, bump[0], bump[1])))
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
