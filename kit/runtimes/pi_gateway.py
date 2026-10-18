"""Small client for the project Pi broker used by controllers and the dashboard."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .pi_broker import project_service_lock
from .pi_rpc import PiControlError, process_identity


_owned_service_processes = {}


class PiSessionControl:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.connection_file = self.root / '.pi' / 'kit-service' / 'connection.json'

    def _read_connection(self):
        try:
            connection = json.loads(self.connection_file.read_text(encoding='utf-8'))
            if (not isinstance(connection, dict) or connection.get('format') != 1 or
                    connection.get('project') != str(self.root) or
                    type(connection.get('port')) is not int or not 0 < connection['port'] < 65536 or
                    type(connection.get('pid')) is not int or connection['pid'] <= 0 or
                    not isinstance(connection.get('identity'), str) or not connection['identity'] or
                    not isinstance(connection.get('token'), str) or len(connection['token']) < 32):
                raise ValueError()
            return connection
        except (OSError, ValueError):
            return None

    def _request(self, connection, operation, params=None, data=None, timeout=60):
        from ..dashboard.launcher import local_request
        request = Request('http://127.0.0.1:' + str(connection['port']) + '/call',
                          json.dumps(dict(operation=operation, params=params, data=data)).encode('utf-8'),
                          {'Authorization': 'Bearer ' + connection['token'], 'Content-Type': 'application/json'})
        try:
            with local_request(request, timeout=timeout) as response:
                result = json.load(response)
            return result['result']
        except HTTPError as error:
            try:
                message = json.load(error).get('error')
            except (ValueError, OSError):
                message = None
            raise PiControlError(message or 'Pi did not confirm operation: ' + operation) from error
        except (OSError, ValueError, KeyError, URLError) as error:
            raise PiControlError('Pi service connection failed; inspect state before retrying') from error

    def _ensure_connection(self):
        # Established clients only need authenticated health, not the startup
        # lock. Watchers and the dashboard can then observe the same service.
        connection = self._read_connection()
        if connection:
            try:
                health = self._request(connection, 'service.health', timeout=3)
                if health == dict(project=str(self.root), protocol=1):
                    return connection
            except PiControlError:
                if process_identity(connection['pid']) == connection.get('identity'):
                    raise PiControlError('Existing Pi service is alive but unresponsive; replacement is blocked')
        with project_service_lock(self.root):
            connection = self._read_connection()
            if connection:
                try:
                    result = self._request(connection, 'service.health', timeout=3)
                    if result == dict(project=str(self.root), protocol=1):
                        return connection
                except PiControlError:
                    if process_identity(connection['pid']) == connection.get('identity'):
                        raise PiControlError('Existing Pi service is alive but unresponsive; replacement is blocked')
            options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
            log_file = self.connection_file.parent / 'service.log'
            if log_file.exists() and log_file.stat().st_size > 64_000:
                log_file.write_text('', encoding='utf-8')
            with log_file.open('ab') as output:
                process = subprocess.Popen([sys.executable, '-B', '-u', '-m', 'kit.runtimes.pi_broker', '--root', str(self.root)],
                                           cwd=Path(__file__).parents[2], stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=output, **options)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                connection = self._read_connection()
                if connection and connection.get('pid') == process.pid:
                    try:
                        self._request(connection, 'service.health', timeout=2)
                        _owned_service_processes[process.pid] = process
                        return connection
                    except PiControlError:
                        pass
                if process.poll() is not None:
                    break
                time.sleep(.05)
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            raise PiControlError('Project Pi service did not start')

    def call(self, operation, params=None, data=None):
        try:
            return self._request(self._ensure_connection(), operation, params, data)
        except PiControlError as error:
            from ..dashboard.session_control import ControlError
            raise ControlError(str(error)) from error

    def capabilities(self):
        if self.call('service.health') != dict(project=str(self.root), protocol=1):
            raise PiControlError('Unknown Pi broker protocol')

    def sessions(self, parent=None):
        return self.call('session.list', dict(parentID=parent))['data']

    def tree(self, root_session):
        if root_session not in {row['id'] for row in self.sessions()}:
            raise PiControlError('Root Pi session does not belong to this project')
        found = [root_session]
        for identifier in found:
            for child in self.sessions(identifier):
                if child['id'] in found or len(found) >= 200:
                    raise PiControlError('Invalid or excessive Pi session tree')
                found.append(child['id'])
        return found

    def active(self):
        return set(self.call('session.active')['data'])

    def interrupt(self, identifier):
        result = self.call('session.interrupt', dict(sessionID=identifier))
        if result != dict(interrupted=True):
            raise PiControlError('Pi session interruption was not confirmed')

    def clear_inbox(self, identifier):
        self.call('session.inbox.cancel', dict(sessionID=identifier))
        if self.call('session.inbox.list', dict(sessionID=identifier))['data']:
            raise PiControlError('Pi queue is still populated')

    def export_session(self, identifier):
        return self.call('session.export', dict(sessionID=identifier))

    def prepare_models(self, choices, selected):
        try:
            prepared = json.loads((self.root / '.pi/kit-runtime.json').read_text(encoding='utf-8'))
            if prepared.get('choices') != choices:
                raise PiControlError('Prepared Pi choices do not match the approved model settings')
            for field, role in (('masterChief', 'build'), ('executors', 'executor'), ('bugFixer', 'bug-fixer')):
                if not selected.get(field):
                    continue
                configured = prepared['roles'][role]
                if (not configured.get('enabled', True) or
                        configured['provider'] + '/' + configured['model'] != selected[field]):
                    raise PiControlError('Prepared Pi role does not match the approved model reference')
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise PiControlError('Prepared Pi model configuration could not be verified') from error
        # Close only confirmed idle processes so the next start reads fresh credentials.
        # The caller already wrote configuration inside the preparation lock.
        self.call('service.reload')
        available = self.call('model.list')['data']
        references = {row['providerID'] + '/' + row['id'] for row in available}
        if not {reference.split('#', 1)[0] for reference in selected.values() if reference} <= references:
            raise PiControlError('Selected models are not available in the prepared Pi configuration')

    def switch_model(self, identifier, reference):
        provider, model = reference.split('/', 1)
        if '#' in model:
            raise PiControlError('Pi model variants must be configured explicitly before continuation')
        selection = dict(providerID=provider, id=model)
        self.call('session.switchModel', dict(sessionID=identifier), dict(model=selection))
        if self.call('session.get', dict(sessionID=identifier))['data']['model'] != selection:
            raise PiControlError('Pi did not confirm the selected session model')

    def prepare_resume(self, identifier, task):
        from ..task_control_state import read_state
        reference = read_state(self.root, task).get('settings_revision')
        if reference:
            from ..model_switch import verify_revision
            selected = verify_revision(self.root, task, reference)
            self.prepare_models(selected['choices'], selected['models'])
            self.switch_model(identifier, selected['models']['masterChief'])

    def resume(self, identifier, task, operation_id):
        from ..task_control_state import read_state
        text = (f'User resumed the paused task {task} from its dashboard. Continue this same task ID. '
                'Read the saved work plan and task journal. Inspect partial edits and interrupted executor attempts '
                'before continuing; do not assume an interrupted attempt passed review or tests. '
                'Do not reset loop guards or start a new task. Continue the next unfinished approved work item.')
        reference = read_state(self.root, task).get('settings_revision')
        if reference:
            from ..model_switch import verify_revision
            selected = verify_revision(self.root, task, reference)
            text += (' Use the explicitly approved model revision ' + reference + ' for future attempts: '
                     + json.dumps(selected['models'], ensure_ascii=True) + '. Keep the original settings as history. '
                     'Inspect the interrupted attempt before a new controlled attempt; preserve all budgets and guards.')
        response = self.call('session.prompt', dict(sessionID=identifier),
                             dict(id='msg_' + operation_id, text=text, resume=True))
        if response.get('data', {}).get('id') != 'msg_' + operation_id:
            raise PiControlError('Pi did not confirm continuation of the task')

    def remove(self, identifier):
        self.call('session.remove', dict(sessionID=identifier))

    def shutdown_service(self):
        with project_service_lock(self.root):
            connection = self._read_connection()
            if not connection:
                return dict(stopped=True)
            if process_identity(connection['pid']) != connection['identity']:
                # A dead owner cannot reply to HTTP. Removing its metadata is
                # safe while startup is locked; never contact a reused port.
                self.connection_file.unlink(missing_ok=True)
                return dict(stopped=True)
            result = self._request(connection, 'service.shutdown')
            owned_process = _owned_service_processes.pop(connection['pid'], None)
            if owned_process:
                owned_process.wait(timeout=10)
            else:
                deadline = time.monotonic() + 10
                while process_identity(connection['pid']) == connection['identity']:
                    if time.monotonic() >= deadline:
                        raise PiControlError('Pi service has not confirmed its exit')
                    time.sleep(.05)
            return result


def collect_session_exports(root, session):
    service = PiSessionControl(root)
    return [service.export_session(identifier) for identifier in service.tree(session)]
