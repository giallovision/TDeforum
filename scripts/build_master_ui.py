# Text DAT `builder_master_ui` (right-click > Run Script).
#
# Rebuilds the Deforum_UI custom pages from scripts/tdeforum/schema.py (the
# same list the payload builder reads). Values, expressions, binds and export
# targets you already set are KEPT, matched by parameter name; set
# RESET_TO_DEFAULTS = True to throw them away instead.

import json
import os
import sys

RESET_TO_DEFAULTS = False

_path = me.par.file.eval()
_scripts = os.path.dirname(_path) if _path else 'T:/scripts'
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import tdeforum
tdeforum.reload_all()
from tdeforum import schema


def _mode_name(par):
    return getattr(par.mode, 'name', str(par.mode)).split('.')[-1].upper()


def snapshot(ui):
    saved = {}
    for p in ui.customPars:
        saved[p.name] = {
            'mode': _mode_name(p),
            'expr': p.expr,
            'bind': getattr(p, 'bindExpr', ''),
            'val': p.val,
        }
    return saved


def restore(par, saved):
    mode = saved['mode']
    if mode == 'EXPRESSION' and saved['expr']:
        par.expr = saved['expr']
        par.mode = ParMode.EXPRESSION
        return
    if mode == 'BIND' and saved['bind']:
        par.bindExpr = saved['bind']
        par.mode = ParMode.BIND
        return
    # CONSTANT, or EXPORT (the exporting CHOP re-attaches by name; keep its fallback value)
    value = saved['val']
    if par.isMenu and value not in par.menuNames:
        return
    par.mode = ParMode.CONSTANT
    try:
        par.val = value
    except Exception:
        if par.style == 'Int':
            par.val = int(float(value))
        elif par.style == 'Float':
            par.val = float(value)
        else:
            par.val = str(value)


def create(page, field):
    name, label = field.td_name, field.label
    kind = field.kind
    if kind == schema.MENU:
        p = page.appendMenu(name, label=label)[0]
        p.menuNames = field.menu
        p.menuLabels = field.labels
        p.default = field.default
    elif kind == schema.TOGGLE:
        p = page.appendToggle(name, label=label)[0]
        p.default = bool(field.default)
    elif kind == schema.INT:
        p = page.appendInt(name, label=label)[0]
        p.default = int(field.default)
    elif kind == schema.FLOAT:
        p = page.appendFloat(name, label=label)[0]
        p.default = float(field.default)
    else:  # str, schedule, seed, checkpoint, status
        p = page.appendStr(name, label=label)[0]
        p.default = str(field.default)
    if field.norm and kind in (schema.INT, schema.FLOAT):
        p.normMin, p.normMax = field.norm
    p.val = p.default
    if kind == schema.STATUS:
        p.readOnly = True
    if field.expr:
        p.expr = field.expr
        p.mode = ParMode.EXPRESSION
    return p


def ensure_prompt_dat(root, ui):
    prompt_path = _scripts + '/prompt.json'
    if not os.path.exists(prompt_path):
        default_prompt = {"0": "Biomorphic liquid gold morphing", "120": "Bioluminescent neural network blooming"}
        with open(prompt_path, 'w', encoding='utf-8') as f:
            json.dump(default_prompt, f, indent=4)
    prompt_dat = root.op('deforum_prompts') or root.create(textDAT, 'deforum_prompts')
    prompt_dat.par.file = prompt_path
    prompt_dat.par.syncfile = 1
    prompt_dat.dock = ui
    prompt_dat.viewer = True
    prompt_dat.nodeX = ui.nodeX
    prompt_dat.nodeY = ui.nodeY - 180
    prompt_dat.expose = False


def write_map_table(root, ui):
    table = root.op('deforum_api_map') or root.create(tableDAT, 'deforum_api_map')
    table.clear()
    table.appendRow(['td_name', 'api_name', 'sent_as', 'target'])
    for field in schema.FIELDS:
        table.appendRow([field.td_name, field.api, field.key, field.target or 'td-only'])
    table.dock = ui
    table.viewer = False
    table.expose = False


def run_ui_construction():
    root = me.parent()
    ui = root.op('Deforum_UI') or root.create(baseCOMP, 'Deforum_UI')
    saved = {} if RESET_TO_DEFAULTS else snapshot(ui)

    for page in list(ui.customPages):
        page.destroy()
    pages = {}
    for name in schema.PAGE_ORDER:
        pages[name] = ui.appendCustomPage(name)

    kept = []
    for field in schema.FIELDS:
        p = create(pages[field.page], field)
        if field.td_name in saved and field.kind != schema.STATUS:
            try:
                restore(p, saved[field.td_name])
                kept.append(field.td_name)
            except Exception as exc:
                print('[TDeforum] could not restore %s: %s' % (field.td_name, exc))

    write_map_table(root, ui)
    ensure_prompt_dat(root, ui)

    dropped = sorted(set(saved) - set(schema.BY_TD))
    print('[TDeforum] Deforum_UI rebuilt: %d parameters, %d previous values kept.'
          % (len(schema.FIELDS), len(kept)))
    for name in dropped:
        print('[TDeforum]   dropped %s (%s)' % (name, schema.RETIRED_TD_NAMES.get(name, 'not in schema')))


run_ui_construction()
