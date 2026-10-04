#!/usr/bin/env python3
"""Run GLM's official Sparkling Lake example in a clean dir and check expected.json.
Foundation case for the GLM KI. Exit 0 PASS, 2 checks failed, 3 glm binary missing."""
import argparse, csv, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent; EXP=json.loads((HERE/"expected.json").read_text())
_DEF="/mnt/disk1/Hydrocraft_server/model/glm/bin/glm"
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--glm-bin"); a=ap.parse_args()
    b=next((c for c in (a.glm_bin, os.environ.get("GLM_BIN"), shutil.which("glm"), _DEF) if c and Path(c).exists()), None)
    if not b: print("MISSING DEPENDENCY: glm binary not found (set GLM_BIN). NOT run.",file=sys.stderr); return 3
    run=Path(tempfile.mkdtemp(prefix="glm_sparkling_"))
    shutil.copy(HERE/"inputs"/"glm3.nml", run/"glm3.nml")
    shutil.copytree(HERE/"inputs"/"bcs", run/"bcs"); (run/"output").mkdir()
    cp=subprocess.run([b,"--nml","glm3.nml"],cwd=run,capture_output=True,text=True,timeout=300)
    fails=[]
    if EXP["stdout_contains"] not in cp.stdout: fails.append(f"no '{EXP['stdout_contains']}' (rc={cp.returncode})")
    lk=run/"output"/"lake.csv"
    if not lk.is_file(): fails.append("output/lake.csv missing")
    else:
        rows=list(csv.reader(open(lk)))
        hdr=[h.strip() for h in rows[0]]; data=rows[1:]
        if len(data)!=EXP["output_rows"]: fails.append(f"{len(data)} rows vs {EXP['output_rows']}")
        for chk in EXP["numeric_checks"]:
            ci=hdr.index(chk["column"]); val=float(data[-1][ci])
            if abs(val-chk["expected"])>chk["tol"]: fails.append(f"{chk['name']}: {val} vs {chk['expected']}±{chk['tol']}")
            else: print(f"  OK {chk['name']}: {val}")
    shutil.rmtree(run,ignore_errors=True)
    if fails: print("FAIL:",file=sys.stderr); [print("  -",f,file=sys.stderr) for f in fails]; return 2
    print("PASS: GLM Sparkling reproduced the expected results."); return 0
if __name__=="__main__": raise SystemExit(main())
