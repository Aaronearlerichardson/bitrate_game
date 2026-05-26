"""Game-mode abstraction.

A GameMode encapsulates *the selection rules* — how the player turns input
into a selection event. It's the swap point for trying different paradigms
(GridQuest, direct typing, center-out, etc.) without touching anything else.

The mode is fed normalized input via handle_slot_key(slot_idx). It owns
the current target and the partial-selection state (e.g. "first key pressed,
waiting for second"), and emits a SelectionResult when a selection completes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Protocol

from .config import GameConfig
from .core import TargetSource


# -----------------------------------------------------------------------------
# Shared types
# -----------------------------------------------------------------------------

@dataclass
class SelectionResult:
    """Returned by a GameMode when a selection completes."""
    correct: bool
    target: int              # cued target index in [0, N)
    selected: Optional[int]  # what the player actually picked (None if invalid)


# -----------------------------------------------------------------------------
# GridQuest view model
#
# These dataclasses describe what to draw. The renderer reads them and is
# completely agnostic about *how* the game decides what's in each tile.
# -----------------------------------------------------------------------------

class GridStage(Enum):
    GROUP_SELECT = auto()  # 9 tiles each represent one of 9 outer groups
    TILE_SELECT = auto()   # 9 tiles each represent one inner position within the chosen group


@dataclass
class GridSlotView:
    """One of the nine tiles in the GridQuest 3x3 layout.

    Stage-1 highlight: the tile that contains the target group.
    Stage-2 highlight: the tile that *is* the target slot.
    """
    is_target_group: bool   # stage 1: this tile's group contains the cued target
    is_target_tile: bool    # stage 2: this tile is the exact target slot


@dataclass
class GridView:
    """Complete renderable view of the GridQuest mode."""
    stage: GridStage
    target: int                              # current cued target, 0..N-1
    slots: tuple[GridSlotView, ...]          # always num_tiles entries
    active_group_idx: Optional[int]          # set in stage 2 to indicate the chosen group
    last_feedback_correct: Optional[bool]    # None / True / False — for flash
    last_feedback_at: float                  # monotonic timestamp


# -----------------------------------------------------------------------------
# GameMode protocol
# -----------------------------------------------------------------------------

class GameMode(Protocol):
    """A selection paradigm.

    Implementations:
      - decide what target is being cued,
      - convert raw 'slot key' presses into a complete selection,
      - expose a renderable view of the current state.

    Different modes (GridQuest, direct keyboard, SSVEP-style, center-out)
    swap in by implementing this protocol. Nothing above the mode layer
    changes.
    """

    def reset(self) -> None: ...
    def handle_slot_key(self, slot_idx: int) -> Optional[SelectionResult]: ...
    def current_view(self) -> object: ...  # mode-specific view dataclass


# -----------------------------------------------------------------------------
# GridQuestMode
# -----------------------------------------------------------------------------

class GridQuestMode:
    """Two-step spatial selection on a 3x3 grid.

    Each target is an integer T in [0, num_tiles * num_tiles), decomposed
    via `divmod(T, num_tiles)` into (group_idx, slot_idx). The cue
    (rendered by the renderer as a mini 9x9 reference board with cell T
    highlighted) tells the player exactly which outer-then-inner
    coordinates to navigate to.

    Selection takes exactly two slot-key presses:

        1. First press picks one of 9 outer groups.
        2. The same 9 tiles then represent the 9 inner positions of the
           chosen group; the second press picks one inner position.

    Scoring (one selection = one (key1, key2) pair):
      * Correct iff key1 == target_group AND key2 == target_slot.
      * A wrong key1 ends the trial immediately as incorrect — no point
        letting the player guess a key2 for a target that's no longer
        reachable. (Matches Shenoy et al. (2021)'s per-pair scoring.)

    The mode never advances the target until both keys have been entered
    (or stage-1 has failed).
    """

    def __init__(self, cfg: GameConfig, target_source: TargetSource,
                 time_fn=time.monotonic) -> None:
        self._cfg = cfg
        self._source = target_source
        self._time_fn = time_fn
        self._target: int = 0
        self._stage: GridStage = GridStage.GROUP_SELECT
        self._active_group: Optional[int] = None
        # Last selection feedback for the renderer to flash. Cleared lazily.
        self._last_correct: Optional[bool] = None
        self._last_feedback_at: float = 0.0
        self.reset()

    # --- lifecycle ------------------------------------------------------

    def reset(self) -> None:
        self._target = self._source.next_target()
        self._stage = GridStage.GROUP_SELECT
        self._active_group = None
        self._last_correct = None
        self._last_feedback_at = 0.0

    # --- input ----------------------------------------------------------

    def handle_slot_key(self, slot_idx: int) -> Optional[SelectionResult]:
        """Process a slot keypress. Returns a SelectionResult only when a
        full two-key selection has been resolved (or stage-1 has failed).

        slot_idx must be 0..num_tiles-1; out-of-range raises ValueError so
        the adapter can't silently bug us with mis-mapped keys.
        """
        if not (0 <= slot_idx < self._cfg.num_tiles):
            raise ValueError(f"slot_idx {slot_idx} out of range")

        target_group, target_slot = divmod(self._target, self._cfg.num_tiles)

        if self._stage == GridStage.GROUP_SELECT:
            # First key commits a group. Wrong group = trial fails.
            if slot_idx != target_group:
                result = SelectionResult(
                    correct=False, target=self._target, selected=None,
                )
                self._last_correct = False
                self._last_feedback_at = self._time_fn()
                self._target = self._source.next_target()
                self._stage = GridStage.GROUP_SELECT
                self._active_group = None
                return result

            self._active_group = slot_idx
            self._stage = GridStage.TILE_SELECT
            return None

        # Stage 2: second key resolves the full selection. selected is the
        # full target index that the player's (key1, key2) pair points at.
        assert self._active_group is not None
        selected = self._active_group * self._cfg.num_tiles + slot_idx
        correct = (slot_idx == target_slot)  # group was already correct
        result = SelectionResult(
            correct=correct, target=self._target, selected=selected,
        )

        # Set up the next trial.
        self._last_correct = correct
        self._last_feedback_at = self._time_fn()
        self._target = self._source.next_target()
        self._stage = GridStage.GROUP_SELECT
        self._active_group = None
        return result

    # --- view -----------------------------------------------------------

    def current_view(self) -> GridView:
        target_group, target_slot = divmod(self._target, self._cfg.num_tiles)
        slots: list[GridSlotView] = []
        if self._stage == GridStage.GROUP_SELECT:
            for g in range(self._cfg.num_tiles):
                slots.append(GridSlotView(
                    is_target_group=(g == target_group),
                    is_target_tile=False,
                ))
        else:
            for s in range(self._cfg.num_tiles):
                slots.append(GridSlotView(
                    is_target_group=False,  # not meaningful in stage 2
                    is_target_tile=(s == target_slot),
                ))

        return GridView(
            stage=self._stage,
            target=self._target,
            slots=tuple(slots),
            active_group_idx=self._active_group,
            last_feedback_correct=self._last_correct,
            last_feedback_at=self._last_feedback_at,
        )
