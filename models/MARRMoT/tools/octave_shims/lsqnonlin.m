function [x, resnorm, residual, exitflag, output] = lsqnonlin(fun, x0, lb, ub, opts)
% LSQNONLIN  Minimal drop-in shim for MARRMoT on a GNU Octave install that
%            lacks the Octave-Forge `optim` package (which normally provides
%            lsqnonlin).  MARRMoT only ever calls lsqnonlin as the LAST-RESORT
%            third solver in its NewtonRaphson -> fsolve -> lsqnonlin cascade
%            (see MARRMoT_model.solve_stores / rerunSolver).  For MARRMoT's
%            square store-update systems (numStores residuals == numStores
%            unknowns) a root solve and a least-squares solve coincide, so we
%            satisfy the call with core-Octave `fsolve` (always available) and
%            apply the lower/upper bound clamp lsqnonlin would have enforced.
%
%   Call signature used by MARRMoT:
%       [x, ~, residual, exitflag] = lsqnonlin(fun, x0, lb, [], opts)
%   Returns: x (solution), resnorm (sum of squared residuals),
%            residual (fun(x)), exitflag, output(struct).
%
%   Added 2026-06-23 by the MARRMoT KI (offline install, no packages.octave.org
%   reachable; optim/struct/statistics could not be fetched).  Documented in
%   diagnostics/triplets.yaml (dt_marrmot_no_optim).
    if nargin < 5 || isempty(opts); opts = optimset(); end
    if nargin < 4; ub = []; end
    if nargin < 3; lb = []; end

    x0 = x0(:);
    try
        [x, residual, exitflag] = fsolve(fun, x0, opts);
    catch
        % If even fsolve throws, fall back to the start point so the caller's
        % min-resnorm selection logic still has a finite candidate.
        x = x0; exitflag = 0;
        try
            residual = fun(x);
        catch
            residual = zeros(size(x0));
        end
    end

    x = x(:);
    if ~isempty(lb); x = max(x, lb(:)); end
    if ~isempty(ub); x = min(x, ub(:)); end

    residual = fun(x);
    residual = residual(:);
    resnorm  = sum(residual.^2);
    output = struct('algorithm', 'lsqnonlin-fsolve-shim', ...
                    'iterations', NaN, 'funcCount', NaN);
end
