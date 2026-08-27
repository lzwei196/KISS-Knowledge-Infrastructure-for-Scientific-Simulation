from __future__ import annotations

import json
import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from kiss_cli import ki_updates, settings


class KiUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.home = self.root / "updates"
        self.base.mkdir()
        self.env = mock.patch.dict(
            ki_updates.os.environ,
            {"GEOFORGE_KI_UPDATE_HOME": str(self.home)}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    @staticmethod
    def _dag(name: str) -> str:
        return (
            "template_version: '3.5'\n"
            "identity:\n"
            f"  model_id: {name}\n"
            "  repo_url: https://example.org/model\n"
            "boundary: {}\ninputs: {}\noutputs: {}\nstates: {}\n"
            "processes:\n"
            f"  nodes: [{{id: {name.lower()}_run}}]\n"
            "  internal_edges: []\n"
            "influence: {}\nsafety: {}\n"
        )

    def _write_ki(self, library: Path, name: str, skill: str) -> None:
        model = library / "models" / name
        model.mkdir(parents=True, exist_ok=True)
        (model / "SKILL.md").write_text(skill, encoding="utf-8")
        (model / "preflight_check.py").write_text(
            "print('PREFLIGHT_REPORT={\\\"ok\\\": true}')\n", encoding="utf-8")
        (model / "dag.yaml").write_text(self._dag(name), encoding="utf-8")
        manifests = library / "kiss" / "manifests"
        manifests.mkdir(parents=True, exist_ok=True)
        (manifests / f"{name}.yaml").write_text(
            "verified: unverified\n", encoding="utf-8")

    def _archive(self, packages: dict[str, str], *, unsafe_link: bool = False) -> Path:
        path = self.root / "update.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, skill in packages.items():
                prefix = f"repo-mac-version/models/{name}"
                archive.writestr(f"{prefix}/SKILL.md", skill)
                archive.writestr(
                    f"{prefix}/preflight_check.py",
                    "print('PREFLIGHT_REPORT={\\\"ok\\\": true}')\n")
                archive.writestr(f"{prefix}/dag.yaml", self._dag(name))
                archive.writestr(
                    f"repo-mac-version/kiss/manifests/{name}.yaml",
                    "verified: unverified\n")
            if unsafe_link:
                info = zipfile.ZipInfo(
                    "repo-mac-version/models/Demo/tools/private-tool")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "/Users/author/private-tool")
        return path

    def test_valid_snapshot_activates_and_reports_package_changes(self):
        self._write_ki(self.base, "Demo", "old instructions")
        archive = self._archive({"Demo": "new instructions", "NewModel": "new KI"})
        activated: list[Path] = []
        manager = ki_updates.UpdateManager(
            self.base, activated.append, branch="mac-version")

        def download(destination: Path) -> None:
            shutil.copyfile(archive, destination)

        with mock.patch.object(
                manager, "_remote_revision",
                return_value=("a" * 16 + "-" + "b" * 16, "a" * 40, "b" * 40)), \
             mock.patch.object(manager, "_download", side_effect=download):
            self.assertTrue(manager.start())
            report = manager.wait(10)

        self.assertEqual(report["state"], "updated")
        self.assertEqual(report["added"], ["NewModel"])
        self.assertEqual(report["updated"], ["Demo"])
        self.assertEqual(len(activated), 1)
        self.assertEqual(
            (activated[0] / "models" / "Demo" / "SKILL.md").read_text(),
            "new instructions")
        self.assertEqual(ki_updates.active_library_root(), activated[0])
        self.assertTrue(any(
            "SKILL.md" in row["updated_files"] for row in report["changes"]
            if row["name"] == "Demo"))

    def test_unsafe_snapshot_is_rejected_and_current_library_is_kept(self):
        self._write_ki(self.base, "Demo", "safe current instructions")
        archive = self._archive({"Demo": "remote"}, unsafe_link=True)
        activated: list[Path] = []
        manager = ki_updates.UpdateManager(
            self.base, activated.append, branch="mac-version")

        with mock.patch.object(
                manager, "_remote_revision",
                return_value=("c" * 16 + "-" + "d" * 16, "c" * 40, "d" * 40)), \
             mock.patch.object(
                manager, "_download",
                side_effect=lambda destination: shutil.copyfile(archive, destination)):
            manager.start()
            report = manager.wait(10)

        self.assertEqual(report["state"], "error")
        self.assertIn("absolute symbolic link", report["error"])
        self.assertEqual(activated, [])
        self.assertIsNone(ki_updates.active_library_root())
        self.assertEqual(
            (self.base / "models" / "Demo" / "SKILL.md").read_text(),
            "safe current instructions")

    def test_existing_revision_skips_archive_download(self):
        revision = "e" * 16 + "-" + "f" * 16
        snapshot = self.home / "snapshots" / revision
        self._write_ki(snapshot, "Demo", "validated")
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "state.json").write_text(json.dumps({
            "active_snapshot": revision,
            "revision": revision,
            "package_count": 1,
        }), encoding="utf-8")
        manager = ki_updates.UpdateManager(
            snapshot, lambda _path: None, branch="mac-version")
        with mock.patch.object(
                manager, "_remote_revision",
                return_value=(revision, "e" * 40, "f" * 40)), \
             mock.patch.object(manager, "_download") as download:
            manager.start()
            report = manager.wait(10)
        self.assertEqual(report["state"], "up_to_date")
        download.assert_not_called()

    def test_remote_revision_pins_archive_to_exact_commit(self):
        manager = ki_updates.UpdateManager(
            self.base, lambda _path: None, branch="mac-version")
        commit_sha = "1" * 40
        tree_sha = "2" * 40
        models_sha = "3" * 40
        kiss_sha = "4" * 40
        manifests_sha = "5" * 40
        replies = [
            {"sha": commit_sha, "commit": {"tree": {"sha": tree_sha}}},
            {"tree": [{"path": "models", "sha": models_sha},
                      {"path": "kiss", "sha": kiss_sha}]},
            {"tree": [{"path": "manifests", "sha": manifests_sha}]},
        ]
        with mock.patch.object(manager, "_request_json", side_effect=replies) as request:
            revision, got_models, got_manifests = manager._remote_revision()
        self.assertEqual(revision, f"{'3' * 16}-{'5' * 16}")
        self.assertEqual((got_models, got_manifests), (models_sha, manifests_sha))
        self.assertEqual(manager._archive_ref, commit_sha)
        self.assertEqual(manager._source_commit, commit_sha)
        self.assertIn(f"/commits/{manager.branch}", request.call_args_list[0].args[0])

    def test_updater_uses_dedicated_github_proxy_route(self):
        manager = ki_updates.UpdateManager(
            self.base, lambda _path: None, branch="mac-version")
        opener = mock.Mock()
        response = object()
        opener.open.return_value = response
        request = ki_updates.urllib.request.Request("https://api.github.com/test")
        with mock.patch.object(
                settings, "proxy_url_for",
                return_value="http://127.0.0.1:7897") as route, \
             mock.patch.object(
                 ki_updates.urllib.request, "build_opener",
                 return_value=opener) as build:
            self.assertIs(manager._open(request, timeout=12), response)
        route.assert_called_with(settings.GITHUB_PROXY_TARGET)
        proxy_handler = build.call_args.args[0]
        self.assertEqual(proxy_handler.proxies["https"], "http://127.0.0.1:7897")
        opener.open.assert_called_once_with(request, timeout=12)

    def test_frontend_explains_scope_and_desktop_starts_updates(self):
        package = Path(__file__).parents[1] / "kiss_cli"
        app = (package / "app.py").read_text(encoding="utf-8")
        gui = (package / "gui.py").read_text(encoding="utf-8")
        chat = (package / "web" / "app.html").read_text(encoding="utf-8")
        library = (package / "web" / "library.html").read_text(encoding="utf-8")
        self.assertIn("auto_update=True", app)
        self.assertIn('route == "/api/ki-updates"', gui)
        self.assertIn('route == "/api/ki-updates/check"', gui)
        self.assertIn("does not change chat projects", library)
        self.assertIn("ki-update-toast", chat)
        self.assertIn("network:github", chat)
        self.assertIn("network:github", library)
        self.assertIn("Network settings", library)
