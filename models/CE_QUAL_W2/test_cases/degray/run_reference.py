#!/usr/bin/env python3
"""Run the official CE-QUAL-W2 v5 DeGray example in a clean dir and check expected.json.
Foundation test case for the CE_QUAL_W2 KI. inputs/ are the unmodified distribution
files; prepare_example_linux.py (shipped with CE-QUAL-W2 v5) does the authentic
Linux prep — flatten InputFiles/ and add case-fix symlinks — then w2_v5 runs.
Exit 0 PASS, 2 checks failed, 3 w2_v5 missing (reported, not skipped)."""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent; EXP=json.loads((HERE/"expected.json").read_text())
PREP=HERE/"prepare_example_linux.py"
_DEF="/mnt/disk1/Hydrocraft_server/model/ce_qual_w2/bin/w2_v5"
def find_bin(a):
    for c in (a, os.environ.get("W2_BIN"), shutil.which("w2_v5"), _DEF):
        if c and Path(c).exists(): return c
    return None
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--w2-bin"); a=ap.parse_args()
    b=find_bin(a.w2_bin)
    if not b:
        print("MISSING DEPENDENCY: w2_v5 binary not found (set W2_BIN). NOT run.",file=sys.stderr); return 3
    run=Path(tempfile.mkdtemp(prefix="w2_degray_"))
    shutil.copytree(HERE/"inputs", run, dirs_exist_ok=True)
    subprocess.run([sys.executable, str(PREP), str(run)], capture_output=True, text=True, timeout=120)
    cp=subprocess.run([b],cwd=run,capture_output=True,text=True,timeout=600)
    fails=[]
    if EXP["stdout_contains"] not in cp.stdout:
        fails.append(f"no '{EXP['stdout_contains']}' (rc={cp.returncode}); tail: {cp.stdout[-200:]}")
    for o in EXP["outputs_present"]:
        if not (run/o).is_file(): fails.append(f"missing output {o}")
    shutil.rmtree(run,ignore_errors=True)
    if fails:
        print("FAIL:",file=sys.stderr); [print("  -",f,file=sys.stderr) for f in fails]; return 2
    print("PASS: CE-QUAL-W2 DeGray reached Normal termination with expected outputs."); return 0
if __name__=="__main__": raise SystemExit(main())
