# S4: Spinup Simulation

## Purpose

Run a spinup simulation to bring soil temperatures and moisture content to
equilibrium before the production run. Without spinup, the initial soil
conditions (arbitrary temperature, moisture) create a transient signal that
contaminates the first weeks to months of snow simulation results.

## Inputs

| Input          | Description                                        |
|----------------|----------------------------------------------------|
| spinup.ini     | Config file (may differ from production config)     |
| station.smet   | Meteorological forcing (same as production)         |
| station.sno    | Initial profile with soil layers                    |

## Outputs

| Output           | Description                                      |
|------------------|--------------------------------------------------|
| station.sno      | Updated profile with equilibrated soil temps      |
| station.met      | Time series (typically discarded for spinup)      |

## Procedure

1. **Prepare spinup config** — Copy production config, optionally reduce output.
2. **Run spinup** — Execute SNOWPACK for 1–3 complete annual cycles.
3. **Extract end profile** — The final .sno state from spinup becomes the
   initial state for production.
4. **Verify** — Check that soil temperatures are physically reasonable
   (not oscillating unrealistically).

### Spinup strategy

For sites with seasonal snow:
- Run 2–3 years of the same forcing data cyclically.
- The soil temperature profile should converge after 1–2 cycles.

For permafrost sites:
- Spinup may require 10+ years due to deep thermal inertia.
- Use steady-state analytical estimates as initial conditions to reduce spinup time.

For bare soil (no snow layer data):
- Start in early autumn before first snowfall.
- Soil layers will equilibrate during the first freeze cycle.

## Verification

```bash
# Compare soil temperatures between start and end of spinup
# They should be close (within 0.5 K) if equilibrium is reached
head -5 spinup_output/station.sno   # End profile
head -5 input/station.sno           # Start profile
```

Check that:
- Deep soil temperature is stable (±0.2 K between cycles)
- Surface soil temperature shows realistic seasonal cycle
- No numerical instabilities (NaN, extreme values)

## Traps

### Insufficient spinup length
If spinup is too short (e.g., 1 month), soil temperatures retain the arbitrary
initial values. This creates:
- Artificial ground heat flux at the start of the production run
- Wrong snow-ground interface temperature
- Incorrect basal melt rates

**Rule of thumb:** Spinup = at least 2 full annual cycles.

### Using wrong forcing for spinup
If spinup uses a different time period than production, the soil equilibrates
to the wrong climate. Use the same forcing data or a climatological average.

### Forgetting to update the .sno file
After spinup, the final profile must be copied as the initial condition for
the production run. If you reuse the original bare-ground .sno, the spinup
was wasted.

## Example

```bash
# 1. Run 2-year spinup
python tools/run_snowpack.py \
    --binary ./build/bin/snowpack \
    --config spinup.ini \
    --end_date "1997-10-01T00:00" \
    --mode spinup

# 2. Copy end profile as production initial condition
cp output/spinup_MST96.sno input/MST96.sno

# 3. Run production
python tools/run_snowpack.py \
    --binary ./build/bin/snowpack \
    --config io.ini \
    --end_date "1998-06-30T00:00"
```
