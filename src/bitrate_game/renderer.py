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

        # Fit the window to the host display so it never overflows on
        # smaller laptops or under DPI scaling. pygame.display.Info()
        # returns the dimensions of the area pygame can actually use,
        # so this works whether the OS reports 1366x768 native or a
        # DPI-scaled effective resolution.
        info = pg.display.Info()
        fit_w = min(config.WINDOW_W, int(info.current_w * 0.95))
        fit_h = min(config.WINDOW_H, int(info.current_h * 0.88))
        # Renderer layout math reads these constants directly throughout
        # this module, so update them to the actual window size we chose.
        config.WINDOW_W = fit_w
        config.WINDOW_H = fit_h
        # RESIZABLE lets the user drag the window edges. The adapter
        # listens for pygame's VIDEORESIZE event and calls set_mode again
        # with the new dimensions — the renderer's layout math reads
        # config.WINDOW_W / WINDOW_H each frame, so the UI reflows on the
        # next draw without any extra signalling.
        self._screen = pg.display.set_mode((fit_w, fit_h), pg.RESIZABLE)
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
        # Re-fetch the surface each frame: pygame.display.set_mode() may
        # invalidate the previous reference when the window is resized.
        self._screen = self._pygame.display.get_surface()
        if self._screen is None:
            return  # display gone (window closed); loop will exit shortly
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

        Layout is adaptive: titles anchor to the top, the controls bar
        anchors to the bottom, the step list anchors above the controls,
        and the example board fills whatever vertical space remains in
        between. This way the controls/steps never collide on shorter
        windows (e.g. when the auto-fit lands at 88% of a 768p screen)
        and the example board grows when the user enlarges the window.
        """
        s = self._screen
        cx = config.WINDOW_W // 2

        # --- Fixed anchors -------------------------------------------------
        title_y = 55
        subtitle_y = 95
        controls_y = config.WINDOW_H - 30

        # Steps: 4 lines stacked just above the controls bar.
        steps_text = [
            "STEP 1   Find the YELLOW target letter ({tgt!r}). It lives inside one tile.",
            "         Press the key labeled on that tile — its corner shows Q/W/E/A/S/D.",
            "STEP 2   The chosen tile's letters then spread across all six tiles, one per tile.",
            "         Press the key for the tile where your target letter has moved.",
        ]
        step_line_h = 28
        # Bottom of the last step's *center* — its text descends ~13px
        # further, so leave at least 30px between center and controls
        # to keep a comfortable visible gap.
        steps_bottom_y = controls_y - 45
        steps_top_y = steps_bottom_y - step_line_h * (len(steps_text) - 1)

        # Board: fills the space between subtitle and the step list.
        board_top = subtitle_y + 25
        board_bottom = steps_top_y - 25
        board_h = max(180, min(360, board_bottom - board_top))
        board_w = min(760, config.WINDOW_W - 100)
        board_cy = (board_top + board_bottom) // 2

        # --- Draw ----------------------------------------------------------
        title = self._font_large.render("Hex-o-Spell Bit-Rate Game",
                                        True, config.TEXT_COLOR)
        s.blit(title, title.get_rect(center=(cx, title_y)))

        subtitle = self._font_small.render(
            f"Type one letter at a time using two key presses.   "
            f"Alphabet: {self._cfg.n} characters in {self._cfg.num_groups} groups of {self._cfg.group_size}.",
            True, config.MUTED_TEXT_COLOR)
        s.blit(subtitle, subtitle.get_rect(center=(cx, subtitle_y)))

        example_target = "e" if "e" in self._cfg.alphabet else self._cfg.alphabet[0]
        example_view = self._make_example_view(example_target)
        board_rect = self._pygame.Rect(0, 0, board_w, board_h)
        board_rect.center = (cx, board_cy)
        rects = self._slot_rects(board_rect, gutter=14, margin=0)
        self._draw_slots_in(
            example_view, rects,
            big_font=self._font_preview_big,
            small_font=self._font_preview_small,
            flash_active=False,
        )

        prompt = self._font_small.render("EXAMPLE TARGET", True, config.MUTED_TEXT_COLOR)
        s.blit(prompt, prompt.get_rect(center=(cx, board_rect.centery - 18)))
        tgt = self._font_large.render(example_target.upper(),
                                       True, config.TARGET_HIGHLIGHT_COLOR)
        s.blit(tgt, tgt.get_rect(center=(cx, board_rect.centery + 22)))

        y = steps_top_y
        for line in steps_text:
            surf = self._font_small.render(
                line.format(tgt=example_target), True, config.TEXT_COLOR)
            s.blit(surf, surf.get_rect(midleft=(cx - 380, y)))
            y += step_line_h

        controls = "SPACE  practice (unlimited)      ENTER  start 60-second scored run      ESC  quit"
        ctrl = self._font_small.render(controls, True, config.HUD_COLOR)
        s.blit(ctrl, ctrl.get_rect(center=(cx, controls_y)))

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
        """Render the group's chars in a 2-row x 3-col mini-grid.

        The mini-grid mirrors the full board's 3-col x 2-row slot arrangement,
        so chars[0..5] sit at the same relative positions they will occupy
        when the group expands into stage 2. This trains the player's spatial
        expectation: a target seen in the bottom-right of its group will
        appear in the bottom-right slot of the board after the first press.
        """
        s = self._screen
        cols, rows = 3, 2
        cell_w = rect.width / cols
        cell_h = rect.height / rows
        for i, ch in enumerate(chars):
            col = i % cols
            row = i // cols
            cx = rect.x + cell_w * (col + 0.5)
            cy = rect.y + cell_h * (row + 0.5)
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

        # Live bit-rate readout (top-left, out of the tile area).
        self._draw_live_bitrate(st)

        # Top-right timer during scored
        if st.phase == Phase.SCORED:
            t = f"{st.scored_remaining:4.1f}s"
            timer = self._font_medium.render(t, True, config.HUD_COLOR)
            s.blit(timer, timer.get_rect(topright=(config.WINDOW_W - 30, 20)))

    # --- live bitrate readout ------------------------------------------

    def _draw_live_bitrate(self, st: SessionState) -> None:
        """Top-left HUD: running bit-rate + S_c / S_i counts.

        Shown in both FAMILIARIZATION and SCORED so the player can see their
        bit rate while practicing. The label names the current mode
        (PRACTICE vs SCORED) so the player always knows which run produced
        the number on screen.
        """
        if st.phase not in (Phase.FAMILIARIZATION, Phase.SCORED):
            return
        snap = st.tracker_snapshot
        if snap is None:
            return
        s = self._screen
        x, y = 30, 18
        mode_text = "PRACTICE BIT RATE" if st.phase == Phase.FAMILIARIZATION else "SCORED BIT RATE"
        label = self._font_tiny.render(mode_text,
                                        True, config.MUTED_TEXT_COLOR)
        s.blit(label, label.get_rect(topleft=(x, y)))
        bps = self._font_medium.render(f"{snap.bit_rate:.2f} bps",
                                        True, config.TARGET_HIGHLIGHT_COLOR)
        s.blit(bps, bps.get_rect(topleft=(x, y + 20)))
        counts = self._font_small.render(
            f"S_c {snap.correct}   S_i {snap.incorrect}",
            True, config.HUD_COLOR)
        s.blit(counts, counts.get_rect(topleft=(x, y + 58)))

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
