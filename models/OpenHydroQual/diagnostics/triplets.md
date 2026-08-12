# OpenHydroQual — Diagnostic Triplets

Structured error knowledge: symptom → diagnosis → remedy.
Consult this file FIRST when OpenHydroQual misbehaves.

---

### dt_001 — Template path points to non-existent location

**Symptom**: Model crashes immediately with no output or cryptic JSON parse error — `Cannot open file`, `JSON parse error`, `template...not found`.

**Diagnosis**: OHQ example files contain hardcoded absolute paths from the developer's machine (e.g., `/home/arash/Projects/QAquifolium/...`). When run on a different system, these paths do not exist and template loading fails. The binary also resolves the default template path relative to its own location at `../../../resources/`, which may not exist if the binary was moved.

**Remedy**: Replace template paths with local absolute paths. Open the .ohq file, find all `loadtemplate` and `addtemplate` lines, and replace paths with the correct local path to `resources/`. Verify each referenced JSON file exists. Use `run_ohq.py --fix-paths` flag when running example files.

---

### dt_002 — Working folder derivation fails with relative path

**Symptom**: Model runs but produces empty `output.txt` (0 bytes).

**Diagnosis**: OHQ derives the working folder from the .ohq input file path using `QFileInfo::canonicalPath()`. If the input file is specified with a relative path that cannot be resolved, the working folder becomes empty and output files are written to an unexpected location or not at all. Time series input files (inflow.txt, loading files) also resolve from the working folder, so they silently fail to load.

**Remedy**: Always use absolute paths for the input .ohq file. Verify time series files exist in the .ohq file directory. Check output file location in stdout.

---

### dt_003 — Missing unit bracket notation on parameter values

**Symptom**: Values appear unreasonable (e.g., storage shows as 357.6 instead of 357.6 m³).

**Diagnosis**: OHQ uses bracket notation to specify units: `Storage=357.6[m~^3]`. When the brackets are omitted (`Storage=357.6`), the value is accepted but may be interpreted in default units which differ from intended. The `~^` notation represents superscript (m³). This is a silent error because the model runs without complaint.

**Remedy**: Add unit brackets to all dimensional values. Review all `create block/link/source` commands. Use OHQ notation: `[m~^3]` for m³, `[m~^2]` for m², `[1/day]` for rates. Include unit brackets on every value as a coding standard.

---

### dt_004 — Semicolon/comma delimiter confusion in .ohq commands

**Symptom**: Some parameters in a `create` command are silently ignored.

**Diagnosis**: In OHQ script syntax, semicolons separate command fields (e.g., `create block; type=Pond, name=myPond`) while commas separate key=value pairs within a field. Using a semicolon where a comma should be causes the parser to treat subsequent text as a new (invalid) command field, silently dropping parameters.

**Remedy**: Use semicolons only between command and type/name fields. Format: `create block;type=X,name=Y,prop1=V1,prop2=V2` — commas between properties. Follow exact syntax from working examples.

---

### dt_005 — Time units in seconds instead of days

**Symptom**: Flow rates or reactions are 86400x too fast or too slow.

**Diagnosis**: OHQ uses DAYS as the internal time unit for everything: simulation time, timestep, reaction rates (1/day), flow rates (m³/day), diffusion coefficients (m²/day). Inputting values in per-second or per-hour units without conversion causes rates to be off by factors of 86400 or 24 respectively. This is the most common unit trap because many external data sources use SI (seconds).

**Remedy**: Convert all rates to per-day: multiply m³/s by 86400 → m³/day; multiply m/s (Ksat) by 86400 → m/day; multiply m²/s (diffusion) by 86400 → m²/day; multiply 1/hr rates by 24 → 1/day.

---

### dt_006 — Concentration in wrong units (mg/m³ or ug/L instead of g/m³)

**Symptom**: Concentrations are 1000x too high, reactions saturate immediately.

**Diagnosis**: OHQ uses g/m³ for all concentrations, which is numerically equal to mg/L. If input data is in ug/L or mg/m³, concentrations are 1000x too high. This causes Monod-type reaction kinetics (X/(X+K)) to saturate at 1.0, making reactions appear zero-order and hiding the effect of half-saturation constants.

**Remedy**: Divide ug/L values by 1000 to get mg/L = g/m³. Verify initial concentrations are in expected range. Check loading files are in g/day not mg/day.

---

### dt_007 — Fixed-head boundary block Storage too small

**Symptom**: Boundary block water level changes during simulation (should be fixed).

**Diagnosis**: Fixed-head boundary blocks must have artificially large Storage values (e.g., 100000 m³) to act as infinite reservoirs. If Storage is small (e.g., 100 m³), the boundary block depletes or fills during simulation, causing the head to change and flow to reverse or stop. The model runs without errors but the boundary condition is violated.

**Remedy**: Set `Storage>=100000[m~^3]` for all fixed_head blocks. Verify head remains constant in output.

---

### dt_008 — Crank-Nicholson weight too low for timestep size

**Symptom**: Solution oscillates wildly or diverges to NaN — `nan`, `inf`, `NaN` in output.

**Diagnosis**: Setting `c_n_weight=0` (fully explicit) or low values like 0.3 with a large `initial_time_step` causes numerical instability. The explicit scheme has a Courant-type stability limit. When violated, solutions oscillate and eventually produce NaN. The default `c_n_weight=1` (fully implicit) is unconditionally stable.

**Remedy**: Set `c_n_weight=1` (fully implicit) for stability. If accuracy is needed, try 0.5 (Crank-Nicholson) with smaller timestep. Reduce `initial_time_step` if oscillations persist. Start with `c_n_weight=1`, only reduce after stability is confirmed.

---

### dt_009 — Solver hangs due to tight NR tolerance

**Symptom**: Solver hangs indefinitely, CPU at 100% but no progress.

**Diagnosis**: If `nr_tolerance` is very small (e.g., 1e-10) and the system is highly nonlinear, the NR solver repeatedly reduces the timestep until it hits `minimum_timestep` but still cannot converge. It then makes tiny progress per step, effectively stalling. The `maximum_number_of_matrix_inversions` limit (default 200000) may take hours to reach.

**Remedy**: Relax `nr_tolerance` to 0.001. Set `minimum_timestep` to 1e-6. Set `maximum_time_allowed` to 3600 (1 hour CPU limit). Use `nr_tolerance=0.001` as default starting point.

---

### dt_010 — Inflow rate in m³/s instead of m³/day

**Symptom**: Pond fills or drains unrealistically fast (hours instead of days).

**Diagnosis**: OHQ expects flow rates in m³/day. If inflow time series data is in m³/s (SI standard), the flow is 86400x too high. A 1 m³/s inflow becomes 86400 m³/day, which will fill a small pond in minutes of simulation time. The model runs without error but produces physically impossible water levels.

**Remedy**: Multiply m³/s values by 86400 to get m³/day. Verify inflow magnitude is reasonable for the system.

---

### dt_011 — Hydraulic conductivity in m/s instead of m/day

**Symptom**: Groundwater drains completely or water table drops to aquifer bottom.

**Diagnosis**: OHQ expects hydraulic conductivity in m/day. A typical sand aquifer has Ksat around 1e-4 m/s = 8.64 m/day. If the m/s value (1e-4) is entered directly, it becomes 1e-4 m/day, which is extremely low (clay). Conversely, entering a literature value of 8.64 m/day as m/s gives 746496 m/day, causing instant drainage.

**Remedy**: Convert Ksat to m/day: `K_day = K_sec * 86400`. Verify: sand ~1–10 m/day, clay ~0.001 m/day.

---

### dt_012 — Solar radiation in MJ/m²/day instead of W/m²

**Symptom**: ET is unrealistically high (>50 mm/day) or low, or model shows excessive water loss.

**Diagnosis**: OHQ Penman ET model expects solar radiation in W/m². ERA5 and many datasets provide daily totals in MJ/m²/day. The conversion factor is 1 MJ/m²/day = 10⁶/86400 W/m² = 11.57 W/m². Using MJ/m²/day directly gives values ~11.6x too low, resulting in underestimated ET.

**Remedy**: Convert MJ/m²/day to W/m² by multiplying by 11.57. Verify: clear-sky noon peak ~800–1000 W/m².

---

### dt_013 — Negative concentrations from numerical undershoot

**Symptom**: Negative concentrations appear in output.

**Diagnosis**: When reaction rates are fast relative to the timestep and `c_n_weight` is less than 1, the solver can produce small negative concentrations. This violates mass conservation and can cascade to produce NaN values if the negative concentration enters a log or sqrt in a reaction expression. OHQ does not enforce non-negativity constraints.

**Remedy**: Use `c_n_weight=1` and reduce `initial_time_step` to 0.0001. If persists, reduce reaction rates or increase half-saturation constants. Always use fully implicit scheme for reactive transport.

---

### dt_014 — Relative humidity as percentage instead of fraction

**Symptom**: ET is unrealistically high (>50 mm/day) or model shows excessive water loss.

**Diagnosis**: OHQ Penman ET calculation expects relative humidity as a fraction (0–1). If provided as percentage (0–100), the vapor pressure deficit calculation produces extremely large values, causing ET to be grossly overestimated. The model runs without error.

**Remedy**: Divide RH by 100 to convert from % to fraction. Verify: typical RH is 0.3–0.9 as fraction.

---

### dt_015 — Missing runtime shared libraries

**Symptom**: Binary fails to start with shared library errors — `libOHQLib.so...not found`, `libQt6Core.so...not found`, `libgsl.so...not found`.

**Diagnosis**: OHQLibTest requires libOHQLib.so, Qt6Core, GSL, LAPACK, BLAS, and Armadillo shared libraries at runtime. If any are not in `LD_LIBRARY_PATH`, the binary fails immediately. This is common when running from a different directory than the build folder.

**Remedy**: `export LD_LIBRARY_PATH=/path/to/OHQLib/build:$LD_LIBRARY_PATH`. Or: `sudo ldconfig` after installing libraries. Verify: `ldd OHQLibTest` (no "not found" lines). Add `LD_LIBRARY_PATH` export to shell profile.

---

### dt_016 — OHQ spells "weir" as "wier" in templates

**Symptom**: Weir block type not found, model reports unknown type — `type...not found`, `unknown...type...weir`.

**Diagnosis**: The standard English spelling is "weir" but OHQ uses "wier" in its `main_components.json` template. Using "weir" instead of "wier" causes a type lookup failure. This is a known quirk of the codebase.

**Remedy**: Use `wier` (OHQ spelling) instead of `weir` in all `create link` commands. Verify available types by checking `main_components.json`. Always reference type names from the loaded templates.

---

### dt_017 — Reaction parameter base_value set to 0

**Symptom**: Reaction does not affect constituent concentrations.

**Diagnosis**: In the .ohq examples, reaction parameters are created with `base_value=0` as placeholders. If these are not updated with actual kinetic constants, the reaction rate expression evaluates to zero and no reaction occurs. The model runs normally but constituent concentrations remain unchanged.

**Remedy**: Set non-zero `base_value` for all reaction parameters. Typical values: mu_H=6.0, K_s=20, K_o=0.2, mu_N=0.8. Never leave `base_value=0` unless intentionally disabling a reaction.

---

### dt_018 — Diffusion coefficient in m²/s instead of m²/day

**Symptom**: Diffusion appears too fast or too slow by factor of 86400.

**Diagnosis**: OHQ expects diffusion coefficients in m²/day. Literature values are typically in m²/s (e.g., molecular diffusion ~1e-9 m²/s). Converting: 1e-9 m²/s × 86400 = 8.64e-5 m²/day. The example files use 0.0017 m²/day which includes turbulent mixing. Using m²/s values directly gives negligible diffusion.

**Remedy**: Multiply m²/s values by 86400 to get m²/day. Typical OHQ range: 0.0001–0.01 m²/day (includes turbulent). Use representative values from OHQ examples as reference.
