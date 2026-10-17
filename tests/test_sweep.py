import json
import os
import unittest
from unittest import mock

import numpy as np

from _fakes import make_network  # noqa: F401  (puts scripts/ on sys.path)
import test_controller
from test_controller import FEED_UI, respond
from tdeforum import config, feed, modulation, payload, schema, sweep
from tdeforum import td_controller as ctl

import shutil
import tempfile

try:
    import cv2
except ImportError:          # the GPU host's system Python may not have OpenCV (TouchDesigner does)
    cv2 = None
NEEDS_CV2 = unittest.skipIf(cv2 is None, "OpenCV not installed (pip install opencv-python-headless)")


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
        self.assertIsNone(sweep.check(dict(ok, animation_mode="3D")))           # Hybrid Video source
        self.assertIn("Video Input", sweep.check(dict(ok, animation_mode="Interpolation")))
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

    def test_trail_decay_fades_to_five_percent(self):
        self.assertEqual(sweep.trail_decay(0), 0.0)
        self.assertAlmostEqual(sweep.trail_decay(12) ** 12, 0.0498, places=3)


def write_depth_video(path, frames=30, width=64, height=32, fps=30.0):
    """A depth video whose grey level rises left (far, 0) to right (near, 255), every frame."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height), True)
    row = np.round(np.linspace(0, 255, width)).astype(np.uint8)
    grey = np.tile(row, (height, 1))
    for _ in range(frames):
        writer.write(cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR))
    writer.release()
    return path


def read_video(path):
    capture = cv2.VideoCapture(path)
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    capture.release()
    return frames


def white_columns(frame, level=128):
    return np.nonzero(frame.mean(axis=0) > level)[0]


@NEEDS_CV2
class RenderTest(unittest.TestCase):
    """The real thing: OpenCV decodes a depth video, numpy masks it, OpenCV encodes the result."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.depth = write_depth_video(os.path.join(self.dir, "depth.mp4"), frames=20)

    def render(self, total=20, size=(64, 32), **values):
        out = os.path.join(self.dir, "out.mp4")
        plan = sweep.plan(values, total, 0, 1, sweep.video_frames(self.depth))
        result = sweep.render(self.depth, out, plan, size)
        return result, read_video(out)

    def test_band_moves_from_near_to_far(self):
        result, frames = self.render(sweep_width=24)
        self.assertEqual((result["frames"], len(frames)), (20, 20))
        first, last = white_columns(frames[0]), white_columns(frames[-1])
        self.assertTrue(len(first) and first.min() > 52, first)      # right edge = near = 230-255
        self.assertTrue(len(last) and last.max() < 12, last)         # left edge = far = 0-24
        middle = white_columns(frames[10])
        self.assertTrue(20 < middle.mean() < 44, middle)

    def test_min_mode_goes_the_other_way(self):
        _result, frames = self.render(sweep_width=24, sweep_mode="min")
        self.assertTrue(white_columns(frames[0]).max() < 12)
        self.assertTrue(white_columns(frames[-1]).min() > 52)

    def test_trail_leaves_a_fading_glow_behind_the_band(self):
        _result, plain = self.render(sweep_width=16)
        _result, trail = self.render(sweep_width=16, sweep_trail=12)
        behind = plain[12].mean(axis=0) < 20                   # columns the band has already left...
        glow = trail[12].mean(axis=0)[behind]
        self.assertTrue((glow > 20).any(), glow)               # ...still glow with a trail
        self.assertTrue((glow < 250).all())

    def test_grow_widens_and_blur_softens_the_band(self):
        _r, plain = self.render(sweep_width=12)
        _r, grown = self.render(sweep_width=12, sweep_grow=4)
        _r, blurred = self.render(sweep_width=12, sweep_blur=3.0)
        self.assertGreater(len(white_columns(grown[10])), len(white_columns(plain[10])) + 4)
        grey = lambda f: ((f.mean(axis=0) > 20) & (f.mean(axis=0) < 235)).sum()
        self.assertGreater(grey(blurred[10]), grey(plain[10]) + 2)

    def test_output_is_resized_to_the_render_size(self):
        _result, frames = self.render(size=(96, 48))
        self.assertEqual(frames[0].shape, (48, 96))

    def test_depth_smoothing_of_a_still_depth_changes_nothing(self):
        _a, plain = self.render(sweep_width=24)
        _b, smooth = self.render(sweep_width=24, sweep_smooth=0.8)
        self.assertLess(np.abs(plain[15].astype(int) - smooth[15].astype(int)).mean(), 2.0)

    def job(self, **overrides):
        job = {"key": "k", "depth_local": self.depth, "fetch_url": None, "values": {"sweep_width": 20},
               "plan": {"mode": "Video Input", "frame_mode": "trim", "max_frames": 20, "extract_from_frame": 0,
                        "extract_nth_frame": 1, "source_frames": 20},
               "ui_max": 20, "size": (64, 32), "fps": 30.0,
               "out_share": os.path.join(self.dir, "cn_sweep_k.mp4"),
               "sidecar": os.path.join(self.dir, "cn_sweep_k.mp4.json")}
        job.update(overrides)
        return job

    def test_run_job_writes_the_video_and_the_result_file(self):
        job = self.job()
        result = sweep.run_job(job)
        self.assertTrue(result["ok"], result)
        self.assertEqual(sweep.read_result(job["sidecar"]), result)
        self.assertEqual(len(read_video(job["out_share"])), 20)
        self.assertIn("at the end of 20 frames", result["describe"])
        self.assertNotIn("init_frames", result)

    def test_a_short_init_video_replans_the_render(self):
        job = self.job()
        job["plan"].update(max_frames=40, source_frames=40)
        job["ui_max"] = 40
        result = sweep.run_job(job)
        self.assertEqual((result["frames"], result["init_frames"], result["depth_frames"]), (20, 20, 20))

    def test_missing_depth_video_is_downloaded(self):
        fetched = os.path.join(self.dir, "fetch", "depth.mp4")
        calls = []

        def fake_download(url, path, timeout=60.0):
            calls.append(url)
            shutil.copyfile(self.depth, path) if os.path.isdir(os.path.dirname(path)) else (
                os.makedirs(os.path.dirname(path)), shutil.copyfile(self.depth, path))
            return os.path.getsize(path)
        with mock.patch.object(sweep, "download", side_effect=fake_download):
            result = sweep.run_job(self.job(depth_local=fetched, fetch_url="http://h:8188/view?x"))
        self.assertTrue(result["ok"], result)
        self.assertEqual(calls, ["http://h:8188/view?x"])
        self.assertGreater(result["fetched"], 0)

    def test_errors_end_up_in_the_result_file(self):
        job = self.job(depth_local=os.path.join(self.dir, "missing.mp4"))
        result = sweep.run_job(job)
        self.assertFalse(result["ok"])
        self.assertIn("not readable from TouchDesigner", result["error"])
        self.assertEqual(sweep.read_result(job["sidecar"])["ok"], False)

    def test_job_key_changes_with_the_look_but_not_with_unrelated_values(self):
        plan = {"max_frames": 240, "extract_from_frame": 0, "extract_nth_frame": 1, "source_frames": 240}
        a = sweep.job_key("/d.mp4", {"sweep_width": 10}, plan, (1024, 576))
        self.assertEqual(a, sweep.job_key("/d.mp4", {"sweep_width": 10, "zoom": 2}, plan, (1024, 576)))
        self.assertNotEqual(a, sweep.job_key("/d.mp4", {"sweep_width": 11}, plan, (1024, 576)))
        self.assertNotEqual(a, sweep.job_key("/e.mp4", {"sweep_width": 10}, plan, (1024, 576)))
        self.assertNotEqual(a, sweep.job_key("/d.mp4", {"sweep_width": 10}, dict(plan, max_frames=120), (1024, 576)))


class ConfigViewTest(unittest.TestCase):
    def test_comfy_view_for_outputs_and_inputs(self):
        cfg = config.load()
        self.assertEqual(config.comfy_view(cfg, "/opt/a1111/td_masks/preprocessed_vids/a_00001.mp4"),
                         ("output", "preprocessed_vids", "a_00001.mp4"))
        self.assertEqual(config.comfy_view(cfg, "/opt/a1111/td_inputs/comfy_videos/archive/t.mp4"),
                         ("input", "archive", "t.mp4"))
        self.assertIsNone(config.comfy_view(cfg, "/opt/a1111/td_masks/feeds/x.mp4"))
        url = config.comfy_view_url(cfg, "output", "preprocessed_vids", "a b.mp4")
        self.assertIn(":8188/view?", url)
        self.assertIn("filename=a+b.mp4", url)
        self.assertIn("type=output", url)
        share, container = config.fetch_paths(cfg, "/opt/a1111/td_masks/preprocessed_vids/a_00001.mp4")
        self.assertEqual(container, "/opt/a1111/td_masks/comfy_fetch/a_00001.mp4")
        self.assertTrue(share.endswith("td_masks/comfy_fetch/a_00001.mp4"))


class SchemaFeedTest(unittest.TestCase):
    def test_fields_and_page(self):
        self.assertEqual(schema.PAGE_ORDER[-len(schema.PAGE_CNS) - 2], schema.PAGE_SWEEP)
        fields = [f for f in schema.FIELDS if f.page == schema.PAGE_SWEEP and not f.api.startswith("pagepreset")]
        self.assertEqual(sorted(f.api for f in fields), sorted(
            ["sweep_depth_video", "sweep_prepare_only", "sweep_force", "sweep_enabled", "sweep_model", "sweep_mode",
             "sweep_cycles", "sweep_shape", "sweep_direction", "sweep_width", "sweep_softness", "sweep_trail",
             "sweep_grow", "sweep_blur", "sweep_show_latest",
             "sweep_smooth", "sweep_fill", "sweep_as_mask", "sweep_depth_path", "sweep_info"]))
        self.assertTrue(all(f.target is None for f in fields))
        self.assertEqual(fields[0].api, "sweep_enabled")
        self.assertEqual(schema.BY_API["sweep_depth_path"].td_name, "Sweepdepthpath")
        self.assertIn(feed.SWEEP, schema.BY_API["feed_1_mode"].menu)

    def test_requests_include_sweep_units(self):
        base = {"cn_1_enabled": True, "feed_1_mode": "sweep", "sweep_enabled": True}
        self.assertEqual([(r.unit, r.mode) for r in feed.requests(base)], [(1, "sweep")])
        self.assertEqual(feed.requests(dict(base, cn_1_enabled=False)), [])
        masked = feed.requests(dict(base, cn_1_enabled=False, sweep_as_mask=True))
        self.assertEqual([(r.unit, r.mode) for r in masked], [(1, "sweep")])


SWEEP_UI = dict(FEED_UI, animation_mode="Video Input", sweep_enabled=True, feed_1_mode="sweep",
                feed_1_top="", cn_1_enabled=True, comfy_preproc_enable=False, W=64, H=32,
                video_init_path="/opt/a1111/td_inputs/comfy_videos/archive/a.mp4",
                video_mask_path="/opt/a1111/td_masks/mask_01.mov", use_mask_video=False, sweep_width=10)


@NEEDS_CV2
class SweepControllerTest(test_controller.FeedTest.__bases__[0]):
    setUp_base = test_controller.FeedTest.setUp
    state = test_controller.FeedTest.state
    tick = test_controller.FeedTest.tick
    posts = test_controller.FeedTest.posts
    DEPTH = "a_64x32_DepthAnythingV2Preprocessor_75f_00001.mp4"
    DEPTH_CONTAINER = "/opt/a1111/td_masks/preprocessed_vids/" + DEPTH

    def setUp(self):
        self.setUp_base()
        self.spawned = []

        def inline(target, *args):            # the background render runs right here
            self.spawned.append(args)
            target(*args)
        patcher = mock.patch.object(ctl, "_spawn", side_effect=inline)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, **overrides):
        self.root = make_network(dict(SWEEP_UI, **overrides), comp=True, prompt_rows=[("0", "gold", "")])
        self.ui = self.root.op("deforum")
        return self.ui

    def depth_on_share(self, frames=75):
        return write_depth_video(config.to_share(self.cfg, self.DEPTH_CONTAINER), frames=frames)

    def depth_done(self, on_share=True, frames=75):
        respond(self.root, "webclient_comfyui", 200, {"prompt_id": "p1", "number": 1, "node_errors": {}})
        self.tick()
        if on_share:
            self.depth_on_share(frames)
        respond(self.root, "webclient_comfyui", 200, {"p1": {
            "status": {"status_str": "success", "completed": True},
            "outputs": {"21": {"gifs": [{"filename": self.DEPTH, "subfolder": "preprocessed_vids"}]}}}})

    def sent(self):
        return json.loads(self.posts()[-1][2])["deforum_settings"]

    def run_to_render(self, **overrides):
        ui = self.make(**overrides)
        ctl.queue(self.root)
        self.depth_done()
        self.assertEqual(self.state(), ctl.SWEEP_RENDERING)
        self.tick()
        return ui

    def test_depth_then_sweep_then_render(self):
        ui = self.make()
        ctl.queue(self.root)
        self.assertEqual(self.state(), ctl.COMFY_SUBMITTED)
        job = json.loads(self.root.op("webclient_comfyui").requests[0][2])
        node = job["prompt"]["19"]
        self.assertEqual((node["class_type"], node["inputs"]["ckpt_name"]),
                         ("DepthAnythingV2Preprocessor", "depth_anything_v2_vits.pth"))
        self.depth_done()
        self.assertEqual(ui.par.Sweepdepthpath.val, self.DEPTH_CONTAINER)
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(self.state(), ctl.SWEEP_RENDERING)
        self.assertEqual(self.posts(), [])
        self.tick()                                   # result file found -> on to Deforum
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        s = self.sent()
        self.assertRegex(s["cn_1_vid_path"], r"^/opt/a1111/td_masks/feeds/cn_sweep_[0-9a-f]{10}\.mp4$")
        self.assertEqual(ui.par.Cn1vidpath.val, s["cn_1_vid_path"])
        self.assertIs(s["cn_1_enabled"], True)
        self.assertEqual(s["max_frames"], 75)
        share = config.to_share(self.cfg, s["cn_1_vid_path"])
        frames = read_video(share)
        self.assertEqual(len(frames), 75)
        self.assertGreater(white_columns(frames[0]).min(), 52)
        self.assertLess(white_columns(frames[-1]).max(), 12)
        self.assertEqual(ui.op("sweep_preview").par.file.val, share)
        self.assertIn("245-255 at the start", ui.par.Sweepinfo.val)
        self.assertIn("75 frames in", ui.par.Sweepinfo.val)

    def test_depth_video_is_downloaded_from_comfyui_when_not_on_the_share(self):
        fixture = write_depth_video(os.path.join(self.share, "fixture", "d.mp4"), frames=75)
        urls = []

        def fake_download(url, path, timeout=60.0):
            urls.append(url)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copyfile(fixture, path)
            return os.path.getsize(path)
        ui = self.make()
        ctl.queue(self.root)
        with mock.patch.object(sweep, "download", side_effect=fake_download):
            self.depth_done(on_share=False)
        self.assertEqual(len(urls), 1)
        self.assertIn(":8188/view?", urls[0])
        self.assertIn("subfolder=preprocessed_vids", urls[0])
        self.assertIn("type=output", urls[0])
        self.assertTrue(os.path.isfile(os.path.join(self.share, "td_masks", "comfy_fetch", self.DEPTH)))
        self.tick()
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        self.assertIn("cn_sweep_", self.sent()["cn_1_vid_path"])

    def test_a_depth_video_under_a_counterless_name_is_found_and_renamed(self):
        import urllib.error
        fixture = write_depth_video(os.path.join(self.share, "fixture", "d.mp4"), frames=75)
        real = self.DEPTH.replace("_00001", "")

        def comfy_view(url, path, timeout=60.0):
            if "filename=" + real not in url:                 # only the name VHS really wrote exists
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copyfile(fixture, path)
            return os.path.getsize(path)
        ui = self.make()
        ctl.queue(self.root)
        with mock.patch.object(sweep, "download", side_effect=comfy_view):
            self.depth_done(on_share=False)
            self.tick()
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        self.assertEqual(ui.par.Sweepdepthpath.val, "/opt/a1111/td_masks/preprocessed_vids/" + real)
        self.assertIn("/opt/a1111/td_masks/preprocessed_vids/" + real,
                      self.root.storage[ctl.CACHE_KEY].values())

    def test_a_depth_video_comfyui_no_longer_has_is_made_again_once(self):
        import urllib.error
        fixture = write_depth_video(os.path.join(self.share, "fixture", "d.mp4"), frames=75)
        jobs = {"n": 0}

        def view(url, path, timeout=60.0):
            if jobs["n"] < 2:                                 # gone under every name
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copyfile(fixture, path)
            return os.path.getsize(path)
        ui = self.make()
        ctl.queue(self.root)
        with mock.patch.object(sweep, "download", side_effect=view):
            jobs["n"] = 1
            self.depth_done(on_share=False)
            self.assertEqual(self.state(), ctl.SWEEP_RENDERING)
            self.tick()                                   # 404 everywhere -> forget it, new ComfyUI job
            self.assertEqual(self.state(), ctl.COMFY_SUBMITTED)
            self.assertEqual(ui.par.Sweepdepthpath.val, "")
            posts = [r for r in self.root.op("webclient_comfyui").requests if r[0] == "POST"]
            self.assertEqual(len(posts), 2)
            jobs["n"] = 2
            self.depth_done(on_share=False)
            self.tick()
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)

    def test_a_second_404_fails_with_the_url(self):
        import urllib.error

        def gone(url, path, timeout=60.0):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        ui = self.make()
        ctl.queue(self.root)
        with mock.patch.object(sweep, "download", side_effect=gone):
            self.depth_done(on_share=False)
            self.tick()
            self.depth_done(on_share=False)
            self.tick()
        self.assertEqual(self.state(), ctl.IDLE)
        status = ui.par.Pipelinestatus.val
        self.assertIn("ComfyUI has no depth video", status)
        self.assertIn("_0000N", status)
        self.assertIn("/view?", status)

    def test_second_queue_hits_both_caches(self):
        self.run_to_render()
        ctl.cancel(self.root)
        ctl.queue(self.root)
        posts = [r for r in self.root.op("webclient_comfyui").requests if r[0] == "POST"]
        self.assertEqual(len(posts), 1, "no second ComfyUI job")
        self.assertEqual(len(self.spawned), 1, "no second render")
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)

    def test_force_re_render_ignores_the_sweep_cache_only(self):
        ui = self.run_to_render()
        ctl.cancel(self.root)
        ui.par.Sweepforce = type(ui.par.Sweepwidth)("Sweepforce", True)
        preview = ui.op("sweep_preview")
        preview.par.file.val = self.spawned[0][0]["out_share"]      # TD shows the old sweep
        ctl.queue(self.root)
        posts = [r for r in self.root.op("webclient_comfyui").requests if r[0] == "POST"]
        self.assertEqual(len(posts), 1, "the depth video stays cached")
        self.assertEqual(len(self.spawned), 2, "the sweep renders again")
        self.assertEqual(self.spawned[1][0]["out_share"], self.spawned[0][0]["out_share"])
        self.assertEqual(preview.par.file.val, "", "the preview let go of the file it shows")
        self.assertEqual(self.state(), ctl.SWEEP_RENDERING)

    def test_changing_the_look_renders_again(self):
        ui = self.run_to_render()
        first = self.sent()["cn_1_vid_path"]
        ctl.cancel(self.root)
        ui.par.Sweepwidth.val = 30
        ctl.queue(self.root)
        self.assertEqual(len(self.spawned), 2)
        self.tick()
        self.assertNotEqual(self.sent()["cn_1_vid_path"], first)

    def test_mask_only_sets_the_video_mask(self):
        ui = self.run_to_render(cn_1_enabled=False, sweep_as_mask=True)
        s = self.sent()
        self.assertIs(s["use_mask_video"], True)
        self.assertIn("cn_sweep_", s["video_mask_path"])
        self.assertEqual(ui.par.Usemaskvideo.val, 1)

    def test_prepare_only_stops_after_the_sweep_with_a_preview(self):
        ui = self.make(sweep_prepare_only=True)
        ctl.queue(self.root)
        self.depth_done()
        self.tick()
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertIn("sweep ready", ui.par.Pipelinestatus.val)
        self.assertEqual(self.posts(), [])
        self.assertTrue(os.path.isfile(ui.op("sweep_preview").par.file.val))
        ui.par.Sweepprepareonly.val = 0                # now render with it: all cached
        ctl.queue(self.root)
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        self.assertEqual(len(self.spawned), 1)

    def test_a_short_init_video_is_learned_from_its_depth_video(self):
        ui = self.make()
        ctl.queue(self.root)
        self.depth_done(frames=40)
        self.tick()
        known = self.root.storage[ctl.FRAMES_KEY]
        self.assertEqual(known, {SWEEP_UI["video_init_path"]: 40})
        s = self.sent()
        self.assertEqual(s["max_frames"], 40)
        self.assertEqual(len(read_video(config.to_share(self.cfg, s["cn_1_vid_path"]))), 40)
        self.assertIn("at the end of 40 frames", ui.par.Sweepinfo.val)
        ctl.cancel(self.root)                         # next Queue: no new depth job, no new render
        ctl.queue(self.root)
        posts = [r for r in self.root.op("webclient_comfyui").requests if r[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        self.assertEqual(self.sent()["max_frames"], 40)

    def test_a_broken_depth_video_fails_with_the_reason(self):
        ui = self.make()
        ctl.queue(self.root)
        respond(self.root, "webclient_comfyui", 200, {"prompt_id": "p1", "number": 1, "node_errors": {}})
        self.tick()
        path = config.to_share(self.cfg, self.DEPTH_CONTAINER)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"not a video")
        respond(self.root, "webclient_comfyui", 200, {"p1": {
            "status": {"status_str": "success", "completed": True},
            "outputs": {"21": {"gifs": [{"filename": self.DEPTH, "subfolder": "preprocessed_vids"}]}}}})
        self.tick()
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertIn("Sweep Depth render failed", ui.par.Pipelinestatus.val)

    def test_premade_depth_video_skips_comfy(self):
        premade = "/opt/a1111/td_masks/preprocessed_vids/mine_depth.mp4"
        write_depth_video(config.to_share(self.cfg, premade), frames=75)
        ui = self.make(sweep_depth_video=premade)
        ctl.queue(self.root)
        self.assertEqual(self.root.op("webclient_comfyui").requests, [])
        self.assertEqual(ui.par.Sweepdepthpath.val, premade)
        self.tick()
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)

    def test_cancel_during_the_render_keeps_its_result_as_cache(self):
        self.make()
        ctl.queue(self.root)
        self.depth_done()
        ctl.cancel(self.root)
        self.assertEqual(self.state(), ctl.IDLE)
        ctl.queue(self.root)
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)

    def test_urllib_transport_runs_the_depth_stage(self):
        self.cfg["comfy_transport"] = "urllib"
        self.make()
        self.depth_on_share()
        calls = []

        def fake(method, url, data=None, timeout=15.0):
            calls.append((method, url))
            if method == "POST":
                return 200, json.dumps({"prompt_id": "p1", "number": 1, "node_errors": {}})
            return 200, json.dumps({"p1": {"status": {"status_str": "success", "completed": True},
                                           "outputs": {"21": {"gifs": [{"filename": self.DEPTH,
                                                                        "subfolder": "preprocessed_vids"}]}}}})
        with mock.patch.object(ctl, "_http", side_effect=fake):
            ctl.queue(self.root)
            self.assertEqual(self.state(), ctl.COMFY_RUNNING)
            self.tick()
        self.assertEqual([c[0] for c in calls], ["POST", "GET"])
        self.assertTrue(calls[0][1].endswith(":8188/prompt") and calls[1][1].endswith("/history/p1"))
        self.assertEqual(self.state(), ctl.SWEEP_RENDERING)
        self.assertEqual(self.root.op("webclient_comfyui").requests, [], "the Web Client DAT is not used")

    def test_urllib_failure_names_the_reason(self):
        self.cfg["comfy_transport"] = "urllib"
        ui = self.make()
        with mock.patch.object(ctl, "_http", side_effect=OSError("[WinError 10061] refused")):
            ctl.queue(self.root)
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertIn("WinError 10061", ui.par.Pipelinestatus.val)

    def test_comfy_rejection_text_reaches_the_status(self):
        self.cfg["comfy_transport"] = "urllib"
        ui = self.make()
        bad = json.dumps({"error": {"message": "Prompt outputs failed validation"}, "node_errors": {}})
        with mock.patch.object(ctl, "_http", return_value=(400, bad)):
            ctl.queue(self.root)
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertIn("rejected the workflow (HTTP 400)", ui.par.Pipelinestatus.val)

    def test_unreachable_comfyui_fails_at_once_with_the_address(self):
        ui = self.make()
        ctl.queue(self.root)
        self.assertEqual(self.state(), ctl.COMFY_SUBMITTED)
        ctl.on_error(self.root, self.root.op("webclient_comfyui"), "connection refused")
        self.assertEqual(self.state(), ctl.IDLE)
        status = ui.par.Pipelinestatus.val
        self.assertIn("could not reach ComfyUI", status)
        self.assertIn(":8188", status)

    def test_doctor_checks_the_ports_and_explains_hidden_folders(self):
        self.make(sweep_depth_path=self.DEPTH_CONTAINER)
        with mock.patch.object(ctl, "_reachable",
                               side_effect=lambda h, p, t=2.0: "open" if p == 7865 else "NOT reachable (x)"):
            with mock.patch("builtins.print") as out:
                ctl.doctor(self.root)
        text = "\n".join(str(c.args[0]) for c in out.call_args_list if c.args)
        self.assertIn("7865 open", text)
        self.assertIn("8188 NOT reachable (x)", text)
        self.assertIn("Samba does not follow it", text)
        self.assertIn("downloaded from ComfyUI at Queue", text)

    def test_preview_reports_the_sweep(self):
        self.make()
        with mock.patch("builtins.print") as out:
            ctl.preview(self.root)
        text = "\n".join(str(c.args[0]) for c in out.call_args_list if c.args)
        self.assertIn("sweep: max sweep", text)
        self.assertIn("245-255 at the start", text)
        self.assertIn("-> ControlNet 1", text)

    def test_hybrid_2d_render_uses_the_sweep_as_its_guide(self):
        ui = self.make(animation_mode="2D", hybrid_motion="Optical Flow", hybrid_composite="None")
        ctl.queue(self.root)
        self.depth_done()
        self.tick()
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        s = self.sent()
        self.assertEqual((s["animation_mode"], s["hybrid_motion"]), ("2D", "Optical Flow"))
        self.assertIs(s["hybrid_generate_inputframes"], True)
        self.assertIn("cn_sweep_", s["cn_1_vid_path"])
        self.assertEqual(len(read_video(config.to_share(self.cfg, s["cn_1_vid_path"]))), s["max_frames"])

    def test_wrong_animation_mode_fails_with_a_reason(self):
        self.make(animation_mode="Interpolation")
        ctl.queue(self.root)
        self.assertEqual(self.root.op("webclient_comfyui").requests, [])
        self.assertIn("Video Input", self.ui.par.Pipelinestatus.val)


class LiveValuesTest(unittest.TestCase):
    VALUES = {"bpm": 120.0, "beats_per_bar": 4, "loop_bars": 2, "out_fps": 60, "render_strategy": "cadence",
              "render_fps": "30", "length_source": "tempo", "seamless_loop": False, "loop_overlap_beats": 0,
              "translation_z": 0.5, "zoom": 1.0, "chop_mode": "add",
              "mod1_active": True, "mod1_target": "translation_z", "mod1_shape": "sine", "mod1_beats": 1.0,
              "mod1_depth": 1.0, "mod1_phase": 0.0, "mod1_sharpness": 4.0}

    def test_matches_the_render_curve(self):
        values = dict((f.api, f.default) for f in schema.FIELDS)
        values.update(self.VALUES)
        tp = payload.tempo_plan(values)
        live = payload.live_values(values, None, 7.5, 60.0)       # a quarter beat into the loop
        t = 7.5 * tp["render_fps"] / 60.0
        slot = modulation.Slot("translation_z", "sine", 1.0, 1.0)
        self.assertAlmostEqual(live["translation_z"], modulation.evaluate(0.5, [slot], tp["fpb"], t))
        self.assertAlmostEqual(live["translation_z"], 1.5, places=6)
        self.assertAlmostEqual(live["render_frame"], t)
        self.assertNotIn("zoom", live, "unmodulated parameters are left out")

    def test_raw_override_is_left_out_and_chop_adds(self):
        values = dict((f.api, f.default) for f in schema.FIELDS)
        values.update(self.VALUES)
        values["translation_z:raw"] = "0:(3)"
        live = payload.live_values(values, {"zoom": [0.0, 0.1]}, 0.0, 60.0)
        self.assertNotIn("translation_z", live)
        self.assertAlmostEqual(live["zoom"], 1.0)

    def test_script_chop_cook(self):
        values = dict((f.api, f.default) for f in schema.FIELDS)
        values.update(self.VALUES)
        root = make_network(values, comp=True, prompt_rows=[("0", "gold", "")])
        ui = root.op("deforum")

        class Chan(list):
            pass

        class FakeScript(object):
            def __init__(self):
                self.inputs = [{"loop_frame": [7.5]}]
                self.time = type("T", (), {"rate": 60.0})()
                self.chans = {}
                self.numSamples = 0

            def parent(self):
                return ui

            def clear(self):
                self.chans = {}

            def appendChan(self, name):
                self.chans[name] = Chan([0.0])
                return self.chans[name]
        op_ = FakeScript()
        ctl.mod_live_cook(op_)
        self.assertEqual(op_.numSamples, 1)
        self.assertAlmostEqual(op_.chans["translation_z"][0], 1.5, places=5)
        self.assertIn("render_frame", op_.chans)


if __name__ == "__main__":
    unittest.main()
