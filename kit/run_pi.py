"""Start the Chief through the same Pi service that the dashboard controls.

The service owns the conversation. Closing this console leaves the session
available to the dashboard; stopping the service is an explicit operation.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .dashboard.controls import TaskControls
from .dashboard.launcher import ensure_dashboard
from .pi_configuration import locate_pi_command, prepare_pi_configuration, resolve_role_model_references
from .runtime_selection import create_session_gateway, uses_pi_runtime
from .task_metrics import TaskMetrics
from .loop_guards import TaskHalted


def find_task_for_session(project_root: Path, session_identifier: str) -> str:
    """Require one journal for this exact session instead of choosing the latest."""
    matching_tasks = []
    task_metrics = TaskMetrics(project_root)
    for journal_path in (project_root / '.metrics').glob('*/events.jsonl'):
        task_events = task_metrics.read(journal_path.parent.name)
        if task_events and task_events[0].get('session') == session_identifier:
            matching_tasks.append(journal_path.parent.name)
    if len(matching_tasks) != 1:
        raise ValueError('The selected session must belong to exactly one task journal.')
    return matching_tasks[0]


def create_managed_task(project_root: Path, gateway, requested_task: str | None = None) -> tuple[str, str]:
    """Create one Chief and record its real session identity before sending input."""
    task_identifier = requested_task or 'task-' + datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    task_metrics = TaskMetrics(project_root)
    if task_metrics.task_dir(task_identifier).exists():
        raise ValueError('That task already exists. Use --session with its exact session ID to continue it.')
    selected_reference = resolve_role_model_references(project_root)['masterChief']
    provider_identifier, model_identifier = selected_reference.split('/', 1)
    created_session = gateway.call('session.create', data={
        'parentID': None, 'title': task_identifier, 'agent': 'build',
        'model': {'providerID': provider_identifier, 'id': model_identifier},
    })['data']
    session_identifier = created_session['id']
    try:
        task_metrics.start(task_identifier, session=session_identifier, title=task_identifier, track_delegations=True)
    except Exception:
        gateway.remove(session_identifier)
        raise
    return task_identifier, session_identifier


def public_assistant_text(session_export: dict, already_printed: dict[str, str]) -> list[str]:
    """Return new public text, keeping thinking and tool arguments out of the console."""
    pieces_to_print = []
    for message in session_export.get('messages', []):
        message_information = message.get('info', message)
        if message_information.get('role') != 'assistant':
            continue
        message_identifier = str(message_information.get('id', ''))
        text = ''.join(part.get('text', '') for part in message.get('parts', message.get('content', []))
                       if isinstance(part, dict) and part.get('type') == 'text')
        printed_text = already_printed.get(message_identifier, '')
        if text.startswith(printed_text) and text != printed_text:
            pieces_to_print.append(text[len(printed_text):])
        already_printed[message_identifier] = text
    return pieces_to_print


def wait_for_chief(project_root: Path, gateway, task_identifier: str, session_identifier: str,
                   *, timeout_seconds: float = 3600, already_printed=None) -> None:
    """Observe the existing run; a timeout leaves its outcome unconfirmed."""
    printed_messages = {} if already_printed is None else already_printed
    deadline = time.monotonic() + timeout_seconds
    while True:
        session_export = gateway.export_session(session_identifier)
        for text in public_assistant_text(session_export, printed_messages):
            print(text, end='', flush=True)
        session_tree = gateway.tree(session_identifier)
        if not gateway.active().intersection(session_tree):
            print()
            last_assistant = next((message.get('info', {}) for message in reversed(session_export.get('messages', []))
                                   if message.get('info', {}).get('role') == 'assistant'), {})
            session_information = gateway.call('session.get', {'sessionID': session_identifier})['data']
            if last_assistant.get('error') or session_information.get('outcome', {}).get('type') == 'error':
                raise RuntimeError('Pi ended with an error. Read the task dashboard before continuing.')
            task_metrics = TaskMetrics(project_root)
            task_events = task_metrics.read(task_identifier)
            if any(event['kind'] == 'finish' for event in task_events):
                return
            task_metrics.read_events_if_work_allowed(task_identifier)
            raise RuntimeError(
                'The Chief stopped before the task recorded finish. The task is incomplete. '
                'Inspect its dashboard and continue the same conversation with '
                'start.cmd --session ' + session_identifier)
        if time.monotonic() >= deadline:
            raise TimeoutError('The console wait expired. The task remains available in its dashboard.')
        time.sleep(.25)


def submit_user_request(project_root: Path, gateway, task_identifier: str, session_identifier: str,
                        user_text: str, *, timeout_seconds: float) -> None:
    """Send one identified request and tell the Chief which accounting already exists."""
    task_events = TaskMetrics(project_root).read(task_identifier)
    if any(event['kind'] == 'finish' for event in task_events):
        raise ValueError('The task is finished. Start a new console for a new task.')
    TaskMetrics(project_root).read_events_if_work_allowed(task_identifier)
    previously_printed = {}
    public_assistant_text(gateway.export_session(session_identifier), previously_printed)
    request_identifier = 'msg_' + uuid.uuid4().hex
    task_context = (
        f'This is the managed Pi kit task {task_identifier}. Your exact session ID is {session_identifier}. '
        'The launcher has already started its journal with tracked delegations. Do not start a second task '
        'or repeat the start command. Read AGENTS.md and the current project plan. Use the execution controller '
        'for workers and preserve this task ID through review, tests, pause and continuation. '
        'Record the final UI review and finish only after every accepted item is integrated and the full tests pass.\n\n'
        'User request:\n' + user_text
    )
    gateway.call('session.prompt', {'sessionID': session_identifier},
                 {'id': request_identifier, 'text': task_context})
    wait_for_chief(project_root, gateway, task_identifier, session_identifier,
                   timeout_seconds=timeout_seconds, already_printed=previously_printed)


def handle_console_command(project_root: Path, gateway, task_identifier: str, command: str) -> bool:
    """Apply a local command and return whether the console should stay open."""
    if command == '/quit':
        return False
    if command == '/sessions':
        print(json.dumps(gateway.sessions(), ensure_ascii=False, indent=2))
        return True
    actions = {'/pause': 'pause', '/resume': 'resume', '/cancel': 'cancel'}
    if command not in actions:
        raise ValueError('Commands: /pause, /resume, /cancel, /sessions, /quit')
    controls = TaskControls(project_root, gateway=gateway)
    session_identifier = TaskMetrics(project_root).read(task_identifier)[0]['session']
    previously_printed = {}
    if command == '/resume':
        public_assistant_text(gateway.export_session(session_identifier), previously_printed)
    controls.request(task_identifier, actions[command])
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        current_state = controls.view(task_identifier)
        if current_state.get('status') not in ('pausing', 'resuming', 'cancelling'):
            print(current_state.get('message', current_state.get('error', current_state.get('status'))))
            if command == '/resume' and current_state.get('status') == 'running':
                wait_for_chief(project_root, gateway, task_identifier, session_identifier,
                               already_printed=previously_printed)
            return True
        time.sleep(.1)
    raise TimeoutError('The control operation is still unconfirmed. Read the task dashboard.')


def main(arguments=None) -> int:
    """Prepare a project, open its managed Chief, or stop its local Pi service."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--prompt', help='Send one request and wait for the current work to settle.')
    parser.add_argument('--task', help='Choose an unused task ID for a new conversation.')
    parser.add_argument('--session', help='Continue this exact existing session and its task.')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--configure', action='store_true')
    parser.add_argument('--authenticate', action='store_true', help='Open Pi for /login in this project before choosing native models.')
    parser.add_argument('--stop-service', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--wait-seconds', type=float, default=3600)
    options = parser.parse_args(arguments)
    project_root = options.root.resolve()
    try:
        if not uses_pi_runtime(project_root):
            raise ValueError('Run this launcher in a project containing pi-kit.json with runtime pi.')
        if options.wait_seconds <= 0:
            raise ValueError('--wait-seconds must be positive.')
        if options.configure:
            return subprocess.call([sys.executable, '-B', '-m', 'kit.configurator.app'], cwd=project_root)
        if options.authenticate:
            agent_directory = project_root / '.pi/agent'
            agent_directory.mkdir(parents=True, exist_ok=True)
            environment = dict(os.environ, PI_CODING_AGENT_DIR=str(agent_directory))
            print('Use /login to connect your provider, then /quit. Start a kit task with start.cmd afterwards.')
            return subprocess.call(locate_pi_command(project_root) + [
                '--no-session', '--no-tools', '--no-extensions', '--no-mcp',
                '--no-skills', '--no-prompt-templates', '--no-themes'], cwd=project_root, env=environment)
        gateway = create_session_gateway(project_root)
        if options.stop_service:
            gateway.shutdown_service()
            print('The project Pi service is stopped.')
            return 0
        if options.prepare_only:
            prepare_pi_configuration(project_root)
            print('Pi settings are prepared. No model request was sent.')
            return 0
        if not (project_root / '.pi/kit-runtime.json').is_file():
            prepare_pi_configuration(project_root)
        else:
            resolve_role_model_references(project_root)
        if options.session:
            session_identifier = options.session
            task_identifier = find_task_for_session(project_root, session_identifier)
            if options.task and options.task != task_identifier:
                raise ValueError('--task does not match the selected session.')
            gateway.call('session.get', {'sessionID': session_identifier})
        else:
            task_identifier, session_identifier = create_managed_task(project_root, gateway, options.task)
        dashboard = ensure_dashboard(project_root, task_identifier, open_browser=not options.no_browser)
        print('Task: ' + task_identifier)
        print('Session: ' + session_identifier)
        print('Dashboard: ' + dashboard['url'])
        if options.session and gateway.active().intersection(gateway.tree(session_identifier)):
            try:
                wait_for_chief(project_root, gateway, task_identifier, session_identifier,
                               timeout_seconds=options.wait_seconds)
            except KeyboardInterrupt:
                handle_console_command(project_root, gateway, task_identifier, '/pause')
        if options.prompt:
            try:
                submit_user_request(project_root, gateway, task_identifier, session_identifier,
                                    options.prompt, timeout_seconds=options.wait_seconds)
            except KeyboardInterrupt:
                handle_console_command(project_root, gateway, task_identifier, '/pause')
                return 130
            return 0
        print('Enter a task. Ctrl+C pauses it. /quit closes this console and keeps its history.')
        while True:
            try:
                user_text = input('> ').strip()
                if not user_text:
                    continue
                if user_text.startswith('/'):
                    if not handle_console_command(project_root, gateway, task_identifier, user_text):
                        return 0
                else:
                    submit_user_request(project_root, gateway, task_identifier, session_identifier,
                                        user_text, timeout_seconds=options.wait_seconds)
            except KeyboardInterrupt:
                print()
                handle_console_command(project_root, gateway, task_identifier, '/pause')
            except EOFError:
                return 0
            except TaskHalted as error:
                print(str(error), file=sys.stderr)
            except (OSError, ValueError, RuntimeError) as error:
                print(str(error), file=sys.stderr)
    except TaskHalted as error:
        print(str(error), file=sys.stderr)
        return 3
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
