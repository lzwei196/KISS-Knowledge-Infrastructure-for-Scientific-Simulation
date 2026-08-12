#!/usr/bin/env python3
"""Stage EPIC control + list-COM files in a workspace and write an EPICRUN.DAT
line pointing at the user's new SIT/SOL/OPC/weather files."""
import argparse
import os
import shutil
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import copy_template, read_text_crlf, write_text_crlf, TEMPLATES_DIR


LIST_FILES = ["SITECOM.DAT", "SOILCOM.DAT", "OPSCCOM.DAT",
              "WPM1USEL.DAT", "WINDUSEL.DAT", "WDLSTCOM.DAT"]

FLAT_DATS = [
    "EPICFILE.DAT", "CROPCOM.DAT", "FERT2012.DAT", "TILLCOM.DAT",
    "PESTCOM.DAT", "PARM1102.DAT", "MLRN1102.DAT", "PRNT1102.DAT",
    "CMOD1102.DAT", "TR55COM.DAT", "WIDXCOM.DAT", "WPM5US.DAT",
    "AYEAR.DAT", "EPICERR.DAT", "RTSOIL.DAT", "SOIL35K.DAT",
    "WORKSPACE.DAT",
]


def _stage_flats(workspace):
    for fn in FLAT_DATS:
        src = os.path.join(TEMPLATES_DIR, fn)
        if os.path.isfile(src):
            dst = os.path.join(workspace, fn)
            if not os.path.isfile(dst):
                shutil.copy2(src, dst)


def _append_list(workspace, listname, filename):
    path = os.path.join(workspace, listname)
    if not os.path.isfile(path):
        write_text_crlf(path, '')
    text = read_text_crlf(path)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines, start=1):
        if filename.strip() in ln:
            return i
    idx = len(lines) + 1
    lines.append(f"{idx:>6d} {filename}")
    write_text_crlf(path, "\r\n".join(lines))
    return idx


def build(workspace, run_name, sit, sol, opc, stn, nbyr, iyr0):
    os.makedirs(workspace, exist_ok=True)
    _stage_flats(workspace)

    copy_template("EPICFILE.DAT", workspace)
    cont = os.path.join(workspace, "EPICCONT.DAT")
    if not os.path.isfile(cont):
        copy_template("EPICCONT.DAT", workspace)

    cont_text = read_text_crlf(cont)
    cont_lines = cont_text.splitlines()
    row0 = cont_lines[0]
    head = f"{nbyr:>5d}{iyr0:>5d}"
    cont_lines[0] = head + (row0[10:] if len(row0) > 10
                            else "   1   1   3 2345   0   0   1   4   0   0   0   0   0   0   0   0   0   0")
    write_text_crlf(cont, "\r\n".join(cont_lines))

    isit = _append_list(workspace, "SITECOM.DAT", sit)
    isol = _append_list(workspace, "SOILCOM.DAT", sol)
    iopc = _append_list(workspace, "OPSCCOM.DAT", opc)
    iwp1 = _append_list(workspace, "WPM1USEL.DAT", f"{stn}.WP1")
    iwnd = _append_list(workspace, "WINDUSEL.DAT", f"{stn}.WND")
    idly = _append_list(workspace, "WDLSTCOM.DAT", f"{stn}.DLY")

    run_line = (
        f"{run_name:<10}{isit:>4d}{iwp1:>4d}{0:>4d}{iwnd:>4d}"
        f"{isol:>4d}{iopc:>4d}{idly:>4d}/"
    )
    run_path = os.path.join(workspace, "EPICRUN.DAT")
    header = "XXXXXXXX   SIT WP1 WP5 WND SOL OPS DLY"
    write_text_crlf(run_path, run_line + "\r\n" + header)
    print(f"  wrote {run_path}")
    print(f"  run line: {run_line}")
    return run_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--sit", required=True)
    ap.add_argument("--sol", required=True)
    ap.add_argument("--opc", required=True)
    ap.add_argument("--stn", required=True)
    ap.add_argument("--nbyr", type=int, default=10)
    ap.add_argument("--iyr0", type=int, default=2000)
    args = ap.parse_args()
    build(args.workspace, args.run_name, args.sit, args.sol, args.opc,
          args.stn, args.nbyr, args.iyr0)


if __name__ == "__main__":
    main()
