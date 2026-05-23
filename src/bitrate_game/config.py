"""Single source of truth for game tunables.

All design parameters live here so swapping alphabets, key layouts, or timings
doesn't require touching game logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


# -----------------------------------------------------------------------------
# Hex-o-Spell layout
# -----------------------------------------------------------------------------
# Six selection slots arranged as a 3x2 grid (with a central HUD). Each slot
# holds GROUP_SIZE characters in stage 1. After the first key, the chosen
# group's characters expand into the same six slots for stage 2.
#
# N = NUM_GROUPS * GROUP_SIZE.  Bit-rate formula uses log2(N - 1).

NUM_GROUPS: int = 6
GROUP_SIZE: int = 5  # -> N = 30, log2(29) ≈ 4.858 bits per selection

# The alphabet must satisfy len(ALPHABET) == NUM_GROUPS * GROUP_SIZE.
# Letters first (most familiar to typists), then four punctuation marks to fill
# out the 6th hex group. Order doesn't matter for the i.i.d. property.
ALPHABET: tuple[str, ...] = tuple("abcdefghijklmnopqrstuvwxyz.,!?")


# -----------------------------------------------------------------------------
# Key bindings
# -----------------------------------------------------------------------------
# Six logical "slot keys". Order corresponds to slot index 0..5:
#
#       slot 0 (NW)   slot 1 (N)   slot 2 (NE)
#                       HUD
#       slot 3 (SW)   slot 4 (S)   slot 5 (SE)
#
# Same keys are reused for both stages of the two-step selection.

SLOT_KEYS: tuple[str, ...] = ("q", "w", "e", "a", "s", "d")

# Control keys (string names, mapped to backend key codes by the adapter)
KEY_ADVANCE: str = "space"   # advance from welcome / familiarization start
KEY_START_SCORED: str = "return"  # start the scored 60-second run
KEY_QUIT: str = "escape"


# -----------------------------------------------------------------------------
# Timings
# -----------------------------------------------------------------------------

SCORED_DURATION_SEC: float = 60.0
COUNTDOWN_SEC: float = 3.0
FEEDBACK_FLASH_SEC: float = 0.08  # visual confirmation pulse on each selection


# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------

WINDOW_W: int = 1280
WINDOW_H: int = 800
FPS: int = 120  # high FPS keeps perceived input latency low for fast typists

BG_COLOR = (16, 18, 22)
HUD_COLOR = (220, 224, 232)
TILE_COLOR = (40, 44, 54)
TILE_BORDER_COLOR = (70, 76, 90)
TILE_ACTIVE_COLOR = (60, 100, 160)   # stage-2 highlight on the chosen group
TARGET_HIGHLIGHT_COLOR = (250, 200, 60)
CORRECT_FLASH_COLOR = (80, 200, 120)
INCORRECT_FLASH_COLOR = (220, 80, 80)
TEXT_COLOR = (230, 232, 240)
MUTED_TEXT_COLOR = (140, 144, 156)


# -----------------------------------------------------------------------------
# Derived / validation
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class GameConfig:
    """Frozen snapshot of config for passing into the game.

    Stored as a dataclass so swapping the active config (e.g. for a smaller
    alphabet during development) is a one-line change in main.py.
    """
    alphabet: tuple[str, ...] = ALPHABET
    num_groups: int = NUM_GROUPS
    group_size: int = GROUP_SIZE
    slot_keys: tuple[str, ...] = SLOT_KEYS
    scored_duration_sec: float = SCORED_DURATION_SEC
    countdown_sec: float = COUNTDOWN_SEC

    @property
    def n(self) -> int:
        return len(self.alphabet)

    def __post_init__(self) -> None:
        if self.n != self.num_groups * self.group_size:
            raise ValueError(
                f"alphabet length {self.n} != num_groups * group_size "
                f"({self.num_groups} * {self.group_size})"
            )
        if len(self.slot_keys) != self.num_groups:
            raise ValueError(
                f"slot_keys has {len(self.slot_keys)} keys, expected {self.num_groups}"
            )
        if self.n < 3:
            raise ValueError(f"N must be >= 3 for positive bit rate, got {self.n}")

    def group_of(self, char: str) -> int:
        """Return which group index a character belongs to."""
        return self.alphabet.index(char) // self.group_size

    def index_in_group(self, char: str) -> int:
        """Return the position (0..group_size-1) of a character within its group."""
        return self.alphabet.index(char) % self.group_size

    def chars_in_group(self, group_idx: int) -> Sequence[str]:
        start = group_idx * self.group_size
        return self.alphabet[start : start + self.group_size]


DEFAULT_CONFIG: GameConfig = GameConfig()
