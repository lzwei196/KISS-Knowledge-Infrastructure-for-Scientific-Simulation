# Forcing Data Preparation -- Skill Document

> **Stage ID**: s2_forcing_prep
> **Pipeline order**: 2 of 7
> **Depends on**: s1_domain_setup

## Purpose

Build SUMMA's forcing NetCDF files straight from a forcing source, with the
variable names, units and time stamps SUMMA needs. SUMMA requires 7 forcing
variables, all at the same sub-daily step. A wrong unit gives no error, only
wrong physics.

**One tool does this: `tools/s2_forcing_prep/build_summa_forcing_from_reanalysis.py`.**
It reads the source through the shared loader `ki_tools_common.load_forcing` at
every HRU location of `attributes.nc`. SUMMA forcing is never made out of another
model's forcing files.

## Prerequisites

- [ ] Local attributes NetCDF exists from Stage 1 (`attributes.nc`)
- [ ] The forcing source is named: `cmfd`, `nasa_power` or `mswx`
- [ ] The elevation the source values stand for is known (see Step 1), or it is
      decided to build without lapse correction (`--no_lapse`)

## Inputs

| Input | Description |
|-------|-------------|
| `--attributes_nc` | SUMMA local attributes NetCDF from Stage 1. Its hruId order is the order of the forcing files. |
| `--source` | `cmfd`, `nasa_power` or `mswx`. **No default: name it.** |
| `--start_year --end_year` | whole years |
| `--forcing_dir` | root folder of the cmfd / mswx store (default: the loader's own) |
| `--reference_elev_nc` / `--reference_elev_m` / `--no_lapse` | exactly one: the elevation the source stands for (a field, or one number), or no lapse correction |
| `--lapse_rate` | K/m, default -0.0065 |
| `--output_dir` | where `forcing_YYYY.nc` and `forcingFileList.txt` go |

## Sources

| Source | Step | Period, area | How it is read |
|--------|------|--------------|----------------|
| `cmfd` | 3 h | 1951-2024, China (15-55 N, 70-140 E) | all HRU points in one pass per file; about 3-5 min per year |
| `nasa_power` | 1 h | 2001 on, global | one request per distinct HRU location and year (network) |
| `mswx` | 3 h | 1979 on, global | one read per distinct HRU location; about 20 min per location and year, so slow for many HRUs |

## What the tool converts

From the loader's standard series to SUMMA:

| SUMMA variable | From | Conversion | If wrong (silent) |
|----------------|------|------------|-------------------|
| `pptrate` kg m-2 s-1 | precipitation in the step (mm), or the store's rate | mm / step seconds | Runoff 3-8x wrong |
| `airtemp` K | deg C | + 273.15 | Energy balance fails |
| `SWRadAtm`, `LWRadAtm` W m-2 | W/m2 | none | -- |
| `windspd` m s-1 | m/s | none | -- |
| `airpres` Pa | Pa | none (never kPa) | ET 100x wrong, NaN |
| `spechum` kg/kg | kg/kg | none | -- |

Time stamps are written period-ending and `data_step` is the source's real step
(10800 s for cmfd and mswx, 3600 s for nasa_power). A missing value in the source
stops the build; nothing is filled in.

## Procedure

### Step 1: Decide the reference elevation

The source values stand for the elevation of the source's grid cell, not of the
HRU. For `cmfd` pass the store's own elevation field:

```
--reference_elev_nc KISSPATH_DATA/elev/elev_CMFD_V0200_B-00_fx_010deg.nc
```

For a source with no elevation field at hand, pass the cell elevation as one
number with `--reference_elev_m` (NASA POWER reports the elevation of its cell
for a point), or state `--no_lapse`. One of the three must be given.

### Step 2: Build the forcing

```bash
python tools/s2_forcing_prep/build_summa_forcing_from_reanalysis.py \
  --attributes_nc outputs/<run>/summa_settings/attributes.nc \
  --source cmfd \
  --start_year <start> --end_year <end> \
  --reference_elev_nc KISSPATH_DATA/elev/elev_CMFD_V0200_B-00_fx_010deg.nc \
  --output_dir outputs/<run>/summa_forcing/
```

Outside China:

```bash
python tools/s2_forcing_prep/build_summa_forcing_from_reanalysis.py \
  --attributes_nc outputs/<run>/summa_settings/attributes.nc \
  --source nasa_power \
  --start_year <start> --end_year <end> \
  --reference_elev_m <elevation of the NASA POWER cell> \
  --output_dir outputs/<run>/summa_forcing/
```

**Expected result**: One NetCDF file per year in `summa_forcing/`, plus `forcingFileList.txt`.
A finished year is skipped on a second call; `--force` rebuilds.

**If this fails**: See diagnostic triplet dt_005 (hruId mismatch).

### Step 3: Validate forcing units

```bash
python -c "
from netCDF4 import Dataset
ds = Dataset('outputs/<run>/summa_forcing/forcing_<year>.nc')
import numpy as np
for var in ['pptrate', 'airtemp', 'SWRadAtm', 'LWRadAtm', 'windspd', 'airpres', 'spechum']:
    vals = ds.variables[var][:]
    print(f'{var}: mean={np.nanmean(vals):.6e}, min={np.nanmin(vals):.4e}, max={np.nanmax(vals):.4e}, units={ds.variables[var].units}')
ds.close()
"
```

**Expected ranges** (temperate climate):
| Variable | Expected Mean | Red Flag |
|----------|--------------|----------|
| pptrate | 1e-5 to 1e-4 kg/m2/s | > 1e-3 or < 1e-7 |
| airtemp | 275-295 K | < 200 or > 320 |
| SWRadAtm | 100-250 W/m2 | negative values |
| LWRadAtm | 250-400 W/m2 | < 100 or > 500 |
| windspd | 1-5 m/s | negative values |
| airpres | 80000-105000 Pa | < 1000 (still in kPa!) |
| spechum | 0.002-0.015 kg/kg | > 1 (still in g/kg!) |

**If values are outside expected ranges**: See diagnostic triplets dt_003, dt_004, dt_012.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Forcing NetCDFs | `outputs/<run>/summa_forcing/forcing_YYYY.nc` | One per year, all 7 vars present |
| Forcing file list | `outputs/<run>/summa_forcing/forcingFileList.txt` | Lists all forcing files; `create_file_manager.py` puts it in settingsPath (dt_032) |

## Validation Checks

1. **All 7 variables present**: `ncdump -h forcing.nc | grep -c 'pptrate\|airtemp\|SWRadAtm\|LWRadAtm\|windspd\|airpres\|spechum'` should return 7.
2. **Time dimension correct**: For 3-hourly, 365 days = 2920 steps; for hourly, 8760. `ncdump -h forcing.nc | grep 'time ='`
3. **HRU IDs match attributes**: Compare hruId in forcing and attributes files. See dt_005.
4. **No fill values in data**: Check for -9999 or NaN values. See dt_013.

## Common Pitfalls

> **PITFALL**: Building the forcing by hand instead of with the tool.
> That brings back the traps the tool handles: precipitation divided by the wrong
> step (dt_003), pressure in kPa (dt_004), period-start time stamps, shortwave
> spikes.

> **PITFALL**: No reference elevation on a high basin.
> Air temperature and pressure then stand for the source cell's height, not the
> HRU's; snowmelt timing is wrong. See dt_031.

> **PITFALL**: Reusing forcing files from a different domain setup.
> hruId mismatch causes immediate crash. Always regenerate after changing GRU/HRU structure. See dt_005.

---

*This skill document is part of the hydrocraft-summa knowledge infrastructure.*
*Stage 2 of 7 | Tools used: build_summa_forcing_from_reanalysis | Related triplets: dt_003, dt_004, dt_005, dt_012, dt_013, dt_031, dt_032*

## Known archive issue: CMFD V0200 SRad spurious spikes (Tibetan Plateau)

CMFD V0200 3-hourly `SRad` contains rare physically impossible spikes over the
Tibetan Plateau (upper Yellow / Tangnaihai domain, probed 1980-1990: up to
2701 W/m2, at most 0.041% of a year, none in 1980-82). A 3-hour MEAN cannot
exceed the TOA horizontal ceiling (~1410 W/m2). `build_summa_forcing_from_reanalysis.py`
now clips values above `SW_CEILING_WM2=1410` with a logged count and a `sw_qc`
provenance entry, and ABORTS if more than 0.5% of a year exceeds the ceiling
(that indicates a units/loader error, never a spot artifact). Do NOT loosen
`RANGES["SWRadAtm"]` to swallow such values silently.

### Acceptance / resume contract (enforced by `validate_year_output`)

The shortwave QC is only meaningful if it also governs which files are
ACCEPTED, not just which are written. `validate_year_output()` is the single
gate used both after a write and on resume, and a forcing year is accepted
only when BOTH hold:

1. `SWRadAtm <= SW_CEILING_WM2` (1410 W/m2), via `POST_QC_MAX`, which caps the
   accepted upper bound below the raw `RANGES["SWRadAtm"]` bound of 1500; and
2. the global attribute `sw_qc` is present (`REQUIRED_PROVENANCE_ATTRS`).

`RANGES` is unchanged and still describes the RAW archive; `POST_QC_MAX` is the
post-QC contract. Both checks exist because a cached year written before the QC
step can otherwise be skipped as "complete": a file with `SWRadAtm` max in the
1410-1500 band satisfies the raw range check, and a file with no provenance at
all was never screened. Observed on this domain: `forcing_1984.nc` from the
pre-QC build has an SW max of 1420 W/m2, and none of the pre-QC files carry
`sw_qc`.

Consequence on the first run after this change: every pre-QC cached year is
rejected and rebuilt, logging
`rebuilding -- cached file rejected (missing 'sw_qc' provenance attribute ...)`.
This is intended -- it is what guarantees the scored run's forcing came
entirely from the QC-aware path. Use `--force` only to rebuild unconditionally.
