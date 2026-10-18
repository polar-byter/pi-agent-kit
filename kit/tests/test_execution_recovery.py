"""Regression scenarios found during the autonomous tanks_test run."""
import json
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from kit.tests import test_parallel_execution as fixtures
from kit.execution_watch import claim_attempt_watcher, launch_summary
from kit.execution_policy import attempt_counts


class ExecutionRecoveryTests(unittest.TestCase):
    setUp = fixtures.ParallelExecutionTests.setUp
    save_choices = fixtures.ParallelExecutionTests.save_choices
    launch = fixtures.ParallelExecutionTests.launch

    def test_worker_identifier_explains_the_exact_attempt_without_rebinding(self):
        attempt = self.launch('a')
        with self.assertRaisesRegex(ValueError, 'Use --attempt ' + attempt['event_id']):
            self.controller.binding(attempt['worker_id'])
        self.assertEqual(len(self.service.sessions), 1)

    def test_unknown_identifier_has_a_distinct_diagnostic(self):
        with self.assertRaisesRegex(ValueError, 'No session binding'):
            self.controller.binding('missing')

    def test_failed_empty_attempt_can_continue_through_the_selected_fixer(self):
        attempt = self.launch('a')
        self.controller.stop(attempt['event_id'], 'returned')
        self.metrics.inspect('demo', 'a')
        self.metrics.review('demo', 'a', 'failed')
        self.assertEqual(attempt_counts(self.metrics.read('demo'), 'a')['executor'], 1)
        with self.assertRaisesRegex(ValueError, 'bug fixer'):
            self.launch('a')
        successor = self.launch('a', role='bug_fixer', previous=attempt['event_id'])
        self.assertEqual(successor['role'], 'bug_fixer')
        self.assertEqual(self.service.sessions[self.controller.binding(successor['event_id'])]['model']['id'], 'fixer')
        with self.assertRaises(ValueError):
            self.launch('a', role='bug_fixer', previous=attempt['event_id'])

    def test_repeated_stop_records_one_terminal_event(self):
        attempt = self.launch('a')
        first = self.controller.stop(attempt['event_id'], 'returned')
        second = self.controller.stop(attempt['event_id'], 'deadline')
        self.assertEqual(first, second)
        ended = [e for e in self.metrics.read('demo') if e['kind'] == 'attempt_end']
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0]['reason'], 'returned')

    def test_second_watcher_cannot_sample_or_duplicate_the_first(self):
        attempt = self.launch('a')
        entered, release = threading.Event(), threading.Event()
        results, errors = [], []
        def observe(identifier, elapsed):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Test did not release the watcher')
            return 'returned'
        def run():
            try:
                results.append(self.controller.watch(attempt['event_id'], poll_seconds=0))
            except Exception as error:
                errors.append(error)
        with patch.object(self.controller, 'observe', side_effect=observe) as sample:
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                duplicate = self.controller.watch(attempt['event_id'], poll_seconds=0)
                self.assertEqual(duplicate['kind'], 'watching')
                self.assertEqual(sample.call_count, 1)
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(results[0]['stopped'])
        self.assertEqual(len([e for e in self.metrics.read('demo') if e['kind'] == 'attempt_end']), 1)

    def test_watcher_lock_is_released_after_its_process_is_killed(self):
        path = self.home / 'process-watcher.lock'
        code = ('import sys,time; from pathlib import Path; '
                'from kit.execution_watch import claim_attempt_watcher; '
                'context=claim_attempt_watcher(Path(sys.argv[1])); '
                'assert context.__enter__(); print("ready",flush=True); time.sleep(30)')
        process = subprocess.Popen([sys.executable, '-B', '-c', code, str(path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            with claim_attempt_watcher(path) as acquired:
                self.assertFalse(acquired)
        finally:
            process.kill()
            process.communicate(timeout=5)
        with claim_attempt_watcher(path) as acquired:
            self.assertTrue(acquired)

    def test_launch_summary_has_a_short_unambiguous_followup_command(self):
        attempt = self.launch('a')
        summary = launch_summary('demo', attempt)
        self.assertEqual(summary['attempt_id'], attempt['event_id'])
        self.assertIn('--attempt ' + attempt['event_id'], summary['watch_command'])
        self.assertEqual(summary['supervision'], 'automatic')
        self.assertNotIn('requirements', summary)
        self.assertLess(len(json.dumps(summary)), 1000)

    def export_fixture(self, finish, tool_count=0):
        attempt = self.launch('a')
        sid = self.controller.binding(attempt['event_id'])
        export = dict(info=dict(id=sid, parentID='ses_root'), messages=[dict(
            info=dict(role='assistant', finish=finish), parts=[dict(type='tool', id=str(i),
                state=dict(status='completed', input=dict(i=i), output='read')) for i in range(tool_count)])])
        return attempt, sid, export

    def test_inactive_length_finish_is_not_a_successful_return(self):
        attempt, sid, export = self.export_fixture('length')
        self.service.running.discard(sid)
        with patch.object(self.controller.metrics, 'export_session', return_value=export), patch.object(self.controller, 'metrics_cli', return_value='unused'):
            self.assertEqual(self.controller.observe(attempt['event_id'], 0), 'token_limit')

    def test_active_session_is_not_ended_by_a_historical_length_finish(self):
        attempt, sid, export = self.export_fixture('length')
        with patch.object(self.controller.metrics, 'export_session', return_value=export), patch.object(self.controller, 'metrics_cli', return_value='unused'):
            self.assertIsNone(self.controller.observe(attempt['event_id'], 0))

    def test_parallel_tool_calls_each_consume_the_public_step_budget(self):
        attempt, sid, export = self.export_fixture('tool-calls', tool_count=24)
        with patch.object(self.controller.metrics, 'export_session', return_value=export), patch.object(self.controller, 'metrics_cli', return_value='unused'):
            self.assertEqual(self.controller.observe(attempt['event_id'], 0), 'step_limit')

    def test_token_limit_hands_off_once_without_changing_model_choices(self):
        attempt = self.launch('a')
        with patch.object(self.controller, 'observe', return_value='token_limit'):
            result = self.controller.watch(attempt['event_id'], poll_seconds=0)
        self.assertIn('handoff', result)
        events = self.metrics.read('demo')
        self.assertEqual([e['result'] for e in events if e['kind'] == 'review'], ['rework'])
        self.assertEqual([e['role'] for e in events if e['kind'] == 'delegation'], ['executor', 'bug_fixer'])
