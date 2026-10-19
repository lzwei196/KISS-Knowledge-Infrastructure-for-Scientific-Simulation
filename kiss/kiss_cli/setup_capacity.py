"""Read-only disk headroom checks before setup and KI-maintenance copies.

These are estimates, not reservations or write-permission/readiness proofs.
Existing transactional integrity checks remain responsible for adoption.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

from . import firstrun, ki_guard, ki_investigation, ki_tree, ki_verification

RESERVE_BYTES = 64 * 1024 * 1024
_BLOCK = 4096


class CapacityError(RuntimeError):
    def __init__(self, volumes):
        self.volumes = volumes
        parts = []
        for item in volumes:
            if item.get("error"):
                parts.append(f"Cannot check free space at {item['path']}: {item['error']}")
            else:
                mib = 1024 * 1024
                extra = max(0, item["required_bytes"] - item["free_bytes"])
                parts.append(f"{item['path']}: {item['free_bytes'] / mib:.1f} MiB available; "
                    f"at least {item['required_bytes'] / mib:.1f} MiB needed "
                    f"(free another {(extra + mib - 1) // mib} MiB)")
        super().__init__("Setup paused for disk space. " + "; ".join(parts) +
            ". Free space on the listed volume(s), then retry setup. "
            "This check does not reserve space.")

    def response(self):
        return {"error": str(self), "code": "setup_storage_capacity",
                "state": "waiting_for_user", "needs_user": True,
                "capacity": self.volumes}


def _ancestor(path):
    """Find the actual destination volume without making the destination."""
    path = Path(path).expanduser().absolute()
    while not path.exists():
        if path.parent == path:
            raise OSError("No existing destination ancestor")
        path = path.parent
    if not path.is_dir():
        path = path.parent
    return path.resolve(strict=True)


def _volume(path):
    parent = _ancestor(path)
    # st_dev identifies mounted filesystems, including Windows volume serials;
    # drive-letter spelling alone would miss mount points and aliases.
    return parent.stat().st_dev, str(parent), shutil.disk_usage(parent).free


def _temporary_root():
    # gettempdir() may create a probe file on its first call. This boundary must
    # also work on an already full disk, so inspect configured locations only.
    if tempfile.tempdir is not None:
        return Path(os.fsdecode(tempfile.tempdir))
    candidates = [os.environ[key] for key in ("TMPDIR", "TEMP", "TMP") if os.environ.get(key)]
    candidates.extend(([str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Temp"),
                        "C:/TEMP", "C:/TMP"] if os.name == "nt" else ["/tmp", "/var/tmp", "/usr/tmp"]))
    candidates.append(os.getcwd())
    return next(Path(value) for value in candidates if Path(value).is_dir())


def _allocation(root):
    """Bounded physical-tree estimate; contained aliases are not duplicated."""
    if root is None or not Path(root).exists():
        return 0
    inventory = ki_tree.scan(Path(root))
    return _BLOCK + sum(max(_BLOCK, ((entry.size + _BLOCK - 1) // _BLOCK) * _BLOCK)
                        for entry in inventory.entries)


def _require(copies):
    volumes, unavailable = {}, []
    for path, size, purpose in copies:
        try:
            ident, label, free = _volume(path)
        except OSError as error:
            unavailable.append({"path": str(path), "error": str(error), "purposes": [purpose]})
            continue
        row = volumes.setdefault(ident, {"path": label, "free_bytes": free,
            "copy_bytes": 0, "required_bytes": RESERVE_BYTES, "purposes": []})
        row["free_bytes"] = min(row["free_bytes"], free)
        row["copy_bytes"] += size
        row["required_bytes"] += size
        row["purposes"].append(purpose)
    blocked = unavailable + [row for row in volumes.values()
                             if row["free_bytes"] < row["required_bytes"]]
    if blocked:
        raise CapacityError(blocked)
    return list(volumes.values())


def require_setup(root, *, workroot, source_root=None):
    """Reject known low space before a setup lease, log or provider is started."""
    size = _allocation(source_root)
    return _require([(root, size, "setup KI copy"), (workroot, 0, "setup job records"),
        (ki_guard._home(), size, "KI baseline backup"),
        (ki_verification._store(), 0, "verification records"),
        (firstrun.data_dir(), 0, "profile records"),
        (_temporary_root(), size, "temporary KI checks")])


def require_repair(root, *, workroot, source_root, helper_root):
    """Recheck the remaining conservative copy budget at repair checkpoints."""
    size = _allocation(Path(root) / "ki")
    # Review context contains selected active/upstream KI and shared helpers,
    # never an entire workspace, runtime or model installation. Its writer is
    # bounded separately; estimate actual inputs rather than reserving its cap.
    context = min(ki_investigation.MAX_CONTEXT_BYTES,
                  size + _allocation(source_root) + _allocation(helper_root) + 48 * 1024)
    return _require([(root, size, "adoption replacement"), (workroot, 0, "setup job records"),
        (ki_investigation._home(), 2 * size + 2 * context, "retained source, draft and review evidence"),
        (ki_guard._home(), size, "adopted KI backup"),
        (ki_verification._store(), 0, "verification records"),
        (firstrun.data_dir(), 0, "profile records"),
        (_temporary_root(), size, "temporary KDT snapshot")])
