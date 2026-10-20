import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import bot, dedale, record, write_bot
from tools.common import (
    LOGIN,
    Season,
    about,
    bot_dirs,
    check_game,
    duo_spec,
    game_id,
    maze_seed,
    read_bots,
    read_games,
    solo_spec,
    spec_seed,
    swapped_mazes,
    write_games,
)

SEASON = Season("test", "0.1.0", 31, 31, 80, 50, 4, 4, 2000, 100, "3.12")


class SeasonTests(unittest.TestCase):
    def test_the_repository_season_loads(self):
        season = Season.load()
        self.assertGreater(season.mazes_per_pairing, 0)
        self.assertEqual(season.width % 2, 1)

    def test_maze_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "season.json"
            path.write_text(
                json.dumps(
                    {
                        "season": "s",
                        "dedale": "0.1.0",
                        "python": "3.11",
                        "size": "21x11",
                        "loops": 50,
                        "points": 30,
                        "mazes_per_pairing": 2,
                        "solo_mazes": 1,
                        "startup_ms": 1000,
                        "move_ms": 50,
                    }
                )
            )
            season = Season.load(path)
        self.assertEqual((season.width, season.height), (21, 11))
        self.assertEqual(season.python, "3.11")
        args = season.maze_args("00ff")
        self.assertEqual(args[args.index("--size") + 1], "21x11")
        self.assertEqual(args[args.index("--seed") + 1], "00ff")
        self.assertEqual(args[args.index("--move-ms") + 1], "50")


class BotTests(unittest.TestCase):
    def test_bot_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_bot(root, "ada/wall")
            write_bot(root, "_baseline/greedy")
            (root / "bots" / "stray.txt").write_text("not a user")
            (root / "bots" / "ada" / "notes.txt").write_text("not a bot")
            (root / "bots" / "ada" / "link").symlink_to(root / "bots" / "ada" / "wall")
            self.assertEqual([i for i, _ in bot_dirs(root)], ["_baseline/greedy", "ada/wall"])

    def test_keys_and_baselines(self):
        self.assertEqual(bot("ada/wall", 3).key, "ada/wall@3")
        self.assertTrue(bot("_baseline/greedy").baseline)
        self.assertFalse(bot("ada/wall").baseline)

    def test_logins(self):
        for login in ["ada", "Ada-Lovelace", "a1", "x" * 39]:
            self.assertTrue(LOGIN.fullmatch(login), login)
        for login in ["_baseline", "-ada", "ada-", "a--b", "x" * 40, "a.b", ""]:
            self.assertFalse(LOGIN.fullmatch(login), login)

    @unittest.skipUnless(dedale(), "needs Dedale (DEDALE or dedale on the PATH)")
    def test_what_bots_say(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_bot(root, "ada/wall", name="Wall", version=3)
            write_bot(root, "bob/mute", source="def move():\n    return 'stay'\n")
            bots = read_bots(dedale(), root)
            self.assertEqual([b.id for b in bots], ["ada/wall", "bob/mute"])
            wall, mute = bots
            self.assertEqual((wall.name, wall.author, wall.version), ("Wall", "ada", 3))
            self.assertTrue(wall.said_hello)
            self.assertEqual((mute.name, mute.version), (None, None))
            self.assertTrue(mute.said_hello)
            silent = about(dedale(), [("eve/none", root / "missing.py")])
            self.assertEqual(silent[0].version, None)


class GameTests(unittest.TestCase):
    def test_maze_seeds(self):
        secret = b"secret"
        self.assertEqual(maze_seed(secret, "a", "b"), maze_seed(secret, "a", "b"))
        self.assertNotEqual(maze_seed(secret, "a", "b"), maze_seed(secret, "a", "c"))
        self.assertNotEqual(maze_seed(secret, "a"), maze_seed(b"other", "a"))
        self.assertEqual(len(maze_seed(None, "a")), 16)
        self.assertNotEqual(maze_seed(None, "a"), maze_seed(None, "a"))

    def test_duo_mazes(self):
        a, b = bot("ada/wall"), bot("bob/runner", 2)
        spec = duo_spec(SEASON, b, a, 1)
        self.assertEqual(spec, duo_spec(SEASON, a, b, 1))
        self.assertEqual(spec["bots"], ["ada/wall@1", "bob/runner@2"])
        self.assertNotIn("swapped", spec, "the corner is drawn, not part of what the game is")
        self.assertEqual(spec_seed(b"s", spec), spec_seed(b"s", spec))
        self.assertNotEqual(spec_seed(b"s", spec), spec_seed(b"s", duo_spec(SEASON, a, b, 2)))
        # A new version plays new mazes.
        newer = duo_spec(SEASON, a, bot("bob/runner", 3), 1)
        self.assertNotEqual(spec_seed(b"s", spec), spec_seed(b"s", newer))
        self.assertEqual(len(spec_seed(None, spec)), 16)

    def test_corners_split_evenly(self):
        a = bot("ada/wall")
        draws = []
        for other in ("bob/runner", "cleo/fast", "dan/slow"):
            specs = [duo_spec(SEASON, a, bot(other), maze) for maze in range(20)]
            swapped = swapped_mazes(b"s", specs)
            self.assertEqual(len(swapped), 10)
            self.assertEqual(swapped, swapped_mazes(b"s", list(reversed(specs))))
            self.assertEqual(len(swapped_mazes(None, specs)), 10)
            draws.append(swapped)
        self.assertEqual(len({frozenset(d) for d in draws}), 3, "each pairing draws its own half")
        self.assertEqual(len(swapped_mazes(b"s", specs[:5])), 2)

    def test_the_yardstick_plays_a_bots_own_solo_mazes(self):
        wall, greedy = bot("ada/wall"), bot("_baseline/greedy")
        own = solo_spec(SEASON, wall, wall, 0)
        yardstick = solo_spec(SEASON, greedy, wall, 0)
        self.assertEqual(spec_seed(b"s", own), spec_seed(b"s", yardstick))
        self.assertNotEqual(game_id(own), game_id(yardstick))

    def test_the_games_file(self):
        a, b = bot("ada/wall"), bot("bob/runner")
        games = [
            record(duo_spec(SEASON, a, b, 0), [60, 40]),
            record(solo_spec(SEASON, a, a, 0), [100]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "games.json.gz"
            self.assertEqual(read_games(path), [])
            write_games(path, games)
            first = path.read_bytes()
            self.assertEqual(sorted(g["id"] for g in read_games(path)), sorted(g["id"] for g in games))
            write_games(path, list(reversed(games)))
            self.assertEqual(path.read_bytes(), first, "the same games make the same bytes")

    def test_malformed_games_are_refused(self):
        good = record(duo_spec(SEASON, bot("ada/wall"), bot("bob/runner"), 0), [60, 40])
        check_game(good)
        broken = [
            dict(good, id="0" * 16),
            dict(good, result=dict(good["result"], half_points=[60])),
            dict(good, result=dict(good["result"], half_points=[60, -1])),
            dict(good, players=[{"startup": "ok", "failures": 0}]),
            {key: value for key, value in good.items() if key != "code"},
            dict(good, swapped="yes"),
            dict(good, spec=dict(good["spec"], kind="trio")),
            "a game",
        ]
        for game in broken:
            with self.subTest(game=game), self.assertRaises(ValueError):
                check_game(game)
