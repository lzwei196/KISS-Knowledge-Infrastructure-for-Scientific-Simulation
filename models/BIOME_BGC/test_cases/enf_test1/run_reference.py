#!/usr/bin/env python3
"""Run Biome-BGC's official enf_test1 example in a clean dir and check expected.json.
Foundation test case for the BIOME_BGC KI: authentic shipped example (Missoula ENF).
Exit 0 PASS, 2 checks failed, 3 bgc binary missing (reported, not skipped)."""
import argparse, json, os, shutil, subprocess, sys, tempfile, hashlib
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent; EXP=json.loads((HERE/"expected.json").read_text())
_DEF="/mnt/disk1/Hydrocraft_server/model/biome-bgc/bgc-src/bgc"
def find_bin(a):
    for c in (a, os.environ.get("BGC_BIN"), shutil.which("bgc"), _DEF):
        if c and Path(c).exists(): return c
    return None
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--bgc-bin"); a=ap.parse_args()
    b=find_bin(a.bgc_bin)
    if not b:
        print("MISSING DEPENDENCY: bgc binary not found (set BGC_BIN). NOT run.",file=sys.stderr); return 3
    run=Path(tempfile.mkdtemp(prefix="bbgc_enf_"))
    for src in (HERE/"inputs").rglob("*"):
        if src.is_file():
            d=run/src.relative_to(HERE/"inputs"); d.parent.mkdir(parents=True,exist_ok=True); shutil.copy(src,d)
    (run/"outputs").mkdir(exist_ok=True); (run/"restart").mkdir(exist_ok=True)
    cp=subprocess.run([b,"enf_test1.ini"],cwd=run,capture_output=True,text=True,timeout=600)
    fails=[]
    if EXP["stdout_contains"] not in cp.stdout: fails.append(f"did not reach {EXP['stdout_contains']!r} (rc={cp.returncode})")
    for o in EXP["outputs_present"]:
        if not (run/"outputs"/o).is_file(): fails.append(f"missing output {o}")
    ann=run/"outputs"/"oth.annout"
    if ann.is_file():
        arr=np.fromfile(ann,dtype=EXP["annual_output"]["dtype"])
        if arr.size!=EXP["annual_output"]["n_values"]: fails.append(f"annout has {arr.size} values, expected {EXP['annual_output']['n_values']}")
        for chk in EXP["numeric_checks"]:
            try:
                v=float(arr[chk["index"]])
                if abs(v-chk["expected"])>chk["tol"]: fails.append(f"{chk['name']}: {v} vs {chk['expected']}±{chk['tol']}")
                else: print(f"  OK {chk['name']}: {v}")
            except Exception as e: fails.append(f"{chk['name']}: {e}")
        got=hashlib.sha256(ann.read_bytes()).hexdigest()
        print(f"  annout sha256 {'MATCHES' if got==EXP['annual_output']['sha256'] else 'differs from'} baseline (informational)")
    else: fails.append("oth.annout missing")
    shutil.rmtree(run,ignore_errors=True)
    if fails:
        print("FAIL:",file=sys.stderr); [print("  -",f,file=sys.stderr) for f in fails]; return 2
    print("PASS: Biome-BGC enf_test1 reproduced the expected results."); return 0
if __name__=="__main__": raise SystemExit(main())
