"""Token provenance, unknown counters, completion evidence and local file boundaries."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from kit.dashboard import delivery, observations
from kit.dashboard.tests import test_runtime
from kit.task_metrics import TaskMetrics, TOKEN_FIELDS


def usage_row(model='master', **values):
    row = dict(provider='provider', model=model, messages=2, missing_usage=0, **dict.fromkeys(TOKEN_FIELDS, 10))
    row.update(values)
    return row


class TokenData(unittest.TestCase):
    def setUp(self):
        self.events = [{'kind': 'start', 'at': 100}]
        self.live = {'models': {'master_chief': ['provider/master'], 'executor': ['provider/executor']},
                     'updated_at': 150, 'usage': {'models': [usage_row()], 'sessions': ['root'], 'warnings': []}}

    def test_finish_snapshot_wins_over_later_exports(self):
        self.events.append({'kind': 'finish', 'at': 130, 'ended': 129, 'usage': {'models': [usage_row(input=42)], 'sessions': ['root', 'child'], 'warnings': []}})
        view = observations.token_view(self.events, self.live)
        self.assertEqual(view['totals']['input'], 42)
        self.assertEqual(view['source'], 'finish')
        self.assertEqual(view['snapshot_at'], 129)
        self.assertEqual(view['sessions'], 2)
        self.assertEqual(view['models'][0]['roles'], ['master_chief'])
        self.assertNotIn('total', view['totals'])

    def test_live_columns_sum_models_without_combining_categories(self):
        self.live['usage']['models'].append(usage_row('executor', output=3))
        view = observations.token_view(self.events, self.live)
        self.assertEqual(view['totals']['input'], 20)
        self.assertEqual(view['totals']['output'], 13)
        self.assertEqual(view['totals']['reasoning'], 20)
        self.assertEqual(view['models'][1]['roles'], ['executor'])

    def test_unknown_invalid_and_zero_are_distinct(self):
        for invalid in (None, True, -1, 1.5, '12'):
            self.live['usage']['models'] = [usage_row(input=invalid, cache_write=0), usage_row('executor')]
            view = observations.token_view(self.events, self.live)
            self.assertIsNone(view['totals']['input'])
            self.assertEqual(view['models'][0]['cache_write'], 0)
        self.assertFalse(observations.token_view(self.events, {})['available'])
        self.assertIsNone(observations.token_view(self.events, {})['totals']['input'])

    def test_missing_finish_usage_is_not_replaced_by_unbounded_live_usage(self):
        self.events.append({'kind': 'finish', 'at': 130})
        self.assertFalse(observations.token_view(self.events, self.live)['available'])

    def test_attempt_bindings_distinguish_fixer_usage_from_executor_usage(self):
        self.events[0]['session'] = 'root'
        self.events.extend([
            {'kind': 'attempt_session', 'session': 'worker', 'role': 'executor'},
            {'kind': 'attempt_session', 'session': 'fixer', 'role': 'bug_fixer'}])
        self.live['models']['executor'] = ['provider/shared']
        self.live['usage']['models'] = [usage_row('shared')]
        self.live['usage']['session_usage'] = [dict(session='fixer', provider='provider', model='shared')]
        roles = observations.token_view(self.events, self.live)['models'][0]['roles']
        self.assertEqual(roles, ['bug_fixer'])
        self.live['usage']['session_usage'].append(dict(session='worker', provider='provider', model='shared'))
        roles = observations.token_view(self.events, self.live)['models'][0]['roles']
        self.assertEqual(roles, ['executor', 'bug_fixer'])

    def test_shared_actual_model_lists_both_roles(self):
        self.live['models']['executor'] = ['provider/master']
        self.assertEqual(observations.token_view(self.events, self.live)['models'][0]['roles'], ['master_chief', 'executor'])

    def test_partial_subtotal_combines_complete_and_incomplete_models(self):
        partial = usage_row('executor', input=None, messages=3, missing_usage=1,
                            known={'input': 42}, known_messages={'input': 2})
        self.live['usage']['models'].append(partial)
        view = observations.token_view(self.events, self.live)
        self.assertIsNone(view['totals']['input'])
        self.assertEqual(view['known']['input'], 52)
        self.assertEqual(view['known_messages']['input'], 4)
        self.assertEqual(view['missing_counts']['input'], 1)
        self.assertEqual(view['missing_usage'], 1)
        self.assertEqual(view['totals']['output'], 20)

    def test_all_unknown_and_legacy_unknown_never_become_known_zero(self):
        for metadata in ({}, {'known': {'input': 0}, 'known_messages': {'input': 0}},
                         {'known': {'input': True}, 'known_messages': {'input': 1}},
                         {'known': {'input': 12}, 'known_messages': {'input': 99}}):
            self.live['usage']['models'] = [usage_row(input=None, **metadata)]
            view = observations.token_view(self.events, self.live)
            self.assertIsNone(view['totals']['input'])
            self.assertIsNone(view['known']['input'])

    def test_frozen_partial_snapshot_is_read_without_mutating_journal(self):
        row = usage_row(input=None, known={'input': 0}, known_messages={'input': 1})
        self.events.append({'kind': 'finish', 'at': 130, 'usage': {'models': [row]}})
        before = json.dumps(self.events, sort_keys=True)
        view = observations.token_view(self.events, self.live)
        self.assertEqual(view['known']['input'], 0)
        self.assertEqual(view['missing_counts']['input'], 1)
        self.assertIsNone(view['totals']['input'])
        self.assertEqual(json.dumps(self.events, sort_keys=True), before)

    def test_worker_uses_kit_deduplication_and_excludes_unfinished_messages(self):
        completed = {'id': 'one', 'type': 'assistant', 'time': {'created': 110000, 'completed': 120000},
                     'model': {'providerID': 'provider', 'id': 'master'}, 'tokens': {'input': 12, 'output': 4, 'reasoning': 2, 'cache': {'read': 7, 'write': 0}}, 'content': []}
        incomplete = dict(completed, id='two', time={'created': 125000})
        export = {'info': {'id': 'root'}, 'messages': [completed, incomplete]}
        reader = observations.SessionReader(collect=lambda *args: [export, export], ttl=60)
        events = [{'kind': 'start', 'at': 100, 'session': 'root'}]
        for _ in range(100):
            live = reader.view(Path.cwd(), events)
            if live['available']: break
            time.sleep(.01)
        self.assertTrue(live['available'])
        view = observations.token_view(events, live)
        self.assertEqual(view['totals']['input'], 12)
        self.assertEqual(view['models'][0]['messages'], 1)
        self.assertTrue(any('Незавершённые' in warning for warning in view['warnings']))


class DeliveryData(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='project with spaces ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.metrics = TaskMetrics(self.root); self.metrics.start('task')
        self.events = [{'kind': 'start', 'at': 100}, {'kind': 'test', 'at': 110, 'scope': 'full', 'status': 'passed', 'tests': 8}, {'kind': 'finish', 'at': 130, 'ended': 129}]

    def test_completion_waits_for_finish_and_separates_verification(self):
        self.assertFalse(delivery.completion(self.root, 'task', self.events[:-1])['finished'])
        data = delivery.completion(self.root, 'task', self.events)
        self.assertTrue(data['verified']); self.assertEqual(data['duration_seconds'], 29)
        self.assertEqual(data['project_path'], str(self.root))
        self.assertFalse(delivery.completion(self.root, 'task', [self.events[0], self.events[-1]])['verified'])
        failed = [self.events[0], dict(self.events[1], status='failed'), self.events[-1]]
        self.assertFalse(delivery.completion(self.root, 'task', failed)['verified'])

    def test_pending_delegation_prevents_success_badge(self):
        events = [self.events[0], {'kind':'delegation','at':105,'event_id':'pending'}, *self.events[1:]]
        data = delivery.completion(self.root, 'task', events)
        self.assertFalse(data['verified']); self.assertEqual(data['pending'], 1)

    def test_conventional_launcher_and_explicit_nested_launcher(self):
        (self.root / 'run.ps1').write_text('Write-Output hello', encoding='utf-8')
        self.assertEqual(delivery.launch_file(self.root, 'task').name, 'run.ps1')
        folder = self.root / 'tools'; folder.mkdir(); (folder / 'my start.py').write_text('print(1)', encoding='utf-8')
        progress = self.metrics.task_dir('task') / 'progress'; progress.mkdir()
        (progress / 'result.json').write_text(json.dumps({'launcher':'tools/my start.py'}), encoding='utf-8')
        data = delivery.completion(self.root, 'task', self.events)
        self.assertEqual(data['launcher']['name'], 'tools/my start.py')
        self.assertEqual(data['launcher']['url'], '/launch-file?task=task')

    def test_pi_console_is_not_inferred_as_an_application_launcher(self):
        (self.root / 'pi-kit.json').write_text(json.dumps({'runtime': 'pi'}), encoding='utf-8')
        for name in ('start.cmd', 'start.sh'):
            (self.root / name).write_text('Pi kit console', encoding='utf-8')
        self.assertIsNone(delivery.launch_file(self.root, 'task'))
        (self.root / 'run.cmd').write_text('Application launcher', encoding='utf-8')
        self.assertEqual(delivery.launch_file(self.root, 'task').name, 'run.cmd')

    def test_pi_project_publishes_its_explicit_nested_application_launcher(self):
        (self.root / 'pi-kit.json').write_text(json.dumps({'runtime': 'pi'}), encoding='utf-8')
        (self.root / 'start.cmd').write_text('Pi kit console', encoding='utf-8')
        (self.root / 'game').mkdir()
        (self.root / 'game/play.cmd').write_text('Application launcher', encoding='utf-8')
        progress = self.metrics.task_dir('task') / 'progress'
        progress.mkdir()
        (progress / 'result.json').write_text(json.dumps({'launcher': 'game/play.cmd'}), encoding='utf-8')
        self.assertEqual(delivery.completion(self.root, 'task', self.events)['launcher']['name'], 'game/play.cmd')

    def test_pi_console_is_rejected_when_explicitly_registered_as_a_result(self):
        (self.root / 'pi-kit.json').write_text(json.dumps({'runtime': 'pi'}), encoding='utf-8')
        progress = self.metrics.task_dir('task') / 'progress'
        progress.mkdir()
        for name in ('start.cmd', 'start.sh'):
            (self.root / name).write_text('Pi kit console', encoding='utf-8')
            (progress / 'result.json').write_text(json.dumps({'launcher': name}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'not an application launcher'):
                delivery.launch_file(self.root, 'task')

    def test_unsafe_explicit_launcher_never_becomes_a_link(self):
        folder = self.metrics.task_dir('task') / 'progress'; folder.mkdir()
        for name in ('../outside.ps1', '.opencode/secret.py', str(self.root / 'run.ps1')):
            (folder / 'result.json').write_text(json.dumps({'launcher':name}), encoding='utf-8')
            self.assertIsNone(delivery.completion(self.root, 'task', self.events)['launcher'])
            with self.assertRaises(ValueError): delivery.launch_file(self.root, 'task')
        (folder / 'result.json').write_text('{', encoding='utf-8')
        self.assertIn('launcher_error', delivery.completion(self.root, 'task', self.events))


class DeliveryHTTP(unittest.TestCase):
    setUp = test_runtime.RuntimeHTTP.setUp
    close = test_runtime.RuntimeHTTP.close
    request = test_runtime.RuntimeHTTP.request

    def headers(self):
        return {'Origin': f'http://127.0.0.1:{self.server.server_port}', 'X-Dashboard-UI-Token': self.server.ui_token}

    def test_open_folder_checks_origin_token_and_rejects_any_path(self):
        with patch.object(self.server, 'open_project', return_value={'opened':True}) as open_folder:
            self.assertEqual(self.request('/api/project/open', 'POST')[0], 403)
            self.assertEqual(self.request('/api/project/open', 'POST', dict(self.headers(), Origin='https://foreign'))[0], 403)
            self.assertEqual(self.request('/api/project/open?path=C:/other', 'POST', self.headers())[0], 400)
            open_folder.assert_not_called()
            self.assertEqual(self.request('/api/project/open', 'POST', self.headers())[0], 200)
            open_folder.assert_called_once_with()
        with patch.object(self.server, 'open_project', side_effect=OSError('gone')):
            self.assertEqual(self.request('/api/project/open', 'POST', self.headers())[0], 503)

    def test_native_open_targets_only_server_root(self):
        if os.name == 'nt':
            with patch('kit.dashboard.runtime.os.startfile') as native:
                self.assertTrue(self.server.open_project()['opened'])
                native.assert_called_once_with(str(self.root.resolve()))
        else:
            with patch('kit.dashboard.runtime.subprocess.Popen') as native:
                self.assertTrue(self.server.open_project()['opened'])
                self.assertEqual(native.call_args.args[0][-1], str(self.root.resolve()))

    def test_launch_file_is_readonly_escaped_and_cannot_select_a_secret(self):
        (self.root / 'run.ps1').write_text('<script>window.hacked=1</script>', encoding='utf-8')
        (self.root / 'secret.txt').write_text('SECRET', encoding='utf-8')
        code, _, body = self.request('/launch-file?task=first&path=secret.txt')
        self.assertEqual(code, 200); self.assertIn('&lt;script&gt;', body); self.assertNotIn('<script>', body); self.assertNotIn('SECRET', body)
        self.assertEqual(self.request('/launch-file?task=../outside')[0], 400)
        self.assertEqual(self.request('/launch-file?task=missing')[0], 404)
        (self.root / 'run.ps1').unlink()
        self.assertEqual(self.request('/launch-file?task=first')[0], 404)

    def test_finish_tokens_work_without_cli_or_architecture(self):
        self.metrics.append('first', 'finish', ended=time.time(), usage={'models':[usage_row(input=25)], 'sessions':['root'], 'warnings':[]})
        code, _, body = self.request('/api/task?task=first')
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(data['tokens']['totals']['input'],25)
        self.assertTrue(data['completion']['finished'])
        self.assertFalse(data['completion']['verified'])

    def test_bad_token_snapshot_does_not_hide_finished_state(self):
        self.metrics.append('first', 'finish', ended=time.time(), usage={'models':['bad']})
        code, _, body = self.request('/api/task?task=first')
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertFalse(data['tokens']['available']); self.assertEqual(data['status'],'finished')


if __name__ == '__main__':
    unittest.main()
