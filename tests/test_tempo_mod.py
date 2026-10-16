import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import _deforum_sim as sim
from tdeforum import modulation, prompt_seq, tempo
from tdeforum.modulation import Slot


class TempoTest(unittest.TestCase):
    def test_frames_per_beat_at_60(self):
        self.assertEqual(tempo.frames_per_beat(90, 60), 40)
        self.assertEqual(tempo.frames_per_beat(120, 60), 30)
        self.assertEqual(tempo.frames_per_beat(150, 60), 24)

    def test_cadence_plan(self):
        p = tempo.plan(bpm=120, bars=2, strategy="cadence", overlap_beats=1)
        self.assertEqual((p["render_fps"], p["interp_x"], p["engine"]), (60, 1, None))
        self.assertEqual(p["loop_frames"], 240)
        self.assertEqual(p["overlap_frames"], 30)
        self.assertEqual(p["max_frames"], 270)
        self.assertEqual(p["out_loop_frames"], 240)
        self.assertEqual(p["warnings"], [])

    def test_interpolate_plan(self):
        p = tempo.plan(bpm=150, bars=1, strategy="interpolate", render_fps=15, engine="FILM")
        self.assertEqual((p["render_fps"], p["interp_x"]), (15, 4))
        self.assertEqual(p["loop_frames"], 24)       # 4 beats * 6 frames
        self.assertEqual(p["out_loop_frames"], 96)   # 4 beats * 24 frames at 60

    def test_all_three_tempos_whole_loops_at_30_and_60(self):
        for bpm in (90, 120, 150):
            for strategy, fps in (("cadence", 60), ("interpolate", 30)):
                p = tempo.plan(bpm=bpm, bars=1, strategy=strategy, render_fps=fps)
                self.assertEqual(p["warnings"], [], (bpm, fps))

    def test_drifting_loop_warns(self):
        p = tempo.plan(bpm=90, bars=1, beats_per_bar=1, strategy="interpolate", render_fps=20)
        self.assertTrue(p["warnings"])               # 13.333 frames per beat

    def test_bad_interpolation_rejected(self):
        with self.assertRaises(ValueError):
            tempo.plan(strategy="interpolate", out_fps=60, render_fps=25)

    def test_no_overlap_without_seamless(self):
        p = tempo.plan(bpm=120, seamless=False, overlap_beats=2)
        self.assertEqual(p["overlap_frames"], 0)


class ModulationTest(unittest.TestCase):
    FPB = 30.0

    def test_every_shape_expression_matches_python(self):
        for shape in modulation.SHAPE_NAMES:
            slot = Slot("zoom", shape, beats=1, depth=0.03, phase=0.1, sharpness=5)
            sched, _bounds, mode = modulation.compile_field(1.0, [slot], self.FPB, 150)
            self.assertEqual(mode, "expression")
            got = sim.series(sched, 150)
            for t in range(150):
                self.assertAlmostEqual(got[t], modulation.evaluate(1.0, [slot], self.FPB, t), 9, (shape, t))

    def test_expression_survives_deforums_comma_colon_split(self):
        slots = [Slot("x", s, beats=b, depth=d) for s, b, d in
                 (("square", 2, 0.5), ("bump", 0.5, -1.25), ("decay", 0.25, 2.0))]
        sched, _b, _m = modulation.compile_field(0.0, slots, self.FPB, 10)
        body = sched.split(":", 1)[1]
        self.assertNotIn(",", body)
        self.assertNotIn(":", body)

    def test_constant_and_raw(self):
        self.assertEqual(modulation.compile_field(0.065, [], 30, 10)[0], "0:(0.065)")
        self.assertEqual(modulation.compile_field(1, [], 30, 10, raw="0:(1), 30:(2)")[0], "0:(1), 30:(2)")
        self.assertEqual(modulation.compile_field(1, [], 30, 10, raw="1.5")[0], "0:(1.5)")

    def test_periodic_slots_loop(self):
        slot = Slot("translation_z", "saw_up", beats=2, depth=3)
        sched, _b, _m = modulation.compile_field(0, [slot], self.FPB, 300)
        v = sim.series(sched, 300)
        for t in range(120):          # 4-beat loop = 120 frames
            self.assertAlmostEqual(v[t], v[t + 120], 9)

    def test_loop_warnings(self):
        ok = Slot("zoom", beats=2, depth=0.1, index=1)
        bad = Slot("zoom", beats=3, depth=0.1, index=2)
        self.assertEqual(modulation.loop_warnings([ok], 16), [])
        self.assertEqual(len(modulation.loop_warnings([ok, bad], 16)), 1)

    def test_chop_bake_add_and_replace(self):
        chop = modulation.resample_loop([0.0, 1.0], loop_frames=4, total_frames=6)
        self.assertEqual(chop, [0.0, 0.5, 1.0, 0.5, 0.0, 0.5])   # wraps last -> first, tail repeats
        sched, bounds, mode = modulation.compile_field(2.0, [], 30, 6, chop=chop)
        self.assertEqual(mode, "baked")
        self.assertEqual(sim.series(sched, 6), [2.0, 2.5, 3.0, 2.5, 2.0, 2.5])
        sched, _b, _m = modulation.compile_field(2.0, [], 30, 6, chop=chop, chop_mode="replace")
        self.assertEqual(sim.series(sched, 6)[2], 1.0)
        self.assertEqual(bounds, (2.0, 3.0))

    def test_chop_plus_slots(self):
        slot = Slot("angle", "sine", beats=1, depth=10)
        chop = [1.0] * 60
        sched, _b, _m = modulation.compile_field(0, [slot], self.FPB, 60, chop=chop)
        v = sim.series(sched, 60)
        self.assertAlmostEqual(v[7], 1.0 + 10 * __import__("math").sin(2 * __import__("math").pi * 7 / 30), 4)

    def test_resample_60fps_chop_to_15fps_render(self):
        samples = list(range(120))                 # one 120 bpm bar recorded at 60 fps
        out = modulation.resample_loop(samples, loop_frames=30, total_frames=30)   # rendered at 15 fps
        self.assertEqual(out[:3], [0.0, 4.0, 8.0])


class PromptSeqTest(unittest.TestCase):
    def plan(self, **kw):
        args = dict(bpm=120, bars=2, strategy="cadence", overlap_beats=1)
        args.update(kw)
        return tempo.plan(**args)      # fpb 30, loop 240, overlap 30, max 270

    def test_single_prompt(self):
        prompts, _w = prompt_seq.compile_sequence([("0", "gold", "")], self.plan(seamless=False))
        self.assertEqual(prompts, {"0": "gold"})

    def test_crossfade_weights(self):
        rows = [("beat", "prompt", "xfade"), ("0", "gold", "1"), ("4", "ice", "2")]
        prompts, _w = prompt_seq.compile_sequence(rows, self.plan(seamless=False))
        self.assertEqual(prompts["0"], "gold")
        self.assertEqual(prompts["120"], "ice")
        self.assertIn("90", prompts)                  # fade gold->ice over beat 3..4
        mid = sim.composable_weights(sim.prompt_at(prompts, 105, 240))
        self.assertEqual([p for p, _w in mid], ["gold", "ice"])
        self.assertAlmostEqual(mid[0][1], 0.5)
        self.assertAlmostEqual(mid[0][1] + mid[1][1], 1.0)
        self.assertEqual(sim.prompt_at(prompts, 89, 240), "gold")
        self.assertEqual(sim.prompt_at(prompts, 200, 240), "ice")   # no loop fade

    def test_weights_stay_in_unit_range_through_fade(self):
        rows = [("0", "a", "1"), ("4", "b", "1")]
        prompts, _w = prompt_seq.compile_sequence(rows, self.plan())
        for f in range(270):
            for _p, w in sim.composable_weights(sim.prompt_at(prompts, f, 270)):
                self.assertTrue(-1e-9 <= w <= 1 + 1e-9, (f, w))

    def test_seamless_loop_fades_back_and_tail_repeats_head(self):
        rows = [("0", "a", "1"), ("4", "b", "1")]
        prompts, _w = prompt_seq.compile_sequence(rows, self.plan())
        self.assertEqual(sim.prompt_at(prompts, 240, 270), "a")          # loop point = first prompt
        end = sim.composable_weights(sim.prompt_at(prompts, 225, 270))   # b -> a during the last beat
        self.assertEqual([p for p, _w in end], ["b", "a"])
        for f in range(30):                                              # overlap tail == head
            self.assertEqual(sim.prompt_at(prompts, 240 + f, 270), sim.prompt_at(prompts, f, 270))

    def test_backticks_and_rows_past_loop(self):
        rows = [("0", "a `x`", ""), ("99", "late", "")]
        prompts, warnings = prompt_seq.compile_sequence(rows, self.plan(seamless=False))
        self.assertEqual(prompts, {"0": "a x"})
        self.assertEqual(len(warnings), 2)

    def test_seed_rows_from_prompt_json(self):
        rows = prompt_seq.rows_from_prompts({"0": "a", "60": "b"}, 30.0)
        self.assertEqual(rows, [("0", "a", ""), ("2", "b", "")])


if __name__ == "__main__":
    unittest.main()
