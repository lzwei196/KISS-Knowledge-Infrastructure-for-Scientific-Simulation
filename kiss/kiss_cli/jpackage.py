"""Fixed installation-only Julia package operations; no model functions called."""
from pathlib import Path
import re
from uuid import UUID
from .rpackage import scoped

MARK = '@@KISS-JULIA-PACKAGE-OK@@'
PROBE = '''using UUIDs
length(ARGS) == 6 || error("invalid arguments")
project, depot, name, uuid, version, symbols = ARGS
realpath(Base.active_project()) == realpath(joinpath(project,"Project.toml")) || error("wrong project")
empty!(LOAD_PATH); append!(LOAD_PATH,["@","@stdlib"])
empty!(DEPOT_PATH); push!(DEPOT_PATH,realpath(depot))
m = Base.require(Base.PkgId(UUID(uuid),name))
string(Base.PkgId(m).uuid) == uuid || error("wrong UUID")
string(pkgversion(m)) == version || error("wrong version")
f = realpath(pathof(m))
root = realpath(depot)
startswith(f,root*string(Base.Filesystem.path_separator)) || error("module outside depot")
for s in split(symbols,",")
    isdefined(m,Symbol(s)) || error("missing package binding")
end
println("@@KISS-JULIA-PACKAGE-OK@@")
println(f)'''
INSTALL = '''length(ARGS) == 2 || error("invalid arguments")
project,depot = ARGS
realpath(Base.active_project()) == realpath(joinpath(project,"Project.toml")) || error("wrong project")
empty!(LOAD_PATH); append!(LOAD_PATH,["@","@stdlib"])
mkpath(depot); empty!(DEPOT_PATH); push!(DEPOT_PATH,realpath(depot))
ENV["JULIA_PKG_PRECOMPILE_AUTO"]="0"
using Pkg
Pkg.instantiate(;allow_autoprecomp=false)'''


def validate(c):
    keys = {'name','uuid','version','project','depot','runtime','symbols'}
    if not isinstance(c,dict) or set(c) != keys:
        raise ValueError('julia_package needs name/uuid/version/project/depot/runtime/symbols')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',str(c['name'])):
        raise ValueError('invalid Julia package name')
    if str(UUID(c['uuid'])) != c['uuid']:
        raise ValueError('invalid Julia package UUID')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?',str(c['version'])):
        raise ValueError('invalid Julia package version')
    if not isinstance(c['symbols'],list) or not c['symbols'] or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_!]*',str(s)) for s in c['symbols']):
        raise ValueError('invalid Julia package symbols')
    for k in ('project','depot','runtime'):
        p=Path(c[k])
        if p.anchor or '..' in p.parts or not p.parts:
            raise ValueError('Julia paths must be relative within workspace')
    return c


def args(project,depot,c=None):
    prefix=['--startup-file=no','--history-file=no','--threads=1','--project='+str(project),'-e']
    if c is None:
        return prefix+[INSTALL,str(project),str(depot)]
    c=validate(c)
    return prefix+[PROBE,str(project),str(depot),c['name'],c['uuid'],c['version'],','.join(c['symbols'])]


def guard(argv,cwd,root):
    if argv in (['--version'],['--help']):
        return
    if len(argv) not in (8,12) or argv[:3] != ['--startup-file=no','--history-file=no','--threads=1'] or not argv[3].startswith('--project=') or argv[4]!='-e':
        raise ValueError('Julia permits only fixed scoped package install/load probes')
    project=scoped(argv[6],cwd,root); depot=scoped(argv[7],cwd,root)
    if scoped(argv[3].split('=',1)[1],cwd,root)!=project:
        raise ValueError('Julia project mismatch')
    if len(argv)==8 and argv[5]==INSTALL:
        return
    if len(argv)!=12 or argv[5]!=PROBE:
        raise ValueError('Julia script is not a fixed package operation')
    validate(dict(name=argv[8],uuid=argv[9],version=argv[10],symbols=argv[11].split(','),project='project',depot='depot',runtime='runtime'))


IMPORT_TIMEOUT_SECONDS = 120


def startup_env(depot):
    """Use the same scoped cache identity before setup and verifier startup."""
    import os
    return dict(JULIA_DEPOT_PATH=str(depot), JULIA_LOAD_PATH="@" + os.pathsep + "@stdlib",
                JULIA_NUM_THREADS="1", JULIA_NUM_PRECOMPILE_TASKS="1",
                JULIA_PKG_PRECOMPILE_AUTO="0")
