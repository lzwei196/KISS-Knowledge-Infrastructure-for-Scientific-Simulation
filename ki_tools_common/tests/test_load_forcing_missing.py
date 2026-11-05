"""Missing data in the shared daily/hourly loaders is never filled.

Synthetic CMFD files and a fake NASA POWER service plant known gaps. The
loaders must stop by default (on_missing="raise"), return NaN with
on_missing="nan", and never turn missing rain into 0 mm or a missing extreme
into the daily mean. Complete inputs must give the plain mean/max/min/sum.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ki_tools_common import load_forcing as lf  # noqa: E402

LATS = np.array([30.05, 30.15])
LONS = np.array([115.05, 115.15])
VARS = {  # key: (value per step, unit note)
    "temp": 283.15,      # K
    "prec": 1e-4,        # kg m-2 s-1 -> 8.64 mm/day
    "srad": 150.0,
    "lrad": 300.0,
    "wind": 2.0,
    "shum": 0.008,
    "pres": 100000.0,
}


def write_cmfd_year(root, year, holes=None, drop_step=None, skip_vars=(), keep_until=None,
                    shift_var=None, repeat_all=None):
    """One flat V0200 file per variable for `year`, 3-hourly, 2x2 grid.
    holes: {var: [(step, ilat, ilon), ...]} set to NaN.
    drop_step: remove this time step from EVERY variable (a short day)."""
    import xarray as xr
    n = ((np.datetime64(f"{year + 1}-01-01") - np.datetime64(f"{year}-01-01"))
         .astype(int)) * 8
    times = np.datetime64(f"{year}-01-01T00:00") + np.arange(n) * np.timedelta64(3, "h")
    keep = np.ones(n, bool)
    if drop_step is not None:
        keep[np.atleast_1d(drop_step)] = False
    if keep_until is not None:          # store ends early (e.g. trailing months absent)
        keep &= times < np.datetime64(keep_until)
    for key, val in VARS.items():
        if key in skip_vars:            # this variable's file is absent from the store
            continue
        a = np.full((n, 2, 2), val, dtype="float32")
        if key == "temp":   # a daily cycle so max/min differ from the mean
            a += (4.0 * np.sin(np.arange(n) % 8 / 8 * 2 * np.pi))[:, None, None].astype("float32")
        for (s, i, j) in (holes or {}).get(key, []):
            a[s, i, j] = np.nan
        tk = times[keep]
        if repeat_all is not None:      # SAME bad axis in every variable: a step repeated,
            tk = tk.copy(); tk[repeat_all + 1] = tk[repeat_all]   # the next one lost
        if key == shift_var:            # same length, one step's time label moved
            tk = tk.copy(); tk[50] = tk[49]
        ds = xr.Dataset({key: (("time", "lat", "lon"), a[keep])},
                        coords={"time": tk, "lat": LATS, "lon": LONS})
        ds.to_netcdf(os.path.join(root, f"{key}_CMFD_V0200_B-01_03hr_010deg_"
                                         f"{year}01-{year}12.nc"))


class CMFDDaily(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_year_plain_statistics(self):
        write_cmfd_year(self.root, 2001)
        d = lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root)
        self.assertEqual(len(d["dates"]), 365)
        self.assertAlmostEqual(d["precip_mm"][0], 8.64, places=3)
        self.assertAlmostEqual(d["temp_mean_c"][0], 10.0, places=3)
        self.assertGreater(d["temp_max_c"][0], d["temp_mean_c"][0] + 3.5)
        self.assertLess(d["temp_min_c"][0], d["temp_mean_c"][0] - 3.5)
        self.assertTrue(np.all(np.isfinite(d["srad_wm2"])))

    def test_one_missing_rain_step_never_becomes_zero_or_partial_mean(self):
        write_cmfd_year(self.root, 2001, holes={"prec": [(8 * 40 + 3, 0, 0)]})
        with self.assertRaisesRegex(ValueError, r"precip_mm is missing on 1 of 365 days \(first: 2001-02-10"):
            lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root)
        d = lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root, on_missing="nan")
        self.assertTrue(np.isnan(d["precip_mm"][40]))
        self.assertEqual(int(np.sum(np.isnan(d["precip_mm"]))), 1)

    def test_all_missing_rain_day_is_not_zero(self):
        write_cmfd_year(self.root, 2001, holes={"prec": [(8 * 5 + k, 0, 0) for k in range(8)]})
        d = lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root, on_missing="nan")
        self.assertTrue(np.isnan(d["precip_mm"][5]))
        self.assertNotIn(0.0, list(d["precip_mm"]))

    def test_missing_temperature_step_makes_extremes_missing(self):
        write_cmfd_year(self.root, 2001, holes={"temp": [(8 * 7 + 2, 0, 0)]})
        d = lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root, on_missing="nan")
        for k in ("temp_mean_c", "temp_max_c", "temp_min_c"):
            self.assertTrue(np.isnan(d[k][7]), k)
        with self.assertRaisesRegex(ValueError, "temp_mean_c is missing"):
            lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root)

    def test_short_day_stops_even_with_nan(self):
        # One 3-hour record absent: the time axis is broken, so values cannot be
        # placed on their times; the loader stops whatever on_missing says.
        write_cmfd_year(self.root, 2001, drop_step=8 * 100 + 4)
        for om in ("raise", "nan"):
            with self.assertRaisesRegex(ValueError, "time steps are not equal after 2001-04-11T09:00"):
                lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root, on_missing=om)

    def test_store_short_on_every_day_stops(self):
        # 7 samples every day (the 21:00 step absent all year)
        write_cmfd_year(self.root, 2001, drop_step=list(range(7, 365 * 8, 8)))
        with self.assertRaisesRegex(ValueError, "time steps are not equal"):
            lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root)

    def test_missing_year_stops(self):
        write_cmfd_year(self.root, 2001)
        with self.assertRaisesRegex(ValueError, r"365 of 730 days in 2001-01-01..2002-12-31 are absent"):
            lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2002, self.root)

    def test_gap_in_other_variable_stops(self):
        write_cmfd_year(self.root, 2001, holes={"srad": [(8 * 3, 0, 0)]})
        with self.assertRaisesRegex(ValueError, "srad_wm2 is missing on 1 of 365"):
            lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root)

    def test_multi_point_same_rules(self):
        write_cmfd_year(self.root, 2001, holes={"prec": [(8 * 9 + 1, 1, 1)]})
        pts = [(30.05, 115.05), (30.15, 115.15)]
        with self.assertRaisesRegex(ValueError, r"\(30.15, 115.15\): precip_mm is missing"):
            lf.load_daily_forcing_points("cmfd", pts, 2001, 2001, self.root)
        res = lf.load_daily_forcing_points("cmfd", pts, 2001, 2001, self.root, on_missing="nan")
        self.assertTrue(np.isfinite(res[0]["precip_mm"][9]))
        self.assertTrue(np.isnan(res[1]["precip_mm"][9]))
        self.assertAlmostEqual(res[0]["precip_mm"][9], 8.64, places=3)

    def test_areal_partial_cell_gap_is_not_replaced_by_other_cells(self):
        write_cmfd_year(self.root, 2001, holes={"prec": [(8 * 12 + 5, 1, 1)]})
        lat = [30.05, 30.05, 30.15, 30.15]
        lon = [115.05, 115.15, 115.05, 115.15]
        d = lf.load_daily_forcing("cmfd", lat, lon, 2001, 2001, self.root, on_missing="nan")
        self.assertTrue(np.isnan(d["precip_mm"][12]))
        self.assertEqual(d["cmfd_cells_without_data"], 0)

    def test_areal_cell_outside_data_is_left_out_and_counted(self):
        never = [(s, 1, 1) for s in range(365 * 8)]
        write_cmfd_year(self.root, 2001, holes={k: never for k in VARS})
        lat = [30.05, 30.05, 30.15, 30.15]
        lon = [115.05, 115.15, 115.05, 115.15]
        d = lf.load_daily_forcing("cmfd", lat, lon, 2001, 2001, self.root)
        self.assertEqual(d["cmfd_cells_without_data"], 1)
        self.assertEqual(d["cmfd_cells_requested"], 4)
        self.assertAlmostEqual(d["precip_mm"][0], 8.64, places=3)

    def test_variable_file_absent_stops_unless_not_needed(self):
        write_cmfd_year(self.root, 2001, skip_vars=("lrad",))
        with self.assertRaisesRegex(ValueError, "lrad_wm2 is missing on 365 of 365"):
            lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root)
        d = lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root,
                                  variables=("P", "Tair", "SWd", "Wind", "spechum", "Pres"))
        self.assertTrue(np.all(np.isnan(d["lrad_wm2"])))
        # Names the loader does not know (older callers, e.g. SWAP "tmin", "prcp")
        # exclude nothing: every variable is checked, so the missing lrad stops.
        with self.assertWarnsRegex(UserWarning, "every variable is checked"):
            with self.assertRaisesRegex(ValueError, "lrad_wm2 is missing"):
                lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root,
                                      variables=["tmin", "tmax", "prcp", "srad", "wind", "rh"])

    def test_period_checks_only_the_part_year_asked_for(self):
        write_cmfd_year(self.root, 2001, keep_until="2001-07-01")
        with self.assertRaisesRegex(ValueError, "pass period="):
            lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root)
        d = lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root,
                                  period=("2001-03-01", "2001-06-30"))
        self.assertEqual(len(d["dates"]), 181)
        with self.assertRaisesRegex(ValueError, "absent from the source"):
            lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root,
                                  period=("2001-03-01", "2001-07-02"))
        with self.assertRaisesRegex(ValueError, "must lie inside"):
            lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root,
                                  period=("2000-12-01", "2001-01-31"))

    def test_period_gap_inside_still_stops(self):
        write_cmfd_year(self.root, 2001, holes={"prec": [(8 * 100 + 1, 0, 0)]})
        with self.assertRaisesRegex(ValueError, "precip_mm is missing on 1"):
            lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root,
                                  period=("2001-04-01", "2001-04-30"))
        d = lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root,
                                  period=("2001-05-01", "2001-05-31"))
        self.assertEqual(len(d["dates"]), 365)

    def test_subdaily_points_strict(self):
        pts = [(30.05, 115.05), (30.15, 115.15)]
        write_cmfd_year(self.root, 2001)
        res = lf.load_subdaily_forcing_points("cmfd", pts, 2001, 2001, self.root)
        self.assertEqual(len(res[0]["dates"]), 365 * 8)
        import shutil
        shutil.rmtree(self.root); os.makedirs(self.root)
        write_cmfd_year(self.root, 2001, skip_vars=("wind",))
        with self.assertRaisesRegex(ValueError, "wind_ms is missing"):
            lf.load_subdaily_forcing_points("cmfd", pts, 2001, 2001, self.root)
        shutil.rmtree(self.root); os.makedirs(self.root)
        write_cmfd_year(self.root, 2001, keep_until="2001-11-01")
        with self.assertRaisesRegex(ValueError, "needs 2920 evenly"):
            lf.load_subdaily_forcing_points("cmfd", pts, 2001, 2001, self.root)
        res = lf.load_subdaily_forcing_points("cmfd", pts, 2001, 2001, self.root,
                                              period=("2001-01-01", "2001-10-31"))
        self.assertEqual(len(res[1]["dates"]), 304 * 8)
        shutil.rmtree(self.root); os.makedirs(self.root)
        write_cmfd_year(self.root, 2001, holes={"prec": [(500, 1, 1)]})
        with self.assertRaisesRegex(ValueError, r"\(30.15, 115.15\): prec_kgm2s is missing"):
            lf.load_subdaily_forcing_points("cmfd", pts, 2001, 2001, self.root)

    def test_variable_with_shifted_time_axis_stops(self):
        write_cmfd_year(self.root, 2001, shift_var="prec")
        with self.assertRaisesRegex(ValueError, "CMFD prec 2001: time axis differs"):
            lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root)
        with self.assertRaisesRegex(ValueError, "CMFD prec 2001: time axis differs"):
            lf.load_daily_forcing_points("cmfd", [(30.05, 115.05), (30.15, 115.15)], 2001, 2001, self.root)
        with self.assertRaisesRegex(ValueError, "CMFD prec 2001: time axis differs"):
            lf.load_subdaily_forcing_points("cmfd", [(30.05, 115.05)], 2001, 2001, self.root)

    def test_same_bad_axis_in_every_variable_stops(self):
        # day 3: 00,03,06,09,09,15,18,21 -> still 8 records; 12:00 is missing
        write_cmfd_year(self.root, 2001, repeat_all=8 * 3 + 3)
        for call in (lambda: lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, self.root),
                     lambda: lf.load_daily_forcing_points("cmfd", [(30.05, 115.05), (30.15, 115.15)],
                                                          2001, 2001, self.root),
                     lambda: lf.load_subdaily_forcing_points("cmfd", [(30.05, 115.05)], 2001, 2001,
                                                             self.root)):
            with self.assertRaisesRegex(ValueError, "CMFD 2001: time steps are not equal after 2001-01-04T09:00"):
                call()

    def test_bad_on_missing_value(self):
        with self.assertRaisesRegex(ValueError, "on_missing must be one of"):
            lf.load_daily_forcing("cmfd", 30.0, 115.0, 2001, 2001, self.root, on_missing="fill")


def power_daily_json(year, holes):
    days = np.arange(np.datetime64(f"{year}-01-01"), np.datetime64(f"{year + 1}-01-01"))
    keys = [str(d).replace("-", "") for d in days]
    base = {"T2M": 10.0, "T2M_MIN": 5.0, "T2M_MAX": 15.0, "PRECTOTCORR": 3.0,
            "ALLSKY_SFC_SW_DWN": 4.8, "ALLSKY_SFC_LW_DWN": 7.2, "WS2M": 1.5,
            "WS10M": 2.5, "QV2M": 8.0, "PS": 100.0}
    par = {p: {k: v for k in keys} for p, v in base.items()}
    for p, idx in holes.items():
        for i in idx:
            par[p][keys[i]] = -999.0
    return {"properties": {"parameter": par}}


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def fake_session(payload):
    s = mock.MagicMock()
    s.get.return_value = FakeResp(payload)
    return s


class PowerDaily(unittest.TestCase):
    def run_power(self, holes, **kw):
        with mock.patch("requests.Session", return_value=fake_session(power_daily_json(2015, holes))):
            return lf.load_daily_forcing("nasa_power", 45.0, -75.0, 2015, 2015, **kw)

    def test_complete(self):
        d = self.run_power({})
        self.assertEqual(len(d["dates"]), 365)
        self.assertAlmostEqual(float(d["precip_mm"][0]), 3.0)
        self.assertAlmostEqual(float(d["wind_ms"][0]), 2.5)
        self.assertAlmostEqual(float(d["wind2_ms"][0]), 1.5)
        self.assertEqual(d["wind_height_m"], 10.0)

    def test_missing_rain_is_not_zero(self):
        with self.assertRaisesRegex(ValueError, "precip_mm is missing on 2 of 365"):
            self.run_power({"PRECTOTCORR": [3, 4]})
        d = self.run_power({"PRECTOTCORR": [3, 4]}, on_missing="nan")
        self.assertTrue(np.isnan(d["precip_mm"][3]) and np.isnan(d["precip_mm"][4]))

    def test_missing_extreme_is_not_the_mean(self):
        d = self.run_power({"T2M_MIN": [10], "T2M_MAX": [11]}, on_missing="nan")
        self.assertTrue(np.isnan(d["temp_min_c"][10]))
        self.assertTrue(np.isnan(d["temp_max_c"][11]))
        with self.assertRaisesRegex(ValueError, "temp_max_c is missing|temp_min_c is missing"):
            self.run_power({"T2M_MIN": [10]})

    def test_unneeded_variable_with_a_gap_does_not_stop(self):
        d = self.run_power({"WS10M": [7]}, variables=("P", "Tair"))
        self.assertTrue(np.isnan(d["wind_ms"][7]))
        with self.assertRaisesRegex(ValueError, "precip_mm is missing"):
            self.run_power({"PRECTOTCORR": [7]}, variables=("P", "Tair"))

    def test_missing_2m_wind_is_checked_too(self):
        with self.assertRaisesRegex(ValueError, "wind2_ms is missing on 1 of 365"):
            self.run_power({"WS2M": [30]})
        d = self.run_power({"WS2M": [30]}, variables=("P", "Tair", "SWd", "LWd", "spechum", "Pres"))
        self.assertTrue(np.isnan(d["wind2_ms"][30]))

    def test_missing_10m_wind_is_not_2m_wind(self):
        d = self.run_power({"WS10M": [20]}, on_missing="nan")
        self.assertTrue(np.isnan(d["wind_ms"][20]))
        self.assertAlmostEqual(float(d["wind2_ms"][20]), 1.5)
        with self.assertRaisesRegex(ValueError, "wind_ms is missing on 1 of 365"):
            self.run_power({"WS10M": [20]})


def power_hourly_json(year, holes):
    hrs = np.arange(np.datetime64(f"{year}-01-01T00"), np.datetime64(f"{year + 1}-01-01T00"),
                    np.timedelta64(1, "h"))
    keys = [str(h)[:13].replace("-", "").replace("T", "") for h in hrs]
    base = {"T2M": 10.0, "PRECTOTCORR": 0.5, "ALLSKY_SFC_SW_DWN": 200.0,
            "ALLSKY_SFC_LW_DWN": 300.0, "WS2M": 1.5, "WS10M": 2.5, "QV2M": 8.0, "PS": 100.0}
    par = {p: {k: v for k in keys} for p, v in base.items()}
    for p, idx in holes.items():
        for i in idx:
            par[p][keys[i]] = -999.0
    return {"properties": {"parameter": par},
            "parameters": {"PRECTOTCORR": {"units": "mm/hour"}}}


class NotRequested(unittest.TestCase):
    def test_mswx_unrequested_variables_may_be_all_nan(self):
        self.assertEqual(lf._not_requested("mswx", ("P",)),
                         ("temp_mean_c", "temp_max_c", "temp_min_c", "srad_wm2", "lrad_wm2",
                          "wind_ms", "wind2_ms", "shum_kgkg", "pres_pa"))
        self.assertEqual(lf._not_requested("cmfd", ("P",)), lf._not_requested("mswx", ("P",)))
        self.assertEqual(lf._not_requested("mswx", None), ())
        days = np.arange(np.datetime64("2015-01-01"), np.datetime64("2016-01-01"))
        out = {"dates": days, "precip_mm": np.ones(365),
               "temp_mean_c": np.full(365, np.nan), "temp_max_c": np.full(365, np.nan),
               "temp_min_c": np.full(365, np.nan), "wind_ms": np.full(365, np.nan)}
        lf._require_complete_daily(out, "mswx", 2015, 2015, "x", lf._not_requested("mswx", ("P",)))
        with self.assertRaisesRegex(ValueError, "temp_mean_c is missing on 365"):
            lf._require_complete_daily(out, "mswx", 2015, 2015, "x", lf._not_requested("mswx", ("P", "Tair")))
        with self.assertRaisesRegex(ValueError, "wind_ms is missing on 365"):
            lf._require_complete_daily(out, "nasa_power", 2015, 2015, "x", lf._not_requested("nasa_power", ("P", "Wind")))
        out["precip_mm"] = np.full(365, np.nan)
        with self.assertRaisesRegex(ValueError, "precip_mm is missing on 365"):
            lf._require_complete_daily(out, "mswx", 2015, 2015, "x", lf._not_requested("mswx", ("P",)))


class CMFDHourlyMonthly(unittest.TestCase):
    """load_hourly_forcing('cmfd') reads the monthly-file layout Temp/, Prec/, ..."""
    SUB = {"temp": "Temp", "prec": "Prec", "srad": "SRad", "lrad": "LRad",
           "wind": "Wind", "shum": "SHum", "pres": "Pres"}

    def write(self, root, year, bad=None):
        import xarray as xr
        for key, sub in self.SUB.items():
            os.makedirs(os.path.join(root, sub), exist_ok=True)
            for m in range(1, 13):
                t0 = np.datetime64(f"{year}-{m:02d}-01T00:00")
                t1 = np.datetime64(f"{year + (m == 12)}-{m % 12 + 1:02d}-01T00:00")
                times = np.arange(t0, t1, np.timedelta64(3, "h"))
                if bad and bad[0] == key and bad[1] == m:
                    times = times + np.timedelta64(90, "m")       # half-step shift
                a = np.full((times.size, 2, 2), VARS[key], dtype="float32")
                xr.Dataset({key: (("time", "lat", "lon"), a)},
                           coords={"time": times, "lat": LATS, "lon": LONS}).to_netcdf(
                    os.path.join(root, sub, f"{key}_CMFD_V0200_B-01_03hr_010deg_{year}{m:02d}.nc"))

    def test_real_time_axis_used_and_checked(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(d, 2001)
            out = lf.load_hourly_forcing("cmfd", 30.05, 115.05, 2001, 2001, d)
            self.assertEqual(len(out["dates"]), 2920)
            self.assertAlmostEqual(float(out["precip_mm"][0]), 1e-4 * 10800, places=4)
        with tempfile.TemporaryDirectory() as d:
            self.write(d, 2001, bad=("wind", 6))
            with self.assertRaisesRegex(ValueError, "CMFD sub-daily 2001-06 wind.*time axis differs"):
                lf.load_hourly_forcing("cmfd", 30.05, 115.05, 2001, 2001, d)


class OldStyleVariables(unittest.TestCase):
    def test_swap_style_names_load_complete_data(self):
        with tempfile.TemporaryDirectory() as d:
            write_cmfd_year(d, 2001)
            with self.assertWarns(UserWarning):
                out = lf.load_daily_forcing("cmfd", 30.05, 115.05, 2001, 2001, d,
                    variables=["tmin", "tmax", "prcp", "srad", "wind", "rh", "pres", "shum"])
            self.assertEqual(len(out["dates"]), 365)


class SameAxis(unittest.TestCase):
    def test_same_axis(self):
        a = np.arange(np.datetime64("2001-01-01"), np.datetime64("2001-01-11"))
        lf._same_axis(a, a.copy(), "x")
        b = a.copy(); b[3] = b[2]
        with self.assertRaisesRegex(ValueError, "x: time axis differs.*first difference at 2001-01-04"):
            lf._same_axis(a, b, "x")
        with self.assertRaisesRegex(ValueError, "no time coordinate"):
            lf._same_axis(a, None, "x")


class MswxTimeAxis(unittest.TestCase):
    def write(self, path, days_since_1900):
        import h5py
        with h5py.File(path, "w") as f:
            d = f.create_dataset("time", data=np.asarray(days_since_1900, dtype="float64"))
            d.attrs["units"] = b"days since 1900-1-1 00:00:00"

    def test_good_repeated_and_gapped_axes(self):
        with tempfile.TemporaryDirectory() as d:
            base = 42003.0                      # 2015-01-01 00:00
            good = base + np.arange(2920) * 0.125
            self.write(os.path.join(d, "g.nc"), good)
            lf._mswx_check_time(os.path.join(d, "g.nc"), 2015)
            rep = np.insert(good, 100, good[100])           # 2921 steps
            self.write(os.path.join(d, "r.nc"), rep)
            with self.assertRaisesRegex(ValueError, "2921 steps, expected 2920"):
                lf._mswx_check_time(os.path.join(d, "r.nc"), 2015)
            shifted = np.delete(np.insert(good, 100, good[100]), 2000)   # right count, wrong axis
            self.write(os.path.join(d, "s.nc"), shifted)
            with self.assertRaisesRegex(ValueError, "2920 steps, expected 2920.*first wrong step 2015-01-13"):
                lf._mswx_check_time(os.path.join(d, "s.nc"), 2015)


class PowerHourly(unittest.TestCase):
    def run_power(self, holes, **kw):
        payload = power_hourly_json(2015, holes)
        with mock.patch("requests.Session", return_value=fake_session(payload)), \
                mock.patch.object(lf, "_nasa_power_check_hourly_against_daily", return_value=None):
            return lf.load_hourly_forcing("nasa_power", 45.0, -75.0, 2015, 2015, **kw)

    def test_missing_hourly_rain_is_not_zero(self):
        with self.assertRaisesRegex(ValueError, "precip_mm is missing"):
            self.run_power({"PRECTOTCORR": [100]})
        d = self.run_power({"PRECTOTCORR": [100]}, on_missing="nan")
        self.assertTrue(np.isnan(d["precip_mm"][100]))

    def test_short_but_evenly_spaced_series_stops(self):
        payload = power_hourly_json(2015, {})
        for par in payload["properties"]["parameter"].values():
            for k in [k for k in par if k.startswith("201512")]:
                del par[k]                       # December missing, spacing still even
        with mock.patch("requests.Session", return_value=fake_session(payload)), \
                mock.patch.object(lf, "_nasa_power_check_hourly_against_daily", return_value=None):
            with self.assertRaisesRegex(ValueError, "needs 8760 evenly spaced steps"):
                lf.load_hourly_forcing("nasa_power", 45.0, -75.0, 2015, 2015)

    def test_wind_height_is_10m_and_not_mixed(self):
        d = self.run_power({"WS10M": [5]}, on_missing="nan")
        self.assertEqual(d["wind_height_m"], 10.0)
        self.assertTrue(np.isnan(d["wind_ms"][5]))
        self.assertAlmostEqual(float(d["wind_ms"][6]), 2.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
