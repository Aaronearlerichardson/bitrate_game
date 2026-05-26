"""Single source of truth for game tunables.

All design parameters live here so swapping key layouts, grid size, or
timings doesn't require touching game logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


# -----------------------------------------------------------------------------
# GridQuest layout
# -----------------------------------------------------------------------------
# Nine selection tiles arranged as a 3x3 grid. Each selection takes two
# keypresses:
#   * key 1 picks one of 9 outer "groups" (which 3x3 cell of the mini-9x9
#     reference board contains the target).
#   * key 2 picks one of 9 inner positions within that group.
#
# N = NUM_TILES * NUM_TILES = 81.  Bit-rate formula uses log2(N - 1).

NUM_TILES: int = 9  # 3x3 grid of selection tiles, reused for both stages


# -----------------------------------------------------------------------------
# Key bindings
# -----------------------------------------------------------------------------
# Nine logical "slot keys", spatially mapped to the 3x3 grid:
#
#       slot 0 (NW)   slot 1 (N)   slot 2 (NE)
#       slot 3 (W)    slot 4 (C)   slot 5 (E)
#       slot 6 (SW)   slot 7 (S)   slot 8 (SE)
#
# Same nine keys are reused for both stages of the two-step selection.

SLOT_KEYS: tuple[str, ...] = ("q", "w", "e", "a", "s", "d", "z", "x", "c")

# Control keys (string names, mapped to backend key codes by the adapter)
KEY_ADVANCE: str = "space"        # context-sensitive: start practice / back to welcome
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
    grid during development) is a one-line change in main.py.
    """
    num_tiles: int = NUM_TILES
    slot_keys: tuple[str, ...] = SLOT_KEYS
    scored_duration_sec: float = SCORED_DURATION_SEC
    countdown_sec: float = COUNTDOWN_SEC

    @property
    def n(self) -> int:
        """Total number of distinguishable targets: 9 * 9 = 81."""
        return self.num_tiles * self.num_tiles

    @property
    def alphabet(self) -> Sequence[int]:
        """Target alphabet: integers 0..n-1.

        Each target T decomposes as `divmod(T, num_tiles) -> (group, slot)`.
        Exposed so TargetSource implementations can be alphabet-agnostic.
        """
        return range(self.n)

    def __post_init__(self) -> None:
        if len(self.slot_keys) != self.num_tiles:
            raise ValueError(
                f"slot_keys has {len(self.slot_keys)} keys, expected "
                f"{self.num_tiles}"
            )
        if self.num_tiles < 2:
            raise ValueError(
                f"num_tiles must be >= 2 for two-stage selection, got "
                f"{self.num_tiles}"
            )
        if self.n < 3:
            raise ValueError(
                f"N must be >= 3 for positive bit rate, got {self.n}"
            )


DEFAULT_CONFIG: GameConfig = GameConfig()
