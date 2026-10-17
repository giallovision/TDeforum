# Text DAT `builder_master_ui` (right-click > Run Script).
#
# Builds (or rebuilds) the `deforum` Base COMP in this network from
# scripts/tdeforum/schema.py -- the same list the payload builder reads -- and
# replaces the old Deforum_UI:
#
#   * first run: values, expressions and binds are MIGRATED from Deforum_UI
#     (schedules become a float base + a raw override; see tdeforum/migrate.py).
#     Deforum_UI itself is left untouched and is no longer read; delete it later.
#   * later runs: the COMP's own values are KEPT, matched by parameter name.
#     Set RESET_TO_DEFAULTS = True to go back to the schema baselines instead.
#
# Inside the COMP it creates (only when missing, never overwriting your edits):
#   prompt_seq        table DAT  beat | prompt | xfade   (seeded from prompt.json)
#   in_mod            In CHOP    COMP input 1: the Mod CHOP (channels named after parameters)
#   schedule_preview  table DAT  filled by the bake button / td_controller.preview()
#   loop_head/tail -> loop_cross -> out_loop   seamless loop player (COMP output 1)
#   feedN_sel -> feedN_out   per ControlNet unit: Select TOP (source TOP) -> Movie File Out TOP
#                            that records the guide movie at Queue (see README, "ControlNet from a TOP")
#   sweep_preview -> out_sweep   the last Sweep Depth mask video (COMP output 2)
#   in_head/in_tail -> in_cross -> out_input   the init video looped like the render (COMP output 3)
#   beat_clock        Constant CHOP  loop / beat / bar phase of the timeline at the COMP's tempo
#   mod_live          Script CHOP    Mod Matrix (+ Mod CHOP) values at the current loop frame,
#                                    channels named after parameters (drive live visuals with it)
#   ui_exec           Parameter Execute DAT  Example Preset applies when picked; Re-apply Preset
#                                    and Edit prompt_seq buttons
# and removes ops older versions made that are no longer used (sweep_depth, sweep_mask, ...).

import json
import os
import sys

RESET_TO_DEFAULTS = False
COMP_NAME = 'deforum'
OLD_UI = 'Deforum_UI'

_path = me.par.file.eval()
_scripts = os.path.dirname(_path) if _path else 'T:/scripts'
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import importlib
import tdeforum
tdeforum = importlib.reload(tdeforum)      # a cached older __init__ would reload an old module list
tdeforum.reload_all()
from tdeforum import migrate, payload, prompt_seq, schema, td_controller


def say(text):
    print('[TDeforum] ' + text)


def _mode_name(par):
    return getattr(par.mode, 'name', str(par.mode)).split('.')[-1].upper()


def snapshot(comp):
    saved = {}
    for p in comp.customPars:
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


def _help(p, text):
    try:
        p.help = text
    except Exception:
        pass


def create(page, field, section=False):
    name, label = field.td_name, field.ui_label
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
    elif kind in (schema.FLOAT, schema.MOD):
        p = page.appendFloat(name, label=label)[0]
        p.default = float(field.default)
    elif kind == schema.PULSE:
        p = page.appendPulse(name, label=label)[0]
        return [p]
    elif kind == schema.FILE:
        p = page.appendFile(name, label=label)[0]
        p.default = str(field.default)
    else:  # str, schedule, seed, checkpoint, status
        p = page.appendStr(name, label=label)[0]
        p.default = str(field.default)
    if field.norm and kind in (schema.INT, schema.FLOAT, schema.MOD):
        p.normMin, p.normMax = field.norm
    p.val = p.default
    if section:
        try:
            p.startSection = True
        except Exception:
            pass
    if kind == schema.STATUS:
        p.readOnly = True
    if field.expr:
        p.expr = field.expr
        p.mode = ParMode.EXPRESSION
    created = [p]
    if kind == schema.MOD:
        _help(p, 'Base value. Drop a CHOP channel on it (CHOP Reference or Export CHOP) and the whole '
                 'channel is baked into the schedule at Queue (Mod Matrix > CHOP Timing); the Mod Matrix '
                 'and the Mod CHOP add beat-locked motion on top.')
        raw = page.appendStr(field.raw_td_name, label='     raw schedule')[0]
        raw.default = ''
        _help(raw, 'Optional hand-written Deforum schedule, e.g. 0:(1), 30:(1.04). '
                   'When not empty it is sent verbatim and the base + modulation are ignored. '
                   'A CHOP channel dropped here works like one dropped on the base.')
        created.append(raw)
    return created


# --------------------------------------------------------------------------- inner network

def _set_menu(par, *choices):
    """Set a built-in menu par to the first choice it knows; report if none fits."""
    names = list(getattr(par, 'menuNames', []) or [])
    for choice in choices:
        if choice in names:
            par.val = choice
            return True
    say('NOTE %s.%s has no %s (menu: %s); set it by hand' % (par.owner.name, par.name, '/'.join(choices), names))
    return False


def _expr(op_, name, expression):
    par = getattr(op_.par, name, None)
    if par is None:
        say('NOTE %s has no parameter %r; loop player needs it set by hand to: %s' % (op_.name, name, expression))
        return
    par.expr = expression
    par.mode = ParMode.EXPRESSION


def _get(comp, optype, name, x, y):
    found = comp.op(name)
    if found is None:
        found = comp.create(optype, name)
        found.nodeX, found.nodeY = x, y
        say('created %s/%s' % (comp.name, name))
    return found


# Playhead in output frames, wrapped to the loaded loop.
_LOOP = "int(parent().par.Loopoutframes.eval() or 0)"
_RATE = "float(parent().par.Loopoutrate.eval() or 1)"
_P = '((absTime.frame + parent().par.Loopoffset.eval()) %% max(1, %s))' % _LOOP


def _blank(table):
    """New Table DATs may hold one empty cell; treat any all-empty table as empty."""
    for r in range(table.numRows):
        for c in range(table.numCols):
            if str(table[r, c].val).strip():
                return False
    return True


def build_inner(comp, values):
    seq = _get(comp, tableDAT, 'prompt_seq', -400, 200)
    if _blank(seq):
        seq.clear()
        seq.appendRow(['beat', 'prompt', 'xfade'])
        try:
            with open(_scripts + '/prompt.json', 'r', encoding='utf-8') as fh:
                prompts = json.load(fh)
            tp = payload.tempo_plan(values)
            fpb = tp['fpb'] if tp else 30.0
            for row in prompt_seq.rows_from_prompts(prompts, fpb):
                seq.appendRow(list(row))
            say('prompt_seq seeded from prompt.json (frame keys converted to beats; check them)')
        except Exception as exc:
            seq.appendRow(['0', 'A cinematic macro shot of liquid gold morphing, biomorphic shapes', ''])
            say('prompt_seq seeded with a default prompt (%s)' % exc)
    seq.viewer = True

    _get(comp, inCHOP, 'in_mod', -400, 0)
    preview = _get(comp, tableDAT, 'schedule_preview', -400, -200)
    if _blank(preview):
        preview.clear()
        preview.appendRow(['parameter', 'mode', 'schedule'])
    preview.viewer = True

    head = _get(comp, moviefileinTOP, 'loop_head', 0, 100)
    tail = _get(comp, moviefileinTOP, 'loop_tail', 0, -100)
    for player, offset in ((head, ''), (tail, ' + int(%s * %s)' % (_LOOP, _RATE))):
        playmode = getattr(player.par, 'playmode', None)
        if playmode is not None:
            _set_menu(playmode, 'specify', 'specifyindex')
        unit = getattr(player.par, 'indexunit', None)
        if unit is not None:
            _set_menu(unit, 'indices', 'index', 'frames')
        _expr(player, 'index', 'int(%s * %s)%s' % (_P, _RATE, offset))

    for unit in range(1, schema.CN_UI_UNITS + 1):
        y = -300 - 150 * unit
        sel = _get(comp, selectTOP, td_controller.FEED_SELECT % unit, 0, y)
        rec = _get(comp, moviefileoutTOP, td_controller.FEED_OUT % unit, 250, y)
        rec.inputConnectors[0].connect(sel)
        kind = getattr(rec.par, 'type', None)
        if kind is not None:
            _set_menu(kind, 'movie')

    # Sweep Depth: the controller renders the mask video itself; this just shows the result.
    for name in td_controller.OBSOLETE_INNER:
        stale = comp.op(name)
        if stale is not None:
            stale.destroy()
            say('removed %s/%s (Sweep Depth renders its video directly now)' % (comp.name, name))
    preview = _get(comp, moviefileinTOP, td_controller.SWEEP_PREVIEW, -300, -700)
    preview.viewer = True
    out_sweep = _get(comp, outTOP, 'out_sweep', 400, -700)     # COMP output 2 (below out_loop)
    out_sweep.inputConnectors[0].connect(preview)

    build_clock(comp)

    # Buttons: picking a preset applies it, Re-apply, Edit prompt_seq.
    ui_exec = _get(comp, parameterexecuteDAT, 'ui_exec', -400, -600)
    for name, value in (('file', _scripts + '/ui_exec.py'), ('syncfile', 1), ('op', comp.path),
                        ('pars', ' '.join(td_controller.ui_watched())), ('custom', 1), ('builtin', 0),
                        ('valuechange', 1), ('onpulse', 1), ('active', 1)):
        par = getattr(ui_exec.par, name, None)
        if par is None:
            say('NOTE %s has no parameter %r; set it to %r by hand' % (ui_exec.name, name, value))
            continue
        par.val = value

    cross = _get(comp, crossTOP, 'loop_cross', 200, 0)
    cross.inputConnectors[0].connect(head)
    cross.inputConnectors[1].connect(tail)
    _expr(cross, 'cross', _CROSS)
    out = _get(comp, outTOP, 'out_loop', 400, 0)
    out.inputConnectors[0].connect(cross)

    build_input_loop(comp)


# Tail weight 1 -> 0 over the overlap at the start of each loop (smoothstep: no kink at
# either end), 0 afterwards.
_CROSS = ('(lambda p, o: (lambda w: w * w * (3.0 - 2.0 * w))(1.0 - p / o) if 0 < o and p < o else 0.0)'
          '(%s, int(parent().par.Loopoutoverlap.eval() or 0))' % _P)


def _input_index(offset):
    """Init-video frame for the loop playhead: start + stride * render frame (the frame Deforum used)."""
    return ('int(parent().par.Loopinstart.eval() or 0) + int(parent().par.Loopinstride.eval() or 1) * '
            'int((%s%s) * float(parent().par.Loopinrate.eval() or 1))' % (_P, offset))


def build_input_loop(comp):
    """COMP output 3: the init video at render size, looped and seam-crossfaded like the render,
    so render and input line up frame for frame for blending / compositing."""
    head = _get(comp, moviefileinTOP, 'in_head', 0, -950)
    tail = _get(comp, moviefileinTOP, 'in_tail', 0, -1100)
    for player, offset in ((head, ''), (tail, ' + %s' % _LOOP)):
        playmode = getattr(player.par, 'playmode', None)
        if playmode is not None:
            _set_menu(playmode, 'specify', 'specifyindex')
        unit = getattr(player.par, 'indexunit', None)
        if unit is not None:
            _set_menu(unit, 'indices', 'index', 'frames')
        _expr(player, 'index', _input_index(offset))
        res = getattr(player.par, 'outputresolution', None)
        if res is not None:
            _set_menu(res, 'custom')
            _expr(player, 'resolutionw', 'int(parent().par.Width.eval())')
            _expr(player, 'resolutionh', 'int(parent().par.Height.eval())')
        else:
            say('NOTE %s has no outputresolution; set Common > Output Resolution to the render size by hand'
                % player.name)
    cross = _get(comp, crossTOP, 'in_cross', 200, -1000)
    cross.inputConnectors[0].connect(head)
    cross.inputConnectors[1].connect(tail)
    _expr(cross, 'cross', _CROSS)
    out = _get(comp, outTOP, 'out_input', 400, -1000)        # COMP output 3 (below out_sweep)
    out.inputConnectors[0].connect(cross)


# Timeline position inside the loop, the same way the feed recorder and the render count it:
# frame 0 = Pipeline > Feed loop start (or the timeline start), tempo from the Tempo page.
_START = '(parent().par.Feedloopstart.eval() or me.time.start)'
_F = '(me.time.frame - %s)' % _START
_BEATS = '(%s / me.time.rate * parent().par.Bpm.eval() / 60.0)' % _F
_LOOP_BEATS = '(parent().par.Loopbars.eval() * parent().par.Beatsperbar.eval())'
CLOCK = [
    ('loop_frame', '(%s %% (%s * 60.0 / parent().par.Bpm.eval() * me.time.rate))' % (_F, _LOOP_BEATS)),
    ('loop_phase', '((%s / %s) %% 1)' % (_BEATS, _LOOP_BEATS)),
    ('beat', '(%s %% %s)' % (_BEATS, _LOOP_BEATS)),
    ('beat_phase', '(%s %% 1)' % _BEATS),
    ('bar_phase', '((%s / parent().par.Beatsperbar.eval()) %% 1)' % _BEATS),
    ('kick', '(2.718281828459045 ** (-6.0 * (%s %% 1)))' % _BEATS),
]


def _constant_channels(chop, channels):
    """Name + expression per channel on a Constant CHOP (sequential pars or the older nameN)."""
    block = getattr(getattr(chop, 'seq', None), 'const', None)
    if block is not None:
        block.numBlocks = len(channels)
        name_fmt, value_fmt = 'const%dname', 'const%dvalue'
    else:
        name_fmt, value_fmt = 'name%d', 'value%d'
    for i, (name, expression) in enumerate(channels):
        npar = getattr(chop.par, name_fmt % i, None)
        vpar = getattr(chop.par, value_fmt % i, None)
        if npar is None or vpar is None:
            say('NOTE %s has no %s / %s; set channel %s = %s by hand'
                % (chop.name, name_fmt % i, value_fmt % i, name, expression))
            return False
        npar.val = name
        vpar.expr = expression
        vpar.mode = ParMode.EXPRESSION
    return True


def build_clock(comp):
    clock = _get(comp, constantCHOP, 'beat_clock', -400, -400)
    _constant_channels(clock, CLOCK)
    live = _get(comp, scriptCHOP, 'mod_live', -200, -400)
    live.inputConnectors[0].connect(clock)          # cooks whenever the clock moves
    callbacks = _get(comp, textDAT, 'mod_live_callbacks', -200, -550)
    callbacks.par.file.val = _scripts + '/mod_live_chop.py'
    callbacks.par.syncfile.val = 1
    if getattr(live.par, 'callbacks', None) is not None:
        live.par.callbacks.val = callbacks
    else:
        say('NOTE %s has no callbacks parameter; point it at mod_live_callbacks by hand' % live.name)


# --------------------------------------------------------------------------- side tables

def ensure_prompt_dat(root, comp):
    prompt_path = _scripts + '/prompt.json'
    if not os.path.exists(prompt_path):
        default_prompt = {"0": "Biomorphic liquid gold morphing", "120": "Bioluminescent neural network blooming"}
        with open(prompt_path, 'w', encoding='utf-8') as f:
            json.dump(default_prompt, f, indent=4)
    prompt_dat = root.op('deforum_prompts') or root.create(textDAT, 'deforum_prompts')
    prompt_dat.par.file = prompt_path
    prompt_dat.par.syncfile = 1
    prompt_dat.dock = comp
    prompt_dat.viewer = True
    prompt_dat.expose = False


def write_map_table(root, comp):
    table = root.op('deforum_api_map') or root.create(tableDAT, 'deforum_api_map')
    table.clear()
    table.appendRow(['td_name', 'api_name', 'sent_as', 'target', 'page'])
    for field in schema.FIELDS:
        table.appendRow([field.td_name, field.api, field.key, field.target or 'td-only', field.page])
        if field.kind == schema.MOD:
            table.appendRow([field.raw_td_name, field.api + ' (raw)', field.key, 'deforum', field.page])
    table.dock = comp
    table.viewer = False
    table.expose = False


# --------------------------------------------------------------------------- main

def run():
    root = me.parent()
    comp = root.op(COMP_NAME)
    old = root.op(OLD_UI)
    first = comp is None
    if first:
        comp = root.create(baseCOMP, COMP_NAME)
        if old is not None:
            comp.nodeX, comp.nodeY = old.nodeX + 250, old.nodeY
        say('created %s' % comp.path)

    if RESET_TO_DEFAULTS:
        saved, from_old = {}, False
    elif first and old is not None:
        saved, from_old = snapshot(old), True
    else:
        saved, from_old = snapshot(comp), False

    for page in list(comp.customPages):
        page.destroy()
    pages = dict((name, comp.appendCustomPage(name)) for name in schema.PAGE_ORDER)

    by_name = {}
    for field in schema.FIELDS:
        section = field.api.endswith('_active') and field.api.startswith('mod')
        for p in create(pages[field.page], field, section):
            by_name[p.name] = p

    kept, notes = [], []
    since = 0 if first else int(comp.fetch('tdeforum_baseline', 0, search=False) or 0)
    for action in migrate.plan(saved, from_old, since):
        if action[0] == 'note':
            notes.append(action[1])
            continue
        _kind, name, entry = action
        par = by_name.get(name)
        if par is None:
            continue
        try:
            restore(par, entry)
            kept.append(name)
        except Exception as exc:
            say('could not restore %s: %s' % (name, exc))

    comp.store('tdeforum_baseline', migrate.BASELINE_VERSION)
    values = td_controller.read_ui(comp)
    build_inner(comp, values)
    write_map_table(root, comp)
    ensure_prompt_dat(root, comp)
    preview = comp.op(td_controller.SWEEP_PREVIEW)
    if preview is not None and not str(preview.par.file.eval() or '').strip():
        try:
            found = td_controller.show_latest_sweep(root, quiet=True)
            if found:
                say('sweep_preview: %s' % found)
        except Exception as exc:
            say('sweep_preview not set: %s' % exc)

    total = len(schema.all_td_names())
    say('%s %s: %d parameters on %d pages, %d values %s.' % (
        'built' if first else 'rebuilt', comp.path, total, len(schema.PAGE_ORDER), len(kept),
        'migrated from ' + OLD_UI if from_old else 'kept'))
    for name in migrate.dropped(saved):
        say('  dropped %s (%s)' % (name, schema.RETIRED_TD_NAMES.get(name, 'not in schema')))
    for note in notes:
        say('NOTE ' + note)
    menu = getattr(comp.par, 'Preset', None)
    say('driveable (labels start with "%s", %d): drag a CHOP channel onto one (CHOP Reference / Export CHOP); '
        'it then shows%s and the whole channel is baked at Queue' % (schema.MOD_MARK.strip(), len(schema.MOD_FIELDS), schema.LINK_MARK))
    say('presets: %d examples in the Example Preset menu (Tempo page), pages: %s' % (
        len(getattr(menu, 'menuNames', []) or []) - 1 if menu is not None else 0,
        ', '.join(schema.PAGE_ORDER[-len(schema.PAGE_CNS) - 2:-len(schema.PAGE_CNS)])))
    try:
        tp = payload.tempo_plan(values)
        say('tempo: ' + (tdeforum.tempo.describe(tp) if tp else 'manual length'))
    except ValueError as exc:
        say('tempo settings invalid: %s' % exc)
    if first and old is not None:
        say('%s is no longer read. Delete it once the COMP looks right.' % OLD_UI)
    say('next: wire your loop CHOP into %s input 1 (channel names = parameter names, e.g. translation_z), '
        'edit %s/prompt_seq, then press bake to preview the schedules.' % (comp.name, comp.name))


run()
