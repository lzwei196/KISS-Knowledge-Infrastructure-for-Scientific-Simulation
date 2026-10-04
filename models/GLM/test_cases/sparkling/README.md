# GLM — foundation test case: "Sparkling"

Authentic foundation case: GLM's official **Sparkling Lake** example (NTL-LTER,
Wisconsin) from the AED/UWA GLM distribution. `inputs/` are unmodified.

| | |
|---|---|
| Engine | GLM (General Lake Model) 3.3.3, binary `glm` |
| Source | AED/UWA GLM distribution, Sparkling Lake example |
| KI | `GLM` |

## Run
```
python run_reference.py   # finds glm (or $GLM_BIN, --glm-bin); 0=PASS 3=binary missing
# equivalently, in a dir with glm3.nml + bcs/ + output/:  glm --nml glm3.nml
```
PASS = "Model Run Complete", `output/lake.csv` with 731 daily rows, final-day lake
Volume ≈ 5,566,185 m³ (recorded 2026-10-04; deterministic). Missing binary reported, never faked.
