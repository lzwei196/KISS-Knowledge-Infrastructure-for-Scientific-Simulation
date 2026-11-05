# VIC-LDNDC Coupling — Skill Document

> **Stage ID**: s10_vic_coupling
> **Pipeline order**: 10 of 10
> **Depends on**: a finished VIC run (its RESULTS)

## Purpose

Use VIC simulation RESULTS in an LDNDC run: the simulated soil moisture on the LDNDC start date sets the LDNDC initial water content, so the first year needs less spin-up.

This stage takes results only. LDNDC climate and soil are never made from VIC forcing files or the VIC soil parameter file: climate comes from the data source through S4 (`convert_forcing_to_ldndc_climate.py`), soil from HWSD through S2 (`hwsd_to_ldndc_soil.py`).

## Prerequisites

- [ ] VIC simulation complete; output files at `outputs/{run_name}/vic_result/`
- [ ] LDNDC site layers known (S2 complete)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| vic_result_dir | directory | VIC run | VIC simulation output (flux files with soil moisture) |
| lat, lon | number | S1 | Target grid cell |

## Procedure

### Step 1: Extract VIC soil moisture for initial conditions

```bash
python tools/s10_vic_coupling/vic_to_ldndc_soilwater.py
```

Uses the VIC output soil moisture columns on the simulation start date, converts mm to volumetric fraction (theta = SM_mm / layer_depth_mm) and maps the VIC 3 layers onto the LDNDC layer profile.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| soil moisture JSON | in-memory | Theta in [0, porosity] per layer |

## Common Pitfalls

> **PITFALL**: VIC soil moisture includes ice in frozen soil
> For a start date in winter, check the value against porosity before using it.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 10 of 10 | Tools used: vic_to_ldndc_soilwater*
