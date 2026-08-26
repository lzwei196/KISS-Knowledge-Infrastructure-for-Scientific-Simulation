# Stage 0: Preflight

## Purpose

Verify that this KI can run the real CaMa-Flood v4.20 Fortran executable and that the required global map, setup binaries, Python modules, KI tools, and diagnostic corpus are present before any basin setup or simulation.

## Inputs

- `SKILL.md`
- `preflight_check.py`
- `diagnostics/triplets.yaml`
- `KISSPATH_BINARIES/cmf_v420_pkg/src/MAIN_cmf`
- `KISSPATH_BINARIES/cmf_v420_pkg/map/glb_15min/`
- `KISSPATH_BINARIES/cmf_v420_pkg/map/data/ELSE_GPCC_coastmod_dayclm-1981-2010.one`

## Outputs

- Terminal pass/fail report for critical dependencies.
- Final `PREFLIGHT_REPORT=<json>` line emitted by `preflight_check.py`.
- Exit code `0` only when all critical checks pass.

## Procedure

Run from the KI root:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python preflight_check.py
```

For a quick manual probe of the model binding named in `SKILL.md`:

```bash
test -x KISSPATH_BINARIES/cmf_v420_pkg/src/MAIN_cmf
test -d KISSPATH_BINARIES/cmf_v420_pkg/map/glb_15min
test -s KISSPATH_BINARIES/cmf_v420_pkg/map/data/ELSE_GPCC_coastmod_dayclm-1981-2010.one
```

## Verification

The preflight output should include passing checks for:

- `CaMa-Flood binary`
- `CaMa-Flood binary startup`
- `CaMa global river map`
- `Map setup binary cut_domain`, `generate_inpmat`, `calc_outclm`, and `calc_rivwth`
- `KI tool tools/prepare_runoff_input.py`, `tools/configure_simulation.py`, `tools/run_cama.py`, and `tools/parse_cama_output.py`

Inspect the machine-readable line:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python preflight_check.py | tail -1
```

## Traps

- `dt_002`: `MAIN_cmf` is missing, not executable, or fails the startup probe. Restore or rebuild the Fortran binary; do not replace it with a Python routing approximation.
- `dt_cama_004`: missing `calc_outclm` or GPCC climatology will later break channel-parameter setup because climatological discharge must be computed from `glb_15min`.
- `dt_cama_011`: missing regional high-resolution map support may not block preflight but will break downstream downscaling or CaMa-to-SFINCS coupling.

## Example

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python preflight_check.py
```

Proceed only after the command exits `0`.
