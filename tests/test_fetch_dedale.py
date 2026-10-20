import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from tools.fetch_dedale import RELEASES, expected_sum, fetch


def archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.name = "dedale-x86_64-unknown-linux-musl"
        self.archive = archive(
            {
                f"{self.name}/dedale": b"\x7fELF binary",
                f"{self.name}/README.md": b"readme",
                "../escape": b"never written",
            }
        )
        self.sums = f"{hashlib.sha256(self.archive).hexdigest()}  {self.name}.tar.gz\n"

    def get(self, sums: str):
        files = {
            f"{RELEASES}/v0.1.0/{self.name}.tar.gz": self.archive,
            f"{RELEASES}/v0.1.0/SHA256SUMS": sums.encode(),
        }
        return lambda url: files[url]

    def test_the_binary_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            binary = fetch("0.1.0", out, get=self.get(self.sums))
            self.assertEqual(binary.read_bytes(), b"\x7fELF binary")
            self.assertTrue(binary.stat().st_mode & 0o100)
            self.assertEqual([p.name for p in out.iterdir()], ["dedale"])
            self.assertFalse((Path(tmp) / "escape").exists())

    def test_a_wrong_checksum_is_refused(self):
        wrong = f"{'0' * 64}  {self.name}.tar.gz\n"
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, "checksum"):
            fetch("0.1.0", Path(tmp), get=self.get(wrong))

    def test_sums_list_the_archive(self):
        self.assertEqual(expected_sum("AB  x.tar.gz\ncd *y.tar.gz\n", "y.tar.gz"), "cd")
        with self.assertRaisesRegex(ValueError, "lists no"):
            expected_sum("ab  x.tar.gz\n", "z.tar.gz")
