# CHOP Execute DAT `bake_exec` (chop: null2 / bake button).
# Preview: compiles everything Queue would send (tempo plan, Mod Matrix, Mod CHOP
# bake, prompt sequence) WITHOUT sending it, fills deforum/schedule_preview and
# prints the moving schedules and any warnings. The actual CHOP bake happens at
# Queue time from the deforum COMP's Mod CHOP input.


def _ctl(reload=False):
    import os
    import sys
    path = me.par.file.eval()
    scripts = os.path.dirname(path) if path else 'T:/scripts'
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import tdeforum
    if reload:
        tdeforum.reload_all()
    from tdeforum import td_controller
    return td_controller


def onOffToOn(channel, sampleIndex, val, prev):
    _ctl(reload=True).bake(me.parent())
    return
