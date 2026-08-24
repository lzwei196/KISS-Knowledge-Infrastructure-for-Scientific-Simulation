"""Release-gate audit for KI software visibility inside provider chats.

The catalogue, installer, preflight and agent sandbox are separate layers.  A
green status badge is trustworthy only when all four agree about the same
paths.  This module checks that contract for every bundled KI and performs
deeper checks for every workspace already installed on the current machine.

It deliberately does not call a paid model API.  ``--run-preflight`` executes
each verified KI's real local preflight/reference smoke test; the remaining
checks prove that its successful paths are then visible through the exact
policy and CLI-directory bridge used by Claude, Codex and Kimi.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import install, providers
from .catalog import Catalog
from .manifest import Manifest
from .paths import CONFIG_NAME, KissConfig
from .policy import Policy


_ITEM_SUFFIX = re.compile(r"\s+\(\d+\s+items?\)\s*$", re.IGNORECASE)
# The negative lookbehind rejects the slash inside a relative path such as
# ``diagnostics/triplets.yaml`` while retaining a path at line start or after
# ``at `` / ``: ``.
_ABSOLUTE = re.compile(r"(?<![A-Za-z0-9_.-])(?:[A-Za-z]:[\\/]|/)[^\r\n]+")


def preflight_paths(status: dict) -> list[Path]:
    """Extract concrete paths asserted by successful preflight lines."""
    found: list[Path] = []
    seen: set[str] = set()
    for step in status.get("steps") or []:
        if not isinstance(step, dict) or step.get("name") != "preflight":
            continue
        for line in str(step.get("detail") or "").splitlines():
            stripped = line.strip()
            if not (stripped.startswith("OK") or stripped.startswith("[OK]")):
                continue
            match = _ABSOLUTE.search(stripped)
            if not match:
                continue
            value = _ITEM_SUFFIX.sub("", match.group(0)).strip().rstrip(".,;")
            key = str(Path(value))
            if key not in seen:
                seen.add(key)
                found.append(Path(value))
    return found


def _manifest(ki, manifests: Path) -> Manifest:
    if ki.manifest:
        return Manifest.load(ki.manifest)
    shipped = manifests / f"{ki.name}.yaml"
    return Manifest.load(shipped) if shipped.is_file() else Manifest.stub_for(ki)


def _covered(path: Path, roots: list[str]) -> bool:
    try:
        target = path.resolve(strict=False)
    except OSError:
        target = path.absolute()
    for raw in roots:
        root = Path(raw)
        try:
            root = root.resolve(strict=False)
        except OSError:
            root = root.absolute()
        if target == root or root in target.parents:
            return True
    return False


def audit(models: Path, workroot: Path, manifests: Path,
          *, run_preflight: bool = False) -> dict:
    """Audit all catalogue contracts and installed workspaces."""
    catalogue = Catalog(models)
    workroot = Path(workroot).expanduser().resolve()
    manifests = Path(manifests).resolve()
    report: dict = {
        "catalogue_count": len(catalogue),
        "contract_checked": 0,
        "installed_count": 0,
        "verified_count": 0,
        "failed_installations": [],
        "verified": [],
        "errors": [],
        "warnings": [],
        "ran_preflight": bool(run_preflight),
    }

    for ki in catalogue:
        try:
            man = _manifest(ki, manifests)
            static_cfg = KissConfig.default(workroot / ki.name.lower())
            static_policy = Policy.derive(ki, man, static_cfg)
            if not static_policy.allows("read", ki.root):
                raise RuntimeError("KI root is not readable by its derived policy")
            if not static_policy.allows("exec", ki.root):
                raise RuntimeError("KI tools are not executable by their derived policy")
            if man.depends_on:
                binaries = static_cfg.roles["binaries"]
                if not (static_policy.allows("read", binaries) and
                        static_policy.allows("exec", binaries)):
                    raise RuntimeError(
                        "declared coupled models are not visible under the binaries role")
            report["contract_checked"] += 1
        except Exception as error:
            report["errors"].append({
                "model": ki.name, "stage": "contract", "detail":
                f"{type(error).__name__}: {error}",
            })
            continue

        workspace = workroot / ki.name.lower()
        status_path = workspace / "status.json"
        if not status_path.is_file():
            continue
        report["installed_count"] += 1
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            report["errors"].append({
                "model": ki.name, "stage": "status", "detail": str(error),
            })
            continue
        if not status.get("ok"):
            report["failed_installations"].append(ki.name)
            continue
        report["verified_count"] += 1

        item = {"model": ki.name, "paths": [], "preflight": "saved"}
        report["verified"].append(item)
        try:
            cfg = KissConfig.load(workspace)
            live_root = workspace / "ki"
            live = type(ki)(name=ki.name,
                            root=live_root if live_root.is_dir() else ki.root)
            pol = Policy.derive(live, man, cfg)
            pol.add_verified_install(workspace, ki.name)
            cli_roots = providers.policy_directories(pol)
            paths = preflight_paths(status)
            for checked in paths:
                exists = checked.exists()
                policy_visible = (pol.allows("read", checked) or
                                  pol.allows("exec", checked))
                cli_visible = _covered(checked, cli_roots)
                row = {"path": str(checked), "exists": exists,
                       "policy_visible": policy_visible,
                       "cli_visible": cli_visible}
                item["paths"].append(row)
                if not (exists and policy_visible and cli_visible):
                    report["errors"].append({
                        "model": ki.name, "stage": "verified-path", **row,
                    })

            if run_preflight:
                check = install.run_preflight(live, cfg.python, cfg)
                item["preflight"] = "passed" if check.ok else "failed"
                if not check.ok:
                    report["errors"].append({
                        "model": ki.name, "stage": "live-preflight",
                        "detail": check.detail[:4000],
                    })
        except Exception as error:
            report["errors"].append({
                "model": ki.name, "stage": "installed-visibility",
                "detail": f"{type(error).__name__}: {error}",
            })

    report["ok"] = not report["errors"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit all KIs and installed provider-visible software paths")
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--workroot", type=Path, default=Path.home() / "kiss")
    parser.add_argument("--manifests", type=Path, required=True)
    parser.add_argument("--run-preflight", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = audit(args.models, args.workroot, args.manifests,
                   run_preflight=args.run_preflight)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        state = "PASS" if result["ok"] else "FAIL"
        print(f"{state}: {result['contract_checked']}/{result['catalogue_count']} KI "
              f"contracts; {result['verified_count']} verified installations; "
              f"{len(result['errors'])} visibility errors")
        if result["failed_installations"]:
            print("Existing incomplete installations (not contract failures): " +
                  ", ".join(result["failed_installations"]))
        for error in result["errors"]:
            print(f"  {error['model']} [{error['stage']}]: "
                  f"{error.get('path') or error.get('detail')}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
