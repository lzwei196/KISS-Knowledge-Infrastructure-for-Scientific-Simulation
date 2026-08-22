"""calibration_kit — model-agnostic calibration for the self-improve KI engine.

A SIBLING module to the self-improve KI: the loop makes a model RUN CORRECTLY;
this kit tunes its PARAMETERS to fit the dag-defined obs. Data assimilation
(sequential state estimation) is a separate sibling, not part of this module.

Public entry: calib.calibrate(ki_path, workdir, run_model, obs_shape_by_var, ...).
See CALIBRATION_YAML_SCHEMA.md for the per-model contract and README.md for design.
"""
from . import objectives, applicator, calib  # noqa: F401
