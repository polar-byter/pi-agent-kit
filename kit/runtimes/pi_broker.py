"""Authenticated project service that owns Pi processes independently of the dashboard."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
import uuid

from .pi_exports import normalize_session_export
from .pi_rpc import PiControlError, PiRpcProcess, process_identity, terminate_verified_process


def write_private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as output:
            os.chmod(temporary, 0o600)
            json.dump(value, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def project_service_lock(root, name='startup', nonblocking=False):
    folder = Path(root) / '.pi' / 'kit-service'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / (name + '.lock')).open('a+b') as handle:
        # Reading byte zero before acquiring its Windows record lock fails
        # when another client already owns it. Size inspection needs no read.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK if nonblocking else msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def canonical_plain_path(value):
    path = Path(value).absolute()
    for component in (path, *path.parents):
        if component.is_symlink() or (hasattr(component, 'is_junction') and component.is_junction()):
            raise PiControlError('Linked paths cannot be used by the Pi service')
        if component.is_file() and component.stat().st_nlink > 1:
            raise PiControlError('Hard linked paths cannot be used by the Pi service')
    return path.resolve()


class ProjectPiBroker:
    def __init__(self, root, process_factory=PiRpcProcess):
        self.root = canonical_plain_path(root)
        self.folder = self.root / '.pi' / 'kit-service'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.folder / 'registry.json'
        self.process_factory = process_factory
        self.processes = {}
        self.lock = threading.RLock()
        if self.registry_file.exists():
            registry = json.loads(self.registry_file.read_text(encoding='utf-8'))
            if registry.get('project') != str(self.root) or registry.get('format') != 1:
                raise PiControlError('Pi registry does not belong to this project')
            self.sessions = registry['sessions']
        else:
            self.sessions = {}
        for session in self.sessions.values():
            self._verify_registered_session(session)
            if self._previous_process_is_alive(session):
                session['status'] = 'unknown'
            else:
                if session.get('status') in ('running', 'unknown'):
                    self.record_unexpected_process_exit(session)
                session['status'] = 'stopped'
                session.pop('process', None)
        self.save()

    def save(self):
        write_private_json(self.registry_file, dict(format=1, project=str(self.root), sessions=self.sessions))

    def configuration(self):
        try:
            configuration = json.loads((self.root / '.pi' / 'kit-runtime.json').read_text(encoding='utf-8'))
            if configuration.get('format') != 1 or configuration.get('runtime') != 'pi':
                raise ValueError()
            return configuration
        except (OSError, ValueError) as error:
            raise PiControlError('Prepare the Pi project configuration first') from error

    def _verify_registered_session(self, session):
        if session.get('project') != str(self.root):
            raise PiControlError('Session belongs to another project')
        transcript = canonical_plain_path(session['transcript'])
        if not transcript.is_relative_to(self.folder / 'sessions'):
            raise PiControlError('Session transcript is outside the project service')
        if session.get('parentID') is not None and session['parentID'] not in self.sessions:
            raise PiControlError('Session parent is missing')

    def _previous_process_is_alive(self, session):
        reference = session.get('process')
        return bool(reference and reference.get('identity') and
                    process_identity(reference['pid']) == reference['identity'])

    def session(self, identifier):
        if not isinstance(identifier, str) or identifier not in self.sessions:
            raise PiControlError('Session was not found in this project')
        session = self.sessions[identifier]
        self._verify_registered_session(session)
        return session

    def public_session(self, session):
        return dict(id=session['id'], parentID=session.get('parentID'), title=session.get('title', ''),
                    agent=session['agent'], model=session.get('model'),
                    location=dict(directory=str(self.root)), status=session['status'],
                    workspace=session.get('workspace'), permissions=session.get('permissions', []),
                    outcome=session.get('outcome', {}))

    def record_unexpected_process_exit(self, session):
        """Keep missing completion evidence distinct from a returned worker report."""
        session['outcome'] = dict(type='error', code='process_exit',
                               message='Pi exited before the kit confirmed completion')

    def refresh(self, session):
        process = self.processes.get(session['id'])
        if process:
            if process.process.poll() is not None:
                if not process.settled.is_set() or process.process.returncode:
                    self.record_unexpected_process_exit(session)
                session['status'] = 'stopped'
                session.pop('process', None)
                self.processes.pop(session['id'], None)
            else:
                state = process.request('get_state')
                if state.get('sessionFile'):
                    native_path = canonical_plain_path(state['sessionFile'])
                    if native_path != canonical_plain_path(session['transcript']):
                        raise PiControlError('Pi opened an unexpected session transcript')
                running = (state.get('isStreaming') or state.get('isCompacting') or
                           state.get('pendingMessageCount') or not process.settled.is_set())
                session['status'] = 'running' if running else 'idle'
                native_model = state.get('model')
                if native_model:
                    session['model'] = dict(providerID=native_model['provider'], id=native_model['id'])
        elif not self._previous_process_is_alive(session):
            if session.get('status') in ('running', 'unknown'):
                self.record_unexpected_process_exit(session)
            session['status'] = 'stopped'
            session.pop('process', None)
        else:
            session['status'] = 'unknown'

    def start_process(self, session):
        self.refresh(session)
        if session['id'] in self.processes:
            return self.processes[session['id']]
        if session['status'] == 'unknown':
            raise PiControlError('Previous Pi process is still alive; confirm its stop before restoring')
        from ..pi_configuration import locate_pi_command, pi_process_environment
        configuration = self.configuration()
        command = list(locate_pi_command(self.root))
        command += ['--mode', 'rpc', '--session', session['transcript'], '--no-extensions', '--no-mcp',
                    '--no-skills', '--no-prompt-templates', '--no-themes']
        role = configuration['roles'].get(session['agent'])
        if not role or not role.get('enabled', True):
            raise PiControlError('The selected Pi role is disabled')
        selection = session.get('model')
        if selection:
            command += ['--provider', selection['providerID'], '--model', selection['id']]
        prompt = role.get('system_prompt', '')
        if prompt:
            command += ['--append-system-prompt', prompt]
        environment = dict(pi_process_environment(self.root), PI_CODING_AGENT_DIR=configuration['agent_directory'],
                           PI_KIT_PROJECT=str(self.root), PI_KIT_SESSION_ID=session['id'],
                           OPENCODE_KIT_ROOT=str(self.root), OPENCODE_KIT_SERVER_MODE='pi-broker')
        if session.get('parentID'):
            policy = dict(project=str(self.root), workspace=session['workspace'], source=session['source'], progress=session['progress'])
            environment['PI_KIT_WORKER_POLICY'] = json.dumps(policy)
            command += ['--tools', 'read,edit,write', '--extension', str(Path(__file__).parents[1] / 'pi' / 'worker_permissions.ts')]
        else:
            # Windows can expose a WSL bash launcher without an installed Linux
            # distribution. Pi's native PowerShell tool needs no extra runtime.
            shell_tool = 'powershell' if os.name == 'nt' else 'bash'
            command += ['--tools', 'read,' + shell_tool + ',edit,write']
        process = self.process_factory(command, session.get('workspace', str(self.root)), environment)
        self.processes[session['id']] = process
        session['process'] = dict(pid=process.process.pid, identity=process.identity)
        session['status'] = 'unknown'
        self.save()
        try:
            state = process.request('get_state')
            if state.get('isStreaming') or state.get('isCompacting') or state.get('pendingMessageCount'):
                raise PiControlError('Restored Pi session was unexpectedly active')
            process.request('set_auto_retry', enabled=False)
            session['status'] = 'idle'
            if session.get('parentID'):
                if not self.permission_check(session, 'read', session['source']):
                    raise PiControlError('Pi worker permission extension did not confirm its policy')
                if self.permission_check(session, 'bash', '*'):
                    raise PiControlError('Pi worker shell restriction was not confirmed')
            self.save()
            return process
        except Exception:
            process.close()
            self.processes.pop(session['id'], None)
            session['status'] = 'stopped'
            session.pop('process', None)
            self.save()
            raise

    def permission_check(self, session, action, resource):
        process = self.processes.get(session['id'])
        if not process:
            process = self.start_process(session)
        tool = {'edit': 'write', 'shell': 'bash'}.get(action, action)
        target = str(self.root / resource) if not Path(resource).is_absolute() else resource
        nonce = uuid.uuid4().hex
        request = dict(nonce=nonce, tool=tool, input=dict(path=target))
        response = process.request('prompt', message='/kit-permission-check ' + json.dumps(request))
        if not isinstance(response, dict) or response.get('disposition') != 'handled':
            raise PiControlError('Worker permission check was not handled by the native extension')
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with process.lock:
                events = list(process.events)
            for event in events:
                text = event.get('message', '')
                if event.get('type') == 'extension_ui_request' and text.startswith('pi-kit-permission:'):
                    result = json.loads(text.split(':', 1)[1])
                    if result.get('nonce') == nonce:
                        return result.get('allowed') is True
            time.sleep(.01)
        raise PiControlError('Native worker permission decision was not confirmed')

    def create(self, data):
        configuration = self.configuration()
        parent = data.get('parentID')
        if parent is not None:
            self.session(parent)
        agent = data.get('agent', 'executor' if parent else 'build')
        role = configuration['roles'].get(agent)
        if not role or not role.get('enabled', True):
            raise PiControlError('Requested Pi role is unavailable')
        identifier = 'ses_' + uuid.uuid4().hex
        transcript_folder = self.folder / 'sessions'
        transcript_folder.mkdir(exist_ok=True)
        session = dict(id=identifier, parentID=parent, project=str(self.root), agent=agent,
                       title=str(data.get('title', '')), status='stopped', admissions={},
                       transcript=str(transcript_folder / (identifier + '.jsonl')),
                       model=data.get('model') or dict(providerID=role['provider'], id=role['model']))
        if parent:
            try:
                workspace, source, progress = (canonical_plain_path(data[field]) for field in ('workspace', 'source', 'progress'))
            except (KeyError, TypeError) as error:
                raise PiControlError('Worker creation requires exact workspace, source and progress paths') from error
            if (not workspace.is_dir() or not workspace.is_relative_to(self.root / '.metrics') or
                    not source.is_relative_to(workspace) or source == workspace or
                    not progress.is_relative_to(self.root / '.metrics') or progress.is_relative_to(workspace)):
                raise PiControlError('Worker paths do not match this project isolated workspace')
            session.update(workspace=str(workspace), source=str(source), progress=str(progress), permissions=data.get('permissions', []))
        self.sessions[identifier] = session
        self.save()
        self.start_process(session)
        return dict(data=self.public_session(session))

    def export(self, session):
        self.refresh(session)
        if session['id'] in self.processes:
            entries = self.processes[session['id']].request('get_entries')['entries']
        else:
            path = canonical_plain_path(session['transcript'])
            entries = []
            if path.exists():
                lines = path.read_text(encoding='utf-8').splitlines()
                for index, line in enumerate(lines):
                    try:
                        entries.append(json.loads(line))
                    except ValueError:
                        if index != len(lines) - 1:
                            raise PiControlError('Pi transcript contains an unreadable entry')
        return normalize_session_export(session, entries)

    def collect_session_family_for_removal(self, identifier):
        """Validate one bounded family before closing processes or deleting history."""
        identifiers = [identifier]
        visited = {identifier}
        for parent_identifier in identifiers:
            for child_identifier, child in self.sessions.items():
                if child.get('parentID') != parent_identifier:
                    continue
                if child_identifier in visited or len(identifiers) >= 200:
                    raise PiControlError('Invalid or excessive Pi session family; no history was removed')
                identifiers.append(child_identifier)
                visited.add(child_identifier)
        family = []
        for member_identifier in identifiers:
            member = self.session(member_identifier)
            if member.get('id') != member_identifier:
                raise PiControlError('Session identity does not match the project registry')
            transcript = canonical_plain_path(member['transcript'])
            expected_transcript = self.folder / 'sessions' / (member_identifier + '.jsonl')
            if transcript != expected_transcript:
                raise PiControlError('Session transcript does not match its registered identity')
            self.refresh(member)
            if member['status'] in ('running', 'unknown'):
                raise PiControlError('Confirm the entire session family has stopped before deleting its history')
            family.append((member, transcript))
        transcript_paths = {transcript for member, transcript in family}
        for other_identifier, other_session in self.sessions.items():
            if other_identifier not in visited and canonical_plain_path(other_session['transcript']) in transcript_paths:
                raise PiControlError('A session outside this family references the same transcript')
        return family

    def remove_session_family(self, identifier):
        family = self.collect_session_family_for_removal(identifier)
        for member, transcript in family:
            process = self.processes.get(member['id'])
            if process:
                process.close()
                self.processes.pop(member['id'], None)
            member['status'] = 'stopped'
            member.pop('process', None)
        # Parents remain registered until all of their children have been removed.
        for member, transcript in reversed(family):
            transcript.unlink(missing_ok=True)
            del self.sessions[member['id']]
            self.save()
        return dict(removed=True)

    def dispatch(self, operation, params=None, data=None):
        with self.lock:
            result = self._dispatch(operation, params or {}, data or {})
            self.save()
            return result

    def _dispatch(self, operation, params, data):
        if operation == 'service.health':
            return dict(project=str(self.root), protocol=1)
        if operation == 'session.create':
            return self.create(data)
        if operation == 'session.list':
            parent = params.get('parentID')
            parent = None if parent in (None, 'null') else parent
            if parent:
                self.session(parent)
            return dict(data=[self.public_session(row) for row in self.sessions.values() if row.get('parentID') == parent])
        if operation == 'session.active':
            for session in self.sessions.values():
                self.refresh(session)
            return dict(data={sid: dict(type='running') for sid, row in self.sessions.items() if row['status'] in ('running', 'unknown')})
        if operation == 'model.list':
            from ..pi_configuration import list_available_pi_models
            models = list_available_pi_models(self.root)
            if isinstance(models, dict):
                models = models.get('data', models.get('models', []))
            return dict(data=[dict(zip(('providerID', 'id'), row.split('/', 1))) if isinstance(row, str)
                              else dict(providerID=row.get('providerID', row.get('provider')), id=row.get('id', row.get('model')))
                              for row in models])
        if operation == 'service.reload':
            for session in self.sessions.values():
                self.refresh(session)
                if session['status'] in ('running', 'unknown'):
                    raise PiControlError('Stop every project session before preparing new models')
            for process in self.processes.values():
                process.close()
            self.processes.clear()
            for session in self.sessions.values():
                session['status'] = 'stopped'
                session.pop('process', None)
            return dict(prepared=True)
        session = self.session(params.get('sessionID'))
        self.refresh(session)
        if operation == 'session.get':
            return dict(data=self.public_session(session))
        if operation == 'session.export':
            return self.export(session)
        if operation == 'session.permission.create':
            if not session.get('parentID'):
                raise PiControlError('Permission preflight is only available for isolated workers')
            allowed = all(self.permission_check(session, data.get('action'), resource) for resource in data.get('resources', []))
            return dict(data=dict(effect='allow' if allowed and data.get('resources') else 'deny'))
        if operation == 'session.prompt':
            identifier = data.get('id')
            text = data.get('text')
            if not isinstance(identifier, str) or not identifier.startswith('msg_') or not isinstance(text, str) or not text:
                raise PiControlError('A prompt requires an explicit message identity and text')
            import hashlib
            digest = hashlib.sha256(text.encode()).hexdigest()
            admitted = session['admissions'].get(identifier)
            if admitted:
                if admitted['digest'] != digest:
                    raise PiControlError('Message identity was already used for different text')
                if admitted['status'] != 'accepted':
                    raise PiControlError('Previous prompt admission is unknown; inspect history before continuing')
                return dict(data=dict(id=identifier))
            if session['status'] in ('running', 'unknown'):
                raise PiControlError('Session must be confirmed idle before accepting another prompt')
            process = self.start_process(session)
            session['admissions'][identifier] = dict(digest=digest, status='unknown')
            session.pop('outcome', None)
            session['status'] = 'running'
            process.settled.clear()
            self.save()
            response = process.request('prompt', message=text)
            if (response or {}).get('disposition') == 'handled':
                process.settled.set()
                session['status'] = 'idle'
            session['admissions'][identifier]['status'] = 'accepted'
            return dict(data=dict(id=identifier))
        if operation == 'session.interrupt':
            process = self.processes.get(session['id'])
            if process:
                process.stop_run()
                session['status'] = 'idle'
            elif self._previous_process_is_alive(session):
                reference = session['process']
                terminate_verified_process(reference['pid'], reference['identity'])
                session['status'] = 'stopped'
                session.pop('process', None)
            return dict(interrupted=True)
        if operation == 'session.inbox.list':
            if session['status'] == 'unknown':
                raise PiControlError('Session queue is unknown until its previous process stops')
            if session['id'] in self.processes:
                state = self.processes[session['id']].request('get_state')
                if state.get('pendingMessageCount'):
                    return dict(data=[dict(id='msg_pi_pending')])
            return dict(data=[])
        if operation == 'session.inbox.cancel':
            if session['id'] in self.processes:
                process = self.processes[session['id']]
                process.request('clear_queue')
                if process.request('get_state').get('pendingMessageCount'):
                    raise PiControlError('Pi queue clearing was not confirmed')
            elif session['status'] == 'unknown':
                raise PiControlError('Pi queue clearing was not confirmed')
            return dict(cancelled=True)
        if operation == 'session.switchModel':
            if session['status'] in ('running', 'unknown'):
                raise PiControlError('Pause the session before changing its model')
            selection = data.get('model', {})
            process = self.start_process(session)
            actual = process.request('set_model', provider=selection['providerID'], modelId=selection['id'])
            if actual.get('provider') != selection['providerID'] or actual.get('id') != selection['id']:
                raise PiControlError('Pi did not confirm the selected model')
            session['model'] = dict(providerID=actual['provider'], id=actual['id'])
            return dict(data=self.public_session(session))
        if operation == 'session.remove':
            return self.remove_session_family(session['id'])
        raise PiControlError('Unsupported Pi control operation')

    def close(self):
        with self.lock:
            for process in self.processes.values():
                process.close()
            self.processes.clear()
            for session in self.sessions.values():
                if not self._previous_process_is_alive(session):
                    session['status'] = 'stopped'
                    session.pop('process', None)
            self.save()


def serve(root):
    try:
        with project_service_lock(root, name='owner', nonblocking=True):
            serve_owned_project(root)
    except OSError as error:
        raise PiControlError('Another Pi service already owns this project') from error


def serve_owned_project(root):
    broker = ProjectPiBroker(root)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass

        def do_POST(self):
            if self.path != '/call' or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2_000_000:
                    raise ValueError()
                request = json.loads(self.rfile.read(length))
                if request.get('operation') == 'service.shutdown':
                    if broker.dispatch('session.active')['data']:
                        raise PiControlError('Stop all project sessions before shutting down the Pi service')
                    broker.close()
                    result = dict(stopped=True)
                    threading.Thread(target=server.shutdown, daemon=True).start()
                else:
                    result = broker.dispatch(request['operation'], request.get('params'), request.get('data'))
                payload, status = dict(result=result), 200
            except PiControlError as error:
                payload, status = dict(error=str(error)), 409
            except Exception:
                # Errors from dependencies and providers can include sensitive values.
                payload, status = dict(error='Pi could not confirm this action; inspect session state before retrying'), 409
            encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    metadata_file = broker.folder / 'connection.json'
    write_private_json(metadata_file, dict(format=1, project=str(broker.root), port=server.server_port, token=token,
                       pid=os.getpid(), identity=process_identity(os.getpid())))
    try:
        server.serve_forever(poll_interval=.2)
    finally:
        broker.close()
        server.server_close()
        metadata_file.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    arguments = parser.parse_args()
    try:
        serve(Path(arguments.root))
    except PiControlError as error:
        import sys
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        import sys
        print('Pi project service could not start; verify its configuration and local runtime', file=sys.stderr)
        raise SystemExit(1)
