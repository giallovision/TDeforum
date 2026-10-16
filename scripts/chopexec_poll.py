# CHOP Execute DAT `chopexec_poll` (chop: timer1, channel: cycles_pulse).
# Each timer cycle polls only what the pipeline is waiting on (ComfyUI history,
# one Deforum job, or the finished file). Idle = no requests at all.
# tick() debounces itself, so it is safe with Off-to-On and/or While-On enabled.


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
    _ctl().tick(me.parent())
    return


def whileOn(channel, sampleIndex, val, prev):
    _ctl().tick(me.parent())
    return
