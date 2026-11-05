"""_k2lib -- shared helpers for the REAL KINEROS2 engine tools (private module, not a CLI).

Everything here drives or reads the official USDA-ARS KINEROS2 Fortran program (K2shell,
version 25-Oct-2019, ARS-SWRC/KINEROS2).  Nothing here computes runoff physics.

Facts this module encodes (all verified against the source in
KISSPATH_HOME/engine_builds_20261006/KINEROS2/src_patched and by running the binary):

* Batch mode: ``k2 -b kin.fil`` (``-s`` = batch + silent).  Each kin.fil LINE is one run:
  ``parfile,rainfile,outfile,"title",tfin_min,dt_min,courant,sed,multfile|N,table``.
  Fields are split on commas with NO trimming, so a space after a comma becomes part of the
  next file name ("Can't open  EX1.PRE").  Each field is character(len=150).
* EVERY engine failure exits with status 0: errxit() ends in ``stop ' '`` and the other
  aborts are ``stop ' error - ...'``.  Success must be judged from the output text.
* Parameter/rain files are read by reader.for: lines upper-cased, only columns 1-200 read,
  a tag is found by PREFIX match on the first token that starts with the requested short
  name and is preceded by ',' or line start; list values stop at end of line (the manual
  says lists may continue on the next line -- the code does not do that).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

KI_DIR = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = KI_DIR / "examples" / "ars_samples"
OBS_DIR = KI_DIR / "examples" / "wg11_observed"
DB_PATH = "KISSPATH_ROOT/hydrocraft.db"
# Builder result (auto_dissect_multi_agent/_build_results/KINEROS2.json); used only when
# neither KINEROS2_BIN nor the models DB names a binary.
DEFAULT_BINARY = "KISSPATH_HOME/engine_builds_20261006/KINEROS2/build_github/k2"
ENGINE_VERSION = "KINEROS2 25-Oct-2019"

# English -> SI factors for the quantities the engine prints
FT3_TO_M3 = 0.028316846592
IN_TO_MM = 25.4
ACRE_TO_HA = 0.40468564224
SHORT_TON_PER_ACRE_TO_T_PER_HA = 0.90718474 / 0.40468564224
LB_TO_KG = 0.45359237

# Text that means the engine stopped early.  The binary still exits 0 in every case.
FAILURE_PATTERNS = (
    # errxit(): "\n error - <id>\n <msg>".  Case-SENSITIVE on purpose: every good run prints
    # "Error (Volume in - Volume out - Storage) < 1 percent" and per-element "Error:  -0.12 %".
    re.compile(r"^\s*error\s+-", re.M),
    re.compile(r"STOP\s+error", re.I),                # stop ' error - ...'
    re.compile(r"zero multiplier", re.I),             # infilt: stop ' zero multiplier'
    re.compile(r"neg stor values", re.I),             # infilt: stop ' neg stor values ...'
    re.compile(r"Fortran runtime error", re.I),
    re.compile(r"Program received signal", re.I),
    re.compile(r"too many breakpoints|too much rainfall data", re.I),
)


def fmt_num(x, digits: int = 6) -> str:
    """Plain decimal text for a tagged file.  NEVER '1.6e+06': reader.for treats '+' as a separator,
    so the engine would read the two tokens '1.6E' and '06' (and stop 'missing or invalid')."""
    s = f"{float(x):.{digits}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


class EngineError(RuntimeError):
    """The engine could not be run, or it ran and reported a failure."""


# ----------------------------------------------------------------------------- binary
def resolve_binary(explicit: str | None = None) -> Path:
    """Return the absolute path of the real k2 executable.

    Order: explicit argument -> $KINEROS2_BIN -> models.binary_path in the HydroCraft DB
    -> DEFAULT_BINARY.  Raises EngineError if the chosen file is missing or not executable.
    """
    cand = explicit or os.environ.get("KINEROS2_BIN")
    source = "argument" if explicit else ("KINEROS2_BIN" if cand else None)
    if not cand:
        try:
            con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
            row = con.execute("select binary_path from models where id='KINEROS2'").fetchone()
            con.close()
            if row and row[0]:
                cand, source = row[0], "models DB"
        except sqlite3.Error:
            pass
    if not cand:
        cand, source = DEFAULT_BINARY, "default"
    p = Path(cand).resolve()
    if not p.is_file():
        raise EngineError(f"KINEROS2 binary not found: {p} (from {source}); see triplet dt_kineros2_021")
    if not os.access(p, os.X_OK):
        raise EngineError(f"KINEROS2 binary is not executable: {p}")
    return p


# ----------------------------------------------------------------------------- tag reader mirror
def _is_alpha(c: str) -> bool:
    """reader.for alpha(): 0-9 A-Z . - / : \\ _ (and lower case, since lines are upper-cased)."""
    o = ord(c)
    return 45 <= o <= 57 or 65 <= o <= 90 or 97 <= o <= 122 or c in "_:\\"


@dataclass
class Token:
    line: int        # index into the file's line list
    start: int       # column of first char (0-based, in the original line)
    end: int         # column after last char
    text: str        # upper-cased token text
    delim: str      # '*' first token on its line, '=' after an equals sign, else ','


@dataclass
class Block:
    name: str                 # e.g. GLOBAL, PLANE, CHANNEL, POND, or a rain gage label
    begin_line: int
    end_line: int             # index of the END line (or last line if END missing)
    tokens: list = field(default_factory=list)
    comment: str = ""
    label: str = ""           # full text after BEGIN (the engine keeps only the first word as name)

    def _find(self, lname: str):
        lname = lname.upper()
        for k, tok in enumerate(self.tokens):
            if tok.delim in ",*" and tok.text.startswith(lname):
                return k
        return None

    def lookup(self, lname: str, indx: int = 0):
        """Return (value_text, Token) exactly as the engine's getr4/getstr would, else (None, None)."""
        k = self._find(lname)
        if k is None:
            return None, None
        nx = max(indx, 1)
        nxt = self.tokens[k + 1] if k + 1 < len(self.tokens) else None
        if nxt is not None and nxt.delim == "=":                       # list mode
            line = self.tokens[k].line
            vals = []
            for j in range(k + 1, len(self.tokens)):
                t = self.tokens[j]
                if t.line != line:
                    break
                after = self.tokens[j + 1] if j + 1 < len(self.tokens) else None
                if j > k + 1 and after is not None and after.delim == "=" and after.line == line:
                    break                                               # next tag on this line
                vals.append(t)
            if nx <= len(vals):
                return vals[nx - 1].text, vals[nx - 1]
            return None, None
        # column mode: header token's position on its line, value nx lines further down
        head = self.tokens[k]
        line_tokens = [t for t in self.tokens if t.line == head.line]
        col = line_tokens.index(head)
        lines = sorted({t.line for t in self.tokens if t.line > head.line})
        if nx > len(lines):
            return None, None
        row = [t for t in self.tokens if t.line == lines[nx - 1]]
        if col < len(row):
            return row[col].text, row[col]
        return None, None

    def get_float(self, lname: str, indx: int = 0):
        v, _ = self.lookup(lname, indx)
        if v is None:
            return None
        try:
            return float(v)
        except ValueError:
            return None

    def get_list(self, lname: str, maxn: int = 20) -> list:
        out = []
        for i in range(1, maxn + 1):
            v, _ = self.lookup(lname, i)
            if v is None:
                break
            out.append(v)
        return out

    @property
    def element_id(self):
        v = self.get_float("ID")
        return int(v) if v is not None else None


@dataclass
class TaggedFile:
    path: Path
    lines: list               # original lines WITH their line endings
    blocks: list

    @property
    def text(self) -> str:
        return "".join(self.lines)

    def write(self, path: Path | None = None) -> Path:
        out = Path(path or self.path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="") as fh:
            fh.write(self.text)
        return out


def read_tagged(path) -> TaggedFile:
    """Parse a KINEROS2 parameter (.par) or rainfall (.pre) file the way reader.for does."""
    path = Path(path)
    with open(path, newline="") as fh:
        lines = fh.readlines()
    blocks, cur = [], None
    for li, raw in enumerate(lines):
        body = raw[:200]                                   # engine reads columns 1-200 only
        bang = body.find("!")
        code = body if bang < 0 else body[:bang]
        stripped = code.strip()
        if cur is None:
            m = re.match(r"\s*BEGIN\s+([A-Za-z0-9_.\-/:\\]+)(.*)", code, re.I)
            if m:
                cur = Block(name=m.group(1).upper(), begin_line=li, end_line=li,
                            comment=body[bang + 1:].strip() if bang >= 0 else "",
                            label=(m.group(1) + m.group(2)).strip())
            continue
        if re.match(r"END(\s|$)", stripped, re.I):
            cur.end_line = li
            blocks.append(cur)
            cur = None
            continue
        if not stripped:
            continue
        # tokenise like the engine: alpha runs; '=' before a token makes it a list value
        i, first, delim = 0, True, "*"
        while i < len(code):
            c = code[i]
            if _is_alpha(c):
                j = i
                while j < len(code) and _is_alpha(code[j]):
                    j += 1
                cur.tokens.append(Token(li, i, j, code[i:j].upper(), "*" if first else delim))
                first, delim, i = False, ",", j
                continue
            if c == "=":
                delim = "="
            i += 1
    if cur is not None:                                    # unterminated block
        cur.end_line = len(lines) - 1
        blocks.append(cur)
    return TaggedFile(path=path, lines=lines, blocks=blocks)


def set_token(tf: TaggedFile, tok: Token, new_text: str) -> None:
    """Replace one value token in place, keeping every other byte (copy-first editing)."""
    line = tf.lines[tok.line]
    tf.lines[tok.line] = line[:tok.start] + new_text + line[tok.end:]
    shift = len(new_text) - (tok.end - tok.start)
    for b in tf.blocks:
        for t in b.tokens:
            if t.line == tok.line and t.start > tok.start:
                t.start += shift
                t.end += shift
    tok.end = tok.start + len(new_text)
    tok.text = new_text.upper()


def insert_line_before_end(tf: TaggedFile, block: Block, text: str) -> None:
    """Add 'text' as a new line just before the block's END line (keeps the file's line ending)."""
    eol = "\r\n" if tf.lines and tf.lines[0].endswith("\r\n") else "\n"
    tf.lines.insert(block.end_line, text.rstrip("\r\n") + eol)
    fresh = read_tagged_from_lines(tf.path, tf.lines)
    tf.blocks = fresh.blocks


def read_tagged_from_lines(path, lines) -> TaggedFile:
    tmp = Path(str(path) + ".k2lib_tmp")
    with open(tmp, "w", newline="") as fh:
        fh.write("".join(lines))
    try:
        return read_tagged(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def global_block(tf: TaggedFile) -> Block | None:
    return next((b for b in tf.blocks if b.name == "GLOBAL"), None)


def par_units(tf: TaggedFile) -> str:
    g = global_block(tf)
    u, _ = g.lookup("U") if g else (None, None)
    if not u:
        raise EngineError(f"{tf.path}: GLOBAL block has no UNITS tag (engine stops 'units not specified')")
    if u[0] == "M":
        return "metric"
    if u[0] == "E":
        return "english"
    raise EngineError(f"{tf.path}: UNITS={u} not recognised (engine wants METRIC or ENGLISH)")


ELEMENT_TYPES = ("PLANE", "CHANNEL", "POND", "PIPE", "INJECT", "URBAN", "ADDER", "DIVERTER", "OVERBANK")


def validate_parfile(tf: TaggedFile, rain: TaggedFile | None = None) -> dict:
    """Static checks that catch the silent and the exit-0 failures before a run.

    Returns {"errors": [...], "warnings": [...], "elements": [...], "outlet": id}.
    """
    errs, warns, elements = [], [], []
    g = global_block(tf)
    if g is None or tf.blocks[0].name != "GLOBAL":
        errs.append("the first block must be BEGIN GLOBAL")
    else:
        if g.get_float("C") is None:
            errs.append("GLOBAL has no CLEN (characteristic length) -> engine stops 'char. length not found'")
        try:
            par_units(tf)
        except EngineError as e:
            errs.append(str(e))
    for li, raw in enumerate(tf.lines):
        code = raw.split("!")[0].rstrip("\r\n")
        if len(code.rstrip()) > 200:
            warns.append(f"line {li + 1} has {len(code.rstrip())} chars; the engine ignores everything after column 200")
    for b in tf.blocks:
        for t1, t2 in zip(b.tokens, b.tokens[1:]):
            if t1.line == t2.line and re.fullmatch(r"[0-9.]+E", t1.text) and t2.text[:1].isdigit():
                errs.append(f"line {t1.line + 1}: '{t1.text}+{t2.text}' -- the reader splits exponents at '+'; "
                            f"write the number in plain decimal (or with 'E' and no '+')")
    rain_sat = False
    if rain is not None:
        rain_sat = any(b.lookup("S")[0] is not None for b in rain.blocks)
    usat = g.get_float("SA") if g else None
    seen = set()
    referenced = set()
    no_sat = []
    for b in tf.blocks[1:]:
        if b.name not in ELEMENT_TYPES:
            errs.append(f"block BEGIN {b.name} (line {b.begin_line + 1}) is not an element type {ELEMENT_TYPES}")
            continue
        if b.name == "OVERBANK":
            continue
        eid = b.element_id
        if eid is None:
            errs.append(f"{b.name} block at line {b.begin_line + 1} has no ID")
            continue
        if eid in seen:
            errs.append(f"duplicate element ID {eid}")
        ups = [int(float(v)) for v in b.get_list("UP", 10)]
        lats = [int(float(v)) for v in b.get_list("LA", 3)]
        for r in ups + lats:
            if r not in seen:
                errs.append(f"{b.name} {eid} references element {r} that is not defined ABOVE it "
                            f"(blocks must be in processing order)")
            referenced.add(r)
        if len(lats) > 2:
            errs.append(f"{b.name} {eid} lists {len(lats)} LATERAL elements; max is 2")
        ks = b.get_float("KS") if b.get_float("KE") is None else b.get_float("KE")
        if b.name in ("PLANE", "CHANNEL", "URBAN") and ks and ks > 0:
            g1 = b.get_float("G")
            if g1 and g1 > 0:
                if b.get_float("SA") is None and usat is None and not rain_sat:
                    if rain is not None:
                        errs.append(f"{b.name} {eid}: pervious with G>0 but no SAT in the element, the GLOBAL "
                                    f"block or the rain gages -> engine stops 'initial soil saturation (SA) not specified'")
                    else:
                        no_sat.append(eid)
                if b.lookup("DI")[0] is None:
                    errs.append(f"{b.name} {eid}: no DIST (pore size distribution index)")
                if b.lookup("PO")[0] is None:
                    errs.append(f"{b.name} {eid}: no POROSITY")
                d = b.get_float("DI")
                if d is not None and d > 1.5:
                    errs.append(f"{b.name} {eid}: DIST={d} > 1.5 (engine stops)")
        if b.name in ("PLANE", "CHANNEL") and b.get_float("L") is None:
            errs.append(f"{b.name} {eid}: no LENGTH")
        if b.name in ("PLANE", "CHANNEL") and b.get_float("SL") is None:
            errs.append(f"{b.name} {eid}: no SLOPE")
        if b.name in ("PLANE", "CHANNEL") and b.get_float("MA") is None and b.get_float("CH") is None:
            errs.append(f"{b.name} {eid}: no MANNING or CHEZY roughness")
        seen.add(eid)
        elements.append({"type": b.name, "id": eid, "upstream": ups, "lateral": lats,
                         "print": int(b.get_float("PRI") or 0)})
    if no_sat:
        warns.append(f"{len(no_sat)} pervious element(s) {no_sat[:8]}{'...' if len(no_sat) > 8 else ''} have no SAT "
                     f"in the parameter file: it must come from the rain gages (no rain file was checked)")
    outlet = elements[-1]["id"] if elements else None
    for e in elements[:-1]:
        if e["id"] not in referenced and e["type"] != "DIVERTER":
            warns.append(f"{e['type']} {e['id']} is not UPSTREAM/LATERAL of any later element: its outflow never "
                         f"reaches the outlet (the event summary 'Outflow' is the LAST element only)")
    return {"errors": errs, "warnings": warns, "elements": elements, "outlet": outlet}


def rain_units_check(rain: TaggedFile, units: str) -> list:
    """Warn when total gage depth looks like the wrong unit system for the parameter file."""
    warns = []
    for b in rain.blocks:
        n = b.get_float("N")
        if not n:
            continue
        lab = "D" if b.lookup("D", 1)[0] is not None else "I"
        if lab != "D":
            continue
        last = b.get_float("D", int(n))
        if last is None:
            continue
        if units == "metric" and 0 < last < 3:
            warns.append(f"gage {b.name}: storm total {last} looks like INCHES but the parameter file is METRIC")
        if units == "english" and last > 12:
            warns.append(f"gage {b.name}: storm total {last} looks like MM but the parameter file is ENGLISH")
    return warns


# ----------------------------------------------------------------------------- run files
def write_kin_fil(path, parfile, rainfile, outfile, title, tfin_min, dt_min,
                  courant=False, sediment=False, multfile=None, table=True) -> str:
    """Write a one-run batch file exactly as K2shell parses it (no spaces after commas)."""
    for name, v in (("parfile", parfile), ("rainfile", rainfile or ""), ("outfile", outfile),
                    ("multfile", multfile or "")):
        if "," in str(v) or " " in str(v):
            raise EngineError(f"{name} '{v}' contains a comma or space; kin.fil fields cannot (copy it to a short name)")
        if len(str(v)) > 150:
            raise EngineError(f"{name} longer than 150 chars is truncated by the engine")
    if '"' in title:
        raise EngineError("title cannot contain double quotes")
    yn = lambda b: "Y" if b else "N"
    line = (f'{parfile},{rainfile or ""},{outfile},"{title}",{tfin_min:g},{dt_min:g},'
            f'{yn(courant)},{yn(sediment)},{multfile or "N"},{yn(table)}')
    Path(path).write_text(line + "\n")
    return line


MULT_KEYS = ("ks", "manning", "cv", "g", "interception", "cohesion", "splash")
CHANNEL_MULT_KEYS = ("chan_ks", "chan_g", "chan_manning", "woolhiser", "chan_length", "init_sat")


def write_mult_file(path, mults: dict) -> list:
    """Multiplier file: 7 lines (Ks, n, CV, G, interception, cohesion, splash), optional 6 more
    (channel Ks, channel G, channel n, Woolhiser coeff, channel length, initial saturation)."""
    unknown = set(mults) - set(MULT_KEYS) - set(CHANNEL_MULT_KEYS)
    if unknown:
        raise ValueError(f"unknown multiplier keys {sorted(unknown)}; allowed {MULT_KEYS + CHANNEL_MULT_KEYS}")
    vals = [float(mults.get(k, 1.0)) for k in MULT_KEYS]
    if any(k in mults for k in CHANNEL_MULT_KEYS):
        vals += [float(mults.get(k, 1.0)) for k in CHANNEL_MULT_KEYS]
    if vals[3] <= 0:
        raise ValueError("G multiplier must be > 0 (engine stops 'zero multiplier')")
    Path(path).write_text("".join(f"{v:g}\n" for v in vals))
    return vals


def run_engine(workspace: Path, binary: Path, kin_fil: str = "kin.fil", timeout: float = 600) -> dict:
    """Run 'k2 -b kin.fil' in workspace.  Returns rc/stdout/stderr; never trusts rc alone."""
    try:
        cp = subprocess.run([str(binary), "-b", kin_fil], cwd=str(workspace), capture_output=True,
                            text=True, errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise EngineError(f"engine timed out after {timeout}s (huge tfin/dt ratio?)") from e
    return {"rc": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr}


def engine_failures(out_text: str, stdout: str = "", stderr: str = "") -> list:
    """Every reason to call this run a failure, from the text (the engine's rc is always 0)."""
    reasons = []
    blob = "\n".join([out_text or "", stdout or "", stderr or ""])
    for pat in FAILURE_PATTERNS:
        m = pat.search(blob)
        if m:
            lo = blob.rfind("\n", 0, m.start()) + 1
            hi = blob.find("\n", m.end())
            hi2 = blob.find("\n", hi + 1) if hi >= 0 else -1
            reasons.append(blob[lo:hi2 if hi2 > 0 else None].strip().replace("\n", " | ")[:200])
    if "Event Volume Summary" not in (out_text or ""):
        reasons.append("output file has no 'Event Volume Summary' (run did not finish)")
    return reasons


# ----------------------------------------------------------------------------- output parser
_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?"


def _f(s):
    try:
        return float(s.replace("D", "E").replace("d", "e"))
    except (ValueError, AttributeError):
        return float("nan")


def parse_output(text: str) -> dict:
    """Parse a KINEROS2 .out file (version 25-Oct-2019 layout) into plain Python objects."""
    res = {"version": None, "title": None, "run": {}, "multipliers": {}, "warnings": [],
           "elements": [], "event_summary": {}, "tabular_summary": [], "units": None,
           "errors": engine_failures(text)}
    m = re.search(r"KINEROS2\s+(\S+)", text)
    res["version"] = f"KINEROS2 {m.group(1)}" if m else None
    m = re.search(r"Title:\s*(.*)", text)
    res["title"] = m.group(1).strip() if m else None
    for key, lab in (("parfile", "Parameter File Used"), ("rainfile", "Rainfall File Used"),
                     ("tfin_min", "Length of Run, minutes"), ("dt_min", "Time Step, minutes"),
                     ("courant", "Use Courant criteria?"), ("sediment", "Simulate Sed. Transport?"),
                     ("multfile", "Multiplier file \\(if any\\)"), ("table", "Tabular Summary?")):
        mm = re.search(lab + r"\.*\s*(.*)", text)
        if mm:
            res["run"][key] = mm.group(1).strip()
    for key, lab in (("ks", "Saturated Conductivity"), ("manning", "Manning n"), ("cv", "CV of Ksat"),
                     ("g", "Capillary Drive Coeff"), ("interception", "Intercepted Depth"),
                     ("cohesion", "Sediment Cohesion Coeff"), ("splash", "Sediment Splash Coeff")):
        mm = re.search(lab + r"\.*\s*(" + _NUM + ")", text)
        if mm:
            res["multipliers"][key] = _f(mm.group(1))
    for mm in re.finditer(r"(Plane|Channel|Pond|Urban|Pipe)\s+(\d+):\s+based on length and parameter CLEN,\s*"
                          r"the numerical increment of\s+(" + _NUM + r")", text):
        res["warnings"].append({"kind": "numerical_increment_too_large", "element_type": mm.group(1),
                                "element_id": int(mm.group(2)), "increment": _f(mm.group(3))})
    for mm in re.finditer(r"Elem\.\s+(\d+)\s+rating exceeded at time\s+(" + _NUM + ")", text):
        res["warnings"].append({"kind": "rating_exceeded", "element_id": int(mm.group(1)),
                                "time_min": _f(mm.group(2))})
    if re.search(r"cu ft", text):
        res["units"] = "english"
    elif re.search(r"cu m", text):
        res["units"] = "metric"

    # per-element sections (PRINT >= 1)
    heads = list(re.finditer(r"^\s*(Plane|Channel|Pond|Urban|Pipe|Adder|Injection|Inject)\s+Elem(?:ent|\.)\s+(\d+)\s*$",
                             text, re.M))
    for k, h in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else text.find("Event Volume Summary", h.end())
        sec = text[h.end(): end if end > 0 else None]
        el = {"type": h.group(1).upper(), "id": int(h.group(2))}
        mm = re.search(r"Contributing area =\s*(" + _NUM + r")\s*(\S+)", sec)
        if mm:
            el["contributing_area"], el["area_unit"] = _f(mm.group(1)), mm.group(2)
        mm = re.search(r"Peak flow =\s*(" + _NUM + r")\s*(cu m /s|cu ft/s)\s*\((" + _NUM + r")\s*(mm/hr|in/hr)\)\s*at\s*("
                       + _NUM + r")\s*min", sec)
        if mm:
            el.update(peak_discharge=_f(mm.group(1)), peak_discharge_unit=mm.group(2),
                      peak_rate=_f(mm.group(3)), peak_rate_unit=mm.group(4), peak_time_min=_f(mm.group(5)))
        mm = re.search(r"Peak sediment discharge =\s*(" + _NUM + r")\s*(\S+)\s*at\s*(" + _NUM + r")\s*min", sec)
        if mm:
            el.update(peak_sediment_discharge=_f(mm.group(1)), peak_sediment_unit=mm.group(2),
                      peak_sediment_time_min=_f(mm.group(3)))
        wb = {}
        for lab in ("Rain", "Inflow", "Infilt", "Stored", "Out", "Error"):
            mm = re.search(r"^\s*" + lab + r":\s*(" + _NUM + r")", sec, re.M)
            if mm:
                wb[lab.lower()] = _f(mm.group(1))
        el["water_balance"] = wb
        sb = {}
        for lab in ("In", "Deposited", "Soil Loss", "Out"):
            mm = re.search(lab + r":\s*(" + _NUM + r")\s*(kg|lb)\s*$", sec, re.M)
            if mm:
                sb[lab.lower().replace(" ", "_")] = _f(mm.group(1))
        if sb:
            el["sediment_balance"] = sb
        hm = re.search(r"Elapsed Time.*\n(.*)\n", sec)
        if hm:
            cols = ["time_min", "rain_rate", "outflow_rate", "discharge"]
            if "Sediment" in hm.group(0):
                cols.append("sediment_discharge")
            rows = []
            for line in sec[hm.end():].splitlines():
                s = line.strip()
                if not s:
                    if rows:
                        break
                    continue
                parts = s.split()
                if not re.fullmatch(_NUM, parts[0]):
                    break
                rows.append([_f(p) for p in parts[:len(cols)]])
            el["hydrograph_columns"] = cols
            el["hydrograph"] = rows
        res["elements"].append(el)

    # event summary
    es = {}
    sm = re.search(r"Event Volume Summary:(.*?)(?:Tabular Summary|\Z)", text, re.S)
    if sm:
        body = sm.group(1)
        for line in body.splitlines():
            mm = re.match(r"^\s*([A-Za-z][A-Za-z ]+?)\s+(" + _NUM + r")\s*(mm|in)?\s+(" + _NUM + r")", line)
            if mm:
                key = mm.group(1).strip().lower().replace(" ", "_")
                es[key] = {"depth": _f(mm.group(2)), "volume": _f(mm.group(4))}
        es["volume_error_lt_1pct"] = "Error (Volume in - Volume out - Storage) < 1 percent" in body
        mm = re.search(r"Total watershed area =\s*(" + _NUM + r")\s*(\S+)", body)
        if mm:
            es["watershed_area"], es["area_unit"] = _f(mm.group(1)), mm.group(2)
        mm = re.search(r"Sediment yield =\s*(" + _NUM + r")\s*(\S+)", body)
        if mm:
            es["sediment_yield"], es["sediment_yield_unit"] = _f(mm.group(1)), mm.group(2)
        mm = re.search(r"Particle size \((mm|in)\)\s+(.*)\n\s*Yield \((\S+)\)\s+(.*)", body)
        if mm:
            es["sediment_by_class"] = {"size_unit": mm.group(1), "sizes": [_f(x) for x in mm.group(2).split()],
                                       "yield_unit": mm.group(3), "yields": [_f(x) for x in mm.group(4).split()]}
        mm = re.search(r"Time step distribution \(100,75,50%\) =\s*(.*)min", body)
        if mm:
            es["time_step_distribution_min"] = [_f(x) for x in mm.group(1).replace(",", " ").split()]
        es["courant_adjusted"] = "Time step was adjusted to meet Courant condition" in body
        es["volume_warnings"] = re.findall(r"(?im)^.*(?:differ|greater than one percent|warning).*$", body)
    res["event_summary"] = es

    tm = re.search(r"Tabular Summary of Element Hydrologic Components\s*\n(.*)", text, re.S)
    if tm:
        lines = tm.group(1).splitlines()
        unit_line = next((ln for ln in lines if "cu m" in ln or "cu ft" in ln), "")
        for line in lines:
            parts = line.split()
            # a data row = integer id + element type word; select by content, never by position
            if len(parts) < 9 or not parts[0].isdigit() or not parts[1].isalpha():
                if res["tabular_summary"] and not line.strip():
                    break
                continue
            row = {"id": int(parts[0]), "type": parts[1].upper()}
            names = ["element_area", "cumulated_area", "inflow", "rainfall", "outflow", "peak_rate",
                     "total_infiltration", "initial_water_content", "subsoil_infiltration", "sediment_yield"]
            for nm, v in zip(names, parts[2:]):
                row[nm] = _f(v)
            res["tabular_summary"].append(row)
        res["tabular_units_line"] = unit_line.strip()
    return res


def outlet_element(parsed: dict, outlet_id=None):
    els = parsed.get("elements") or []
    if outlet_id is not None:
        for e in els:
            if e["id"] == int(outlet_id):
                return e
        return None
    return els[-1] if els else None


def to_si(parsed: dict) -> dict:
    """Headline numbers in SI (m3/s, m3, mm, ha, t/ha) whatever UNITS the run used."""
    eng = parsed.get("units") == "english"
    qf = FT3_TO_M3 if eng else 1.0
    df = IN_TO_MM if eng else 1.0
    es = parsed.get("event_summary") or {}
    out = {}
    for k, v in es.items():
        if isinstance(v, dict) and "depth" in v:
            out[f"{k}_depth_mm"] = v["depth"] * df
            out[f"{k}_volume_m3"] = v["volume"] * qf
    if "watershed_area" in es:
        out["watershed_area_ha"] = es["watershed_area"] * (ACRE_TO_HA if eng else 1.0)
    if "sediment_yield" in es:
        out["sediment_yield_t_per_ha"] = es["sediment_yield"] * (SHORT_TON_PER_ACRE_TO_T_PER_HA if eng else 1.0)
    return out


def write_json(path, obj) -> None:
    Path(path).write_text(json.dumps(obj, indent=2, default=str))


def copy_case(files: dict, workspace: Path) -> dict:
    """Copy input files into the workspace under short names.  files: {role: src_path}."""
    workspace.mkdir(parents=True, exist_ok=True)
    placed = {}
    for role, src in files.items():
        if not src:
            continue
        src = Path(src)
        if not src.is_file():
            raise EngineError(f"{role} file not found: {src}")
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", src.name)
        dst = workspace / name
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        placed[role] = name
    return placed
