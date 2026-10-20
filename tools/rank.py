"""The standings: the duo board (the Schulze method on each pairing's share
of points) and the solo board (turns to clear, relative to the greedy
baseline on the same mazes).

    python3 -m tools.rank --games FILE --bots FILE --out FILE
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from tools.common import ROOT, YARDSTICK, Season, head_commit, read_games

HALF = Fraction(1, 2)


@dataclass
class Pairing:
    """The games of two bots, in their order."""

    games: list[dict] = field(default_factory=list)
    mine: int = 0
    theirs: int = 0

    def share(self) -> Fraction:
        """The first bot's share of the points; even when nobody scored."""
        total = self.mine + self.theirs
        return Fraction(self.mine, total) if total else HALF


def pairings(season: Season, keys: dict[str, str], games: list[dict]) -> dict[tuple[str, str], Pairing]:
    """Complete pairings of the current versions (`keys`: id to key), both
    ways round: (a, b) holds a's view."""
    current = {key: bot_id for bot_id, key in keys.items()}
    found: dict[tuple[str, str], Pairing] = {}
    for game in games:
        spec = game["spec"]
        if spec["kind"] != "duo" or spec.get("season") != season.name:
            continue
        if not all(key in current for key in spec["bots"]):
            continue
        a, b = (current[key] for key in spec["bots"])
        points = game["result"]["half_points"]
        for me, other, mine, theirs in ((a, b, points[0], points[1]), (b, a, points[1], points[0])):
            pairing = found.setdefault((me, other), Pairing())
            pairing.games.append(game)
            pairing.mine += mine
            pairing.theirs += theirs
    expected = 2 * season.mazes_per_pairing
    return {pair: p for pair, p in found.items() if len(p.games) == expected}


def schulze(ids: list[str], share: dict[tuple[str, str], Fraction]) -> dict[str, int]:
    """For each bot, how many others it ranks above: a link a→b of strength
    `share[a, b]` when a beats b; a path is as strong as its weakest link;
    a is above b when its strongest path to b beats b's strongest to a."""
    strength = {
        (a, b): share[a, b] if share.get((a, b), HALF) > HALF else Fraction(0)
        for a in ids
        for b in ids
        if a != b
    }
    for k in ids:
        for a in ids:
            if a == k:
                continue
            for b in ids:
                if b in (a, k):
                    continue
                strength[a, b] = max(strength[a, b], min(strength[a, k], strength[k, b]))
    return {a: sum(strength[a, b] > strength[b, a] for b in ids if b != a) for a in ids}


def duo_board(season: Season, bots: list[dict], games: list[dict]) -> tuple[list[dict], dict]:
    keys = {bot["id"]: f"{bot['id']}@{bot['version']}" for bot in bots}
    ids = sorted(keys)
    found = pairings(season, keys, games)
    share = {pair: p.share() for pair, p in found.items()}
    above = schulze(ids, share)

    def average(bot_id: str) -> Fraction:
        mine = [s for (a, _), s in share.items() if a == bot_id]
        return sum(mine, Fraction(0)) / len(mine) if mine else HALF

    order = sorted(ids, key=lambda i: (-above[i], -average(i), i))
    current = set(keys.values())
    board = []
    for rank, bot_id in enumerate(order, 1):
        mine = {b: s for (a, b), s in share.items() if a == bot_id}
        played = [
            g for g in games if keys[bot_id] in g["spec"]["bots"] and set(g["spec"]["bots"]) <= current
        ]
        seat = lambda g: g["spec"]["bots"].index(keys[bot_id])  # noqa: E731
        board.append(
            {
                "rank": rank,
                "id": bot_id,
                "above": above[bot_id],
                "won": sum(s > HALF for s in mine.values()),
                "drawn": sum(s == HALF for s in mine.values()),
                "lost": sum(s < HALF for s in mine.values()),
                "share": round(float(average(bot_id)), 4),
                "failures": sum(g["players"][seat(g)]["failures"] > 0 for g in played),
                "provisional": len(mine) < len(ids) - 1,
            }
        )
    head = {
        "ids": order,
        "shares": [
            [None if a == b or (a, b) not in share else round(float(share[a, b]), 4) for b in order]
            for a in order
        ],
        "games": [
            [[g["id"] for g in found[a, b].games] if (a, b) in found else [] for b in order]
            for a in order
        ],
    }
    return board, head


def solo_turns(season: Season, game: dict) -> int:
    """Turns to clear; the turn limit for a maze not cleared."""
    result = game["result"]
    if result["reason"] == "cleared" and result.get("cleared_turn"):
        return result["cleared_turn"]
    return 4 * season.width * season.height


def solo_board(season: Season, bots: list[dict], games: list[dict]) -> list[dict]:
    keys = {bot["id"]: f"{bot['id']}@{bot['version']}" for bot in bots}
    yardstick = keys.get(YARDSTICK)
    solo: dict[tuple[str, str, int], dict] = {}
    for game in games:
        spec = game["spec"]
        if spec["kind"] == "solo" and spec.get("season") == season.name:
            solo[spec["bots"][0], spec["mazes_of"], spec["maze"]] = game
    rows = []
    for bot_id, key in sorted(keys.items()):
        ratios, cleared = [], 0
        for maze in range(season.solo_mazes):
            own = solo.get((key, key, maze))
            reference = solo.get((yardstick, key, maze)) if yardstick else None
            if own is None or reference is None:
                continue
            cleared += own["result"]["reason"] == "cleared"
            ratios.append(Fraction(solo_turns(season, own), solo_turns(season, reference)))
        ratio = sum(ratios, Fraction(0)) / len(ratios) if ratios else None
        rows.append(
            {
                "id": bot_id,
                "ratio": None if ratio is None else round(float(ratio), 4),
                "cleared": cleared,
                "mazes": len(ratios),
                "provisional": len(ratios) < season.solo_mazes,
                "_exact": ratio,
            }
        )
    rows.sort(key=lambda r: (r["_exact"] is None, r["_exact"] or 0, -r["cleared"], r["id"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        del row["_exact"]
    return rows


def standings(season: Season, bots: list[dict], games: list[dict], commit: str) -> dict:
    duo, head = duo_board(season, bots, games)
    return {
        "season": season.name,
        "dedale": season.dedale,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "bots": bots,
        "duo": duo,
        "head_to_head": head,
        "solo": solo_board(season, bots, games),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--games", required=True, help="the games file")
    parser.add_argument("--bots", required=True, help="the pool, as `arena schedule` writes it")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    season = Season.load(ROOT / "season.json")
    bots = json.loads(Path(args.bots).read_text())
    result = standings(season, bots, read_games(Path(args.games)), head_commit())
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1))
    print(f"{len(result['duo'])} bots ranked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
