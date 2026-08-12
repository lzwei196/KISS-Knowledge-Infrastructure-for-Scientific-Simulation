#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      generate_weather_stations
Stage:        s3_weather_preparation
Description:  Create weather-sta.cli (+ weather-wgn.cli fallback) for SWAT+.

weather-sta.cli is read POSITIONALLY by SWAT+ rev59. The verified column order,
from the shipped developer example
/mnt/disk1/Hydrocraft_server/models/SWAT_Plus/run_lrew/swatplus_rev59_demo/weather-sta.cli, is:

    name   wgn   pcp   tmp   slr   hmd   wnd   wnd_dir   atmo_dep

Two traps (dt_040):
  * `wgn` is the SECOND column, not the last. Writing pcp first makes SWAT+ read the
    pcp station name as the wgn name, then run out of tokens and read into the next
    line -- producing alternating "staNN file not found (pgage)" / "(atmodep)".
  * The pcp..wnd columns hold the FILE NAME WITH EXTENSION (`sta01.pcp`), not a bare
    stem. A bare stem makes every gage lookup fail and SWAT+ silently falls back to
    the weather GENERATOR, driving the whole simulation with synthetic climatology.

The generator file is `weather-wgn.cli` (named by rev59's file.cio), NOT the SWAT2012
name `wgn.wgn`. An existing weather-wgn.cli is PRESERVED only if every station has a
complete, numerically parseable 12x14 block; otherwise (absent, incomplete, or
malformed) it is synthesised from the station weather files.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json, math
from pathlib import Path

PCP_CLI_PATH = ""
STATION_COORDS = []
SUBBASIN_CENTROIDS = []
OUTPUT_DIR = ""

if len(sys.argv) >= 5:
    PCP_CLI_PATH = sys.argv[1]
    STATION_COORDS = json.loads(sys.argv[2])
    SUBBASIN_CENTROIDS = json.loads(sys.argv[3])
    OUTPUT_DIR = sys.argv[4]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CW = 20                 # column width for weather-sta.cli
WET_THRESHOLD = 0.1     # mm/day; a day with more precipitation than this is "wet"
VARS = ("pcp", "tmp", "slr", "hmd", "wnd")


def validate_inputs():
    errors = []
    if not PCP_CLI_PATH or not Path(PCP_CLI_PATH).exists():
        errors.append(f"pcp.cli not found: {PCP_CLI_PATH}")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def _read_station_file(path):
    """Return (header_meta, rows) for a SWAT+ weather file (3 header lines)."""
    lines = [l for l in path.read_text().strip().split("\n")]
    meta = lines[2].split()
    rows = [[float(x) for x in l.split()] for l in lines[3:] if l.strip()]
    return meta, rows


def _month_of(year, jday):
    from datetime import date, timedelta
    return (date(year, 1, 1) + timedelta(days=jday - 1)).month


def _mean(v):
    return sum(v) / len(v) if v else 0.0


def _sd(v):
    if len(v) < 2:
        return 0.0
    m = _mean(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def _skew(v):
    """Sample skewness, scipy.stats.skew(bias=False): g1 uses the POPULATION sd."""
    n = len(v)
    if n < 3:
        return 0.0
    m = _mean(v)
    s0 = math.sqrt(sum((x - m) ** 2 for x in v) / n)   # population sd (ddof=0)
    if s0 == 0:
        return 0.0
    g1 = sum(((x - m) / s0) ** 3 for x in v) / n
    return math.sqrt(n * (n - 1)) / (n - 2) * g1


def _dewpoint(tmean, rh):
    """Magnus-Tetens, alpha=17.625 / beta=243.04 (Alduchov & Eskridge 1996)."""
    rh = min(max(rh, 1e-6), 1.0)
    g = 17.625 * tmean / (243.04 + tmean) + math.log(rh)
    return 243.04 * g / (17.625 - g)


def _wgn_stats(out_dir, name):
    """12 monthly rows x 14 statistics, computed from the station's own weather files."""
    data = {}
    for v in VARS:
        p = out_dir / f"{name}.{v}"
        if not p.exists():
            return None, None
        data[v] = _read_station_file(p)
    meta = data["pcp"][0]
    lat, lon, elev = float(meta[2]), float(meta[3]), float(meta[4])
    years = sorted({int(r[0]) for r in data["pcp"][1]})

    pcp = {(int(r[0]), int(r[1])): r[2] for r in data["pcp"][1]}
    tmp = {(int(r[0]), int(r[1])): (r[2], r[3]) for r in data["tmp"][1]}
    slr = {(int(r[0]), int(r[1])): r[2] for r in data["slr"][1]}
    hmd = {(int(r[0]), int(r[1])): r[2] for r in data["hmd"][1]}
    wnd = {(int(r[0]), int(r[1])): r[2] for r in data["wnd"][1]}

    keys = sorted(pcp)
    months = {k: _month_of(*k) for k in keys}
    wet = {k: pcp[k] > WET_THRESHOLD for k in keys}

    rows = []
    for m in range(1, 13):
        km = [k for k in keys if months[k] == m]
        tx = [tmp[k][0] for k in km]
        tn = [tmp[k][1] for k in km]
        pw = [pcp[k] for k in km if wet[k]]

        # monthly precipitation total, averaged over years
        tot = [sum(pcp[k] for k in km if k[0] == y) for y in years]
        ndays = [sum(1 for k in km if k[0] == y and wet[k]) for y in years]

        # Forward-looking wet/dry Markov transition probabilities:
        #   wet_dry = P(tomorrow wet | today dry),  wet_wet = P(tomorrow wet | today wet)
        # Day pairs may straddle a month boundary; the pair is attributed to the month
        # of the CONDITIONING day. (A hand-computed weather-wgn.cli produced elsewhere
        # used a slightly different boundary rule and can differ by <=0.04 in these two
        # columns. This is immaterial: weather-wgn.cli is only consulted when a station
        # file is missing, and an existing well-formed file is preserved untouched.)
        nd = nw = ndw = nww = 0
        for i, k in enumerate(keys):
            if months[k] != m or i + 1 >= len(keys):
                continue
            if wet[k]:
                nw += 1; nww += wet[keys[i + 1]]
            else:
                nd += 1; ndw += wet[keys[i + 1]]
        wet_dry = ndw / nd if nd else 0.0
        wet_wet = nww / nw if nw else 0.0

        # pcp_hhr: maximum 0.5 h rainfall, taken as 0.3 x the largest daily total
        # observed in this calendar month over the whole record.
        hhr = 0.3 * max([pcp[k] for k in km] or [0.0])

        dew = _mean([_dewpoint((tmp[k][0] + tmp[k][1]) / 2.0, hmd[k]) for k in km])

        rows.append([_mean(tx), _mean(tn), _sd(tx), _sd(tn),
                     _mean(tot), _sd(pw), _skew(pw),
                     wet_dry, wet_wet, _mean(ndays), hhr,
                     _mean([slr[k] for k in km]), dew,
                     _mean([wnd[k] for k in km])])
    return (lat, lon, elev, len(years)), rows


WGN_COLS = (" tmp_max_ave   tmp_min_ave    tmp_max_sd    tmp_min_sd       pcp_ave"
            "        pcp_sd      pcp_skew       wet_dry       wet_wet      pcp_days"
            "       pcp_hhr       slr_ave       dew_ave       wnd_ave  ")


def _wgn_is_wellformed(path, station_names):
    """True iff EVERY station has a complete, numerically parseable wgn block.

    A block is: a `wgn_<name> lat lon elev nyears` line (>=5 tokens, fields 2-5
    numeric), then one column-header line, then exactly 12 monthly rows of exactly
    14 floats each. Anything else -> False, so the file is recomputed from the
    station weather files rather than trusted. A leading title line, or any other
    line outside a block, is ignored.
    """
    if not path.exists():
        return False
    try:
        lines = path.read_text().rstrip("\n").split("\n")
    except Exception:
        return False

    heads = {}
    for i, l in enumerate(lines):
        tok = l.split()
        if tok and tok[0].startswith("wgn_"):
            heads.setdefault(tok[0], i)

    for name in station_names:
        i = heads.get(f"wgn_{name}")
        if i is None:
            logger.info(f"weather-wgn.cli: no block for wgn_{name} -> regenerate")
            return False
        hdr = lines[i].split()
        if len(hdr) < 5:
            logger.info(f"weather-wgn.cli: wgn_{name} header has {len(hdr)} tokens, "
                        f"need >=5 -> regenerate")
            return False
        try:
            [float(x) for x in hdr[1:5]]              # lat lon elev nyears
        except ValueError:
            logger.info(f"weather-wgn.cli: wgn_{name} header fields not numeric -> regenerate")
            return False
        # lines[i+1] is the column header; lines[i+2 : i+14] are the 12 monthly rows.
        rows = lines[i + 2:i + 14]
        if len(rows) != 12:
            logger.info(f"weather-wgn.cli: wgn_{name} has {len(rows)} monthly rows, "
                        f"need 12 -> regenerate")
            return False
        for r in rows:
            vals = r.split()
            if len(vals) != 14:
                logger.info(f"weather-wgn.cli: wgn_{name} monthly row has {len(vals)} "
                            f"fields, need 14 -> regenerate")
                return False
            try:
                [float(x) for x in vals]
            except ValueError:
                logger.info(f"weather-wgn.cli: wgn_{name} monthly row not numeric -> regenerate")
                return False
    return True


def process():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    pcp_lines = Path(PCP_CLI_PATH).read_text().strip().split("\n")
    station_files = [l.strip() for l in pcp_lines[2:] if l.strip()]
    station_names = [Path(f).stem for f in station_files]
    if not station_names:
        raise ValueError(f"no station entries parsed from {PCP_CLI_PATH}")

    # ---- weather-sta.cli : name wgn pcp tmp slr hmd wnd wnd_dir atmo_dep
    wsta_path = output_dir / "weather-sta.cli"
    with open(wsta_path, "w") as f:
        f.write("weather-sta.cli: written by SWAT+ knowledge infrastructure\n")
        cols = ["name", "wgn", "pcp", "tmp", "slr", "hmd", "wnd", "wnd_dir", "atmo_dep"]
        f.write("".join(c.ljust(CW) for c in cols) + "\n")
        for name in station_names:
            row = [name, f"wgn_{name}"] + [f"{name}.{v}" for v in VARS] + ["null", "null"]
            f.write("".join(c.ljust(CW) for c in row) + "\n")

    # ---- weather-wgn.cli : preserve if already well-formed, else synthesise
    wgn_path = output_dir / "weather-wgn.cli"
    if _wgn_is_wellformed(wgn_path, station_names):
        logger.info(f"weather-wgn.cli already well-formed for {len(station_names)} "
                    f"stations -> preserved (not regenerated)")
        wgn_mode = "preserved"
    else:
        with open(wgn_path, "w") as f:
            f.write("weather-wgn.cli: written by SWAT+ knowledge infrastructure "
                    "(monthly stats computed from the station weather files)\n")
            for i, name in enumerate(station_names):
                hdr, rows = _wgn_stats(output_dir, name)
                if hdr is None:
                    lat = STATION_COORDS[i][0] if i < len(STATION_COORDS) else 0.0
                    lon = STATION_COORDS[i][1] if i < len(STATION_COORDS) else 0.0
                    raise FileNotFoundError(
                        f"station files for {name} not found in {output_dir}; "
                        f"cannot compute wgn statistics (lat={lat}, lon={lon})")
                lat, lon, elev, nyr = hdr
                f.write(f"wgn_{name:<24}{lat:12.5f}{lon:14.5f}{elev:14.5f}{nyr:10d}  \n")
                f.write(WGN_COLS + "\n")
                for r in rows:
                    f.write("".join(f"{x:14.5f}" for x in r) + "\n")
        wgn_mode = "computed"

    # The SWAT2012 name wgn.wgn is never read by rev59 (file.cio names weather-wgn.cli).
    stale = output_dir / "wgn.wgn"
    if stale.exists():
        stale.unlink()
        logger.info("removed stale wgn.wgn (SWAT2012 name; rev59 reads weather-wgn.cli)")

    logger.info(f"Created weather-sta.cli ({len(station_names)} stations); "
                f"weather-wgn.cli {wgn_mode}")
    return {"status": "success",
            "weather_sta_cli": str(wsta_path),
            "weather_wgn_cli": str(wgn_path),
            "wgn_mode": wgn_mode,
            "n_stations": len(station_names)}


def validate_outputs(result):
    errors = []
    for key in ("weather_sta_cli", "weather_wgn_cli"):
        if not Path(result[key]).exists():
            errors.append(f"Expected output not created: {result[key]}")
    if Path(OUTPUT_DIR, "wgn.wgn").exists():
        errors.append("wgn.wgn must not be written (rev59 reads weather-wgn.cli)")

    sta = Path(result["weather_sta_cli"]).read_text().rstrip("\n").split("\n")
    hdr = sta[1].split()
    if hdr != ["name", "wgn", "pcp", "tmp", "slr", "hmd", "wnd", "wnd_dir", "atmo_dep"]:
        errors.append(f"weather-sta.cli column order wrong: {hdr}")
    for line in sta[2:]:
        tok = line.split()
        if len(tok) != 9:
            errors.append(f"weather-sta.cli row has {len(tok)} tokens, expected 9: {line!r}")
            continue
        if not tok[1].startswith("wgn_"):
            errors.append(f"column 2 must be the wgn name, got {tok[1]!r}")
        for j, v in enumerate(VARS, start=2):
            if not tok[j].endswith(f".{v}"):
                errors.append(f"column {j+1} must be a {v} FILE name, got {tok[j]!r}")
            if not Path(OUTPUT_DIR, tok[j]).exists():
                errors.append(f"referenced weather file missing: {tok[j]}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
