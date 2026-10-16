# Execute DAT `feed_capture_exec` (Frame End on; created and file-synced by setup_network).
# While a ControlNet feed is being recorded (Queue with Guide Source = "TOP: record the
# loop") this steps the project timeline one planned frame at a time and pulses the
# Movie File Out TOPs inside the deforum COMP. Idle = one cheap storage lookup per frame.
# All logic lives in scripts/tdeforum/td_controller.py (capture_tick).


def _ctl():
    import os
    import sys
    path = me.par.file.eval()
    scripts = os.path.dirname(path) if path else 'T:/scripts'
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from tdeforum import td_controller
    return td_controller


def onFrameEnd(frame):
    _ctl().capture_tick(me.parent())
    return
