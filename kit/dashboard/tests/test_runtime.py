"""HTTP behavior of the operational dashboard, independent of future exercises."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlencode

from kit.dashboard import runtime
from kit.dashboard.launcher import project_id
from kit.task_metrics import TaskMetrics


class RuntimeHTTP(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.metrics = TaskMetrics(self.root)
        self.metrics.start('first', title='Первая <b>задача</b>')
        self.metrics.start('second', title='Вторая задача')
        self.server = runtime.DashboardServer(self.root)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def request(self, path, method='GET', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=2)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode('utf-8')
        finally:
            connection.close()

    def test_health_identifies_project_without_exposing_control_token(self):
        code, _, text = self.request('/api/health')
        data = json.loads(text)
        self.assertEqual(code, 200)
        self.assertEqual(data['project_root'], str(self.root.resolve()))
        self.assertEqual(data['project']['id'], project_id(self.root))
        self.assertEqual(data['instance_id'], self.server.instance)
        self.assertNotIn('control_token', data)

    def test_page_is_served_with_no_store(self):
        code, headers, text = self.request('/')
        self.assertEqual(code, 200)
        self.assertIn('text/html', headers['Content-Type'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertIn('Refreshes every 2 seconds', text)
        self.assertIn('id="language-select"', text)

    def test_pi_project_uses_its_runtime_name_and_translations(self):
        (self.root / 'pi-kit.json').write_text(json.dumps({'runtime': 'pi'}), encoding='utf-8')
        code, _, page = self.request('/')
        self.assertEqual(code, 200)
        self.assertIn("data.title + ' · Pi'", page)
        self.assertIn('Prepare Pi', page)
        self.assertNotIn('Prepare OpenCode', page)
        code, _, body = self.request('/api/i18n')
        self.assertEqual(code, 200)
        catalog = json.loads(body)['catalog']
        self.assertEqual(catalog['Pi task'], 'Задача Pi')

    def test_task_id_selects_the_right_journal(self):
        for task, title in [('first', 'Первая <b>задача</b>'), ('second', 'Вторая задача')]:
            code, _, text = self.request('/api/task?' + urlencode({'task': task, 'project': project_id(self.root)}))
            self.assertEqual(code, 200)
            data = json.loads(text)
            self.assertEqual(data['task'], task)
            self.assertEqual(data['title'], title)

    def test_new_events_are_visible_without_restarting_server(self):
        self.metrics.append('first', 'review', work_item='Rules', result='rework')
        code, _, text = self.request('/api/task?task=first')
        data = json.loads(text)
        self.assertEqual(code, 200)
        self.assertEqual(data['event_count'], 2)
        self.assertEqual(data['reworks'], 1)
        self.assertEqual(data['activity'][-1]['work_item'], 'Rules')

    def test_runtime_folder_is_not_listed_as_a_task(self):
        (self.root / '.metrics' / '.dashboard').mkdir()
        code, _, text = self.request('/api/tasks')
        self.assertEqual(code, 200)
        self.assertEqual({row['task'] for row in json.loads(text)}, {'first', 'second'})

    def test_invalid_task_and_wrong_project_are_rejected(self):
        for query in ({'task': '../secret'}, {'task': 'first', 'project': 'wrong'}):
            code, _, _ = self.request('/api/task?' + urlencode(query))
            self.assertEqual(code, 400)
        self.assertEqual(self.request('/api/task?task=first&task=second')[0], 400)

    def test_unknown_task_and_unknown_path_are_not_found(self):
        self.assertEqual(self.request('/api/task?task=missing')[0], 404)
        self.assertEqual(self.request('/opencode.jsonc')[0], 404)

    def test_foreign_host_is_forbidden(self):
        self.assertEqual(self.request('/api/health', headers={'Host': 'evil.example'})[0], 403)

    def test_malformed_journal_does_not_crash_server(self):
        path = self.metrics.task_dir('first') / 'events.jsonl'
        path.write_text('{}\n', encoding='utf-8')
        self.assertEqual(self.request('/api/task?task=first')[0], 400)
        self.assertEqual(self.request('/api/health')[0], 200)

    def test_report_remains_available_after_finish(self):
        self.metrics.finish('first')
        code, headers, text = self.request('/api/report?task=first')
        self.assertEqual(code, 200)
        self.assertIn('text/plain', headers['Content-Type'])
        self.assertEqual(text, (self.metrics.task_dir('first') / 'report.md').read_text(encoding='utf-8'))
        self.assertIn('Первая &lt;b&gt;задача&lt;/b&gt;', text)

    def test_stop_requires_own_token(self):
        self.assertEqual(self.request('/api/stop', 'POST')[0], 403)
        self.assertEqual(self.request('/api/stop', 'POST', {'X-Dashboard-Token': 'wrong'})[0], 403)
        self.assertEqual(self.request('/api/stop', 'POST', {'X-Dashboard-Token': self.server.control_token})[0], 200)
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
