"""CHOP channels dropped onto a deforum parameter (chop_link.py and its payload / controller use)."""

import unittest

from _fakes import Channel, Op, Par, ParMode, make_network
from tdeforum import chop_link, payload, schema, td_controller as ctl

from test_controller import TEMPO_UI


def chop(name, parent=None, rate=30.0, start=0.0, **channels):
    o = Op(name, parent)
    o.channels = [Channel(n, v) for n, v in channels.items()]
    o.rate, o.start = rate, start
    return o


RAMP = [float(i) for i in range(60)]          # one value per render frame of a 60-frame loop


class LinkReadTest(unittest.TestCase):
    def setUp(self):
        self.pattern = chop("pattern1", chan1=RAMP, chan2=[1.0] * 60)
        self.ops = {"pattern1": self.pattern, "/project1/pattern1": self.pattern}
        self.resolve = self.ops.get

    def link(self, par):
        return chop_link.link_of(par, None, self.resolve)

    def test_chop_reference(self):
        link = self.link(Par("Translationz", 3.0, ParMode.EXPRESSION, "op('pattern1')['chan1']"))
        self.assertEqual(link.samples, RAMP)
        self.assertEqual(link.rate, 30.0)
        self.assertIsNone(link.note)
        self.assertIn("chan1", link.source)

    def test_index_and_chan_forms(self):
        self.assertEqual(self.link(Par("Zoom", 1, ParMode.EXPRESSION, 'op("pattern1")[1]')).samples, [1.0] * 60)
        self.assertEqual(self.link(Par("Zoom", 1, ParMode.EXPRESSION,
                                       "op('/project1/pattern1').chan('chan1')")).samples, RAMP)

    def test_maths_over_the_whole_channel(self):
        link = self.link(Par("Zoom", 1, ParMode.EXPRESSION,
                             "1 + op('pattern1')['chan1'] * 0.01 + op('pattern1')['chan2']"))
        self.assertAlmostEqual(link.samples[0], 2.0)
        self.assertAlmostEqual(link.samples[59], 2.59)
        self.assertIsNone(link.note)

    def test_unevaluable_expression_falls_back_to_the_channel(self):
        link = self.link(Par("Zoom", 1, ParMode.EXPRESSION, "math.sin(op('pattern1')['chan1'])"))
        self.assertEqual(link.samples, RAMP)
        self.assertIn("as-is", link.note)

    def test_export(self):
        par = Par("Translationz", 0.0, ParMode.EXPORT)
        par.exportOP, par.exportSource = self.pattern, self.pattern.channels[0]
        link = self.link(par)
        self.assertEqual(link.samples, RAMP)
        self.assertIn("export", link.source)

    def test_not_linked(self):
        self.assertIsNone(self.link(Par("Zoom", 1.0)))
        self.assertIsNone(self.link(Par("Zoom", 1.0, ParMode.EXPRESSION, "me.time.frame * 0.01")))
        self.assertIsNone(self.link(Par("Zoom", 1.0, ParMode.EXPRESSION, "op('missing')['chan1']")))
        missing = self.link(Par("Zoom", 1.0, ParMode.EXPRESSION, "op('pattern1')['nope']"))
        self.assertEqual(missing.samples, [])
        self.assertIn("not found", missing.note)

    def test_timeline_window(self):
        # 2-second loop starting 1 s into a 30 Hz channel: samples 30..89 (wrapping past the end)
        link = chop_link.Link(RAMP, 30.0, 0.0)
        window = chop_link.loop_samples(link, chop_link.TIMELINE, 2.0, 1.0)
        self.assertEqual(len(window), 60)
        self.assertEqual(window[0], 30.0)
        self.assertEqual(window[29], 59.0)
        self.assertEqual(window[30], 0.0)
        self.assertEqual(chop_link.loop_samples(link, chop_link.LOOP, 2.0, 1.0), RAMP)


class LinkPayloadTest(unittest.TestCase):
    def values(self, **extra):
        v = dict(TEMPO_UI, mod1_active=False, loop_seeds=False)
        v.update(extra)
        return v

    def test_link_bakes_the_whole_channel(self):
        links = {"translation_z": chop_link.Link(RAMP, 30.0).as_dict()}
        result = payload.build_request(self.values(), links=links)
        how, sched = result["schedules"]["translation_z"]
        self.assertEqual(how, "chop")
        keys = sched.split(", ")
        self.assertEqual(len(keys), result["plan"]["max_frames"])     # 75 = loop + 1 beat overlap
        self.assertEqual(keys[0], "0:(0.00000)")
        self.assertEqual(keys[59], "59:(59.00000)")
        self.assertEqual(keys[60], "60:(0.00000)")                   # the overlap wraps to the loop start
        self.assertIn("translation_z", payload.summary(result))

    def test_mod_matrix_adds_on_top(self):
        links = {"translation_z": chop_link.Link([5.0, 5.0], 30.0).as_dict()}
        result = payload.build_request(self.values(mod1_active=True), links=links)
        values = [float(k.split("(")[1].rstrip(")")) for k in result["schedules"]["translation_z"][1].split(", ")]
        self.assertAlmostEqual(values[0], 7.0)          # kick decay starts at depth 2 on top of the 5 base
        self.assertTrue(all(v >= 5.0 - 1e-6 for v in values))

    def test_raw_text_wins_and_warns(self):
        links = {"zoom": chop_link.Link(RAMP, 30.0).as_dict()}
        v = self.values()
        v[payload.raw_key("zoom")] = "0:(1.01)"
        result = payload.build_request(v, links=links)
        self.assertEqual(result["schedules"]["zoom"], ("raw", "0:(1.01)"))
        self.assertTrue(any("raw schedule is set" in w for w in result["warnings"]))

    def test_hybrid_schedules_are_linkable(self):
        result = payload.build_request(self.values(hybrid_flow_factor_schedule=1.0, hybrid_comp_alpha_schedule=0.5))
        self.assertEqual(result["schedules"]["hybrid_flow_factor_schedule"], ("constant", "0:(1)"))
        links = {"hybrid_comp_alpha_schedule": chop_link.Link([0.0, 1.0], 30.0).as_dict()}
        result = payload.build_request(self.values(hybrid_comp_alpha_schedule=0.5), links=links)
        self.assertEqual(result["schedules"]["hybrid_comp_alpha_schedule"][0], "chop")
        self.assertIn("hybrid_comp_alpha_schedule", schema.MOD_APIS)

    def test_live_values_follow_the_link(self):
        links = {"zoom": chop_link.Link(RAMP, 30.0).as_dict()}
        live = payload.live_values(self.values(), None, 20.0, 60.0, links)   # 20 timeline frames = render frame 10
        self.assertAlmostEqual(live["zoom"], 10.0)


class LinkControllerTest(unittest.TestCase):
    def setUp(self):
        self.root = make_network(dict(TEMPO_UI, mod1_active=False), comp=True)
        self.ui = self.root.op("deforum")
        self.ui.parent = lambda: self.root
        self.root.add(chop("pattern1", self.root, chan1=RAMP))

    def test_reference_on_base_and_raw(self):
        self.ui.par.Translationz = Par("Translationz", 12.0, ParMode.EXPRESSION, "op('pattern1')['chan1']")
        self.ui.par.Zoomraw = Par("Zoomraw", "0.5", ParMode.EXPRESSION, "op('pattern1')['chan1'] * 0.001 + 1")
        values = ctl.read_ui(self.ui)
        links = ctl.read_links(self.ui, values)
        self.assertEqual(sorted(links), ["translation_z", "zoom"])
        self.assertEqual(values[payload.raw_key("zoom")], "")          # the raw text is the channel, not a schedule
        self.assertIn("Translationz <- /project1/pattern1", ctl.describe_links(links))
        result = payload.build_request(values, links=links)
        self.assertEqual(result["schedules"]["zoom"][0], "chop")
        self.assertTrue(result["schedules"]["zoom"][1].startswith("0:(1.00000), 1:(1.00100)"))

    def test_linked_labels(self):
        tz = schema.BY_API["translation_z"]
        self.ui.par.Translationz = Par("Translationz", 0.0, ParMode.EXPRESSION, "op('pattern1')['chan1']")
        self.ui.par.Translationz.label = tz.ui_label
        self.ui.par.Zoom.label = schema.BY_API["zoom"].ui_label
        self.assertTrue(tz.ui_label.startswith(schema.MOD_MARK))
        self.ui.par.Choplinksinfo = Par("Choplinksinfo", "")
        values = ctl.read_ui(self.ui)
        ctl.show_links(self.ui, ctl.read_links(self.ui, values))
        self.assertEqual(self.ui.par.Translationz.label, tz.ui_label + schema.LINK_MARK)
        self.assertEqual(self.ui.par.Zoom.label, schema.BY_API["zoom"].ui_label)
        self.assertIn("Translationz", self.ui.par.Choplinksinfo.val)
        self.ui.par.Translationz.mode = ParMode.CONSTANT                 # unlinked: the mark goes away
        ctl.show_links(self.ui, ctl.read_links(self.ui, ctl.read_ui(self.ui)))
        self.assertEqual(self.ui.par.Translationz.label, tz.ui_label)
        self.assertTrue(self.ui.par.Choplinksinfo.val.startswith("none"))

    def test_timeline_timing_uses_feed_loop_start(self):
        self.root.timeline = None
        self.ui.time = type("T", (), {"rate": 60.0, "start": 1})()
        self.ui.par.Feedloopstart = Par("Feedloopstart", 61)        # 1 s into the timeline
        self.ui.par.Choptiming = Par("Choptiming", chop_link.TIMELINE)
        self.ui.par.Translationz = Par("Translationz", 0.0, ParMode.EXPRESSION, "op('pattern1')['chan1']")
        values = ctl.read_ui(self.ui)
        links = ctl.read_links(self.ui, values)
        self.assertAlmostEqual(links["translation_z"]["loop_start_seconds"], 1.0)
        result = payload.build_request(values, links=links)
        self.assertTrue(result["schedules"]["translation_z"][1].startswith("0:(30.00000)"))


if __name__ == "__main__":
    unittest.main()
