"""Trains the Q-Learner's weights by Q-learning on simulated games.

Q(s, p) = w . phi(s, p), phi from ../qfeatures.py (the bot's own features).
Each turn a learner picks a target point epsilon-greedily on Q and steps
toward it; the reward is the points it collected that turn minus the
opponent's (solo: its points). After each turn

    w += alpha * (r + gamma * max_p' Q(s', p') - Q(s, p)) * phi(s, p)

Duo games are played against a mix of opponents: greedy (nearest point),
racer (nearest point it reaches first) and the learner itself (self-play,
both sides learning). Every --eval-every games the greedy policy on Q
(epsilon 0) plays a fixed set of held-out mazes against greedy and racer;
the best weights so far are written to --out.

The simulator follows the referee's rules: simultaneous moves, a point both
players step on in the same turn is split, the game ends when the points are
gone or at 4 * W * H turns. Mazes come from the `dedale` binary (`dedale
maze --seed`), so they are the competition's kind.

Needs numpy and an extracted Dedale release: DEDALE (the binary) or the
release extracted at the repository root.

Usage, from the bot's folder:
  python3 tools/train.py --games 20000 --out weights.json
  python3 tools/train.py --eval-only --weights weights.json
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import qfeatures as qf  # noqa: E402

DEDALE = os.environ.get(
    "DEDALE", str(HERE.parents[3] / "dedale-x86_64-unknown-linux-musl" / "dedale"))


def gen_maze(seed, size="31x31", loops=80, points=40):
    out = subprocess.run(
        [DEDALE, "maze", "--size", size, "--loops", str(loops), "--points", str(points),
         "--seed", seed], capture_output=True, text=True, check=True)
    rows = out.stdout.strip("\n").split("\n")
    h, w = len(rows), len(rows[0])
    pts = [(x, y) for y, r in enumerate(rows) for x, c in enumerate(r) if c == "."]
    return qf.Board(w, h, lambda x, y: rows[y][x] != "#", pts)


# --- Policies: (board, left, me, opp) -> step index or None ---------------

def greedy(board, left, me, opp, rng):
    d = board.dist[left, me]
    return board.step_toward(me, int(left[int(np.argmin(d))]))


def racer(board, left, me, opp, rng):
    d = board.dist[left, me]
    do = board.dist[left, opp] if opp is not None else d + 1
    ahead = d <= do
    if ahead.any():
        d = np.where(ahead, d, qf.FAR)
    return board.step_toward(me, int(left[int(np.argmin(d))]))


class QAgent:
    """Picks targets epsilon-greedily on Q; learns when `learn` is set."""

    def __init__(self, w, eps=0.0, learn=False, alpha=0.0, gamma=0.97):
        self.w, self.eps, self.learn = w, eps, learn
        self.alpha, self.gamma = alpha, gamma
        self.prev = None  # features of the action taken last turn
        self.chooser = qf.Chooser()
        self.reward = 0.0

    def __call__(self, board, left, me, opp, rng):
        cand, X = qf.features(board, left, me, opp)
        q = X @ self.w
        if self.learn and self.prev is not None:
            self.update(self.reward + self.gamma * q.max())
        explore = rng.randrange(len(cand)) if self.eps and rng.random() < self.eps else None
        target = self.chooser.pick(cand, q, left, me, opp, explore)
        row = np.flatnonzero(cand == target)
        # A locked target may have left the candidates: no features, no update.
        self.prev = X[row[0]].copy() if len(row) else None
        self.reward = 0.0
        return board.step_toward(me, target)

    def update(self, target):
        delta = target - self.prev @ self.w
        self.w += self.alpha * float(np.clip(delta, -2.0, 2.0)) * self.prev

    def finish(self):
        if self.learn and self.prev is not None:
            self.update(self.reward)
        self.prev = None


def play(board, policies, swap, rng):
    """Plays one game; returns (turns, scores). Rewards go to QAgents as it runs."""
    w, h = board.width, board.height
    starts = [0, (h - 1) * w + (w - 1)]
    if swap:
        starts.reverse()
    pos = starts[:len(policies)]
    alive = np.ones(board.total, dtype=bool)
    cell_point = {int(c): i for i, c in enumerate(board.pcell)}
    scores = [0.0] * len(policies)
    duo = len(policies) == 2
    turn, max_turns = 0, 4 * w * h
    while alive.any() and turn < max_turns:
        turn += 1
        left = np.flatnonzero(alive)
        nxt = []
        for i, pol in enumerate(policies):
            opp = pos[1 - i] if duo else None
            k = pol(board, left, pos[i], opp, rng)
            to = pos[i]
            if k is not None:
                for kk, nc in board.adj[pos[i]]:
                    if kk == k:
                        to = nc
            nxt.append(to)
        gains = [0.0] * len(policies)
        if duo and nxt[0] == nxt[1] and nxt[0] in cell_point and alive[cell_point[nxt[0]]]:
            alive[cell_point[nxt[0]]] = False
            gains = [0.5, 0.5]
        else:
            for i, c in enumerate(nxt):
                p = cell_point.get(c)
                if p is not None and alive[p]:
                    alive[p] = False
                    gains[i] = 1.0
        for i, pol in enumerate(policies):
            scores[i] += gains[i]
            if isinstance(pol, QAgent):
                pol.reward += gains[i] - gains[1 - i] if duo else gains[i]
        pos = nxt
    for pol in policies:
        if isinstance(pol, QAgent):
            pol.finish()
    return turn, scores


def evaluate(w, boards, opponents, rng):
    """Point share of the greedy-on-Q policy against each opponent, and solo turns."""
    res = {}
    for name, opp in opponents.items():
        mine = theirs = 0.0
        wins = losses = 0
        for b in boards:
            for swap in (False, True):
                _, (a, o) = play(b, [QAgent(w), opp], swap, rng)
                mine += a
                theirs += o
                wins += a > o
                losses += a < o
        res[name] = (mine / (mine + theirs), wins, losses)
    return res


def evaluate_solo(w, boards, rng):
    return sum(play(b, [QAgent(w)], False, rng)[0] for b in boards)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20000)
    ap.add_argument("--solo-share", type=float, default=0.2, help="share of training games alone")
    ap.add_argument("--alpha", type=float, default=0.01)
    ap.add_argument("--alpha-end", type=float, default=0.001)
    ap.add_argument("--gamma", type=float, default=0.97)
    ap.add_argument("--eps", type=float, default=0.15)
    ap.add_argument("--eps-end", type=float, default=0.02)
    ap.add_argument("--mix", default="greedy:0.3,racer:0.3,self:0.4")
    ap.add_argument("--maze-pool", type=int, default=2000, help="distinct training mazes")
    ap.add_argument("--eval-mazes", type=int, default=30)
    ap.add_argument("--eval-every", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--weights", help="start from these weights")
    ap.add_argument("--out", default=str(HERE.parent / "weights.json"))
    ap.add_argument("--eval-only", action="store_true")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    eval_boards = [gen_maze(f"e{args.seed:03x}{i:012x}") for i in range(args.eval_mazes)]
    opponents = {"greedy": greedy, "racer": racer}

    if args.weights:
        data = json.loads(Path(args.weights).read_text())
        assert data["features"] == qf.FEATURES, "weights were trained on other features"
        w_duo, w_solo = np.array(data["duo"]), np.array(data["solo"])
    else:
        # Start as greedy: Q grows as the nearest point gets nearer.
        w_duo = np.zeros(qf.NF)
        w_duo[qf.FEATURES.index("near_slow")] = 1.0
        w_solo = w_duo.copy()

    def report(tag):
        r = evaluate(w_duo, eval_boards, opponents, rng)
        solo = evaluate_solo(w_solo, eval_boards[:10], rng)
        line = "  ".join(f"{k} {s:.3f} ({wn}-{ls})" for k, (s, wn, ls) in r.items())
        print(f"{tag}: {line}  solo turns {solo}", flush=True)
        return sum(s for s, _, _ in r.values()) / len(r), solo

    if args.eval_only:
        report("eval")
        return

    pool = [f"{args.seed:03x}{i:013x}" for i in range(args.maze_pool)]
    boards = {}
    mix = [(k, float(v)) for k, v in (m.split(":") for m in args.mix.split(","))]
    best = report("start")
    best_solo = best[1]
    save(args.out, w_duo, w_solo, args, best)
    t0 = time.time()
    for g in range(1, args.games + 1):
        frac = g / args.games
        alpha = args.alpha * (args.alpha_end / args.alpha) ** frac
        eps = args.eps + (args.eps_end - args.eps) * frac
        seed = rng.choice(pool)
        if seed not in boards:
            if len(boards) > 500:
                boards.pop(next(iter(boards)))
            boards[seed] = gen_maze(seed)
        b = boards[seed]
        swap = rng.random() < 0.5
        if rng.random() < args.solo_share:
            play(b, [QAgent(w_solo, eps, True, alpha, args.gamma)], swap, rng)
        else:
            kind = rng.choices([k for k, _ in mix], [v for _, v in mix])[0]
            me = QAgent(w_duo, eps, True, alpha, args.gamma)
            if kind == "self":
                other = QAgent(w_duo, eps, True, alpha, args.gamma)
            else:
                other = opponents[kind]
            play(b, [me, other], swap, rng)
        if g % args.eval_every == 0:
            score, solo = report(f"game {g} ({time.time() - t0:.0f} s, alpha {alpha:.4f})")
            if score > best[0]:
                best = (score, best[1])
                save(args.out, w_duo, None, args, best)
            if solo < best_solo:
                best_solo = solo
                save(args.out, None, w_solo, args, best)
    print("best:", best, "solo", best_solo)
    for name, wd, ws in zip(qf.FEATURES, w_duo, w_solo):
        print(f"  {name:16s} duo {wd:+8.3f}  solo {ws:+8.3f}")


def save(path, w_duo, w_solo, args, best):
    p = Path(path)
    data = json.loads(p.read_text()) if p.exists() else {}
    if data.get("features") != qf.FEATURES:
        data = {}
    data["features"] = qf.FEATURES
    if w_duo is not None:
        data["duo"] = [round(float(v), 6) for v in w_duo]
        data["duo_eval"] = round(best[0], 4)
    if w_solo is not None:
        data["solo"] = [round(float(v), 6) for v in w_solo]
    data["trained"] = {k: v for k, v in vars(args).items() if k not in ("out", "weights", "eval_only")}
    data.setdefault("duo", data.get("solo"))
    data.setdefault("solo", data.get("duo"))
    p.write_text(json.dumps(data, indent=1) + "\n")


if __name__ == "__main__":
    main()
