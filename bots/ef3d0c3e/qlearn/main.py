"""Q-Learner: picks its target with a Q-function learned by Q-learning.

An action is "step toward remaining point p". Q(s, p) = w . phi(s, p) is
linear in hand-made features (qfeatures.py): how far p is, who wins the race
to it, which points it leads on to. The weights were learned offline by
Q-learning over simulated games (tools/train.py) and are loaded from
weights.json; in a game the bot only plays greedily on Q. Duo and solo have
their own weights.
"""

import json
from collections import deque
from pathlib import Path

import numpy as np

import dedale
from dedale import Move

import qfeatures as qf

NAME = "Q-Learner"
AUTHOR = "ef3d0c3e"
DESCRIPTION = ("Chooses its target point with a linear Q-function over race and "
               "cluster features, learned offline by Q-learning against greedy, "
               "racing and self-play opponents.")
VERSION = 1

MOVES = (Move.UP, Move.DOWN, Move.LEFT, Move.RIGHT)  # qfeatures.STEPS order

board = None
weights = None
chooser = qf.Chooser()


def init():
    global board, weights
    data = json.loads((Path(__file__).parent / "weights.json").read_text())
    if data["features"] != qf.FEATURES:
        raise ValueError("weights.json does not match qfeatures.FEATURES")
    weights = np.array(data["duo" if dedale.opponent is not None else "solo"])
    maze = dedale.maze
    board = qf.Board(maze.width, maze.height, maze.is_open, dedale.points)


def move():
    if not dedale.points:
        return Move.STAY
    if board is None or not board.fields:
        return greedy()
    me = board.cell(dedale.me.pos)
    opp = board.cell(dedale.opponent.pos) if dedale.opponent is not None else None
    left = np.array(sorted(board.number[p] for p in dedale.points), dtype=np.int64)
    cand, X = qf.features(board, left, me, opp)
    q = X @ weights
    target = chooser.pick(cand, q, left, me, opp)
    row = np.flatnonzero(cand == target)
    value = f"Q={q[row[0]]:.2f}" if len(row) else "kept"
    dedale.mark([board.points[target]], label=f"target {value}{' (loop: kept)' if chooser.locked else ''}",
                color="pink")
    k = board.step_toward(me, target)
    return MOVES[k] if k is not None else Move.STAY


def greedy():
    """Breadth-first walk to the nearest point, for boards too big to precompute."""
    start = dedale.me.pos
    first = {start: None}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        if cell in dedale.points:
            return first[cell] or Move.STAY
        for step, nxt in dedale.maze.neighbors(*cell):
            if nxt not in first:
                first[nxt] = first[cell] or step
                queue.append(nxt)
    return Move.STAY
