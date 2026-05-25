"""Game-mode abstraction.

A GameMode encapsulates *the selection rules* — how the player turns input
into a selection event. It's the swap point for trying different paradigms
(Hex-o-Spell, direct typing, center-out, etc.) without touching anything else.

The mode is fed normalized input via handle_slot_key(slot_idx). It owns
the current target and the partial-selection state (e.g. "first key pressed,
waiting for second"), and emits a SelectionResult when a selection completes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Protocol, Sequence

from .config import GameConfig
from .core import TargetSource


# -----------------------------------------------------------------------------
# Shared types
# -----------------------------------------------------------------------------

@dataclass
class SelectionResult:
    """Returned by a GameMode when a selection completes."""
    correct: bool
    target: str
    selected: Optional[str]  # what the player actually picked (None if invalid)


# -----------------------------------------------------------------------------
# Hex-o-Spell view model
#
# These dataclasses describe what to draw. The renderer reads them and is
# completely agnostic about *how* the game decides what's in each slot.
# -----------------------------------------------------------------------------

class HexStage(Enum):
    GROUP_SELECT = auto()  # six tiles each show a group of letters
    LETTER_SELECT = auto() # six tiles each show one letter from the chosen group


@dataclass
class HexSlotView:
    """One of the six tiles in the Hex-o-Spell layout."""
    chars: tuple[str, ...]     # 1 char in stage 2, group_size chars in stage 1
    contains_target: bool       # whether the cued target is in this slot's chars
    is_target_letter: bool      # stage-2 only: is THIS slot exactly the target letter


@dataclass
class HexView:
    """Complete renderable view of the Hex-o-Spell mode."""
    stage: HexStage
    target_char: str
    slots: tuple[HexSlotView, ...]
    active_group_idx: Optional[int]  # set in stage 2 to indicate the chosen group
    last_feedback_correct: Optional[bool]  # None / True / False — for flash
    last_feedback_at: float  # monotonic timestamp


# -----------------------------------------------------------------------------
# GameMode protocol
# -----------------------------------------------------------------------------

class GameMode(Protocol):
    """A selection paradigm.

    Implementations:
      - decide what target is being cued,
      - convert raw 'slot key' presses into a complete selection,
      - expose a renderable view of the current state.

    Different modes (Hex-o-Spell, direct keyboard, SSVEP-style, center-out)
    swap in by implementing this protocol. Nothing above the mode layer
    changes.
    """

    def reset(self) -> None: ...
    def handle_slot_key(self, slot_idx: int) -> Optional[SelectionResult]: ...
    def current_view(self) -> object: ...  # mode-specific view dataclass


# -----------------------------------------------------------------------------
# HexOSpellMode
# -----------------------------------------------------------------------------

class HexOSpellMode:
    """Two-step Hex-o-Spell selection.

    Each target is selected via exactly two slot-key presses:

        1. First press picks one of NUM_GROUPS groups.
        2. The group's characters then occupy the same six slots; the second
           press picks one character within the group.

    Scoring (one selection = one (key1, key2) pair):
      * Correct iff key1 selects the group containing the target AND
        key2 selects the target's position within that group.
      * If group has fewer than NUM_GROUPS characters in stage 2 (which can
        happen if group_size < num_groups), pressing an unfilled slot in
        stage 2 counts as incorrect (selected = None).

    The mode never advances target until both keys have been entered.
    """

    def __init__(self, cfg: GameConfig, target_source: TargetSource,
                 time_fn=time.monotonic) -> None:
        self._cfg = cfg
        self._source = target_source
        self._time_fn = time_fn
        self._target: str = ""
        self._stage: HexStage = HexStage.GROUP_SELECT
        self._active_group: Optional[int] = None
        # Last selection feedback for the renderer to flash. Cleared lazily.
        self._last_correct: Optional[bool] = None
        self._last_feedback_at: float = 0.0
        self.reset()

    # --- lifecycle ------------------------------------------------------

    def reset(self) -> None:
        self._target = self._source.next_target()
        self._stage = HexStage.GROUP_SELECT
        self._active_group = None
        self._last_correct = None
        self._last_feedback_at = 0.0

    # --- input ----------------------------------------------------------

    def handle_slot_key(self, slot_idx: int) -> Optional[SelectionResult]:
        """Process a slot keypress. Returns a SelectionResult only when a
        full two-key selection has been resolved.

        slot_idx must be 0..num_groups-1; out-of-range raises ValueError so
        the adapter can't silently bug us with mis-mapped keys.
        """
        if not (0 <= slot_idx < self._cfg.num_groups):
            raise ValueError(f"slot_idx {slot_idx} out of range")

        if self._stage == HexStage.GROUP_SELECT:
            # First key commits a group. If the player picked a group that
            # doesn't contain the target, the trial fails immediately — no
            # point letting them guess a second key for a target that can no
            # longer be reached. This matches Shenoy et al.'s scoring of one
            # selection per (key1, key2) pair: a wrong key1 is one wrong pair.
            group_chars = self._cfg.chars_in_group(slot_idx)
            if self._target not in group_chars:
                result = SelectionResult(
                    correct=False, target=self._target, selected=None,
                )
                self._last_correct = False
                self._last_feedback_at = self._time_fn()
                self._target = self._source.next_target()
                self._stage = HexStage.GROUP_SELECT
                self._active_group = None
                return result

            self._active_group = slot_idx
            self._stage = HexStage.LETTER_SELECT
            return None

        # Stage 2: second key resolves the full selection.
        assert self._active_group is not None
        group_chars = self._cfg.chars_in_group(self._active_group)

        selected: Optional[str]
        if slot_idx < len(group_chars):
            selected = group_chars[slot_idx]
        else:
            # Player pressed a slot that has no letter (only relevant if
            # group_size < num_groups). Counts as a wrong selection.
            selected = None

        correct = (selected == self._target)
        result = SelectionResult(correct=correct, target=self._target, selected=selected)

        # Set up the next trial.
        self._last_correct = correct
        self._last_feedback_at = self._time_fn()
        self._target = self._source.next_target()
        self._stage = HexStage.GROUP_SELECT
        self._active_group = None
        return result

    # --- view -----------------------------------------------------------

    def current_view(self) -> HexView:
        slots: list[HexSlotView] = []
        if self._stage == HexStage.GROUP_SELECT:
            for g in range(self._cfg.num_groups):
                chars = tuple(self._cfg.chars_in_group(g))
                slots.append(HexSlotView(
                    chars=chars,
                    contains_target=(self._target in chars),
                    is_target_letter=False,
                ))
        else:
            assert self._active_group is not None
            group_chars = self._cfg.chars_in_group(self._active_group)
            for slot_idx in range(self._cfg.num_groups):
                if slot_idx < len(group_chars):
                    c = group_chars[slot_idx]
                    slots.append(HexSlotView(
                        chars=(c,),
                        contains_target=False,  # not meaningful in stage 2
                        is_target_letter=(c == self._target),
                    ))
                else:
                    slots.append(HexSlotView(
                        chars=(),
                        contains_target=False,
                        is_target_letter=False,
                    ))

        return HexView(
            stage=self._stage,
            target_char=self._target,
            slots=tuple(slots),
            active_group_idx=self._active_group,
            last_feedback_correct=self._last_correct,
            last_feedback_at=self._last_feedback_at,
        )
