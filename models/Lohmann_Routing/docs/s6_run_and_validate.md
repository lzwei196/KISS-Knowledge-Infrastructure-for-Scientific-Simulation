# s6_run_and_validate

Run the compiled Lohmann `route_1.0` binary and validate the routed discharge outputs.

## Preflight

From the KI root, run:

```bash
python preflight_check.py
```

The preflight checks the compiled routing executable at `KISSPATH_BINARIES/route_1.0/src/rout`, the Python environment, KI files, and diagnostics.

## Run

Run the real routing executable with a generated `rout_global.txt`:

```bash
KISSPATH_BINARIES/route_1.0/src/rout rout_global.txt
```

Keep paths in `rout_global.txt` short. The Fortran implementation uses fixed-length strings, so long absolute paths can be truncated and produce missing-input messages even when files exist.

Before rerunning with `staloc` line 2 set to `NONE`, remove stale `*.uh_s` files in the work directory. The binary opens new unit-hydrograph cache files with `STATUS='NEW'`.

## Outputs

- `<NAME5>.day`: daily routed discharge in `m3/s`.
- `<NAME5>.month`: monthly mean discharge in `m3/s`.
- `<NAME5>.year`: climatological 12-month mean cycle in `m3/s`.
- `<NAME5>.day_mm`: basin-area-normalized daily discharge in `mm/day`.
- `<NAME5>.month_mm`: basin-area-normalized monthly discharge in `mm/day`.

Validate `m3/s` outputs directly against observed gauge discharge. Validate `*_mm` outputs only after converting observed gauge discharge with the same basin-area normalizer.

## Failure Modes

- `dt_004`: compiled `NROW` or `NCOL` is smaller than the parameter grid.
- `dt_006`: long paths are truncated by Fortran fixed-length strings.
- `dt_009`: existing `*.uh_s` cache blocks recomputation.
- `dt_010`: stale `*.uh_s` cache is silently reused and shifts hydrograph timing.
- `dt_018`: missing or non-executable routing binary.
- `dt_020`: observed `m3/s` discharge is compared to model `mm/day` outputs without conversion.
