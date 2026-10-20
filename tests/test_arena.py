import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import bot, dedale, record, write_bot
from tools.arena import main, merge, missing, record as record_game, shards
from tools.common import Season, duo_spec, read_games, solo_spec

SEASON = Season("test", "0.1.0", 11, 11, 80, 10, 2, 1, 2000, 100)
POOL = [bot("_baseline/greedy"), bot("ada/wall"), bot("bob/runner", 2)]


def involved(game: dict) -> set[str]:
    """Who a game is for: its players, and whose solo maze it is."""
    return {*game["spec"]["bots"], game["spec"].get("mazes_of")}


class ScheduleTests(unittest.TestCase):
    def test_every_game_once(self):
        games = missing(SEASON, POOL, set(), b"secret")
        duo = [g for g in games if g["spec"]["kind"] == "duo"]
        solo = [g for g in games if g["spec"]["kind"] == "solo"]
        # 3 pairings, 2 mazes, one game each.
        self.assertEqual(len(duo), 3 * 2)
        self.assertTrue(all(isinstance(g["swapped"], bool) for g in games))
        # Each bot's own maze, and the yardstick on the two others'.
        self.assertEqual(len(solo), 3 + 2)
        self.assertEqual(len({g["id"] for g in games}), len(games))
        self.assertEqual(games, missing(SEASON, list(reversed(POOL)), set(), b"secret"))

    def test_seats_follow_the_spec(self):
        games = missing(SEASON, POOL, set(), b"secret")
        for game in games:
            seats = [path.split("/")[1] + "/" + path.split("/")[2] for path in game["bots"]]
            ids = [key.split("@")[0] for key in game["spec"]["bots"]]
            if game["spec"]["kind"] == "duo":
                self.assertEqual(seats, ids)

    def test_played_games_are_left_out(self):
        games = missing(SEASON, POOL, set(), b"secret")
        done = {game["id"] for game in games[:5]}
        self.assertEqual(missing(SEASON, POOL, done, b"secret"), games[5:])

    def test_a_new_bot_plays_only_its_own_games(self):
        done = {g["id"] for g in missing(SEASON, POOL, set(), b"secret")}
        todo = missing(SEASON, [*POOL, bot("cleo/new")], done, b"secret")
        self.assertTrue(all("cleo/new@1" in involved(game) for game in todo))
        # Against each of the 3 bots, 2 mazes; its solo maze, alone and by
        # the yardstick.
        self.assertEqual(len([g for g in todo if g["spec"]["kind"] == "duo"]), 3 * 2)
        self.assertEqual(len([g for g in todo if g["spec"]["kind"] == "solo"]), 2)

    def test_a_new_version_plays_only_its_own_games(self):
        done = {g["id"] for g in missing(SEASON, POOL, set(), b"secret")}
        todo = missing(SEASON, [POOL[0], POOL[1], bot("bob/runner", 3)], done, b"secret")
        self.assertTrue(all("bob/runner@3" in involved(game) for game in todo))
        self.assertEqual(len([g for g in todo if g["spec"]["kind"] == "duo"]), 2 * 2)
        self.assertEqual(len([g for g in todo if g["spec"]["kind"] == "solo"]), 2)

    def test_shards_keep_groups_whole(self):
        games = missing(SEASON, POOL, set(), b"secret")
        split = shards(games, 4)
        self.assertEqual(len(split), 4)
        self.assertEqual(sum(len(s) for s in split), len(games))
        for group in {g["group"] for g in games}:
            holding = [i for i, s in enumerate(split) if any(g["group"] == group for g in s)]
            self.assertEqual(len(holding), 1, group)
        self.assertEqual(shards([], 3), [[], [], []])


REPLAY = {
    "code": "ded2-11x11-l80-p10-00000000000000ff",
    "dedale": "0.1.0",
    "config": {"startup_ms": 2000, "move_ms": 100, "max_turns": 484, "seating": "duo"},
    "result": {"reason": "cleared", "turns": 40, "half_points": [12, 8], "winner": 0, "cleared_turn": 40},
    "players": [{"startup": {"outcome": "ok"}}, {"startup": {"outcome": "late"}}],
    "stats": [
        {"outcomes": {"ok": 40, "illegal": 0, "timeout": 0}},
        {"outcomes": {"ok": 30, "illegal": 4, "timeout": 6}},
    ],
}


class RecordTests(unittest.TestCase):
    def test_what_a_game_keeps(self):
        spec = duo_spec(SEASON, POOL[1], POOL[2], 0)
        game = record_game(spec, REPLAY, "abc")
        self.assertFalse(game["swapped"])
        swapped = dict(REPLAY, config=dict(REPLAY["config"], seating="duo_swapped"))
        self.assertTrue(record_game(spec, swapped, "abc")["swapped"])
        self.assertEqual(game["code"], REPLAY["code"])
        self.assertEqual(game["result"]["half_points"], [12, 8])
        self.assertEqual(game["players"], [{"startup": "ok", "failures": 0}, {"startup": "late", "failures": 10}])
        self.assertEqual((game["commit"], game["dedale"], game["move_ms"]), ("abc", "0.1.0", 100))

    def test_merging(self):
        a = record(duo_spec(SEASON, POOL[1], POOL[2], 0), [12, 8])
        b = record(solo_spec(SEASON, POOL[1], POOL[1], 0), [20])
        with tempfile.TemporaryDirectory() as tmp:
            shard = Path(tmp) / "shard.json"
            shard.write_text(json.dumps({"games": [a, b], "errors": [{"id": "x", "error": "boom"}]}))
            games, errors = merge([a], [shard])
            self.assertEqual(sorted(g["id"] for g in games), sorted([a["id"], b["id"]]))
            self.assertEqual(errors, [{"id": "x", "error": "boom"}])
            shard.write_text(json.dumps({"games": [dict(b, id="0" * 16)]}))
            with self.assertRaises(ValueError):
                merge([], [shard])


@unittest.skipUnless(dedale(), "needs Dedale (DEDALE or dedale on the PATH)")
class TournamentTests(unittest.TestCase):
    def test_a_whole_tournament_then_only_whats_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "season.json").write_text(
                json.dumps(
                    {
                        "season": "test",
                        "dedale": "0.1.0",
                        "size": "11x11",
                        "loops": 80,
                        "points": 10,
                        "mazes_per_pairing": 1,
                        "solo_mazes": 1,
                        "startup_ms": 2000,
                        "move_ms": 100,
                    }
                )
            )
            write_bot(root, "_baseline/greedy", name="Greedy", move="right")
            write_bot(root, "ada/down", name="Down", move="down")
            games = root / "out" / "games.json.gz"
            import tools.arena as arena

            run = lambda: arena.run_command(  # noqa: E731
                type("Args", (), {"dedale": dedale(), "sandbox": False, "games": str(games)}), root
            )
            self.assertEqual(run(), 0)
            played = read_games(games)
            # One pairing on one maze, two own solo mazes, one yardstick game.
            self.assertEqual(len(played), 1 + 2 + 1)
            self.assertTrue(all(isinstance(g["swapped"], bool) for g in played))
            solo = {(g["spec"]["bots"][0], g["spec"]["mazes_of"]): g["code"] for g in played if g["spec"]["kind"] == "solo"}
            self.assertEqual(solo[("_baseline/greedy@1", "ada/down@1")], solo[("ada/down@1", "ada/down@1")])
            self.assertTrue(all(len(g["result"]["half_points"]) == len(g["spec"]["bots"]) for g in played))
            self.assertTrue(all(g["code"].startswith("ded2-11x11-l80-p10-") for g in played))
            bots = json.loads((games.parent / "bots.json").read_text())
            self.assertEqual([b["id"] for b in bots], ["_baseline/greedy", "ada/down"])

            write_bot(root, "ada/down", name="Down", move="down", version=2)
            self.assertEqual(run(), 0)
            again = read_games(games)
            # The new version: the pairing again, its solo maze and the yardstick's.
            self.assertEqual(len(again), len(played) + 1 + 1 + 1)

    def test_the_command_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(main(["merge", "--games", str(out / "g.json.gz"), "--out", str(out / "g.json.gz")]), 0)
            self.assertEqual(read_games(out / "g.json.gz"), [])
