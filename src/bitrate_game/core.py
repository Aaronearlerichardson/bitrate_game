"""Framework-agnostic game core.

This module deliberately has zero dependency on pygame or any UI framework.
Everything here is plain Python so it can be:
  * unit-tested in isolation,
  * reused if we swap to a browser frontend (port the algorithms, not the code),
  * driven by a non-keyboard input modality without changing anything.

Contains:
  - TargetSource: i.i.d. uniform random target generator
  - BitRateTracker: Sc / Si / t bookkeeping and B = log2(N-1) * max(Sc-Si, 0) / t
  - Session: state machine for welcome -> familiarize -> countdown -> scored -> results
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Protocol, Sequence


# -----------------------------------------------------------------------------
# Target generation
# -----------------------------------------------------------------------------

class TargetSource(Protocol):
    """Source of cued targets. Must produce an i.i.d. sequence.

    The Protocol form lets us swap in test doubles or alternative samplers
    (e.g. for replay determinism) without inheriting from a base class.

    Targets are integers in [0, N) where N is the size of the alphabet.
    The mode decides what each integer *means* (e.g. for GridQuest,
    `divmod(target, num_tiles)` gives (group_idx, slot_idx)).
    """

    @property
    def alphabet(self) -> Sequence[int]: ...

    def next_target(self) -> int: ...


class IIDUniformTargetSource:
    """Uniform-random target sampler with replacement.

    Each call to next_target() returns an independent sample from the alphabet.
    No state, no patterns, no language model. Seeded for reproducibility if
    desired (e.g. for grader-comparable runs).
    """

    def __init__(self, alphabet: Sequence[int], seed: Optional[int] = None) -> None:
        items = tuple(alphabet)
        if len(items) < 3:
            raise ValueError(f"alphabet must have >= 3 entries, got {len(items)}")
        self._alphabet: tuple[int, ...] = items
        self._rng = random.Random(seed)

    @property
    def alphabet(self) -> tuple[int, ...]:
        return self._alphabet

    def next_target(self) -> int:
        # Critically: we do NOT condition on the previous target. Repeats
        # are allowed and expected. This is what makes the sequence i.i.d.
        return self._rng.choice(self._alphabet)


# -----------------------------------------------------------------------------
# Bit-rate tracking
# -----------------------------------------------------------------------------

@dataclass
class BitRateSnapshot:
    """Immutable snapshot of the tracker state at a moment in time."""
    n: int
    correct: int
    incorrect: int
    elapsed_sec: float
    bit_rate: float


class BitRateTracker:
    """Implements the Shenoy et al. (2021) achieved bit rate formula.

        B = log2(N - 1) * max(Sc - Si, 0) / t

    The tracker maintains a logical clock that can be paused/resumed (so
    familiarization time doesn't pollute the scored window) and uses a
    monotonic time source so wall-clock changes don't affect it.
    """

    def __init__(self, n: int, time_fn=time.monotonic) -> None:
        if n < 3:
            raise ValueError(f"N must be >= 3, got {n}")
        self._n = n
        self._time_fn = time_fn
        self._correct = 0
        self._incorrect = 0
        self._accumulated_sec = 0.0
        self._running_since: Optional[float] = None

    # --- control --------------------------------------------------------

    def start(self) -> None:
        """Begin (or resume) accumulating time."""
        if self._running_since is None:
            self._running_since = self._time_fn()

    def pause(self) -> None:
        """Stop accumulating time without resetting counts."""
        if self._running_since is not None:
            self._accumulated_sec += self._time_fn() - self._running_since
            self._running_since = None

    def reset(self) -> None:
        """Zero everything. Used between familiarization and scored runs."""
        self._correct = 0
        self._incorrect = 0
        self._accumulated_sec = 0.0
        self._running_since = None

    # --- recording ------------------------------------------------------

    def record_correct(self) -> None:
        self._correct += 1

    def record_incorrect(self) -> None:
        self._incorrect += 1

    # --- queries --------------------------------------------------------

    @property
    def correct(self) -> int:
        return self._correct

    @property
    def incorrect(self) -> int:
        return self._incorrect

    @property
    def n(self) -> int:
        return self._n

    def elapsed_sec(self) -> float:
        live = 0.0 if self._running_since is None else (self._time_fn() - self._running_since)
        return self._accumulated_sec + live

    def bit_rate(self) -> float:
        """Achieved bit rate in bits/sec. Returns 0 if no time has elapsed."""
        t = self.elapsed_sec()
        if t <= 0.0:
            return 0.0
        net = max(self._correct - self._incorrect, 0)
        return math.log2(self._n - 1) * net / t

    def snapshot(self) -> BitRateSnapshot:
        return BitRateSnapshot(
            n=self._n,
            correct=self._correct,
            incorrect=self._incorrect,
            elapsed_sec=self.elapsed_sec(),
            bit_rate=self.bit_rate(),
        )


# -----------------------------------------------------------------------------
# Session state machine
# -----------------------------------------------------------------------------

class Phase(Enum):
    """Top-level session phases. The GameMode runs *within* SCORED (and
    FAMILIARIZATION); the Session manages transitions between phases."""
    WELCOME = auto()
    FAMILIARIZATION = auto()
    COUNTDOWN = auto()
    SCORED = auto()
    RESULTS = auto()


@dataclass
class SessionState:
    """Snapshot of the session for the renderer to consume.

    Keep this a plain dataclass so the renderer doesn't need to know about
    the Session class at all — it just receives a state object.
    """
    phase: Phase
    countdown_remaining: float = 0.0
    scored_remaining: float = 0.0
    tracker_snapshot: Optional[BitRateSnapshot] = None
    final_snapshot: Optional[BitRateSnapshot] = None  # populated on RESULTS


class Session:
    """Owns the BitRateTracker and drives phase transitions based on elapsed
    time and external 'advance' signals.

    The Session does NOT know about input devices or rendering. It exposes:
      - tick(): advance time-driven transitions (e.g. countdown -> scored)
      - on_advance(): user pressed the 'advance' key (welcome -> familiarize, etc.)
      - on_selection(correct): record a selection during familiarize/scored
      - state(): produce a renderable snapshot
    """

    def __init__(
        self,
        n: int,
        scored_duration_sec: float,
        countdown_sec: float,
        time_fn=time.monotonic,
    ) -> None:
        self._tracker = BitRateTracker(n=n, time_fn=time_fn)
        self._scored_duration = scored_duration_sec
        self._countdown_sec = countdown_sec
        self._time_fn = time_fn
        self._phase: Phase = Phase.WELCOME
        self._phase_start: float = time_fn()
        self._final_snapshot: Optional[BitRateSnapshot] = None

    # --- phase helpers --------------------------------------------------

    def _enter(self, phase: Phase) -> None:
        self._phase = phase
        self._phase_start = self._time_fn()

    def _phase_elapsed(self) -> float:
        return self._time_fn() - self._phase_start

    # --- public API -----------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def tracker(self) -> BitRateTracker:
        return self._tracker

    def on_advance(self) -> None:
        """User pressed the 'advance' key (SPACE). Context-sensitive:

          WELCOME          -> FAMILIARIZATION  (start practice)
          FAMILIARIZATION  -> WELCOME          (back to menu)
          COUNTDOWN        -> WELCOME          (abort before the run starts)
          SCORED           -> WELCOME          (abort mid-run; stats discarded)
          RESULTS          -> WELCOME          (start over)
        """
        if self._phase == Phase.WELCOME:
            self._tracker.reset()
            self._tracker.start()
            self._enter(Phase.FAMILIARIZATION)
        else:
            # Any non-welcome phase = back to welcome. Pause the tracker
            # first so an aborted SCORED run doesn't keep accumulating
            # time, then reset everything for a fresh start.
            self._tracker.pause()
            self._tracker.reset()
            self._final_snapshot = None
            self._enter(Phase.WELCOME)

    def on_start_scored(self) -> None:
        """User pressed the 'start scored run' key during familiarization."""
        if self._phase == Phase.FAMILIARIZATION:
            self._tracker.reset()
            self._enter(Phase.COUNTDOWN)

    def on_selection(self, correct: bool) -> None:
        """Record a completed selection during a play phase.

        Counts are tracked in both FAMILIARIZATION and SCORED so the live
        bit-rate readout works in practice too. The tracker is reset on
        entry to COUNTDOWN, so practice stats never bleed into the scored run.
        """
        if self._phase in (Phase.FAMILIARIZATION, Phase.SCORED):
            if correct:
                self._tracker.record_correct()
            else:
                self._tracker.record_incorrect()

    def tick(self) -> None:
        """Drive time-based phase transitions. Call once per frame."""
        if self._phase == Phase.COUNTDOWN:
            if self._phase_elapsed() >= self._countdown_sec:
                self._enter(Phase.SCORED)
                self._tracker.start()
        elif self._phase == Phase.SCORED:
            if self._phase_elapsed() >= self._scored_duration:
                self._tracker.pause()
                self._final_snapshot = self._tracker.snapshot()
                self._enter(Phase.RESULTS)

    def state(self) -> SessionState:
        countdown_remaining = 0.0
        scored_remaining = 0.0
        if self._phase == Phase.COUNTDOWN:
            countdown_remaining = max(0.0, self._countdown_sec - self._phase_elapsed())
        elif self._phase == Phase.SCORED:
            scored_remaining = max(0.0, self._scored_duration - self._phase_elapsed())
        return SessionState(
            phase=self._phase,
            countdown_remaining=countdown_remaining,
            scored_remaining=scored_remaining,
            tracker_snapshot=self._tracker.snapshot(),
            final_snapshot=self._final_snapshot,
        )

    def is_active_for_input(self) -> bool:
        """Whether the GameMode should accept selection input right now."""
        return self._phase in (Phase.FAMILIARIZATION, Phase.SCORED)
