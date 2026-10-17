"""Loop length when a render is capped, Fit Loop to Init Video, output 3 filled in by tick()."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from _fakes import make_network
from tdeforum import config, payload, td_controller as ctl

from test_controller import TEMPO_UI


class LoopCapTest(unittest.TestCase):
    def values(self, **kw):
        v = dict(TEMPO_UI, bpm=150.0, loop_bars=16, render_fps="20", seamless_loop=False,
                 animation_mode="Video Input", mod1_active=False)
        v.update(kw)
        return v

    def test_capped_render_loops_what_was_rendered(self):
        result = payload.build_request(self.values(), frame_counter=lambda path: 380)
        self.assertEqual(result["plan"]["max_frames"], 380)
        expect = ctl._expectation(result)
        self.assertEqual((expect["out_loop"], expect["overlap_out"]), (380 * 3, 0))   # not 1536

    def test_fit_bars(self):
        # 150 bpm at 20 fps: 8 frames a beat, 32 a bar; 380 frames hold 11 bars
        self.assertEqual(payload.fit_bars(self.values(), 380), 11)
        # seamless with a 2-beat overlap needs 16 more frames: still 11 (352 + 16 <= 380)
        self.assertEqual(payload.fit_bars(self.values(seamless_loop=True, loop_overlap_beats=2.0), 380), 11)
        self.assertEqual(payload.fit_bars(self.values(seamless_loop=True, loop_overlap_beats=2.0), 360), 10)
        self.assertIsNone(payload.fit_bars(self.values(video_frame_mode="stride"), 380))
        self.assertEqual(payload.fit_bars(self.values(), 10), 1)


class InputPendingTest(unittest.TestCase):
    def setUp(self):
        self.share = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.share)
        self.root = make_network(dict(TEMPO_UI), comp=True)
        self.ui = self.root.op("deforum")

    def test_output_three_fills_in_when_the_conform_finishes(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV not installed")
        src = self.share + "/in.mp4"
        writer = cv2.VideoWriter(src, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (32, 18))
        for i in range(20):
            writer.write(np.full((18, 32, 3), i * 12, np.uint8))
        writer.release()
        from tdeforum import inputloop
        job = inputloop.make_job(src, self.share + "/feeds", "/opt/a1111/td_masks/feeds", (64, 36), 4, 2, 6, 20)
        info = {"share": src, "start": 4, "stride": 2, "rate": 1.0, "job": job}
        queued = []
        with mock.patch.object(ctl, "_spawn", side_effect=lambda target, *args: queued.append((target, args))):
            ctl._load_input(self.root, self.ui, info)
            self.assertEqual(self.ui.op("in_head").par.file.val, "")          # still conforming
            target, args = queued[0]
            target(*args)                                                      # the thread finishes
            ctl._poll_input(self.root)
        self.assertEqual(self.ui.op("in_head").par.file.val, job["out_share"])
        self.assertEqual((self.ui.par.Loopinstart.val, self.ui.par.Loopinstride.val), ("0", "1"))
        capture = cv2.VideoCapture(job["out_share"])
        self.assertEqual(int(capture.get(7)), 6)                               # frames 4, 6, ... 14
        means = []
        for _ in range(2):
            ok, frame = capture.read()
            means.append(float(frame.mean()))
        self.assertEqual(min((36, 48, 60), key=lambda v: abs(v - means[0])), 48)    # source frame 4
        self.assertAlmostEqual(means[1] - means[0], 24, delta=8)                     # stride 2
        capture.release()
        self.assertIsNone(self.root.fetch(ctl.INPUT_PENDING_KEY))


if __name__ == "__main__":
    unittest.main()
