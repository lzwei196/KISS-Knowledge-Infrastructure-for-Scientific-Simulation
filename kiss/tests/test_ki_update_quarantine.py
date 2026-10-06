"""Rejected libraries retain complete evidence without weakening activation."""
import hashlib
import json
import shutil
from pathlib import Path
from unittest import mock

from kiss_cli import ki_updates
from . import test_ki_updates as updater_tests


def test_failed_doctor_keeps_full_candidate_findings_and_unchanged_fixture_bytes():
    case = updater_tests.KiUpdateTests()
    case.setUp()
    try:
        case._write_ki(case.base, "Demo", "safe installed instructions")
        fixture = "model input /mnt/disk1/Hydrocraft_server/model/solver\n"
        names = [f"Model{number}" for number in range(7)]
        archive = case._archive(
            {name: "Instructions\n/mnt/disk1/Hydrocraft_server/models/old\n" for name in names},
            extra={"models/Model0/test_cases/native/input.cfg": fixture})
        activated = []
        manager = ki_updates.UpdateManager(case.base, activated.append)
        manager._source_commit = "d" * 40
        manager._component_trees = {"models": "a" * 40, "manifests": "b" * 40,
                                    "shared_tools": "c" * 40, "data_kis": None}
        with mock.patch.object(manager, "_remote_revision", return_value=("a" * 32, "a" * 40, "b" * 40)), \
             mock.patch.object(manager, "_download", side_effect=lambda target: shutil.copyfile(archive, target)):
            manager._run()
        report = manager.status()
        assert report["state"] == "error" and activated == []
        evidence = report["validation_failure"]
        assert evidence["activated"] is False and evidence["stage"] == "package_validation"
        assert evidence["source_commit"] == "d" * 40
        assert evidence["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
        assert evidence["source_content_sha256"] == evidence["candidate_content_sha256"]
        target = Path(evidence["quarantine_path"])
        assert target.parent == (case.home / "quarantine").resolve()
        assert json.loads(Path(evidence["report_path"]).read_text(encoding="utf-8")) == evidence
        assert (target / "models/Model0/test_cases/native/input.cfg").read_text() == fixture
        blockers = [row for row in evidence["findings"] if row["severity"] == "BLOCK"]
        assert {row["ki"] for row in blockers} == set(names)
        hits = evidence["portability_files"]
        row = next(row for row in hits if row["path"].endswith("input.cfg"))
        assert row["sha256"] == hashlib.sha256(fixture.encode()).hexdigest()
        assert len(row["matches"]) == 1
        assert {key: row["matches"][0][key] for key in ("line", "path", "role")} == {
            "line": 1, "path": "/mnt/disk1/Hydrocraft_server/model/solver", "role": "binaries"}
        assert row["matches"][0]["classification"] == "blocked"
        assert len(hits) == 8  # Full detail includes files past the five-KI preview.
        assert not list(case.home.glob(".incoming-*"))
        assert ki_updates.active_library_root() is None
        assert not (case.home / "state.json").exists()
        assert (case.base / "models/Demo/SKILL.md").read_text() == "safe installed instructions"

        # Retry skips the identical transfer, but repeats all package checks.
        with mock.patch.object(manager, "_remote_revision", return_value=("a" * 32, "a" * 40, "b" * 40)), \
             mock.patch.object(manager, "_download", side_effect=AssertionError("unexpected transfer")), \
             mock.patch.object(manager, "_validate", wraps=manager._validate) as validate:
            manager._run()
        retry = manager.status()["validation_failure"]
        assert retry["archive_cache_reused"] is True and validate.call_count == 1
        assert retry["quarantine_path"] != evidence["quarantine_path"]
        assert target.is_dir() and activated == []

        # A changed cache cannot bypass a fresh download or doctor.
        cached_archive = case.home / "archives" / ("d" * 40 + ".zip")
        cached_archive.write_bytes(b"tampered")
        with mock.patch.object(manager, "_remote_revision", return_value=("a" * 32, "a" * 40, "b" * 40)), \
             mock.patch.object(manager, "_download", side_effect=lambda target: shutil.copyfile(archive, target)) as download:
            manager._run()
        assert download.call_count == 1
        assert manager.status()["validation_failure"]["archive_cache_reused"] is False
        assert activated == []
    finally:
        case.tearDown()


def test_partial_unsafe_extraction_is_quarantined_without_cached_validation():
    case = updater_tests.KiUpdateTests()
    case.setUp()
    try:
        archive = case._archive({"Demo": "remote"}, unsafe_link=True)
        manager = ki_updates.UpdateManager(case.base, lambda _: (_ for _ in ()).throw(AssertionError("activated")))
        manager._source_commit = "e" * 40
        with mock.patch.object(manager, "_remote_revision", return_value=("a" * 32, "a" * 40, "b" * 40)), \
             mock.patch.object(manager, "_download", side_effect=lambda target: shutil.copyfile(archive, target)):
            manager._run()
        evidence = manager.status()["validation_failure"]
        assert evidence["stage"] == "extraction" and evidence["activated"] is False
        assert "absolute symbolic link" in evidence["error"]
        assert Path(evidence["report_path"]).is_file()
        assert not (Path(evidence["quarantine_path"]) / "models/Demo/tools/private-tool").exists()
        assert not (case.home / "archives" / ("e" * 40 + ".zip")).exists()
        assert ki_updates.active_library_root() is None
    finally:
        case.tearDown()
