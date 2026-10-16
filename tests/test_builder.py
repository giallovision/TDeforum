"""Run scripts/build_master_ui.py against a mock of the TouchDesigner API it uses.

This checks the builder's own logic (pages, migration from Deforum_UI, rebuild
keeping values, inner network, loop-player wiring) and that the controller can
read the result. It cannot check TouchDesigner's own parameter names; the build
log prints a NOTE for any built-in parameter it could not find.
"""

import enum
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from _fakes import ROOT_DIR
from tdeforum import config, payload, td_controller as ctl

BUILDER = os.path.join(ROOT_DIR, "scripts", "build_master_ui.py")


class ParMode(enum.Enum):
    CONSTANT = 0
    EXPRESSION = 1
    EXPORT = 2
    BIND = 3


class Par(object):
    def __init__(self, owner, name, style="Str", val=""):
        self.owner, self.name, self.style = owner, name, style
        self.val, self.default, self.expr, self.bindExpr = val, val, "", ""
        self.mode = ParMode.CONSTANT
        self.menuNames, self.menuLabels = [], []
        self.normMin = self.normMax = None
        self.readOnly = self.startSection = False
        self.help = ""

    @property
    def isMenu(self):
        return self.style == "Menu"

    def eval(self):
        return self.val

    def pulse(self):
        pass


class Pars(object):
    pass


class Page(object):
    def __init__(self, comp, name):
        self.comp, self.name = comp, name

    def _add(self, name, style, val):
        p = Par(self.comp, name, style, val)
        setattr(self.comp.par, name, p)
        self.comp.customPars.append(p)
        return [p]

    def appendFloat(self, name, label=""):
        return self._add(name, "Float", 0.0)

    def appendInt(self, name, label=""):
        return self._add(name, "Int", 0)

    def appendStr(self, name, label=""):
        return self._add(name, "Str", "")

    def appendToggle(self, name, label=""):
        return self._add(name, "Toggle", False)

    def appendMenu(self, name, label=""):
        return self._add(name, "Menu", "")

    def destroy(self):
        self.comp.customPages.remove(self)
        for p in [p for p in self.comp.customPars]:
            delattr(self.comp.par, p.name)
        self.comp.customPars[:] = []


class Connector(object):
    def __init__(self):
        self.source = None

    def connect(self, other):
        self.source = other


class Node(object):
    def __init__(self, kind, name, parent=None, builtins=()):
        self.kind, self.name, self.parent_ = kind, name, parent
        self.path = (parent.path if parent else "") + "/" + name
        self.par = Pars()
        self.customPars, self.customPages, self.children = [], [], {}
        self.rows = []
        self.inputConnectors = [Connector(), Connector()]
        self.inputs = []
        self.outputs = []
        self.channels = []
        self.numChans = 0
        self.nodeX = self.nodeY = 0
        self.viewer = self.expose = False
        self.dock = None
        self.storage = {}
        for bname, style, val, menu in builtins:
            p = Par(self, bname, style, val)
            p.menuNames = list(menu)
            setattr(self.par, bname, p)

    def parent(self):
        return self.parent_

    def op(self, name):
        return self.children.get(name)

    def create(self, kind, name):
        builtins = BUILTINS.get(kind, ())
        node = Node(kind, name, self, builtins)
        if kind == "tableDAT":
            node.rows = [[""]]          # TD's new Table DAT: one empty cell
        self.children[name] = node
        return node

    def appendCustomPage(self, name):
        page = Page(self, name)
        self.customPages.append(page)
        return page

    # table
    @property
    def numRows(self):
        return len(self.rows)

    @property
    def numCols(self):
        return max((len(r) for r in self.rows), default=0)

    def appendRow(self, row):
        self.rows.append([str(c) for c in row])

    def clear(self):
        self.rows = []

    def __getitem__(self, rc):
        return type("Cell", (), {"val": self.rows[rc[0]][rc[1]]})()

    def fetch(self, key, default=None, search=True):
        return self.storage.get(key, default)

    def store(self, key, value):
        self.storage[key] = value


BUILTINS = {
    "moviefileinTOP": [("file", "Str", "", ()), ("index", "Float", 0, ()),
                       ("playmode", "Menu", "locked", ("locked", "specify", "sequential")),
                       ("indexunit", "Menu", "frames", ("indices", "frames", "seconds", "fraction")),
                       ("reloadpulse", "Pulse", 0, ())],
    "crossTOP": [("cross", "Float", 0, ())],
    "textDAT": [("file", "Str", "", ()), ("syncfile", "Toggle", False, ())],
}


def run_builder(root, scripts_dir, out):
    me = Node("textDAT", "builder_master_ui", root, BUILTINS["textDAT"])
    me.par.file.val = scripts_dir + "/build_master_ui.py"
    env = {"me": me, "ParMode": ParMode, "print": lambda *a: out.append(" ".join(str(x) for x in a))}
    for kind in ("baseCOMP", "tableDAT", "textDAT", "inCHOP", "moviefileinTOP", "crossTOP", "outTOP"):
        env[kind] = kind
    with mock.patch.object(ctl, "_constant_mode", lambda par: ParMode.CONSTANT):
        with open(BUILDER, encoding="utf-8") as fh:
            code = fh.read()
        exec(compile(code, BUILDER, "exec"), env)


def old_ui(root):
    """A Deforum_UI as the previous build_master_ui left it (string schedules)."""
    ui = root.create("baseCOMP", "Deforum_UI")
    page = ui.appendCustomPage("Motion (2D/3D)")
    for name, val in (("Zoom", "0:(1.05)"), ("Translationz", "0:(0), 299:(6)"), ("Border", "zeros"),
                      ("Strengthschedule", "0: (0.5)"), ("Cfgscalescheduleval", "x"),
                      ("Cfgscaleschedule", "0: (2.0)"), ("Diffusioncadence", 4),
                      ("Sampler", "LCM"), ("Baketarget", "translation_z")):
        page.appendStr(name)[0].val = val
    rot = page.appendStr("Rotation3dy")[0]
    rot.val, rot.mode = "0:(0)", ParMode.EXPORT
    return ui


class BuilderTest(unittest.TestCase):
    def setUp(self):
        self.share = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.share)
        self.scripts = self.share + "/scripts"
        os.makedirs(self.scripts)
        with open(self.scripts + "/prompt.json", "w") as fh:
            json.dump({"0": "gold", "60": "ice"}, fh)
        self.root = Node("baseCOMP", "project1")
        self.log = []

    def build(self):
        run_builder(self.root, self.scripts, self.log)
        return self.root.op("deforum")

    def test_first_build_migrates_old_ui(self):
        old_ui(self.root)
        comp = self.build()
        self.assertEqual([p.name for p in comp.customPages][:3], ["Tempo", "Globals", "Prompts"])
        self.assertEqual(comp.par.Zoom.val, 1.05)
        self.assertEqual(comp.par.Zoomraw.val, "")
        self.assertEqual(comp.par.Translationzraw.val, "0:(0), 299:(6)")
        self.assertEqual(comp.par.Strengthschedule.val, 0.5)
        self.assertEqual(comp.par.Cfgscaleschedule.val, 2.0)
        self.assertEqual((comp.par.Border.val, comp.par.Paddingmode.val), ("replicate", "zeros"))
        self.assertEqual(comp.par.Diffusioncadence.val, 4)
        self.assertEqual(comp.par.Pipelinestatus.readOnly, True)
        text = "\n".join(self.log)
        self.assertIn("migrated from Deforum_UI", text)
        self.assertIn("Rotation3dy was CHOP-exported", text)
        self.assertIn("dropped Baketarget", text)

    def test_inner_network_and_loop_player(self):
        comp = self.build()
        seq = comp.op("prompt_seq")
        self.assertEqual(seq.rows[0], ["beat", "prompt", "xfade"])
        self.assertEqual(len(seq.rows), 3)                       # seeded from prompt.json
        head, tail, cross = comp.op("loop_head"), comp.op("loop_tail"), comp.op("loop_cross")
        self.assertEqual((head.par.playmode.val, head.par.indexunit.val), ("specify", "indices"))
        self.assertEqual(head.par.index.mode, ParMode.EXPRESSION)
        self.assertIn("Loopoutrate", tail.par.index.expr)
        self.assertEqual(cross.par.cross.mode, ParMode.EXPRESSION)
        self.assertIs(cross.inputConnectors[0].source, head)
        self.assertIs(cross.inputConnectors[1].source, tail)
        self.assertIs(comp.op("out_loop").inputConnectors[0].source, cross)
        self.assertIsNotNone(comp.op("in_mod"))
        self.assertFalse(any("NOTE loop_" in line for line in self.log))

    def test_rebuild_keeps_values_and_tables(self):
        comp = self.build()
        comp.par.Bpm.val = 150.0
        comp.par.Mod1active.val = True
        comp.par.Angleraw.val = "0:(0), 24:(5)"
        comp.op("prompt_seq").appendRow(["8", "fire", "2"])
        comp = self.build()
        self.assertEqual(comp.par.Bpm.val, 150.0)
        self.assertIs(comp.par.Mod1active.val, True)
        self.assertEqual(comp.par.Angleraw.val, "0:(0), 24:(5)")
        self.assertEqual(comp.op("prompt_seq").rows[-1], ["8", "fire", "2"])
        self.assertIn("values kept", "\n".join(self.log))

    def test_controller_reads_the_built_comp(self):
        comp = self.build()
        comp.par.Mod1active.val = True
        comp.par.Mod1depth.val = 0.5
        values = ctl.read_ui(comp)
        self.assertEqual(values[payload.raw_key("zoom")], "")
        result = payload.build_request(values, {"0": "x"}, {}, prompt_rows=ctl.read_prompt_rows(comp),
                                       chop=ctl.read_mod_chop(comp, values))
        s = result["request"]["deforum_settings"]
        self.assertEqual((s["fps"], s["max_frames"]), (60, 270))
        self.assertIn("sin(", s["zoom"])                         # slot 1 default target = zoom
        self.assertEqual(s["prompts"]["0"], "gold")


if __name__ == "__main__":
    unittest.main()
