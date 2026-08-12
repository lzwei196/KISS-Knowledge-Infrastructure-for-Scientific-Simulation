#!/usr/bin/env python3
"""
select_model_template.py — Select a Raven emulation template and generate .rvi skeleton.

Raven supports 15+ emulation templates. This tool selects one by name (or recommends
based on basin characteristics) and generates the .rvi file with the correct process
algorithm selections, soil layers, and state variable definitions.

Usage:
    python select_model_template.py \
        --template gr4j \
        --output_dir /path/to/raven_run \
        --basin_name chaohe

    # Auto-recommend based on basin characteristics:
    python select_model_template.py \
        --recommend \
        --climate semi_humid \
        --area_km2 8783 \
        --snow_dominated false \
        --output_dir /path/to/raven_run \
        --basin_name chaohe
"""

import argparse
import json
import os
import sys
from datetime import datetime

# ============================================================================
# EMULATION TEMPLATE LIBRARY
# Source: Raven v4.1 User Manual, Appendix F + source code verification
# Each template defines: process algorithms, soil layers, state variables,
# parameters (with defaults and calibration ranges), and forcing requirements
# ============================================================================

TEMPLATES = {
    "gr4j": {
        "full_name": "GR4J (Genie Rural a 4 parametres Journalier)",
        "level": "Level 1 (near-exact emulation)",
        "reference": "Perrin et al., 2003",
        "n_params": 4,
        "description": "French lumped 4-parameter daily model. Best for humid basins with limited data.",
        "climate_suitability": ["humid", "semi_humid", "tropical"],
        "data_requirement": "minimal",  # only precip + temp
        "snow_capable": True,  # CemaNeige snow module included per F.4
        "soil_layers": 4,
        # From Raven User Manual Appendix F.4 — GR4J Configuration (exact copy)
        # Aliases: PRODUCT_STORE=SOIL[0], ROUTING_STORE=SOIL[1], TEMP_STORE=SOIL[2], GW_STORE=SOIL[3]
        "processes": {
            "Precipitation": "PRECIP_RAVEN ATMOS_PRECIP MULTIPLE",
            "SnowTempEvolve": "SNOTEMP_NEWTONS SNOW_TEMP",
            "SnowBalance": "SNOBAL_CEMA_NEIGE SNOW PONDED_WATER",
            "OpenWaterEvaporation": "OPEN_WATER_EVAP PONDED_WATER ATMOSPHERE",
            "Infiltration": "INF_GR4J PONDED_WATER MULTIPLE",
            "SoilEvaporation": "SOILEVAP_GR4J PRODUCT_STORE ATMOSPHERE",
            "Percolation": "PERC_GR4J PRODUCT_STORE TEMP_STORE",
            "Flush": "RAVEN_DEFAULT SURFACE_WATER TEMP_STORE",
            "Split": "RAVEN_DEFAULT TEMP_STORE CONVOLUTION[0] CONVOLUTION[1] 0.9",
            "Convolve": "CONVOL_GR4J_1 CONVOLUTION[0] ROUTING_STORE",
            "Convolve_2": "CONVOL_GR4J_2 CONVOLUTION[1] TEMP_STORE",
            "Percolation_2": "PERC_GR4JEXCH ROUTING_STORE GW_STORE",
            "Percolation_3": "PERC_GR4JEXCH2 TEMP_STORE GW_STORE",
            "Flush_2": "RAVEN_DEFAULT TEMP_STORE SURFACE_WATER",
            "Baseflow": "BASE_GR4J ROUTING_STORE SURFACE_WATER",
        },
        "aliases": {
            "PRODUCT_STORE": "SOIL[0]",
            "ROUTING_STORE": "SOIL[1]",
            "TEMP_STORE": "SOIL[2]",
            "GW_STORE": "SOIL[3]",
        },
        "soil_model": "SOIL_MULTILAYER 4",
        "routing": "ROUTE_NONE",
        "catchment_route": "ROUTE_DUMP",
        "evaporation": "PET_OUDIN",  # manual F.4/F.11 says PET_DATA; needs :Data PET in .rvt (Gauge.cpp:279)
        "parameters": {
            "GR4J_X1": {"default": 350.0, "min": 1.0, "max": 1500.0, "unit": "mm", "desc": "Production store capacity"},
            "GR4J_X2": {"default": 0.0, "min": -10.0, "max": 5.0, "unit": "mm/d", "desc": "Groundwater exchange coefficient"},
            "GR4J_X3": {"default": 90.0, "min": 1.0, "max": 500.0, "unit": "mm", "desc": "Routing store capacity"},
            "GR4J_X4": {"default": 1.5, "min": 0.5, "max": 10.0, "unit": "d", "desc": "Unit hydrograph time base"},
        },
        "forcing_minimum": ["PRECIP", "TEMP_AVE"],
    },

    "hbv_ec": {
        "full_name": "HBV-EC (Environment Canada variant)",
        "level": "Level 1",
        "reference": "Bergstrom, 1976; Hamilton et al., 2000",
        "n_params": 21,
        "description": "Standard HBV with snow, glacier support. Robust general-purpose model.",
        "climate_suitability": ["humid", "semi_humid", "cold", "alpine", "continental"],
        "data_requirement": "moderate",
        "snow_capable": True,
        "soil_layers": 3,
        # From Raven User Manual Appendix F.2 — HBV-EC Configuration (exact copy)
        # Aliases: FAST_RESERVOIR=SOIL[1], SLOW_RESERVOIR=SOIL[2]
        "processes": {
            "SnowRefreeze": "FREEZE_DEGREE_DAY SNOW_LIQ SNOW",
            "Precipitation": "PRECIP_RAVEN ATMOS_PRECIP MULTIPLE",
            "CanopyEvaporation": "CANEVP_ALL CANOPY ATMOSPHERE",
            "CanopySublimation": "CANEVP_ALL CANOPY_SNOW ATMOSPHERE",
            "SnowBalance": "SNOBAL_SIMPLE_MELT SNOW SNOW_LIQ",
            "Overflow": "OVERFLOW_RAVEN SNOW_LIQ PONDED_WATER",
            "Infiltration": "INF_HBV PONDED_WATER MULTIPLE",
            "SoilEvaporation": "SOILEVAP_HBV SOIL[0] ATMOSPHERE",
            "CapillaryRise": "CRISE_HBV FAST_RESERVOIR SOIL[0]",
            "LakeEvaporation": "LAKE_EVAP_BASIC SLOW_RESERVOIR ATMOSPHERE",
            "Percolation": "PERC_CONSTANT FAST_RESERVOIR SLOW_RESERVOIR",
            "Baseflow": "BASE_POWER_LAW FAST_RESERVOIR SURFACE_WATER",
            "Baseflow_2": "BASE_LINEAR SLOW_RESERVOIR SURFACE_WATER",
            # LateralEquilibrate dropped: names HRU group AllHRUs, which needs
            # :DefineHRUGroups in .rvi + :HRUGroup membership in .rvh. Neither tool
            # emits them, so Raven aborts at ParseInput.cpp:3078. No-op when lumped.
        },
        "aliases": {
            "FAST_RESERVOIR": "SOIL[1]",
            "SLOW_RESERVOIR": "SOIL[2]",
        },
        "soil_model": "SOIL_MULTILAYER 3",
        "routing": "ROUTE_NONE",
        "catchment_route": "ROUTE_TRI_CONVOLUTION",
        "evaporation": "PET_OUDIN",  # manual F.2 says PET_FROMMONTHLY; needs :MonthlyAveEvaporation (Gauge.cpp:242)
        "parameters": {
            "MELT_FACTOR": {"default": 4.0, "min": 1.0, "max": 8.0, "unit": "mm/d/degC", "desc": "Degree-day snowmelt factor"},
            "REFREEZE_FACTOR": {"default": 2.0, "min": 0.0, "max": 5.0, "unit": "mm/d/degC", "desc": "Refreezing factor"},
            "HBV_BETA": {"default": 2.0, "min": 0.5, "max": 6.0, "unit": "-", "desc": "Soil moisture nonlinearity"},
            "FC": {"default": 200.0, "min": 50.0, "max": 500.0, "unit": "mm", "desc": "Field capacity"},
            "MAX_PERC_RATE": {"default": 2.0, "min": 0.1, "max": 10.0, "unit": "mm/d", "desc": "Max percolation rate"},
            "K1": {"default": 0.1, "min": 0.01, "max": 0.5, "unit": "1/d", "desc": "Upper zone recession"},
            "K2": {"default": 0.01, "min": 0.001, "max": 0.1, "unit": "1/d", "desc": "Lower zone recession"},
        },
        "forcing_minimum": ["PRECIP", "TEMP_MIN", "TEMP_MAX"],
    },

    "hmets": {
        "full_name": "HMETS (Hydrological Model - Ecole de Technologie Superieure)",
        "level": "Level 1",
        "reference": "Martel et al., 2017",
        "n_params": 21,
        "description": "Canadian hybrid multi-model with advanced snow. Good for cold regions.",
        "climate_suitability": ["cold", "alpine", "continental", "semi_humid"],
        "data_requirement": "moderate",
        "snow_capable": True,
        "soil_layers": 2,
        # From Raven User Manual Appendix F.7 — HMETS Configuration (exact copy)
        "processes": {
            "SnowBalance": "SNOBAL_HMETS MULTIPLE MULTIPLE",
            "Precipitation": "RAVEN_DEFAULT ATMOS_PRECIP MULTIPLE",
            "Infiltration": "INF_HMETS PONDED_WATER MULTIPLE",
            "Overflow": "OVERFLOW_RAVEN SOIL[0] CONVOLUTION[1]",
            "Baseflow": "BASE_LINEAR SOIL[0] SURFACE_WATER",
            "Percolation": "PERC_LINEAR SOIL[0] SOIL[1]",
            "Overflow_2": "OVERFLOW_RAVEN SOIL[1] CONVOLUTION[1]",
            "SoilEvaporation": "SOILEVAP_ALL SOIL[0] ATMOSPHERE",
            "Convolve": "CONVOL_GAMMA CONVOLUTION[0] SURFACE_WATER",
            "Convolve_2": "CONVOL_GAMMA_2 CONVOLUTION[1] SURFACE_WATER",
            "Baseflow_2": "BASE_LINEAR SOIL[1] SURFACE_WATER",
        },
        "extra_options": [":AllowSoilOverfill"],
        "soil_model": "SOIL_TWO_LAYER",
        "routing": "ROUTE_NONE",
        "catchment_route": "ROUTE_GAMMA_CONVOLUTION",
        "evaporation": "PET_OUDIN",
        "parameters": {
            "HMETS_RUNOFF_COEFF": {"default": 0.3, "min": 0.0, "max": 1.0, "unit": "-", "desc": "Runoff coefficient", "type": "LandUseParameter"},
            "GAMMA_SHAPE": {"default": 3.0, "min": 0.1, "max": 20.0, "unit": "-", "desc": "Gamma shape for UH", "type": "LandUseParameter"},
            "GAMMA_SCALE": {"default": 0.5, "min": 0.01, "max": 5.0, "unit": "d", "desc": "Gamma scale for UH", "type": "LandUseParameter"},
            "DD_MELT_TEMP": {"default": 0.0, "min": -5.0, "max": 5.0, "unit": "degC", "desc": "Melt threshold temperature"},
            "DD_MELT_FACTOR": {"default": 3.0, "min": 0.5, "max": 10.0, "unit": "mm/d/degC", "desc": "Degree-day melt factor"},
            "MIN_MELT_FACTOR": {"default": 1.0, "min": 0.0, "max": 5.0, "unit": "mm/d/degC", "desc": "Min melt factor"},
            "MAX_MELT_FACTOR": {"default": 5.0, "min": 2.0, "max": 15.0, "unit": "mm/d/degC", "desc": "Max melt factor"},
            "DD_REFREEZE_FACTOR": {"default": 1.0, "min": 0.0, "max": 5.0, "unit": "mm/d/degC", "desc": "Refreeze factor"},
            "DD_AGGRADATION": {"default": 0.0, "min": 0.0, "max": 1.0, "unit": "-", "desc": "Snow aggradation fraction"},
            "GAMMA_SHAPE2": {"default": 3.0, "min": 0.1, "max": 20.0, "unit": "-", "desc": "Gamma shape for UH2 (CONVOL_GAMMA_2)", "type": "LandUseParameter"},
            "GAMMA_SCALE2": {"default": 0.5, "min": 0.01, "max": 5.0, "unit": "d", "desc": "Gamma scale for UH2 (CONVOL_GAMMA_2)", "type": "LandUseParameter"},
            "SWI_REDUCT_COEFF": {"default": 0.5, "min": 0.0, "max": 1.0, "unit": "-", "desc": "SWI reduction coefficient", "type": "GlobalParameter"},
            "SNOW_SWI": {"default": 0.05, "min": 0.0, "max": 0.3, "unit": "-", "desc": "Snow water equivalent fraction for liquid", "type": "GlobalParameter"},
        },
        "forcing_minimum": ["PRECIP", "TEMP_MIN", "TEMP_MAX"],
    },

    "mohyse": {
        "full_name": "MOHYSE (Modele Hydrologique Simplifie)",
        "level": "Level 1",
        "reference": "Fortin & Turcotte, 2007",
        "n_params": 10,
        "description": "Simple 10-parameter model. Fast calibration, good baseline.",
        "climate_suitability": ["humid", "semi_humid"],
        "data_requirement": "minimal",
        "snow_capable": True,
        "soil_layers": 2,
        # From Raven User Manual Appendix F.6 — MOHYSE Configuration (exact copy)
        # Note: manual specifies :DirectEvaporation and :RainSnowFraction RAINSNOW_DATA
        "processes": {
            "SoilEvaporation": "SOILEVAP_LINEAR SOIL[0] ATMOSPHERE",
            "SnowBalance": "SNOBAL_SIMPLE_MELT SNOW PONDED_WATER",
            "Precipitation": "RAVEN_DEFAULT ATMOS_PRECIP MULTIPLE",
            "Infiltration": "INF_HBV PONDED_WATER SOIL[0]",
            "Baseflow": "BASE_LINEAR SOIL[0] SURFACE_WATER",
            "Percolation": "PERC_LINEAR SOIL[0] SOIL[1]",
            "Baseflow_2": "BASE_LINEAR SOIL[1] SURFACE_WATER",
        },
        "extra_options": [":DirectEvaporation"],
        "soil_model": "SOIL_TWO_LAYER",
        "routing": "ROUTE_NONE",
        "catchment_route": "ROUTE_GAMMA_CONVOLUTION",
        "evaporation": "PET_MOHYSE",
        "parameters": {
            "MOHYSE_PET_COEFF": {"default": 1.0, "min": 0.1, "max": 3.0, "unit": "-", "desc": "PET correction factor"},
            "MELT_FACTOR": {"default": 3.0, "min": 0.5, "max": 10.0, "unit": "mm/d/degC", "desc": "Degree-day melt factor"},
        },
        "forcing_minimum": ["PRECIP", "TEMP_MIN", "TEMP_MAX"],
    },

    "sac_sma": {
        "full_name": "Sacramento Soil Moisture Accounting (SAC-SMA)",
        "level": "Level 1",
        "reference": "Burnash, 1973; NWS RFC",
        "n_params": 16,
        "description": "US National Weather Service operational model. Complex soil moisture accounting.",
        "climate_suitability": ["humid", "semi_humid", "semi_arid", "continental"],
        "data_requirement": "moderate",
        "snow_capable": True,  # includes SNOBAL_SIMPLE_MELT per F.11
        "soil_layers": 7,
        # From Raven User Manual Appendix F.11 — SAC-SMA Configuration (exact copy)
        # Aliases: UZ_T=SOIL[0], UZ_F=SOIL[1], LZ_T=SOIL[2], LZ_PF=SOIL[3], LZ_PS=SOIL[4]
        # SOIL_MULTILAYER 7 per manual (7 soil layers total)
        "processes": {
            "SnowBalance": "SNOBAL_SIMPLE_MELT SNOW PONDED_WATER",
            "Precipitation": "RAVEN_DEFAULT ATMOS_PRECIP MULTIPLE",
            "SoilEvaporation": "SOILEVAP_SACSMA MULTIPLE ATMOSPHERE",
            "SoilBalance": "SOILBAL_SACSMA MULTIPLE MULTIPLE",
            "OpenWaterEvaporation": "OPEN_WATER_RIPARIAN SURFACE_WATER ATMOSPHERE",
        },
        "aliases": {
            "UZ_T": "SOIL[0]",
            "UZ_F": "SOIL[1]",
            "LZ_T": "SOIL[2]",
            "LZ_PF": "SOIL[3]",
            "LZ_PS": "SOIL[4]",
        },
        "soil_model": "SOIL_MULTILAYER 7",
        "routing": "ROUTE_NONE",
        "catchment_route": "ROUTE_DUMP",
        "evaporation": "PET_OUDIN",  # manual F.4/F.11 says PET_DATA; needs :Data PET in .rvt (Gauge.cpp:279)
        "parameters": {
            "SAC_UZTWM": {"default": 50.0, "min": 1.0, "max": 150.0, "unit": "mm", "desc": "Upper zone tension water max"},
            "SAC_UZFWM": {"default": 40.0, "min": 1.0, "max": 150.0, "unit": "mm", "desc": "Upper zone free water max"},
            "SAC_LZTWM": {"default": 130.0, "min": 1.0, "max": 500.0, "unit": "mm", "desc": "Lower zone tension water max"},
            "SAC_LZFPM": {"default": 40.0, "min": 1.0, "max": 1000.0, "unit": "mm", "desc": "Lower zone primary free water max"},
            "SAC_LZFSM": {"default": 25.0, "min": 1.0, "max": 400.0, "unit": "mm", "desc": "Lower zone supplemental free water max"},
            "SAC_UZK": {"default": 0.3, "min": 0.1, "max": 0.75, "unit": "1/d", "desc": "Upper zone depletion rate"},
            "SAC_LZPK": {"default": 0.01, "min": 0.001, "max": 0.05, "unit": "1/d", "desc": "Lower zone primary depletion rate"},
            "SAC_LZSK": {"default": 0.05, "min": 0.01, "max": 0.25, "unit": "1/d", "desc": "Lower zone supplemental depletion rate"},
            "SAC_PFREE": {"default": 0.06, "min": 0.0, "max": 0.8, "unit": "-", "desc": "Percolation fraction"},
        },
        "forcing_minimum": ["PRECIP", "TEMP_MIN", "TEMP_MAX"],
    },

    "hymod": {
        "full_name": "HYMOD (Hydrological Model)",
        "level": "Level 1",
        "reference": "Boyle, 2001; Wagener et al., 2001",
        "n_params": 5,
        "description": "Simple 5-parameter conceptual model. Excellent for benchmarking.",
        "climate_suitability": ["humid", "semi_humid"],
        "data_requirement": "minimal",
        "snow_capable": True,  # includes SNOBAL_SIMPLE_MELT per F.9
        "soil_layers": 2,
        # From Raven User Manual Appendix F.9 — HYMOD/HYMOD2 Configuration (exact copy)
        # SOIL_MULTILAYER 2; SOIL[0]=soil store, SOIL[1]=slow reservoir
        "processes": {
            "Precipitation": "PRECIP_RAVEN ATMOS_PRECIP MULTIPLE",
            "SnowBalance": "SNOBAL_SIMPLE_MELT SNOW PONDED_WATER",
            "Infiltration": "INF_PDM PONDED_WATER MULTIPLE",
            "Flush": "RAVEN_DEFAULT SURFACE_WATER SOIL[1] 0.5",
            "SoilEvaporation": "SOILEVAP_PDM SOIL[0] ATMOSPHERE",
            "Baseflow": "BASE_LINEAR SOIL[1] SURFACE_WATER",
        },
        "soil_model": "SOIL_MULTILAYER 2",
        "routing": "ROUTE_NONE",
        "catchment_route": "ROUTE_RESERVOIR_SERIES",
        "evaporation": "PET_HAMON",
        "parameters": {
            "HYMOD_CMAX": {"default": 200.0, "min": 1.0, "max": 1000.0, "unit": "mm", "desc": "Max soil moisture capacity"},
            "HYMOD_B": {"default": 0.5, "min": 0.0, "max": 2.0, "unit": "-", "desc": "Spatial variability index"},
            "HYMOD_ALPHA": {"default": 0.7, "min": 0.0, "max": 1.0, "unit": "-", "desc": "Quick/slow flow partition (Flush fraction)"},
            "HYMOD_KS": {"default": 0.01, "min": 0.001, "max": 0.1, "unit": "1/d", "desc": "Slow reservoir rate"},
            "HYMOD_KQ": {"default": 0.3, "min": 0.1, "max": 0.99, "unit": "1/d", "desc": "Quick reservoir rate"},
        },
        "forcing_minimum": ["PRECIP", "TEMP_MIN", "TEMP_MAX"],
    },

    "ubc": {
        "full_name": "UBC Watershed Model",
        "level": "Level 1",
        "reference": "Quick, 1995; University of British Columbia",
        "n_params": 20,
        "description": "UBC model with elevation band discretization. Best for mountainous snow basins.",
        "climate_suitability": ["cold", "alpine", "continental"],
        "data_requirement": "moderate",
        "snow_capable": True,
        "soil_layers": 6,
        # From Raven User Manual Appendix F.1 — UBC Watershed Model Emulation (exact copy)
        # Aliases: TOP_SOIL=SOIL[0], INT_SOIL=SOIL[1], SHALLOW_GW=SOIL[2],
        #          DEEP_GW=SOIL[3], INT_SOIL2=SOIL[4], INT_SOIL3=SOIL[5]
        "processes": {
            "SnowAlbedoEvolve": "SNOALB_UBCWM",
            "SnowBalance": "SNOBAL_UBCWM MULTIPLE MULTIPLE",
            "Precipitation": "PRECIP_RAVEN ATMOS_PRECIP MULTIPLE",
            "SoilEvaporation": "SOILEVAP_UBC MULTIPLE ATMOSPHERE",
            "Infiltration": "INF_UBC PONDED_WATER MULTIPLE",
            "Percolation": "PERC_LINEAR_ANALYTIC INT_SOIL INT_SOIL2",
            "Percolation_2": "PERC_LINEAR_ANALYTIC INT_SOIL2 INT_SOIL3",
            "Baseflow": "BASE_LINEAR INT_SOIL3 SURFACE_WATER",
            "Baseflow_2": "BASE_LINEAR SHALLOW_GW SURFACE_WATER",
            "Baseflow_3": "BASE_LINEAR DEEP_GW SURFACE_WATER",
            "GlacierRelease": "GRELEASE_LINEAR GLACIER SURFACE_WATER",
        },
        "aliases": {
            "TOP_SOIL": "SOIL[0]",
            "INT_SOIL": "SOIL[1]",
            "SHALLOW_GW": "SOIL[2]",
            "DEEP_GW": "SOIL[3]",
            "INT_SOIL2": "SOIL[4]",
            "INT_SOIL3": "SOIL[5]",
        },
        "soil_model": "SOIL_MULTILAYER 6",
        "routing": "ROUTE_NONE",
        "catchment_route": "ROUTE_DUMP",
        "evaporation": "PET_OUDIN",  # manual F.1 says PET_MONTHLY_FACTOR; needs :MonthlyAveEvaporation (Gauge.cpp:242)
        "parameters": {
            "UBC_P0AGEN": {"default": 12.0, "min": 1.0, "max": 30.0, "unit": "d", "desc": "Gradient time constant"},
        },
        "forcing_minimum": ["PRECIP", "TEMP_MIN", "TEMP_MAX"],
    },

    "hypr": {
        "full_name": "HYPR (Hybrid Prediction for Prairies)",
        "level": "Level 1",
        "reference": "Ahmed et al., 2020",
        "n_params": 9,
        "description": "Hybrid model tuned for Canadian prairies (pothole/depression storage).",
        "climate_suitability": ["cold", "continental", "semi_arid"],
        "data_requirement": "moderate",
        "snow_capable": True,
        "soil_layers": 3,
        "processes": {
            "Precipitation": "PRECIP_RAVEN ATMOS_PRECIP MULTIPLE",
            "SnowBalance": "SNOBAL_HBV MULTIPLE MULTIPLE",
            "Infiltration": "INF_HBV PONDED_WATER MULTIPLE",
            "SoilEvaporation": "SOILEVAP_HBV SOIL[0] ATMOSPHERE",
            "Percolation": "PERC_LINEAR SOIL[0] SOIL[1]",
            "Baseflow": "BASE_LINEAR SOIL[0] SURFACE_WATER",
            "Baseflow_2": "BASE_POWER_LAW SOIL[1] SURFACE_WATER",
        },
        "soil_model": "SOIL_MULTILAYER 3",
        "routing": "ROUTE_NONE",  # ROUTE_DIFFUSIVE_WAVE needs :ChannelProfile in .rvp
        "catchment_route": "ROUTE_TRI_CONVOLUTION",
        "evaporation": "PET_PRIESTLEY_TAYLOR",
        "parameters": {
            "MELT_FACTOR": {"default": 5.0, "min": 1.0, "max": 10.0, "unit": "mm/d/degC", "desc": "Degree-day melt factor"},
            "HBV_BETA": {"default": 1.5, "min": 0.5, "max": 5.0, "unit": "-", "desc": "Soil moisture nonlinearity"},
        },
        "forcing_minimum": ["PRECIP", "TEMP_MIN", "TEMP_MAX"],
    },
}

# Climate-based recommendation matrix
CLIMATE_RECOMMENDATIONS = {
    "humid": ["gr4j", "hymod", "hbv_ec", "sac_sma"],
    "semi_humid": ["hbv_ec", "gr4j", "hmets", "sac_sma"],
    "semi_arid": ["sac_sma", "hbv_ec", "hypr"],
    "arid": ["sac_sma"],
    "cold": ["hbv_ec", "hmets", "ubc", "hypr"],
    "alpine": ["ubc", "hbv_ec", "hmets"],
    "tropical": ["gr4j", "hymod", "sac_sma"],
    "continental": ["hbv_ec", "hmets", "sac_sma", "hypr"],
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.template and args.template not in TEMPLATES:
        errors.append(f"Unknown template '{args.template}'. Available: {', '.join(TEMPLATES.keys())}")

    if args.recommend and not args.climate:
        errors.append("--climate is required when using --recommend")

    if args.climate and args.climate not in CLIMATE_RECOMMENDATIONS:
        errors.append(f"Unknown climate '{args.climate}'. Available: {', '.join(CLIMATE_RECOMMENDATIONS.keys())}")

    if not args.output_dir:
        errors.append("--output_dir is required")

    if not args.basin_name:
        errors.append("--basin_name is required")

    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def read_hru_elevations(rvh_path):
    """Return the list of HRU elevations (m) declared in a .rvh file."""
    elevs = []
    if not (rvh_path and os.path.isfile(rvh_path)):
        return elevs
    in_hrus = False
    cols = None
    for raw in open(rvh_path):
        s = raw.strip()
        if s.startswith(":HRUs"):
            in_hrus = True
            continue
        if s.startswith(":EndHRUs"):
            break
        if not in_hrus or not s or s.startswith("#"):
            continue
        toks = [t.strip() for t in s.split(",")]
        if s.startswith(":Attributes"):
            cols = toks  # toks[0] == ":Attributes"; HRU id occupies that slot
            continue
        if s.startswith(":Units") or s.startswith(":"):
            continue
        if cols and "ELEVATION" in cols:
            j = cols.index("ELEVATION")
            if j < len(toks):
                try:
                    elevs.append(float(toks[j]))
                except ValueError:
                    pass
    return elevs


def resolve_pet_method(tmpl, rvt_path, pet_method="auto"):
    """Decide the :Evaporation method actually written to the .rvi.

    Appendix-F reference for most emulations is PET_OUDIN, a temperature-index
    formula with no radiation term. In a cold HIGH-ELEVATION basin Oudin
    systematically UNDER-estimates PET, so the calibrator has to buy the
    missing evaporation back through soil parameters (dt_rav_039). When the
    forcing .rvt actually carries SHORTWAVE, Priestley-Taylor is the physically
    grounded choice and is used instead.

    pet_method: "auto" (default), "template" (keep Appendix F verbatim), or an
    explicit Raven method name (e.g. PET_HARGREAVES).
    """
    reference = tmpl["evaporation"]
    if pet_method and pet_method not in ("auto", "template"):
        return pet_method, reference, True, f"explicitly requested {pet_method}"
    if pet_method == "template":
        return reference, reference, False, "Appendix-F reference kept verbatim"

    has_shortwave = False
    if rvt_path and os.path.isfile(rvt_path):
        try:
            head = open(rvt_path, errors="ignore").read(400000)
            has_shortwave = ":Data SHORTWAVE" in head or ":Data SW_RADIA" in head
        except Exception:
            has_shortwave = False

    if reference == "PET_OUDIN" and has_shortwave:
        return ("PET_PRIESTLEY_TAYLOR", reference, True,
                "forcing carries SHORTWAVE; Oudin has no radiation term and "
                "under-estimates PET in cold high-elevation basins (dt_rav_039)")
    return reference, reference, False, (
        "no SHORTWAVE in forcing — temperature-index reference retained"
        if reference == "PET_OUDIN" else "template reference requires no substitution")


# PET methods that consume net radiation, and therefore care which shortwave
# the model uses.
_RADIATION_PET = ("PET_PRIESTLEY_TAYLOR", "PET_PENMAN_MONTEITH",
                  "PET_PENMAN_COMBINATION", "PET_TURC_1961", "PET_MAKKINK_1957")


def resolve_sw_radiation(pet_resolved, rvt_path):
    """Decide whether Raven should USE the shortwave supplied in the .rvt.

    Raven's default is SW_RAD_DEFAULT: it computes clear-sky shortwave from
    latitude and date and, with the default CLOUDCOV_NONE, applies NO cloud
    attenuation. Any :Data SHORTWAVE in the .rvt is then silently discarded --
    Raven says so ("SW_RADIA data supplied at gauge ... but will not be used
    due to choice of forcing generation algorithm") but the run still succeeds.
    For a radiation-based PET that means potential evaporation is driven by
    clear-sky radiation every single day, which over-evaporates a cloudy
    monsoon-fed alpine basin (dt_rav_041).

    :SWRadiationMethod SW_RAD_DATA makes Raven use the measured/reanalysis
    shortwave actually present in the forcing (and sets cloud correction to
    NONE itself, ParseInput.cpp:3696).
    """
    if pet_resolved not in _RADIATION_PET:
        return {"applied": False, "reason": f"{pet_resolved} does not use radiation"}
    has_shortwave = False
    if rvt_path and os.path.isfile(rvt_path):
        try:
            head = open(rvt_path, errors="ignore").read(400000)
            has_shortwave = ":Data SHORTWAVE" in head or ":Data SW_RADIA" in head
        except Exception:
            has_shortwave = False
    if not has_shortwave:
        return {"applied": False,
                "reason": "no SHORTWAVE in the .rvt — Raven's clear-sky estimate is all there is"}
    return {"applied": True, "method": "SW_RAD_DATA",
            "reason": "forcing supplies SHORTWAVE; without SW_RAD_DATA Raven "
                      "discards it and drives PET with clear-sky radiation (dt_rav_041)"}


def resolve_orographic(elevations, gauge_elev=None, mode="auto", min_relief_m=100.0):
    """Decide whether the .rvi needs orographic (lapse) corrections.

    Raven defaults orocorr_temp / orocorr_precip / orocorr_PET to OROCORR_NONE
    (ParseInput.cpp:260-262). With no :OroTempCorrect directive EVERY HRU is
    forced with the gauge's own temperature regardless of its ELEVATION, so an
    elevation-band .rvh built by s1 is SILENTLY INERT: five bands spanning
    2.5 km of relief see one identical temperature and one identical
    precipitation series. In a snow-dominated alpine basin that removes the
    accumulation/melt gradient that drives the hydrograph (dt_rav_040).

    OROCORR_SIMPLELAPSE lapses temperature by ADIABATIC_LAPSE [C/km] and
    precipitation by PRECIP_LAPSE [mm/d/km] against the gauge reference
    elevation (OrographicCorrections.cpp:32, :223). Both globals are declared
    required by Raven once the directive is present, so s2 emits them
    automatically and s9 can calibrate them.

    NOTE: :OroPETCorrect does NOT accept OROCORR_SIMPLELAPSE (ParseInput.cpp
    case 18 takes only HBV/PRMS/UBCWM/NONE), so PET correction is left at its
    default; PET is already recomputed per HRU from the lapsed temperature.
    """
    relief = (max(elevations) - min(elevations)) if len(elevations) > 1 else 0.0
    if mode == "none":
        return {"applied": False, "method": None, "relief_m": round(relief, 1),
                "reason": "disabled by --orographic none"}
    if mode == "simple" or (mode == "auto" and relief >= min_relief_m):
        return {"applied": True, "method": "OROCORR_SIMPLELAPSE",
                "relief_m": round(relief, 1), "n_hrus": len(elevations),
                "gauge_elevation_m": gauge_elev,
                "reason": f"HRU relief {relief:.0f} m >= {min_relief_m:.0f} m — "
                          "without lapse correction every band shares one forcing"}
    return {"applied": False, "method": None, "relief_m": round(relief, 1),
            "reason": f"HRU relief {relief:.0f} m < {min_relief_m:.0f} m — lumped forcing is adequate"}


def read_gauge_elevation(rvt_path):
    """Reference elevation of the forcing gauge declared in the .rvt."""
    if not (rvt_path and os.path.isfile(rvt_path)):
        return None
    for raw in open(rvt_path, errors="ignore"):
        s = raw.strip()
        if s.startswith(":Elevation"):
            try:
                return float(s.split()[1])
            except (IndexError, ValueError):
                return None
        if s.startswith(":Data"):
            break
    return None


def generate_rvi_content(template_name, basin_name, start_date="2000-01-01",
                          end_date="2010-12-31", timestep="1.0",
                          pet_method="auto", orographic="auto", run_dir=None):
    """Generate .rvi file content from a template.

    Returns (content, meta) where meta records the PET and orographic decisions.
    """
    tmpl = TEMPLATES[template_name]
    rvh_path = os.path.join(run_dir, f"{basin_name}.rvh") if run_dir else None
    rvt_path = os.path.join(run_dir, f"{basin_name}.rvt") if run_dir else None

    pet_resolved, pet_reference, pet_substituted, pet_reason = resolve_pet_method(
        tmpl, rvt_path, pet_method)
    oro = resolve_orographic(read_hru_elevations(rvh_path),
                             read_gauge_elevation(rvt_path), orographic)
    sw = resolve_sw_radiation(pet_resolved, rvt_path)
    meta = {
        "pet": {"requested": pet_method, "template_reference": pet_reference,
                "resolved": pet_resolved, "substituted": pet_substituted,
                "reason": pet_reason},
        "orographic": oro,
        "sw_radiation": sw,
    }

    lines = []
    lines.append(f"# Raven .rvi file — {tmpl['full_name']} emulation")
    lines.append(f"# Generated by HydroCraft select_model_template.py")
    lines.append(f"# Template: {template_name} ({tmpl['reference']})")
    lines.append(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # Model structure
    lines.append(f":StartDate       {start_date} 00:00:00")
    lines.append(f":EndDate         {end_date} 00:00:00")
    lines.append(f":TimeStep        {timestep}")
    lines.append("")

    # Evaporation and snow — template-specific methods per Appendix F
    if pet_substituted:
        lines.append(f"# :Evaporation substituted: Appendix-F reference is "
                     f"{pet_reference}. {pet_reason}. --pet_method template restores it.")
    lines.append(f":Evaporation     {pet_resolved}")
    lines.append(f":OW_Evaporation  {pet_resolved}")
    if sw.get("applied"):
        lines.append(f"# {sw['reason']}")
        lines.append(f":SWRadiationMethod {sw['method']}")

    # Template-specific RainSnowFraction (manual Appendix F)
    rain_snow_map = {
        "ubc": "RAINSNOW_UBCWM",
        "hbv_ec": "RAINSNOW_HBV",
        "mohyse": "RAINSNOW_DINGMAN",  # manual F.6 says RAINSNOW_DATA; needs :Data SNOWFALL (Gauge.cpp:111)
        "sac_sma": "RAINSNOW_DINGMAN",  # manual F.11 says RAINSNOW_DATA; needs :Data SNOWFALL (Gauge.cpp:111)
        "hymod": "RAINSNOW_THRESHOLD",
    }
    rain_snow = rain_snow_map.get(template_name, "RAINSNOW_DINGMAN")
    lines.append(f":RainSnowFraction {rain_snow}")

    # Template-specific PotentialMeltMethod (manual Appendix F)
    melt_map = {
        "hmets": "POTMELT_HMETS",
        "ubc": "POTMELT_UBCWM",
        "hbv_ec": "POTMELT_HBV",
    }
    melt_method = melt_map.get(template_name, "POTMELT_DEGREE_DAY")
    lines.append(f":PotentialMeltMethod {melt_method}")

    # Orographic corrections — REQUIRED whenever the .rvh has elevation bands.
    # Raven's default is OROCORR_NONE, which silently forces every band with
    # the gauge's own temperature/precipitation (dt_rav_040).
    if oro.get("applied"):
        lines.append(f"# Orographic lapse ON: {oro['reason']} "
                     f"(gauge ref {oro.get('gauge_elevation_m')} m, "
                     f"{oro.get('n_hrus')} HRUs). ADIABATIC_LAPSE / PRECIP_LAPSE "
                     f"are emitted by s2 and calibrated by s9.")
        lines.append(f":OroTempCorrect   {oro['method']}")
        lines.append(f":OroPrecipCorrect {oro['method']}")
    lines.append("")

    # Extra options (e.g., :AllowSoilOverfill for HMETS, :DirectEvaporation for MOHYSE)
    for opt in tmpl.get("extra_options", []):
        lines.append(opt)

    # Soil model
    lines.append(f":SoilModel       {tmpl['soil_model']}")
    lines.append("")

    # Routing
    lines.append(f":Routing         {tmpl['routing']}")
    lines.append(f":CatchmentRoute  {tmpl['catchment_route']}")
    lines.append("")

    # Aliases (for templates that use named soil compartments)
    if "aliases" in tmpl:
        for alias_name, alias_target in tmpl["aliases"].items():
            lines.append(f":Alias {alias_name} {alias_target}")
        lines.append("")

    # Hydrologic processes
    lines.append(":HydrologicProcesses")
    for proc_name, proc_def in tmpl["processes"].items():
        # Strip trailing _2, _3 etc. from process names (used for duplicate keys in dict)
        # e.g., "Overflow_2" -> "Overflow", "Baseflow_2" -> "Baseflow"
        raven_name = proc_name.rsplit('_', 1)[0] if proc_name[-1].isdigit() and '_' in proc_name else proc_name
        lines.append(f"  :{raven_name}  {proc_def}")
    lines.append(":EndHydrologicProcesses")
    lines.append("")

    # Output options
    lines.append("# --- Output Options ---")
    lines.append(":EvaluationMetrics NASH_SUTCLIFFE KLING_GUPTA PCT_BIAS RMSE")
    lines.append(":WriteHydrographs")
    lines.append(":WriteForcingFunctions")
    # NOTE: Raven.exe is built WITHOUT NetCDF (-Dnetcdf disabled in Makefile).
    # Emitting :WriteNetcdfFormat yes makes CustomOutput write 0-byte .nc files
    # and suppresses the CSV equivalents. Leave it off so CustomOutput -> CSV.
    lines.append(":SilentMode")
    lines.append(f":RunName          {basin_name}_{template_name}")
    lines.append("")

    # Custom output for water balance
    lines.append(":CustomOutput DAILY AVERAGE PRECIP BY_BASIN")
    lines.append(":CustomOutput DAILY AVERAGE AET BY_BASIN")
    lines.append("")

    return "\n".join(lines), meta


def process(args):
    """Main processing: select template and generate .rvi file."""
    results = {}

    # Determine template
    if args.recommend:
        climate = args.climate
        recommended = CLIMATE_RECOMMENDATIONS.get(climate, [])

        # Filter by snow capability if specified
        if args.snow_dominated and args.snow_dominated.lower() == "true":
            recommended = [t for t in recommended if TEMPLATES[t]["snow_capable"]]

        results["recommendation"] = {
            "climate": climate,
            "recommended_templates": recommended,
            "details": {t: {
                "full_name": TEMPLATES[t]["full_name"],
                "n_params": TEMPLATES[t]["n_params"],
                "description": TEMPLATES[t]["description"],
                "snow_capable": TEMPLATES[t]["snow_capable"],
            } for t in recommended}
        }

        if not args.template:
            args.template = recommended[0] if recommended else "hbv_ec"
            results["auto_selected"] = args.template

    template_name = args.template
    tmpl = TEMPLATES[template_name]

    # Generate .rvi file. The .rvh / .rvt already staged in --output_dir tell us
    # the basin's relief and whether radiation forcing exists, so the PET and
    # orographic decisions are made from the ACTUAL site, not from a default.
    rvi_content, rvi_meta = generate_rvi_content(
        template_name, args.basin_name,
        start_date=args.start_date or "2000-01-01",
        end_date=args.end_date or "2010-12-31",
        timestep=args.timestep or "1.0",
        pet_method=getattr(args, "pet_method", "auto"),
        orographic=getattr(args, "orographic", "auto"),
        run_dir=args.output_dir,
    )
    results.update(rvi_meta)

    os.makedirs(args.output_dir, exist_ok=True)
    rvi_path = os.path.join(args.output_dir, f"{args.basin_name}.rvi")

    with open(rvi_path, "w") as f:
        f.write(rvi_content)

    results["template"] = {
        "name": template_name,
        "full_name": tmpl["full_name"],
        "level": tmpl["level"],
        "reference": tmpl["reference"],
        "n_params": tmpl["n_params"],
        "description": tmpl["description"],
        "soil_layers": tmpl["soil_layers"],
        "snow_capable": tmpl["snow_capable"],
        "forcing_minimum": tmpl["forcing_minimum"],
        "parameters": tmpl["parameters"],
    }
    results["output_rvi"] = rvi_path
    results["status"] = "success"

    return results


def validate_outputs(results, args):
    """Validate generated output files."""
    errors = []

    rvi_path = results.get("output_rvi")
    if rvi_path and not os.path.isfile(rvi_path):
        errors.append(f"Expected .rvi file not found: {rvi_path}")
    elif rvi_path:
        with open(rvi_path) as f:
            content = f.read()
        if ":HydrologicProcesses" not in content:
            errors.append(".rvi file missing :HydrologicProcesses block")
        if ":StartDate" not in content:
            errors.append(".rvi file missing :StartDate")

    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def main():
    parser = argparse.ArgumentParser(description="Select Raven emulation template")
    parser.add_argument("--template", type=str, help="Template name (gr4j, hbv_ec, hmets, mohyse, sac_sma, hymod, ubc, hypr)")
    parser.add_argument("--recommend", action="store_true", help="Auto-recommend based on basin characteristics")
    parser.add_argument("--climate", type=str, help="Climate type (humid, semi_humid, semi_arid, arid, cold, alpine, tropical, continental)")
    parser.add_argument("--area_km2", type=float, help="Basin area in km2")
    parser.add_argument("--snow_dominated", type=str, help="Is the basin snow-dominated? (true/false)")
    parser.add_argument("--output_dir", type=str, required=True, help="Output directory for .rvi file")
    parser.add_argument("--basin_name", type=str, required=True, help="Basin name (used for file prefix)")
    parser.add_argument("--start_date", type=str, default="2000-01-01", help="Simulation start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", type=str, default="2010-12-31", help="Simulation end date (YYYY-MM-DD)")
    parser.add_argument("--timestep", type=str, default="1.0", help="Timestep in days (default: 1.0)")
    parser.add_argument("--pet_method", type=str, default="auto",
                        help="PET method: auto (substitute Oudin->Priestley-Taylor when "
                             "SHORTWAVE forcing exists), template (Appendix F verbatim), "
                             "or an explicit Raven method name")
    parser.add_argument("--orographic", type=str, default="auto",
                        choices=["auto", "none", "simple"],
                        help="Orographic lapse corrections: auto (on when the .rvh has "
                             "relief >= 100 m), simple (force on), none (force off)")
    parser.add_argument("--list", action="store_true", help="List all available templates and exit")

    args = parser.parse_args()

    if args.list:
        for name, tmpl in TEMPLATES.items():
            print(f"  {name:12s}  {tmpl['n_params']:2d} params  {tmpl['full_name']}")
            print(f"               Climate: {', '.join(tmpl['climate_suitability'])}")
            print(f"               Snow: {'Yes' if tmpl['snow_capable'] else 'No'}  |  Forcing: {', '.join(tmpl['forcing_minimum'])}")
            print()
        sys.exit(0)

    # Validate
    validation = validate_inputs(args)
    if validation["status"] == "error":
        print(json.dumps(validation, indent=2))
        sys.exit(1)

    # Process
    try:
        results = process(args)
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(2)

    # Validate outputs
    output_validation = validate_outputs(results, args)
    if output_validation["status"] == "error":
        results["output_validation"] = output_validation
        print(json.dumps(results, indent=2))
        sys.exit(3)

    print(json.dumps(results, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
