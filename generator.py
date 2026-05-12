"""
generator.py — Layered filtering pipeline for nonogram puzzle generation.
Python pre-filter → Prolog uniqueness check (background thread).
"""

import random
import threading
import os

# ── Difficulty config ──────────────────────────────────────────────────────────
DIFFICULTY = {
    1: {"name": "Easy",      "fill_prob": 0.65, "max_ambiguity": 40,  "min_forced": 0.45},
    2: {"name": "Medium",    "fill_prob": 0.50, "max_ambiguity": 80,  "min_forced": 0.25},
    3: {"name": "Difficult", "fill_prob": 0.38, "max_ambiguity": 160, "min_forced": 0.08},
    4: {"name": "Extreme",   "fill_prob": 0.28, "max_ambiguity": 9999,"min_forced": 0.00},
}

# ── Prolog singleton ───────────────────────────────────────────────────────────
_prolog      = None
_prolog_lock = threading.Lock()

def _get_prolog():
    global _prolog
    if _prolog is None:
        from pyswip import Prolog
        _prolog = Prolog()
        pl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nonogram.pl")
        _prolog.consult(pl)
    return _prolog

# ── Grid / clue helpers ────────────────────────────────────────────────────────
def _make_grid(rows, cols, fill_prob):
    return [
        [1 if random.random() < fill_prob else 0 for _ in range(cols)]
        for _ in range(rows)
    ]

def get_clues(line):
    clues, count = [], 0
    for cell in line:
        if cell:
            count += 1
        elif count:
            clues.append(count)
            count = 0
    if count:
        clues.append(count)
    return clues # If the list is empty, it returns [], which matches Prolog

def row_clues(grid):
    return [get_clues(row) for row in grid]

def col_clues(grid):
    rows, cols = len(grid), len(grid[0])
    return [get_clues([grid[r][c] for r in range(rows)]) for c in range(cols)]

# ── Gate 1: clue-count constraints (spec rule) ────────────────────────────────
def _clue_counts_ok(rc, cc, rows, cols):
    max_rc = max(1, cols // 2)
    max_cc = max(1, rows // 2)
    for c in rc:
        if c != [0] and len(c) > max_rc:
            return False
    for c in cc:
        if c != [0] and len(c) > max_cc:
            return False
    return True

# ── Gate 2: ambiguity / forced-cell pre-filter ─────────────────────────────────
def _ambiguity(clue, length):
    min_sp = sum(clue) + len(clue) - 1
    slack  = max(0, length - min_sp)
    return slack * len(clue)

def _forced(clue, length):
    min_sp = sum(clue) + len(clue) - 1
    slack  = max(0, length - min_sp)
    return sum(max(0, run - slack) for run in clue)

def _python_ok(rc, cc, rows, cols, diff):
    p = DIFFICULTY[diff]
    amb = (sum(_ambiguity(c, cols) for c in rc) +
           sum(_ambiguity(c, rows) for c in cc))
    forced_ratio = (
        sum(_forced(c, cols) for c in rc) +
        sum(_forced(c, rows) for c in cc)
    ) / max(1, rows * cols)
    return amb <= p["max_ambiguity"] and forced_ratio >= p["min_forced"]

# ── Gate 3: Prolog uniqueness ──────────────────────────────────────────────────
def _prolog_unique(rc, cc):
    with _prolog_lock:
        prolog = _get_prolog()
        try:
            result = list(prolog.query(f"is_unique({rc}, {cc})"))
            return bool(result)
        except Exception:
            return False

# ── Public generator ───────────────────────────────────────────────────────────
class PuzzleGenerator:
    """
    Call generate(rows, cols, difficulty, callback).
    Runs in a daemon thread; calls callback(puzzle_dict) when done.
    puzzle_dict keys: grid, row_clues, col_clues, rows, cols,
                      difficulty, diff_name, attempts
    """

    def __init__(self):
        self.generating = False
        self.status     = "Idle"
        self._thread    = None

    def generate(self, rows, cols, difficulty, callback):
        if self.generating:
            return
        self.generating = True
        self.status     = f"Generating {DIFFICULTY[difficulty]['name']} puzzle…"
        t = threading.Thread(
            target=self._run,
            args=(rows, cols, difficulty, callback),
            daemon=True,
        )
        t.start()
        self._thread = t

    def _run(self, rows, cols, difficulty, callback):
        fp      = DIFFICULTY[difficulty]["fill_prob"]
        attempt = 0

        while True:
            attempt += 1
            if attempt % 20 == 0:
                self.status = f"Searching… (attempt {attempt})"

            grid = _make_grid(rows, cols, fp)
            rc   = row_clues(grid)
            cc   = col_clues(grid)

            if not _clue_counts_ok(rc, cc, rows, cols):
                continue
            if not _python_ok(rc, cc, rows, cols, difficulty):
                continue
            if not _prolog_unique(rc, cc):
                continue

            puzzle = {
                "grid":      grid,
                "row_clues": rc,
                "col_clues": cc,
                "rows":      rows,
                "cols":      cols,
                "difficulty":  difficulty,
                "diff_name":   DIFFICULTY[difficulty]["name"],
                "attempts":    attempt,
            }
            self.status     = f"Ready! ({DIFFICULTY[difficulty]['name']}, {attempt} attempts)"
            self.generating = False
            callback(puzzle)
            return
