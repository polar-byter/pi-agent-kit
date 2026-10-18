"""Local task journal, test runner and OpenCode usage report. See docs/kit/METRICS.ru.md.

Why this module is the core of the control loop:
the Master Chief runs the executor, checks its work and tests it,
but .metrics/<ID>/events.jsonl is the only source of truth for what happened.
The Master Chief is a model too: it can be restarted, forget things or bend the rules,
so the journal, not its memory, decides what was recorded, changed, tested and accepted.
task_metrics.py is the command line to read and write that journal, and to produce a usage report at the end.

The journal is append-only: one JSON event per line (start, delegation, inspect, review,
test, halt, resume, finish ...). Events are never edited or removed; every answer
("can this be accepted?", "is it time to stop?") is computed by reading all events.

What the commands enforce:
  - delegate freezes the allowed files, the requirements and a snapshot of the project;
  - inspect detects edits outside the allowed files (delegation_guard.py);
  - review --result accepted needs evidence for every recorded requirement and a green test.

But it is not only a journal: it also enforces loop guards. After every test run and
review, task_metrics.py itself checks the guards against the journal (limit_breach()).
If any guard is breached, it appends a "halt" event and exits with code 3 (STOP);
the task stays halted until the user decides and the Master Chief runs `resume`.
The guards are (DEFAULT_LIMITS, they can be changed at `start`):
  - max_reworks=3: one work item sent back to the executor, or failed without edits, 3 times;
  - max_no_result=3: test runs in a row without a readable result (setup or build problem);
  - max_failed_runs=12: test runs in a row that are not green in the same scope;
  - max_runs=60: test runs in total since start or the last resume.
Isolated controller attempts use per-role budgets instead (execution_policy.py).
Dashboard controls (pause, cancel) also block new work (blocking_reason()).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

# The same file is loaded in two ways, and each needs its own import form:
# - as part of the kit package (python -m kit..., or "from ..task_metrics import" in the dashboard):
#   __package__ == 'kit' and the project root is on sys.path, so only the relative
#   ".delegation_guard" ("from the same package as this module") can find the neighbour;
# - as a script (kit/task_metrics.py) or from the tests, which put kit/ on sys.path:
#   __package__ is empty, a relative import fails, and the plain "delegation_guard" works.
#
# The module is split by responsibility; this file keeps only the task commands and the CLI:
#   journal.py       the append-only event log (TaskJournal) and event helpers
#   loop_guards.py   when a task must STOP (limit_breach, is_halted, DEFAULT_LIMITS)
#   suite_runner.py  running the test command and reading its result (SuiteRunnerMixin)
#   usage_report.py  token usage from OpenCode exports and report.md (UsageReportMixin)
# Names that used to live here are imported back, so "from task_metrics import X" keeps working.
if __package__:
    from .delegation_guard import (compare_project_snapshots, normalize_delegated_path, read_requirements,
                                   review_checks, take_project_snapshot)
    from .journal import (KNOWN_EVENT_TYPES, WINDOWS_RESERVED, TaskJournal, corrected_events, normalize_work_item,
                          pending_attempts, session_id, valid_number)
    from .loop_guards import (DEFAULT_LIMITS, TaskHalted, is_halted, limit_breach, since_last_resume,
                              task_limits, trailing)
    from .suite_runner import (CATEGORY_FAILED, CATEGORY_INCOMPLETE, CATEGORY_NO_RESULT, CATEGORY_PASSED,
                               CATEGORY_TIMEOUT, SuiteRunnerMixin, diagnose, final_status, fresh_xml_files,
                               local_tag, parse_junit_files, parse_unittest, resolve_command, run_category,
                               run_command)
    from .task_control_state import blocking_reason
    from .usage_report import (TOKEN_FIELDS, UsageReportMixin, add_usage, descendants,
                               master_chief_tool_child_references, message_info, message_model,
                               message_tokens, new_usage_row, resolve_opencode, text_or_unknown)
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from delegation_guard import (compare_project_snapshots, normalize_delegated_path, read_requirements,
                                  review_checks, take_project_snapshot)
    from journal import (KNOWN_EVENT_TYPES, WINDOWS_RESERVED, TaskJournal, corrected_events, normalize_work_item,
                         pending_attempts, session_id, valid_number)
    from loop_guards import (DEFAULT_LIMITS, TaskHalted, is_halted, limit_breach, since_last_resume,
                             task_limits, trailing)
    from suite_runner import (CATEGORY_FAILED, CATEGORY_INCOMPLETE, CATEGORY_NO_RESULT, CATEGORY_PASSED,
                              CATEGORY_TIMEOUT, SuiteRunnerMixin, diagnose, final_status, fresh_xml_files,
                              local_tag, parse_junit_files, parse_unittest, resolve_command, run_category,
                              run_command)
    from task_control_state import blocking_reason
    from usage_report import (TOKEN_FIELDS, UsageReportMixin, add_usage, descendants,
                              master_chief_tool_child_references, message_info, message_model,
                              message_tokens, new_usage_row, resolve_opencode, text_or_unknown)

# Final UI/UX improvement stage of the Master Chief: done with evidence, skipped with a reason,
# or not applicable because the product has no user interface.
UX_OUTCOMES = ('completed', 'skipped', 'not_applicable')
UX_REASON_LIMIT = 300
# failed: the executor returned no work (error, rate limit, unavailable model) and changed no files.
REVIEW_RESULTS = {'accepted', 'rework', 'failed', 'blocked'}

# Exit codes of the command line, so the Master Chief can react without parsing text.
EXIT_OK = 0
EXIT_TESTS_FAILED = 1
EXIT_USAGE = 2
EXIT_STOP = 3
EXIT_NO_RESULT = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest='action', required=True)
    start = sub.add_parser('start')
    start.add_argument('--session')
    start.add_argument('--title')
    start.add_argument('--track-delegations', action='store_true', help='require registered executor attempts for reviews')
    start.add_argument('--no-dashboard', action='store_true', help='disable the automatic dashboard for this start')
    start.add_argument('--no-browser', action='store_true', help='start/reuse the dashboard without opening a browser')
    for name in DEFAULT_LIMITS:
        start.add_argument('--' + name.replace('_', '-'), type=int, dest=name,
                            help=f'loop guard, default {DEFAULT_LIMITS[name]}')
    review = sub.add_parser('review')
    review.add_argument('--work-item', '--piece', dest='work_item', required=True)
    review.add_argument('--result', choices=sorted(REVIEW_RESULTS), required=True,
                        help='failed = the executor returned no work and changed no files; not a rework')
    review.add_argument('--checks', type=Path, help='JSON requirement/code/test checklist for acceptance')
    delegation = sub.add_parser('delegate')
    delegation.add_argument('--work-item', '--piece', dest='work_item', required=True)
    delegation.add_argument('--files', nargs='+', required=True)
    delegation.add_argument('--scope', help='test scope; defaults to the work item name')
    delegation.add_argument('--requirements', type=Path, required=True, help='JSON list recorded before the executor call')
    inspect = sub.add_parser('inspect')
    inspect.add_argument('--work-item', '--piece', dest='work_item', required=True)
    resume = sub.add_parser('resume')
    resume.add_argument('--reason', required=True)
    ux = sub.add_parser('ux-review', help='record the final UI/UX improvement stage before finish')
    ux_outcome = ux.add_mutually_exclusive_group(required=True)
    ux_outcome.add_argument('--checks', type=Path,
                            help='JSON list of performed scenarios: scenario, actions, result, optional fixed')
    ux_outcome.add_argument('--skipped', help='why the stage could not be performed, e.g. no browser available')
    ux_outcome.add_argument('--not-applicable', dest='not_applicable',
                            help='why the product has no user interface to improve')
    test = sub.add_parser('test')
    test.add_argument('--scope', default='full', help='work-item/module name or full for the complete suite')
    test.add_argument('--phase', choices=['work', 'baseline'], default='work')
    test.add_argument('--attempt', help='exact isolated delegation ID for this test result')
    check = sub.add_parser('check')
    for command in (test, check):
        command.add_argument('--timeout', type=float, default=300)
        command.add_argument('--junit')
        command.add_argument('--junit-dir')
        command.add_argument('command', nargs=argparse.REMAINDER)
    finish = sub.add_parser('finish')
    finish.add_argument('--language', choices=('en', 'ru'), help='report language; otherwise saved UI preference or system language')
    finish.add_argument('--export', action='append', dest='exports')
    finish.add_argument('--opencode', default='opencode')
    for command in (start, delegation, inspect, review, resume, ux, test, finish):
        command.add_argument('--task', required=True)
    return parser


class TaskMetrics(TaskJournal, SuiteRunnerMixin, UsageReportMixin):
    """The task commands: start, delegate, inspect, review, test, resume, ux-review, finish.

    Each command reads the journal, checks its rules and appends one event.
    The journal itself (read, append, lock) comes from TaskJournal; running tests
    from SuiteRunnerMixin; token usage and report.md from UsageReportMixin.

    Calling finish again for a finished task returns the same report without
    recounting; the report is written to report.md in the task directory.
    """

    def start(self, task: str, session: str | None = None, title: str | None = None,
              limits: dict | None = None, track_delegations: bool = False) -> dict:
        if session is not None:
            session_id(session)
        limits = dict(DEFAULT_LIMITS, **{k: v for k, v in (limits or {}).items() if v is not None})
        if set(limits) != set(DEFAULT_LIMITS) or any(type(v) is not int or v < 1 for v in limits.values()):
            raise ValueError('Limits must be positive integers: ' + ', '.join(DEFAULT_LIMITS))
        self.task_dir(task).mkdir(parents=True, exist_ok=False)
        with self.lock(task):
            # session=session puts the value into append's **data as the "session" key;
            # session_id(session) above has already validated it.
            server = {}
            from kit.runtime_selection import uses_pi_runtime
            if uses_pi_runtime(self.root):
                server.update(runtime='pi', server_mode='managed')
            if os.environ.get('OPENCODE_KIT_ROOT') and Path(os.environ['OPENCODE_KIT_ROOT']).resolve() == self.root:
                server['server_mode'] = os.environ.get('OPENCODE_KIT_SERVER_MODE', 'unknown')
            return self.append(task, 'start', session=session, title=title or task, limits=limits,
                               track_delegations=track_delegations, ux_review_required=track_delegations,
                               **server)


    def read_events_if_work_allowed(self, task: str) -> list[dict]:
        """Read the journal for a command that does work; refuse if the task may not work now.

        Every command that changes the task (delegate, inspect, review, test) starts with it,
        and execution_controller.py rechecks it before admitting a worker. Work is allowed when:
          1. the task is not finished (read_events_if_not_finished);
          2. the user did not pause, stop or delete it in the dashboard
             (.metrics/.task-controls/<task>.json, see blocking_reason);
          3. no loop guard STOP is active: no "halt" event without a later "resume".
        Returns all events of the task (with audited corrections applied).
        Raises ValueError when the task is finished or the journal is broken (exit code 2),
        and TaskHalted with the reason when it is paused or stopped (exit code 3, STOP).
        resume() uses read_events_if_not_finished instead: it must work while a STOP is active.
        """
        events = self.read_events_if_not_finished(task)
        reason = blocking_reason(self.root, task)
        if reason:
            raise TaskHalted(reason)
        halt = is_halted(events)
        if halt:
            raise TaskHalted(halt['reason'])
        return events

    def guard(self, task: str, events: list[dict]) -> dict | None:
        """Appends a 'halt' event if a loop guard is reached. Returns that event or None."""
        reason = limit_breach(events, task_limits(events))
        return self.append(task, 'halt', reason=reason) if reason else None

    def attempt_root(self, task: str, attempt: dict) -> Path:
        """Only controller-owned plain directories may hold isolated edits."""
        if not attempt.get('workspace'):
            return self.root
        path = self.root / attempt['workspace']
        base = self.task_dir(task) / 'workspaces'
        if path.resolve() != path.absolute() or not path.resolve().is_relative_to(base.resolve()) or not path.is_dir():
            raise ValueError('Invalid isolated workspace')
        return path

    def delegate(self, task: str, work_item: str, files: list[str], scope: str | None = None,
                 requirements_file: Path | None = None, *, workspace: str | None = None,
                 worker_id: str | None = None, role: str = 'executor', contracts: list[str] | None = None) -> dict:
        """Register one executor attempt before the executor starts: what it may change and how it is judged.

        The Master Chief calls it as `task_metrics.py delegate` right before every executor
        call, including every retry: each retry after a review is a new attempt.
        In sequential mode a new attempt is refused while the previous one has no review.

        Parameters given by the Master Chief (he does it via command line):
            - task: the task ID from `start`; the journal is .metrics/<task>/events.jsonl.
            - work_item: the name of the assignment, for example a class "GameService".
                Reviews, inspections and loop guard counters are grouped by this name.
            - files: the source file the executor may edit, relative to the project root.
                A list for the command line, but after removing duplicates it must be exactly
                one file: the snapshot comparison treats any other changed file as unexpected.
            - scope: the test scope of this work item, for example "GameService"; defaults to
                work_item. review() accepts only a green test run in this scope or in "full".
            - requirements_file: a JSON list of requirement texts, relative to the project root.
                The list is copied into the journal now, so later edits of the file do not
                change what the review must prove. Required when the task tracks delegations.

        Parameters given only by execution_controller.py (parallel mode, keyword-only):
            -workspace: the worker's own copy of the project under .metrics/<task>/workspaces/;
                files are checked and the snapshot is taken there instead of the project root.
            - worker_id: the worker slot that runs this attempt; one open attempt per worker.
            - role: "executor" or "bug_fixer" (the fixer that continues a failed attempt).
            - contracts: shared read-only files (interfaces, common types), relative to the
                project root; required when more than one executor may run at the same time.

        Writes a before - snapshot file, appends a delegation event with the allowed
        file, the scope, the snapshot file name and the requirement texts. 
        Returns that event.
        Raises ValueError when a rule is broken and TaskHalted when the task is stopped or paused.
        """
        # Require a work item name, file list and non-blank effective test scope.
        if not work_item.strip() or not files or not (scope or work_item).strip():
            raise ValueError('Delegation needs a work item, files and a non-empty test scope')

        # Validate paths and remove duplicate file names.
        target = self.attempt_root(task, {'workspace': workspace})
        allowed = sorted({normalize_delegated_path(target, name) for name in files})

        # Allow exactly one unique file per attempt.
        # what does it mean: the executor may change only one file, and any other changed file is unexpected.
        if len(allowed) != 1:
            raise ValueError('Delegate exactly one source file per executor attempt')
        requirement_texts = read_requirements(self.root / requirements_file) if requirements_file else []
        with self.lock(task):
            events = self.read_events_if_work_allowed(task)
            if events[0].get('track_delegations') and not requirement_texts:
                raise ValueError('Tracked delegation requires a requirements file')
            pending = pending_attempts(events)
            details = {}
            if workspace:
                details = self.reserve_isolated_slot(task, events, pending, work_item, allowed,
                                                     workspace, worker_id, role, contracts)
            elif pending:
                # Sequential mode: one attempt at a time; any review closes the previous one.
                raise ValueError('Review the pending delegation before starting another')
            before = take_project_snapshot(target)
            filename = 'before-' + uuid.uuid4().hex + '.json'
            (self.task_dir(task) / filename).write_text(json.dumps(before), encoding='utf-8')
            return self.append(task, 'delegation', work_item=work_item.strip(), files=allowed,
                               scope=(scope or work_item).strip(), snapshot=filename, requirements=requirement_texts, **details)

    def reserve_isolated_slot(self, task: str, events: list[dict], pending: list[dict], work_item: str,
                              allowed: list[str], workspace: str, worker_id: str | None, role: str,
                              contracts: list[str] | None) -> dict:
        """Check the parallel-mode rules for one isolated attempt; return its extra event fields.

        Called by delegate() under the task lock, only for execution_controller.py attempts.
        Rules: a known role and worker; a free worker slot (maxExecutors from the task's
        execution settings); this work item, worker and workspace are not in use; the file is
        not assigned to another worker or awaiting integration; shared contracts are given
        by this attempt and by every attempt still running beside it. The returned base_hashes let integrate() detect
        that the main project changed while the worker was busy.
        """
        if __package__:
            from .execution_policy import normalize_policy
            from .run_opencode import load_choices
            from .task_control_state import read_state
        else:
            from execution_policy import normalize_policy
            from run_opencode import load_choices
            from task_control_state import read_state
        settings = self.task_dir(task) / 'execution-settings.json'
        choices = json.loads(settings.read_text(encoding='utf-8')) if settings.exists() else load_choices(self.root)
        selected = read_state(self.root, task).get('settings_revision')
        if selected:
            # model_switch also loads the dashboard controls, so import it only when a revision is chosen.
            if __package__:
                from .model_switch import revision
            else:
                from model_switch import revision
            choices = revision(self.root, task, selected)['choices']
        policy = normalize_policy(choices.get('execution'))
        if role not in ('executor', 'bug_fixer') or not worker_id:
            raise ValueError('Isolated attempts need a worker identity and role')
        if (any(not e.get('workspace') or e['work_item'] == work_item or e.get('worker_id') == worker_id for e in pending)
                or len(pending) >= policy['maxExecutors']
                or any(e.get('workspace') == workspace for e in events if e['kind'] == 'delegation')):
            raise ValueError('Worker slot, work item or workspace is already in use')
        accepted = {e.get('delegation_id') for e in events if e['kind'] == 'review' and e['result'] == 'accepted'}
        integrated = {e.get('delegation_id') for e in events if e['kind'] == 'integration'}
        reserved = pending + [e for e in events if e['kind'] == 'delegation' and e['event_id'] in accepted - integrated]
        if any(set(e['files']) & set(allowed) for e in reserved):
            raise ValueError('Source file is already assigned or awaiting integration')
        contract_paths = sorted({normalize_delegated_path(self.root, p) for p in (contracts or [])})
        # Contracts are needed only when attempts really overlap: a lone attempt (a single-module
        # task, or the last ready work item) runs without them even though two slots are allowed.
        if pending and (not contract_paths or any(not e.get('contracts') for e in pending)):
            raise ValueError('Parallel work requires explicit shared contracts for every running attempt; '
                             'wait for the running attempt or launch both with --contracts')
        base = take_project_snapshot(self.root)
        return dict(workspace=workspace, worker_id=worker_id, role=role,
                    base_hashes={p: base.get(p) for p in allowed + contract_paths},
                    contracts=contract_paths)

    def inspect(self, task: str, work_item: str) -> dict:
        """Save file changes for the pending attempt; refuse a second inspection.

        The Master Chief must call this after the executor returns, before its own edits.
        We also check that the executor stopped, and that the work item matches the pending attempt;
        and snapshot the project to detect any edits outside the allowed file.
        if the executor changed any other file, the review will refuse acceptance.
        """
        with self.lock(task):
            events = self.read_events_if_work_allowed(task)
            work_item = work_item.strip()  # delegate() records the stripped name
            attempts = pending_attempts(events, work_item)
            if not attempts:
                raise ValueError(f'No delegated attempt of {work_item!r} is waiting for inspection; '
                                 'register it with delegate first')
            if len(attempts) > 1:
                raise ValueError(f'Several open attempts of {work_item!r}; the journal is inconsistent, '
                                 'close the extra attempts with review --result rework before inspecting')
            attempt = attempts[0]
            if attempt.get('workspace') and not any(e['kind'] == 'attempt_end' and e['delegation_id'] == attempt['event_id']
                                                   and e.get('stopped') is True for e in events):
                raise ValueError('Confirm that this isolated worker stopped before inspection')
            if any(e['kind'] == 'inspection' and e['delegation_id'] == attempt['event_id'] for e in events):
                raise ValueError('Executor edits already inspected; do not overwrite the evidence')
            before = json.loads((self.task_dir(task) / attempt['snapshot']).read_text(encoding='utf-8'))
            after = take_project_snapshot(self.attempt_root(task, attempt))
            changes = compare_project_snapshots(before, after, attempt['files'])
            filename = 'after-' + uuid.uuid4().hex + '.json'
            (self.task_dir(task) / filename).write_text(json.dumps(after), encoding='utf-8')
            return self.append(task, 'inspection', delegation_id=attempt['event_id'], work_item=work_item,
                               snapshot=filename, **changes)

    def review(self, task: str, work_item: str, result: str, checks: Path | None = None) -> dict:
        """Record the Chief's accepted/rework/failed/blocked decision and evidence.

        result is not an outcome computed here: it is the decision the Master Chief proposes,
        passed as `task_metrics.py review --result <decision>`. review() only checks whether
        that decision may be recorded and writes it to the journal, or refuses it.

        Acceptance requires allowed edits, matching requirement checks and a green
        scoped/full run on unchanged files. "failed" means the executor returned no work
        (error, rate limit, unavailable model): it is allowed only when the attempt changed
        no files and it is not counted as a rework. This method does not call the Master
        Chief, review source code or run tests. blocked preserves partial source
        after a confirmed infrastructure interruption. Legacy tasks may have no delegation.
        """

        # A. Check the arguments and read the journal under the task lock.
        work_item = work_item.strip()
        if not work_item or result not in REVIEW_RESULTS:
            raise ValueError('Review requires a work item and accepted/rework/failed/blocked result')

        with self.lock(task):
            # B. Find the attempt this review is about, and check that the work item matches it.
            events = self.read_events_if_work_allowed(task)
            # pending delegations are those that have not been reviewed yet; we need to find the last one for this work item
            pending = pending_attempts(events, work_item)
            evidence = {}
            if pending_attempts(events) and not pending:
                raise ValueError('Review must match the pending delegated work item')
            # if the task is tracking delegations, we must have a pending delegation to review; otherwise, raise an error
            if events[0].get('track_delegations') and not pending:
                raise ValueError('Register the executor attempt with delegate before reviewing')

            if pending:
                attempt = pending[-1]
                if attempt['work_item'] != work_item:
                    raise ValueError('Review must match the pending delegated work item')

                # C. Reconstruct who changed what: executor, then reviewer after inspection. 
                # If the executor changed unexpected files, acceptance is refused.
                before = json.loads((self.task_dir(task) / attempt['snapshot']).read_text(encoding='utf-8'))
                after = take_project_snapshot(self.attempt_root(task, attempt))
                # inspections are the inspection events for this attempt; 
                # we need the last one to get the reviewer's changes
                inspections = [e for e in events if e['kind'] == 'inspection' and
                               e['delegation_id'] == attempt['event_id']]
                # compare function may create unexpected changes if the executor changed files that were not allowed; we need to check for that
                changes = compare_project_snapshots(before, after, attempt['files'])

                if inspections:
                    inspected = inspections[-1]
                    changes = {k: inspected[k] for k in ('changed', 'unexpected')}
                    inspected_snapshot = json.loads((self.task_dir(task) / inspected['snapshot']).read_text(encoding='utf-8'))
                    subsequent = compare_project_snapshots(inspected_snapshot, after, [])['changed']
                    changes['reviewer_changes'] = subsequent
                    if result == 'accepted' and any(p in attempt['files'] for p in subsequent):
                        raise ValueError('Delegated source changed after inspection; register a fresh attempt')
                    
                elif result == 'accepted' and events[0].get('track_delegations'):
                    raise ValueError('Run inspect immediately after the executor returns, before reviewer edits')
                
                evidence = dict(delegation_id=attempt['event_id'], **changes)

                # D. Rules for blocked and failed
                if result == 'blocked':
                    ended = [e for e in events if e['kind'] == 'attempt_end'
                             and e.get('delegation_id') == attempt['event_id']]
                    if not ended or not ended[-1].get('stopped') or ended[-1]['reason'] not in ('api_error', 'rate_limit', 'setup_error', 'paused', 'cancelled'):
                        raise ValueError('Blocked requires a confirmed infrastructure interruption')
                    evidence['reason'] = ended[-1]['reason']

                if result == 'failed' and changes['changed']:
                    raise ValueError('The executor changed files: review the attempt as accepted or rework, '
                                     'not failed: ' + ', '.join(changes['changed']))

                # E. Rules for accepted: no foreign edits, full evidence, green test on these files
                if result == 'accepted':
                    if changes['unexpected']:
                        raise ValueError('Executor changed unexpected files: ' + ', '.join(changes['unexpected']))
                    # check that the review checks cover every recorded requirement exactly once
                    if checks is None:
                        raise ValueError('Acceptance needs --checks with requirement/code/test evidence')
                    evidence['checks'] = review_checks(self.root / checks)
                    # validate that the review checks cover every recorded requirement exactly once
                    if attempt.get('requirements') and (
                            len(evidence['checks']) != len(attempt['requirements']) or
                            {c['requirement'] for c in evidence['checks']} != set(attempt['requirements'])):
                        raise ValueError('Review checks must cover every recorded requirement exactly once')
                    anchor = inspections[-1] if inspections else attempt

                    # find all test runs after the delegation (or inspection) for this scope, ignoring baseline runs
                    runs = [e for e in events[events.index(anchor) + 1:] if e['kind'] == 'test'
                            and e.get('phase') != 'baseline'
                            and e.get('scope', 'full') in {attempt['scope'], 'full'}
                            and (e.get('delegation_id') == attempt['event_id'] if attempt.get('workspace')
                                 else not e.get('delegation_id'))]
                    # check that the last test run after delegation was green; if not, the tests must be rerun before acceptance
                    if not runs or runs[-1]['status'] != 'passed':
                        raise ValueError('Acceptance needs a green test run for this scope after delegation')
                    # check that the project files have not changed since the last green test run; if they have, the tests must be rerun before acceptance
                    tested = json.loads((self.task_dir(task) / runs[-1]['snapshot']).read_text(encoding='utf-8'))
                    if compare_project_snapshots(tested, after, [])['changed']:
                        raise ValueError('Project files changed since the green test; rerun tests before acceptance')

            # F. Record the decision with its evidence, then check the loop guards 
            if result == 'blocked' and not pending:
                raise ValueError('Blocked requires an isolated attempt')
            event = self.append(task, 'review', work_item=work_item, result=result, **evidence)
            halt = self.guard(task, events + [event])
            return dict(event, halt=halt['reason']) if halt else event

    def resume(self, task: str, reason: str) -> dict:
        """
        Lifts a stop after the user's decision. The reason is kept in the journal and the report.
        Every loop guard counts from zero again after this event.
        """
        if not reason.strip():
            raise ValueError('Resume requires a reason: what the user decided')
        with self.lock(task):
            events = self.read_events_if_not_finished(task)
            if not is_halted(events):
                raise ValueError('Task is not stopped; nothing to resume')
            return self.append(task, 'resume', reason=reason.strip())

    def ux_review(self, task: str, checks: Path | None = None, skipped: str | None = None,
                  not_applicable: str | None = None) -> dict:
        """Record the final UI/UX improvement stage of the Master Chief.

        Exactly one outcome is required:
        - checks: a JSON list of interactive scenarios that were really performed, each
          {"scenario": ..., "actions": ..., "result": ...} with an optional "fixed"
          description of an interface change made because of it;
        - skipped: why the stage could not be performed (no browser, no display, ...);
        - not_applicable: why the product has no user interface to improve.
        All executor attempts must already have a recorded review. The latest event
        counts; an earlier skip can be replaced by a later completed review.
        """
        given = [value for value in (checks, skipped, not_applicable) if value is not None]
        if len(given) != 1:
            raise ValueError('ux-review needs exactly one of --checks, --skipped or --not-applicable')
        data = {}
        if checks is not None:
            try:
                rows = json.loads((self.root / checks).read_text(encoding='utf-8-sig'))
            except (OSError, ValueError) as error:
                raise ValueError(f'Cannot read UI/UX checks {checks}: {error}') from error
            if not isinstance(rows, list) or not rows:
                raise ValueError('UI/UX checks must be a non-empty JSON list of scenarios')
            clean = []
            for index, row in enumerate(rows, 1):
                if not isinstance(row, dict):
                    raise ValueError(f'UI/UX check {index} must be an object')
                item = {}
                for key in ('scenario', 'actions', 'result'):
                    value = row.get(key)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(f'UI/UX check {index} needs a non-empty "{key}"')
                    item[key] = value.strip()
                fixed = row.get('fixed')
                if fixed is not None:
                    if not isinstance(fixed, str):
                        raise ValueError(f'UI/UX check {index}: "fixed" must be text')
                    if fixed.strip():
                        item['fixed'] = fixed.strip()
                from kit.browser_evidence import validate_browser_evidence
                item['browser_evidence'] = validate_browser_evidence(self.root, task, row.get('browser_evidence'))
                observation = row.get('visual_observation')
                if not isinstance(observation, str) or not observation.strip():
                    raise ValueError('A completed UX scenario needs a visual_observation from its screenshot.')
                item['visual_observation'] = observation.strip()
                clean.append(item)
            data = dict(outcome='completed', checks=clean, scenarios=len(clean),
                        fixed=sum('fixed' in item for item in clean))
        else:
            reason = (skipped if skipped is not None else not_applicable).strip()
            if not reason:
                raise ValueError('A skipped or not applicable UI/UX stage needs a reason')
            if len(reason) > UX_REASON_LIMIT:
                raise ValueError(f'The UI/UX reason is longer than {UX_REASON_LIMIT} characters')
            data = dict(outcome='skipped' if skipped is not None else 'not_applicable', reason=reason)
        with self.lock(task):
            reason = blocking_reason(self.root, task)
            if reason:
                raise TaskHalted(reason)
            events = self.read_events_if_not_finished(task)
            if pending_attempts(events):
                raise ValueError('Record a review for every executor attempt before the UI/UX stage')
            return self.append(task, 'ux_review', **data)


    # run a test command for a task, capturing its output and return code, and optionally parsing JUnit XML reports
    def test(self, task: str, command: list[str], timeout: float = 300, junit: str | None = None,
             junit_dir: str | None = None, scope: str = 'full', phase: str = 'work', attempt_id: str | None = None) -> dict:
        if not scope.strip() or phase not in {'work', 'baseline'}:
            raise ValueError('Provide a non-empty scope and work/baseline phase')
        scope = scope.strip()
        with self.lock(task):
            events = self.read_events_if_work_allowed(task)
            runner, binding = self, {}
            if attempt_id:
                candidates = [e for e in pending_attempts(events) if e['event_id'] == attempt_id and e.get('workspace')]
                if len(candidates) != 1 or scope != candidates[0]['scope']:
                    raise ValueError('Tests must match one open isolated attempt and its scope')
                runner = TaskMetrics(self.attempt_root(task, candidates[0]))
                binding['delegation_id'] = attempt_id
            elif any(e.get('workspace') for e in pending_attempts(events)):
                raise ValueError('Use --attempt while isolated workers await review')
            xml, folder = runner.report_source(junit, junit_dir)
            if phase == 'baseline' and any(
                    (e['kind'] == 'delegation' and e.get('scope') == scope) or
                    (e['kind'] == 'test' and e.get('scope', 'full') == scope) for e in events):
                raise ValueError('Baseline is allowed only once per scope, before its delegations and tests')
            evidence = {}
            if pending_attempts(events) or any(e['kind'] == 'integration' for e in events):
                filename = 'tested-' + uuid.uuid4().hex + '.json'
                (self.task_dir(task) / filename).write_text(json.dumps(take_project_snapshot(runner.root)), encoding='utf-8')
                evidence['snapshot'] = filename
            started = time.monotonic()
            output, code, parsed, category = runner.execute(command, timeout, xml, folder)
            log = 'test-' + uuid.uuid4().hex + '.log'
            (self.task_dir(task) / log).write_text(output, encoding='utf-8')
            hints = diagnose(output, code, parsed, category, bool(xml or folder))
            event = self.append(task, 'test', command=command, returncode=code, log=log, scope=scope, phase=phase,
                                duration_seconds=time.monotonic()-started, category=category,
                                 **({'hints': hints} if hints else {}), **binding, **evidence, **parsed)
            halt = self.guard(task, events + [event])
            return dict(event, halt=halt['reason']) if halt else event

    def check(self, command: list[str], timeout: float = 300, junit: str | None = None,
              junit_dir: str | None = None) -> dict:
        """
        Dry run of the test command without a task: can the runner read its results?

        Used once when the kit is connected to a project and before each implementation task.
        A single JUnit file written by the check is removed, so the same name can be used again.
        """
        xml, folder = self.report_source(junit, junit_dir)
        output, code, parsed, category = self.execute(command, timeout, xml, folder)
        if xml is not None and xml.exists():
            xml.unlink()
        readable = category in {CATEGORY_PASSED, CATEGORY_FAILED, CATEGORY_INCOMPLETE}
        return dict(readable=readable, category=category, returncode=code, output=output,
                    hints=diagnose(output, code, parsed, category, bool(xml or folder)), **parsed)


    # it is our final step to finish a task, collect exports, parse usage, and write a Markdown report to report.md in the task directory
    def finish(self, task: str, export_paths: list[str] | None = None, executable: str = 'opencode', language: str | None = None) -> str:
        if __package__:
            from .localization import load_language
        else:
            from localization import load_language
        language = language or load_language(self.root)
        with self.lock(task):
            reason = blocking_reason(self.root, task)
            if reason:
                raise TaskHalted(reason)
            events = self.read(task)
            finished = next((e for e in events if e['kind'] == 'finish'), None)
            isolated = [e for e in events if e['kind'] == 'delegation' and e.get('workspace')]
            if isolated and not finished:
                if pending_attempts(events):
                    raise ValueError('Resolve all isolated attempts before finish')
                integrated = {e['delegation_id'] for e in events if e['kind'] == 'integration'}
                accepted = {e['delegation_id'] for e in events if e['kind'] == 'review' and e['result'] == 'accepted'}
                if any(e['event_id'] in accepted and e['event_id'] not in integrated for e in isolated):
                    raise ValueError('Integrate accepted isolated attempts before finish')
                latest = {e['work_item']: e for e in isolated}
                if any(e['event_id'] not in accepted & integrated for e in latest.values()):
                    raise ValueError('Every isolated work item needs an accepted, integrated latest attempt')
                runs = [e for e in events if e['kind'] == 'test' and e.get('scope') == 'full' and not e.get('delegation_id')]
                if (not runs or runs[-1]['status'] != 'passed' or not runs[-1].get('snapshot')
                        or compare_project_snapshots(json.loads((self.task_dir(task)/runs[-1]['snapshot']).read_text(encoding='utf-8')),
                                   take_project_snapshot(self.root), [])['changed']):
                    raise ValueError('Finish needs a green full test of the integrated project')
            if (not finished and events[0].get('ux_review_required')
                    and not any(e['kind'] == 'ux_review' for e in events)):
                raise ValueError('Record the UI/UX improvement stage with ux-review before finish: '
                                 '--checks <file>, --skipped "<reason>" or --not-applicable "<reason>"')
            if finished:
                report = self.render(task, events, finished['usage'], finished['ended'], language)
            else:
                ended = time.time()
                usage = dict(models=[], warnings=[], sessions=[])
                try:
                    session = events[0]['session']
                    if not session:
                        raise ValueError('Нет ID сессии OpenCode: токены — нет данных.')
                    exports = ([json.loads((self.root / p).read_text(encoding='utf-8-sig')) for p in export_paths]
                               if export_paths else self.collect_exports(session, executable))
                    usage = self.parse_exports(exports, session, events[0]['at'], ended)
                except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
                    usage['warnings'].append(f'Токены — нет данных: {error}')
                # Journal first: report-write failure can be retried without recounting.
                self.append(task, 'finish', ended=ended, usage=usage)
                report = self.render(task, events, usage, ended, language)
            folder = self.task_dir(task)
            tmp = folder / ('report-'+uuid.uuid4().hex+'.tmp')
            tmp.write_text(report, encoding='utf-8')
            tmp.replace(folder/'report.md')
            return report

def launch_task_dashboard(root: Path, task: str, open_browser: bool) -> dict:
    """Launch from the CLI only; importing/using TaskMetrics stays side-effect free."""
    if __package__:
        from .dashboard.launcher import ensure_dashboard
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from kit.dashboard.launcher import ensure_dashboard
    return ensure_dashboard(root, task, open_browser=open_browser)


def main(argv=None) -> int:
    """
    Command line. Exit codes tell the Master Chief what to do next:
    0 passed or done; 1 tests ran and failed; 4 no readable test result (setup or build);
    3 STOP: a loop guard is reached, ask the user; 2 wrong usage or a broken journal.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    args = build_parser().parse_args(argv)
    metrics = TaskMetrics(args.root)
    try:
        if args.action == 'start':
            limits = {name: getattr(args, name) for name in DEFAULT_LIMITS}
            event = metrics.start(args.task, args.session, args.title, limits, args.track_delegations)
            if (not args.no_dashboard and os.environ.get('OPENCODE_KIT_DASHBOARD', '').lower() not in ('off', '0')
                    and any((metrics.root / name).is_file() for name in ('opencode.jsonc', 'pi-kit.json'))
                    and (metrics.root / 'kit').is_dir()):
                try:
                    dashboard = launch_task_dashboard(metrics.root, args.task, not args.no_browser)
                    if not args.no_browser and not dashboard['opened']:
                        print('Dashboard browser did not open: ' + dashboard['url'], file=sys.stderr)
                except (OSError, ValueError, RuntimeError) as error:
                    dashboard = {'status': 'unavailable', 'error': str(error)}
                    print('Dashboard unavailable; task journal was saved: ' + str(error), file=sys.stderr)
                event = dict(event, dashboard=dashboard)
        elif args.action == 'review':
            event = metrics.review(args.task, args.work_item, args.result, args.checks)
        elif args.action == 'delegate':
            event = metrics.delegate(args.task, args.work_item, args.files, args.scope, args.requirements)
        elif args.action == 'inspect':
            event = metrics.inspect(args.task, args.work_item)
        elif args.action == 'resume':
            event = metrics.resume(args.task, args.reason)
        elif args.action == 'ux-review':
            event = metrics.ux_review(args.task, args.checks, args.skipped, args.not_applicable)
        elif args.action == 'finish':
            print(metrics.finish(args.task, args.exports, args.opencode, args.language))
            return EXIT_OK
        elif args.action == 'check':
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            result = metrics.check(command, args.timeout, args.junit, args.junit_dir)
            print(result.pop('output'))
            print(json.dumps(result, ensure_ascii=False))
            if result['readable']:
                print(f'CHECK OK: the runner reads results ({result["tests"]} tests).', file=sys.stderr)
                return EXIT_OK
            print('CHECK FAILED: the runner cannot read test results.', file=sys.stderr)
            for hint in result['hints']:
                print('- ' + hint, file=sys.stderr)
            return EXIT_NO_RESULT
        else:
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            event = metrics.test(args.task, command, args.timeout, args.junit, args.junit_dir, args.scope, args.phase, args.attempt)
            print((metrics.task_dir(args.task)/event['log']).read_text(encoding='utf-8'))
            print(json.dumps(event, ensure_ascii=False))
            return report_test(event, args.task)
        print(json.dumps(event, ensure_ascii=False))
        if args.action == 'inspect' and event['unexpected']:
            print('UNEXPECTED EDITS: record rework and inspect these files: ' +
                  ', '.join(event['unexpected']), file=sys.stderr)
            return EXIT_TESTS_FAILED
        if event.get('halt'):
            print_stop(event['halt'], args.task)
            return EXIT_STOP
        return EXIT_OK
    except TaskHalted as halt:
        print_stop(str(halt), args.task)
        return EXIT_STOP
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f'Metrics error: {error}', file=sys.stderr)
        return EXIT_USAGE


def report_test(event: dict, task: str) -> int:
    """Prints what the Master Chief should do after a test run and returns the exit code."""
    if event.get('halt'):
        print_stop(event['halt'], task)
        return EXIT_STOP
    category = event['category']
    if category == CATEGORY_PASSED:
        return EXIT_OK
    if category in {CATEGORY_FAILED, CATEGORY_INCOMPLETE}:
        print('TESTS FAILED: the tests ran. Read the failures: send the work item back to the executor '
              '(review --result rework) or fix the tests if they contradict the spec.', file=sys.stderr)
        return EXIT_TESTS_FAILED
    print('NO RESULT: the tests did not produce a readable result. Usually this is a setup or build '
          'problem, not an executor mistake. Record a rework only if the log shows a compile error in '
          'code the executor just wrote; otherwise fix the setup or ask the user.', file=sys.stderr)
    for hint in event.get('hints', []):
        print('- ' + hint, file=sys.stderr)
    return EXIT_NO_RESULT


def print_stop(reason: str, task: str) -> None:
    """The STOP message. The Master Chief must end the loop and wait for the user's decision."""
    print(f'STOP: {reason}', file=sys.stderr)
    print('Do not run more tests and do not send more reworks. Tell the user what happened and what '
          'you suggest, then wait. Continue only after the user decides, with: '
          f'task_metrics.py resume --task {task} --reason "<the user\'s decision>"', file=sys.stderr)


if __name__ == '__main__':
    sys.exit(main())
