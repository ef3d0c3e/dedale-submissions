import json
import re
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.test_rank import SEASON
from tools.bot_python import LIBRARIES, PYPI, build, main, parse, pin, read_libraries
from tools.common import ROOT

A, B = "a" * 64, "b" * 64
WORKFLOWS = ROOT / ".github" / "workflows"
# How a workflow makes the bots' Python and hands it to Dedale.
STEP = 'python=$(python3 -m tools.bot_python build --out "$RUNNER_TEMP/bot-python")'


class ParseTests(unittest.TestCase):
    def test_pins_with_hashes(self):
        text = (
            f"# why\nNumPy==2.5.4 \\\n    --hash=sha256:{A} \\\n    --hash=sha256:{B}\n\n"
            f"scipy==1.18.1 --hash=sha256:{A}  # note\n"
        )
        self.assertEqual(parse(text), {"numpy": "2.5.4", "scipy": "1.18.1"})
        self.assertEqual(parse("# nothing yet\n"), {})

    def test_loose_or_unhashed_pins_are_refused(self):
        for text in ["numpy>=2.5\n", "numpy\n", "numpy==2.5.4\n", "-r other.txt\n"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse(text)

    def test_the_seasons_libraries(self):
        self.assertEqual(read_libraries(), {"numpy": "2.5.4", "scipy": "1.18.1", "networkx": "3.7"})
        # Every file of each release: wheels for every platform, not just CI's.
        self.assertGreater(LIBRARIES.read_text().count("--hash=sha256:"), 100)


def pypi(releases: dict[tuple[str, str], list[dict]]):
    def get(url: str) -> bytes:
        name, version, _ = url.removeprefix(f"{PYPI}/").split("/")
        return json.dumps({"urls": releases[(name, version)]}).encode()

    return get


def files(*hashes: str, yanked: bool = False) -> list[dict]:
    return [{"digests": {"sha256": h}, "yanked": yanked} for h in hashes]


class PinTests(unittest.TestCase):
    def test_every_files_hash(self):
        get = pypi({("numpy", "2.5.4"): files(B, A, A), ("networkx", "3.7"): files(A)})
        text = pin(["NumPy==2.5.4", "networkx==3.7"], get)
        self.assertEqual(parse(text), {"numpy": "2.5.4", "networkx": "3.7"})
        self.assertIn(f"numpy==2.5.4 \\\n    --hash=sha256:{A} \\\n    --hash=sha256:{B}\nnetworkx==3.7", text)
        self.assertTrue(text.startswith("# The libraries bots may import"))

    def test_what_cannot_be_pinned(self):
        get = pypi({("numpy", "1.0"): files(A, yanked=True), ("numpy", "0.1"): []})
        for requirement, why in [("numpy>=2", "NAME==VERSION"), ("numpy==1.0", "yanked"), ("numpy==0.1", "no files")]:
            with self.subTest(requirement=requirement), self.assertRaisesRegex(ValueError, why):
                pin([requirement], get)


class FakeRun:
    """Stands in for `subprocess.run`: records commands, answers a version."""

    def __init__(self, version: str):
        self.version = version
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=f"{self.version}\n")


class BuildTests(unittest.TestCase):
    def test_another_python_is_refused(self):
        run = FakeRun("3.11")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, "Python 3.12, but .* Python 3.11"):
            build(Path(tmp) / "env", SEASON, "python3", LIBRARIES, run)
        self.assertEqual(len(run.commands), 1, "nothing made")

    def test_wheels_with_their_hashes_only(self):
        run = FakeRun("3.12")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "env"
            interpreter = build(out, SEASON, "python3", LIBRARIES, run)
        self.assertEqual(interpreter, out.resolve() / "bin" / "python")
        self.assertEqual(run.commands[1], ["python3", "-m", "venv", "--clear", str(out.resolve())])
        install = run.commands[2]
        self.assertEqual(install[:4], [str(interpreter), "-m", "pip", "install"])
        self.assertIn("--require-hashes", install)
        self.assertEqual(install[install.index("--only-binary") + 1], ":all:")
        self.assertEqual(install[-2:], ["--requirement", str(LIBRARIES)])

    def test_a_real_environment(self):
        version = "%d.%d" % sys.version_info[:2]
        with tempfile.TemporaryDirectory() as tmp:
            # No libraries, so nothing to download.
            libraries = Path(tmp) / "libraries.txt"
            libraries.write_text("# none\n")
            out = Path(tmp) / "env"
            interpreter = build(out, replace(SEASON, python=version), sys.executable, libraries)
            prefix = subprocess.run(
                [interpreter, "-c", "import sys; print(sys.prefix)"], check=True, capture_output=True, text=True
            ).stdout.strip()
            self.assertEqual(Path(prefix), out.resolve())

    def test_the_command_line_reports_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "no-python")
            self.assertEqual(main(["build", "--out", str(Path(tmp) / "env"), "--python", missing]), 1)


def jobs(path: Path) -> dict[str, str]:
    """A workflow's jobs, as name: text."""
    text = path.read_text().split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z][a-z-]*):\n", text, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


class WorkflowTests(unittest.TestCase):
    def test_only_the_jobs_that_play_install_the_libraries(self):
        tournament = jobs(WORKFLOWS / "tournament.yml")
        self.assertEqual(sorted(tournament), ["deploy", "play", "schedule"])
        play = tournament["play"]
        self.assertLess(play.index(STEP), play.index("tools.arena play"))
        self.assertIn('echo "DEDALE_PYTHON=$python" >> "$GITHUB_ENV"', play)
        # The schedule job holds the maze secret.
        for job in ["schedule", "deploy"]:
            self.assertNotIn("bot_python", tournament[job], job)
        checks = jobs(WORKFLOWS / "pull-request.yml")
        submission = checks["submission"]
        self.assertLess(submission.index(STEP), submission.index("tools.validate"))
        self.assertNotIn("bot_python", checks["tools"])
