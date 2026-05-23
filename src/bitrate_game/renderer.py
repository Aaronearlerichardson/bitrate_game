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
from .mode import HexSlotView, HexStage, HexView


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
        |  [slot Q]      [slot W]      [slot E]         |
        |                                               |
        |               [ central HUD ]                 |
        |                                               |
        |  [slot A]      [slot S]      [slot D]         |
        |                                               |
        |  bottom bar: phase-specific instructions      |
        +-----------------------------------------------+
    """

    def __init__(self, cfg: GameConfig) -> None:
        import pygame
        self._pygame = pygame
        self._cfg = cfg
        self._screen = None
        self._font_huge = None
        self._font_large = None
        self._font_medium = None
        self._font_small = None
        self._font_tiny = None
        self._font_preview_big = None
        self._font_preview_small = None
        self._clock = None

    # --- lifecycle ------------------------------------------------------

    def init(self) -> None:
        pg = self._pygame
        pg.init()
        pg.display.set_caption("Bitrate Game — Hex-o-Spell")
        self._screen = pg.display.set_mode((config.WINDOW_W, config.WINDOW_H))
        # SysFont(None, ...) picks a reasonable system font on every platform
        # without bundling a TTF.
        self._font_huge = pg.font.SysFont(None, 160)
        self._font_large = pg.font.SysFont(None, 72)
        self._font_medium = pg.font.SysFont(None, 40)
        self._font_small = pg.font.SysFont(None, 26)
        self._font_tiny = pg.font.SysFont(None, 22)
        # Smaller font sizes for the welcome-screen preview board.
        self._font_preview_big = pg.font.SysFont(None, 56)
        self._font_preview_small = pg.font.SysFont(None, 30)
        self._clock = pg.time.Clock()

    def shutdown(self) -> None:
        self._pygame.quit()

    def tick(self) -> None:
        if self._clock is not None:
            self._clock.tick(config.FPS)

    # --- top-level draw -------------------------------------------------

    def draw(self, session_state: SessionState, mode_view: object) -> None:
        assert self._screen is not None, "init() must be called first"
        self._screen.fill(config.BG_COLOR)

        phase = session_state.phase
        if phase == Phase.WELCOME:
            self._draw_welcome()
        elif phase == Phase.RESULTS:
            self._draw_results(session_state)
        else:
            assert isinstance(mode_view, HexView), \
                f"renderer expected HexView, got {type(mode_view).__name__}"
            self._draw_hex_board(session_state, mode_view)

        self._pygame.display.flip()

    # ====================================================================
    # Welcome screen
    # ====================================================================

    def _draw_welcome(self) -> None:
        """Title + preview board with a worked example + controls.

        The preview board is rendered with the *same* slot-drawing code as
        gameplay, just at a smaller scale and with hand-constructed slots
        for the example. This guarantees the player sees exactly what they'll
        see in the real game.
        """
        s = self._screen
        cx = config.WINDOW_W // 2

        # Title
        title = self._font_large.render("Hex-o-Spell Bit-Rate Game",
                                        True, config.TEXT_COLOR)
        s.blit(title, title.get_rect(center=(cx, 70)))

        subtitle = self._font_small.render(
            f"Type one letter at a time using two key presses.   "
            f"Alphabet: {self._cfg.n} characters in {self._cfg.num_groups} groups of {self._cfg.group_size}.",
            True, config.MUTED_TEXT_COLOR)
        s.blit(subtitle, subtitle.get_rect(center=(cx, 110)))

        # Preview board (scaled-down stage-1 view with example target)
        example_target = "e" if "e" in self._cfg.alphabet else self._cfg.alphabet[0]
        example_view = self._make_example_view(example_target)

        board_rect = self._pygame.Rect(0, 0, 760, 360)
        board_rect.center = (cx, 320)
        rects = self._slot_rects(board_rect, gutter=14, margin=0)
        self._draw_slots_in(
            example_view, rects,
            big_font=self._font_preview_big,
            small_font=self._font_preview_small,
            flash_active=False,
        )

        # Mini HUD overlay on the preview to label it
        prompt = self._font_small.render("EXAMPLE TARGET", True, config.MUTED_TEXT_COLOR)
        s.blit(prompt, prompt.get_rect(center=(cx, board_rect.centery - 18)))
        tgt = self._font_large.render(example_target.upper(),
                                       True, config.TARGET_HIGHLIGHT_COLOR)
        s.blit(tgt, tgt.get_rect(center=(cx, board_rect.centery + 22)))

        # Step-by-step instructions
        steps = [
            f"STEP 1   Find the YELLOW target letter ('{example_target}'). It lives inside one tile.",
            f"         Press the key labeled on that tile — its corner shows Q/W/E/A/S/D.",
            "STEP 2   The chosen tile's letters then spread across all six tiles, one per tile.",
            "         Press the key for the tile where your target letter has moved.",
        ]
        y = board_rect.bottom + 30
        for line in steps:
            surf = self._font_small.render(line, True, config.TEXT_COLOR)
            s.blit(surf, surf.get_rect(midleft=(cx - 380, y)))
            y += 30

        # Controls bar at the bottom
        controls = "SPACE  practice (unlimited)      ENTER  start 60-second scored run      ESC  quit"
        ctrl = self._font_small.render(controls, True, config.HUD_COLOR)
        s.blit(ctrl, ctrl.get_rect(center=(cx, config.WINDOW_H - 40)))

    def _make_example_view(self, target: str) -> HexView:
        """Build a fake stage-1 HexView showing the layout with `target`
        highlighted. Used only on the welcome screen as a visual primer."""
        slots: list[HexSlotView] = []
        for g in range(self._cfg.num_groups):
            chars = tuple(self._cfg.chars_in_group(g))
            slots.append(HexSlotView(
                chars=chars,
                contains_target=(target in chars),
                is_target_letter=False,
            ))
        return HexView(
            stage=HexStage.GROUP_SELECT,
            target_char=target,
            slots=tuple(slots),
            active_group_idx=None,
            last_feedback_correct=None,
            last_feedback_at=0.0,
        )

    # ====================================================================
    # Results screen
    # ====================================================================

    def _draw_results(self, st: SessionState) -> None:
        s = self._screen
        cx = config.WINDOW_W // 2
        snap = st.final_snapshot
        if snap is None:
            return

        title = self._font_large.render("Run complete", True, config.TEXT_COLOR)
        s.blit(title, title.get_rect(center=(cx, 140)))

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

    # ====================================================================
    # Gameplay board
    # ====================================================================

    def _draw_hex_board(self, st: SessionState, view: HexView) -> None:
        # Full-window board with default margins.
        rects = self._slot_rects(board_rect=None)
        flash_active = self._flash_is_active(view)
        self._draw_slots_in(view, rects,
                            big_font=self._font_huge,
                            small_font=self._font_large,
                            flash_active=flash_active)
        self._draw_hud(st, view)
        self._draw_bottom_bar(st, view)
        if st.phase == Phase.COUNTDOWN:
            self._draw_countdown_overlay(st)

    def _flash_is_active(self, view: HexView) -> bool:
        if view.last_feedback_correct is None:
            return False
        return (time.monotonic() - view.last_feedback_at) < config.FEEDBACK_FLASH_SEC

    # --- slot rectangles ------------------------------------------------

    def _slot_rects(self, board_rect=None, gutter: int = 30, margin: int = 80):
        """Return 6 slot rects laid out in a 3x2 grid.

        If `board_rect` is None, fill the window minus default margins.
        Otherwise lay out within the given rect.
        """
        pg = self._pygame
        if board_rect is None:
            margin_x = margin
            margin_y = 100
            x0, y0 = margin_x, margin_y
            board_w = config.WINDOW_W - 2 * margin_x
            board_h = config.WINDOW_H - 2 * margin_y
        else:
            x0, y0 = board_rect.x, board_rect.y
            board_w = board_rect.width
            board_h = board_rect.height

        cols, rows = 3, 2
        w = (board_w - (cols - 1) * gutter) // cols
        h = (board_h - (rows - 1) * gutter) // rows
        rects: list = []
        for r in range(rows):
            for c in range(cols):
                x = x0 + c * (w + gutter)
                y = y0 + r * (h + gutter)
                rects.append(pg.Rect(x, y, w, h))
        return rects

    # --- slot drawing ---------------------------------------------------

    def _draw_slots_in(self, view: HexView, rects, *, big_font, small_font,
                       flash_active: bool) -> None:
        """Render each of the 6 tiles into the supplied rectangles.

        Visual rules:
          * Every tile shows its key letter (Q/W/E/A/S/D) in the corner so
            the keyboard mapping is always visible.
          * In stage 1: the slot containing the target letter gets a
            highlighted border + tinted background. Its target letter is
            colored yellow.
          * In stage 2: every tile shows a single big letter; the one that
            equals the target is colored yellow.
          * On a recent selection: every tile flashes green (correct) or red
            (incorrect) briefly.
        """
        pg = self._pygame
        s = self._screen
        for idx, rect in enumerate(rects):
            slot = view.slots[idx]

            base = config.TILE_COLOR
            border = config.TILE_BORDER_COLOR
            border_w = 3

            # Stage-1 target-home highlight: very visible cue for new players.
            if view.stage == HexStage.GROUP_SELECT and slot.contains_target:
                # Subtle tint + bold yellow border.
                base = (44, 50, 64)
                border = config.TARGET_HIGHLIGHT_COLOR
                border_w = 5
            # Stage-2 tinted border so it's obvious we're in stage 2.
            elif view.stage == HexStage.LETTER_SELECT:
                border = config.TILE_ACTIVE_COLOR

            if flash_active:
                base = (
                    config.CORRECT_FLASH_COLOR
                    if view.last_feedback_correct
                    else config.INCORRECT_FLASH_COLOR
                )

            pg.draw.rect(s, base, rect, border_radius=18)
            pg.draw.rect(s, border, rect, width=border_w, border_radius=18)

            # Always-on key label in the tile's top-left corner.
            self._draw_key_label(rect, self._cfg.slot_keys[idx])

            # Tile contents.
            if not slot.chars:
                continue
            if len(slot.chars) == 1:
                self._draw_single_char(rect, slot.chars[0],
                                       slot.is_target_letter, big_font)
            else:
                self._draw_group_chars(
                    rect, slot.chars, view.target_char,
                    highlight_target=(view.stage == HexStage.GROUP_SELECT),
                    font=small_font,
                )

    def _draw_key_label(self, rect, key_char: str) -> None:
        """Small key letter in the top-left of a tile (e.g. 'Q')."""
        font = self._font_tiny
        # Background pill for legibility against the tile color.
        text = font.render(key_char.upper(), True, config.HUD_COLOR)
        pad_x, pad_y = 10, 6
        bg = self._pygame.Rect(
            rect.x + 10, rect.y + 8,
            text.get_width() + 2 * pad_x, text.get_height() + 2 * pad_y,
        )
        self._pygame.draw.rect(self._screen, config.BG_COLOR, bg, border_radius=6)
        self._pygame.draw.rect(self._screen, config.TILE_BORDER_COLOR, bg,
                                width=1, border_radius=6)
        self._screen.blit(text, (bg.x + pad_x, bg.y + pad_y))

    def _draw_single_char(self, rect, ch: str, is_target: bool, font) -> None:
        color = config.TARGET_HIGHLIGHT_COLOR if is_target else config.TEXT_COLOR
        surf = font.render(ch, True, color)
        self._screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_group_chars(self, rect, chars, target_char, *,
                           highlight_target: bool, font) -> None:
        """Render the group's chars in a horizontal row centered in the tile."""
        s = self._screen
        n = len(chars)
        cell_w = rect.width / n
        for i, ch in enumerate(chars):
            cx = rect.x + cell_w * (i + 0.5)
            cy = rect.y + rect.height // 2 + 8  # nudge below the key label
            color = config.TEXT_COLOR
            if highlight_target and ch == target_char:
                color = config.TARGET_HIGHLIGHT_COLOR
            surf = font.render(ch, True, color)
            s.blit(surf, surf.get_rect(center=(int(cx), int(cy))))

    # --- HUD ------------------------------------------------------------

    def _draw_hud(self, st: SessionState, view: HexView) -> None:
        s = self._screen
        cx = config.WINDOW_W // 2
        cy = config.WINDOW_H // 2

        # Target prompt (always shown during play)
        prompt = self._font_small.render("TARGET", True, config.MUTED_TEXT_COLOR)
        s.blit(prompt, prompt.get_rect(center=(cx, cy - 24)))
        tgt = self._font_large.render(view.target_char.upper(),
                                       True, config.TARGET_HIGHLIGHT_COLOR)
        s.blit(tgt, tgt.get_rect(center=(cx, cy + 18)))

        # Live bit-rate stats (scored phase only)
        snap = st.tracker_snapshot
        if snap is not None and st.phase == Phase.SCORED:
            bps_text = f"{snap.bit_rate:.2f} bps"
            left = self._font_medium.render(bps_text, True, config.HUD_COLOR)
            s.blit(left, left.get_rect(midright=(cx - 200, cy)))

            score_text = f"S_c {snap.correct}   S_i {snap.incorrect}"
            right = self._font_medium.render(score_text, True, config.HUD_COLOR)
            s.blit(right, right.get_rect(midleft=(cx + 200, cy)))

        # Top-right timer during scored
        if st.phase == Phase.SCORED:
            t = f"{st.scored_remaining:4.1f}s"
            timer = self._font_medium.render(t, True, config.HUD_COLOR)
            s.blit(timer, timer.get_rect(topright=(config.WINDOW_W - 30, 20)))

    # --- bottom bar -----------------------------------------------------

    def _draw_bottom_bar(self, st: SessionState, view: HexView) -> None:
        """Phase- and stage-specific instructional text.

        During play, the bottom bar always tells the player what action is
        expected RIGHT NOW. This is the second line of defense after the
        target-tile highlight — eyes have something to read if they're lost.
        """
        s = self._screen
        cx = config.WINDOW_W // 2
        y = config.WINDOW_H - 36

        if st.phase == Phase.FAMILIARIZATION:
            top = "FAMILIARIZATION  —  practice as long as you like.  ENTER  start scored run  •  ESC  quit"
            stage_msg = self._stage_msg(view)
            self._blit_two_lines(top, stage_msg, cx, y)
        elif st.phase == Phase.COUNTDOWN:
            self._blit_centered("Get ready...", cx, y)
        elif st.phase == Phase.SCORED:
            self._blit_centered(self._stage_msg(view), cx, y)

    def _stage_msg(self, view: HexView) -> str:
        if view.stage == HexStage.GROUP_SELECT:
            return ("STEP 1  —  press the key (Q/W/E/A/S/D) for the tile "
                    "containing the highlighted target letter.")
        return ("STEP 2  —  press the key for the tile where the "
                "highlighted target letter is now.")

    def _blit_centered(self, text: str, cx: int, y: int) -> None:
        surf = self._font_small.render(text, True, config.MUTED_TEXT_COLOR)
        self._screen.blit(surf, surf.get_rect(center=(cx, y)))

    def _blit_two_lines(self, top: str, bottom: str, cx: int, y: int) -> None:
        top_surf = self._font_small.render(top, True, config.MUTED_TEXT_COLOR)
        bot_surf = self._font_small.render(bottom, True, config.HUD_COLOR)
        self._screen.blit(top_surf, top_surf.get_rect(center=(cx, y - 18)))
        self._screen.blit(bot_surf, bot_surf.get_rect(center=(cx, y + 12)))

    # --- countdown ------------------------------------------------------

    def _draw_countdown_overlay(self, st: SessionState) -> None:
        s = self._screen
        cx = config.WINDOW_W // 2
        cy = config.WINDOW_H // 2
        n = int(st.countdown_remaining) + (1 if st.countdown_remaining > 0 else 0)
        n = max(n, 1)
        overlay = self._pygame.Surface((360, 360), self._pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        s.blit(overlay, overlay.get_rect(center=(cx, cy)))
        big = self._font_huge.render(str(n), True, config.TARGET_HIGHLIGHT_COLOR)
        s.blit(big, big.get_rect(center=(cx, cy)))
