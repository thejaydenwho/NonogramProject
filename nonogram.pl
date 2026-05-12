:- use_module(library(clpfd)).
:- use_module(library(aggregate)).

%% ── Core solver ───────────────────────────────────────────────────────────────
solve_nonogram(RowClues, ColClues, Solution) :-
    length(RowClues, NRows),
    length(ColClues, NCols),
    length(Solution, NRows),
    maplist(length_list(NCols), Solution),
    maplist(line_clues, Solution, RowClues),
    transpose(Solution, Transposed),
    maplist(line_clues, Transposed, ColClues),
    maplist(label, Solution).

length_list(N, L) :- length(L, N).

%% ── Line constraint engine ────────────────────────────────────────────────────
line_clues(Line, Clues) :-
    Line ins 0..1,
    apply_clues(Line, Clues).

apply_clues(Line, []) :-
    maplist(=(0), Line).
apply_clues([], []).
apply_clues(Line, [C|Rest]) :-
    integer(C), C > 0,
    append(Zeros, Remainder, Line),
    maplist(=(0), Zeros),
    length(Run, C),
    maplist(=(1), Run),
    append(Run, After, Remainder),
    (   Rest = []
    ->  maplist(=(0), After)
    ;   After = [0|Tail],
        apply_clues(Tail, Rest)
    ).

%% ── Uniqueness check ──────────────────────────────────────────────────────────
is_unique(RowClues, ColClues) :-
    solve_nonogram(RowClues, ColClues, Sol1),
    !,
    \+ (
        solve_nonogram(RowClues, ColClues, Sol2),
        Sol2 \= Sol1
    ).

%% ── Count solutions up to Max (for difficulty scoring) ───────────────────────
count_solutions(RowClues, ColClues, Max, Count) :-
    findnsols(Max, _, solve_nonogram(RowClues, ColClues, _), Sols),
    length(Sols, Count).

%% ── Forced-cell ratio via overlap analysis ────────────────────────────────────
%% forced_overlap(+Clue, +LineLen, -ForcedCount)
%% Counts cells forced by the standard overlap technique for one line.
forced_overlap([], _, 0).
forced_overlap(Clue, Len, Forced) :-
    Clue \= [],
    sumlist(Clue, S),
    length(Clue, N),
    MinSpace is S + N - 1,
    Slack is max(0, Len - MinSpace),
    aggregate_all(sum(F), (member(R, Clue), F is max(0, R - Slack)), Forced).

%% puzzle_forced_ratio(+RowClues, +ColClues, +NRows, +NCols, -Ratio)
puzzle_forced_ratio(RowClues, ColClues, NRows, NCols, Ratio) :-
    Total is NRows * NCols,
    aggregate_all(sum(F),
        (member(RC, RowClues), forced_overlap(RC, NCols, F)), RowForced),
    aggregate_all(sum(F),
        (member(CC, ColClues), forced_overlap(CC, NRows, F)), ColForced),
    Combined is (RowForced + ColForced) / 2,
    Ratio is Combined / max(1, Total).

%% ── Difficulty score (0.0 easy → 1.0 hard) ───────────────────────────────────
%% Based on: forced ratio (inverted), clue fragmentation, slack
puzzle_difficulty(RowClues, ColClues, NRows, NCols, Score) :-
    puzzle_forced_ratio(RowClues, ColClues, NRows, NCols, FR),
    %% Fragmentation: avg number of clue groups per line
    length(RowClues, NRows),
    aggregate_all(sum(N), (member(RC, RowClues), length(RC, N)), RSum),
    aggregate_all(sum(N), (member(CC, ColClues), length(CC, N)), CSum),
    TotalLines is NRows + NCols,
    AvgGroups is (RSum + CSum) / max(1, TotalLines),
    %% Slack: avg slack per line
    aggregate_all(sum(Sl),
        (member(RC, RowClues), RC \= [],
         sumlist(RC, S), length(RC, N),
         Sl is max(0, NCols - (S + N - 1))), RSlack),
    aggregate_all(sum(Sl),
        (member(CC, ColClues), CC \= [],
         sumlist(CC, S), length(CC, N),
         Sl is max(0, NRows - (S + N - 1))), CSlack),
    AvgSlack is (RSlack + CSlack) / max(1, TotalLines),
    MaxSlack is max(NCols, NRows),
    NormSlack is min(1.0, AvgSlack / max(1, MaxSlack)),
    %% Combine: high forced_ratio = easy, high slack = hard, high groups = hard
    MaxGroups is min(NCols, NRows) / 2,
    NormGroups is min(1.0, AvgGroups / max(1, MaxGroups)),
    Score is (1.0 - FR) * 0.5 + NormSlack * 0.3 + NormGroups * 0.2.
