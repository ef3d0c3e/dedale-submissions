"""What the tests share: bots written on the fly, game records, Dedale."""

from __future__ import annotations

import os
import shutil
import textwrap
from pathlib import Path

from tools.common import Bot, game_id

BOT = '''
NAME = "{name}"
AUTHOR = "{author}"
DESCRIPTION = "A test bot."
VERSION = {version}


def move():
    return "{move}"
'''


def dedale() -> str | None:
    """Dedale for the end-to-end tests: `DEDALE`, or `dedale` on the PATH."""
    return os.environ.get("DEDALE") or shutil.which("dedale")


def chromium() -> str | None:
    """A browser for the site's script: `CHROMIUM`, or one on the PATH."""
    names = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
    return os.environ.get("CHROMIUM") or next(filter(None, map(shutil.which, names)), None)


def write_bot(
    root: Path, bot_id: str, name: str = "", version: int = 1, move: str = "stay", source: str = ""
) -> Path:
    """`bots/<bot_id>/main.py` under `root`; its directory."""
    directory = root / "bots" / bot_id
    directory.mkdir(parents=True, exist_ok=True)
    text = source or BOT.format(
        name=name or bot_id.split("/")[1], author=bot_id.split("/")[0], version=version, move=move
    )
    (directory / "main.py").write_text(textwrap.dedent(text))
    return directory


def bot(bot_id: str, version: int = 1, name: str | None = None) -> Bot:
    return Bot(
        id=bot_id,
        path=Path("bots") / bot_id / "main.py",
        name=name or bot_id.split("/")[1],
        author=bot_id.split("/")[0],
        description="A test bot.",
        version=version,
        said_hello=True,
    )


def record(spec: dict, half_points: list[int], turns: int = 100, reason: str = "cleared") -> dict:
    """A game as the arena records it."""
    winner = None
    if len(half_points) == 2 and half_points[0] != half_points[1]:
        winner = 0 if half_points[0] > half_points[1] else 1
    return {
        "id": game_id(spec),
        "spec": spec,
        "code": "ded2-31x31-l80-p50-0000000000000001",
        "date": "2026-10-20T00:00:00Z",
        "commit": "0" * 40,
        "dedale": "0.1.0",
        "startup_ms": 2000,
        "move_ms": 100,
        "result": {
            "reason": reason,
            "turns": turns,
            "half_points": half_points,
            "winner": winner,
            "cleared_turn": turns if reason == "cleared" else None,
        },
        "players": [{"startup": "ok", "failures": 0} for _ in half_points],
    }
