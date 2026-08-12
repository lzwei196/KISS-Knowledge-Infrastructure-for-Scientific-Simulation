# Lohmann_Routing — Diagnostic Triplets

Structured error knowledge: symptom → diagnosis → remedy.
Consult this file FIRST when the Lohmann routing model misbehaves.

---

### dt_001 — Disconnected flow direction network

**Symptom**: Routing model runs but no output files generated, or only a few cells are processed.

**Diagnosis**: When aggregating high-resolution DEM flow directions to coarse VIC grid, the network may become disconnected. Some cells have no valid downstream neighbor, so flow cannot reach the outlet.

**Remedy**: Use the `run_build_routing_new.py` script's "calculate first, fix later" algorithm to ensure all cells reach the outlet. The script detects disconnected cells and reroutes them to the nearest connected neighbor.

---

### dt_002 — Incorrect staloc file format

**Symptom**: No output when running routing. Model exits immediately.

**Diagnosis**: The staloc file must contain exactly two lines. Line 1: `1 XX column row -9999` (station definition). Line 2: the UH_S file path, or `NONE` to recalculate. If the format is wrong, the routing binary cannot parse the station location.

**Remedy**: Ensure staloc file has two lines:
```
1 XX column row -9999
NONE
```
The second line is the UH_S file path; `NONE` means recalculate the unit hydrograph.

---

### dt_003 — Incorrect UH.all file format

**Symptom**: `End of file` error during runtime. Error reading UH.all.

**Diagnosis**: UH.all must be in 12-line format, each line containing an index (0-11) and a weight value. The weights must sum to 1.0. If the file has fewer than 12 lines or uses a different format, the Fortran READ statement fails.

**Remedy**: Use the correct 12-line unit hydrograph format:
```
   0   0.15
   1   0.40
   2   0.25
   ...
   11  0.0
```

---

### dt_004 — Insufficient model dimensions (NROW/NCOL)

**Symptom**: Error `Incorrect dimensions: Reset nrow and ncol in main to X Y`.

**Diagnosis**: NROW and NCOL parameters in the routing model source code (`rout.f`) are smaller than the actual grid size of the basin. The Fortran arrays are statically allocated and cannot exceed these dimensions.

**Remedy**: Modify `/path/to/route_1.0/src/rout.f`:
```fortran
PARAMETER (NROW = 100, NCOL = 100)  ! Adjust as needed
```
Then recompile: `make clean && make`.

---

### dt_005 — Extremely large or negative discharge values

**Symptom**: Monthly discharge reaches tens of thousands m3/s, or large negative discharge values appear.

**Diagnosis**: The routing model reads incorrect columns from VIC output. VIC output files have many columns, and the preprocessing script must extract the correct ones (columns 0, 1, 2, 3, 18, 16, 17 from the VIC output, skipping the first 3 rows).

**Remedy**: Use the preprocessing script (`preprocess_vic_for_routing.py`) to extract the correct columns from VIC output. Verify discharge magnitudes are physically reasonable for the basin area.

---

### dt_006 — Fortran path length limit (60-80 characters)

**Symptom**: Files exist but reported as `NOT FOUND`. Output is all 0 or NaN.

**Diagnosis**: Fortran string length is limited to 60-80 characters. Absolute paths longer than this get truncated, causing the routing binary to open wrong or nonexistent files without a clear error message.

**Remedy**: Create symbolic links and use relative paths:
```bash
cd /path/to/routing_config/
ln -sf /long/path/to/vic_for_routing vic_in
```
Or work from a short-path directory like `/tmp/rout_work`.

---

### dt_007 — Coordinate system mismatch (grid vs VIC filenames)

**Symptom**: Many `XX.XXXX_YYY.YYYY NOT FOUND, INSERTING ZEROS` messages. Output discharge is all zero.

**Diagnosis**: Grid coordinates in auxiliary files (xmask, fdir) don't match VIC output filenames. The routing model constructs expected filenames from the grid coordinates, and if `xllcorner`/`yllcorner` are set incorrectly, the computed filenames won't match any existing VIC output files.

**Remedy**: Verify coordinates match:
```bash
ls vic_for_routing/ | head -5    # Check VIC file coordinates
head -6 XX_xmask.txt             # Check xmask coordinate definition
```
Ensure xllcorner and yllcorner are set correctly so grid center coordinates match VIC filenames.

---

### dt_008 — Self-referencing symlink in routing_param (infinite recursion)

**Symptom**: `shutil.copytree` error `Too many levels of symbolic links`. Directory structure shows `routing_param/routing_param/routing_param/...` infinite nesting.

**Diagnosis**: A symbolic link named `routing_param` was created INSIDE the `routing_param/` directory, pointing back to the `routing_param/` directory itself. This creates an infinite recursion loop. This typically happens when incorrectly handling the Fortran path length limitation (dt_006).

**Remedy**: NEVER create a symlink named `routing_param` inside the `routing_param/` directory. Correct approaches:
```bash
# Correct: Create symlink to routing_param from OUTSIDE (e.g., /tmp)
ln -sf /long/path/to/routing_param /tmp/rout_work
cd /tmp/rout_work && ./rout_exe rout_global.txt

# Correct: Inside routing_param, only create symlinks to OTHER directories
cd routing_param/
ln -sf /path/to/vic_for_routing vic_in          # OK
ln -sf /path/to/route_1.0/src/rout rout_exe     # OK
```
KEY RULE: Symlinks inside `routing_param/` must NEVER point back to `routing_param/` itself.

---

### dt_009 — UH_S file already exists

**Symptom**: Error `Cannot open file 'XX .uh_s': File exists`.

**Diagnosis**: The routing model tries to create a `.uh_s` file but one already exists from a previous run. The Fortran OPEN statement with STATUS='NEW' fails if the file already exists.

**Remedy**: Delete existing `.uh_s` files before re-running: `rm -f "XX   .uh_s"`. Note the possible extra spaces in the filename.
