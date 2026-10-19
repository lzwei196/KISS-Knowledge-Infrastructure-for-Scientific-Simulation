"""Refresh runtime fingerprints only while bootstrapping a new installation.

Installing Python into the already selected environment can replace its
launcher without changing a single KI path or byte. A trusted setup ticket
allows the host to reproduce the exact projection and refresh that fingerprint.
This is not KI editing, runtime relocation, or software/scientific verification.
Existing installations cannot obtain a ticket from their editable status files.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path
import time
import uuid

from . import (helper_identity, install, ki_adaptations, ki_guard,
               ki_verification, paths, setup, software_verification)


@dataclass(frozen=True)
class FreshSetupTicket:
    root: Path
    nonce: str


@dataclass
class RuntimeChange:
    """In-memory host transaction; never accepted from an agent request."""
    ticket: FreshSetupTicket
    before: dict
    expected_projection: dict | None
    expected_ticket: dict


def _location(ticket):
    if not isinstance(ticket, FreshSetupTicket) or len(ticket.nonce) != 32:
        raise ValueError("A host-created fresh setup ticket is required")
    if any(ch not in "0123456789abcdef" for ch in ticket.nonce):
        raise ValueError("Invalid fresh setup ticket")
    return ki_adaptations._home() / "fresh-setups" / (ticket.nonce + ".json")


def _read(ticket, *, state=None):
    record = ki_adaptations._read(_location(ticket))
    if (not record or record.get("kind") != "fresh_setup_runtime"
            or record.get("root") != str(ticket.root)
            or record.get("nonce") != ticket.nonce
            or (state is not None and record.get("state") != state)):
        raise ValueError("Fresh setup authority is absent, closed or changed")
    return record


def _write(ticket, record):
    return ki_adaptations._write(_location(ticket), record)


def begin(root, *, allowed=True):
    """Called by the host before creating the first active setup KI.

    No provider-controlled readiness flag is consulted. An existing or formerly
    enrolled KI cannot become fresh by deleting its files or status.json.
    """
    if not allowed:
        return None
    root = Path(root).absolute()
    live = root / "ki"
    if (root.resolve() != root or live.exists() or live.is_symlink()
            or ki_guard.is_managed(live)):
        return None
    ki_adaptations._separate(root)
    ticket = FreshSetupTicket(root, uuid.uuid4().hex)
    _write(ticket, {**ki_adaptations._base(), "kind": "fresh_setup_runtime",
                   "root": str(root), "nonce": ticket.nonce, "state": "started",
                   "created_at": time.time(), "refreshes": []})
    return ticket


def _identity(cfg):
    return software_verification.runtime_identity(cfg)


def _helpers(cfg):
    common = Path(cfg.roles["ki_tools_common"])
    binding, files, legacy = helper_identity.checked_marker(common)
    if legacy:
        raise ValueError("Fresh setup requires source-bound shared helpers")
    return {"root": str(common), "binding": binding, "files": files,
            "marker_sha256": hashlib.sha256((common / helper_identity.MARKER).read_bytes()).hexdigest()}


def capture(ticket, ki, live_ki, cfg, *, library_root, manifest):
    """Freeze the host's freshly created source/config/projection before DS."""
    if ticket is None:
        return
    record = _read(ticket, state="started")
    if (Path(cfg.root).absolute() != ticket.root
            or Path(live_ki.root).absolute() != ticket.root / "ki"
            or ki.name != live_ki.name):
        raise ValueError("Fresh setup binding does not match its reserved workspace")
    origin = ki_adaptations.projection(live_ki.root, cfg)
    if not origin or not origin.get("path_projection"):
        # Most KIs have no executable-content-bound path proof to renew.
        # The hook must not impose new runtime/helper bootstrap prerequisites
        # on those installations; their ordinary setup checks still apply.
        record.update(state="not_applicable", reason="no_runtime_fingerprint_projection")
        # A host runtime bootstrap can also serve ordinary Python KIs. Capture
        # that optional authority only when existing strict bindings already
        # qualify; it must never become a new prerequisite for native KIs.
        try:
            _contained_runtime(ticket, cfg)
            ki_guard.require_intact(ki.root)
            ki_guard.require_intact(live_ki.root)
            if _identity(setup.load_runtime_config(ticket.root)) != _identity(cfg):
                raise ValueError("Saved runtime changed")
            record.update(state="captured_basic", model=ki.name,
                source=str(Path(ki.root).absolute()), library=str(Path(library_root).absolute()),
                runtime_identity=_identity(cfg), projection=origin, helpers=_helpers(cfg),
                context=ki_adaptations._context(ki.root, cfg, model=ki.name,
                    library_root=library_root, manifest=manifest),
                source_digest=ki_verification.content_digest(ki.root),
                active_digest=ki_verification.content_digest(live_ki.root))
        except (ValueError, KeyError, OSError) as error:
            record.update(state="not_applicable", reason="no_bound_workspace_python",
                          bootstrap_ineligible=str(error))
        _write(ticket, record)
        return
    ki_guard.require_intact(ki.root)
    context = ki_adaptations._context(ki.root, cfg, model=ki.name,
                                      library_root=library_root, manifest=manifest)
    if (context != origin["context"] or origin["source_root"] != str(Path(ki.root).absolute())
            or origin["logical_target"] != str(ticket.root / "ki")
            or _identity(setup.load_runtime_config(ticket.root)) != _identity(cfg)):
        raise ValueError("Fresh setup source or saved runtime changed during preparation")
    # Only the model workspace's environment can be populated during setup.
    # On POSIX the interpreter itself may legitimately be a venv symlink.
    _contained_runtime(ticket, cfg)
    record.update(state="captured", model=ki.name, source=str(Path(ki.root).absolute()),
                  library=str(Path(library_root).absolute()), runtime_identity=_identity(cfg),
                  projection=origin, helpers=_helpers(cfg))
    _write(ticket, record)


def _contained_runtime(ticket, cfg):
    selected, environment = Path(cfg.python).absolute(), Path(cfg.roles["python_env"]).absolute()
    if (ticket.root not in selected.parents or ticket.root not in environment.parents
            or environment.resolve() != environment
            or selected.parent.resolve() != selected.parent):
        raise ValueError("Fresh setup runtime must be inside its unaliased workspace")


def _current(ticket, record, ki, live_ki, cfg, library_root, manifest):
    if (Path(cfg.root).absolute() != ticket.root
            or Path(live_ki.root).absolute() != ticket.root / "ki"
            or ki.name != record["model"] or live_ki.name != ki.name
            or str(Path(ki.root).absolute()) != record["source"]
            or str(Path(library_root).absolute()) != record["library"]
            or _identity(cfg) != record["runtime_identity"]
            or _identity(setup.load_runtime_config(ticket.root)) != record["runtime_identity"]):
        raise ValueError("Fresh setup may not relocate or change its saved runtime paths")
    ki_guard.require_intact(ki.root)
    ki_guard.require_intact(live_ki.root)
    origin = record["projection"]
    if record.get("state") == "captured_basic":
        if (ki_adaptations._read(ki_adaptations._location(live_ki.root)) != origin
                or ki_verification.content_digest(ki.root) != record["source_digest"]
                or ki_verification.content_digest(live_ki.root) != record["active_digest"]
                or ki_adaptations._context(ki.root, cfg, model=ki.name,
                    library_root=library_root, manifest=manifest) != record["context"]
                or _helpers(cfg) != record["helpers"]):
            raise ValueError("Fresh setup source, KI, helpers or authority changed")
        return origin, None
    if (ki_adaptations._read(ki_adaptations._location(live_ki.root)) != origin
            or ki_verification.content_digest(live_ki.root) != origin["projected_digest"]
            or ki_adaptations._context(ki.root, cfg, model=ki.name,
                library_root=library_root, manifest=manifest) != origin["context"]
            or _helpers(cfg) != record["helpers"]):
        raise ValueError("Fresh setup source, KI, helpers or projection authority changed")
    ki_adaptations._retained(origin["upstream_root"], origin["upstream_digest"])
    portable = ki_adaptations._retained(origin["portable_root"], origin["portable_digest"])
    if origin.get("portable_report"):
        ki_verification.require_current(portable, origin["portable_report"])
    return origin, portable


def require_current(ticket, ki, live_ki, cfg, *, library_root, manifest):
    """Host bootstrap authority; never issued from provider-editable status."""
    record = _read(ticket)
    if record.get("state") not in {"captured", "captured_basic"}:
        raise ValueError("An active fresh setup with bound workspace Python is required")
    _contained_runtime(ticket, cfg)
    _current(ticket, record, ki, live_ki, cfg, library_root, manifest)
    return record


def begin_change(ticket, ki, live_ki, cfg, *, library_root, manifest):
    record = require_current(ticket, ki, live_ki, cfg,
                             library_root=library_root, manifest=manifest)
    return RuntimeChange(ticket, deepcopy(record), deepcopy(record["projection"]), deepcopy(record))


def _unsigned(doc):
    return {key: value for key, value in doc.items() if key != "signature"} if doc else doc


def rollback_change(change, restore_runtime, ki, live_ki, cfg, *, library_root, manifest):
    """Restore only this transaction's exact authenticated records and runtime.

    A concurrent/foreign authority change is not overwritten. The caller keeps
    all candidate environments for diagnosis rather than deleting them.
    """
    record = _read(change.ticket)
    projection = ki_adaptations._read(ki_adaptations._location(live_ki.root))
    if (_unsigned(record) not in [_unsigned(change.before), _unsigned(change.expected_ticket)]
            or _unsigned(projection) not in [_unsigned(change.before["projection"]),
                                           _unsigned(change.expected_projection)]):
        raise ValueError("Runtime rollback refused changed host authority; environments were retained")
    current = deepcopy(change.before)
    current["projection"] = projection
    _current(change.ticket, current, ki, live_ki, cfg, library_root, manifest)
    restore_runtime()
    if projection != change.before["projection"]:
        ki_adaptations._write(ki_adaptations._location(live_ki.root), change.before["projection"])
    if record != change.before:
        _write(change.ticket, change.before)
    # Ordinary validation proves the restored interpreter matches its old proof.
    ki_adaptations.projection(live_ki.root, cfg)


def refresh(ticket, ki, live_ki, cfg, *, library_root, manifest, change=None):
    """Prove byte-identical projection under a replaced same-path interpreter.

    Called only from the active host setup lifecycle, before its normal final
    checks. The signed ticket closes when that attempt ends. This writes no KI,
    helper, config, approval, execution receipt, or ready status.
    """
    if ticket is None:
        return False
    with ki_guard.operation(live_ki.root):
        record = _read(ticket)
        if record.get("state") in {"not_applicable", "captured_basic"}:
            return False
        if record.get("state") != "captured":
            raise ValueError("Fresh setup authority is absent, closed or changed")
        origin, portable = _current(ticket, record, ki, live_ki, cfg, library_root, manifest)
        proof = origin.get("path_projection")
        if not proof:
            ki_adaptations.projection(live_ki.root, cfg)
            return False
        from . import ki_fresh_paths
        current_runtime = ki_fresh_paths._fresh_runtime(cfg)
        if current_runtime == proof["runtime"]:
            ki_adaptations.projection(live_ki.root, cfg)
            return False
        unchanged = {key: value for key, value in current_runtime.items() if key != "selected_python"}
        previous = {key: value for key, value in proof["runtime"].items() if key != "selected_python"}
        if unchanged != previous:
            raise ValueError("Only the fresh setup interpreter fingerprint may change")
        # A replaced launcher must still identify this exact Python environment.
        checked_cfg = deepcopy(cfg)
        checked = setup.prepare_existing_python(checked_cfg, live_ki.root, cfg.python)
        if not checked.ok or _identity(checked_cfg) != record["runtime_identity"]:
            raise ValueError("Fresh setup interpreter identity check failed: " + checked.detail)
        install.check_cancelled()
        with install.scratch_directory(".setup-runtime-proof-", None) as scratch:
            candidate = Path(scratch) / "ki"
            report, renewed = ki_adaptations.project_runtime(portable, candidate, cfg,
                model=ki.name, target_root=live_ki.root, manifest=origin.get("effective_manifest"))
            if (report.unresolved or report.corrupted or renewed is None
                    or ki_verification.content_digest(candidate) != origin["projected_digest"]
                    or renewed["runtime"] != current_runtime):
                raise ValueError("Fresh runtime projection differs from the intact active KI")
            ki_fresh_paths.require_fresh_current(renewed, candidate_root=live_ki.root)
            _current(ticket, record, ki, live_ki, cfg, library_root, manifest)
            install.check_cancelled()
            updated = deepcopy(origin)
            updated["path_projection"] = renewed
            updated["runtime_refresh"] = {"scope": "fresh_setup_same_paths",
                "ticket": ticket.nonce, "ki_changed": False, "helpers_changed": False,
                "preflight_passed": False, "refreshed_at": time.time()}
            if change is not None:
                if change.ticket != ticket:
                    raise ValueError("Runtime transaction belongs to another setup")
                change.expected_projection = deepcopy(updated)
            written = ki_adaptations._write(ki_adaptations._location(live_ki.root), updated)
            # This ordinary reader independently checks the renewed exact proof.
            ki_adaptations.projection(live_ki.root, cfg)
            record["projection"] = written
            record["refreshes"].append({"previous_python": proof["runtime"]["selected_python"],
                "current_python": current_runtime["selected_python"], "at": time.time()})
            if change is not None:
                change.expected_ticket = deepcopy(record)
            _write(ticket, record)
        return True


def close(ticket):
    """Retain the signed audit and permanently close this attempt's authority."""
    if ticket is None:
        return
    record = _read(ticket)
    record.update(state="closed", closed_at=time.time())
    _write(ticket, record)
