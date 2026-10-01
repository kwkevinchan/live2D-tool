#!/usr/bin/env bash
# Checks that need no ComfyUI and no window: every Python tool compiles and imports, and the Godot player's rules
# (Tests/live/puppet_test.tscn, headless). Run from anywhere; exit status 1 when anything fails.
#   Tools/run_tests.sh            LIVE2D_PYTHON picks the Python (default: python)
set -u
cd "$(dirname "$0")/.."
PY="${LIVE2D_PYTHON:-python}"
fail=0

echo "== Python: compile"
"$PY" -m py_compile Tools/art/*.py Tools/live2d_studio/app.py || fail=1

echo "== Python: import"
# multiview.py needs MV-Adapter's own environment (torch, diffusers): compiled above, not imported here
PYTHONIOENCODING=utf-8 "$PY" - <<'EOF' || fail=1
import importlib, os, sys
sys.path.insert(0, os.path.join("Tools", "art"))
bad = 0
for f in sorted(os.listdir(os.path.join("Tools", "art"))):
    if f.endswith(".py") and f != "multiview.py":
        try:
            importlib.import_module(f[:-3])
        except Exception as e:
            print("  FAIL %s: %r" % (f, e))
            bad += 1
print("  %s" % ("ok" if not bad else "%d failed" % bad))
sys.exit(1 if bad else 0)
EOF

echo "== Godot: puppet_test"
GODOT="$(PYTHONIOENCODING=utf-8 "$PY" -c "import sys; sys.path.insert(0, 'Tools/art'); import config; print(config.GODOT)")"
if [ -z "$GODOT" ] || [ ! -e "$GODOT" ]; then
    echo "  no Godot (live2d.toml [paths] godot, or GODOT)"
    fail=1
else
    out="$("$GODOT" --headless --path . res://Tests/live/puppet_test.tscn 2>&1)"
    code=$?
    echo "$out" | grep -E "puppet:|FAIL" | sed 's/^/  /'
    [ $code -eq 0 ] || fail=1
fi

[ $fail -eq 0 ] && echo "== all passed" || echo "== FAILED"
exit $fail
