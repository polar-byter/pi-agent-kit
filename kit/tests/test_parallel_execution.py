"""Isolated parallel attempts, acceptance, conflict detection and watchdog routing."""
import json
import fnmatch
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from kit.execution_controller import ExecutionController, worker_permissions
from kit.task_metrics import TaskMetrics
from kit.run_opencode import prepare
from kit.dashboard.tracking import work_items


class FakeService:
    def __init__(self, directory):
        self.directory = str(directory)
        self.running = set()
        self.sessions = {}
        self.prompts = []

    def call(self, operation, params=None, data=None):
        if operation == 'session.create':
            sid = 'ses_worker_' + str(len(self.sessions))
            self.sessions[sid] = dict(data, id=sid, location={'directory': self.directory})
            return {'data': self.sessions[sid]}
        if operation == 'session.prompt':
            self.running.add(params['sessionID'])
            self.prompts.append(data['text'])
            return {'data': {'id': data['id']}}
        if operation == 'session.permission.create':
            rules = self.sessions[params['sessionID']]['permissions']
            effects = []
            for resource in data['resources']:
                matches = [rule for rule in rules if fnmatch.fnmatchcase(data['action'], rule['action'])
                           and fnmatch.fnmatchcase(resource, rule['resource'])]
                effects.append(matches[-1]['effect'] if matches else 'ask')
            return {'data': {'id': 'per_probe', 'effect': 'deny' if 'deny' in effects else effects[0]}}
        if operation == 'session.inbox.list':
            return {'data': []}
        if operation == 'session.get':
            if params['sessionID'] == 'ses_root':
                return {'data': {'id': 'ses_root', 'parentID': None, 'location': {'directory': self.directory}}}
            return {'data': self.sessions[params['sessionID']]}
        raise AssertionError(operation)

    def active(self):
        return set(self.running)

    def interrupt(self, sid):
        self.running.discard(sid)

    def clear_inbox(self, sid):
        pass


class ParallelExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / '.opencode').mkdir()
        self.choices = {'executors': {'source': 'opencode', 'model': 'test/worker'},
                        'bugFixer': {'source': 'opencode', 'model': 'test/fixer'},
                        'execution': {'maxExecutors': 2, 'maxSeconds': 1}}
        self.save_choices()
        (self.root / 'CONTRACT.md').write_text('f returns the module number', encoding='utf-8')
        (self.root / 'tests').mkdir()
        for name, number in (('a', 1), ('b', 2), ('c', 3)):
            (self.root / (name + '.py')).write_text('def f():\n    return 0\n', encoding='utf-8')
            (self.root / 'tests' / ('test_' + name + '.py')).write_text(
                f'import unittest\nimport {name}\nclass Test(unittest.TestCase):\n'
                f'    def test_value(self): self.assertEqual({name}.f(), {number})\n', encoding='utf-8')
        self.metrics = TaskMetrics(self.root)
        self.metrics.start('demo', 'ses_root', track_delegations=True)
        self.home = self.root / '.metrics/demo'
        for name in ('a', 'b', 'c'):
            (self.home / (name + '-requirements.json')).write_text(json.dumps(['Return the module number']), encoding='utf-8')
        self.service = FakeService(self.root)
        self.controller = ExecutionController(self.root, 'demo', self.service, watcher=lambda identifier: None)

    def save_choices(self):
        (self.root / '.opencode/kit-models.json').write_text(json.dumps(self.choices), encoding='utf-8')

    def launch(self, name, **kwargs):
        return self.controller.launch(name, name + '.py', '.metrics/demo/' + name + '-requirements.json', ['CONTRACT.md'], **kwargs)

    def accept(self, attempt, number):
        name = attempt['work_item']
        workspace = self.metrics.attempt_root('demo', attempt)
        (workspace / (name + '.py')).write_text(f'def f():\n    return {number}\n', encoding='utf-8')
        self.controller.stop(attempt['event_id'], 'returned')
        self.metrics.inspect('demo', name)
        result = self.metrics.test('demo', [sys.executable, '-u', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_' + name + '.py'],
                                   scope=name, attempt_id=attempt['event_id'])
        self.assertEqual(result['status'], 'passed')
        checks = self.home / (name + '-checks.json')
        checks.write_text(json.dumps([{'requirement': 'Return the module number', 'code': name + '.f',
                                       'test': 'test_value', 'verified': True}]), encoding='utf-8')
        self.metrics.review('demo', name, 'accepted', checks)

    def test_worker_prompt_names_existing_root_test_files(self):
        attempt = self.launch('a')
        workspace = self.metrics.attempt_root('demo', attempt)
        prompt = self.service.prompts[-1]
        self.assertIn(str(workspace / 'tests/test_a.py'), prompt)
        self.assertNotIn('Tests to read, if needed:', prompt)

    def test_worker_prompt_uses_test_files_next_to_a_nested_application(self):
        (self.root / 'game/app').mkdir(parents=True)
        (self.root / 'game/tests').mkdir()
        (self.root / 'game/app/logic.js').write_text('function createGame() {}', encoding='utf-8')
        (self.root / 'game/tests/logic.test.cjs').write_text('// Game rule tests.', encoding='utf-8')
        attempt = self.controller.launch('nested', 'game/app/logic.js',
            '.metrics/demo/a-requirements.json', ['CONTRACT.md'])
        workspace = self.metrics.attempt_root('demo', attempt)
        prompt = self.service.prompts[-1]
        self.assertIn(str(workspace / 'game/tests/logic.test.cjs'), prompt)
        self.assertNotIn(str(workspace / 'tests/test_a.py'), prompt)

    def test_worker_prompt_does_not_invent_a_missing_test_directory(self):
        for test_file in (self.root / 'tests').iterdir():
            test_file.unlink()
        (self.root / 'tests').rmdir()
        self.launch('a')
        self.assertIn('Test files available to read: none found near this source', self.service.prompts[-1])

    def test_two_isolated_workers_are_checked_and_integrated_independently(self):
        a, b = self.launch('a'), self.launch('b')
        self.assertNotEqual(a['worker_id'], b['worker_id'])
        for attempt, prompt in zip((a, b), self.service.prompts):
            workspace = self.metrics.attempt_root('demo', attempt)
            self.assertIn(str(workspace / 'CONTRACT.md'), prompt)
            self.assertIn(str(workspace / attempt['files'][0]), prompt)
        with self.assertRaisesRegex(ValueError, 'slot'):
            self.launch('c')
        with self.assertRaisesRegex(ValueError, 'stopped'):
            self.metrics.inspect('demo', 'a')
        self.accept(a, 1)
        self.controller.integrate(a['event_id'])
        self.assertIn('return 0', (self.root / 'b.py').read_text())
        self.accept(b, 2)
        self.controller.integrate(b['event_id'])
        self.assertIn('return 1', (self.root / 'a.py').read_text())
        self.assertIn('return 2', (self.root / 'b.py').read_text())
        items = work_items(self.metrics.read('demo'))
        self.assertTrue(all(i['attempts'][-1]['integrated'] for i in items))
        self.assertEqual(len(items[0]['attempts'][-1]['tests']), 1)

    def test_resources_are_relative_and_only_assigned_files_are_writable(self):
        a, b = self.launch('a'), self.launch('b')
        workspace = self.metrics.attempt_root('demo', a)
        sid = self.controller.binding(a['event_id'])
        rules = self.service.sessions[sid]['permissions']
        self.assertTrue(all(not Path(rule['resource']).is_absolute() and '\\' not in rule['resource'] for rule in rules))
        other = self.metrics.attempt_root('demo', b).relative_to(self.root).as_posix() + '/b.py'
        for action, resource in [('edit', other), ('read', other), ('edit', 'CONTRACT.md'),
                                 ('read', str(workspace / 'a.py')), ('edit', workspace.relative_to(self.root).as_posix() + '/b.py')]:
            result = self.service.call('session.permission.create', {'sessionID': sid},
                                       {'action': action, 'resources': [resource]})
            self.assertEqual(result['data']['effect'], 'deny', (action, resource))
        with self.assertRaises(ValueError):
            worker_permissions(self.root, self.root.parent, 'a.py', self.home / 'progress.json')

    def test_native_permission_mismatch_stops_before_watcher_or_model_input(self):
        original = self.service.call
        def mismatched(operation, params=None, data=None):
            if operation == 'session.permission.create':
                return {'data': {'id': 'per_probe', 'effect': 'deny'}}
            return original(operation, params, data)
        watcher = []
        self.controller.start_watcher = watcher.append
        with patch.object(self.service, 'call', side_effect=mismatched):
            with self.assertRaisesRegex(ValueError, 'permission preflight'):
                self.launch('a')
        self.assertEqual(watcher, [])
        self.assertEqual(self.service.prompts, [])
        ended = self.metrics.read('demo')[-1]
        self.assertEqual((ended['kind'], ended['reason'], ended['stopped']), ('attempt_end', 'setup_error', True))

    def test_shared_contract_change_blocks_integration(self):
        a = self.launch('a')
        self.accept(a, 1)
        (self.root / 'CONTRACT.md').write_text('Changed contract', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'contract'):
            self.controller.integrate(a['event_id'])
        self.assertIn('return 0', (self.root / 'a.py').read_text())

    def test_default_policy_allows_two_workers(self):
        del self.choices['execution']
        self.save_choices()
        self.launch('a'), self.launch('b')
        with self.assertRaisesRegex(ValueError, 'slot'):
            self.launch('c')

    def test_lone_attempt_needs_no_contracts_but_overlap_does(self):
        a = self.controller.launch('a', 'a.py', '.metrics/demo/a-requirements.json', [])
        self.assertEqual(a['contracts'], [])
        with self.assertRaisesRegex(ValueError, 'shared contracts'):
            self.launch('b')
        with self.assertRaisesRegex(ValueError, 'shared contracts'):
            self.controller.launch('b', 'b.py', '.metrics/demo/b-requirements.json', [])
        self.accept(a, 1)
        self.launch('b')

    def test_private_server_points_to_the_sequential_protocol(self):
        rows = (self.home / 'events.jsonl').read_text(encoding='utf-8').splitlines()
        rows[0] = json.dumps(dict(json.loads(rows[0]), server_mode='standalone'))
        (self.home / 'events.jsonl').write_text('\n'.join(rows) + '\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Continue sequentially'):
            self.launch('a')

    def test_same_source_cannot_be_assigned_under_another_work_item(self):
        self.launch('a')
        with self.assertRaisesRegex(ValueError, 'already assigned'):
            self.controller.launch('other', 'a.py', '.metrics/demo/b-requirements.json', ['CONTRACT.md'])

    def test_saved_new_choices_do_not_change_a_running_tasks_models_or_capacity(self):
        self.launch('a')
        self.choices['executors']['model'] = 'test/new-model'
        self.choices['execution']['maxExecutors'] = 1
        self.save_choices()
        b = self.launch('b')
        sid = self.controller.binding(b['event_id'])
        self.assertEqual(self.service.sessions[sid]['model']['id'], 'worker')
        with self.assertRaisesRegex(ValueError, 'Finish or cancel'):
            prepare(self.root)

    def test_failed_integration_journal_write_restores_main_source(self):
        a = self.launch('a')
        self.accept(a, 1)
        with patch.object(self.controller.metrics, 'append', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.controller.integrate(a['event_id'])
        self.assertIn('return 0', (self.root / 'a.py').read_text())
        self.controller.integrate(a['event_id'])
        self.assertIn('return 1', (self.root / 'a.py').read_text())

    def test_public_repeat_detection_does_not_recount_exports_or_read_reasoning(self):
        a = self.launch('a')
        sid = self.controller.binding(a['event_id'])
        parts = [{'type': 'reasoning', 'text': 'not a public event'}]
        export = {'info': {'id': sid, 'parentID': 'ses_root'}, 'messages': [
            {'id': 'm1', 'type': 'assistant', 'content': parts}]}
        with patch.object(self.controller.metrics, 'export_session', return_value=export):
            self.assertIsNone(self.controller.observe(a['event_id'], 0))
            for i in range(3):
                parts.append({'id': 'tool-' + str(i), 'type': 'tool', 'tool': 'read',
                              'state': {'status': 'completed', 'input': {'path': 'a.py'}, 'output': 'same'}})
                result = self.controller.observe(a['event_id'], 0)
                if i < 2:
                    self.assertIsNone(result)
                    self.assertIsNone(self.controller.observe(a['event_id'], 0))
            self.assertEqual(result, 'repeated_actions')
        cache = (self.home / ('watch-' + a['event_id'] + '.json')).read_text()
        self.assertNotIn('not a public event', cache)
        self.assertNotIn('same', cache)

    def test_other_attempt_and_root_test_cannot_accept_this_worker(self):
        a, b = self.launch('a'), self.launch('b')
        with self.assertRaisesRegex(ValueError, '--attempt'):
            self.metrics.test('demo', [sys.executable, '-c', 'pass'])
        with self.assertRaisesRegex(ValueError, 'scope'):
            self.metrics.test('demo', [sys.executable, '-c', 'pass'], scope='b', attempt_id=a['event_id'])

    def test_watchdog_hands_off_once_and_keeps_partial_implementation(self):
        self.choices['execution']['fixerMaxAttempts'] = 1
        self.save_choices()
        a = self.launch('a')
        workspace = self.metrics.attempt_root('demo', a)
        (workspace / 'a.py').write_text('def f():\n    return -1\n', encoding='utf-8')
        with patch.object(self.controller, 'observe', side_effect=['step_limit', 'step_limit']):
            result = self.controller.watch(a['event_id'], poll_seconds=0)
            self.assertIn('handoff', result)
            result = self.controller.watch(result['handoff'], poll_seconds=0)
        self.assertTrue(result['stopped'])
        self.assertFalse(self.service.active())
        attempts = [e for e in self.metrics.read('demo') if e['kind'] == 'delegation']
        self.assertEqual([a['role'] for a in attempts], ['executor', 'bug_fixer'])
        self.assertIn('return -1', (self.metrics.attempt_root('demo', attempts[-1]) / 'a.py').read_text())
        self.assertEqual(self.service.sessions[self.controller.binding(attempts[-1]['event_id'])]['model']['id'], 'fixer')

    def test_rate_limit_is_not_an_automatic_paid_fallback(self):
        a = self.launch('a')
        with patch.object(self.controller, 'observe', return_value='rate_limit'):
            self.controller.watch(a['event_id'], poll_seconds=0)
        self.assertEqual(len(self.service.sessions), 1)

    def test_supervisor_start_failure_prevents_input_admission(self):
        self.controller.start_watcher = lambda identifier: (_ for _ in ()).throw(RuntimeError('supervisor unavailable'))
        with self.assertRaisesRegex(RuntimeError, 'supervisor unavailable'):
            self.launch('a')
        self.assertEqual(self.service.prompts, [])
        self.assertFalse(self.service.active())
        self.assertTrue(self.metrics.read('demo')[-1]['stopped'])

    def test_wall_clock_deadline_also_interrupts_a_stuck_observation(self):
        self.choices.pop('bugFixer')
        self.save_choices()
        a = self.launch('a')
        release = threading.Event()
        started = time.monotonic()
        try:
            with patch.object(self.controller, 'observe', side_effect=lambda *args: release.wait(5)):
                result = self.controller.watch(a['event_id'], poll_seconds=0)
            self.assertEqual(result['reason'], 'deadline')
            self.assertLess(time.monotonic() - started, 2)
            self.assertFalse(self.service.active())
        finally:
            release.set()

    def test_stuck_sample_at_deadline_hands_off_instead_of_reporting_api_failure(self):
        a = self.launch('a')
        release = threading.Event()
        try:
            with patch.object(self.controller, 'observe', side_effect=lambda *args: release.wait(5)):
                result = self.controller.watch(a['event_id'], 0)
            self.assertIn('handoff', result)
            ended = [e for e in self.metrics.read('demo') if e['kind'] == 'attempt_end'][0]
            self.assertEqual(ended['reason'], 'deadline')
            self.assertEqual(self.controller.attempt(result['handoff'])['role'], 'bug_fixer')
        finally:
            release.set()

    def test_unavailable_observation_does_not_turn_execution_deadline_into_api_failure(self):
        a = self.launch('a')
        with patch.object(self.controller, 'observe', side_effect=RuntimeError('sampling failed')):
            result = self.controller.watch(a['event_id'], .05)
        self.assertIn('handoff', result)
        events = self.metrics.read('demo')
        self.assertEqual(next(e for e in events if e['kind'] == 'attempt_end')['reason'], 'deadline')
        self.assertNotIn('blocked', [e['result'] for e in events if e['kind'] == 'review'])

    def expired_api_fixture(self):
        a = self.launch('a')
        sid = self.controller.binding(a['event_id'])
        with patch('kit.execution_controller.time.time', return_value=a['at'] + 2):
            self.controller.stop(a['event_id'], 'api_error')
            self.metrics.inspect('demo', 'a')
            self.metrics.review('demo', 'a', 'blocked')
        self.service.sessions[sid]['outcome'] = 'interrupted'
        export = {'info': {'id': sid, 'parentID': 'ses_root'}, 'messages': [
            {'type': 'assistant', 'error': {'type': 'aborted', 'message': 'Step interrupted'}}]}
        return a, export

    def test_audited_timeout_repair_preserves_journal_and_restores_fixer_route(self):
        from kit.execution_policy import attempt_counts
        from kit.task_metrics import corrected_events
        from kit.dashboard.runtime import task_view
        a, export = self.expired_api_fixture()
        journal = self.home / 'events.jsonl'
        before = journal.read_bytes()
        with patch.object(self.controller.metrics, 'export_session', return_value=export), patch('kit.execution_controller.time.time', return_value=a['at'] + 3):
            self.controller.repair_deadline(a['event_id'], 'User requested repair of watchdog classification')
        self.assertTrue(journal.read_bytes().startswith(before))
        events = self.metrics.read('demo')
        self.assertEqual(corrected_events(events), events)
        self.assertEqual(next(e for e in events if e['kind'] == 'review')['result'], 'rework')
        self.assertEqual(attempt_counts(events, 'a')['executor'], 1)
        self.assertEqual(task_view(self.root, 'demo')['reworks'], 1)
        with patch.object(self.controller.metrics, 'export_session', return_value=export):
            with self.assertRaisesRegex(ValueError, 'misclassification'):
                self.controller.repair_deadline(a['event_id'], 'Duplicate')
        successor = self.launch('a', role='bug_fixer', previous=a['event_id'])
        self.assertEqual(successor['role'], 'bug_fixer')

    def test_actual_provider_error_cannot_be_relabelled_as_deadline(self):
        a, export = self.expired_api_fixture()
        export['messages'][0]['error'] = {'type': 'api', 'message': '429 provider quota exhausted'}
        before = self.metrics.read('demo')
        with patch.object(self.controller.metrics, 'export_session', return_value=export):
            with self.assertRaisesRegex(ValueError, 'Provider error'):
                self.controller.repair_deadline(a['event_id'], 'Repair')
        self.assertEqual(self.metrics.read('demo'), before)

    def test_early_api_failure_is_not_a_deadline(self):
        a = self.launch('a')
        self.controller.stop(a['event_id'], 'api_error')
        self.metrics.inspect('demo', 'a')
        self.metrics.review('demo', 'a', 'blocked')
        with self.assertRaisesRegex(ValueError, 'misclassification'):
            self.controller.repair_deadline(a['event_id'], 'Repair')

    def test_native_abort_is_not_reported_as_provider_api_error(self):
        a = self.launch('a')
        sid = self.controller.binding(a['event_id'])
        export = {'info': {'id': sid, 'parentID': 'ses_root'}, 'messages': [
            {'type': 'assistant', 'error': {'type': 'aborted', 'message': 'Step interrupted'}}]}
        with patch.object(self.controller.metrics, 'export_session', return_value=export):
            self.assertEqual(self.controller.observe(a['event_id'], 0), 'cancelled')

    def test_repair_requires_idle_coordinator_too(self):
        a, export = self.expired_api_fixture()
        self.service.running.add('ses_root')
        with patch.object(self.controller.metrics, 'export_session', return_value=export):
            with self.assertRaisesRegex(ValueError, 'all linked execution stopped'):
                self.controller.repair_deadline(a['event_id'], 'Repair')

    def test_correction_cannot_change_acceptance_or_another_attempt(self):
        from kit.task_metrics import corrected_events
        events = [dict(kind='attempt_end', event_id='end', delegation_id='a', reason='api_error', stopped=True, at=1),
                  dict(kind='review', event_id='review', delegation_id='a', result='accepted', at=2),
                  dict(kind='attempt_reclassification', event_id='correction', delegation_id='a',
                       end_event='end', review_event='review', reason='deadline', explanation='Repair', at=3)]
        with self.assertRaisesRegex(ValueError, 'API/blocked'):
            corrected_events(events)
        self.assertEqual(events[1]['result'], 'accepted')
        events[1].update(result='blocked', delegation_id='other')
        with self.assertRaisesRegex(ValueError, 'API/blocked'):
            corrected_events(events)

    def test_progress_exists_before_input_without_claiming_implementation(self):
        original = self.service.call
        def call(operation, params=None, data=None):
            if operation == 'session.prompt':
                paths = list((self.home / 'progress').glob('*.json'))
                self.assertEqual(len(paths), 1)
                value = json.loads(paths[0].read_text())
                self.assertEqual(value['implemented_ids'], [])
                self.assertIsNone(value['current_id'])
                self.assertIn(str(paths[0]), data['text'])
                self.assertIn('You may read files inside this workspace', data['text'])
                self.assertIn('Do not browse the main project', data['text'])
            return original(operation, params, data)
        self.service.call = call
        attempt = self.launch('a')
        self.assertEqual(Path(attempt['workspace']).name, attempt['worker_id'])

    def test_old_three_failure_guard_cannot_abort_handoff(self):
        for _ in range(3):
            # Build history from the former protocol, which could retry the weak role.
            with patch('kit.execution_controller.attempt_counts', return_value={'executor': 0, 'bug_fixer': 0}):
                a = self.launch('a')
            self.controller.stop(a['event_id'], 'deadline')
            self.metrics.inspect('demo', 'a')
            self.assertNotIn('halt', self.metrics.review('demo', 'a', 'rework'))
        fixer = self.launch('a', role='bug_fixer', previous=a['event_id'])
        self.assertEqual(fixer['role'], 'bug_fixer')

    def test_reviewed_code_defect_requires_fixer_instead_of_repeating_weak_model(self):
        a = self.launch('a')
        self.controller.stop(a['event_id'], 'returned')
        self.metrics.inspect('demo', 'a')
        self.metrics.review('demo', 'a', 'rework')
        with self.assertRaisesRegex(ValueError, 'bug fixer'):
            self.launch('a')
        fixer = self.launch('a', role='bug_fixer', previous=a['event_id'])
        self.assertEqual(fixer['role'], 'bug_fixer')

    def test_executor_budget_halts_when_fixer_is_disabled(self):
        self.choices.pop('bugFixer')
        self.choices['execution']['executorMaxAttempts'] = 1
        self.save_choices()
        a = self.launch('a')
        with patch.object(self.controller, 'observe', return_value='deadline'):
            result = self.controller.watch(a['event_id'], 0)
        self.assertIn('executor code repair budget exhausted: 1/1', result['halt'])
        self.assertEqual(len(self.service.sessions), 1)

    def test_dashboard_budget_matches_review_guard_and_keeps_roles_separate(self):
        a = self.launch('a')
        with patch.object(self.controller, 'observe', return_value='step_limit'):
            self.controller.watch(a['event_id'], 0)
        item = work_items(self.metrics.read('demo'))[0]
        self.assertEqual(item['budget']['used'], {'executor': 1, 'bug_fixer': 0})
        self.assertEqual(item['budget']['fixer_limit'], 6)

    def test_progress_write_failure_sends_no_model_request(self):
        write_text = Path.write_text
        def write(path, *args, **kwargs):
            if path.parent.name == 'progress':
                raise OSError('cannot initialize progress')
            return write_text(path, *args, **kwargs)
        with patch.object(Path, 'write_text', write):
            with self.assertRaisesRegex(OSError, 'initialize progress'):
                self.launch('a')
        self.assertFalse(self.service.prompts)
        self.assertEqual(self.metrics.read('demo')[-1]['reason'], 'setup_error')

    def test_fixer_uses_own_budget_then_stops_without_watcher_crash(self):
        self.choices['execution'].update(fixerMaxAttempts=2, maxAttempts=8)
        self.save_choices()
        a = self.launch('a')
        with patch.object(self.controller, 'observe', return_value='step_limit'):
            first = self.controller.watch(a['event_id'], 0)
            second = self.controller.watch(first['handoff'], 0)
            last = self.controller.watch(second['handoff'], 0)
        self.assertIn('bug_fixer code repair budget exhausted: 2/2', last['halt'])
        self.assertEqual(len(self.service.sessions), 3)
        self.assertFalse(self.service.active())

    def test_total_budget_stops_even_with_fixer_budget_remaining(self):
        self.choices['execution'].update(maxAttempts=2, fixerMaxAttempts=6)
        self.save_choices()
        a = self.launch('a')
        with patch.object(self.controller, 'observe', return_value='deadline'):
            first = self.controller.watch(a['event_id'], 0)
            last = self.controller.watch(first['handoff'], 0)
        self.assertIn('2/2 attempts per work item', last['halt'])
        self.assertEqual(len(self.service.sessions), 2)

    def test_partial_source_then_quota_is_blocked_without_spending_code_budget(self):
        from kit.execution_policy import attempt_counts
        a = self.launch('a')
        (self.metrics.attempt_root('demo', a) / 'a.py').write_text('def f():\n    return -1\n')
        with patch.object(self.controller, 'observe', return_value='rate_limit'):
            result = self.controller.watch(a['event_id'], 0)
        events = self.metrics.read('demo')
        self.assertEqual(events[-1]['result'], 'blocked')
        self.assertEqual(events[-1]['changed'], ['a.py'])
        self.assertEqual(attempt_counts(events, 'a'), {'executor': 0, 'bug_fixer': 0})
        self.assertNotIn('handoff', result)
        self.assertEqual(len(self.service.sessions), 1)

    def test_blocked_cannot_hide_a_code_failure(self):
        a = self.launch('a')
        self.controller.stop(a['event_id'], 'deadline')
        self.metrics.inspect('demo', 'a')
        with self.assertRaisesRegex(ValueError, 'infrastructure'):
            self.metrics.review('demo', 'a', 'blocked')

    def test_paused_executor_can_continue_with_a_configured_fixer(self):
        self.choices['bugFixer'] = {'source': 'opencode', 'model': 'test/fixer'}
        self.save_choices()
        attempt = self.launch('a')
        self.controller.stop(attempt['event_id'], 'paused')
        self.metrics.inspect('demo', 'a')
        self.metrics.review('demo', 'a', 'blocked')
        successor = self.launch('a', previous=attempt['event_id'])
        self.assertEqual(successor['role'], 'executor')
        with self.assertRaises(ValueError):
            self.launch('a', previous=attempt['event_id'])

    def test_explicit_infrastructure_retry_preserves_partial_source_and_role(self):
        a = self.launch('a')
        (self.metrics.attempt_root('demo', a) / 'a.py').write_text('def f():\n    return -1\n')
        with patch.object(self.controller, 'observe', return_value='api_error'):
            self.controller.watch(a['event_id'], 0)
        retry = self.launch('a', previous=a['event_id'])
        self.assertEqual(retry['role'], 'executor')
        self.assertIn('return -1', (self.metrics.attempt_root('demo', retry) / 'a.py').read_text())

    def test_duplicate_fixer_successor_is_rejected(self):
        a = self.launch('a')
        self.controller.stop(a['event_id'], 'deadline')
        self.metrics.inspect('demo', 'a')
        self.metrics.review('demo', 'a', 'rework')
        fixer = self.launch('a', role='bug_fixer', previous=a['event_id'])
        self.controller.stop(fixer['event_id'], 'returned')
        self.metrics.inspect('demo', 'a')
        self.metrics.review('demo', 'a', 'rework')
        with self.assertRaisesRegex(ValueError, 'eligible'):
            self.launch('a', role='bug_fixer', previous=a['event_id'])
        with self.assertRaisesRegex(ValueError, 'bounce'):
            self.launch('a')

    def test_unconfirmed_stop_does_not_start_fixer(self):
        a = self.launch('a')
        self.service.interrupt = lambda sid: None
        with patch.object(self.controller, 'observe', return_value='step_limit'), patch('kit.execution_controller.time.sleep'):
            with self.assertRaisesRegex(ValueError, 'unconfirmed'):
                self.controller.watch(a['event_id'], poll_seconds=0)
        self.assertEqual(len(self.service.sessions), 1)

    def test_dependency_and_finish_guards(self):
        with self.assertRaisesRegex(ValueError, 'Dependency'):
            self.launch('b', dependencies=['a'])
        a = self.launch('a')
        with self.assertRaisesRegex(ValueError, 'Resolve'):
            self.metrics.finish('demo')
        self.accept(a, 1)
        with self.assertRaisesRegex(ValueError, 'Integrate'):
            self.metrics.finish('demo')
        self.controller.integrate(a['event_id'])
        with self.assertRaisesRegex(ValueError, 'full test'):
            self.metrics.finish('demo')

    def test_root_session_from_a_different_project_is_never_used(self):
        self.service.directory = str(self.root.parent)
        with self.assertRaisesRegex(ValueError, 'exact project'):
            self.launch('a')
        self.assertEqual(self.service.sessions, {})
        self.assertEqual(self.service.prompts, [])

    def test_finish_requires_all_latest_items_and_full_integrated_tests(self):
        for name, number in (('a', 1), ('b', 2), ('c', 3)):
            attempt = self.launch(name)
            self.accept(attempt, number)
            self.controller.integrate(attempt['event_id'])
        result = self.metrics.test('demo', [sys.executable, '-u', '-m', 'unittest', 'discover', '-s', 'tests'], scope='full')
        self.assertEqual(result['status'], 'passed')
        export = self.home / 'empty-root-export.json'
        export.write_text(json.dumps({'info': {'id': 'ses_root'}, 'messages': []}), encoding='utf-8')
        self.metrics.ux_review('demo', skipped='no browser available in tests')
        text = self.metrics.finish('demo', [str(export)])
        self.assertIn('Расход по попыткам', text)
        self.assertEqual(self.metrics.read('demo')[-1]['kind'], 'finish')


if __name__ == '__main__':
    unittest.main()
