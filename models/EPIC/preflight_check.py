#!/usr/bin/env python3
"""Preflight check for the EPIC 1102 KI."""
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

MODEL_ID = "EPIC"
MODEL_NAME = "EPIC 1102 (v2025-05-25)"
EPIC_OK_RETURN_CODES = (0, 38)
REQUIRED_TEMPLATES = (
    "EPICRUN.DAT",
    "EPICCONT.DAT",
    "EPICFILE.DAT",
    "CROPCOM.DAT",
    "FERT2012.DAT",
    "PARM1102.DAT",
    "umstead.SIT",
    "umstead.SOL",
    "umstead.OPC",
    "NCRDU.DLY",
    "NCCLAYTO.WP1",
    "NCCLAYTO.WND",
)
REQUIRED_TOOL_FILES = (
    "_common.py",
    "run_epic.py",
    "build_control_files.py",
    "convert_forcing_to_epic.py",
    "parse_outputs.py",
)


def triplets_path(ki_dir):
    return os.path.join(ki_dir, "diagnostics", "triplets.yaml")


def recovery_fix(ki_dir, detail):
    return f"{detail}. Check {triplets_path(ki_dir)} for matching recovery guidance."


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


class Preflight:
    def __init__(self, ki_dir):
        self.ki_dir = ki_dir
        self.checks = []
        self.pass_count = 0
        self.fail_count = 0

    def record(self, kind, subject, critical, ok, label, fix=""):
        status = "pass" if ok else "fail"
        check = {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if ok else fix,
        }
        self.checks.append(check)
        if ok:
            self.pass_count += 1
            print(f"  OK    {label}: {subject}")
        else:
            self.fail_count += 1
            marker = "FAIL" if critical else "WARN"
            print(f"  {marker:<5} {label}: {subject}")
            print(f"         Fix: {fix}")
        return ok

    def check_file(self, path, label, kind="data", critical=True, executable=False):
        path = os.path.abspath(path)
        subject = os.path.realpath(path) if os.path.exists(path) else path
        if not os.path.isfile(path):
            return self.record(
                kind,
                subject,
                critical,
                False,
                label,
                recovery_fix(self.ki_dir, f"Restore required file at {path}"),
            )
        if executable and not os.access(path, os.X_OK):
            return self.record(
                kind,
                subject,
                critical,
                False,
                label,
                recovery_fix(self.ki_dir, f"Make executable with: chmod +x {path}"),
            )
        return self.record(kind, subject, critical, True, label)

    def check_dir(self, path, label, critical=True):
        path = os.path.abspath(path)
        subject = os.path.realpath(path) if os.path.exists(path) else path
        ok = os.path.isdir(path) and bool(os.listdir(path))
        if not ok:
            return self.record(
                "data",
                subject,
                critical,
                False,
                label,
                recovery_fix(self.ki_dir, f"Restore non-empty directory at {path}"),
            )
        return self.record("data", f"{subject} ({len(os.listdir(path))} items)", critical, True, label)

    def check_binary_in_path(self, name, label, critical=True):
        found = shutil.which(name)
        if found:
            return self.record("binary", os.path.realpath(found), critical, True, label)
        return self.record(
            "binary",
            name,
            critical,
            False,
            label,
            recovery_fix(self.ki_dir, f"Install {name} and ensure it is on PATH"),
        )

    def check_import(self, module, label, critical=True):
        try:
            importlib.import_module(module)
        except Exception as exc:
            return self.record(
                "import",
                module,
                critical,
                False,
                label,
                recovery_fix(self.ki_dir, f"Make Python import '{module}' available: {exc}"),
            )
        return self.record("import", module, critical, True, label)

    def check_epic_starts(self, binary, wine):
        subject = os.path.realpath(binary)
        try:
            with tempfile.TemporaryDirectory(prefix="epic_preflight_") as work:
                for fn in os.listdir(os.path.join(self.ki_dir, "templates")):
                    src = os.path.join(self.ki_dir, "templates", fn)
                    if os.path.isfile(src):
                        shutil.copy2(src, os.path.join(work, fn))
                exe = os.path.join(work, os.path.basename(binary))
                shutil.copy2(binary, exe)
                proc = subprocess.run(
                    [wine, exe],
                    cwd=work,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=20,
                )
                produced = any(
                    name.endswith((".OUT", ".ACY", ".ANN")) or name == "RUN1102.SUM"
                    for name in os.listdir(work)
                )
                ok = proc.returncode in EPIC_OK_RETURN_CODES and produced
                if ok:
                    return self.record("run", subject, True, True, "EPIC startup smoke")
                stderr_tail = proc.stderr.decode("ascii", errors="replace").splitlines()[-3:]
                detail = f"EPIC smoke returned {proc.returncode}; stderr tail: {' | '.join(stderr_tail)}"
        except subprocess.TimeoutExpired:
            detail = "EPIC smoke timed out after 20 seconds"
        except Exception as exc:
            detail = f"EPIC smoke could not run: {exc}"
        return self.record(
            "run",
            subject,
            True,
            False,
            "EPIC startup smoke",
            recovery_fix(self.ki_dir, detail),
        )


def resolve_epic_binary(ki_dir):
    tools_dir = os.path.join(ki_dir, "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        from _common import resolve_binary

        return resolve_binary()
    except Exception:
        return os.environ.get(
            "EPIC_BINARY",
            os.path.abspath(
                os.path.join(os.path.dirname(ki_dir), "bin", "epic1102-official_release.exe")
            ),
        )


def add_kdt_common_to_path():
    candidates = (
        "KISSPATH_INTERNAL_NOT_SHIPPED/ki_tools_common",
        "KISSPATH_INTERNAL_NOT_SHIPPED/kdt-release/ki_tools_common",
        "KISSPATH_KI_TOOLS_COMMON/ki_tools_common",
    )
    for cand in candidates:
        if os.path.isdir(cand):
            parent = os.path.dirname(cand)
            if parent not in sys.path:
                sys.path.insert(0, parent)
            return


def main():
    ki_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(ki_dir, "templates")
    tools_dir = os.path.join(ki_dir, "tools")
    preflight = Preflight(ki_dir)

    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_NAME}")
    print("=" * 60)

    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    add_kdt_common_to_path()

    binary = resolve_epic_binary(ki_dir)
    wine = shutil.which("wine") or "wine"

    preflight.check_file(binary, "EPIC 1102 binary", kind="binary", executable=True)
    preflight.check_binary_in_path("wine", "Wine runtime")
    preflight.check_dir(templates_dir, "templates/")
    for fn in REQUIRED_TEMPLATES:
        preflight.check_file(os.path.join(templates_dir, fn), f"template {fn}")
    preflight.check_dir(tools_dir, "tools/")
    for fn in REQUIRED_TOOL_FILES:
        preflight.check_file(os.path.join(tools_dir, fn), f"tool {fn}")

    print()
    print("  Required imports:")
    for module, label in (
        ("_common", "EPIC shared tool helper"),
        ("ki_tools_common", "ki_tools_common"),
        ("ki_tools_common.load_forcing", "load_forcing helper"),
        ("numpy", "numpy"),
        ("xarray", "xarray"),
        ("yaml", "PyYAML"),
    ):
        preflight.check_import(module, label)

    print()
    preflight.check_epic_starts(binary, wine)

    print()
    triplets = triplets_path(ki_dir)
    if os.path.isfile(triplets):
        print(f"  INFO  Diagnostic triplets: {triplets}")
    else:
        preflight.record(
            "data",
            triplets,
            False,
            False,
            "diagnostics/triplets.yaml",
            f"Restore diagnostics/triplets.yaml so failures have recovery guidance.",
        )

    print()
    print(f"  Results: {preflight.pass_count} passed, {preflight.fail_count} failed")
    if any(c["status"] == "fail" and c.get("critical") for c in preflight.checks):
        print("  STATUS: PREFLIGHT FAILED")
    else:
        print("  STATUS: PREFLIGHT PASSED")
    emit_report(MODEL_ID, preflight.checks)


if __name__ == "__main__":
    main()
