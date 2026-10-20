import tempfile
import unittest
from pathlib import Path

from tests.helpers import bot, record
from tests.test_rank import SEASON, info, pairing
from tools.common import solo_spec, write_games
from tools.rank import standings
from tools.site import build, replay_command, shade

HOSTILE = '<script>alert("pwned")</script> & co'


class SiteTests(unittest.TestCase):
    def setUp(self):
        hostile = dict(info("eve/sly"), name=HOSTILE, description=HOSTILE, author="<b>eve</b>")
        self.bots = [info("_baseline/greedy"), info("a/x"), hostile]
        self.games = (
            pairing("a/x", "_baseline/greedy", 7, 3)
            + pairing("a/x", "eve/sly", 6, 4)
            + pairing("eve/sly", "_baseline/greedy", 5, 5)
            + [record(solo_spec(SEASON, bot("a/x"), bot("a/x"), 0), [10], 90)]
        )
        self.standings = standings(SEASON, self.bots, self.games, "f" * 40)

    def build(self, out: Path) -> None:
        games_file = out.parent / "games.json.gz"
        write_games(games_file, self.games)
        build(self.standings, self.games, out, games_file)

    def test_the_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            for name in ["index.html", "style.css", "standings.json", "games.json.gz",
                         "bots/a/x.html", "bots/_baseline/greedy.html", "bots/eve/sly.html"]:
                self.assertTrue((out / name).exists(), name)
            index = (out / "index.html").read_text()
            self.assertIn('href="bots/a/x.html">x v1</a>', index)
            self.assertIn('<span class="tag">baseline</span>', index)
            self.assertIn("70.0%", index.replace("65.0%", "70.0%"))
            page = (out / "bots" / "a" / "x.html").read_text()
            self.assertIn('id="vs-eve-sly"', page)
            self.assertIn("3.5 to 1.5", page)
            self.assertIn("../../style.css", page)

    def test_the_season_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            index = (out / "index.html").read_text()
            self.assertIn("11×11 mazes with 10 points and\n80% loops; 2 s to start, 100 ms per move.", index)
            self.assertIn("Each pair of bots plays 2 games, 1 fresh maze from both corners.", index)
            self.assertIn("Each bot clears 2 mazes alone", index)

    def test_bot_text_stays_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            for name in ["index.html", "bots/eve/sly.html", "bots/a/x.html"]:
                text = (out / name).read_text()
                self.assertNotIn("<script>", text, name)
                self.assertNotIn("<b>eve</b>", text, name)
            self.assertIn("&lt;script&gt;", (out / "bots" / "eve" / "sly.html").read_text())

    def test_replay_commands(self):
        swapped = next(g for g in self.games if g["spec"].get("swapped"))
        command = replay_command(swapped)
        self.assertTrue(command.startswith(f"git checkout {swapped['commit']}\ndedale run bots/"))
        self.assertIn(f"--maze {swapped['code']} --swap --startup-ms 2000 --move-ms 100", command)
        solo = self.games[-1]
        self.assertIn("dedale run bots/a/x/main.py --maze", replay_command(solo))
        self.assertNotIn("--swap", replay_command(solo))

    def test_corners(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            page = (out / "bots" / "a" / "x.html").read_text()
            self.assertEqual(page.count("from the top-left corner"), page.count("from the bottom-right corner"))

    def test_shades(self):
        self.assertEqual([shade(s) for s in (0.5, 0.52, 0.6, 0.9, 0.45, 0.2)], ["", "w1", "w2", "w3", "l2", "l3"])
