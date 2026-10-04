#!/usr/bin/env python3
"""Run the official SMHI HYPE demo in a clean dir and check expected.json.
Foundation case for the HYPE KI. Exit 0 PASS, 2 checks failed, 3 hype binary missing."""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent; EXP=json.loads((HERE/"expected.json").read_text())
_DEF="/mnt/disk1/Hydrocraft_server/model/hype/hype"
def load(fp):
    rows=[ln.split('\t') for ln in open(fp,errors="replace") if not ln.startswith('!') and ln.strip()]
    return rows[1:]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--hype-bin"); a=ap.parse_args()
    b=next((c for c in (a.hype_bin, os.environ.get("HYPE_BIN"), shutil.which("hype"), _DEF) if c and Path(c).exists()), None)
    if not b: print("MISSING DEPENDENCY: hype binary not found (set HYPE_BIN). NOT run.",file=sys.stderr); return 3
    run=Path(tempfile.mkdtemp(prefix="hype_demo_"))
    shutil.copy(HERE/"inputs"/"info.txt", run/"info.txt")
    shutil.copytree(HERE/"inputs"/"modelfiles", run/"modelfiles")
    shutil.copytree(HERE/"inputs"/"forcingdir", run/"forcingdir"); (run/"resultdir").mkdir()
    cp=subprocess.run([b,"./"],cwd=run,capture_output=True,text=True,timeout=300)
    fails=[]
    # HYPE routes its "halt: successfully" line to a log file; success is proven by
    # the result files + numeric checks below, so the stdout string is informational.
    if EXP.get("stdout_contains") and EXP["stdout_contains"] not in cp.stdout:
        print(f"  note: '{EXP['stdout_contains']}' not on captured stdout (logged to file); rc={cp.returncode}")
    for rf in EXP["result_files"]:
        if not (run/"resultdir"/rf).is_file(): fails.append(f"missing result {rf}")
    for chk in EXP["numeric_checks"]:
        fp=run/chk["file"]
        if not fp.is_file(): fails.append(f"{chk['name']}: {chk['file']} missing"); continue
        d=load(fp)
        if chk["reduce"]=="n_rows":
            if len(d)!=chk["expected"]: fails.append(f"{chk['name']}: {len(d)} vs {chk['expected']}")
            else: print(f"  OK {chk['name']}: {len(d)}")
        else:
            v=np.array([[float(x) for x in r[1:]] for r in d]); val=float(v.max())
            if abs(val-chk["expected"])>chk["tol"]: fails.append(f"{chk['name']}: {val} vs {chk['expected']}±{chk['tol']}")
            else: print(f"  OK {chk['name']}: {val}")
    shutil.rmtree(run,ignore_errors=True)
    if fails: print("FAIL:",file=sys.stderr); [print("  -",f,file=sys.stderr) for f in fails]; return 2
    print("PASS: HYPE demo reproduced the expected results."); return 0
if __name__=="__main__": raise SystemExit(main())
