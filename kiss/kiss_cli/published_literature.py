"""Validate the literature metadata of a published process-model package.

This is not gathered-paper, full-text, authoring or scientific verification.
It never fetches a paper, executes candidate code, or manufactures provenance.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .catalog import _norm

POLICY = "published-literature-v2-exporter-parity"
_MAX_BYTES = 4 * 1024 * 1024
_DOI = re.compile(r"10\.\d{4,9}/[^\s\x00-\x1f\x7f]+\Z", re.IGNORECASE)


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _doi(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value,
                   flags=re.IGNORECASE)
    return value.casefold() if _DOI.fullmatch(value) else None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


class _MetadataLoader(yaml.SafeLoader):
    """Do not let a later YAML key silently replace declared evidence."""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        pairs = [(self.construct_object(key, deep=deep),
                  self.construct_object(value, deep=deep)) for key, value in node.value]
        result = {}
        for key, value in pairs:
            try:
                if key in result:
                    raise ValueError(f"duplicate YAML key {key!r}")
                result[key] = value
            except TypeError as error:
                raise ValueError("YAML mapping keys must be scalar values") from error
        return result


def _read(root, relative, failures, *, json_document=False):
    try:
        path = root / relative
        with path.open("rb") as handle:
            raw = handle.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise ValueError("document exceeds 4 MiB")
        text = raw.decode("utf-8")
        doc = (json.loads(text, object_pairs_hook=_object) if json_document
               else yaml.load(text, Loader=_MetadataLoader))
        if not isinstance(doc, dict):
            raise ValueError("expected a mapping")
        return doc
    except (OSError, ValueError, yaml.YAMLError, RecursionError) as error:
        failures.append(f"{relative}: cannot read metadata ({error})")
        return None


def _strings(value) -> bool:
    return isinstance(value, list) and all(_text(item) for item in value)


def _identity(value, model_name, label, failures):
    # Reuse catalogue spelling equivalence: HEC-HMS/HEC_HMS, SWAT+/SWAT_Plus.
    if not _text(model_name) or not _text(value) or not _norm(value) or _norm(value) != _norm(model_name):
        failures.append(f"{label}: model identity conflicts with {model_name!r}")


def _cites(document, field, known, label, failures):
    # Bounded traversal also rejects cyclic YAML aliases without recursion.
    pending = [(document, label)]
    remaining = 25000
    while pending:
        remaining -= 1
        if remaining < 0:
            failures.append(f"{label}: citation structure exceeds traversal limit")
            return
        value, location = pending.pop()
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{location}.{key}"
                if key == field:
                    if not _strings(item):
                        failures.append(f"{child}: expected a list of nonempty citation keys")
                    else:
                        for ref in item:
                            if ref not in known:
                                failures.append(f"{child}: unknown citation key {ref!r}")
                if isinstance(item, (dict, list)):
                    pending.append((item, child))
        elif isinstance(value, list):
            pending.extend((item, f"{location}[{i}]") for i, item in enumerate(value)
                           if isinstance(item, (dict, list)))


def check(root: Path, *, model_name: str, kind: str = "process_model") -> dict:
    """Return explicit published metadata/citation validation, never authoring proof.

    The exporter distributes bibliography, not fetched-text proof. Cross-file
    DOI coverage is reported as an audit warning: KDT does not require each
    declared reference to be duplicated in the exported paper library. Unknown
    citation keys and contradictory deferred/validation claims still fail.
    """
    root = Path(root)
    failures, warnings = [], []
    info = {"policy": POLICY, "scope": "published_metadata_only", "kind": kind,
            "fetched_text_verified": False, "scientific_validation": False,
            "validation_reference_count": 0, "dag_citation_count": 0,
            "deferred_count": 0, "dag_deferred_count": 0,
            "deferred_without_doi": 0,
            "published_without_doi": 0,
            "validation_references_outside_papers": 0,
            "dag_citations_outside_papers": 0,
            "dag_bibliography_without_doi": 0}
    present = (root / "docs/papers.json").is_file()
    if kind not in ("process_model", "task_workflow"):
        return {"ok": False, "present": present, "count": 0,
                "failures": [f"Unsupported published literature KI kind: {kind!r}"],
                "warnings": [], "info": info}
    if kind == "task_workflow" and not present:
        return {"ok": True, "present": False, "count": 0, "failures": [],
                "warnings": ["Task workflow has no published bibliography; literature is advisory for this kind"],
                "info": info}
    doc = _read(root, "docs/papers.json", failures, json_document=True)
    rows = []
    papers = set()
    if doc is not None:
        expected = {"model", "note", "count", "open_access", "papers"}
        if set(doc) != expected:
            failures.append("docs/papers.json: expected exporter fields model, note, count, open_access, papers")
        if not _text(model_name) or doc.get("model") != model_name:
            failures.append(f"docs/papers.json: model must equal {model_name!r}")
        if not _text(doc.get("note")):
            failures.append("docs/papers.json.note: expected nonempty metadata-only description")
        if not isinstance(doc.get("papers"), list) or not doc["papers"]:
            failures.append("docs/papers.json.papers: expected a nonempty list")
        else:
            rows = doc["papers"]
        for i, row in enumerate(rows):
            label = f"docs/papers.json.papers[{i}]"
            if not isinstance(row, dict):
                failures.append(f"{label}: expected a record")
                continue
            if set(row) - {"doi", "title", "access", "role", "serves"}:
                failures.append(f"{label}: unsupported fields; metadata must not contain fetched-text/status evidence")
            raw_doi = row.get("doi")
            doi = _doi(raw_doi)
            if raw_doi == "" and _text(row.get("title")):
                # Paper.from_gathered deliberately preserves title-only records.
                info["published_without_doi"] += 1
                warnings.append(f"{label}: title-only published reference has no DOI; not directly fetchable")
            elif doi is None:
                failures.append(f"{label}.doi: expected a DOI")
            elif doi in papers:
                failures.append(f"{label}.doi: duplicate normalized DOI {doi!r}")
            else:
                papers.add(doi)
            if not isinstance(row.get("title"), str):
                failures.append(f"{label}.title: expected a string")
            elif not row["title"].strip():
                warnings.append(f"{label}.title: blank published title; DOI metadata has not been enriched")
            if row.get("access") not in ("open", "subscription"):
                failures.append(f"{label}.access: expected open or subscription")
            if "role" in row and not isinstance(row["role"], str):
                failures.append(f"{label}.role: expected a string")
            if "serves" in row and not _strings(row["serves"]):
                failures.append(f"{label}.serves: expected a list of nonempty quantity strings")
        for key, actual in (("count", len(rows)),
                            ("open_access", sum(isinstance(r, dict) and r.get("access") == "open" for r in rows))):
            if type(doc.get(key)) is not int or doc[key] != actual:
                failures.append(f"docs/papers.json.{key}: must equal {actual}")

    convention = (_read(root, "docs/validation_convention.yaml", failures)
                  if kind == "process_model" or (root / "docs/validation_convention.yaml").exists()
                  else None)
    references, deferred = {}, set()
    if convention is not None:
        if kind == "process_model" or "model_id" in convention:
            _identity(convention.get("model_id"), model_name,
                      "docs/validation_convention.yaml.model_id", failures)
        references = convention.get("references", {})
        if not isinstance(references, dict):
            failures.append("docs/validation_convention.yaml.references: expected a mapping")
            references = {}
        reference_dois = set()
        for key, row in references.items():
            label = f"docs/validation_convention.yaml.references.{key}"
            if not _text(key) or not isinstance(row, dict):
                failures.append(f"{label}: expected a named reference record")
                continue
            doi = _doi(row.get("doi"))
            if doi is None:
                failures.append(f"{label}.doi: expected a DOI")
            else:
                reference_dois.add(doi)
                if doi not in papers:
                    info["validation_references_outside_papers"] += 1
                    warnings.append(f"{label}: DOI {doi!r} absent from docs/papers.json; declared reference metadata remains in the convention, fetched-text evidence is not verified")
        info["validation_reference_count"] = len(references)
        _cites(convention, "cites", references, "validation_convention", failures)
        entries = convention.get("deferred_paywalled", [])
        if not isinstance(entries, list):
            failures.append("docs/validation_convention.yaml.deferred_paywalled: expected a list")
            entries = []
        for i, row in enumerate(entries):
            label = f"docs/validation_convention.yaml.deferred_paywalled[{i}]"
            if not isinstance(row, dict):
                failures.append(f"{label}: expected a deferred reference record")
                continue
            if set(row) != {"doi", "ref", "needed_for"}:
                failures.append(f"{label}: expected doi, ref and needed_for; deferred literature is not fetched evidence")
            raw_doi = row.get("doi")
            doi = _doi(raw_doi)
            if raw_doi is None or raw_doi in ("unknown_not_fetched", "unknown_standard_not_fetched"):
                # These explicit shipped sentinels name unmet literature needs.
                # They never enter the DOI set and cannot fill a citation gap.
                info["deferred_without_doi"] += 1
            elif doi is None:
                failures.append(f"{label}.doi: expected a DOI")
            elif doi in deferred:
                failures.append(f"{label}: duplicate normalized deferred DOI {doi!r}")
            else:
                deferred.add(doi)
            if not _text(row.get("ref")) or not _strings(row.get("needed_for")) or not row.get("needed_for"):
                failures.append(f"{label}: nonempty ref and needed_for quantities are required")
            if doi in reference_dois:
                failures.append(f"{label}: DOI {doi!r} is both deferred and a validation reference")
        info["deferred_count"] = len(entries)

    dag = (_read(root, "dag.yaml", failures)
           if kind == "process_model" or (root / "dag.yaml").exists() else None)
    if dag is not None:
        identity = dag.get("identity")
        if kind == "process_model" or isinstance(identity, dict) and "model_id" in identity:
            _identity(identity.get("model_id") if isinstance(identity, dict) else None,
                      model_name, "dag.yaml.identity.model_id", failures)
        influence = dag.get("influence", {})
        if not isinstance(influence, dict):
            failures.append("dag.yaml.influence: expected a mapping")
            influence = {}
        citations = influence.get("citation_index", {})
        if not isinstance(citations, dict):
            failures.append("dag.yaml.influence.citation_index: expected a mapping")
            citations = {}
        info["dag_citation_count"] = len(citations)
        for key, row in citations.items():
            label = f"dag.yaml.influence.citation_index.{key}"
            if not _text(key) or not isinstance(row, dict):
                failures.append(f"{label}: expected a named citation record")
                continue
            raw_doi = row.get("doi")
            if raw_doi in (None, ""):
                if not _text(row.get("short_citation")) or not _text(row.get("note")):
                    failures.append(f"{label}: DOI-less bibliography needs short_citation and an explanatory note")
                else:
                    info["dag_bibliography_without_doi"] += 1
                continue
            doi = _doi(raw_doi)
            if doi is None:
                failures.append(f"{label}.doi: expected a DOI")
            elif doi in deferred:
                info["dag_deferred_count"] += 1
            elif doi not in papers:
                info["dag_citations_outside_papers"] += 1
                warnings.append(f"{label}: DOI {doi!r} absent from published papers and explicit deferred metadata; DAG citation metadata alone does not prove fetched/read evidence")
        _cites(dag, "citations", citations, "dag", failures)
    if info["dag_deferred_count"]:
        warnings.append(f"{info['dag_deferred_count']} DAG citation(s) remain explicitly deferred/paywalled; no fetched-text or validation evidence is claimed")
    if info["dag_bibliography_without_doi"]:
        warnings.append(f"{info['dag_bibliography_without_doi']} DAG bibliography item(s) have no DOI; descriptive metadata only, not crosslinked paper evidence")
    if info["deferred_without_doi"]:
        warnings.append(f"{info['deferred_without_doi']} deferred literature target(s) have no known DOI; unmet needs only, not crosslinked paper evidence")
    return {"ok": not failures, "present": present, "count": len(rows),
            "failures": failures, "warnings": warnings, "info": info}
