"""Strict installation-only loader for the pinned MARRMoT Octave toolbox."""
from pathlib import Path
import hashlib
import re
from .rpackage import scoped

MARK = "@@KISS-OCTAVE-TOOLBOX-OK@@"
FLAGS = ["--no-init-all", "--no-history", "--no-window-system", "--quiet"]
PROBE = "a=argv(); assert(numel(a)==4);\nsource=canonicalize_file_name(a{1}); packages=canonicalize_file_name(a{2});\npkg('prefix',fullfile(packages,'packages'),fullfile(packages,'packages'));\npkg('local_list',fullfile(packages,'package-list'));\npkg('global_list',fullfile(packages,'global-package-list'));\nwanted=strsplit(a{4},','); installed=pkg('list');\nfor j=1:numel(wanted)\n  pair=strsplit(wanted{j},'='); assert(numel(pair)==2); found=false;\n  for k=1:numel(installed)\n    if strcmp(installed{k}.name,pair{1})\n      assert(strcmp(installed{k}.version,pair{2}));\n      ip=canonicalize_file_name(installed{k}.dir);\n      assert(strncmp(ip,[packages,filesep],numel(packages)+1));\n      if isfield(installed{k},'archprefix')\n        ap=canonicalize_file_name(installed{k}.archprefix);\n        assert(strncmp(ap,[packages,filesep],numel(packages)+1));\n      end\n      found=true;\n    end\n  end\n  assert(found);\nend\npkg('load','optim');\nnative=functions(str2func('__max_nargin_optim__'));\nnp=canonicalize_file_name(native.file);\nassert(strncmp(np,[packages,filesep],numel(packages)+1));\nassert(strcmp(np(end-3:end),'.oct'));\ndescription=type('__max_nargin_optim__');\nassert(!isempty(strfind(description{1},'dynamically-linked function')));\nprintf('NATIVE_OK %s\\n',np);\naddpath(genpath(fullfile(source,'MARRMoT','Models')));\naddpath(genpath(fullfile(source,'MARRMoT','Functions')));\nnames=strsplit(a{3},','); assert(numel(names)==47);\nfor i=1:numel(names)\n  name=names{i};\n  mc=meta.class.fromName(name);\n  assert(!isempty(mc));\n  assert(strcmp(mc.Name,name));\n  actual=canonicalize_file_name(which(name));\n  expected=canonicalize_file_name(fullfile(source,'MARRMoT','Models','Model files',[name,'.m']));\n  assert(strcmp(actual,expected));\n  method_names=methods(name);\n  assert(any(strcmp(method_names,'model_fun')));\n  printf('CLASS_OK %s %s\\n',name,actual);\nend\nprintf('@@KISS-OCTAVE-TOOLBOX-OK@@\\n');\n"


def classes_valid(names):
    if (not isinstance(names,list) or len(names)!=47 or len(set(names))!=47
        or any(not isinstance(n,str) or not re.fullmatch(r"m_[0-9]{2}_[A-Za-z0-9_]+",n) for n in names)
        or sorted(int(n[2:4]) for n in names)!=list(range(1,48))):
        raise ValueError("Octave contract requires each of the 47 MARRMoT model classes exactly once")


def packages_valid(packages):
    if not isinstance(packages,dict) or set(packages)!={"optim","statistics","struct"}:
        raise ValueError("Octave contract requires optim, statistics and struct versions")
    if any(not isinstance(v,str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+",v) for v in packages.values()):
        raise ValueError("invalid Octave package version")


def validate(c):
    keys={"runtime","source","package_registry_root","classes","source_files","packages"}
    if not isinstance(c,dict) or set(c)!=keys:
        raise ValueError("invalid Octave toolbox contract fields")
    classes_valid(c["classes"]); packages_valid(c["packages"])
    for k in ("runtime","source","package_registry_root"):
        p=Path(c[k])
        if p.anchor or ".." in p.parts or not p.parts:
            raise ValueError("Octave paths must be relative and contained in workspace")
    expected={"MARRMoT/Models/Model files/"+n+".m" for n in c["classes"]+["MARRMoT_model"]}
    if not isinstance(c["source_files"],dict) or set(c["source_files"])!=expected:
        raise ValueError("Octave source hashes must cover base class and all 47 model classes")
    if any(not isinstance(v,str) or not re.fullmatch(r"[0-9a-f]{64}",v) for v in c["source_files"].values()):
        raise ValueError("invalid Octave source SHA256")
    return c


def verify_source(source,c,root):
    for relative,expected in validate(c)["source_files"].items():
        p=scoped(source/relative,root,root)
        if source not in p.parents or not p.is_file() or p.stat().st_size>2_000_000:
            raise ValueError("Octave model source absent or escapes pinned tree")
        if hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise ValueError("Octave model source checksum mismatch: "+relative)


def probe_args(script,source,packages,c):
    validate(c)
    return FLAGS+[str(script),str(source),str(packages),",".join(c["classes"]),
                  ",".join(k+"="+v for k,v in sorted(c["packages"].items()))]


def guard(args,cwd,root):
    if args==["--version"]:
        return
    if len(args)!=9 or args[:4]!=FLAGS:
        raise ValueError("Octave permits only the fixed toolbox load probe")
    script=scoped(args[4],cwd,root)
    if not script.is_file() or script.stat().st_size>16000 or script.read_text()!=PROBE:
        raise ValueError("Octave probe script is not the exact trusted loader")
    scoped(args[5],cwd,root); scoped(args[6],cwd,root)
    classes_valid(args[7].split(","))
    pairs=[x.split("=") for x in args[8].split(",")]
    if len(pairs)!=3 or any(len(x)!=2 for x in pairs):
        raise ValueError("invalid Octave package version arguments")
    packages_valid(dict(pairs))
