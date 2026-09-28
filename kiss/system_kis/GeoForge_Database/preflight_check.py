#!/usr/bin/env python3
"""Structural preflight for the GeoForge Database task-workflow KI."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    checks = []

    def check(name: str, ok: bool, subject: Path, fix: str) -> None:
        checks.append({
            "id": name,
            "kind": "file",
            "subject": str(subject),
            "critical": True,
            "status": "pass" if ok else "fail",
            "fix": "" if ok else fix,
        })

    tool = root / "tools" / "search_catalogue.py"
    docs = [root / "docs" / f"s{i}_{name}.md" for i, name in (
        (1, "scope_query"), (2, "search_catalogue"), (3, "report_selection"))]
    check("search-tool", tool.is_file(), tool, "Restore tools/search_catalogue.py")
    for index, document in enumerate(docs, 1):
        check(f"stage-doc-{index}", document.is_file(), document, "Restore the KDT stage document")
    if tool.is_file():
        try:
            compile(tool.read_text(encoding="utf-8"), str(tool), "exec")
            syntax_ok = True
        except (OSError, SyntaxError):
            syntax_ok = False
        check("tool-syntax", syntax_ok, tool, "Repair the Python syntax before publishing the KI")
    report = {"checks": checks, "ki_kind": "task_workflow"}
    print("PREFLIGHT_REPORT=" + json.dumps(report, separators=(",", ":")))
    return 0 if all(row["status"] == "pass" for row in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
