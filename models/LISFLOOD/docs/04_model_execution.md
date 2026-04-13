# Stage 4: Model Execution

## Purpose

Execute the LISFLOOD hydrological model, handling cold starts (spin-up), warm starts (from saved state), and common runtime issues.

## Inputs

| Input | Description | Notes |
|-------|-------------|-------|
| settings.xml | Complete LISFLOOD configuration | All paths, parameters, options |
| Forcing data | pr, ta, et0, e0 NetCDF stacks | Covering StepStart to StepEnd |
| Static maps | MaskMap, LDD, soil, land use, channels | In PathMaps directory |
| Initial conditions | State maps (optional for cold start) | In PathInit directory |

## Outputs

| Output | Description | Location |
|--------|-------------|----------|
| dis.nc | Discharge maps [m³/s] | PathOut |
| *.tss | Time series at gauges | PathOut |
| State maps (cold start) | End-state for warm start | PathInit |
| *.nc | Other output variables | PathOut |

## Procedure

### Cold Start (Spin-up)

1. **Set `InitLisflood = 1`** in settings XML options
2. **Set initial values** for state variables:
   - `ThetaInit1Value`, `ThetaInit2Value`, `ThetaInit3Value` — soil moisture [m³/m³]
   - `LZInitValue` — lower zone storage [mm]
   - `UZInitValue` — upper zone storage [mm]
   - `SnowCoverAInitValue`, etc. — snow cover [mm]
3. **Run the model**: `lisflood settings/cold.xml`
4. **Save end-state maps** for warm start initialization

### Warm Start

1. **Set `InitLisflood = 0`**
2. **Point initial conditions** to cold-run end-state maps
3. **Run the model**: `lisflood settings/warm.xml`

### Execution Command

```bash
# Method 1: installed package
lisflood /path/to/settings.xml

# Method 2: from source
python src/lisf1.py /path/to/settings.xml

# Method 3: with execution wrapper (preflight checks)
python tools/run_lisflood.py --settings /path/to/settings.xml --mode cold

# Method 4: Monte Carlo ensemble
lisflood settings.xml -m 100

# Method 5: Ensemble Kalman Filter
lisflood settings.xml -e 50
```

## Verification

- [ ] Model runs without errors (check stderr output)
- [ ] dis.nc exists in PathOut and has expected time dimension
- [ ] Discharge values are physically reasonable (not all zero, not NaN)
- [ ] Water balance residual (twb.nc) is near zero
- [ ] Runtime is reasonable (minutes to hours, not days)
- [ ] No NaN warnings in model output

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| dt_011 | fatal | MaskMap path not found — immediate crash |
| dt_012 | fatal | Forcing path/prefix mismatch — `Unable to open` error |
| dt_013 | fatal | Lake/reservoir ID missing from lookup table — NaN or crash |
| dt_017 | degraded | Numba JIT compilation fails — falls back to slow Python loop |
| dt_018 | **silent** | writeNetcdfStack and writeNetcdf both off — no spatial output |

## Common Errors and Solutions

### "Unable to open file"
- **Cause**: Path in settings.xml doesn't resolve correctly
- **Fix**: Use absolute paths or ensure `$(PathRoot)` resolves correctly
- **Check**: `python tools/run_lisflood.py --settings settings.xml --check_only`

### "Error reading NetCDF"
- **Cause**: NetCDF format incompatibility or corrupted file
- **Fix**: Verify with `ncdump -h forcing.nc`

### Segmentation fault
- **Cause**: Usually PCRaster-related — LDD issues, memory overflow
- **Fix**: Check LDD validity, reduce domain size, increase memory

### Very slow execution
- **Cause**: Numba compilation on first run (normal), or very small DtSec
- **Fix**: First run is slower due to JIT compilation. For subsequent runs, Numba caches.
- **Alternative**: Set `numCPUs_parallelNumba = 0` for auto-parallelization

## Example

```bash
# Full workflow: cold start → warm start
# 1. Create output directory
mkdir -p /data/lisflood/out

# 2. Cold start (1-year spin-up)
lisflood /data/lisflood/settings/cold.xml

# 3. Verify cold start succeeded
ls -la /data/lisflood/out/dis.nc
python -c "import netCDF4; d=netCDF4.Dataset('/data/lisflood/out/dis.nc'); print(d['dis'].shape)"

# 4. Warm start (production run)
lisflood /data/lisflood/settings/warm.xml

# 5. Check discharge output
python tools/parse_output.py \
    --output_dir /data/lisflood/out \
    --summary /data/lisflood/run_summary.json
```
