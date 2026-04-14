#!/usr/bin/env python3
"""
DayCent preflight check — verifies the binary, helper, example data, and
required Python imports exist BEFORE the agent attempts to run the model.

Run: python preflight_check.py
Exit 0 = ready to proceed; exit 1 = at least one failure (with fix instructions).

Why: Without preflight, an agent that hits a missing binary may silently fall
back to a Python reimplementation of DayCent equations, producing scientifically
invalid results. The preflight surfaces problems while they are easy to fix.
"""

import os
import sys
import subprocess

PASS = 0
FAIL = 0
MODEL_NAME = "DayCent (DDcentEVI rev 491)"

BIN_DIR = ("/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/"
           "_work_v2/DayCent/source/repo/Linux_Version_491")
DDCENT = os.path.join(BIN_DIR, "DDcentEVI_rev491")
DDLIST = os.path.join(BIN_DIR, "DDlist100_rev491")

EXAMPLE_DIR = ("/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/"
               "_work_v2/DayCent/source/repo/WoosterExampleLinux")

KI_DIR = os.path.dirname(os.path.abspath(__file__))


def check_file(path, label, executable=False):
    global PASS, FAIL
    if os.path.isfile(path):
        if executable and not os.access(path, os.X_OK):
            print(f"  WARN  {label}: exists but not executable: {path}")
            print(f"         Fix:  chmod +x {path}")
            FAIL += 1
        else:
            sz = os.path.getsize(path)
            print(f"  OK    {label}: {path}  ({sz} bytes)")
            PASS += 1
    else:
        print(f"  FAIL  {label}: NOT FOUND at {path}")
        FAIL += 1


def check_dir(path, label):
    global PASS, FAIL
    if os.path.isdir(path):
        n = len(os.listdir(path))
        print(f"  OK    {label}: {path}  ({n} items)")
        PASS += 1
    else:
        print(f"  FAIL  {label}: directory NOT FOUND at {path}")
        FAIL += 1


def check_import(module, fix_hint):
    global PASS, FAIL
    try:
        __import__(module)
        print(f"  OK    import {module}")
        PASS += 1
    except Exception as e:
        print(f"  FAIL  import {module}: {e}")
        print(f"         Fix:  {fix_hint}")
        FAIL += 1


def check_binary_runs():
    global PASS, FAIL
    if not os.path.isfile(DDCENT):
        return
    try:
        # Banner contains a stray non-UTF8 byte — capture as bytes and
        # decode tolerantly.
        proc = subprocess.run([DDCENT], capture_output=True, timeout=10)
        raw = (proc.stdout or b"") + (proc.stderr or b"")
        out = raw.decode("utf-8", errors="replace")
        if "DAILYDAYCENT" in out and "revision" in out:
            print("  OK    DDcentEVI_rev491 banner: confirmed")
            PASS += 1
        else:
            print(f"  WARN  DDcentEVI_rev491 ran but banner not as expected")
            print(f"         output: {out[:200]}")
            FAIL += 1
    except Exception as e:
        print(f"  FAIL  could not invoke DDcentEVI_rev491: {e}")
        FAIL += 1


def main():
    print(f"=== preflight: {MODEL_NAME} ===")

    print("\n[1] Binary executables")
    check_file(DDCENT, "DDcentEVI_rev491", executable=True)
    check_file(DDLIST, "DDlist100_rev491", executable=True)

    print("\n[2] Bundled Wooster example")
    check_dir(EXAMPLE_DIR, "WoosterExampleLinux")
    check_file(os.path.join(EXAMPLE_DIR, "wooster_eq.sch"), "wooster_eq.sch")
    check_file(os.path.join(EXAMPLE_DIR, "wooster_site.100"), "wooster_site.100")
    check_file(os.path.join(EXAMPLE_DIR, "soils.in"), "soils.in")
    check_file(os.path.join(EXAMPLE_DIR, "sitepar.in"), "sitepar.in")
    check_file(os.path.join(EXAMPLE_DIR, "wooster_prism.wth"), "wooster_prism.wth")
    check_file(os.path.join(EXAMPLE_DIR, "no_outfiles.in"), "no_outfiles.in")
    check_file(os.path.join(EXAMPLE_DIR, "few_outfiles.in"), "few_outfiles.in")

    print("\n[3] KI files")
    check_file(os.path.join(KI_DIR, "SKILL.md"), "SKILL.md")
    check_file(os.path.join(KI_DIR, "knowledge_infrastructure.yaml"), "knowledge_infrastructure.yaml")
    check_file(os.path.join(KI_DIR, "diagnostics/triplets.yaml"), "diagnostics/triplets.yaml")
    check_file(os.path.join(KI_DIR, "tools/convert_forcing_to_daycent.py"), "convert_forcing_to_daycent.py")
    check_file(os.path.join(KI_DIR, "tools/convert_soil_to_daycent.py"), "convert_soil_to_daycent.py")
    check_file(os.path.join(KI_DIR, "tools/run_daycent.py"), "run_daycent.py")
    check_file(os.path.join(KI_DIR, "tools/parse_daycent_output.py"), "parse_daycent_output.py")

    print("\n[4] Python imports (optional but used by tools)")
    sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
    check_import("numpy", "pip install numpy")
    check_import("ki_tools_common.load_forcing",
                 "pip install -e /home/server/knowledge-dissection-toolkit/auto_dissect/ki_tools_common")
    check_import("ki_tools_common.soil_utils",
                 "pip install -e /home/server/knowledge-dissection-toolkit/auto_dissect/ki_tools_common")

    print("\n[5] Binary smoke test")
    check_binary_runs()

    total = PASS + FAIL
    print(f"\n=== summary: {PASS}/{total} passed, {FAIL} failed ===")
    if FAIL:
        print("Some preflight checks failed.")
        print("See diagnostics/triplets.yaml for known failure patterns.")
        return 1
    print("All preflight checks passed. Safe to proceed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
