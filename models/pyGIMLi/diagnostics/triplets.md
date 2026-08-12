# pyGIMLi — Diagnostic Triplets

Structured error knowledge: symptom → diagnosis → remedy.
Consult this file FIRST when pyGIMLi misbehaves.

---

### dt_001 — Input apparent resistivity in Ohm instead of Ohm-m

**Symptom**: Inverted resistivity model values are 1000x higher than expected for site geology. Model range 10000-1e8 Ohm-m for typical sedimentary site.

**Diagnosis**: The geometric factor k was not applied to convert resistance (V/I) to apparent resistivity (k * V/I). Some instruments export raw resistance. pyGIMLi expects Ohm-m for the `rhoa` token.

**Remedy**: Apply geometric factor: `rhoa = k * R`, where `k = 2*pi / (1/AM - 1/AN - 1/BM + 1/BN)`. In pyGIMLi: `data['rhoa'] = ert.createGeometricFactors(data) * data['r']`. Always verify rhoa range before inversion: 1-10000 Ohm-m is typical near-surface.

---

### dt_002 — SRT travel times in milliseconds instead of seconds

**Symptom**: SRT inversion produces velocities 1000x too high (e.g., 500000 m/s).

**Diagnosis**: SEG-2 files and some pick programs export travel times in ms. pyGIMLi expects seconds. If times are 1000x too large, the inverted slowness is 1000x too small, giving unrealistic velocities.

**Remedy**: Divide travel times by 1000: `data['t'] /= 1000.0`. Check data['t'] range: should be 0.001-0.1 s for near-surface. If median(t) > 1.0, times are likely in ms.

---

### dt_003 — Sensor coordinates in lat/lon degrees instead of local metres

**Symptom**: Mesh generation fails with `degenerate triangle` or nonsensical geometry. Mesh covers < 1 m or > 10000 km.

**Diagnosis**: GPS coordinates (e.g., 39.9 N, 116.4 E) treated as metres produce a mesh ~0.01 m wide. Or projected coordinates in large numbers produce numerical precision issues.

**Remedy**: Project coordinates to local Cartesian (UTM or local origin subtracted). Compute survey extent: should be 10-1000 m for typical surveys. If extent < 1 m, coordinates are in degrees and need projection.

---

### dt_004 — IP phase sign convention mismatch

**Symptom**: IP inversion produces nonsensical Cole-Cole parameters. Phase values > 100 mrad or negative when should be positive.

**Diagnosis**: Some instruments report IP phase as positive values. pyGIMLi's SIP framework expects negative phase (lag convention). Feeding positive phases produces inverted Cole-Cole parameters.

**Remedy**: Negate phase values: `data['ipa'] = -abs(data['ipa'])`. Check instrument manual for sign convention.

---

### dt_005 — Error estimates as percentage instead of fraction

**Symptom**: Chi-squared is either extremely high (>100) or extremely low (<0.01). Inversion converges but chi-squared never reaches ~1.0.

**Diagnosis**: pyGIMLi expects relative error as a fraction (e.g., 0.03 for 3%). If errors are given as percentages (e.g., 3.0 for 3%), data weighting is 100x wrong. Errors as percentage lead to chi-squared ~100x too small (overfitting).

**Remedy**: Convert errors: if max(err) > 1, divide by 100. Check data['err'] range: should be 0.01-0.20 for typical data. Use `ert.estimateError()` if unsure about error format.

---

### dt_006 — Duplicate or overlapping electrode positions

**Symptom**: `createParaMesh` fails with segfault or `no valid triangulation`.

**Diagnosis**: Triangle requires unique node positions. If two electrodes have identical or near-identical coordinates (within floating-point tolerance), the Delaunay triangulation fails.

**Remedy**: Remove duplicate sensors; snap to grid if positions are very close. Check with `sensors = data.sensors()` for duplicates with 1mm tolerance. Use `pg.unique(sensors)` or manually remove duplicates. Re-number ABMN indices after removing electrodes.

---

### dt_007 — Boundary region too small causing edge artifacts

**Symptom**: Inversion produces edge artifacts — model values spike at boundaries. Extreme resistivity/velocity values at model edges.

**Diagnosis**: If the mesh boundary is too close to the sensor array, the zero-flux or fixed boundary condition leaks into the parametric domain, creating artificial high/low values at the edges.

**Remedy**: Increase boundary factor to 3-5x the electrode spread: `mesh = pg.meshtools.createParaMesh(data, boundary=5)`. Alternatively, mask boundary cells in visualization: coverage < 0.1. Always use boundary >= 3 for real field data inversions.

---

### dt_008 — Mesh too fine causing slow inversion or memory issues

**Symptom**: Inversion is very slow (hours instead of minutes) or runs out of memory. `mesh.cellCount() > 100000`.

**Diagnosis**: Each mesh cell adds a model parameter. The Jacobian matrix is n_data x n_cells, and solving the normal equations scales as O(n^3). A 2D ERT inversion with > 50000 cells is typically excessive.

**Remedy**: Increase `paraMaxCellSize`; reduce quality; use coarser paraDX. For 2D surveys: aim for 2000-20000 cells. `paraMaxCellSize = electrode_spacing^2` is a good starting point. Check `mesh.cellCount()` before running inversion.

---

### dt_009 — Regularization lambda too high (over-smoothed model)

**Symptom**: Model is extremely smooth — no anomalies visible despite known geology. Homogeneous-looking model.

**Diagnosis**: High lambda over-penalizes model roughness, producing a smooth model that fits data poorly. The model looks like a homogeneous half-space despite the data containing anomaly signatures.

**Remedy**: Reduce lambda by factor 2-5 and re-run; target chi-squared ~1.0. Start with lam=20, then try lam=10, lam=5, lam=2. Stop when chi-squared ~1.0; do not go below 0.5.

---

### dt_010 — Inversion diverges due to zero/negative data or errors

**Symptom**: Inversion diverges — chi-squared increases or NaN values appear in model. `RuntimeWarning: invalid value`.

**Diagnosis**: TransLogLU requires strictly positive data. If apparent resistivity contains zero or negative values (bad measurement, polarity error), the log transform produces NaN/Inf. Zero errors produce infinite weights.

**Remedy**: Remove zero/negative data: `data.remove(data['rhoa'] <= 0)`. Set error floor: `data['err'] = np.maximum(data['err'], 0.01)`. For negative apparent resistivity: check electrode numbering (ABMN swap). Always filter data before inversion.

---

### dt_011 — Checkerboard artifacts from disabled singularity removal

**Symptom**: Checkerboard-like artifacts near current/source electrodes (ERT). Regular pattern of high/low near electrode positions.

**Diagnosis**: The FEM solution has a point-source singularity at current electrodes. Without singularity removal, the numerical error at these points propagates into the Jacobian and model. The artifact looks like real structure but is purely numerical.

**Remedy**: Enable singularity removal: `ERTManager(sr=True)` (default is True). For borehole ERT: ensure primary potential is computed correctly. Never disable sr unless you have a specific reason.

---

### dt_012 — SRT velocity/slowness transform confusion

**Symptom**: SRT inversion produces velocity inversion artefact — slower layer above faster. Velocity decreasing with depth in a clearly layered setting.

**Diagnosis**: pyGIMLi inverts for slowness (s/m), not velocity (m/s). The travel time forward problem is linear in slowness. If a log transform is applied assuming velocity parameterization, the inversion may produce artifacts. Default TravelTimeManager handles this correctly.

**Remedy**: Use default TravelTimeManager — do not override model transform. Do not set `mgr.fop.modelTrans = pg.trans.TransLog()` manually. Model values are slowness; display as velocity = 1/slowness.

---

### dt_013 — Systematic data error not captured by random noise model

**Symptom**: Systematic misfit pattern — residuals are structured, not random. Residual pseudosection shows consistent positive/negative bands.

**Diagnosis**: The error model (relativeError + absoluteError) assumes random noise. Systematic errors from electrode contact problems, cable cross-talk, or instrument drift produce structured residuals that smooth regularization cannot reproduce.

**Remedy**: Identify and remove systematic outliers; use reciprocal analysis. Plot residual pseudosection to find structured patterns. Remove data with |residual/error| > 3. If reciprocals are available, use reciprocal error as data error. Check for dead electrodes.

---

### dt_014 — Starting model too far from true model

**Symptom**: Inversion requires many iterations (>15) and chi-squared plateaus above 2.

**Diagnosis**: Gauss-Newton inversion is locally convergent. If the starting model is far from the truth, the linearization is poor and convergence is slow. The inversion may get stuck in a local minimum.

**Remedy**: Use a better starting model based on data statistics. For ERT: `startModel = geometric_mean(rhoa) = exp(mean(log(rhoa)))`. For SRT: startModel based on median apparent velocity from first arrivals. Or use 1D inversion result as starting model for 2D.

---

### dt_015 — Overfitting (lambda too low or errors too large)

**Symptom**: Model shows many small-scale fluctuations that don't match known geology. Noisy-looking model with cell-to-cell variation; chi-squared < 0.5.

**Diagnosis**: When chi-squared << 1, the inversion is fitting noise, producing spurious small-scale structure. This happens when errors are overestimated (giving too much freedom) or lambda is too low (insufficient smoothing).

**Remedy**: If chi-squared < 0.5: double lambda and re-run. If errors seem reasonable: use `robustData=True` for L1 norm. Target chi-squared = 1.0 +/- 0.2; stop reducing lambda when reached.

---

### dt_016 — Electrode spacing unit error compresses depth scale

**Symptom**: Depth of investigation appears half of expected from electrode spread. Model resolves only shallow features; deep anomalies missed.

**Diagnosis**: If electrode positions are in cm instead of m, the mesh is 100x too small. The inversion runs correctly but the depth axis is wrong. The model appears to have shallow investigation depth because the scale is compressed.

**Remedy**: Verify and correct electrode position units to metres. Check `data.sensors()` range matches physical survey extent. If range is 1/100 of expected: positions are in cm.

---

### dt_017 — Analytical geometric factor used for borehole geometry

**Symptom**: ERT model in borehole geometry is physically unreasonable. Resistivity > 1e6 or < 0.01 near borehole electrodes.

**Diagnosis**: The standard analytical geometric factor k assumes a homogeneous half-space with surface electrodes. For borehole, crosshole, or surface+borehole configurations, this factor is invalid, producing systematically biased apparent resistivities.

**Remedy**: Use numerical geometric factor: `k = ert.createGeometricFactors(data, mesh=mesh)`. For crosshole: always use numerical geometric factors.

---

### dt_018 — Low-coverage regions show misleading structure

**Symptom**: Model looks reasonable but low-coverage regions show misleading structure. Interesting anomalies in regions with coverage < 10%.

**Diagnosis**: Cells with low cumulative sensitivity (coverage) are poorly constrained by the data. Their values are controlled primarily by regularization and the starting model, not by the measured data. Displaying these cells at full opacity is geophysically misleading.

**Remedy**: Always display model with coverage mask or alpha channel: `coverage = np.array(pg.math.sumCols(mgr.fop.jacobian())); coverage /= coverage.max(); pg.show(mesh, model, coverage=coverage)`. Mask cells where coverage < 0.1.
