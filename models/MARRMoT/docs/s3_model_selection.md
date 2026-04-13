# Skill: Model Selection

## Purpose

Choose an appropriate MARRMoT model structure from the 47 available options
based on the target catchment characteristics, study objectives, and
available data. This is a decision-making skill, not a tool-based skill.

MARRMoT's unique value is enabling fair comparison across model structures
under identical numerical and data conditions. Model selection may involve
running multiple structures and comparing their performance.

## Inputs

| Input                     | Source           | Format   |
|---------------------------|------------------|----------|
| Catchment characteristics | Site knowledge   | Text     |
| Climate type              | Koppen / local   | Text     |
| Study objective           | User decision    | Text     |
| Available data            | Inventory        | Text     |
| Desired complexity        | User decision    | 1-24 params |

## Outputs

| Output                    | Format   | Contents                    |
|---------------------------|----------|-----------------------------|
| Selected model name(s)    | String   | e.g. m_29_hymod_5p_5s       |
| Justification             | Text     | Why this structure fits      |

## Procedure

### Step 1: Assess catchment processes

Identify which hydrological processes dominate:

| Process              | Relevant models                              | Key indicator          |
|----------------------|----------------------------------------------|------------------------|
| Snow accumulation    | m_06, m_12, m_37 (HBV), m_43 (GSM-SOCONT)   | Tmin < 0 in winter     |
| Deep groundwater     | m_33 (Sacramento), m_35, m_45 (PRMS)         | Sustained baseflow     |
| Quick surface runoff | m_01, m_14 (TOPMODEL), m_28 (Xinanjiang)     | Flashy hydrograph      |
| Multiple stores      | m_22 (VIC), m_37 (HBV), m_38 (TANK)          | Complex recession      |
| Wetland/depression   | m_02                                          | Flat, wet terrain      |

### Step 2: Match complexity to data

| Data availability      | Recommended complexity | Example models                    |
|------------------------|------------------------|-----------------------------------|
| P + T + PET only       | 1-5 params             | m_01, m_07 (GR4J), m_29 (HyMOD)  |
| + observed Q (short)   | 5-10 params            | m_18 (SIMHYD), m_28 (Xinanjiang)  |
| + observed Q (long)    | 10-20 params           | m_33 (Sacramento), m_37 (HBV)     |
| + snow data            | snow models            | m_37 (HBV), m_12                  |

**Rule of thumb**: Never use more parameters than you have years of
calibration data. A 15-parameter model needs at least 15 years.

### Step 3: Select benchmark candidates

For most studies, start with these well-tested structures:

| Model               | Params | Stores | Best for                           |
|----------------------|--------|--------|------------------------------------|
| m_01_collie1_1p_1s   | 1      | 1      | Sanity check, baseline             |
| m_07_gr4j_4p_2s      | 4      | 2      | General-purpose, robust            |
| m_29_hymod_5p_5s     | 5      | 5      | Benchmark, fast/slow flow split    |
| m_18_simhyd_7p_3s    | 7      | 3      | Australian catchments              |
| m_33_sacramento_11p_5s| 11    | 5      | US operational forecasting         |
| m_37_hbv96_15p_5s    | 15     | 5      | Snow-influenced catchments         |

### Step 4: Run and compare

Use MARRMoT's multi-model workflow (workflow_example_3.m) to run
multiple structures with the same forcing data and compare KGE/NSE.

## Verification

- Confirm the selected model exists: `m = feval('model_name')` should not error
- Check numParams and numStores match expectations
- Verify the model includes relevant processes (snow, groundwater, etc.)

## Traps

- **Over-parameterisation**: Using m_47 (24 params) with 5 years of data
  leads to equifinality — many parameter sets fit equally well but
  predict poorly outside calibration.

- **Missing processes**: Using a non-snow model (m_29) in a snow-dominated
  catchment ignores the dominant runoff generation mechanism.

- **Structural assumption mismatch**: TOPMODEL (m_14) assumes a water table
  connected to the stream. In deep-aquifer systems this is wrong.

## Example

For a temperate catchment with seasonal snow, 20 years of daily Q data,
and moderate complexity preference:

**Recommended**: m_37_hbv96_15p_5s (HBV-96)
- Includes snow routine (TT, TTI, TTM, ddf parameters)
- 15 parameters feasible with 20 years of data
- Well-documented and widely benchmarked

**Alternative**: m_29_hymod_5p_5s for quick baseline comparison.
