"""The Python bots run with: a virtual environment of the season's Python
version holding the libraries pinned in `libraries.txt`.

    python3 -m tools.bot_python build [--out DIR]     # prints its interpreter, for Dedale's --python
    python3 -m tools.bot_python pin NAME==VERSION...  # rewrites libraries.txt from PyPI
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from tools.common import ROOT, Season

LIBRARIES = ROOT / "libraries.txt"
PYPI = "https://pypi.org/pypi"
REQUIREMENT = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.+!_-]+)")
HEADER = """\
# The libraries bots may import besides the standard library, the same for
# every bot all season. `python3 -m tools.bot_python build` installs them;
# `python3 -m tools.bot_python pin` writes this file, with the hash of every
# file of each release so that pip installs exactly these on any platform.
"""


def parse(text: str) -> dict[str, str]:
    """The libraries a requirements file pins, as name: version, in order.
    Every one must be pinned with `==` and come with its hashes."""
    pinned: dict[str, str] = {}
    for line in text.replace("\\\n", " ").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        found = REQUIREMENT.match(line)
        if not found:
            raise ValueError(f"not pinned with `==`: {line}")
        if "--hash=sha256:" not in line:
            raise ValueError(f"{found[1]} has no hashes")
        pinned[found[1].lower()] = found[2]
    return pinned


def read_libraries(path: Path = LIBRARIES) -> dict[str, str]:
    return parse(path.read_text())


def python_version(python: str, run=subprocess.run) -> str:
    """`3.12` for a Python 3.12 interpreter."""
    script = "import sys; print('%d.%d' % sys.version_info[:2])"
    result = run([python, "-c", script], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def build(out: Path, season: Season, python: str = sys.executable, libraries: Path = LIBRARIES, run=subprocess.run) -> Path:
    """Makes the environment in `out` (emptied first) and returns its
    interpreter. Only wheels are installed, and only the files hashed."""
    version = python_version(python, run)
    if version != season.python:
        raise ValueError(f"the season runs bots with Python {season.python}, but {python} is Python {version}")
    pinned = read_libraries(libraries)
    out = out.resolve()
    # Its output goes to stderr: stdout is only the interpreter's path.
    venv = [python, "-m", "venv", "--clear", *([] if pinned else ["--without-pip"]), os.fspath(out)]
    run(venv, check=True, stdout=sys.stderr)
    interpreter = out / "bin" / "python"
    if pinned:
        install = [
            os.fspath(interpreter),
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--no-input",
            "--disable-pip-version-check",
            "--quiet",
            "--requirement",
            os.fspath(libraries.resolve()),
        ]
        run(install, check=True, stdout=sys.stderr)
    return interpreter


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def pin(requirements: list[str], get=download) -> str:
    """A requirements file pinning `name==version`s, with the hashes of
    every file PyPI has for each."""
    blocks = []
    for requirement in requirements:
        found = REQUIREMENT.fullmatch(requirement)
        if not found:
            raise ValueError(f"expected NAME==VERSION, got {requirement!r}")
        name, version = found[1].lower(), found[2]
        release = json.loads(get(f"{PYPI}/{name}/{version}/json"))
        files = release["urls"]
        if not files:
            raise ValueError(f"PyPI has no files for {name} {version}")
        if any(f.get("yanked") for f in files):
            raise ValueError(f"{name} {version} is yanked")
        hashes = sorted({f["digests"]["sha256"] for f in files})
        lines = [f"{name}=={version}", *(f"    --hash=sha256:{h}" for h in hashes)]
        blocks.append(" \\\n".join(lines) + "\n")
    return HEADER + "".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("build", help="make the environment and print its interpreter")
    make.add_argument("--out", type=Path, default=ROOT / ".bot-python")
    make.add_argument("--python", default=sys.executable, help="the Python to make it from (default: this one)")
    write = commands.add_parser("pin", help="write libraries.txt")
    write.add_argument("requirements", nargs="+", metavar="NAME==VERSION")
    write.add_argument("--out", type=Path, default=LIBRARIES)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            print(os.fspath(build(args.out, Season.load(), args.python)))
        else:
            args.out.write_text(pin(args.requirements))
            print(f"{args.out}: {', '.join(args.requirements)}")
    except subprocess.CalledProcessError as error:
        print(f"{error.cmd[0]} failed (exit {error.returncode})", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as error:
        print(f"bot_python: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
