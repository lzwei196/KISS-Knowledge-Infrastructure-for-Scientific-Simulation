#!/usr/bin/env python3
"""
parse_sfr_output.py -- Parse SFR (Streamflow Routing) output from MODFLOW 6.

Part of MODFLOW 6 Knowledge Infrastructure, Stage S11 (Streamflow Routing).
KDT v5.0 approach.

Reads:
  - Binary stage file (.sfr.stg) -- stream stage per reach per time step
  - Binary budget file (.sfr.cbc) -- stream-aquifer flow, inflow, outflow
  - Listing file (.lst) -- budget summaries, convergence info
  - CSV observation file (.sfr.obs.csv) -- if observations were defined

Key capabilities:
  1. Extract stream stage for any time step or all time steps
  2. Compute stream-aquifer exchange (gaining/losing reaches)
  3. Parse streamflow along the network (inflow/outflow per reach)
  4. Generate flow duration curves at observation points
  5. Parse SFR budget from listing file
  6. Export stage/flow time series to CSV/JSON

References:
  - mf6io.pdf pp. 123-137 (SFR Package)
  - FloPy: flopy.utils.binaryfile.HeadFile (reads .sfr.stg as STAGE)
  - FloPy: flopy.utils.CellBudgetFile (reads .sfr.cbc)
"""

import os
import sys
import json
import argparse
import re
import numpy as np

try:
    import flopy
    import flopy.utils.binaryfile as bf
except ImportError:
    print("ERROR: FloPy is required. Install with: pip install flopy")
    sys.exit(1)


def lyne_hollick_baseflow(flow, *, alpha, passes):
    """Derived low-frequency flow component, not direct groundwater exchange.

    Alternating forward/backward Lyne-Hollick recursion, with each pass
    initialized at the corresponding endpoint and constrained to [0, input].
    The constraint is applied to the recursive state: after clipping, the
    quickflow carried to the next step is input - clipped baseflow, so a
    negative quickflow from a recession does not suppress the next rise
    (constrained form, Ladson et al. 2013, Aust. J. Water Resour. 17(1)).
    Alpha and pass count must be specified identically for model and gauge.
    """
    q = np.asarray(flow, dtype=float)
    if q.ndim != 1 or len(q) < 2 or not np.isfinite(q).all() or (q < 0).any():
        raise ValueError("Baseflow filter requires >=2 finite nonnegative flow values")
    if (not np.isfinite(alpha) or not 0 < alpha < 1
            or not isinstance(passes, (int, np.integer)) or passes < 1):
        raise ValueError("Specify 0 < alpha < 1 and a positive integer pass count")
    base = q.copy()
    for pass_index in range(passes):
        previous = base.copy()
        quick = np.zeros(len(q))
        step = 1 if pass_index % 2 == 0 else -1
        indices = range(1, len(q)) if step == 1 else range(len(q) - 2, -1, -1)
        for i in indices:
            quick[i] = alpha * quick[i - step] + (1 + alpha) / 2 * (previous[i] - previous[i - step])
            base[i] = min(max(previous[i] - quick[i], 0.), previous[i])
            quick[i] = previous[i] - base[i]
    return base


class SFROutputParser:
    """Parse and analyze SFR (Streamflow Routing) model output."""

    def __init__(
        self,
        stage_file=None,
        budget_file=None,
        listing_file=None,
        obs_file=None,
        precision="double",
        nreaches=None,
    ):
        """
        Initialize parser.

        Parameters
        ----------
        stage_file : str or None
            Path to binary stage file (.sfr.stg).
        budget_file : str or None
            Path to SFR cell budget file (.sfr.cbc).
        listing_file : str or None
            Path to listing file (.lst).
        obs_file : str or None
            Path to observation CSV file (.sfr.obs.csv).
        precision : str
            Binary file precision: 'single' or 'double'.
            MODFLOW 6.6.1 linux binary is double precision.
        nreaches : int or None
            Number of reaches. Auto-detected from stage file if available.
        """
        self.stage_file = stage_file
        self.budget_file = budget_file
        self.listing_file = listing_file
        self.obs_file = obs_file
        self.precision = precision

        self.stg = None
        self.cbc = None
        self.times = None
        self.kstpkper = None
        self.nreaches = nreaches

        # A path that was given but does not exist is an error, never an
        # empty result.
        for label, path in (("stage", stage_file), ("budget", budget_file),
                            ("listing", listing_file), ("observation", obs_file)):
            if path is not None and not os.path.isfile(path):
                raise FileNotFoundError(f"SFR {label} file not found: {path}")

        # Open stage file
        if stage_file is not None:
            self.stg = bf.HeadFile(
                stage_file, precision=precision, text="STAGE"
            )
            self.times = self.stg.get_times()
            self.kstpkper = self.stg.get_kstpkper()

            # Detect nreaches from first record
            data0 = self.stg.get_data(totim=self.times[0])
            # SFR stage is stored as (1, 1, nreaches)
            self.nreaches = data0.shape[-1]

        # Open budget file
        if budget_file is not None:
            self.cbc = bf.CellBudgetFile(
                budget_file, precision=precision
            )

        # Load observations
        self.obs_data = None
        if obs_file is not None:
            self.obs_data = self._load_obs_csv(obs_file)

    def _load_obs_csv(self, obs_file):
        """Load observation CSV file; an unreadable file is an error."""
        try:
            data = np.genfromtxt(
                obs_file, delimiter=",", names=True,
                dtype=None, encoding="utf-8"
            )
        except Exception as e:
            raise ValueError(f"Could not read SFR observation file {obs_file}: {e}") from e
        if data.dtype.names is None:
            raise ValueError(f"SFR observation file {obs_file} has no header columns")
        return np.atleast_1d(data)  # one data row gives a 0-d array

    def get_stages(self, totim=None, kstpkper=None):
        """
        Get stream stage for all reaches at a specific time.

        Parameters
        ----------
        totim : float or None
            Simulation time. If None, returns last time step.
        kstpkper : tuple or None
            (time step, stress period) tuple. Overrides totim.

        Returns
        -------
        np.ndarray
            1D array of stages, length = nreaches.
        """
        if self.stg is None:
            raise ValueError("No stage file loaded.")

        if kstpkper is not None:
            data = self.stg.get_data(kstpkper=kstpkper)
        elif totim is not None:
            data = self.stg.get_data(totim=totim)
        else:
            data = self.stg.get_data(totim=self.times[-1])

        return data.flatten()[:self.nreaches]

    def get_all_stages(self):
        """
        Get stage time series for all reaches across all time steps.

        Returns
        -------
        dict
            {"times": list, "stages": 2D array (ntimes x nreaches)}
        """
        if self.stg is None:
            raise ValueError("No stage file loaded.")

        all_stages = []
        for t in self.times:
            stages = self.get_stages(totim=t)
            all_stages.append(stages)

        return {
            "times": list(self.times),
            "stages": np.array(all_stages),
        }

    def get_budget_terms(self):
        """
        Get available budget term names from the SFR budget file.

        Returns
        -------
        list of str
            Budget term names (e.g., 'GWF', 'RAINFALL', 'EVAPORATION',
            'RUNOFF', 'EXT-INFLOW', 'EXT-OUTFLOW', 'STORAGE',
            'FROM-MVR', 'TO-MVR').
        """
        if self.cbc is None:
            raise ValueError("No budget file loaded.")

        return self.cbc.get_unique_record_names()

    def _budget_records(self, text):
        """All SFR budget records for one term, selected by exact record index.

        FloPy's get_data(totim=...) matches times with np.isclose, so close but
        distinct time steps can match one query. Records are therefore read by
        their index in the file (cbc.get_indices / cbc.get_record) and carry
        their own (kstp, kper, totim). Returns a list of
        (totim, kstp, kper, recarray) in file order. Raises ValueError if the
        term is absent, a record is not a node/q list, times are not strictly
        increasing, a time step appears twice (ambiguous), or the term is
        missing at any time step saved in the budget file (MODFLOW 6 writes
        every SFR budget term at each saved step, so a gap means lost data,
        never a step to skip).
        """
        if self.cbc is None:
            raise ValueError("No budget file loaded.")
        try:
            indices = self.cbc.get_indices(text=text)
        except ValueError as exc:
            raise ValueError(f"No {text} term in SFR budget file") from exc
        if indices is None or len(indices) == 0:
            raise ValueError(f"No {text} records in SFR budget file")
        ra = self.cbc.recordarray
        out = []
        for idx in indices:
            idx = int(idx)
            rec = self.cbc.get_record(idx)
            if not {"node", "q"}.issubset(getattr(rec, "dtype", np.dtype([])).names or ()):
                raise ValueError(f"{text} record {idx} is not a node/q list")
            out.append((float(ra["totim"][idx]), int(ra["kstp"][idx]),
                        int(ra["kper"][idx]), rec))
        times = np.array([r[0] for r in out])
        steps = [(r[1], r[2]) for r in out]
        if not np.isfinite(times).all() or (np.diff(times) <= 0).any():
            raise ValueError(f"{text} record times must be finite and strictly increasing")
        if len(set(steps)) != len(steps):
            raise ValueError(f"Ambiguous {text} records: a (kstp, kper) appears more than once")
        saved = {(int(k), int(p)) for k, p in zip(ra["kstp"], ra["kper"])}
        missing = sorted(saved - set(steps))
        if missing:
            raise ValueError(f"{text} record missing at saved time step(s) (kstp, kper) {missing[:5]}"
                             f"{' ...' if len(missing) > 5 else ''}")
        return out

    @staticmethod
    def _check_units(length_unit_m, time_unit_seconds):
        if (length_unit_m is None) != (time_unit_seconds is None):
            raise ValueError("Give both length_unit_m and time_unit_seconds, or neither")
        if length_unit_m is not None and any(
                not np.isfinite(v) or v <= 0 for v in (length_unit_m, time_unit_seconds)):
            raise ValueError("Length and time unit conversion factors must be finite and positive")

    def _exchange_by_reach(self, rec, time):
        """GWF exchange q keyed by 1-based reach (record node), not row order."""
        nodes = np.asarray(rec["node"], dtype=int)
        q = np.asarray(rec["q"], dtype=float)
        # A present record with zero entries is valid: no reach is connected
        # to a GWF cell (cellid NONE in SFR PACKAGEDATA). An absent record is
        # caught in _budget_records.
        if len(set(nodes.tolist())) != len(nodes):
            raise ValueError(f"Duplicate reach IDs in GWF exchange record at time {time}")
        if not np.isfinite(q).all():
            raise ValueError(f"Nonfinite GWF exchange at time {time}")
        order = np.argsort(nodes)
        return nodes[order], q[order]

    def get_stream_aquifer_exchange(self, totim=None, length_unit_m=None,
                                    time_unit_seconds=None):
        """
        Get stream-aquifer exchange for each reach (SFR budget term GWF).

        Positive values = flow from aquifer to stream (gaining reach).
        Negative values = flow from stream to aquifer (losing reach).

        MODFLOW writes q in model length^3 / model time. Give both
        length_unit_m and time_unit_seconds to convert to m3/day; otherwise
        values stay in native model units and are labelled so.

        Parameters
        ----------
        totim : float or None
            Simulation time; must equal a record time exactly. None = last.

        Returns
        -------
        dict with "reaches", "exchange", "unit", totals and gaining/losing
        reach IDs. Raises ValueError if the GWF term or the time is missing.
        """
        self._check_units(length_unit_m, time_unit_seconds)
        records = self._budget_records("GWF")
        if totim is None:
            time, _, _, rec = records[-1]
        else:
            match = [r for r in records if r[0] == float(totim)]
            if len(match) != 1:
                raise ValueError(f"No single GWF exchange record at time {totim}")
            time, _, _, rec = match[0]
        nodes, exchange = self._exchange_by_reach(rec, time)
        if length_unit_m is not None:
            exchange = exchange * length_unit_m ** 3 / time_unit_seconds * 86400.0
            unit = "m3/day"
        else:
            unit = "model_length^3/model_time (native, not converted)"
        gaining = [int(n) for n, v in zip(nodes, exchange) if v > 0]
        losing = [int(n) for n, v in zip(nodes, exchange) if v < 0]

        return {
            "time": time,
            "unit": unit,
            "reaches": [int(n) for n in nodes],
            "exchange": exchange.tolist(),
            "total_exchange": float(np.sum(exchange)),
            "gaining_reaches": gaining,
            "losing_reaches": losing,
            "n_gaining": len(gaining),
            "n_losing": len(losing),
            "n_connected_reaches": int(len(nodes)),
            "max_gain": float(np.max(exchange)) if len(nodes) else None,
            "max_loss": float(np.min(exchange)) if len(nodes) else None,
        }

    def stage_time_series(self, reach_number):
        """
        Get stage time series for a specific reach.

        Parameters
        ----------
        reach_number : int
            1-based reach number.

        Returns
        -------
        dict
            {"times": list, "stages": list}
        """
        if self.stg is None:
            raise ValueError("No stage file loaded.")

        idx = reach_number - 1  # Convert to 0-based
        stages = []
        for t in self.times:
            data = self.get_stages(totim=t)
            stages.append(float(data[idx]))

        return {
            "reach": reach_number,
            "times": list(self.times),
            "stages": stages,
        }

    def outlet_flow_time_series(self, reach_numbers, *, length_unit_m, time_unit_seconds):
        """Negated EXT-OUTFLOW at explicit 1-based outlets, converted to m3/s.

        Native SFR budget sign is negative for external downstream outflow
        (USGS gwf-sfr.f90 sfr_cq). Select by record node ID, never row order.
        Unit conversion is explicit because MODFLOW units are user-defined.
        """
        reaches = list(reach_numbers)
        if (not reaches or len(set(reaches)) != len(reaches)
                or any(not isinstance(i, (int, np.integer)) or i <= 0 for i in reaches)):
            raise ValueError("Specify unique positive 1-based outlet reach IDs")
        if any(not np.isfinite(v) or v <= 0 for v in (length_unit_m, time_unit_seconds)):
            raise ValueError("Length and time unit conversion factors must be finite and positive")
        if self.cbc is None:
            raise ValueError("An SFR budget file is required for streamflow")
        records = self._budget_records("EXT-OUTFLOW")
        times = np.array([r[0] for r in records], dtype=float)
        flows = []
        for time, _, _, rec in records:
            selected = []
            for reach in reaches:
                values = rec["q"][rec["node"] == reach]
                if len(values) != 1 or not np.isfinite(values).all() or (values > 0).any():
                    raise ValueError(f"Missing, duplicate, nonfinite or positive EXT-OUTFLOW for reach {reach} at time {time}")
                selected.append(float(values[0]))
            flows.append(-sum(selected) * length_unit_m ** 3 / time_unit_seconds)
        if not np.isfinite(flows).all():
            raise ValueError("Converted streamflow is nonfinite")
        return {"dag_variable": "streamflow", "reach_numbers": reaches,
                "times": times.tolist(), "time_unit_seconds": time_unit_seconds,
                "length_unit_m": length_unit_m, "unit": "m3/s",
                "source_term": "EXT-OUTFLOW", "sign_conversion": "negate native outflow",
                "streamflow": flows}

    def summary(self, length_unit_m=None, time_unit_seconds=None):
        """
        Generate a comprehensive summary of SFR output.

        Returns
        -------
        dict
            Summary with stage statistics, exchange summary, etc.
        """
        result = {
            "nreaches": self.nreaches,
            "ntimesteps": len(self.times) if self.times else 0,
            "simulation_time": {
                "start": float(self.times[0]) if self.times else None,
                "end": float(self.times[-1]) if self.times else None,
            },
        }

        # Stage summary at last time step
        if self.stg is not None:
            final_stages = self.get_stages()
            # Filter sentinel values: MODFLOW 6 uses 1e30 (HDRY) or -1e30
            # (DNODATA) for dry/inactive reaches
            valid = final_stages[
                (final_stages < 1e10) & (final_stages > -1e10)
            ]
            n_dry = int(np.sum(
                (final_stages >= 1e10) | (final_stages <= -1e10)
            ))
            result["final_stage"] = {
                "min": float(np.min(valid)) if len(valid) > 0 else None,
                "max": float(np.max(valid)) if len(valid) > 0 else None,
                "mean": float(np.mean(valid)) if len(valid) > 0 else None,
                "n_valid_reaches": int(len(valid)),
                "dry_reaches": n_dry,
            }

        # Exchange summary at last time step
        if self.cbc is not None:
            result["stream_aquifer_exchange"] = self.get_stream_aquifer_exchange(
                length_unit_m=length_unit_m, time_unit_seconds=time_unit_seconds)

        # Observations
        if self.obs_data is not None:
            result["observations"] = {
                "columns": list(self.obs_data.dtype.names),
                "nrecords": len(self.obs_data),
            }

        # Listing file budget
        if self.listing_file is not None:
            result["budget_from_listing"] = self._parse_listing_budget()

        return result

    def _parse_listing_budget(self):
        """Parse SFR budget information from listing file."""
        try:
            with open(self.listing_file, "r") as f:
                content = f.read()
        except OSError as exc:
            raise OSError(f"Could not read listing file {self.listing_file}: {exc}") from exc

        # Find SFR budget sections
        budget_info = {}

        # Look for PERCENT DISCREPANCY
        pct_pattern = r"PERCENT DISCREPANCY\s*=\s*([\d\.\-eE\+]+)"
        pct_matches = re.findall(pct_pattern, content)
        if pct_matches:
            budget_info["percent_discrepancy_last"] = float(pct_matches[-1])

        # Look for SFR-related budget in the model listing
        # SFR IN/OUT flows appear in the volumetric budget of the GWF model
        sfr_in_pattern = r"SFR\s*=\s*([\d\.\-eE\+]+)"
        sfr_matches = re.findall(sfr_in_pattern, content)
        if sfr_matches:
            # SFR appears twice: once in IN section, once in OUT section
            budget_info["sfr_budget_terms_found"] = len(sfr_matches)

        # Check for convergence issues
        if "FAILED TO CONVERGE" in content:
            budget_info["convergence_failures"] = content.count(
                "FAILED TO CONVERGE"
            )
        else:
            budget_info["convergence_failures"] = 0

        # Check for normal termination in model listing or simulation listing
        budget_info["normal_termination"] = "Normal termination" in content

        # Also check mfsim.lst in the same directory
        if not budget_info["normal_termination"]:
            sim_lst = os.path.join(
                os.path.dirname(self.listing_file), "mfsim.lst"
            )
            if os.path.exists(sim_lst):
                try:
                    with open(sim_lst, "r") as f:
                        sim_content = f.read()
                    budget_info["normal_termination"] = (
                        "Normal termination" in sim_content
                    )
                except Exception:
                    pass

        return budget_info

    def export_csv(self, output_file, reach_numbers=None):
        """
        Export stage time series to CSV.

        Parameters
        ----------
        output_file : str
            Output CSV file path.
        reach_numbers : list of int or None
            1-based reach numbers to include. If None, all reaches.
        """
        if self.stg is None:
            raise ValueError("No stage file loaded.")

        if reach_numbers is None:
            reach_numbers = list(range(1, self.nreaches + 1))

        header = "time," + ",".join(
            [f"reach_{r}" for r in reach_numbers]
        )
        rows = [header]

        for t in self.times:
            stages = self.get_stages(totim=t)
            values = [f"{t:.6f}"] + [
                f"{stages[r - 1]:.6f}" for r in reach_numbers
            ]
            rows.append(",".join(values))

        with open(output_file, "w") as f:
            f.write("\n".join(rows) + "\n")

        print(f"Exported {len(self.times)} time steps, "
              f"{len(reach_numbers)} reaches to {output_file}")

    def export_exchange_csv(self, output_file, length_unit_m=None,
                            time_unit_seconds=None):
        """
        Export stream-aquifer exchange time series to CSV.

        Every time step must have a GWF record for the same reaches; a missing
        or changed record stops the export (it is never written as zero flow).
        Values are native model units unless both unit factors are given, in
        which case they are m3/day. The unit is written in the header line.
        """
        self._check_units(length_unit_m, time_unit_seconds)
        records = self._budget_records("GWF")
        reach_ids = None
        rows = []
        for time, _, _, rec in records:
            nodes, exchange = self._exchange_by_reach(rec, time)
            if reach_ids is None:
                reach_ids = nodes
            elif not np.array_equal(nodes, reach_ids):
                raise ValueError(f"GWF exchange reaches change at time {time}")
            if length_unit_m is not None:
                exchange = exchange * length_unit_m ** 3 / time_unit_seconds * 86400.0
            rows.append(",".join([f"{time:.6f}"] + [f"{v:.6f}" for v in exchange]))
        unit = ("m3/day" if length_unit_m is not None
                else "model_length^3/model_time (native, not converted)")
        header = ",".join(["time"] + [f"reach_{r}_exchange" for r in reach_ids])

        with open(output_file, "w") as f:
            f.write(f"# unit: {unit}\n" + header + "\n" + "\n".join(rows) + "\n")

        print(f"Exported exchange data ({len(rows)} time steps, {unit}) to {output_file}")


# ---------------------------------------------------------------------------
# CLI interface
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Parse MODFLOW 6 SFR output (stage, budget, exchange)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Summary of SFR results
  python parse_sfr_output.py --stage gwf.sfr.stg --summary

  # Stage time series for specific reach
  python parse_sfr_output.py --stage gwf.sfr.stg --reach-ts 5

  # Stream-aquifer exchange analysis
  python parse_sfr_output.py --budget gwf.sfr.cbc --exchange \\
      --listing gwf.lst

  # Export all stages to CSV
  python parse_sfr_output.py --stage gwf.sfr.stg --export-csv stages.csv

  # Export exchange to CSV
  python parse_sfr_output.py --budget gwf.sfr.cbc --export-exchange exch.csv

  # Full analysis as JSON
  python parse_sfr_output.py --stage gwf.sfr.stg --budget gwf.sfr.cbc \\
      --listing gwf.lst --summary --json
        """,
    )

    parser.add_argument("--stage", type=str,
                        help="Path to SFR stage file (.sfr.stg)")
    parser.add_argument("--budget", type=str,
                        help="Path to SFR budget file (.sfr.cbc)")
    parser.add_argument("--listing", type=str,
                        help="Path to listing file (.lst)")
    parser.add_argument("--obs", type=str,
                        help="Path to observation CSV file (.sfr.obs.csv)")
    parser.add_argument("--summary", action="store_true",
                        help="Print comprehensive summary")
    parser.add_argument("--reach-ts", type=int,
                        help="Stage time series for a reach (1-based)")
    parser.add_argument("--exchange", action="store_true",
                        help="Print stream-aquifer exchange analysis")
    parser.add_argument("--export-csv", type=str,
                        help="Export stages to CSV file")
    parser.add_argument("--export-exchange", type=str,
                        help="Export exchange to CSV file")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--outlet-reaches", nargs="+", type=int,
                        help="1-based external outlet IDs for streamflow JSON")
    parser.add_argument("--length-unit-m", type=float,
                        help="Model length unit in metres (required for --outlet-reaches; "
                             "optional for exchange output, which is then m3/day)")
    parser.add_argument("--time-unit-seconds", type=float,
                        help="Model time unit in seconds (pair with --length-unit-m)")
    parser.add_argument("--baseflow-alpha", type=float, help="Explicit Lyne-Hollick filter alpha")
    parser.add_argument("--baseflow-passes", type=int, help="Explicit alternating filter pass count")

    args = parser.parse_args()

    if (args.length_unit_m is None) != (args.time_unit_seconds is None):
        parser.error("Specify both --length-unit-m and --time-unit-seconds, or neither")
    units = dict(length_unit_m=args.length_unit_m, time_unit_seconds=args.time_unit_seconds)

    if args.outlet_reaches is not None:
        if not args.budget or args.length_unit_m is None or args.time_unit_seconds is None:
            parser.error("--outlet-reaches requires --budget, --length-unit-m and --time-unit-seconds")
    if (args.baseflow_alpha is None) != (args.baseflow_passes is None):
        parser.error("Specify both --baseflow-alpha and --baseflow-passes")
    if args.baseflow_alpha is not None and args.outlet_reaches is None:
        parser.error("Baseflow requires --outlet-reaches")

    if not any([args.stage, args.budget, args.listing, args.obs]):
        parser.print_help()
        return

    sp = SFROutputParser(
        stage_file=args.stage,
        budget_file=args.budget,
        listing_file=args.listing,
        obs_file=args.obs,
    )

    if args.outlet_reaches is not None:
        result = sp.outlet_flow_time_series(args.outlet_reaches,
            length_unit_m=args.length_unit_m, time_unit_seconds=args.time_unit_seconds)
        if args.baseflow_alpha is not None:
            steps = np.diff(result["times"])
            if not len(steps) or not np.allclose(steps, steps[0], rtol=1e-9, atol=1e-12):
                raise ValueError("Baseflow filtering requires a regular time interval; no resampling is performed")
            result["baseflow"] = lyne_hollick_baseflow(result["streamflow"],
                alpha=args.baseflow_alpha, passes=args.baseflow_passes).tolist()
            result["baseflow_derivation"] = {"method": "Lyne-Hollick",
                "alpha": args.baseflow_alpha, "passes": args.baseflow_passes,
                "cadence_seconds": float(steps[0] * args.time_unit_seconds),
                "meaning": "filtered outlet-flow component, not direct GWF exchange"}
        print(json.dumps(result, indent=2, allow_nan=False))
        return

    if args.summary:
        result = sp.summary(**units)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print("\n=== SFR Output Summary ===")
            print(f"Reaches: {result['nreaches']}")
            print(f"Time steps: {result['ntimesteps']}")
            if result.get("final_stage"):
                fs = result["final_stage"]
                print(f"\nFinal stage (m):")
                print(f"  Min: {fs['min']:.3f}" if fs['min'] is not None else "  Min: N/A")
                print(f"  Max: {fs['max']:.3f}" if fs['max'] is not None else "  Max: N/A")
                print(f"  Mean: {fs['mean']:.3f}" if fs['mean'] is not None else "  Mean: N/A")
                print(f"  Dry reaches: {fs['dry_reaches']}")
            if result.get("stream_aquifer_exchange"):
                ex = result["stream_aquifer_exchange"]
                print(f"\nStream-aquifer exchange:")
                print(f"  Total: {ex['total_exchange']:.3f} {ex['unit']}")
                print(f"  Gaining reaches: {ex['n_gaining']}")
                print(f"  Losing reaches: {ex['n_losing']}")
            if result.get("budget_from_listing"):
                bl = result["budget_from_listing"]
                print(f"\nBudget:")
                print(f"  Normal termination: {bl['normal_termination']}")
                print(f"  Convergence failures: {bl['convergence_failures']}")
                if "percent_discrepancy_last" in bl:
                    print(f"  Percent discrepancy: "
                          f"{bl['percent_discrepancy_last']:.4f}%")
        return

    if args.reach_ts:
        ts = sp.stage_time_series(args.reach_ts)
        if args.json:
            print(json.dumps(ts, indent=2))
        else:
            print(f"\nStage time series for reach {args.reach_ts}:")
            print(f"{'Time':>12s}  {'Stage (m)':>12s}")
            print("-" * 26)
            for t, s in zip(ts["times"], ts["stages"]):
                print(f"{t:12.2f}  {s:12.4f}")
        return

    if args.exchange:
        ex = sp.get_stream_aquifer_exchange(**units)
        if args.json:
            print(json.dumps(ex, indent=2))
        else:
            print("\n=== Stream-Aquifer Exchange (last time step) ===")
            print(f"Unit: {ex['unit']}")
            print(f"{'Reach':>6s}  {'Exchange':>18s}  {'Type':>10s}")
            print("-" * 38)
            for r, v in zip(ex["reaches"], ex["exchange"]):
                rtype = "gaining" if v > 0 else ("losing" if v < 0 else "neutral")
                print(f"{r:6d}  {v:18.4f}  {rtype:>10s}")
            print("-" * 38)
            print(f"Total: {ex['total_exchange']:.4f} {ex['unit']}")
        return

    if args.export_csv:
        sp.export_csv(args.export_csv)
        return

    if args.export_exchange:
        sp.export_exchange_csv(args.export_exchange, **units)
        return


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
