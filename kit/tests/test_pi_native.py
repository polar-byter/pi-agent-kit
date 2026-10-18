"""Native terminal ownership, callback admission and safe installed-project updates."""
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from kit import pi_project_update, run_pi
from kit.pi_installation import InstallError, ROOT_FILES, TREES, install_project
from kit.runtimes.pi_broker import ProjectPiBroker, write_private_json
from kit.runtimes.pi_interactive import PiInteractiveProcess
from kit.runtimes.pi_native_state import attach_interactive_session
from kit.runtimes.pi_rpc import PiControlError
from kit.task_metrics import TaskMetrics


class NativeTransportTests(unittest.TestCase):
    def setUp(self):
        self.operations = []
        self.running = False
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_arguments):
                pass

            def do_POST(self):
                if self.headers.get('Authorization') != 'Bearer ' + 'a' * 64:
                    self.send_error(403)
                    return
                command = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.operations.append(command['operation'])
                if command['operation'] == 'get_state':
                    data = dict(settled=not owner.running, isStreaming=owner.running,
                                isCompacting=False, pendingMessageCount=0)
                elif command['operation'] == 'prompt':
                    owner.running = True
                    data = {'disposition': 'started'}
                elif command['operation'] == 'abort':
                    owner.running = False
                    data = None
                else:
                    data = None
                encoded = json.dumps(dict(success=command['operation'] != 'unsupported', data=data)).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(encoded)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.identity = patch('kit.runtimes.pi_interactive.process_identity', return_value='birth')
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.process = PiInteractiveProcess(dict(id='ses_native', process=dict(pid=123, identity='birth'),
            interactive=dict(port=self.server.server_port, token='a' * 64)))

    def close_server(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def test_service_close_aborts_work_without_closing_the_users_terminal(self):
        self.process.request('prompt', message='work')
        self.process.close()
        self.assertFalse(self.running)
        self.assertIn('abort', self.operations)
        self.assertNotIn('shutdown', self.operations)
        self.assertIsNone(self.process.process.poll())

    def test_settled_state_is_confirmed_by_the_native_endpoint(self):
        self.process.request('prompt', message='work')
        self.assertFalse(self.process.settled.is_set())
        self.process.stop_run()
        self.assertTrue(self.process.settled.is_set())

    def test_an_unconfirmed_native_operation_is_an_error(self):
        with self.assertRaises(PiControlError):
            self.process.request('unsupported')

    def test_a_dead_terminal_is_not_contacted_or_replaced(self):
        with patch('kit.runtimes.pi_interactive.process_identity', return_value=None):
            with self.assertRaisesRegex(PiControlError, 'exited'):
                self.process.request('get_state')
        self.assertEqual(self.operations, [])


class NativeSessionBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        write_private_json(self.root / '.pi/kit-runtime.json', dict(format=1, runtime='pi', roles={
            'build': dict(provider='test', model='chief', enabled=True, system_prompt='')}))
        self.broker = ProjectPiBroker(self.root)
        self.addCleanup(self.broker.close)
        self.transcript = self.broker.folder / 'sessions/native-history.jsonl'
        self.transcript.parent.mkdir(exist_ok=True)
        self.transcript.write_text('', encoding='utf-8')
        self.transport = Mock()
        self.transport.request.return_value = dict(sessionFile=str(self.transcript), settled=True)
        self.transport_patch = patch('kit.runtimes.pi_native_state.PiInteractiveProcess', return_value=self.transport)
        self.transport_patch.start()
        self.addCleanup(self.transport_patch.stop)
        self.data = dict(id='ses_native', transcript=str(self.transcript), pid=os.getpid(), port=12345,
                         token='a' * 64, task='native-task')

    def test_the_same_native_session_keeps_one_task_journal(self):
        first = attach_interactive_session(self.broker, self.data)
        second = attach_interactive_session(self.broker, self.data)
        self.assertEqual(first, second)
        self.assertEqual(len(TaskMetrics(self.root).read('native-task')), 1)
        public = self.broker.public_session(self.broker.sessions['ses_native'])
        self.assertNotIn('interactive', public)

    def test_callback_admission_does_not_take_the_process_control_lock(self):
        attach_interactive_session(self.broker, self.data)
        outcomes = []
        with self.broker.lock:
            worker = threading.Thread(target=lambda: outcomes.append(self.broker.dispatch(
                'task.status', {'sessionID': 'ses_native'})))
            worker.start()
            worker.join(timeout=1)
            callback_completed = not worker.is_alive()
        worker.join(timeout=2)
        self.assertTrue(callback_completed, 'Native callback waited for its own interruption lock')
        self.assertFalse(outcomes[0]['finished'])

    def test_another_identity_cannot_register_the_same_history(self):
        attach_interactive_session(self.broker, self.data)
        with self.assertRaisesRegex(PiControlError, 'already owns'):
            attach_interactive_session(self.broker, dict(self.data, id='ses_other'))

    def test_a_native_history_outside_the_service_is_rejected(self):
        with self.assertRaisesRegex(PiControlError, 'must stay'):
            attach_interactive_session(self.broker, dict(self.data, transcript=str(self.root / 'private.jsonl')))
        self.assertEqual(self.broker.sessions, {})

    def test_an_unconfirmed_reattachment_preserves_the_existing_endpoint(self):
        attach_interactive_session(self.broker, self.data)
        before = json.loads(json.dumps(self.broker.sessions['ses_native']))
        self.transport.request.return_value = dict(sessionFile='another-history.jsonl', settled=True)
        with self.assertRaises(PiControlError):
            attach_interactive_session(self.broker, dict(self.data, token='b' * 64))
        self.assertEqual(self.broker.sessions['ses_native'], before)


class ProjectUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / 'template'
        self.source.mkdir()
        for name in ROOT_FILES:
            (self.source / name).write_text('{}' if name.endswith('.json') else 'Template file', encoding='utf-8')
        for tree in TREES:
            (self.source / tree).mkdir()
        (self.source / 'kit/run_pi.py').write_text('old entry', encoding='utf-8')
        self.project = self.base / 'application'
        install_project(self.source, str(self.project))
        self.stop_patch = patch.object(pi_project_update, 'stop_project_services_for_update')
        self.stop_services = self.stop_patch.start()
        self.addCleanup(self.stop_patch.stop)

    def test_update_preserves_application_settings_and_task_history(self):
        settings = self.project / '.pi/kit-models.json'
        settings.write_text('User models', encoding='utf-8')
        (self.project / 'TASK.md').write_text('User requirements', encoding='utf-8')
        (self.source / 'kit/run_pi.py').write_text('native entry', encoding='utf-8')
        result = pi_project_update.update_project(self.source, str(self.project))
        self.assertGreater(result['updated_files'], 0)
        self.assertEqual((self.project / 'kit/run_pi.py').read_text(), 'native entry')
        self.assertEqual(settings.read_text(), 'User models')
        self.assertEqual((self.project / 'TASK.md').read_text(), 'User requirements')

    def test_an_edited_kit_file_blocks_the_update_before_services_stop(self):
        (self.project / 'kit/run_pi.py').write_text('User edit', encoding='utf-8')
        (self.source / 'kit/run_pi.py').write_text('native entry', encoding='utf-8')
        with self.assertRaisesRegex(InstallError, 'was edited'):
            pi_project_update.update_project(self.source, str(self.project))
        self.stop_services.assert_not_called()
        self.assertEqual((self.project / 'kit/run_pi.py').read_text(), 'User edit')

    def test_conflicting_new_files_are_preserved(self):
        (self.source / 'kit/native.py').write_text('new native code', encoding='utf-8')
        (self.project / 'kit/native.py').write_text('user file', encoding='utf-8')
        with self.assertRaises(InstallError):
            pi_project_update.update_project(self.source, str(self.project))
        self.assertEqual((self.project / 'kit/native.py').read_text(), 'user file')

    def test_a_failed_write_restores_previously_updated_files(self):
        for name in ('kit/run_pi.py', 'AGENTS.md'):
            (self.source / name).write_text('new content', encoding='utf-8')
        before = (self.project / 'AGENTS.md').read_bytes()
        original_replace = os.replace
        calls = []
        def fail_second_replace(source, target):
            calls.append(str(target))
            if len(calls) == 2:
                raise OSError('test write failure')
            return original_replace(source, target)
        with patch.object(pi_project_update.os, 'replace', side_effect=fail_second_replace):
            with self.assertRaisesRegex(OSError, 'write failure'):
                pi_project_update.update_project(self.source, str(self.project))
        self.assertEqual((self.project / 'AGENTS.md').read_bytes(), before)
        self.assertEqual((self.project / 'kit/run_pi.py').read_text(), 'old entry')


class NativeEntryTests(unittest.TestCase):
    def test_default_start_opens_native_pi_without_creating_an_rpc_chief(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            (root / 'pi-kit.json').write_text('{"runtime":"pi"}')
            (root / '.pi').mkdir()
            (root / '.pi/kit-runtime.json').write_text('{}')
            stack.enter_context(patch.object(run_pi, 'create_session_gateway'))
            stack.enter_context(patch.object(run_pi, 'resolve_role_model_references'))
            create_rpc = stack.enter_context(patch.object(run_pi, 'create_managed_task'))
            native = stack.enter_context(patch('kit.pi_native.launch_native_pi', return_value=0))
            self.assertEqual(run_pi.main(['--root', str(root)]), 0)
            native.assert_called_once()
            create_rpc.assert_not_called()


class NativeExtensionTests(unittest.TestCase):
    def setUp(self):
        import shutil
        self.node = shutil.which('node')
        if not self.node:
            self.skipTest('Node is not installed')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.operations = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_arguments):
                pass

            def do_POST(self):
                command = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.operations.append(command['operation'])
                results = {'task.status': {'finished': False}, 'task.controlState': {'status': 'cancelled'},
                           'task.workAllowed': {'allowed': True}, 'session.detachInteractive': {'detached': True}}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'result': results.get(command['operation'], {})}).encode())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        write_private_json(self.root / '.pi/kit-service/connection.json', dict(project=str(self.root),
                           port=self.server.server_port, token='a' * 64))
        write_private_json(self.root / '.pi/kit-runtime.json', dict(roles={'build': {'provider': 'test', 'model': 'chief'}}))

    def close_server(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def run_extension(self, checks):
        import subprocess
        javascript = '''
import assert from 'node:assert/strict';
const { createChiefExtension } = await import(process.argv[2]);
const hooks = {};
const pi = { on(name, handler) { hooks[name] = handler; }, registerCommand() {} };
const state = { identifier: 'ses_native', task: 'native-task', session: { model: {provider: 'test', id: 'chief'} } };
createChiefExtension(process.argv[1], state, {noBrowser: true})(pi);
const context = {ui: {notify() {}}};
''' + checks
        module = Path(__file__).resolve().parents[1] / 'pi/native_chief_extension.mjs'
        result = subprocess.run([self.node, '--input-type=module', '-e', javascript, str(self.root), module.as_uri()],
                                cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_quit_detaches_an_already_cancelled_native_conversation(self):
        self.run_extension("await hooks.session_shutdown({reason: 'quit'});")
        self.assertIn('session.detachInteractive', self.operations)
        self.assertNotIn('task.control', self.operations)

    def test_task_metadata_does_not_replace_or_append_a_user_message(self):
        self.run_extension(r'''
const event = Object.freeze({systemPrompt: 'Original system instructions', prompt: 'My exact multiline\nrequirements'});
const result = await hooks.before_agent_start(event, context);
assert.ok(result.systemPrompt.startsWith(event.systemPrompt));
assert.ok(result.systemPrompt.includes('native-task'));
assert.equal(result.message, undefined);
assert.equal(event.prompt, 'My exact multiline\nrequirements');
''')


if __name__ == '__main__':
    unittest.main()
