# S5: Production Run

## Purpose

Execute the main SNOWPACK simulation after spinup is complete. The production
run generates the primary outputs: snow depth evolution, SWE, energy fluxes,
mass balance terms, and optionally layer profiles and stability indices.

## Inputs

| Input          | Description                                        |
|----------------|----------------------------------------------------|
| io.ini         | Production configuration file                       |
| station.smet   | Meteorological forcing for the simulation period    |
| station.sno    | Initial profile (from spinup or bare ground)        |

## Outputs

| Output           | Description                                      |
|------------------|--------------------------------------------------|
| station.met      | Time series: HS, SWE, energy/mass fluxes          |
| station.pro      | Layer profiles: T, ρ, grain size at intervals      |
| station.haz      | Avalanche hazard indices (if enabled)              |
| station.sno      | Final snowpack state (restart file)                |

## Procedure

1. **Verify inputs** — Confirm .smet covers the full simulation period;
   .sno profile date matches or precedes first forcing timestamp.
2. **Create output directory** — Must exist before running SNOWPACK.
3. **Run simulation** — `snowpack -c io.ini -e <end_date>`
4. **Monitor** — Check for errors in stderr.
5. **Verify output** — Confirm .met file exists and has expected length.

## Verification

```bash
# Check output file exists and has data
wc -l output/station.met
# Quick visual check: HS should show seasonal cycle
awk '/^[0-9]/ {print $1, $2}' output/station.met | head -20

# Check for NaN in output
grep -c "nan" output/station.met
```

### Expected behavior
- Alpine sites: Snow accumulates Oct–Mar, melts Apr–Jun, HS returns to ~0 by July
- Polar sites: Snow may persist year-round
- Snow density increases from ~50–100 kg/m³ (new snow) to 300–500 kg/m³ (old snow)
- SWE should be non-negative at all times

## Traps

### Forcing gap causes crash (dt_016) — FATAL
If the SMET file has a gap larger than the MeteoIO buffer, the simulation
crashes with a "no data available" error. MeteoIO can interpolate small gaps
but not large ones.

**Prevention:** Ensure continuous hourly data. Fill gaps with interpolation
or reanalysis data before running.

### Profile date after first forcing timestamp
If the .sno ProfileDate is after the first SMET timestamp, SNOWPACK has no
initial state for the early period. It may crash or produce garbage.

**Rule:** ProfileDate ≤ first SMET timestamp.

### Output directory doesn't exist (dt_016)
SNOWPACK does not create the output directory automatically. If the path
in [Output] METEOPATH doesn't exist, the simulation runs but cannot write
output — effectively a silent failure on some systems.

### Very long simulations and memory
For multi-decade simulations, SNOWPACK accumulates layers in memory. With
the default MINIMUM_L_ELEMENT = 0.01 m and annual snowfall of 3+ m, the
model creates many layers. Set REDUCE_N_ELEMENTS to limit layer count.

### Timestep stability
With explicit solvers, very large timesteps (>15 min for deep snowpacks)
can cause oscillations in the temperature profile. Symptoms: oscillating
TSS, energy balance not closing.

## Example

```bash
# Standard production run
python tools/run_snowpack.py \
    --binary ./build/bin/snowpack \
    --config io.ini \
    --end_date "1996-06-30T23:00" \
    --mode production

# Check output
python tools/parse_output.py \
    --input output/MST96.met \
    --output results/MST96_ts.csv \
    --variables HS,SWE,TA,qs,ql,MS_RUNOFF
```
