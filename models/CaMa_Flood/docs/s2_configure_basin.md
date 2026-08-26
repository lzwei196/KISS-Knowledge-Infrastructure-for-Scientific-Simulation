# Stage 2: Configure Basin

## Purpose

Create the basin-specific CaMa-Flood map directory, source-grid input matrix, channel geometry files, Manning map, and generated shell run script used by `MAIN_cmf`.

## Inputs

- `tools/configure_simulation.py`
- CaMa global map: `KISSPATH_BINARIES/cmf_v420_pkg/map/glb_15min/`
- GPCC climatology: `KISSPATH_BINARIES/cmf_v420_pkg/map/data/ELSE_GPCC_coastmod_dayclm-1981-2010.one`
- Runoff NetCDF directory from Stage 1
- Source grid extent, either:
  - `--grid_nc /path/to/basin_grid.nc`, or
  - `--west --east --south --north --grid_resolution`

## Outputs

- `KISSPATH_BINARIES/cmf_v420_pkg/map/{basin}_15min/`
- Required map files such as `nextxy.bin`, `ctmare.bin`, `elevtn.bin`, `nxtdst.bin`, `rivlen.bin`, and `fldhgt.bin`
- `diminfo_{basin}_025deg.txt`
- `inpmat_{basin}_025deg.bin`
- `outclm.bin`, `rivwth.bin`, `rivwth_gwdlr.bin`, `rivhgt.bin`, and `rivman.bin`
- `KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_{basin}_1d_nc.sh`

## Procedure

Run from the KI root. This command uses the Bengbu source-grid edges shown in `SKILL.md` and an existing CaMa-ready forcing directory:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/configure_simulation.py \
  --basin_name bengbu \
  --west 111.75 --east 117.75 --south 31.0 --north 35.0 \
  --grid_resolution 0.25 \
  --start_year 2000 --end_year 2005 \
  --runoff_dir KISSPATH_ROOT/ata-kdt/bengbu_ki_driven/outputs/cama_input \
  --runoff_prefix bengbu_runoff_1d_ \
  --pmanriv 0.30 \
  --pmanfld 0.10 \
  --nspinup 2
```

The tool performs four internal steps:

- regionalization with `cut_domain`, `cut_bifway`, `set_map`, and `combine_hires`
- input matrix generation with `generate_inpmat`
- channel parameters with `calc_outclm` from `glb_15min`, then `calc_rivwth` from the regional map directory
- shell script generation under `gosh/`

## Verification

Check the generated files:

```bash
test -s KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/nextxy.bin
test -s KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/diminfo_bengbu_025deg.txt
test -s KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/inpmat_bengbu_025deg.bin
test -s KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/rivwth_gwdlr.bin
test -s KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh
```

Audit the source-grid extent encoded in `diminfo`:

```bash
sed -n '1,11p' KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/diminfo_bengbu_025deg.txt
```

Verify channel width file size against the regional grid:

```bash
python -c 'import os; p="KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min"; lines=open(p+"/diminfo_bengbu_025deg.txt").read().splitlines(); print(os.path.getsize(p+"/rivwth.bin"), int(lines[0].split()[0])*int(lines[1].split()[0])*4)'
```

## Traps

- `dt_cama_002`: input matrix built from the buffered CaMa domain instead of the source runoff grid. Use `--grid_nc` or source cell-edge coordinates.
- `dt_cama_004`: `calc_outclm` run outside `glb_15min`. The KI tool runs it from the global map before copying `outclm.bin` into the regional directory.
- `dt_cama_003` and `dt_cama_008`: `calc_rivwth` used nonregional or global `diminfo`, corrupting channel width/depth arrays.
- `dt_cama_005`: regional map reused across basins. Each new basin needs its own `map/{basin}_15min`.
- `dt_cama_010`: malformed `diminfo` from hand edits. Regenerate with `tools/configure_simulation.py`.

## Example

Dry-check the generated Bengbu script before execution:

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/run_cama.py \
  --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh \
  --dry_run
```
