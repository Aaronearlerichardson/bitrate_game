#!/usr/bin/env bash
# Launches the prebuilt Hex-o-Spell binary for the host platform.
#
# The binary is produced by scripts/build.py (Nuitka). This launcher does NOT
# create a venv or install anything — it only resolves <os>-<arch> and execs
# the matching artifact under dist/.
#
# Works on macOS, Linux, and Git Bash / WSL on Windows.
# For native Windows cmd / PowerShell, use run.bat instead.

set -euo pipefail
cd "$(dirname "$0")"

# --- Detect OS ---
case "$(uname -s)" in
    Darwin)               PLATFORM="macos" ;;
    Linux)                PLATFORM="linux" ;;
    MINGW*|MSYS*|CYGWIN*) PLATFORM="windows" ;;
    *)
        echo "Unsupported OS: $(uname -s)" >&2
        exit 1
        ;;
esac

# --- Detect arch ---
case "$(uname -m)" in
    x86_64|amd64)   ARCH="x86_64" ;;
    arm64|aarch64)  ARCH="arm64"  ;;
    *)
        echo "Unsupported arch: $(uname -m)" >&2
        exit 1
        ;;
esac

EXE_NAME="bitrate_game-${PLATFORM}-${ARCH}"
[ "$PLATFORM" = "windows" ] && EXE_NAME="${EXE_NAME}.exe"

# Locate either a onefile binary at dist/<name> or a standalone bundle
# at dist/bitrate_game-<os>-<arch>/<name>.
ONEFILE="dist/${EXE_NAME}"
BUNDLE="dist/bitrate_game-${PLATFORM}-${ARCH}/${EXE_NAME}"

if [ -f "$ONEFILE" ]; then
    EXE="$ONEFILE"
elif [ -f "$BUNDLE" ]; then
    EXE="$BUNDLE"
else
    echo "No prebuilt binary for ${PLATFORM}-${ARCH}." >&2
    echo "Expected one of:" >&2
    echo "  $ONEFILE" >&2
    echo "  $BUNDLE" >&2
    echo "Build it first:" >&2
    echo "  python scripts/build.py" >&2
    exit 1
fi

exec "$EXE" "$@"
