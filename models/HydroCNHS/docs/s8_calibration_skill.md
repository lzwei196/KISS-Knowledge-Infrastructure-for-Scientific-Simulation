# S8: Calibration Workflow

## Purpose

Optimize HydroCNHS model parameters against observed streamflow using the
built-in genetic algorithm (GA) from DEAP. Calibration is essential because
initial parameter estimates from soil/land-use data rarely produce
satisfactory discharge simulation.

## Inputs

| Input | Format | Unit | Source |
|-------|--------|------|--------|
| Uncalibrated model.yaml | YAML file | — | S3 output (with -99 params) |
| Climate data | Python dicts | °C, cm/day | S1 output |
| Observed streamflow | dict or DataFrame | cms | Gauge data |
| Parameter bounds | DataFrame | varies | `hydrocnhs.gen_default_bounds()` |

## Outputs

| Output | Format | Unit | Destination |
|--------|--------|------|-------------|
| Calibrated model.yaml | YAML file | — | S5 for validation |
| Best fitness value | float | unitless | Evaluation |
| Calibration history | list | — | Convergence analysis |

## Procedure

### 1. Prepare the model YAML

Set all parameters to calibrate to -99:

```yaml
RainfallRunoff:
  WSLO:
    Pars:
      CN2: -99    # Will be optimized
      IS: -99
      Res: -99
      Sep: 0.01   # Fixed (low sensitivity)
      Alpha: -99
      Beta: -99
      Ur: -99
      Df: -99
      Kc: -99
```

### 2. Generate parameter bounds

```python
import hydrocnhs
import hydrocnhs.calibration as cali

model_dict = hydrocnhs.load_model("model.yaml")
df_bounds = hydrocnhs.gen_default_bounds(model_dict)
print(df_bounds)
# Shows: parameter name, lower bound, upper bound for each -99 param
```

Custom bounds can be set by modifying `df_bounds`:

```python
# Tighten CN2 range based on land-use knowledge
df_bounds.loc[df_bounds["Parameter"] == "CN2", "Upper"] = 85
df_bounds.loc[df_bounds["Parameter"] == "CN2", "Lower"] = 50
```

### 3. Define evaluation function

The evaluation function receives an individual (parameter vector) and
must return a tuple of fitness values.

```python
def evaluation(individual, info):
    """Evaluate a parameter set. Returns (fitness,)."""
    # Convert individual vector to model parameters
    cali_model = cali.Convertor.to_model_dict(
        model_dict, individual, formatter
    )

    # Run simulation
    try:
        sim_model = hydrocnhs.Model(cali_model)
        Q = sim_model.run(temp=temp, prec=prec, pet=pet)
    except Exception:
        return (-999,)  # Penalize failed runs

    # Compute fitness (KGE at target outlets)
    indicator = hydrocnhs.Indicator()
    fitness_values = []

    for outlet in observed:
        obs = np.array(observed[outlet])
        sim = np.array(sim_model.dc.Q_routed.get(outlet, [0]*len(obs)))

        # Skip warmup
        obs = obs[warmup_days:]
        sim = sim[warmup_days:]

        kge = indicator.get_kge(obs, sim)
        fitness_values.append(kge)

    return (np.mean(fitness_values),)
```

### 4. Configure and run GA

```python
# Create random number generator for reproducibility
rn_gen = hydrocnhs.create_rn_gen(seed=42)

# Set up formatter for parameter conversion
formatter = cali.Convertor(model_dict)

# Configure GA
ga = cali.GA_DEAP(evaluation, rn_gen)
ga.set(
    inputs={"model": model_dict, "temp": temp, "prec": prec,
            "observed": observed},
    config={
        "pop_size": 100,     # Population size (50-200)
        "max_gen": 200,      # Maximum generations (100-500)
        "cxpb": 0.9,         # Crossover probability
        "mutpb": 0.3,        # Mutation probability
    },
    formatter=formatter,
)

# Run calibration
ga.run()

# Get best solution
best_params = ga.solution[0]      # Parameter vector
best_fitness = ga.solution[1]     # Fitness value
```

### 5. Save calibrated model

```python
# Convert best parameters back to model dict
calibrated_dict = cali.Convertor.to_model_dict(
    model_dict, best_params, formatter
)

# Write to YAML
hydrocnhs.write_model(calibrated_dict, "Calibrated_model.yaml")
```

### 6. Validate calibration

Run the calibrated model and check metrics:

```python
model = hydrocnhs.Model("Calibrated_model.yaml")
Q = model.run(temp=temp, prec=prec)

for outlet in observed:
    obs = np.array(observed[outlet])[warmup_days:]
    sim = np.array(model.dc.Q_routed[outlet])[warmup_days:]

    indicator = hydrocnhs.Indicator()
    print(f"{outlet}:")
    print(f"  NSE = {indicator.get_nse(obs, sim):.3f}")
    print(f"  KGE = {indicator.get_kge(obs, sim):.3f}")
```

## Verification

- Best fitness should improve over generations (check convergence)
- If fitness plateaus early (< 20 gen), population is too small or bounds too wide
- If fitness never exceeds 0.5 (KGE), check input data units
- Run validation on an independent period (split-sample test)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt_014: Forgotten -99 params | GA ignores unflagged params | Set to -99 |
| dt_012: Wrong bounds | GA explores unrealistic params | Tighten based on domain |
| Equifinality | Multiple "good" solutions | Use multi-objective (KGE + iKGE) |
| Overfitting | Good calibration, poor validation | Split-sample test |

## Example

Complete calibration for TRB GWLF:

```bash
# Using the wrapper
python run_hydrocnhs.py \
    --mode calibrate \
    --model model_uncalibrated.yaml \
    --climate-pickle TRB_inputs.pickle \
    --observed-pickle TRB_observed.pickle \
    --generations 200 \
    --population 100 \
    --output Calibrated_TRB_GWLF.yaml
```

Typical calibration time:
- 7 subbasins, GWLF, 33 years: ~30 min (100 gen, pop=50, 4 cores)
- With ABM agents: ~2–4 hours (more parameters, longer per evaluation)
