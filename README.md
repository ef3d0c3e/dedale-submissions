# Dedale competition

Bots for [Dedale](https://github.com/ef3d0c3e/dedale), the maze referee,
compete here. Submit a bot with a pull request; once it is merged it plays
the bots already there, and the ranking is published at
<https://ef3d0c3e.github.io/dedale-submissions/>.

- [How it works](#how-it-works)
- [Submitting a bot](#submitting-a-bot)
- [Libraries](#libraries)
- [Games](#games)
- [Ranking](#ranking)
- [Baselines](#baselines)
- [Reproducing a game](#reproducing-a-game)
- [Licence](#licence)
- [For maintainers](#for-maintainers)

## How it works

1. You add your bot under `bots/<your GitHub login>/<bot>/` in a fork and
   open a pull request, ticking the box that licenses it under the MIT
   License ([Licence](#licence)).
2. A check reads what your bot says about itself, makes sure the pull
   request only touches your own folder and the box is ticked, and plays a
   few games with it in Dedale's sandbox. Its report is in the check's
   summary.
3. Once a maintainer merges it, your bot plays each bot already in the
   pool, and its mazes alone; then the site is updated with the new
   ranking. Only the new bot's games are played: the results of the others
   against each other are kept.

## Submitting a bot

New to Dedale? Its guide, [Writing a bot](https://github.com/ef3d0c3e/dedale/blob/master/docs/writing-a-bot.md),
goes from an empty file to a competitive bot.

**Layout.** A bot is a folder: `bots/<login>/<bot>/main.py`, where `<login>`
is your GitHub login and `<bot>` a name of your choice (lower-case letters,
digits, `-` and `_`, up to 40 characters). Next to `main.py` you may add
helper modules and data files; load them relative to the bot's file:

```python
from pathlib import Path

TABLE = (Path(__file__).parent / "table.bin").read_bytes()
```

A bot's folder holds at most 10 MiB, and no symbolic links. You may enter
several bots.

**Who it is.** These globals are required, as plain literals at the top of
`main.py` (Dedale reads them without running your code):

```python
NAME = "Racer"          # what it is called, unique in the pool
AUTHOR = "Ada"          # who wrote it
DESCRIPTION = "Goes for the nearest point it reaches before the opponent."
VERSION = 1             # raise it whenever the bot changes
```

**Updating.** Change your files in place and raise `VERSION`: the check
refuses changed files with the same version. A new version plays all its
games again; the old version's games stay in the history.

**Rules.** Bots are Python 3.12, with the standard library and the
[libraries](#libraries) below, and run in Dedale's sandbox: no network, an
empty environment, a read-only view of the system and of their own folder,
a private `/tmp` of 64 MiB, 2048 MiB of memory per process, 64 processes
and threads, one CPU. Each bot gets the season's
startup budget for importing it and running `init()`, then a time limit
per move ([`season.json`](season.json)); a late move is lost and the bot
stays.

**Before opening the pull request**, check your bot with the season's
Dedale release (the `dedale` version in [`season.json`](season.json);
`python3 -m tools.fetch_dedale` downloads it to `.dedale/dedale` on Linux):

```sh
dedale about bots/ada/racer/main.py                 # what Dedale reads
dedale run bots/ada/racer/main.py bots/_baseline/greedy/main.py --sandbox
python3 -m tools.validate --author ada              # the pull request's check
```

If your bot imports a library, run it with the season's Python (see
[Libraries](#libraries)): add `--python .bot-python/bin/python` to
`dedale run`, or set `DEDALE_PYTHON=.bot-python/bin/python`, which
`tools.validate` passes on to Dedale too.

### Step by step

One pull request per bot, from a branch of your fork. With `ada` as your
login and `racer` as the bot:

1. **Fork** this repository on GitHub and clone your fork.
2. **Branch** from `master`, named after the bot: `git switch -c ada/racer`
   (for a later version, `ada/racer-v2`).
3. **Add** the bot's folder, `bots/ada/racer/`, with `main.py` and anything
   it loads, and nothing outside it: the check refuses changes elsewhere.
4. **Check** it with the commands above.
5. **Commit** with a title saying what happens to the pool:
   `Add ada/racer`, `Update ada/racer to version 2`, or
   `Remove ada/racer`.
6. **Push** and open a pull request against `master`, with the same title.
   Fill in the template: what the bot does, what changed (for an update),
   the libraries it imports, and **tick the licence box**
   ([Licence](#licence)).
7. **The check** runs: its report is in the pull request's Checks tab,
   under *Pull request / Submission*, in the summary. On a first pull
   request, a maintainer has to approve the run first. To fix something,
   push to the same branch, or edit the description: the check runs again.
8. **A maintainer merges** it. The tournament then plays your bot's games,
   and it shows up on the [site](https://ef3d0c3e.github.io/dedale-submissions/),
   marked provisional until all its games are played.

## Libraries

Besides the standard library, bots may import:

| Library | Version | For instance |
|---|---|---|
| [numpy](https://numpy.org) | 2.5.4 | Arrays: distance grids, flood fills, fast simulations of the game |
| [scipy](https://scipy.org) | 1.18.1 | `scipy.sparse.csgraph` (breadth-first search, Dijkstra, all-pairs distances, in C), `scipy.optimize.linear_sum_assignment`, `scipy.ndimage` |
| [networkx](https://networkx.org) | 3.7 | Graphs in plain Python: shortest paths, approximate tours |

They run on **Python 3.12**, the same for every bot all season, pinned in
[`libraries.txt`](libraries.txt) with the hash of every file. Importing
counts against the startup budget, but takes a fraction of it: about
20 ms for numpy, 60 ms for `scipy.sparse.csgraph` and 35 ms for networkx.
They compute on one thread, like the bot: each bot has one CPU.

To get the same at home, with Python 3.12:

```sh
python3.12 -m tools.bot_python build    # makes .bot-python/, prints its python
```

or install `numpy==2.5.4 scipy==1.18.1 networkx==3.7` in a virtual
environment of your own. Packages from `pip install --user` do not count:
they live in your home directory, which the sandbox hides, so a bot that
imports one works without `--sandbox` and fails with it. Other packages are
not available.

## Games

Each pair of bots plays 20 games, each on its own maze: each bot starts 10
of them top-left and 10 bottom-right, which ones drawn at random. Each bot
also clears 20 mazes alone. The maze size, number of points, share of
loops and timings are the season's ([`season.json`](season.json)):
Dedale's defaults, 31×31 with 40 points and 80% loops, 5 s to start and
100 ms per move.

Tournaments only play what is missing. After a merge, a new bot, or a new
version of one, plays its games against every bot in the pool; games
already played are never played again.

Mazes are **fresh for each pairing**: their seeds, and who starts in which
corner, come from a secret and the two bots' versions, so nobody can know
or tune for them before they are played. Each game's maze code and
corners are published with its result, so any game can be played again
without the secret.

Every game is recorded in `games.json.gz`, published on the site: who
played (`<login>/<bot>@<version>`), the maze code, the corner, the timings,
the repository commit and Dedale version it was played at, the date and the
result. Replays and logs are not kept.

## Ranking

**Head to head.** A pairing's score is a bot's share of all the points
collected over its 20 games: 0.5 is even. The board is sorted by
**points**: a bot's pairing scores averaged over its opponents, in percent
(50 is even); ties go to the higher win rate. Click a column on the site
to sort by it instead:

- **Win rate**: games won, draws counting half.
- **Pairings** won, drawn and lost.
- **Schulze**: the rank by the Schulze method. A bot ranks above another
  when it beats it, directly or through a chain of bots each beating the
  next, by a wider margin than the other manages back. A bot that beats
  every other is first, and unlike points, entering weak or copied bots
  lifts nobody.
- **Games with failures**: late, illegal or missing moves, crashes.

Only each bot's latest version is ranked; a bot with games still to play is
marked provisional.

**Solo.** A separate board ranks how fast each bot clears its mazes alone,
as its turns divided by the greedy baseline's on the same mazes (lower is
better; a maze not cleared counts the turn limit).

## Baselines

`bots/_baseline/` holds Dedale's example bots: greedy, tour and rollout.
They play every tournament like any bot, so a newcomer always has
opponents and the ranking has fixed references. `_baseline` cannot be a
GitHub login, so only maintainers change them.

## Reproducing a game

Each game on the site shows the command that plays it again, for instance:

```sh
git checkout <commit>
dedale run bots/ada/racer/main.py bots/_baseline/greedy/main.py \
    --maze ded2-31x31-l80-p40-1a2b3c4d5e6f7a8b --swap --startup-ms 5000 --move-ms 100
```

with the Dedale version the game was played with, and for bots that import
a library, the season's Python (`--python`, see [Libraries](#libraries)).
Bots that depend on timing may play slightly differently.

## Licence

Everything here is under the [MIT License](LICENSE), and so are the bots:
**by opening a pull request that adds or changes a bot, you license it
under the MIT License** and confirm that you wrote it, or have the right
to license it so. You keep the copyright of your bot: the licence lets
anyone use, copy, change and share it, keeping your copyright notice and
the licence with it, as you may do with the others' bots.

The pull request template has a box saying so; the check refuses a pull
request that adds or changes a bot until it is ticked (editing the
description runs the check again).

## For maintainers

- **Tools** (`tools/`, standard library only, Python 3.10 or later, run as
  `python3 -m tools.<name>` from the root): `fetch_dedale` (the season's
  release, checked against its checksums), `bot_python` (the bots' Python:
  `build` makes a virtual environment with `libraries.txt`, from wheels and
  only the files hashed; `pin numpy==… scipy==…` rewrites the file from
  PyPI, listing every dependency too), `validate` (the pull request check),
  `arena` (schedule, play and merge games), `rank` (standings), `site` (the
  static site). `scripts/check.sh` runs their tests (the end-to-end ones
  need Dedale: `DEDALE` or `dedale` on the PATH).
- **Workflows**: `pull-request.yml` (read-only token, no secrets: the
  tools' tests and actionlint, then the submission check, which skips
  Dependabot's pull requests: they only update the pinned actions) and
  `tournament.yml` (on each push to `master`: schedule, play in parallel
  jobs, then merge, rank and deploy; only the schedule job holds the
  `MAZE_SECRET` secret, only the deploy job can write). The bots run on
  the bots' Python in the play jobs and the submission check; the schedule
  job installs no library. Dependabot proposes updates of the actions
  weekly.
- **Settings**: a repository secret `MAZE_SECRET` (any long random string);
  Pages built from GitHub Actions; "Require approval for first-time
  contributors" for workflow runs; `master` protected, merged through pull
  requests.
- **Results** live as the `games.json.gz` asset of the `results` release,
  replaced after each tournament (a file committed at each run would grow
  the history by its full size every time).
- **A new season** (new Dedale version, settings, Python or libraries):
  edit `season.json` and `libraries.txt` (`bot_python pin`); every game is
  played again under the new season's name. The runner's `python3` must
  be the season's Python: `bot_python build` stops otherwise.
