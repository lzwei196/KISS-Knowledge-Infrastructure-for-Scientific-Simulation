# Stage 3: Model Execution — Skill Document

## Purpose

Execute the HexWatershed binary with a prepared configuration to perform the full
hydrological analysis: depression filling, flow direction, stream definition, watershed
delineation, and characteristic computation.

## Inputs

| Input                         | Source        | Format | Notes                               |
|------------------------------|---------------|--------|--------------------------------------|
| `hexwatershed` binary        | CMake build   | ELF    | Compiled C++ executable              |
| Configuration JSON           | Stage 0       | JSON   | All parameters and paths             |
| Mesh JSON                    | Stage 1       | JSON   | Cell topology and elevations         |
| Basin JSON (optional)        | Stage 2       | JSON   | Only if iFlag_flowline=1             |

## Outputs

| Output                                 | Format | Description                        |
|----------------------------------------|--------|------------------------------------|
| `watershed_NNNNN.json`                 | GeoJSON| Per-watershed cell data            |
| `watershed_NNNNN_characteristics.txt`  | Text   | Basin-level summary metrics        |
| `watershed_NNNNN_segment_*.txt`        | Text   | Stream segment characteristics     |
| `watershed_NNNNN_subbasin_*.txt`       | Text   | Subbasin characteristics           |
| `hexwatershed.json`                    | JSON   | Domain-level summary (multi-outlet)|
| `hexwatershed.vtk`                     | VTK    | 3D visualization (if enabled)      |
| `configuration.in`                     | Text   | Copy of input configuration        |
| `starlog.txt`                          | Text   | Execution log                      |

## Procedure

1. **Build the binary** (if not already built):
   ```bash
   cd /path/to/hexwatershed/src/repo
   mkdir -p build && cd build
   cmake .. -DCMAKE_BUILD_TYPE=Release
   make -j$(nproc)
   ```

2. **Verify prerequisites**:
   ```bash
   # Binary exists and is executable
   test -x ./hexwatershed && echo "OK"

   # Config is valid JSON
   python3 -c "import json; json.load(open('config.json'))"

   # Output directory exists
   mkdir -p /data/output/hexwatershed
   ```

3. **Run the model**:
   ```bash
   ./hexwatershed /absolute/path/to/config.json
   ```

   Or use the wrapper tool:
   ```bash
   python run_hexwatershed.py --binary ./hexwatershed --config /path/to/config.json
   ```

4. **Monitor execution**:
   - The model prints progress to stdout
   - Runtime depends on mesh size: ~seconds for 1000 cells, minutes for 100K+
   - No progress bar; watch for "Finished" in output

5. **Check for errors**:
   - Non-zero exit code = crash
   - Zero exit code but no output files = silent failure (wrong config)

## Verification

```bash
# Check exit code
./hexwatershed config.json; echo "Exit code: $?"

# Check output files exist
ls /data/output/hexwatershed/watershed_*.json
ls /data/output/hexwatershed/watershed_*_characteristics.txt

# Quick validation of output
python3 -c "
import json, os
d = '/data/output/hexwatershed'
jsons = [f for f in os.listdir(d) if f.startswith('watershed_') and f.endswith('.json') and 'char' not in f]
print(f'Watershed files: {len(jsons)}')
for jf in jsons[:3]:
    data = json.load(open(os.path.join(d, jf)))
    if 'features' in data:
        print(f'  {jf}: {len(data[\"features\"])} cells')
"

# Check log for errors
grep -i "error\|fail\|abort" /data/output/hexwatershed/starlog.txt || echo "No errors in log"
```

## Internal Algorithm Sequence

The `compset_run_model()` function executes these steps in order:

1. **Depression filling** — Priority-Flood algorithm raises cells in local minima
   to their pour-point elevation. Modifies `dElevation_mean` permanently.
   Original preserved in `dElevation_raw`.

2. **Flow direction** — Steepest descent: for each cell, find the neighbor with
   maximum (elevation_self - elevation_neighbor) / distance. Store in
   `lCellID_downslope_dominant`.

3. **Stream burning** (if enabled) — Override flow directions along known channels.
   Breaching corrects elevation at crossings within `dBreach_threshold` meters.

4. **Flow accumulation** — Iterative topological accumulation from headwaters to
   outlet. Each cell's `dAccumulation` = count of all upstream cells + 1.

5. **Stream grid definition** — Cells with accumulation above threshold (or
   burned-in flag) are marked as stream (`iFlag_stream = 1`).

6. **Watershed boundary** — Trace upstream from outlets to mark all contributing
   cells with `lWatershed` ID.

7. **Confluence detection** — Cells with >1 upstream stream cell are confluences.

8. **Segment definition** — Stream reaches between confluences become segments.

9. **Stream topology** — Establish downstream connections between segments.

10. **Stream order** — Assign Strahler order to each segment.

11. **Subbasin definition** — Delineate hillslopes and subbasins per segment.

12. **Watershed characteristics** — Compute area, slope, length, drainage density,
    TWI, and travel distances.

## Traps

### TRAP: Depression filling changes elevation (dt_001)
After depression filling, `dElevation_mean` will differ from `dElevation_raw` in
depression areas. If you compare output elevations to your input DEM and find
differences, this is expected behavior, not an error.

### TRAP: Zero output files with exit code 0
The most common cause: the outlet cell ID in the basin config doesn't match any
mesh cell. The model completes successfully but produces no watershed because it
cannot find the starting point. Check `lCellID_outlet` values.

### TRAP: Topology mode without topology data (dt_018)
If `iFlag_stream_burning_topology = 1` but no topological flowline file is provided,
the model will fall back to elevation-based routing, silently ignoring the flag.
The results will differ from expectations without any error message.

### TRAP: Very large meshes
For meshes >500K cells, ensure sufficient RAM. The O(n²) neighbor search in some
algorithms can be slow. Consider using OpenMP-compiled binary for parallel speedup.

## Example

```bash
# Minimal run without stream burning
./hexwatershed /data/config_simple.json

# Full run with stream burning and hillslopes
python run_hexwatershed.py \
    --binary ./build/hexwatershed \
    --mesh-type hexagon \
    --mesh-input /data/mesh \
    --output-dir /data/output \
    --basins-file /data/basins.json \
    --stream-grid-option 1 \
    --stream-burning-topology 1 \
    --hillslope 1 \
    --breach-threshold 0.1
```
