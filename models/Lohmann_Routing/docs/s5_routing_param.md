# s5_routing_param

Build Lohmann routing parameter files for a basin and station.

## Tool

Use `s5_routing_param/run_build_routing_new.py`.

The script builds the ArcInfo-style grids and routing control files consumed by the `route_1.0` Fortran executable:

- `*_direc.txt`: D8 flow direction grid.
- `*_frac.txt`: fraction of each grid cell draining to the gauge.
- `*_xmask.txt`: flow distance in metres.
- `*_staloc.txt`: station location file with two required lines.
- `UH.all`: 12-line within-cell unit hydrograph.
- `rout_global.txt`: routing control file.

## Key Checks

The builder uses a two-step flow-network procedure: compute an initial coarse-grid D8 network, then iteratively repair cells that do not reach the outlet. Use only a generated `*_direc.txt` after the log shows that the final connected-cell count equals the active-cell count.

Check the generated parameter files:

```bash
awk 'NR>6{for(i=1;i<=NF;i++) if($i<0 || $i>1){print FNR":"$i; bad=1}} END{exit bad}' *_frac.txt
awk 'NR>6{for(i=1;i<=NF;i++) if($i>0 && $i<1000){print FNR":"$i; bad=1}} END{exit bad}' *_xmask.txt
awk 'NF!=2{bad=1} {sum+=$2} END{if (NR!=12 || bad || sum<0.999 || sum>1.001) exit 1}' UH.all
```

## Failure Modes

- `dt_001`: disconnected D8 network gives no output or too few upstream cells.
- `dt_002`: malformed station file causes immediate exit or no station output.
- `dt_003`: `UH.all` is not exactly 12 indexed ordinates.
- `dt_011`: fraction grid contains area units instead of 0-1 fractions.
- `dt_012`: xmask distances are degrees or kilometres instead of metres.
- `dt_015`: external D8 code convention does not match the routing binary.
- `dt_016`: `rout_global.txt` boolean toggles do not match following scalar/path values.
