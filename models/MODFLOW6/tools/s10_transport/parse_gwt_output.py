#!/usr/bin/env python3
"""
parse_gwt_output.py -- Parse GWT concentration output, compute plume extent,
breakthrough curves, mass budget analysis.

Part of MODFLOW 6 Knowledge Infrastructure, Stage S10 (Transport).
KDT v5.0 approach.

Reads:
  - Binary concentration file (.ucn) -- same format as .hds (HeadFile)
  - Cell budget file (.cbc) -- mass flow terms
  - Listing file (.lst) -- mass budget summaries

Key capabilities:
  1. Extract concentration arrays for any time step
  2. Compute plume extent (cells above threshold)
  3. Generate breakthrough curves (concentration vs time at observation points)
  4. Parse mass budget from listing file
  5. Compute concentration statistics (max, mean, mass in domain)
  6. Export concentrations to numpy/CSV for further analysis

References:
  - mf6io.pdf pp. 176-177 (GWT Output Control)
  - FloPy: flopy.utils.binaryfile.HeadFile (also reads .ucn files)
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


class GWTOutputParser:
    """Parse and analyze GWT (Groundwater Transport) model output."""

    def __init__(
        self,
        concentration_file,
        budget_file=None,
        listing_file=None,
        precision="double",
        nlay=None,
        nrow=None,
        ncol=None,
        delr=None,
        delc=None,
    ):
        """
        Initialize parser.

        Parameters
        ----------
        concentration_file : str
            Path to binary concentration file (.ucn).
        budget_file : str or None
            Path to cell budget file (.cbc).
        listing_file : str or None
            Path to listing file (.lst).
        precision : str
            Binary file precision: 'single' or 'double'.
            MODFLOW 6.6.1 linux binary is double precision.
        nlay, nrow, ncol : int or None
            Grid dimensions (auto-detected from concentration file if not given).
        delr, delc : float/array or None
            Cell sizes in meters (needed for plume extent calculations).
        """
        self.concentration_file = concentration_file
        self.budget_file = budget_file
        self.listing_file = listing_file
        self.precision = precision

        if not os.path.exists(concentration_file):
            raise FileNotFoundError(f"Concentration file not found: {concentration_file}")

        # Open concentration file (same binary format as HeadFile but with
        # text="CONCENTRATION" instead of "HEAD")
        self.ucn = bf.HeadFile(concentration_file, precision=precision,
                               text="CONCENTRATION")

        # Get time info
        self.times = self.ucn.get_times()
        self.kstpkper = self.ucn.get_kstpkper()

        # Get grid dimensions from first record
        data0 = self.ucn.get_data(totim=self.times[0])
        self.nlay = data0.shape[0]
        self.nrow = data0.shape[1]
        self.ncol = data0.shape[2]

        # Override if explicitly provided
        if nlay is not None:
            self.nlay = nlay
        if nrow is not None:
            self.nrow = nrow
        if ncol is not None:
            self.ncol = ncol

        self.delr = delr
        self.delc = delc

        # Open budget file if provided
        self.cbc = None
        if budget_file is not None and os.path.exists(budget_file):
            self.cbc = bf.CellBudgetFile(budget_file, precision=precision)

    def get_concentration(self, totim=None, kstpkper=None, layer=None):
        """
        Get concentration array for a specific time.

        Parameters
        ----------
        totim : float or None
            Total simulation time. If None, uses last time step.
        kstpkper : tuple or None
            (time_step, stress_period) tuple (0-indexed).
        layer : int or None
            If specified, return only this layer (0-indexed).

        Returns
        -------
        np.ndarray
            Concentration array: (nlay, nrow, ncol) or (nrow, ncol) if layer specified.
        """
        if totim is None and kstpkper is None:
            totim = self.times[-1]

        if totim is not None:
            conc = self.ucn.get_data(totim=totim)
        else:
            conc = self.ucn.get_data(kstpkper=kstpkper)

        if layer is not None:
            return conc[layer]
        return conc

    def get_all_concentrations(self):
        """
        Get concentration arrays for all saved time steps.

        Returns
        -------
        dict
            {totim: conc_array} for all time steps.
        """
        result = {}
        for t in self.times:
            result[t] = self.ucn.get_data(totim=t)
        return result

    def breakthrough_curve(self, layer, row, col):
        """
        Extract a breakthrough curve (concentration vs time) at a specific cell.

        Parameters
        ----------
        layer, row, col : int
            Cell indices (0-indexed).

        Returns
        -------
        dict
            {"times": list, "concentrations": list, "cell": (layer, row, col)}
        """
        times = []
        concs = []
        for t in self.times:
            data = self.ucn.get_data(totim=t)
            c = float(data[layer, row, col])
            # Filter out HDRY sentinel values
            if abs(c) < 1.0e20:
                times.append(float(t))
                concs.append(c)

        return {
            "times": times,
            "concentrations": concs,
            "cell": (layer, row, col),
            "peak_concentration": max(concs) if concs else 0.0,
            "time_of_peak": times[concs.index(max(concs))] if concs else None,
            "final_concentration": concs[-1] if concs else 0.0,
        }

    def plume_extent(self, threshold, totim=None, layer=0):
        """
        Compute plume extent (area and cell count above concentration threshold).

        Parameters
        ----------
        threshold : float
            Concentration threshold defining the plume boundary.
        totim : float or None
            Time for which to compute plume extent. If None, uses last time.
        layer : int
            Layer to analyze (0-indexed).

        Returns
        -------
        dict
            {
                "n_cells": int,
                "area_m2": float or None (if delr/delc provided),
                "fraction_of_domain": float,
                "max_concentration": float,
                "mean_concentration_in_plume": float,
                "center_of_mass_row": float,
                "center_of_mass_col": float,
                "threshold": float,
                "time": float,
                "layer": int,
            }
        """
        conc = self.get_concentration(totim=totim, layer=layer)
        if totim is None:
            totim = self.times[-1]

        # Filter out HDRY sentinel
        valid = np.abs(conc) < 1.0e20
        conc_clean = np.where(valid, conc, 0.0)

        # Plume cells
        plume_mask = conc_clean >= threshold
        n_cells = int(np.sum(plume_mask))
        n_active = int(np.sum(valid))

        # Statistics
        if n_cells > 0:
            plume_concs = conc_clean[plume_mask]
            max_conc = float(np.max(plume_concs))
            mean_conc = float(np.mean(plume_concs))

            # Center of mass (row, col weighted by concentration)
            rows, cols = np.where(plume_mask)
            weights = conc_clean[plume_mask]
            total_mass = np.sum(weights)
            com_row = float(np.sum(rows * weights) / total_mass) if total_mass > 0 else 0.0
            com_col = float(np.sum(cols * weights) / total_mass) if total_mass > 0 else 0.0
        else:
            max_conc = 0.0
            mean_conc = 0.0
            com_row = 0.0
            com_col = 0.0

        # Area calculation
        area_m2 = None
        if self.delr is not None and self.delc is not None:
            if isinstance(self.delr, (int, float)):
                cell_area = float(self.delr) * float(self.delc)
            else:
                # delr and delc are arrays -- compute per-cell areas
                dr = np.array(self.delr)
                dc = np.array(self.delc)
                if plume_mask.any():
                    rows_p, cols_p = np.where(plume_mask)
                    cell_area = float(np.sum(dr[cols_p] * dc[rows_p]))
                    area_m2 = cell_area
                else:
                    area_m2 = 0.0
            if area_m2 is None:
                area_m2 = n_cells * cell_area

        return {
            "n_cells": n_cells,
            "area_m2": area_m2,
            "fraction_of_domain": n_cells / n_active if n_active > 0 else 0.0,
            "max_concentration": max_conc,
            "mean_concentration_in_plume": mean_conc,
            "center_of_mass_row": com_row,
            "center_of_mass_col": com_col,
            "threshold": threshold,
            "time": float(totim),
            "layer": layer,
        }

    def plume_evolution(self, threshold, layer=0):
        """
        Track plume evolution over all time steps.

        Parameters
        ----------
        threshold : float
            Concentration threshold for plume boundary.
        layer : int
            Layer to analyze.

        Returns
        -------
        list of dict
            Plume extent at each time step.
        """
        results = []
        for t in self.times:
            pe = self.plume_extent(threshold=threshold, totim=t, layer=layer)
            results.append(pe)
        return results

    def concentration_statistics(self, totim=None, layer=None):
        """
        Compute concentration statistics for a given time step.

        Parameters
        ----------
        totim : float or None
            Time. If None, uses last.
        layer : int or None
            Layer. If None, computes for all layers.

        Returns
        -------
        dict
            Statistics including min, max, mean, median, std, mass_in_domain.
        """
        conc = self.get_concentration(totim=totim, layer=layer)
        if totim is None:
            totim = self.times[-1]

        # Filter HDRY
        valid = np.abs(conc) < 1.0e20
        conc_clean = conc[valid]

        if len(conc_clean) == 0:
            return {
                "time": float(totim),
                "n_active_cells": 0,
                "min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0, "std": 0.0,
            }

        # Cell volumes for mass calculation
        mass_in_domain = None
        if self.delr is not None and self.delc is not None:
            # Simplified mass calculation (assumes uniform porosity)
            if isinstance(self.delr, (int, float)):
                cell_vol = float(self.delr) * float(self.delc)  # area only, need thickness
            else:
                cell_vol = None  # too complex without full grid info
            # Mass = sum(C * V * porosity) but we don't know porosity here
            # Just report total_concentration_volume = sum(C * cell_area)

        stats = {
            "time": float(totim),
            "n_active_cells": int(np.sum(valid)),
            "n_nonzero_cells": int(np.sum(conc_clean > 0)),
            "min": float(np.min(conc_clean)),
            "max": float(np.max(conc_clean)),
            "mean": float(np.mean(conc_clean)),
            "median": float(np.median(conc_clean)),
            "std": float(np.std(conc_clean)),
            "percentile_95": float(np.percentile(conc_clean, 95)),
            "percentile_99": float(np.percentile(conc_clean, 99)),
            "total_concentration": float(np.sum(conc_clean)),
        }

        if layer is not None:
            stats["layer"] = layer

        return stats

    def parse_mass_budget(self):
        """
        Parse the mass budget from the GWT listing file.

        The listing file contains mass budget summaries for each time step
        with IN and OUT terms.

        Returns
        -------
        list of dict
            List of budget records, each containing:
            - time_step, stress_period
            - in_terms: dict of {component: mass_rate}
            - out_terms: dict of {component: mass_rate}
            - total_in, total_out
            - percent_discrepancy
        """
        if self.listing_file is None or not os.path.exists(self.listing_file):
            return {"error": "Listing file not available"}

        budgets = []
        with open(self.listing_file, "r") as f:
            content = f.read()

        # Find mass budget summary blocks
        # Pattern: "MASS BUDGET FOR ENTIRE MODEL"
        budget_pattern = re.compile(
            r"MASS BUDGET FOR ENTIRE MODEL.*?"
            r"AT END OF TIME STEP\s+(\d+)\s+IN STRESS PERIOD\s+(\d+)\s*\n"
            r"(.*?)"
            r"PERCENT DISCREPANCY\s*=\s*([\d.E+\-]+)",
            re.DOTALL
        )

        for match in budget_pattern.finditer(content):
            kstp = int(match.group(1))
            kper = int(match.group(2))
            block = match.group(3)
            pct_disc = float(match.group(4))

            in_terms = {}
            out_terms = {}
            total_in = 0.0
            total_out = 0.0

            # Parse IN and OUT sections
            in_section = False
            out_section = False
            for line in block.split("\n"):
                line = line.strip()
                if "IN:" in line:
                    in_section = True
                    out_section = False
                    continue
                elif "OUT:" in line:
                    in_section = False
                    out_section = True
                    continue
                elif "TOTAL IN" in line:
                    parts = line.split("=")
                    if len(parts) == 2:
                        try:
                            total_in = float(parts[1].strip())
                        except ValueError:
                            pass
                    in_section = False
                    continue
                elif "TOTAL OUT" in line:
                    parts = line.split("=")
                    if len(parts) == 2:
                        try:
                            total_out = float(parts[1].strip())
                        except ValueError:
                            pass
                    out_section = False
                    continue

                # Parse individual terms
                if (in_section or out_section) and "=" in line:
                    parts = line.split("=")
                    if len(parts) == 2:
                        name = parts[0].strip()
                        try:
                            value = float(parts[1].strip())
                        except ValueError:
                            continue
                        if in_section:
                            in_terms[name] = value
                        else:
                            out_terms[name] = value

            budgets.append({
                "time_step": kstp,
                "stress_period": kper,
                "in_terms": in_terms,
                "out_terms": out_terms,
                "total_in": total_in,
                "total_out": total_out,
                "percent_discrepancy": pct_disc,
            })

        return budgets

    def export_concentration_csv(self, output_file, totim=None, layer=0):
        """
        Export concentration data to CSV file.

        Parameters
        ----------
        output_file : str
            Path to output CSV file.
        totim : float or None
            Time. If None, uses last.
        layer : int
            Layer to export.
        """
        conc = self.get_concentration(totim=totim, layer=layer)
        if totim is None:
            totim = self.times[-1]

        with open(output_file, "w") as f:
            f.write("row,col,concentration\n")
            for i in range(conc.shape[0]):
                for j in range(conc.shape[1]):
                    c = conc[i, j]
                    if abs(c) < 1.0e20:  # Skip HDRY
                        f.write(f"{i},{j},{c:.8e}\n")

        print(f"Exported layer {layer} concentration at time {totim} to {output_file}")

    def export_breakthrough_csv(self, output_file, cells):
        """
        Export breakthrough curves for multiple cells to CSV.

        Parameters
        ----------
        output_file : str
            Path to output CSV file.
        cells : list of tuples
            List of (layer, row, col) tuples.
        """
        # Get all breakthrough curves
        curves = {}
        for cell in cells:
            key = f"L{cell[0]}_R{cell[1]}_C{cell[2]}"
            btc = self.breakthrough_curve(cell[0], cell[1], cell[2])
            curves[key] = btc

        with open(output_file, "w") as f:
            # Header
            header = "time," + ",".join(curves.keys())
            f.write(header + "\n")

            # Use the first curve's times as reference
            ref_key = list(curves.keys())[0]
            for i, t in enumerate(curves[ref_key]["times"]):
                row = [f"{t:.6f}"]
                for key in curves:
                    if i < len(curves[key]["concentrations"]):
                        row.append(f"{curves[key]['concentrations'][i]:.8e}")
                    else:
                        row.append("")
                f.write(",".join(row) + "\n")

        print(f"Exported breakthrough curves for {len(cells)} cells to {output_file}")

    def summary(self):
        """
        Generate a comprehensive summary of GWT simulation results.

        Returns
        -------
        dict
            Summary dictionary.
        """
        n_times = len(self.times)
        t_min = self.times[0] if n_times > 0 else None
        t_max = self.times[-1] if n_times > 0 else None

        # Final concentration stats
        final_stats = self.concentration_statistics()

        # Mass budget check
        mass_budget = self.parse_mass_budget()
        if isinstance(mass_budget, list) and len(mass_budget) > 0:
            final_budget = mass_budget[-1]
            max_disc = max(abs(b["percent_discrepancy"]) for b in mass_budget)
        else:
            final_budget = None
            max_disc = None

        return {
            "grid": {
                "nlay": self.nlay,
                "nrow": self.nrow,
                "ncol": self.ncol,
            },
            "time_info": {
                "n_saved_steps": n_times,
                "first_time": t_min,
                "last_time": t_max,
            },
            "final_concentration": final_stats,
            "mass_budget": {
                "final_budget": final_budget,
                "max_percent_discrepancy": max_disc,
                "budget_acceptable": max_disc < 1.0 if max_disc is not None else None,
            },
        }


def main():
    parser = argparse.ArgumentParser(
        description="Parse GWT (Groundwater Transport) model output from MODFLOW 6"
    )
    parser.add_argument("ucn_file", type=str,
                        help="Path to binary concentration file (.ucn)")
    parser.add_argument("--budget-file", type=str, default=None,
                        help="Path to cell budget file (.cbc)")
    parser.add_argument("--listing-file", type=str, default=None,
                        help="Path to listing file (.lst)")
    parser.add_argument("--precision", type=str, default="double",
                        choices=["single", "double"],
                        help="Binary file precision (default: double)")
    parser.add_argument("--summary", action="store_true",
                        help="Print summary of results")
    parser.add_argument("--stats", action="store_true",
                        help="Print concentration statistics for final time step")
    parser.add_argument("--plume", type=float, default=None,
                        help="Compute plume extent above this concentration threshold")
    parser.add_argument("--plume-layer", type=int, default=0,
                        help="Layer for plume analysis (default: 0)")
    parser.add_argument("--breakthrough", type=str, default=None,
                        help="Breakthrough curve at cell 'layer,row,col' (0-indexed)")
    parser.add_argument("--export-csv", type=str, default=None,
                        help="Export final concentration to CSV file")
    parser.add_argument("--export-layer", type=int, default=0,
                        help="Layer to export (default: 0)")
    parser.add_argument("--time", type=float, default=None,
                        help="Specific time for analysis (default: last)")
    parser.add_argument("--delr", type=float, default=None,
                        help="Cell size in row direction (m)")
    parser.add_argument("--delc", type=float, default=None,
                        help="Cell size in column direction (m)")
    parser.add_argument("--mass-budget", action="store_true",
                        help="Parse and print mass budget from listing file")
    parser.add_argument("--plume-evolution", type=float, default=None,
                        help="Track plume evolution above threshold over all time steps")
    parser.add_argument("--json", action="store_true",
                        help="Output results in JSON format")

    args = parser.parse_args()

    gp = GWTOutputParser(
        concentration_file=args.ucn_file,
        budget_file=args.budget_file,
        listing_file=args.listing_file,
        precision=args.precision,
        delr=args.delr,
        delc=args.delc,
    )

    if args.summary:
        result = gp.summary()
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print("\n=== GWT Simulation Summary ===")
            print(f"Grid: {result['grid']['nlay']} layers x {result['grid']['nrow']} rows x {result['grid']['ncol']} cols")
            print(f"Saved time steps: {result['time_info']['n_saved_steps']}")
            print(f"Time range: {result['time_info']['first_time']} to {result['time_info']['last_time']}")
            fc = result['final_concentration']
            print(f"\nFinal Concentration Statistics:")
            print(f"  Min: {fc['min']:.6e}")
            print(f"  Max: {fc['max']:.6e}")
            print(f"  Mean: {fc['mean']:.6e}")
            print(f"  Median: {fc['median']:.6e}")
            print(f"  Active cells: {fc['n_active_cells']}")
            print(f"  Non-zero cells: {fc['n_nonzero_cells']}")
            mb = result['mass_budget']
            if mb['max_percent_discrepancy'] is not None:
                print(f"\nMass Budget:")
                print(f"  Max percent discrepancy: {mb['max_percent_discrepancy']:.4f}%")
                print(f"  Budget acceptable (<1%): {mb['budget_acceptable']}")

    if args.stats:
        result = gp.concentration_statistics(totim=args.time)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print("\n=== Concentration Statistics ===")
            for k, v in result.items():
                print(f"  {k}: {v}")

    if args.plume is not None:
        result = gp.plume_extent(threshold=args.plume, totim=args.time, layer=args.plume_layer)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"\n=== Plume Extent (threshold={args.plume}) ===")
            print(f"  Cells above threshold: {result['n_cells']}")
            print(f"  Fraction of domain: {result['fraction_of_domain']:.4f}")
            if result['area_m2'] is not None:
                print(f"  Plume area: {result['area_m2']:.1f} m2 ({result['area_m2']/1e6:.4f} km2)")
            print(f"  Max concentration: {result['max_concentration']:.6e}")
            print(f"  Mean in plume: {result['mean_concentration_in_plume']:.6e}")
            print(f"  Center of mass: row={result['center_of_mass_row']:.1f}, col={result['center_of_mass_col']:.1f}")

    if args.plume_evolution is not None:
        results = gp.plume_evolution(threshold=args.plume_evolution, layer=args.plume_layer)
        if args.json:
            print(json.dumps(results, indent=2, default=str))
        else:
            print(f"\n=== Plume Evolution (threshold={args.plume_evolution}) ===")
            print(f"  {'Time':>12s}  {'Cells':>8s}  {'Fraction':>10s}  {'Max Conc':>12s}")
            for r in results:
                print(f"  {r['time']:12.2f}  {r['n_cells']:8d}  {r['fraction_of_domain']:10.4f}  {r['max_concentration']:12.6e}")

    if args.breakthrough is not None:
        parts = [int(x) for x in args.breakthrough.split(",")]
        if len(parts) != 3:
            print("ERROR: --breakthrough must be 'layer,row,col'")
            sys.exit(1)
        result = gp.breakthrough_curve(parts[0], parts[1], parts[2])
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"\n=== Breakthrough Curve at ({parts[0]},{parts[1]},{parts[2]}) ===")
            print(f"  Peak concentration: {result['peak_concentration']:.6e}")
            print(f"  Time of peak: {result['time_of_peak']}")
            print(f"  Final concentration: {result['final_concentration']:.6e}")
            print(f"  {'Time':>12s}  {'Concentration':>14s}")
            for t, c in zip(result['times'], result['concentrations']):
                print(f"  {t:12.4f}  {c:14.6e}")

    if args.export_csv is not None:
        gp.export_concentration_csv(args.export_csv, totim=args.time, layer=args.export_layer)

    if args.mass_budget:
        budgets = gp.parse_mass_budget()
        if isinstance(budgets, dict) and "error" in budgets:
            print(f"ERROR: {budgets['error']}")
        elif args.json:
            print(json.dumps(budgets, indent=2, default=str))
        else:
            print("\n=== Mass Budget Summary ===")
            for b in budgets:
                print(f"\n  Time Step {b['time_step']}, Stress Period {b['stress_period']}:")
                print(f"    IN:")
                for name, val in b['in_terms'].items():
                    print(f"      {name}: {val:.6e}")
                print(f"    OUT:")
                for name, val in b['out_terms'].items():
                    print(f"      {name}: {val:.6e}")
                print(f"    Total IN:  {b['total_in']:.6e}")
                print(f"    Total OUT: {b['total_out']:.6e}")
                print(f"    Percent Discrepancy: {b['percent_discrepancy']:.4f}%")


if __name__ == "__main__":
    main()
