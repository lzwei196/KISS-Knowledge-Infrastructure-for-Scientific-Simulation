# S4: Model Execution

## Purpose

Run the Daisy binary on a prepared `.dai` setup file and capture all outputs, logs, and potential error messages.

## Inputs

| Input | Source | Format | Required |
|-------|--------|--------|----------|
| Main `.dai` file | S3 output | Daisy setup file | Yes |
| Weather `.dwf` file | S1 output | Daisy Weather File | Yes |
| Soil `.dai` file | S2 output | Soil definitions | Yes |
| Library files | Daisy install | crop.dai, tillage.dai, etc. | Yes |
| Daisy binary | Build or install | `daisy` executable | Yes |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `harvest.dlf` | Daisy Log File | Harvest events |
| `field_nitrogen.dlf` | Daisy Log File | Field N balance |
| `field_water.dlf` | Daisy Log File | Field water balance |
| `soil_nitrogen.dlf` | Daisy Log File | Soil N profile |
| `soil_water.dlf` | Daisy Log File | Soil water profile |
| `<crop>.dlf` | Daisy Log File | Crop development |
| `checkpoint-*.dai` | Daisy checkpoint | Simulation state for restart |
| `daisy.log` | Log file | Run log with errors/warnings |

## Procedure

1. **Locate binary**:
   ```bash
   # From build directory
   /path/to/daisy/build/linux-gcc-portable/daisy

   # From system install
   daisy

   # Check version
   daisy -v
   ```

2. **Prepare working directory** — Copy/link all input files:
   ```bash
   mkdir -p /tmp/daisy-run
   cp my-setup.dai my-weather.dwf my-soil.dai /tmp/daisy-run/
   cd /tmp/daisy-run
   ```

3. **Run simulation**:
   ```bash
   daisy my-setup.dai
   ```
   Daisy reads the .dai file, loads libraries from its lib/ directory, and writes output .dlf files to the current directory.

4. **Check results**:
   ```bash
   # Check log for errors
   grep -i error daisy.log

   # List output files
   ls *.dlf

   # Quick preview of harvest
   head -30 harvest.dlf
   ```

5. **Batch execution** (multiple scenarios):
   ```bash
   # Using batch mode
   daisy batch-setup.dai

   # Using spawn mode (parallel)
   daisy spawn-setup.dai
   ```

## Verification

- [ ] `daisy.log` exists and shows no fatal errors
- [ ] Expected .dlf files are present and non-empty
- [ ] Harvest yield values are physically reasonable (2–15 Mg DM/ha for cereals)
- [ ] Checkpoint file generated (confirms simulation reached checkpoint date)
- [ ] No "nan" or "inf" values in output files
- [ ] Simulation end date matches expected stop time

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Library files not found | "Unknown component" errors | Run from directory with lib/ visible, or install Daisy properly |
| Wrong working directory | "File not found" for .dwf | cd to directory containing input files before running |
| Binary not on PATH | "command not found" | Use full path or add build dir to PATH |
| Memory exhaustion | Killed / segfault on long runs | Reduce output frequency, use monthly instead of hourly |
| Infinite simulation | Hangs, never finishes | Check management timeline — a `wait` condition may never be satisfied |
| Negative time step | "Negative dt" error | Usually caused by extreme soil hydraulic conditions; check K_sat and soil params |
| Convergence failure | "Could not find solution" warnings | Reduce irrigation intensity, check soil parameter consistency |

## Example

```bash
# Using the wrapper tool
python ki/tools/run_daisy.py \
    --dai-file test.dai \
    --work-dir /tmp/daisy-test \
    --binary /path/to/build/linux-gcc-portable/daisy \
    --timeout 300

# Direct execution
cd /tmp/daisy-test
/path/to/daisy test.dai
echo "Exit code: $?"
ls -la *.dlf
```

### Expected Runtime

| Simulation Type | Duration | Typical Runtime |
|----------------|----------|-----------------|
| Single year, daily output | 1 year | 5–30 seconds |
| Multi-year rotation | 5 years | 30–120 seconds |
| High-frequency hourly output | 1 year | 30–180 seconds |
| Batch (10 scenarios) | 5 years each | 5–20 minutes |
