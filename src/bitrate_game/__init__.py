"""GridQuest — a spatial-selection game that maximizes BCI-style bit rate."""

import warnings as _warnings

# Pygame's __init__.py imports its submodules inside `try / except
# (ImportError, OSError)` blocks. When the imported submodule is "urgent"
# (e.g. pygame.image, pygame.transform) and not present in the bundle —
# which is the case for our Nuitka builds, where those modules are
# excluded via --nofollow-import-to and/or physically stripped — pygame
# emits a RuntimeWarning of the form "import <name>: <reason>". The
# module is then substituted with a MissingModule placeholder and the
# rest of pygame works fine, so the warnings are pure stderr noise.
#
# Install the filter at package-import time so it's active before any
# of our submodules (adapters / renderer) trigger `import pygame`.
_warnings.filterwarnings(
    "ignore",
    category=RuntimeWarning,
    message=r"^import \w+:",
)

__version__ = "0.3.0"
