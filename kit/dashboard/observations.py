"""Non-blocking OpenCode observations for the operational page, never reasoning text."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import time

from ..task_metrics import TaskMetrics, TOKEN_FIELDS, message_info, message_model, valid_number
from ..provider_limits import quota_error


class ObservedMetrics(TaskMetrics):
    def cli_json(self, executable: str, args: list[str]):
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        result = subprocess.run([executable, *args], cwd=self.root, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10, **options)
        if result.returncode:
            raise ValueError('OpenCode session data is unavailable')
        try:
            return json.loads(result.stdout.lstrip('\ufeff'))
        except ValueError as error:
            raise ValueError('OpenCode returned an unreadable session') from error


def display_models(root: Path) -> dict:
    """Configured references only, not proof of what a session actually used."""
    from ..runtime_selection import uses_pi_runtime
    if uses_pi_runtime(root):
        choices_path = root / '.pi/kit-models.json'
    else:
        choices_path = root / '.opencode/kit-models.json'
    # Display saved references even when a provider key is not available yet.
    choices = json.loads(choices_path.read_text(encoding='utf-8-sig')) if choices_path.is_file() else {}
    if not isinstance(choices, dict):
        raise ValueError('Saved model choices must contain an object')
    result = {}
    for role, field in (('master_chief', 'masterChief'), ('executor', 'executors'), ('bug_fixer', 'bugFixer')):
        choice = choices.get(field)
        if isinstance(choice, dict) and isinstance(choice.get('model'), str):
            result[role] = choice['model']
    return result


def token_view(events: list[dict], live: dict) -> dict:
    """Prefer the finish journal snapshot; otherwise use the background export snapshot.

    Never sum overlapping categories. Exact totals stay unknown if incomplete;
    known subtotals and per-column coverage are separate presentation facts.
    Roles describe actual observed models, not configured model choices.
    """
    finished = next((event for event in events if event['kind'] == 'finish'), None)
    raw = finished.get('usage') if finished else live.get('usage')
    snapshot_at = finished.get('ended', finished['at']) if finished else live.get('updated_at')
    if not valid_number(snapshot_at):
        snapshot_at = None
    source = 'finish' if finished else 'session'
    empty = {'available': False, 'source': source, 'snapshot_at': snapshot_at,
             'models': [], 'totals': dict.fromkeys(TOKEN_FIELDS), 'sessions': None,
             'known': dict.fromkeys(TOKEN_FIELDS), 'known_messages': dict.fromkeys(TOKEN_FIELDS),
             'missing_counts': dict.fromkeys(TOKEN_FIELDS), 'missing_usage': None,
             'warnings': [], 'reason': 'Данные о токенах пока недоступны'}
    if not isinstance(raw, dict) or not isinstance(raw.get('models'), list):
        return empty
    if len(raw['models']) > 2000:
        raise ValueError('Too many token rows')
    rows = []
    actual = live.get('models', {})
    session_roles = {events[0].get('session'): 'master_chief'} if events[0].get('session') else {}
    for event in events:
        if event.get('kind') == 'attempt_session' and event.get('session'):
            session_roles[event['session']] = 'bug_fixer' if event.get('role') == 'bug_fixer' else 'executor'
    observed_roles = {}
    for session_usage in raw.get('session_usage', []):
        if not isinstance(session_usage, dict) or session_usage.get('session') not in session_roles:
            continue
        provider, model = session_usage.get('provider'), session_usage.get('model')
        if isinstance(provider, str) and isinstance(model, str):
            observed_roles.setdefault(provider + '/' + model, set()).add(session_roles[session_usage['session']])
    for row in raw['models']:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key] or len(row[key]) > 250 for key in ('provider', 'model')):
            raise ValueError('Invalid token model')
        result = {key: row[key] for key in ('provider', 'model')}
        reference = row['provider'] + '/' + row['model']
        result['roles'] = [role for role in ('master_chief', 'executor', 'bug_fixer')
                           if (role in observed_roles[reference] if reference in observed_roles
                               else reference in actual.get(role, []))]
        for field in (*TOKEN_FIELDS, 'messages', 'missing_usage'):
            value = row.get(field)
            result[field] = value if type(value) is int and value >= 0 else None
        result['known'], result['known_messages'], result['missing_counts'] = {}, {}, {}
        for field in TOKEN_FIELDS:
            known = row.get('known', {}).get(field) if isinstance(row.get('known'), dict) else None
            covered = row.get('known_messages', {}).get(field) if isinstance(row.get('known_messages'), dict) else None
            messages = result['messages']
            valid = (type(known) is int and known >= 0 and type(covered) is int and
                     covered >= 0 and messages is not None and covered < messages and
                     (covered > 0 or known == 0))
            # Old snapshots with an exact sum still provide a known subtotal.
            # An old unknown sum cannot be reconstructed from a message count.
            if result[field] is not None:
                known, covered = result[field], messages
            elif not valid:
                known, covered = None, None
            elif covered == 0:
                known = None
            result['known'][field] = known
            result['known_messages'][field] = covered
            result['missing_counts'][field] = messages - covered if messages is not None and covered is not None else None
        rows.append(result)
    totals = {field: sum(row[field] for row in rows) if rows and all(row[field] is not None for row in rows) else None for field in TOKEN_FIELDS}
    sessions = raw.get('sessions')
    warnings = raw.get('warnings', [])
    warnings = [item[:500] for item in warnings[:20] if isinstance(item, str)] if isinstance(warnings, list) else []
    known = {field: sum(row['known'][field] for row in rows if row['known'][field] is not None)
             if any(row['known'][field] is not None for row in rows) else None for field in TOKEN_FIELDS}
    covered = {field: sum(row['known_messages'][field] or 0 for row in rows) for field in TOKEN_FIELDS}
    missing = {field: sum(row['missing_counts'][field] for row in rows)
               if rows and all(row['missing_counts'][field] is not None for row in rows) else None for field in TOKEN_FIELDS}
    return dict(empty, available=bool(rows), models=rows, totals=totals, known=known, known_messages=covered,
                missing_counts=missing,
                missing_usage=sum(row['missing_usage'] for row in rows) if rows and all(row['missing_usage'] is not None for row in rows) else None,
                sessions=len(set(sessions)) if isinstance(sessions, list) and all(isinstance(item, str) for item in sessions) else None,
                warnings=warnings)


def observations(exports: list[dict], root_session: str, since: float, until: float) -> dict:
    """Project the actual session tree into public text/tools/models and current activity."""
    models = {'master_chief': [], 'executor': []}
    feed, current, calls, session_models, quota_errors = [], [], [], {}, []
    for export in exports:
        session = export.get('info', {}).get('id')
        role = 'master_chief' if session == root_session else 'executor'
        newest = None
        for message in export.get('messages', []):
            info = message_info(message)
            if info.get('role', info.get('type')) != 'assistant':
                continue
            stamp = info.get('time', {})
            created = stamp.get('created')
            if not valid_number(created) or not since - 5 <= created / 1000 <= until:
                continue
            if newest is None or created >= newest.get('time', {}).get('created', 0):
                newest = info
            provider, model = message_model(info)
            reference = provider + '/' + model if provider != 'unknown' and model != 'unknown' else None
            if reference and reference not in models[role]:
                models[role].append(reference)
            if newest is info:
                session_models[session] = reference
            parts = message.get('parts', message.get('content', []))
            last_tool = None
            for index, part in enumerate(parts):
                if not isinstance(part, dict) or part.get('type') not in ('text', 'tool'):
                    continue
                at = part.get('time', {}).get('created', part.get('time', {}).get('start', created))
                if not valid_number(at) or not since <= at / 1000 <= until:
                    continue
                row = {'session': session, 'role': role, 'model': reference,
                       'at': at / 1000, 'id': str(part.get('id', part.get('partID', info.get('id', '') + ':' + str(index))))}
                if part['type'] == 'text':
                    text = part.get('text')
                    if not isinstance(text, str) or not text.strip():
                        continue
                    row.update(kind='text', text=' '.join(text.split())[:500])
                else:
                    state = part.get('state', {})
                    inputs = state.get('input', {})
                    if not isinstance(inputs, dict):
                        inputs = {}
                    tool = part.get('name', part.get('tool', 'tool'))
                    # Do not expose shell commands, outputs, prompts or credentials.
                    target = inputs.get('path', inputs.get('filePath', ''))
                    if not isinstance(target, str):
                        target = ''
                    row.update(kind='tool', tool=tool, target=target[:250], status=state.get('status'))
                    last_tool = row
                    metadata = state.get('metadata', {})
                    child = metadata.get('sessionID', metadata.get('sessionId')) if isinstance(metadata, dict) else None
                    if role == 'master_chief' and child:
                        calls.append({'at': row['at'], 'session': child})
                feed.append(row)
            if not valid_number(stamp.get('completed')):
                running = last_tool if last_tool and last_tool.get('status') in ('running', 'pending') else None
                current.append(dict(running or {'at': created / 1000, 'kind': 'thinking'},
                                    role=role, model=reference, session=session))
        if newest and quota_error(newest.get('error')):
            quota_errors.append({'session': session, 'message': newest.get('id'),
                                 'at': newest['time']['created'] / 1000,
                                 'model': '/'.join(message_model(newest))})
    return {'available': True, 'models': models, 'feed': sorted(feed, key=lambda row: row['at'])[-100:],
            'current': sorted(current, key=lambda row: row['at']), 'calls': calls, 'session_models': session_models,
            'quota_errors': quota_errors}


class SessionReader:
    """Export in a daemon worker; HTTP requests return immediately with cached data."""
    def __init__(self, collect=None, ttl=15, clock=time.monotonic):
        self.collect = collect or (lambda root, sid: ObservedMetrics(root).collect_exports(sid))
        self.ttl, self.clock = ttl, clock
        self.lock = threading.Lock()
        self.entries = {}

    def view(self, root: Path, events: list[dict]) -> dict:
        session = events[0].get('session')
        if not session:
            return {'available': False, 'loading': False, 'reason': 'Задача без сессии OpenCode'}
        key = (str(root.resolve()), session, events[0]['at'])
        ended = next((event.get('ended', event['at']) for event in events if event['kind'] == 'finish'), None)
        with self.lock:
            if key not in self.entries and len(self.entries) >= 32:
                idle = [(value['next'], item) for item, value in self.entries.items() if not value['loading']]
                if not idle:
                    return {'available': False, 'loading': True, 'reason': 'Читаем другие сессии проекта'}
                del self.entries[min(idle)[1]]
            entry = self.entries.setdefault(key, {'next': 0, 'loading': False, 'data': None})
            if not entry['loading'] and self.clock() >= entry['next'] and not (ended and entry.get('final')):
                entry['loading'] = True
                threading.Thread(target=self.fetch, args=(key, root, session, events[0]['at'], ended), daemon=True).start()
            result = dict(entry['data'] or {'available': False, 'reason': 'Читаем сессии OpenCode'})
            result['loading'] = entry['loading']
            return result

    def fetch(self, key, root, session, since, ended):
        try:
            exports = self.collect(root, session)
            until = ended or time.time()
            data = observations(exports, session, since, until)
            data['usage'] = TaskMetrics(root).parse_exports(exports, session, since, until)
            data.update(updated_at=time.time())
        except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
            data = {'available': False, 'reason': 'Не удалось получить сессии OpenCode', 'updated_at': time.time()}
        with self.lock:
            entry = self.entries[key]
            entry.update(data=data, loading=False, next=self.clock() + self.ttl,
                         final=bool(ended and data['available']))


def attach_models(items: list[dict], live: dict):
    """Match tool-created child sessions to the serialized delegation time window."""
    child_models = live.get('session_models', {})
    for item in items:
        for attempt in item['attempts']:
            end = attempt.get('inspection_at', attempt.get('review_at', float('inf')))
            child = attempt.get('session')
            if not child and not attempt.get('workspace'):
                child = next((call['session'] for call in live.get('calls', []) if attempt['at'] <= call['at'] <= end), None)
            attempt['model'] = child_models.get(child)
            usage = live.get('usage', {}).get('session_usage', [])
            attempt['usage'] = [row for row in usage if row.get('session') == child] if child else None
            if not attempt['model'] and attempt['usage']:
                references = [row['provider'] + '/' + row['model'] for row in attempt['usage']
                              if row.get('provider') not in (None, 'unknown') and row.get('model') not in (None, 'unknown')]
                attempt['model'] = ', '.join(dict.fromkeys(references)) or None
        item['model'] = item['attempts'][-1].get('model')
