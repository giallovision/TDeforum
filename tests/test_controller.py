"""Drive td_controller through whole pipeline runs with fake TD objects."""

import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from _fakes import ROOT_DIR, Channel, ParMode, make_network
from tdeforum import config, td_controller as ctl

UI = {
    "sd_model_checkpoint": "0", "W": 1024, "H": 576, "max_frames": 120, "animation_mode": "3D",
    "seed": "-1", "n_prompt": "text", "use_mask_video": False, "video_frame_mode": "trim",
    "video_init_path": "/opt/a1111/td_inputs/comfy_videos/archive/a.mp4",
    "cn_1_enabled": True, "cn_1_vid_path": "/opt/a1111/td_masks/mask_01.mov",
    "comfy_preproc_enable": False, "comfy_preprocessor": "PiDiNetPreprocessor",
    "pipeline_status": "idle", "auto_load": True, "force_preprocess": False,
    "bake_points": 3, "bake_target": "translation_z", "translation_z": "0:(0)", "zoom": "0:(1.0)",
}


def respond(root, dat_name, code, body):
    data = json.dumps(body).encode() if body is not None else b""
    ctl.on_response(root, root.op(dat_name), {"code": code, "message": ""}, data)


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.share = tempfile.mkdtemp()
        cfg = config.load()
        cfg.update(share_root=self.share + "/", runtime_dir=self.share + "/runtime",
                   prompt_file=self.share + "/prompt.json",
                   comfy_template=os.path.join(ROOT_DIR, "scripts", "templates", "TD_CN_PreProc.json"),
                   poll_interval_s=0.0, comfy_transport="webclient")
        with open(cfg["prompt_file"], "w") as fh:
            json.dump({"0": "liquid gold"}, fh)
        self.cfg = cfg
        patcher = mock.patch.object(config, "load", return_value=cfg)
        patcher.start()
        self.addCleanup(patcher.stop)
        ports = mock.patch.object(ctl, "_reachable", return_value="open")
        ports.start()
        self.addCleanup(ports.stop)
        http = mock.patch.object(ctl, "_http", return_value=(200, "{}"))
        http.start()
        self.addCleanup(http.stop)
        self.addCleanup(shutil.rmtree, self.share)
        self.root = make_network(dict(UI))

    def state(self):
        return self.root.storage[ctl.STATE_KEY]["state"]

    def tick(self):
        self.root.storage[ctl.STATE_KEY]["last_tick"] = 0
        ctl.tick(self.root)

    def test_full_render_and_autoload(self):
        ctl.queue(self.root)
        posts = self.root.op("webclient_deforum").requests
        self.assertEqual(len(posts), 1, "exactly one batch per Queue press")
        body = json.loads(posts[0][2])
        self.assertEqual(body["deforum_settings"]["animation_prompts_negative"], "text")
        self.assertTrue(os.path.isfile(self.share + "/runtime/last_deforum_payload.json"))

        ctl.queue(self.root)  # second press while busy is ignored
        self.assertEqual(len(posts), 1)

        respond(self.root, "webclient_deforum", 202,
                {"message": "Job(s) accepted", "batch_id": "batch(1)", "job_ids": ["batch(1)-0"]})
        self.assertEqual(self.state(), ctl.DEFORUM_RUNNING)

        self.tick()
        polls = self.root.op("webclient_progress").requests
        # Built from the loaded config so a scripts/tdeforum.local.json override
        # (e.g. server_host) does not break the test.
        expected = config.deforum_url(config.load(), "/deforum_api/jobs/batch(1)-0")
        self.assertEqual(polls[-1][:2], ("GET", expected))

        respond(self.root, "webclient_progress", 200,
                {"id": "batch(1)-0", "status": "ACCEPTED", "phase": "GENERATING", "phase_progress": 0.4})
        self.assertIn("40%", self.root.op("Deforum_UI").par.Pipelinestatus.val)

        outdir = "/opt/a1111/outputs/img2img-images/Deforum_20261016120000"
        respond(self.root, "webclient_progress", 200,
                {"id": "batch(1)-0", "status": "SUCCEEDED", "phase": "DONE", "phase_progress": 1.0,
                 "outdir": outdir, "timestring": "20261016120000", "execution_time": 90})
        self.assertEqual(self.state(), ctl.WAITING_FILE)
        expected = self.share + "/td_outputs/img2img-images/Deforum_20261016120000/20261016120000.mp4"
        self.assertEqual(self.root.storage[ctl.STATE_KEY]["video_share"], expected)

        os.makedirs(os.path.dirname(expected))
        with open(expected, "wb") as fh:
            fh.write(b"x" * 100)
        self.tick()  # size seen once
        self.assertEqual(self.state(), ctl.WAITING_FILE)
        self.tick()  # size stable -> load
        self.assertEqual(self.state(), ctl.IDLE)
        movie = self.root.op("moviefilein1")
        self.assertEqual(movie.par.file.val, expected)
        self.assertEqual(movie.par.file.mode, ParMode.CONSTANT)
        self.assertEqual(movie.par.reloadpulse.pulses, 1)

    def test_rejected_batch_goes_idle(self):
        ctl.queue(self.root)
        respond(self.root, "webclient_deforum", 422, {"detail": "bad"})
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertIn("error", self.root.op("Deforum_UI").par.Pipelinestatus.val)

    def test_failed_job(self):
        ctl.queue(self.root)
        respond(self.root, "webclient_deforum", 202, {"batch_id": "b", "job_ids": ["b-0"]})
        respond(self.root, "webclient_progress", 200,
                {"id": "b-0", "status": "FAILED", "phase": "GENERATING", "message": "CUDA OOM"})
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertIn("CUDA OOM", self.root.storage[ctl.STATE_KEY]["last_result"])

    def test_submit_timeout(self):
        ctl.queue(self.root)
        self.root.storage[ctl.STATE_KEY]["submitted"] = time.time() - 999
        self.tick()
        self.assertEqual(self.state(), ctl.IDLE)

    def test_comfy_then_render_and_cache(self):
        ui = self.root.op("Deforum_UI")
        ui.par.Comfypreprocenable.val = True
        ctl.queue(self.root)
        comfy_dat = self.root.op("webclient_comfyui")
        self.assertEqual(len(comfy_dat.requests), 1)
        self.assertEqual(self.root.op("webclient_deforum").requests, [])

        respond(self.root, "webclient_comfyui", 200, {"prompt_id": "p1", "number": 1, "node_errors": {}})
        self.tick()
        self.assertTrue(comfy_dat.requests[-1][1].endswith("/history/p1"))
        respond(self.root, "webclient_comfyui", 200, {})  # still running
        self.assertEqual(self.state(), ctl.COMFY_RUNNING)
        respond(self.root, "webclient_comfyui", 200, {"p1": {
            "status": {"status_str": "success", "completed": True},
            "outputs": {"21": {"gifs": [{"filename": "a_1024x576_PiDiNetPreprocessor_120f_00001.mp4",
                                          "subfolder": "preprocessed_vids"}]}}}})
        cn_path = "/opt/a1111/td_masks/preprocessed_vids/a_1024x576_PiDiNetPreprocessor_120f_00001.mp4"
        self.assertEqual(ui.par.Cn1vidpath.val, cn_path)
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        sent = json.loads(self.root.op("webclient_deforum").requests[-1][2])
        self.assertEqual(sent["deforum_settings"]["cn_1_vid_path"], cn_path)

        # Same settings again: cache hit, straight to Deforum.
        ctl.cancel(self.root)
        ctl.queue(self.root)
        self.assertEqual(len(comfy_dat.requests), 2)  # no new /prompt
        self.assertEqual(len(self.root.op("webclient_deforum").requests), 2)

    def test_cancel_running_job(self):
        ctl.queue(self.root)
        respond(self.root, "webclient_deforum", 202, {"batch_id": "b", "job_ids": ["b-0"]})
        ctl.cancel(self.root)
        self.assertEqual(self.root.op("webclient_progress").requests[-1][0], "DELETE")
        self.assertEqual(self.state(), ctl.IDLE)

    def test_latest_render(self):
        paths = ["x/Deforum_1/20260101000000.mp4", "x/Deforum_2/20260301000000_depth.mp4",
                 "x/Deforum_2/20260201000000.mp4"]
        self.assertEqual(ctl.latest_render(paths), "x/Deforum_2/20260201000000.mp4")


TEMPO_UI = dict(UI, **{
    "bpm": 120.0, "beats_per_bar": 4, "loop_bars": 1, "out_fps": 60,
    "render_strategy": "interpolate", "render_fps": "30", "interp_engine": "RIFE v4.6",
    "seamless_loop": True, "loop_overlap_beats": 1.0, "loop_seeds": True, "length_source": "tempo",
    "seed_behavior": "iter", "prompt_source": "sequence", "prompt_xfade_beats": 1.0,
    "translation_z": 0.0, "zoom": 1.0, "rotation_3d_y": 0.0, "strength_schedule": 0.6,
    "mod1_active": True, "mod1_target": "translation_z", "mod1_shape": "decay", "mod1_beats": 1.0,
    "mod1_depth": 2.0, "mod1_phase": 0.0, "mod1_sharpness": 6.0,
    "chop_mode": "add", "chop_path": "", "bake_points": 0,
})
STAMP = "20261016120000"
OUTDIR = "/opt/a1111/outputs/img2img-images/Deforum_" + STAMP


class TempoCompTest(ControllerTest.__bases__[0]):
    """The 'deforum' COMP: tempo plan, mod matrix, Mod CHOP, prompt sequence, loop player."""

    setUp = ControllerTest.setUp
    state = ControllerTest.state
    tick = ControllerTest.tick

    def make(self, **overrides):
        self.root = make_network(dict(TEMPO_UI, **overrides), comp=True,
                                 prompt_rows=[("0", "gold", ""), ("2", "ice", "")],
                                 chop={"rotation_3d_y": [0.0, 1.0], "wave3": [5.0]})
        return self.root.op("deforum")

    def finish(self):
        respond(self.root, "webclient_deforum", 202, {"batch_id": "b", "job_ids": ["b-0"]})
        respond(self.root, "webclient_progress", 200,
                {"id": "b-0", "status": "SUCCEEDED", "phase": "DONE", "phase_progress": 1.0,
                 "outdir": OUTDIR, "timestring": STAMP, "execution_time": 60})

    def write(self, name):
        path = self.share + "/td_outputs/img2img-images/Deforum_%s/%s" % (STAMP, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"x" * 100)
        return path

    def test_tempo_request(self):
        ui = self.make()
        ctl.queue(self.root)
        s = json.loads(self.root.op("webclient_deforum").requests[0][2])["deforum_settings"]
        # 120 bpm at 30 fps: 15 frames/beat, 4-beat loop + 1 beat overlap
        self.assertEqual((s["fps"], s["max_frames"]), (30, 75))
        self.assertEqual((s["frame_interpolation_engine"], s["frame_interpolation_x_amount"]), ("RIFE v4.6", 2))
        self.assertIs(s["store_frames_in_ram"], False)
        self.assertEqual((s["seed_behavior"], s["seed_schedule"]), ("schedule", "0:(s + t%60)"))
        self.assertIn("exp(-6*((t/15.0) % 1))", s["translation_z"])
        self.assertTrue(s["rotation_3d_y"].startswith("0:(0.00000), 1:("))   # baked from the CHOP
        self.assertEqual(s["strength_schedule"], "0:(0.6)")
        self.assertIn("gold :`(30 - t)/15.0` AND ice", s["prompts"]["15"])
        self.assertEqual(s["prompts"]["60"], "gold")
        self.assertIn("120 bpm", ui.par.Tempoinfo.val)

    def test_interpolated_file_and_loop_player(self):
        ui = self.make()
        ctl.queue(self.root)
        self.finish()
        st = self.root.storage[ctl.STATE_KEY]
        self.assertTrue(st["video_share"].endswith("/%s_RIFE_x2.mp4" % STAMP))
        path = self.write("%s_RIFE_x2.mp4" % STAMP)
        self.tick()
        self.tick()
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertEqual(ui.op("loop_head").par.file.val, path)
        self.assertEqual(ui.op("loop_tail").par.file.val, path)
        self.assertEqual(ui.par.Loopoutframes.val, "120")      # 4 beats at 60 fps
        self.assertEqual(ui.par.Loopoutoverlap.val, "30")      # 15 render frames x2
        self.assertEqual(ui.par.Loopoutrate.val, "1")

    def test_missing_interpolation_falls_back_to_plain_render(self):
        ui = self.make()
        ctl.queue(self.root)
        self.finish()
        plain = self.write(STAMP + ".mp4")
        self.root.storage[ctl.STATE_KEY]["waiting_since"] = time.time() - ctl.INTERP_FALLBACK_S - 1
        self.tick()
        self.tick()
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertEqual(ui.op("loop_head").par.file.val, plain)
        self.assertEqual(ui.par.Loopoutrate.val, "0.5")        # 30 fps file on a 60 fps loop

    def test_cadence_mode_loads_plain_file(self):
        ui = self.make(render_strategy="cadence")
        ctl.queue(self.root)
        s = json.loads(self.root.op("webclient_deforum").requests[0][2])["deforum_settings"]
        self.assertEqual((s["fps"], s["max_frames"], s["frame_interpolation_engine"]), (60, 150, "None"))
        self.finish()
        self.assertTrue(self.root.storage[ctl.STATE_KEY]["video_share"].endswith("/%s.mp4" % STAMP))

    def test_preview_table(self):
        ui = self.make()
        result = ctl.preview(self.root)
        rows = ui.op("schedule_preview").rows
        self.assertEqual(rows[0], ["parameter", "mode", "schedule"])
        self.assertEqual(rows[1][:2], ["translation_z", "expression"])
        self.assertEqual(rows[2][:2], ["rotation_3d_y", "baked"])
        self.assertTrue(any(r[0] == "prompt @15" for r in rows))
        self.assertTrue(any("wave3" in w for w in result["warnings"]))
        self.assertEqual(self.root.op("webclient_deforum").requests, [])   # nothing sent

    def test_old_ui_still_renders_without_the_comp(self):
        root = make_network(dict(UI))
        self.assertEqual(ctl._op(root, "ui").name, "Deforum_UI")


FEED_UI = dict(TEMPO_UI, mod1_active=False, cn_1_enabled=True, feed_1_mode="top_loop",
               feed_1_top="/project1/final_out", feed_loop_start=0)


class FeedTest(ControllerTest.__bases__[0]):
    """ControlNet guide feeds recorded from a TOP at Queue."""

    setUp = ControllerTest.setUp
    state = ControllerTest.state
    tick = ControllerTest.tick

    def make(self, **overrides):
        self.root = make_network(dict(FEED_UI, **overrides), comp=True,
                                 prompt_rows=[("0", "gold", "")])
        self.ui = self.root.op("deforum")
        self.timeline = self.root.timeline
        self.out = self.ui.op("feed1_out")
        return self.ui

    def record_all(self, limit=500):
        """Run Frame End callbacks until the recording finishes (one callback per TD frame)."""
        for _ in range(limit):
            if self.state() != ctl.CAPTURING:
                return
            self.step()
        self.fail("capture never finished")

    def step(self, source="frameend"):
        """One TouchDesigner frame: the timeline advances, then Frame End fires."""
        self.timeline.advance()
        ctl.capture_tick(self.root, source)

    def posts(self):
        return self.root.op("webclient_deforum").requests

    def feed_file(self, n=1):
        path = self.share + "/td_masks/feeds/cn%d_feed.mp4" % n
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"x" * 200)
        return path

    def test_loop_capture_end_to_end(self):
        ui = self.make()
        self.timeline.frame, self.timeline.play = 42, True
        ctl.queue(self.root)
        self.assertEqual(self.state(), ctl.CAPTURING)
        self.assertEqual(self.posts(), [], "nothing is rendered before the guide exists")
        self.assertEqual((self.timeline.play, self.timeline.frame), (True, 1))
        self.assertEqual(ui.op("feed1_sel").par.top.val, "/project1/final_out")
        self.assertEqual(self.out.par.file.val, self.share + "/td_masks/feeds/cn1_feed.mp4")

        self.record_all()
        self.assertEqual(self.state(), ctl.WAITING_FEED)
        # 75 render frames at 30 fps from a 60 fps timeline: every second frame, wrapping at 120.
        expected = [1 + (2 * k) % 120 for k in range(75)]
        self.assertEqual(self.out.recorded, expected)
        self.assertEqual(self.out.par.addframe.pulses, 75)
        self.assertEqual(self.out.par.record.val, 0)
        self.assertEqual((self.timeline.play, self.timeline.frame), (True, 42), "timeline given back")
        self.assertEqual(self.posts(), [])

        path = self.feed_file()
        with mock.patch.object(ctl, "_frame_counter", return_value=lambda container: 75):
            self.tick()                                  # size seen once
            self.assertEqual(self.state(), ctl.WAITING_FEED)
            self.tick()                                  # size stable -> verified -> render
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        s = json.loads(self.posts()[0][2])["deforum_settings"]
        self.assertEqual(s["cn_1_vid_path"], "/opt/a1111/td_masks/feeds/cn1_feed.mp4")
        self.assertIs(s["cn_1_enabled"], True)
        self.assertEqual(s["max_frames"], 75)
        self.assertEqual(ui.par.Cn1vidpath.val, "/opt/a1111/td_masks/feeds/cn1_feed.mp4")
        self.assertIn("75 frames", ui.par.Feed1info.val)
        self.assertTrue(os.path.isfile(path))

    def test_continuous_method_records_every_cooked_frame(self):
        ui = self.make(feed_method="continuous")
        ctl.queue(self.root)
        for _ in range(500):
            if self.state() != ctl.CAPTURING:
                break
            self.timeline.advance()
            for unit in (1, 2, 3):                      # a TD frame cooks, then Frame End fires
                mfo = ui.op("feed%d_out" % unit)
                if mfo.par.record.val and not mfo.par.pause.val:
                    mfo.recorded.append(self.timeline.frame)
            ctl.capture_tick(self.root)
        self.assertEqual(self.state(), ctl.WAITING_FEED)
        self.assertEqual(self.out.recorded, [1 + (2 * k) % 120 for k in range(75)])
        self.assertEqual(self.out.par.addframe.pulses, 0)

    def test_two_units_record_in_one_pass(self):
        ui = self.make(cn_2_enabled=True, feed_2_mode="top_loop", feed_2_top="/project1/final_out",
                       cn_2_vid_path="")
        ctl.queue(self.root)
        self.record_all()
        self.assertEqual(ui.op("feed2_out").recorded, self.out.recorded)
        self.assertEqual(ui.op("feed2_out").par.file.val, self.share + "/td_masks/feeds/cn2_feed.mp4")

    def test_feed_too_short_stops_the_render(self):
        self.make()
        ctl.queue(self.root)
        self.record_all()
        self.feed_file()
        with mock.patch.object(ctl, "_frame_counter", return_value=lambda container: 70):
            self.tick()
            self.tick()
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertIn("recorded 70 frames, expected 75", self.root.storage[ctl.STATE_KEY]["last_result"])
        self.assertEqual(self.posts(), [])

    def test_feed_file_never_appears(self):
        self.make()
        ctl.queue(self.root)
        self.record_all()
        self.root.storage[ctl.STATE_KEY]["waiting_since"] = time.time() - ctl.FEED_FINALIZE_TIMEOUT_S - 1
        self.tick()
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertIn("did not appear", self.root.storage[ctl.STATE_KEY]["last_result"])

    def test_short_timeline_is_extended_and_restored(self):
        self.make()
        self.timeline.end = self.timeline.rangeEnd = 60
        ctl.queue(self.root)
        self.assertEqual(self.timeline.rangeEnd, 119)
        self.record_all()
        self.assertEqual(self.out.recorded, [1 + (2 * k) % 120 for k in range(75)])
        self.assertEqual((self.timeline.end, self.timeline.rangeEnd), (60, 60))

    def test_stray_jump_is_corrected(self):
        self.make()
        self.timeline.frame, self.timeline.play = 47, True
        ctl.queue(self.root)
        for i in range(20):
            self.step()
        self.timeline._frame = 500                      # a script moved it once
        self.record_all()
        self.assertEqual(self.state(), ctl.WAITING_FEED)
        self.assertEqual(self.out.recorded, [1 + (2 * k) % 120 for k in range(75)])

    def test_setting_the_frame_may_land_one_past(self):
        self.make()
        self.timeline.lands_past = 1
        ctl.queue(self.root)
        self.record_all()
        self.assertEqual(self.state(), ctl.WAITING_FEED)
        self.assertEqual(self.out.recorded, [1 + (2 * k) % 120 for k in range(75)])

    def test_timeline_that_is_held_elsewhere_fails_clearly_and_restores(self):
        self.make()
        self.timeline.frame, self.timeline.play = 7, True
        ctl.queue(self.root)
        for _ in range(60):
            if self.state() != ctl.CAPTURING:
                break
            self.timeline.advance()
            self.timeline._frame = 500                  # something else keeps driving it
            ctl.capture_tick(self.root)
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertIn("something else driving the timeline", self.root.storage[ctl.STATE_KEY]["last_result"])
        self.assertEqual(self.out.par.record.val, 0)
        self.assertEqual((self.timeline.play, self.timeline.frame), (True, 7))
        self.assertEqual(self.posts(), [])

    def test_stalled_frame_end_falls_back_to_run_chain(self):
        self.make()
        self.timeline.frame, self.timeline.play = 47, True
        scheduled = []
        original = ctl._schedule_run
        self.addCleanup(setattr, ctl, "_schedule_run", original)
        ctl._schedule_run = lambda root: scheduled.append(1)
        ctl.queue(self.root)
        self.step()                                     # Frame End works for a moment, then stops
        st = self.root.storage[ctl.STATE_KEY]
        st["updated"] -= 60
        st["last_tick"] = 0
        self.tick()
        self.assertEqual(self.root.storage[ctl.STATE_KEY]["driver"], "run")
        self.step()                                     # a late Frame End is ignored now
        before = self.root.storage[ctl.STATE_KEY]["since_set"]
        self.step()
        self.assertEqual(self.root.storage[ctl.STATE_KEY]["since_set"], before)
        for _ in range(500):
            if self.state() != ctl.CAPTURING:
                break
            self.step("run")
        self.assertEqual(self.state(), ctl.WAITING_FEED)
        self.assertTrue(scheduled)

    def test_resync_pulses_file_synced_dats(self):
        self.make()
        class Dat(object):
            def __init__(s, path):
                s.name = "d"
                s.par = type("P", (), {})()
                s.par.file = type("F", (), {"eval": lambda self: path})()
                s.pulses = 0
                outer = s
                s.par.loadonstartpulse = type("L", (), {"pulse": lambda self: setattr(outer, "pulses", outer.pulses + 1)})()
        scripts = ctl.config.load()["scripts_dir"]
        inside, outside = Dat(scripts + "/x.py"), Dat("C:/other/x.py")
        self.root.findChildren = lambda depth=1: [inside, outside]
        self.assertEqual(ctl.resync(self.root), 1)
        self.assertEqual((inside.pulses, outside.pulses), (1, 0))

    def test_cancel_during_capture(self):
        self.make()
        self.timeline.frame, self.timeline.play = 7, True
        ctl.queue(self.root)
        for _ in range(10):
            ctl.capture_tick(self.root)
        ctl.cancel(self.root)
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertEqual(self.out.par.record.val, 0)
        self.assertEqual((self.timeline.play, self.timeline.frame), (True, 7))
        ctl.capture_tick(self.root)                     # late callbacks are harmless
        self.assertEqual(self.timeline.frame, 7)

    def test_queue_while_capturing_is_ignored(self):
        self.make()
        ctl.queue(self.root)
        ctl.queue(self.root)
        self.assertEqual(self.state(), ctl.CAPTURING)
        self.assertEqual(self.posts(), [])

    def test_still_mode_saves_a_png_and_renders_at_once(self):
        ui = self.make(feed_1_mode="top_still")
        ctl.queue(self.root)
        top = self.root.op("final_out")
        self.assertEqual(top.saved, [self.share + "/td_masks/feeds/cn1_feed.png"])
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        s = json.loads(self.posts()[0][2])["deforum_settings"]
        self.assertEqual(s["cn_1_vid_path"], "/opt/a1111/td_masks/feeds/cn1_feed.png")
        self.assertEqual(self.timeline.frame, 1)        # the timeline is never touched for a still
        self.assertTrue(ui.par.Feed1info.val.startswith("still"))

    def test_missing_source_top_fails_before_touching_the_timeline(self):
        self.make(feed_1_top="/project1/nothing")
        self.timeline.frame = 9
        ctl.queue(self.root)
        self.assertEqual(self.state(), ctl.IDLE)
        self.assertIn("not found", self.root.storage[ctl.STATE_KEY]["last_result"])
        self.assertEqual((self.timeline.play, self.timeline.frame), (True, 9))

    def test_missing_stepper_dat_fails_with_the_fix(self):
        self.make()
        del self.root.children["feed_capture_exec"]
        ctl.queue(self.root)
        self.assertIn("run setup_network", self.root.storage[ctl.STATE_KEY]["last_result"])

    def test_disabled_unit_or_file_mode_renders_normally(self):
        self.make(cn_1_enabled=False)
        ctl.queue(self.root)
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        self.assertEqual(self.out.recorded, [])
        self.make(feed_1_mode="file")
        ctl.cancel(self.root)
        ctl.queue(self.root)
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)

    def test_comfy_preprocess_is_skipped_for_a_top_feed(self):
        ui = self.make(comfy_preproc_enable=True)
        ctl.queue(self.root)
        self.record_all()
        self.feed_file()
        with mock.patch.object(ctl, "_frame_counter", return_value=lambda container: 75):
            self.tick()
            self.tick()
        self.assertEqual(self.state(), ctl.DEFORUM_SUBMITTED)
        self.assertEqual(self.root.op("webclient_comfyui").requests, [])

    def test_preview_describes_the_recording_without_sending_anything(self):
        self.make()
        result = ctl.preview(self.root)
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.state() if ctl.STATE_KEY in self.root.storage else ctl.IDLE, ctl.IDLE)
        self.assertEqual(result["request"]["deforum_settings"]["max_frames"], 75)

    def test_other_cn_units_are_sent_from_their_pages(self):
        self.make(cn_2_enabled=True, cn_2_model="control_depth", cn_2_weight=0.7, cn_2_vid_path="/x/d.mp4")
        result = ctl.export_payload(self.root)
        s = result["request"]["deforum_settings"]
        self.assertEqual((s["cn_2_model"], s["cn_2_weight"], s["cn_2_vid_path"]),
                         ("control_depth", "0:(0.7)", "/x/d.mp4"))
        self.assertIs(s["cn_2_enabled"], True)
        self.assertIs(s["cn_3_enabled"], False)
        self.assertEqual(s["cn_3_weight"], "0:(1.0)")


if __name__ == "__main__":
    unittest.main()
