# CHOP Execute DAT `loadvideo_exec` (chop: null3 / LoadVideo button).
# Created by setup_network.py. Loads the newest <timestring>.mp4 Deforum render
# from td_outputs/img2img-images into moviefilein1.


def _ctl():
    import os
    import sys
    path = me.par.file.eval()
    scripts = os.path.dirname(path) if path else 'T:/scripts'
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from tdeforum import td_controller
    return td_controller


def onOffToOn(channel, sampleIndex, val, prev):
    _ctl().load_latest(me.parent())
    return
