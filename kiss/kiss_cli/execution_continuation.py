"""One host continuation of a still-approved, verified execution turn.

This never approves, repairs, acquires, or starts a process itself. A temporary
signed scope constrains the existing common API/CLI dispatch to previously
missing steps. Receipt evidence remains the only completion authority.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

MARKER = '.geoforge/execution-continuation.json'
BLOCKER = '.geoforge/execution-continuation-blocked.json'
POLICY = 'approved-execution-continuation-v1'

# Inspection errors do not establish that an approved execution failed. The
# fresh snapshot below still checks every required input, preflight and receipt.
# Keep this finite: a new tool must not gain continuation eligibility by name.
_INSPECTION_TOOLS = frozenset({
    'read_ki_file', 'list_ki_files', 'search_diagnostics', 'list_skills', 'read_skill',
    'list_project_files', 'read_project_file', 'list_work_files', 'read_work_file',
    'search_catalogue', 'describe_dataset',
})


def tool_result_blocker(name, output, *, user_denied=False):
    """Return a bounded blocking reason, never authorization to run a step.

    The caller must retain an earlier blocker for the rest of its provider
    turn. In particular, a later successful read cannot erase a failed launch.
    All explicit denials remain blocking, including inspection denials.
    """
    text = str(output).lstrip()
    if user_denied:
        return 'user_denied'
    if text.startswith('DENIED'):
        return 'tool_denied'
    if name == 'run_preflight' and text.startswith('FAIL'):
        return 'preflight_failed'
    if text.startswith('ERROR:'):
        if isinstance(name, str) and name in _INSPECTION_TOOLS:
            return None
        return 'tool_error'
    return None


def _decision(turn, reason, *, blocked=True, error=None):
    """Best-effort bounded diagnostics; failure to log never changes a gate."""
    try:
        from . import execution, provider_diagnostics
        fs = turn.session
        metadata = {'phase': 'execution', 'reason': reason, 'blocked': blocked,
            'state': getattr(getattr(fs, 'state', None), 'value', ''),
            'turn_id': execution.current_turn_id(fs.project),
            'approval_id': fs.approval_id}
        if error is not None:
            metadata['error'] = str(error)
        provider_diagnostics.record(fs.project, 'execution_continuation', **metadata)
    except Exception:
        pass


def _hash(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _snapshot(fs):
    from . import acquire, execution, project_verification, setup
    from .catalog import KI
    project = Path(fs.project).resolve()
    fs.ctx = fs.flow.states.FlowContext.load(project)
    fs.reload_artifacts()
    if fs.state.value != 'EXECUTING' or fs.approval_status() != 'OK':
        raise ValueError('Continuation requires the same currently approved execution plan.')
    if execution.stop_requested(project):
        raise ValueError('The user stopped this project.')
    blocker = _read(project, blocker=True)
    if blocker and blocker.get('turn_id') == execution.current_turn_id(project):
        raise ValueError('A project execution wrapper failed during this user turn.')
    pending = setup.request(project, archive_obsolete=False)
    if pending and pending.get('status') == 'waiting':
        raise ValueError('The project is waiting for a user answer.')
    if getattr(fs, 'continuation_blocked', False):
        raise ValueError('The provider encountered a tool failure or denial.')
    plan = fs.plan or {}
    if set(plan.get('selected_kis') or []) != set(fs.ki_roots) or set(fs.ctx.selected_kis) != set(fs.ki_roots):
        raise ValueError('The selected project KIs changed.')
    preflights = {}
    for name, root in fs.ki_roots.items():
        checked = project_verification.status(project, KI(name, Path(root)))
        if not checked.get('can_run'):
            raise ValueError('The exact project preflight is not current for ' + name + '.')
        preflights[name] = checked['receipt']
    proof = fs.evidence(enforcement=fs.ctx.enforcement.value)
    if (proof.get('validation') == 'failed' or proof.get('stale_steps')
            or proof.get('unreceipted_artifacts')):
        raise ValueError('Current execution evidence needs review before continuing.')
    acq = acquire.status(project)
    if acq.get('approval_sha256') == fs.approval_id and acq.get('status') not in {'done', 'idle'}:
        raise ValueError('Approved acquisition has not completed.')
    # Missing generated inputs may be produced by an earlier pending step.
    # Missing external input bytes are a blocker, not a reason to launch.
    items = {str(item.get('id')): item for item in (fs.inventory or {}).get('items', [])}
    produced = set()
    for step in plan.get('steps', []):
        for ident in step.get('inputs') or []:
            if ident in produced:
                continue
            local = (items.get(str(ident)) or {}).get('local_paths') or []
            if not local:
                raise ValueError('A required external input has no local path: ' + str(ident))
            for raw in local:
                p = Path(str(raw).replace('${PROJECT}', str(project)))
                if not (p if p.is_absolute() else project / p).exists():
                    raise ValueError('A required external input is missing: ' + str(ident))
        if step.get('tool') or step.get('kind') == 'download':
            produced.update(step.get('outputs') or [])
    binding = {'project': str(project), 'approval_id': fs.approval_id,
        'plan_sha256': fs.flow.plan.sha256(plan),
        'inventory_sha256': fs.flow.plan.sha256(fs.inventory),
        'roots': {n: str(Path(p).resolve()) for n, p in fs.ki_roots.items()},
        'preflights_sha256': _hash(preflights)}
    return binding, proof


def offer(turn):
    """Decide after a provider final; only bounded diagnostics may be written."""
    if turn.kind != 'execution':
        _decision(turn, 'not_execution_turn')
        return None
    if turn.provider_succeeded is False or getattr(turn.session, 'provider_succeeded', None) is False:
        _decision(turn, 'provider_failed')
        return None
    if turn.provider_succeeded is not True and getattr(turn.session, 'provider_succeeded', None) is not True:
        _decision(turn, 'provider_not_succeeded')
        return None
    try:
        binding, proof = _snapshot(turn.session)
        missing = proof.get('steps_missing') or []
        if not missing:
            _decision(turn, 'no_pending_steps', blocked=False)
            return None
        from .execution import current_turn_id
        turn_id = current_turn_id(turn.session.project)
        if not turn_id:
            _decision(turn, 'no_turn_id')
            return None
        previous = _read(turn.session.project)
        if previous and previous.get('turn_id') == turn_id:
            _decision(turn, 'continuation_already_used')
            return None  # a scope, including a closed one, is used once per human turn
        steps = [s for s in turn.session.plan['steps'] if str(s.get('id')) in missing]
        if not steps or any(s.get('kind') == 'download' or not s.get('tool') for s in steps):
            _decision(turn, 'pending_step_requires_handoff')
            return None
        _decision(turn, 'offered', blocked=False)
        return {'binding': binding, 'turn_id': turn_id,
            'pending_ids': [str(s['id']) for s in steps], 'passed_ids': proof.get('steps_passed', []),
            'steps': steps, 'evidence_sha256': _hash(proof)}
    except (ValueError, OSError, RuntimeError, TypeError, KeyError) as error:
        _decision(turn, 'snapshot_rejected', error=error)
        return None


def prompt(ticket):
    return ('[HOST: CONTINUE THE EXISTING APPROVED EXECUTION]\n'
        'The provider ended after checks while approved steps still lack receipts. '
        'Continue these exact pending steps in their approved order and with their approved '
        'arguments, working directories and output paths. Do not rerun preflight merely to '
        'end again. Do not repeat passed steps. Do not write additional numeric CSV/data '
        'artifacts outside the approved steps; publish or discuss the existing reviewed outputs. '
        'Use the normal receipt-producing tools/wrappers. If a real blocker or user decision '
        'appears, use the existing question/replan tool and stop; do not improvise authority.\n'
        'Already passed: ' + json.dumps(ticket['passed_ids']) + '\n'
        'Exact pending approved steps: ' + json.dumps(ticket['steps'], ensure_ascii=False) + '\n'
        'This is the single bounded continuation for this user turn. Completion still requires '
        'current signed receipts; a summary is not execution evidence.')


def _read(project, *, blocker=False):
    path = Path(project) / (BLOCKER if blocker else MARKER)
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or path.resolve() != path.absolute() or path.stat().st_nlink != 1:
        raise ValueError('Continuation marker is not an ordinary host file.')
    if path.stat().st_size > 256 * 1024:
        raise ValueError('Continuation marker is too large.')
    with path.open('rb') as stream:
        data = stream.read(256 * 1024 + 1)
    if len(data) > 256 * 1024:
        raise ValueError('Continuation marker grew during inspection.')
    doc = json.loads(data)
    from . import flowgate
    if (not flowgate.load().receipts.verify(project, doc) or doc.get('policy') != POLICY
            or doc.get('state') not in ({'blocked'} if blocker else {'active', 'closed'})):
        raise ValueError('Continuation marker is invalid.')
    return doc


def _write(project, doc, *, blocker=False):
    from . import flowgate, obs_access
    path = Path(project) / (BLOCKER if blocker else MARKER)
    path.parent.mkdir(exist_ok=True)
    if path.parent.resolve() != path.parent.absolute() or path.parent.is_symlink():
        raise ValueError('Continuation directory uses an alias.')
    _read(project, blocker=blocker)  # invalid current markers never gain write authority
    obs_access._atomic_json(path, flowgate.load().receipts.sign(project, dict(doc)))


def record_cli_failure(project, step_id, exit_code):
    """Record an observed wrapper refusal, not a scientific attempt/receipt.

    Only a child with the exact inherited host generation can block that turn.
    A standalone manual CLI invocation must not poison an old GUI generation.
    """
    from . import execution, flowgate
    project = Path(project).resolve()
    inherited = os.environ.get(execution.TURN_ID_ENV)
    owner = os.environ.get(execution.TURN_PROJECT_ENV)
    if (not inherited or not owner or Path(owner).resolve() != project
            or inherited != execution.current_turn_id(project)):
        return
    if flowgate.load().states.FlowContext.load(project).state.value != 'EXECUTING':
        return
    _write(project, {'policy': POLICY, 'state': 'blocked', 'turn_id': inherited,
        'project': str(project), 'step_id': str(step_id or '')[:200],
        'exit_code': int(exit_code), 'created_at': time.time(),
        'source': 'project-run-tool-wrapper'}, blocker=True)


@contextmanager
def scoped(turn, ticket, *, stopped, turn_id):
    """The GUI holds its project lease; the existing turn generation handles new input."""
    from . import execution
    fs = turn.session
    if stopped() or not turn_id or ticket.get('turn_id') != turn_id or execution.current_turn_id(fs.project) != turn_id:
        raise ValueError('Continuation was stopped or superseded by new input.')
    current = offer(turn)
    if current != ticket:
        raise ValueError('The approved execution context changed before continuation.')
    ident = uuid.uuid4().hex
    doc = {'policy': POLICY, 'id': ident, 'state': 'active', 'binding': ticket['binding'],
           'pending_ids': ticket['pending_ids'], 'turn_id': turn_id, 'created_at': time.time()}
    _write(fs.project, doc)
    try:
        if stopped() or execution.current_turn_id(fs.project) != turn_id:
            raise ValueError('Continuation was stopped or superseded by new input.')
        if _snapshot(fs)[0] != ticket['binding']:
            raise ValueError('The project changed while claiming continuation.')
        yield
    finally:
        current = _read(fs.project)
        if current and current.get('id') == ident:
            _write(fs.project, {**doc, 'state': 'closed', 'closed_at': time.time()})


def require_step(fs, step_id):
    """Idempotent admission: CLI and execution both call check_step_tool."""
    doc = _read(fs.project)
    if not doc:
        return
    from .execution import current_turn_id
    if doc.get('turn_id') != current_turn_id(fs.project):
        return  # a new explicit user turn retains ordinary rerun semantics
    if doc['state'] == 'closed':
        raise ValueError('This turn has already used its bounded continuation; await new user input.')
    # Standalone CLI wrappers reconstruct only the invoked KI. Revalidate all
    # signed selected roots without silently accepting a different invoked KI.
    from . import flowgate
    roots = doc.get('binding', {}).get('roots', {})
    if any(roots.get(n) != str(Path(p).resolve()) for n, p in fs.ki_roots.items()):
        raise ValueError('The invoked KI differs from the continuation scope.')
    bound = flowgate.FlowSession.open(fs.project, {n: Path(p) for n, p in roots.items()})
    bound.continuation_blocked = getattr(fs, 'continuation_blocked', False)
    binding, proof = _snapshot(bound)
    if binding != doc.get('binding'):
        raise ValueError('Approval, KI or verified runtime changed during continuation.')
    if str(step_id) not in doc.get('pending_ids', []) or str(step_id) not in proof.get('steps_missing', []):
        raise ValueError('Continuation may run only still-missing approved steps; passed steps cannot repeat.')
