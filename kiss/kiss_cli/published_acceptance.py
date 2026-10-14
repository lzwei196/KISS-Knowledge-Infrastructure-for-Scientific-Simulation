"""Official distribution acceptance, separate from KDT authoring acceptance.

Only the updater issues origins, after fetching an exact official commit. A
signed snapshot envelope authorizes catalogue enrollment at its managed path;
a portable package report alone never authorizes import, edits or adoption.
These host receipts are not a sandbox against other same-user applications.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import doctor, kdtstudio, ki_verification

POLICY = "official-published-ki-v2"
SCOPE = "official_published_package"
SNAPSHOT_CONTRACT = "all-packages-current-published-kdt-v1"
REPOSITORY = "lzwei196/KISS---Knowledge-Infrastructure-for-Scientific-Simulation"


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def profile_digest() -> str:
    import sys
    from . import ki_guidance_composition, platform_guidance_provenance, published_kdt
    return _hash({"profile": published_kdt.profile_source_digest(),
                  "acceptance": published_kdt._module_identity(sys.modules[__name__]),
                  "guidance": platform_guidance_provenance._implementation(),
                  "composition": ki_guidance_composition.policy_digest()})


def _authority(root: Path) -> Path:
    return ki_verification._authority(root) / "publication"


def _sign(root: Path, value: dict) -> dict:
    return ki_verification._receipts().sign(_authority(root), value)


def _authentic(root: Path, value: dict) -> bool:
    return isinstance(value, dict) and ki_verification._receipts().verify(_authority(root), value)


def _issue_origin(root: Path, *, source_commit: str, archive_sha256: str,
                  source_content_sha256: str, overlay: dict, trees: dict) -> dict:
    """Internal updater boundary, never an agent tool or a request parameter."""
    from . import ki_updates
    from .catalog import Catalog
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit or ""):
        raise ValueError("Official publication requires an exact source commit")
    if any(not re.fullmatch(r"[0-9a-f]{64}", value or "")
           for value in (archive_sha256, source_content_sha256)):
        raise ValueError("Official publication requires archive and extracted-source hashes")
    root = Path(root).resolve()
    if root.parent != ki_updates.update_root().resolve() or not root.name.startswith(".incoming-"):
        raise ValueError("Publication origin can only be issued for updater staging")
    packages = {}
    for ki in Catalog(root / "models", data_dir=ki_updates.data_ki_root(root)):
        digest = ki_verification.content_digest(ki.root)
        if not digest:
            raise ValueError(f"Cannot bind published package {ki.name}")
        packages[ki.name] = {"path": ki.root.relative_to(root).as_posix(), "digest": digest}
    return _sign(root, {
        "scope": "official_update_origin", "policy": POLICY,
        "repository": REPOSITORY, "source_commit": source_commit,
        "archive_sha256": archive_sha256, "source_content_sha256": source_content_sha256,
        "candidate_content_sha256": ki_updates._snapshot_content_hash(root),
        "staging_root": str(root), "trees": trees, "overlay": overlay,
        "packages": packages,
    })


def _origin_valid(root: Path, origin: dict) -> bool:
    return (_authentic(root, origin) and origin.get("scope") == "official_update_origin"
            and origin.get("policy") == POLICY and origin.get("repository") == REPOSITORY)


def verify_candidate(root: Path, *, name: str, kind: str, origin: dict) -> dict:
    from . import published_kdt
    root = Path(root).resolve()
    if not _origin_valid(root, origin):
        raise ValueError("Missing authentic official update origin")
    expected = (origin.get("packages") or {}).get(name) or {}
    staging = Path(origin["staging_root"])
    if (root != (staging / expected.get("path", "")).resolve()
            or ki_verification.content_digest(root) != expected.get("digest")):
        raise ValueError("Published candidate differs from its official staging origin")
    if os.environ.get("GEOFORGE_KDT_ENGINE"):
        raise ValueError("Official publication requires the reviewed installed KDT engine")
    profile_before = profile_digest()
    report = ki_verification._check_candidate(root, name=name, kind=kind,
        _gate_adapter=lambda gate: published_kdt.gate_view(gate, model_name=name))
    if profile_digest() != profile_before:
        raise ValueError("Published verifier changed during verification; retry with the current profile")
    report.update(gate_policy=POLICY, scope=SCOPE, profile_digest=profile_before,
                  origin_id=_hash(origin), source_commit=origin["source_commit"],
                  name=name, package_path=expected["path"],
                  state="PublishedPackageAccepted" if report["ok"] else "PublicationRejected",
                  authoring_verification=False, literature_evidence="published_metadata_only")
    return _sign(root, report)


def require_current(root: Path, report: dict, *, name: str, origin: dict) -> dict:
    if not _origin_valid(root, origin) or not _authentic(root, report):
        raise ValueError("Published acceptance is unauthenticated")
    expected = (origin.get("packages") or {}).get(name) or {}
    if (report.get("scope") != SCOPE or report.get("gate_policy") != POLICY
            or report.get("ok") is not True or report.get("name") != name
            or report.get("state") != "PublishedPackageAccepted"
            or report.get("authoring_verification") is not False
            or report.get("literature_evidence") != "published_metadata_only"
            or report.get("origin_id") != _hash(origin)
            or report.get("source_commit") != origin.get("source_commit")
            or report.get("package_path") != expected.get("path")
            or report.get("candidate_digest") != expected.get("digest")
            or report.get("profile_digest") != profile_digest()
            or report.get("doctor_policy") != doctor.VALIDATION_POLICY_VERSION
            or report.get("engine_policy") != kdtstudio.REVIEWED_COMMIT
            or report.get("engine_source_digest") != kdtstudio.engine_source_digest()
            or report.get("engine_override") is not False
            or report.get("desktop_requested") is not True):
        raise ValueError("Published acceptance failed or its evidence contract changed")
    if ki_verification.content_digest(root) != expected.get("digest"):
        raise ValueError("Published package contents changed after verification")
    return report


def _require_package_reports(root: Path, origin: dict, rows: list[dict]) -> None:
    """Integrity of old bytes never substitutes for current package evidence."""
    expected = origin.get("packages")
    if (not isinstance(expected, dict) or not expected or not isinstance(rows, list)
            or any(not isinstance(row, dict) or not isinstance(row.get("name"), str) for row in rows)
            or len(rows) != len(expected) or {row["name"] for row in rows} != set(expected)):
        raise ValueError("Official snapshot acceptance does not cover every package")
    for row in rows:
        item = expected[row["name"]]
        if (row.get("state") != "PublishedPackageAccepted"
                or row.get("candidate_digest") != item.get("digest")
                or not isinstance(row.get("report"), dict)):
            raise ValueError(f"Every package needs current published KDT acceptance: {row['name']}")
        require_current(root / item["path"], row["report"], name=row["name"], origin=origin)


def _seal_snapshot(root: Path, *, origin: dict, rows: list[dict], revision: str) -> dict:
    from . import ki_updates
    if (not _origin_valid(root, origin)
            or ki_updates._snapshot_content_hash(root) != origin["candidate_content_sha256"]):
        raise ValueError("Official snapshot changed before publication acceptance")
    _require_package_reports(root, origin, rows)
    return _sign(root, {"scope": "official_published_snapshot", "policy": POLICY,
        "package_validation": SNAPSHOT_CONTRACT,
        "revision": revision, "content_sha256": origin["candidate_content_sha256"],
        "profile_digest": profile_digest(), "origin": origin, "packages": rows,
        "engine_policy": kdtstudio.REVIEWED_COMMIT,
        "engine_source_digest": kdtstudio.engine_source_digest(),
        "doctor_policy": doctor.VALIDATION_POLICY_VERSION,
        "checked_at": time.time(), "native_regression": "not_run"})


def require_snapshot(root: Path, meta: dict) -> dict:
    """Accept only a sealed managed snapshot, never a caller-supplied report."""
    from . import ki_updates
    root = Path(root).resolve()
    envelope = meta.get("publication_acceptance")
    if (root.parent != (ki_updates.update_root() / "snapshots").resolve()
            or root.name != meta.get("revision") or not _authentic(root, envelope)
            or envelope.get("scope") != "official_published_snapshot"
            or envelope.get("policy") != POLICY or envelope.get("revision") != root.name
            or envelope.get("package_validation") != SNAPSHOT_CONTRACT
            or envelope.get("profile_digest") != profile_digest()
            or envelope.get("engine_policy") != kdtstudio.REVIEWED_COMMIT
            or envelope.get("engine_source_digest") != kdtstudio.engine_source_digest()
            or envelope.get("doctor_policy") != doctor.VALIDATION_POLICY_VERSION):
        raise ValueError("Missing current signed acceptance for the managed snapshot")
    origin = envelope.get("origin") or {}
    if (not _origin_valid(root, origin) or meta.get("source_commit") != origin.get("source_commit")
            or meta.get("trees") != origin.get("trees")
            or (meta.get("windows_overlay") or None) != (origin.get("overlay") or None)
            or meta.get("content_sha256") != envelope.get("content_sha256")
            or envelope.get("content_sha256") != ki_updates._snapshot_content_hash(root)):
        raise ValueError("Official snapshot provenance or content changed")
    _require_package_reports(root, origin, envelope.get("packages"))
    return envelope


def catalogue_bindings(catalog) -> dict:
    """Publication enrollment is restricted to the signed snapshot namespace."""
    from . import ki_updates
    root = Path(catalog.models_dir).resolve().parent
    if root.parent != (ki_updates.update_root() / "snapshots").resolve():
        return {}
    try:
        envelope = require_snapshot(root, ki_updates._read_json(root / ki_updates.SNAPSHOT_MANIFEST))
    except (OSError, ValueError, TypeError):
        return {}
    origin = envelope["origin"]
    accepted = {}
    for row in envelope["packages"]:
        name = row["name"]
        ki = catalog.packages.get(name)
        expected = origin["packages"][name]
        if not ki or Path(ki.root).resolve() != (root / expected["path"]).resolve():
            continue
        try:
            require_current(ki.root, row["report"], name=name, origin=origin)
            accepted[name] = expected["digest"]
        except (OSError, ValueError, TypeError):
            continue
    return accepted
