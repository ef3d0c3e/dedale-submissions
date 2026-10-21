# Contributing a bot

A pull request here adds, updates or removes one bot. This page says what
to put in it and how to open it; the rules bots play by are in the README,
under [Submitting a bot](README.md#submitting-a-bot).

Anything else, such as the tools, the site or the documentation: open an
issue. The check refuses pull requests that change files outside your own
bot's folder.

- [What goes in the bot's folder](#what-goes-in-the-bots-folder)
- [The pull request, step by step](#the-pull-request-step-by-step)
- [Licence](#licence)

## What goes in the bot's folder

Everything about your bot lives in `bots/<your GitHub login>/<bot>/`, and
only there. For instance:

```
bots/ada/racer/
├── main.py         the bot (required)
├── paths.py        a module it imports
├── weights.json    data it loads
├── README.md       how it works
├── notes/          research, experiments, references
└── tuning/         the tuner that wrote weights.json
```

- **`main.py`** (required): the bot, with `NAME`, `AUTHOR`, `DESCRIPTION`
  and `VERSION` at the top ([Submitting a bot](README.md#submitting-a-bot)).
- **Modules and data it loads**: helpers, tables, weights. Load them
  relative to the bot's file (`Path(__file__).parent`). Don't name a module
  after a standard or allowed library (`random.py`, `numpy.py`): the bot's
  folder comes first on the import path, so yours would be imported
  instead.
- **`README.md`** (optional, welcome): GitHub shows it below the folder's
  files, and the bot's page on the site links there. Say how the bot
  plays, what `init()` precomputes and how `move()` decides, what you tried
  that did not work, and how it does against the baselines.
- **Research and references** (optional): notes, experiment results,
  links to the papers, articles or algorithms you built on.
- **Tools you built for it** (optional): a tuner for its parameters, a
  trainer, a benchmark, test mazes. They run on your machine, not in the
  competition, so they may use any library: say in the README what they
  need and how to run them. Commit what they produce (the weights
  `main.py` loads): a bot cannot install or download anything.

Only `main.py` and what it imports run in the competition; the rest is
for whoever reads your bot.

**Not in it:**

- files outside the folder: the check refuses them;
- symbolic links, or more than 10 MiB in all;
- what your machine generates: caches, virtual environments, replays,
  logs (`__pycache__/` is ignored already);
- work by others that you may not license under MIT ([Licence](#licence)):
  link to it instead;
- secrets, tokens, personal data.

**Every file is part of the bot.** A bot can read its whole folder, so the
check treats a change to any file in it, a typo fixed in the README
included, as a new bot: raise `VERSION`, and its games are played again.
Finish the notes before you submit, or fix them with the next version.

## The pull request, step by step

One pull request per bot, from a branch of your fork. With `ada` as your
login and `racer` as the bot:

1. **Fork** this repository on GitHub and clone your fork.
2. **Branch** from `master`, named after the bot: `git switch -c ada/racer`
   (for a later version, `ada/racer-v2`).
3. **Add** the bot's folder, `bots/ada/racer/`, with `main.py`, anything
   it loads and anything else about it ([above](#what-goes-in-the-bots-folder)).
4. **Check** it with the season's Dedale, as the README shows under
   [Submitting a bot](README.md#submitting-a-bot): `dedale about`, a game
   in the sandbox, and `python3 -m tools.validate --author ada`, the pull
   request's check.
5. **Commit** with a title saying what happens to the pool:
   `Add ada/racer`, `Update ada/racer to version 2`, or
   `Remove ada/racer`.
6. **Push** and open a pull request against `master`, with the same title.
   Fill in the template: what the bot does, what changed (for an update),
   the libraries it imports, the files besides `main.py`, and **tick the
   licence box**.
7. **The check** runs: its report is in the pull request's Checks tab,
   under *Pull request / Submission*, in the summary. On a first pull
   request, a maintainer has to approve the run first. To fix something,
   push to the same branch, or edit the description: the check runs again.
8. **A maintainer merges** it. The tournament then plays your bot's games,
   and it shows up on the [site](https://ef3d0c3e.github.io/dedale-submissions/),
   marked provisional until all its games are played.

## Licence

By opening a pull request that adds or changes a bot, you license
everything in its folder, notes and tools included, under the
[MIT License](LICENSE), and confirm that you wrote it or have the right to
license it so. You keep the copyright. The README's
[Licence](README.md#licence) section says what this allows.
