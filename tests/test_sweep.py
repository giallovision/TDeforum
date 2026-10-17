import json
import os
import unittest
from unittest import mock

import numpy as np

from _fakes import make_network  # noqa: F401  (puts scripts/ on sys.path)
import test_controller
from test_controller import FEED_UI, respond
from tdeforum import config, feed, schema, sweep
from tdeforum import td_controller as ctl


def S(**kw):
    return sweep.Settings(**kw)


def levels(p, mode="max", width=10):
    lo, hi = sweep.band(p, mode, width)
    return round(lo * 255), round(hi * 255)


class MathTest(unittest.TestCase):
    def test_max_starts_on_245_255_and_ends_on_0_10(self):
        self.assertEqual(levels(0.0), (245, 255))
        self.assertEqual(levels(1.0), (0, 10))
        lo, hi = levels(0.5)
        self.assertTrue(0 < lo < 245 and 10 < hi < 255)

    def test_min_is_the_opposite_way(self):
        self.assertEqual(levels(0.0, "min"), (0, 10))
        self.assertEqual(levels(1.0, "min"), (245, 255))

    def test_one_ramp_over_240_frames_goes_start_to_end_monotonically(self):
        s = S()
        pos = [sweep.position(k, 240, s) for k in range(240)]
        self.assertEqual((pos[0], pos[-1]), (0.0, 1.0))
        self.assertTrue(all(b > a for a, b in zip(pos, pos[1:])))

    def test_cycles_restart_and_last_frame_lands_on_the_end(self):
        s = S(cycles=2)
        pos = [sweep.position(k, 241, s) for k in range(241)]
        self.assertEqual(pos[0], 0.0)
        self.assertAlmostEqual(pos[120], 0.0, places=6)
        self.assertEqual(pos[-1], 1.0)
        self.assertGreater(pos[119], 0.95)

    def test_pingpong_goes_out_and_back(self):
        s = S(shape="pingpong")
        pos = [sweep.position(k, 101, s) for k in range(101)]
        self.assertEqual((pos[0], pos[50], pos[100]), (0.0, 1.0, 0.0))

    def test_reverse_swaps_start_and_end(self):
        s = S(direction="reverse")
        self.assertEqual((sweep.position(0, 50, s), sweep.position(49, 50, s)), (1.0, 0.0))

    def test_single_frame_and_bad_settings_are_safe(self):
        s = S(mode="bogus", cycles=-3, width=9999, fill="x", shape="?", direction="?")
        self.assertEqual((s.mode, s.fill, s.shape, s.direction), ("max", "white", "ramp", "forward"))
        self.assertEqual(sweep.position(0, 1, s), 0.0)
        lo, hi = sweep.band(0.5, "max", s.width)
        self.assertTrue(0.0 <= lo <= hi <= 1.0)

    def test_from_values_reads_the_sweep_fields(self):
        s = sweep.from_values({"sweep_mode": "min", "sweep_cycles": "3", "sweep_width": 20,
                               "sweep_softness": 4, "sweep_fill": "depth"})
        self.assertEqual((s.mode, s.cycles, s.width, s.softness, s.fill), ("min", 3.0, 20.0, 4.0, "depth"))


class PlanTest(unittest.TestCase):
    def test_indices_follow_extract_window_and_clamp(self):
        plan = sweep.plan({}, 10, extract_from=5, nth=2, depth_frames=20)
        self.assertEqual(plan["indices"], [5, 7, 9, 11, 13, 15, 17, 19, 19, 19])
        self.assertEqual(len(plan["bands"]), 10)
        self.assertEqual(len(plan["warnings"]), 1)
        text = sweep.describe(sweep.plan({}, 240))
        self.assertIn("245-255 at the start", text)
        self.assertIn("0-10 at the end of 240 frames", text)

    def test_check_explains_what_is_missing(self):
        ok = {"sweep_enabled": True, "animation_mode": "Video Input", "video_init_path": "/x.mp4"}
        self.assertIsNone(sweep.check(ok))
        self.assertIn("switched off", sweep.check(dict(ok, sweep_enabled=False)))
        self.assertIn("Video Input", sweep.check(dict(ok, animation_mode="3D")))
        self.assertIn("Video Init Path", sweep.check(dict(ok, video_init_path="")))


class FramePlanTest(unittest.TestCase):
    def test_sequential_plan_never_wraps_and_says_so(self):
        with mock.patch.object(feed, "project_frames_per_loop", return_value=120):
            tp = {"render_fps": 30.0}
            wrapped = feed.frame_plan(tp, 100, 60, 1)
            straight = feed.frame_plan(tp, 100, 60, 1, wrap=False)
        self.assertEqual(wrapped["frames"][60], 1)
        self.assertEqual(straight["frames"][60], 121)
        self.assertIn("wrapping at 120", feed.describe(wrapped))
        self.assertNotIn("wrapping", feed.describe(straight))


class MaskTest(unittest.TestCase):
    def setUp(self):
        self.d = np.arange(256, dtype=np.float32).reshape(1, 256) / 255.0

    def test_hard_band_is_inclusive(self):
        lo, hi = sweep.band(0.0, "max", 10)
        m = sweep.mask(self.d, lo, hi)
        self.assertEqual(list(np.nonzero(m[0])[0]), list(range(245, 256)))
        self.assertEqual(set(np.unique(m)), {0.0, 1.0})

    def test_soft_edges_feather_outside_and_keep_the_core(self):
        lo, hi = 100 / 255.0, 120 / 255.0
        m = sweep.mask(self.d, lo, hi, softness=10 / 255.0)[0]
        self.assertEqual(m[110], 1.0)
        self.assertTrue(0.0 < m[95] < 1.0 and 0.0 < m[125] < 1.0)
        self.assertEqual((m[50], m[200]), (0.0, 0.0))

    def test_depth_fill_keeps_shading(self):
        m = sweep.mask(self.d, 100 / 255.0, 120 / 255.0, fill="depth")[0]
        self.assertAlmostEqual(float(m[110]), 110 / 255.0, places=5)
        self.assertEqual(float(m[50]), 0.0)

    def test_rgba_in_grey_rgba_out(self):
        img = np.zeros((2, 3, 4), dtype=np.float32)
        img[..., :3] = 0.97
        img[0, 0, :3] = 0.2
        out = sweep.mask_rgba(img, 0.95, 1.0)
        self.assertEqual(out.shape, (2, 3, 4))
        self.assertEqual((out[0, 0, 0], out[1, 1, 1], out[1, 1, 3]), (0.0, 1.0, 1.0))

    def test_cook_uses_the_stored_band(self):
        class Src(object):
            def numpyArray(self, delayed=False):
                a = np.zeros((1, 4, 4), dtype=np.float32)
                a[0, :, :3] = np.array([0.1, 0.5, 0.9, 1.0], dtype=np.float32)[:, None]
                a[0, :, 3] = 1.0
                return a

        class Script(object):
            def __init__(self):
                self.inputs, self.out, self.stored = [Src()], None, {}

            def fetch(self, key, default=None):
                return self.stored.get(key, default)

            def copyNumpyArray(self, arr):
                self.out = arr

        op = Script()
        op.stored[sweep.SCRIPT_BAND_KEY] = (0.85, 1.0, 0.0, "white")
        sweep.cook(op)
        self.assertEqual(list(op.out[0, :, 0]), [0.0, 0.0, 1.0, 1.0])


class SchemaFeedTest(unittest.TestCase):
    def test_fields_and_page(self):
        self.assertEqual(schema.PAGE_ORDER[-len(schema.PAGE_CNS) - 2], schema.PAGE_SWEEP)
        fields = [f for f in schema.FIELDS if f.page == schema.PAGE_SWEEP]
        self.assertEqual(sorted(f.api for f in fields), sorted(
            ["sweep_enabled", "sweep_model", "sweep_mode", "sweep_cycles", "sweep_shape", "sweep_direction",
             "sweep_width", "sweep_softness", "sweep_fill", "sweep_as_mask", "sweep_depth_path", "sweep_info"]))
        self.assertTrue(all(f.target is None for f in fields))
        self.assertEqual(schema.BY_API["sweep_depth_path"].td_name, "Sweepdepthpath")
        self.assertIn(feed.SWEEP, schema.BY_API["feed_1_mode"].menu)

    def test_requests_include_sweep_units(self):
        base = {"cn_1_enabled": True, "feed_1_mode": "sweep", "sweep_enabled": True}
        self.assertEqual([(r.unit, r.mode) for r in feed.requests(base)], [(1, "sweep")])
        self.assertEqual(feed.requests(dict(base, cn_1_enabled=False)), [])
        masked = feed.requests(dict(base, cn_1_enabled=False, sweep_as_mask=True))
        self.assertEqual([(r.unit, r.mode) for r in masked], [(1, "sweep")])


SWEEP_UI = dict(FEED_UI, animation_mode="Video Input", sweep_enabled=True, feed_1_mode="sweep",
                feed_1_top="", cn_1_enabled=True, comfy_preproc_enable=False,
                video_init_path="/opt/a1111/td_inputs/comfy_videos/archive/a.mp4")


class SweepControllerTest(test_controller.FeedTest.__bases__[0]):
    setUp = test_controller.FeedTest.setUp
    state = test_controller.FeedTest.state
    tick = test_controller.FeedTest.tick
    record_all = test_controller.FeedTest.record_all
    step = test_controller.FeedTest.step
    posts = test_controller.FeedTest.posts
    feed_file = test_controller.FeedTest.feed_file
    DEPTH = "a_1024x576_DepthAnythingV2Preprocessor_75f_00001.mp4"

    def make(self, **overrides):
        self.root = make_network(dict(SWEEP_UI, **overrides), comp=True, prompt_rows=[("0", "gold", "")])
        self.ui = self.root.op("deforum")
        self.timeline = self.root.timeline
        self.out = self.ui.op("feed1_out")
        self.depth, self.script = self.ui.op("sweep_depth"), self.ui.op("sweep_mask")
        return self.ui

    def probe(self):
        seen = []
        original = self.out.par.addframe.pulse

        def pulse():
            original()
            seen.append((self.depth.par.index.val, self.script.fetch(sweep.SCRIPT_BAND_KEY)))
        self.out.par.addframe.pulse = pulse
        return seen

    def depth_done(self):
        comfy = self.root.op("webclient_comfyui")
        respond(self.root, "webclient_comfyui", 200, {"prompt_id": "p1", "number": 1, "node_errors": {}})
        self.tick()
        path = config.to_share(self.cfg, "/opt/a1111/td_masks/preprocessed_vids/" + self.DEPTH)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"x" * 50)
        respond(self.root, "webclient_comfyui", 200, {"p1": {
            "status": {"status_str": "success", "completed": True},
            "outputs": {"21": {"gifs": [{"filename": self.DEPTH, "subfolder": "preprocessed_vids"}]}}}})
        return comfy

    def test_depth_job_then_recording_of_every_band(self):
        ui = self.make()
        ctl.queue(self.root)
        comfy = self.root.op("webclient_comfyui")
        self.assertEqual(self.state(), ctl.COMFY_SUBMITTED)
        job = json.loads(comfy.requests[0][2])
        self.assertIn("DepthAnythingV2Preprocessor", json.dumps(job))
        self.assertEqual(self.posts(), [])

        seen = self.probe()
        self.depth_done()
        self.assertEqual(self.state(), ctl.CAPTURING)
        self.assertEqual(ui.par.Sweepdepthpath.val, "/opt/a1111/td_masks/preprocessed_vids/" + self.DEPTH)
        self.assertEqual(self.depth.par.file.val, config.to_share(self.cfg, ui.par.Sweepdepthpath.val))
        self.assertEqual(self.out.par.file.val, self.share + "/td_masks/feeds/cn1_feed.mp4")
        self.assertEqual(ui.op("feed1_sel").par.top.val, self.script.path)

        self.record_all()
        self.assertEqual(self.state(), ctl.WAITING_FEED)
        self.assertEqual(len(seen), 75)
        self.assertEqual([i for i, _ in seen], list(range(75)))
        first, last = seen[0][1], seen[-1][1]
        self.assertEqual((round(first[0] * 255), round(first[1] * 255)), (245, 255))
        self.assertEqual((round(last[0] * 255), round(last[1] * 255)), (0, 10))
        self.assertIn("245-255 at the start", ui.par.Sweepinfo.val)

        self.feed_file()
        with mock.patch.object(ctl, "_frame_counter", return_value=lambda container: 75):
            self.tick()
            self.tick()
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        s = json.loads(self.posts()[0][2])["deforum_settings"]
        self.assertEqual(s["animation_mode"], "Video Input")
        self.assertEqual(s["cn_1_vid_path"], "/opt/a1111/td_masks/feeds/cn1_feed.mp4")
        self.assertIs(s["cn_1_enabled"], True)
        self.assertEqual(s["max_frames"], 75)

    def test_cached_depth_video_skips_comfy(self):
        self.make()
        ctl.queue(self.root)
        self.depth_done()
        ctl.cancel(self.root)
        ctl.queue(self.root)
        posts = [r for r in self.root.op("webclient_comfyui").requests if r[0] == "POST" and r[1].endswith("/prompt")]
        self.assertEqual(len(posts), 1, "no second /prompt")
        self.assertEqual(self.state(), ctl.CAPTURING)

    def test_mask_only_sets_the_video_mask(self):
        ui = self.make(cn_1_enabled=False, sweep_as_mask=True, video_mask_path="/opt/a1111/td_masks/mask_01.mov")
        ctl.queue(self.root)
        self.depth_done()
        self.record_all()
        self.feed_file()
        with mock.patch.object(ctl, "_frame_counter", return_value=lambda container: 75):
            self.tick()
            self.tick()
        s = json.loads(self.posts()[0][2])["deforum_settings"]
        self.assertIs(s["use_mask_video"], True)
        self.assertEqual(s["video_mask_path"], "/opt/a1111/td_masks/feeds/cn1_feed.mp4")
        self.assertEqual(ui.par.Usemaskvideo.val, 1)

    def test_preview_and_doctor_report_the_sweep(self):
        self.make()
        with mock.patch("builtins.print") as out:
            ctl.preview(self.root)
            ctl.doctor(self.root)
        text = "\n".join(str(c.args[0]) for c in out.call_args_list if c.args)
        self.assertIn("Sweep Depth", text)
        self.assertIn("245-255 at the start", text)
        self.assertIn("depth video: (none yet", text)
        self.assertNotIn("wrapping", [l for l in text.splitlines() if "feed: ControlNet" in l][0])

    def test_wrong_animation_mode_fails_with_a_reason(self):
        self.make(animation_mode="3D")
        ctl.queue(self.root)
        self.assertEqual(self.root.op("webclient_comfyui").requests, [])
        self.assertIn("Video Input", self.ui.par.Pipelinestatus.val)

    def test_max_and_min_bands_for_the_first_and_last_frame(self):
        self.make(sweep_mode="min", sweep_cycles=1.0)
        ctl.queue(self.root)
        seen = self.probe()
        self.depth_done()
        self.record_all()
        self.assertEqual((round(seen[0][1][0] * 255), round(seen[0][1][1] * 255)), (0, 10))
        self.assertEqual((round(seen[-1][1][0] * 255), round(seen[-1][1][1] * 255)), (245, 255))


if __name__ == "__main__":
    unittest.main()
