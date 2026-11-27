"""The board and the features Q is computed from, shared by the bot and its trainer.

Nothing here imports `dedale`: the trainer (tools/train.py) builds a Board from
maze text and plays its own simulated games with exactly the same features the
bot uses in the competition.

An action is "take one step toward remaining point p". Q(s, p) = w . phi(s, p),
with phi below: how far p is, who wins the race to it, and what is left to
collect around it afterwards.
"""

from collections import deque

import numpy as np

FAR = 1 << 20  # Distance to a wall cell (never reached)
G1 = 0.9  # Slow decay: a point 10 steps away keeps 0.35 of its weight
G2 = 0.75  # Fast decay: only the next few steps count
STEPS = ((0, -1), (0, 1), (-1, 0), (1, 0))  # up, down, left, right
SWITCH_MARGIN = 0.02  # Q a new target must gain over last turn's to replace it
CANDIDATES = 16  # Points considered as targets each turn: the nearest ones
MAX_FIELD_CELLS = 3_000_000  # Points x cells beyond which the board is not built

FEATURES = [
    "bias",
    "near_slow",  # G1 ** d_me
    "near_fast",  # G2 ** d_me
    "dist",  # d_me / 20
    "win",  # I get there first, times G1 ** d_me
    "tie",  # we get there together (a split), times G1 ** d_me
    "lose",  # the opponent gets there first, times G1 ** d_me
    "margin",  # (d_opp - d_me) / 8, clipped to [-1, 1]
    "follow_mine",  # points after p I still reach first, decayed with distance from p
    "follow_theirs",  # points after p the opponent reaches first
    "follow_mine_now",  # follow_mine, decayed by the way to p too
    "neighbour",  # G1 ** distance from p to the nearest other point
    "opp_target",  # p is the opponent's nearest point
    "opp_target_lost",  # ... and it gets there first
    "left",  # share of the points still on the board
    "opp_near",  # G1 ** d_opp: how close the opponent is to p
    "cluster",  # points around p, quickly decayed
]
NF = len(FEATURES)


class Board:
    """The maze as cell numbers (y * width + x), with a distance field from every point."""

    def __init__(self, width, height, is_open, points):
        self.width, self.height = width, height
        n = width * height
        self.open = [is_open(i % width, i // width) for i in range(n)]
        self.adj = [[] for _ in range(n)]  # cell -> [(step index, next cell)]
        for c in range(n):
            if not self.open[c]:
                continue
            x, y = c % width, c // width
            for k, (dx, dy) in enumerate(STEPS):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and self.open[ny * width + nx]:
                    self.adj[c].append((k, ny * width + nx))
        self.points = sorted(points)  # point number -> (x, y)
        self.number = {p: i for i, p in enumerate(self.points)}
        self.pcell = np.array([y * width + x for x, y in self.points], dtype=np.int64)
        self.fields = len(self.points) * n <= MAX_FIELD_CELLS
        if self.fields:
            self.dist = np.array([self.bfs(c) for c in self.pcell.tolist()], dtype=np.int64)
            self.pp = self.dist[:, self.pcell]  # point-to-point distances
        self.total = len(self.points)

    def cell(self, pos):
        return pos[1] * self.width + pos[0]

    def bfs(self, start):
        dist = [FAR] * (self.width * self.height)
        dist[start] = 0
        queue = deque([start])
        adj = self.adj
        while queue:
            c = queue.popleft()
            d = dist[c] + 1
            for _, nc in adj[c]:
                if dist[nc] == FAR:
                    dist[nc] = d
                    queue.append(nc)
        return dist

    def step_toward(self, cell, point):
        """The step index of a shortest way from `cell` to point number `point`."""
        field = self.dist[point]
        want = field[cell] - 1
        for k, nc in self.adj[cell]:
            if field[nc] == want:
                return k
        return None


def features(board, left, me, opp):
    """Features of every candidate target.

    `left`: numbers of the points still on the board (numpy int array),
    `me`, `opp`: cells (opp None when alone). Returns (candidates, X): the
    candidate point numbers and one row of features for each.
    """
    k = len(left)
    d_me_all = board.dist[left, me].astype(np.float64)
    if opp is None:
        d_opp_all = np.full(k, float(FAR))
    else:
        d_opp_all = board.dist[left, opp].astype(np.float64)

    order = np.argsort(d_me_all, kind="stable")
    sel = order[:CANDIDATES]  # positions in `left`
    cand = left[sel]
    dm = d_me_all[sel]
    do = d_opp_all[sel]
    pp = board.pp[np.ix_(cand, left)].astype(np.float64)  # candidate -> every point left
    others = pp > 0  # leaves p itself out (points are distinct cells)

    win = dm < do
    tie = dm == do
    lose = dm > do
    near = G1 ** dm
    # After taking p, I reach q at d_me(p) + d(p, q); the opponent at d_opp(q).
    mine_after = (dm[:, None] + pp) < d_opp_all[None, :]
    decay = np.where(others, G1 ** pp, 0.0)
    follow_mine = (decay * mine_after).sum(1)
    follow_theirs = (decay * ~mine_after).sum(1)
    nearest_other = np.where(others, pp, np.inf).min(1) if k > 1 else np.full(len(cand), np.inf)

    f = {
        "bias": 1.0,
        "near_slow": near,
        "near_fast": G2 ** dm,
        "dist": dm / 20.0,
        "win": win * near,
        "tie": tie * near,
        "lose": lose * near,
        "margin": np.clip((do - dm) / 8.0, -1.0, 1.0),
        "follow_mine": follow_mine / 4.0,
        "follow_theirs": follow_theirs / 4.0,
        "follow_mine_now": follow_mine * near / 4.0,
        "neighbour": np.where(np.isfinite(nearest_other),
                              G1 ** np.minimum(nearest_other, 1e3), 0.0),
        "opp_target": 0.0,
        "opp_target_lost": 0.0,
        "left": k / max(board.total, 1),
        "opp_near": 0.0,
        "cluster": np.where(others, G2 ** pp, 0.0).sum(1) / 2.0,
    }
    if opp is not None:
        is_target = cand == left[int(np.argmin(d_opp_all))]
        f["opp_target"] = is_target
        f["opp_target_lost"] = is_target & lose
        f["opp_near"] = G1 ** np.minimum(do, 1e3)
    X = np.empty((len(cand), NF))
    for j, name in enumerate(FEATURES):
        X[:, j] = f[name]
    return cand, X


def choose(cand, q, prev):
    """The index of the target to take: the best on Q, but last turn's target
    stays unless another beats it by SWITCH_MARGIN (two targets of nearly the
    same value would otherwise swap every step, walking back and forth)."""
    best = int(np.argmax(q))
    kept = np.flatnonzero(cand == prev)
    if len(kept) and q[best] < q[kept[0]] + SWITCH_MARGIN:
        return int(kept[0])
    return best


class Chooser:
    """Picks the target each turn, and breaks loops.

    Against an opponent that reacts to it, two targets can trade places as
    the opponent moves, and both players walk the same cycle until the turn
    limit. A cycle shows as a state seen before (my cell, the opponent's
    cell, the points left): from then on the current target is kept until it
    is collected.
    """

    def __init__(self):
        self.target = -1  # point number aimed at last turn
        self.locked = False
        self.seen = set()

    def pick(self, cand, q, left, me, opp, explore=None):
        """The target point number; `explore` (a candidate index) overrides Q."""
        alive = self.target >= 0 and bool((left == self.target).any())
        state = (me, opp, len(left))
        if not alive:
            self.locked = False
        elif state in self.seen:
            self.locked = True
        self.seen.add(state)
        if not self.locked:
            a = explore if explore is not None else choose(cand, q, self.target)
            self.target = int(cand[a])
        return self.target
