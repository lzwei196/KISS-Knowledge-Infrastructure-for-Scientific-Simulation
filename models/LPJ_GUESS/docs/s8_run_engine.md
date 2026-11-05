# Stage 8 (real engine): run LPJ-GUESS 4.1.1

**Purpose.** Run the compiled engine `KISSPATH_HOME/engine_builds_20261006/LPJ_GUESS/build/guess`
headless with honest exit codes. (`tools/run_lpjguess.py` is the SURROGATE — do not use it for results.)

**Inputs.** `example`: nothing (shipped demo data). `cf`: `forcing_meta.json`, CO2 file,
optional soil file / fire model / spin-up / `--set` lines.

**Outputs.** `<out_dir>/run/` with the copied `.ins` files, `site_cf.ins`, `soils_site.dat`,
`guess.log`, `guess_stdout.log` and all `.out` tables; last stdout line = JSON summary.

**Procedure.**
```bash
python tools/run_lpjguess_engine.py example --out_dir /tmp/lpj_demo          # ~4 min
python tools/run_lpjguess_engine.py cf --forcing_meta forcing/forcing_meta.json \
  --co2_file KISSPATH_KI_ROOT/LPJ_GUESS/inputs/co2/co2_1901_2014.txt \
  --out_dir run_detha                                                        # ~16 s
# restrict PFTs (real stand), e.g. spruce only:
python tools/run_lpjguess_engine.py cf ... --set 'pft "TeBS" ( include 0 )' --set ...
```
The cf mode copies `global_cf.ins` → `site_cf.ins`, edits the `file_*` params, appends
`firemodel`, `nyear_spinup`, monthly output files and `--set` lines, and writes a soil map
copy with one exact line for the site.

**Verification (what the tool checks).** rc 0; `Finished` line in guess.log; every expected
`.out` has rows; same last Year in all tables (cf: = forcing end year); example: the
reference `<engine>/run_global_demo` must exist and be complete (every annual table present,
and the run and the reference hold the same set of `.out` files, 19 for the demo), then every
value is compared (default tolerance 0). A missing/empty/incomplete reference is exit 5, never
a silent pass. `--reference_dir ''` skips the comparison and the JSON then says
`"reproduced": false`. Exit 2 input, 3 engine, 4 outputs, 5 example mismatch / no usable reference.

**Traps.** dt_lpjguess_019 (searchradius_soil segfault), 020 (soil map), 027 (PNV vs real
stand), 028 (BLAZE), 030 (judge by rc + Finished), 031 (commented param lines), 032 (demo exactness).

**Example.** 2026-10-07: demo 252 s, 19/19 files byte-identical. DE-Tha cf run 16 s,
last year 2014, soil cell (13.75, 50.75) code 2.
