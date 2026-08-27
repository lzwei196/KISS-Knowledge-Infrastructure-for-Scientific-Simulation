# S5: Spinup Strategy -- Skill Document

## Purpose

Run BIOME-BGC for hundreds to thousands of simulated years to bring soil carbon and nitrogen pools to steady-state equilibrium. This is the most critical and unique stage in the BIOME-BGC pipeline -- no other HydroCraft model requires multi-century spinup.

**If skipped**: NEE estimates are meaningless -- dominated by initial condition artifacts for decades. Soil C pools trend monotonically instead of fluctuating around equilibrium. Published studies that skip spinup are scientifically invalid.

**If truncated**: If spinup is too short, soil C pools are still trending. NEE will show a drift that masks the real climate signal.

## Prerequisites

- [ ] Spinup .ini generated (mode=spinup, write_restart=1, no output)
- [ ] Met file exists (from S3)
- [ ] EPC file exists (from S2)
- [ ] Restart directory exists (for writing .endpoint file)
- [ ] CO2 set to appropriate value (280 ppm for pre-industrial, or ~370 for year-2000 start)

## Why Spinup Is Necessary

Soil organic carbon (SOC) pools have turnover times of:
- Fast pool (soil1c): ~10-20 years
- Medium pool (soil2c): ~20-50 years
- Slow pool (soil3c): ~100-500 years
- Recalcitrant pool (soil4c): ~500-5000 years

Starting from zero initial conditions, these pools take centuries to millennia to reach equilibrium. During this transient period:
- NEE is strongly negative (apparent carbon sink) as pools fill
- The "sink" is an artifact of initialization, not a real climate response
- Only after equilibrium does NEE reflect actual ecosystem-atmosphere exchange

## Spinup Duration by Biome

| Biome | Typical Duration | Reasoning |
|-------|-----------------|-----------|
| C3/C4 Grassland | 1000-1500 years | No wood, fast turnover |
| Deciduous Broadleaf | 2000-3000 years | Moderate wood, deciduous litter |
| Evergreen Needleleaf | 3000-6000 years | Slow-decomposing litter (high lignin) |
| Boreal/Taiga | 4000-6000 years | Cold temperatures slow decomposition |
| Tropical Evergreen | 2000-3000 years | Warm temperatures speed decomposition |
| Shrubland | 1500-2500 years | Low biomass but slow woody decomposition |

## Procedure

### Step 1: Configure spinup .ini

```bash
python tools/generate_site_ini.py \
  --met_file <met_file> --epc_file <epc_file> \
  --output_prefix outputs/spinup \
  --lat <lat> --elevation <elev> \
  --soil_depth <m> --sand <pct> --silt <pct> --clay <pct> \
  --start_year <start> --n_met_years <N> \
  --mode spinup \
  --max_spinup_years 6000 \
  --co2_ppm 280 \
  --ndep 0.0001 \
  --output spinup.ini
```

**Key spinup settings:**
- `mode=spinup`: Sets spinup flag, disables output, enables restart writing
- `co2_ppm=280`: Pre-industrial CO2 for equilibrium (NOT modern ~420 ppm)
- `ndep=0.0001`: Pre-industrial N deposition (NOT modern values)
- `max_spinup_years=6000`: Safety limit (usually converges in 2000-4000)

### Step 2: Run spinup

```bash
python tools/run_bgc_spinup.py \
  --bgc_binary KISSPATH_BINARIES/biome-bgc/bgc-src/bgc \
  --ini_file spinup.ini \
  --timeout 600
```

**Expected runtime**: 1-5 minutes wall clock for 6000 model years. This is NORMAL -- do not interrupt.

**Expected result**: JSON with status=success, restart_file path, restart_size_bytes == sizeof(restart_data_struct) for the build — 584 bytes for the shipped 4.2 binary (identical to the bundled `restart/enf_test1.endpoint`). A 584-byte endpoint is complete; 0 bytes means the spinup crashed.

### Step 3: Verify spinup convergence

After spinup, check:
1. The restart (.endpoint) file was written
2. File size equals sizeof(restart_data_struct) — 584 bytes with the shipped binary (empty = crash during spinup)

For detailed convergence checking, run a short normal simulation reading the restart and examining the annual output trend over the last 100 years. SOC change should be < 0.5 gC/m2/yr.

### Step 4: Set up normal run to read restart

```bash
python tools/generate_site_ini.py \
  ... (same site params) \
  --mode normal \
  --read_restart \
  --restart_file restart/<prefix>.endpoint \
  --co2_ppm 370 \
  --output normal.ini
```

## Convergence Criteria

| Criterion | Threshold | How to Check |
|-----------|-----------|-------------|
| SOC annual change | < 0.5 gC/m2/yr | Compare soilc between last two years |
| Net N mineralization change | < 0.01 gN/m2/yr | Check daily_net_nmin annual sum trend |
| Total ecosystem C change | < 1.0 gC/m2/yr | Compare totalc between consecutive years |

## Common Spinup Failures

### Failure: SOC keeps increasing (dt_012)
**Cause**: N deposition too high (modern value used for pre-industrial spinup)
**Fix**: Set ndep to 0.0001 kgN/m2/yr for spinup

### Failure: Negative soil mineral N (dt_013)
**Cause**: N immobilization exceeds input over centuries
**Fix**: Increase nfix from 0.0004 to 0.0008 kgN/m2/yr

### Failure: Strong NEE drift in normal run after spinup (dt_014)
**Cause**: CO2 mismatch between spinup (280 ppm) and normal run (370+ ppm)
**Fix**: Use transition period or set spinup CO2 closer to normal run start

### Failure: SOC oscillates without converging (dt_016)
**Cause**: Short met record (5-10 years) with high variability
**Fix**: Use 20+ year met record or increase max_spinup_years

### Failure: Restart file read error (dt_015)
**Cause**: Incompatible binary version or corrupted file
**Fix**: Re-run spinup with the same binary that will read the restart

## Spinup Acceleration (Advanced)

BIOME-BGC 4.2 supports spinup acceleration (Thornton & Rosenbloom 2005) internally. After ~300 simulated years, slow SOM pool decomposition rates are temporarily multiplied. This reduces effective spinup time from ~6000 to ~500-1000 years without loss of accuracy.

The acceleration is controlled by the model internally when the spinup flag is set. No additional configuration needed.

## Post-Spinup CO2 Transition Strategy

For historical simulations starting at year 2000:
1. **Spinup**: CO2 = 280 ppm (pre-industrial steady state)
2. **Transition (optional)**: 50-year ramp from 280 to 370 ppm using co2_flag=1 and a CO2 file
3. **Normal run**: CO2 = 370+ ppm (or time-varying from co2.txt)

If skipping the transition, expect ~10-20 years of NEE drift at the start of the normal run. Discard this as warmup.

## Validation Checks

1. [ ] Restart file exists and size == 584 bytes (sizeof restart_data_struct for the shipped binary; compare with `restart/enf_test1.endpoint`)
2. [ ] Spinup used pre-industrial CO2 (280 ppm) and N deposition (0.0001)
3. [ ] Spinup duration was appropriate for the biome (see table)
4. [ ] Normal run reads the spinup restart successfully
5. [ ] NEE in normal run does not show monotonic drift over the simulation period
