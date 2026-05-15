import copy

UNKNOWN = -1
EMPTY = 0
FILLED = 1

_pattern_cache = {}


def generate_line_patterns(length, clues):
    """Generate every legal line pattern for a clue list and line length."""
    key = (length, tuple(clues))
    if key in _pattern_cache:
        return _pattern_cache[key]

    patterns = []

    def backtrack(pos, clue_index, current):
        if clue_index == len(clues):
            tail = [EMPTY] * (length - len(current))
            patterns.append(tuple(current + tail))
            return

        run = clues[clue_index]
        remaining_runs = sum(clues[clue_index + 1 :])
        remaining_separators = len(clues) - clue_index - 1
        max_start = length - run - remaining_runs - remaining_separators

        for start in range(pos, max_start + 1):
            next_line = current + [EMPTY] * (start - len(current)) + [FILLED] * run
            if clue_index < len(clues) - 1:
                next_line.append(EMPTY)
            next_pos = len(next_line)
            backtrack(next_pos, clue_index + 1, next_line)

    if not clues:
        patterns.append(tuple([EMPTY] * length))
    else:
        backtrack(0, 0, [])

    _pattern_cache[key] = patterns
    return patterns


def line_matches(known, pattern):
    for k, p in zip(known, pattern):
        if k == UNKNOWN:
            continue
        if k != p:
            return False
    return True


def consensus_from_patterns(patterns):
    if not patterns:
        return []
    length = len(patterns[0])
    consensus = []
    for i in range(length):
        first = patterns[0][i]
        if all(pattern[i] == first for pattern in patterns):
            consensus.append(first)
        else:
            consensus.append(UNKNOWN)
    return consensus


class StepSolver:
    def __init__(self, row_clues, col_clues, player_board=None):
        self.row_clues = row_clues
        self.col_clues = col_clues
        self.rows = len(row_clues)
        self.cols = len(col_clues)

        self.board = [
            [UNKNOWN] * self.cols
            for _ in range(self.rows)
        ]
        if player_board is not None:
            for r in range(min(self.rows, len(player_board))):
                for c in range(min(self.cols, len(player_board[r]))):
                    if player_board[r][c] == 1:
                        self.board[r][c] = FILLED

        self.possible_rows = [
            generate_line_patterns(self.cols, clues)
            for clues in self.row_clues
        ]
        self.possible_cols = [
            generate_line_patterns(self.rows, clues)
            for clues in self.col_clues
        ]

        self._queue = [("row", r) for r in range(self.rows)] + [("col", c) for c in range(self.cols)]
        self._step = 0
        self._done = False
        self.solved = False
        self.stuck = False

    def _board_line(self, line_type, index):
        if line_type == "row":
            return list(self.board[index])
        return [self.board[r][index] for r in range(self.rows)]

    def _set_board_cell(self, r, c, value):
        self.board[r][c] = value

    def _filter_patterns(self, patterns, known):
        return [p for p in patterns if line_matches(known, p)]

    def _queue_opposite(self, line_type, r, c):
        if line_type == "row":
            self._queue.append(("col", c))
        else:
            self._queue.append(("row", r))

    def _snapshot(self):
        return {
            "board": copy.deepcopy(self.board),
            "possible_rows": copy.deepcopy(self.possible_rows),
            "possible_cols": copy.deepcopy(self.possible_cols),
            "queue": copy.deepcopy(self._queue),
            "step": self._step,
            "done": self._done,
            "solved": self.solved,
            "stuck": self.stuck,
        }

    def _restore(self, snap):
        self.board = copy.deepcopy(snap["board"])
        self.possible_rows = copy.deepcopy(snap["possible_rows"])
        self.possible_cols = copy.deepcopy(snap["possible_cols"])
        self._queue = copy.deepcopy(snap["queue"])
        self._step = snap["step"]
        self._done = snap["done"]
        self.solved = snap["solved"]
        self.stuck = snap["stuck"]

    def _unknown_cells(self):
        for r in range(self.rows):
            for c in range(self.cols):
                if self.board[r][c] == UNKNOWN:
                    yield r, c

    def _valid_values_for_cell(self, r, c):
        row_known = self._board_line("row", r)
        col_known = self._board_line("col", c)
        row_patterns = self._filter_patterns(self.possible_rows[r], row_known)
        col_patterns = self._filter_patterns(self.possible_cols[c], col_known)
        if not row_patterns or not col_patterns:
            return []
        row_values = {p[c] for p in row_patterns}
        col_values = {p[r] for p in col_patterns}
        return sorted(row_values & col_values)

    def _set_cell(self, r, c, value):
        self.board[r][c] = value
        self._queue.append(("row", r))
        self._queue.append(("col", c))

    def __iter__(self):
        return self

    def __next__(self):
        if self._done:
            raise StopIteration

        while self._queue:
            line_type, index = self._queue.pop(0)
            known = self._board_line(line_type, index)
            patterns = self.possible_rows[index] if line_type == "row" else self.possible_cols[index]
            filtered = self._filter_patterns(patterns, known)

            if not filtered:
                self._done = True
                self.stuck = True
                raise StopIteration

            if len(filtered) != len(patterns):
                if line_type == "row":
                    self.possible_rows[index] = filtered
                else:
                    self.possible_cols[index] = filtered

            consensus = consensus_from_patterns(filtered)
            changes = []
            for pos, value in enumerate(consensus):
                if value == UNKNOWN:
                    continue
                if known[pos] == UNKNOWN:
                    if line_type == "row":
                        r, c = index, pos
                    else:
                        r, c = pos, index
                    self._set_board_cell(r, c, value)
                    changes.append((r, c, value))

            if changes:
                self._step += 1
                for r, c, _ in changes:
                    self._queue_opposite(line_type, r, c)
                return {
                    "board": [list(row) for row in self.board],
                    "changed": changes,
                    "step": self._step,
                    "line_type": line_type,
                    "line_index": index,
                }

        self._done = True
        self.solved = all(cell != UNKNOWN for row in self.board for cell in row)
        raise StopIteration


def solve_steps(row_clues, col_clues, player_board=None):
    solver = StepSolver(row_clues, col_clues, player_board)
    yield {
        "board": [list(row) for row in solver.board],
        "changed": [],
        "step": 0,
        "line_type": None,
        "line_index": None,
        "guess": False,
    }

    guess_stack = []
    current_iter = iter(solver)

    while True:
        try:
            step = next(current_iter)
            step["guess"] = False
            yield step
            continue
        except StopIteration:
            if solver.solved:
                return
            if solver.stuck:
                while guess_stack:
                    snapshot, guess_options, guess_index, guess_cell = guess_stack.pop()
                    if guess_index + 1 >= len(guess_options):
                        continue
                    solver._restore(snapshot)
                    next_value = guess_options[guess_index + 1]
                    guess_stack.append((snapshot, guess_options, guess_index + 1, guess_cell))
                    solver._set_cell(*guess_cell, next_value)
                    solver._step += 1
                    current_iter = iter(solver)
                    yield {
                        "board": [list(row) for row in solver.board],
                        "changed": [(guess_cell[0], guess_cell[1], next_value)],
                        "step": solver._step,
                        "line_type": "guess",
                        "line_index": None,
                        "guess": True,
                    }
                    break
                else:
                    return
                continue

            unknowns = list(solver._unknown_cells())
            if not unknowns:
                return

            best = None
            best_options = None
            deduced = None

            for cell in unknowns:
                values = solver._valid_values_for_cell(*cell)
                if not values:
                    solver.stuck = True
                    break
                if len(values) == 1:
                    deduced = (cell, values[0])
                    break
                if best is None or len(values) < len(best_options):
                    best = cell
                    best_options = values

            if solver.stuck:
                continue

            if deduced is not None:
                cell, value = deduced
                solver._set_cell(cell[0], cell[1], value)
                solver._step += 1
                current_iter = iter(solver)
                yield {
                    "board": [list(row) for row in solver.board],
                    "changed": [(cell[0], cell[1], value)],
                    "step": solver._step,
                    "line_type": "deduce",
                    "line_index": None,
                    "guess": False,
                }
                continue

            if best is None:
                return

            guess_cell = best
            guess_options = best_options
            snapshot = solver._snapshot()
            guess_stack.append((snapshot, guess_options, 0, guess_cell))
            solver._set_cell(*guess_cell, guess_options[0])
            solver._step += 1
            current_iter = iter(solver)
            yield {
                "board": [list(row) for row in solver.board],
                "changed": [(guess_cell[0], guess_cell[1], guess_options[0])],
                "step": solver._step,
                "line_type": "guess",
                "line_index": None,
                "guess": True,
            }
            continue
