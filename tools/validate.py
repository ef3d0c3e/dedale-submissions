"""Decides whether a pull request's bots may join: run by the pull request
check, and by submitters before opening one.

    python3 -m tools.validate --author LOGIN [--base REF] [--dedale PATH] [--sandbox] [--root DIR]

`--root` checks another checkout: the pull request check runs the base
branch's tools, which a pull request cannot change, on the pull request's
files. Prints a Markdown report (also written to `GITHUB_STEP_SUMMARY` when set) and
exits with 1 when anything is wrong, listing every reason.
"""

from __future__ import annotations

import argparse
import ast
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tools.common import (
    BASELINE,
    BOT_NAME,
    ENTRY,
    LOGIN,
    MAX_BOT_BYTES,
    ROOT,
    Bot,
    GameError,
    Season,
    failures,
    maze_seed,
    play,
    read_bots,
)

# Smoke games stop here: enough to see a bot start and play.
SMOKE_TURNS = 200
MAX_VERSION = 2**32 - 1


@dataclass
class Report:
    """What the check found: per bot, then for the pull request as a whole."""

    errors: list[str] = field(default_factory=list)
    bots: dict[str, list[str]] = field(default_factory=dict)

    def fail(self, message: str, bot: str | None = None) -> None:
        self.errors.append(f"`{bot}`: {message}" if bot else message)
        if bot:
            self.bots.setdefault(bot, []).append(f"✗ {message}")

    def ok(self, bot: str, message: str) -> None:
        self.bots.setdefault(bot, []).append(f"✓ {message}")

    def markdown(self) -> str:
        lines = ["## Submission check", ""]
        if not self.bots and not self.errors:
            lines.append("No bot changed.")
        for bot, notes in sorted(self.bots.items()):
            lines += [f"### `{bot}`", "", *(f"- {note}" for note in notes), ""]
        general = [e for e in self.errors if not e.startswith("`")]
        if general:
            lines += ["### The pull request", "", *(f"- ✗ {e}" for e in general), ""]
        lines.append("**Refused**: fix the points above." if self.errors else "**Accepted.**")
        return "\n".join(lines) + "\n"


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def changed_paths(root: Path, base: str) -> list[str]:
    """Paths the branch changes since it left `base` (renames as two paths)."""
    done = git(root, "diff", "--name-only", "--no-renames", f"{base}...HEAD")
    if done.returncode != 0:
        raise RuntimeError(f"git diff against {base}: {done.stderr.strip()}")
    return [line for line in done.stdout.splitlines() if line]


def maintainers(root: Path, base: str) -> set[str]:
    """The maintainers' logins, as the base branch lists them: a pull request
    cannot make its author one."""
    done = git(root, "show", f"{base}:MAINTAINERS")
    if done.returncode != 0:
        return set()
    lines = (line.split("#")[0].strip() for line in done.stdout.splitlines())
    return {line.lower() for line in lines if line}


def literal_version(source: str) -> int | None:
    """`VERSION` as Dedale's harness reads it: the last top-level assignment
    of an integer literal from 1; `None` otherwise."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    version = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "VERSION" for t in targets):
            literal = value.value if isinstance(value, ast.Constant) else None
            ok = type(literal) is int and 1 <= literal <= MAX_VERSION
            version = literal if ok else None
    return version


def base_version(root: Path, base: str, bot_id: str) -> tuple[bool, int | None]:
    """Whether the bot exists on `base`, and its version there."""
    done = git(root, "show", f"{base}:bots/{bot_id}/{ENTRY}")
    if done.returncode != 0:
        return False, None
    return True, literal_version(done.stdout)


def folder_problems(directory: Path) -> list[str]:
    """What is wrong with a bot's folder: no entry, links, too large."""
    problems = []
    if not (directory / ENTRY).is_file() or (directory / ENTRY).is_symlink():
        problems.append(f"no `{ENTRY}`")
    size = 0
    for parent, dirs, files in os.walk(directory):
        for name in dirs + files:
            path = Path(parent) / name
            if path.is_symlink():
                problems.append(f"`{path.relative_to(directory)}` is a symbolic link")
            elif path.is_file():
                size += path.stat().st_size
    if size > MAX_BOT_BYTES:
        problems.append(f"{size / 2**20:.1f} MiB, more than {MAX_BOT_BYTES // 2**20} MiB")
    return problems


def opponent(pool: list[Bot], bot: Bot) -> Bot | None:
    """A baseline to play a smoke game against: greedy unless it is the bot."""
    baselines = [b for b in pool if b.baseline and b.id != bot.id]
    preferred = [b for b in baselines if b.id == f"{BASELINE}/greedy"]
    return (preferred or baselines or [None])[0]


def smoke(report: Report, dedale: str, season: Season, bot: Bot, rival: Bot, sandbox: bool) -> None:
    """One game against `rival` on a random maze: the bot must start in time
    and never crash."""
    try:
        replay = play(dedale, season, [bot, rival], maze_seed(None), False, sandbox, SMOKE_TURNS)
    except GameError as error:
        report.fail(f"Dedale could not play a game with it: {error}", bot.id)
        return
    player = replay["players"][0]
    outcomes = replay["stats"][0]["outcomes"]
    startup = player["startup"]["outcome"]
    summary = (
        f"{replay['result']['turns']} turns against `{rival.id}` on `{replay['code']}`: "
        f"{outcomes['ok']} moves, {failures(outcomes)} problems"
    )
    if startup != "ok":
        error = player["startup"].get("error") or {}
        detail = f" ({error.get('message')})" if error.get("message") else ""
        report.fail(f"did not start: `{startup}`{detail}; {summary}", bot.id)
    elif outcomes.get("crashed", 0):
        report.fail(f"crashed; {summary}", bot.id)
    elif outcomes["ok"] == 0:
        report.fail(f"never made a move; {summary}", bot.id)
    else:
        report.ok(bot.id, f"played: {summary}")


def check(
    root: Path,
    base: str,
    author: str,
    dedale: str | None,
    sandbox: bool = False,
    games: bool = True,
) -> Report:
    report = Report()
    maintainer = author.lower() in maintainers(root, base)
    paths = changed_paths(root, base)

    touched: set[str] = set()
    for path in paths:
        parts = path.split("/")
        mine = len(parts) >= 2 and parts[0] == "bots" and parts[1].lower() == author.lower()
        if not maintainer and not mine:
            report.fail(f"`{path}` is outside `bots/{author}/`")
            continue
        if parts[0] == "bots":
            if len(parts) < 4:
                report.fail(f"`{path}` is not inside a bot's folder (`bots/<login>/<bot>/`)")
            else:
                touched.add(f"{parts[1]}/{parts[2]}")

    present = sorted(b for b in touched if (root / "bots" / b).is_dir())
    for bot_id in sorted(touched - set(present)):
        report.ok(bot_id, "removed")
    for bot_id in present:
        user, name = bot_id.split("/")
        if not (LOGIN.fullmatch(user) or user == BASELINE):
            report.fail(f"`{user}` is not a GitHub login", bot_id)
        if not BOT_NAME.fullmatch(name):
            report.fail("its name is not lower-case letters, digits, `-` and `_` (40 at most)", bot_id)
        for problem in folder_problems(root / "bots" / bot_id):
            report.fail(problem, bot_id)
    if not present or dedale is None:
        if present:
            report.fail("Dedale is needed to read the bots (`--dedale` or `dedale` on the PATH)")
        return report

    pool = read_bots(dedale, root, sandbox)
    by_id = {bot.id: bot for bot in pool}
    names: dict[str, list[str]] = {}
    for bot in pool:
        if bot.name:
            names.setdefault(bot.name.casefold(), []).append(bot.id)
    season = Season.load(root / "season.json")
    for bot_id in present:
        bot = by_id.get(bot_id)
        if bot is None:
            continue
        if not bot.said_hello:
            report.fail("Dedale could not read it: it did not start", bot_id)
            continue
        missing = [
            glob
            for glob, value in (
                ("NAME", bot.name),
                ("AUTHOR", bot.author),
                ("DESCRIPTION", bot.description),
                ("VERSION", bot.version),
            )
            if value is None
        ]
        if missing:
            listed = ", ".join(f"`{m}`" for m in missing)
            report.fail(f"no {listed} (plain literals at the top of `{ENTRY}`)", bot_id)
            continue
        others = [i for i in names[bot.name.casefold()] if i != bot_id]
        if others:
            report.fail(f"its name, {bot.name!r}, is taken by `{others[0]}`", bot_id)
        existed, before = base_version(root, base, bot_id)
        if existed and before is not None and bot.version <= before:
            report.fail(f"changed but still at version {bot.version}: raise `VERSION`", bot_id)
        elif not existed and bot.version != 1:
            report.fail(f"a new bot starts at version 1, not {bot.version}", bot_id)
        else:
            report.ok(bot_id, f"{bot.name} by {bot.author}, version {bot.version}")
        if games and not any(e.startswith(f"`{bot_id}`") for e in report.errors):
            rival = opponent(pool, bot)
            if rival is None:
                report.fail("no baseline to play a game against", bot_id)
            else:
                smoke(report, dedale, season, bot, rival, sandbox)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--author", required=True, help="the pull request's GitHub login")
    parser.add_argument("--base", default="origin/master", help="the branch it merges into")
    parser.add_argument("--dedale", default=os.environ.get("DEDALE") or shutil.which("dedale"))
    parser.add_argument("--sandbox", action="store_true", help="play in Dedale's sandbox")
    parser.add_argument("--no-games", action="store_true", help="skip the smoke games")
    parser.add_argument("--root", type=Path, default=ROOT, help="the checkout to check")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    report = check(root, args.base, args.author, args.dedale, args.sandbox, not args.no_games)
    text = report.markdown()
    print(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as file:
            file.write(text)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
