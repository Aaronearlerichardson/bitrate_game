"""Pygame renderer for GridQuest.

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
from .mode import GridSlotView, GridStage, GridView


# -----------------------------------------------------------------------------
# Renderer protocol
# -----------------------------------------------------------------------------

class Renderer(Protocol):
    def init(self) -> None: ...
    def draw(self, session_state: SessionState, mode_view: object) -> None: ...
    def shutdown(self) -> None: ...


# -----------------------------------------------------------------------------
# Pygame GridQuest renderer
# -----------------------------------------------------------------------------

class PygameGridRenderer:
    """Renders the GridQuest 3x3 board + session HUD with pygame.

    Layout:

        +---------------------------------------------------+
        |  [Q]      [W]      [E]                            |
        |                                                   |
        |  [A]      [S]      [D]    (central HUD with cue)  |
        |                                                   |
        |  [Z]      [X]      [C]                            |
        |                                                   |
        |  bottom bar: phase-specific instructions          |
        +---------------------------------------------------+

    Each tile shows its key letter (Q/W/E/A/S/D/Z/X/C) in the corner.
    Stage 1: the tile whose group contains the target gets a yellow border.
    Stage 2: the target tile gets a yellow border.
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
        pg.display.set_caption("GridQuest — bit-rate game")

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
            assert isinstance(mode_view, GridView), \
                f"renderer expected GridView, got {type(mode_view).__name__}"
            self._draw_grid_board(session_state, mode_view)

        self._pygame.display.flip()

    # ====================================================================
    # Welcome screen
    # ====================================================================

    def _draw_welcome(self) -> None:
        """Title + cue/board side-by-side example + step text + controls.

        Layout is adaptive: titles anchor to the top, the controls bar
        anchors to the bottom, the step list anchors above the controls,
        and the example panel fills whatever vertical space remains in
        between.
        """
        s = self._screen
        cx = config.WINDOW_W // 2

        # --- Fixed anchors -------------------------------------------------
        title_y = 55
        subtitle_y = 95
        controls_y = config.WINDOW_H - 30

        steps_text = [
            "STEP 1   The cue board shows a single YELLOW square in one of the 9 cells.",
            "         Press the key (Q/W/E/A/S/D/Z/X/C) for the OUTER group that contains it.",
            "STEP 2   The 9 tiles now represent the 9 INNER positions of the chosen group.",
            "         Press the key for the inner position the target sat in.",
        ]
        step_line_h = 28
        # Leave 30px between last step center and controls center.
        steps_bottom_y = controls_y - 45
        steps_top_y = steps_bottom_y - step_line_h * (len(steps_text) - 1)

        # Panel: fills the space between subtitle and the step list.
        panel_top = subtitle_y + 25
        panel_bottom = steps_top_y - 25
        panel_h = max(180, min(360, panel_bottom - panel_top))
        panel_w = min(720, config.WINDOW_W - 100)
        panel_cy = (panel_top + panel_bottom) // 2

        # --- Draw ----------------------------------------------------------
        title = self._font_large.render("GridQuest", True, config.TEXT_COLOR)
        s.blit(title, title.get_rect(center=(cx, title_y)))

        subtitle = self._font_small.render(
            f"Two keypresses per selection. "
            f"N = {self._cfg.n} targets ({self._cfg.num_tiles} groups "
            f"× {self._cfg.num_tiles} inner positions).",
            True, config.MUTED_TEXT_COLOR)
        s.blit(subtitle, subtitle.get_rect(center=(cx, subtitle_y)))

        # Two panels side by side: left = the cue board, right = the tile
        # board with the (group, slot) answer highlighted. Picking a target
        # in roughly the middle to look balanced.
        example_target = (self._cfg.n // 2) + (self._cfg.num_tiles // 2)
        cue_w = panel_h  # square cue board
        cue_rect = self._pygame.Rect(0, 0, cue_w, panel_h)
        cue_rect.center = (cx - panel_w // 4, panel_cy)
        self._draw_cue_grid(cue_rect, example_target,
                            label="EXAMPLE TARGET")

        board_rect = self._pygame.Rect(0, 0, panel_w // 2 + 40, panel_h)
        board_rect.center = (cx + panel_w // 4, panel_cy)
        self._draw_example_board(board_rect, example_target)

        y = steps_top_y
        for line in steps_text:
            surf = self._font_small.render(line, True, config.TEXT_COLOR)
            s.blit(surf, surf.get_rect(midleft=(cx - 380, y)))
            y += step_line_h

        controls = ("SPACE  practice (unlimited)      "
                    "ENTER  start 60-second scored run      "
                    "ESC  quit")
        ctrl = self._font_small.render(controls, True, config.HUD_COLOR)
        s.blit(ctrl, ctrl.get_rect(center=(cx, controls_y)))

    def _draw_example_board(self, rect, target: int) -> None:
        """A scaled-down 3x3 tile board that highlights the target group
        (stage-1 view) so the player sees exactly what they'll see in
        gameplay after reading the cue."""
        rects = self._slot_rects(board_rect=rect, gutter=10, margin=0)
        target_group, _ = divmod(target, self._cfg.num_tiles)
        for idx, r in enumerate(rects):
            is_target = (idx == target_group)
            base = (44, 50, 64) if is_target else config.TILE_COLOR
            border = (config.TARGET_HIGHLIGHT_COLOR
                      if is_target else config.TILE_BORDER_COLOR)
            border_w = 4 if is_target else 2
            self._pygame.draw.rect(self._screen, base, r, border_radius=10)
            self._pygame.draw.rect(self._screen, border, r,
                                   width=border_w, border_radius=10)
            self._draw_key_label(r, self._cfg.slot_keys[idx])

    # --- cue grid (mini-9x9 reference board) ----------------------------

    def _draw_cue_grid(self, rect, target: int, *,
                       label: Optional[str] = None) -> None:
        """Draw a mini-9x9 reference board with cell `target` highlighted.

        The board has thick borders between the nine 3x3 outer groups and
        thin borders between the inner cells. This single visual encodes
        both stages of the selection: outer position -> key 1, inner
        position -> key 2.
        """
        pg = self._pygame
        s = self._screen
        nt = self._cfg.num_tiles  # 9, but written generically
        side = max(int(nt ** 0.5), 1)  # the outer/inner grid is sqrt(nt) x sqrt(nt)
        # For num_tiles=9: side = 3, total cells = 9*9 = 81 = num_tiles^2.

        # Reserve a small label strip at the top if a label is given.
        if label:
            lbl = self._font_small.render(label, True, config.MUTED_TEXT_COLOR)
            s.blit(lbl, lbl.get_rect(midtop=(rect.centerx, rect.top - 2)))
            grid_top = rect.top + lbl.get_height() + 6
        else:
            grid_top = rect.top
        grid_size = min(rect.width, rect.bottom - grid_top)
        grid_x = rect.centerx - grid_size // 2
        grid_y = grid_top

        # Background panel for the grid.
        bg_rect = pg.Rect(grid_x, grid_y, grid_size, grid_size)
        pg.draw.rect(s, (28, 32, 40), bg_rect, border_radius=8)

        target_group, target_slot = divmod(target, nt)
        tg_row, tg_col = divmod(target_group, side)
        ts_row, ts_col = divmod(target_slot, side)

        # Cells per row on the mini board = side*side (3 outer × 3 inner = 9).
        cells_per_row = side * side
        cell = grid_size / cells_per_row

        # Highlight the target cell.
        # Absolute (row, col) of the target on the 9x9 board:
        abs_row = tg_row * side + ts_row
        abs_col = tg_col * side + ts_col
        hl = pg.Rect(
            int(grid_x + abs_col * cell),
            int(grid_y + abs_row * cell),
            int(cell) + 1,
            int(cell) + 1,
        )
        pg.draw.rect(s, config.TARGET_HIGHLIGHT_COLOR, hl)

        # Inner cell lines (thin).
        thin = (60, 66, 80)
        for i in range(1, cells_per_row):
            x = int(grid_x + i * cell)
            y = int(grid_y + i * cell)
            pg.draw.line(s, thin, (x, grid_y), (x, grid_y + grid_size), 1)
            pg.draw.line(s, thin, (grid_x, y), (grid_x + grid_size, y), 1)

        # Outer group lines (thick) — every `side`th cell.
        thick = (140, 150, 170)
        for i in range(0, side + 1):
            x = int(grid_x + i * side * cell)
            y = int(grid_y + i * side * cell)
            pg.draw.line(s, thick, (x, grid_y), (x, grid_y + grid_size), 3)
            pg.draw.line(s, thick, (grid_x, y), (grid_x + grid_size, y), 3)

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

    def _draw_grid_board(self, st: SessionState, view: GridView) -> None:
        rects = self._slot_rects(board_rect=None)
        flash_active = self._flash_is_active(view)
        self._draw_slots_in(view, rects, flash_active=flash_active)
        self._draw_hud(st, view)
        self._draw_bottom_bar(st, view)
        if st.phase == Phase.COUNTDOWN:
            self._draw_countdown_overlay(st)

    def _flash_is_active(self, view: GridView) -> bool:
        if view.last_feedback_correct is None:
            return False
        return (time.monotonic() - view.last_feedback_at) < config.FEEDBACK_FLASH_SEC

    # --- slot rectangles ------------------------------------------------

    def _slot_rects(self, board_rect=None, gutter: int = 30, margin: int = 80):
        """Return num_tiles rects laid out in a sqrt(num_tiles) square.

        For num_tiles=9, that's a 3x3 grid. If `board_rect` is None, fill
        the window minus default margins; otherwise lay out within the
        given rect.
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

        side = max(int(self._cfg.num_tiles ** 0.5), 1)  # 3 for num_tiles=9
        w = (board_w - (side - 1) * gutter) // side
        h = (board_h - (side - 1) * gutter) // side
        rects: list = []
        for r in range(side):
            for c in range(side):
                x = x0 + c * (w + gutter)
                y = y0 + r * (h + gutter)
                rects.append(pg.Rect(x, y, w, h))
        return rects

    # --- slot drawing ---------------------------------------------------

    def _draw_slots_in(self, view: GridView, rects, *,
                       flash_active: bool) -> None:
        """Render each of the num_tiles tiles.

        Visual rules:
          * Every tile shows its key letter (Q/W/E/A/S/D/Z/X/C) in the corner.
          * Stage 1: the tile whose group contains the target gets a thick
            yellow border + slightly tinted background.
          * Stage 2: every tile has a blue border (showing we're in stage 2);
            the target tile additionally gets the yellow highlight.
          * On a recent selection: every tile flashes green (correct) or
            red (incorrect) briefly.
        """
        pg = self._pygame
        s = self._screen
        for idx, rect in enumerate(rects):
            slot = view.slots[idx]

            base = config.TILE_COLOR
            border = config.TILE_BORDER_COLOR
            border_w = 3

            if view.stage == GridStage.GROUP_SELECT and slot.is_target_group:
                base = (44, 50, 64)
                border = config.TARGET_HIGHLIGHT_COLOR
                border_w = 5
            elif view.stage == GridStage.TILE_SELECT:
                border = config.TILE_ACTIVE_COLOR
                if slot.is_target_tile:
                    base = (44, 50, 64)
                    border = config.TARGET_HIGHLIGHT_COLOR
                    border_w = 5

            if flash_active:
                base = (
                    config.CORRECT_FLASH_COLOR
                    if view.last_feedback_correct
                    else config.INCORRECT_FLASH_COLOR
                )

            pg.draw.rect(s, base, rect, border_radius=18)
            pg.draw.rect(s, border, rect, width=border_w, border_radius=18)
            self._draw_key_label(rect, self._cfg.slot_keys[idx])

    def _draw_key_label(self, rect, key_char: str) -> None:
        """Small key letter in the top-left of a tile (e.g. 'Q')."""
        font = self._font_tiny
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

    # --- HUD ------------------------------------------------------------

    def _draw_hud(self, st: SessionState, view: GridView) -> None:
        s = self._screen
        cx = config.WINDOW_W // 2
        cy = config.WINDOW_H // 2

        # Target cue: a mini-9x9 reference board centered in the HUD area.
        cue_size = 180
        cue_rect = self._pygame.Rect(0, 0, cue_size, cue_size)
        cue_rect.center = (cx, cy)
        self._draw_cue_grid(cue_rect, view.target, label="TARGET")

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

    def _draw_bottom_bar(self, st: SessionState, view: GridView) -> None:
        """Phase- and stage-specific instructional text.

        During play, the bottom bar always tells the player what action is
        expected RIGHT NOW. This is the second line of defense after the
        target-tile highlight — eyes have something to read if they're lost.
        """
        cx = config.WINDOW_W // 2
        y = config.WINDOW_H - 36

        if st.phase == Phase.FAMILIARIZATION:
            top = ("FAMILIARIZATION  —  practice as long as you like.  "
                   "ENTER  scored run  •  SPACE  menu  •  ESC  quit")
            self._blit_two_lines(top, self._stage_msg(view), cx, y)
        elif st.phase == Phase.COUNTDOWN:
            self._blit_two_lines("Get ready...", "SPACE  abort  •  ESC  quit", cx, y)
        elif st.phase == Phase.SCORED:
            self._blit_two_lines(self._stage_msg(view),
                                 "SPACE  abort  •  ESC  quit", cx, y)

    def _stage_msg(self, view: GridView) -> str:
        if view.stage == GridStage.GROUP_SELECT:
            return ("STEP 1  —  press the key for the OUTER group "
                    "containing the highlighted cell.")
        return ("STEP 2  —  press the key for the INNER position "
                "the highlighted cell sat in.")

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
