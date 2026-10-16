# Text DAT `preproc_payload_exec` (right-click > Run Script).
# Runs only the ComfyUI preprocess for the current deforum COMP settings and, when
# it finishes, points Cn1vidpath at the result. Queue does this automatically
# when ControlNet Unit 1 > "Preprocess via ComfyUI" is on.
#
# Output naming / caching: <video>_<W>x<H>_<preprocessor>_<frames>f, remembered
# per project in /project1 storage; Pipeline > "Force ComfyUI re-preprocess"
# bypasses the cache.

import os
import sys

_path = me.par.file.eval()
_scripts = os.path.dirname(_path) if _path else 'T:/scripts'
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import tdeforum
tdeforum.reload_all()
from tdeforum import td_controller

td_controller.preprocess_only(me.parent())
