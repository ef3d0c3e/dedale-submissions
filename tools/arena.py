"""Tournaments, a few games at a time: only the games the games file lacks
are played, for the bots in the pool now (`<login>/<bot>@<version>`).

    python3 -m tools.arena schedule --dedale PATH --games FILE --out DIR [--shards N]
    python3 -m tools.arena play --schedule DIR/schedule.json --shard K --dedale PATH --out FILE [--sandbox]
    python3 -m tools.arena merge --games FILE --out FILE SHARD...
    python3 -m tools.arena run --dedale PATH --games FILE [--sandbox]   # all three, here

Maze seeds and corners come from the `MAZE_SECRET` environment variable
(see `common.spec_seed` and `common.swapped_mazes`); without it, from a
secret drawn for the run, so they are random, but each pairing still splits
its corners evenly and the yardstick still plays a bot's own solo mazes.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from tools.common import (
    ROOT,
    YARDSTICK,
    Bot,
    GameError,
    Season,
    check_game,
    duo_spec,
    failures,
    game_id,
    head_commit,
    play,
    read_bots,
    read_games,
    solo_spec,
    spec_seed,
    swapped_mazes,
    write_games,
)


def missing(season: Season, pool: list[Bot], done: set[str], secret: bytes) -> list[dict]:
    """The games still to play, each with its seed and corner, its bots'
    files in seat order, and its group: a pairing's games, or a bot's solo
    games, which one runner plays one after the other."""
    pool = sorted(pool, key=lambda bot: bot.id)
    yardstick = next((bot for bot in pool if bot.id == YARDSTICK), None)
    games = []

    def add(spec: dict, seats: list[Bot], group: str, swapped: bool = False) -> None:
        if game_id(spec) not in done:
            games.append(
                {
                    "id": game_id(spec),
                    "spec": spec,
                    "seed": spec_seed(secret, spec),
                    "swapped": swapped,
                    "bots": [str(bot.path) for bot in seats],
                    "group": group,
                }
            )

    for a, b in itertools.combinations(pool, 2):
        specs = [duo_spec(season, a, b, maze) for maze in range(season.mazes_per_pairing)]
        swapped = swapped_mazes(secret, specs)
        for spec in specs:
            add(spec, [a, b], f"{a.key} {b.key}", spec["maze"] in swapped)
    for bot in pool:
        for maze in range(season.solo_mazes):
            add(solo_spec(season, bot, bot, maze), [bot], bot.key)
            if yardstick is not None and yardstick.id != bot.id:
                add(solo_spec(season, yardstick, bot, maze), [yardstick], bot.key)
    return games


def shards(games: list[dict], count: int) -> list[list[dict]]:
    """`count` shards, whole groups each, the largest groups first to the
    least loaded shard."""
    groups: dict[str, list[dict]] = {}
    for game in games:
        groups.setdefault(game["group"], []).append(game)
    out: list[list[dict]] = [[] for _ in range(max(1, count))]
    for group in sorted(groups.values(), key=lambda g: (-len(g), g[0]["group"])):
        min(out, key=len).extend(group)
    return out


def record(spec: dict, replay: dict, commit: str) -> dict:
    """What the games file keeps of a game: enough to know its result and to
    play it again."""
    result = replay["result"]
    return {
        "id": game_id(spec),
        "spec": spec,
        "code": replay["code"],
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "dedale": replay["dedale"],
        "startup_ms": replay["config"]["startup_ms"],
        "move_ms": replay["config"]["move_ms"],
        "swapped": replay["config"]["seating"] == "duo_swapped",
        "result": {
            "reason": result["reason"],
            "turns": result["turns"],
            "half_points": result["half_points"],
            "winner": result["winner"],
            "cleared_turn": result["cleared_turn"],
        },
        "players": [
            {"startup": player["startup"]["outcome"], "failures": failures(stats["outcomes"])}
            for player, stats in zip(replay["players"], replay["stats"])
        ],
    }


def play_shard(
    dedale: str, season: Season, games: list[dict], root: Path, sandbox: bool, commit: str
) -> dict:
    """Plays a shard's games one at a time. A game Dedale could not play is
    tried once more, then listed as an error: never recorded as a result."""
    played, errors = [], []
    for game in games:
        seats = [Bot(id=f"seat{i}", path=root / path) for i, path in enumerate(game["bots"])]
        swapped = bool(game.get("swapped"))
        for attempt in (1, 2):
            try:
                replay = play(dedale, season, seats, game["seed"], swapped, sandbox)
            except GameError as error:
                if attempt == 2:
                    errors.append({"id": game["id"], "error": str(error)})
                continue
            played.append(record(game["spec"], replay, commit))
            print(f"{game['id']} {' vs '.join(game['spec']['bots'])}: {replay['result']['reason']}")
            break
    return {"games": played, "errors": errors}


def merge(games: list[dict], shard_files: list[Path]) -> tuple[list[dict], list[dict]]:
    """The games file's games with every shard's, checked; and the errors."""
    by_id = {game["id"]: game for game in games}
    errors = []
    for path in shard_files:
        data = json.loads(path.read_text())
        for game in data.get("games", []):
            check_game(game)
            by_id.setdefault(game["id"], game)
        errors += data.get("errors", [])
    return list(by_id.values()), errors


def pool_file(pool: list[Bot], root: Path) -> list[dict]:
    """The bots as the ranking and the site need them."""
    return [dict(bot.about(), path=str(bot.path.relative_to(root))) for bot in pool]


def schedule_command(args, root: Path = ROOT) -> int:
    season = Season.load(root / "season.json")
    pool = read_bots(args.dedale, root, args.sandbox)
    unknown = [bot.id for bot in pool if bot.version is None]
    if unknown:
        print(f"left out, no version: {', '.join(unknown)}", file=sys.stderr)
    pool = [bot for bot in pool if bot.version is not None]
    # Files relative to the root: the jobs that play check out the same commit.
    relative = [replace(bot, path=bot.path.relative_to(root)) for bot in pool]
    # Without the secret, one drawn for this run: both corners of a maze, and
    # the yardstick on a bot's solo mazes, still play the same mazes.
    secret = os.environ.get("MAZE_SECRET", "").encode() or os.urandom(32)
    done = {game["id"] for game in read_games(Path(args.games))}
    todo = missing(season, relative, done, secret)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    split = shards(todo, args.shards)
    (out / "schedule.json").write_text(json.dumps({"season": season.name, "shards": split}, indent=1))
    (out / "bots.json").write_text(json.dumps(pool_file(pool, root), indent=1))
    print(f"{len(todo)} games to play in {len(split)} shards, {len(pool)} bots")
    return 0


def play_command(args, root: Path = ROOT) -> int:
    season = Season.load(root / "season.json")
    schedule = json.loads(Path(args.schedule).read_text())
    if schedule["season"] != season.name:
        print(f"the schedule is for season {schedule['season']}, not {season.name}", file=sys.stderr)
        return 1
    games = schedule["shards"][args.shard] if args.shard < len(schedule["shards"]) else []
    result = play_shard(args.dedale, season, games, root, args.sandbox, head_commit(root))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result))
    for error in result["errors"]:
        print(f"not played: {error['id']}: {error['error']}", file=sys.stderr)
    return 0


def merge_command(args) -> int:
    games, errors = merge(read_games(Path(args.games)), [Path(p) for p in args.shards])
    write_games(Path(args.out), games)
    print(f"{len(games)} games in {args.out}")
    for error in errors:
        print(f"not played: {error['id']}: {error['error']}", file=sys.stderr)
    return 1 if errors else 0


def run_command(args, root: Path = ROOT) -> int:
    """Schedule, play and merge here, in one shard."""
    with tempfile.TemporaryDirectory(prefix="dedale-arena-") as tmp:
        work = Path(tmp)
        common = {"dedale": args.dedale, "sandbox": args.sandbox}
        schedule_command(argparse.Namespace(games=args.games, out=work, shards=1, **common), root)
        play_command(
            argparse.Namespace(schedule=work / "schedule.json", shard=0, out=work / "s.json", **common),
            root,
        )
        status = merge_command(argparse.Namespace(games=args.games, out=args.games, shards=[work / "s.json"]))
        shutil.copy(work / "bots.json", Path(args.games).with_name("bots.json"))
        return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    dedale = os.environ.get("DEDALE") or shutil.which("dedale")

    schedule = commands.add_parser("schedule", help="list the games to play, in shards")
    schedule.add_argument("--games", required=True, help="the games file (may not exist yet)")
    schedule.add_argument("--out", required=True, help="writes schedule.json and bots.json there")
    schedule.add_argument("--shards", type=int, default=1)

    play_parser = commands.add_parser("play", help="play one shard")
    play_parser.add_argument("--schedule", required=True)
    play_parser.add_argument("--shard", type=int, required=True)
    play_parser.add_argument("--out", required=True)

    merge_parser = commands.add_parser("merge", help="add the shards' games to the games file")
    merge_parser.add_argument("--games", required=True)
    merge_parser.add_argument("--out", required=True)
    merge_parser.add_argument("shards", nargs="*")

    run = commands.add_parser("run", help="schedule, play and merge, here")
    run.add_argument("--games", required=True)

    for sub in (schedule, play_parser, run):
        sub.add_argument("--dedale", default=dedale, required=dedale is None)
        sub.add_argument("--sandbox", action="store_true", help="play in Dedale's sandbox")

    args = parser.parse_args(argv)
    return {
        "schedule": schedule_command,
        "play": play_command,
        "merge": merge_command,
        "run": run_command,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
