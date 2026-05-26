"""Entry point: wires the components together and runs the loop.

This is the only module that knows about every layer; everything else only
depends on the layer immediately below it. To swap any component (different
mode, different renderer, different input adapter), edit *only* this file.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from .adapters import InputAdapter, InputEvent, InputEventType, PygameKeyboardAdapter
from .config import DEFAULT_CONFIG, GameConfig
from .core import IIDUniformTargetSource, Phase, Session
from .mode import GameMode, HexOSpellMode
from .renderer import PygameHexRenderer, Renderer


def build_pygame_stack(
    cfg: GameConfig, seed: Optional[int] = None
) -> tuple[InputAdapter, GameMode, Renderer, Session]:
    """Construct the pygame variant of the stack.

    Returns the four collaborators. Replacing this function with one that
    builds a different stack (e.g. websocket adapter + browser renderer)
    is the entire 'switch frontends' migration.
    """
    target_source = IIDUniformTargetSource(alphabet=cfg.alphabet, seed=seed)
    mode = HexOSpellMode(cfg=cfg, target_source=target_source)
    session = Session(
        n=cfg.n,
        scored_duration_sec=cfg.scored_duration_sec,
        countdown_sec=cfg.countdown_sec,
    )
    renderer = PygameHexRenderer(cfg=cfg)
    adapter = PygameKeyboardAdapter(cfg=cfg)
    return adapter, mode, renderer, session


def run_loop(
    adapter: InputAdapter,
    mode: GameMode,
    renderer: Renderer,
    session: Session,
) -> None:
    """Main event loop. Stays running until QUIT or window close."""
    renderer.init()
    try:
        running = True
        while running:
            # 1. Drain input
            for ev in adapter.poll():
                running = _handle_event(ev, mode, session)
                if not running:
                    break

            # 2. Advance time-driven session transitions
            session.tick()

            # 3. Render
            renderer.draw(session.state(), mode.current_view())

            # 4. Frame rate cap (pygame-specific; renderer owns the clock)
            if hasattr(renderer, "tick"):
                renderer.tick()
    finally:
        adapter.shutdown()
        renderer.shutdown()

    _print_final_results(session)


def _handle_event(ev: InputEvent, mode: GameMode, session: Session) -> bool:
    """Apply one input event. Returns False if the loop should exit."""
    if ev.type in (InputEventType.QUIT, InputEventType.WINDOW_CLOSE):
        return False

    if ev.type == InputEventType.ADVANCE:
        # Welcome -> familiarization, or Results -> Welcome.
        session.on_advance()
        if session.phase == Phase.FAMILIARIZATION:
            mode.reset()
        return True

    if ev.type == InputEventType.START_SCORED:
        # ENTER from the welcome screen jumps straight into the scored
        # countdown; the welcome screen's controls bar promises this. From
        # familiarization, it ends practice and starts the scored run.
        if session.phase == Phase.WELCOME:
            session.on_advance()       # WELCOME -> FAMILIARIZATION
            session.on_start_scored()  # FAMILIARIZATION -> COUNTDOWN
            mode.reset()
        elif session.phase == Phase.FAMILIARIZATION:
            session.on_start_scored()
            mode.reset()  # clear any partial stage-1 state
        return True

    if ev.type == InputEventType.SLOT:
        # Only the mode logic during active phases.
        if session.is_active_for_input() and ev.slot_idx is not None:
            result = mode.handle_slot_key(ev.slot_idx)
            if result is not None:
                session.on_selection(result.correct)
        return True

    return True


def _print_final_results(session: Session) -> None:
    """Echo final results to stdout for the grader's terminal record."""
    snap = session.state().final_snapshot
    if snap is None:
        print("[no scored run completed]")
        return
    print("=" * 50)
    print("FINAL RESULTS")
    print("=" * 50)
    print(f"  N             = {snap.n}")
    print(f"  S_c (correct) = {snap.correct}")
    print(f"  S_i (errors)  = {snap.incorrect}")
    print(f"  t (seconds)   = {snap.elapsed_sec:.3f}")
    print(f"  Bit rate B    = {snap.bit_rate:.4f} bits/sec")
    print("=" * 50)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hex-o-Spell bit-rate game (Science Corp SWE homework)"
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Optional RNG seed for the target sequence (for reproducible runs).",
    )
    parser.add_argument(
        "--smoke-test", action="store_true",
        help="Initialize the stack, then exit. Used by CI to verify the binary boots.",
    )
    args = parser.parse_args(argv)

    cfg = DEFAULT_CONFIG
    adapter, mode, renderer, session = build_pygame_stack(cfg=cfg, seed=args.seed)

    if args.smoke_test:
        try:
            renderer.init()
        finally:
            renderer.shutdown()
            adapter.shutdown()
        print("smoke test ok")
        return 0

    run_loop(adapter, mode, renderer, session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
