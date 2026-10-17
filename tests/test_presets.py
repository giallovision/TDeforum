import json
import unittest

from _fakes import ParMode, make_network, ROOT_DIR  # noqa: F401  (puts scripts/ on sys.path)
import test_controller
from test_payload import KNOWN_KEYS, MODELS, _comp_values
from tdeforum import migrate, payload, presets, schema, sweep
from tdeforum import td_controller as ctl


class PresetDataTest(unittest.TestCase):
    def test_three_unorthodox_per_mode(self):
        for mode in ("2D", "3D", "Video Input", "Interpolation"):
            odd = [p for p in presets.PRESETS if p.mode == mode and p.level == presets.UNORTHODOX
                   and not p.id.startswith("hybrid_")]
            self.assertEqual(len(odd), 3, mode)
            for p in odd:
                self.assertIn("(unorthodox)", p.label)

    def test_interpolation_presets_hold_the_seed_and_loop_cleanly(self):
        defaults = dict((f.api, f.default) for f in schema.FIELDS)
        for preset in [p for p in presets.PRESETS if p.mode == "Interpolation"]:
            values = _comp_values(**presets.resolve(preset, defaults))
            result = payload.build_request(values, {"0": "x"}, MODELS)
            s = result["request"]["deforum_settings"]
            self.assertEqual((s["animation_mode"], s["seed_behavior"]), ("Interpolation", "fixed"), preset.id)
            self.assertIs(s["enable_subseed_scheduling"], True, preset.id)
            self.assertFalse([w for w in result["warnings"] if "loop" in w or "LCM" in w], (preset.id, result["warnings"]))

    def test_flow_puppet_turns_hybrid_video_on(self):
        defaults = dict((f.api, f.default) for f in schema.FIELDS)
        values = _comp_values(**presets.resolve(presets.BY_ID["2d_flow_puppet"], defaults))
        s = payload.build_request(values, {"0": "x"}, MODELS)["request"]["deforum_settings"]
        self.assertEqual((s["hybrid_motion"], s["hybrid_generate_inputframes"]), ("Optical Flow", True))
        self.assertEqual(s["extract_nth_frame"], 1)

    def test_thirtyone_examples_good_and_extreme_per_mode(self):
        self.assertEqual(len(presets.PRESETS), 31)

    def test_four_hybrid_presets_use_the_video_and_the_sweep(self):
        hybrids = [p for p in presets.PRESETS if p.id.startswith("hybrid_")]
        self.assertEqual(len(hybrids), 4)
        defaults = dict((f.api, f.default) for f in schema.FIELDS)
        for p in hybrids:
            self.assertIn(p.mode, ("2D", "3D"))
            self.assertNotEqual(p.values["hybrid_motion"], "None", p.id)
            self.assertTrue(p.values["sweep_enabled"], p.id)
            self.assertEqual(p.values["feed_1_mode"], "sweep", p.id)
            values = _comp_values(**presets.resolve(p, defaults))
            self.assertIsNone(sweep.check(values), p.id)
            result = payload.build_request(values, {"0": "x"}, MODELS)
            s = result["request"]["deforum_settings"]
            self.assertIs(s["hybrid_generate_inputframes"], True, p.id)
            self.assertEqual(s["diffusion_cadence"], 2, p.id)
        self.assertTrue(presets.BY_ID["hybrid_ghost_peel"].values["sweep_as_mask"])
        for mode in ("3D", "2D", "Video Input"):
            levels = [p.level for p in presets.PRESETS if p.mode == mode and p.level != presets.UNORTHODOX]
            self.assertGreaterEqual(levels.count(presets.GOOD), 1, mode)
            self.assertGreaterEqual(levels.count(presets.EXTREME), 1, mode)
            self.assertGreaterEqual(len(levels), 2, mode)

    def test_menu_has_none_first_and_unique_ids(self):
        self.assertEqual(presets.NAMES[0], "none")
        self.assertEqual(len(set(presets.NAMES)), len(presets.NAMES))
        field = schema.BY_API["preset"]
        self.assertEqual((field.menu, field.default, field.page), (presets.NAMES, "none", schema.PAGE_ORDER[0]))
        self.assertEqual(schema.FIELDS[0].api, "preset")           # first thing on the first page
        self.assertEqual(presets.LABELS[0], "None")

    def test_every_key_exists_and_values_fit_the_field(self):
        for preset in presets.PRESETS:
            for api, value in preset.values.items():
                field = schema.BY_API.get(api)
                self.assertIsNotNone(field, "%s: %s" % (preset.id, api))
                if field.menu:
                    self.assertIn(value, field.menu, "%s: %s" % (preset.id, api))
                if field.kind in (schema.FLOAT, schema.INT, schema.MOD):
                    self.assertIsInstance(value, (int, float), "%s: %s" % (preset.id, api))
                if field.safe:
                    lo, hi = field.safe
                    self.assertTrue((lo is None or value >= lo) and (hi is None or value <= hi),
                                    "%s: %s=%s outside %s" % (preset.id, api, value, field.safe))
                if field.kind == schema.TOGGLE:
                    self.assertIsInstance(value, bool)

    def test_presets_leave_the_seed_and_checkpoint_setup_alone(self):
        protected = {"seed", "loop_seeds", "sampler", "scheduler", "steps", "W", "H", "img2img_fix_steps",
                     "sd_model_checkpoint", "sd_vae", "n_prompt", "cfg_scale_schedule"}
        for preset in presets.PRESETS:
            self.assertFalse(protected & set(preset.values), preset.id)
            if preset.mode in ("2D", "3D"):
                self.assertNotIn("seed_behavior", preset.values, preset.id)
            if not preset.values.get("sweep_enabled"):
                self.assertFalse([k for k in preset.values if k.startswith("cn_") or k.startswith("feed_")],
                                 preset.id)

    def test_video_presets_hold_the_seed_and_restyle_every_frame(self):
        for preset in presets.PRESETS:
            if preset.mode != "Video Input":
                continue
            self.assertEqual(preset.values["diffusion_cadence"], 1, preset.id)
            expected = "iter" if preset.id == "video_melt" else "fixed"
            self.assertEqual(preset.values["seed_behavior"], expected, preset.id)

    def test_good_presets_pass_the_lcm_checks(self):
        defaults = dict((f.api, f.default) for f in schema.FIELDS)
        for preset in presets.PRESETS:
            values = _comp_values(**presets.resolve(preset, defaults))
            warnings = payload.build_request(values, {"0": "x"}, MODELS)["warnings"]
            self.assertFalse([w for w in warnings if "LCM" in w or "int(steps" in w or "Cadence" in w],
                             "%s: %s" % (preset.id, warnings))

    def test_sweep_presets_switch_sweep_on_and_use_unit_one_as_the_guide(self):
        sweeps = [p for p in presets.PRESETS if p.id.startswith("video_depth_sweep")]
        self.assertEqual(len(sweeps), 3)
        self.assertEqual(sorted(p.level for p in sweeps), [presets.EXTREME, presets.GOOD, presets.GOOD])
        modes = sorted(p.values["sweep_mode"] for p in sweeps)
        self.assertEqual(modes, ["max", "min", "min"])
        for p in sweeps:
            self.assertEqual(p.mode, "Video Input")
            self.assertTrue(p.values["sweep_enabled"] and p.values["cn_1_enabled"])
            self.assertEqual(p.values["feed_1_mode"], "sweep")
            self.assertTrue([k for k in p.values if k.startswith("sweep_")])
            self.assertEqual(p.values["sweep_model"], "depth_anything_v2_vits")
            self.assertGreater(p.values["sweep_grow"], 0)
            self.assertGreater(p.values["sweep_blur"], 0)

    def test_reset_keys_are_motion_or_slot_toggles(self):
        for key in presets.RESET_KEYS:
            field = schema.BY_API[key]
            self.assertTrue(field.page in (schema.PAGE_MOTION2D, schema.PAGE_MOTION3D)
                            or key.endswith("_active"), key)

    def test_each_preset_builds_a_valid_request(self):
        defaults = dict((f.api, f.default) for f in schema.FIELDS)
        for preset in presets.PRESETS:
            values = _comp_values(**presets.resolve(preset, defaults))
            result = payload.build_request(values, {"0": "x"}, MODELS)
            s = result["request"]["deforum_settings"]
            self.assertEqual(s["animation_mode"], preset.mode, preset.id)
            self.assertEqual(sorted(k for k in s if k not in KNOWN_KEYS), [], preset.id)
            behaviour = preset.values.get("seed_behavior", "iter")
            self.assertEqual((s["seed"], s["seed_behavior"]), (424242, behaviour), preset.id)
            json.dumps(result["request"])
            if preset.level == presets.GOOD:
                bad = [w for w in result["warnings"]
                       if "-only" in w or "outside" in w or "does not divide" in w]
                self.assertEqual(bad, [], "%s: %s" % (preset.id, result["warnings"]))

    def test_beat_presets_use_mod_slots(self):
        for preset_id in ("3d_kick_push", "3d_strobe_push", "2d_twirl", "3d_warp_drive"):
            self.assertTrue(presets.BY_ID[preset_id].values.get("mod1_active"), preset_id)
        self.assertFalse(presets.BY_ID["3d_tunnel_roll"].values.get("mod1_active", False))


class BaselineTest(unittest.TestCase):
    def test_iterate_and_424242(self):
        self.assertEqual(schema.BY_API["seed"].default, "424242")
        self.assertEqual(schema.BY_API["seed_behavior"].default, "iter")
        self.assertIs(schema.BY_API["loop_seeds"].default, False)

    def test_old_defaults_move_to_the_new_baseline_but_custom_values_stay(self):
        const = lambda val: {"mode": "CONSTANT", "expr": "", "bind": "", "val": val}
        actions = migrate.plan({"Seed": const("-1"), "Loopseeds": const(1)}, False)
        self.assertEqual([a[0] for a in actions if a[0] == "set"], [])
        self.assertEqual(len([a for a in actions if a[0] == "note"]), 2)
        kept = migrate.plan({"Seed": const("99"), "Loopseeds": const(0)}, False)
        self.assertEqual(sorted(a[1] for a in kept if a[0] == "set"), ["Loopseeds", "Seed"])
        driven = migrate.plan({"Seed": {"mode": "EXPRESSION", "expr": "absTime.frame", "bind": "", "val": "-1"}},
                              False)
        self.assertEqual([a[1] for a in driven if a[0] == "set"], ["Seed"])


class ApplyPresetTest(test_controller.ControllerTest.__bases__[0]):
    setUp = test_controller.ControllerTest.setUp

    def make(self, **overrides):
        values = dict((f.api, f.default) for f in schema.FIELDS)
        values.update(overrides)
        self.root = make_network(values, comp=True, prompt_rows=[("0", "gold", "")])
        self.ui = self.root.op("deforum")
        return self.ui

    def pick(self, name):
        self.ui.par.Preset.val = name

    def test_nothing_happens_on_none(self):
        ui = self.make()
        self.assertFalse(ctl.apply_preset(self.root))
        self.assertEqual(ui.par.Translationz.val, 0.0)

    def test_apply_on_bake_then_restore_with_none(self):
        ui = self.make(translation_z=0.5, **{"translation_z:raw": "0:(1)"})
        ui.par.Translationzraw.val = "0:(1)"
        ui.par.Zoom.val = 1.01
        self.pick("3d_tunnel_roll")
        ctl.preview(self.root)                                    # bake
        self.assertEqual(ui.par.Animationmode.val, "3D")
        self.assertEqual((ui.par.Translationz.val, ui.par.Translationzraw.val), (0.6, ""))
        self.assertEqual(ui.par.Zoom.val, 1.0, "motion not named by the preset goes back to baseline")
        self.assertEqual(ui.par.Strengthschedule.val, 0.75)
        self.assertEqual(ui.par.Seed.val, "424242")
        self.assertIn("3D - Tunnel roll", ui.par.Presetinfo.val)

        self.pick("none")
        ctl.preview(self.root)
        self.assertEqual((ui.par.Translationz.val, ui.par.Translationzraw.val), (0.5, "0:(1)"))
        self.assertEqual(ui.par.Zoom.val, 1.01)
        self.assertEqual(ui.par.Strengthschedule.val, schema.BY_API["strength_schedule"].default)
        self.assertEqual(ui.par.Animationmode.val, "3D")
        self.assertIn("None", ui.par.Presetinfo.val)

    def test_switching_presets_restores_first_and_never_stacks(self):
        ui = self.make()
        self.pick("3d_kick_push")
        ctl.apply_preset(self.root)
        self.assertTrue(ui.par.Mod1active.val and ui.par.Mod2active.val)
        self.assertEqual((ui.par.Mod1target.val, ui.par.Mod1shape.val), ("translation_z", "decay"))
        self.pick("2d_zoom_drift")
        ctl.apply_preset(self.root)
        self.assertEqual(ui.par.Animationmode.val, "2D")
        self.assertFalse(ui.par.Mod1active.val or ui.par.Mod2active.val)
        self.assertEqual((ui.par.Translationz.val, ui.par.Zoom.val), (0.0, 1.003))
        self.pick("none")
        ctl.apply_preset(self.root)
        self.assertEqual(ui.par.Animationmode.val, "3D")
        self.assertEqual(ui.par.Zoom.val, 1.0)

    def test_tweaks_after_applying_survive_until_the_selection_changes(self):
        ui = self.make()
        self.pick("3d_tunnel_roll")
        ctl.apply_preset(self.root)
        ui.par.Translationz.val = 2.0
        self.assertFalse(ctl.apply_preset(self.root))
        ctl.preview(self.root)
        self.assertEqual(ui.par.Translationz.val, 2.0)

    def test_driven_parameters_are_left_alone(self):
        ui = self.make()
        ui.par.Translationz.mode, ui.par.Translationz.expr = ParMode.EXPRESSION, "op('lfo')[0]"
        ui.par.Translationz.val = 0.25
        self.pick("3d_tunnel_roll")
        ctl.apply_preset(self.root)
        self.assertEqual((ui.par.Translationz.mode, ui.par.Translationz.val), (ParMode.EXPRESSION, 0.25))
        self.assertEqual(ui.par.Rotation3dz.val, 0.04)
        self.pick("none")
        ctl.apply_preset(self.root)
        self.assertEqual((ui.par.Translationz.mode, ui.par.Translationz.expr), (ParMode.EXPRESSION, "op('lfo')[0]"))

    def test_reapply_puts_the_preset_back_after_tweaks(self):
        ui = self.make()
        self.pick("video_depth_sweep_away")
        ctl.apply_preset(self.root)
        self.assertEqual((ui.par.Animationmode.val, ui.par.Sweepenabled.val, ui.par.Feed1mode.val,
                          ui.par.Cn1enabled.val), ("Video Input", 1, "sweep", 1))
        ui.par.Animationmode.val, ui.par.Sweepenabled.val = "3D", 0       # tweaked / reset elsewhere
        self.assertFalse(ctl.apply_preset(self.root))                     # same selection: kept
        self.assertTrue(ctl.apply_preset(self.root, force=True))          # Re-apply Preset
        self.assertEqual((ui.par.Animationmode.val, ui.par.Sweepenabled.val), ("Video Input", 1))
        self.pick("none")
        ctl.apply_preset(self.root)
        self.assertEqual((ui.par.Animationmode.val, ui.par.Sweepenabled.val), ("3D", 0))

    def test_reapply_with_none_selected_does_nothing(self):
        self.make()
        self.assertFalse(ctl.apply_preset(self.root, force=True))

    def test_edit_prompt_seq_opens_the_table(self):
        self.make()
        table = self.ui.op("prompt_seq")
        opened = []
        table.openViewer = lambda: opened.append(True)
        ctl.open_prompt_seq(self.root)
        self.assertEqual(opened, [True])

    def test_prompt_preset_writes_prompt_seq_and_none_restores_it(self):
        from tdeforum import prompt_presets
        ui = self.make(prompt_source="json")
        table = ui.op("prompt_seq")
        self.assertEqual(len(prompt_presets.PRESETS), 10)
        ui.par.Promptpreset.val = "cosmic_eye"
        self.assertTrue(ctl.apply_prompt_preset(self.root))
        self.assertEqual(table.rows[0], ["beat", "prompt", "xfade"])
        self.assertIn("cosmic eye", table.rows[1][1])
        self.assertEqual(ui.par.Promptsource.val, "sequence")
        ui.par.Promptpreset.val = "neural_bloom"
        ctl.apply_prompt_preset(self.root)
        self.assertIn("neural network", table.rows[1][1])
        ui.par.Promptpreset.val = "none"
        ctl.apply_prompt_preset(self.root)
        self.assertEqual(table.rows, [["beat", "prompt", "xfade"], ["0", "gold", ""]])
        values = ctl.read_ui(ui)
        prompts = payload.build_request(values, {"0": "x"}, MODELS, prompt_rows=ctl.read_prompt_rows(ui))
        self.assertEqual(prompts["request"]["deforum_settings"]["prompts"]["0"], "gold")

    def test_every_prompt_preset_compiles(self):
        from tdeforum import prompt_presets
        values = _comp_values()
        for preset in prompt_presets.PRESETS:
            rows = [["beat", "prompt", "xfade"]] + [list(r) for r in preset.rows]
            s = payload.build_request(values, {"0": "x"}, MODELS, prompt_rows=rows)["request"]["deforum_settings"]
            self.assertEqual(s["prompts"]["0"], preset.rows[0][1], preset.id)
            self.assertLess(len(preset.rows[0][1].split()), 45, preset.id)       # CLIP: 77 tokens

    def test_every_preset_applies_and_then_queues(self):
        ui = self.make()
        for preset in presets.PRESETS:
            self.pick(preset.id)
            self.assertTrue(ctl.apply_preset(self.root), preset.id)
            values = ctl.read_ui(ui)
            self.assertEqual(values["animation_mode"], preset.mode, preset.id)
            for api, value in preset.values.items():
                field = schema.BY_API[api]
                self.assertEqual(values[api], ctl._coerce_par(field, value), "%s %s" % (preset.id, api))
            result = payload.build_request(values, {"0": "x"}, MODELS)
            self.assertEqual(result["request"]["deforum_settings"]["animation_mode"], preset.mode)
        self.pick("none")
        ctl.apply_preset(self.root)
        self.assertEqual(ctl.read_ui(ui)["translation_z"], 0.0)


if __name__ == "__main__":
    unittest.main()


class PagePresetDataTest(unittest.TestCase):
    def test_every_page_but_globals_has_a_menu_first(self):
        from tdeforum import page_presets
        for page in schema.PAGE_ORDER:
            fields = [f for f in schema.FIELDS if f.page == page]
            if page in (schema.PAGE_GLOBALS, schema.PAGE_PROMPTS):
                self.assertFalse([f for f in fields if f.api.startswith("pagepreset")], page)
                continue
            self.assertIn(page, page_presets.PAGES, page)
            menu = schema.BY_API[page_presets.api(page)]
            first = [f.api for f in fields if not f.api.startswith("preset")][0]
            self.assertEqual(first, menu.api, page)
            self.assertEqual(menu.menu[0], "none")
        self.assertIn("prompt_preset", schema.BY_API)          # the Prompts page's own preset

    def test_page_presets_only_touch_their_page_with_valid_values(self):
        from tdeforum import page_presets
        defaults = dict((f.api, f.default) for f in schema.FIELDS)
        for page, (_slug, items) in page_presets.PAGES.items():
            self.assertGreaterEqual(len(items), 3, page)
            for preset in items:
                for api, value in preset.values.items():
                    field = schema.BY_API[api]
                    self.assertEqual(field.page, page, "%s/%s: %s" % (page, preset.id, api))
                    if field.menu:
                        self.assertIn(value, field.menu, "%s/%s: %s" % (page, preset.id, api))
                values = _comp_values(**dict(defaults, **preset.values))
                result = payload.build_request(values, {"0": "x"}, MODELS)
                bad = [w for w in result["warnings"] if "LCM" in w or "outside" in w or "-only" not in w and
                       "int(steps" in w]
                self.assertEqual(bad, [], "%s/%s: %s" % (page, preset.id, result["warnings"]))


class PagePresetApplyTest(test_controller.ControllerTest.__bases__[0]):
    setUp = test_controller.ControllerTest.setUp
    make = ApplyPresetTest.make

    def test_page_preset_applies_and_none_restores(self):
        ui = self.make()
        ui.par.Pagepresetmotion3d.val = "orbit"
        self.assertTrue(ctl.on_ui_value(self.root, "Pagepresetmotion3d"))
        self.assertEqual((ui.par.Rotation3dy.val, ui.par.Paddingmode.val), (0.15, "reflection"))
        ui.par.Pagepresetmotion3d.val = "push"                  # switching restores first
        ctl.on_ui_value(self.root, "Pagepresetmotion3d")
        self.assertEqual((ui.par.Rotation3dy.val, ui.par.Translationz.val, ui.par.Paddingmode.val),
                         (0.0, 0.6, "border"))
        ui.par.Pagepresetmotion3d.val = "none"
        ctl.on_ui_value(self.root, "Pagepresetmotion3d")
        self.assertEqual(ui.par.Translationz.val, 0.0)

    def test_page_presets_stack_and_the_example_preset_resets_them(self):
        ui = self.make()
        ui.par.Pagepresetcamera.val = "wide"
        ctl.on_ui_value(self.root, "Pagepresetcamera")
        ui.par.Pagepresetflow.val = "deflicker"
        ctl.on_ui_value(self.root, "Pagepresetflow")
        ui.par.Promptpreset.val = "cosmic_eye"
        ctl.on_ui_value(self.root, "Promptpreset")
        self.assertEqual((ui.par.Fovschedule.val, ui.par.Opticalflowredogeneration.val), (100.0, "RAFT"))
        ui.par.Preset.val = "3d_tunnel_roll"
        ctl.on_ui_value(self.root, "Preset")
        self.assertEqual((ui.par.Pagepresetcamera.val, ui.par.Pagepresetflow.val, ui.par.Promptpreset.val),
                         ("none", "none", "none"))
        self.assertEqual(ui.par.Opticalflowredogeneration.val, "None")
        self.assertEqual(ui.op("prompt_seq").rows[-1], ["0", "gold", ""])
        self.assertEqual(ui.par.Fovschedule.val, 70.0)             # the example's own value
        ui.par.Pagepresetcamera.val = "tele"                       # on top of the example
        ctl.on_ui_value(self.root, "Pagepresetcamera")
        self.assertEqual(ui.par.Fovschedule.val, 35.0)
        ui.par.Preset.val = "none"
        ctl.on_ui_value(self.root, "Preset")
        self.assertEqual((ui.par.Pagepresetcamera.val, ui.par.Fovschedule.val), ("none", 70.0))
        self.assertEqual(ui.par.Animationmode.val, "3D")

    def test_reapply_with_none_clears_page_presets(self):
        ui = self.make()
        ui.par.Pagepresetdiffusion.val = "steady"
        ctl.on_ui_value(self.root, "Pagepresetdiffusion")
        self.assertEqual(ui.par.Strengthschedule.val, 0.8)
        self.assertTrue(ctl.on_ui_pulse(self.root, "Presetapply"))
        self.assertEqual((ui.par.Pagepresetdiffusion.val, ui.par.Strengthschedule.val),
                         ("none", schema.BY_API["strength_schedule"].default))
