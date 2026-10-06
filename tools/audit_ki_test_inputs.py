#!/usr/bin/env python3
"""Deterministic offline test/input-pack inventory of the actual Desktop catalogue.

This reads metadata and hashes local candidates. It does not download, install,
import model tools, execute models, verify scientific inputs, or publish packs.
Empty declarations never establish that a KI needs no inputs. Dataset mentions
remain evidence to review, not a claim that the dataset can drive that model.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "kiss"))

import yaml
from kiss_cli.catalog import Catalog
from kiss_cli import preparation


SCHEMA = "geoforge.ki-test-input-inventory.v1"
DOCUMENTS = ("dag.yaml", "docs/format_spec.yaml", "knowledge_infrastructure.yaml", "SKILL.md")
AUDIT_REFERENCES = (
    "docs/KI-LIBRARY-PLANNING-PRE-EVALUATION-2026-09-27.md",
    "docs/PROJECT-INPUTS-AND-PATHS-PLAN-2026-09-27.md",
    "docs/audits/ki-planning-2026-09-27/census.json",
)
PRIVATE_KEY = re.compile(r"token|password|passwd|secret|credential|authorization|access_key|api_key|share_link|download_url|manual_url|extract.*code", re.I)
PRIVATE_TEXT = re.compile(r"(?:https?://|www\.)\S+|(?:[A-Za-z]:[\\/]|/(?:mnt|home|Users|media|var|tmp)/)[^\s\"']+", re.I)
SECRET_ASSIGNMENT = re.compile(r"\b(?:token|password|passwd|secret|api[_ -]?key|提取码|密码)\s*[:=：]\s*\S+", re.I)
CADENCE = re.compile(r"hour|daily|diurnal|subdaily|day|month|annual|year|cadence|timestep|time.step|interval|temporal|步长|小时|日尺度", re.I)
SOURCE_MENTION = re.compile(r"\b(?:CMFD|MSWX|NASA\s*POWER|ERA5(?:-Land)?|GFS|FNL|HWSD|SoilGrids|NLDAS|GLDAS|GSWP\w*|Daymet|WorldClim|PRISM|CHIRPS|MERIT|HydroSHEDS|AVHRR)\b", re.I)
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules"}
OUTPUT_DIRS = {"outputs", "output", "results", "result", "figures", "plots", "logs", "diagnostics", "installer"}
DATA_DIRS = {"data", "inputs", "input", "examples", "example", "samples", "sample", "test_data", "fixtures", "templates", "parameters", "params"}
SOURCE_SUFFIXES = {".py", ".sh", ".ps1", ".md", ".yaml", ".yml", ".toml", ".c", ".h", ".cpp", ".f", ".f90", ".r"}
DATA_SUFFIXES = {".nc", ".nc4", ".csv", ".tsv", ".dat", ".obs", ".wea", ".sit", ".sol", ".soil", ".veg", ".moi", ".tem", ".dly", ".wnd", ".wp1", ".sub", ".mgt", ".inp", ".prj", ".nml", ".nam", ".asc", ".grd", ".tif", ".tiff", ".shp", ".shx", ".dbf", ".mdb", ".h5", ".hdf", ".hdf5", ".cfg", ".ini", ".par", ".param", ".xml", ".hru", ".bdy", ".ldas"}
TEST_STAGES = (
    ("review_case_and_requirements", "Select a reproducible case, KI implementation/mode, period/site/grid and required input roles; resolve metadata conflicts."),
    ("install", "Record OS/architecture, installation command, dependency versions and working model/component version."),
    ("acquire_input_pack", "Record pack ID/version, allowed distribution, complete file manifest, SHA-256 checks and local receipt; keep access details private."),
    ("validate_source_inputs", "Check actual variables, units, coverage, calendar/cadence, grid/site, gaps, duplicates and input-role bindings."),
    ("reject_bad_input", "Deliberately supply missing, malformed or incompatible inputs and confirm the KI fails clearly before accepting a run; retain the negative-test receipts."),
    ("prepare_model_inputs", "Run this KI's pinned loaders/tools and preserve conversion commands, hashes, input/output manifest and prerequisite ordering."),
    ("native_or_component_run", "Execute the selected model or framework component using those inputs; retain exit status, log and output manifest."),
    ("scientific_validation", "Check model-specific acceptance criteria, finite outputs and applicable conservation/reference comparisons; do not equate exit zero with validity."),
    ("new_site", "Select an independent site, domain or component case appropriate to this KI; acquire and prepare its own inputs and validate the end-to-end result without substituting reference-case files."),
    ("clean_replay", "Repeat from the published pack in a clean project and compare the declared reproducibility criteria."),
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def public(value):
    """Keep declarations, not access links/codes, credentials, or machine paths."""
    if isinstance(value, dict):
        return {str(key): public(item) for key, item in value.items() if not PRIVATE_KEY.search(str(key))}
    if isinstance(value, (list, tuple)):
        return [public(item) for item in value]
    if isinstance(value, str):
        return SECRET_ASSIGNMENT.sub("[private access detail omitted]", PRIVATE_TEXT.sub("[external location omitted]", value))
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "[non-finite metadata value]"
    return str(value)


def document(path):
    if not path.is_file() or path.is_symlink():
        return {}, "MISSING_OR_SYMLINK"
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return {}, "UNREADABLE_METADATA"
    return (value, "READABLE_MAPPING") if isinstance(value, dict) else ({}, "NONMAPPING_METADATA")


def scalars(value, pointer=""):
    if isinstance(value, dict):
        for key, nested in value.items():
            if not PRIVATE_KEY.search(str(key)):
                yield from scalars(nested, pointer + "/" + str(key).replace("~", "~0").replace("/", "~1"))
    elif isinstance(value, list):
        for i, nested in enumerate(value):
            yield from scalars(nested, pointer + "/" + str(i))
    else:
        yield pointer, value


def declarations(value, pointer):
    """Retain nested groups and exact document pointers for named input rows."""
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from declarations(item, pointer + "/" + str(index))
    elif isinstance(value, dict):
        if any(value.get(key) not in (None, "", []) for key in ("name", "var", "field", "file", "variable")):
            yield pointer, public(value)
        else:
            for key, item in value.items():
                if not PRIVATE_KEY.search(str(key)):
                    yield from declarations(item, pointer + "/" + str(key))


def candidate_basis(relative):
    parts = relative.parts
    if any(part.lower() in OUTPUT_DIRS for part in parts[:-1]):
        return None
    suffix = relative.suffix.lower()
    if suffix in SOURCE_SUFFIXES or suffix in {".png", ".jpg", ".jpeg", ".pdf", ".xlsx", ".exe", ".dll", ".so", ".log", ".sum"}:
        # Example JSON/YAML decks are candidates; executable scripts are not.
        if suffix not in {".yaml", ".yml"} or not any(part.lower() in DATA_DIRS for part in parts[:-1]):
            return None
    if any(part.lower() in DATA_DIRS for part in parts[:-1]):
        return "located_in_example_input_data_or_template_directory"
    if suffix in DATA_SUFFIXES:
        return "scientific_data_or_configuration_extension"
    if suffix in {".txt", ".json"} and re.search(r"forcing|weather|soil|veglib|template|boundary|initial|grid|param", relative.name, re.I):
        return "input_or_template_filename_hint"
    return None


def file_evidence(ki):
    candidates, source_hashes, omitted = [], [], 0
    for path in sorted(ki.root.rglob("*"), key=lambda p: p.relative_to(ki.root).as_posix()):
        relative = path.relative_to(ki.root)
        if any(part.lower() in SKIP_DIRS for part in relative.parts) or PRIVATE_KEY.search(relative.name):
            continue
        if path.is_symlink():
            omitted += 1
            continue
        if not path.is_file():
            continue
        basis = candidate_basis(relative)
        is_source = path.suffix.lower() in SOURCE_SUFFIXES
        if not basis and not is_source:
            continue
        digest = sha256(path)
        if is_source:
            source_hashes.append({"path": relative.as_posix(), "sha256": digest})
        if basis:
            candidates.append({"path": relative.as_posix(), "bytes": path.stat().st_size,
                               "sha256": digest, "candidate_basis": basis, "status": "PRESENT_UNVERIFIED"})
    encoded = json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return candidates, {"sha256": hashlib.sha256(encoded).hexdigest(), "hashed_file_count": len(source_hashes),
                        "method": "SHA-256 of sorted relative-path/content-SHA256 records for source/document suffixes; no absolute paths or timestamps",
                        "symlinks_omitted": omitted}


def inspect(ki):
    metadata, parsed, inputs, cadence, sources, versions = [], {}, [], [], [], []
    for relative in DOCUMENTS:
        path = ki.root / relative
        row = {"path": relative, "sha256": sha256(path) if path.is_file() and not path.is_symlink() else None}
        if relative.endswith(".yaml"):
            doc, row["status"] = document(path)
            parsed[relative] = doc
        else:
            row["status"] = "PRESENT_UNVERIFIED" if row["sha256"] else "MISSING_OR_SYMLINK"
        metadata.append(row)
    for relative in ("dag.yaml", "docs/format_spec.yaml"):
        doc = parsed[relative]
        groups = doc.get("inputs") or {}
        if isinstance(groups, dict):
            for category, raw in groups.items():
                for pointer, fields in declarations(raw, "/inputs/" + str(category)):
                    inputs.append({"category": str(category), "fields": fields,
                                   "evidence": {"path": relative, "yaml_key": pointer}})
        for pointer, value in scalars(doc):
            if not isinstance(value, (str, int, float)):
                continue
            text = str(value)
            in_input = pointer.startswith("/inputs/")
            temporal_field = pointer in {"/boundary/temporal", "/boundary/notes"} or pointer.startswith("/time/")
            if (in_input and CADENCE.search(text)) or temporal_field:
                cadence.append({"value": public(value), "evidence": {"path": relative, "yaml_key": pointer},
                                "status": "DECLARATION_REQUIRES_CASE_REVIEW"})
            if (in_input and re.search(r"source|dataset", pointer, re.I)) or SOURCE_MENTION.search(text):
                sources.append({"value": public(value), "evidence": {"path": relative, "yaml_key": pointer},
                                "status": "MENTION_ONLY_NOT_COMPATIBILITY_OR_AVAILABILITY"})
    for relative, prefix in (("dag.yaml", "identity"), ("docs/format_spec.yaml", "model"),
                             ("knowledge_infrastructure.yaml", "package")):
        block = parsed[relative].get(prefix) or {}
        impl = block.get("implementation") or {} if isinstance(block, dict) else {}
        if isinstance(impl, dict) and impl.get("version"):
            versions.append({"value": public(impl["version"]), "implementation_id": public(impl.get("id")),
                             "evidence": {"path": relative, "yaml_key": f"/{prefix}/implementation"}})
        elif isinstance(block, dict) and block.get("package"):
            versions.append({"value": public(block["package"]), "implementation_id": None,
                             "evidence": {"path": relative, "yaml_key": f"/{prefix}/package"}})
    forcing_rows = [row for row in inputs if row["category"] == "forcing"]
    forcing_names = sorted({str(row["fields"].get("name") or row["fields"].get("variable") or row["fields"].get("var") or row["fields"].get("field"))
                            for row in forcing_rows if any(row["fields"].get(key) for key in ("name", "variable", "var", "field"))})
    candidates, source_tree = file_evidence(ki)
    cautions = ["Declarations and local file presence do not establish a complete usable input package.",
                "Dataset keyword mentions are not supported-source mappings or live availability checks."]
    if not forcing_rows:
        cautions.append("No parsed forcing rows: input requirements remain unresolved, not empty or unnecessary.")
    if parsed["dag.yaml"] == {}:
        cautions.append("DAG metadata missing/unreadable; inspect format specification, SKILL and selected component.")
    if ki.name == "EF5":
        cautions.append("Prior audit identified EF5 format_spec describing HYPE; resolve this metadata conflict against EF5 tools before selecting inputs (docs/KI-LIBRARY-PLANNING-PRE-EVALUATION-2026-09-27.md).")
    if ki.name in {"BMI", "ESMF", "PyMT"}:
        cautions.append("Framework/interface: select the runtime component and derive its actual inputs; no universal meteorological forcing pack is established.")
    if ki.name == "WRF":
        cautions.append("Generic CMFD mentions do not establish WRF forcing compatibility. WPS needs the appropriate GRIB/pressure-level fields, Vtable and geo_em static fields; verify GFS/ERA5/FNL configuration against the actual KI.")
    try:
        reader_count = len(preparation._model_inputs(ki))
        reader_status = "READ_SUCCESS_NOT_SCIENTIFIC_VALIDATION"
    except Exception:
        reader_count, reader_status = None, "READER_ERROR_REVIEW_REQUIRED"
    return {
        "name": ki.name, "model_versions": versions,
        "metadata": {"review_status": "REVIEW_REQUIRED", "documents": metadata, "cautions": cautions,
                     "production_input_reader": {"status": reader_status, "row_count": reader_count}},
        "source_tree": source_tree, "declared_inputs": inputs,
        "forcing": {"status": "DECLARED_NOT_VALIDATED" if forcing_rows else "UNRESOLVED",
                    "names": forcing_names, "cadence_evidence": cadence, "source_evidence": sources,
                    "selected_dataset_ids": [], "source_selection_status": "UNRESOLVED"},
        "bundled_candidates": {"status": "CANDIDATES_PRESENT_NOT_VERIFIED" if candidates else "NO_CANDIDATES_FOUND_BY_HEURISTIC",
                               "complete_pack_verified": False, "candidate_count": len(candidates), "files": candidates},
        "input_pack": {"status": "UNRESOLVED", "pack_id": None, "pack_version": None, "catalogue_dataset_ids": [],
                       "delivery_preference": "baidu_netdisk", "publication_status": "UNVERIFIED", "case_id": None,
                       "site_grid_period": None, "licensing_and_distribution_review": "NOT_RUN",
                       "note": "Delivery preference does not assert a pack exists, is downloadable, licensed for redistribution, complete or ready for this KI."},
        "tests": {"overall_status": "NOT_RUN", "required_stages": [{"id": name, "status": "NOT_RUN", "required_evidence": evidence}
                                                                      for name, evidence in TEST_STAGES],
                  "conditional_stages": [{"id": "calibration", "status": "NOT_RUN", "applicability": "UNDETERMINED",
                                          "required_evidence": "First determine whether this KI/case supports meaningful calibration. If applicable, record parameter bounds, observations, training/holdout split, objective, optimizer budget and independent validation; otherwise document why it is not applicable."}]},
    }


def build_inventory(models, *, expected_count=127):
    catalog = Catalog(Path(models))
    packages = sorted(catalog, key=lambda ki: ki.name)
    if len(packages) != expected_count:
        raise ValueError(f"Production catalogue has {len(packages)} KIs; expected {expected_count}. Refusing an incomplete or different inventory.")
    rows = [inspect(ki) for ki in packages]
    document_hashes = [{"ki": row["name"], "documents": row["metadata"]["documents"]} for row in rows]
    return {
        "schema_version": SCHEMA, "method": "Offline production-Catalog census of actual files; no downloads, installation, model execution, dataset compatibility validation or package publication.",
        "expected_ki_count": expected_count, "actual_ki_count": len(rows),
        "source": {"catalog_reader_sha256": sha256(REPO / "kiss/kiss_cli/catalog.py"),
                   "input_reader_sha256": sha256(REPO / "kiss/kiss_cli/preparation.py"), "generator_sha256": sha256(Path(__file__)),
                   "metadata_sha256": hashlib.sha256(json.dumps(document_hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                   "audit_references": [{"path": path, "sha256": sha256(REPO / path)} for path in AUDIT_REFERENCES if (REPO / path).is_file()]},
        "summary": {"test_status_counts": dict(Counter(row["tests"]["overall_status"] for row in rows)),
                    "ki_with_forcing_declarations": sum(bool(row["forcing"]["names"]) for row in rows),
                    "ki_with_bundled_candidates": sum(bool(row["bundled_candidates"]["files"]) for row in rows),
                    "bundled_candidate_files": sum(row["bundled_candidates"]["candidate_count"] for row in rows),
                    "verified_complete_packs": 0, "resolved_pack_ids": 0},
        "kis": rows,
    }


def markdown_matrix(inventory):
    """Human-readable declaration audit, deliberately separate from run receipts."""
    def cell(value):
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    lines = ["# KI test and input-package inventory", "",
             f"Exactly {inventory['actual_ki_count']} production catalogue KIs. This is a declaration/file-presence audit; all tests below are **NOT_RUN** and every pack is **UNRESOLVED**.", "",
             "Bundled files are candidates only. Their count does not prove a complete or usable input package. Separate reference-pack run receipts do not change this audit's default test status.", "",
             "Required test stages: " + ", ".join(name for name, _ in TEST_STAGES) + ".", "",
             "Calibration is a conditional stage: NOT_RUN, applicability UNDETERMINED for every KI. It is not assumed to apply to all models/frameworks.", "",
             "| KI | Declared forcing names | Input categories | Bundled candidate files | Review flags | Input pack | Required tests |",
             "|---|---|---|---:|---|---|---|"]
    for row in inventory["kis"]:
        flags = ["case/source review"]
        if not row["forcing"]["names"]:
            flags.append("forcing unresolved")
        if any(doc["path"] == "dag.yaml" and doc["status"] != "READABLE_MAPPING" for doc in row["metadata"]["documents"]):
            flags.append("DAG review")
        if row["name"] == "EF5":
            flags.append("EF5/HYPE metadata conflict")
        if row["name"] in {"BMI", "ESMF", "PyMT"}:
            flags.append("runtime component selection")
        if row["name"] == "WRF":
            flags.append("GRIB/pressure-level/WPS requirements")
        values = [row["name"], "; ".join(row["forcing"]["names"]) or "UNRESOLVED (not evidence of no inputs)",
                  ", ".join(sorted({item["category"] for item in row["declared_inputs"]})) or "UNRESOLVED",
                  row["bundled_candidates"]["candidate_count"], "; ".join(flags), "UNRESOLVED", f"NOT_RUN (all {len(TEST_STAGES)} stages)"]
        lines.append("| " + " | ".join(cell(value) for value in values) + " |")
    lines += ["", "The JSON inventory preserves declaration pointers, source hashes, candidate-file hashes and unresolved selection fields.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, default=REPO / "models")
    parser.add_argument("--output", type=Path, default=REPO / "docs/audits/ki-test-inputs-2026-10-04/inventory.json")
    parser.add_argument("--markdown", type=Path, help="Markdown matrix path; defaults to TEST-MATRIX.md beside the JSON output.")
    parser.add_argument("--expected-count", type=int, default=127,
                        help="Fail on a different production catalogue size (default: 127).")
    args = parser.parse_args(argv)
    markdown = args.markdown or args.output.with_name("TEST-MATRIX.md")
    if markdown.resolve() == args.output.resolve():
        parser.exit(1, "Markdown and JSON output paths must differ.\n")
    try:
        inventory = build_inventory(args.models, expected_count=args.expected_count)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Inventory not written: {type(error).__name__}: {error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(markdown_matrix(inventory), encoding="utf-8")
    print(json.dumps({"schema_version": SCHEMA, "actual_ki_count": inventory["actual_ki_count"], "summary": inventory["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
