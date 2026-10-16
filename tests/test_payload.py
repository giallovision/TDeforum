import json
import os
import unittest

from _fakes import ROOT_DIR  # noqa: F401  (puts scripts/ on sys.path)
from tdeforum import comfy, config, payload, schedules, schema

KNOWN_KEYS = set(json.load(open(os.path.join(ROOT_DIR, "tests", "data", "deforum_keys_5d63a339.json"))))

UI = {
    "sd_model_checkpoint": "0: 0, 75: 1", "sd_vae": "Automatic", "W": 1024, "H": 576,
    "steps": 10, "max_frames": 300, "sampler": "LCM", "animation_mode": "3D",
    "seed_behavior": "fixed", "seed": "-1", "n_prompt": "blurry, text",
    "use_mask_video": False, "video_init_path": "/opt/a1111/td_inputs/comfy_videos/a.mp4",
    "video_mask_path": "/opt/a1111/td_masks/mask_01.mov", "video_frame_mode": "trim",
    "border": "zeros", "zoom": "1.05", "translation_z": "0:(0), 299:(6)",
    "cn_1_enabled": True, "cn_1_weight": 0.8, "cn_1_resize_mode": "Just Resize",
    "comfy_preproc_enable": True, "comfy_preprocessor": "PiDiNetPreprocessor",
    "strength": 0.21, "diffusion_cadence": 4, "optical_flow_cadence": "RAFT",
    "pipeline_status": "idle", "bake_points": 32, "bake_target": "none",
}
MODELS = {"0": "angra.safetensors", "1": "comic.safetensors"}


class SchemaTest(unittest.TestCase):
    def test_td_names_match_original_rule(self):
        self.assertEqual(schema.td_name("translation_z"), "Translationz")
        self.assertEqual(schema.td_name("cn_1_vid_path"), "Cn1vidpath")
        self.assertEqual(schema.td_name("W"), "Width")
        self.assertEqual(schema.td_name("rotation_3d_x"), "Rotation3dx")

    def test_td_names_unique(self):
        names = [f.td_name for f in schema.FIELDS]
        self.assertEqual(len(names), len(set(names)))

    def test_every_deforum_key_is_known_to_deforum(self):
        for field in schema.FIELDS:
            if field.target == "deforum" and field.kind != schema.CHECKPOINT and field.api != "border":
                self.assertIn(field.key, KNOWN_KEYS, field.api)


class PayloadTest(unittest.TestCase):
    def build(self, **overrides):
        values = dict(UI, **overrides)
        return payload.build_request(values, {"0": "liquid gold"}, MODELS)

    def test_only_keys_deforum_reads(self):
        settings = self.build()["request"]["deforum_settings"]
        unknown = sorted(k for k in settings if k not in KNOWN_KEYS)
        self.assertEqual(unknown, [])

    def test_negative_prompt_and_options(self):
        req = self.build()["request"]
        self.assertEqual(req["deforum_settings"]["animation_prompts_negative"], "blurry, text")
        self.assertNotIn("n_prompt", req["deforum_settings"])
        self.assertEqual(req["options_overrides"], {"sd_vae": "Automatic"})
        self.assertNotIn("override_settings", req)

    def test_checkpoint_schedule_resolves_indices(self):
        s = self.build()["request"]["deforum_settings"]
        self.assertTrue(s["enable_checkpoint_scheduling"])
        self.assertEqual(s["checkpoint_schedule"], '0: "angra.safetensors", 75: "comic.safetensors"')

    def test_schedules_and_types(self):
        s = self.build()["request"]["deforum_settings"]
        self.assertEqual(s["zoom"], "0:(1.05)")
        self.assertEqual(s["translation_z"], "0:(0), 299:(6)")
        self.assertEqual(s["cn_1_weight"], "0:(0.8)")
        self.assertEqual(s["cn_1_guidance_end"], "0:(1.0)")
        self.assertEqual(s["seed"], -1)
        self.assertIs(s["cn_1_enabled"], True)
        self.assertEqual(s["cn_1_resize_mode"], "Just Resize")
        self.assertEqual(s["diffusion_cadence"], 4)
        self.assertEqual((s["border"], s["padding_mode"]), ("replicate", "zeros"))
        for unit in range(2, 6):
            self.assertIs(s["cn_%d_enabled" % unit], False)

    def test_td_only_fields_not_sent(self):
        s = self.build()["request"]["deforum_settings"]
        for key in ("comfy_preproc_enable", "comfy_preprocessor", "video_frame_mode",
                    "pipeline_status", "bake_points", "bake_target", "image_format", "max_mask_frames"):
            self.assertNotIn(key, s)

    def test_3d_uses_full_frame_count(self):
        result = self.build()
        self.assertEqual(result["request"]["deforum_settings"]["max_frames"], 300)

    def test_frame_counter_caps_trim(self):
        values = dict(UI, animation_mode="Video Input", use_mask_video=True)
        counts = {"/opt/a1111/td_inputs/comfy_videos/a.mp4": 500, "/opt/a1111/td_masks/mask_01.mov": 120}
        result = payload.build_request(values, None, MODELS, counts.get)
        s = result["request"]["deforum_settings"]
        self.assertEqual((s["max_frames"], s["extract_to_frame"], s["extract_nth_frame"]), (120, 119, 1))
        self.assertEqual(result["plan"]["limited_by"], "mask video")

    def test_unreadable_video_warns_but_builds(self):
        values = dict(UI, animation_mode="Video Input")
        result = payload.build_request(values, None, MODELS, lambda p: None)
        self.assertEqual(result["request"]["deforum_settings"]["max_frames"], 300)
        self.assertTrue(any("not readable" in w for w in result["warnings"]))


class PlanTest(unittest.TestCase):
    def test_stride_covers_whole_video(self):
        plan = payload.plan_frames("Video Input", 240, "stride", init_frames=2400)
        self.assertEqual((plan["max_frames"], plan["extract_nth_frame"], plan["extract_to_frame"]), (240, 10, 2399))
        self.assertEqual(plan["source_frames"], 2400)

    def test_stride_short_video_is_capped(self):
        plan = payload.plan_frames("Video Input", 240, "stride", init_frames=100)
        self.assertEqual((plan["max_frames"], plan["extract_nth_frame"]), (100, 1))

    def test_stride_rounds_up_available_frames(self):
        plan = payload.plan_frames("Video Input", 240, "stride", init_frames=500)
        self.assertEqual(plan["extract_nth_frame"], 2)
        self.assertEqual(plan["max_frames"], 240)

    def test_2d_with_mask(self):
        plan = payload.plan_frames("2D", 300, use_mask_video=True, mask_frames=90)
        self.assertEqual((plan["max_frames"], plan["extract_to_frame"]), (90, 89))


class ScheduleTest(unittest.TestCase):
    def test_quantize_matches_original(self):
        self.assertEqual(schedules.quantize_indices(300, 32)[:3], [0, 10, 19])
        self.assertEqual(schedules.quantize_indices(300, 32)[-1], 299)
        self.assertEqual(len(schedules.quantize_indices(300, 0)), 300)
        self.assertEqual(schedules.quantize_indices(10, 1), [0])

    def test_keyframe_string(self):
        self.assertEqual(schedules.keyframe_string([0, 0.5, 1.0], 0), "0:(0.0000), 1:(0.5000), 2:(1.0000)")

    def test_checkpoint_variants(self):
        self.assertEqual(schedules.checkpoint_schedule("1", MODELS, "d"), '0: "comic.safetensors"')
        self.assertEqual(schedules.checkpoint_schedule("x.safetensors", MODELS, "d"), '0: "x.safetensors"')
        self.assertEqual(schedules.checkpoint_schedule("9", MODELS, "d"), '0: "d"')
        self.assertEqual(schedules.checkpoint_schedule('{0: "a", 30: 1}', MODELS, "d"),
                         '0: "a", 30: "comic.safetensors"')


class PathTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load()
        self.cfg["share_root"] = "T:/"

    def test_outputs_map_to_td_outputs(self):
        self.assertEqual(config.to_share(self.cfg, "/opt/a1111/outputs/img2img-images/Deforum_1/1.mp4"),
                         "T:/td_outputs/img2img-images/Deforum_1/1.mp4")

    def test_round_trip(self):
        path = "/opt/a1111/td_masks/mask_01.mov"
        self.assertEqual(config.to_container(self.cfg, config.to_share(self.cfg, path)), path)

    def test_unmapped(self):
        self.assertIsNone(config.to_share(self.cfg, "/somewhere/else.mp4"))

    def test_comfy_paths(self):
        self.assertEqual(config.to_comfy_input(self.cfg, "/opt/a1111/td_inputs/comfy_videos/archive/a.mp4"),
                         "input/archive/a.mp4")
        self.assertEqual(config.comfy_output_to_container(self.cfg, "preprocessed_vids", "a_00001.mp4"),
                         "/opt/a1111/td_masks/preprocessed_vids/a_00001.mp4")


class ComfyTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load()
        with open(os.path.join(ROOT_DIR, "scripts", "templates", "TD_CN_PreProc.json")) as fh:
            self.template = json.load(fh)

    def test_build_prompt_stride_uses_source_frames(self):
        plan = payload.plan_frames("Video Input", 240, "stride", init_frames=2400)
        job = comfy.build_prompt(self.template, self.cfg, dict(UI, video_init_path="/opt/a1111/td_inputs/comfy_videos/archive/taichi_portrait.mp4"), plan)
        wf = job["body"]["prompt"]
        self.assertEqual(wf["10"]["inputs"]["frame_load_cap"], 2400)
        self.assertEqual(wf["10"]["inputs"]["video"], "input/archive/taichi_portrait.mp4")
        self.assertEqual(wf["21"]["inputs"]["filename_prefix"],
                         "preprocessed_vids/taichi_portrait_1024x576_PiDiNetPreprocessor_2400f")
        self.assertEqual(job["cache_key"], "taichi_portrait_1024x576_PiDiNetPreprocessor_2400f")
        self.assertEqual(self.template["10"]["inputs"]["frame_load_cap"], 300)  # template untouched

    def test_force_changes_prefix(self):
        plan = payload.plan_frames("3D", 120)
        job = comfy.build_prompt(self.template, self.cfg, UI, plan, force=True, stamp="20261016")
        self.assertTrue(job["body"]["prompt"]["21"]["inputs"]["filename_prefix"].endswith("_120f_20261016"))

    def test_parse_history(self):
        self.assertEqual(comfy.parse_history({}, "p1")[0], "pending")
        done = {"p1": {"status": {"status_str": "success", "completed": True},
                       "outputs": {"21": {"gifs": [{"filename": "a_00001.mp4", "subfolder": "preprocessed_vids"}]}}}}
        self.assertEqual(comfy.parse_history(done, "p1"), ("done", "preprocessed_vids", "a_00001.mp4", None))
        failed = {"p1": {"status": {"status_str": "error", "completed": False, "messages": [
            ["execution_error", {"node_id": "19", "exception_type": "RuntimeError", "exception_message": "boom"}]]},
            "outputs": {}}}
        state, _s, _f, msg = comfy.parse_history(failed, "p1")
        self.assertEqual(state, "error")
        self.assertIn("node 19", msg)


if __name__ == "__main__":
    unittest.main()
