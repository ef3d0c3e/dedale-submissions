import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import dedale, write_bot
from tools.common import MAX_BOT_BYTES
from tools.validate import check, literal_version, main

SEASON = {
    "season": "test",
    "dedale": "0.1.0",
    "python": "3.12",
    "size": "11x11",
    "loops": 80,
    "points": 10,
    "mazes_per_pairing": 1,
    "solo_mazes": 1,
    "startup_ms": 2000,
    "move_ms": 100,
}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class Repo:
    """A repository with a base commit on `master` and a pull request on top."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q", "-b", "master")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "Test")
        (self.root / "MAINTAINERS").write_text("# maintainers\nboss\n")
        (self.root / "season.json").write_text(json.dumps(SEASON))
        (self.root / "README.md").write_text("readme\n")
        write_bot(self.root, "_baseline/greedy", name="Greedy", move="right")
        write_bot(self.root, "ada/wall", name="Wall")
        self.commit("base")
        git(self.root, "branch", "base")

    def commit(self, message: str) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "--allow-empty", "-m", message)

    def check(self, author: str, games: bool = False, tool: str | None = None):
        self.commit("pull request")
        return check(self.root, "base", author, tool, games=games)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()


class PathTests(unittest.TestCase):
    def test_only_your_own_folder(self):
        with Repo() as repo:
            (repo.root / "README.md").write_text("changed\n")
            write_bot(repo.root, "ada/wall", name="Wall", version=2)
            report = repo.check("bob")
            self.assertEqual(len(report.errors), 2, report.errors)
            self.assertTrue(all("outside `bots/bob/`" in e for e in report.errors))

    def test_maintainers_may_change_anything(self):
        with Repo() as repo:
            (repo.root / "README.md").write_text("changed\n")
            write_bot(repo.root, "_baseline/greedy", name="Greedy", version=2)
            report = repo.check("Boss")
            self.assertEqual([e for e in report.errors if "outside" in e], [], report.errors)

    def test_a_pull_request_cannot_make_its_author_a_maintainer(self):
        with Repo() as repo:
            (repo.root / "MAINTAINERS").write_text("boss\neve\n")
            write_bot(repo.root, "_baseline/greedy", name="Greedy", version=2)
            report = repo.check("eve")
            self.assertEqual(len([e for e in report.errors if "outside" in e]), 2, report.errors)

    def test_files_belong_in_a_bot_folder(self):
        with Repo() as repo:
            (repo.root / "bots" / "bob").mkdir(parents=True)
            (repo.root / "bots" / "bob" / "notes.txt").write_text("hi\n")
            report = repo.check("bob")
            self.assertIn("not inside a bot's folder", report.errors[0])

    def test_folders(self):
        with Repo() as repo:
            write_bot(repo.root, "bob/Loud")
            (repo.root / "bots" / "bob" / "empty").mkdir()
            (repo.root / "bots" / "bob" / "empty" / "data.txt").write_text("no entry\n")
            big = write_bot(repo.root, "bob/big")
            with open(big / "table.bin", "wb") as file:
                file.truncate(MAX_BOT_BYTES + 1)
            linked = write_bot(repo.root, "bob/linked")
            (linked / "data").symlink_to("/etc/passwd")
            report = repo.check("bob")
            joined = "\n".join(report.errors)
            self.assertIn("`bob/Loud`: its name is not lower-case", joined)
            self.assertIn("`bob/empty`: no `main.py`", joined)
            self.assertIn("`bob/big`: 10.0 MiB, more than 10 MiB", joined)
            self.assertIn("`bob/linked`: `data` is a symbolic link", joined)

    def test_removing_your_bot(self):
        with Repo() as repo:
            git(repo.root, "rm", "-q", "-r", "bots/ada/wall")
            report = repo.check("ada")
            self.assertEqual(report.errors, [])
            self.assertEqual(report.bots["ada/wall"], ["✓ removed"])

    def test_checking_another_checkout(self):
        with Repo() as repo:
            write_bot(repo.root, "bob/runner", name="Runner")
            repo.commit("pull request")
            args = ["--author", "eve", "--base", "base", "--root", str(repo.root), "--no-games"]
            self.assertEqual(main(args), 1, "bob's folder is not eve's")

    def test_nothing_to_check(self):
        with Repo() as repo:
            report = repo.check("ada")
            self.assertEqual(report.errors, [])
            self.assertIn("No bot changed.", report.markdown())


class VersionTests(unittest.TestCase):
    def test_literal_version(self):
        self.assertEqual(literal_version("VERSION = 3\n"), 3)
        self.assertEqual(literal_version("VERSION = 1\nVERSION = 4\n"), 4)
        self.assertEqual(literal_version("VERSION: int = 2\n"), 2)
        for source in ["VERSION = True\n", "VERSION = 0\n", "VERSION = '3'\n", "VERSION = 1 + 1\n",
                       "if x:\n    VERSION = 3\n", "VERSION = (\n", "", "VERSION = 4294967296\n"]:
            self.assertIsNone(literal_version(source), source)


@unittest.skipUnless(dedale(), "needs Dedale (DEDALE or dedale on the PATH)")
class IdentityTests(unittest.TestCase):
    def test_a_new_bot_starts_at_version_1(self):
        with Repo() as repo:
            write_bot(repo.root, "bob/runner", name="Runner", version=2)
            report = repo.check("bob", tool=dedale())
            self.assertIn("starts at version 1, not 2", report.errors[0])

    def test_a_changed_bot_raises_its_version(self):
        with Repo() as repo:
            (repo.root / "bots" / "ada" / "wall" / "data.txt").write_text("new\n")
            report = repo.check("ada", tool=dedale())
            self.assertIn("still at version 1", report.errors[0])
        with Repo() as repo:
            write_bot(repo.root, "ada/wall", name="Wall", version=2)
            report = repo.check("ada", tool=dedale())
            self.assertEqual(report.errors, [])
            self.assertIn("✓ Wall by ada, version 2", report.bots["ada/wall"])

    def test_who_it_is(self):
        with Repo() as repo:
            write_bot(repo.root, "bob/anonymous", source="VERSION = 1\ndef move():\n    return 'stay'\n")
            write_bot(repo.root, "bob/copy", name="WALL")
            report = repo.check("bob", tool=dedale())
            joined = "\n".join(report.errors)
            self.assertIn("`bob/anonymous`: no `NAME`, `AUTHOR`, `DESCRIPTION`", joined)
            self.assertIn("`bob/copy`: its name, 'WALL', is taken by `ada/wall`", joined)

    def test_smoke_games(self):
        with Repo() as repo:
            write_bot(repo.root, "bob/runner", name="Runner", move="down")
            write_bot(
                repo.root,
                "bob/broken",
                source='NAME = "Broken"\nAUTHOR = "bob"\nDESCRIPTION = "x"\nVERSION = 1\n'
                "def init():\n    raise RuntimeError('no luck')\n"
                "def move():\n    return 'stay'\n",
            )
            write_bot(
                repo.root,
                "bob/quitter",
                source='NAME = "Quitter"\nAUTHOR = "bob"\nDESCRIPTION = "x"\nVERSION = 1\n'
                "import sys\ndef move():\n    sys.exit(3)\n",
            )
            report = repo.check("bob", games=True, tool=dedale())
            joined = "\n".join(report.errors)
            self.assertNotIn("bob/runner", joined)
            self.assertTrue(any(n.startswith("✓ played") for n in report.bots["bob/runner"]))
            self.assertIn("`bob/broken`: did not start: `init_error` (RuntimeError: no luck)", joined)
            self.assertIn("`bob/quitter`: crashed", joined)
            self.assertIn("**Refused**", report.markdown())
