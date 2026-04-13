# Pywr Reservoir Operations Workflow

## Prerequisites

- VIC simulation completed (Steps 1-7 of HydroCraft workflow)
- Basin shapefile available
- Python environment with Pywr: `/home/server/桌面/test/hydro-claude/python_env/bin/python3`

## Stage Sequence

```
[VIC Complete] --> S1: Verify Pywr
                   |
                   v
              S2: Find Dams in Basin (GRanD)
                   |
                   v
              S3: Build Reservoir Properties
                   |
                   +-----> S5: Operating Rules (parallel with S4)
                   |
                   v
              S4: Convert VIC to Inflow
                   |
                   +-----> S6: Demand Nodes (after S4 for MAF estimate)
                   |
                   v
              S7: Assemble Pywr Model (needs S3+S4+S5+S6)
                   |
                   v
              S8a: Run Pywr
                   |
                   +-----> S8b: Plot Results
                   |
                   +-----> S8c: Check Overtopping -> DLBreach?
                   |
                   v
              S8d: Inject Releases to CaMa (optional)
                   |
                   v
              [Re-run CaMa-Flood with regulated flow]
```

## Typical Runtimes

| Stage | Runtime | Notes |
|-------|---------|-------|
| S1 Verify | < 5 sec | One-time check |
| S2 Find dams | 1-5 sec | GRanD CSV scan |
| S3 Properties | < 1 sec | Computation only |
| S4 VIC to inflow | 10-60 sec | Depends on number of cells and years |
| S5 Operating rules | < 1 sec | Computation only |
| S6 Demands | < 1 sec | Computation only |
| S7 Assembly | 1-5 sec | JSON generation + validation |
| S8a Run | 5-60 sec | Pywr LP solver (daily timestep) |
| S8b Plot | 2-5 sec | Matplotlib rendering |
| S8c Overtopping | < 1 sec | CSV analysis |
| S8d CaMa inject | 5-30 sec per file | NetCDF read/write |

## Decision Points

1. **No dams found in basin**: Skip Pywr workflow. Not all basins have dams.

2. **Multiple dams in basin**: Model each dam separately, or model the largest one. For cascade reservoir systems, build Pywr model with multiple storage nodes in series.

3. **No VIC output available**: Use observed discharge or synthetic inflow instead of VIC-derived inflow.

4. **Overtopping detected**: Offer to run DLBreach for dam-break risk assessment.

5. **CaMa re-run with regulated flow**: Only needed for basins where reservoir regulation significantly affects downstream hydrology (large reservoir capacity relative to annual flow).
