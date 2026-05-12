"""
generator.py — Thorough yet efficient nonogram puzzle generation.

Pipeline per candidate:
  Gate 1 (instant)   — clue-count rule from spec (cols//2, rows//2)
  Gate 2 (fast, ~ms) — Python overlap analysis: forced-ratio + ambiguity
  Gate 3 (medium)    — Prolog difficulty score (no solving, just arithmetic)
  Gate 4 (slow)      — Prolog uniqueness check (full CLP(FD) solve x2)

Gates 1-3 are cheap and kill >95% of bad candidates before Gate 4 runs.
"""

import random
import threading
import os
import math

# ── Difficulty bands ───────────────────────────────────────────────────────────
# Each band is defined as a target range for the Prolog difficulty score (0–1)
# plus a fill_prob that biases the random grid toward that region.
#
#  Score guide:  0.0–0.25 = Easy   0.25–0.50 = Medium
#                0.50–0.75 = Hard   0.75–1.0  = Extreme
#
DIFFICULTY = {
    1: {
        "name":        "Easy",
        "fill_prob":   0.68,       # dense → long runs → high overlap
        "score_lo":    0.00,
        "score_hi":    0.28,
        # Python pre-filter mirrors (fast approximation of Prolog score)
        "min_forced":  0.48,       # high forced ratio = easy
        "max_ambig":   35,
    },
    2: {
        "name":        "Medium",
        "fill_prob":   0.52,
        "score_lo":    0.25,
        "score_hi":    0.52,
        "min_forced":  0.22,
        "max_ambig":   90,
    },
    3: {
        "name":        "Difficult",
        "fill_prob":   0.38,
        "score_lo":    0.48,
        "score_hi":    0.76,
        "min_forced":  0.05,
        "max_ambig":   200,
    },
    4: {
        "name":        "Extreme",
        "fill_prob":   0.28,
        "score_lo":    0.72,
        "score_hi":    1.00,
        "min_forced":  0.00,
        "max_ambig":   9999,
    },
}

# ── Prolog singleton (thread-safe) ─────────────────────────────────────────────
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

# ── Grid helpers ───────────────────────────────────────────────────────────────
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
    return clues  # [] means empty row/col — Prolog handles []

def row_clues(grid):
    return [get_clues(row) for row in grid]

def col_clues(grid):
    rows, cols = len(grid), len(grid[0])
    return [get_clues([grid[r][c] for r in range(rows)]) for c in range(cols)]

# ── Gate 1: clue-count rule (spec) ────────────────────────────────────────────
def _gate1_clue_counts(rc, cc, rows, cols):
    """Max clues per row ≤ cols//2, per col ≤ rows//2."""
    max_rc = max(1, cols // 2)
    max_cc = max(1, rows // 2)
    for c in rc:
        if len(c) > max_rc:
            return False
    for c in cc:
        if len(c) > max_cc:
            return False
    return True

# ── Gate 2: Python overlap analysis (fast approximation) ──────────────────────
def _slack(clue, length):
    if not clue:
        return length
    return max(0, length - (sum(clue) + len(clue) - 1))

def _forced_cells(clue, length):
    """Cells guaranteed filled by overlap logic for one line."""
    if not clue:
        return 0
    sl = _slack(clue, length)
    return sum(max(0, run - sl) for run in clue)

def _ambiguity(clue, length):
    """How many ways can the clue 'slide around' — higher = harder."""
    if not clue:
        return 0
    return _slack(clue, length) * len(clue)

def _python_score(rc, cc, rows, cols):
    """
    Fast Python approximation of the Prolog difficulty score.
    Returns (forced_ratio, ambiguity_total, approx_score 0–1).
    """
    total = rows * cols

    forced = (
        sum(_forced_cells(c, cols) for c in rc) +
        sum(_forced_cells(c, rows) for c in cc)
    ) / 2
    forced_ratio = forced / max(1, total)

    ambig = (
        sum(_ambiguity(c, cols) for c in rc) +
        sum(_ambiguity(c, rows) for c in cc)
    )

    # Fragmentation: avg groups per line
    all_clues = rc + cc
    avg_groups = sum(len(c) for c in all_clues) / max(1, len(all_clues))
    max_groups = min(cols, rows) / 2

    # Slack normalised
    all_slacks_r = [_slack(c, cols) for c in rc]
    all_slacks_c = [_slack(c, rows) for c in cc]
    avg_slack = (sum(all_slacks_r) + sum(all_slacks_c)) / max(1, rows + cols)
    norm_slack = min(1.0, avg_slack / max(1, max(cols, rows)))

    norm_groups = min(1.0, avg_groups / max(1, max_groups))
    approx_score = (1.0 - forced_ratio) * 0.5 + norm_slack * 0.3 + norm_groups * 0.2

    return forced_ratio, ambig, approx_score

def _gate2_python(rc, cc, rows, cols, diff):
    d = DIFFICULTY[diff]
    forced_ratio, ambig, approx_score = _python_score(rc, cc, rows, cols)

    # Must pass forced ratio and ambiguity checks
    if forced_ratio < d["min_forced"]:
        return False
    if ambig > d["max_ambig"]:
        return False

    # Score must be in an expanded band (Prolog will tighten it)
    margin = 0.10
    if approx_score < d["score_lo"] - margin:
        return False
    if approx_score > d["score_hi"] + margin:
        return False

    return True

# ── Gate 3: Prolog difficulty score ───────────────────────────────────────────
def _gate3_prolog_score(rc, cc, rows, cols, diff):
    """
    Calls puzzle_difficulty/5 in Prolog. No solving — pure arithmetic.
    Much faster than Gate 4 but more accurate than Python approximation.
    """
    d = DIFFICULTY[diff]
    with _prolog_lock:
        prolog = _get_prolog()
        try:
            q = f"puzzle_difficulty({rc},{cc},{rows},{cols},S)"
            results = list(prolog.query(q))
            if not results:
                return False
            score = float(results[0]["S"])
            return d["score_lo"] <= score <= d["score_hi"]
        except Exception:
            return False

# ── Gate 4: Prolog uniqueness (full solve) ────────────────────────────────────
def _gate4_unique(rc, cc):
    with _prolog_lock:
        prolog = _get_prolog()
        try:
            results = list(prolog.query(f"is_unique({rc},{cc})"))
            return bool(results)
        except Exception:
            return False

# ── Stats tracker for adaptive fill_prob ──────────────────────────────────────
class _AdaptiveSampler:
    """
    Tracks gate-pass rates and slightly nudges fill_prob when the generator
    is stuck, keeping search efficient across unusual grid sizes.
    """
    def __init__(self, base_prob, lo=0.15, hi=0.85):
        self.prob       = base_prob
        self.lo         = lo
        self.hi         = hi
        self._streak    = 0   # consecutive gate-2 failures
        self._direction = 0   # +1 denser, -1 sparser

    def nudge(self, gate2_passed):
        if gate2_passed:
            self._streak = 0
        else:
            self._streak += 1
            if self._streak > 30:
                # Alternate nudge direction to avoid getting stuck
                self._direction = 1 if self._streak % 60 < 30 else -1
                self.prob = max(self.lo, min(self.hi,
                    self.prob + self._direction * 0.03))

# ── Public generator ───────────────────────────────────────────────────────────
class PuzzleGenerator:
    """
    generate(rows, cols, difficulty, callback)
      → runs in daemon thread
      → calls callback(puzzle_dict) exactly once when a valid puzzle is found

    puzzle_dict keys:
      grid, row_clues, col_clues, rows, cols,
      difficulty, diff_name, attempts,
      g1_rejected, g2_rejected, g3_rejected, g4_rejected
    """

    def __init__(self):
        self.generating = False
        self.status     = "Idle"
        self._thread    = None

    def generate(self, rows, cols, difficulty, callback):
        if self.generating:
            return
        self.generating = True
        self.status = f"Generating {DIFFICULTY[difficulty]['name']} puzzle…"
        t = threading.Thread(
            target=self._run,
            args=(rows, cols, difficulty, callback),
            daemon=True,
        )
        t.start()
        self._thread = t

    def _run(self, rows, cols, difficulty, callback):
        d       = DIFFICULTY[difficulty]
        sampler = _AdaptiveSampler(d["fill_prob"])

        attempt = g1_rej = g2_rej = g3_rej = g4_rej = 0

        while True:
            attempt += 1
            if attempt % 25 == 0:
                self.status = (
                    f"Searching… attempt {attempt} "
                    f"(G1:{g1_rej} G2:{g2_rej} G3:{g3_rej} G4:{g4_rej})"
                )

            grid = _make_grid(rows, cols, sampler.prob)
            rc   = row_clues(grid)
            cc   = col_clues(grid)

            # Gate 1 — clue count rule (instant)
            if not _gate1_clue_counts(rc, cc, rows, cols):
                g1_rej += 1
                continue

            # Gate 2 — Python pre-filter (milliseconds)
            if not _gate2_python(rc, cc, rows, cols, difficulty):
                g2_rej += 1
                sampler.nudge(False)
                continue
            sampler.nudge(True)

            # Gate 3 — Prolog difficulty score (fast, no solving)
            if not _gate3_prolog_score(rc, cc, rows, cols, difficulty):
                g3_rej += 1
                continue

            # Gate 4 — Prolog uniqueness (slow, full solve)
            if not _gate4_unique(rc, cc):
                g4_rej += 1
                continue

            # ── All gates passed ──────────────────────────────────────────
            puzzle = {
                "grid":       grid,
                "row_clues":  rc,
                "col_clues":  cc,
                "rows":       rows,
                "cols":       cols,
                "difficulty": difficulty,
                "diff_name":  d["name"],
                "attempts":   attempt,
                "g1_rejected": g1_rej,
                "g2_rejected": g2_rej,
                "g3_rejected": g3_rej,
                "g4_rejected": g4_rej,
            }
            self.status = (
                f"Ready! {d['name']} — {attempt} attempts "
                f"(G1:{g1_rej} G2:{g2_rej} G3:{g3_rej} G4:{g4_rej})"
            )
            self.generating = False
            callback(puzzle)
            return