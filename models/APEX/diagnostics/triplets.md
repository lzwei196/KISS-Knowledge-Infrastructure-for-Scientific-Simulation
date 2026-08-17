# APEX 1501 — Diagnostic Triplets

Structured error knowledge: symptom → diagnosis → remedy.
Consult this file FIRST when apex1501 misbehaves.

---

### file_missing_uppercase — Case-sensitive filename mismatch

**Symptom**: `File ... IS MISSING`

**Diagnosis**: apex1501 reads filenames literally from APEXFILE.DAT and *LIST.DAT. On Linux the filesystem is case-sensitive, so SITE01.SIT (uppercase) and SITE01.sit (lowercase) are different files. APEX silently exits 0 after this error.

**Remedy**: Rename all per-subarea files on disk to UPPERCASE extensions (.SIT, .SUB, .SOL, .OPC/.MGT, .WP1, .WND, .DLY) and verify the *LIST.DAT entries match exactly.

---

### lwe_dat_missing — LWE.DAT entry missing from APEXFILE.DAT

**Symptom**: `forrtl: severe (24): end-of-file during read, unit 22`

**Diagnosis**: Pre-1501 APEXFILE.DAT lacks the `FLWE LWE.DAT` line. The 1501 binary requires an LWE.DAT entry (for the Long-term Water-Erosion module), and EOFs at unit 22 (APEXFILE) when it's missing.

**Remedy**: Append a line `FLWE     LWE.DAT` to APEXFILE.DAT and `touch LWE.DAT` in the workspace. The example dataset already ships with both.

---

### sub_too_short — SUB file has fewer than 22 lines

**Symptom**: `MAIN_1501.f90:2858`

**Diagnosis**: apex1501 reads beyond the 12 documented lines of *.SUB and EOFs if the file has fewer than 22 lines.

**Remedy**: Pad the *.SUB file with rows of `0.00` until it has 22 lines. The shipped SUBA01.SUB template already has the required padding.

---

### weather_units_srad — Solar radiation in wrong units

**Symptom**: ET implausibly low, or WYLD too high

**Diagnosis**: SRAD provided in W/m² instead of MJ/m²/day. APEX expects MJ/m²/day. A typical mid-latitude daily value is 10–25 MJ/m²/day, NOT 200–300.

**Remedy**: Multiply W/m² by 0.0864 to get MJ/m²/day. `s2_convert_forcing.py` already applies this conversion when reading from CMFD/MSWX/POWER.

---

### zero_exit_silent_crash — Silent failure with exit code 0

**Symptom**: Exit code 0 but RUN1501.SUM missing or empty

**Diagnosis**: apex1501 returns 0 even on Fortran severe errors. Never trust the exit code; always check that RUN1501.SUM was written and look at EPICERR.DAT for the real diagnostic.

**Remedy**: `s6_run_apex.py` already verifies RUN1501.SUM exists and is non-empty after every invocation, and surfaces EPICERR.DAT in the exception message.

---

### ngn_weather_mismatch — Weather generator overrides forcing file

**Symptom**: Weather generator spinning random sequence

**Diagnosis**: NGN in APEXCONT.DAT controls which weather variables are GENERATED (digits 1=PRCP, 2=TMAX, 3=TMIN, 4=SRAD, 5=WIND, 6=RH). If a digit lists a variable but that column is also populated in *.DLY, APEX may use the generator and ignore the file.

**Remedy**: To read all variables from *.DLY, set `NGN=0` in APEXCONT.DAT. To use the validated default of `NGN=2345` (generate srad/temps/wind), leave the corresponding *.DLY columns blank.

---

### hwsd_lookup_failed — HWSD soil raster lookup failure

**Symptom**: `HWSD raster lookup failed`

**Diagnosis**: Either the HWSD raster path is wrong, the lat/lon falls outside the raster bounds, or rasterio is not installed in the active environment.

**Remedy**: Verify HWSD raster path with `ls KISSPATH_DATA`, ensure -180<=lon<=180 and -60<=lat<=85, and `pip install rasterio` if missing. `lookup_hwsd` falls back to texture defaults so soil build will still proceed but with imprecise numbers.
