# Stage 3: Configuration

## Purpose

Set up the LPJmL configuration file (`lpjml_config.cjson`) with correct simulation parameters, input/output paths, and model switches for the target simulation. The configuration controls all aspects of the simulation including which processes are active, temporal extent, and output variables.

## Inputs

| Input | Description |
|-------|-------------|
| `lpjml_config.cjson` | Master configuration template |
| `input.cjson` | Input file paths (CLM format) |
| `input_netcdf.cjson` | Input file paths (NetCDF format, alternative) |
| `par/*.cjson` | Parameter files (PFT, soil, hydro, management) |

## Outputs

| Output | Description |
|--------|-------------|
| Preprocessed JSON | `lpjml_config_spinup.json` or `lpjml_config_restart.json` |

## Procedure

### 1. Choose simulation type

- **Natural vegetation only** (PNV): `landuse: "no"`, no FROM_RESTART
- **With crops/land use**: `landuse: "yes"`, requires FROM_RESTART and spinup restart

### 2. Set key switches

```json
{
    "with_nitrogen": "lim",           // Nitrogen limitation on/off
    "fire": "fire",                   // Fire module: "no_fire", "fire", "spitfire"
    "irrigation": "lim",             // "no", "lim" (water-limited), "pot" (potential)
    "sowing_date_option": "prescribed_sdate",  // Use input sowing dates
    "crop_phu_option": "prescribed",  // Use input PHU values
    "fertilizer_input": "yes",       // Read fertilizer from input files
    "manure_input": true,            // Read manure from input files
    "river_routing": true,           // Enable global river routing
    "permafrost": true,              // Enable permafrost module
    "reservoir": true,               // Enable reservoir operations
    "equilsoil": true/false          // true for spinup, false for transient
}
```

### 3. Set temporal parameters

**Spinup (natural vegetation)**:
```json
{
    "nspinup": 4000,        // 4000 years of spinup
    "nspinyear": 30,        // Cycle 30-year climate period
    "firstyear": 1901,      // First year of climate data
    "lastyear": 1901,       // Only output the last year
    "restart": false,
    "write_restart": true,
    "write_restart_filename": "restart/restart_1700_nv.lpj",
    "restart_year": 1700
}
```

**Transient (with land use, FROM_RESTART)**:
```json
{
    "nspinup": 420,         // Additional spinup with N cycling
    "nspinyear": 30,
    "firstyear": 1901,
    "lastyear": 2019,
    "outputyear": 1901,     // Start writing output from this year
    "restart": true,
    "restart_filename": "restart/restart_1700_nv.lpj",
    "write_restart": true,
    "write_restart_filename": "restart/restart_1900_crop.lpj",
    "restart_year": 1900
}
```

### 4. Configure input paths

Update `input.cjson` with paths to your prepared climate, soil, land use, and CO2 files. Set `inpath` to the base directory.

### 5. Select output variables

Add/remove entries in the `"output"` array. Each entry specifies:
```json
{ "id": "harvestc", "file": { "fmt": "raw", "name": "output/flux_harvest" }}
```

### 6. Set grid extent

```json
"startgrid": "all",    // or integer cell index
"endgrid": "all"       // or integer cell index
```

## Verification

- Run `bin/lpjcheck lpjml_config.cjson` to validate syntax
- Run `bin/lpjml -vv lpjml_config.cjson` to verbosely check values during config read
- Run `bin/lpjfiles lpjml_config.cjson` to list all input/output files

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Missing FROM_RESTART for transient | Runs as spinup (no crops) | Add `-DFROM_RESTART` to command |
| equilsoil=true in transient | Extremely slow, destroys soil C | Set `equilsoil: false` |
| Wrong firstyear/lastyear | ERROR015 (invalid year) | Match climate data period |
| inpath not set | ERROR002 (cannot find inputs) | Set LPJINPATH or `"inpath"` |
| Output directory missing | ERROR045 | Run `make test` or `mkdir output restart` |
| Version mismatch | Config rejection | Set `"version": "6.0"` |
| Missing parameter includes | Parse error | Ensure `par/*.cjson` files exist |
| soilmap null entry | First entry must be null for code 0 | Keep `null` as first soilmap entry |

## Example

```bash
# Check configuration
bin/lpjcheck lpjml_config.cjson

# List all required files
bin/lpjfiles lpjml_config.cjson

# Run with verbose config reading
bin/lpjml -vv lpjml_config.cjson
```
