# Q-Learner

Chooses which point to go for with a Q-function learned by **Q-learning**.
Nothing is searched or simulated during a game: each move is one feature
computation and one dot product, about 0.1–0.3 ms.

## Why offline, and why approximate

Every game starts a fresh process on a fresh maze, with the bot's folder
read-only, so a bot cannot learn during the competition, and a table indexed
by raw states would never see the same state twice. The Q-function is
therefore **linear in hand-made features**, Q(s, a) = w · φ(s, a), and the
weights are learned offline over tens of thousands of simulated games
(`tools/train.py`), then committed as `weights.json`.

## States, actions, rewards

- **Action**: "take one step toward remaining point p", re-chosen every turn.
  Only the 16 nearest points are candidates.
- **Features** φ(s, p), in `qfeatures.py` and shared by bot and trainer:
  how near p is (two decays and linear), who wins the race to it (win / tie /
  lose, weighted by nearness, and the margin), the points after p that I
  would still reach first or that the opponent would (`follow_mine`,
  `follow_theirs`), the nearest other point and the local cluster, whether p
  is the opponent's nearest point (and whether the opponent gets it first),
  how close the opponent is to p, and the share of points left.
- **Reward**: my points minus the opponent's, every turn (solo: my points),
  discounted by γ = 0.97 per turn.
- **Update**, after every turn:
  `w += α (r + γ max_p' Q(s', p') − Q(s, p)) φ(s, p)`, with ε-greedy
  exploration (ε 0.15 → 0.02, α 0.01 → 0.001 over 20 000 games).

`init()` runs one breadth-first search from every point (about 30 ms), so
every distance the features need is a table lookup.

## What it learned (duo weights)

| Feature | Weight | Reading |
|---|---|---|
| `near_fast` | +1.28 | the nearest points matter most |
| `win` / `tie` / `lose` | +0.39 / −0.75 / −0.93 | go for races it wins; a split is barely better than a loss |
| `opp_target` | +0.45 | take the point the opponent is heading to… |
| `opp_target_lost` | −0.41 | …unless the opponent gets there first |
| `opp_near` | −0.38 | stay out of the opponent's neighbourhood |
| `follow_mine`, `follow_mine_now` | +0.17, +0.18 | points that lead on to more points it wins |
| `follow_theirs` | +0.30 | contesting the opponent's region pays too |
| `cluster` | −0.24 | less than you'd think: tight clusters get swept anyway |

## Two policy guards (in `qfeatures.py`, used in training too)

- **Switching margin**: last turn's target stays unless another beats it by
  0.02 in Q. Without it, two far points of nearly equal value swapped every
  step and the bot walked back and forth until the turn limit.
- **Loop breaker** (`Chooser`): if a state (my cell, the opponent's cell,
  points left) comes back, the game is in a cycle, so the current target is
  kept until collected. Against Courser, whose plan reacts to the bot's
  moves, the two bots once walked a 10-turn cycle for 3500 turns.

The trainer plays the same policy, so Q is learned for what the bot actually
does.

## Results

Real referee, season settings (31×31, 80% loops, 40 points, 100 ms),
10 mazes × 2 corners, 0 failures throughout:

| Opponent | Seed | W–D–L | Points |
|---|---|---|---|
| Greedy | 3 | 10–6–4 | 408.5–391.5 |
| Tour | 3 | 16–4–0 | 455–345 |
| Rollout | 3 | 9–6–5 | 410–390 |
| Rollout | 7 | 4–9–7 | 406.5–393.5 |
| Clusters | 3 | 8–7–5 | 409.5–390.5 |
| Courser | 3 | 10–2–8 | 409.5–390.5 |
| Courser | 7 | 7–5–8 | 399.5–400.5 |

Every row was played with the loop breaker. The Greedy, Tour, Rollout
seed 3 and Clusters pairings gave the same results without it: the breaker
only acts once a state repeats, which happened only against Courser. There,
without it, seed 3 was 9–1–10 and 397.5–399.5, with one game running to
turn 3812.

Single games against rollout, no problems in any: 11×11 won, 51×51 won,
500 points won 268–232, a sandboxed game drawn; `--loops 0` and
`--move-ms 20` lost 18–22 and 19–21. A mirror game ends normally (188 turns).

**Solo is greedy.** Solo Q-learning (reward = points, discounted) never beat
its greedy start: learned solo policies took 5–10% more turns than greedy on
held-out mazes, whatever γ (0.95–0.99). The trainer keeps the best solo
weights it has seen, which are the start, so solo plays greedy (3272 turns
on 10 mazes where greedy takes 3275 and Tour 3009). A turn-count reward,
and features about the shape of the remaining tour, are the obvious next try.

## What did not work

- A `committed` feature (p was last turn's target), meant to let Q learn to
  stop dithering, learned a negative weight: targets chased for long are far
  ones, and far targets are worth less. Switching then paid, and the bot
  dithered more. Replaced by the fixed switching margin.
- A `my_nearest` indicator did the same harm through a small negative
  weight, and was dropped.
- γ = 0.99 learned more slowly and no better (0.520 against 0.523 point
  share on the held-out set); 0.95 and 0.97 tied.

## Training it again

`tools/train.py` needs numpy and an extracted Dedale release, for its maze
generator (`DEDALE=path/to/dedale`, or the release extracted at the
repository root). From this folder:

```sh
python3 tools/train.py --games 20000 --gamma 0.97 --out weights.json   # ~6 min
python3 tools/train.py --eval-only --weights weights.json
```

It plays its own simulation of the referee's rules (simultaneous moves,
splits, the turn limit), training against greedy (30%), a racer that goes
for the nearest point it reaches first (30%) and itself (40%, both sides
learning). Every 2000 games it evaluates the greedy-on-Q policy on 30
held-out mazes against greedy and the racer, and writes the best weights so
far.
