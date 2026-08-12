#!/usr/bin/env python3
"""
gen_rain_duration.py — Generate RHESSys daytime_rain_duration from daily precipitation.

RHESSys defaults rain_duration = 86400 s (all day) when any precipitation > 0 and no
daytime_rain_duration file is provided. This zeroes transpiration on every rainy day
(zone_daily_F.c lines 293-309, dt_022). This tool generates a physically reasonable
duration estimate from precipitation intensity.

Method:
    rain_hours = min(24, precip_mm / rain_rate)
    where rain_rate is the assumed active rainfall rate (mm/hr).
    A rain_rate of 2 mm/hr is appropriate for humid subtropical/monsoon climates.

The output file is in hours (RHESSys reads as non-critical daily sequence and
multiplies by 3600 to get seconds in zone_daily_I.c line 460).

Usage:
    python gen_rain_duration.py \\
        --precip clim/bengbu_base.rain \\
        --out    clim/bengbu_base.daytime_rain_duration \\
        --rate   2.0

Then add to base station file:
    <increment non-critical daily sequence count by 1>
    daytime_rain_duration
"""
import argparse
import sys


def gen_rain_duration(precip_file: str, out_file: str, rain_rate: float) -> None:
    with open(precip_file) as f:
        lines = f.readlines()

    header = lines[0].strip()
    values = []
    for line in lines[1:]:
        precip_m = float(line.strip())
        precip_mm = precip_m * 1000.0
        if precip_mm <= 0:
            hours = 0.0
        else:
            hours = min(24.0, precip_mm / rain_rate)
        values.append(hours)

    with open(out_file, 'w') as f:
        f.write(header + '\n')
        for v in values:
            f.write(f'{v:.4f}\n')

    total = len(values)
    nonzero = sum(1 for v in values if v > 0)
    mean_rainy = (sum(v for v in values if v > 0) / nonzero) if nonzero > 0 else 0
    print(f"Wrote {total} days: {nonzero} rainy ({100*nonzero/total:.0f}%)")
    print(f"Mean rain duration on rainy days: {mean_rainy:.2f} h")
    print(f"Output: {out_file}")


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--precip', required=True,
                   help='Daily precipitation file (RHESSys format, m/day)')
    p.add_argument('--out', required=True,
                   help='Output daytime_rain_duration file (hours)')
    p.add_argument('--rate', type=float, default=2.0,
                   help='Assumed active rain rate (mm/hr). Default 2.0')
    args = p.parse_args()
    gen_rain_duration(args.precip, args.out, args.rate)
