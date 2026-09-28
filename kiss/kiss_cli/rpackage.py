"""Fixed installation-only R package loader; never invokes model functions."""
from pathlib import Path
import re

MARK = '@@KISS-R-PACKAGE-OK@@'
PROBE = '''a <- commandArgs(TRUE); stopifnot(length(a)==6L)
lib <- normalizePath(a[1], mustWork=TRUE)
library(a[2], lib.loc=lib, character.only=TRUE)
stopifnot(as.character(packageVersion(a[2], lib.loc=lib)) == a[3])
dll <- getLoadedDLLs()[[a[2]]]
stopifnot(!is.null(dll))
stopifnot(normalizePath(dll[["path"]], mustWork=TRUE) == normalizePath(file.path(lib,a[2],a[4]), mustWork=TRUE))
stopifnot(a[5] %in% names(getDLLRegisteredRoutines(dll)$.Fortran))
stopifnot(is.function(getExportedValue(a[2],a[6])))
cat("@@KISS-R-PACKAGE-OK@@\\n", a[2], a[3], dll[["path"]], "\\n")'''


def validate(contract):
    keys = {'name', 'version', 'library', 'dll', 'fortran_symbol', 'function'}
    if (not isinstance(contract, dict) or not keys <= set(contract)
            or set(contract) - keys - {'library_root'}):
        raise ValueError('r_package needs name/version/library/dll/fortran_symbol/function')
    if contract.get('library_root', 'model') not in {'model', 'workspace'}:
        raise ValueError('R library_root must be model or workspace')
    for key in ('name', 'fortran_symbol', 'function'):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]*', str(contract[key])):
            raise ValueError(f'invalid R {key}')
    if not re.fullmatch(r'[0-9]+(?:[.-][0-9]+)*', str(contract['version'])):
        raise ValueError('invalid R package version')
    for key in ('library', 'dll'):
        p = Path(contract[key])
        if p.anchor or '..' in p.parts or not p.parts:
            raise ValueError(f'R {key} must be a relative contained path')
    return contract


def probe_args(library, contract):
    c = validate(contract)
    return ['--vanilla', '-e', PROBE, str(library), c['name'],
            c['version'], c['dll'], c['fortran_symbol'], c['function']]


def scoped(path, cwd, root):
    p = Path(path)
    p = (p if p.is_absolute() else cwd / p).resolve()
    if p == root or root in p.parents:
        return p
    raise ValueError('R installation path escapes workspace')


def guard(command, args, cwd, root):
    if command == 'r':
        if len(args) != 4 or args[:2] != ['CMD', 'INSTALL'] or not args[2].startswith('--library='):
            raise ValueError('only R CMD INSTALL --library=<workspace> <workspace-source> is permitted')
        scoped(args[2].split('=', 1)[1], cwd, root)
        scoped(args[3], cwd, root)
        return
    if len(args) != 9 or args[:3] != ['--vanilla', '-e', PROBE]:
        raise ValueError('Rscript permits only the fixed native-package load probe')
    lib = scoped(args[3], cwd, root)
    c = dict(zip(('name','version','dll','fortran_symbol','function'), args[4:]))
    c['library'] = 'library'
    validate(c)
    scoped(lib / c['name'] / c['dll'], cwd, root)
