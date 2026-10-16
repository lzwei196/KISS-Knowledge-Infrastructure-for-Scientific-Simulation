#!/usr/bin/env python3
"""
Generate the main ParFlow Python run script (pftools API) by rendering
workflow/run_script_template.py.fmt -- a template that follows the SHIPPED
CLM example (parflow source test/python/washita/LW_Test.py) key-for-key.

The previous version could not produce a runnable script: it violated the
KI's own validated triplets dt_pf_v001/v002/v003/v004, declared an undefined
geometry 'indicator_input', and its main() never forwarded subsurface/slope/
IC/forcing paths (all upstream stage products were silently ignored).

Soil heterogeneity: IndicatorField from s2 (texture_indicator.pfb +
texture_params.json). CLM forcing: MetForcing='3D' chunks from s5. Restart:
--start_time_hours + --ic_pfb <last dump> (CLM soil states restart cold --
crash recovery only). Mannings: hour time base => n in hr*m^(-1/3) = SI/3600.

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import glob
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime

# ParFlow install used as the generated script's PARFLOW_DIR default. It lives
# here (a .py, which the desktop port rewrites), never in the .fmt template.
# PARFLOW_DIR in the environment overrides it, at render time and at run time.
PARFLOW_INSTALL = "KISSPATH_BINARIES/parflow/install"


def resolve_parflow_dir(parflow_dir=None):
    """--parflow_dir, else $PARFLOW_DIR, else PARFLOW_INSTALL; must hold bin/parflow."""
    d = parflow_dir or os.environ.get("PARFLOW_DIR") or PARFLOW_INSTALL
    exe = os.path.join(d, "bin", "parflow")
    if not os.path.isfile(exe):
        raise FileNotFoundError(
            f"ParFlow install not found: {exe} does not exist. Pass --parflow_dir or set "
            f"PARFLOW_DIR to the ParFlow install folder (the one holding bin/parflow).")
    return os.path.abspath(d)


TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "..", "workflow", "run_script_template.py.fmt")

CLM_BLOCK = '''run.Solver.LSM = "CLM"
run.Solver.CLM.CLMFileDir = "."
run.Solver.CLM.Print1dOut = False
run.Solver.CLM.CLMDumpInterval = 24
run.Solver.CLM.MetForcing = "3D"
run.Solver.CLM.MetFileName = "{met_name}"
run.Solver.CLM.MetFilePath = "{met_path}"
run.Solver.CLM.MetFileNT = {met_nt}
run.Solver.CLM.IstepStart = {istep_start}
run.Solver.CLM.EvapBeta = "Linear"
run.Solver.CLM.VegWaterStress = "Saturation"
run.Solver.CLM.ResSat = 0.1
run.Solver.CLM.WiltingPoint = 0.12
run.Solver.CLM.FieldCapacity = 0.98
run.Solver.CLM.IrrigationType = "none"
run.Solver.PrintCLM = True
run.Solver.WriteCLMBinary = False'''


def process(domain_json, run_name, output_dir,
            start_date="2000-01-01", end_date="2010-12-31",
            dt_hours=1.0, dump_interval_hours=24,
            enable_clm=True, terrain_following=True, p=1, q=1, r=1,
            texture_params=None, indicator_pfb=None,
            slope_x_pfb=None, slope_y_pfb=None, ic_pfb=None,
            clm_dir=None, forcing_dir=None, met_name="NLDAS", met_nt=24,
            mannings_hr=1.0e-5, k_anisotropy=0.1, start_time_hours=0,
            nl_max_iter=300, eta_value=0.001, use_jacobian=True,
            derivative_epsilon=1e-16, krylov_dim=70,
            pc_matrix_type="FullJacobian", homogeneous_default_soil=False,
            parflow_dir=None):
    with open(domain_json) as f:
        grid = json.load(f)["grid"]
    nx, ny, nz = grid["nx"], grid["ny"], grid["nz"]
    dx, dy = grid["dx"], grid["dy"]
    dz_layers = grid["dz_layers_m"]
    total_depth = grid["total_depth_m"]
    dz0 = dz_layers[0]
    if any(abs(d - dz0) > 1e-9 for d in dz_layers):
        raise ValueError(
            "Non-uniform dz with Box geometry activates only the bottom layer "
            "(dt_pf_v005): regenerate the domain with uniform --dz_layers.")

    # Check all referenced inputs before creating/overwriting any run products.
    if (not run_name or run_name in (".", "..") or "/" in run_name or "\\" in run_name
            or (os.sep in run_name) or (os.altsep and os.altsep in run_name)):
        raise ValueError(f"run_name {run_name!r} must be a plain name (no path separators)")
    parflow_dir = resolve_parflow_dir(parflow_dir)
    required = [(ic_pfb, "ic_pfb", (nz, ny, nx)),
                (slope_x_pfb, "slope_x_pfb", (1, ny, nx)),
                (slope_y_pfb, "slope_y_pfb", (1, ny, nx))]
    if bool(texture_params) != bool(indicator_pfb):
        raise ValueError("texture_params and indicator_pfb must be supplied together")
    if not texture_params and not homogeneous_default_soil:
        # Without them the template's fixed domain soil (Perm 0.00104 m/h,
        # porosity 0.43, van Genuchten alpha 3.6 / n 1.56, SRes 0.18) would be
        # used for every cell. That must be an explicit choice.
        raise ValueError("texture_params and indicator_pfb (from s2) are required; pass "
                         "--homogeneous_default_soil to run the template's one fixed soil "
                         "everywhere (recorded in soil_provenance.json)")
    if indicator_pfb:
        required.append((indicator_pfb, "indicator_pfb", (nz, ny, nx)))
    for path, label, shape in required:
        if not path:
            raise ValueError(f"{label} is required; missing inputs have no fallback")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{label}: input file not found: {path}")
    import numpy as np
    from parflow.tools.io import read_pfb
    for path, label, shape in required:
        try:
            values = read_pfb(path)
        except Exception as exc:
            raise ValueError(f"{label}: cannot read PFB {path}: {exc}") from exc
        if values.shape != shape or not np.isfinite(values).all():
            raise ValueError(f"{label}: expected finite PFB of shape {shape}, got {values.shape}")
    clm_inputs = []
    if enable_clm:
        if not clm_dir:
            raise ValueError("clm_dir is required with CLM enabled")
        for fn in ("drv_clmin.dat", "drv_vegm.dat", "drv_vegp.dat"):
            src = os.path.join(clm_dir, fn)
            if not os.path.isfile(src) or os.path.getsize(src) == 0:
                raise FileNotFoundError(f"CLM driver file missing or empty: {src}")
            clm_inputs.append((src, fn))
        if not forcing_dir or not glob.glob(os.path.join(forcing_dir, f"{met_name}.*.pfb")):
            raise ValueError("forcing_dir must contain the requested CLM forcing PFB chunks")
        forcing_dir = os.path.abspath(forcing_dir)

    total_hours = int((datetime.strptime(end_date, "%Y-%m-%d")
                       - datetime.strptime(start_date, "%Y-%m-%d")).total_seconds() / 3600)
    if start_time_hours % dump_interval_hours != 0:
        raise ValueError("start_time_hours must be a multiple of dump_interval")
    istep_start = int(start_time_hours) + 1

    classes = {}
    if texture_params:
        with open(texture_params) as f:
            classes = {int(k): v for k, v in json.load(f).items()}
        if not classes:
            raise ValueError("texture_params must contain at least one soil class")
    for prm in classes.values():
        # ParFlow VanGenuchten SRes is a saturation FRACTION, not theta_r
        prm["sres_frac"] = round(prm["sres"] / max(prm["porosity"], 1e-6), 4)
    gnames = " ".join(f"c{c}" for c in sorted(classes))
    if classes:
        # Every indicator value must be a class; a cell with any other value
        # would silently get the template's domain soil instead.
        import numpy as np
        from parflow.tools.io import read_pfb
        raw = np.unique(np.asarray(read_pfb(indicator_pfb), dtype=np.float64))
        # Class ids are whole numbers; a value such as 1.49 is not class 1
        # and is never rounded to one.
        not_int = raw[~(np.isfinite(raw) & (raw == np.floor(raw)))]
        if not_int.size:
            raise ValueError(f"indicator_pfb has {not_int.size} distinct non-integer values "
                             f"(first {min(5, not_int.size)}: {not_int[:5].tolist()}); "
                             f"class ids must be whole numbers")
        ind = raw.astype(np.int64)
        unknown = sorted(set(ind.tolist()) - set(classes))
        if unknown:
            raise ValueError(f"indicator_pfb has values {unknown[:10]} with no class in "
                             f"texture_params (classes {sorted(classes)[:10]})")

    def per_class(*fmts):
        return "\n".join(f.format(c=c, **prm)
                         for c, prm in sorted(classes.items()) for f in fmts)

    indi = ""
    if classes:
        indi = ('run.GeomInput.indi_input.InputType = "IndicatorField"\n'
                f'run.GeomInput.indi_input.GeomNames = "{gnames}"\n'
                'run.Geom.indi_input.FileName = "texture_indicator.pfb"\n'
                + per_class('run.GeomInput.c{c}.Value = {c}'))

    slopes = "\n".join(f'run.TopoSlopes{a}.Type = "PFBFile"\n'
                           f'run.TopoSlopes{a}.GeomNames = "domain"\n'
                           f'run.TopoSlopes{a}.FileName = "slope_{a.lower()}.pfb"'
                           for a in ("X", "Y"))

    bcs = "\n".join(f'run.Patch.{pa}.BCPressure.Type = "FluxConst"\n'
                    f'run.Patch.{pa}.BCPressure.Cycle = "constant"\n'
                    f'run.Patch.{pa}.BCPressure.alltime.Value = 0.0'
                    for pa in ("left", "right", "front", "back", "bottom"))

    dist_files = (["texture_indicator.pfb"] if classes else []) + \
        (["slope_x.pfb", "slope_y.pfb"] if slope_x_pfb and slope_y_pfb else []) + \
        ["ic_pressure.pfb"]
    dist_block = "\n".join(f'run.dist(os.path.join(here, "{f}"))' for f in dist_files)
    if enable_clm and forcing_dir:
        dist_block += (
            f'\n_nsub = {p * q * r}'
            f'\nfor _f in sorted(glob.glob(os.path.join("{forcing_dir}", "{met_name}.*.pfb"))):'
            '\n    _d = _f + ".dist"'
            '\n    _ok = os.path.exists(_d) and sum(1 for _l in open(_d) if _l.strip()) == _nsub'
            '\n    if not _ok:'
            '\n        run.dist(_f)')

    clm = CLM_BLOCK.format(met_name=met_name, met_path=forcing_dir or ".",
                           met_nt=met_nt, istep_start=istep_start) if enable_clm else ""

    with open(TEMPLATE) as f:
        tmpl = f.read()
    # Six Newton-Krylov keys render from CLI flags. If the template still
    # hardcodes any of them (older revision), rewrite that line to the
    # placeholder before rendering, so the KINSol-stall fallback
    # (UseJacobian=False + PFSymmetric) is reachable with either template.
    _solver_lines = {
        "nl_max_iter": ("run.Solver.Nonlinear.MaxIter = 80",
                        "run.Solver.Nonlinear.MaxIter = {nl_max_iter}"),
        "eta_value": ("run.Solver.Nonlinear.EtaValue = 0.001",
                      "run.Solver.Nonlinear.EtaValue = {eta_value}"),
        "use_jacobian": ("run.Solver.Nonlinear.UseJacobian = True",
                         "run.Solver.Nonlinear.UseJacobian = {use_jacobian}"),
        "derivative_epsilon": (
            "run.Solver.Nonlinear.DerivativeEpsilon = 1e-16",
            "run.Solver.Nonlinear.DerivativeEpsilon = {derivative_epsilon}"),
        "krylov_dim": ("run.Solver.Linear.KrylovDimension = 70",
                       "run.Solver.Linear.KrylovDimension = {krylov_dim}"),
        "pc_matrix_type": (
            'run.Solver.Linear.Preconditioner.PCMatrixType = "FullJacobian"',
            'run.Solver.Linear.Preconditioner.PCMatrixType = "{pc_matrix_type}"'),
    }
    for _k, (_old, _new) in _solver_lines.items():
        if ("{%s}" % _k) in tmpl:
            continue
        if tmpl.count(_old) != 1:
            raise RuntimeError(
                "template exposes neither {%s} nor the line %r exactly once"
                " -- cannot render this solver key from flags" % (_k, _old))
        tmpl = tmpl.replace(_old, _new)
    script = tmpl.format(
            run_name=run_name, nx=nx, ny=ny, nz=nz, dx=dx, dy=dy, dz0=dz0,
            total_depth=total_depth, start_date=start_date, end_date=end_date,
            total_hours=total_hours, start_time_hours=start_time_hours,
            p=p, q=q, r=r,
            geominput_names="domain_input" + (" indi_input" if classes else ""),
            upper_x=nx * dx, upper_y=ny * dy, indi=indi, gnames=gnames,
            perm_classes=per_class('run.Geom.c{c}.Perm.Type = "Constant"',
                                   'run.Geom.c{c}.Perm.Value = {ks_m_hr}  # {name}'),
            k_anisotropy=k_anisotropy,
            start_count=int(start_time_hours // dump_interval_hours),
            start_time_f=float(start_time_hours), stop_time_f=float(total_hours),
            dump_interval_f=float(dump_interval_hours), dt_hours=dt_hours,
            porosity_classes=per_class('run.Geom.c{c}.Porosity.Type = "Constant"',
                                       'run.Geom.c{c}.Porosity.Value = {porosity}'),
            bcs=bcs, slopes=slopes, mannings_hr=mannings_hr,
            relperm_classes=per_class('run.Geom.c{c}.RelPerm.Alpha = {alpha_1m}',
                                      'run.Geom.c{c}.RelPerm.N = {n}'),
            saturation_classes=per_class('run.Geom.c{c}.Saturation.Alpha = {alpha_1m}',
                                         'run.Geom.c{c}.Saturation.N = {n}',
                                         'run.Geom.c{c}.Saturation.SRes = {sres_frac}',
                                         'run.Geom.c{c}.Saturation.SSat = 1.0'),
            clm=clm, tfg=terrain_following, dist_block=dist_block,
            nl_max_iter=nl_max_iter, eta_value=eta_value,
            use_jacobian=use_jacobian,
            derivative_epsilon=derivative_epsilon,
            krylov_dim=krylov_dim, pc_matrix_type=pc_matrix_type,
            parflow_dir_repr=repr(parflow_dir),
        )

    script_path = os.path.join(output_dir, f"run_{run_name}.py")
    compile(script, script_path, "exec")
    provenance = {"soil": "indicator classes from texture_params" if classes else
                  "HOMOGENEOUS template default (--homogeneous_default_soil): Perm 0.00104 m/h, "
                  "porosity 0.43, VG alpha 3.6, n 1.56, SRes 0.18 in every cell",
                  "texture_params": texture_params, "indicator_pfb": indicator_pfb,
                  "n_classes": len(classes)}

    # Stage the COMPLETE run (inputs under canonical names, provenance, script)
    # in a private folder next to output_dir. Nothing in output_dir changes
    # until every copy has succeeded; a failed copy leaves the old script,
    # inputs and provenance exactly as they were.
    out_abs = os.path.realpath(os.path.abspath(output_dir))
    parent = os.path.dirname(out_abs)
    os.makedirs(parent, exist_ok=True)
    stage = tempfile.mkdtemp(prefix="." + os.path.basename(out_abs) + ".staging_", dir=parent)
    staged = {}
    stage_keep = [False]
    try:
        names = []
        for src, dst in [(indicator_pfb, "texture_indicator.pfb"),
                         (slope_x_pfb, "slope_x.pfb"), (slope_y_pfb, "slope_y.pfb"),
                         (ic_pfb, "ic_pressure.pfb")] + clm_inputs:
            if src:
                if not os.path.isfile(src):
                    raise FileNotFoundError(f"Input file not found: {src}")
                shutil.copyfile(src, os.path.join(stage, dst))
                names.append(dst)
        with open(os.path.join(stage, "soil_provenance.json"), "w") as fh:
            json.dump(provenance, fh, indent=2)
        names.append("soil_provenance.json")
        with open(os.path.join(stage, os.path.basename(script_path)), "w") as fh:
            fh.write(script)
        os.chmod(os.path.join(stage, os.path.basename(script_path)), 0o755)
        names.append(os.path.basename(script_path))  # script is published LAST
        # Publish as one transaction: same-filesystem renames only. Each
        # existing target is first moved aside into the staging folder; if
        # any step fails, published files are removed and the old ones are
        # moved back, so output_dir ends exactly as it was.
        for nm in names:
            if os.path.isdir(os.path.join(out_abs, nm)):
                raise IsADirectoryError(f"cannot publish {nm}: {os.path.join(out_abs, nm)} is a folder")
        created_out = not os.path.isdir(out_abs)
        os.makedirs(out_abs, exist_ok=True)
        old_dir = os.path.join(stage, "_previous")
        os.mkdir(old_dir)
        moved_aside, published = [], []
        try:
            for nm in names:
                dst = os.path.join(out_abs, nm)
                if os.path.lexists(dst):
                    os.replace(dst, os.path.join(old_dir, nm))
                    moved_aside.append(nm)
                os.replace(os.path.join(stage, nm), dst)
                published.append(nm)
        except BaseException as exc:
            problems = []
            for nm in reversed(published):
                try:
                    os.unlink(os.path.join(out_abs, nm))
                except OSError as e:
                    problems.append(f"remove new {nm}: {e}")
            for nm in reversed(moved_aside):
                try:
                    os.replace(os.path.join(old_dir, nm), os.path.join(out_abs, nm))
                except OSError as e:
                    problems.append(f"restore old {nm}: {e}")
            if created_out and not problems:
                try:
                    os.rmdir(out_abs)
                except OSError:
                    pass
            if problems:
                # Keep the staging folder (it holds the old files) and say so.
                stage_keep[0] = True
                raise RuntimeError(
                    f"publishing the run into {out_abs} failed ({exc}) and the rollback was "
                    f"incomplete: {problems}. Old files are kept in {old_dir}.") from exc
            raise
        for nm in published:
            if nm.endswith(".pfb") or nm.startswith("drv_"):
                staged[nm] = os.path.join(output_dir, nm)
    finally:
        if not stage_keep[0]:
            shutil.rmtree(stage, ignore_errors=True)

    return {
        "status": "success", "run_script": script_path, "run_name": run_name,
        "grid": {"nx": nx, "ny": ny, "nz": nz, "dx": dx, "dy": dy, "dz": dz0},
        "total_depth_m": total_depth, "simulation_hours": total_hours,
        "start_time_hours": start_time_hours, "istep_start": istep_start,
        "expected_pressure_dumps": (total_hours - start_time_hours) // dump_interval_hours + 1,
        "mpi_topology": {"P": p, "Q": q, "R": r, "total_cores": p * q * r},
        "clm_enabled": enable_clm,
        "subsurface_classes": {c: v["name"] for c, v in classes.items()},
        "staged_inputs": staged,
        "parflow_dir": parflow_dir,
        "run_command": f"cd {output_dir} && python run_{run_name}.py",
    }


ARGS = [
    ("--domain_json", dict(required=True)),
    ("--run_name", dict(required=True)),
    ("--output_dir", dict(required=True)),
    ("--start_date", dict(default="2000-01-01")),
    ("--end_date", dict(default="2010-12-31")),
    ("--dt_hours", dict(type=float, default=1.0)),
    ("--dump_interval", dict(type=int, default=24)),
    ("--no_clm", dict(action="store_true")),
    ("--no_tfg", dict(action="store_true")),
    ("--p", dict(type=int, default=1)),
    ("--q", dict(type=int, default=1)),
    ("--r", dict(type=int, default=1)),
    ("--texture_params", dict(default=None, help="texture_params.json from s2")),
    ("--indicator_pfb", dict(default=None, help="texture_indicator.pfb from s2")),
    ("--slope_x_pfb", dict(default=None)),
    ("--slope_y_pfb", dict(default=None)),
    ("--ic_pfb", dict(default=None, help="initial (or restart) pressure PFB")),
    ("--clm_dir", dict(default=None, help="s4 output dir with drv_*.dat")),
    ("--forcing_dir", dict(default=None, help="s5 output dir with NLDAS chunks")),
    ("--met_name", dict(default="NLDAS")),
    ("--met_nt", dict(type=int, default=24)),
    ("--mannings_hr", dict(type=float, default=1.0e-5)),
    ("--k_anisotropy", dict(type=float, default=0.1)),
    ("--nl_max_iter", dict(type=int, default=300,
                           help="Solver.Nonlinear.MaxIter (docs/s7_solver_skill.md default)")),
    ("--eta_value", dict(type=float, default=0.001)),
    ("--use_jacobian", dict(choices=["true", "false"], default="true",
                            help="false = FD Jacobian-vector products (KINSol stall fallback)")),
    ("--derivative_epsilon", dict(type=float, default=1e-16)),
    ("--krylov_dim", dict(type=int, default=70)),
    ("--pc_matrix_type", dict(choices=["FullJacobian", "PFSymmetric"],
                              default="FullJacobian")),
    ("--homogeneous_default_soil", dict(action="store_true",
        help="explicitly run without texture inputs: the template's one fixed soil in "
             "every cell (recorded in soil_provenance.json)")),
    ("--parflow_dir", dict(default=None,
        help="ParFlow install folder (holds bin/parflow); default $PARFLOW_DIR, else the KI's "
             "install path. Written as the generated script's PARFLOW_DIR default.")),
    ("--start_time_hours", dict(type=int, default=0,
                                help="restart offset (multiple of dump_interval)")),
]


def main():
    ap = argparse.ArgumentParser(description="Generate ParFlow run script")
    for name, kw in ARGS:
        ap.add_argument(name, **kw)
    a = ap.parse_args()
    if not os.path.exists(a.domain_json):
        print(json.dumps({"status": "error",
                          "errors": [f"Domain definition not found: {a.domain_json}"]}))
        sys.exit(1)
    result = process(
        a.domain_json, a.run_name, a.output_dir, a.start_date, a.end_date,
        a.dt_hours, a.dump_interval, not a.no_clm, not a.no_tfg, a.p, a.q, a.r,
        texture_params=a.texture_params, indicator_pfb=a.indicator_pfb,
        slope_x_pfb=a.slope_x_pfb, slope_y_pfb=a.slope_y_pfb, ic_pfb=a.ic_pfb,
        clm_dir=a.clm_dir, forcing_dir=a.forcing_dir, met_name=a.met_name,
        met_nt=a.met_nt, mannings_hr=a.mannings_hr,
        k_anisotropy=a.k_anisotropy, start_time_hours=a.start_time_hours,
        nl_max_iter=a.nl_max_iter, eta_value=a.eta_value,
        use_jacobian=(a.use_jacobian == "true"),
        homogeneous_default_soil=a.homogeneous_default_soil,
        derivative_epsilon=a.derivative_epsilon, krylov_dim=a.krylov_dim,
        pc_matrix_type=a.pc_matrix_type, parflow_dir=a.parflow_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "error", "errors": [str(exc)]}), file=sys.stderr)
        sys.exit(1)
