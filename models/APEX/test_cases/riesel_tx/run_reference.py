#!/usr/bin/env python3
"""Run the official APEX0806 Riesel TX example in a clean dir and check expected.json.

Foundation case for the APEX KI. The inputs are the unmodified ex1_RiselTX files from
the official "APEX v.0806 Editor" download (Texas A&M AgriLife, 2015-09-23). The model
is run through the KI's own tools/s6_run_apex.py (wine APEX0806.exe) and the crop table
is read with tools/s7_parse_output.py.

The download also ships the small side outputs fort.102/108/112/128 that the APEX
team's own run wrote (2015-09-04). They are kept in reference/ and our run must
reproduce them (printed values equal).

Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.
Binary lookup: --apex-bin -> $APEX_BIN -> `which APEX0806.exe` -> server default.
"""
import argparse, json, os, re, shutil, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
_DEF = "/mnt/disk1/Hydrocraft_server/models/APEX/knowledge_infrastructure/reference/APEX0806.exe"
REF_FORT = ("fort.102", "fort.108", "fort.112", "fort.128")
_NUM = re.compile(r"[-+]?\d*\.?\d+(?:[EeDd][-+]?\d+)?")


def nums(text):
    return [float(x.replace("D", "E").replace("d", "e")) for x in _NUM.findall(text)]


def max_abs_diff(a, b):
    """Largest difference between two lists of printed numbers (inf if counts differ)."""
    if len(a) != len(b):
        return float("inf")
    return max((abs(x - y) for x, y in zip(a, b)), default=0.0)


def find_binary(arg):
    for c in (arg, os.environ.get("APEX_BIN"), shutil.which("APEX0806.exe"), _DEF):
        if c and Path(c).is_file():
            return Path(c)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apex-bin", help="path to APEX0806.exe")
    a = ap.parse_args()
    exe = find_binary(a.apex_bin)
    if exe is None:
        print("MISSING DEPENDENCY: APEX0806.exe not found (use --apex-bin or $APEX_BIN). NOT run.",
              file=sys.stderr)
        return 3
    if not shutil.which("wine"):
        print("MISSING DEPENDENCY: wine not on PATH (APEX0806.exe is a Windows PE32 program). NOT run.",
              file=sys.stderr)
        return 3
    try:
        import pandas  # noqa: F401  (needed by tools/s7_parse_output.py)
    except ImportError:
        print("MISSING DEPENDENCY: pandas (needed by the KI parse tool). NOT run.", file=sys.stderr)
        return 3
    sys.path.insert(0, str(TOOLS))
    import s6_run_apex as s6
    import s7_parse_output as s7

    run = Path(tempfile.mkdtemp(prefix="apex_riesel_"))
    fails, got = [], {}
    try:
        for f in sorted((HERE / "inputs").iterdir()):
            shutil.copy(f, run / f.name)
        shutil.copy(exe, run / "APEX0806.exe")
        print(f"  engine: {exe}")
        try:
            info = s6.run(run, timeout=900)
        except Exception as e:  # s6 raises on no output / severe errors
            fails.append(f"KI run tool s6_run_apex failed: {e}")
            info = None

        if info is not None:
            print(f"  ran APEX0806 via tools/s6_run_apex.py (rc={info['returncode']})")
            out = (run / "OUTPUT.OUT").read_text(errors="replace")
            err = run / "EPICERR.DAT"
            err_bad = err.is_file() and "ERROR" in err.read_text(errors="replace").upper()
            finished = (info["returncode"] == 0 and not info["terminal_fault_accepted"]
                        and not err_bad and "TOTAL RUN TIME" in out
                        and "TOTAL WATER BALANCE" in out and "TOTAL SEDIMENT BALANCE" in out)
            if finished:
                print("  OK finished normally: rc=0, OUTPUT.OUT has both end balances and 'TOTAL RUN TIME'")
            else:
                fails.append("run did not finish normally (rc, EPICERR or OUTPUT.OUT end blocks)")

            # 1) official reference side outputs (written by the APEX team's own run)
            for f in REF_FORT:
                ref = nums((HERE / "reference" / f).read_text(errors="replace"))
                new_p = run / f
                new = nums(new_p.read_text(errors="replace")) if new_p.is_file() else []
                got[f"{f.replace('.', '')}_maxdiff_vs_official"] = max_abs_diff(ref, new)
            f108 = [l for l in (run / "fort.108").read_text().splitlines() if l.strip()]
            got["fort108_years"] = len(f108)
            got["fort112_outflow_mm"] = nums((run / "fort.112").read_text())[0]

            # 2) water balance closure printed by APEX (PER, percent)
            m = re.search(r"TOTAL WATER BALANCE\s+PER\s*=\s*(\S+)", out)
            got["water_balance_error_pct"] = float(m.group(1).replace("D", "E")) if m else float("nan")

            # 3) annual crop table via the KI parse tool
            df = s7.parse(run)
            acy = df[df["__source__"] == "OUTPUT.ACY"].copy()
            for c in ("YR", "YLDG", "BIOM"):
                acy[c] = acy[c].astype(float)
            corn = acy[acy["CPNM"] == "CORN"]
            got.update({
                "acy_rows": len(acy),
                "acy_first_year": acy["YR"].min(),
                "acy_last_year": acy["YR"].max(),
                "corn_harvests": len(corn),
                "corn_mean_yield_t_ha": corn["YLDG"].mean(),
                "corn_max_yield_t_ha": corn["YLDG"].max(),
                "corn_mean_biomass_t_ha": corn["BIOM"].mean(),
            })

            # 4) annual outlet water/sediment table OUTPUT.AWS
            aws = [l.split() for l in (run / "OUTPUT.AWS").read_text().splitlines()]
            aws = [r for r in aws if r and re.fullmatch(r"\d{4}", r[0])]
            got["aws_runoff_qts_sum_mm"] = sum(float(r[4]) for r in aws)

            for c in EXP["numeric_checks"]:
                v = got.get(c["name"])
                if v is None or not abs(v - c["expected"]) <= c["tol"]:
                    fails.append(f"{c['name']}: {v} vs {c['expected']} +/- {c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:.6g}")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: APEX0806 Riesel TX example reproduced the official reference and expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
