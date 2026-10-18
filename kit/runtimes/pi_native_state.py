"""Bind the current native Pi conversation to the existing kit journal."""
from datetime import datetime
from pathlib import Path
import uuid

from ..task_metrics import TaskMetrics
from ..loop_guards import is_halted
from .pi_rpc import PiControlError, process_identity
from .pi_interactive import PiInteractiveProcess


def task_for_interactive_session(root, session_identifier):
    metrics = TaskMetrics(root)
    matches = [path.parent.name for path in (root / '.metrics').glob('*/events.jsonl')
               if metrics.read(path.parent.name)[0].get('session') == session_identifier]
    if len(matches) != 1:
        raise PiControlError('The native conversation needs exactly one task journal')
    return matches[0]


def attach_interactive_session(broker, data):
    from .pi_broker import canonical_plain_path
    transcript = canonical_plain_path(data['transcript'])
    if transcript.parent != broker.folder / 'sessions' or transcript.suffix != '.jsonl':
        raise PiControlError('Native Pi history must stay in this project service')
    identifier = data['id']
    if not isinstance(identifier, str) or not identifier.startswith('ses_') or not identifier[4:].isalnum():
        raise PiControlError('Invalid native session identity')
    port, token, pid = data['port'], data['token'], data['pid']
    if type(port) is not int or not 0 < port < 65536 or not isinstance(token, str) or len(token) < 32 or type(pid) is not int:
        raise PiControlError('Invalid native terminal endpoint')
    identity = process_identity(pid)
    if not identity:
        raise PiControlError('The native terminal process is not alive')
    existing = broker.sessions.get(identifier)
    if existing:
        if existing.get('parentID') or existing['transcript'] != str(transcript):
            raise PiControlError('Native session ancestry or history changed')
        if broker._previous_process_is_alive(existing) and existing['process'] != dict(pid=pid, identity=identity):
            raise PiControlError('Another process still owns this conversation')
    else:
        if any(row['transcript'] == str(transcript) for row in broker.sessions.values()):
            raise PiControlError('Another identity already owns this history')
    role = broker.configuration()['roles']['build']
    session = dict(existing) if existing else dict(id=identifier, parentID=None, project=str(broker.root), agent='build',
                               title='Native Pi', status='idle', admissions={}, transcript=str(transcript))
    session.update(interactive=dict(port=port, token=token), native_transcript_name=transcript.name,
                   process=dict(pid=pid, identity=identity), model=dict(providerID=role['provider'], id=role['model']))
    process = PiInteractiveProcess(session)
    state = process.request('get_state')
    if state.get('sessionFile') != str(transcript):
        raise PiControlError('Native Pi did not confirm its history file')
    broker.sessions[identifier] = session
    broker.processes[identifier] = process
    session['status'] = 'running' if not state.get('settled') else 'idle'
    if existing:
        task = task_for_interactive_session(broker.root, identifier)
    else:
        task = data.get('task') or 'task-' + datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
        try:
            TaskMetrics(broker.root).start(task, session=identifier, title=task, track_delegations=True)
        except Exception:
            broker.sessions.pop(identifier, None)
            broker.processes.pop(identifier, None)
            raise
    broker.save()
    return dict(data=dict(session=identifier, task=task))


def interactive_task_operation(broker, operation, identifier, data):
    from ..dashboard.controls import TaskControls
    from ..dashboard.launcher import ensure_dashboard
    metrics = TaskMetrics(broker.root)
    task = task_for_interactive_session(broker.root, identifier)
    events = metrics.read(task)
    if operation == 'task.status':
        return dict(task=task, finished=any(event['kind'] == 'finish' for event in events),
                    halted=bool(is_halted(events)))
    if operation == 'task.workAllowed':
        metrics.read_events_if_work_allowed(task)
        return dict(allowed=True, task=task)
    if operation == 'task.dashboard':
        return ensure_dashboard(broker.root, task, open_browser=data.get('open_browser', True))
    if operation == 'task.control':
        return TaskControls(broker.root).request(task, data['action'])
    if operation == 'task.controlState':
        return TaskControls(broker.root).view(task)
    if operation == 'task.canSwitch':
        if is_halted(events):
            raise PiControlError('A protective STOP requires the user decision before switching conversations')
        state = TaskControls(broker.root).view(task)
        finished = any(event['kind'] == 'finish' for event in events)
        if not finished and state.get('status') not in ('paused', 'cancelled'):
            raise PiControlError('Pause this task before switching or forking the native conversation')
        return dict(allowed=True)
    if operation == 'session.detachInteractive':
        session = broker.session(identifier)
        process = broker.processes.get(identifier)
        if process:
            state = process.request('get_state')
            if not state.get('settled') or state.get('pendingMessageCount'):
                raise PiControlError('Stop native Pi before detaching its conversation')
        broker.processes.pop(identifier, None)
        session.pop('process', None)
        session.pop('interactive', None)
        session['status'] = 'stopped'
        return dict(detached=True)
    raise PiControlError('Unsupported native task operation')
