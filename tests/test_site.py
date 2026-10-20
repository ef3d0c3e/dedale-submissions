import re
import subprocess
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests.helpers import bot, chromium, record
from tests.test_rank import SEASON, info, pairing
from tools.common import solo_spec, write_games
from tools.rank import standings
from tools.site import build, replay_command, shade

HOSTILE = '<script>alert("pwned")</script> & co'


class Built(unittest.TestCase):
    """Three bots, one with hostile text, and their games."""

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


class SiteTests(Built):
    def test_the_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            for name in ["index.html", "style.css", "sort.js", "standings.json", "games.json.gz",
                         "bots/a/x.html", "bots/_baseline/greedy.html", "bots/eve/sly.html"]:
                self.assertTrue((out / name).exists(), name)
            index = (out / "index.html").read_text()
            self.assertIn('href="bots/a/x.html">x v1</a>', index)
            self.assertIn('<span class="tag">baseline</span>', index)
            # x: 70% of the points against greedy, 60% against sly.
            self.assertIn('<tr data-points="0.65" data-winrate="1" data-pairings="2" data-schulze="1"', index)
            self.assertIn('<td class="num">65.0</td><td class="num">100.0% <span class="muted">4–0–0</span>', index)
            self.assertIn('<script src="sort.js" defer></script>', index)
            page = (out / "bots" / "a" / "x.html").read_text()
            self.assertIn('id="vs-eve-sly"', page)
            self.assertIn("<p>2 won, 0 drawn, 0 lost</p>", page)
            self.assertIn("3.5 to 1.5", page)
            self.assertIn("../../style.css", page)
            self.assertNotIn("<script", page)

    def test_only_the_sites_own_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            for name in ["index.html", "bots/a/x.html"]:
                text = (out / name).read_text()
                self.assertIn("default-src 'none'; style-src 'self'; script-src 'self'", text, name)
                self.assertNotRegex(text, r"<script>|\sstyle=|\son[a-z]+=", name)

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


@unittest.skipUnless(chromium(), "needs Chromium (CHROMIUM, or chromium or google-chrome on the PATH)")
class SortTests(Built):
    """The boards' script, run by a headless browser on the built site."""

    def board(self, fragment: str) -> str:
        """The duo board once the index has loaded with `fragment`."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            self.build(out)
            handler = partial(Quiet, directory=str(out))
            with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                threading.Thread(target=server.serve_forever, daemon=True).start()
                url = f"http://127.0.0.1:{server.server_address[1]}/index.html#{fragment}"
                done = subprocess.run(
                    [chromium(), "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
                     f"--user-data-dir={tmp}/profile", "--virtual-time-budget=5000", "--dump-dom", url],
                    capture_output=True, text=True, timeout=120,
                )
                server.shutdown()
        self.assertEqual(done.returncode, 0, done.stderr)
        dom = done.stdout
        start = dom.index('data-board="duo"')
        return dom[start:dom.index("</table>", start)]

    def rows(self, board: str) -> list[tuple[str, str]]:
        return re.findall(r'<tr data-points[^>]*><td class="num">(\d+)</td><td><a href="bots/([^"]+)\.html"', board)

    def test_the_default_order(self):
        board = self.board("")
        self.assertEqual(self.rows(board), [("1", "a/x"), ("2", "eve/sly"), ("3", "_baseline/greedy")])
        self.assertIn("<button", board, "the headers became buttons")

    def test_an_order_from_the_address(self):
        board = self.board("duo=-points")
        self.assertEqual(self.rows(board), [("1", "_baseline/greedy"), ("2", "eve/sly"), ("3", "a/x")])
        self.assertRegex(board, r'data-key="points"[^>]*aria-sort="ascending"')

    def test_ties_keep_the_default_order(self):
        # sly and greedy both won a quarter of their games.
        board = self.board("duo=winrate")
        self.assertEqual(self.rows(board), [("1", "a/x"), ("2", "eve/sly"), ("3", "_baseline/greedy")])
        self.assertNotRegex(board, r'data-key="points"[^>]*aria-sort')


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass
