from __future__ import annotations

import json
import hashlib
import runpy
import tomllib
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


class ReleaseMetadataTests(unittest.TestCase):
    def test_smoke_accepts_an_explicit_guide_edition_and_legacy_manifests(self):
        guide_edition = runpy.run_path(str(REPO / "tools" / "windows_release_smoke.py"))["guide_edition"]
        self.assertEqual(guide_edition({"version": "0.6.55"}), "0.6.55")
        self.assertEqual(guide_edition({"version": "0.6.56", "guides": {"edition": "0.6.55"}}), "0.6.55")
        for invalid in ("", None, 55):
            with self.subTest(edition=invalid), self.assertRaises(AssertionError):
                guide_edition({"version": "0.6.56", "guides": {"edition": invalid}})

    def test_bundled_guides_match_the_declared_reviewed_edition(self):
        manifest = json.loads((REPO / "release-manifest.json").read_text(encoding="utf-8"))
        guides = manifest["guides"]
        edition = guides["edition"]
        self.assertRegex(edition, r"^\d+\.\d+\.\d+$")
        document_root = REPO / "docs" / "manual" / edition
        self.assertEqual(guides["validation"], f"docs/manual/{edition}/validation.json")
        validation = json.loads((REPO / guides["validation"]).read_text(encoding="utf-8"))
        self.assertEqual(validation["version"], edition)
        self.assertEqual(validation["status"], "passed")
        expected_routes = {f"/guide/{kind}/{lang}.{ext}"
                           for kind in ("manual", "quickstart", "calibration")
                           for lang in ("en", "zh-CN") for ext in ("html", "pdf")}
        self.assertEqual({row["route"] for row in validation["outputs"]}, expected_routes)
        for row in validation["outputs"]:
            with self.subTest(route=row["route"]):
                source = REPO / row["source"]
                self.assertEqual(source.parent, document_root)
                kind, filename = row["route"].removeprefix("/guide/").split("/")
                expected_bundle = f"kiss/kiss_cli/web/guides/{kind}-{filename}"
                self.assertEqual(row["bundled"], expected_bundle)
                paths = [REPO / expected_bundle]
                # Generated source HTML is ignored by Git; PDFs and every
                # offline asset are tracked and must exist in a fresh checkout.
                if source.suffix == ".pdf" or source.exists():
                    paths.append(source)
                for path in paths:
                    content = path.read_bytes()
                    self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])
                    self.assertEqual(len(content), row["bytes"])
                if source.suffix == ".html":
                    self.assertIn(edition, content.decode("utf-8"))
                else:
                    self.assertTrue(content.startswith(b"%PDF-"))
                    if kind == "quickstart":
                        self.assertEqual(row["pages"], 3)
        revision = json.loads((document_root / "quickstart-illustrated-validation.json").read_text(encoding="utf-8"))
        self.assertEqual(revision["revision"], guides["quickstart_revision"])
        self.assertEqual(revision["status"], "passed")

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

    def test_windows_release_versions_and_runtime_gate_agree(self):
        with (REPO / "kiss" / "pyproject.toml").open("rb") as stream:
            version = tomllib.load(stream)["project"]["version"]
        spec = (REPO / "kiss" / "GeoForgeDesktopWindows.spec").read_text(encoding="utf-8")
        installer = (REPO / "kiss" / "installer" / "GeoForgeDesktopWindows.iss").read_text(encoding="utf-8")
        workflow = (REPO / ".github" / "workflows" / "windows-release.yml").read_text(encoding="utf-8")
        self.assertIn(f'#define AppVersion "{version}"', installer)
        self.assertIn(f'default: windows-v{version}', workflow)
        self.assertIn('version=version_info', spec)
        self.assertIn('if len(ki_packages) != 127:', spec)
        self.assertNotIn('(str(REPO / "models"), "models")', spec)
        self.assertEqual(workflow.count('python tools/windows_release_smoke.py'), 2)


if __name__ == "__main__":
    unittest.main()
