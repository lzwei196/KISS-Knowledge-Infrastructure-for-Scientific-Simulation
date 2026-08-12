#!/usr/bin/env python3
"""
aggregate_grid_to_pixel.py — area-weight a DSSAT gridded ensemble
(grid_yield_long.csv from run_grid_ensemble.py) to the observation pixel's
support.

    sim_pixel(year) = SUM_members( area_ha * hwam_kgha ) / SUM_members( area_ha )

The weight of a member is the physical area of ITS OWN technology class
(irrigated or rainfed) from SPAM2020, so the pixel's irrigated fraction is
REPRESENTED rather than assumed. A single fully-auto-irrigated point run
implicitly asserts irrigated_fraction = 1.0; at 33.75N/114.25E the true SPAM
value is 0.61, and the missing 39% is exactly the drought-limited fraction that
carries the interannual signal.

This mirrors the OBS-side convention already used in
ki_tools_common/crop_obs.py::_load_spam_box / get_spam_regional_yield, where the
regional observed yield is likewise total production / total area rather than an
unweighted cell mean.

Only years for which EVERY member reports a yield are aggregated by default, so
the pixel series is not silently composed of a different member subset each
year (which would fabricate interannual variability). Use --allow_partial_years
to relax that, in which case the realised member count per year is reported.

Usage:
    python aggregate_grid_to_pixel.py \
        --long_csv  /tmp/grid/grid_yield_long.csv \
        --out_csv   /tmp/grid/pixel_sim_series.csv \
        --weights_csv /tmp/grid/weights.csv

Outputs
-------
--out_csv     : year, sim_kgha, n_members, irrigated_area_fraction, total_area_ha
--weights_csv : member_id, tech, area_ha, weight   (the audit trail)

Exit codes: 0 = ok; 1 = input error; 2 = nothing aggregatable.
"""

import argparse
import csv
import os
import sys
from collections import defaultdict


def read_long(path):
    """Read grid_yield_long.csv -> (records, weights).

    records : {(member_id, tech): {year: hwam_kgha}}
    weights : {(member_id, tech): area_ha}
    """
    records = defaultdict(dict)
    weights = {}
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        need = {'member_id', 'tech', 'year', 'hwam_kgha', 'area_ha'}
        if not need.issubset({c.strip() for c in (rd.fieldnames or [])}):
            raise ValueError(
                f"{path}: expected columns {sorted(need)}, got {rd.fieldnames}")
        for row in rd:
            key = (row['member_id'].strip(), row['tech'].strip())
            try:
                year = int(row['year'])
                hwam = float(row['hwam_kgha'])
                area = float(row['area_ha'])
            except (TypeError, ValueError):
                continue
            if area <= 0:
                continue
            records[key][year] = hwam
            weights[key] = area
    return records, weights


def aggregate(records, weights, allow_partial_years=False):
    """Area-weighted pixel-average yield per year."""
    if not records:
        return [], {}

    years_per_member = {k: set(v) for k, v in records.items()}
    all_years = sorted(set().union(*years_per_member.values()))
    complete = sorted(set.intersection(*years_per_member.values()))

    years = all_years if allow_partial_years else complete
    total_area = sum(weights.values())
    irr_area = sum(a for (mid, tech), a in weights.items() if tech.upper() == 'I')

    out = []
    for y in years:
        num = 0.0
        den = 0.0
        irr_num = 0.0
        n = 0
        for key, series in records.items():
            if y not in series:
                continue
            w = weights[key]
            num += w * series[y]
            den += w
            if key[1].upper() == 'I':
                irr_num += w
            n += 1
        if den <= 0:
            continue
        out.append({
            'year': y,
            'sim_kgha': round(num / den, 1),
            'n_members': n,
            'irrigated_area_fraction': round(irr_num / den, 4),
            'total_area_ha': round(den, 1),
        })

    meta = {
        'n_members_total': len(records),
        'total_area_ha': round(total_area, 1),
        'irrigated_area_fraction_all': (round(irr_area / total_area, 4)
                                        if total_area > 0 else None),
        'years_all': all_years,
        'years_complete': complete,
        'years_dropped_incomplete': (
            [] if allow_partial_years else sorted(set(all_years) - set(complete))),
    }
    return out, meta


def main():
    ap = argparse.ArgumentParser(
        description='Area-weight a DSSAT gridded ensemble to the obs pixel')
    ap.add_argument('--long_csv', required=True,
                    help='grid_yield_long.csv from run_grid_ensemble.py')
    ap.add_argument('--out_csv', required=True,
                    help='Output year,sim_kgha,... pixel series')
    ap.add_argument('--weights_csv', default=None,
                    help='Optional audit trail of the area weights')
    ap.add_argument('--allow_partial_years', action='store_true',
                    help='Aggregate years for which only SOME members reported '
                         '(default: drop them, and say so)')
    a = ap.parse_args()

    if not os.path.isfile(a.long_csv):
        sys.stderr.write(f"ERROR: not found: {a.long_csv}\n")
        sys.exit(1)
    try:
        records, weights = read_long(a.long_csv)
    except ValueError as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.exit(1)

    rows, meta = aggregate(records, weights, a.allow_partial_years)
    if not rows:
        sys.stderr.write(
            f"ERROR: nothing to aggregate from {a.long_csv} "
            f"({len(records)} member(s)).\n")
        sys.exit(2)

    os.makedirs(os.path.dirname(os.path.abspath(a.out_csv)) or '.', exist_ok=True)
    with open(a.out_csv, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['year', 'sim_kgha', 'n_members',
                                           'irrigated_area_fraction',
                                           'total_area_ha'])
        w.writeheader()
        w.writerows(rows)

    if a.weights_csv:
        total = sum(weights.values())
        os.makedirs(os.path.dirname(os.path.abspath(a.weights_csv)) or '.',
                    exist_ok=True)
        with open(a.weights_csv, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['member_id', 'tech', 'area_ha', 'weight'])
            for (mid, tech), area in sorted(weights.items()):
                w.writerow([mid, tech, round(area, 3),
                            round(area / total, 6) if total > 0 else 0])

    print(f"Aggregated {meta['n_members_total']} member(s), "
          f"{meta['total_area_ha']} ha, irrigated fraction "
          f"{meta['irrigated_area_fraction_all']} -> {len(rows)} year(s)")
    if meta['years_dropped_incomplete']:
        # No silent truncation: name the years that were not fully covered.
        print(f"DROPPED {len(meta['years_dropped_incomplete'])} incomplete "
              f"year(s) (not every member reported): "
              f"{meta['years_dropped_incomplete']}")
    print(f"Written: {a.out_csv}")
    for r in rows[:5]:
        print(f"  {r['year']}: {r['sim_kgha']} kg/ha "
              f"(n={r['n_members']}, irr_frac={r['irrigated_area_fraction']})")


if __name__ == '__main__':
    main()
