#!/usr/bin/env python3
"""
split_kdown.py - Split CMFD total Kdown into direct-beam and diffuse components.

RHESSys requires BOTH Kdown_direct (beam) AND Kdown_diffuse to use measured radiation.
If only one is provided, RHESSys falls back to constant clear-sky radiation (silent error).

Method: Erbs et al. (1982) diffuse fraction model.
  kt = Kdown_measured / Ra_extraterrestrial  (clearness index)
  kd = diffuse_fraction:
    kt <= 0.22: kd = 1.0 - 0.09*kt
    0.22 < kt <= 0.80: kd = 0.9511 - 0.1604*kt + 4.388*kt^2 - 16.638*kt^3 + 12.336*kt^4
    kt > 0.80: kd = 0.165

Ra computation: FAO-56 equation for daily extraterrestrial radiation.
  phi: latitude in radians
  DOY: day of year (1-365)
"""
import math
import sys

def ra_daily(doy: int, lat_deg: float) -> float:
    """Extraterrestrial radiation [kJ/m2/day] for given DOY and latitude."""
    GSC = 82.0  # kJ/m2/min (= 0.0820 MJ/m2/min × 1000); FAO-56 solar constant
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi / 365 * doy)
    delta = 0.409 * math.sin(2 * math.pi / 365 * doy - 1.39)
    arg = -math.tan(phi) * math.tan(delta)
    arg = max(-1.0, min(1.0, arg))
    omega_s = math.acos(arg)
    Ra = (1440 / math.pi) * GSC * dr * (
        omega_s * math.sin(phi) * math.sin(delta)
        + math.cos(phi) * math.cos(delta) * math.sin(omega_s)
    )
    return max(Ra, 0.01)  # avoid division by zero at poles


def erbs_diffuse_fraction(kt: float) -> float:
    """Erbs et al. (1982) diffuse fraction from clearness index kt."""
    kt = max(0.0, min(1.0, kt))
    if kt <= 0.22:
        return 1.0 - 0.09 * kt
    elif kt <= 0.80:
        return 0.9511 - 0.1604*kt + 4.388*kt**2 - 16.638*kt**3 + 12.336*kt**4
    else:
        return 0.165


def split_kdown(kdown_file: str, lat_deg: float,
                out_direct: str, out_diffuse: str) -> None:
    with open(kdown_file) as f:
        lines = f.readlines()

    header = lines[0].strip()  # e.g. "1979 1 1 01"
    parts = header.split()
    year0, month0, day0 = int(parts[0]), int(parts[1]), int(parts[2])

    # Compute day-of-year for the starting date
    def doy_from_ymd(y, m, d):
        import datetime
        return datetime.date(y, m, d).timetuple().tm_yday

    out_dir = []
    out_dif = []
    doy_start = doy_from_ymd(year0, month0, day0)

    import datetime
    current = datetime.date(year0, month0, day0)
    for i, line in enumerate(lines[1:]):
        val = float(line.strip())
        doy = current.timetuple().tm_yday
        Ra = ra_daily(doy, lat_deg)
        kt = min(1.0, val / Ra)
        kd = erbs_diffuse_fraction(kt)
        diffuse = val * kd
        direct  = val * (1.0 - kd)
        out_dir.append(direct)
        out_dif.append(diffuse)
        current += datetime.timedelta(days=1)

    with open(out_direct, 'w') as f:
        f.write(header + '\n')
        for v in out_dir:
            f.write(f'{v:.4f}\n')

    with open(out_diffuse, 'w') as f:
        f.write(header + '\n')
        for v in out_dif:
            f.write(f'{v:.4f}\n')

    print(f"Wrote {len(out_dir)} values to {out_direct} and {out_diffuse}")
    # Sanity check: print first 7 split values
    print("\nDay | Total  | Direct | Diffuse | kt")
    current = datetime.date(year0, month0, day0)
    with open(kdown_file) as f:
        lines2 = f.readlines()
    for i in range(min(7, len(out_dir))):
        val = float(lines2[i+1].strip())
        doy = current.timetuple().tm_yday
        Ra = ra_daily(doy, lat_deg)
        kt = min(1.0, val/Ra)
        print(f"{current} (doy={doy:3d}) | {val:8.1f} | {out_dir[i]:8.1f} | {out_dif[i]:8.1f} | {kt:.3f}")
        current += datetime.timedelta(days=1)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--kdown', required=True, help='Input total Kdown file (RHESSys format)')
    p.add_argument('--lat', type=float, required=True, help='Latitude in degrees')
    p.add_argument('--out-direct', required=True, help='Output beam Kdown file')
    p.add_argument('--out-diffuse', required=True, help='Output diffuse Kdown file')
    args = p.parse_args()
    split_kdown(args.kdown, args.lat, args.out_direct, args.out_diffuse)
