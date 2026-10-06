"""Materialised reference cases retain their manifest's exact source bytes."""
import hashlib
import json

from kiss_cli import paths, port


def test_reference_case_hashes_survive_materialisation_and_refresh(tmp_path):
    source = tmp_path / "source"
    case = source / "test_cases" / "trial"
    inputs = case / "inputs"
    inputs.mkdir(parents=True)
    files = {
        "inputs/Trial.303.inp": b"Shaw 3.0\nTrial.30.sit\nKISSPATH_OUTPUTS\r\n",
        "inputs/forcing.obs": b"forcing\r\n1 2 3\n",
        "expected.json": b'{"literal": "KISSPATH_DATA", "value": 1}\n',
        "run_reference.py": b'# literal KISSPATH_ROOT\nprint("reference")\n',
        "README.md": "Reference case: \u00b1 tolerance\n".encode("utf-8"),
    }
    manifest = {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in files.items()}
    files["manifest.json"] = (json.dumps({"files": manifest}, indent=2) + "\n").encode()
    for name, data in files.items():
        (case / name).write_bytes(data)
    (source / "SKILL.md").write_text("output=KISSPATH_OUTPUTS/result.nc\n", encoding="utf-8")
    destination = tmp_path / "project" / "models" / "M" / "ki"
    cfg = paths.KissConfig.default(tmp_path / "project")

    for attempt in range(2):
        if attempt:
            (destination / "test_cases" / "trial" / "inputs" / "Trial.303.inp").write_bytes(b"stale")
        port.materialise(source, destination, cfg)
        copied = destination / "test_cases" / "trial"
        assert all((copied / name).read_bytes() == data for name, data in files.items())
        declared = json.loads((copied / "manifest.json").read_bytes())["files"]
        for name, metadata in declared.items():
            data = (copied / name).read_bytes()
            assert len(data) == metadata["bytes"]
            assert hashlib.sha256(data).hexdigest() == metadata["sha256"]
        assert (destination / "SKILL.md").read_text(encoding="utf-8") == (
            f"output={cfg.roles['outputs'].as_posix()}/result.nc\n")
