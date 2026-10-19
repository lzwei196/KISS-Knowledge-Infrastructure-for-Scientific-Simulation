"""Real tiny archive/worker fixtures only; no model, provider or network execution."""
import copy
import hashlib
import io
import json
import stat
import struct
import tarfile
import zipfile
from pathlib import Path

import pytest

from kiss_cli import archive_input_copies as archives, project_data_tools

OPAQUE = b"CDF\x02\x00\xff\x00opaque scientific-looking fixture\n"


def archive(path, entries, *, kind="tar", dirs=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "zip":
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for name in dirs:
                target.writestr(name.rstrip("/") + "/", b"")
            for name, data in entries:
                info = zipfile.ZipInfo(name)
                info.filename = name  # Preserve adversarial backslashes on Windows.
                info.compress_type = zipfile.ZIP_DEFLATED
                target.writestr(info, data)
    else:
        with tarfile.open(path, "w:gz" if kind == "tar.gz" else "w") as target:
            for name in dirs:
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                target.addfile(info)
            for name, data in entries:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                target.addfile(info, io.BytesIO(data))
    return path


def capture(project, sources):
    from ki_tools_common.flow import receipts
    files = [p.relative_to(project).as_posix() for p in sources]
    return receipts.capture_inputs(project, {"inputs": ["archive"]},
        {"items": [{"id": "archive", "local_paths": files}]}, [], project)


def result(project, source, *, contents=OPAQUE, snapshot=None, inputs=None, output="outputs/staged/input.nc", **kwargs):
    target = project / output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(contents)
    return project_data_tools.validate_outputs(project, [target], 0,
        input_files=[str(source)] if inputs is None else inputs,
        input_snapshot=capture(project, [source]) if snapshot is None else snapshot, **kwargs)


def copied(report):
    return [row for row in report["checks"] if row.get("scope") == "unchanged_archive_member_copy"]


@pytest.mark.parametrize("kind", ["tar", "tar.gz", "zip"])
def test_opaque_member_copy_has_exact_host_provenance_no_readiness(tmp_path, kind):
    source = archive(tmp_path / ("inputs/case." + kind), [("./case/input.nc", OPAQUE)], kind=kind,
                     dirs=(".", "./case"))
    before = source.read_bytes()
    report = result(tmp_path, source)
    assert report["status"] == "passed", report
    witness, = copied(report)
    assert witness["source"] == "inputs/case." + kind
    assert witness["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert witness["source_bytes"] == len(before)
    assert witness["member"] == "./case/input.nc"
    assert witness["normalized_member"] == "case/input.nc"
    assert witness["sha256"] == hashlib.sha256(OPAQUE).hexdigest()
    assert witness["bytes"] == len(OPAQUE)
    assert witness["preparation_scope"] == "input_preparation_only"
    assert report["scientific_validation"] == "not_performed" and report["model_ready"] is False
    assert source.read_bytes() == before


@pytest.mark.parametrize("kind", ["tar", "tar.gz", "zip"])
@pytest.mark.parametrize("windows", [False, True], ids=["posix", "windows"])
def test_host_path_semantics_allow_posix_timestamps_but_never_windows_ads(tmp_path, monkeypatch, kind, windows):
    monkeypatch.setattr(archives, "_WINDOWS_NAMES", windows)
    name = "./case/RESTART/HYDRO_RST.2011-08-26_00:00_DOMAIN1"
    source = archive(tmp_path / ("inputs/case." + kind), [(name, OPAQUE)], kind=kind,
                     dirs=("./", "./case/", "./case/RESTART/"))
    report = result(tmp_path, source)
    assert report["status"] == ("failed" if windows else "passed")
    if windows:
        assert copied(report) == []
    else:
        row, = copied(report)
        assert row["member"] == name and row["normalized_member"] == name[2:]
        assert row["scientific_validation"] == "not_performed"
        assert report["model_ready"] is False


@pytest.mark.parametrize("windows", [False, True], ids=["posix", "windows"])
@pytest.mark.parametrize("name", ["C:evil.nc", "./C:evil.nc", "././c:/evil.nc",
    "../2011_00:00.nc", "case/../2011_00:00.nc", "/2011_00:00.nc",
    "case\\2011_00:00.nc", "case//2011_00:00.nc"])
def test_posix_timestamp_support_never_loosens_unsafe_paths(monkeypatch, windows, name):
    monkeypatch.setattr(archives, "_WINDOWS_NAMES", windows)
    with pytest.raises(ValueError):
        archives._member_name(name, False)


@pytest.mark.parametrize("kind", ["tar", "zip"])
def test_posix_timestamp_names_still_reject_normalized_aliases(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(archives, "_WINDOWS_NAMES", False)
    name = "case/HYDRO_RST.2011-08-26_00:00_DOMAIN1"
    source = archive(tmp_path / ("inputs/case." + kind),
                     [(name, OPAQUE), ("./" + name, b"other")], kind=kind)
    assert result(tmp_path, source)["status"] == "failed"


@pytest.mark.parametrize("kind", ["tar", "tar.gz", "zip"])
def test_transformed_or_unknown_member_bytes_are_not_copy_evidence(tmp_path, kind):
    source = archive(tmp_path / ("inputs/case." + kind), [("case/input.nc", OPAQUE)], kind=kind)
    report = result(tmp_path, source, contents=OPAQUE + b"changed")
    assert report["status"] == "failed" and copied(report) == []


@pytest.mark.parametrize("kind", ["tar", "zip"])
@pytest.mark.parametrize("name", ["../escape.nc", "/absolute.nc", "case/../evil.nc", "case\\evil.nc",
                                   "C:evil.nc", "case//evil.nc", "NUL.nc", "case/evil. "])
def test_unsafe_later_member_rejects_even_an_earlier_matching_file(tmp_path, kind, name):
    source = archive(tmp_path / ("inputs/case." + kind), [("case/input.nc", OPAQUE), (name, b"bad")], kind=kind)
    report = result(tmp_path, source)
    assert report["status"] == "failed" and copied(report) == []


@pytest.mark.parametrize("kind", ["tar", "zip"])
@pytest.mark.parametrize("names", [
    ("case/input.nc", "./case/input.nc"), ("case/Input.nc", "case/input.nc"),
    ("case/\u00e9.nc", "case/e\u0301.nc"), ("case", "case/input.nc"),
])
def test_ambiguous_names_and_file_parent_conflicts_rejected(tmp_path, kind, names):
    source = archive(tmp_path / ("inputs/case." + kind), [(names[0], OPAQUE), (names[1], b"other")], kind=kind)
    report = result(tmp_path, source)
    assert report["status"] == "failed" and copied(report) == []


@pytest.mark.parametrize("member_type", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE,
                                       tarfile.BLKTYPE, tarfile.FIFOTYPE, tarfile.GNUTYPE_SPARSE])
def test_tar_links_sparse_and_special_members_reject_archive(tmp_path, member_type):
    source = tmp_path / "inputs/case.tar"
    source.parent.mkdir()
    with tarfile.open(source, "w") as target:
        good = tarfile.TarInfo("input.nc"); good.size = len(OPAQUE)
        target.addfile(good, io.BytesIO(OPAQUE))
        bad = tarfile.TarInfo("other"); bad.type = member_type; bad.linkname = "input.nc"
        target.addfile(bad)
    report = result(tmp_path, source)
    assert report["status"] == "failed" and copied(report) == []


def test_zip_symlink_rejected(tmp_path):
    source = tmp_path / "inputs/case.zip"
    source.parent.mkdir()
    with zipfile.ZipFile(source, "w") as target:
        target.writestr("input.nc", OPAQUE)
        link = zipfile.ZipInfo("link"); link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        target.writestr(link, "input.nc")
    assert result(tmp_path, source)["status"] == "failed"


@pytest.mark.parametrize("kind", ["tar", "tar.gz", "zip"])
@pytest.mark.parametrize("limit,value", [("MAX_ENTRIES", 1), ("MAX_MEMBER_BYTES", 5),
                                         ("MAX_TOTAL_BYTES", len(OPAQUE)), ("MAX_ARCHIVE_BYTES", 8)])
def test_limits_reject_actual_small_archives_without_large_allocations(tmp_path, monkeypatch, kind, limit, value):
    source = archive(tmp_path / ("inputs/case." + kind), [("input.nc", OPAQUE), ("other.nc", OPAQUE)], kind=kind)
    monkeypatch.setattr(archives, limit, value)
    report = result(tmp_path, source)
    assert report["status"] == "failed" and copied(report) == []


@pytest.mark.parametrize("defect", ["no_capture", "not_granted", "argument_only", "hash", "size", "archive_changed"])
def test_requires_approved_grant_and_current_prelaunch_input_bytes(tmp_path, defect):
    source = archive(tmp_path / "inputs/case.tar", [("input.nc", OPAQUE)])
    snapshot = capture(tmp_path, [source])
    inputs = [str(source)]
    if defect == "no_capture":
        snapshot = {}
    elif defect == "not_granted":
        inputs = []
    elif defect == "argument_only":
        snapshot["input_coverage"]["files"] = []
    elif defect == "hash":
        snapshot["inputs"][0]["sha256"] = "0" * 64
    elif defect == "size":
        snapshot["inputs"][0]["bytes"] += 1
    else:
        archive(source, [("other-member.nc", OPAQUE)])
    report = result(tmp_path, source, snapshot=snapshot, inputs=inputs)
    assert report["status"] == "failed" and copied(report) == []


def test_tar_trailing_hidden_archive_rejected(tmp_path):
    source = archive(tmp_path / "inputs/case.tar", [("input.nc", OPAQUE)])
    extra = archive(tmp_path / "second.tar", [("other.nc", b"other")])
    with source.open("ab") as stream:
        stream.write(extra.read_bytes())
    assert result(tmp_path, source)["status"] == "failed"


def test_zip_directory_allocation_bound_precedes_zipfile(tmp_path, monkeypatch):
    source = archive(tmp_path / "inputs/case.zip", [("input.nc", OPAQUE)], kind="zip")
    monkeypatch.setattr(archives, "MAX_ZIP_DIRECTORY_BYTES", 1)
    monkeypatch.setattr(archives.zipfile, "ZipFile", lambda *a, **kw: pytest.fail("must reject before directory allocation"))
    assert result(tmp_path, source)["status"] == "failed"


def test_forged_zip_entry_count_rejected_before_allocation(tmp_path, monkeypatch):
    source = archive(tmp_path / "inputs/case.zip", [("input.nc", OPAQUE), ("other.nc", b"other")], kind="zip")
    data = bytearray(source.read_bytes()); end = data.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", data, end + 8, 1, 1)
    source.write_bytes(data)
    monkeypatch.setattr(archives.zipfile, "ZipFile", lambda *a, **kw: pytest.fail("must reject before allocation"))
    assert result(tmp_path, source)["status"] == "failed"


@pytest.mark.parametrize("kind", ["tar", "zip"])
def test_absolute_root_directory_is_not_harmless_relative_root(tmp_path, kind):
    source = archive(tmp_path / ("inputs/case." + kind), [("input.nc", OPAQUE)], kind=kind, dirs=("/",))
    assert result(tmp_path, source)["status"] == "failed"


def test_empty_output_without_matching_member_path_remains_unsupported(tmp_path):
    source = archive(tmp_path / "inputs/case.tar", [("case/empty.TBL", b"")])
    report = result(tmp_path, source, contents=b"", output="outputs/empty.TBL")
    assert report["status"] == "failed" and copied(report) == []
    assert any("empty" in row.get("detail", "") for row in report["checks"])


@pytest.mark.parametrize("limit,value", [("MAX_METADATA_HEADERS", 1), ("MAX_METADATA_TOTAL", 4)])
def test_pax_metadata_has_aggregate_limits(tmp_path, monkeypatch, limit, value):
    source = tmp_path / "inputs/case.tar"; source.parent.mkdir()
    with tarfile.open(source, "w", format=tarfile.PAX_FORMAT) as target:
        for name in ("input.nc", "other.nc"):
            info = tarfile.TarInfo(name); info.size = len(OPAQUE); info.pax_headers = {"mtime": "1.25"}
            target.addfile(info, io.BytesIO(OPAQUE))
    monkeypatch.setattr(archives, limit, value)
    assert result(tmp_path, source)["status"] == "failed"


@pytest.mark.parametrize("headers", [{"GNU.sparse.map": "0,1"}, {"path": "/"}, {"comment": "x" * 8193}])
def test_pax_sparse_absolute_and_large_effective_metadata_rejected(tmp_path, headers):
    source = tmp_path / "inputs/case.tar"; source.parent.mkdir()
    with tarfile.open(source, "w", format=tarfile.PAX_FORMAT) as target:
        info = tarfile.TarInfo("input.nc"); info.size = len(OPAQUE); info.pax_headers = headers
        target.addfile(info, io.BytesIO(OPAQUE))
    assert result(tmp_path, source)["status"] == "failed"


def test_cached_archive_changed_after_first_output_cannot_pass_final_validation(tmp_path, monkeypatch):
    source = archive(tmp_path / "inputs/case.tar", [("input.nc", OPAQUE)])
    real = archives.ArchiveCopies.match
    def changing_match(self, *args, **kwargs):
        witness = real(self, *args, **kwargs)
        archive(source, [("changed.nc", OPAQUE)])
        return witness
    monkeypatch.setattr(archives.ArchiveCopies, "match", changing_match)
    report = result(tmp_path, source)
    assert report["status"] == "failed"
    assert any(row["check"] == "archive_copy_inputs_current" and not row["ok"] for row in report["checks"])


@pytest.mark.parametrize("suffix,data", [("csv", b"\nraw CSV preamble\nno uniform columns\n"),
                                       ("json", b"{invalid original json}"), ("txt", b"\x00raw")])
def test_untyped_raw_member_preservation_does_not_claim_format_validation(tmp_path, suffix, data):
    source = archive(tmp_path / "inputs/case.tar", [("case/raw." + suffix, data)])
    report = result(tmp_path, source, contents=data, output="outputs/case/raw." + suffix)
    assert report["status"] == "passed", report
    assert copied(report)[0]["scientific_validation"] == "not_performed"
    changed = result(tmp_path, source, contents=data + b"changed", output="outputs/case/raw." + suffix)
    assert changed["status"] == "failed" and copied(changed) == []


def test_empty_member_requires_unique_exact_path_and_still_satisfies_declared_freshness(tmp_path):
    source = archive(tmp_path / "inputs/case.tar", [("./case/empty.TBL", b"")])
    authored = project_data_tools.write(tmp_path, "M", "stage", "pass", "converter")
    step = {**authored["step_template"], "inputs": ["archive"], "outputs": ["empty"]}
    inventory = {"items": [{"id": "archive", "local_paths": ["inputs/case.tar"]},
        {"id": "empty", "local_paths": ["outputs/staged/case/empty.TBL"], "status": "missing"}]}
    report = result(tmp_path, source, contents=b"", output="outputs/staged/case/empty.TBL", step=step, inventory=inventory)
    assert report["status"] == "passed", report
    assert copied(report)[0]["member"] == "./case/empty.TBL"
    assert copied(report)[0]["bytes"] == 0
    assert report["model_ready"] is False
    duplicate = archive(tmp_path / "inputs/second.tar", [("case/empty.TBL", b"")])
    ambiguous = result(tmp_path, source, contents=b"", output="outputs/staged/case/empty.TBL",
        inputs=[str(source), str(duplicate)], snapshot=capture(tmp_path, [source, duplicate]))
    assert ambiguous["status"] == "failed" and copied(ambiguous) == []


def test_invalid_archive_scan_failure_cached_for_multiple_outputs(tmp_path, monkeypatch):
    source = archive(tmp_path / "inputs/case.tar", [("input.nc", OPAQUE), ("../bad.nc", b"bad")])
    cache = archives.ArchiveCopies(tmp_path, [str(source)], capture(tmp_path, [source]))
    real, calls = archives._tar, []
    def scan(*args):
        calls.append(1); return real(*args)
    monkeypatch.setattr(archives, "_tar", scan)
    for _ in range(2):
        with pytest.raises(ValueError):
            cache.match(len(OPAQUE), hashlib.sha256(OPAQUE).hexdigest())
    assert len(calls) == 1


def test_tar_padding_across_archives_counts_toward_one_expansion_budget(tmp_path, monkeypatch):
    first = archive(tmp_path / "inputs/one.tar.gz", [("input.nc", OPAQUE)], kind="tar.gz")
    second = archive(tmp_path / "inputs/two.tar.gz", [("other.nc", OPAQUE)], kind="tar.gz")
    monkeypatch.setattr(archives, "MAX_TOTAL_BYTES", 15000)
    monkeypatch.setattr(archives, "MAX_ZIP_DIRECTORY_BYTES", 1)
    report = result(tmp_path, first, inputs=[str(first), str(second)], snapshot=capture(tmp_path, [first, second]))
    assert report["status"] == "failed"
    assert any("aggregate decompressed" in row.get("detail", "") for row in report["checks"])


def test_per_call_cache_scans_once_but_records_each_exact_witness(tmp_path, monkeypatch):
    source = archive(tmp_path / "inputs/case.tar", [("z/input.nc", OPAQUE), ("a/equal.TBL", OPAQUE)])
    snap = capture(tmp_path, [source])
    count, real = [], archives._tar
    def scan(*args):
        count.append(1)
        return real(*args)
    monkeypatch.setattr(archives, "_tar", scan)
    outputs = []
    for name in ("first.nc", "second.TBL"):
        output = tmp_path / "outputs" / name
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(OPAQUE); outputs.append(output)
    report = project_data_tools.validate_outputs(tmp_path, outputs, 0, input_files=[str(source)], input_snapshot=snap)
    assert report["status"] == "passed" and len(count) == 1
    assert [r["member"] for r in copied(report)] == ["a/equal.TBL"] * 2


def test_direct_input_copy_unchanged_and_does_not_open_archive(tmp_path, monkeypatch):
    source = tmp_path / "inputs/raw.nc"; source.parent.mkdir(); source.write_bytes(OPAQUE)
    monkeypatch.setattr(archives.ArchiveCopies, "match", lambda *a: pytest.fail("direct copy already proved"))
    report = result(tmp_path, source)
    assert report["status"] == "passed" and copied(report) == []
    assert any(r.get("scope") == "unchanged_input_copy" for r in report["checks"])


def test_explicit_typed_contract_failure_cannot_use_archive_copy(tmp_path, monkeypatch):
    from .test_project_data_formats import AGRO_CONTRACT
    contract = copy.deepcopy(AGRO_CONTRACT)
    source = archive(tmp_path / "inputs/case.tar", [("agro.yaml", b"[1,2,3]\n")])
    authored = project_data_tools.write(tmp_path, "M", "reader", "pass", "converter", output_formats=[contract])
    step = {**authored["step_template"], "inputs": ["archive"]}
    monkeypatch.setattr(archives.ArchiveCopies, "match", lambda *a: pytest.fail("typed output cannot fall back"))
    report = result(tmp_path, source, contents=b"[1,2,3]\n", output=contract["path"], step=step)
    assert report["status"] == "failed" and copied(report) == []


WORKER = '''import tarfile
from pathlib import Path
with tarfile.open('inputs/case.tar', 'r:') as archive:
    content = archive.extractfile('case/input.nc').read()
out = Path('outputs/staged/input.nc'); out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(content)
'''


def test_real_worker_signed_receipt_binds_archive_and_output_currentness(tmp_path, monkeypatch):
    from .test_project_data_tools import case, approve, run
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    c = case(tmp_path, WORKER, arguments=[])
    _, project, fs, plan, inventory, _ = c
    source = archive(project / "inputs/case.tar", [("case/input.nc", OPAQUE)])
    plan["steps"][0]["kind"] = "prepare"
    plan["steps"][0]["project_data_tool"]["arguments"] = []
    inventory["items"][0]["local_paths"] = ["inputs/case.tar"]
    inventory["items"][-1]["local_paths"] = ["outputs/staged/input.nc"]
    approve(c)
    response = run(c)
    summary = json.loads(response.splitlines()[1].split("[RECEIPT] ", 1)[1])
    receipt_path = Path(summary["receipt"])
    receipt = json.loads(receipt_path.read_text())
    assert receipt["validation"]["status"] == "passed", receipt
    assert receipt["model_executed"] is False and receipt["execution_scope"] == "project_data_tool"
    witness, = copied(receipt["validation"])
    assert witness["source_sha256"] == receipt["inputs"][0]["sha256"]
    evidence = lambda: fs.flow.receipts.evidence(project, plan, fs.flow.approval.read(project),
        enforcement="exact", inventory=inventory)
    assert evidence()["steps_passed"] == ["M:read"]
    preserved = receipt_path.read_bytes()
    archive(source, [("case/input.nc", OPAQUE + b"changed")])
    assert evidence()["steps_passed"] == []
    assert receipt_path.read_bytes() == preserved
