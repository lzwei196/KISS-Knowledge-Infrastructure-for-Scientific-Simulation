"""
Reader for SWAP .swp files that follows the TTUTIL 4.2.7 data-file syntax
exactly, so the KI tools see the same KEY = value settings SWAP sees.

SWAP 4.2.0 reads the .swp through TTUTIL (RDINIT / RDSINR / RDSCHA ...).
The pinned build links libttutil 4.2.7 (repo meson.build, ttutil_version).
This module is a direct port of that version's parser, not a guess:

* lexer: the character-class table ITYPE, the jump table LEXJTB and the
  start states JMPPTR are copied from ttutil v4.2.7 src/rdjdat.gin, and
  tokens are found the way src/rdlex.for does it (every start state is run,
  the longest match wins, ties go to the later start state);
* parser: the state table JUMPTB and its error messages are copied from
  src/rdsctb.for, and the loop below follows RDSCTB: repeat values n*v,
  string concatenation 'a' // 'b', values continued on following lines,
  multi-name tables (values go to the names in turn), a table ended by ';'
  or by the next name after an end of line, '!' comments anywhere, and a
  record skipped when its first column is '*' or '!' or it is empty
  (RDSCTB record loop);
* records: split as src/recread.f90 does: a record ends at LF, CR, CR LF
  or LF CR (one end each), trailing blanks are kept;
* missing values (TTUTIL's missing-value token) come back as MISSING; a
  reader then gets TTUTIL's own default for it (rddata.for: integer -99,
  real -99.99, string '- MISSING -', logical .FALSE.); RDSINR skips its
  range check for -99, so SWAP runs on with switch = -99.
* errors: any syntax error, an incomplete table, a type change inside one
  variable, a name longer than 31 characters, or a name used twice is a
  TTUTIL error, and TTUTIL then stops the program (rddata.for FATALERR
  after RDINDX; rdindx.for 'name already used'). read_swp() raises
  SwpSyntaxError in all those cases instead of guessing.

read_swp(path) -> {lowercase name: value or list of values}. A variable
with one value gives the value itself; with more (array or table column)
a list. Values are int, float, str (quotes removed), or the raw text for
logicals and dates/times; a TTUTIL missing value gives MISSING. Strings
are plain ASCII: TTUTIL refuses any byte >= 128 or control code (TAB too)
inside a quoted string, so a non-ASCII path in a .swp is a syntax error.
"""

TEOI, TEOL, TTIME, TINTEG, TFLOAT, TSPACE, TCOMMA, TEQUAL, TSEMIC, TMULT, \
    TLPAR, TRPAR, TSCONC, TCMMNT, TIDENT, TSTRNG, TLOGIC, TMISS = range(1, 19)
_VALUE_TOKENS = {TSTRNG, TINTEG, TFLOAT, TTIME, TLOGIC, TMISS}
_VTYPE = {TINTEG: "I", TFLOAT: "F", TSTRNG: "C", TLOGIC: "L", TTIME: "T"}
_EOTAB = 16
_INLMX = 31          # longest variable name TTUTIL accepts (rdindx.for)

# ttutil v4.2.7 src/rdjdat.gin: ITYPE(0:255), character code -> class
ITYPE = (
    1,1,1,1,1,1,1,1,1,1,1,1,1,2,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    3,4,5,5,6,5,5,7,8,9,10,11,12,13,14,15,16,16,16,16,16,16,16,16,16,16,17,18,5,19,5,5,
    5,20,20,20,21,21,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,5,5,5,5,22,
    5,20,20,20,21,21,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,20,5,5,5,5,1,
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
    1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,
)
# ttutil v4.2.7 src/rdjdat.gin: LEXJTB(43,22); LEXJTB[state-1][class-1]
LEXJTB = (
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2,0,0,0,0,0,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,3,0,3,2,10,0,0,0,0,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,4,0,0,0,5,5,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,6,0,6,4,0,0,0,0,0,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,6,0,6,0,0,0,0,5,5,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,7,0,0,0,0,0,0),
    (-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,7,-3,-3,-3,-3,-3,8),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,9,0,0,0,0,0,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,9,10,0,0,0,0,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,11,0,0,0,0,0,0),
    (-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,11,12,-3,-3,-3,-3,-3),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,13,0,0,0,0,0,0),
    (-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,14,-3,13,-3,-3,-3,-3,-3,-3),
    (-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,-3,14,-3,-3,-3,-3,-3,-3),
    (0,0,0,0,0,0,0,0,0,0,16,0,16,17,0,18,0,0,0,0,0,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,17,0,18,0,0,0,0,0,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,19,0,0,0,0,0,0),
    (-4,-4,-4,-4,-4,-4,-4,-4,-4,-4,-4,-4,-4,19,-4,18,-4,-4,-4,-4,20,-4),
    (-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,19,-5,-5,-5,-5,20,-5),
    (0,0,0,0,0,0,0,0,0,0,21,0,21,0,0,21,0,0,0,0,0,0),
    (-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,-5,21,-5,-5,-5,-5,-5,-5),
    (0,0,23,30,0,0,0,28,29,27,0,24,0,0,31,0,0,26,25,0,0,0),
    (-6,-6,23,30,-6,-6,-6,28,29,27,-6,24,-6,-6,31,-6,-6,26,25,-6,-6,-6),
    (-7,-7,24,-7,-7,-7,-7,-7,-7,-7,-7,-7,-7,-7,-7,-7,-7,-7,-7,-7,-7,-7),
    (-8,-8,25,-8,-8,-8,-8,-8,-8,-8,-8,-8,-8,-8,-8,-8,-8,-8,-8,-8,-8,-8),
    (-9,-9,26,-9,-9,-9,-9,-9,-9,-9,-9,-9,-9,-9,-9,-9,-9,-9,-9,-9,-9,-9),
    (-10,-10,27,-10,-10,-10,-10,-10,-10,-10,-10,-10,-10,-10,-10,-10,-10,-10,-10,-10,-10,-10),
    (-11,-11,28,-11,-11,-11,-11,-11,-11,-11,-11,-11,-11,-11,-11,-11,-11,-11,-11,-11,-11,-11),
    (-12,-12,29,-12,-12,-12,-12,-12,-12,-12,-12,-12,-12,-12,-12,-12,-12,-12,-12,-12,-12,-12),
    (30,-14,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30,30),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,32,0,0,0,0,0,0,0),
    (-13,-13,32,-13,-13,-13,-13,-13,-13,-13,-13,-13,-13,-13,-13,-13,-13,-13,-13,-13,-13,-13),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,34,34,0),
    (-15,-15,-15,-15,-15,34,-15,-15,-15,-15,-15,-15,-15,-15,-15,34,-15,-15,-15,34,34,34),
    (0,0,0,0,0,0,36,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0),
    (0,0,37,37,37,37,0,37,37,37,37,37,37,37,37,37,37,37,37,37,37,37),
    (0,0,37,37,37,37,38,37,37,37,37,37,37,37,37,37,37,37,37,37,37,37),
    (-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16,-16),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,40,0,0,0,0,0,0,0,0),
    (0,0,0,0,0,0,0,0,0,0,0,0,0,41,0,0,0,0,0,40,40,0),
    (-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17,-17),
    (0,0,0,0,0,0,0,0,0,0,0,0,43,0,0,0,0,0,0,0,0,0),
    (-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18,-18),
)
JMPPTR = (1, 15, 22, 33, 35, 39, 42)
# ttutil v4.2.7 src/rdsctb.for: JUMPTB(-1:16, 0:18); JUMPTB[token][state+1]
JUMPTB = (
    (-1,0,-1,-1,-1,-1,-1,-1,0,0,0,0,0,0,0,0,0,0),
    (16,16,16,-1,-1,-1,-1,-1,0,16,0,16,0,16,0,16,16,0),
    (6,15,1,3,3,4,6,6,7,15,9,15,11,15,13,15,15,0),
    (-1,12,-1,-1,-1,-1,-1,12,12,0,12,0,0,0,12,12,12,0),
    (-1,8,-1,-1,-1,-1,-1,8,8,0,12,0,0,0,8,8,8,0),
    (-1,12,-1,-1,-1,-1,-1,12,12,0,12,0,0,0,12,12,12,0),
    (-1,0,1,2,3,4,5,6,7,14,9,14,11,14,13,14,15,0),
    (4,13,-1,4,-1,-1,4,-1,0,13,0,13,0,13,0,13,0,0),
    (7,0,-1,7,-1,-1,7,-1,0,0,0,0,0,0,0,0,0,0),
    (16,16,-1,-1,-1,-1,-1,-1,0,16,0,16,0,16,0,16,16,0),
    (-1,0,-1,-1,-1,-1,-1,-1,0,9,0,0,0,0,0,0,0,0),
    (-1,0,-1,-1,-1,-1,-1,-1,0,0,0,0,0,0,0,0,0,0),
    (-1,0,-1,-1,-1,-1,-1,-1,0,0,0,0,0,0,0,0,0,0),
    (-1,0,-1,-1,-1,-1,-1,-1,0,0,0,11,0,0,0,0,0,0),
    (-1,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,0),
    (5,16,2,5,5,5,5,5,0,0,0,0,0,0,0,0,16,0),
    (-1,10,-1,-1,-1,-1,-1,10,10,0,10,0,10,0,10,10,10,0),
    (-1,12,-1,-1,-1,-1,-1,12,12,0,12,0,0,0,12,12,12,0),
    (-1,12,-1,-1,-1,-1,-1,12,12,0,12,0,0,0,12,12,12,0),
)
# src/rdsctb.for MESSAG(1:15), message for the state the error happened in
MESSAG = ('Variable name expected', 'Next variable name or = expected', 'Without =, a next name is expected', 'Next variable name expected', 'Next name, = or value on next line', 'Next name or first value expected', 'Value expected', 'Illegal after INTEGER value', 'After * a value is expected', 'Illegal after CHARACTER string', 'After // next string expected', 'No proper value separation', 'There must be another value', 'After a value this is illegal', 'New variable or next value expected')


class SwpSyntaxError(ValueError):
    """The .swp breaks TTUTIL syntax; SWAP would stop on it."""


class _Missing:
    def __repr__(self):
        return "MISSING"


MISSING = _Missing()
# TTUTIL default missing values (rddata.for DATA IM_D, RM_D, CM_D, LM_D);
# SWAP never changes them (no RDMDEF call in src/).
MISSING_INT = -99
MISSING_REAL = -99.99
MISSING_STR = "- MISSING -"


def _split_records(data):
    """Records of a file the way src/recread.f90 splits them: the end of a
    record is the first CR or LF; a CR right after LF, or an LF right after
    CR, belongs to the same end."""
    i, n = 0, len(data)
    while i < n:
        jcr, jlf = data.find(b"\r", i), data.find(b"\n", i)
        ends = [j for j in (jcr, jlf) if j >= 0]
        if not ends:
            yield data[i:]
            return
        j = min(ends)
        yield data[i:j]
        other = b"\n" if data[j:j + 1] == b"\r" else b"\r"
        i = j + 1
        if data[i:i + 1] == other:
            i += 1


def _records(data):
    """Significant records with record numbers (RDSCTB record loop: a record
    starting with CHAR(26), the DOS end-of-file mark, ends the file; a record
    whose first column is '*' or '!', or which is empty, is skipped)."""
    for lineno, rec in enumerate(_split_records(data), 1):
        if rec[:1] == b"\x1a":
            return
        if not rec or rec[:1] in (b"*", b"!"):
            continue
        yield lineno, rec


def _lex_record(rec):
    """Tokens of one record, as (token, text); ends with TEOL (rdlex.for)."""
    codes = [ITYPE[b] for b in rec] + [2]        # CHAR(13) end of line
    stblen = len(codes)                          # 1-based length incl. EOL
    ip = 0
    while True:
        isp = ip + 1
        if isp >= stblen:
            yield TEOL, ""
            return
        token, tmpp = 0, isp
        for start in JMPPTR:
            state, p = start, isp
            while state > 0:
                state = LEXJTB[state - 1][codes[p - 1] - 1]
                p += 1
            if state < 0:
                p -= 2
                if p >= tmpp:
                    tmpp, token = p, -state
        ip = tmpp
        yield token, rec[isp - 1:ip].decode("latin-1")


def _tokens(data):
    for lineno, rec in _records(data):
        for token, text in _lex_record(rec):
            yield token, text, lineno
    yield TEOI, "", None


def _value(token, text):
    if token == TINTEG:
        return int(text)
    if token == TFLOAT:
        return float(text.replace("d", "e").replace("D", "e"))
    if token == TSTRNG:
        # ASCII only: bytes >= 128 and control codes (TAB included) are
        # ITYPE class 1, which the string states of LEXJTB (36, 37) do not
        # accept, so TTUTIL rejects them inside a string (syntax error)
        return text[1:-1]
    if token == TMISS:
        return MISSING
    return text                                  # logical, date/time


def read_swp(path):
    with open(path, "rb") as f:
        return read_swp_bytes(f.read(), path)


def read_swp_bytes(data, path="<swp>"):
    toks = list(_tokens(data))
    pos = 0
    result = {}
    where = {}

    def fail(msg, lineno):
        at = f"line {lineno}" if lineno else "end of file"
        raise SwpSyntaxError(f"{path}: {at}: {msg} (TTUTIL would stop SWAP)")

    eof = False
    while not eof:
        state, names, values, coltype = 1, [], [], {}
        irep, nval, tbcomp, last_rep = 1, 0, True, 0
        lineno = None
        while state != _EOTAB:
            token, text, lineno = toks[pos]
            pos += 1
            old = state
            state = JUMPTB[token][old + 1]
            if old > 0 and state <= 0:
                if token == TEOI:
                    fail("Unexpected End_Of_File", lineno)
                fail(f"{MESSAG[old - 1]} (at {text!r})", lineno)
            if token == TIDENT and state != _EOTAB:
                if len(text) > _INLMX:
                    fail(f"Variable name too long: {text}", lineno)
                names.append((text.upper(), lineno))
            elif token in _VALUE_TOKENS:
                if token == TINTEG and toks[pos][0] == TMULT:
                    irep = int(text)
                    if len(names) > 1:
                        fail("Repeat value not allowed in table", lineno)
                    if irep <= 0:
                        fail("Repeat value should be positive", lineno)
                elif old == 11:                  # after //: concatenate
                    # the repeat count belongs to the whole joined string
                    # (n*'a'//'b' gives n copies of 'ab'), as RDTMP1 task 7
                    # extends the value just written, repeat value included
                    joined = values[-1] + _value(token, text)
                    values[-last_rep:] = [joined] * last_rep
                else:
                    val = _value(token, text)
                    values.extend([val] * irep)
                    last_rep = irep
                    nval += irep
                    colnum = 1 + (nval - 1) % max(1, len(names))
                    if token != TMISS:
                        vt = _VTYPE[token]
                        have = coltype.setdefault(colnum, vt)
                        if have != vt:
                            fail("Inconsistent variable type", lineno)
                    irep = 1
                    tbcomp = colnum == len(names)
        if not tbcomp:
            fail("Previous table is incomplete", lineno)
        if token == TIDENT:
            pos -= 1                             # name starts the next table
        elif token == TEOI:
            eof = True
        ncol = len(names)
        for k, (name, nline) in enumerate(names):
            col = values[k::ncol] if ncol else []
            key = name.lower()
            if key in result:
                fail(f"name already used: {name} (first on line "
                     f"{where[key]})", nline)
            where[key] = nline
            result[key] = col[0] if len(col) == 1 else col
    return result
