:- use_module(library(clpfd)).

%% solve_nonogram(+RowClues, +ColClues, -Solution)
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

%% is_unique(+RowClues, +ColClues)
is_unique(RowClues, ColClues) :-
    solve_nonogram(RowClues, ColClues, Sol1),
    !,
    \+ (
        solve_nonogram(RowClues, ColClues, Sol2),
        Sol2 \= Sol1
    ).
