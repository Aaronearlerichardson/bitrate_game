"""Pygame renderer for the Hex-o-Spell mode.

The Renderer protocol below describes the contract: given a SessionState and
a mode-specific view, draw it. Implementations own their backend's lifecycle
(window, fonts, etc.).

Swap points:
  * To switch from pygame to another desktop framework, write a new class
    matching the Renderer protocol and inject it in main.py.
  * To switch to a browser frontend, you'd replace the renderer + adapter
    pair entirely with a websocket bridge. The core/mode logic stays.
"""

from __future__ import annotations

import time
from typing import Optional, Protocol

from . import config
from .config import GameConfig
from .core import Phase, SessionState
from .mode import HexStage, HexView


# -----------------------------------------------------------------------------
# Renderer protocol
# -----------------------------------------------------------------------------

class Renderer(Protocol):
    def init(self) -> None: ...
    def draw(self, session_state: SessionState, mode_view: object) -> None: ...
    def shutdown(self) -> None: ...


# -----------------------------------------------------------------------------
# Pygame Hex renderer
# -----------------------------------------------------------------------------

class PygameHexRenderer:
    """Renders Hex-o-Spell + session HUD with pygame.

    Layout:

        +-----------------------------------------------+
        |  [slot 0]      [slot 1]      [slot 2]         |
        |                                               |
        |               [ central HUD ]                 |
        |                                               |
        |  [slot 3]      [slot 4]      [slot 5]         |
        |                                               |
        |  bottom bar: phase-specific instructions      |
        +-----------------------------------------------+
    """

    def __init__(self, cfg: GameConfig) -> None:
        import pygame  # local import: see adapters.py for rationale
        self._pygame = pygame
        self._cfg = cfg
        self._screen = None
        self._font_huge = None
        self._font_large = None
        self._font_medium = None
        self._font_small = None
        self._clock = None

    # --- lifecycle ------------------------------------------------------

    def init(self) -> None:
        pg = self._pygame
        pg.init()
        pg.display.set_caption("Bitrate Game — Hex-o-Spell")
        self._screen = pg.display.set_mode((config.WINDOW_W, config.WINDOW_H))
        # Use the default system font; pygame.font.SysFont(None, ...) picks a
        # reasonable system font on all platforms without bundling a TTF.
        self._font_huge = pg.font.SysFont(None, 160)
        self._font_large = pg.font.SysFont(None, 72)
        self._font_medium = pg.font.SysFont(None, 40)
        self._font_small = pg.font.SysFont(None, 26)
        self._clock = pg.time.Clock()

    def shutdown(self) -> None:
        self._pygame.quit()

    def tick(self) -> None:
        """Cap the frame rate. Separate from draw() so the loop owns timing."""
        if self._clock is not None:
            self._clock.tick(config.FPS)

    # --- drawing --------------------------------------------------------

    def draw(self, session_state: SessionState, mode_view: object) -> None:
        assert self._screen is not None, "init() must be called first"
        self._screen.fill(config.BG_COLOR)

        phase = session_state.phase
        if phase == Phase.WELCOME:
            self._draw_welcome()
        elif phase == Phase.RESULTS:
            self._draw_results(session_state)
        else:
            # FAMILIARIZATION, COUNTDOWN, SCORED: always show the hex board.
            assert isinstance(mode_view, HexView), \
                f"renderer expected HexView, got {type(mode_view).__name__}"
            self._draw_hex_board(session_state, mode_view)

        self._pygame.display.flip()

    # --- screen helpers -------------------------------------------------

    def _draw_welcome(self) -> None:
        pg = self._pygame
        s = self._screen
        cx = config.WINDOW_W // 2

        title = self._font_large.render("Hex-o-Spell Bit-Rate Game",
                                        True, config.TEXT_COLOR)
        s.blit(title, title.get_rect(center=(cx, 140)))

        lines = [
            f"Alphabet: {self._cfg.n} characters in {self._cfg.num_groups} groups "
            f"of {self._cfg.group_size}",
            "",
            "Each target requires two key presses:",
            "  1) press the slot key containing the target letter",
            "  2) press the slot key for the letter itself",
            "",
            "Slot keys are spatially mapped:",
            "      Q   W   E      <-  top row",
            "      A   S   D      <-  bottom row",
            "",
            "SPACE  start familiarization (unlimited practice)",
            "ENTER  begin the 60-second scored run",
            "ESC    quit",
        ]
        for i, line in enumerate(lines):
            color = config.MUTED_TEXT_COLOR if line.startswith("ESC") else config.TEXT_COLOR
            surf = self._font_medium.render(line, True, color)
            s.blit(surf, surf.get_rect(center=(cx, 240 + i * 38)))

    def _draw_results(self, st: SessionState) -> None:
        s = self._screen
        cx = config.WINDOW_W // 2
        snap = st.final_snapshot
        if snap is None:
            return

        title = self._font_large.render("Run complete", True, config.TEXT_COLOR)
        s.blit(title, title.get_rect(center=(cx, 140)))

        # Headline bit rate
        bps_str = f"{snap.bit_rate:.2f} bits / sec"
        big = self._font_huge.render(bps_str, True, config.TARGET_HIGHLIGHT_COLOR)
        s.blit(big, big.get_rect(center=(cx, 320)))

        breakdown = [
            f"N (alphabet size) = {snap.n}",
            f"S_c (correct selections) = {snap.correct}",
            f"S_i (incorrect selections) = {snap.incorrect}",
            f"t (elapsed seconds) = {snap.elapsed_sec:.2f}",
            f"B = log2(N-1) * max(S_c - S_i, 0) / t",
        ]
        for i, line in enumerate(breakdown):
            surf = self._font_medium.render(line, True, config.TEXT_COLOR)
            s.blit(surf, surf.get_rect(center=(cx, 460 + i * 42)))

        hint = self._font_small.render(
            "SPACE  return to welcome screen     ESC  quit",
            True, config.MUTED_TEXT_COLOR)
        s.blit(hint, hint.get_rect(center=(cx, config.WINDOW_H - 60)))

    def _draw_hex_board(self, st: SessionState, view: HexView) -> None:
        self._draw_slots(view)
        self._draw_hud(st, view)
        self._draw_bottom_bar(st)
        if st.phase == Phase.COUNTDOWN:
            self._draw_countdown_overlay(st)

    # --- pieces ---------------------------------------------------------

    def _slot_rects(self):
        """Compute the 6 slot rectangles. 3 columns x 2 rows."""
        pg = self._pygame
        margin_x = 80
        margin_y = 100
        gutter = 30
        cols, rows = 3, 2
        w = (config.WINDOW_W - 2 * margin_x - (cols - 1) * gutter) // cols
        h = (config.WINDOW_H - 2 * margin_y - (rows - 1) * gutter) // rows
        rects: list = []
        for r in range(rows):
            for c in range(cols):
                x = margin_x + c * (w + gutter)
                y = margin_y + r * (h + gutter)
                rects.append(pg.Rect(x, y, w, h))
        return rects

    def _draw_slots(self, view: HexView) -> None:
        pg = self._pygame
        s = self._screen
        rects = self._slot_rects()
        now = time.monotonic()
        flash_active = (
            view.last_feedback_correct is not None
            and (now - view.last_feedback_at) < config.FEEDBACK_FLASH_SEC
        )

        for idx, rect in enumerate(rects):
            slot = view.slots[idx]
            base = config.TILE_COLOR
            border = config.TILE_BORDER_COLOR

            if view.stage == HexStage.LETTER_SELECT:
                if view.active_group_idx == idx:
                    # The slot the player pressed in stage 1 doesn't get
                    # special treatment in our layout because the group's
                    # letters are spread across ALL slots. We instead tint
                    # all stage-2 tiles slightly.
                    pass
                base = config.TILE_COLOR
                border = config.TILE_ACTIVE_COLOR

            if flash_active:
                base = (
                    config.CORRECT_FLASH_COLOR
                    if view.last_feedback_correct
                    else config.INCORRECT_FLASH_COLOR
                )

            pg.draw.rect(s, base, rect, border_radius=18)
            pg.draw.rect(s, border, rect, width=3, border_radius=18)

            # Draw the slot's characters.
            if not slot.chars:
                # Stage-2 empty slot (rare; only if group_size < num_groups).
                continue
            if len(slot.chars) == 1:
                self._draw_single_char(rect, slot.chars[0], slot.is_target_letter)
            else:
                self._draw_group_chars(rect, slot.chars, view.target_char,
                                       slot.contains_target,
                                       view.stage == HexStage.GROUP_SELECT)

    def _draw_single_char(self, rect, ch: str, is_target: bool) -> None:
        color = config.TARGET_HIGHLIGHT_COLOR if is_target else config.TEXT_COLOR
        surf = self._font_huge.render(ch, True, color)
        self._screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_group_chars(self, rect, chars, target_char, contains_target,
                           highlight_target) -> None:
        """Render group_size characters in a row inside the rect."""
        pg = self._pygame
        s = self._screen
        n = len(chars)
        cell_w = rect.width / n
        for i, ch in enumerate(chars):
            cx = rect.x + cell_w * (i + 0.5)
            cy = rect.y + rect.height // 2
            color = config.TEXT_COLOR
            if highlight_target and ch == target_char:
                color = config.TARGET_HIGHLIGHT_COLOR
            surf = self._font_large.render(ch, True, color)
            s.blit(surf, surf.get_rect(center=(int(cx), int(cy))))

    def _draw_hud(self, st: SessionState, view: HexView) -> None:
        """Central HUD overlay between the two rows: target + live stats."""
        pg = self._pygame
        s = self._screen
        cx = config.WINDOW_W // 2
        cy = config.WINDOW_H // 2

        # Target prompt
        prompt = self._font_small.render("TARGET", True, config.MUTED_TEXT_COLOR)
        s.blit(prompt, prompt.get_rect(center=(cx, cy - 24)))
        tgt = self._font_large.render(view.target_char.upper(),
                                       True, config.TARGET_HIGHLIGHT_COLOR)
        s.blit(tgt, tgt.get_rect(center=(cx, cy + 18)))

        # Live bit-rate readouts on left/right of the HUD column
        snap = st.tracker_snapshot
        if snap is not None and st.phase in (Phase.SCORED, Phase.COUNTDOWN):
            bps_text = f"{snap.bit_rate:.2f} bps"
            left = self._font_medium.render(bps_text, True, config.HUD_COLOR)
            s.blit(left, left.get_rect(midright=(cx - 200, cy)))

            score_text = f"S_c {snap.correct}   S_i {snap.incorrect}"
            right = self._font_medium.render(score_text, True, config.HUD_COLOR)
            s.blit(right, right.get_rect(midleft=(cx + 200, cy)))

        # Top-right: countdown timer during SCORED
        if st.phase == Phase.SCORED:
            t = f"{st.scored_remaining:4.1f}s"
            timer = self._font_medium.render(t, True, config.HUD_COLOR)
            s.blit(timer, timer.get_rect(topright=(config.WINDOW_W - 30, 20)))

    def _draw_bottom_bar(self, st: SessionState) -> None:
        s = self._screen
        cx = config.WINDOW_W // 2
        y = config.WINDOW_H - 36

        if st.phase == Phase.FAMILIARIZATION:
            msg = "FAMILIARIZATION — practice as long as you like.  ENTER to start scored run.  ESC to quit."
        elif st.phase == Phase.COUNTDOWN:
            msg = "Get ready..."
        elif st.phase == Phase.SCORED:
            msg = "SCORED RUN — type as fast and accurately as you can."
        else:
            msg = ""

        if msg:
            surf = self._font_small.render(msg, True, config.MUTED_TEXT_COLOR)
            s.blit(surf, surf.get_rect(center=(cx, y)))

    def _draw_countdown_overlay(self, st: SessionState) -> None:
        s = self._screen
        cx = config.WINDOW_W // 2
        cy = config.WINDOW_H // 2
        # Use ceiling so 0.01s remaining still shows "1".
        n = int(st.countdown_remaining) + (1 if st.countdown_remaining > 0 else 0)
        n = max(n, 1)
        # Big number in a translucent dark backing
        overlay = self._pygame.Surface((360, 360), self._pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        s.blit(overlay, overlay.get_rect(center=(cx, cy)))
        big = self._font_huge.render(str(n), True, config.TARGET_HIGHLIGHT_COLOR)
        s.blit(big, big.get_rect(center=(cx, cy)))
