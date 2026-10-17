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

    def appendPulse(self, name, label=""):
        return self._add(name, "Pulse", 0)

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

    def destroy(self):
        self.parent_.children.pop(self.name, None)
        self.destroyed = True

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
    "selectTOP": [("top", "Str", "", ())],
    "scriptCHOP": [("callbacks", "Str", "", ())],
    "parameterexecuteDAT": [(n, "Str", "", ()) for n in ("file", "syncfile", "op", "pars", "custom", "builtin",
                                                         "valuechange", "onpulse", "active")],
    "constantCHOP": [(n % i, "Str" if n.startswith("name") else "Float", "" if n.startswith("name") else 0.0, ())
                     for i in range(10) for n in ("name%d", "value%d")],
    "moviefileoutTOP": [("file", "Str", "", ()), ("type", "Menu", "movie", ("movie", "image")),
                        ("record", "Toggle", False, ()), ("pause", "Toggle", False, ()),
                        ("addframe", "Pulse", 0, ())],
    "textDAT": [("file", "Str", "", ()), ("syncfile", "Toggle", False, ())],
}


def run_builder(root, scripts_dir, out):
    me = Node("textDAT", "builder_master_ui", root, BUILTINS["textDAT"])
    me.par.file.val = scripts_dir + "/build_master_ui.py"
    env = {"me": me, "ParMode": ParMode, "print": lambda *a: out.append(" ".join(str(x) for x in a))}
    for kind in ("baseCOMP", "tableDAT", "textDAT", "inCHOP", "moviefileinTOP", "crossTOP", "outTOP",
                 "selectTOP", "moviefileoutTOP", "scriptCHOP", "constantCHOP", "parameterexecuteDAT"):
        env[kind] = kind
    with mock.patch.object(ctl, "_constant_mode", lambda par: ParMode.CONSTANT):
        with open(BUILDER, encoding="utf-8") as fh:
            code = fh.read()
        exec(compile(code, BUILDER, "exec"), env)
    return env


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

    def test_feed_ops_per_unit(self):
        comp = self.build()
        for unit in (1, 2, 3):
            sel, rec = comp.op("feed%d_sel" % unit), comp.op("feed%d_out" % unit)
            self.assertIsNotNone(sel)
            self.assertIs(rec.inputConnectors[0].source, sel)
            self.assertEqual(rec.par.type.val, "movie")
            self.assertEqual(getattr(comp.par, "Feed%dmode" % unit).val, "file")
            self.assertTrue(hasattr(comp.par, "Cn%dvidpath" % unit))
        self.assertFalse(any("NOTE feed" in line for line in self.log))
        self.assertEqual(comp.par.Feedloopstart.val, 0)

    def test_preset_menu_and_report(self):
        from tdeforum import presets
        comp = self.build()
        self.assertEqual(list(comp.par.Preset.menuNames), presets.NAMES)
        self.assertEqual(len(presets.NAMES), 32)
        self.assertTrue(any("presets: 31 examples" in line for line in self.log), self.log[-6:])

    def test_sweep_preview_and_old_live_sweep_ops_removed(self):
        comp = self.build()
        for name in ("sweep_depth", "sweep_mask", "sweep_callbacks"):     # what 0011 built
            comp.create("textDAT", name)
        comp = self.build()
        self.assertIsNotNone(comp.op("sweep_preview"))
        for name in ("sweep_depth", "sweep_mask", "sweep_callbacks"):
            self.assertIsNone(comp.op(name), name)
        self.assertTrue(any("removed deforum/sweep_mask" in line for line in self.log))
        for name in ("Sweepenabled", "Sweepmode", "Sweeptrail", "Sweepsmooth", "Sweepinfo"):
            self.assertTrue(hasattr(comp.par, name), name)
        self.assertIn("Sweep Depth", [p.name for p in comp.customPages])

    def test_sweep_preview_is_comp_output_two_and_shows_the_newest_sweep(self):
        folder = os.path.join(self.share, "td_masks", "feeds")
        os.makedirs(folder, exist_ok=True)
        for i, name in enumerate(("cn_sweep_old.mp4", "cn_sweep_new.mp4", "cn_sweep_x.tmp.mp4")):
            path = os.path.join(folder, name)
            open(path, "wb").close()
            os.utime(path, (1000 + i, 1000 + i))
        os.utime(os.path.join(folder, "cn_sweep_x.tmp.mp4"), (5000, 5000))
        comp = self.build()
        preview = comp.op("sweep_preview")
        self.assertIs(comp.op("out_sweep").inputConnectors[0].source, preview)
        self.assertTrue(preview.viewer)
        cfg = config.load()
        cfg.update(share_root=self.share + "/")
        ctl.show_latest_sweep(self.root, cfg)
        self.assertTrue(preview.par.file.val.endswith("cn_sweep_new.mp4"), preview.par.file.val)

    def test_beat_clock_and_mod_live(self):
        comp = self.build()
        clock, live = comp.op("beat_clock"), comp.op("mod_live")
        names = [getattr(clock.par, "name%d" % i).val for i in range(6)]
        self.assertEqual(names, ["loop_frame", "loop_phase", "beat", "beat_phase", "bar_phase", "kick"])
        for i in range(6):
            value = getattr(clock.par, "value%d" % i)
            self.assertEqual(value.mode, ParMode.EXPRESSION)
            self.assertIn("me.time.frame", value.expr)
            self.assertIn("parent().par.Bpm", value.expr)
        self.assertIs(live.inputConnectors[0].source, clock)
        cb = comp.op("mod_live_callbacks")
        self.assertTrue(cb.par.file.val.endswith("mod_live_chop.py"))
        self.assertIs(live.par.callbacks.val, cb)
        self.assertFalse(any("NOTE beat_clock" in line or "NOTE mod_live" in line for line in self.log))

    def test_clock_expressions_count_like_the_feed_recorder(self):
        env = run_builder(self.root, self.scripts, self.log)

        def value(par_val):
            return type("P", (), {"eval": lambda self: par_val})()

        comp = type("C", (), {})()
        comp.par = type("Pars", (), {"Feedloopstart": value(0), "Bpm": value(120.0),
                                     "Beatsperbar": value(4), "Loopbars": value(2)})()
        # 120 bpm at 60 fps = 30 frames a beat; timeline starts at 1 (= render frame 0)
        me = type("Me", (), {})()
        me.time = type("Time", (), {"frame": 1 + 30 * 9 + 15, "start": 1, "rate": 60.0})()
        ch = dict((name, eval(expr, {"me": me, "parent": lambda: comp})) for name, expr in env["CLOCK"])
        self.assertAlmostEqual(ch["beat"], 1.5)                    # 9.5 beats -> 1.5 into the 8-beat loop
        self.assertAlmostEqual(ch["beat_phase"], 0.5)
        self.assertAlmostEqual(ch["loop_frame"], 45.0)
        self.assertAlmostEqual(ch["loop_phase"], 1.5 / 8)
        self.assertAlmostEqual(ch["bar_phase"], (9.5 / 4) % 1)
        self.assertAlmostEqual(ch["kick"], 2.718281828459045 ** -3.0)
        comp.par.Feedloopstart = value(16)                         # Pipeline > Feed loop start
        me.time.frame = 16
        ch = dict((name, eval(expr, {"me": me, "parent": lambda: comp})) for name, expr in env["CLOCK"])
        self.assertEqual((ch["loop_frame"], ch["beat"]), (0.0, 0.0))

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

    def test_lcm_baseline_bump_applies_once(self):
        comp = self.build()
        self.assertEqual(comp.storage["tdeforum_baseline"], 2)
        self.assertEqual((comp.par.Steps.val, comp.par.Cfgscaleschedule.val), (4, 1.8))
        comp.storage["tdeforum_baseline"] = 1          # a COMP built before this baseline...
        comp.par.Cfgscaleschedule.val = 7.0            # ...still at the old CFG
        comp.par.Steps.val = 6                         # a value you chose is kept
        comp = self.build()
        self.assertEqual((comp.par.Cfgscaleschedule.val, comp.par.Steps.val), (1.8, 6))
        self.assertTrue(any("Cfgscaleschedule was the old baseline (7.0); now 1.8" in l for l in self.log))
        comp.par.Cfgscaleschedule.val = 7.0            # set on purpose after the upgrade: kept
        comp = self.build()
        self.assertEqual(comp.par.Cfgscaleschedule.val, 7.0)

    def test_ui_exec_watches_the_buttons(self):
        comp = self.build()
        ui_exec = comp.op("ui_exec")
        self.assertTrue(ui_exec.par.file.val.endswith("ui_exec.py"))
        self.assertEqual(ui_exec.par.pars.val.split(), ctl.ui_watched())
        self.assertIn("Pagepresetmotion3d", ui_exec.par.pars.val)
        self.assertEqual(ui_exec.par.op.val, comp.path)
        self.assertEqual((ui_exec.par.valuechange.val, ui_exec.par.onpulse.val), (1, 1))
        for name in ("Presetapply", "Promptedit"):
            self.assertEqual(getattr(comp.par, name).style, "Pulse")
        self.assertFalse(any("NOTE ui_exec" in line for line in self.log))

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


SETUP = os.path.join(ROOT_DIR, "scripts", "setup_network.py")


class SetupNetworkTest(unittest.TestCase):
    def run_setup(self, root):
        me = Node("textDAT", "setup", root, BUILTINS["textDAT"])
        me.par.file.val = os.path.join(ROOT_DIR, "scripts", "setup_network.py")
        out = []
        env = {"me": me, "ParMode": ParMode, "op": lambda path: root,
               "print": lambda *a: out.append(" ".join(str(x) for x in a))}
        for kind in ("executeDAT", "textDAT", "chopexecuteDAT"):
            env[kind] = kind
        with open(SETUP, encoding="utf-8") as fh:
            exec(compile(fh.read(), SETUP, "exec"), env)
        return out

    def test_cross1_overshoot_is_fixed_once(self):
        root = Node("baseCOMP", "project1")
        root.create("baseCOMP", "deforum")
        cross = root.create("crossCHOP", "cross1")
        cross.par.cross = Par(cross, "cross", "Float", 0.0)
        cross.par.cross.mode = ParMode.EXPRESSION
        cross.par.cross.expr = "op('crossfade')[0] * len(me.inputs)"
        out = self.run_setup(root)
        self.assertEqual(cross.par.cross.expr, "op('crossfade')[0] * (len(me.inputs) - 1)")
        self.assertTrue(any("cross1.cross:" in line for line in out), out)
        out = self.run_setup(root)
        self.assertEqual(cross.par.cross.expr, "op('crossfade')[0] * (len(me.inputs) - 1)")
        self.assertFalse(any("cross1.cross:" in line for line in out))
