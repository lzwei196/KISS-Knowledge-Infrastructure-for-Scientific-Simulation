from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


class ReleaseMetadataTests(unittest.TestCase):
    def test_manifest_and_changelog_match_the_build_version(self):
        with (REPO / "kiss" / "pyproject.toml").open("rb") as stream:
            version = tomllib.load(stream)["project"]["version"]
        manifest = json.loads(
            (REPO / "release-manifest.json").read_text(encoding="utf-8"))
        changelog = (REPO / "DESKTOP_CHANGELOG.md").read_text(encoding="utf-8")

        self.assertEqual(manifest["version"], version)
        self.assertIn(f"## v{version}", changelog)
        self.assertEqual(manifest["ki_library"]["package_count"], 127)
        self.assertRegex(manifest["source"]["code_commit"], r"^[0-9a-f]{40}$")

    def test_all_desktop_release_assets_include_audit_metadata(self):
        spec = (REPO / "kiss" / "GeoForgeDesktop.spec").read_text(encoding="utf-8")
        workflow = (REPO / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8")

        self.assertIn('release-manifest.json"), "."', spec)
        self.assertIn('DESKTOP_CHANGELOG.md"), "."', spec)
        self.assertIn("release-manifest.json DESKTOP_CHANGELOG.md SHA256SUMS.txt", workflow)
        self.assertIn('sha256sum "${ASSETS[@]}"', workflow)


if __name__ == "__main__":
    unittest.main()
