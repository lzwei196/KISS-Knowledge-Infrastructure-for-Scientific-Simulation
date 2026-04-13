# Model Execution — Skill Document

> **Stage ID**: s8_execution
> **Pipeline order**: 8 of 10
> **Depends on**: s2_site_config, s3_setup_modules, s4_climate_prep, s5_airchemistry_prep, s6_management_config, s7_species_params

## Purpose

Run the LDNDC binary with the prepared project configuration. This stage executes the C++ model core which integrates all process modules (microclimate, watercycle, soilchemistry, physiology) over the simulation period. Typical runtime: 1-30 minutes per site depending on period length and output detail.

## Prerequisites

- [ ] All input files generated and validated (S2-S7 complete)
- [ ] LDNDC binary installed and executable
- [ ] project.xml references all input files correctly
- [ ] Sufficient disk space for output (estimate: ~50 MB per site-year at daily resolution)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| ldndc_binary | file | Installation | Path to `ldndc` executable |
| project_xml | file | S1 | Master project configuration |

## Procedure

### Step 1: Pre-flight checks

Before running, verify all input files exist:
```bash
# Check all source files referenced in project.xml
ls {project_dir}/input/site.xml
ls {project_dir}/input/setup.xml
ls {project_dir}/input/climate.txt
ls {project_dir}/input/airchem.txt
ls {project_dir}/input/mana.xml
ls {project_dir}/input/parameters_species.xml
```

### Step 2: Run LDNDC

```bash
python tools/s8_execution/run_ldndc.py
```

Or directly:
```bash
cd {project_dir}
/home/server/LDNDC/bin/ldndc project.xml
```

**Expected behavior**:
- LDNDC prints initialization messages (reading XML files, loading modules)
- Progress indicators during simulation (year boundaries, daily stepping)
- Exit code 0 on success

**Expected runtime**:
- 1-year simulation, daily output: 1-3 minutes
- 10-year simulation, daily output: 5-15 minutes
- 10-year simulation, subdaily output: 15-30 minutes

### Step 3: Verify output

```bash
ls {project_dir}/output/
```

**Expected files** (depends on setup.xml output modules):
- `soilchemistry-daily.txt` -- daily GHG fluxes and leaching
- `watercycle-daily.txt` -- daily water balance
- `physiology-daily.txt` -- daily vegetation variables
- `ecosystem-yearly.txt` -- annual integrated fluxes
- `soilchemistry-layer-daily.txt` -- per-layer daily values (if configured)

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Output directory | `{project_dir}/output/` | Contains .txt output files |
| soilchemistry-daily.txt | `{project_dir}/output/soilchemistry-daily.txt` | Has header + daily data rows |

## Validation Checks

1. **Exit code**: Must be 0. Non-zero indicates error.
2. **Output file existence**: At least the configured output modules produced files
3. **Output file size**: Files are non-empty (>100 bytes)
4. **Row count**: Daily output files have approximately N_days rows (header + 1 per day)
5. **No NaN values**: Spot-check first and last rows for NaN/inf values

## Common Pitfalls

> **PITFALL**: Segfault from invalid soil data
> Zero or negative bulk density, or zero-thickness soil layers, cause segfaults during initialization. The error gives no indication of which parameter is wrong.
> **Do this instead**: Validate site.xml before running (S2 validation checks).
> See diagnostic triplet dt_010.

> **PITFALL**: NaN propagation mid-simulation
> Extreme parameter combinations can cause numerical instability partway through the simulation. Check if output files have NaN values.
> See diagnostic triplet dt_011.

> **PITFALL**: Running from wrong directory
> LDNDC resolves relative paths from the current working directory, not from the project.xml location. Always `cd` to the project directory before running.

> **PITFALL**: Long-running process appears stuck
> LDNDC may produce no stdout for 1-2 minutes during computationally intensive periods. This is normal. Do not kill the process unless it exceeds 2x expected runtime.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 8 of 10 | Tools used: run_ldndc | Related triplets: dt_010, dt_011*
