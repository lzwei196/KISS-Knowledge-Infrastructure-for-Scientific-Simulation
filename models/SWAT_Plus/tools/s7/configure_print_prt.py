#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      configure_print_prt
Stage:        s7_simulation_config
Description:  Configure print.prt for SWAT+ output selection.

SWAT+ reads print.prt SEQUENTIALLY (list-directed Fortran reads). The file has a
fixed structure that must be preserved exactly:

    line 1   title
    line 2   nyskip day_start yrc_start day_end yrc_end interval   (header)
    line 3   <values>
    line 4   aa_int_cnt                                            (header)
    line 5   <value>
    line 6   csvout dbout cdfout                                   (header)
    line 7   <values>
    line 8   soilout mgtout hydcon fdcout                          (header)
    line 9   <values>
    line 10  objects daily monthly yearly avann                    (header)
    line 11+ 37 object rows, IN CANONICAL ORDER

Dropping the csvout/soilout header blocks, reordering the object rows, or omitting
rows shifts every subsequent read and silently disables ALL output (see dt_041).

This tool therefore EDITS AN EXISTING print.prt IN PLACE — rewriting only the nyskip
field and the four flag fields of the requested object rows. Every other line is
copied through unchanged. The canonical 37-row rev59 template is written ONLY when
no print.prt exists at all.

An existing print.prt that cannot be edited in place is a HARD ERROR (exit 2); it is
never silently replaced by the template, which would reset the flags of rows the
caller did not ask about and overwrite the deck's own csvout/soilout values.

An output category that is not a known SWAT+ object row is a HARD ERROR (exit 1),
never a silent drop.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, re, logging, json
from pathlib import Path

OUTPUT_VARIABLES = {}
NYSKIP = 2
OUTPUT_DIR = ""

if len(sys.argv) >= 3:
    OUTPUT_VARIABLES = json.loads(sys.argv[1])
    OUTPUT_DIR = sys.argv[2]
if len(sys.argv) >= 4:
    NYSKIP = int(sys.argv[3])

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Canonical object-row order, verified against the shipped rev59 developer example
# KISSPATH_KI_ROOT/SWAT_Plus/run_lrew/swatplus_rev59_demo/print.prt
# (lines 11-47). Order is load-bearing: SWAT+ identifies rows POSITIONALLY.
CANONICAL_OBJECTS = [
    "basin_wb", "basin_nb", "basin_ls", "basin_pw", "basin_aqu",
    "basin_res", "basin_cha", "basin_sd_cha", "basin_psc",
    "region_wb", "region_nb", "region_ls", "region_pw", "region_aqu",
    "region_res", "region_cha", "region_sd_cha", "region_psc",
    "lsunit_wb", "lsunit_nb", "lsunit_ls", "lsunit_pw",
    "hru_wb", "hru_nb", "hru_ls", "hru_pw",
    "hru-lte_wb", "hru-lte_nb", "hru-lte_ls", "hru-lte_pw",
    "channel", "channel_sd",
    "aquifer", "reservoir", "recall", "hyd", "ru",
]

HDR_TIME = "nyskip      day_start  yrc_start  day_end   yrc_end   interval"
HDR_OBJ  = "objects                  daily       monthly        yearly         avann"


def _flags(cfg):
    return ["y" if cfg.get(k, False) else "n"
            for k in ("daily", "monthly", "yearly", "avann")]


def _row(name, cfg):
    d, m, y, a = _flags(cfg)
    return f"{name:<29}{d:<14}{m:<14}{y:<14}{a}"


def validate_inputs():
    if not OUTPUT_DIR:
        logger.error("OUTPUT_DIR is not set"); sys.exit(1)
    unknown = [c for c in OUTPUT_VARIABLES if c not in CANONICAL_OBJECTS]
    if unknown:
        logger.error(f"Unknown print.prt object row(s): {unknown}. "
                     f"Valid rows: {CANONICAL_OBJECTS}")
        sys.exit(1)
    logger.info("Input validation passed.")


def _canonical_template():
    out = ["print.prt: written by SWAT+ knowledge infrastructure",
           HDR_TIME,
           f"{NYSKIP:<12}{0:<10}{0:<10}{0:<10}{0:<10}{1}",
           "aa_int_cnt", "0",
           "csvout        dbout         cdfout",
           "n             n             n",
           "soilout       mgtout        hydcon        fdcout",
           "n             n             n             n",
           HDR_OBJ]
    for name in CANONICAL_OBJECTS:
        out.append(_row(name, OUTPUT_VARIABLES.get(name, {})))
    return out


def _edit_in_place(lines):
    """Preserve structure; change only nyskip and the requested object rows."""
    obj_i = next((i for i, l in enumerate(lines)
                  if l.split() and l.split()[0] == "objects"), None)
    if obj_i is None:
        raise ValueError("existing print.prt has no 'objects' header line")

    ny_i = next((i for i, l in enumerate(lines)
                 if l.split() and l.split()[0] == "nyskip"), None)
    if ny_i is None or ny_i + 1 >= len(lines):
        raise ValueError("existing print.prt has no nyskip header/value line")
    vals = lines[ny_i + 1].split()
    if len(vals) < 6:
        raise ValueError(f"nyskip value line malformed: {lines[ny_i+1]!r}")
    # Replace ONLY the nyskip token; day_start..interval are copied verbatim,
    # including their original spacing. Pad to the old token's width so the
    # existing column alignment survives.
    m = re.match(r"^(\s*)(\S+)(.*)$", lines[ny_i + 1], re.S)
    lines[ny_i + 1] = m.group(1) + str(NYSKIP).ljust(len(m.group(2))) + m.group(3)

    present = {}
    for i in range(obj_i + 1, len(lines)):
        tok = lines[i].split()
        if tok:
            present[tok[0]] = i

    missing = [c for c in OUTPUT_VARIABLES if c not in present]
    if missing:
        raise ValueError(f"requested row(s) absent from existing print.prt: {missing}")

    for cat, cfg in OUTPUT_VARIABLES.items():
        lines[present[cat]] = _row(cat, cfg)
    return lines


def process():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    print_prt_path = output_dir / "print.prt"

    if print_prt_path.exists():
        lines = print_prt_path.read_text().replace("\r\n", "\n").rstrip("\n").split("\n")
        try:
            lines = _edit_in_place(lines)
        except ValueError as e:
            # NEVER fall back to the template here: that would reset the flags of
            # every row the caller did not request and clobber the deck's own
            # csvout/soilout values. An unusable existing deck is operator error.
            logger.error(f"existing print.prt at {print_prt_path} cannot be edited "
                         f"in place: {e}. Refusing to overwrite it with the canonical "
                         f"template — repair or remove the file and re-run.")
            sys.exit(2)
        mode = "edited_in_place"
    else:
        lines = _canonical_template()
        mode = "canonical_template"

    print_prt_path.write_text("\n".join(lines) + "\n")
    logger.info(f"print.prt {mode}: nyskip={NYSKIP}, enabled={sorted(OUTPUT_VARIABLES)}")
    return {"status": "success", "print_prt": str(print_prt_path),
            "mode": mode, "nyskip": NYSKIP,
            "configured_outputs": list(OUTPUT_VARIABLES.keys())}


def validate_outputs(result):
    p = Path(result["print_prt"])
    if not p.exists():
        logger.error("print.prt not created"); sys.exit(3)
    lines = p.read_text().rstrip("\n").split("\n")
    obj_i = next((i for i, l in enumerate(lines)
                  if l.split() and l.split()[0] == "objects"), None)
    if obj_i is None:
        logger.error("print.prt missing 'objects' header"); sys.exit(3)
    rows = [l.split()[0] for l in lines[obj_i + 1:] if l.split()]
    if rows != CANONICAL_OBJECTS:
        logger.error(f"print.prt object rows deviate from canonical order: {rows}")
        sys.exit(3)
    for blk in ("csvout", "soilout"):
        if not any(l.split() and l.split()[0] == blk for l in lines[:obj_i]):
            logger.error(f"print.prt missing required '{blk}' header block"); sys.exit(3)
    for cat, cfg in OUTPUT_VARIABLES.items():
        want = _flags(cfg)
        got = next(l.split()[1:5] for l in lines[obj_i + 1:] if l.split()[0] == cat)
        if got != want:
            logger.error(f"row {cat}: wrote {got}, expected {want}"); sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
