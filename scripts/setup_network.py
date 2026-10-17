# One-time wiring for the tdeforum controller. Idempotent: safe to re-run.
#
# Run it either way:
#   * Text DAT in /project1 with File = T:/scripts/setup_network.py, right-click > Run Script
#   * Textport:  exec(open('T:/scripts/setup_network.py', encoding='utf-8').read())
#
# Every change is printed. Nothing is deleted.
# (cross1's crossfade expression is corrected if it still overshoots: see step 8.)

import os
import sys


def _root():
    try:
        candidate = me.parent()
        if candidate is not None and (candidate.op('deforum') is not None
                                      or candidate.op('Deforum_UI') is not None):
            return candidate
    except Exception:
        pass
    return op('/project1')


ROOT = _root()
_file = ''
try:
    _file = me.par.file.eval()
except Exception:
    pass
SCRIPTS = os.path.dirname(_file) if _file else 'T:/scripts'
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import tdeforum
tdeforum.reload_all()
from tdeforum import config

CFG = config.load()


def say(msg):
    print('[TDeforum setup] ' + msg)


def set_par(o, name, value):
    par = getattr(o.par, name, None)
    if par is None:
        say('%s has no parameter %s (skipped)' % (o.path, name))
        return
    current = par.eval()
    target = value.path if hasattr(value, 'path') else value
    current_cmp = current.path if hasattr(current, 'path') else current
    if par.mode != ParMode.CONSTANT or current_cmp != target:
        par.mode = ParMode.CONSTANT
        par.val = value
        say('%s.%s = %r' % (o.name, name, target))


def main():
    if ROOT is None or (ROOT.op('deforum') is None and ROOT.op('Deforum_UI') is None):
        say('neither the deforum COMP nor Deforum_UI found; run this from /project1')
        return

    # 1. One callbacks DAT (file-synced) for all three Web Client DATs.
    callbacks = ROOT.op('webclient2_callbacks')
    urls = {
        'webclient_deforum': config.deforum_url(CFG, '/deforum_api/batches'),
        'webclient_progress': config.deforum_url(CFG, '/deforum_api/jobs'),
        'webclient_comfyui': config.comfy_url(CFG, '/prompt'),
    }
    for name, url in urls.items():
        dat = ROOT.op(name)
        if dat is None:
            say('%s missing' % name)
            continue
        if callbacks is not None:
            set_par(dat, 'callbacks', callbacks)
        set_par(dat, 'url', url)

    # 2. Prompt DAT pointed at the file the controller reads.
    prompts = ROOT.op('deforum_prompts')
    if prompts is not None:
        set_par(prompts, 'file', SCRIPTS + '/prompt.json')
        set_par(prompts, 'syncfile', True)

    # 3. Script DATs run as Python.
    for name in ('export_deforum_payload', 'preproc_payload_exec'):
        dat = ROOT.op(name)
        if dat is not None:
            set_par(dat, 'language', 'python')

    # 4. Poll on the timer's cycle pulse edge.
    poll = ROOT.op('chopexec_poll')
    if poll is not None:
        set_par(poll, 'offtoon', True)
        set_par(poll, 'whileon', False)

    # 5. moviefilein1 gets an exact path from the controller instead of the
    #    newest-name-in-folder expression (which also matched _depth / interpolated files).
    movie = ROOT.op('moviefilein1')
    if movie is not None and movie.par.file.mode != ParMode.CONSTANT:
        current = movie.par.file.eval()
        movie.par.file.mode = ParMode.CONSTANT
        movie.par.file.val = current
        say('moviefilein1.file -> constant (%s)' % current)

    # 6. folder_monitor.refresh referenced a channel that does not exist
    #    (null3 carries "LoadVideo", the expression asked for "Load_Video").
    folder = ROOT.op('folder_monitor')
    if folder is not None and folder.par.refresh.mode == ParMode.EXPRESSION:
        say('folder_monitor.refresh expression %r removed (LoadVideo now has its own exec DAT)'
            % folder.par.refresh.expr)
        folder.par.refresh.mode = ParMode.CONSTANT

    # 7. LoadVideo button -> loadvideo_exec.
    null3 = ROOT.op('null3')
    loader = ROOT.op('loadvideo_exec')
    if null3 is not None and loader is None:
        loader = ROOT.create(chopexecuteDAT, 'loadvideo_exec')
        loader.nodeX, loader.nodeY = null3.nodeX + 200, null3.nodeY
        say('created loadvideo_exec')
    if loader is not None and null3 is not None:
        set_par(loader, 'chop', null3)
        set_par(loader, 'offtoon', True)
        set_par(loader, 'valuechange', False)
        set_par(loader, 'file', SCRIPTS + '/loadvideo_exec.py')
        set_par(loader, 'syncfile', True)

    # 7b. Frame-End stepper that records ControlNet feeds from TOPs.
    stepper = ROOT.op('feed_capture_exec')
    if stepper is None:
        stepper = ROOT.create(executeDAT, 'feed_capture_exec')
        stepper.nodeX, stepper.nodeY = (loader.nodeX if loader is not None else 0), \
            (loader.nodeY - 150 if loader is not None else -300)
        say('created feed_capture_exec')
    set_par(stepper, 'file', SCRIPTS + '/feed_capture_exec.py')
    set_par(stepper, 'syncfile', True)
    set_par(stepper, 'framestart', False)
    set_par(stepper, 'frameend', True)
    set_par(stepper, 'active', True)

    # 7c. The builder DAT reads its script from the share like the others, so a patched
    #     build_master_ui.py is what runs (a DAT holding stale text rebuilt the old UI once).
    builder = ROOT.op('builder_master_ui')
    if builder is None:
        builder = ROOT.create(textDAT, 'builder_master_ui')
        say('created builder_master_ui')
    set_par(builder, 'file', SCRIPTS + '/build_master_ui.py')
    set_par(builder, 'syncfile', True)

    # 8. Creative chain: fix what is plainly wrong, report the rest.
    comp = ROOT.op('deforum')
    wave = ROOT.op('wave_generator')
    if comp is None:
        say('NOTE no deforum COMP yet: run builder_master_ui (it migrates Deforum_UI)')
    elif wave is not None and wave not in list(comp.inputs):
        say('NOTE wave_generator is not wired into the deforum COMP. The bake button no longer '
            'writes keyframe strings; connect a CHOP whose channels are named after parameters '
            '(translation_z, zoom, strength_schedule, ...) to the COMP input, one loop long. '
            'To make live visuals loop with the render, time them from deforum/beat_clock '
            '(loop_phase, beat_phase, kick) and read the render\'s own curves from deforum/mod_live.')
    record = ROOT.op('record1')
    if record is not None and not record.outputs:
        say('NOTE record1 has no outputs: cross1/crossfade never reach wave_generator. '
            'Wire record1 -> math1 if the crossfade morph is meant to modulate Deforum.')
    cross = ROOT.op('cross1')
    if cross is not None:
        expr = cross.par.cross.expr or ''
        if cross.par.cross.mode == ParMode.EXPRESSION and 'len(me.inputs)' in expr and '- 1' not in expr:
            fixed = expr.replace('len(me.inputs)', '(len(me.inputs) - 1)')
            cross.par.cross.expr = fixed
            say('cross1.cross: %r -> %r (a Cross CHOP blends 0..inputs-1; the old one overshot past '
                'the last input)' % (expr, fixed))

    say('done. Next: run builder_master_ui, then op("deforum_payload_exec").module.doctor()')


main()
