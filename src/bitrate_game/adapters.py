"""Input adapters.

The InputAdapter protocol decouples the game from any specific input device
or library. The pygame keyboard adapter is the default; future adapters
might include MIDI, gamepad, mouse-region, or a websocket bridge from a
browser frontend.

Every adapter emits a normalized stream of InputEvent values. The game
loop only ever sees InputEvent instances — it doesn't know about scan codes,
modifier keys, or anything backend-specific.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Protocol, Sequence

from . import config
from .config import GameConfig


# -----------------------------------------------------------------------------
# Normalized input events
# -----------------------------------------------------------------------------

class InputEventType(Enum):
    SLOT = auto()      # a slot-key (Q/W/E/A/S/D etc.) was pressed
    ADVANCE = auto()   # advance phase (welcome -> familiarize, results -> welcome)
    START_SCORED = auto()  # familiarization -> countdown -> scored
    QUIT = auto()      # user wants to quit
    WINDOW_CLOSE = auto()  # window's close button


@dataclass(frozen=True)
class InputEvent:
    type: InputEventType
    slot_idx: Optional[int] = None  # only meaningful for SLOT


# -----------------------------------------------------------------------------
# InputAdapter protocol
# -----------------------------------------------------------------------------

class InputAdapter(Protocol):
    """Source of normalized input events.

    poll() is called once per frame and returns all events accumulated since
    the previous call. The order matters (preserves key-press ordering).
    """
    def poll(self) -> Sequence[InputEvent]: ...
    def shutdown(self) -> None: ...


# -----------------------------------------------------------------------------
# Pygame keyboard adapter
# -----------------------------------------------------------------------------

class PygameKeyboardAdapter:
    """Maps pygame KEYDOWN events to InputEvents.

    All key bindings come from GameConfig — change the layout there, not here.
    """

    def __init__(self, cfg: GameConfig) -> None:
        # Import inside the constructor so importing this module doesn't
        # require pygame at parse time. (Helps unit tests on machines
        # without SDL.)
        import pygame
        self._pygame = pygame

        # Build a slot-key map: pygame key code -> slot index.
        self._slot_map: dict[int, int] = {}
        for idx, name in enumerate(cfg.slot_keys):
            self._slot_map[self._keycode(name)] = idx

        self._advance_key = self._keycode("space")
        self._start_scored_key = self._keycode("return")
        self._quit_key = self._keycode("escape")

    def _keycode(self, name: str) -> int:
        """Resolve a friendly key name (config-level) to a pygame keycode.

        Accepts lowercase letters and a few named control keys.
        """
        pg = self._pygame
        special = {
            "space": pg.K_SPACE,
            "return": pg.K_RETURN,
            "enter": pg.K_RETURN,
            "escape": pg.K_ESCAPE,
            "tab": pg.K_TAB,
        }
        if name in special:
            return special[name]
        if len(name) == 1 and name.isalpha():
            return getattr(pg, f"K_{name.lower()}")
        raise ValueError(f"unknown key name: {name!r}")

    def poll(self) -> list[InputEvent]:
        out: list[InputEvent] = []
        pg = self._pygame
        for ev in pg.event.get():
            if ev.type == pg.QUIT:
                out.append(InputEvent(InputEventType.WINDOW_CLOSE))
            elif ev.type == pg.VIDEORESIZE:
                # User dragged the window edge. Recreate the display
                # surface at the new size and update the layout constants
                # the renderer reads each frame. A floor of 800x500 keeps
                # the hex board legible — anything smaller crops tiles.
                new_w = max(ev.w, 800)
                new_h = max(ev.h, 500)
                pg.display.set_mode((new_w, new_h), pg.RESIZABLE)
                config.WINDOW_W = new_w
                config.WINDOW_H = new_h
            elif ev.type == pg.KEYDOWN:
                if ev.key in self._slot_map:
                    out.append(InputEvent(InputEventType.SLOT,
                                          slot_idx=self._slot_map[ev.key]))
                elif ev.key == self._advance_key:
                    out.append(InputEvent(InputEventType.ADVANCE))
                elif ev.key == self._start_scored_key:
                    out.append(InputEvent(InputEventType.START_SCORED))
                elif ev.key == self._quit_key:
                    out.append(InputEvent(InputEventType.QUIT))
                # other keys: silently ignored (no penalty — see README)
        return out

    def shutdown(self) -> None:
        # The adapter doesn't own pygame.quit(); the renderer does.
        pass
