#!/usr/bin/env python3
"""
parse_epanet_output.py — Parse EPANET binary .out file and report .rpt to CSV/DataFrames.

Reads the EPANET binary output file format (4-byte aligned records) and
extracts node results (demand, head, pressure, quality) and link results
(flow, velocity, headloss, quality, status, setting, reaction rate,
friction factor) for all time periods.

Can also parse text report files as a fallback.

Usage:
    python parse_epanet_output.py output.out --csv results/
    python parse_epanet_output.py output.out --summary
    python parse_epanet_output.py --rpt report.rpt --csv results/

Pattern: validate → process → validate
"""

import argparse
import csv
import os
import re
import struct
import sys
from pathlib import Path

MAGIC_NUMBER = 516114521


def validate_binary_file(filepath):
    """Validate EPANET binary output file."""
    errors = []

    if not os.path.isfile(filepath):
        errors.append(f"File not found: {filepath}")
        return errors

    fsize = os.path.getsize(filepath)
    if fsize < 884:  # Minimum prolog + epilog
        errors.append(f"File too small ({fsize} bytes): {filepath}")
        return errors

    with open(filepath, "rb") as f:
        # Check magic number at start
        magic = struct.unpack('i', f.read(4))[0]
        if magic != MAGIC_NUMBER:
            errors.append(f"Invalid magic number: {magic} (expected {MAGIC_NUMBER})")

        # Check magic number at end
        f.seek(-4, 2)
        magic_end = struct.unpack('i', f.read(4))[0]
        if magic_end != MAGIC_NUMBER:
            errors.append(f"Invalid trailing magic: {magic_end}")

    return errors


# EPANET 2.2 writes IDs and chemical name/units as MAXID+1 = 32 bytes; EPANET 2.0
# wrote 16 bytes. The width is found from the file size (see detect_id_len).
ID_LEN_CANDIDATES = (32, 16)


def prolog_size_bytes(n_nodes, n_links, n_tanks, id_len):
    """Size of the prolog for a given ID width (EPANET output.c savenetdata)."""
    return (15 * 4 + 3 * 80 + 2 * 260 + 2 * id_len
            + id_len * (n_nodes + n_links)
            + 3 * 4 * n_links + 2 * 4 * n_tanks
            + 4 * n_nodes + 2 * 4 * n_links)


def detect_id_len(filepath):
    """Return (id_len, n_periods) whose layout matches the file size exactly, else (None, info)."""
    file_size = os.path.getsize(filepath)
    with open(filepath, "rb") as f:
        ints = struct.unpack('15i', f.read(60))
        f.seek(-12, 2)
        n_periods = struct.unpack('i', f.read(4))[0]
    n_nodes, n_tanks, n_links, n_pumps = ints[2], ints[3], ints[4], ints[5]
    energy = 28 * n_pumps + 4
    period = 16 * n_nodes + 32 * n_links
    tried = []
    for id_len in ID_LEN_CANDIDATES:
        pro = prolog_size_bytes(n_nodes, n_links, n_tanks, id_len)
        expect = pro + energy + n_periods * period + 28
        tried.append(f"id_len={id_len}: expected {expect} bytes")
        if n_periods >= 0 and expect == file_size:
            return id_len, n_periods
    return None, (f"file is {file_size} bytes, epilog says {n_periods} periods; "
                  + "; ".join(tried))


def read_prolog(f, id_len=32):
    """Read the prolog section of the binary output file."""
    f.seek(0)
    prolog = {}

    prolog['magic'] = struct.unpack('i', f.read(4))[0]
    prolog['version'] = struct.unpack('i', f.read(4))[0]
    prolog['n_nodes'] = struct.unpack('i', f.read(4))[0]
    prolog['n_tanks_reservoirs'] = struct.unpack('i', f.read(4))[0]
    prolog['n_links'] = struct.unpack('i', f.read(4))[0]
    prolog['n_pumps'] = struct.unpack('i', f.read(4))[0]
    prolog['n_valves'] = struct.unpack('i', f.read(4))[0]
    prolog['quality_type'] = struct.unpack('i', f.read(4))[0]
    prolog['trace_node'] = struct.unpack('i', f.read(4))[0]
    prolog['flow_units'] = struct.unpack('i', f.read(4))[0]
    prolog['pressure_units'] = struct.unpack('i', f.read(4))[0]
    prolog['statistics'] = struct.unpack('i', f.read(4))[0]
    prolog['report_start'] = struct.unpack('i', f.read(4))[0]
    prolog['report_step'] = struct.unpack('i', f.read(4))[0]
    prolog['duration'] = struct.unpack('i', f.read(4))[0]

    # Title lines (3 x 80 chars)
    prolog['title1'] = f.read(80).decode('ascii', errors='replace').strip('\x00').strip()
    prolog['title2'] = f.read(80).decode('ascii', errors='replace').strip('\x00').strip()
    prolog['title3'] = f.read(80).decode('ascii', errors='replace').strip('\x00').strip()

    # File names (260 chars each)
    prolog['input_file'] = f.read(260).decode('ascii', errors='replace').strip('\x00').strip()
    prolog['report_file'] = f.read(260).decode('ascii', errors='replace').strip('\x00').strip()

    # Chemical name and units (id_len chars each)
    prolog['chem_name'] = f.read(id_len).decode('ascii', errors='replace').split('\x00')[0].strip()
    prolog['chem_units'] = f.read(id_len).decode('ascii', errors='replace').split('\x00')[0].strip()

    n_nodes = prolog['n_nodes']
    n_links = prolog['n_links']
    n_tanks = prolog['n_tanks_reservoirs']

    # Node IDs (id_len chars each)
    node_ids = []
    for _ in range(n_nodes):
        nid = f.read(id_len).decode('ascii', errors='replace').split('\x00')[0].strip()
        node_ids.append(nid)
    prolog['node_ids'] = node_ids

    # Link IDs (id_len chars each)
    link_ids = []
    for _ in range(n_links):
        lid = f.read(id_len).decode('ascii', errors='replace').split('\x00')[0].strip()
        link_ids.append(lid)
    prolog['link_ids'] = link_ids

    # Link start nodes
    prolog['link_start_nodes'] = list(struct.unpack(f'{n_links}i', f.read(4 * n_links)))

    # Link end nodes
    prolog['link_end_nodes'] = list(struct.unpack(f'{n_links}i', f.read(4 * n_links)))

    # Link type codes
    prolog['link_types'] = list(struct.unpack(f'{n_links}i', f.read(4 * n_links)))

    # Tank node indices
    prolog['tank_indices'] = list(struct.unpack(f'{n_tanks}i', f.read(4 * n_tanks)))

    # Tank cross-sectional areas
    prolog['tank_areas'] = list(struct.unpack(f'{n_tanks}f', f.read(4 * n_tanks)))

    # Node elevations
    prolog['node_elevations'] = list(struct.unpack(f'{n_nodes}f', f.read(4 * n_nodes)))

    # Link lengths
    prolog['link_lengths'] = list(struct.unpack(f'{n_links}f', f.read(4 * n_links)))

    # Link diameters
    prolog['link_diameters'] = list(struct.unpack(f'{n_links}f', f.read(4 * n_links)))

    return prolog


def read_energy(f, n_pumps):
    """Read energy use section."""
    energy = []
    for _ in range(n_pumps):
        pump_data = {
            'pump_index': struct.unpack('i', f.read(4))[0],  # INT4 link index
            'utilization': struct.unpack('f', f.read(4))[0],
            'avg_efficiency': struct.unpack('f', f.read(4))[0],
            'avg_kwh_per_unit': struct.unpack('f', f.read(4))[0],
            'avg_kw': struct.unpack('f', f.read(4))[0],
            'peak_kw': struct.unpack('f', f.read(4))[0],
            'avg_cost_per_day': struct.unpack('f', f.read(4))[0],
        }
        energy.append(pump_data)

    peak_energy = struct.unpack('f', f.read(4))[0]
    return energy, peak_energy


def read_period(f, n_nodes, n_links):
    """Read one reporting period of extended period data."""
    period = {}

    # Node data (4 arrays of n_nodes floats)
    period['demand'] = list(struct.unpack(f'{n_nodes}f', f.read(4 * n_nodes)))
    period['head'] = list(struct.unpack(f'{n_nodes}f', f.read(4 * n_nodes)))
    period['pressure'] = list(struct.unpack(f'{n_nodes}f', f.read(4 * n_nodes)))
    period['quality'] = list(struct.unpack(f'{n_nodes}f', f.read(4 * n_nodes)))

    # Link data (8 arrays of n_links floats)
    period['flow'] = list(struct.unpack(f'{n_links}f', f.read(4 * n_links)))
    period['velocity'] = list(struct.unpack(f'{n_links}f', f.read(4 * n_links)))
    period['headloss'] = list(struct.unpack(f'{n_links}f', f.read(4 * n_links)))
    period['link_quality'] = list(struct.unpack(f'{n_links}f', f.read(4 * n_links)))
    period['status'] = list(struct.unpack(f'{n_links}f', f.read(4 * n_links)))
    period['setting'] = list(struct.unpack(f'{n_links}f', f.read(4 * n_links)))
    period['reaction_rate'] = list(struct.unpack(f'{n_links}f', f.read(4 * n_links)))
    period['friction_factor'] = list(struct.unpack(f'{n_links}f', f.read(4 * n_links)))

    return period


def read_epilog(f):
    """Read epilog section."""
    epilog = {}
    epilog['avg_bulk_reaction'] = struct.unpack('f', f.read(4))[0]
    epilog['avg_wall_reaction'] = struct.unpack('f', f.read(4))[0]
    epilog['avg_tank_reaction'] = struct.unpack('f', f.read(4))[0]
    epilog['avg_source_inflow'] = struct.unpack('f', f.read(4))[0]
    epilog['n_periods'] = struct.unpack('i', f.read(4))[0]
    epilog['warning_flag'] = struct.unpack('i', f.read(4))[0]
    epilog['magic'] = struct.unpack('i', f.read(4))[0]
    return epilog


def parse_binary(filepath):
    """Parse complete EPANET binary output file.

    Raises ValueError when the file layout does not match EPANET 2.0/2.2.
    """
    id_len, n_periods = detect_id_len(filepath)
    if id_len is None:
        raise ValueError("binary layout not recognised (" + n_periods + ")")
    with open(filepath, "rb") as f:
        prolog = read_prolog(f, id_len)
        prolog['id_len'] = id_len
        energy, peak_energy = read_energy(f, prolog['n_pumps'])

        periods = []
        for _ in range(n_periods):
            periods.append(read_period(f, prolog['n_nodes'], prolog['n_links']))

        epilog = read_epilog(f)

    if epilog['magic'] != MAGIC_NUMBER or epilog['n_periods'] != n_periods:
        raise ValueError(f"epilog check failed (magic {epilog['magic']}, "
                         f"periods {epilog['n_periods']} vs {n_periods})")
    return prolog, energy, peak_energy, periods, epilog


def get_flow_unit_label(code):
    """Convert flow unit code to string."""
    labels = {0: "CFS", 1: "GPM", 2: "MGD", 3: "IMGD", 4: "AFD",
              5: "LPS", 6: "LPM", 7: "MLD", 8: "CMH", 9: "CMD"}
    return labels.get(code, f"Unknown({code})")


def get_quality_type_label(code):
    """Convert quality type code to string."""
    labels = {0: "None", 1: "Chemical", 2: "Age", 3: "Trace"}
    return labels.get(code, f"Unknown({code})")


def print_summary(prolog, energy, peak_energy, periods, epilog):
    """Print a summary of parsed results."""
    print("\n" + "=" * 60)
    print("EPANET Output Summary")
    print("=" * 60)
    print(f"  Title:              {prolog['title1']}")
    print(f"  Version:            {prolog['version']}")
    print(f"  Nodes:              {prolog['n_nodes']}")
    print(f"  Tanks/Reservoirs:   {prolog['n_tanks_reservoirs']}")
    print(f"  Links:              {prolog['n_links']}")
    print(f"  Pumps:              {prolog['n_pumps']}")
    print(f"  Valves:             {prolog['n_valves']}")
    print(f"  Flow Units:         {get_flow_unit_label(prolog['flow_units'])}")
    print(f"  Quality Type:       {get_quality_type_label(prolog['quality_type'])}")
    print(f"  Duration:           {prolog['duration']}s ({prolog['duration']/3600:.1f}h)")
    print(f"  Report Step:        {prolog['report_step']}s ({prolog['report_step']/60:.0f}min)")
    print(f"  Reporting Periods:  {epilog['n_periods']}")
    print(f"  Warning Flag:       {epilog['warning_flag']}")
    print(f"  Periods Parsed:     {len(periods)}")

    if energy:
        print(f"\n  Energy Usage:")
        for e in energy:
            print(f"    Pump {int(e['pump_index'])}: "
                  f"util={e['utilization']:.1f}%, "
                  f"eff={e['avg_efficiency']:.1f}%, "
                  f"kW={e['avg_kw']:.1f}")

    if periods:
        # Print first period summary
        p = periods[0]
        print(f"\n  First Period Node Results (t={prolog['report_start']}s):")
        for i, nid in enumerate(prolog['node_ids'][:5]):
            print(f"    {nid}: demand={p['demand'][i]:.2f}, "
                  f"head={p['head'][i]:.2f}, pressure={p['pressure'][i]:.2f}")
        if len(prolog['node_ids']) > 5:
            print(f"    ... ({len(prolog['node_ids']) - 5} more nodes)")


def export_node_csv(csv_path, prolog, periods, report_step):
    # time_s counts from the report start time (prolog report_start).
    """Export node results to CSV."""
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)

    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'time_s', 'time_h', 'node_id', 'demand', 'head', 'pressure', 'quality'
        ])
        for t, period in enumerate(periods):
            time_s = prolog['report_start'] + t * report_step
            time_h = time_s / 3600.0
            for i, nid in enumerate(prolog['node_ids']):
                writer.writerow([
                    time_s, f"{time_h:.2f}", nid,
                    f"{period['demand'][i]:.4f}",
                    f"{period['head'][i]:.4f}",
                    f"{period['pressure'][i]:.4f}",
                    f"{period['quality'][i]:.4f}",
                ])

    print(f"  [OK] Node CSV: {csv_path} ({len(periods)} periods x {prolog['n_nodes']} nodes)")


def export_link_csv(csv_path, prolog, periods, report_step):
    """Export link results to CSV."""
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)

    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'time_s', 'time_h', 'link_id', 'flow', 'velocity', 'headloss',
            'quality', 'status', 'setting', 'reaction_rate', 'friction_factor'
        ])
        for t, period in enumerate(periods):
            time_s = prolog['report_start'] + t * report_step
            time_h = time_s / 3600.0
            for i, lid in enumerate(prolog['link_ids']):
                writer.writerow([
                    time_s, f"{time_h:.2f}", lid,
                    f"{period['flow'][i]:.4f}",
                    f"{period['velocity'][i]:.4f}",
                    f"{period['headloss'][i]:.4f}",
                    f"{period['link_quality'][i]:.4f}",
                    f"{period['status'][i]:.0f}",
                    f"{period['setting'][i]:.4f}",
                    f"{period['reaction_rate'][i]:.6f}",
                    f"{period['friction_factor'][i]:.6f}",
                ])

    print(f"  [OK] Link CSV: {csv_path} ({len(periods)} periods x {prolog['n_links']} links)")


# Section titles of the EPANET text report (text.h FMT40/49/71/76/77/79/80, "Analysis begun/ended")
REPORT_SECTION_END = re.compile(
    r'(Reporting Criteria:|Hydraulic Status:|Energy Usage:|(\S+\s+)?(Node|Link) Results:|Analysis (begun|ended))')


def _is_number(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def parse_report_file(rpt_path, csv_dir):
    """Fallback: parse text report file to CSV."""
    if not os.path.isfile(rpt_path):
        print(f"[ERROR] Report file not found: {rpt_path}")
        return False

    os.makedirs(csv_dir, exist_ok=True)

    nodes = []
    links = []
    current_section = None
    current_time = None
    after_page_break = False

    with open(rpt_path, "r") as f:
        for line in f:
            stripped = line.strip()

            # Detect time header
            time_match = re.match(r'Node Results at (.+):', stripped)
            if time_match:
                current_section = "nodes"
                current_time = time_match.group(1)
                continue

            time_match = re.match(r'Link Results at (.+):', stripped)
            if time_match:
                current_section = "links"
                current_time = time_match.group(1)
                continue

            # Page break: EPANET writes "\f" then "  Page <n>    <title>" (FMT82)
            if '\f' in line:
                after_page_break = True
                continue
            if after_page_break and stripped:
                after_page_break = False
                if re.match(r'Page\s+\d+(\s|$)', stripped):
                    continue

            # Other report section titles (report.c / text.h) end a results table
            if REPORT_SECTION_END.match(stripped):
                current_section = None
                continue

            # Skip separators and blank lines
            if stripped.startswith('-') or not stripped:
                continue

            # Parse data lines; column-header and page-header lines are not data:
            # a data row has numbers in the value columns.
            parts = stripped.split()
            if len(parts) >= 4 and current_time and all(_is_number(x) for x in parts[1:4]):
                if current_section == "nodes":
                    nodes.append({
                        'time': current_time,
                        'node_id': parts[0],
                        'demand': parts[1],
                        'head': parts[2],
                        'pressure': parts[3],
                        'quality': parts[4] if len(parts) > 4 and _is_number(parts[4]) else '0',
                    })
                elif current_section == "links":
                    links.append({
                        'time': current_time,
                        'link_id': parts[0],
                        'flow': parts[1],
                        'velocity': parts[2],
                        'headloss': parts[3],
                    })

    # Write CSVs
    if nodes:
        node_csv = os.path.join(csv_dir, "nodes.csv")
        with open(node_csv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=nodes[0].keys())
            writer.writeheader()
            writer.writerows(nodes)
        print(f"  [OK] Node CSV from report: {node_csv} ({len(nodes)} records)")

    if links:
        link_csv = os.path.join(csv_dir, "links.csv")
        with open(link_csv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=links[0].keys())
            writer.writeheader()
            writer.writerows(links)
        print(f"  [OK] Link CSV from report: {link_csv} ({len(links)} records)")

    return bool(nodes or links)


def validate_exported_csvs(csv_dir):
    """Validate exported CSV files."""
    csv_files = list(Path(csv_dir).glob("*.csv"))
    if not csv_files:
        print(f"  [WARN] No CSV files found in {csv_dir}")
        return False

    for csv_file in csv_files:
        size = csv_file.stat().st_size
        with open(csv_file, 'r') as f:
            n_lines = sum(1 for _ in f)
        print(f"  [OK] {csv_file.name}: {n_lines} lines, {size} bytes")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Parse EPANET binary output or text report to CSV"
    )
    parser.add_argument("binary_file", nargs="?", help="EPANET binary .out file")
    parser.add_argument("--rpt", help="Text report .rpt file (fallback parser)")
    parser.add_argument("--csv", help="Output CSV directory")
    parser.add_argument("--summary", action="store_true", help="Print summary only")

    args = parser.parse_args()

    if not args.binary_file and not args.rpt:
        parser.error("Must provide either a binary .out file or --rpt report file")

    # ── Binary output parsing ─────────────────────────────────────────────────
    if args.binary_file:
        print(f"\n[PARSE] Binary file: {args.binary_file}")

        # Step 1: Validate
        errors = validate_binary_file(args.binary_file)
        if errors:
            for e in errors:
                print(f"  [ERR] {e}")
            sys.exit(1)

        # Step 2: Parse
        try:
            prolog, energy, peak_energy, periods, epilog = parse_binary(args.binary_file)
        except (ValueError, struct.error) as exc:
            print(f"  [ERR] Could not read {args.binary_file}: {exc}")
            sys.exit(1)

        # Step 3: Output
        if args.summary or not args.csv:
            print_summary(prolog, energy, peak_energy, periods, epilog)

        if args.csv:
            print(f"\n[EXPORT] CSV directory: {args.csv}")
            export_node_csv(
                os.path.join(args.csv, "nodes.csv"),
                prolog, periods, prolog['report_step']
            )
            export_link_csv(
                os.path.join(args.csv, "links.csv"),
                prolog, periods, prolog['report_step']
            )

            # Step 4: Validate exports
            validate_exported_csvs(args.csv)

    # ── Report file parsing (fallback) ────────────────────────────────────────
    elif args.rpt:
        print(f"\n[PARSE] Report file: {args.rpt}")
        csv_dir = args.csv or "results"
        success = parse_report_file(args.rpt, csv_dir)
        if success:
            validate_exported_csvs(csv_dir)
        else:
            print("[ERROR] Failed to parse report file")
            sys.exit(1)

    print("\n[DONE]")


if __name__ == "__main__":
    main()
