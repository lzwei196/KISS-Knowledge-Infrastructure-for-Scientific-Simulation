# Stage 8 — External Channel Routing (mizuRoute)

SUMMA has **no internal channel routing**. `averageRoutedRunoff` is the sub-grid gamma
time-delay histogram, not channel discharge. Gauged-streamflow validation therefore
requires this stage. See `dag.yaml` hazards:
`averageRoutedRunoff_scored_as_channel_discharge`,
`mizuroute_hybas_id_int32_overflow_and_unit_double_conversion`,
`lumped_discretisation_cannot_be_routed`.

## Tools

| Tool | Purpose |
|---|---|
| `tools/s8_routing/build_river_network.py` | HydroBASINS lev07 -> `ntopo.nc` + `gru_hru_mapping.csv` + `hybas_map.csv`, by upstream `NEXT_DOWN` traversal from the gauge sub-basin. |
| `tools/s8_routing/summa_to_mizuroute.py` | SUMMA output -> mizuRoute `<fname_qsim>` runoff NetCDF. Units pass through as `m/s`, unconverted. |
| `tools/s8_routing/run_mizuroute.py` | Writes control + `param.nml`, executes `mizuroute.exe`, extracts outlet discharge to `routed_discharge.csv`. |

Run all three with `KISSPATH_PYTHON_ENV/bin/python`.

## Pipeline

    PY=KISSPATH_PYTHON_ENV/bin/python

    $PY tools/s8_routing/build_river_network.py \
        --hybas_shp <hybas_as_lev07_v1c.shp> --outlet_hybas_id <HYBAS_ID> \
        --dem <dem.tif> --output_dir route/ --veg_index <N> --soil_index <N>

    # re-run s1..s6 with route/gru_hru_mapping.csv (one GRU per sub-basin),
    # forcing one CMFD column per GRU, data_step=10800,
    # outputControl must emit scalarTotalRunoff

    $PY tools/s8_routing/summa_to_mizuroute.py \
        --summa_output_nc <summa_out.nc> --ntopo_nc route/ntopo.nc \
        --output_nc route/runoff.nc

    $PY tools/s8_routing/run_mizuroute.py \
        --ntopo_nc route/ntopo.nc --runoff_nc route/runoff.nc --output_dir route/ \
        --sim_start YYYY-MM-DD --sim_end YYYY-MM-DD \
        --outlet_seg_id <from build_river_network stdout JSON> --dt 10800

Score `route/routed_discharge.csv` (`date`, `Q_m3s`) against the gauge.

## Silent contracts

- **Feed `scalarTotalRunoff`, not `averageRoutedRunoff`.** `<doesBasinRoute> 1` applies the
  hillslope UH inside mizuRoute; the delayed variable would be routed twice.
- **`m/s` is native.** `read_control.f90:456` -> `case('m'); length_conv = 1._dp`. Do not
  convert; a `/1000` makes discharge 1000x wrong.
- **IDs are renumbered 1..N.** HYBAS_ID (max 4,071,348,160) overflows mizuRoute's int32
  ntopo payload (`read_streamSeg.f90:254`, `i4b`). Originals live in `hybas_map.csv`.
- **`route_opt=1` (IRF) is hard-coded.** Only IRF avoids consuming channel `Slope`, which
  HydroBASINS does not carry and which `build_river_network.py` writes as a nominal
  placeholder purely to satisfy `popMetadat.f90:134`.
- **A lumped GRU cannot be routed.** Re-discretise to one GRU per sub-basin first.

## Interpreting the result

Routing conserves mass. It moves water in time (NSE/KGE) and **cannot change PBIAS**.
Re-audit `validate_water_balance` before reading any metric: a residual of the same
magnitude as |PBIAS| indicates a storage sink (commonly perpetual snow in the top
elevation bands — SUMMA has no glacier module), not a routing deficiency.
