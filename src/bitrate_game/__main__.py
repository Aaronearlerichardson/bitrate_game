"""Package entry point: enables `python -m bitrate_game` and Nuitka builds."""

# Install the warning filter BEFORE any other imports. Pygame's __init__
# is triggered as soon as bitrate_game.main pulls in adapters / renderer,
# and pygame emits a RuntimeWarning of the form "import <name>: <reason>"
# for every "urgent" submodule it can't find in the bundle (image,
# transform, joystick, mouse, sprite, pixelcopy, ... — all of which we
# deliberately exclude via --nofollow-import-to and/or strip_pygame.py).
# The same filter is also installed in bitrate_game/__init__.py for
# safety; this duplicate guarantees the filter is active no matter which
# file Nuitka treats as the program entry on a given platform.
import warnings as _warnings

_warnings.filterwarnings(
    "ignore",
    category=RuntimeWarning,
    message=r"^import \w+:",
)

import sys

from bitrate_game.main import main

if __name__ == "__main__":
    sys.exit(main())
