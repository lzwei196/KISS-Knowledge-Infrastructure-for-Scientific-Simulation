# S1: Site Definition (.ini File) -- Skill Document

## Purpose

Generate the BIOME-BGC initialization (.ini) file that controls all aspects of a simulation: input file paths, simulation timing, climate change scenarios, CO2, site physical properties, initial conditions, and output configuration.

**If skipped**: The model cannot run -- the .ini file is the sole entry point.

**If done incorrectly**: Parameters silently shift (dt_004), causing wrong fluxes with no error message. This is the most dangerous stage.

## Prerequisites

- [ ] Meteorological data file exists (from S3: convert_forcing_to_bgc.py)
- [ ] EPC file exists (from S2: select_ecophysiology.py)
- [ ] Soil properties known (from HWSD or VIC soil params)
- [ ] Simulation period defined (start year, number of years)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| met_file | path | S3 output | Met data file path (relative to working directory) |
| epc_file | path | S2 output | Ecophysiology parameter file path |
| lat | float | DEM/VIC grid | Site latitude (degrees, negative for S hemisphere) |
| elevation | float | DEM | Site elevation (meters) |
| soil_depth | float | HWSD | Effective rooting depth (meters, typical 0.5-3.0) |
| sand, silt, clay | float | HWSD | Soil texture (%, must sum to 100) |
| start_year | int | User | First simulation year |
| n_met_years | int | Met file | Number of years in met data |
| mode | str | User | "spinup" or "normal" |
| co2_ppm | float | Mauna Loa | CO2 concentration (ppm, 280-420 for historical) |
| ndep | float | Global dataset | N deposition (kgN/m2/yr, 0.0001-0.01) |

## Procedure

### Step 1: Run generate_site_ini.py

```bash
python tools/generate_site_ini.py \
  --met_file <met_path> --epc_file <epc_path> \
  --output_prefix <output_dir/prefix> \
  --lat <lat> --elevation <elev> \
  --soil_depth <depth_m> --sand <pct> --silt <pct> --clay <pct> \
  --start_year <year> --n_met_years <N> \
  --mode <spinup|normal> \
  --co2_ppm <ppm> --ndep <kgN/m2/yr> \
  --output <output_ini_path>
```

**Expected result**: JSON with status=success, ini_sections=12 (11 keyword sections + END_INIT).

**If it fails**: Check the JSON error message. Most common: sand+silt+clay != 100 (see dt_003).

### Step 2: Verify the .ini file

After generation, verify:
1. All file paths exist: met file, epc file, restart directory
2. The output prefix directory exists (create if needed)
3. For normal mode with restart: the restart .endpoint file exists

### Step 3: For spinup mode

The tool automatically:
- Sets spinup flag = 1
- Sets write_restart = 1
- Disables daily/annual output (saves disk)
- Sets max_spinup_years = 6000

### Step 4: For normal mode with restart

Pass `--read_restart` to read the spinup endpoint file.

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| .ini file | As specified by --output | File exists, ~80-120 lines |

## Validation Checks

1. [ ] File contains all 11 keyword sections (MET_INPUT through END_INIT)
2. [ ] sand + silt + clay = 100.0
3. [ ] soil_depth is in meters (0.5-3.0 typical)
4. [ ] CO2 is in ppm (100-1500)
5. [ ] N deposition is in kgN/m2/yr (0.0001-0.01 typical)
6. [ ] All referenced files exist

## Common Pitfalls

- **dt_004**: Extra blank line in manually edited .ini shifts all parameters. NEVER hand-edit.
- **dt_005**: CO2 in wrong units (fraction vs ppm). Tool validates range.
- **dt_006**: Soil depth in cm instead of m. Tool validates range (0, 10].
- **dt_002**: Wrong file paths. Use absolute paths or verify working directory.
