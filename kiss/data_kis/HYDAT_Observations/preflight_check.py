#!/usr/bin/env python3
"""Check the shipped data reader, not availability or quality of external data."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

IMPORT_MODULES = ("argparse", "calendar", "csv", "datetime", "hashlib", "json", "math", "sqlite3")


def main():
    root = Path(__file__).resolve().parent
    checks = []
    def check(name, ok, fix, detail=""):
        checks.append({"id": name, "kind": "runtime", "critical": True,
                       "status": "pass" if ok else "fail", "fix": "" if ok else fix,
                       "detail": detail})
    check("python-version", sys.version_info >= (3, 11), "Configure Python 3.11 or newer.")
    for module in IMPORT_MODULES:
        try:
            importlib.import_module(module)
            check("import-"+module, True, "")
        except ImportError as exc:
            check("import-"+module, False, "Repair the configured Python standard library.", str(exc))
    for relative in ("SKILL.md", "knowledge_infrastructure.yaml", "docs/format_spec.yaml", "tools/read_observations.py"):
        check("file-"+relative, (root/relative).is_file(), "Restore the complete data-KI package.")
    try:
        compile((root/"tools/read_observations.py").read_text(encoding="utf-8"), "read_observations.py", "exec")
        with tempfile.TemporaryDirectory(prefix="geoforge-data-ki-preflight-") as temporary:
            result = subprocess.run([sys.executable, "-B", str(root/"tools/read_observations.py"), "--help"],
                                    cwd=temporary, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            check("reader-help", result.returncode == 0 and "--station" in result.stdout and
                  not list(Path(temporary).iterdir()), "Restore the reader and repair its Python runtime.",
                  result.stderr[-500:])
    except (OSError, SyntaxError, subprocess.SubprocessError) as exc:
        check("reader-help", False, "Restore the reader and repair its Python runtime.", str(exc))
    print("PREFLIGHT_REPORT="+json.dumps({"checks": checks, "ki_kind": "task_workflow",
                                        "role": "data_reader", "model_executed": False}))
    return 0 if all(c["status"] == "pass" for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
