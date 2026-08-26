# Stage 2: Configure Basin Skill

Thin wrapper for the preserved detailed note: [s2_configure_basin.md](s2_configure_basin.md).

## Purpose

Build the basin-specific CaMa-Flood map directory, source-grid input matrix, channel-geometry files, Manning map, and generated shell script that will run the real `MAIN_cmf` binary.

## Inputs

- `tools/configure_simulation.py`
- Global map: `KISSPATH_BINARIES/cmf_v420_pkg/map/glb_15min/`
- GPCC climatology: `KISSPATH_BINARIES/cmf_v420_pkg/map/data/ELSE_GPCC_coastmod_dayclm-1981-2010.one`
- Stage 1 forcing directory: `KISSPATH_ROOT/ata-kdt/bengbu_ki_driven/outputs/cama_input`
- Source grid extent or `--grid_nc`
- `diagnostics/triplets.yaml`

## Outputs

- Regional map directory such as `KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/`
- Required map binaries: `nextxy.bin`, `ctmare.bin`, `elevtn.bin`, `nxtdst.bin`, `rivlen.bin`, `fldhgt.bin`
- `diminfo_bengbu_025deg.txt`
- `inpmat_bengbu_025deg.bin`
- `outclm.bin`, `rivwth.bin`, `rivwth_gwdlr.bin`, `rivhgt.bin`, `rivman.bin`
- Run script: `KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh`

## Procedure

Run the configured pipeline from the KI root. This command matches the Bengbu source-grid edges and forcing path documented in `SKILL.md`:

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

Internally, `tools/configure_simulation.py` regionalizes from `glb_15min`, runs `generate_inpmat` for the source grid, runs `calc_outclm` from the global map, runs `calc_rivwth` from the regional map with regional `diminfo`, creates `rivman.bin`, and writes the shell script under `gosh/`.

## Verification

Check the generated Bengbu files that exist in this KI's bound CaMa-Flood tree:

```bash
test -s KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/nextxy.bin
test -s KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/diminfo_bengbu_025deg.txt
test -s KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/inpmat_bengbu_025deg.bin
test -s KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/rivwth_gwdlr.bin
test -s KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh
```

Audit the source-grid extent and river-width array size:

```bash
sed -n '1,11p' KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min/diminfo_bengbu_025deg.txt
python -c 'import os; p="KISSPATH_BINARIES/cmf_v420_pkg/map/bengbu_15min"; lines=open(p+"/diminfo_bengbu_025deg.txt").read().splitlines(); print(os.path.getsize(p+"/rivwth.bin"), int(lines[0].split()[0])*int(lines[1].split()[0])*4)'
```

## Traps

- `dt_007`: Stage 2 assumes `OLAT = NtoS`; a source forcing file with ascending latitude maps runoff to the wrong CaMa cells.
- `dt_008`: the input matrix was generated from the buffered CaMa domain instead of the source runoff grid edges.
- `dt_011`: `calc_outclm` was run outside `KISSPATH_BINARIES/cmf_v420_pkg/map/glb_15min`, producing missing or zero-filled climatological discharge.
- `dt_012`: `calc_rivwth` used global or nonregional `diminfo`, so channel-width binaries do not match the regional grid.
- `dt_013`: an old `map/{basin}_15min` directory was reused for a different basin, silently routing water through the wrong network.
- `dt_014`: `diminfo_{basin}_025deg.txt` was hand-edited into a format the Fortran readers cannot parse.
- `dt_015`: regionalization did not produce the high-resolution `1min` subgrid needed by downstream flood coupling.

## Example

```bash
cd KISSPATH_KI_ROOT/CaMa_Flood/knowledge_infrastructure
python tools/run_cama.py \
  --script KISSPATH_BINARIES/cmf_v420_pkg/gosh/run_bengbu_1d_nc.sh \
  --dry_run
```

