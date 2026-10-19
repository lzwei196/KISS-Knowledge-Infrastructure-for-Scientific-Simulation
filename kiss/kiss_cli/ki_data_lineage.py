"""Read-only bundled-data provenance across completed local maintenance.

A maintenance adoption is not a fresh portable projection. This composition
keeps that distinction, and grants neither readiness nor repair reuse authority.
"""
from __future__ import annotations

from pathlib import Path

from . import ki_adaptations as adapt, ki_guard, ki_verification, software_verification

MAX_ADOPTIONS = 32
MAX_JOURNALS = 1000


def _retained_projection(doc, live, retained, cfg):
    """Reproduce the original signed projection on exact frozen baseline bytes."""
    adapt._auth(doc)
    if (doc.get("kind") != "projection" or doc.get("live_root") != str(live)
            or doc.get("projected_digest") != adapt._digest(retained)
            or doc.get("context_id") != adapt._hash(doc.get("context"))):
        raise ValueError("Original KI projection or saved runtime binding is stale")
    adapt.require_projection_runtime(doc, cfg)
    adapt._retained(doc["upstream_root"], doc["upstream_digest"])
    portable = adapt._retained(doc["portable_root"], doc["portable_digest"])
    adapt.require_path_binding(doc, cfg)
    expected_helpers = doc["context"].get("helper_source_digest")
    if expected_helpers is not None and adapt._prepared_helper(cfg) != expected_helpers:
        raise ValueError("Prepared shared helpers no longer match the original signed KI lineage")
    if doc.get("portable_report"):
        ki_verification.require_current(portable, doc["portable_report"])
    if doc.get("path_projection") is not None:
        from . import ki_fresh_paths
        report = doc["path_projection"]
        if (report.get("logical_target") != doc.get("logical_target")
                or report.get("policy_sha256") != doc["context"].get("path_normalizer")):
            raise ValueError("Original fresh-path policy/target differs from its signed lineage")
        # Only the physical inspection location changes in this ephemeral copy.
        # The signed full digest, logical deployment target, runtime, source and
        # exact reproduced file inventory all remain mandatory. Nothing is saved.
        retained_report = {**report, "physical_root": str(retained)}
        ki_fresh_paths.require_fresh_current(retained_report, candidate_root=retained)


def _adoption(project, ki, live, doc, digest):
    from . import ki_investigation as investigation, ki_maintenance
    draft, verification, transaction = doc.get("draft") or {}, doc.get("verification") or {}, doc.get("apply") or {}
    source = draft.get("maintenance_source") or {}
    report = verification.get("report") or {}
    if (doc.get("status") != "applied" or transaction.get("status") != "complete"
            or draft.get("repair_mode") != "maintenance" or draft.get("authoring_scope") != "local"
            or draft.get("project_local") is not True or draft.get("ki_name") != ki
            or draft.get("active_root") != str(live) or doc.get("ki_roots", {}).get(ki) != str(live)
            or transaction.get("ki_name") != ki or verification.get("ok") is not True
            or transaction.get("verification_id") != verification.get("id")
            or transaction.get("new_digest") != digest or transaction.get("adopted_digest") != digest
            or report.get("candidate_digest") != digest
            or source.get("original_root") != str(live)
            or source.get("source_scope") != "intact_host_baseline"
            or transaction.get("old_digest") != source.get("base_digest")
            or doc.get("baseline_digests", {}).get(ki) != source.get("base_digest")
            or source.get("base_digest") == digest):
        raise ValueError("KI data requires a completed exact maintenance adoption journal")
    # Reuse the same host gates as explicit adoption, including the retained
    # candidate, current maintenance policy and any runtime-sensitive recipe.
    candidate = investigation._require_verified_candidates(doc)
    if adapt._digest(candidate) != digest:
        raise ValueError("Retained maintenance candidate differs from the adopted KI")
    base = ki_maintenance.require_source(source, name=ki)
    return base, source


def require_projection(project, ki, live, cfg):
    """Return authentic projection/data lineage; never refresh or enroll it."""
    try:
        return _require_projection(project, ki, live, cfg)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Maintenance data lineage is incomplete or malformed; review the retained repair history") from error


def _require_projection(project, ki, live, cfg):
    project, live = Path(project).resolve(), Path(live).absolute()
    derived = require_setup_projection(project, ki, live, cfg)
    if derived is not None:
        return derived
    return _ordinary_projection(project, ki, live, cfg)


def _ordinary_projection(project, ki, live, cfg):
    """Original projection/maintenance route, without Setup-derivation recursion."""
    try:
        return adapt.projection(live, cfg)
    except adapt.AdaptationError:
        # Do not turn a missing, corrupt or same-digest stale projection into a
        # fallback. Only a committed maintenance revision can compose lineage.
        origin = adapt._read(adapt._location(live))
        current = adapt._digest(live)
        if origin is None or origin.get("projected_digest") == current:
            raise
    baseline = ki_guard.require_intact(live, required=True)
    retained, source, chain = _maintenance_chain(project, ki, live, current, origin.get("projected_digest"))
    _retained_projection(origin, live, retained, cfg)
    if ki_guard.require_intact(live, required=True) != baseline or adapt._read(adapt._location(live)) != origin:
        raise ValueError("KI authority changed while checking bundled data lineage")
    return {"kind": "maintenance_data_lineage", "live_root": str(live),
            "projected_digest": current, "original_projection": origin, "adoptions": chain,
            "unchanged_ki_data_sha256": {path: row["sha256"] for path, row in source["protected_inventory"].items()
                                          if row.get("kind") == "file"}}


def require_setup_projection(project, ki, live, cfg):
    """Optional current Setup-derived lineage, including later reviewed repairs.

    Absence alone returns None. This is also the GUI/preflight gate: pending
    derivations cannot fall back even while ordinary projected bytes are intact.
    Historical baseline authentication grants no authority over newer live bytes;
    the existing exact signed maintenance chain must prove every later adoption.
    """
    from . import project_setup_repair
    project, live = Path(project).resolve(), Path(live).absolute()
    try:
        derived = project_setup_repair.require_baseline(live, cfg, model=ki)
        if derived is None:
            baseline = ki_guard.require_intact(live, required=False)
            if baseline and baseline.get("origin") == "verified_maintenance_candidate":
                # Missing Setup authority cannot downgrade maintained bytes to
                # legacy. Genuine older project maintenance must still prove
                # its own complete journal chain to the ordinary projection.
                proof = _ordinary_projection(project, ki, live, cfg)
                if proof is None:
                    raise ValueError("Maintained project KI has no authenticated projection lineage")
                return proof
            return None
        binding = derived["binding"]
        if (binding.get("project_root") != str(project)
                or binding.get("live_root") != str(live)
                or Path(cfg.root).absolute() != project):
            raise ValueError("Project maintenance data belongs to another project binding")
        baseline = ki_guard.require_intact(live, required=True)
        current, chain = adapt._digest(live), []
        if current == derived["projected_digest"]:
            project_setup_repair.require_record(live, cfg, model=ki)
            retained = None  # Recheck the preserved immutable candidate below.
        else:
            retained, _source, chain = _maintenance_chain(
                project, ki, live, current, derived["projected_digest"])
        checked = project_setup_repair.require_baseline(live, cfg, model=ki, retained=retained)
        if checked != derived or ki_guard.require_intact(live, required=True) != baseline:
            raise ValueError("Project maintenance authority changed while checking bundled data lineage")
        return {"kind": "maintenance_data_lineage", "live_root": str(live),
                "projected_digest": current, "adoptions": chain,
                "original_projection": derived["ordinary_projection"],
                "project_derivation": {"policy": derived["policy"],
                    "setup_adoption_digest": binding["setup_adoption_digest"],
                    "recipe": binding["recipe"]},
                "unchanged_ki_data_sha256": {
                    path: row["sha256"] for path, row in derived["protected_inventory"].items()
                    if row.get("kind") == "file"}}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Project maintenance derivation is incomplete or malformed") from error


def _maintenance_chain(project, ki, live, current, stop_digest):
    from . import ki_investigation as investigation
    baseline = ki_guard.require_intact(live, required=True)
    if baseline.get("origin") != "verified_maintenance_candidate":
        raise ValueError("Changed KI projection has no authenticated maintenance adoption")
    pending = investigation.pending_preflight(project).get("kis", {}).get(ki)
    if not isinstance(pending, dict) or pending.get("digest") != current:
        raise ValueError("Maintenance adoption has no matching host project record")
    doc = investigation._load(project, pending.get("job_id"))
    if pending.get("verification_id") != (doc.get("verification") or {}).get("id"):
        raise ValueError("Maintenance project record names another verification")
    digest, seen, chain = current, set(), []
    journals = None
    for _ in range(MAX_ADOPTIONS):
        if doc["id"] in seen:
            raise ValueError("Maintenance lineage contains a cycle")
        seen.add(doc["id"])
        retained, source = _adoption(project, ki, live, doc, digest)
        chain.append(doc["id"])
        digest = source["base_digest"]
        if digest == stop_digest:
            break
        if journals is None:
            candidates = list(investigation._base(project).glob("*/job.json"))
            if len(candidates) > MAX_JOURNALS:
                raise ValueError("Maintenance journal inventory exceeds its bounded size")
            journals = [investigation._load(project, p.parent.name) for p in candidates]
        parents = [row for row in journals if row.get("id") not in seen
                   and (row.get("apply") or {}).get("adopted_digest") == digest
                   and row.get("status") == "applied"
                   and (row.get("draft") or {}).get("active_root") == str(live)]
        if len(parents) != 1:
            raise ValueError("Maintenance lineage is incomplete or ambiguous; review the retained repair history")
        doc = parents[0]
    else:
        raise ValueError("Maintenance lineage exceeds its bounded history")
    if ki_guard.require_intact(live, required=True) != baseline:
        raise ValueError("KI authority changed while checking bundled data lineage")
    return retained, source, chain
