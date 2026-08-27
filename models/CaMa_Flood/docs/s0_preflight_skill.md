# Stage 0: Preflight Skill

Thin wrapper for the preserved detailed note: [s0_preflight.md](s0_preflight.md).

## Purpose

Verify this KI is bound to the real CaMa-Flood v4.20 executable and the local HydroCraft map/setup files before any runoff conversion, map preparation, execution, or calibration work.

## Inputs

- `SKILL.md`
- `preflight_check.py`
- `diagnostics/triplets.yaml`
- `KISSPATH_BINARIES/cmf_v420_pkg/src/MAIN_cmf`
- `KISSPATH_BINARIES/cmf_v420_pkg/map/glb_15min/`
- `KISSPATH_BINARIES/cmf_v420_pkg/map/data/ELSE_GPCC_coastmod_dayclm-1981-2010.one`

## Outputs

- Terminal dependency report.
- Final `PREFLIGHT_REPORT=<json>` line from `preflight_check.py`.
- Exit code `0` when all critical binary, map, setup-tool, Python-import, and KI-tool checks pass.

## Procedure

Run the KI preflight from the KI root:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python preflight_check.py
```

Manually spot-check the core binding if preflight fails:

```bash
test -x KISSPATH_BINARIES/cmf_v420_pkg/src/MAIN_cmf
test -d KISSPATH_BINARIES/cmf_v420_pkg/map/glb_15min
test -s KISSPATH_BINARIES/cmf_v420_pkg/map/data/ELSE_GPCC_coastmod_dayclm-1981-2010.one
test -s diagnostics/triplets.yaml
```

## Verification

Confirm the report contract is present and machine-readable:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python preflight_check.py | tail -1
```

The last line must start with `PREFLIGHT_REPORT=` and the critical checks for `MAIN_cmf`, `glb_15min`, `generate_inpmat`, `calc_outclm`, `calc_rivwth`, and the four pipeline tools must pass.

## Traps

- `dt_002`: `preflight_check.py` reports the CaMa-Flood binary missing, not executable, loader-broken, or failing its startup probe. Restore or rebuild `KISSPATH_BINARIES/cmf_v420_pkg/src/MAIN_cmf`; do not substitute a Python routing approximation.
- `dt_011`: missing `calc_outclm` or the GPCC climatology will later break Stage 2 channel-parameter generation because climatological discharge must be accumulated from `glb_15min`.
- `dt_015`: absence of the regional high-resolution `1min` support is a setup dependency for downstream downscaling and CaMa-to-SFINCS coupling.

## Example

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python preflight_check.py
```

