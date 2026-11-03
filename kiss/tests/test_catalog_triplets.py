"""KI.triplets reads diagnostics/triplets.yaml first; .md only when there is no .yaml (2026-11-03)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kiss_cli.catalog import KI


class CatalogTripletsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "X"
        (self.root / "diagnostics").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_yaml_wins_when_both_exist(self):
        (self.root / "diagnostics" / "triplets.md").write_text("# old\n")
        (self.root / "diagnostics" / "triplets.yaml").write_text("- id: a\n")
        self.assertEqual(KI("X", self.root).triplets.name, "triplets.yaml")

    def test_md_only_is_still_found(self):
        (self.root / "diagnostics" / "triplets.md").write_text("# old\n")
        self.assertEqual(KI("X", self.root).triplets.name, "triplets.md")

    def test_none_when_neither_exists(self):
        self.assertIsNone(KI("X", self.root).triplets)


if __name__ == "__main__":
    unittest.main()
