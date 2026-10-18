"""Broker protocol checks with controlled RPC and a separate optional native smoke."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from kit.runtimes.pi_broker import ProjectPiBroker, project_service_lock, write_private_json
from kit.runtimes.pi_exports import normalize_session_export
from kit.runtimes.pi_rpc import PiControlError, PiRpcProcess, process_identity


FAKE_RPC_SOURCE = '''import json, sys, time
running = False
pending = 0
for line in sys.stdin:
    request = json.loads(line)
    operation = request['type']
    data = None
    if operation == 'get_state':
        data = dict(isStreaming=running, isCompacting=False, pendingMessageCount=pending)
    elif operation == 'prompt':
        running = True
        data = dict(disposition='started')
        if request.get('message') == 'unsettled':
            running = False
            print(json.dumps(dict(type='agent_end')), flush=True)
    elif operation == 'abort':
        running = False
        print(json.dumps(dict(type='agent_settled')), flush=True)
    elif operation == 'clear_queue':
        pending = 0
        data = dict(steering=[], followUp=[])
    elif operation == 'get_entries':
        data = dict(entries=[])
    elif operation == 'set_model':
        data = dict(provider=request['provider'], id=request['modelId'])
    print(json.dumps(dict(type='response', id=request['id'], command=operation, success=True, data=data)), flush=True)
'''


class PiRuntimeTests(unittest.TestCase):

    def test_aborted_export_does_not_require_an_error_message(self):
        export = normalize_session_export(dict(id='ses_test', project='project'), [dict(
            id='message', message=dict(role='assistant', stopReason='aborted', content=[]))])
        self.assertEqual(export['messages'][0]['info']['error']['type'], 'aborted')

    def test_length_export_preserves_the_finish_reason_without_provider_error(self):
        export = normalize_session_export(dict(id='ses_test', project='project'), [dict(
            id='message', message=dict(role='assistant', stopReason='length', content=[]))])
        self.assertEqual(export['messages'][0]['info']['finish'], 'length')
        self.assertNotIn('error', export['messages'][0]['info'])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.fake_script = self.root / 'fake_rpc.py'
        self.fake_script.write_text(FAKE_RPC_SOURCE, encoding='utf-8')
        roles = {role: dict(provider='local', model='test', enabled=True, system_prompt='')
                 for role in ('build', 'executor', 'bug-fixer', 'executor-fast')}
        write_private_json(self.root / '.pi/kit-runtime.json', dict(format=1, runtime='pi', roles=roles,
                          agent_directory=str(self.root / '.pi/agent')))
        self.command_patch = patch('kit.pi_configuration.locate_pi_command', return_value=[sys.executable, '-u', str(self.fake_script)])
        self.command_patch.start()
        self.broker = ProjectPiBroker(self.root)

    def tearDown(self):
        self.broker.close()
        self.command_patch.stop()
        self.temporary.cleanup()

    def create_root(self):
        return self.broker.dispatch('session.create', data=dict(title='test'))['data']['id']

    def test_startup_lock_waits_without_reading_another_process_locked_byte(self):
        command = ('import sys,time; from kit.runtimes.pi_broker import project_service_lock; '
                   'lease=project_service_lock(sys.argv[1]); lease.__enter__(); '
                   'print("locked",flush=True); time.sleep(.4); lease.__exit__(None,None,None)')
        process = subprocess.Popen([sys.executable, '-B', '-u', '-c', command, str(self.root)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   cwd=Path(__file__).resolve().parents[2])
        try:
            self.assertEqual(process.stdout.readline().strip(), 'locked')
            with project_service_lock(self.root):
                pass
            self.assertEqual(process.wait(timeout=5), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()

    def test_shutdown_of_a_dead_service_does_not_contact_its_old_port(self):
        from kit.runtimes.pi_gateway import PiSessionControl
        gateway = PiSessionControl(self.root)
        write_private_json(gateway.connection_file, dict(format=1, project=str(self.root),
                           port=12345, token='a' * 40, pid=123456, identity='old-owner'))
        with patch('kit.runtimes.pi_gateway.process_identity', return_value=None), \
                patch.object(gateway, '_request') as request:
            self.assertEqual(gateway.shutdown_service(), dict(stopped=True))
        request.assert_not_called()
        self.assertFalse(gateway.connection_file.exists())

    def test_connection_metadata_requires_a_process_identity(self):
        from kit.runtimes.pi_gateway import PiSessionControl
        gateway = PiSessionControl(self.root)
        for value in ([], {}, dict(format=1, project=str(self.root), port=True, token='a' * 40)):
            write_private_json(gateway.connection_file, value)
            self.assertIsNone(gateway._read_connection())

    def test_chief_uses_the_native_platform_shell(self):
        identifier = self.create_root()
        command = self.broker.processes[identifier].process.args
        enabled_tools = command[command.index('--tools') + 1].split(',')
        self.assertIn('powershell' if os.name == 'nt' else 'bash', enabled_tools)
        self.assertNotIn('bash' if os.name == 'nt' else 'powershell', enabled_tools)
        self.assertEqual(set(enabled_tools), {'read', 'edit', 'write', 'powershell' if os.name == 'nt' else 'bash'})

    def test_admission_is_idempotent_and_requires_same_text(self):
        identifier = self.create_root()
        parameters = dict(sessionID=identifier)
        prompt = dict(id='msg_first', text='one')
        self.assertEqual(self.broker.dispatch('session.prompt', parameters, prompt), dict(data=dict(id='msg_first')))
        self.assertEqual(self.broker.dispatch('session.prompt', parameters, prompt), dict(data=dict(id='msg_first')))
        with self.assertRaises(PiControlError):
            self.broker.dispatch('session.prompt', parameters, dict(id='msg_first', text='other'))
        self.assertIn(identifier, self.broker.dispatch('session.active')['data'])
        self.broker.dispatch('session.interrupt', parameters)
        self.assertNotIn(identifier, self.broker.dispatch('session.active')['data'])

    def test_unknown_admission_is_never_replayed(self):
        identifier = self.create_root()
        original_request = self.broker.processes[identifier].request
        def lose_prompt_confirmation(operation, **fields):
            if operation == 'prompt':
                raise PiControlError('timeout')
            return original_request(operation, **fields)
        with patch.object(self.broker.processes[identifier], 'request', side_effect=lose_prompt_confirmation):
            with self.assertRaises(PiControlError):
                self.broker.dispatch('session.prompt', dict(sessionID=identifier), dict(id='msg_unknown', text='work'))
        with self.assertRaises(PiControlError):
            self.broker.dispatch('session.prompt', dict(sessionID=identifier), dict(id='msg_unknown', text='work'))
        registry = json.loads(self.broker.registry_file.read_text())
        self.assertEqual(registry['sessions'][identifier]['admissions']['msg_unknown']['status'], 'unknown')

    def test_crashed_owned_process_keeps_an_error_outcome_in_the_registry(self):
        identifier = self.create_root()
        parameters = {'sessionID': identifier}
        self.broker.dispatch('session.prompt', parameters, {'id': 'msg_crash', 'text': 'work'})
        owned_process = self.broker.processes[identifier]
        owned_process.process.kill()
        owned_process.process.wait(timeout=5)
        self.assertNotIn(identifier, self.broker.dispatch('session.active')['data'])
        session = self.broker.dispatch('session.get', parameters)['data']
        self.assertEqual(session['status'], 'stopped')
        self.assertEqual(session['outcome']['type'], 'error')
        self.assertEqual(session['outcome']['code'], 'process_exit')
        registry = json.loads(self.broker.registry_file.read_text(encoding='utf-8'))
        self.assertEqual(registry['sessions'][identifier]['outcome'], session['outcome'])
        self.assertEqual(registry['sessions'][identifier]['admissions']['msg_crash']['status'], 'accepted')
        owned_process.close()

    def test_agent_end_alone_does_not_confirm_idle(self):
        identifier = self.create_root()
        self.broker.dispatch('session.prompt', dict(sessionID=identifier), dict(id='msg_unsettled', text='unsettled'))
        self.assertIn(identifier, self.broker.dispatch('session.active')['data'])
        self.broker.dispatch('session.interrupt', dict(sessionID=identifier))
        self.assertNotIn(identifier, self.broker.dispatch('session.active')['data'])

    def test_restart_cannot_spawn_second_writer(self):
        identifier = self.create_root()
        recovered = ProjectPiBroker(self.root)
        self.assertEqual(recovered.sessions[identifier]['status'], 'unknown')
        with self.assertRaises(PiControlError):
            recovered.start_process(recovered.session(identifier))
        self.broker.close()
        process = recovered.start_process(recovered.session(identifier))
        self.assertIsNotNone(process)
        recovered.close()

    def test_closed_session_can_restore_history_and_change_model(self):
        identifier = self.create_root()
        self.broker.close()
        recovered = ProjectPiBroker(self.root)
        try:
            result = recovered.dispatch('session.switchModel', dict(sessionID=identifier), dict(model=dict(providerID='other', id='next')))
            self.assertEqual(result['data']['model'], dict(providerID='other', id='next'))
        finally:
            recovered.close()

    def test_recovered_orphan_requires_confirmed_process_exit(self):
        identifier = self.create_root()
        recovered = ProjectPiBroker(self.root)
        self.assertIn(identifier, recovered.dispatch('session.active')['data'])
        recovered.dispatch('session.interrupt', dict(sessionID=identifier))
        self.assertNotIn(identifier, recovered.dispatch('session.active')['data'])
        recovered.close()

    def test_prepare_models_validates_frozen_choices_without_rewriting_configuration(self):
        from kit.runtimes.pi_gateway import PiSessionControl
        choices = dict(masterChief=dict(source='api', model='test'))
        configuration_path = self.root / '.pi/kit-runtime.json'
        prepared = json.loads(configuration_path.read_text())
        prepared['choices'] = choices
        write_private_json(configuration_path, prepared)
        before = configuration_path.read_bytes()
        gateway = PiSessionControl(self.root)
        calls = []
        def control(operation, *arguments):
            calls.append(operation)
            return dict(data=[dict(providerID='local', id='test')]) if operation == 'model.list' else dict(prepared=True)
        with patch.object(gateway, 'call', side_effect=control):
            gateway.prepare_models(choices, dict(masterChief='local/test'))
            self.assertEqual(calls, ['service.reload', 'model.list'])
            with self.assertRaises(PiControlError):
                gateway.prepare_models(dict(masterChief='changed'), dict(masterChief='local/test'))
            with self.assertRaises(PiControlError):
                gateway.prepare_models(choices, dict(masterChief='foreign/model'))
        self.assertEqual(configuration_path.read_bytes(), before)

    def test_worker_cannot_use_unknown_parent_or_unbounded_workspace(self):
        with self.assertRaises(PiControlError):
            self.broker.dispatch('session.create', data=dict(parentID='ses_foreign', agent='executor'))
        identifier = self.create_root()
        with self.assertRaises(PiControlError):
            self.broker.dispatch('session.create', data=dict(parentID=identifier, agent='executor', workspace=str(self.root),
                                 source=str(self.root / 'source.py'), progress=str(self.root / 'progress.json')))

    def test_live_session_cannot_be_deleted(self):
        identifier = self.create_root()
        parameters = dict(sessionID=identifier)
        self.broker.dispatch('session.prompt', parameters, dict(id='msg_work', text='work'))
        with self.assertRaises(PiControlError):
            self.broker.dispatch('session.remove', parameters)
        self.broker.dispatch('session.interrupt', parameters)
        self.assertTrue(self.broker.dispatch('session.remove', parameters)['removed'])
        self.assertFalse(self.broker.sessions)

    def test_unknown_native_error_is_not_copied_into_export(self):
        session = dict(id='ses_test', project=str(self.root), agent='build', model=dict(providerID='test', id='one'))
        entry = dict(id='entry', timestamp='2026-10-18T00:00:00Z', message=dict(role='assistant',
            content=[dict(type='thinking', thinking='private'), dict(type='text', text='public')],
            errorMessage='secret token=abc 429', usage=dict(input=2, output=3, cacheRead=1, cacheWrite=0, cost=dict(total=.2))))
        result = normalize_session_export(session, [entry])
        self.assertEqual(result['messages'][0]['info']['id'], 'msg_entry')
        self.assertEqual(result['messages'][0]['info']['tokens']['input'], 2)
        self.assertEqual(result['messages'][0]['parts'], [dict(type='text', text='public')])
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('private', json.dumps(result))

    def test_process_identity_disappears_after_exit(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])
        try:
            self.assertTrue(process_identity(process.pid))
        finally:
            process.terminate()
            process.wait(timeout=5)
        self.assertIsNone(process_identity(process.pid))


class NativePiRuntimeSmoke(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('PI_KIT_NATIVE_SMOKE') == '1', 'native Pi smoke is explicitly selected')
    def test_rpc_and_worker_extension_without_model_request(self):
        repository = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            agent_directory = root / '.pi/agent'
            agent_directory.mkdir(parents=True)
            write_private_json(root / '.pi/installation.json', dict(runtime_root=str(repository)))
            write_private_json(agent_directory / 'models.json', dict(providers={'kit-offline': dict(
                baseUrl='http://127.0.0.1:1/v1', api='openai-completions', apiKey='offline-smoke',
                models=[dict(id='offline', name='Offline smoke', reasoning=False, input=['text'],
                             contextWindow=32000, maxTokens=512, cost=dict(input=0, output=0, cacheRead=0, cacheWrite=0))])}))
            roles = {role: dict(provider='kit-offline', model='offline', enabled=True, system_prompt='')
                     for role in ('build', 'executor')}
            write_private_json(root / '.pi/kit-runtime.json', dict(format=1, runtime='pi', roles=roles, agent_directory=str(agent_directory)))
            broker = ProjectPiBroker(root)
            try:
                parent = broker.dispatch('session.create', data=dict(title='native smoke'))['data']['id']
                workspace = root / '.metrics/smoke/workspaces/worker'
                workspace.mkdir(parents=True)
                source = workspace / 'source.py'
                source.write_text('value = 1\n')
                progress = root / '.metrics/smoke/progress/worker.json'
                progress.parent.mkdir()
                progress.write_text('{}')
                child = broker.dispatch('session.create', data=dict(parentID=parent, agent='executor',
                    workspace=str(workspace), source=str(source), progress=str(progress)))['data']['id']
                for action, resource, expected in [('read', str(source), 'allow'), ('edit', str(source), 'allow'),
                    ('read', str(workspace), 'allow'), ('edit', str(workspace / 'other.py'), 'deny'),
                    ('read', str(root / '.env'), 'deny'), ('shell', '*', 'deny'), ('subagent', '*', 'deny')]:
                    result = broker.dispatch('session.permission.create', dict(sessionID=child), dict(action=action, resources=[resource]))
                    self.assertEqual(result['data']['effect'], expected, (action, resource))
                self.assertEqual(broker.dispatch('session.active')['data'], {})
                self.assertEqual(broker.export(broker.session(child))['messages'], [])
                broker.dispatch('session.interrupt', dict(sessionID=child))
                self.assertEqual(source.read_text(), 'value = 1\n')
                process = broker.processes[child]
                nonce = 'nested-check'
                process.request('prompt', message='/kit-permission-check ' + json.dumps(dict(
                    nonce=nonce, tool='read', input=dict(path=str(source)), parentToolCallId='outer/1')))
                notification = next(event for event in process.events if nonce in event.get('message', ''))
                self.assertFalse(json.loads(notification['message'].split(':', 1)[1])['allowed'])
                alias = workspace / 'source-alias.py'
                os.link(source, alias)
                try:
                    self.assertFalse(broker.permission_check(broker.session(child), 'read', str(source)))
                finally:
                    alias.unlink()
                self.assertTrue(broker.permission_check(broker.session(child), 'edit', str(source)))
            finally:
                broker.close()

            # Two independent clients reconnect to one authenticated service.
            from kit.runtimes.pi_gateway import PiSessionControl, collect_session_exports
            from urllib.error import HTTPError
            from urllib.request import Request, urlopen
            gateway = PiSessionControl(root)
            try:
                gateway.capabilities()
                connection = json.loads(gateway.connection_file.read_text())
                request = Request('http://127.0.0.1:' + str(connection['port']) + '/call',
                    json.dumps(dict(operation='service.health')).encode(), {'Authorization': 'Bearer invalid'})
                with self.assertRaises(HTTPError) as caught:
                    urlopen(request, timeout=3)
                self.assertEqual(caught.exception.code, 403)
                other_gateway = PiSessionControl(root)
                self.assertEqual(other_gateway.tree(parent), [parent, child])
                self.assertEqual(json.loads(other_gateway.connection_file.read_text())['pid'], connection['pid'])
                self.assertEqual([row['info']['id'] for row in collect_session_exports(root, parent)], [parent, child])
                self.assertEqual(gateway.active(), set())
                gateway.switch_model(parent, 'kit-offline/offline')
                gateway.remove(child)
                gateway.remove(parent)
                self.assertEqual(gateway.sessions(), [])
            finally:
                gateway.shutdown_service()
                deadline = time.monotonic() + 5
                while gateway.connection_file.exists() and time.monotonic() < deadline:
                    time.sleep(.05)


if __name__ == '__main__':
    unittest.main()
