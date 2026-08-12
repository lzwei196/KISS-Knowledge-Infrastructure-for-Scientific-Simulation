"""
MARRMoT Execution Wrapper
==========================
Run a MARRMoT model via GNU Octave subprocess. Generates an Octave script
from the forcing CSV + parameter JSON, executes it, and captures output.

CRITICAL: Requires GNU Octave with optim package installed.
  The wrapper generates a temporary .m script and runs it via `octave --eval`.

CRITICAL: delta_t must be 1 for daily data. If delta_t does not match
  the forcing timestep, all fluxes will be scaled incorrectly (dt_009).

CRITICAL: S0 vector length must equal the model's numStores. Too few
  elements cause an index error; too many are silently ignored (dt_012).

Usage:
  python run_marrmot.py --forcing forcing.csv \
    --model m_29_hymod_5p_5s \
    --params params.json \
    --output run_output.json

  python run_marrmot.py --forcing forcing.csv \
    --model m_01_collie1_1p_1s \
    --theta "[100]" --s0 "[0]" \
    --output run_output.json
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import re

import numpy as np

# Directory holding KI-local Octave shims (e.g. an lsqnonlin.m that wraps core
# fsolve for installs without the Octave-Forge optim package). Added to the
# Octave path AFTER the MARRMoT genpath so MARRMoT's solver cascade still works
# when optim cannot be installed offline. See diagnostics dt_marrmot_no_optim.
SHIM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "octave_shims")

# Octave shims materialised into the RUN DIRECTORY at execution time (as opposed
# to the checked-in ones in SHIM_DIR). Same pattern as OF_PERSIST_SHIM below:
# the .m source lives in this file and is written next to the run outputs, which
# every generated script puts on the Octave path.
NORMCDF_SHIM = r"""function p = normcdf(x, mu, sigma)
% NORMCDF  Minimal drop-in shim for MARRMoT on a GNU Octave install that lacks
%          the Octave-Forge `statistics` package (which normally provides
%          normcdf). Same rationale as the lsqnonlin shim: this box has no
%          reachable packages.octave.org, so statistics cannot be fetched.
%
%   Blast radius: exactly one MARRMoT flux function, `saturation_13`
%   (saturation-excess flow from a store with a lognormal distribution of
%   contributing area), used by exactly one structure, m_42_hycymodel_12p_6s.
%   Without this shim m_42 dies on its FIRST objective evaluation with
%   "'normcdf' undefined", so the structure cannot be calibrated at all -- it
%   silently drops out of any multi-structure comparison.
%
%   The standard normal CDF is an exact expression in the complementary error
%   function, which IS core Octave:
%       Phi(z) = 0.5 * erfc(-z / sqrt(2))
%   so this is a mathematically exact substitute, not an approximation.
%   Vectorised and NaN-preserving, matching the reference normcdf.
%
%   Signatures supported (all MARRMoT needs is the first):
%       normcdf(x)              standard normal, mu=0, sigma=1
%       normcdf(x, mu, sigma)   general normal
%
%   Documented in diagnostics/triplets.yaml (dt_020).
    if nargin < 2 || isempty(mu);    mu    = 0; end
    if nargin < 3 || isempty(sigma); sigma = 1; end

    z = (x - mu) ./ sigma;
    p = 0.5 * erfc(-z ./ sqrt(2));

    % sigma <= 0 is undefined for a normal distribution; the reference
    % implementation returns NaN rather than a silently wrong probability.
    bad = ~(sigma > 0);
    if any(bad(:))
        p(bad) = NaN;
    end
end
"""


def _octave_has(func_name):
    """True if `func_name` resolves in this Octave install (probe, fail-safe).

    A probe failure returns False so the caller writes the shim: the shims are
    exact substitutes, so an unnecessary one is harmless, whereas a missing one
    kills the run.
    """
    try:
        probe = subprocess.run(
            ["octave", "--no-gui", "--no-window-system", "--eval",
             f"exit(exist('{func_name}') > 0)"],
            capture_output=True, text=True, timeout=30)
        return probe.returncode != 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def materialize_runtime_shims(output_dir):
    """Write run-directory Octave shims for functions this install lacks.

    Every generated script addpath()s the run directory, so anything dropped
    here is visible to MARRMoT without shipping extra files in the KI tree.
    """
    written = []
    if not _octave_has("normcdf"):
        with open(os.path.join(output_dir, "normcdf.m"), "w") as f:
            f.write(NORMCDF_SHIM)
        written.append("normcdf.m")
    return written


def validate_inputs(args):
    """Validate inputs before building Octave script."""
    errors = []

    if not os.path.isfile(args.forcing):
        errors.append(f"Forcing file not found: {args.forcing}")

    if args.params and not os.path.isfile(args.params):
        errors.append(f"Parameter file not found: {args.params}")

    if not args.calibrate and not args.params and not args.theta:
        errors.append("Either --params (JSON) or --theta must be provided")

    if args.calibrate:
        if not args.observed or not os.path.isfile(args.observed):
            errors.append("--calibrate requires --observed <obs_q.csv>")
        if not args.model:
            errors.append("--calibrate requires --model")

    if args.marrmot_path and not os.path.isdir(args.marrmot_path):
        errors.append(f"MARRMoT path not found: {args.marrmot_path}")

    # Check Octave is available
    try:
        result = subprocess.run(["octave", "--version"],
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            errors.append("Octave not found or not working")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        errors.append("GNU Octave not installed or not in PATH")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def load_params(args):
    """Load model parameters from JSON file or CLI args."""
    if args.params:
        with open(args.params) as f:
            pdata = json.load(f)
        theta = pdata.get("theta", [])
        s0 = pdata.get("S0", [])
        model = pdata.get("model", args.model)
    else:
        theta = json.loads(args.theta)
        s0 = json.loads(args.s0) if args.s0 else []
        model = args.model

    return model, theta, s0


def build_octave_script(forcing_csv, model_name, theta, s0,
                        marrmot_path, delta_t, output_csv,
                        solver_tol, solver_maxiter):
    """
    Generate an Octave .m script that:
    1. Loads forcing data from CSV
    2. Creates model object
    3. Sets parameters, forcing, initial conditions
    4. Runs the model
    5. Writes outputs to CSV
    """
    theta_str = "[" + ", ".join(str(t) for t in theta) + "]"

    if s0:
        s0_str = "[" + ", ".join(str(s) for s in s0) + "]"
    else:
        s0_str = "zeros(1, m.numStores)"

    shim_dir = SHIM_DIR

    script = f"""\
% Auto-generated MARRMoT run script
% Do not edit -- generated by run_marrmot.py

% Add MARRMoT to path
addpath(genpath('{marrmot_path}'));
% KI-local Octave shims (provides lsqnonlin via fsolve when optim is absent).
% Prepended so it shadows nothing in MARRMoT but covers the missing function.
addpath('{shim_dir}');
% Run directory: holds shims materialised at execution time (see
% materialize_runtime_shims in run_marrmot.py, e.g. normcdf for m_42).
kdt_rundir = fileparts('{output_csv}');
if ~isempty(kdt_rundir); addpath(kdt_rundir); end

% Load optim package (Octave)
try
    pkg load optim;
catch
end

% Read forcing CSV (skip header lines starting with #)
fid = fopen('{forcing_csv}', 'r');
header_lines = 0;
while true
    line = fgetl(fid);
    if line(1) == '#'
        header_lines = header_lines + 1;
    else
        header_lines = header_lines + 1;  % column header
        break;
    end
end
fclose(fid);

data = csvread('{forcing_csv}', header_lines, 1);
% data columns: P, Ep, T (columns 2,3,4 after date)
P  = data(:, 1);
Ep = data(:, 2);
T  = data(:, 3);

fprintf('Loaded %d timesteps of forcing data\\n', length(P));
fprintf('P mean: %.2f mm/d, Ep mean: %.2f mm/d, T mean: %.2f C\\n', ...
    mean(P), mean(Ep), mean(T));

% Create model
m = feval('{model_name}');
fprintf('Model: %s (%d params, %d stores)\\n', ...
    '{model_name}', m.numParams, m.numStores);

% Set parameters
m.theta = {theta_str};

% Set forcing: [P, Ep, T] -- CRITICAL: this column order!
m.input_climate = [P, Ep, T];
m.delta_t = {delta_t};

% Set initial conditions
m.S0 = {s0_str};

% Solver options
m.solver_opts.resnorm_tolerance = {solver_tol};
m.solver_opts.resnorm_maxiter = {solver_maxiter};

% Run model
fprintf('Running model...\\n');
[fluxOutput, fluxInternal, storeInternal, waterBalance] = m.get_output();
fprintf('Model run complete.\\n');

% Extract total outflow Q (mm/d) and actual ET
% MARRMoT v2 returns structs; v1 returned matrices. Handle both.
if isstruct(fluxOutput)
    Q = fluxOutput.Q;
    if isfield(fluxOutput, 'Ea')
        Ea = fluxOutput.Ea;
    else
        Ea = zeros(length(Q), 1);
    end
else
    Q = fluxOutput(:, 1);
    if size(fluxOutput, 2) > 1
        Ea = fluxOutput(:, 2);
    else
        Ea = zeros(size(Q));
    end
end
% Ensure column vectors
Q = Q(:);
Ea = Ea(:);

% Write output CSV
% Include per-store storage columns S1..Sn (from m.stores, a t x numStores
% matrix populated by run/get_output). SKILL.md's Output Description promises
% storage columns; they are required to compute delta-storage for the
% post-run water-balance closure check. Downstream tools read Q_mm_d/Ea_mm_d
% by column name, so appending S* columns is backward-compatible.
S = m.stores;
if isempty(S); nS = 0; else; nS = size(S, 2); end
fid = fopen('{output_csv}', 'w');
fprintf(fid, 'timestep,Q_mm_d,Ea_mm_d');
for j = 1:nS; fprintf(fid, ',S%d', j); end
fprintf(fid, '\\n');
for i = 1:length(Q)
    fprintf(fid, '%d,%.6f,%.6f', i, Q(i), Ea(i));
    for j = 1:nS; fprintf(fid, ',%.6f', S(i, j)); end
    fprintf(fid, '\\n');
end
fclose(fid);
fprintf('Output written to {output_csv}\\n');

% Print water balance
fprintf('Water balance: %.4f mm\\n', waterBalance);

% Print summary stats
fprintf('SUMMARY_JSON_START\\n');
fprintf('{{"status":"success","n_timesteps":%d,"Q_mean":%.6f,"Q_max":%.6f,"Ea_mean":%.6f,"water_balance":%.6f}}\\n', ...
    length(Q), mean(Q), max(Q), mean(Ea), waterBalance);
fprintf('SUMMARY_JSON_END\\n');
"""
    return script


def build_calibration_script(forcing_csv, obs_csv, model_name, marrmot_path,
                             delta_t, output_json, n_samples, seed,
                             cal_start, cal_end, solver_tol, solver_maxiter,
                             lb=None, ub=None):
    """Generate an Octave script that runs Monte-Carlo calibration of the REAL
    MARRMoT model.

    Implements pipeline Stage 8 ("run_marrmot.py loop -- Monte Carlo parameter
    optimisation"). Samples ``n_samples`` parameter vectors uniformly from the
    model's own ``parRanges``, runs the real model for each within a single
    Octave session (fast -- no per-sample process startup), and scores each by
    NSE against observed streamflow over the calibration window
    [cal_start, cal_end] (1-based row indices into the forcing/obs series; the
    pre-cal rows act as spin-up and are excluded from scoring). Writes the best
    theta and its calibration NSE to ``output_json``.
    """
    shim_dir = SHIM_DIR
    script = f"""\
% Auto-generated MARRMoT Monte-Carlo calibration script
addpath(genpath('{marrmot_path}'));
addpath('{shim_dir}');  % KI-local lsqnonlin shim (optim package absent)
% Run directory: execution-time shims (materialize_runtime_shims).
kdt_rundir = fileparts('{output_json}');
if ~isempty(kdt_rundir); addpath(kdt_rundir); end
try
    pkg load optim;
catch
end

% --- Load forcing (skip comment + header lines) ---
fid = fopen('{forcing_csv}', 'r');
header_lines = 0;
while true
    line = fgetl(fid);
    if line(1) == '#'
        header_lines = header_lines + 1;
    else
        header_lines = header_lines + 1;
        break;
    end
end
fclose(fid);
data = csvread('{forcing_csv}', header_lines, 1);
P  = data(:, 1); Ep = data(:, 2); T = data(:, 3);

% --- Load observed Q (mm/d): date,Q_mm_d -> read col 1 (0-based offset) ---
Qobs = csvread('{obs_csv}', 1, 1);
Qobs = Qobs(:);

% --- Model + parameter ranges ---
m = feval('{model_name}');
pr = m.parRanges;
np = m.numParams;
% Optional tightened sampling bounds (avoid pathological stiff-solver regions
% that can hang/OOM the implicit Euler fsolve on extreme parameter draws).
lb_ovr = {('[' + ', '.join(str(x) for x in lb) + ']') if lb else '[]'};
ub_ovr = {('[' + ', '.join(str(x) for x in ub) + ']') if ub else '[]'};
if ~isempty(lb_ovr); pr(:,1) = max(pr(:,1), lb_ovr(:)); end
if ~isempty(ub_ovr); pr(:,2) = min(pr(:,2), ub_ovr(:)); end
m.input_climate = [P, Ep, T];
m.delta_t = {delta_t};
m.S0 = zeros(1, m.numStores);
m.solver_opts.resnorm_tolerance = {solver_tol};
m.solver_opts.resnorm_maxiter = {solver_maxiter};

rand('seed', {seed});
cs = {cal_start}; ce = {cal_end};
obs_cal = Qobs(cs:ce);
% Mask non-finite obs (NaN/Inf) so seasonal/gappy HYDAT records (e.g. prairie
% stations that only gauge Mar-Oct) do not poison the NSE -- without this every
% sample's NSE is NaN and calibration silently returns the prior bound.
obs_valid = isfinite(obs_cal);
obs_cal_v = obs_cal(obs_valid);
obs_mean = mean(obs_cal_v);
denom = sum((obs_cal_v - obs_mean).^2);

best_nse = -Inf; best_theta = pr(:,1)';
for i = 1:{n_samples}
    theta = pr(:,1)' + rand(1, np) .* (pr(:,2)' - pr(:,1)');
    m.theta = theta;
    try
        out = m.get_output();
        Qsim = out.Q(:);
    catch
        continue;
    end
    if length(Qsim) < ce, continue; end
    sim_cal = Qsim(cs:ce);
    sim_cal_v = sim_cal(obs_valid);
    if any(~isfinite(sim_cal_v)), continue; end
    nse = 1 - sum((obs_cal_v - sim_cal_v).^2) / denom;
    if nse > best_nse
        best_nse = nse;
        best_theta = theta;
        fprintf('[%d] NEW BEST cal_NSE=%.4f theta=[%s]\\n', i, nse, ...
                sprintf('%.3f ', theta));
        % Persist incrementally so a wall-clock timeout still yields the best
        % theta found so far (the per-sample implicit-Euler solve is slow, so
        % long calibrations are routinely killed before the loop completes).
        fid = fopen('{output_json}', 'w');
        fprintf(fid, '{{"model":"{model_name}","cal_nse":%.6f,"theta":[', best_nse);
        for k = 1:np
            if k < np; fprintf(fid, '%.6f,', best_theta(k));
            else; fprintf(fid, '%.6f', best_theta(k)); end
        end
        fprintf(fid, ']}}\\n');
        fclose(fid);
    end
end

% --- Write best theta JSON ---
fid = fopen('{output_json}', 'w');
fprintf(fid, '{{"model":"{model_name}","cal_nse":%.6f,"theta":[', best_nse);
for k = 1:np
    if k < np
        fprintf(fid, '%.6f,', best_theta(k));
    else
        fprintf(fid, '%.6f', best_theta(k));
    end
end
fprintf(fid, ']}}\\n');
fclose(fid);
fprintf('CALIBRATION_DONE best_cal_NSE=%.4f\\n', best_nse);
"""
    return script


OF_PERSIST_SHIM = r"""function f = kdt_of_persist(Q_obs, Q_sim, idx, varargin)
% KDT incremental-persistence wrapper around a MARRMoT of_* objective.
%
% MARRMoT_model.calibrate() only returns par_opt when my_cmaes finishes, so the
% caller's best_theta.json was written ONLY at the very end of the search. Any
% wall-clock cap (--timeout) therefore threw away a perfectly good incumbent --
% fatal for the expensive >=5-store structures (m_37 hbv ~50 s/eval), which are
% exactly the ones that cannot finish their eval budget. The Monte-Carlo path
% already persisted incrementally (build_calibration_script); this gives CMA-ES
% the same protection.
%
% calibrate() builds its fitness as (-1)^inverse_flag * feval(of_name, ...), and
% obj.run() assigns obj.theta before each evaluation, so the live candidate is
% readable from the (handle-class) model object via a global. We track the raw
% OF (higher = better for NSE/KGE families) and rewrite best_theta.json on every
% improvement, via a tmp+rename so a kill can never leave a half-written file.
global KDT_OF_NAME KDT_MODEL KDT_BEST_OF KDT_BEST_FILE KDT_MODEL_NAME

f = feval(KDT_OF_NAME, Q_obs, Q_sim, idx, varargin{:});

if isfinite(f) && (isempty(KDT_BEST_OF) || f > KDT_BEST_OF)
    KDT_BEST_OF = f;
    th = KDT_MODEL.theta;
    np = numel(th);
    tmp = [KDT_BEST_FILE '.tmp'];
    fid = fopen(tmp, 'w');
    if fid < 0; return; end
    fprintf(fid, '{"model":"%s","of_name":"%s","cal_of":%.6f,"partial":true,"theta":[', ...
            KDT_MODEL_NAME, KDT_OF_NAME, f);
    for k = 1:np
        if k < np
            fprintf(fid, '%.6f,', th(k));
        else
            fprintf(fid, '%.6f', th(k));
        end
    end
    fprintf(fid, ']}\n');
    fclose(fid);
    rename(tmp, KDT_BEST_FILE);
end
end
"""


def build_cmaes_calibration_script(forcing_csv, obs_csv, model_name, marrmot_path,
                                   delta_t, output_json, seed,
                                   cal_start, cal_end, solver_tol, solver_maxiter,
                                   of_name="of_KGE", max_fun_evals=2500,
                                   restarts=0, lb=None, ub=None):
    """Generate an Octave script that calibrates the REAL MARRMoT model with the
    toolbox's built-in CMA-ES optimiser via ``MARRMoT_model.calibrate``.

    This is the optimiser MARRMoT itself ships and documents (see
    ``Functions/Optimisation functions/my_cmaes.m`` and
    ``User manual/Examples/workflow_example_4.m``). Unlike the uniform
    Monte-Carlo sampler in ``build_calibration_script`` -- which is hopeless in
    >6 dimensions because the good region of parRanges is an exponentially small
    fraction of the hypercube -- CMA-ES adapts a covariance matrix and converges
    on the optimum even for the 15-parameter snow+soil+GW structures (m_37 hbv,
    m_33 sacramento). The objective is computed by a MARRMoT ``of_*`` function
    over ``cal_idx`` = [cal_start, cal_end]; ``check_and_select`` natively drops
    NaN / negative obs, so seasonal/gappy HYDAT records (e.g. prairie creeks
    gauged only Mar-Oct) need no extra masking. inverse_flag=1 so CMA-ES
    minimises -OF (KGE/NSE are maximised).
    """
    shim_dir = SHIM_DIR
    lb_str = ('[' + ', '.join(str(x) for x in lb) + ']') if lb else '[]'
    ub_str = ('[' + ', '.join(str(x) for x in ub) + ']') if ub else '[]'
    script = f"""\
% Auto-generated MARRMoT CMA-ES calibration script (MARRMoT_model.calibrate)
addpath(genpath('{marrmot_path}'));
addpath('{shim_dir}');
try
    pkg load optim;
catch
end

% --- Load forcing (skip comment + header lines) ---
fid = fopen('{forcing_csv}', 'r');
header_lines = 0;
while true
    line = fgetl(fid);
    if line(1) == '#'
        header_lines = header_lines + 1;
    else
        header_lines = header_lines + 1;
        break;
    end
end
fclose(fid);
data = csvread('{forcing_csv}', header_lines, 1);
P  = data(:, 1); Ep = data(:, 2); T = data(:, 3);

% --- Load observed Q (mm/d); NaN gaps preserved (csvread parses 'NaN') ---
Qobs = csvread('{obs_csv}', 1, 1);
Qobs = Qobs(:);

% --- Model + parameter ranges ---
m = feval('{model_name}');
np = m.numParams;
pr = m.parRanges;
lb_ovr = {lb_str};
ub_ovr = {ub_str};
if ~isempty(lb_ovr); pr(:,1) = max(pr(:,1), lb_ovr(:)); end
if ~isempty(ub_ovr); pr(:,2) = min(pr(:,2), ub_ovr(:)); end

m.input_climate = [P, Ep, T];
m.delta_t = {delta_t};
m.S0 = zeros(1, m.numStores);
m.solver_opts.resnorm_tolerance = {solver_tol};
m.solver_opts.resnorm_maxiter = {solver_maxiter};

% --- CMA-ES options (mirrors workflow_example_4.m) ---
optim_opts.insigma  = .3*(pr(:,2) - pr(:,1));
optim_opts.LBounds  = pr(:,1);
optim_opts.UBounds  = pr(:,2);
optim_opts.PopSize  = 4 + floor(3*log(np));
optim_opts.TolX       = 1e-7 * min(optim_opts.insigma);
optim_opts.TolFun     = 1e-7;
optim_opts.TolHistFun = 1e-7;
optim_opts.MaxFunEvals = {max_fun_evals};
% IPOP-CMA-ES: restart with a doubled population when a run stalls. Essential
% for the rugged, multi-modal objective surfaces of conceptual hydrology models
% (a single mean-start run gets trapped in a local optimum -- observed here:
% mean-start NSE 0.199 vs a broader search's 0.30+). MaxFunEvals caps the total
% evaluation budget ACROSS restarts (counteval is global in my_cmaes).
optim_opts.Restarts   = {restarts};
optim_opts.IncPopSize = 2;
optim_opts.SaveVariables = 'off';   % avoid .mat write (crashes under Octave)
optim_opts.LogModulo  = 0;          % no on-disk cmaes log files
optim_opts.EvalParallel = false;
optim_opts.Seed = {seed};

par_ini = mean(pr, 2);
cal_idx = ({cal_start}:{cal_end})';
of_name = '{of_name}';

% --- Incremental persistence of the CMA-ES incumbent (kdt_of_persist shim) ---
% Without this, best_theta.json appears only after my_cmaes returns, so any
% wall-clock cap discards the whole search. See OF_PERSIST_SHIM in run_marrmot.py.
addpath(fileparts('{output_json}'));
global KDT_OF_NAME KDT_MODEL KDT_BEST_OF KDT_BEST_FILE KDT_MODEL_NAME
KDT_OF_NAME   = of_name;
KDT_MODEL     = m;
KDT_BEST_OF   = [];
KDT_BEST_FILE = '{output_json}';
KDT_MODEL_NAME = '{model_name}';
of_call = 'kdt_of_persist';

fprintf('CMA-ES calibrating %s (%d params) on idx %d-%d, OF=%s\\n', ...
        '{model_name}', np, {cal_start}, {cal_end}, of_name);

% KGE-family objective functions take a 3-element component-weight vector as a
% trailing argument; NSE-family (of_NSE, of_log_NSE, of_inverse_NSE) take none.
% Passing weights to an NSE objective errors with "too many inputs".
if ~isempty(strfind(of_name, 'KGE'))
    [par_opt, of_cal, stopflag, output] = m.calibrate( ...
        Qobs, cal_idx, 'my_cmaes', par_ini, optim_opts, of_call, 1, 1, [1,1,1]);
else
    [par_opt, of_cal, stopflag, output] = m.calibrate( ...
        Qobs, cal_idx, 'my_cmaes', par_ini, optim_opts, of_call, 1, 1);
end

% --- Write best theta JSON ---
fid = fopen('{output_json}', 'w');
fprintf(fid, '{{"model":"{model_name}","of_name":"{of_name}","cal_of":%.6f,"theta":[', of_cal);
for k = 1:np
    if k < np
        fprintf(fid, '%.6f,', par_opt(k));
    else
        fprintf(fid, '%.6f', par_opt(k));
    end
end
fprintf(fid, ']}}\\n');
fclose(fid);
fprintf('CALIBRATION_DONE best_cal_OF=%.4f\\n', of_cal);
"""
    return script


def process_calibrate(args):
    """Calibration driver (Stage 8): uniform Monte-Carlo or built-in CMA-ES."""
    model_name = args.model
    marrmot_path = _resolve_marrmot_path(args.marrmot_path)
    if marrmot_path is None:
        return {"status": "error",
                "errors": ["Cannot find MARRMoT source directory"]}

    output_dir = os.path.dirname(args.output) or "."
    os.makedirs(output_dir, exist_ok=True)
    materialize_runtime_shims(output_dir)
    best_json = os.path.join(output_dir, "best_theta.json")

    if args.optimizer == "cmaes":
        script = build_cmaes_calibration_script(
            forcing_csv=os.path.abspath(args.forcing),
            obs_csv=os.path.abspath(args.observed),
            model_name=model_name,
            marrmot_path=os.path.abspath(marrmot_path),
            delta_t=args.delta_t,
            output_json=os.path.abspath(best_json),
            seed=args.seed,
            cal_start=args.cal_start,
            cal_end=args.cal_end,
            solver_tol=args.solver_tol,
            solver_maxiter=args.solver_maxiter,
            of_name=args.of_name,
            max_fun_evals=args.max_fun_evals,
            restarts=args.restarts,
            lb=json.loads(args.lb) if args.lb else None,
            ub=json.loads(args.ub) if args.ub else None,
        )
    else:
        script = build_calibration_script(
            forcing_csv=os.path.abspath(args.forcing),
            obs_csv=os.path.abspath(args.observed),
            model_name=model_name,
            marrmot_path=os.path.abspath(marrmot_path),
            delta_t=args.delta_t,
            output_json=os.path.abspath(best_json),
            n_samples=args.n_samples,
            seed=args.seed,
            cal_start=args.cal_start,
            cal_end=args.cal_end,
            solver_tol=args.solver_tol,
            solver_maxiter=args.solver_maxiter,
            lb=json.loads(args.lb) if args.lb else None,
            ub=json.loads(args.ub) if args.ub else None,
        )
    if args.optimizer == "cmaes":
        # The objective shim must sit on the Octave path next to best_theta.json.
        with open(os.path.join(output_dir, "kdt_of_persist.m"), "w") as f:
            f.write(OF_PERSIST_SHIM)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".m", delete=False,
                                     dir=output_dir) as f:
        f.write(script)
        script_path = f.name

    if args.optimizer == "cmaes":
        print(f"CMA-ES calibrating {model_name} (OF={args.of_name}, "
              f"max_fun_evals={args.max_fun_evals})...", file=sys.stderr)
    else:
        print(f"Calibrating {model_name} with {args.n_samples} samples...",
              file=sys.stderr)
    timed_out = False
    try:
        result = subprocess.run(
            ["octave", "--no-gui", "--no-window-system", script_path],
            capture_output=True, text=True, timeout=args.timeout, cwd=output_dir)
        print(result.stdout[-1500:], file=sys.stderr)
    except subprocess.TimeoutExpired as exc:
        # A wall-clock cap is a NORMAL outcome for the expensive (>=5-store)
        # structures, not an error: both optimisers persist their incumbent to
        # best_theta.json, so fall through and return that partial result rather
        # than letting TimeoutExpired escape and discard hours of search.
        timed_out = True
        result = subprocess.CompletedProcess(
            exc.cmd, -1,
            stdout=(exc.stdout or b"").decode("utf-8", "replace")
            if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            stderr=(exc.stderr or b"").decode("utf-8", "replace")
            if isinstance(exc.stderr, bytes) else (exc.stderr or ""))
        print(f"Octave calibration hit the {args.timeout}s wall-clock cap; "
              f"returning the best theta persisted so far.", file=sys.stderr)
    # A single pathological parameter sample (e.g. tiny Smax -> stiff ODE) can make
    # Octave attempt a huge transient allocation; the kernel OOM-killer then sends
    # SIGKILL (returncode -9), which the per-sample try/catch CANNOT trap. The MC
    # loop persists the best theta found so far to best_json on every improvement
    # (see build_calibration_script), so a kill mid-search still leaves a usable
    # result on disk. Only treat the run as a hard error if NO valid theta survived.
    partial = result.returncode != 0
    best = None
    if os.path.exists(best_json):
        try:
            with open(best_json) as f:
                cand = json.load(f)
            if isinstance(cand.get("theta"), list) and len(cand["theta"]) > 0:
                best = cand
        except (json.JSONDecodeError, OSError):
            best = None
    if best is None:
        if partial:
            print(result.stderr[-1500:], file=sys.stderr)
        return {"status": "error", "model": model_name,
                "errors": [f"Octave exit {result.returncode}",
                           result.stderr[:500]]}
    try:
        os.unlink(script_path)
    except OSError:
        pass
    res = {"status": "partial" if partial else "success",
           "model": model_name,
           "optimizer": args.optimizer,
           "best_theta_json": best_json,
           "cal_nse": best.get("cal_nse"),
           "cal_of": best.get("cal_of"), "of_name": best.get("of_name"),
           "theta": best.get("theta")}
    if partial:
        res["timed_out"] = timed_out
        res["warnings"] = [
            f"Calibration hit the {args.timeout}s wall-clock cap; returning the "
            "best theta persisted up to that point. The search was budget-limited, "
            "not failed -- report the eval budget alongside the metric."
            if timed_out else
            f"Octave exited {result.returncode} (likely OOM-SIGKILL on a "
            "pathological sample) before the MC loop finished; returning the "
            "best theta persisted up to the kill point. Re-run with tighter "
            "--lb/--ub (especially a Smax lower bound >= ~20 mm) to avoid the "
            "stiff-ODE allocation spike."]
    return res


def _resolve_marrmot_path(marrmot_path):
    if marrmot_path:
        return marrmot_path
    candidates = [
        "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/MARRMoT/source/repo/MARRMoT",
        os.path.expanduser("~/MARRMoT/MARRMoT"),
        "./MARRMoT",
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


def process(args):
    """Build and execute Octave script."""
    model_name, theta, s0 = load_params(args)

    # Determine MARRMoT source path
    marrmot_path = args.marrmot_path
    if not marrmot_path:
        # Try common locations
        candidates = [
            "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/MARRMoT/source/repo/MARRMoT",
            os.path.expanduser("~/MARRMoT/MARRMoT"),
            "./MARRMoT",
        ]
        for c in candidates:
            if os.path.isdir(c):
                marrmot_path = c
                break
        if not marrmot_path:
            return {"status": "error",
                    "errors": ["Cannot find MARRMoT source directory"]}

    # Prepare output paths
    output_dir = os.path.dirname(args.output) or "."
    os.makedirs(output_dir, exist_ok=True)
    materialize_runtime_shims(output_dir)
    output_csv = os.path.join(output_dir, "marrmot_timeseries.csv")

    # Build Octave script
    script = build_octave_script(
        forcing_csv=os.path.abspath(args.forcing),
        model_name=model_name,
        theta=theta,
        s0=s0,
        marrmot_path=os.path.abspath(marrmot_path),
        delta_t=args.delta_t,
        output_csv=os.path.abspath(output_csv),
        solver_tol=args.solver_tol,
        solver_maxiter=args.solver_maxiter,
    )

    # Write script to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".m",
                                      delete=False, dir=output_dir) as f:
        f.write(script)
        script_path = f.name

    print(f"Generated Octave script: {script_path}", file=sys.stderr)
    print(f"Model: {model_name}, theta={theta}, S0={s0}", file=sys.stderr)

    # Execute
    try:
        result = subprocess.run(
            ["octave", "--no-gui", "--no-window-system", script_path],
            capture_output=True, text=True,
            timeout=args.timeout,
            cwd=output_dir,
        )

        stdout = result.stdout
        stderr = result.stderr

        print(f"Octave exit code: {result.returncode}", file=sys.stderr)
        if stderr:
            print(f"Octave stderr:\n{stderr[:2000]}", file=sys.stderr)

        # Parse summary JSON from stdout
        summary = {}
        match = re.search(
            r'SUMMARY_JSON_START\s*\n(.*?)\nSUMMARY_JSON_END',
            stdout, re.DOTALL)
        if match:
            try:
                summary = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        run_result = {
            "status": "success" if result.returncode == 0 else "error",
            "model": model_name,
            "theta": theta,
            "S0": s0,
            "delta_t": args.delta_t,
            "output_csv": output_csv,
            "script_path": script_path,
            "return_code": result.returncode,
            "stdout_first_500": stdout[:500],
            "stderr_first_500": stderr[:500],
            "warnings": [],
        }
        run_result.update(summary)

        if result.returncode != 0:
            run_result["errors"] = [
                f"Octave exited with code {result.returncode}",
                stderr[:500],
            ]

    except subprocess.TimeoutExpired:
        run_result = {
            "status": "error",
            "errors": [f"Octave timed out after {args.timeout}s"],
            "model": model_name,
            "warnings": [],
        }
    finally:
        # Clean up temp script (keep for debugging if failed)
        if os.path.exists(script_path) and run_result.get("status") == "success":
            os.unlink(script_path)

    return run_result


def validate_outputs(result):
    """Validate execution outputs."""
    if result["status"] != "success":
        return result

    warnings = result.get("warnings", [])

    # Check output CSV exists
    if "output_csv" in result and not os.path.isfile(result["output_csv"]):
        warnings.append("Output CSV not created -- model may have failed")

    # Check water balance
    wb = result.get("water_balance", None)
    if wb is not None and abs(wb) > 1.0:
        warnings.append(
            f"Water balance error = {wb:.4f} mm (> 1 mm threshold, dt_014)")

    # Check Q values
    q_mean = result.get("Q_mean", None)
    if q_mean is not None and q_mean < 0:
        warnings.append("Negative mean Q -- check parameter configuration")
    if q_mean is not None and q_mean > 100:
        warnings.append("Mean Q > 100 mm/d -- possible unit error in forcing")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run MARRMoT model via Octave subprocess")
    parser.add_argument("--forcing", required=True,
                        help="Forcing CSV file (from convert_forcing.py)")
    parser.add_argument("--model", default=None,
                        help="Model name (e.g. m_29_hymod_5p_5s)")
    parser.add_argument("--params", default=None,
                        help="Parameter JSON file (from convert_parameters.py)")
    parser.add_argument("--theta", default=None,
                        help="Parameter vector as JSON array")
    parser.add_argument("--s0", default=None,
                        help="Initial storage vector as JSON array")
    parser.add_argument("--delta-t", type=float, default=1.0,
                        help="Time step in days (default: 1)")
    parser.add_argument("--output", required=True,
                        help="Output JSON file")
    parser.add_argument("--marrmot-path", default=None,
                        help="Path to MARRMoT source directory")
    parser.add_argument("--solver-tol", type=float, default=0.1,
                        help="Solver residual tolerance")
    parser.add_argument("--solver-maxiter", type=int, default=6,
                        help="Solver max re-runs")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Execution timeout in seconds")
    parser.add_argument("--calibrate", action="store_true",
                        help="Monte-Carlo calibrate (Stage 8): sample params "
                             "from parRanges, score NSE vs --observed")
    parser.add_argument("--observed", default=None,
                        help="Observed Q CSV (date,Q_mm_d) for calibration")
    parser.add_argument("--optimizer", default="mc", choices=["mc", "cmaes"],
                        help="Calibration optimiser: 'mc' uniform Monte-Carlo "
                             "(default, legacy) or 'cmaes' MARRMoT built-in "
                             "CMA-ES via MARRMoT_model.calibrate (recommended, "
                             "scales to >6 params)")
    parser.add_argument("--of-name", default="of_KGE",
                        help="MARRMoT objective function for CMA-ES "
                             "(of_KGE, of_NSE, of_inverse_NSE, of_log_NSE, ...)")
    parser.add_argument("--max-fun-evals", type=int, default=2500,
                        help="CMA-ES max objective-function evaluations budget")
    parser.add_argument("--restarts", type=int, default=0,
                        help="CMA-ES IPOP restarts (doubled popsize each) to "
                             "escape local optima; total evals still capped by "
                             "--max-fun-evals")
    parser.add_argument("--n-samples", type=int, default=200,
                        help="Number of Monte-Carlo parameter samples")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed for reproducible calibration")
    parser.add_argument("--cal-start", type=int, default=None,
                        help="1-based calibration start row (forcing index)")
    parser.add_argument("--cal-end", type=int, default=None,
                        help="1-based calibration end row (forcing index)")
    parser.add_argument("--lb", default=None,
                        help="JSON array: tightened lower sampling bounds")
    parser.add_argument("--ub", default=None,
                        help="JSON array: tightened upper sampling bounds")

    args = parser.parse_args()
    validate_inputs(args)
    if args.calibrate:
        result = process_calibrate(args)
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(json.dumps(result, indent=2))
        return
    result = process(args)
    result = validate_outputs(result)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
