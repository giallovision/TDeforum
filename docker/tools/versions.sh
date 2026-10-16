#!/usr/bin/env bash
# Runs INSIDE the container: `docker exec -i tdeforum-a1111 bash -s < docker/tools/versions.sh`
# Prints the Python stack and the exact source commits that are running.
set -u
python3 - <<'PY'
import importlib
for name in ("torch", "torchvision", "torchaudio", "xformers", "numpy", "transformers"):
    try:
        mod = importlib.import_module(name)
        print("%-13s %s" % (name, getattr(mod, "__version__", "?")))
    except Exception as exc:
        print("%-13s NOT IMPORTABLE (%s)" % (name, exc))
try:
    import torch
    print("%-13s %s | cuda available: %s" % ("cuda", torch.version.cuda, torch.cuda.is_available()))
except Exception:
    pass
PY
for pair in "A1111_REF=/opt/a1111" \
            "DEFORUM_REF=/opt/a1111/extensions/sd-webui-deforum" \
            "CONTROLNET_REF=/opt/a1111/extensions/sd-webui-controlnet"; do
    key="${pair%%=*}"; dir="${pair#*=}"
    echo "${key}=$(git -C "$dir" rev-parse HEAD 2>/dev/null || echo unknown)"
done
