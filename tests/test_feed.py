"""ControlNet guide feeds: the frame plan and paths (pure Python)."""

import unittest

from _fakes import ROOT_DIR  # noqa: F401  (puts scripts/ on sys.path)
from tdeforum import config, feed, tempo


class FramePlanTest(unittest.TestCase):
    def test_cadence_120bpm_wraps_the_overlap_onto_the_loop_start(self):
        tp = tempo.plan(bpm=120, bars=2, strategy="cadence", overlap_beats=1.0)
        plan = feed.frame_plan(tp, tp["max_frames"], 60, 1)
        frames = plan["frames"]
        self.assertEqual((len(frames), plan["step"], plan["loop"]), (270, 1, 240))
        self.assertEqual((frames[0], frames[239], frames[240], frames[269]), (1, 240, 1, 30))
        self.assertEqual(plan["warnings"], [])

    def test_interpolate_samples_every_second_timeline_frame(self):
        tp = tempo.plan(bpm=120, bars=1, strategy="interpolate", render_fps=30, overlap_beats=1.0)
        plan = feed.frame_plan(tp, tp["max_frames"], 60, 1)
        frames = plan["frames"]
        self.assertEqual((len(frames), plan["step"], plan["loop"]), (75, 2, 120))
        self.assertEqual(frames[:3], [1, 3, 5])
        self.assertEqual((frames[59], frames[60], frames[74]), (119, 1, 29))

    def test_each_tempo_covers_one_loop_of_the_timeline(self):
        for bpm, per_beat in ((90, 40), (120, 30), (150, 24)):
            tp = tempo.plan(bpm=bpm, bars=1, strategy="cadence", overlap_beats=0)
            plan = feed.frame_plan(tp, tp["max_frames"], 60, 1)
            self.assertEqual(plan["loop"], 4 * per_beat)
            self.assertEqual(plan["frames"][-1], 4 * per_beat)

    def test_manual_length_is_sequential_from_the_start_frame(self):
        plan = feed.frame_plan(None, 5, 60, 10)
        self.assertEqual((plan["frames"], plan["step"], plan["loop"]), ([10, 11, 12, 13, 14], 1, None))

    def test_unsamplable_rates_are_refused(self):
        tp = tempo.plan(bpm=120, bars=1, strategy="interpolate", render_fps=20)
        with self.assertRaises(ValueError):
            feed.frame_plan(tp, 10, 50, 1)           # 50 / 20 = 2.5
        tp = tempo.plan(bpm=120, bars=1, strategy="cadence")
        with self.assertRaises(ValueError):
            feed.frame_plan(tp, 10, 30, 1)           # timeline slower than the render

    def test_drifting_loop_is_reported(self):
        tp = tempo.plan(bpm=100, bars=1, strategy="cadence")      # 4 beats = 144 frames at 60: whole
        self.assertEqual(feed.frame_plan(tp, 10, 60, 1)["warnings"], [])
        tp = tempo.plan(bpm=97, bars=1, strategy="cadence")
        self.assertTrue(feed.frame_plan(tp, 10, 60, 1)["warnings"])

    def test_describe(self):
        tp = tempo.plan(bpm=120, bars=2, strategy="cadence", overlap_beats=1.0)
        text = feed.describe(feed.frame_plan(tp, tp["max_frames"], 60, 1))
        self.assertEqual(text, "270 frames, timeline 1..240, wrapping at 240")


class RequestsAndPathsTest(unittest.TestCase):
    def test_only_enabled_top_units_are_requested(self):
        values = {"cn_1_enabled": True, "feed_1_mode": "top_loop", "feed_1_top": " /project1/final_out ",
                  "cn_2_enabled": False, "feed_2_mode": "top_still", "feed_2_top": "/project1/x",
                  "cn_3_enabled": True, "feed_3_mode": "file"}
        wants = feed.requests(values)
        self.assertEqual([(w.unit, w.mode, w.top) for w in wants], [(1, "top_loop", "/project1/final_out")])

    def test_unknown_mode_is_treated_as_file(self):
        self.assertEqual(feed.mode_of({"feed_1_mode": "bogus"}, 1), feed.FILE)
        self.assertEqual(feed.requests({"cn_1_enabled": True, "feed_1_mode": "bogus"}), [])

    def test_paths_map_to_the_share(self):
        cfg = config.load()
        self.assertEqual(feed.container_path(cfg, 2, feed.TOP_LOOP), "/opt/a1111/td_masks/feeds/cn2_feed.mp4")
        self.assertEqual(feed.container_path(cfg, 1, feed.TOP_STILL), "/opt/a1111/td_masks/feeds/cn1_feed.png")
        self.assertTrue(feed.share_path(cfg, 2, feed.TOP_LOOP).endswith("td_masks/feeds/cn2_feed.mp4"))
        cfg = dict(cfg, cn_feed_ext=".mov")
        self.assertTrue(feed.container_path(cfg, 1, feed.TOP_LOOP).endswith(".mov"))

    def test_verify(self):
        self.assertEqual(feed.verify(75, 75), (True, "75 frames"))
        self.assertFalse(feed.verify(75, 70)[0])
        self.assertTrue(feed.verify(75, 76)[0])
        self.assertTrue(feed.verify(75, None)[0])

    def test_is_video(self):
        self.assertTrue(feed.is_video("/a/b/c.MOV"))
        self.assertFalse(feed.is_video("/a/b/c.png"))


if __name__ == "__main__":
    unittest.main()
