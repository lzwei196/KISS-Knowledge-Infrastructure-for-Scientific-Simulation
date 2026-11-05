#!/usr/bin/env python3
"""fetch_wgew_dap.py -- download Walnut Gulch (WGEW) runoff and rain-gage data from the USDA-ARS
Southwest Watershed Research Center Data Access Project (https://www.tucson.ars.ag.gov/dap/).

These are the observations KINEROS2 was built and tested against: flume runoff (event summary or
full breakpoint hydrograph) and recording rain-gage breakpoints (the native input of a KINEROS2
rainfall file).  Data before 2000 come from the 'analog' pages, 2000 onward from 'digital/'.

  runoff   --flumes 11 --start 1980-08-04 --end 1980-08-04 --type breakpoint --units cf
  precip   --gages 89,51,90 --start 1980-08-04 --end 1980-08-04 --type breakpoint --units inches

Units: runoff 'cf' = discharge in ft3/s (breakpoint) or ft3 (summary); 'mm'/'inches' are per the
flume's NOMINAL drainage area (flume 11: 2035 ac) -- use 'cf' when the model's contributing area
differs from the flume area.  Rain depth units must match the KINEROS2 parameter file UNITS.

Network: the ARS host refuses TLS through some proxies.  Tried in order: --proxy, $WGEW_PROXY,
http://127.0.0.1:7877 (works on the HydroCraft server, 2026-10-06), $HTTPS_PROXY, direct.
The saved file keeps the DAP text verbatim, with '#'-prefixed provenance lines added on top.

Exit codes: 0 data saved | 2 bad arguments | 3 no route to the server / unexpected reply | 4 no events
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.tucson.ars.ag.gov/dap/"
WATERSHEDS = {"walnut_gulch": "63", "santa_rita": "76"}


def _endpoint(kind: str, year: int) -> str:
    era = "digital/" if year >= 2000 else ""
    return BASE + era + ("runoff_eventh.asp" if kind == "runoff" else "eventh.asp")


def _proxies(explicit):
    seen = []
    for p in (explicit, os.environ.get("WGEW_PROXY"), "http://127.0.0.1:7877",
              os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"), ""):
        if p is not None and p not in seen:
            seen.append(p)
    return seen


def post(url: str, form: dict, proxy_list, timeout=90):
    data = urllib.parse.urlencode(form).encode()
    errors = []
    for proxy in proxy_list:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})
        opener = urllib.request.build_opener(handler)
        try:
            with opener.open(urllib.request.Request(url, data=data), timeout=timeout) as r:
                body = r.read().decode("latin-1", errors="replace")
            if body.lstrip().startswith("#Event report"):
                return body, proxy or "direct"
            errors.append(f"{proxy or 'direct'}: unexpected reply ({body[:80]!r})")
        except Exception as e:  # network errors differ per proxy; try the next one
            errors.append(f"{proxy or 'direct'}: {type(e).__name__}: {str(e)[:100]}")
    raise ConnectionError("; ".join(errors))


def build_form(kind, ids, start, end, typ, units, watershed):
    f = {"Watershed": WATERSHEDS[watershed], "StartMonth": start.month, "StartDay": start.day,
         "StartYear": start.year, "EndMonth": end.month, "EndDay": end.day, "EndYear": end.year,
         "all": "ON", "type": typ, "format": "text", "units": units, "submit": "Submit"}
    if kind == "runoff":
        f.update(flumes=ids, sortby="sortby_flume")
    else:
        f.update(gages=ids, sortby="sortby_gage")
    return f


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["runoff", "precip"])
    ap.add_argument("--flumes", help="runoff: flume ids, e.g. 11 or 1,6,11")
    ap.add_argument("--gages", help="precip: gage ids, e.g. 89,51,90")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (same era as --start: both <2000 or both >=2000)")
    ap.add_argument("--type", choices=["summary", "breakpoint"], default="breakpoint")
    ap.add_argument("--units", required=True, help="runoff: cf|mm|inches   precip: inches|mm")
    ap.add_argument("--watershed", choices=sorted(WATERSHEDS), default="walnut_gulch")
    ap.add_argument("--proxy")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        s = dt.date.fromisoformat(a.start); e = dt.date.fromisoformat(a.end)
    except ValueError as ex:
        print(f"ERROR: {ex}", file=sys.stderr); return 2
    if (s.year >= 2000) != (e.year >= 2000) or e < s:
        print("ERROR: --start/--end must be ordered and in one era (pre-2000 analog or 2000+ digital)", file=sys.stderr)
        return 2
    ids = a.flumes if a.kind == "runoff" else a.gages
    if not ids:
        print(f"ERROR: {a.kind} needs --{'flumes' if a.kind == 'runoff' else 'gages'}", file=sys.stderr); return 2
    allowed = {"runoff": ("cf", "mm", "inches"), "precip": ("inches", "mm")}[a.kind]
    if a.units not in allowed:
        print(f"ERROR: --units for {a.kind} must be one of {allowed}", file=sys.stderr); return 2
    url = _endpoint(a.kind, s.year)
    form = build_form(a.kind, ids, s, e, a.type, a.units, a.watershed)
    try:
        body, route = post(url, form, _proxies(a.proxy))
    except ConnectionError as ex:
        print(f"NO ROUTE to {url}: {ex}", file=sys.stderr); return 3
    data_lines = [ln for ln in body.splitlines() if ln.strip() and not ln.startswith("#")]
    head = (f"#source_url: {url}\n#form: {urllib.parse.urlencode(form)}\n#route: {route}\n"
            f"#fetched_at: {dt.datetime.now().isoformat(timespec='seconds')}\n"
            f"#data_use: WGEW Data Use Agreement, {BASE}data_use_agreement.htm\n")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(head + body.replace("\r\n", "\n"))
    print(f"saved {out}: {len(data_lines)} data line(s) via {route}")
    return 0 if data_lines else 4


if __name__ == "__main__":
    sys.exit(main())
