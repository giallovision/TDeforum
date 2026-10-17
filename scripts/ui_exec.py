# Parameter Execute DAT `ui_exec` (inside the deforum COMP; created and file-synced by
# build_master_ui). Watches the COMP's own buttons:
#   Preset         picking an Example Preset applies it at once (it is also checked at bake / Queue)
#   Presetapply    "Re-apply Preset": lays the selected preset over the COMP again
#   Promptedit     opens deforum/prompt_seq in a floating editor
#   Promptpreset   writes the picked visionary prompt into prompt_seq
#   Sweepshowlatest  points sweep_preview (COMP output 2) at the newest Sweep Depth video
# Logic: tdeforum/td_controller.py.


def _ctl():
    import os
    import sys
    path = me.par.file.eval()
    scripts = os.path.dirname(path) if path else 'T:/scripts'
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from tdeforum import td_controller
    return td_controller


def onValueChange(par, prev):
    if par.name == 'Preset':
        _ctl().apply_preset(par.owner.parent())
    elif par.name == 'Promptpreset':
        _ctl().apply_prompt_preset(par.owner.parent())
    return


def onPulse(par):
    if par.name == 'Presetapply':
        _ctl().apply_preset(par.owner.parent(), force=True)
    elif par.name == 'Promptedit':
        _ctl().open_prompt_seq(par.owner.parent())
    elif par.name == 'Sweepshowlatest':
        _ctl().show_latest_sweep(par.owner.parent())
    return
