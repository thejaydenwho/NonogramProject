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
import signal

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
        "fill_prob":   0.5,       # dense → long runs → high overlap
        "score_lo":    0.00,
        "score_hi":    0.25,
        # Python pre-filter mirrors (fast approximation of Prolog score)
        "min_forced":  0.48,       # high forced ratio = easy
        "max_ambig":   35,
    },
    2: {
        "name":        "Medium",
        "fill_prob":   0.45,
        "score_lo":    0.25,
        "score_hi":    0.50,
        "min_forced":  0.22,
        "max_ambig":   90,
    },
    3: {
        "name":        "Difficult",
        "fill_prob":   0.4,
        "score_lo":    0.50,
        "score_hi":    0.75,
        "min_forced":  0.05,
        "max_ambig":   200,
    },
    4: {
        "name":        "Extreme",
        "fill_prob":   0.35,
        "score_lo":    0.75,
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
def _random_clue_list(length, fill_prob):
    if random.random() < 0.05:
        return []
    if random.random() < 0.05:
        return [length]

    target_filled = int(round(random.gauss(fill_prob * length, max(1, length * 0.10))))
    target_filled = max(0, min(length, target_filled))
    if target_filled == 0:
        return []
    if target_filled == length:
        return [length]

    max_runs = min(target_filled, max(1, length // 2))
    avg_runs = max(1, int(math.ceil(fill_prob * length / 3)))
    runs = random.randint(1, min(max_runs, avg_runs + 1))
    runs = min(runs, target_filled)

    run_lengths = [1] * runs
    remaining = target_filled - runs
    for _ in range(remaining):
        run_lengths[random.randrange(runs)] += 1
    random.shuffle(run_lengths)
    return run_lengths


def _row_from_clues(length, clues):
    if not clues:
        return [0] * length
    if sum(clues) + len(clues) - 1 >= length:
        pattern = []
        for idx, run in enumerate(clues):
            pattern.extend([1] * run)
            if idx < len(clues) - 1:
                pattern.append(0)
        if len(pattern) < length:
            pattern.extend([0] * (length - len(pattern)))
        return pattern[:length]

    gaps = [0] * (len(clues) + 1)
    available = length - sum(clues) - (len(clues) - 1)
    for _ in range(available):
        gaps[random.randrange(len(gaps))] += 1

    pattern = []
    for idx, run in enumerate(clues):
        pattern.extend([0] * gaps[idx])
        pattern.extend([1] * run)
        if idx < len(clues) - 1:
            pattern.append(0)
    pattern.extend([0] * gaps[-1])
    if len(pattern) < length:
        pattern.extend([0] * (length - len(pattern)))
    return pattern[:length]


def _random_row_pattern(length, fill_prob):
    return _row_from_clues(length, _random_clue_list(length, fill_prob))


def _count_runs(line):
    runs = 0
    prev = 0
    for cell in line:
        if cell and not prev:
            runs += 1
        prev = cell
    return runs


def _partial_column_ok(prefix, rows, fill_prob):
    filled = sum(prefix)
    runs = _count_runs(prefix)
    remaining = rows - len(prefix)
    if runs > rows // 2:
        return False
    if remaining == 0:
        return True

    open_run = bool(prefix and prefix[-1] == 1)
    finished_runs = runs - 1 if open_run else runs
    max_extra_runs = (remaining + 1) // 2 if not open_run else 1 + (remaining - 1 + 1) // 2
    if finished_runs + max_extra_runs > rows // 2:
        return False

    expected_fill = fill_prob * rows
    if filled > expected_fill + remaining + 1:
        return False
    if filled + remaining < expected_fill - 1:
        return False

    if len(prefix) >= max(3, rows // 4):
        frac = filled / len(prefix)
        if frac < max(0.0, fill_prob - 0.30) or frac > min(1.0, fill_prob + 0.30):
            return False
    return True


def _build_grid_by_rows(rows, cols, fill_prob):
    for _ in range(20):
        grid = []
        for _ in range(rows):
            row_tries = 0
            while row_tries < 10:
                row = _random_row_pattern(cols, fill_prob)
                grid.append(row)
                if all(
                    _partial_column_ok([grid[r][c] for r in range(len(grid))], rows, fill_prob)
                    for c in range(cols)
                ):
                    break
                grid.pop()
                row_tries += 1
            else:
                break
        if len(grid) == rows:
            return grid
    return None


def _make_grid(rows, cols, fill_prob):
    grid = _build_grid_by_rows(rows, cols, fill_prob)
    if grid is not None:
        return grid
    return [_random_row_pattern(cols, fill_prob) for _ in range(rows)]

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
_pattern_count_cache = {}

def _slack(clue, length):
    if not clue:
        return length
    return max(0, length - (sum(clue) + len(clue) - 1))

def _pattern_count(clue, length):
    if not clue:
        return 1
    key = (tuple(clue), length)
    if key in _pattern_count_cache:
        return _pattern_count_cache[key]
    sl = _slack(clue, length)
    count = math.comb(sl + len(clue), len(clue))
    _pattern_count_cache[key] = count
    return count

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

    row_pattern_logs = [math.log1p(_pattern_count(c, cols)) for c in rc]
    col_pattern_logs = [math.log1p(_pattern_count(c, rows)) for c in cc]
    avg_log_patterns = (
        sum(row_pattern_logs) + sum(col_pattern_logs)
    ) / max(1, rows + cols)
    norm_pattern = min(1.0, avg_log_patterns / 10.0)

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
    approx_score = (
        (1.0 - forced_ratio) * 0.45 +
        norm_slack * 0.25 +
        norm_groups * 0.2 +
        norm_pattern * 0.1
    )

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
    # For larger grids, tighten the margins to filter more aggressively
    # For harder difficulties, tighten even more
    grid_size = rows * cols
    if diff >= 3:  # Difficult or Extreme — very tight filtering
        if grid_size <= 25:
            margin = 0.10
        elif grid_size <= 49:
            margin = 0.08
        else:
            margin = 0.05
    else:  # Easy or Medium
        if grid_size <= 25:
            margin = 0.20
        elif grid_size <= 49:
            margin = 0.15
        else:
            margin = 0.10
    
    if approx_score < d["score_lo"] - margin:
        return False
    if approx_score > d["score_hi"] + margin:
        return False

    return True

# ── Gate 2.5: Quick Python solve (fast reject before Prolog uniqueness) ───────
def _gate2_5_quick_solve(grid, rc, cc, rows, cols, diff):
    """Use a fast Python solve to filter candidates before expensive Prolog uniqueness."""
    try:
        from solver import solve_steps
    except ImportError:
        return True

    max_steps = min(1200, 70 * diff + rows * cols * 2)
    last_board = None
    for info in solve_steps(rc, cc):
        if info["step"] > max_steps:
            return False
        last_board = info["board"]
    if last_board is None:
        return False
    return last_board == grid

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
def _gate4_unique(rc, cc, timeout_ms=1000):
    """
    Check uniqueness with adaptive timeout.
    Returns False if check times out (treat as unique=False to skip this candidate).
    timeout_ms scales adaptively: larger puzzles get shorter timeouts.
    """
    with _prolog_lock:
        prolog = _get_prolog()
        try:
            # Use call_with_time_limit for timeout support
            query = f"call_with_time_limit({timeout_ms / 1000}, is_unique({rc},{cc}))"
            results = list(prolog.query(query))
            return bool(results)
        except Exception:
            # Timeout or error — reject this candidate
            # This includes cases where call_with_time_limit isn't available
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
        self.found      = False
        self._threads   = []

    def generate(self, rows, cols, difficulty, callback):
        if self.generating:
            return
        self.generating = True
        self.found = False
        self.status = f"Generating {DIFFICULTY[difficulty]['name']} puzzle…"
        # Scale thread count: larger puzzles + harder difficulties = more threads
        grid_size = rows * cols
        base_threads = 3 if grid_size < 36 else 5 if grid_size < 64 else 8
        # Difficult & Extreme get 50% more threads
        difficulty_multiplier = 1.5 if difficulty >= 3 else 1.0
        num_threads = max(base_threads, int(base_threads * difficulty_multiplier))
        self._threads = []
        for _ in range(num_threads):
            t = threading.Thread(
                target=self._run,
                args=(rows, cols, difficulty, callback),
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def _run(self, rows, cols, difficulty, callback):
        d       = DIFFICULTY[difficulty]
        sampler = _AdaptiveSampler(d["fill_prob"])

        attempt = g1_rej = g2_rej = g3_rej = g3a_rej = g4_rej = 0
        update_interval = 5  # Update status every 5 attempts for real-time feedback
        
        # Adaptive timeout for Gate 4: larger puzzles + harder difficulties = shorter timeouts
        grid_size = rows * cols
        is_hard = difficulty >= 3  # Difficult or Extreme
        
        # Skip Gate 3 at lower threshold for hard difficulties
        skip_gate3 = (grid_size > 100) or (is_hard and grid_size > 49)
        
        # Base timeout by grid size
        if grid_size <= 25:
            gate4_timeout_ms = 2000
        elif grid_size <= 49:
            gate4_timeout_ms = 1500
        elif grid_size <= 64:
            gate4_timeout_ms = 1000
        elif grid_size <= 100:
            gate4_timeout_ms = 800
        else:
            gate4_timeout_ms = 600
        
        # Reduce timeout for hard difficulties (they have more candidates to check)
        if is_hard:
            gate4_timeout_ms = int(gate4_timeout_ms * 0.7)

        while True:
            if self.found:
                return
            attempt += 1
            if attempt % update_interval == 0:
                self.status = (
                    f"Searching… attempt {attempt} "
                    f"(G1:{g1_rej} G2:{g2_rej} G3:{g3_rej} G3a:{g3a_rej} G4:{g4_rej})"
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

            # Gate 3 — Prolog difficulty score (skip for very large grids or hard difficulties)
            if not skip_gate3:
                if not _gate3_prolog_score(rc, cc, rows, cols, difficulty):
                    g3_rej += 1
                    continue

            # Gate 2.5 — quick Python solve before Prolog uniqueness
            if not _gate2_5_quick_solve(grid, rc, cc, rows, cols, difficulty):
                g3a_rej += 1
                continue

            # Gate 4 — Prolog uniqueness (slow, full solve with adaptive timeout)
            if not _gate4_unique(rc, cc, timeout_ms=gate4_timeout_ms):
                g4_rej += 1
                continue

            # ── All gates passed ──────────────────────────────────────────
            if not self.found:
                self.found = True
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
                    "g3a_rejected": g3a_rej,
                    "g4_rejected": g4_rej,
                }
                self.status = (
                    f"Ready! {d['name']} — {attempt} attempts "
                    f"(G1:{g1_rej} G2:{g2_rej} G3:{g3_rej} G3a:{g3a_rej} G4:{g4_rej})"
                )
                self.generating = False
                callback(puzzle)
            return