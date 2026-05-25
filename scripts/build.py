#!/usr/bin/env python3
"""Build a standalone executable for the current platform with Nuitka.

Output: dist/bitrate_game-<os>-<arch>[.exe]

The launchers (run.sh / run.bat) detect host OS+arch and exec the matching
binary from dist/. Nuitka does not cross-compile, so each target platform
must run this script on a matching host (or via CI matrix).

Usage:
    python scripts/build.py                 # onefile, default
    python scripts/build.py --standalone    # folder bundle (faster startup)
    python scripts/build.py --clean         # wipe dist/ and build/ first
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
ENTRY = SRC_DIR / "bitrate_game" / "main.py"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"


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


def run_nuitka(*, onefile: bool, clean: bool) -> int:
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
        # Make sure it's executable on POSIX.
        if platform.system() != "Windows":
            target.chmod(target.stat().st_mode | 0o111)
        print(f"\nBuilt: {target}")
    else:
        # Standalone mode produces a <entry>.dist folder.
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
        # The launcher will exec the binary at the top of the bundle. Nuitka
        # names it after --output-filename, which we already set.
        entry_path = target_dir / out_name
        if platform.system() != "Windows" and entry_path.exists():
            entry_path.chmod(entry_path.stat().st_mode | 0o111)
        print(f"\nBuilt bundle: {target_dir}")
        print(f"Entry: {entry_path}")

    return 0


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
    args = parser.parse_args(argv)
    return run_nuitka(onefile=not args.standalone, clean=args.clean)


if __name__ == "__main__":
    sys.exit(main())
