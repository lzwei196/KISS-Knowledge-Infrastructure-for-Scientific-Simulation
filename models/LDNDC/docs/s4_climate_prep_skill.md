# Climate Data Preparation — Skill Document

> **Stage ID**: s4_climate_prep
> **Pipeline order**: 4 of 10
> **Depends on**: s1_project_setup

## Purpose

Convert meteorological forcing data from external sources (CMFD, MSWX, NASA POWER, FLUXNET site files) into LDNDC's tab-separated `climate.txt` format. This is the primary driver for all LDNDC processes: soil temperature, decomposition rates, ET, snow dynamics, and plant growth all depend on correct climate input.

## Prerequisites

- [ ] Project directory created (S1 complete)
- [ ] Forcing data source identified and accessible
- [ ] Simulation period matches forcing data availability
- [ ] Python environment activated with xarray, netCDF4 installed

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| forcing_source | string | User | cmfd, mswx, nasa_power, fluxnet, fluxnet_fullset |
| forcing_path | directory | HydroCraft data | Path to forcing data files |
| lat, lon | number | S1 | Grid cell coordinates |
| start_date, end_date | string | S1 | Simulation period |
| output_path | file | S1 | Target climate.txt path in input/ |

## Procedure

### Step 1: Convert forcing to LDNDC format

```bash
python tools/s4_climate_prep/convert_forcing_to_ldndc_climate.py \
  <forcing_source> <forcing_path> <lat> <lon> <start YYYY-MM-DD> <end YYYY-MM-DD> <output climate.txt> <elevation_m>
# elevation_m is REQUIRED (real site elevation in metres). It is written to the
# climate.txt %attributes block, which the LDNDC binary reads. There is no 0 m
# default: without it the tool stops with a usage message.
# CMFD: forcing_path = KISSPATH_DATA/forcing/Data_forcing_03hr_010deg
```

**Unit conversion table** (for CMFD/MSWX/NASA POWER the shared loader converts from the known
source unit; nothing is guessed from magnitude. The tool then stops if any daily temperature is
outside -100..70 C):

| Variable | CMFD unit | MSWX unit | LDNDC unit |
|----------|-----------|-----------|------------|
| Temperature | K | C | C (CMFD: subtract 273.15) |
| Precipitation | kg/m2/s | mm/3hr | mm/day (sum over the day) |
| SW radiation | W/m2 | W/m2 | W/m2 (daily mean) |
| Wind speed | m/s | m/s | m/s (daily mean) |

The shared loader (`ki_tools_common.load_forcing.load_daily_forcing`) does these conversions; the tool writes `prec tavg tmax tmin grad wind`.

### Step 2: Validate climate file

```bash
python tools/s4_climate_prep/validate_climate_file.py
```

Set `climate_file` to the generated climate.txt path.

**Expected result**: Validation passes with no errors. What the tool really checks:
- Native files: the column header is the line after `%data` (the `%global`,
  `%climate`, `%attributes` blocks are skipped); plain tab files use line 1
- At least one data row; the header is tab-separated
- Header has required columns (tavg or tmin+tmax, prec)
- In the first 10 data rows only: an error (dt_005) if tavg (or tmin when there is no tavg) is > 100

It does not check precipitation sign, missing values or the full temperature range; the converter
(`convert_forcing_to_ldndc_climate.py`) already stops on those before writing climate.txt.

**If validation fails**: See dt_005 (temperature units) or dt_006 (format errors).

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| climate.txt | `{project_dir}/input/climate.txt` | Tab-separated, header + one row per day, covers simulation period |

## Validation Checks

1. **Row count**: Number of data rows = number of days in simulation period
   - Command: `wc -l climate.txt` minus 1 (header)
   - Expected: (end_date - start_date).days + 1
2. **Temperature range**: All tavg/tmax/tmin values in [-100, 70] C. The converter enforces this
   and stops otherwise. Units come from the source metadata (the shared loader converts from the known
   source unit, e.g. CMFD K - 273.15; FLUXNET is read as degC), never from the size of the values.
   - A value outside this range means a unit was declared wrong at the source (see dt_005): fix the
     source unit and rebuild; never convert by magnitude.
3. **Precipitation non-negative**: All prec values >= 0
4. **No NaN/missing**: No empty cells or NaN values
5. **Column count**: Consistent number of tab-separated columns across all rows

## Common Pitfalls

> **PITFALL**: Temperature in Kelvin
> CMFD and ERA5 provide temperature in Kelvin. If fed directly to LDNDC without K->C conversion, all temperature-dependent processes are wrong. LDNDC gives no error.
> **Do this instead**: Check first data row -- convert declared Kelvin units upstream; never infer units solely from magnitude.
> See diagnostic triplet dt_005.

> **PITFALL**: Sub-daily precipitation not summed
> CMFD and MSWX use 3-hourly timesteps (8 per day). Daily precip must be the SUM of all sub-daily values, not a single value. Taking only one value gives 1/8 the correct precipitation.
> See diagnostic triplet dt_014.

> **PITFALL**: Comma-separated instead of tab-separated
> LDNDC requires TAB separation. Comma-separated or space-separated files cause parse errors.
> See diagnostic triplet dt_006.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 4 of 10 | Tools used: convert_forcing_to_ldndc_climate, validate_climate_file | Related triplets: dt_005, dt_006, dt_014*

## Strict source contract (2026-10 repair)

For `fluxnet_fullset`, supply FULLSET_HH/HR with `TIMESTAMP_START`,
`TIMESTAMP_END`, `TA_F_MDS`, `P_F`, `SW_IN_F`, `WS_F`. For `fluxnet`, use
ERAI_HH/HR with TA_ERA/P_ERA/SW_IN_ERA/WS_ERA. A DD path resolves only to
an unambiguous sibling HH/HR product, recorded in the provenance sidecar.
The `DD` token may end the name (`..._DD.csv`) or sit inside an original
FLUXNET2015 name (`FLX_CN-Din_FLUXNET2015_FULLSET_DD_2003-2005_1-4.csv` ->
`..._HH_2003-2005_1-4.csv` or `..._HR_...`); only that token changes.
DD daytime/nighttime averages are not daily maxima/minima; if interval data
is absent, conversion stops. Provider-filled F values are retained as supplied;
this tool performs no additional gap filling or ERA field substitution.

Every requested 30- or 60-minute interval and all six derived daily fields must
be finite and present. Temperature mean/min/max are derived from every substep;
interval precipitation is summed, and radiation/wind averaged. Missing values,
-9999, duplicate/off-grid intervals, negative P/SW/wind and invalid temperature
ordering stop before replacing an existing output. Small genuine values are
written with 17 significant digits instead of being rounded to zero.

Only full calendar years (Jan 1–Dec 31) are accepted: annual rain and monthly
temperature-amplitude attributes need a complete annual cycle. Output uses
native `%global`, `%climate`, `%attributes`, `%data` blocks with
`prec tavg tmax tmin grad wind` columns and an exact row count.
climate.txt and `climate.txt.provenance.json` are staged together and put in
place as one unit; if either step fails, the previous pair is restored.
`climate.txt.provenance.json` records source SHA256, source product, intervals,
columns and zero local fills. Shared daily CMFD/MSWX/POWER adapters are checked
for complete dates/arrays and valid values; raw substep gaps hidden upstream
remain a separate shared-loader audit. No Kelvin-by-magnitude inference occurs.

Regression: `python -m unittest discover -s tests -p test_climate_contract.py -v`.
