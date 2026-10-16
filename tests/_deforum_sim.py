"""Test-only replica of how Deforum 5d63a339 turns strings into per-frame values.

Mirrors scripts/deforum_helpers/animation_key_frames.py (parse_key_frames,
get_inbetweens) and prompt.py (prepare_prompt). numexpr is replaced by a
restricted Python eval with the same function names; for the operators and
functions the generated expressions use (+ - * / ** %, sin cos tanh exp abs)
the results are identical for the non-negative arguments we produce.
"""

import ast
import math
import re

_FUNCS = {"sin": math.sin, "cos": math.cos, "tan": math.tan, "tanh": math.tanh,
          "exp": math.exp, "abs": abs, "sqrt": math.sqrt, "log": math.log}


def _div(a, b):
    # numexpr.evaluate(truediv='auto') only uses true division when the *caller's*
    # module did `from __future__ import division`; Deforum's modules do not, so
    # int / int floor-divides there. Reproduce that so tests catch t/30 vs t/30.0.
    if isinstance(a, int) and isinstance(b, int):
        return a // b
    return a / b


class _DivToCall(ast.NodeTransformer):
    def visit_BinOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Div):
            return ast.copy_location(
                ast.Call(func=ast.Name(id="_div", ctx=ast.Load()), args=[node.left, node.right], keywords=[]),
                node)
        return node


def _numexpr(expr, **names):
    tree = ast.fix_missing_locations(_DivToCall().visit(ast.parse(expr.strip(), mode="eval")))
    scope = dict(_FUNCS, _div=_div)
    scope.update(names)
    return float(eval(compile(tree, "<numexpr>", "eval"), {"__builtins__": {}}, scope))  # noqa: S307


def _sanitize(value):
    return value.replace("'", "").replace('"', "").replace("(", "").replace(")", "")


def _is_number(value):
    try:
        float(value)
        return True
    except ValueError:
        return False


def parse_key_frames(string, max_frames, seed=0):
    frames = {}
    for part in string.split(","):
        param = part.split(":")
        key = _sanitize(param[0]).strip()
        if _is_number(key):
            frame = int(key)
        else:
            frame = int(_numexpr(param[0].strip().strip("'\""), max_f=max_frames - 1, s=seed))
        frames[frame] = param[1].strip()   # NB: anything after a 2nd ':' is lost, like Deforum
    if not frames and string:
        raise RuntimeError("Key Frame string not correctly formatted")
    return frames


def series(string, max_frames, seed=0):
    """Per-frame float values exactly as get_inbetweens(Linear) builds them."""
    keys = parse_key_frames(string, max_frames, seed)
    values = [None] * max_frames
    value_is_number = False
    value = None
    for i in range(max_frames):
        if i in keys:
            value = keys[i]
            value_is_number = _is_number(_sanitize(value))
            if value_is_number:
                values[i] = float(_sanitize(value))
        if not value_is_number and value is not None:
            values[i] = _numexpr(value, t=i, max_f=max_frames - 1, s=seed)
    known = [i for i, v in enumerate(values) if v is not None]
    values[0] = values[known[0]]
    values[-1] = values[known[-1]]
    known = [i for i, v in enumerate(values) if v is not None]
    for i in range(max_frames):  # linear interpolation, limit_direction both
        if values[i] is None:
            lo = max(k for k in known if k < i)
            hi = min(k for k in known if k > i)
            values[i] = values[lo] + (values[hi] - values[lo]) * (i - lo) / float(hi - lo)
    return values


def prompt_at(prompts, frame, max_frames):
    """Prompt text Deforum hands to A1111 at a frame (held keys + backtick math)."""
    held = None
    for key in sorted(prompts, key=lambda k: int(k)):
        if int(key) <= frame:
            held = prompts[key]
    if held is None:
        held = prompts[sorted(prompts, key=lambda k: int(k))[0]]
    out = held
    for match in re.finditer(r"`.*?`", held):
        expr = match.group(0).replace("t", str(frame)).replace("max_f", str(max_frames - 1)).replace("`", "")
        out = out.replace(match.group(0), str(_numexpr(expr)))
    return out


def composable_weights(prompt):
    """'a :0.25 AND b :0.75' -> [('a', 0.25), ('b', 0.75)] (A1111 composable syntax)."""
    parts = []
    for chunk in prompt.split(" AND "):
        m = re.match(r"^(.*?)\s*:\s*([-+]?(?:\d+\.?\d*|\d*\.\d+))\s*$", chunk.strip())
        parts.append((m.group(1), float(m.group(2))) if m else (chunk.strip(), 1.0))
    return parts
