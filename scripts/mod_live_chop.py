# Script CHOP callbacks `mod_live_callbacks` (inside the deforum COMP; created and file-synced
# by build_master_ui). `mod_live` outputs, for the current position in the loop (its input is
# `beat_clock`, so it cooks every frame), the value of every parameter the Mod Matrix or the
# Mod CHOP moves -- the same numbers the render uses. Channels are named after the parameters
# (translation_z, zoom, strength_schedule, ...) plus render_frame. Logic: td_controller.mod_live_cook.


def _ctl():
    import os
    import sys
    path = me.par.file.eval()
    scripts = os.path.dirname(path) if path else 'T:/scripts'
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from tdeforum import td_controller
    return td_controller


def onSetupParameters(scriptOp):
    return


def onPulse(par):
    return


def onCook(scriptOp):
    _ctl().mod_live_cook(scriptOp)
    return
