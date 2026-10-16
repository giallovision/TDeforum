# CHOP Execute DAT `bake_exec` (chop: null2 / bake button).
# Bakes wave_generator into Deforum keyframe strings:
#   * a channel named like a schedule (zoom, translation_z, ...) goes straight
#     into that Deforum_UI parameter,
#   * otherwise channel 0 goes to Deforum_UI > Pipeline > "Bake into",
#   * bake_out always gets a copy. Points come from Pipeline > "Bake points"
#     (falls back to the quantize_settings CHOP).


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
