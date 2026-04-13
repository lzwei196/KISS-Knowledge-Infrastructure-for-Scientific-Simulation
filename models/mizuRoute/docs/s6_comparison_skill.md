# Stage 6: Routing Method Comparison

## Purpose
Extract discharge from mizuRoute output, compare with observations and other routing models (Lohmann, CaMa-Flood), and evaluate the 5 routing methods against each other.

## 3-Way Comparison: Lohmann vs CaMa-Flood vs mizuRoute

| Aspect | Lohmann | CaMa-Flood | mizuRoute |
|--------|---------|------------|-----------|
| Physics | Unit hydrograph | Local inertia + floodplain | 5 selectable methods |
| Expected match | Very close to IRF | Close to KWE/MC | Depends on method |
| Discharge at outlet | Direct | Direct | Direct |
| Flood extent | No | Yes | No |
| Channel losses | No | Partial | Method-dependent |

### Expected Behavior by Method

| Method comparison | Expected difference | Acceptable range |
|------------------|--------------------|-----------------|
| IRF vs Lohmann | Very similar (both unit hydrograph) | < 10% mean Q |
| KWE vs CaMa-Flood | Similar magnitude, no floodplain | < 20% mean Q |
| MC vs IRF | Slight timing/attenuation differences | < 15% mean Q |
| DW vs KWE | DW more attenuated (diffusion term) | < 20% peak Q |
| KWT vs IRF | Similar for non-extreme events | < 10% mean Q |

### If differences are large (>30%):
1. Check runoff unit conversion (dt_m003) — this explains most large differences
2. Check remap weights (dt_m005, dt_m010) — incomplete coverage
3. Check network topology (dt_m015) — multiple outlets splitting flow
4. Check doesBasinRoute setting (dt_m014) — double hillslope delay

## Performance Metrics
| Metric | Good | Acceptable | Poor |
|--------|------|-----------|------|
| NSE | > 0.7 | 0.4 - 0.7 | < 0.4 |
| KGE | > 0.6 | 0.3 - 0.6 | < 0.3 |
| PBIAS | < 15% | 15-30% | > 30% |
| r | > 0.8 | 0.6 - 0.8 | < 0.6 |

## Procedure
```bash
# Single method extraction
python tools/s6_postprocess/extract_discharge.py \
  --mizuroute_output <output_dir> \
  --network_nc <network_nc> \
  --output discharge.csv \
  --obs_file <obs_file> --warmup_years 2

# All methods comparison
python tools/s6_postprocess/compare_routing_methods.py \
  --control_template <control_file> \
  --exe <mizuroute_exe> \
  --network_nc <network_nc> \
  --output_dir <comparison_dir> \
  --methods IRF,KWT,KWE,MC,DW
```
