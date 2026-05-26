#!/usr/bin/env python3
"""Remove unused pygame submodules and their bundled native libraries.

Pygame's manylinux/macos wheel ships every submodule (mixer, image, midi,
transform, ...) and the entire SDL satellite ecosystem (SDL2_mixer,
SDL2_image, fluidsynth, PulseAudio, ALSA, libdbus, libsystemd, ...) so that
a single wheel works for every pygame app. This game only uses event,
display, font, time, draw, and the Rect/Surface/Color primitives — so we
delete the rest from the installed pygame package BEFORE Nuitka inspects it.

This is the only reliable way to keep those files out of a Nuitka build:
  * Python-level `--nofollow-import-to` doesn't stop Nuitka's pygame plugin
    from bundling the compiled `.so`/`.pyd` files anyway.
  * `--noinclude-data-files` doesn't apply to actual DLL/SO dependencies.
  * `--noinclude-dlls` would work, but the Nuitka-Action wrapper doesn't
    expose it.

Empirically saves ~10 MB on Linux. macOS savings are similar in proportion.

WARNING: destructive. Modifies the installed pygame in-place. Run in CI or
a throwaway env, not your day-to-day Python.
"""

from __future__ import annotations

import sys
from pathlib import Path


# pygame submodule shared-library files to delete. Each removes the module
# from the bundle AND eliminates the demand for its native dependencies.
# Cross-checked against pygame/__init__.py: every entry here is imported in a
# try/except (ImportError, OSError) wrapper, so the missing module becomes a
# `MissingModule` placeholder rather than crashing `import pygame`.
UNUSED_PYGAME_MODULES = [
    "mixer",
    "mixer_music",
    "image",
    "imageext",
    "_camera",
    "_freetype",  # we use pygame.font (SDL2_ttf), not pygame._freetype
    "_sprite",    # only used by pygame.sprite, which we don't import
    "scrap",
    "transform",
    "gfxdraw",
    "pypm",       # MIDI
    "joystick",
    "mouse",      # we use keyboard only
    "cursors",
    "mask",
    "sndarray",
    "surfarray",
    "fastevent",
    "pixelarray",
    "pixelcopy",
    "overlay",
    "threads",
]


# Native-lib prefixes safe to delete. Each is used ONLY by one of the
# pygame submodules above (per the Nuitka report's `Used by ...` field).
# Conservative list: libfreetype, libharfbuzz, libpng, libbrotli, liblzma,
# libcrypto, libbz2 are deliberately KEPT — they're needed by SDL2_ttf
# (which we use through pygame.font) or by Python's own stdlib extensions.
UNUSED_LIB_PREFIXES = [
    # SDL satellites
    "libSDL2_mixer",
    "libSDL2_image",
    # Audio codecs (mixer)
    "libfluidsynth",
    "libsndfile",
    "libogg",
    "libvorbis",
    "libFLAC",
    "libopus",
    "libopusfile",
    "libmpg123",
    "libwavpack",
    "libmodplug",
    # Audio backends (mixer)
    "libasound",
    "libpulse",
    "libpulsecommon",
    "libpulse-simple",
    "libjack",
    "libpipewire",
    "libsndio",
    # Image codecs (image / imageext)
    "libwebp",
    "libsharpyuv",
    "libjpeg",
    "libtiff",
    # MIDI
    "libportmidi",
    # Mixer transitive deps (all credited to mixer.so in the report)
    "libdbus",
    "libgcrypt",
    "libgpg-error",
    "libsystemd",
    "libelf",
    "libdw",
    "libgomp",
    "libattr",
    "libcap",
    "libselinux",
    "libpcre",
    "liblz4",
]


def _candidate_libs_dirs(pygame_dir: Path) -> list[Path]:
    """Locations a pygame wheel may stash its bundled native libs in.

    Linux manylinux wheels use a sibling pygame.libs/ dir. macOS wheels use
    .dylibs/ inside pygame/. Windows wheels drop DLLs directly into pygame/
    alongside the .pyd modules — so pygame_dir itself is included here too.
    """
    return [
        pygame_dir,                          # Windows: DLLs live with the .pyd
        pygame_dir.parent / "pygame.libs",   # Linux manylinux convention
        pygame_dir / ".libs",                # alternative Linux layout
        pygame_dir / ".dylibs",              # macOS
    ]


def _is_unused_lib(basename: str) -> bool:
    """True if `basename` matches one of the UNUSED_LIB_PREFIXES.

    Windows DLLs often lack the 'lib' prefix that Linux/macOS use
    (e.g. SDL2_mixer.dll vs libSDL2_mixer-2-...so.0), so we match both
    forms case-insensitively.
    """
    name = basename.lower()
    for prefix in UNUSED_LIB_PREFIXES:
        p = prefix.lower()
        if name.startswith(p):
            return True
        if p.startswith("lib") and name.startswith(p[3:]):
            return True
    return False


_NATIVE_LIB_EXTS = (".dll", ".so", ".dylib")


def _looks_like_native_lib(name: str) -> bool:
    """Match .dll/.dylib endings plus Linux versioned sonames like .so.0.1.2."""
    lower = name.lower()
    if lower.endswith(_NATIVE_LIB_EXTS):
        return True
    # Linux versioned sonames: libfoo.so.X[.Y[.Z]]
    return ".so." in lower


def main() -> int:
    import pygame  # noqa: PLC0415 — defer so we can print the path on error

    pygame_dir = Path(pygame.__file__).resolve().parent
    print(f"pygame at: {pygame_dir}")

    removed_count = 0
    removed_bytes = 0

    # 1. Delete pygame submodule extension files (.so / .pyd / .dylib).
    for mod in UNUSED_PYGAME_MODULES:
        patterns = [
            f"{mod}.*.so",
            f"{mod}.*.pyd",
            f"{mod}.*.dylib",
            f"{mod}.so",
            f"{mod}.pyd",
        ]
        for pattern in patterns:
            for f in pygame_dir.glob(pattern):
                size = f.stat().st_size
                print(f"rm pygame/{f.name} ({size/1024:.0f} KB)")
                f.unlink()
                removed_count += 1
                removed_bytes += size

    # 2. Delete bundled native libs from any of the candidate locations.
    # On Windows this includes pygame/ itself; the _is_unused_lib filter
    # makes sure we don't touch SDL2.dll / SDL2_ttf.dll / freetype.dll /
    # libpng16 / etc., which the renderer still needs.
    seen: set[Path] = set()
    for libs_dir in _candidate_libs_dirs(pygame_dir):
        if not libs_dir.is_dir() or libs_dir in seen:
            continue
        seen.add(libs_dir)
        print(f"Scanning {libs_dir}")
        for f in sorted(libs_dir.iterdir()):
            if not f.is_file() or not _looks_like_native_lib(f.name):
                continue
            if _is_unused_lib(f.name):
                size = f.stat().st_size
                print(f"  rm {f.name} ({size/1024:.0f} KB)")
                f.unlink()
                removed_count += 1
                removed_bytes += size

    print(
        f"\nStripped {removed_count} files, "
        f"{removed_bytes/1024/1024:.1f} MB total."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
