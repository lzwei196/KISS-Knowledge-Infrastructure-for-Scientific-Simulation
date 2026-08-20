#!/usr/bin/env python3
"""Run one small, reproducible DSSAT point case from public weather data.

This is the simple project bridge used by the GeoForge agent.  It turns a few
scenario choices into the many files DSSAT needs, runs the real model binary,
and saves both results and provenance in the chat project.  It intentionally
uses a bundled generic soil profile unless a calibrated site soil is supplied;
the output is therefore a functional reference simulation, not a locally
calibrated yield claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


KI_TOOLS_COMMON = Path("KISSPATH_KI_TOOLS_COMMON")
if str(KI_TOOLS_COMMON) not in sys.path:
    sys.path.insert(0, str(KI_TOOLS_COMMON))

from ki_tools_common.load_forcing import (  # noqa: E402
    NASA_POWER_DAILY_PARAMS,
    NASA_POWER_DAILY_URL,
    load_daily_forcing,
)

from dssat_workdir_setup import (  # noqa: E402
    DSSAT_BINARY,
    DSSAT_DATA,
    create_workdir,
    parse_summary,
    run_dssat,
)


DEFAULT_SOIL_FILE = Path("KISSPATH_HOME/DSSAT/run_test/SOIL.SOL")
SOIL_LABELS = {
    "IB00000001": "DSSAT generic silty clay",
    "IB00000002": "DSSAT generic loam",
    "IB00000003": "DSSAT generic sandy loam",
    "IB00000010": "DSSAT generic silty clay loam",
    "IB00000011": "DSSAT generic silt loam",
    "IB00000012": "DSSAT generic deep silt loam",
}


def _finite(value, label: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"NASA POWER returned a missing {label} value")
    return value


def _date(value) -> datetime:
    # numpy datetime64 stringifies to ISO YYYY-MM-DD for daily data.
    return datetime.strptime(str(value)[:10], "%Y-%m-%d")


def _tav_amp(dates, tmax, tmin) -> tuple[float, float]:
    daily_mean = (np.asarray(tmax, dtype=float) + np.asarray(tmin, dtype=float)) / 2.0
    tav = float(np.mean(daily_mean))
    monthly = []
    for month in range(1, 13):
        idx = [i for i, d in enumerate(dates) if _date(d).month == month]
        if idx:
            monthly.append(float(np.mean(daily_mean[idx])))
    if len(monthly) != 12:
        raise ValueError("weather does not contain all 12 calendar months")
    # DSSAT's AMP field is the half-range of monthly mean temperature.
    amp = (max(monthly) - min(monthly)) / 2.0
    return tav, amp


def write_daily_weather(data: dict, path: Path, *, station: str, lat: float,
                        lon: float, elevation: float, source_label: str) -> dict:
    """Convert standardized public-weather arrays into one DSSAT WTH file."""
    dates = data["dates"]
    rain = data["precip_mm"]
    tmax = data["temp_max_c"]
    tmin = data["temp_min_c"]
    srad = data["srad_wm2"]
    wind = data["wind_ms"]
    n = len(dates)
    if n not in (365, 366):
        raise ValueError(f"expected one complete weather year, received {n} days")
    if not all(len(data[k]) == n for k in (
            "precip_mm", "temp_max_c", "temp_min_c", "srad_wm2", "wind_ms")):
        raise ValueError("NASA POWER weather arrays have inconsistent lengths")

    station = station.upper()[:4]
    tav, amp = _tav_amp(dates, tmax, tmin)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"*WEATHER DATA : {station} - {source_label}\n")
        handle.write("@ INSI      LAT     LONG  ELEV   TAV   AMP REFHT WNDHT\n")
        handle.write(
            f"  {station:4s} {lat:8.3f} {lon:8.3f} {elevation:5.0f} "
            f"{tav:5.1f} {amp:5.1f}   2.0  10.0\n"
        )
        handle.write("@DATE  SRAD  TMAX  TMIN  RAIN  WIND\n")
        for i, raw_date in enumerate(dates):
            day = _date(raw_date)
            # POWER shortwave is a daily-mean W/m2. DSSAT wants MJ/m2/day.
            radiation = _finite(srad[i], "shortwave radiation") * 0.0864
            # DSSAT's optional WIND column uses km/day.
            wind_km_day = _finite(wind[i], "wind") * 86.4
            handle.write(
                f"{day.year % 100:02d}{day.timetuple().tm_yday:03d}"
                f"{max(0.0, radiation):6.1f}"
                f"{_finite(tmax[i], 'maximum temperature'):6.1f}"
                f"{_finite(tmin[i], 'minimum temperature'):6.1f}"
                f"{max(0.0, _finite(rain[i], 'precipitation')):6.1f}"
                f"{max(0.0, wind_km_day):6.1f}\n"
            )
    return {
        "days": n,
        "tav_c": round(tav, 3),
        "amp_c": round(amp, 3),
        "rain_mm": round(float(np.sum(rain)), 3),
        "mean_srad_mj_m2_day": round(float(np.mean(srad)) * 0.0864, 3),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _load_power_without_requests(lat: float, lon: float, year: int) -> dict:
    """Small stdlib fallback for a verified environment without requests.

    ``ki_tools_common`` remains the preferred loader.  The fallback uses the
    same official endpoint, parameters, fill rules, and unit conversions so a
    missing convenience HTTP package cannot turn public data into a user task.
    """
    query = urllib.parse.urlencode({
        "start": f"{year}0101", "end": f"{year}1231",
        "latitude": lat, "longitude": lon, "community": "RE",
        "parameters": NASA_POWER_DAILY_PARAMS,
        "format": "JSON", "header": "false",
    })
    request = urllib.request.Request(
        f"{NASA_POWER_DAILY_URL}?{query}",
        headers={"User-Agent": "GeoForge-DSSAT/1.0"},
    )
    # Match the canonical loader's deliberate proxy bypass.  Some desktop
    # launch environments inherit a proxy that breaks POWER's TLS handshake.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    try:
        with opener.open(request, timeout=120) as response:
            raw = response.read()
    except OSError as urllib_error:
        # Python builds launched from a signed macOS app can lack the same TLS
        # trust setup as the system command line.  curl is part of macOS and is
        # a more reliable last transport; --noproxy preserves the intentional
        # direct connection used by the canonical loader.
        curl = shutil.which("curl") or "/usr/bin/curl"
        proc = subprocess.run(
            [curl, "--noproxy", "*", "--fail", "--silent", "--show-error",
             "--location", "--max-time", "120", request.full_url],
            capture_output=True, timeout=130,
        )
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(
                f"NASA POWER download failed via Python ({urllib_error}) and curl ({detail})"
            ) from urllib_error
        raw = proc.stdout
    payload = json.loads(raw.decode("utf-8"))
    try:
        parameters = payload["properties"]["parameter"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"NASA POWER returned an unexpected response: {list(payload)}") from exc

    names = {
        "temp_mean_c": "T2M", "temp_min_c": "T2M_MIN",
        "temp_max_c": "T2M_MAX", "precip_mm": "PRECTOTCORR",
        "srad_wm2": "ALLSKY_SFC_SW_DWN", "wind_ms": "WS10M",
    }
    day_keys = sorted(parameters.get("T2M", {}))
    result = {"dates": np.array([np.datetime64(
        datetime.strptime(key, "%Y%m%d").date()) for key in day_keys])}
    for target, source in names.items():
        source_data = parameters.get(source, {})
        if target == "wind_ms" and not source_data:
            source_data = parameters.get("WS2M", {})
        values = []
        for key in day_keys:
            value = source_data.get(key, -999)
            values.append(np.nan if value in (-999, None) else float(value))
        array = np.asarray(values, dtype=float)
        if target == "precip_mm":
            array = np.maximum(array, 0.0)
        elif target == "srad_wm2":
            array = array * (1000.0 / 24.0)  # kWh/m2/day -> daily-mean W/m2
        result[target] = array
    return result


def _load_open_meteo(lat: float, lon: float, year: int) -> tuple[dict, dict]:
    """Fetch ERA5 daily data through Open-Meteo's public archive API."""
    endpoint = "https://archive-api.open-meteo.com/v1/archive"
    query = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "start_date": f"{year}-01-01", "end_date": f"{year}-12-31",
        "daily": (
            "temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "shortwave_radiation_sum,wind_speed_10m_mean"
        ),
        "models": "era5", "timezone": "UTC", "wind_speed_unit": "ms",
    })
    url = f"{endpoint}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "GeoForge-DSSAT/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
    except OSError as urllib_error:
        curl = shutil.which("curl") or "/usr/bin/curl"
        proc = subprocess.run(
            [curl, "--fail", "--silent", "--show-error", "--location",
             "--max-time", "120", url],
            capture_output=True, timeout=130,
        )
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(
                f"Open-Meteo ERA5 download failed via Python ({urllib_error}) "
                f"and curl ({detail})"
            ) from urllib_error
        raw = proc.stdout
    payload = json.loads(raw.decode("utf-8"))
    daily = payload.get("daily") or {}
    units = payload.get("daily_units") or {}
    required = {
        "time", "temperature_2m_max", "temperature_2m_min",
        "precipitation_sum", "shortwave_radiation_sum", "wind_speed_10m_mean",
    }
    missing = sorted(required - set(daily))
    if missing:
        raise RuntimeError(f"Open-Meteo response is missing daily fields: {missing}")
    data = {
        "dates": np.asarray([np.datetime64(value) for value in daily["time"]]),
        "temp_max_c": np.asarray(daily["temperature_2m_max"], dtype=float),
        "temp_min_c": np.asarray(daily["temperature_2m_min"], dtype=float),
        "precip_mm": np.asarray(daily["precipitation_sum"], dtype=float),
        # ERA5-Land shortwave sum is MJ/m2/day; standardize to daily-mean W/m2.
        "srad_wm2": np.asarray(daily["shortwave_radiation_sum"], dtype=float) / 0.0864,
        "wind_ms": np.asarray(daily["wind_speed_10m_mean"], dtype=float),
    }
    meta = {
        "source": "Open-Meteo Historical Weather API (ERA5)",
        "url": endpoint,
        "query": query,
        "dataset": "ERA5",
        "daily_units_reported": units,
        "elevation_m": payload.get("elevation"),
    }
    return data, meta


def load_public_weather(lat: float, lon: float, year: int) -> tuple[dict, dict]:
    nasa_meta = {
        "source": "NASA POWER daily point API",
        "url": NASA_POWER_DAILY_URL,
        "parameters": NASA_POWER_DAILY_PARAMS,
    }
    try:
        return load_daily_forcing("nasa_power", lat, lon, year, year), nasa_meta
    except ImportError as exc:
        if "requests" not in str(exc):
            raise
        print("  requests is absent; using GeoForge's stdlib NASA POWER fallback", flush=True)
        try:
            return _load_power_without_requests(lat, lon, year), nasa_meta
        except Exception as nasa_error:
            print(f"  NASA POWER unavailable ({nasa_error}); trying ERA5", flush=True)
            data, meta = _load_open_meteo(lat, lon, year)
            meta["fallback_reason"] = str(nasa_error)
            return data, meta
    except Exception as nasa_error:
        print(f"  NASA POWER unavailable ({nasa_error}); trying ERA5", flush=True)
        data, meta = _load_open_meteo(lat, lon, year)
        meta["fallback_reason"] = str(nasa_error)
        return data, meta


def run(args) -> dict:
    output = Path(args.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    weather = output / "inputs" / f"{args.station.upper()[:4]}{args.year % 100:02d}01.WTH"

    forcing, weather_source = load_public_weather(args.lat, args.lon, args.year)
    elevation = (args.elevation if args.elevation is not None else
                 float(weather_source.get("elevation_m") or 20.0))
    weather_stats = write_daily_weather(
        forcing, weather, station=args.station, lat=args.lat, lon=args.lon,
        elevation=elevation, source_label=weather_source["source"],
    )

    soil_file = Path(args.soil_file).resolve() if args.soil_file else DEFAULT_SOIL_FILE
    if not soil_file.is_file():
        raise FileNotFoundError(f"soil file not found: {soil_file}")

    short_work = Path(tempfile.mkdtemp(prefix="gf_dssat_", dir="/tmp"))
    copied = False
    try:
        workdir = Path(create_workdir(
            crop="MZ",
            cultivar=args.cultivar,
            weather_file=str(weather),
            soil_id=args.soil_id,
            soil_file=str(soil_file),
            lat=args.lat,
            lon=args.lon,
            planting_date=args.planting_date,
            start_year=args.year,
            end_year=args.year,
            output_dir=str(short_work),
            irrigation="none",
            fert_n=args.fertilizer_n,
        ))
        result = run_dssat(str(workdir), timeout=args.timeout)
        records = parse_summary(str(workdir)) if result["summary_file"] else []

        run_copy = output / "run"
        if run_copy.exists():
            shutil.rmtree(run_copy)
        shutil.copytree(workdir, run_copy, symlinks=True)
        copied = True

        provenance = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "purpose": "GeoForge functional reference simulation; not site-calibrated",
            "scenario": {
                "crop": "maize", "year": args.year,
                "latitude": args.lat, "longitude": args.lon,
                "planting_date": args.planting_date,
                "irrigation": "rainfed", "fertilizer_n_kg_ha": args.fertilizer_n,
                "cultivar": args.cultivar,
            },
            "weather": {
                "file": str(weather), "sha256": _sha256(weather),
                **weather_source,
                **weather_stats,
            },
            "soil": {
                "profile_id": args.soil_id,
                "label": SOIL_LABELS.get(args.soil_id, "user-selected DSSAT profile"),
                "source_file": str(soil_file), "sha256": _sha256(soil_file),
                "assumption": (
                    "Bundled generic DSSAT reference profile used because no "
                    "site-calibrated Bengbu soil was supplied."
                ),
            },
            "software": {
                "binary": str(DSSAT_BINARY),
                "data_directory": str(DSSAT_DATA),
                "binary_sha256": _sha256(DSSAT_BINARY),
            },
            "execution": {
                "success": bool(result["success"]),
                "return_code": result["return_code"],
                "stdout": result["stdout"][-4000:],
                "stderr": result["stderr"][-4000:],
            },
            "summary_records": _json_safe(records),
        }
        (output / "provenance.json").write_text(
            json.dumps(provenance, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        (output / "result.json").write_text(
            json.dumps({
                "success": bool(result["success"]),
                "return_code": result["return_code"],
                "summary_out": str(run_copy / "Summary.OUT") if records else None,
                "records": _json_safe(records),
            }, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        if not result["success"]:
            detail = result["stderr"] or result["stdout"] or "DSSAT did not create a valid Summary.OUT"
            raise RuntimeError(detail.strip())
        if not records:
            raise RuntimeError("DSSAT returned success but Summary.OUT contained no records")
        return {
            "success": True,
            "output_dir": str(output),
            "summary_out": str(run_copy / "Summary.OUT"),
            "provenance": str(output / "provenance.json"),
            "weather": weather_stats,
            "records": _json_safe(records),
        }
    finally:
        if not copied and short_work.exists():
            failed_copy = output / "failed_run"
            if failed_copy.exists():
                shutil.rmtree(failed_copy)
            shutil.copytree(short_work, failed_copy, symlinks=True)
        shutil.rmtree(short_work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch public weather, prepare, run, and archive one DSSAT maize case"
    )
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--planting-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--station", default="BENB", help="four-character DSSAT station code")
    parser.add_argument("--elevation", type=float)
    parser.add_argument("--cultivar", default="IB0035")
    # The KI's harness has always documented IB00000001 as its safe bundled
    # default.  Keep it here: it is the first complete profile in SOIL.SOL and
    # was validated by the real macOS reference run.  Site work should replace
    # this explicit generic assumption with measured/derived local soil.
    parser.add_argument("--soil-id", default="IB00000001", choices=sorted(SOIL_LABELS))
    parser.add_argument("--soil-file")
    parser.add_argument("--fertilizer-n", type=float, default=120.0)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    try:
        payload = run(args)
    except Exception as exc:
        print(json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 1
    print(json.dumps(payload, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
