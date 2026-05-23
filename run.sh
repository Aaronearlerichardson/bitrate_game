#!/usr/bin/env bash
# Launches the Hex-o-Spell bit-rate game.
#
# Behavior:
#   1. Create a local .venv if one doesn't exist.
#   2. Install requirements (idempotent — fast on subsequent runs).
#   3. Run the game.
#
# Works on macOS, Linux, and Git Bash / WSL on Windows.
# For native Windows cmd / PowerShell, use run.bat instead.

set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN=python
fi

VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# Pick the right activate path for the platform.
if [ -f "$VENV_DIR/bin/activate" ]; then
    # POSIX
    PY="$VENV_DIR/bin/python"
elif [ -f "$VENV_DIR/Scripts/python.exe" ]; then
    # Git Bash on Windows
    PY="$VENV_DIR/Scripts/python.exe"
else
    echo "Could not locate virtualenv interpreter" >&2
    exit 1
fi

"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r envs/requirements.txt
PYTHONPATH="src" "$PY" -m bitrate_game.main "$@"
