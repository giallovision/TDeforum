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
                   poll_interval_s=0.0)
        with open(cfg["prompt_file"], "w") as fh:
            json.dump({"0": "liquid gold"}, fh)
        self.cfg = cfg
        patcher = mock.patch.object(config, "load", return_value=cfg)
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def test_bake_routes_by_channel_name_and_target(self):
        wave = self.root.op("wave_generator")
        wave.channels = [Channel("wave3", [0, 1, 2, 3, 4]), Channel("zoom", [1, 1.1, 1.2, 1.3, 1.4])]
        ctl.bake(self.root)
        ui = self.root.op("Deforum_UI")
        self.assertEqual(ui.par.Translationz.val, "0:(0.0000), 2:(2.0000), 4:(4.0000)")
        self.assertEqual(ui.par.Zoom.val, "0:(1.0000), 2:(1.2000), 4:(1.4000)")
        self.assertIn("wave3:", self.root.op("bake_out").text)

    def test_latest_render(self):
        paths = ["x/Deforum_1/20260101000000.mp4", "x/Deforum_2/20260301000000_depth.mp4",
                 "x/Deforum_2/20260201000000.mp4"]
        self.assertEqual(ctl.latest_render(paths), "x/Deforum_2/20260201000000.mp4")


if __name__ == "__main__":
    unittest.main()
