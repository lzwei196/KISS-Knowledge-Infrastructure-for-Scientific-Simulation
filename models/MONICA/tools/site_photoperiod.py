#!/usr/bin/env python3
"""
site_photoperiod.py - latitude -> MONICA photoperiodic daylength, and photoperiod TRANSFER of a long-day cultivar.

Why this tool exists (triplet dt_29):
  MONICA's stock long-day cereal cultivars (e.g. crops/wheat/winter-wheat.json: DaylengthRequirement 20 h,
  BaseDaylength 0/7 h) were parameterised for ~52 N, where MONICA's photoperiodic daylength (sun at -6 deg,
  src/core/crop-module.cpp "old DLP") peaks at 18.5 h. The development rate in every stage with a positive
  requirement is multiplied by (DL - base) / (req - base) (fc_DaylengthFactor). At 35 N the same daylength
  peaks at 15.5 h, so the factor stays ~0.45-0.55 through the whole spring: stem elongation, anthesis and
  maturity slip 3-4 weeks, grain fill lands in the hot season, the harvest index collapses (~0.2) and most
  seasons are cut by AutomaticHarvest latest-date.

Rule implemented (latitude-derived, NO yield fitting): set every positive DaylengthRequirement entry to the
site's MAXIMUM photoperiodic daylength, so the photoperiod factor saturates at the local solstice.
Vernalisation and temperature sums are NOT touched.

Usage:
  site_photoperiod.py daylength --lat 35.0
      -> {"status":"success","lat":35.0,"dl_max_photoperiodic_h":15.5,"doy_max":172,"dl_max_astronomic_h":14.5,
          "ref_52_5N_photoperiodic_h":18.5}
  site_photoperiod.py adapt --lat 35.0 --base $MONICA_PARAMETERS/crops/wheat/winter-wheat.json --out ww_35N.json
      -> writes the adapted cultivar JSON (same schema as the base file) and prints a JSON summary
         {"status":"success","output":..., "daylength_requirement_h":[0,15.5,15.5,15.5,0,0], ...}
  Options: --stages 1 2 3   (0-based stage indices to set; default = every entry > 0; a selected stage MUST
                             carry a positive requirement - the tool transfers an existing long-day
                             requirement, it never creates one)
           --precision 1    (decimal places for the requirement; default 1)

Refusals (exit 2, ONE JSON object {"status":"error","error":...} on stdout, NOTHING written):
  * command-line usage errors (missing subcommand / --lat / --base / --out, non-numeric --lat, unknown
    option, ...): argparse's error hook is overridden, so these ALSO exit 2 with the JSON object on stdout
    (argparse's default usage text is NOT printed; only `-h/--help` prints usage text, with exit 0);
  * latitude outside -90..90;
  * the base cultivar carries ANY negative (short-day) DaylengthRequirement entry - in any stage, selected
    or not (e.g. crops/soybean/*.json: [0,-14.35,...,0]) - this rule is for long-day cultivars only;
  * no entry is positive (photoperiod-insensitive cultivar - nothing to transfer);
  * --out resolves to the --base file itself, or to ANY path inside the monica-parameters repository
    (the repository root is detected from --base: nearest ancestor named 'monica-parameters' or holding
    both crops/ and general/; $MONICA_PARAMETERS, when set, is protected as well);
  * --out is a directory, or its PARENT directory does not exist / is not a directory - the tool creates NO
    directories (create the run directory yourself first); a pre-existing <out>.tmp is refused as well.
File-touch contract: the tool writes exactly two paths, both derived from --out: <realpath(out)>.tmp (transient,
same directory) and then <realpath(out)> via os.replace; nothing else is created or modified.
Exit codes: 0 success, 2 invalid input / usage error / refused.
"""
import argparse
import json
import math
import os
import sys


class _JsonArgumentParser(argparse.ArgumentParser):
    """argparse that reports usage errors the same way as every other refusal of this tool: one JSON object
    {"status":"error","error":...} on stdout and exit 2 (no usage text on stderr). Sub-parsers created by
    add_subparsers() inherit this class (argparse's default parser_class is type(self))."""

    def error(self, message):
        print(json.dumps({"status": "error", "error": f"usage error: {message}",
                          "usage": self.format_usage().strip()}))
        sys.exit(2)


def photoperiodic_daylength(lat_deg, doy, twilight_deg=6.0):
    """MONICA crop-module.cpp: declination = -23.4*cos(2*pi*(doy+10)/365); DL = 12*(pi+2*asin(arg))/pi with
    arg = (sin(twilight) + sin(decl)*sin(lat)) / (cos(decl)*cos(lat)), bounded to [-1, 1]."""
    decl = -23.4 * math.cos(2.0 * math.pi * ((doy + 10.0) / 365.0))
    s = math.sin(math.radians(decl)) * math.sin(math.radians(lat_deg))
    c = math.cos(math.radians(decl)) * math.cos(math.radians(lat_deg))
    arg = (math.sin(math.radians(twilight_deg)) + s) / c
    arg = max(-1.0, min(1.0, arg))
    return 12.0 * (math.pi + 2.0 * math.asin(arg)) / math.pi


def astronomic_daylength(lat_deg, doy):
    return photoperiodic_daylength(lat_deg, doy, twilight_deg=0.0)


def max_daylength(lat_deg):
    best, best_doy = -1.0, None
    for doy in range(1, 366):
        dl = photoperiodic_daylength(lat_deg, doy)
        if dl > best:
            best, best_doy = dl, doy
    return best, best_doy


def _err(msg):
    print(json.dumps({"status": "error", "error": msg}))
    return 2


def _looks_like_parameter_repo(d):
    """monica-parameters layout: <root>/crops, <root>/general, <root>/soil, ... (or the directory is literally
    named monica-parameters)."""
    return (os.path.basename(d.rstrip(os.sep)) == "monica-parameters"
            or (os.path.isdir(os.path.join(d, "crops")) and os.path.isdir(os.path.join(d, "general"))))


def parameter_repo_root(base_path):
    """Nearest ancestor directory of base_path that is a MONICA parameter repository, or None."""
    d = os.path.dirname(os.path.realpath(base_path))
    while True:
        if _looks_like_parameter_repo(d):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _inside(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:          # different drives / mixed abs-rel (Windows); treat as outside
        return False


def protected_roots(base_path):
    """Directories the tool must never write into: the parameter repository that holds --base (if any) and
    $MONICA_PARAMETERS (if set)."""
    roots = []
    r = parameter_repo_root(base_path)
    if r:
        roots.append(r)
    env = os.environ.get("MONICA_PARAMETERS")
    if env:
        roots.append(os.path.realpath(env))
    return roots


def check_out_path(out_path, base_path):
    """Return an error string if out_path violates the file-touch contract, else None."""
    out_r = os.path.realpath(out_path)
    base_r = os.path.realpath(base_path)
    if out_r == base_r:
        return f"--out resolves to the --base file itself ({out_r}); refusing to overwrite the base cultivar"
    if os.path.isdir(out_r):
        return f"--out is a directory ({out_r}); give a file path"
    for root in protected_roots(base_path):
        if _inside(out_r, root):
            return (f"--out ({out_r}) lies inside the MONICA parameter repository ({root}); this tool never "
                    f"writes into the parameter repository - choose an --out in your run/work directory")
    # the tool creates NO directories: the parent of --out must already exist (the runner makes its cultivars/ dir)
    parent = os.path.dirname(out_r) or "."
    if not os.path.isdir(parent):
        return (f"parent directory of --out does not exist or is not a directory ({parent}); this tool creates no "
                f"directories - create the run directory first")
    tmp = out_r + ".tmp"
    if os.path.exists(tmp) or os.path.islink(tmp):
        return f"transient file {tmp} already exists; refusing to overwrite it - remove it first"
    if tmp == base_r:
        return f"transient file {tmp} would be the --base file; choose another --out"
    return None


def cmd_daylength(args):
    dl, doy = max_daylength(args.lat)
    ref, _ = max_daylength(52.5)
    out = {"status": "success", "lat": args.lat,
           "dl_max_photoperiodic_h": round(dl, args.precision), "doy_max": doy,
           "dl_max_astronomic_h": round(astronomic_daylength(args.lat, doy), args.precision),
           "ref_52_5N_photoperiodic_h": round(ref, args.precision),
           "formula": "MONICA crop-module.cpp old DLP: sun at -6 deg, declination -23.4*cos(2pi(doy+10)/365)"}
    print(json.dumps(out, indent=1))
    return 0


def cmd_adapt(args):
    if not os.path.isfile(args.base):
        return _err(f"base cultivar file not found: {args.base}")
    # file-touch contract first: never write over --base or into the parameter repository
    bad_out = check_out_path(args.out, args.base)
    if bad_out:
        return _err(bad_out)
    with open(args.base, encoding="utf-8") as f:
        cv = json.load(f)
    if not isinstance(cv, dict) or "DaylengthRequirement" not in cv:
        return _err("base file is not a MONICA cultivar JSON (no DaylengthRequirement)")
    dlr = cv["DaylengthRequirement"]
    # schema: [[v0..vn], "h"]  or  [v0..vn]
    if isinstance(dlr, list) and len(dlr) == 2 and isinstance(dlr[0], list):
        values, unit, wrapped = list(dlr[0]), dlr[1], True
    elif isinstance(dlr, list):
        values, unit, wrapped = list(dlr), "h", False
    else:
        return _err(f"unexpected DaylengthRequirement schema: {dlr!r}")
    if not all(isinstance(v, (int, float)) for v in values):
        return _err(f"DaylengthRequirement entries must be numbers: {values!r}")
    # long-day cultivars ONLY: any negative (short-day) entry anywhere in the vector -> refuse, whatever --stages says
    neg_all = [i for i, v in enumerate(values) if v < 0]
    if neg_all:
        return _err(f"stages {neg_all} carry a NEGATIVE (short-day) DaylengthRequirement {values}; this transfer rule "
                    f"is for long-day cultivars only - refusing (nothing written)")
    positive = [i for i, v in enumerate(values) if v > 0]
    if not positive:
        return _err("no stage has a positive DaylengthRequirement; nothing to transfer "
                    "(photoperiod-insensitive cultivar - do not use this tool)")
    stages = list(args.stages) if args.stages else positive
    bad = [i for i in stages if i < 0 or i >= len(values)]
    if bad:
        return _err(f"stage index out of range: {bad} (n_stages={len(values)})")
    not_pos = [i for i in stages if values[i] <= 0]
    if not_pos:
        return _err(f"--stages {not_pos} select entries without a positive requirement ({values}); the tool "
                    f"transfers an existing long-day requirement, it never creates one")
    dl, doy = max_daylength(args.lat)
    req = round(dl, args.precision)
    before = list(values)
    for i in stages:
        values[i] = req
    cv["DaylengthRequirement"] = [values, unit] if wrapped else values
    note = (f"DaylengthRequirement transferred by tools/site_photoperiod.py: stages {stages} set to the max "
            f"photoperiodic daylength {req} h at lat {args.lat} (was {before}); base={os.path.basename(args.base)}")
    cv["Description"] = (str(cv.get("Description") or "") + (" | " if cv.get("Description") else "") + note)
    # file-touch contract: no directory creation (parent existence was verified by check_out_path); write
    # <realpath(out)>.tmp in the same directory, then atomically rename it onto <realpath(out)>.
    out_abs = os.path.realpath(args.out)
    tmp = out_abs + ".tmp"
    try:
        with open(tmp, "x", encoding="utf-8") as f:
            json.dump(cv, f, indent=2, ensure_ascii=False)
        os.replace(tmp, out_abs)
    except OSError as e:
        try:
            if os.path.lexists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return _err(f"could not write --out ({out_abs}): {e}")
    print(json.dumps({"status": "success", "output": out_abs, "lat": args.lat,
                      "dl_max_photoperiodic_h": req, "doy_max": doy, "stages_set": stages,
                      "daylength_requirement_h_before": before, "daylength_requirement_h": values,
                      "base_daylength_h": cv.get("BaseDaylength"),
                      "vernalisation_requirement": cv.get("VernalisationRequirement"),
                      "stage_temperature_sum": cv.get("StageTemperatureSum"),
                      "note": note}, indent=1, ensure_ascii=False))
    return 0


def main():
    # _JsonArgumentParser: usage errors -> {"status":"error",...} on stdout, exit 2 (same contract as every refusal)
    p = _JsonArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("daylength", help="max MONICA photoperiodic daylength at a latitude")
    a.add_argument("--lat", type=float, required=True)
    a.add_argument("--precision", type=int, default=1)
    a.set_defaults(func=cmd_daylength)
    b = sub.add_parser("adapt", help="write a cultivar JSON whose positive DaylengthRequirement = local max daylength "
                                     "(refuses short-day cultivars and any --out over --base / inside the parameter repo)")
    b.add_argument("--lat", type=float, required=True)
    b.add_argument("--base", required=True, help="base cultivar JSON (e.g. $MONICA_PARAMETERS/crops/wheat/winter-wheat.json)")
    b.add_argument("--out", required=True, help="output cultivar JSON path (outside the parameter repository, != --base)")
    b.add_argument("--stages", type=int, nargs="*", help="0-based stage indices to set (default: all entries > 0; "
                                                         "selected entries must be > 0)")
    b.add_argument("--precision", type=int, default=1)
    b.set_defaults(func=cmd_adapt)
    args = p.parse_args()
    if not (-90.0 <= args.lat <= 90.0):
        return _err(f"latitude out of range: {args.lat}")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
