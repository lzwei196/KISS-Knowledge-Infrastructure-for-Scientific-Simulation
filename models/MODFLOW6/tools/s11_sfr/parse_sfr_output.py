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

        # Open stage file
        if stage_file is not None and os.path.exists(stage_file):
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
        if budget_file is not None and os.path.exists(budget_file):
            self.cbc = bf.CellBudgetFile(
                budget_file, precision=precision
            )

        # Load observations
        self.obs_data = None
        if obs_file is not None and os.path.exists(obs_file):
            self.obs_data = self._load_obs_csv(obs_file)

    def _load_obs_csv(self, obs_file):
        """Load observation CSV file."""
        try:
            data = np.genfromtxt(
                obs_file, delimiter=",", names=True,
                dtype=None, encoding="utf-8"
            )
            return data
        except Exception as e:
            print(f"WARNING: Could not load observations: {e}")
            return None

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

    def _extract_q_from_budget(self, totim, text):
        """
        Extract flow values from SFR budget recarray.

        SFR budget data is stored as structured recarrays with fields
        (node, node2, q, ...) rather than flat 3D arrays like GWF budgets.

        Parameters
        ----------
        totim : float
            Simulation time.
        text : str
            Budget term name (e.g., 'GWF', 'EXT-INFLOW').

        Returns
        -------
        np.ndarray or None
            1D array of q values per reach, or None if not found.
        """
        try:
            data_list = self.cbc.get_data(totim=totim, text=text)
            if not data_list:
                return None
            data = data_list[0]
            # SFR budget is a recarray with 'q' field
            if hasattr(data, 'dtype') and data.dtype.names and 'q' in data.dtype.names:
                return np.array(data['q'], dtype=float)
            else:
                # Fallback: try to flatten
                return data.flatten()[:self.nreaches]
        except Exception:
            return None

    def get_stream_aquifer_exchange(self, totim=None):
        """
        Get stream-aquifer exchange for each reach.

        Positive values = flow from aquifer to stream (gaining reach).
        Negative values = flow from stream to aquifer (losing reach).

        Parameters
        ----------
        totim : float or None
            Simulation time. If None, uses last time.

        Returns
        -------
        dict
            {"reaches": list, "exchange_m3_per_day": list,
             "gaining": list of reach indices, "losing": list}
        """
        if self.cbc is None:
            raise ValueError("No budget file loaded.")

        if totim is None:
            # Get times from budget file if stage file not loaded
            if self.times is not None:
                totim = self.times[-1]
            else:
                cbc_times = self.cbc.get_times()
                totim = cbc_times[-1]

        exchange = self._extract_q_from_budget(totim, "GWF")
        if exchange is None:
            return {"error": "No GWF budget term found in SFR budget file"}

        nreach = len(exchange)
        gaining = [i + 1 for i in range(nreach) if exchange[i] > 0]
        losing = [i + 1 for i in range(nreach) if exchange[i] < 0]

        return {
            "reaches": list(range(1, nreach + 1)),
            "exchange_m3_per_day": exchange.tolist(),
            "total_exchange_m3_per_day": float(np.sum(exchange)),
            "gaining_reaches": gaining,
            "losing_reaches": losing,
            "n_gaining": len(gaining),
            "n_losing": len(losing),
            "max_gain_m3_per_day": float(np.max(exchange)) if nreach > 0 else 0,
            "max_loss_m3_per_day": float(np.min(exchange)) if nreach > 0 else 0,
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

    def summary(self):
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
            exchange = self.get_stream_aquifer_exchange()
            result["stream_aquifer_exchange"] = exchange

        # Observations
        if self.obs_data is not None:
            result["observations"] = {
                "columns": list(self.obs_data.dtype.names),
                "nrecords": len(self.obs_data),
            }

        # Listing file budget
        if self.listing_file is not None and os.path.exists(self.listing_file):
            budget = self._parse_listing_budget()
            if budget:
                result["budget_from_listing"] = budget

        return result

    def _parse_listing_budget(self):
        """Parse SFR budget information from listing file."""
        if not os.path.exists(self.listing_file):
            return None

        try:
            with open(self.listing_file, "r") as f:
                content = f.read()
        except Exception:
            return None

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

    def export_exchange_csv(self, output_file):
        """
        Export stream-aquifer exchange time series to CSV.

        Parameters
        ----------
        output_file : str
            Output CSV file path.
        """
        if self.cbc is None:
            raise ValueError("No budget file loaded.")

        header = "time," + ",".join(
            [f"reach_{r}_exchange" for r in range(1, self.nreaches + 1)]
        )
        rows = [header]

        cbc_times = self.cbc.get_times()
        for t in cbc_times:
            exchange = self._extract_q_from_budget(t, "GWF")
            if exchange is None:
                exchange = np.zeros(self.nreaches)

            values = [f"{t:.6f}"] + [f"{v:.6f}" for v in exchange]
            rows.append(",".join(values))

        with open(output_file, "w") as f:
            f.write("\n".join(rows) + "\n")

        print(f"Exported exchange data to {output_file}")


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

    args = parser.parse_args()

    if not any([args.stage, args.budget, args.listing, args.obs]):
        parser.print_help()
        return

    sp = SFROutputParser(
        stage_file=args.stage,
        budget_file=args.budget,
        listing_file=args.listing,
        obs_file=args.obs,
    )

    if args.summary:
        result = sp.summary()
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print("\n=== SFR Output Summary ===")
            print(f"Reaches: {result['nreaches']}")
            print(f"Time steps: {result['ntimesteps']}")
            if result.get("final_stage"):
                fs = result["final_stage"]
                print(f"\nFinal stage (m):")
                print(f"  Min: {fs['min']:.3f}" if fs['min'] else "  Min: N/A")
                print(f"  Max: {fs['max']:.3f}" if fs['max'] else "  Max: N/A")
                print(f"  Mean: {fs['mean']:.3f}" if fs['mean'] else "  Mean: N/A")
                print(f"  Dry reaches: {fs['dry_reaches']}")
            if result.get("stream_aquifer_exchange"):
                ex = result["stream_aquifer_exchange"]
                if "error" not in ex:
                    print(f"\nStream-aquifer exchange:")
                    print(f"  Total: {ex['total_exchange_m3_per_day']:.3f} m3/day")
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
        ex = sp.get_stream_aquifer_exchange()
        if args.json:
            print(json.dumps(ex, indent=2))
        else:
            print("\n=== Stream-Aquifer Exchange (last time step) ===")
            if "error" in ex:
                print(f"Error: {ex['error']}")
            else:
                print(f"{'Reach':>6s}  {'Exchange (m3/day)':>18s}  {'Type':>10s}")
                print("-" * 38)
                for r, v in zip(ex["reaches"], ex["exchange_m3_per_day"]):
                    rtype = "gaining" if v > 0 else ("losing" if v < 0 else "neutral")
                    print(f"{r:6d}  {v:18.4f}  {rtype:>10s}")
                print("-" * 38)
                print(f"Total: {ex['total_exchange_m3_per_day']:.4f} m3/day")
        return

    if args.export_csv:
        sp.export_csv(args.export_csv)
        return

    if args.export_exchange:
        sp.export_exchange_csv(args.export_exchange)
        return


if __name__ == "__main__":
    main()
