#!/usr/bin/env python3
"""Run official USGS PHREEQC example 1 (speciation of seawater) and check it.

Foundation case for the PHREEQC KI. Copies inputs/ (unmodified ex1 + phreeqc.dat from
the USGS phreeqc3 git tree) to a fresh temp dir and runs PHREEQC on them. It first tries
the KI's own tools/run_phreeqc.py; if that tool fails, it runs the engine directly
(see README "Known KI gaps"). Then it:
  1. compares the whole output against the official USGS reference/ex1.out, line by line
     (only the 3 header lines that hold file paths, and the trailing "End of Run after
     ... Seconds" timing block, are skipped; numbers may differ by at most one unit in
     the last printed digit),
  2. checks the named values in expected.json (taken from the official ex1.out).
Exit 0 PASS, 2 checks failed, 3 engine missing.

Binary lookup: --phreeqc-bin -> $PHREEQC_BIN -> `which phreeqc` -> server default.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_phreeqc.py"
PARSE_TOOL = HERE.parents[1] / "tools" / "parse_output.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/PHREEQC/source/repo/build/phreeqc"
NUM = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")


def find_bin(arg):
    for c in (arg, os.environ.get("PHREEQC_BIN"), shutil.which("phreeqc"), _DEF):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def unit(tok):
    """One unit in the last printed digit of a numeric token."""
    m = NUM.match(tok)
    mant, exp = m.group(1), m.group(2)
    dec = len(mant.split(".")[1]) if "." in mant else 0
    return 10.0 ** (-dec) * (10.0 ** int(exp[1:]) if exp else 1.0)


def body(text):
    lines = text.splitlines()[3:]  # drop Input/Output/Database file path lines
    while lines and (not lines[-1].strip() or lines[-1].startswith("---")
                     or lines[-1].startswith("End of Run after")):
        lines.pop()
    return lines


def compare_full(got_txt, ref_txt):
    g, r = body(got_txt), body(ref_txt)
    if len(g) != len(r):
        return [f"line count differs: {len(g)} vs official {len(r)}"], 0
    bad, nnum = [], 0
    for i, (a, b) in enumerate(zip(g, r), start=4):
        ta, tb = a.split(), b.split()
        if len(ta) != len(tb):
            bad.append(f"line {i}: '{a.strip()}' vs '{b.strip()}'")
            continue
        for x, y in zip(ta, tb):
            if x == y:
                if NUM.match(x):
                    nnum += 1
                continue
            if NUM.match(x) and NUM.match(y):
                nnum += 1
                if abs(float(x) - float(y)) <= 1.01 * max(unit(x), unit(y)):
                    continue
            bad.append(f"line {i}: '{a.strip()}' vs '{b.strip()}'")
            break
    return bad, nnum


def named_values(txt, spec_rows):
    """Read named values straight from the output text."""
    got = {}
    for k, label in (("pH", "pH"), ("pe", "pe"), ("density", "Density (g/cm³)"),
                     ("ionic_strength", "Ionic strength (mol/kgw)"),
                     ("total_carbon", "Total carbon (mol/kg)"),
                     ("electrical_balance", "Electrical balance (eq)"),
                     ("percent_error", "Percent error, 100*(Cat-|An|)/(Cat+|An|)"),
                     ("iterations", "Iterations"), ("total_H", "Total H"), ("total_O", "Total O")):
        m = re.search(r"^\s*" + re.escape(label) + r"\s*=\s*(\S+)", txt, re.M)
        got[k] = float(m.group(1)) if m else None
    m = re.search(r"Specific Conductance \(.*?\)\s*=\s*(\S+)", txt)
    got["specific_conductance"] = float(m.group(1)) if m else None
    m = re.search(r"^\s*U\s+(\S+)\s+\S+\s*$", txt, re.M)  # Solution composition row
    got["U_total_molality"] = float(m.group(1)) if m else None
    si = re.search(r"-+Saturation indices-+\n\n.*?\n\n(.*?)\n\n", txt, re.S)
    rows = [l.split() for l in si.group(1).splitlines()] if si else []
    got["n_si_phases"] = len(rows)
    for r in rows:
        got["SI_" + r[0]] = float(r[1])
    # species molalities: from the KI parse tool when it works
    got.update(spec_rows)
    return got


def species_from_parse_tool(out, run):
    if not PARSE_TOOL.is_file():
        return {}, "parse tool not found"
    pj = run / "parsed.json"
    cp = subprocess.run([sys.executable, str(PARSE_TOOL), "--input", str(out), "--output",
                         str(pj), "--format", "json", "--extract", "speciation"],
                        capture_output=True, text=True, timeout=120, cwd=run)
    if cp.returncode != 0 or not pj.is_file():
        return {}, f"parse tool failed rc={cp.returncode}"
    sp = json.loads(pj.read_text())["speciation"][0]["species"]
    d = {}
    for s in sp:  # a species can be listed under several elements; first value is kept
        d.setdefault("molality_" + s["species"], s["molality"])
    return d, f"parse tool ok ({len(sp)} species rows)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phreeqc-bin")
    a = ap.parse_args()
    exe = find_bin(a.phreeqc_bin)
    if not exe:
        print("MISSING DEPENDENCY: phreeqc binary not found (--phreeqc-bin, $PHREEQC_BIN, "
              "PATH, or " + _DEF + "). NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="phreeqc_ex1_"))
    fails = []
    try:
        for f in ("ex1", "phreeqc.dat"):
            shutil.copy(HERE / "inputs" / f, run / f)
        out = run / "ex1.out"
        how = None
        if RUN_TOOL.is_file():
            cp = subprocess.run([sys.executable, str(RUN_TOOL), "--binary", exe,
                                 "--input", str(run / "ex1"), "--output", str(out),
                                 "--database", str(run / "phreeqc.dat"), "--workdir", str(run),
                                 "--timeout", "120", "--json-output", str(run / "tool.json")],
                                capture_output=True, text=True, timeout=300, cwd=run)
            if cp.returncode == 0 and out.is_file():
                res = json.loads((run / "tool.json").read_text())
                if res.get("status") == "success" and res.get("exit_code") == 0:
                    how = "KI tool run_phreeqc.py"
            if how is None:
                last = (cp.stderr.strip().splitlines() or ["?"])[-1]
                print(f"  note: KI tool run_phreeqc.py failed ({last}); running engine directly")
                out.unlink(missing_ok=True)
        if how is None:
            cp = subprocess.run([exe, "ex1", "ex1.out", "phreeqc.dat"], capture_output=True,
                                text=True, timeout=120, cwd=run)
            how = "engine directly"
            if cp.returncode != 0:
                fails.append(f"phreeqc exited rc={cp.returncode}: {cp.stderr[-400:]}")
        print(f"  ran PHREEQC via {how}: {exe}")

        if not fails:
            txt = out.read_text(encoding="utf-8", errors="replace")
            ref = (HERE / "reference" / "ex1.out").read_text(encoding="utf-8", errors="replace")
            if not re.search(r"^End of Run after .* Seconds\.", txt, re.M):
                fails.append("no 'End of Run after ... Seconds.' line (run did not finish)")
            else:
                print("  OK finished normally (rc 0 + 'End of Run' line)")
            if "ERROR" in txt:
                fails.append("output contains ERROR")
            bad, nnum = compare_full(txt, ref)
            if bad:
                fails.append(f"{len(bad)} line(s) differ from official ex1.out, first: {bad[0]}")
            else:
                print(f"  OK whole output matches official USGS ex1.out "
                      f"({len(body(ref))} lines, {nnum} numbers within 1 last-digit unit)")
            spec, note = species_from_parse_tool(out, run)
            print(f"  species values: {note}")
            got = named_values(txt, spec)
            for c in EXP["numeric_checks"]:
                v = got.get(c["name"])
                if v is None:
                    fails.append(f"{c['name']}: not found in output")
                elif abs(v - c["expected"]) > c["tol"]:
                    fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}±{c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:.6g}")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: PHREEQC example 1 (seawater speciation) matches the official USGS output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
