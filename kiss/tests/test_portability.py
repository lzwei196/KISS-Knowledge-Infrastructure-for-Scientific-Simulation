"""The repository must be checkout-able on Windows and macOS, not just Linux.

Three names that are perfectly legal on Linux are fatal elsewhere, and each
one has already cost us a release:

  * Two files differing only in case cannot coexist on a case-insensitive
    filesystem. macOS collapsed five APEX pairs during a round-trip and the
    losses looked like deliberate deletions.
  * ``<>:"|?*`` and control characters are rejected by Windows outright.
    CE-QUAL-W2, a Windows model, wrote ".\\Habitat\\x.csv" while running on
    Linux, so the separators became part of the filename and `actions/checkout`
    failed in fifteen seconds — before any build step ran.
  * CON, PRN, AUX, NUL, COM1-9 and LPT1-9 are device names on Windows whatever
    extension follows them.

Checking the index rather than the working tree keeps this honest: what breaks
another machine is what we committed.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ILLEGAL = re.compile(r'[<>:"|?*\\\x00-\x1f]')
RESERVED = ({"CON", "PRN", "AUX", "NUL"}
            | {f"COM{i}" for i in range(1, 10)}
            | {f"LPT{i}" for i in range(1, 10)})


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


class CrossPlatformNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.files = tracked_files()
        self.assertGreater(len(self.files), 100, "git ls-files returned almost nothing")

    def test_no_case_insensitive_collisions(self) -> None:
        groups: dict[str, list[str]] = defaultdict(list)
        for f in self.files:
            groups[f.lower()].append(f)
        clashes = sorted(v for v in groups.values() if len(v) > 1)
        self.assertEqual(
            clashes, [],
            "these files differ only by case and cannot both exist on macOS or "
            "Windows; keep the spelling the model's own control files reference:"
            f"\n{clashes}")

    def test_no_characters_windows_rejects(self) -> None:
        bad = [f for f in self.files if any(ILLEGAL.search(seg) for seg in f.split("/"))]
        self.assertEqual(bad, [], f"illegal on Windows: {bad}")

    def test_no_reserved_device_names(self) -> None:
        bad = [f for f in self.files
               if any(seg.split(".")[0].upper() in RESERVED for seg in f.split("/"))]
        self.assertEqual(bad, [], f"reserved Windows device names: {bad}")

    def test_no_trailing_dots_or_spaces(self) -> None:
        bad = [f for f in self.files
               if any(seg != seg.rstrip(" .") for seg in f.split("/"))]
        self.assertEqual(bad, [], f"Windows silently strips these: {bad}")


if __name__ == "__main__":
    unittest.main()
