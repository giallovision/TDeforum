# Text DAT `export_deforum_payload` (right-click > Run Script).
# Dry run: builds exactly the payload Queue would send and writes it to
# <share>/runtime/last_deforum_payload.json. Nothing is sent to the server.
# Uses the same builder as Queue, so the two can no longer drift apart.

import os
import sys

_path = me.par.file.eval()
_scripts = os.path.dirname(_path) if _path else 'T:/scripts'
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import tdeforum
tdeforum.reload_all()
from tdeforum import td_controller

td_controller.export_payload(me.parent())
