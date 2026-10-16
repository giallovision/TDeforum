# CHOP Execute DAT `deforum_payload_exec` (chop: null1, channel: Queue).
# Queue -> optional ComfyUI preprocess -> ONE Deforum batch -> auto-load.
# All logic lives in scripts/tdeforum/td_controller.py.
#
# Textport helpers:
#   op('deforum_payload_exec').module.status()
#   op('deforum_payload_exec').module.cancel()
#   op('deforum_payload_exec').module.doctor()


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
    _ctl(reload=True).queue(me.parent())
    return


def status():
    return _ctl().status(me.parent())


def cancel():
    _ctl().cancel(me.parent())


def doctor():
    _ctl(reload=True).doctor(me.parent())
