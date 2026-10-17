import json
import math
import os
import unittest

from _fakes import ROOT_DIR  # noqa: F401  (puts scripts/ on sys.path)
import _deforum_sim as sim
from tdeforum import comfy, config, migrate, payload, schedules, schema

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
        names = schema.all_td_names()
        self.assertEqual(len(names), len(set(names)))

    def test_mod_fields_are_deforum_schedules(self):
        for field in schema.MOD_FIELDS:
            self.assertIn(field.key, KNOWN_KEYS, field.api)
        self.assertNotIn("kernel_schedule", schema.MOD_APIS)   # odd-only, not modulatable

    def test_slot_target_menus_list_every_mod(self):
        for n in range(1, schema.MOD_SLOTS + 1):
            target = schema.BY_API["mod%d_target" % n]
            self.assertEqual(target.menu, schema.MOD_APIS)
            self.assertIn(target.default, schema.MOD_APIS)

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
        self.assertEqual(s["cn_1_guidance_end"], "0:(0.8)")       # baseline 4
        self.assertEqual(s["seed"], -1)
        self.assertIs(s["cn_1_enabled"], True)
        self.assertEqual(s["cn_1_resize_mode"], "Just Resize")
        self.assertEqual(s["diffusion_cadence"], 4)
        self.assertEqual((s["border"], s["padding_mode"]), ("replicate", "zeros"))
        for unit in range(2, 6):
            self.assertIs(s["cn_%d_enabled" % unit], False)

    def test_disabled_cn_units_send_full_schedules(self):
        # Deforum crashes on a None schedule even for a disabled unit (gvispc1 log:
        # "'NoneType' object has no attribute 'split'"), so every unit needs them all.
        s = self.build()["request"]["deforum_settings"]
        for unit in range(2, 6):
            for field in schema.cn_fields(1):
                if field.api == "cn_1_enabled":
                    continue
                key = field.key.replace("cn_1_", "cn_%d_" % unit, 1)
                self.assertIn(key, s)
                self.assertIsNotNone(s[key], key)
            self.assertEqual(s["cn_%d_weight" % unit], "0:(1.0)")
            self.assertEqual(s["cn_%d_guidance_end" % unit], "0:(0.8)")

    def test_zoe_depth_is_sent_as_midas_with_a_warning(self):
        for algo in ("Zoe", "Zoe+AdaBins (old)"):
            result = payload.build_request(_comp_values(depth_algorithm=algo, animation_mode="3D"), {"0": "x"}, MODELS)
            self.assertEqual(result["request"]["deforum_settings"]["depth_algorithm"], "Midas-3-Hybrid")
            self.assertTrue(any("crashes in this A1111 image" in w for w in result["warnings"]), algo)
        ok = payload.build_request(_comp_values(depth_algorithm="Leres", animation_mode="3D"), {"0": "x"}, MODELS)
        self.assertEqual(ok["request"]["deforum_settings"]["depth_algorithm"], "Leres")

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


def _comp_values(**overrides):
    """Every COMP field at its schema default, plus overrides (what read_ui returns)."""
    values = dict((f.api, f.default) for f in schema.FIELDS)
    for f in schema.MOD_FIELDS:
        values[payload.raw_key(f.api)] = ""
    values.update(overrides)
    return values


class TempoPayloadTest(unittest.TestCase):
    def build(self, rows=None, chop=None, **overrides):
        return payload.build_request(_comp_values(**overrides), {"0": "json prompt"}, MODELS,
                                     prompt_rows=rows, chop=chop)

    def test_defaults_send_only_known_keys(self):
        for strategy in ("cadence", "interpolate"):
            s = self.build(render_strategy=strategy)["request"]["deforum_settings"]
            self.assertEqual(sorted(k for k in s if k not in KNOWN_KEYS), [], strategy)

    def test_every_mod_baseline_is_a_constant_schedule(self):
        result = self.build()
        for field in schema.MOD_FIELDS:
            how, sched = result["schedules"][field.api]
            self.assertEqual(how, "constant", field.api)
            self.assertEqual(sim.series(sched, 5), [float(field.default)] * 5, field.api)

    def test_default_tempo_plan(self):
        r = self.build()
        s = r["request"]["deforum_settings"]
        # 120 bpm, 2 bars at 60 fps + 1 beat overlap
        self.assertEqual((s["fps"], s["max_frames"], s["diffusion_cadence"]), (60, 270, 4))
        self.assertEqual(s["seed_behavior"], "iter")                # baseline: Iterate (+1)
        self.assertNotIn("seed_schedule", s)
        self.assertEqual(s["prompts"], {"0": "json prompt"})        # no rows -> prompt.json

    def test_loop_seeds_is_opt_in(self):
        s = self.build(loop_seeds=True)["request"]["deforum_settings"]
        self.assertEqual((s["seed_behavior"], s["seed_schedule"]), ("schedule", "0:(s + t%240)"))

    def test_baseline_seed_and_behaviour(self):
        self.assertEqual(schema.BY_API["seed"].default, "424242")
        self.assertEqual(schema.BY_API["seed_behavior"].default, "iter")
        self.assertIs(schema.BY_API["loop_seeds"].default, False)

    def test_slots_and_chop_compile_to_what_deforum_evaluates(self):
        r = self.build(chop={"Translationz": [0.0, 2.0]},
                       mod1_active=True, mod1_target="translation_z", mod1_shape="sine",
                       mod1_beats=4.0, mod1_depth=1.5, mod1_phase=0.0)
        s = r["request"]["deforum_settings"]
        z = sim.series(s["translation_z"], s["max_frames"])
        # CHOP [0, 2] stretched over the 240-frame loop (wrapping 2 -> 0), + a 4-beat sine
        for t in (0, 37, 119, 240, 269):
            phase = (t % 240) / 240.0
            expect_chop = 4 * phase if phase <= 0.5 else 4 * (1 - phase)
            expect = expect_chop + 1.5 * math.sin(2 * math.pi * t / 120.0)
            self.assertAlmostEqual(z[t], expect, 4)
        self.assertEqual(r["schedules"]["translation_z"][0], "baked")

    def test_raw_override_wins(self):
        r = self.build(**{"zoom": 1.2, payload.raw_key("zoom"): "0:(1), 60:(1.1)"})
        self.assertEqual(r["request"]["deforum_settings"]["zoom"], "0:(1), 60:(1.1)")

    def test_prompt_sequence_used_in_tempo_mode(self):
        r = self.build(rows=[["beat", "prompt", "xfade"], ["0", "gold", ""], ["4", "ice", ""]])
        prompts = r["request"]["deforum_settings"]["prompts"]
        self.assertEqual(prompts["0"], "gold")
        self.assertEqual(prompts["120"], "ice")
        r = self.build(rows=[["0", "gold", ""]], prompt_source="json")
        self.assertEqual(r["request"]["deforum_settings"]["prompts"], {"0": "json prompt"})

    def test_manual_length(self):
        s = self.build(length_source="manual", max_frames=99)["request"]["deforum_settings"]
        self.assertEqual(s["max_frames"], 99)
        self.assertNotIn("fps", s)

    def test_kernel_forced_odd(self):
        r = self.build(kernel_schedule=4)
        self.assertEqual(r["request"]["deforum_settings"]["kernel_schedule"], "0:(5)")
        self.assertTrue(any("kernel" in w for w in r["warnings"]))

    def test_dims_and_range_warnings(self):
        r = self.build(animation_mode="3D", mod1_active=True, mod1_target="zoom", mod1_depth=0.1,
                       mod2_active=True, mod2_target="strength_schedule", mod2_depth=0.6)
        joined = " | ".join(r["warnings"])
        self.assertIn("zoom is 2D-only", joined)
        self.assertIn("strength_schedule swings", joined)

    def test_loop_seam_warning(self):
        r = self.build(mod1_active=True, mod1_target="angle", mod1_beats=3.0, mod1_depth=1.0)
        self.assertTrue(any("does not divide" in w for w in r["warnings"]))

    def test_non_looping_seed_behaviour_warns(self):
        r = self.build(seed_behavior="random", loop_seeds=True)
        s = r["request"]["deforum_settings"]
        self.assertEqual(s["seed_behavior"], "random")
        self.assertNotIn("seed_schedule", s)
        self.assertTrue(any("does not repeat" in w for w in r["warnings"]))

    def test_padding_and_border_are_separate(self):
        s = self.build(border="wrap", padding_mode="zeros")["request"]["deforum_settings"]
        self.assertEqual((s["border"], s["padding_mode"]), ("wrap", "zeros"))


class MigrateTest(unittest.TestCase):
    def test_split_schedule(self):
        self.assertEqual(migrate.split_schedule("0:(1.05)"), (1.05, ""))
        self.assertEqual(migrate.split_schedule("0.065"), (0.065, ""))
        self.assertEqual(migrate.split_schedule("0: (0.5)"), (0.5, ""))
        self.assertEqual(migrate.split_schedule("0:(0), 299:(6)"), (None, "0:(0), 299:(6)"))
        self.assertEqual(migrate.split_schedule("0:(1+sin(t/9))"), (None, "0:(1+sin(t/9))"))

    def test_old_ui_values_move_to_base_or_raw(self):
        c = lambda v: {"mode": "CONSTANT", "expr": "", "bind": "", "val": v}
        saved = {"Zoom": c("0:(1.05)"), "Translationz": c("0:(0), 299:(6)"), "Border": c("zeros"),
                 "Strengthschedule": c("0: (0.5)"), "Diffusioncadence": c(4),
                 "Rotation3dy": {"mode": "EXPORT", "expr": "", "bind": "", "val": "0:(0)"},
                 "Noiseschedule": {"mode": "EXPRESSION", "expr": "op('x')[0]", "bind": "", "val": ""},
                 "Baketarget": c("translation_z"), "Pipelinestatus": c("busy")}
        actions = migrate.plan(saved, from_old_ui=True)
        sets = dict((a[1], a[2]["val"] if a[2]["mode"] == "CONSTANT" else a[2]["expr"])
                    for a in actions if a[0] == "set")
        self.assertEqual(sets["Zoom"], 1.05)
        self.assertEqual(sets["Translationzraw"], "0:(0), 299:(6)")
        self.assertEqual(sets["Strengthschedule"], 0.5)
        self.assertEqual((sets["Border"], sets["Paddingmode"]), ("replicate", "zeros"))
        self.assertEqual(sets["Diffusioncadence"], 4)
        self.assertEqual(sets["Noisescheduleraw"], "op('x')[0]")
        self.assertNotIn("Pipelinestatus", sets)
        notes = [a[1] for a in actions if a[0] == "note"]
        self.assertTrue(any("Rotation3dy" in n for n in notes))
        self.assertEqual(migrate.dropped(saved), ["Baketarget"])

    def test_rebuild_keeps_raw_overrides(self):
        c = lambda v: {"mode": "CONSTANT", "expr": "", "bind": "", "val": v}
        actions = migrate.plan({"Zoom": c(1.1), "Zoomraw": c("0:(1), 9:(2)")}, from_old_ui=False)
        sets = dict((a[1], a[2]["val"]) for a in actions if a[0] == "set")
        self.assertEqual(sets, {"Zoom": 1.1, "Zoomraw": "0:(1), 9:(2)"})


class SamplingChecksTest(unittest.TestCase):
    def build(self, **overrides):
        return payload.build_request(_comp_values(**overrides), {"0": "x"}, MODELS)

    def test_defaults_are_lcm_ready_and_send_exact_steps(self):
        result = self.build()
        s = result["request"]["deforum_settings"]
        self.assertEqual((s["steps"], s["cfg_scale_schedule"], s["sampler"]), (4, "0:(1.8)", "LCM"))
        self.assertIs(result["request"]["options_overrides"]["img2img_fix_steps"], True)
        self.assertFalse([w for w in result["warnings"] if "LCM" in w or "int(steps" in w])

    def test_high_cfg_with_lcm_warns(self):
        warnings = self.build(cfg_scale_schedule=7.0)["warnings"]
        self.assertTrue([w for w in warnings if "CFG reaches 7 with the LCM sampler" in w], warnings)
        self.assertFalse([w for w in self.build(cfg_scale_schedule=7.0, sampler="Euler a")["warnings"]
                          if "LCM" in w])

    def test_too_few_img2img_steps_warn_without_exact_steps(self):
        warnings = self.build(img2img_fix_steps=False, strength_schedule=0.65)["warnings"]
        self.assertTrue([w for w in warnings if "1 step(s) at Strength 0.65" in w], warnings)
        self.assertFalse([w for w in self.build(strength_schedule=0.65)["warnings"] if "int(steps" in w])

    def test_video_input_with_cadence_warns(self):
        warnings = self.build(animation_mode="Video Input", diffusion_cadence=4)["warnings"]
        self.assertTrue([w for w in warnings if "Diffusion Cadence 4" in w and "every 4th" in w], warnings)
        self.assertFalse([w for w in self.build(animation_mode="Video Input", diffusion_cadence=1)["warnings"]
                          if "Cadence" in w])


class DepthNodeTest(unittest.TestCase):
    def test_vits_uses_the_dedicated_node_at_512(self):
        with open(os.path.join(ROOT_DIR, "scripts", "templates", "TD_CN_PreProc.json")) as fh:
            template = json.load(fh)
        cfg = config.load()
        values = _comp_values(comfy_preprocessor="depth_anything_v2_vits", comfy_resolution=512)
        plan = payload.plan_frames("Video Input", 240)
        job = comfy.build_prompt(template, cfg, values, plan)
        node = job["body"]["prompt"]["19"]
        self.assertEqual(node["class_type"], "DepthAnythingV2Preprocessor")
        self.assertEqual(node["inputs"]["ckpt_name"], "depth_anything_v2_vits.pth")
        self.assertEqual(node["inputs"]["resolution"], 512)
        self.assertEqual(node["inputs"]["image"], ["11", 0])
        self.assertIn("depth_anything_v2_vits_240f", job["cache_key"])
        load = job["body"]["prompt"]["10"]["inputs"]
        self.assertEqual((load["custom_width"], load["custom_height"]), (1024, 576))
        aio = comfy.build_prompt(template, cfg, _comp_values(comfy_preprocessor="PiDiNetPreprocessor"), plan)
        self.assertEqual(aio["body"]["prompt"]["19"]["class_type"], "AIO_Preprocessor")
        self.assertEqual(aio["body"]["prompt"]["19"]["inputs"]["resolution"], 576)


class HistoryNameTest(unittest.TestCase):
    def test_the_file_vhs_wrote_wins_over_the_reported_name(self):
        history = {"p": {"status": {"status_str": "success", "completed": True}, "outputs": {"21": {"gifs": [
            {"filename": "a_00001.mp4", "subfolder": "preprocessed_vids",
             "fullpath": "/opt/ComfyUI/output/preprocessed_vids/a.mp4"}]}}}}
        self.assertEqual(comfy.parse_history(history, "p"), ("done", "preprocessed_vids", "a.mp4", None))
        del history["p"]["outputs"]["21"]["gifs"][0]["fullpath"]
        self.assertEqual(comfy.parse_history(history, "p")[2], "a_00001.mp4")
