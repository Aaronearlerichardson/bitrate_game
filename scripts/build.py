#!/usr/bin/env python3
"""Build a standalone executable for the current platform with Nuitka.

Output: dist/bitrate_game-<os>-<arch>[.exe]

The launchers (run.sh / run.bat) detect host OS+arch and exec the matching
binary from dist/. Nuitka does not cross-compile, so each target platform
must run this script on a matching host (or via CI matrix).

Default build is tuned for small size: LTO on, audio/image/MIDI pygame
submodules dropped, unused SDL libraries excluded from the bundle, runtime
asserts/docstrings/warnings stripped. Pass --no-slim to disable.

Usage:
    python scripts/build.py                 # onefile, slim, default
    python scripts/build.py --standalone    # folder bundle (faster startup)
    python scripts/build.py --clean         # wipe dist/ and build/ first
    python scripts/build.py --upx           # additionally UPX-compress (Win/Linux)
    python scripts/build.py --no-slim       # disable slim defaults
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
ENTRY = SRC_DIR / "bitrate_game"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"

# Pygame submodules the game never touches. Skipping them prevents Nuitka
# from chasing imports into SDL2_mixer / SDL2_image / portmidi territory.
# Verified by grepping src/bitrate_game for pygame.* usage: only event,
# display, font.SysFont, time.Clock, draw, Rect, Surface are referenced.
UNUSED_PYGAME_MODULES = [
    # Audio / image / MIDI / camera — game has no sound or images.
    "pygame.mixer",
    "pygame.mixer_music",
    "pygame.image",
    "pygame.midi",
    "pygame.camera",
    "pygame.cdrom",
    "pygame._sdl2.audio",
    "pygame._sdl2.mixer",
    # NumPy-coupled pygame views and other pygame submodules unused by
    # this game (renderer only uses pygame.draw + pygame.font.SysFont).
    "pygame.surfarray",
    "pygame.sndarray",
    "pygame.scrap",
    "pygame.transform",
    "pygame.gfxdraw",
    "pygame.fastevent",
    "pygame.examples",
    "pygame.tests",
    "pygame.docs",
    # numpy itself — defensive in case any pygame submodule pulls it in
    # transitively. 30+ MB if it sneaks into the bundle.
    "numpy",
    # Stdlib modules a shipped game has no reason to include.
    "tkinter",
    "unittest",
    "test",
    "pydoc",
    "idlelib",
    "ensurepip",
    "lib2to3",
    "turtle",
    "turtledemo",
]

# DLL/SO/dylib name patterns Nuitka's pygame plugin would otherwise bundle
# but that we don't need (audio codecs, image codecs, MIDI). Patterns use a
# leading wildcard so they match both Windows DLLs ("SDL2_mixer.dll") and
# Linux/macOS shared libs with versioned sonames ("libSDL2_mixer-2.0.so.0",
# "libSDL2_mixer-2.0.0.dylib"). Linux is where the real size wins live —
# pygame manylinux wheels bundle every audio backend (Pulse, ALSA, JACK,
# sndio, PipeWire, fluidsynth), all of which we drop here.
UNUSED_NATIVE_LIBS = [
    # SDL satellite libs
    "*SDL2_mixer*",
    "*SDL2_image*",
    # Audio codecs (only used by SDL2_mixer)
    "*libogg*",
    "*libvorbis*",
    "*libvorbisfile*",
    "*libFLAC*",
    "*libopus*",
    "*libopusfile*",
    "*libmpg123*",
    "*libwavpack*",
    "*libmodplug*",
    "*libfluidsynth*",
    "*libsndfile*",
    # Image codecs (only used by SDL2_image)
    "*libwebp*",
    "*libjpeg*",
    "*libtiff*",
    # Linux audio backends — pygame ships all of them in the wheel
    "*libpulse*",
    "*libpulsecommon*",
    "*libasound*",
    "*libsndio*",
    "*libjack*",
    "*libpipewire*",
    # MIDI
    "*portmidi*",
]


def platform_tag() -> str:
    """Return '<os>-<arch>' tag used in the binary filename."""
    system = platform.system().lower()
    if system == "darwin":
        system = "macos"
    arch = platform.machine().lower()
    arch = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(arch, arch)
    return f"{system}-{arch}"


def output_filename() -> str:
    name = f"bitrate_game-{platform_tag()}"
    if platform.system() == "Windows":
        name += ".exe"
    return name


def run_nuitka(*, onefile: bool, clean: bool, slim: bool, upx: bool) -> int:
    if clean:
        for d in (DIST_DIR, BUILD_DIR):
            if d.exists():
                print(f"Removing {d}")
                shutil.rmtree(d)
    DIST_DIR.mkdir(exist_ok=True)
    BUILD_DIR.mkdir(exist_ok=True)

    out_name = output_filename()

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--assume-yes-for-downloads",
        "--standalone",
        "--include-package=bitrate_game",
        f"--output-dir={BUILD_DIR}",
        f"--output-filename={out_name}",
        "--remove-output",
        str(ENTRY),
    ]
    if onefile:
        cmd.append("--onefile")

    if slim:
        cmd += [
            "--lto=yes",
            # 'no_warnings' would strip the warnings module loader, which
            # CPython's startup tries to `import warnings` regardless and
            # then prints "'import warnings' failed; ModuleNotFoundError"
            # to stderr on every launch. 'no_site' similarly off because
            # site.py setup happens around the same init step.
            "--python-flag=no_asserts,no_docstrings",
            # pygame's __init__.py imports its submodules inside try/except
            # blocks. Nuitka's default behavior is to emit a RuntimeWarning
            # when such an import hits a `--nofollow-import-to` exclusion
            # ("Module 'pygame.image' was actively excluded ..."). It's
            # harmless — pygame catches the ImportError and uses a
            # MissingModule placeholder — but it's noisy on every launch.
            # Suppress just this one warning class:
            "--no-deployment-flag=excluded-module-usage",
        ]
        # Static-link libpython where possible. Saves ~5 MB on Linux,
        # which is by far the most bloated platform for pygame builds.
        # No-op on Windows (always static); harmless if unavailable.
        if platform.system() != "Windows":
            cmd.append("--static-libpython=auto")
        for mod in UNUSED_PYGAME_MODULES:
            cmd.append(f"--nofollow-import-to={mod}")
        for pat in UNUSED_NATIVE_LIBS:
            # --noinclude-dlls works on Windows DLLs; --noinclude-data-files
            # catches .so/.dylib copies the pygame plugin drops in as data.
            cmd.append(f"--noinclude-dlls={pat}")
            cmd.append(f"--noinclude-data-files={pat}")

    env = {**os.environ, "PYTHONPATH": str(SRC_DIR)}

    print("Running:")
    print("  " + " ".join(cmd))
    print()

    result = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
    if result.returncode != 0:
        print(f"\nNuitka build failed (exit {result.returncode}).", file=sys.stderr)
        return result.returncode

    # --- Move/rename the artifact into dist/ ---
    if onefile:
        produced = BUILD_DIR / out_name
        if not produced.exists():
            print(f"Expected onefile artifact missing: {produced}", file=sys.stderr)
            return 1
        target = DIST_DIR / out_name
        if target.exists():
            target.unlink()
        shutil.move(str(produced), str(target))
        if platform.system() != "Windows":
            target.chmod(target.stat().st_mode | 0o111)
        if upx:
            _upx_compress(target)
        print(f"\nBuilt: {target}  ({_human_size(target)})")
    else:
        dist_subdir = BUILD_DIR / f"{ENTRY.stem}.dist"
        if not dist_subdir.exists():
            print(
                f"Expected standalone bundle missing: {dist_subdir}",
                file=sys.stderr,
            )
            return 1
        target_dir = DIST_DIR / f"bitrate_game-{platform_tag()}"
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(dist_subdir), str(target_dir))
        entry_path = target_dir / out_name
        if platform.system() != "Windows" and entry_path.exists():
            entry_path.chmod(entry_path.stat().st_mode | 0o111)
        if upx and entry_path.exists():
            _upx_compress(entry_path)
        print(f"\nBuilt bundle: {target_dir}  ({_human_size_dir(target_dir)})")
        print(f"Entry: {entry_path}")

    return 0


def _human_size(p: Path) -> str:
    n = p.stat().st_size
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _human_size_dir(p: Path) -> str:
    total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    n = float(total)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _upx_compress(target: Path) -> None:
    """Run UPX on `target` in place. Skips silently if upx isn't installed."""
    if shutil.which("upx") is None:
        print("upx not found on PATH — skipping compression.", file=sys.stderr)
        return
    if platform.system() == "Darwin":
        print("upx on macOS binaries is unreliable — skipping.", file=sys.stderr)
        return
    before = target.stat().st_size
    print(f"\nCompressing with UPX: {target}")
    result = subprocess.run(["upx", "--best", "--lzma", str(target)])
    if result.returncode != 0:
        print("upx failed; binary left uncompressed.", file=sys.stderr)
        return
    after = target.stat().st_size
    print(f"  {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Produce a folder bundle instead of a single-file binary.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove dist/ and build/ before building.",
    )
    parser.add_argument(
        "--no-slim",
        dest="slim",
        action="store_false",
        help="Disable size-reduction defaults (LTO, pruned pygame/SDL deps, "
             "stripped docstrings/asserts).",
    )
    parser.add_argument(
        "--upx",
        action="store_true",
        help="Run UPX on the final binary (requires upx on PATH). Big size "
             "win on Windows/Linux; skipped on macOS.",
    )
    args = parser.parse_args(argv)
    return run_nuitka(
        onefile=not args.standalone,
        clean=args.clean,
        slim=args.slim,
        upx=args.upx,
    )


if __name__ == "__main__":
    sys.exit(main())
