# Air Chemistry Data Preparation — Skill Document

> **Stage ID**: s5_airchemistry_prep
> **Pipeline order**: 5 of 10
> **Depends on**: s1_project_setup

## Purpose

Prepare atmospheric boundary conditions for LDNDC: ambient CO2 concentration and nitrogen deposition rates (NH4 and NO3, wet + dry). These drive the background N input to soils (affecting N2O emissions and N leaching) and the CO2 fertilization effect on photosynthesis.

## Prerequisites

- [ ] Project directory created (S1 complete)
- [ ] Atmospheric N deposition data available for the region (or use defaults)
- [ ] CO2 concentration known (historical or scenario)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| output_path | file | S1 | Target airchem.txt path |
| co2_ppm | number | Mauna Loa / SSP scenario | Ambient CO2 (default: 400 ppm) |
| nh4_dep_kgNha | number | EMEP / regional data | NH4 deposition rate (default: 5.0 kgN/ha/yr) |
| no3_dep_kgNha | number | EMEP / regional data | NO3 deposition rate (default: 3.0 kgN/ha/yr) |

## Procedure

### Step 1: Determine atmospheric inputs

**CO2 concentration** (approximate values by decade):
- 1980s: 340 ppm
- 1990s: 360 ppm
- 2000s: 380 ppm
- 2010s: 400 ppm
- 2020s: 420 ppm

**N deposition** (typical ranges by region):
- Western Europe: 10-30 kgN/ha/yr
- Eastern China: 15-40 kgN/ha/yr
- North America: 5-15 kgN/ha/yr
- Tropical regions: 2-8 kgN/ha/yr
- Remote/pristine: 1-3 kgN/ha/yr

### Step 2: Generate airchem.txt

```bash
python tools/s5_airchemistry_prep/generate_airchemistry_file.py
```

**Expected result**: `airchem.txt` with tab-separated format:

```
#	co2	nh4_dep	no3_dep
2000-01-01	370.0	5.0	3.0
```

If `airchemistry endless="yes"` is set in project.xml, a single row is repeated for all simulation years.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| airchem.txt | `{project_dir}/input/airchem.txt` | Header + data rows; CO2 in [280-600] ppm |

## Validation Checks

1. **CO2 range**: 280-600 ppm for historical simulations, up to 1200 ppm for future scenarios
2. **N deposition range**: 0-50 kgN/ha/yr (values > 50 are suspicious -- see dt_007)
3. **File format**: Tab-separated with header row

## Common Pitfalls

> **PITFALL**: N deposition in wrong units (g/m2 instead of kgN/ha)
> 1 g/m2/yr = 10 kgN/ha/yr. Providing values in g/m2 inflates N input by 10x, producing excessive N2O emissions. The model gives no warning.
> **Do this instead**: Verify units match kgN/ha/yr. Typical values: 1-30 kgN/ha/yr.
> See diagnostic triplet dt_007.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 5 of 10 | Tools used: generate_airchemistry_file | Related triplets: dt_007*
