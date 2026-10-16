"""Minimal stand-ins for the TouchDesigner objects td_controller touches."""

import enum
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT_DIR, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


class ParMode(enum.Enum):
    CONSTANT = 0
    EXPRESSION = 1
    EXPORT = 2
    BIND = 3


class Par(object):
    def __init__(self, name, val, mode=ParMode.CONSTANT, expr=""):
        self.name, self.val, self.mode, self.expr = name, val, mode, expr
        self.pulses = 0

    def eval(self):
        return self.val

    def pulse(self):
        self.pulses += 1


class Pars(object):
    def __init__(self, **values):
        for name, val in values.items():
            setattr(self, name, val if isinstance(val, Par) else Par(name, val))


class Cell(object):
    def __init__(self, val):
        self.val = val


class Channel(object):
    def __init__(self, name, vals):
        self.name, self.vals = name, list(vals)


class Op(object):
    def __init__(self, name, parent=None, **pars):
        self.name = name
        self.path = (parent.path if parent else "") + "/" + name
        self.par = Pars(**pars)
        self.storage = {}
        self.children = {}
        self.requests = []
        self.text = ""
        self.rows = []
        self.channels = []
        self.outputs = []

    # COMP
    def op(self, name):
        return self.children.get(name)

    def add(self, child):
        self.children[child.name] = child
        return child

    def fetch(self, key, default=None, search=True):
        return self.storage.get(key, default)

    def store(self, key, value):
        self.storage[key] = value

    # Web Client DAT
    def request(self, url, method, header=None, data=None):
        self.requests.append((method, url, data))

    # Table DAT
    @property
    def numRows(self):
        return len(self.rows)

    @property
    def numCols(self):
        return max((len(r) for r in self.rows), default=0)

    def clear(self):
        self.rows = []

    def appendRow(self, row):
        self.rows.append(list(row))

    def __getitem__(self, index):
        if isinstance(index, tuple):
            return Cell(self.rows[index[0]][index[1]])
        return self.channels[index]

    # CHOP
    @property
    def numChans(self):
        return len(self.channels)

    def chans(self):
        return list(self.channels)


def make_network(ui_values, comp=False, prompt_rows=None, chop=None):
    """A /project1 with the ops td_controller uses.

    comp=False builds the old Deforum_UI; comp=True the new 'deforum' COMP with its
    inner prompt_seq / in_mod / schedule_preview / loop_head / loop_tail ops.
    MOD overrides go in ui_values as "<api>:raw".
    """
    from tdeforum import schema

    root = Op("project1")
    ui_pars = {}
    for field in schema.FIELDS:
        if field.api in ui_values:
            ui_pars[field.td_name] = ui_values[field.api]
        if field.kind == schema.MOD and comp:
            ui_pars[field.raw_td_name] = ui_values.get(field.api + ":raw", "")
    if comp:
        for name in ("Pipelinestatus", "Tempoinfo", "Loopoutframes", "Loopoutoverlap", "Loopoutrate"):
            ui_pars.setdefault(name, "")
    ui = root.add(Op("deforum" if comp else "Deforum_UI", root, **ui_pars))
    if comp:
        seq = ui.add(Op("prompt_seq", ui))
        seq.rows = [["beat", "prompt", "xfade"]] + [list(r) for r in (prompt_rows or [])]
        mod = ui.add(Op("in_mod", ui))
        mod.channels = [Channel(n, v) for n, v in (chop or {}).items()]
        ui.add(Op("schedule_preview", ui))
        for name in ("loop_head", "loop_tail"):
            ui.add(Op(name, ui, file=Par("file", ""), reloadpulse=0))
    for name in ("webclient_deforum", "webclient_progress", "webclient_comfyui"):
        root.add(Op(name, root, callbacks=None))
    root.add(Op("deforum_prompts", root))
    models = root.add(Op("available_models", root))
    models.rows = [["0", "angraRealflexLCMV6_v10.safetensors"], ["1", "comiccraftLCM_beta4.safetensors"]]
    root.add(Op("moviefilein1", root, file=Par("file", "old.mp4", ParMode.EXPRESSION), reloadpulse=0))
    root.add(Op("folder_monitor", root, refresh=0))
    root.add(Op("bake_out", root))
    root.add(Op("wave_generator", root))
    return root
