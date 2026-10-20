"""Downloads the season's Dedale release (by default the static Linux build),
checks it against the release's `SHA256SUMS`, and prints the binary's path.

    python3 -m tools.fetch_dedale [--out DIR] [--target TARGET]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

from tools.common import ROOT, Season

RELEASES = "https://github.com/ef3d0c3e/dedale/releases/download"
TARGET = "x86_64-unknown-linux-musl"


def download(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ValueError(f"{url} not found: is the release published? (drafts cannot be downloaded)") from error
        raise


def expected_sum(sums: str, name: str) -> str:
    """The checksum `SHA256SUMS` gives for `name`."""
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    raise ValueError(f"SHA256SUMS lists no {name}")


def unpack(archive: bytes, name: str, out: Path) -> Path:
    """Writes the archive's `dedale` binary, and nothing else, to `out`."""
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        member = tar.getmember(f"{name}/dedale")
        if not member.isfile():
            raise ValueError(f"{name}/dedale in the archive is not a file")
        source = tar.extractfile(member)
        assert source is not None
        out.mkdir(parents=True, exist_ok=True)
        binary = out / "dedale"
        binary.write_bytes(source.read())
    binary.chmod(0o755)
    return binary


def fetch(version: str, out: Path, target: str = TARGET, get=download) -> Path:
    name = f"dedale-{target}"
    base = f"{RELEASES}/v{version}"
    archive = get(f"{base}/{name}.tar.gz")
    sums = get(f"{base}/SHA256SUMS").decode()
    expected = expected_sum(sums, f"{name}.tar.gz")
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        raise ValueError(f"{name}.tar.gz: checksum {actual}, SHA256SUMS says {expected}")
    return unpack(archive, name, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=ROOT / ".dedale")
    parser.add_argument("--target", default=TARGET)
    parser.add_argument("--version", help="instead of the season's")
    args = parser.parse_args(argv)
    version = args.version or Season.load().dedale
    try:
        binary = fetch(version, args.out, args.target)
    except (OSError, ValueError, KeyError) as error:
        print(f"cannot fetch Dedale {version}: {error}", file=sys.stderr)
        return 1
    print(os.fspath(binary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
