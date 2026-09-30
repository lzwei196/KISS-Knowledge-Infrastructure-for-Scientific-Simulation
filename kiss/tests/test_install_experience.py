from __future__ import annotations

import subprocess
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from kiss_cli import api, catalog, cli, execution, gui, ki_updates, software_audit, setup
from kiss_cli.manifest import Manifest



def _process_run(completed):
    """A recorded subprocess result as the shared launcher reports it."""
    return execution.ProcessRun(
        "succeeded" if completed.returncode == 0 else "failed",
        completed.returncode, completed.stdout or "", completed.stderr or "",
        process_started=True)

class InstallExperienceTests(unittest.TestCase):
    def test_bundled_ki_records_cover_catalogue_and_recipe_copies_agree(self):
        repo = Path(__file__).resolve().parents[2]
        kis = list(catalog.Catalog(repo / "models"))
        self.assertEqual(len(kis), 127)
        report = json.loads((repo / "docs" / "WINDOWS_INSTALL_STRESS_2026-09-07.json").read_text(encoding="utf-8"))
        self.assertEqual({row["model"] for row in report["results"]}, {ki.name for ki in kis})
        counts = {}
        for row in report["results"]:
            counts[row["result"]] = counts.get(row["result"], 0) + 1
        self.assertEqual(report["counts"], counts)
        for ki in kis:
            with self.subTest(model=ki.name):
                self.assertTrue((ki.root / "docs" / "install.windows.md").is_file())
                recipe = ki.root / "kiss.windows.yaml"
                if recipe.is_file():
                    embedded = Manifest.load(recipe)
                    self.assertEqual(embedded.model, ki.name)
                    self.assertEqual(embedded, Manifest.load(
                        repo / "kiss" / "manifests" / f"{ki.name}.yaml"))

    def test_recorded_source_revision_and_canonical_path_reach_agent(self):
        from kiss_cli.manifest import Acquire
        man = Manifest(model="Demo", install_dir="Demo/source/repo",
                       acquire=Acquire(strategy="build", repo="https://example.org/official",
                                       ref="a" * 40, produces="src/demo.exe"))
        hint = gui._installation_manifest_guidance(man)
        self.assertIn("a" * 40, hint)
        self.assertIn("<binaries role>/Demo/source/repo/src/demo.exe", hint)

    @unittest.skipUnless(os.name == "nt", "Windows portable pacman")
    def test_portable_pacman_hooks_receive_its_private_coreutils_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ki_root = root / "ki"
            ki_root.mkdir()
            pacman = root / "msys64" / "usr" / "bin" / "pacman.exe"
            pacman.parent.mkdir(parents=True)
            pacman.write_bytes(b"MZ")
            cfg = SimpleNamespace(root=root, python=sys.executable,
                                  roles={"binaries": root / "binaries"})
            completed = subprocess.CompletedProcess([], 0, stdout="installed", stderr="")
            with mock.patch.object(execution, "run_process", return_value=_process_run(completed)) as run:
                api.execute_tool("run_setup_command", {"argv": [str(pacman), "-S",
                    "--noconfirm", "make"]}, SimpleNamespace(root=ki_root), cfg,
                    setup_mode=True, setup_context={"installation_only": True})
            actual = run.call_args.kwargs["env"]["PATH"].split(os.pathsep)[0]
            self.assertEqual(Path(actual).resolve(), pacman.parent.resolve())

    def test_setup_task_reads_only_current_os_installation_experience(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            notes = root / "docs" / "install.windows.md"
            notes.write_text("Previously observed build remedy")
            ki = catalog.KI("Demo", root)
            cfg = SimpleNamespace(root=root)
            with mock.patch.object(catalog.sys, "platform", "win32"):
                for installation_only in (True, False):
                    task = setup.agent_task(ki, cfg, root, installation_only=installation_only)
                    self.assertIn(str(notes), task)
            with mock.patch.object(catalog.sys, "platform", "darwin"):
                self.assertIsNone(ki.installation_notes)

    def test_platform_recipe_is_used_by_all_manifest_consumers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ki_root = root / "models" / "Demo"
            ki_root.mkdir(parents=True)
            shared = root / "kiss" / "manifests"
            shared.mkdir(parents=True)
            base = "kiss_manifest_version: 1\nmodel: Demo\nverified: unverified\n"
            (shared / "Demo.yaml").write_text(base + "notes: shared\n")
            (ki_root / "kiss.yaml").write_text(base + "notes: generic\n")
            (ki_root / "kiss.windows.yaml").write_text(base + "notes: windows\n")
            (ki_root / "kiss.macos.yaml").write_text(base + "notes: macos\n")
            ki = catalog.KI("Demo", ki_root)
            handler = gui.Handler.__new__(gui.Handler)
            handler.repo_root = root
            handler.library_root = root
            handler.workroot = root / "work"
            for platform, expected in (("win32", "windows"), ("darwin", "macos"),
                                       ("linux", "generic")):
                with self.subTest(platform=platform), mock.patch.object(
                        catalog.sys, "platform", platform):
                    self.assertEqual(cli._manifest_for(ki, root).notes, expected)
                    self.assertEqual(handler._manifest(ki).notes, expected)
                    self.assertEqual(software_audit._manifest(ki, shared).notes, expected)

    def test_library_archive_keeps_both_platform_recipes_and_experience(self):
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "library.zip"
            contents = {
                "models/Demo/kiss.windows.yaml": "windows recipe",
                "models/Demo/kiss.macos.yaml": "mac recipe",
                "models/Demo/docs/install.windows.md": "observed Windows steps",
            }
            with zipfile.ZipFile(archive, "w") as bundle:
                for name, content in contents.items():
                    bundle.writestr(f"repository-commit/{name}", content)
            manager = ki_updates.UpdateManager(root, lambda path: None, branch="main")
            destination = root / "snapshot"
            manager._extract(archive, destination)
            for name, content in contents.items():
                self.assertEqual((destination / name).read_text(), content)

    def test_timeout_returns_even_if_descendant_keeps_output_pipes(self):
        process = mock.MagicMock(spec=subprocess.Popen)
        process.pid, process.returncode = 54321, None
        process.stdout = process.stderr = None
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["build"], 1),
            subprocess.TimeoutExpired(["build"], 5, output=b"build reached link"),
        ]
        with mock.patch.object(execution.subprocess, "Popen", return_value=process),              mock.patch("kiss_cli.processes.terminate_process_tree") as terminate,              mock.patch.object(execution, "kill_tree"):
            run = execution.run_process(["build"], cwd=".", env={}, timeout=1)
        if os.name == "nt":
            terminate.assert_called_once_with(process)
        self.assertEqual(run.status, "timed_out")
        self.assertEqual(run.stdout, "build reached link")
        self.assertIn("could not be fully collected", run.detail)
        self.assertEqual([call.kwargs["timeout"] for call in
                          process.communicate.call_args_list], [1, 5])


if __name__ == "__main__":
    unittest.main()
