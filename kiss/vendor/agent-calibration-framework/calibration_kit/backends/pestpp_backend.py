"""PEST++ / pyEMU backend — regularized / high-dimensional / ensemble inversion.

Use for highly-parameterized inverse problems (groundwater/MODFLOW, distributed
hydro): `pestpp-glm` for deterministic regularized inversion, `pestpp-ies` for
iterative ensemble smoothing when parameter dimension is high.

NOTE — different integration model. PEST++ drives the model itself via template
(.tpl) + instruction (.ins) files and a forward-run script; it does NOT consume our
in-process Problem.evaluate() loop. So this backend builds a pyEMU `Pst` from the
calibration.yaml addresses (params) + the runner (forward-run command) + the obs,
then shells out to the pestpp binary. It therefore needs BOTH `pyemu` AND a
`pestpp-*` binary on PATH (the binaries are distributed separately from pyemu).

STATUS: availability + control-file scaffolding wired; the .tpl/.ins generation from
`address` semantics is the integration seam to complete per model class. Until then
optimize() raises a clear error rather than silently doing nothing.
"""
from __future__ import annotations
import shutil
from .base import Backend, Problem, CalibResult


class PestppBackend(Backend):
    name = "pestpp"

    def __init__(self, variant: str = "ies"):
        self.variant = variant          # ies | glm
        self.binary = f"pestpp-{variant}"

    def available(self) -> bool:           # instance method (depends on chosen binary)
        import importlib.util as u
        return u.find_spec("pyemu") is not None and shutil.which(self.binary) is not None

    @staticmethod
    def library_present() -> bool:
        import importlib.util as u
        return u.find_spec("pyemu") is not None

    def optimize(self, problem: Problem, budget: int, seed: int = 0,
                 contract: dict | None = None, ki_path: str | None = None,
                 workdir: str | None = None, runner_cmd=None, **kw) -> CalibResult:
        import importlib.util as u
        if u.find_spec("pyemu") is None:
            return CalibResult(best_x=[], best_loss=[float("inf")], backend=f"pestpp:{self.variant}",
                               notes="pyemu not installed")
        if shutil.which(self.binary) is None:
            return CalibResult(best_x=[], best_loss=[float("inf")], backend=f"pestpp:{self.variant}",
                               notes=f"{self.binary} binary not on PATH (PEST++ binaries are "
                                     f"distributed separately from pyemu)")
        # --- integration seam (to complete) -------------------------------------
        # import pyemu
        # 1) write a .tpl per parameter file using the address tokens (the inverse of
        #    applicator.write_param: mark the value's span with the PEST template
        #    delimiter so pestpp writes candidate values there).
        # 2) write a .ins to read the model output the runner produces.
        # 3) pst = pyemu.Pst.from_io_files(tpls, inputs, inss, outputs)
        #    set parameter bounds/transforms from contract['parameters'];
        #    set pst.model_command = runner_cmd; set ++ies/glm options + noptmax.
        # 4) pst.write(...); subprocess.run([self.binary, pst_path], cwd=workdir)
        # 5) parse the best phi / posterior ensemble -> CalibResult.
        raise NotImplementedError(
            "PestppBackend.optimize: control-file scaffolding present; the .tpl/.ins "
            "generation from `address` semantics is the per-model-class seam to finish "
            "(see inline plan). Binary + pyemu are available in this env.")
