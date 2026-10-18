"""Token usage from OpenCode session exports and the final Markdown task report.

collect_exports() asks the OpenCode CLI for the root session and every child session
(executors run in child sessions); parse_exports() sums tokens per provider/model;
render() turns the journal and that usage into report.md.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

if __package__:
    from .journal import session_id, valid_number
    from .opencode_cli import locate_opencode
    from .suite_runner import CATEGORY_NO_RESULT, CATEGORY_TIMEOUT
    from .runtime_selection import uses_pi_runtime
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from journal import session_id, valid_number
    from opencode_cli import locate_opencode
    from suite_runner import CATEGORY_NO_RESULT, CATEGORY_TIMEOUT
    from runtime_selection import uses_pi_runtime

TOKEN_FIELDS = ('input', 'output', 'reasoning', 'cache_read', 'cache_write')


def message_info(message):
    """V2 messages are direct objects; legacy messages wrap data in info/parts."""
    if not isinstance(message, dict):
        raise ValueError('Unsupported message structure')
    info = message.get('info', message)
    if not isinstance(info, dict):
        raise ValueError('Unsupported message info')
    return info


def master_chief_tool_child_references(export):
    """Find child sessions that the Master Chief started through its tools.

    When the Master Chief calls an executor, OpenCode runs the executor in a separate
    child session. Its messages and tokens are not part of the Master Chief's export,
    so the report must find every child to count all usage.

    The main source of children is the OpenCode API (session.list, see
    collect_exports). This function is the fallback: it scans tool parts of the
    export for state.metadata.sessionID (or sessionId). Session IDs are taken
    only from tool metadata, never from text written by a model.

    Returns a set of session IDs.
    """
    found = set()
    for message in export['messages']:
        message_info(message)
        for part in message.get('parts', message.get('content', [])):
            if not isinstance(part, dict) or part.get('type') != 'tool':
                continue
            metadata = part.get('state', {}).get('metadata', {})
            if isinstance(metadata, dict):
                for key in ('sessionID', 'sessionId'):
                    if metadata.get(key):
                        found.add(session_id(metadata[key]))
    return found


def resolve_opencode(executable: str) -> str:
    """Find the OpenCode CLI (order in kit/opencode_cli.py).

    Reading exports only needs plain arguments, so a .cmd wrapper on PATH is still accepted
    as the last resort. Unknown names are returned as is.
    """
    return locate_opencode(executable) or shutil.which(executable) or executable


def descendants(sessions: dict, root: str) -> set[str]:
    """Returns root and every session below it (children, grandchildren, ...)."""
    allowed = {root}
    while True:
        more = {sid for sid, items in sessions.items() if items[0]['info'].get('parentID') in allowed}
        if more <= allowed:
            return allowed
        allowed |= more


def text_or_unknown(value) -> str:
    """Returns a non-empty string as is, anything else as 'unknown'."""
    return value if isinstance(value, str) and value else 'unknown'


def message_model(info: dict) -> tuple[str, str]:
    """Provider and model of one assistant message, in the legacy or the V2 format."""
    model_ref = info.get('model') if isinstance(info.get('model'), dict) else {}
    provider = info.get('providerID', model_ref.get('providerID'))
    model = info.get('modelID', model_ref.get('id'))
    return text_or_unknown(provider), text_or_unknown(model)


def new_usage_row(provider: str, model: str) -> dict:
    """An empty report row for one provider/model pair."""
    if provider == 'lmstudio':
        group = 'local'
    elif (provider == 'openrouter' and model.endswith(':free')) or (provider == 'opencode' and model.endswith('-free')):
        # OpenRouter marks its zero-price variants with ":free" (rate limited, no API fee).
        group = 'free'
    elif provider == 'unknown':
        group = 'unknown'
    else:
        group = 'paid'
    return dict(provider=provider, model=model, group=group, messages=0, missing_usage=0,
                known=dict.fromkeys(TOKEN_FIELDS, 0), known_messages=dict.fromkeys(TOKEN_FIELDS, 0),
                **dict.fromkeys(TOKEN_FIELDS, 0))


def message_tokens(info: dict) -> dict:
    """Five token counters of one message; a missing or invalid counter becomes None."""
    tokens = info.get('tokens') if isinstance(info.get('tokens'), dict) else {}
    cache = tokens.get('cache') if isinstance(tokens.get('cache'), dict) else {}
    values = dict(input=tokens.get('input'), output=tokens.get('output'), reasoning=tokens.get('reasoning'),
                  cache_read=cache.get('read'), cache_write=cache.get('write'))
    return {k: v if type(v) is int and v >= 0 else None for k, v in values.items()}


def add_usage(row: dict, values: dict) -> None:
    """Adds one message to a row. One unknown value makes that column's sum unknown for good."""
    row['messages'] += 1
    row['missing_usage'] += int(values['input'] is None or values['output'] is None)
    for field, value in values.items():
        if value is not None:
            row['known'][field] += value
            row['known_messages'][field] += 1
        row[field] = None if value is None or row[field] is None else row[field] + value


class UsageReportMixin:
    """Usage and report methods of TaskMetrics; they need only self.root (the project root)."""

    # parse OpenCode exports for a task, filtering messages by time and collecting token usage statistics
    def parse_exports(self, exports: list[dict], session: str, since: float, until: float) -> dict:
        sessions = {}
        for export in exports:
            if (not isinstance(export, dict) or not isinstance(export.get('info'), dict) or
                    not isinstance(export.get('messages'), list)):
                raise ValueError('Unsupported OpenCode export: expected info and messages')
            sid = session_id(export['info'].get('id'))
            sessions.setdefault(sid, []).append(export)

        if session not in sessions:
            raise ValueError('Root session export is missing')
        allowed = descendants(sessions, session)

        warnings_list = []
        for sid in sessions.keys() - allowed:
            warnings_list.append(f'Посторонняя сессия исключена: {sid}')
        rows, seen, session_rows = {}, {}, {}

        for sid in sorted(allowed):
            for export in sessions[sid]:
                warnings_list.extend(export.get('_metrics_warnings', []))
                for child in master_chief_tool_child_references(export) - allowed:
                    warnings_list.append(f'Нет выгрузки дочерней сессии: {child}')
                for message in export['messages']:
                    info = message_info(message)
                    if info.get('role', info.get('type')) != 'assistant':
                        continue
                    mid = info.get('id')
                    stamp = info.get('time', {})
                    if not isinstance(stamp, dict) or not isinstance(mid, str) or not valid_number(stamp.get('created')):
                        warnings_list.append(f'Пропущено сообщение без ID/времени: {sid}')
                        continue
                    if not since <= stamp['created']/1000 <= until:
                        continue
                    if not valid_number(stamp.get('completed')) or stamp['completed']/1000 > until:
                        warnings_list.append('Незавершённые на момент отчёта сообщения не включены.')
                        continue
                    key = (sid, mid)
                    if key in seen:
                        if seen[key] != info:
                            raise ValueError(f'Conflicting duplicate message: {sid}/{mid}')
                        continue
                    seen[key] = info
                    provider, model = message_model(info)
                    row = rows.setdefault((provider, model), new_usage_row(provider, model))
                    add_usage(row, message_tokens(info))
                    per_session = session_rows.setdefault((sid, provider, model), dict(new_usage_row(provider, model), session=sid, cost_usd=0))
                    add_usage(per_session, message_tokens(info))
                    cost = info.get('cost')
                    per_session['cost_usd'] = (per_session['cost_usd'] + cost
                        if per_session['cost_usd'] is not None and valid_number(cost) else None)
        warnings_list.append('Учтены сообщения в интервале задачи; служебные вызовы вне экспорта могут отсутствовать.')
        if any(r['missing_usage'] for r in rows.values()):
            warnings_list.append('В части сообщений нет корректного расхода токенов; соответствующие суммы неизвестны.')
        return dict(models=list(rows.values()), warnings=list(dict.fromkeys(warnings_list)), sessions=sorted(allowed),
                    session_usage=list(session_rows.values()))

    # run an OpenCode CLI command and parse its JSON output, raising an error if the command fails or returns non-JSON output
    # for instance: opencode session export ses_abc123
    # it will execute the command and return the parsed JSON output, or raise a ValueError if the command fails or returns invalid JSON
    # this command is used to collect exports for a session and its children, which are then parsed to generate a usage report
    # opencode runs this command and returns the JSON output, which is then processed by collect_exports to gather all relevant data for the task
    def cli_json(self, executable: str, args: list[str]):
        result = subprocess.run([executable, *args], cwd=self.root, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        if result.returncode:
            raise ValueError(f'OpenCode {args[0]} failed (exit {result.returncode})')
        try:
            return json.loads(result.stdout.lstrip('\ufeff'))
        except ValueError as error:
            raise ValueError('OpenCode returned non-JSON output; check CLI version/server') from error

    def export_session(self, executable: str, sid: str) -> dict:
        """Export one session, trying the newer CLI command before the legacy one."""
        if uses_pi_runtime(self.root):
            from kit.runtimes.pi_gateway import PiSessionControl
            return PiSessionControl(self.root).export_session(sid)
        try:
            export = self.cli_json(executable, ['session', 'export', sid])
        except ValueError:
            export = self.cli_json(executable, ['export', sid])
        if not isinstance(export, dict) or export.get('info', {}).get('id') != sid:
            raise ValueError('Export session ID mismatch')
        if not isinstance(export.get('messages'), list):
            raise ValueError('Export messages missing')
        return export

    def api_children(self, executable: str, sid: str, children: set[str] | None = None) -> set[str]:
        """Read child sessions, preserving discovered IDs in the supplied set on failure."""
        if children is None:
            children = set()
        cursor, cursors = None, set()
        for _ in range(100):
            args = ['api', 'session.list', '--param', f'parentID={sid}', '--param', 'limit=100']
            if cursor:
                args += ['--param', f'cursor={cursor}']
            page = self.cli_json(executable, args)
            if not isinstance(page, dict) or not isinstance(page.get('data'), list):
                raise ValueError('Unsupported session.list response')
            for item in page['data']:
                if not isinstance(item, dict) or item.get('parentID') != sid:
                    raise ValueError('Child session parent mismatch')
                children.add(session_id(item.get('id')))
            cursor = page.get('cursor', {}).get('next')
            if not cursor:
                return children
            if cursor in cursors:
                raise ValueError('Repeated pagination cursor')
            cursors.add(cursor)
        raise ValueError('Too many session pages')

    # collect OpenCode exports for a session and its children, using the CLI to fetch data and handling pagination and errors
    def collect_exports(self, session: str, executable: str = 'opencode') -> list[dict]:
        session_id(session)
        if uses_pi_runtime(self.root):
            from kit.runtimes.pi_gateway import collect_session_exports
            return collect_session_exports(self.root, session)
        executable = resolve_opencode(executable)
        queue, seen, exports = [session], set(), []
        while queue:
            sid = session_id(queue.pop(0))
            if sid in seen:
                continue
            if len(seen) >= 100:
                raise ValueError('More than 100 sessions; narrow task scope')
            seen.add(sid)
            try:
                export = self.export_session(executable, sid)
                children = master_chief_tool_child_references(export)
                try:
                    self.api_children(executable, sid, children)
                except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                    export['_metrics_warnings'] = [f'Поиск дочерних сессий неполон: {error}']
                queue.extend(sorted(children - seen))
                exports.append(export)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ValueError(f'Cannot collect OpenCode session {sid}: {error}') from error
        return exports

    # We print a Markdown report for a task, summarizing its events, usage statistics, and test results
    # The report includes sections for paid models, local models, and unknown providers, as well as counts of reviews and test outcomes.
    def render(self, task: str, events: list[dict], usage: dict, ended: float, language: str = 'ru') -> str:
        """Render frozen facts in one language; never translate task or worker text."""
        if __package__:
            from . import localization
        else:
            import localization
        def t(key, **values):
            return localization.text(key, language, **values)
        def label(value):
            return str(value).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ').replace('<', '&lt;').replace('>', '&gt;')
        def count(value):
            return t('no data') if value is None else f'{value:,}'.replace(',', ' ' if language == 'ru' else ',')
        duration = max(0, int(ended - events[0]['at']))
        reviews = [e for e in events if e['kind'] == 'review']
        tests = [e for e in events if e['kind'] == 'test']
        lines = [t('## 📊 Task report · {title}', title=label(events[0]['title'])), '',
                 t('⏱ Time: **{minutes} min {seconds} sec**', minutes=duration // 60, seconds=duration % 60), '']
        for group, heading in [('paid', 'Paid models'), ('local', 'Free / local · LM Studio'),
                               ('free', 'Free cloud · OpenRouter / OpenCode'), ('unknown', 'Unknown provider')]:
            rows = [r for r in usage['models'] if r['group'] == group]
            if group in ('free', 'unknown') and not rows:
                continue
            lines += ['### ' + t(heading), '']
            if not rows:
                lines += [t('No calls recorded for this group in the selected interval.'), '']
                continue
            lines += [t('| Model | Input | Output | Reasoning | Cache: read | Cache: write |'), '|---|---:|---:|---:|---:|---:|']
            for row in rows:
                lines.append('| ' + label(row['provider'] + '/' + row['model']) + ' | ' +
                             ' | '.join(count(row[f]) for f in TOKEN_FIELDS) + ' |')
            lines.append('')
        work_tests = [e for e in tests if e.get('phase') != 'baseline']
        lines += [t('🔁 Rework requests: **{reworks}** · Reviews recorded: **{reviews}**',
                    reworks=sum(e['result'] == 'rework' for e in reviews), reviews=len(reviews)), '']
        failed_attempts = sum(e['result'] == 'failed' for e in reviews)
        blocked_attempts = sum(e['result'] == 'blocked' for e in reviews)
        if blocked_attempts:
            lines += [t('Infrastructure interruptions: **{count}**. Partial source is preserved; code repair budgets are unchanged.', count=blocked_attempts), '']
        if failed_attempts:
            lines += [t('⚠️ Executor failures without a result (error, limit, unavailable model): **{count}**. These are not reworks: no files changed.', count=failed_attempts), '']
        lines += [t('🧪 Fully successful runs: **{passed} of {total}**', passed=sum(e['status'] == 'passed' for e in work_tests), total=len(work_tests)), '']
        if len(work_tests) != len(tests):
            lines += [t('Initial checks before implementation (baseline): **{count}**; excluded from successful work runs.', count=len(tests) - len(work_tests)), '']
        full = [e for e in tests if e.get('scope', 'full') == 'full' and e.get('phase') != 'baseline']
        lines += [t('Full suite: **{passed} of {total}**. Other runs may cover a selected class or module.', passed=sum(e['status'] == 'passed' for e in full), total=len(full)), '']
        ux = next((e for e in reversed(events) if e['kind'] == 'ux_review'), None)
        if ux and ux.get('outcome') == 'completed':
            lines += [t('🎨 UI/UX improvement stage completed: {scenarios} scenarios checked, {fixed} issues fixed.',
                        scenarios=ux.get('scenarios', 0), fixed=ux.get('fixed', 0)), '']
            for item in ux.get('checks', []):
                line = '- ' + label(item['scenario']) + ' — ' + label(item['result'])
                if item.get('fixed'):
                    line += ' ' + t('(fixed: {change})', change=label(item['fixed']))
                lines.append(line)
            lines.append('')
        elif ux and ux.get('outcome') == 'skipped':
            lines += [t('🎨 UI/UX improvement stage skipped due to {reason}.', reason=label(ux['reason'])), '']
        elif ux and ux.get('outcome') == 'not_applicable':
            lines += [t('🎨 UI/UX improvement stage not required: {reason}.', reason=label(ux['reason'])), '']
        attempts = [e for e in events if e['kind'] == 'delegation']
        if attempts or events[0].get('track_delegations'):
            closed = {e.get('delegation_id') for e in reviews}
            pending = [e['work_item'] for e in attempts if e['event_id'] not in closed]
            lines += [t('Executor assignments registered: **{total}** · without a recorded review: **{pending}**.', total=len(attempts), pending=len(pending)), '']
            if pending:
                lines += [t('⚠️ Pending reviews: {items}.', items=', '.join(label(p) for p in pending)), '']
        if not full or full[-1]['status'] != 'passed':
            lines += [t('⚠️ The latest full run failed or is missing; overall readiness is unconfirmed.'), '']
        no_result = [e for e in tests if e.get('category') in {CATEGORY_NO_RESULT, CATEGORY_TIMEOUT}]
        if no_result:
            lines += [t('⚙️ Runs without a readable result (build, environment or timeout): **{count}**. These are not executor errors.', count=len(no_result)), '']
        halts = [e for e in events if e['kind'] == 'halt']
        if halts:
            resumes = [e for e in events if e['kind'] == 'resume']
            lines += [t('⛔ Protective stops: **{stops}** · resumes after user decisions: **{resumes}**', stops=len(halts), resumes=len(resumes)), '']
            lines += [t('- Stop: {reason}', reason=label(e['reason'])) for e in halts]
            lines += [t('- Resume: {reason}', reason=label(e['reason'])) for e in resumes]
            lines.append('')
        if tests:
            last = tests[-1]
            lines += [t('Last run: **{status}** · tests: {tests} · failures: {failures} · errors: {errors} · skipped: {skipped}.',
                        status=label(last['status']), **{key: count(last[key]) for key in ('tests', 'failures', 'errors', 'skipped')}), '']
        else:
            lines += [t('No tests were run through the utility; success is unconfirmed.'), '']
        bindings = [e for e in events if e['kind'] == 'attempt_session']
        if bindings:
            lines += [t('### Usage by attempt (included in the total)'), '',
                      t('| Role / worker | Attempt | Actual model | Input | Output | Cost USD |'), '|---|---|---|---:|---:|---:|']
            for binding in bindings:
                rows = [row for row in usage.get('session_usage', []) if row['session'] == binding['session']]
                totals = {field: sum(row[field] for row in rows) if rows and all(row[field] is not None for row in rows) else None
                          for field in ('input', 'output', 'cost_usd')}
                models = ', '.join(row['provider'] + '/' + row['model'] for row in rows) or t('no data')
                cost = t('no data') if totals['cost_usd'] is None else f'{totals["cost_usd"]:.6f}'
                lines.append(f'| {label(binding["role"])} / {label(binding["worker_id"])} | {label(binding["delegation_id"])} | '
                             f'{label(models)} | {count(totals["input"])} | {count(totals["output"])} | {cost} |')
            lines += ['', t('This breakdown is not added to the total again. Missing cost remains unknown.'), '']
        lines += [t('Time is measured from `start` to `finish`; earlier work is excluded.'),
                  t('Reviews and assignments follow the journal; unregistered actions cannot be detected.'),
                  t('All `lmstudio` models have no API fee; OpenRouter `:free` and OpenCode `-free` models are free cloud models; other known providers are classified as paid by default.'),
                  t('Reasoning and cache tokens are shown separately without adding overlapping counters.'),
                  t('Snapshot taken before the final answer; its tokens are excluded. Catalog-based cost and savings were not calculated.'), '']
        if usage['warnings']:
            warnings = []
            for warning in usage['warnings']:
                if warning.startswith('Токены — нет данных: '):
                    warning = t('Tokens unavailable: {reason}', reason=localization.diagnostic(warning.split(': ', 1)[1], language))
                else:
                    warning = localization.diagnostic(warning, language)
                warnings.append('- ' + label(warning))
            lines += [t('Notes:'), ''] + warnings + ['']
        return '\n'.join(lines)
