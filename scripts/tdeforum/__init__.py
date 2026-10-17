"""TDeforum pipeline package.

Everything that decides *what* gets sent to Deforum / ComfyUI lives here as
plain Python, so it can be unit-tested outside TouchDesigner (``make test``).

* ``config``        endpoints, path bridge (container <-> T:/ share), tunables
* ``schedules``     keyframe-string helpers (bake, checkpoint schedules)
* ``tempo``         bpm / bars / fps -> render plan (cadence or RIFE/FILM interpolation)
* ``modulation``    beat-locked LFO shapes -> Deforum expressions or baked keyframes
* ``prompt_seq``    beat-indexed prompts -> held keys + weighted AND crossfades
* ``feed``          ControlNet guide feeds recorded from TOPs (capture plan, paths)
* ``sweep``         Sweep Depth: band maths and the background render of the mask video
* ``presets``       example configurations for the deforum COMP (Example Preset drop-down)
* ``prompt_presets`` starting prompts for the Prompt Preset drop-down
* ``page_presets``  the per-page Page Preset drop-downs
* ``schema``        the deforum COMP's parameter list (drives UI *and* payload)
* ``migrate``       old Deforum_UI values -> the COMP's parameters
* ``payload``       builds the Deforum batch request + frame plan
* ``comfy``         builds the ComfyUI preprocess request / reads its history
* ``td_controller`` TouchDesigner glue: Queue -> preprocess -> render -> load

The DAT scripts in ``scripts/`` stay thin: they put ``scripts/`` on sys.path,
import this package and forward their callbacks to ``td_controller``.
"""

import importlib
import sys

__version__ = "0.9.2"

# Leaves first, so dependants pick up reloaded modules.
_SUBMODULES = ("config", "schedules", "tempo", "modulation", "prompt_seq", "feed", "sweep", "presets", "prompt_presets", "page_presets", "schema",
               "migrate", "payload", "comfy", "td_controller")


def reload_all():
    """Re-import every submodule so edits made in VS Code apply without restarting TD."""
    for name in _SUBMODULES:
        full = "%s.%s" % (__name__, name)
        module = sys.modules.get(full)
        if module is None:
            importlib.import_module(full)
        else:
            importlib.reload(module)
