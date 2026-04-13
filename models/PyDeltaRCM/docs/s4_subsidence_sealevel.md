# Stage 4: Subsidence and Sea Level Rise

## Purpose

Apply optional basin subsidence and sea level rise to the model domain. These processes control the long-term accommodation space for sediment deposition, which fundamentally shapes delta morphology and stratigraphy.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| `eta` | Stage 3 (after sediment routing) | Current bed elevation |
| `toggle_subsidence` | Config | Enable/disable subsidence |
| `subsidence_rate` | Config | Maximum subsidence rate (m/s model time) |
| `start_subsidence` | Config | Time to begin subsidence (s model time) |
| `sigma` | Init | Subsidence rate field (L × W array) |
| `H_SL` | Config/derived | Current sea level |
| `SLR` | Config | Sea level rise rate (m/s model time) |

## Outputs

| Output | Used By | Description |
|--------|---------|-------------|
| `eta` (updated) | Stage 5 finalization | Subsided bed elevation |
| `H_SL` (updated) | Stage 5 finalization | New sea level |

## Procedure

### Subsidence

If `toggle_subsidence = True` and `time >= start_subsidence`:

```python
eta[:] = eta - sigma
```

The `sigma` field is initialized during model setup as a radial pattern centered on the inlet, with maximum subsidence at the domain edges:

```
sigma(r) = subsidence_rate * (r / r_max)
```

Where `r` is the distance from the inlet and `r_max` is the maximum domain distance.

### Sea Level Rise

Applied during `finalize_timestep()`:

```python
H_SL += SLR * dt
```

The new sea level shifts the base level for the entire domain, creating accommodation space for sediment.

## Verification

- [ ] Subsidence only applies after `start_subsidence` time
- [ ] `eta` decreases in subsidence areas (check before/after)
- [ ] Sea level `H_SL` increases linearly with time
- [ ] Combined effect creates accommodation space for sediment

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| `subsidence_rate` in mm/yr | Rate is ~1e12x too high or too low | Convert: mm/yr × If / (365.25×86400×1000) → m/s |
| `start_subsidence` in years | Subsidence starts way too early or never | Convert: years × 365.25 × 86400 → seconds |
| `SLR` in mm/yr | Unrealistic sea level change | Convert same as subsidence_rate |
| Subsidence without enough sediment | Delta drowns, no progradation | Increase C0_percent or reduce subsidence_rate |
| SLR too fast for sediment supply | Basin floods, delta submerged | Balance SLR with sediment supply |

## Example

### SLR Scenario

```yaml
# 3 mm/yr real-world SLR with If=0.05
# SLR_model = 0.003 / (365.25*86400) * 0.05 = 4.76e-12 m/s
SLR: 4.76e-12

# Or use the conversion tool:
# python tools/convert_parameters.py --slr 3.0 --If 0.05
```

### Subsidence Scenario

```yaml
toggle_subsidence: true
subsidence_rate: 2e-9    # m/s model time
start_subsidence: 216000  # seconds model time (~2.5 model days)
```

### Monitoring

```python
# Track accommodation space
for t in range(100):
    delta.update()
    if t % 20 == 0:
        accom = (delta.H_SL - delta.eta).clip(min=0).sum() * delta.dx**2
        print(f"Step {t}: H_SL={delta.H_SL:.4f}m, "
              f"Accommodation={accom:.0f} m3")
```

## Physical Context

### Intermittency Factor and Time

PyDeltaRCM simulates bankfull conditions only. The intermittency factor `If` relates model time to real time:

```
real_time = model_time / If
```

Typical values:
- `If = 0.01`: River floods 1% of the time (arid systems)
- `If = 0.05`: River floods 5% of the time (typical)
- `If = 0.10`: River floods 10% of the time (humid tropics)

### Converting Real-World Rates to Model Time

For any rate R in real-world units (e.g., mm/yr):

```
R_model (m/s) = R_real (mm/yr) × If / (365.25 × 86400 × 1000)
```

The `× If` accounts for the fact that subsidence/SLR occurs continuously in real time, but the model only simulates bankfull time.
