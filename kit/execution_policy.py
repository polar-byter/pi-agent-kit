"""Pure limits and escalation decisions; no sessions, IO or journal mutations."""
from __future__ import annotations

import math


DEFAULT_POLICY = {
    'maxExecutors': 2,
    'maxSteps': 24,
    'maxSeconds': 600,
    'maxRepeatedActions': 3,
    'fixerMaxSteps': 32,
    'fixerMaxSeconds': 600,
    'executorMaxAttempts': 3,
    'fixerMaxAttempts': 6,
    'maxAttempts': 9,
}


def normalize_policy(value: dict | None = None) -> dict:
    """Return an independent complete policy; the default allows two isolated executors.

    None and an empty dict use DEFAULT_POLICY. Accept a partial dict with only
    the default keys; do not mutate the input or DEFAULT_POLICY. Every supplied
    value must be an int, not bool. Ranges are inclusive: maxExecutors 1..8,
    maxSteps/fixerMaxSteps 1..256, maxSeconds/fixerMaxSeconds 1..3600,
    maxRepeatedActions 2..32, role failure budgets 1..100, total budget 1..200.
    Reject non-dicts, unknown keys, invalid types and
    out-of-range values with ValueError. Never coerce strings or floats.
    """
    if value is None:
        value = {}
    if not isinstance(value, dict) or value.keys() - DEFAULT_POLICY.keys():
        raise ValueError('Unknown execution policy fields')
    result = dict(DEFAULT_POLICY)
    bounds = {'maxExecutors': (1, 8), 'maxRepeatedActions': (2, 32),
              'maxSteps': (1, 256), 'fixerMaxSteps': (1, 256),
              'maxSeconds': (1, 3600), 'fixerMaxSeconds': (1, 3600),
              'executorMaxAttempts': (1, 100), 'fixerMaxAttempts': (1, 100),
              'maxAttempts': (1, 200)}
    for key, number in value.items():
        low, high = bounds[key]
        if type(number) is not int or not low <= number <= high:
            raise ValueError(f'{key} must be an integer between {low} and {high}')
        result[key] = number
    return result


def limit_reason(*, steps: int, repeated_actions: int, elapsed_seconds: float,
                 policy: dict | None = None) -> str | None:
    """Classify public execution counters without interpreting private reasoning.

    Validate policy with normalize_policy. steps/repeated_actions are nonnegative
    ints (not bool); elapsed_seconds is a finite nonnegative int/float, not bool.
    Invalid input raises ValueError. Return step_limit at steps >= maxSteps;
    otherwise repeated_actions at repeated_actions >= maxRepeatedActions;
    otherwise deadline at elapsed_seconds >= maxSeconds; else None. This order
    is deterministic. The controller supplies repeated_actions only for identical
    public tool actions without verified result/file progress. A stale progress
    file or no events alone must never increment this counter. A returned reason
    is a signal, not evidence that an executing session has already stopped.
    """
    policy = normalize_policy(policy)
    if any(type(n) is not int or n < 0 for n in (steps, repeated_actions)):
        raise ValueError('Execution counters must be nonnegative integers')
    if (isinstance(elapsed_seconds, bool) or not isinstance(elapsed_seconds, (int, float))
            or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0):
        raise ValueError('Elapsed time must be finite and nonnegative')
    if steps >= policy['maxSteps']:
        return 'step_limit'
    if repeated_actions >= policy['maxRepeatedActions']:
        return 'repeated_actions'
    if elapsed_seconds >= policy['maxSeconds']:
        return 'deadline'
    return None


def next_action(role: str, reason: str, *, fixer_enabled: bool,
                fixer_attempts: int = 0, max_fixer_attempts: int = 1) -> str:
    """Choose a bounded failure route after the old attempt has actually stopped.

    Roles are executor or bug_fixer. Reasons implementation_error, step_limit,
    repeated_actions and deadline return bug_fixer with an explicitly enabled
    fixer and remaining fixer budget. A failed fixer continues as the same role.
    Reasons api_error, rate_limit and setup_error always return blocked, without
    a model switch. Reasons paused and cancelled always return stop. Unknown role
    or reason raises ValueError. fixer_enabled must be bool; fixer_attempts must
    be a nonnegative int, not bool. Validate all arguments before deciding.
    No key access, side effects or implicit model inheritance. The default
    preserves the legacy single correction route; controllers supply the selected
    budget explicitly. There is no route back to executor. This decision never
    overrides task pause/cancel state or the existing global STOP guards.
    """
    implementation = ('implementation_error', 'step_limit', 'repeated_actions', 'deadline', 'token_limit')
    infrastructure = ('api_error', 'rate_limit', 'setup_error')
    if (role not in ('executor', 'bug_fixer') or reason not in implementation + infrastructure + ('paused', 'cancelled')
            or type(fixer_enabled) is not bool or type(fixer_attempts) is not int or fixer_attempts < 0
            or type(max_fixer_attempts) is not int or max_fixer_attempts < 1):
        raise ValueError('Invalid failure routing arguments')
    if reason in infrastructure:
        return 'blocked'
    if (reason in implementation and fixer_enabled and fixer_attempts < max_fixer_attempts
            and (role == 'executor' or fixer_attempts > 0)):
        return 'bug_fixer'
    return 'stop'


INFRASTRUCTURE_REASONS = frozenset(('api_error', 'rate_limit', 'setup_error', 'paused', 'cancelled'))


def attempt_counts(events, work_item):
    """Count reviewed code failures once per isolated attempt since user resume.

    Infrastructure outcomes never spend a code-repair budget, even if the worker
    saved partial source before losing the API. Old journal rows remain unchanged.
    """
    start = max((i + 1 for i, e in enumerate(events) if e['kind'] == 'resume'), default=0)
    attempts = {e['event_id']: e for e in events if e['kind'] == 'delegation'
                and e.get('work_item') == work_item and e.get('workspace')}
    reasons = {e['delegation_id']: e['reason'] for e in events if e['kind'] == 'attempt_end'}
    counts, seen = {'executor': 0, 'bug_fixer': 0}, set()
    for event in events[start:]:
        identifier = event.get('delegation_id')
        if (event['kind'] != 'review' or event.get('result') not in ('rework', 'failed')
                or identifier not in attempts or identifier in seen
                or reasons.get(identifier) in INFRASTRUCTURE_REASONS):
            continue
        seen.add(identifier)
        counts[attempts[identifier].get('role', 'executor')] += 1
    return counts


def budget_reason(counts, policy, role=None):
    """A launch checks its own role; a review stops only exhausted repair/total budgets."""
    policy = normalize_policy(policy)
    if sum(counts.values()) >= policy['maxAttempts']:
        return f'Code repair budget exhausted: {sum(counts.values())}/{policy["maxAttempts"]} attempts per work item'
    roles = (role,) if role else ('bug_fixer',)
    for current in roles:
        key = 'fixerMaxAttempts' if current == 'bug_fixer' else 'executorMaxAttempts'
        if counts[current] >= policy[key]:
            return f'{current} code repair budget exhausted: {counts[current]}/{policy[key]} attempts per work item'
    return None
