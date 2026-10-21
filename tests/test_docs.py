import re
import unittest
from pathlib import Path

from tools.common import ROOT

DOCS = [ROOT / "README.md", ROOT / "CONTRIBUTING.md"]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^```.*?^```", re.M | re.S)


def anchors(path: Path) -> set[str]:
    """The anchors GitHub gives a Markdown file's headings."""
    text = FENCE.sub("", path.read_text())
    headings = re.findall(r"^#+ (.+)$", text, re.M)
    return {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in headings}


class DocsTests(unittest.TestCase):
    def test_links_between_the_docs_resolve(self):
        for doc in DOCS:
            for target in LINK.findall(FENCE.sub("", doc.read_text())):
                if re.match(r"[a-z]+:", target):
                    continue
                with self.subTest(doc=doc.name, target=target):
                    file, _, anchor = target.partition("#")
                    path = (doc.parent / file) if file else doc
                    self.assertTrue(path.exists(), path)
                    if anchor:
                        self.assertIn(anchor, anchors(path))

    def test_pull_requests_point_to_the_guide(self):
        template = (ROOT / ".github" / "pull_request_template.md").read_text()
        self.assertIn("CONTRIBUTING.md", template)
        self.assertIn("## Other files", template)
