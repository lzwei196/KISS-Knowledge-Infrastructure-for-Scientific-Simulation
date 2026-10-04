# HYPE — foundation test case: "demo"

Authentic foundation case: the official **demo** basin shipped with the SMHI HYPE
distribution (3 subbasins, 2005). `inputs/` are the unmodified demo files.

| | |
|---|---|
| Engine | HYPE 5.35.0 (SMHI), binary `hype` |
| Source | SMHI HYPE distribution `demo/` |
| KI | `HYPE` |

## Run
```
python run_reference.py    # finds hype (or $HYPE_BIN, --hype-bin); 0=PASS 3=binary missing
# equivalently, in a dir with info.txt + modelfiles/ + forcingdir/ + resultdir/:  hype ./
```
PASS = "halt: successfully", the five `resultdir/time*.txt` files, 365 daily rows,
peak evaporation ≈ 2.94 mm/day (recorded 2026-10-04; deterministic). Missing binary
reported, never faked.
