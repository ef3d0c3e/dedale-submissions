"""What the tools share: the repository's layout, the season, the bots and
what they say about themselves, the games to play and the games file."""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = "main.py"
# Not a possible GitHub login (logins have no underscore): nobody can submit
# there, and only maintainers change these bots.
BASELINE = "_baseline"
# The solo board's yardstick: every bot's solo mazes are played by it too.
YARDSTICK = f"{BASELINE}/greedy"
MAX_BOT_BYTES = 10 * 1024 * 1024
GAMES_FORMAT = 1

# A GitHub login: letters, digits and single hyphens, none at either end,
# at most 39 characters.
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
BOT_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")


@dataclass(frozen=True)
class Season:
    """The settings every game of a season shares (`season.json`)."""

    name: str
    dedale: str
    width: int
    height: int
    loops: int
    points: int
    mazes_per_pairing: int
    solo_mazes: int
    startup_ms: int
    move_ms: int

    @classmethod
    def load(cls, path: Path = ROOT / "season.json") -> Season:
        data = json.loads(path.read_text())
        width, height = (int(side) for side in data["size"].split("x"))
        return cls(
            name=str(data["season"]),
            dedale=str(data["dedale"]),
            width=width,
            height=height,
            loops=int(data["loops"]),
            points=int(data["points"]),
            mazes_per_pairing=int(data["mazes_per_pairing"]),
            solo_mazes=int(data["solo_mazes"]),
            startup_ms=int(data["startup_ms"]),
            move_ms=int(data["move_ms"]),
        )

    def maze_args(self, seed: str) -> list[str]:
        """`dedale run`'s options for this season's maze from `seed` and timings."""
        return [
            "--size",
            f"{self.width}x{self.height}",
            "--loops",
            str(self.loops),
            "--points",
            str(self.points),
            "--seed",
            seed,
            "--startup-ms",
            str(self.startup_ms),
            "--move-ms",
            str(self.move_ms),
        ]


@dataclass(frozen=True)
class Bot:
    """A bot in the pool, and what it says about itself."""

    id: str
    path: Path
    name: str | None = None
    author: str | None = None
    description: str | None = None
    version: int | None = None
    said_hello: bool = False

    @property
    def key(self) -> str:
        """What a game is played by: `<user>/<bot>@<version>`."""
        return f"{self.id}@{self.version}"

    @property
    def baseline(self) -> bool:
        return self.id.startswith(f"{BASELINE}/")

    def about(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "author": self.author,
            "description": self.description,
            "baseline": self.baseline,
        }


def bot_dirs(root: Path = ROOT) -> list[tuple[str, Path]]:
    """Every `bots/<user>/<bot>/` directory, as (id, directory), by id."""
    found = []
    for user in sorted((root / "bots").glob("*")):
        if not user.is_dir() or user.is_symlink():
            continue
        for bot in sorted(user.glob("*")):
            if bot.is_dir() and not bot.is_symlink():
                found.append((f"{user.name}/{bot.name}", bot))
    return found


def read_bots(dedale: str, root: Path = ROOT, sandbox: bool = False) -> list[Bot]:
    """The pool: every bot with a `main.py`, and what `dedale about` reads."""
    entries = [(bot_id, path / ENTRY) for bot_id, path in bot_dirs(root)]
    entries = [(bot_id, path) for bot_id, path in entries if path.is_file()]
    return about(dedale, entries, sandbox)


def about(dedale: str, entries: list[tuple[str, Path]], sandbox: bool = False) -> list[Bot]:
    """Bots as `dedale about` reads them, for (id, path to `main.py`) pairs."""
    if not entries:
        return []
    command = [dedale, "about", *(["--sandbox"] if sandbox else [])]
    command += [str(path) for _, path in entries]
    out = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    if len(lines) != len(entries):
        raise RuntimeError(f"dedale about gave {len(lines)} answers for {len(entries)} bots")
    return [
        Bot(
            id=bot_id,
            path=path,
            name=said["name"],
            author=said["author"],
            description=said["description"],
            version=said["version"],
            said_hello=said["said_hello"],
        )
        for (bot_id, path), said in zip(entries, lines)
    ]


def maze_seed(secret: bytes | None, *parts: str) -> str:
    """A maze seed (16 hex digits): from the secret and what identifies the
    game, so nobody can know it before it is played, yet every run of the
    schedule finds the same; random without a secret."""
    if secret is None:
        return os.urandom(8).hex()
    return hmac.new(secret, "|".join(parts).encode(), hashlib.sha256).hexdigest()[:16]


def duo_spec(season: Season, a: Bot, b: Bot, maze: int, swapped: bool) -> dict:
    """A duo game: `a` and `b` by id, `a` starting top-left unless swapped."""
    first, second = sorted((a, b), key=lambda bot: bot.id)
    return {
        "season": season.name,
        "kind": "duo",
        "bots": [first.key, second.key],
        "maze": maze,
        "swapped": swapped,
    }


def solo_spec(season: Season, bot: Bot, mazes_of: Bot, maze: int) -> dict:
    """A solo game: `bot` alone on one of `mazes_of`'s solo mazes."""
    return {
        "season": season.name,
        "kind": "solo",
        "bots": [bot.key],
        "mazes_of": mazes_of.key,
        "maze": maze,
    }


def spec_seed(secret: bytes | None, spec: dict) -> str:
    """The seed of a game's maze. Both corners of a pairing share their
    mazes, and the yardstick plays a bot's own solo mazes."""
    if spec["kind"] == "duo":
        parts = [spec["season"], "duo", *spec["bots"], str(spec["maze"])]
    else:
        parts = [spec["season"], "solo", spec["mazes_of"], str(spec["maze"])]
    return maze_seed(secret, *parts)


def game_id(spec: dict) -> str:
    """A game's id: a hash of what it is (who, which maze, which corner)."""
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def read_games(path: Path) -> list[dict]:
    """The games file's games; none when it does not exist yet."""
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as file:
        data = json.load(file)
    if data.get("format") != GAMES_FORMAT:
        raise ValueError(f"{path}: games file format {data.get('format')!r}, not {GAMES_FORMAT}")
    games = data["games"]
    for game in games:
        check_game(game)
    return games


def write_games(path: Path, games: list[dict]) -> None:
    """One JSON document, gzipped, games by id: the same games make the same bytes."""
    data = {"format": GAMES_FORMAT, "games": sorted(games, key=lambda game: game["id"])}
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as file, gzip.GzipFile(fileobj=file, mode="wb", mtime=0) as out:
        out.write(raw)


GAME_FIELDS = {
    "id": str,
    "spec": dict,
    "code": str,
    "date": str,
    "commit": str,
    "dedale": str,
    "startup_ms": int,
    "move_ms": int,
    "result": dict,
    "players": list,
}


def check_game(game: object) -> None:
    """Refuses a game record that is not what the arena writes."""
    if not isinstance(game, dict):
        raise ValueError(f"a game is an object, not {game!r}")
    for field, kind in GAME_FIELDS.items():
        if not isinstance(game.get(field), kind):
            raise ValueError(f"game {game.get('id')!r}: {field} is not a {kind.__name__}")
    spec = game["spec"]
    if game_id(spec) != game["id"]:
        raise ValueError(f"game {game['id']}: its id does not match its spec")
    if spec.get("kind") not in ("duo", "solo"):
        raise ValueError(f"game {game['id']}: unknown kind {spec.get('kind')!r}")
    players = len(spec.get("bots", []))
    result = game["result"]
    half_points = result.get("half_points")
    if (
        players != (2 if spec["kind"] == "duo" else 1)
        or len(game["players"]) != players
        or not isinstance(half_points, list)
        or len(half_points) != players
        or not all(isinstance(h, int) and h >= 0 for h in half_points)
        or not isinstance(result.get("turns"), int)
        or not isinstance(result.get("reason"), str)
    ):
        raise ValueError(f"game {game['id']}: malformed result or players")
    for player in game["players"]:
        if not isinstance(player.get("startup"), str) or not isinstance(player.get("failures"), int):
            raise ValueError(f"game {game['id']}: malformed player")


class GameError(Exception):
    """Dedale could not play a game (not a bot's failure: those are results)."""


def play(
    dedale: str,
    season: Season,
    bots: list[Bot],
    seed: str,
    swapped: bool = False,
    sandbox: bool = False,
    max_turns: int | None = None,
) -> dict:
    """Plays one game with `dedale run` and returns its replay. Player 0 is
    `bots[0]`, starting bottom-right when `swapped`."""
    with tempfile.TemporaryDirectory(prefix="dedale-game-") as tmp:
        command = [dedale, "run", *(str(b.path) for b in bots), *season.maze_args(seed)]
        command += ["--out", tmp, "--color", "never"]
        command += ["--swap"] if swapped else []
        command += ["--sandbox"] if sandbox else []
        command += ["--max-turns", str(max_turns)] if max_turns else []
        done = subprocess.run(command, capture_output=True, text=True)
        replay = Path(tmp) / "replay.json"
        if done.returncode != 0 or not replay.exists():
            reason = done.stderr.strip() or f"dedale run exited with {done.returncode}"
            raise GameError(reason)
        return json.loads(replay.read_text())


def failures(outcomes: dict) -> int:
    """Turns that were not `ok`, from a replay's outcome counts."""
    return sum(n for outcome, n in outcomes.items() if outcome != "ok")


def head_commit(root: Path = ROOT) -> str:
    """The repository's commit: `GITHUB_SHA` on CI, else `git rev-parse HEAD`."""
    if sha := os.environ.get("GITHUB_SHA"):
        return sha
    out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return out.stdout.strip() if out.returncode == 0 else "unknown"
