# Parameter Execute DAT `ui_exec` (inside the deforum COMP; created and file-synced by
# build_master_ui). Watches the COMP's menus and buttons (list: td_controller.ui_watched()):
#   Preset           the Example Preset applies when picked (also checked at bake / Queue)
#   Presetapply      "Re-apply Preset"
#   Pagepreset*      each page's Page Preset
#   Promptpreset     writes the picked visionary prompt into prompt_seq
#   Promptedit       opens deforum/prompt_seq in a floating editor
#   Sweepshowlatest  points sweep_preview (COMP output 2) at the newest Sweep Depth video
# Logic: tdeforum/td_controller.py (on_ui_value / on_ui_pulse).


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
    _ctl().on_ui_value(par.owner.parent(), par.name)
    return


def onPulse(par):
    _ctl().on_ui_pulse(par.owner.parent(), par.name)
    return
