# Stage 4: Model Execution

## Purpose

Run the compiled RHESSys binary with properly configured inputs. This stage
covers command-line construction, common runtime flags, calibration parameters,
and diagnosing execution failures.

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `rhessys7.4` binary | Yes | Compiled model executable |
| World file (`.world`) | Yes | Spatial domain definition |
| World header (`.hdr`) | Yes | Parameter file references |
| TEC file | Yes | Temporal event control |
| Flow table | Recommended | Lateral routing connectivity |
| Climate files | Yes | Via base stations in worldfile |
| Output prefix | Yes | Path prefix for output files |

## Outputs

| Output | Condition | Description |
|--------|-----------|-------------|
| `<prefix>_basin.daily` | `-b` flag | Basin-aggregated daily time series |
| `<prefix>_patch.daily` | `-p` flag | Per-patch daily time series |
| `<prefix>_basin.monthly` | TEC monthly on | Monthly summaries |
| `<prefix>_basin.yearly` | TEC yearly on | Annual summaries |
| `<prefix>_grow_*.daily` | `-g` flag | BGC/growth output |

## Procedure

### Step 1: Basic Execution

Minimal command:
```bash
./rhessys7.4 \
  -w worldfiles/w.world \
  -whdr worldfiles/w.hdr \
  -t tecfiles/tec.test \
  -pre out/run1 \
  -st 1988 10 1 1 \
  -ed 2000 10 1 1 \
  -b
```

### Step 2: Enable Routing

```bash
./rhessys7.4 ... -r flowtables/w.flow
```

Without `-r`, the model uses TOPMODEL-based redistribution within each hillslope.
With `-r`, it uses explicit patch-to-patch routing from the flow table.

### Step 3: Enable BGC Mode

```bash
./rhessys7.4 ... -g
```

The `-g` flag activates carbon/nitrogen cycling (growth). Without it, only the
hydrological model runs and vegetation is static.

### Step 4: Calibration Parameters

The `-s`, `-sv`, and `-svalt` flags multiply default soil parameters:

```bash
./rhessys7.4 ... \
  -s 0.355 651.39 \         # m_multiplier Ksat_multiplier [soil_depth_mult]
  -sv 0.355 651.39 \        # vertical: m_mult Ksat_mult
  -svalt 1.08 1.19           # pore_size_index_mult psi_air_entry_mult
```

**TRAP dt_013:** Never set sensitivity multipliers to 0. This zeros out Ksat or m,
causing division-by-zero or infinite loop. Use very small positive values instead.

### Step 5: Groundwater

```bash
./rhessys7.4 ... -gw 0.01 0.1
# sat_to_gw_coeff = 0.01 (fraction of sat excess going to deep GW)
# gw_loss_coeff = 0.1 (fraction of GW lost per day)
```

### Step 6: TEC File Setup

The TEC file controls when output begins and what type:
```
1989 10 1 1 print_daily_on
1989 10 1 2 print_daily_growth_on
```

**TRAP dt_014:** If the `print_daily_on` event date is BEFORE the `-st` date,
it will be ignored and NO output is produced. Always ensure TEC events are
after the simulation start date.

### Step 7: Spin-up for BGC

**TRAP dt_012:** Carbon and nitrogen pools require centuries to equilibrate.
For BGC simulations:

1. Run 200-500 year spin-up with repeated climate
2. Use `-vegspinup` flag for accelerated spin-up
3. Save final state with TEC `output_current_state` event
4. Use saved state as initial condition for production run

Without spin-up, vegetation may die immediately or grow unrealistically.

## Verification

```bash
# Check model completed
echo $?  # Should be 0

# Check output files exist and have content
ls -la out/run1_basin.daily
wc -l out/run1_basin.daily

# Quick check: streamflow should be reasonable (0 to ~0.05 m/day for most basins)
awk '{print $24}' out/run1_basin.daily | sort -n | tail -5

# Check for NaN or Inf
grep -c -i "nan\|inf" out/run1_basin.daily
```

## Tool

```bash
python ki/tools/run_rhessys.py \
  --binary rhessys/rhessys7.4 \
  --worldfile worldfiles/w.world \
  --worldhdr worldfiles/w.hdr \
  --tecfile tecfiles/tec.test \
  --flowtable flowtables/w.flow \
  --prefix out/test \
  --start "1988 10 1 1" --end "2000 10 1 1" \
  --basin --grow \
  --sensitivity 0.355 651.39
```

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Sensitivity param = 0 | Crash / infinite loop | Use small positive value | dt_013 |
| TEC before start date | No output produced | Move TEC events after -st | dt_014 |
| Flow table mismatch | Segfault | Regenerate flow table | dt_015 |
| No -g flag | Static vegetation, no C/N output | Add -g for BGC mode | — |
| Missing NetCDF flag | Compile error on NetCDF code | Rebuild with -DLIU_NETCDF_READER | dt_016 |
| Negative sat_deficit | Crash / NaN propagation | Check soil parameter consistency | dt_018 |
| No spin-up | Vegetation dies or explodes | Run 200+ year spin-up | dt_012 |

## Example

Full test case command:
```bash
cd source/repo/Testing
../rhessys/rhessys7.4 \
  -t tecfiles/tec.test \
  -w worldfiles/w8TC.world \
  -whdr worldfiles/w8TC.hdr \
  -r flowtables/w8TC.flow \
  -pre out/test \
  -s 0.355794 651.390265 \
  -sv 0.355794 651.390265 \
  -svalt 1.083102 1.193924 \
  -st 1988 10 1 1 -ed 2000 10 1 1 \
  -b -g
```
