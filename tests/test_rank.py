import unittest

from tests.helpers import bot, record
from tools.common import Season, duo_spec, solo_spec
from tools.rank import solo_board, standings

SEASON = Season("test", "0.1.0", 11, 11, 80, 10, 1, 2, 2000, 100)


def info(bot_id: str, version: int = 1) -> dict:
    return dict(bot(bot_id, version).about(), path=f"bots/{bot_id}/main.py")


def pairing(a: str, b: str, mine: int, theirs: int, va: int = 1, vb: int = 1) -> list[dict]:
    """Both corners of the season's maze, `a` scoring `mine` half-points in
    each against `b`'s `theirs`."""
    games = []
    for swapped in (False, True):
        spec = duo_spec(SEASON, bot(a, va), bot(b, vb), 0, swapped)
        first = spec["bots"][0].split("@")[0]
        points = [mine, theirs] if first == a else [theirs, mine]
        games.append(record(spec, points))
    return games


def order(result: dict) -> list[str]:
    return [row["id"] for row in result["duo"]]


class DuoTests(unittest.TestCase):
    def test_a_bot_that_beats_all_is_first(self):
        bots = [info(i) for i in ("a/x", "b/y", "c/z")]
        games = pairing("c/z", "a/x", 11, 9) + pairing("c/z", "b/y", 6, 4) + pairing("a/x", "b/y", 7, 3)
        result = standings(SEASON, bots, games, "abc")
        self.assertEqual(order(result), ["c/z", "a/x", "b/y"])
        first = result["duo"][0]
        self.assertEqual((first["won"], first["drawn"], first["lost"]), (2, 0, 0))
        self.assertFalse(first["provisional"])

    def test_a_cycle_is_settled_by_the_strength_of_the_wins(self):
        # x beats y (60%), y beats z (70%), z beats x (55%): the weakest win
        # gives way, so x is first.
        bots = [info(i) for i in ("a/x", "b/y", "c/z")]
        games = pairing("a/x", "b/y", 6, 4) + pairing("b/y", "c/z", 7, 3) + pairing("c/z", "a/x", 11, 9)
        self.assertEqual(order(standings(SEASON, bots, games, "abc")), ["a/x", "b/y", "c/z"])

    def test_a_weak_bot_lifts_nobody(self):
        # x beats y, but y crushes w harder than x does: an average of shares
        # would put y first; head to head, x stays first.
        bots = [info(i) for i in ("a/x", "b/y", "c/w")]
        games = pairing("a/x", "b/y", 6, 4) + pairing("a/x", "c/w", 7, 3) + pairing("b/y", "c/w", 99, 1)
        result = standings(SEASON, bots, games, "abc")
        self.assertEqual(order(result), ["a/x", "b/y", "c/w"])
        shares = {row["id"]: row["share"] for row in result["duo"]}
        self.assertGreater(shares["b/y"], shares["a/x"])

    def test_copies_lift_nobody(self):
        bots = [info(i) for i in ("a/x", "b/y", "c/z")]
        games = pairing("a/x", "b/y", 6, 4) + pairing("b/y", "c/z", 6, 4) + pairing("a/x", "c/z", 6, 4)
        before = order(standings(SEASON, bots, games, "abc"))
        # z's copy: the same results against everyone, even against z.
        copy = pairing("a/x", "d/z2", 6, 4) + pairing("b/y", "d/z2", 6, 4) + pairing("c/z", "d/z2", 5, 5)
        after = order(standings(SEASON, bots + [info("d/z2")], games + copy, "abc"))
        self.assertEqual([i for i in after if i != "d/z2"], before)

    def test_even_pairings_and_missing_ones(self):
        bots = [info(i) for i in ("a/x", "b/y", "c/z")]
        games = pairing("a/x", "b/y", 5, 5) + pairing("a/x", "c/z", 6, 4)
        result = standings(SEASON, bots, games, "abc")
        rows = {row["id"]: row for row in result["duo"]}
        self.assertEqual(rows["a/x"]["drawn"], 1)
        self.assertTrue(rows["b/y"]["provisional"], "b and c never played")
        self.assertFalse(rows["a/x"]["provisional"])
        head = result["head_to_head"]
        i, j = head["ids"].index("b/y"), head["ids"].index("c/z")
        self.assertIsNone(head["shares"][i][j])
        self.assertEqual(head["games"][i][j], [])

    def test_half_a_pairing_counts_for_nothing(self):
        bots = [info(i) for i in ("a/x", "b/y")]
        result = standings(SEASON, bots, pairing("a/x", "b/y", 9, 1)[:1], "abc")
        self.assertTrue(all(row["provisional"] for row in result["duo"]))

    def test_only_current_versions(self):
        bots = [info("a/x"), info("b/y", 2)]
        old = pairing("a/x", "b/y", 9, 1, vb=1)
        new = pairing("a/x", "b/y", 2, 8, vb=2)
        self.assertEqual(order(standings(SEASON, bots, old + new, "abc")), ["b/y", "a/x"])

    def test_failures_count_games(self):
        bots = [info(i) for i in ("a/x", "b/y")]
        games = pairing("a/x", "b/y", 6, 4)
        games[0]["players"][0]["failures"] = 3
        rows = {row["id"]: row for row in standings(SEASON, bots, games, "abc")["duo"]}
        self.assertEqual((rows["a/x"]["failures"], rows["b/y"]["failures"]), (1, 0))


def solo(bot_id: str, owner: str, maze: int, turns: int, cleared: bool = True) -> dict:
    spec = solo_spec(SEASON, bot(bot_id), bot(owner), maze)
    return record(spec, [10], turns, "cleared" if cleared else "turn_limit")


class SoloTests(unittest.TestCase):
    def test_turns_relative_to_greedy(self):
        greedy, fast, slow = "_baseline/greedy", "a/fast", "b/slow"
        bots = [info(greedy), info(fast), info(slow)]
        games = [
            solo(greedy, greedy, 0, 100), solo(greedy, greedy, 1, 100),
            solo(fast, fast, 0, 80), solo(fast, fast, 1, 90),
            solo(greedy, fast, 0, 100), solo(greedy, fast, 1, 100),
            solo(slow, slow, 0, 120), solo(slow, slow, 1, 484, cleared=False),
            solo(greedy, slow, 0, 100), solo(greedy, slow, 1, 121),
        ]
        board = {row["id"]: row for row in solo_board(SEASON, bots, games)}
        self.assertEqual(board[fast]["ratio"], 0.85)
        self.assertEqual(board[greedy]["ratio"], 1.0)
        # Not cleared: the turn limit, 4·11·11 = 484 turns.
        self.assertEqual(board[slow]["ratio"], round((1.2 + 484 / 121) / 2, 4))
        self.assertEqual(board[slow]["cleared"], 1)
        self.assertEqual([board[i]["rank"] for i in (fast, greedy, slow)], [1, 2, 3])

    def test_missing_mazes(self):
        bots = [info("_baseline/greedy"), info("a/fast")]
        games = [solo("a/fast", "a/fast", 0, 80), solo("_baseline/greedy", "a/fast", 0, 100)]
        board = {row["id"]: row for row in solo_board(SEASON, bots, games)}
        self.assertTrue(board["a/fast"]["provisional"])
        self.assertEqual(board["a/fast"]["mazes"], 1)
        self.assertIsNone(board["_baseline/greedy"]["ratio"])
        self.assertEqual(board["_baseline/greedy"]["rank"], 2)
