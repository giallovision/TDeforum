import json
import unittest

from _fakes import ParMode, make_network, ROOT_DIR  # noqa: F401  (puts scripts/ on sys.path)
import test_controller
from test_payload import KNOWN_KEYS, MODELS, _comp_values
from tdeforum import migrate, payload, presets, schema
from tdeforum import td_controller as ctl


class PresetDataTest(unittest.TestCase):
    def test_twelve_examples_good_and_extreme_per_mode(self):
        self.assertEqual(len(presets.PRESETS), 12)
        for mode in ("3D", "2D", "Video Input"):
            levels = [p.level for p in presets.PRESETS if p.mode == mode]
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
        protected = {"seed", "seed_behavior", "loop_seeds", "sampler", "scheduler", "steps", "W", "H",
                     "sd_model_checkpoint", "sd_vae", "n_prompt", "cfg_scale_schedule"}
        for preset in presets.PRESETS:
            self.assertFalse(protected & set(preset.values), preset.id)
            self.assertFalse([k for k in preset.values if k.startswith("cn_")], preset.id)

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
            self.assertEqual((s["seed"], s["seed_behavior"]), (424242, "iter"), preset.id)
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
        self.assertEqual(ui.par.Strengthschedule.val, 0.78)
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
