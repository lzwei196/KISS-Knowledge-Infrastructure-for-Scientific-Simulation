#!/usr/bin/env python3
"""Run the official DLBreach Teton Dam test case (via WINE) and check expected.json.
Foundation case for the DLBreach KI. Exit 0 PASS, 2 checks failed, 3 missing dep."""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent; EXP=json.loads((HERE/"expected.json").read_text())
_DEF="/mnt/disk1/Hydrocraft_server/model/dlbreach/bin/DLBreach_Barrier.exe"
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--exe"); a=ap.parse_args()
    exe=next((c for c in (a.exe, os.environ.get("DLBREACH_BIN"), _DEF) if c and Path(c).exists()), None)
    wine=shutil.which("wine")
    if not exe: print("MISSING DEPENDENCY: DLBreach_Barrier.exe not found (set DLBREACH_BIN). NOT run.",file=sys.stderr); return 3
    if not wine: print("MISSING DEPENDENCY: wine not found. NOT run.",file=sys.stderr); return 3
    run=Path(tempfile.mkdtemp(prefix="dlb_teton_"))
    shutil.copy(HERE/"inputs"/"Teton_cards.txt", run/"Teton_cards.txt")
    subprocess.run([wine,exe],cwd=run,input="Teton_cards\n",capture_output=True,text=True,timeout=300)
    out=run/"Teton_cards.out"
    if not out.is_file(): print("FAIL: no Teton_cards.out produced",file=sys.stderr); shutil.rmtree(run,ignore_errors=True); return 2
    import numpy as np
    rows=[]
    for ln in out.read_text(errors="replace").splitlines():
        p=ln.split()
        try: rows.append([float(x) for x in p])
        except ValueError: pass
    w=max(len(r) for r in rows); a2=np.array([r for r in rows if len(r)==w])
    fails=[]
    for chk in EXP["numeric_checks"]:
        col=a2[:,chk["column_index"]]; val=float(col.max() if chk["reduce"]=="max" else col[-1])
        if abs(val-chk["expected"])>chk["tol"]: fails.append(f"{chk['name']}: {val} vs {chk['expected']}±{chk['tol']}")
        else: print(f"  OK {chk['name']}: {val}")
    shutil.rmtree(run,ignore_errors=True)
    if fails: print("FAIL:",file=sys.stderr); [print("  -",f,file=sys.stderr) for f in fails]; return 2
    print("PASS: DLBreach Teton reproduced the expected results."); return 0
if __name__=="__main__": raise SystemExit(main())
