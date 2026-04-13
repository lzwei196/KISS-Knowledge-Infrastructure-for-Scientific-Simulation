#!/usr/bin/env python3
"""
Execute the full PyAEZ pipeline (Modules I–VI) for a given study area and crop.

This wrapper script runs all 6 AEZ modules sequentially, producing yield maps,
constraint factor maps (fc1–fc5), and economic suitability results.

Usage:
    python run_pyaez.py --data-dir ./data_input --crop-name maize \
        --crop-params input_crop_TSUM_parameters_maiz_sugar.xlsx \
        --lat-min 13.87 --lat-max 22.59 \
        --output-dir ./data_output \
        --modules 1,2,3,4,5,6
"""

import argparse
import os
import sys
import time
import json
import numpy as np
from pathlib import Path


def validate_inputs(config: dict) -> list:
    """Validate all inputs before pipeline execution."""
    errors = []

    data_dir = Path(config["data_dir"])

    # Check climate arrays
    climate_files = [
        "climate/max_temp.npy", "climate/min_temp.npy",
        "climate/precipitation.npy", "climate/short_rad.npy",
        "climate/wind_speed.npy", "climate/relative_humidity.npy",
    ]
    for f in climate_files:
        fpath = data_dir / f
        if not fpath.exists():
            errors.append(f"Missing climate file: {f}")
            continue

        arr = np.load(str(fpath))
        if arr.ndim != 3:
            errors.append(f"{f}: expected 3D, got {arr.ndim}D")

    # Unit sanity checks on first available temp file
    for tfile in ["climate/max_temp.npy", "climate/min_temp.npy"]:
        fpath = data_dir / tfile
        if fpath.exists():
            arr = np.load(str(fpath))
            if np.nanmean(arr) > 100:
                errors.append(f"{tfile}: mean={np.nanmean(arr):.1f}, likely Kelvin not Celsius")
            break

    # Check humidity range
    hum_path = data_dir / "climate/relative_humidity.npy"
    if hum_path.exists():
        hum = np.load(str(hum_path))
        if np.nanmax(hum) > 1.5:
            errors.append(f"relative_humidity: max={np.nanmax(hum):.1f}, should be 0-1 fraction")

    # Check spatial files
    for raster in ["LAO_Admin.tif", "LAO_Elevation.tif"]:
        if not (data_dir / raster).exists():
            # Also check generic names
            alt_names = ["admin_mask.tif", "elevation.tif", "mask.tif", "dem.tif"]
            found = any((data_dir / a).exists() for a in alt_names)
            if not found:
                errors.append(f"Missing spatial file: {raster} (or equivalent)")

    # Check crop parameter file
    if config.get("crop_params"):
        crop_path = data_dir / config["crop_params"]
        if not crop_path.exists():
            errors.append(f"Missing crop parameter file: {config['crop_params']}")

    return errors


def run_module1_climate_regime(data_dir: Path, lat_min: float, lat_max: float,
                               output_dir: Path, daily: bool = False) -> dict:
    """
    Module I: Climate Regime Analysis.

    Computes: thermal climate, thermal zones, LGP, thermal LGP (0/5/10°C),
    temperature sums, temperature profiles (A1-A9, B1-B9), AEZ classification.
    """
    from pyaez import ClimateRegime, UtilitiesCalc

    t0 = time.time()
    print("\n=== Module I: Climate Regime ===")

    # Load data
    max_temp = np.load(str(data_dir / "climate/max_temp.npy"))
    min_temp = np.load(str(data_dir / "climate/min_temp.npy"))
    precip   = np.load(str(data_dir / "climate/precipitation.npy"))
    srad     = np.load(str(data_dir / "climate/short_rad.npy"))
    wind     = np.load(str(data_dir / "climate/wind_speed.npy"))
    humidity = np.load(str(data_dir / "climate/relative_humidity.npy"))

    from osgeo import gdal
    mask = gdal.Open(str(data_dir / "LAO_Admin.tif")).ReadAsArray()
    elev = gdal.Open(str(data_dir / "LAO_Elevation.tif")).ReadAsArray()

    # Initialize
    clim = ClimateRegime.ClimateRegime()
    clim.setStudyAreaMask(mask, 0)
    clim.setLocationTerrainData(lat_min, lat_max, elev)

    if daily:
        clim.setDailyClimateData(min_temp, max_temp, precip, srad, wind, humidity)
    else:
        clim.setMonthlyClimateData(min_temp, max_temp, precip, srad, wind, humidity)

    # Calculate all indicators
    results = {}
    results["thermal_climate"] = clim.getThermalClimate()
    results["thermal_zone"] = clim.getThermalZone()
    results["lgpt0"] = clim.getThermalLGP0()
    results["lgpt5"] = clim.getThermalLGP5()
    results["lgpt10"] = clim.getThermalLGP10()
    results["tsum0"] = clim.getTemperatureSum0()
    results["tsum5"] = clim.getTemperatureSum5()
    results["tsum10"] = clim.getTemperatureSum10()
    results["temp_profile"] = clim.getTemperatureProfile()
    results["lgp"] = clim.getLGP(Sa=100, D=1)
    results["lgp_classified"] = clim.getLGPClassified(results["lgp"])
    results["lgp_equv"] = clim.getLGPEquivalent()

    # Save outputs
    m1_dir = output_dir / "NB1"
    m1_dir.mkdir(parents=True, exist_ok=True)

    util = UtilitiesCalc.UtilitiesCalc()
    mask_path = str(data_dir / "LAO_Admin.tif")
    for name, arr in results.items():
        if isinstance(arr, np.ndarray) and arr.ndim == 2:
            util.saveRaster(mask_path, str(m1_dir / f"{name}.tif"), arr)

    elapsed = time.time() - t0
    print(f"  Module I complete in {elapsed:.1f}s")
    return results


def run_module2_crop_simulation(data_dir: Path, lat_min: float, lat_max: float,
                                 crop_params: str, crop_name: str,
                                 m1_results: dict, output_dir: Path,
                                 daily: bool = False) -> dict:
    """
    Module II: Crop Simulation.

    Iterates 365 planting dates per pixel to find maximum attainable yield.
    Produces: yield_rain, yield_irr (kg/ha), fc1, fc2 constraint factors.
    """
    from pyaez import CropSimulation

    t0 = time.time()
    print("\n=== Module II: Crop Simulation ===")

    max_temp = np.load(str(data_dir / "climate/max_temp.npy"))
    min_temp = np.load(str(data_dir / "climate/min_temp.npy"))
    precip   = np.load(str(data_dir / "climate/precipitation.npy"))
    srad     = np.load(str(data_dir / "climate/short_rad.npy"))
    wind     = np.load(str(data_dir / "climate/wind_speed.npy"))
    humidity = np.load(str(data_dir / "climate/relative_humidity.npy"))

    from osgeo import gdal
    mask = gdal.Open(str(data_dir / "LAO_Admin.tif")).ReadAsArray()
    elev = gdal.Open(str(data_dir / "LAO_Elevation.tif")).ReadAsArray()

    sim = CropSimulation.CropSimulation()
    sim.setStudyAreaMask(mask, 0)
    sim.setLocationTerrainData(lat_min, lat_max, elev)

    if daily:
        sim.setDailyClimateData(min_temp, max_temp, precip, srad, wind, humidity)
    else:
        sim.setMonthlyClimateData(min_temp, max_temp, precip, srad, wind, humidity)

    sim.readCropandCropCycleParameters(str(data_dir / crop_params), crop_name)
    sim.setSoilWaterParameters(Sa=100 * np.ones(mask.shape), pc=0.5)

    # Import LGP from Module I
    sim.ImportLGPandLGPT(lgp=m1_results["lgp"],
                         lgpt5=m1_results["lgpt5"],
                         lgpt10=m1_results["lgpt10"])

    # Simulate
    sim.simulateCropCycle(start_doy=1, end_doy=365, step_doy=1, leap_year=False)

    results = {
        "yield_rain": sim.getEstimatedYieldRainfed(),
        "yield_irr": sim.getEstimatedYieldIrrigated(),
        "start_date_rain": sim.getOptimumCycleStartDateRainfed(),
        "start_date_irr": sim.getOptimumCycleStartDateIrrigated(),
    }

    # fc1 (thermal screening) and fc2 (moisture)
    screen = sim.getThermalReductionFactor()
    results["fc1_rain"] = screen[0]
    results["fc1_irr"] = screen[1]
    results["fc2_rain"] = sim.getMoistureReductionFactor()

    # Save
    m2_dir = output_dir / "NB2"
    m2_dir.mkdir(parents=True, exist_ok=True)
    for name, arr in results.items():
        if isinstance(arr, np.ndarray):
            np.save(str(m2_dir / f"{crop_name}_{name}.npy"), arr)

    elapsed = time.time() - t0
    print(f"  Module II complete in {elapsed:.1f}s")
    return results


def run_module3_climatic_constraints(data_dir: Path, lat_min: float, lat_max: float,
                                      m1_results: dict, m2_results: dict,
                                      crop_name: str, output_dir: Path) -> dict:
    """Module III: Climatic Constraints → fc3."""
    from pyaez import ClimaticConstraints
    from osgeo import gdal

    t0 = time.time()
    print("\n=== Module III: Climatic Constraints ===")

    mask = gdal.Open(str(data_dir / "LAO_Admin.tif")).ReadAsArray()
    elev = gdal.Open(str(data_dir / "LAO_Elevation.tif")).ReadAsArray()

    max_temp = np.load(str(data_dir / "climate/max_temp.npy"))
    min_temp = np.load(str(data_dir / "climate/min_temp.npy"))
    precip   = np.load(str(data_dir / "climate/precipitation.npy"))
    srad     = np.load(str(data_dir / "climate/short_rad.npy"))
    wind     = np.load(str(data_dir / "climate/wind_speed.npy"))
    humidity = np.load(str(data_dir / "climate/relative_humidity.npy"))

    results = {}
    for condition in ["rain", "irr"]:
        fc3_file = data_dir / f"{crop_name}_fc3_{condition}_lst.xlsx"
        if not fc3_file.exists():
            print(f"  Skipping {condition}: fc3 Excel not found")
            continue

        yield_key = f"yield_{condition}"
        yield_in = m2_results[yield_key]

        clim_con = ClimaticConstraints.ClimaticConstraints(
            lat_min, lat_max, elev, mask, no_mask_value=0)
        clim_con.setClimateData(min_temp=min_temp, max_temp=max_temp,
                                wind_speed=wind, short_rad=srad,
                                rel_humidity=humidity, precip=precip)
        clim_con.setReductionFactors(file_path=str(fc3_file))
        clim_con.applyClimaticConstraints(
            yield_input=yield_in, lgp=m1_results["lgp"],
            lgp_equv=m1_results["lgp_equv"], lgpt10=m1_results["lgpt10"])

        results[f"clim_yield_{condition}"] = clim_con.getClimateAdjustedYield()
        results[f"fc3_{condition}"] = clim_con.getClimateReductionFactor()

    m3_dir = output_dir / "NB3"
    m3_dir.mkdir(parents=True, exist_ok=True)
    for name, arr in results.items():
        np.save(str(m3_dir / f"{crop_name}_{name}.npy"), arr)

    elapsed = time.time() - t0
    print(f"  Module III complete in {elapsed:.1f}s")
    return results


def run_module4_soil_constraints(data_dir: Path, m3_results: dict,
                                  crop_name: str, output_dir: Path) -> dict:
    """Module IV: Soil Constraints → fc4."""
    from pyaez import SoilConstraints
    from osgeo import gdal

    t0 = time.time()
    print("\n=== Module IV: Soil Constraints ===")

    soil_map = gdal.Open(str(data_dir / "LAO_Soil.tif")).ReadAsArray()

    results = {}
    for condition, code in [("rain", "R"), ("irr", "I")]:
        yield_key = f"clim_yield_{condition}"
        if yield_key not in m3_results:
            continue

        sc = SoilConstraints.SoilConstraints()

        rain_xlsx = data_dir / f"{crop_name}_soil_params_rain.xlsx"
        irr_xlsx = data_dir / f"{crop_name}_soil_params_irr.xlsx"
        sc.importSoilReductionSheet(
            rain_sheet_path=str(rain_xlsx), irr_sheet_path=str(irr_xlsx))

        top_xlsx = data_dir / f"{crop_name}_soil_characteristics_topsoil.xlsx"
        sub_xlsx = data_dir / f"{crop_name}_soil_characteristics_subsoil.xlsx"
        sc.calculateSoilQualities(irr_or_rain=code,
                                  topsoil_path=str(top_xlsx),
                                  subsoil_path=str(sub_xlsx))
        sc.calculateSoilRatings(input_level="H")

        yield_adj = sc.applySoilConstraints(soil_map, m3_results[yield_key])
        results[f"soil_yield_{condition}"] = yield_adj
        results[f"fc4_{condition}"] = sc.getSoilSuitabilityMap()

    m4_dir = output_dir / "NB4"
    m4_dir.mkdir(parents=True, exist_ok=True)
    for name, arr in results.items():
        np.save(str(m4_dir / f"{crop_name}_{name}.npy"), arr)

    elapsed = time.time() - t0
    print(f"  Module IV complete in {elapsed:.1f}s")
    return results


def run_module5_terrain_constraints(data_dir: Path, m4_results: dict,
                                     crop_name: str, output_dir: Path) -> dict:
    """Module V: Terrain Constraints → fc5."""
    from pyaez import TerrainConstraints
    from osgeo import gdal

    t0 = time.time()
    print("\n=== Module V: Terrain Constraints ===")

    precip = np.load(str(data_dir / "climate/precipitation.npy"))
    slope = gdal.Open(str(data_dir / "LAO_Slope.tif")).ReadAsArray()

    tc = TerrainConstraints.TerrainConstraints()

    rain_xlsx = data_dir / f"{crop_name}_terrain_constraints_rain.xlsx"
    irr_xlsx = data_dir / f"{crop_name}_terrain_constraints_irr.xlsx"
    tc.importTerrainReductionSheet(irr_file_path=str(irr_xlsx),
                                   rain_file_path=str(rain_xlsx))
    tc.setClimateTerrainData(precip, slope)
    tc.calculateFI()

    results = {"fournier_index": tc.getFI()}

    for condition, code in [("rain", "R"), ("irr", "I")]:
        yield_key = f"soil_yield_{condition}"
        if yield_key not in m4_results:
            continue

        yield_adj = tc.applyTerrainConstraints(m4_results[yield_key], code)
        results[f"terrain_yield_{condition}"] = yield_adj
        results[f"fc5_{condition}"] = tc.getTerrainReductionFactor()

    m5_dir = output_dir / "NB5"
    m5_dir.mkdir(parents=True, exist_ok=True)
    for name, arr in results.items():
        if isinstance(arr, np.ndarray):
            np.save(str(m5_dir / f"{crop_name}_{name}.npy"), arr)

    elapsed = time.time() - t0
    print(f"  Module V complete in {elapsed:.1f}s")
    return results


def run_module6_economic(data_dir: Path, m5_results: dict,
                          crop_name: str, output_dir: Path) -> dict:
    """Module VI: Economic Suitability Analysis."""
    from pyaez import EconomicSuitability

    t0 = time.time()
    print("\n=== Module VI: Economic Suitability ===")

    econ = EconomicSuitability.EconomicSuitability()

    # Default economic parameters (user should customize)
    cost = np.array([30000, 28000, 25000, 22000])  # currency/ha
    yield_levels = np.array([4.8, 5.5, 6.1, 8.7]) / 2  # ton/ha
    prices = np.arange(6.5, 9.5, 0.5) * 1000  # currency/ton

    results = {}
    for condition in ["rain", "irr"]:
        yield_key = f"terrain_yield_{condition}"
        if yield_key not in m5_results:
            continue

        yield_map = m5_results[yield_key] / 1000  # kg/ha → ton/ha
        econ.addACrop(crop_name=f"{crop_name}_{condition}",
                      crop_cost=cost, crop_yield=yield_levels,
                      farm_price=prices, yield_map=yield_map)

        results[f"revenue_{condition}"] = econ.getNetRevenue(f"{crop_name}_{condition}")
        results[f"revenue_class_{condition}"] = econ.getClassifiedNetRevenue(f"{crop_name}_{condition}")

    m6_dir = output_dir / "NB6"
    m6_dir.mkdir(parents=True, exist_ok=True)
    for name, arr in results.items():
        if isinstance(arr, np.ndarray):
            np.save(str(m6_dir / f"{crop_name}_{name}.npy"), arr)

    elapsed = time.time() - t0
    print(f"  Module VI complete in {elapsed:.1f}s")
    return results


def validate_outputs(output_dir: Path, modules: list) -> list:
    """Validate pipeline outputs after execution."""
    errors = []

    module_dirs = {1: "NB1", 2: "NB2", 3: "NB3", 4: "NB4", 5: "NB5", 6: "NB6"}
    for m in modules:
        d = output_dir / module_dirs[m]
        if not d.exists():
            errors.append(f"Module {m}: output directory {d} not found")
        elif len(list(d.glob("*"))) == 0:
            errors.append(f"Module {m}: output directory {d} is empty")

    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("\nAll pipeline outputs validated successfully")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Run PyAEZ pipeline")
    parser.add_argument("--data-dir", required=True, help="Input data directory")
    parser.add_argument("--crop-name", required=True, help="Crop name")
    parser.add_argument("--crop-params", required=True, help="Crop parameter Excel file")
    parser.add_argument("--lat-min", type=float, required=True)
    parser.add_argument("--lat-max", type=float, required=True)
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--modules", default="1,2,3,4,5,6",
                        help="Comma-separated module numbers to run")
    parser.add_argument("--daily", action="store_true",
                        help="Use daily climate data instead of monthly")
    args = parser.parse_args()

    modules = [int(m) for m in args.modules.split(",")]
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pre-flight validation
    errors = validate_inputs(vars(args))
    if errors:
        print("INPUT VALIDATION ERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    t_total = time.time()
    all_results = {}

    if 1 in modules:
        all_results["m1"] = run_module1_climate_regime(
            data_dir, args.lat_min, args.lat_max, output_dir, args.daily)

    if 2 in modules:
        all_results["m2"] = run_module2_crop_simulation(
            data_dir, args.lat_min, args.lat_max,
            args.crop_params, args.crop_name,
            all_results.get("m1", {}), output_dir, args.daily)

    if 3 in modules:
        all_results["m3"] = run_module3_climatic_constraints(
            data_dir, args.lat_min, args.lat_max,
            all_results.get("m1", {}), all_results.get("m2", {}),
            args.crop_name, output_dir)

    if 4 in modules:
        all_results["m4"] = run_module4_soil_constraints(
            data_dir, all_results.get("m3", {}), args.crop_name, output_dir)

    if 5 in modules:
        all_results["m5"] = run_module5_terrain_constraints(
            data_dir, all_results.get("m4", {}), args.crop_name, output_dir)

    if 6 in modules:
        all_results["m6"] = run_module6_economic(
            data_dir, all_results.get("m5", {}), args.crop_name, output_dir)

    # Post-validation
    val_errors = validate_outputs(output_dir, modules)
    elapsed = time.time() - t_total
    print(f"\nTotal pipeline time: {elapsed:.1f}s")

    # Save run summary
    summary = {
        "crop_name": args.crop_name,
        "modules_run": modules,
        "elapsed_s": round(elapsed, 1),
        "output_dir": str(output_dir),
        "errors": val_errors,
    }
    with open(str(output_dir / "run_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    if val_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
