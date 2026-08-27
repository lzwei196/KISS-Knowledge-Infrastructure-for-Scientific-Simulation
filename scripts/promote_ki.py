#!/usr/bin/env python3
"""Promote KI changes from the working tree on the server into this repository.

The repository is canonical for *published* Knowledge Infrastructure. The
server's `models/<id>/knowledge_infrastructure/` directories are working trees:
the self-improve loop and the dissection toolkit write into them, agents edit
tools during runs, and they accumulate run outputs, calibration scratch and
editor backups. Promotion is therefore a reviewed step, not a mirror.

Two rules follow from that, and both exist because breaking them cost us.

1.  **Copy by allowlist, never by directory.** A canonical KI directory is a
    workspace as well as a package. APEX's is 263 MB against the 4.3 MB
    published; excluding only backups and caches still leaves 64 MB of runs/,
    examples/ and a `--help/` directory that a stray `apex --help` created.

2.  **Never regress a file the repository already improved.** The server is
    usually ahead, but not always: VIC and WRF-Hydro's preflight checks were
    rewritten here to verify the software installation rather than project
    data, and a blind sync reimported the older versions and undid that. This
    script now refuses to overwrite a file whose committed version is newer
    than the server's, and lists those refusals for review.

Run it with no arguments to see what would change. Nothing is written without
--apply.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "kiss"))

from kiss_cli import paths as kpaths          # noqa: E402
from kiss_cli.catalog import Catalog          # noqa: E402
from kiss_cli.port import substitute          # noqa: E402

DB = "/mnt/disk1/Hydrocraft_server/hydrocraft.db"

#: What a published KI consists of. Everything else on the server is workspace.
TOP = {"SKILL.md", "SKILL_en.md", "SKILL_zh.md", "dag.yaml", "preflight_check.py",
       "knowledge_infrastructure.yaml", "calibration.yaml", "README.md",
       "CAPABILITY_INVENTORY.md", "DISSECTION_PLAN.md"}
DIRS = {"diagnostics", "docs", "tools", "workflow"}
#: docs/papers.json is generated from these and ships in their place.
DOCS_SKIP = {"gathered_papers.json", "paywalled_targets.json", "papers_index.md"}
TEXT = {".py", ".md", ".yaml", ".yml", ".sh", ".txt", ".cfg", ".ini", ".json", ".toml"}


def shippable(rel: Path) -> bool:
    parts = rel.parts
    if any(p.startswith(".") for p in parts):              # .dag_gen, .kdt_runs
        return False
    if "__pycache__" in parts or rel.suffix == ".pyc":
        return False
    if ".bak" in rel.name or rel.name.endswith("~") or rel.suffix == ".orig":
        return False
    if len(parts) == 1:
        return rel.name in TOP or rel.name.startswith("run_and_score")
    if parts[0] not in DIRS:
        return False
    return not (parts[0] == "docs" and rel.name in DOCS_SKIP)


def repo_mtime(path: Path) -> float:
    """When this file last changed in git — not when it was checked out."""
    out = subprocess.run(
        ["git", "-C", str(REPO), "log", "-1", "--format=%ct", "--", str(path.relative_to(REPO))],
        capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


def canonical_roots() -> dict[str, Path]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = {r[0]: r[1] for r in con.execute("select id, ki_path from models")}
    nrm = lambda s: "".join(c for c in str(s).lower() if c.isalnum())
    return {nrm(k): Path(v) for k, v in rows.items() if v}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write the changes")
    ap.add_argument("--model", help="promote a single package")
    ap.add_argument("--force", action="store_true",
                    help="overwrite even where the repository copy is newer")
    args = ap.parse_args()

    roots = canonical_roots()
    nrm = lambda s: "".join(c for c in str(s).lower() if c.isalnum())
    cat = Catalog(REPO / "models")
    kis = [cat.get(args.model)] if args.model else list(cat)

    updated = added = unchanged = 0
    per: dict[str, int] = {}
    refused: list[tuple[str, str]] = []
    leaks: list[tuple[str, str, str]] = []

    for ki in kis:
        src = roots.get(nrm(ki.name)) or roots.get(nrm((ki.meta or {}).get("model_id") or ""))
        if not src or not src.is_dir():
            continue
        for c in sorted(src.rglob("*")):
            if not c.is_file():
                continue
            rel = c.relative_to(src)
            if not shippable(rel):
                continue
            dest = ki.root / rel
            raw = c.read_bytes()
            if rel.suffix.lower() in TEXT:
                try:
                    text, _ = substitute(raw.decode("utf-8", "replace"))
                    for hit, _role in kpaths.scan_text(text):
                        leaks.append((ki.name, str(rel), hit))
                    out = text.encode("utf-8")
                except Exception:
                    out = raw
            else:
                out = raw

            if dest.exists():
                if hashlib.md5(dest.read_bytes()).hexdigest() == hashlib.md5(out).hexdigest():
                    unchanged += 1
                    continue
                # The published copy may be the newer one. Refuse rather than
                # discover it later through a failing test.
                if not args.force and repo_mtime(dest) > c.stat().st_mtime:
                    refused.append((ki.name, str(rel)))
                    continue
                updated += 1
            else:
                added += 1
            per[ki.name] = per.get(ki.name, 0) + 1
            if args.apply:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(out)

    print("APPLIED" if args.apply else "DRY RUN — nothing written; pass --apply")
    print(f"  unchanged        : {unchanged}")
    print(f"  would update     : {updated}")
    print(f"  would add        : {added}")
    print(f"  packages touched : {len(per)}")
    if refused:
        print(f"\n  REFUSED — the published copy is newer ({len(refused)}):")
        for name, rel in refused:
            print(f"     {name}/{rel}")
        print("  Promote these to the server instead, or re-run with --force.")
    if leaks:
        print(f"\n  LEAKS — these would name the authoring machine ({len(leaks)}):")
        for l in leaks[:10]:
            print(f"     {l[0]}/{l[1]}: {l[2]}")
        return 1
    print("\n  After --apply, always run: pytest kiss/tests -q  and  kiss doctor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
