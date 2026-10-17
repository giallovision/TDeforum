# Script TOP callbacks `sweep_callbacks` (inside the deforum COMP; created and file-synced by
# build_master_ui). The Script TOP `sweep_mask` takes the depth video (`sweep_depth`, white =
# near) and keeps only the grey band that td_controller stored for the frame being recorded;
# the rest goes black. The maths is tdeforum/sweep.py.


def _sweep():
    import os
    import sys
    path = me.par.file.eval()
    scripts = os.path.dirname(path) if path else 'T:/scripts'
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from tdeforum import sweep
    return sweep


def onSetupParameters(scriptOp):
    return


def onPulse(par):
    return


def onCook(scriptOp):
    _sweep().cook(scriptOp)
    return
