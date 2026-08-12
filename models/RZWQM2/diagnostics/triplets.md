# RZWQM2 — Diagnostic Triplets

Structured error knowledge: symptom → diagnosis → remedy.
Consult this file FIRST when RZWQM2 misbehaves.

---

### dt_001 — ipnames.dat Windows path resolution

**Symptom**: RZWQM2 crashes immediately on startup, or creates empty files named like `C:\RZWQM2\projects\...` in the working directory instead of reading the intended input files. Fortran runtime error on OPEN statement.

**Diagnosis**: ipnames.dat contains Windows paths (`C:\...`) but the model is running on Linux. The Fortran OPEN statement interprets backslash-containing strings as literal filenames rather than directory separators. RZWQM2 reads the first 8 lines of ipnames.dat to locate cntrl.dat, rzwqm.dat, rzinit.dat, plgen.dat, the .met file, .brk file, .ana output, and the chemistry file.

**Remedy**: Run `update_ipnames_paths`. Replace all Windows paths with relative Linux paths (`./file.dat`). Verify with `head -8 ipnames.dat` — should show `./cntrl.dat`, `./rzwqm.dat`, `./rzinit.dat`, etc.

---

### dt_002 — RZX database path resolution (DSSAT segfault)

**Symptom**: Segfault during DSSAT crop model initialization — `forrtl: severe (174): SIGSEGV`. Stdout shows `INITIAL VALUES READ IN` as the last message before crash.

**Diagnosis**: .RZX files (MZDSSAT.RZX, SBDSSAT.RZX, WHDSSAT.RZX) contain Windows paths for the DSSAT database directory (`C:\RZWQM2\DATABASES\DSSAT\`) and the project directory. Line 68 of each .RZX file specifies the DSSAT database directory, and line 69 specifies the project directory. The DSSAT module fails to open .CUL, .SPE, and .ECO files, leading to uninitialized pointers and a segfault.

**Remedy**: Run `update_rzx_paths`. Replace line 68 with `DSSAT/` and line 69 with `./` in all .RZX files. Verify the DSSAT/ directory exists and contains the required database files.

---

### dt_003 — Tmin > Tmax in met file

**Symptom**: Model runs but produces unrealistic evapotranspiration, plant growth, or soil temperature values. No error message. ET values are negative or implausibly high, plant growth shows anomalous jumps.

**Diagnosis**: Source weather data has Tmin > Tmax for some days — common with station data around midnight observation times or sensor malfunctions. RZWQM2 does not validate that Tmin <= Tmax. The Penman-Monteith ET calculation receives incorrect vapor pressure deficit, and the soil heat balance uses inverted temperature gradients.

**Remedy**: Run `met_quality_check`. It identifies all days where Tmin > Tmax and swaps the values. Always run met_quality_check before simulation.

---

### dt_004 — BRK precipitation unit mismatch (mm vs inches)

**Symptom**: Model runs to completion but greatly overestimates soil moisture and drainage. Precipitation appears approximately 25x too high. Soil is perpetually saturated.

**Diagnosis**: The .brk file uses INCHES as its precipitation unit, but the .met file uses mm. A rainy day with 25.4 mm should become 1.0 inch in the .brk file. Without the conversion, 25.4 is treated as 25.4 inches (645 mm), inflating precipitation by 25.4x.

**Remedy**: Regenerate the .brk file using `create_breakpoint_file`, which divides mm values by 25.4 automatically. Spot-check: a 25.4 mm day should show ~1.0 in the .brk.

---

### dt_005 — Soil horizon count mismatch

**Symptom**: Model reports `things went wrong when adjusting the calibration input` or crashes with a segfault during soil property reading.

**Diagnosis**: The number of horizons declared in the soil depth section of RZWQM.dat does not match the number of entries in the hydraulic, physical, micropore, or macropore property sections. The hydraulic section must have exactly 3*N lines (3 lines per horizon). If any section has a different count, the Fortran READ statements read past the section boundary into the next section, corrupting all subsequent values.

**Remedy**: Regenerate all soil sections using `write_soil_properties` with a consistent horizon count. Never edit individual soil sections by hand.

---

### dt_006 — DSSAT segfault during crop init (multiple causes)

**Symptom**: `forrtl: severe (174): SIGSEGV` immediately after `INITIAL VALUES READ IN`.

**Diagnosis**: Multiple possible causes: (1) RZX paths are wrong (see dt_002), (2) DSSAT .CUL/.SPE/.ECO files are missing from the DSSAT/ directory, (3) the crop cultivar ID specified in plgen.dat does not match any entry in the corresponding .CUL file. The DSSAT module uses uninitialized memory for crop parameters, leading to a segfault.

**Remedy**: Investigate in order: (1) Check all .RZX paths with `update_rzx_paths`, (2) verify DSSAT/ contains all 29 crop model files, (3) verify the cultivar ID in plgen.dat matches an entry in the corresponding .CUL file.

---

### dt_007 — AVX2 instruction crash on ARM

**Symptom**: Segfault after partial initialization. Under strace, the process shows repeated x32/64-bit mode switching. Running on ARM Mac via Docker with Rosetta translation.

**Diagnosis**: The Linux binary (main_ryzen) was compiled for x86-64-v3 (AVX2 instruction set). Running on ARM Mac via Docker/Rosetta cannot emulate AVX2 instructions. Rosetta translates basic x86-64 but fails on advanced SIMD extensions (VFMADD, VPERM, etc.).

**Remedy**: Use native x86-64 hardware with AVX2 support: x86 Linux with Intel/AMD CPU, or cloud VMs (AWS c5/c6i). Verify with `grep avx2 /proc/cpuinfo`.

---

### dt_008 — Wrong soil texture classification (trailing space bug)

**Symptom**: Model produces biased soil moisture or ET. No error. Results look plausible but systematically deviate from observations. Hydraulic parameters seem wrong for the known soil type.

**Diagnosis**: The `soil_texture_setter()` function has a known edge case: the "silty clay loam" key in `default_setter` has a trailing space (`"silty clay loam "`). If the texture is computed as `"silty clay loam"` (no trailing space), the dictionary lookup fails silently and incorrect default parameters are used.

**Remedy**: Use the `soil_texture_classification` tool which strips whitespace and normalizes the string. Verify the texture class string matches exactly what `soil_default_setter()` expects, character-for-character.

---

### dt_009 — Lat/lon in degrees instead of radians

**Symptom**: Wildly incorrect solar radiation calculations, wrong day length, incorrect ET. The model runs without any error. ET is drastically wrong (too high in winter, too low in summer).

**Diagnosis**: RZWQM.dat grid general properties expect latitude and longitude in RADIANS. At 45 degrees latitude, entering 45.0 instead of 0.785 gives completely wrong solar geometry. sin(45.0 radians) wraps around multiple times, producing meaningless solar angles.

**Remedy**: Convert degrees to radians: `lat_rad = lat_deg * pi / 180`. Verify latitude is between -1.57 and 1.57 and longitude is between -3.14 and 3.14. Any value outside this range indicates degrees were used.

---

### dt_010 — Tile drainage unit error (cm vs mm)

**Symptom**: Tile drainage values appear approximately 10x too low compared to field observations. All other outputs look reasonable. Bias is systematic and exactly ~10x.

**Diagnosis**: The .ana output file reports tile drainage in centimeters. To compare with observations (typically in mm), values must be multiplied by 10. The `parse_ana_output` tool applies the x10 conversion automatically, but manual parsing may miss this.

**Remedy**: Use `parse_ana_output` which applies the x10 conversion for tile_drainage automatically. If parsing manually, multiply column 10 values by 10 to convert from cm to mm.

---

### dt_011 — Node discretization failure (too many layers)

**Symptom**: `nlayer_gen` returns False. Error: `The numerical layering scheme generated TOO MANY layers`. Node count exceeds MAXNOD (300).

**Diagnosis**: Soil horizons are either too close together (very thin layers <5 cm) or the total soil depth exceeds 3000 cm. The half-way rule algorithm cannot fit node boundaries to horizon boundaries within the maximum node count.

**Remedy**: Merge very thin horizons (<5 cm) into adjacent horizons. Reduce maximum soil depth to <=3000 cm. The `generate_nodes` tool will automatically adjust depths slightly if possible.

---

### dt_012 — Linux interpreter path not found (ComputeCanada binary)

**Symptom**: `bash: ./main_ryzen: No such file or directory` — even though the file exists with executable permissions and `file` confirms it is an ELF 64-bit executable.

**Diagnosis**: The binary has a hardcoded ELF interpreter path from ComputeCanada: `/cvmfs/soft.computecanada.ca/.../ld-linux-x86-64.so.2` which does not exist on non-ComputeCanada systems. The kernel cannot find the dynamic linker to start the process.

**Remedy**: `patchelf --set-interpreter /lib64/ld-linux-x86-64.so.2 main_ryzen`. Verify with `readelf -l main_ryzen | grep interpreter` — should show the standard Linux path.

---

### dt_013 — Linux filename case mismatch

**Symptom**: FileNotFoundError for files that clearly exist in the scenario directory. Commonly affects RZWQM.dat/rzwqm.dat, RZINIT.dat/rzinit.dat, IPNAMES.DAT/ipnames.dat.

**Diagnosis**: RZWQM2 was developed on Windows (case-insensitive). The codebase has mixed case conventions: template files use lowercase but some tools reference uppercase. On Linux (case-sensitive), these are different files.

**Remedy**: The RZWQM class constructor uses `_resolve_case()` to try both cases. The `update_ipnames_paths` tool detects actual filenames before writing. When creating new scenarios on Linux, use consistent lowercase for .dat files.

---

### dt_014 — Non-zero E-pan/PAR in .met overrides ET calculation

**Symptom**: Crop dies of water stress despite adequate soil moisture. Root water uptake (PotRWUP) drops to zero during growing season. Yield is 0 or near-zero. Stored soil water remains high (>70 cm) but ActualET is a small fraction of PotentialET.

**Diagnosis**: The .met file has non-zero values in column 7 (E-pan) and column 9 (PAR). When non-zero, RZWQM2 uses them directly instead of computing ET internally via Penman-Monteith. Estimated E-pan/PAR values from forcing data adapters override the model's water balance calculation.

**Remedy**: Set E-pan (column 7) and PAR (column 9) to 0 in all .met files. The `generate_met_file` tool now hardcodes these to 0. Never write estimated E-pan or PAR values — always let RZWQM2 compute them.

---

### dt_021 — update_crop_selection allows empty cultivar_id

**Symptom**: rzwqm.dat has `7000  maize` with no cultivar ID. The model selects wrong default cultivar (e.g., AC0001 TOHONO O'odham for maize). Yield and phenology are wildly wrong for the target region.

**Diagnosis**: The cultivar_id and cultivar_desc parameters were optional with no default. When omitted, the tool wrote a crop line with no cultivar specification, causing the DSSAT module to fall back to the first entry in the .CUL file — typically inappropriate for the target region.

**Remedy**: Added a DEFAULT_CULTIVARS dictionary with sensible defaults per crop code. Verify rzwqm.dat has a full crop line like `7000  maize IB1068 DEKALB 521`.

---

### dt_022 — update_cultivar only updates DSSAT/ subdirectory CUL file

**Symptom**: Cultivar override has no effect on the simulation. The model continues to use original cultivar parameters despite the update.

**Diagnosis**: The `update_cultivar` tool only wrote to the .CUL file in the DSSAT/ subdirectory. However, RZWQM2 reads .CUL files from both the root scenario directory and DSSAT/, depending on configuration. If the root copy is not updated, it may be read instead.

**Remedy**: The tool now discovers and updates BOTH DSSAT/ and root directory .CUL files. Verify with grep for the cultivar ID in both locations.

---

### dt_023 — ECO# column off-by-one in Fortran fixed-width format

**Symptom**: `MZPHEN Error number 7` — the DSSAT crop model cannot look up the ecotype (ECO#) for the specified cultivar.

**Diagnosis**: VRNAME was padded to 16 characters (`.ljust(16)`) but the Fortran fixed-width format requires 17 characters (16 for the name + 1 separator space). This shifted ECO# to position 23 instead of the required position 24.

**Remedy**: Changed `.ljust(16)` to `.ljust(17)` for VRNAME padding. Verify ECO# starts at position 24 (0-indexed) in the generated CUL line.

---

### dt_024 — _convert_to_040() is maize-only — crashes for wheat/soybean

**Symptom**: Wheat gets an 8-parameter CUL line (wrong format), soybean gets a 6-parameter line (wrong format). DSSAT parser error or segfault for non-maize crops.

**Diagnosis**: The `_convert_to_040()` function used a hardcoded maize format: 6 parameters plus Height and Biomass. Wheat (WHCER040) needs 7 parameters and soybean (SBGRO040) needs 15 parameters, each with crop-specific format specifiers.

**Remedy**: Made `_convert_to_040()` crop-aware with a CROP_FORMAT_040 dictionary. Maize=8 (6+2), wheat=7, soybean=15 parameters.

---

### dt_025 — _read_china_cul() regex only matches IB#### ECO codes

**Symptom**: Soybean cultivars (SB0001 etc.) are not parsed from the China CUL library. Tool reports no matching cultivars for soybean. Maize and wheat parse correctly.

**Diagnosis**: The regex pattern `r'(IB\d{4}|DFAULT)'` only matches ECO codes starting with "IB" (maize and wheat). Soybean uses "SB" prefix ECO codes (e.g., SB0001), which are rejected.

**Remedy**: Changed regex to `r'([A-Z]{2}\d{4}|DFAULT)'` — matches any 2-letter + 4-digit ECO code pattern, covering all DSSAT crop model conventions. Do not hardcode crop-specific prefixes in shared parsing logic.

---

### dt_026 — CROP_FORMAT_040['soybean'] had wrong param count (6 vs 15)

**Symptom**: Soybean CUL line is truncated at 6 parameters. DSSAT fails to parse — expects 15 for SBGRO040. Bengbu soybean test yields 0.

**Diagnosis**: The CROP_FORMAT_040 dictionary entry for 'soybean' was a placeholder copied from the maize definition with param_count=6. SBGRO040 actually requires 15 parameters per cultivar line.

**Remedy**: Updated CROP_FORMAT_040['soybean'] to param_count=15 with correct format specifiers. Bengbu test case should produce ~1345 kg/ha.

---

### dt_027 — Cultivar ID falls in a numbering gap

**Symptom**: `update_cultivar.py` exits with INPUT_ERROR when given a cultivar ID in a reserved-but-empty numeric range (e.g., CN0005-CN0010, CN0020, CN0106-CN0110). The China CUL files use non-contiguous numbering.

**Diagnosis**: The China cultivar library uses block numbering with intentional gaps reserved for future entries. Any code that interpolates or generates IDs within a block (e.g., lat-interpolation giving CN0005) produces a valid-looking but non-existent ID. The lookup hits `sys.exit(1)` with no fallback.

**Remedy**: Added `_find_closest_cultivar()` — computes numeric distance from every existing ID with the same prefix and snaps to the closest one. A `[WARNING]` is printed. Always use IDs from the explicit existence table in the China CUL README, or use lat-based auto-selection.

---

### dt_028 — rzwqm_file.py encoding mismatch bloats file 3x per write

**Symptom**: rzwqm.dat grows from ~170KB to 500KB+ after modify+write cycle. Box-drawing characters in separator lines triple in size. Tile drainage output may drop to zero.

**Diagnosis**: The `dat_data` property reads RZWQM.dat with `encoding='ISO-8859-1'`, but all 13 write functions (`open(..., 'w')`) default to UTF-8. Multi-byte re-encoding on each read-modify-write cycle causes ISO-8859-1 single-byte box-drawing characters (bytes 0xB3, 0xC4) to become 2-byte UTF-8 sequences, growing exponentially per cycle. After 2-3 cycles, separator lines are corrupted enough that the Fortran parser misreads section boundaries.

**Remedy**: Changed all 13 `open(self.dat_path, 'w')` calls to `open(self.dat_path, 'w', encoding='ISO-8859-1')`. File size should stay within ~1KB of original after a write cycle. Never use default Python open() encoding (UTF-8) for RZWQM2 data files.

---

### dt_029 — Maize PLANTSUM.OUT missing despite successful harvest

**Symptom**: After a successful maize run, PLANTSUM.OUT is empty or missing — even though MANAGE.OUT shows valid harvest yields (5,000-10,000 kg/ha) and the .ana file has correct daily grain_yield (col 44).

**Diagnosis**: The DSSAT crop module within RZWQM2 occasionally fails to write the summary output file for maize. This appears to be a DSSAT-RZWQM2 interface issue where the summary trigger is not fired when harvest is triggered by date (option 3) rather than growth stage (option 1).

**Remedy**: Use `parse_ana_output.py` as the PRIMARY extraction method for ALL RZWQM2 outputs, including crop yields. The .ana file is the authoritative output containing all 139 daily variables including grain_yield (col 44), biomass_above (col 41), and LAI (col 43). Do NOT rely on PLANTSUM.OUT.

---

### dt_030 — Agent context overflow during RZWQM2 basin setup

**Symptom**: An LLM agent attempting to set up RZWQM2 crashes or returns internal error before completing all pipeline stages. Agent completes S0-S4 but never reaches S7-S8.

**Diagnosis**: The RZWQM2 KI is the largest in HydroCraft (36 tools, 58 KB YAML, 14 stages). An agent reading the full KI plus manipulating large config files (rzwqm.dat ~170 KB) will exceed typical LLM context limits (~100-200K tokens) before the pipeline completes.

**Remedy**: Use `mass_project_generator.py` for batch site setup. It handles all 10 stages internally in a single Python script without requiring agent intervention between stages. Provide a sites CSV and the generator builds all scenarios automatically.

---

### dt_031 — Soil type label shows Ohio template name (cosmetic)

**Symptom**: RZWQM.OUT soil section shows "Rago Loam" or "Rayne Silt Loam" (Ohio template soil names) instead of the actual HWSD soil type, even though numerical soil properties (sand%, silt%, clay%) are correctly set from HWSD data.

**Diagnosis**: `initialize_scenario.py` copies the entire Ohio template directory including soil type name strings. `write_soil_properties.py` updates numerical values but does NOT update the SOIL TYPE label. The label is cosmetic — the model uses numerical values for all computations.

**Remedy**: Verify actual soil properties match HWSD for your target region. The label does not affect results. To fix, manually edit the SOIL TYPE string or update `write_soil_properties.py` to overwrite using the USDA texture class.

---

### dt_032 — Crop selection change doesn't update planting references

**Symptom**: RZWQM2 crashes with `File: SBGRO040.CUL not found` or `MZCER040.CUL not found` after crop selection change.

**Diagnosis**: `update_crop_selection.py` updated the crop definition (line ~488 in rzwqm.dat) but did NOT update the planting schedule plant reference numbers. The planting lines still reference the old crop (e.g., plant_ref=2 for soybean), so RZWQM2 tries to plant the wrong crop and looks for the wrong .CUL file.

**Remedy**: Fixed in `update_crop_selection.py` (2026-04-10): now also calls `_update_planting_references()` to rewrite all planting schedule entries to use the correct plant reference (1=maize, 2=soybean, 3=wheat). Verify with: `grep '^[123]  ' rzwqm.dat`.

---

### dt_033 — RZX comment line replaced instead of database path

**Symptom**: `forrtl: severe (59): list-directed I/O syntax error, unit 69, file MZDSSAT.RZX`.

**Diagnosis**: `update_rzx_paths.py` or `initialize_scenario.py` corrupted the .RZX file by replacing a comment line containing "DSSAT" (e.g., `==  RZWQM-DSSAT CONTROL FILE`) instead of the actual database path lines at positions 68-69.

**Remedy**: Fixed in both tools (2026-04-10): now uses the `DATABASE FILE LOCATIONS` section marker to find the correct path lines, skipping comments. Both path lines must be relative: `DSSAT/` and `./`.

---

### dt_034 — initialize_scenario.py creates scenario inside template directory

**Symptom**: `initialize_scenario.py` creates the new scenario inside the template directory instead of a separate output location. Template directory gets polluted.

**Diagnosis**: The tool only had PROJECT_PATH (which defaults to the canonical template), so new scenarios were created as siblings of the template scenario.

**Remedy**: Fixed (2026-04-10): Added OUTPUT_DIR parameter (6th CLI argument). When set, the tool creates a self-contained project at OUTPUT_DIR with proper structure (scenario/, Meteorology/, Analysis/), IPNAMES.DAT paths pointing to the new location, and relative RZX paths. Usage: `initialize_scenario.py <template_root> <template_name> <new_name> <start> <end> <output_dir>`.
