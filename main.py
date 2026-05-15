"""
main.py — Nonogram game with Pygame UI.
Setup screen → dimension input → difficulty input → puzzle play.
"""
import os
os.environ["SDL_VIDEODRIVER"] = "x11"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import sys
import pygame
import threading
from generator import PuzzleGenerator, DIFFICULTY
import solver

# ── Colours ────────────────────────────────────────────────────────────────────
WHITE      = (255, 255, 255)
BLACK      = (  0,   0,   0)
LIGHT_GREY = (180, 180, 180)   # filled cell
GRID_LINE  = (  0,   0,   0)
BLUE_OVER  = ( 70, 130, 220,  60)   # transparent highlight (RGBA)
BG         = (255, 255, 255)

# ── Screen ─────────────────────────────────────────────────────────────────────
WIN_W, WIN_H = 800, 600

# ── Input state machine ────────────────────────────────────────────────────────
STATE_COLS   = "cols"
STATE_ROWS   = "rows"
STATE_DIFF   = "diff"
STATE_WAIT   = "wait"    # generating in background
STATE_PLAY   = "play"
STATE_SOLVER = "solver"
STATE_SOLVED = "solved"  # brief flash before next puzzle

# ──────────────────────────────────────────────────────────────────────────────
class Game:
    def __init__(self):
        pygame.init()
        pygame.event.set_grab(True)
        self.screen  = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("Nonogram")
        self.clock   = pygame.time.Clock()

        self.font_lg  = pygame.font.SysFont("monospace", 28, bold=True)
        self.font_md  = pygame.font.SysFont("monospace", 20)
        self.font_sm  = pygame.font.SysFont("monospace", 14)
        self.font_xs  = pygame.font.SysFont("monospace", 11)

        self.gen      = PuzzleGenerator()
        self.puzzle   = None          # current puzzle dict
        self.player   = None          # 2-D list of 0/1
        self.state    = STATE_COLS
        self.typed    = ""            # current text input buffer

        self.ncols    = 0
        self.nrows    = 0
        self.diff     = 2

        self.solved_count = 0

        self.solver = None
        self.solver_paused = False
        self.solver_step_count = 0
        self.solver_last_changes = []
        self.solver_status = ""
        self.auto_next_puzzle = False

        # layout (computed once puzzle is known)
        self.cell_px  = 0
        self.grid_x   = 0
        self.grid_y   = 0

        # highlight
        self.hover_r  = -1
        self.hover_c  = -1

        # overlay surface for transparent highlight
        self._hl_surf = None

        # thread-safe puzzle delivery
        self._pending_puzzle = None
        self._pending_lock   = threading.Lock()

    # ── Main loop ─────────────────────────────────────────────────────────────
    def run(self):
        while True:
            self._check_pending()
            self._solver_step()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                self._handle(event)
            self._draw()
            pygame.display.flip()
            self.clock.tick(60)

    # ── Thread-safe puzzle delivery ───────────────────────────────────────────
    def _deliver_puzzle(self, puzzle):
        with self._pending_lock:
            self._pending_puzzle = puzzle

    def _check_pending(self):
        with self._pending_lock:
            if self._pending_puzzle is not None:
                self._load_puzzle(self._pending_puzzle)
                self._pending_puzzle = None

    # ── Puzzle loading ────────────────────────────────────────────────────────
    def _load_puzzle(self, puzzle):
        self.puzzle = puzzle
        rows = puzzle["rows"]
        cols = puzzle["cols"]
        self.player = [[0]*cols for _ in range(rows)]
        self.solver = None
        self.solver_paused = False
        self.solver_step_count = 0
        self.solver_last_changes = []
        self.solver_status = ""
        self.auto_next_puzzle = False
        self._compute_layout(rows, cols)
        self.state = STATE_PLAY

    def _compute_layout(self, rows, cols):
        """
        Fit the grid into roughly the bottom-right 65% of the window.
        Reserve left margin for row clues, top margin for col clues.
        Cell is square; size is chosen to fill ~800x600.
        """
        rc = self.puzzle["row_clues"]
        cc = self.puzzle["col_clues"]

        # Estimate max clue text width (row clues) and height (col clues)
        max_rc_len = max(len(c) for c in rc)          # number of numbers
        max_cc_len = max(len(c) for c in cc)

        # Available area (leave small border)
        avail_w = WIN_W - 20
        avail_h = WIN_H - 60   # 60px top bar for stats

        # Character width ≈ 9px for font_sm (size 14)
        char_w = 9
        # Row clue margin: each number + comma ≈ 3 chars, +1 space between groups
        row_margin = max_rc_len * 3 * char_w + 12
        row_margin = max(60, min(row_margin, 220))

        # Col clue margin: each number stacked, ~16px per digit line
        col_margin = max_cc_len * 16 + 8
        col_margin = max(30, min(col_margin, 160))

        grid_avail_w = avail_w - row_margin
        grid_avail_h = avail_h - col_margin

        cell_w = grid_avail_w // cols
        cell_h = grid_avail_h // rows
        self.cell_px = max(10, min(cell_w, cell_h))

        grid_w = self.cell_px * cols
        grid_h = self.cell_px * rows

        # Pin grid to bottom-right
        self.grid_x = WIN_W - grid_w - 10
        self.grid_y = WIN_H - grid_h - 10

        # Recompute margins based on actual grid position
        self.row_margin_x = self.grid_x       # left edge of grid
        self.col_margin_y = self.grid_y       # top edge of grid

        # Highlight overlay surface
        self._hl_surf = pygame.Surface(
            (self.cell_px, self.cell_px * max(self.puzzle["rows"], self.puzzle["cols"]) + 40),
            pygame.SRCALPHA
        )

        # ── Event handling ────────────────────────────────────────────────────────
    def _handle(self, event):
            # 1. Capture text characters (numbers) using TEXTINPUT
            if self.state in (STATE_COLS, STATE_ROWS, STATE_DIFF):
                if event.type == pygame.TEXTINPUT:
                    if event.text.isdigit():
                        self.typed += event.text
                
                # 2. Capture control keys (Backspace/Enter) using KEYDOWN
                if event.type == pygame.KEYDOWN:
                    self._handle_input(event)
                    
            elif self.state == STATE_PLAY:
                self._handle_play(event)
                
            elif self.state == STATE_SOLVED:
                self._handle_solved(event)

    def _handle_input(self, event):
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_BACKSPACE:
                    self.typed = self.typed[:-1]
                elif event.key == pygame.K_RETURN:
                    self._commit_input()
                
                # This maps the PHYSICAL keys, ignoring NumLock/Shift/Unicode
                numbers = {
                    pygame.K_0: "0", pygame.K_1: "1", pygame.K_2: "2", 
                    pygame.K_3: "3", pygame.K_4: "4", pygame.K_5: "5", 
                    pygame.K_6: "6", pygame.K_7: "7", pygame.K_8: "8", 
                    pygame.K_9: "9",
                    # Also map the Numpad keys explicitly
                    pygame.K_KP0: "0", pygame.K_KP1: "1", pygame.K_KP2: "2",
                    pygame.K_KP3: "3", pygame.K_KP4: "4", pygame.K_KP5: "5",
                    pygame.K_KP6: "6", pygame.K_KP7: "7", pygame.K_KP8: "8",
                    pygame.K_KP9: "9"
                }
                if event.key in numbers:
                    self.typed += numbers[event.key]

    def _commit_input(self):
        val = self.typed.strip()
        self.typed = ""

        if self.state == STATE_COLS:
            try:
                v = int(val)
                if v < 2: v = 2
                if v > 30: v = 30
            except ValueError:
                v = 5
            self.ncols = v
            self.state = STATE_ROWS

        elif self.state == STATE_ROWS:
            try:
                v = int(val)
                if v < 2: v = 2
                if v > 30: v = 30
            except ValueError:
                v = 5
            self.nrows = v
            self.state = STATE_DIFF

        elif self.state == STATE_DIFF:
            try:
                v = int(val)
                if v not in (1, 2, 3, 4):
                    v = 2
            except ValueError:
                v = 2
            self.diff  = v
            self._start_generation()

    def _handle_play(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                if self.solver is None:
                    self._start_solver()
                else:
                    self.solver_paused = not self.solver_paused
                    self.solver_status = "Paused" if self.solver_paused else "Running"
            elif event.key == pygame.K_h:
                self._hint_step()
            elif event.key == pygame.K_n:
                self._start_generation()
            elif event.key == pygame.K_s:
                self.solver = None
                self.solver_paused = False
                self.solver_status = ""
                self.auto_next_puzzle = False
                self.typed = ""
                self.state = STATE_COLS

        elif event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self.solver is None:
                self._toggle_cell(event.pos)

    def _handle_solved(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                self._start_generation()
            elif event.key == pygame.K_s:
                self.typed = ""
                self.state = STATE_COLS

    def _update_hover(self, pos):
        mx, my = pos
        gx, gy = self.grid_x, self.grid_y
        cp = self.cell_px
        c = (mx - gx) // cp
        r = (my - gy) // cp
        cols = self.puzzle["cols"]
        rows = self.puzzle["rows"]
        if 0 <= r < rows and 0 <= c < cols:
            self.hover_r, self.hover_c = r, c
        else:
            self.hover_r = self.hover_c = -1

    def _toggle_cell(self, pos):
        mx, my = pos
        gx, gy = self.grid_x, self.grid_y
        cp = self.cell_px
        c = (mx - gx) // cp
        r = (my - gy) // cp
        cols = self.puzzle["cols"]
        rows = self.puzzle["rows"]
        if 0 <= r < rows and 0 <= c < cols:
            self.player[r][c] ^= 1
            self._check_solved()

    def _check_solved(self):
        if self.player == self.puzzle["grid"]:
            self.solved_count += 1
            self.state = STATE_SOLVED

    def _start_solver(self):
        if not self.puzzle:
            return
        self.solver = solver.solve_steps(
            self.puzzle["row_clues"],
            self.puzzle["col_clues"],
            self.player,
        )
        self.solver_paused = False
        self.solver_step_count = 0
        self.solver_last_changes = []
        self.solver_status = "Running"

    def _hint_step(self):
        if not self.puzzle:
            return
        if self.solver is None:
            self._start_solver()
        self.auto_next_puzzle = False
        self.solver_paused = True
        self._solver_step(force=True)

    def _solver_step(self, force=False):
        if self.solver is None or (self.solver_paused and not force) or self.state != STATE_PLAY:
            return
        try:
            step = next(self.solver)
            self.player = step["board"]
            self.solver_step_count = step["step"]
            self.solver_last_changes = step["changed"]
            self.solver_status = (
                f"{step['line_type'] or 'Init'} {step['line_index']}"
            )
            self._check_solved()
        except StopIteration:
            self.solver = None
            if self.player == self.puzzle["grid"] and self.auto_next_puzzle:
                self.auto_next_puzzle = False
                self._start_generation()
                return
            if self.player == self.puzzle["grid"]:
                self.solver_status = "Solver completed"
            else:
                self.solver_status = "Solver stuck"

    # ── Generation ────────────────────────────────────────────────────────────
    def _start_generation(self):
        self.state = STATE_WAIT
        self.gen.generate(
            self.nrows, self.ncols, self.diff,
            callback=self._deliver_puzzle
        )

    # ── Drawing ───────────────────────────────────────────────────────────────
    def _draw(self):
        self.screen.fill(BG)

        if self.state in (STATE_COLS, STATE_ROWS, STATE_DIFF):
            self._draw_setup()
        elif self.state == STATE_WAIT:
            self._draw_wait()
        elif self.state == STATE_PLAY:
            self._draw_hud()
            self._draw_puzzle()
        elif self.state == STATE_SOLVED:
            self._draw_hud()
            self._draw_solved()

    # ── Setup screen ──────────────────────────────────────────────────────────
    def _draw_setup(self):
        cx = WIN_W // 2

        title = self.font_lg.render("NONOGRAM", True, BLACK)
        self.screen.blit(title, title.get_rect(center=(cx, 80)))

        if self.state == STATE_COLS:
            prompt = "Enter number of columns (X):"
            hint   = "Press Enter to confirm"
        elif self.state == STATE_ROWS:
            prompt = f"Columns: {self.ncols}   Enter number of rows (Y):"
            hint   = "Press Enter to confirm"
        else:
            prompt = f"Columns: {self.ncols}   Rows: {self.nrows}"
            hint   = "Difficulty:  1 Easy  2 Medium  3 Difficult  4 Extreme"

        p_surf = self.font_md.render(prompt, True, BLACK)
        self.screen.blit(p_surf, p_surf.get_rect(center=(cx, 200)))

        h_surf = self.font_sm.render(hint, True, (80, 80, 80))
        self.screen.blit(h_surf, h_surf.get_rect(center=(cx, 235)))

        # Input box
        box = pygame.Rect(cx - 80, 270, 160, 40)
        pygame.draw.rect(self.screen, WHITE, box)
        pygame.draw.rect(self.screen, BLACK, box, 2)
        cursor = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
        inp = self.font_md.render(self.typed + cursor, True, BLACK)
        self.screen.blit(inp, inp.get_rect(center=box.center))

    # ── Wait screen ───────────────────────────────────────────────────────────
    def _draw_wait(self):
        cx, cy = WIN_W // 2, WIN_H // 2
        self._draw_hud()
        msg = self.font_md.render(self.gen.status, True, (40, 40, 40))
        self.screen.blit(msg, msg.get_rect(center=(cx, cy)))
        dots = "." * ((pygame.time.get_ticks() // 400) % 4)
        d = self.font_md.render(dots, True, BLACK)
        self.screen.blit(d, d.get_rect(center=(cx, cy + 36)))

    # ── Solved screen ─────────────────────────────────────────────────────────
    def _draw_solved(self):
        cx, cy = WIN_W // 2, WIN_H // 2
        msg = self.font_lg.render("PUZZLE SOLVED!", True, BLACK)
        self.screen.blit(msg, msg.get_rect(center=(cx, cy - 50)))
        hint1 = self.font_md.render("Press N for new puzzle with same settings", True, (80, 80, 80))
        self.screen.blit(hint1, hint1.get_rect(center=(cx, cy)))
        hint2 = self.font_md.render("Press S to change dimensions and difficulty", True, (80, 80, 80))
        self.screen.blit(hint2, hint2.get_rect(center=(cx, cy + 30)))

    # ── HUD ───────────────────────────────────────────────────────────────────
    def _draw_hud(self):
        diff_name = DIFFICULTY[self.diff]["name"] if self.diff in DIFFICULTY else "Medium"
        hud = f"Solved: {self.solved_count}   Difficulty: {diff_name}"
        surf = self.font_sm.render(hud, True, BLACK)
        self.screen.blit(surf, (10, 10))

        if self.puzzle:
            size_txt = f"{self.puzzle['cols']}x{self.puzzle['rows']}"
            s = self.font_sm.render(size_txt, True, (100, 100, 100))
            self.screen.blit(s, (10, 28))

        if self.solver is not None:
            status_txt = f"Solver: {self.solver_status or 'Running'}  Step: {self.solver_step_count}"
            s2 = self.font_sm.render(status_txt, True, (0, 80, 0))
            self.screen.blit(s2, (10, 48))

        # Controls hint
        ctrl = self.font_xs.render("Space = start/pause solve, H = hint one tile, N = new puzzle, S = change dimensions", True, (160, 160, 160))
        self.screen.blit(ctrl, (WIN_W - ctrl.get_width() - 8, 8))

    # ── Puzzle rendering ──────────────────────────────────────────────────────
    def _draw_puzzle(self):
        p   = self.puzzle
        rc  = p["row_clues"]
        cc  = p["col_clues"]
        rows, cols = p["rows"], p["cols"]
        cp  = self.cell_px
        gx, gy = self.grid_x, self.grid_y

        # --- 1. Highlight row & column (transparent blue) ---
        if self.hover_r >= 0 and self.hover_c >= 0:
            hl = pygame.Surface((cp * cols, cp), pygame.SRCALPHA)
            hl.fill(BLUE_OVER)
            self.screen.blit(hl, (gx, gy + self.hover_r * cp))

            hl2 = pygame.Surface((cp, cp * rows), pygame.SRCALPHA)
            hl2.fill(BLUE_OVER)
            self.screen.blit(hl2, (gx + self.hover_c * cp, gy))

        # --- 2. Cell fills ---
        for r in range(rows):
            for c in range(cols):
                rect = pygame.Rect(gx + c*cp, gy + r*cp, cp, cp)
                if self.player[r][c] == solver.FILLED:
                    pygame.draw.rect(self.screen, LIGHT_GREY, rect)

        # Highlight newly solved cells
        if self.solver_last_changes:
            for r, c, _ in self.solver_last_changes:
                rect = pygame.Rect(gx + c*cp, gy + r*cp, cp, cp)
                pygame.draw.rect(self.screen, (140, 220, 140), rect, 2)

        # --- 3. Grid lines ---
        for r in range(rows + 1):
            lw = 2 if r % 5 == 0 else 1
            pygame.draw.line(self.screen, GRID_LINE,
                             (gx, gy + r*cp), (gx + cols*cp, gy + r*cp), lw)
        for c in range(cols + 1):
            lw = 2 if c % 5 == 0 else 1
            pygame.draw.line(self.screen, GRID_LINE,
                             (gx + c*cp, gy), (gx + c*cp, gy + rows*cp), lw)

        # --- 4. Row clues (left of grid) ---
        for r, clue in enumerate(rc):
            cy_center = gy + r*cp + cp//2
            text = " ".join(str(n) for n in clue)
            surf = self.font_xs.render(text, True, BLACK)
            # right-align against grid left edge
            x = gx - surf.get_width() - 6
            self.screen.blit(surf, (max(0, x), cy_center - surf.get_height()//2))

        # --- 5. Column clues (above grid) ---
        for c, clue in enumerate(cc):
            cx_center = gx + c*cp + cp//2
            # stack numbers vertically, bottom-aligned to grid top
            line_h = self.font_xs.get_linesize()
            total_h = len(clue) * line_h
            y_start = gy - total_h - 4
            for i, num in enumerate(clue):
                surf = self.font_xs.render(str(num), True, BLACK)
                x = cx_center - surf.get_width()//2
                y = y_start + i * line_h
                if y >= 40:   # don't draw over HUD
                    self.screen.blit(surf, (x, y))


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    Game().run()
