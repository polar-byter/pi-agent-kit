"""A paused task remains understandable in both console entry modes."""
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from kit import run_pi
from kit.loop_guards import TaskHalted


class PiConsoleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'pi-kit.json').write_text(json.dumps({'runtime': 'pi'}), encoding='utf-8')
        (self.root / '.pi').mkdir()
        (self.root / '.pi/kit-runtime.json').write_text('{}', encoding='utf-8')

    @contextmanager
    def configured_console_without_model_calls(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(run_pi, 'create_session_gateway', return_value=Mock()))
            stack.enter_context(patch.object(run_pi, 'resolve_role_model_references', return_value={}))
            stack.enter_context(patch.object(run_pi, 'create_managed_task', return_value=('task', 'ses_console')))
            stack.enter_context(patch.object(run_pi, 'ensure_dashboard', return_value={'url': 'http://127.0.0.1/'}))
            stack.enter_context(patch.object(run_pi, 'submit_user_request', side_effect=TaskHalted('Task control: paused')))
            output, errors = StringIO(), StringIO()
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(errors))
            yield output, errors

    def test_one_shot_paused_request_returns_the_protective_exit_code(self):
        with self.configured_console_without_model_calls() as (_, errors):
            result = run_pi.main(['--root', str(self.root), '--headless', '--prompt', 'continue', '--no-browser'])
        self.assertEqual(result, 3)
        self.assertIn('paused', errors.getvalue())
        self.assertNotIn('Traceback', errors.getvalue())

    def test_interactive_pause_keeps_the_console_available_for_local_commands(self):
        with self.configured_console_without_model_calls() as (_, errors), \
                patch('builtins.input', side_effect=['continue', '/quit']):
            result = run_pi.main(['--root', str(self.root), '--headless', '--no-browser'])
        self.assertEqual(result, 0)
        self.assertIn('paused', errors.getvalue())
        self.assertNotIn('Traceback', errors.getvalue())


class PiCompletionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('test-project')
        self.gateway = Mock()
        self.gateway.export_session.return_value = {'messages': []}
        self.gateway.tree.return_value = {'ses_chief', 'ses_worker'}
        self.gateway.active.return_value = set()
        self.gateway.call.return_value = {'data': {'outcome': {}}}
        self.metrics = Mock()
        self.metrics.read.return_value = [{'kind': 'start'}]
        self.metrics_patch = patch.object(run_pi, 'TaskMetrics', return_value=self.metrics)
        self.metrics_patch.start()
        self.addCleanup(self.metrics_patch.stop)
        self.output_patch = patch('sys.stdout', new=StringIO())
        self.output_patch.start()
        self.addCleanup(self.output_patch.stop)

    def wait_for_chief(self, **options):
        return run_pi.wait_for_chief(self.root, self.gateway, 'task', 'ses_chief', **options)

    def test_idle_chief_without_finish_is_reported_as_incomplete(self):
        with self.assertRaisesRegex(RuntimeError, 'incomplete.*--session ses_chief'):
            self.wait_for_chief()
        self.metrics.read_events_if_work_allowed.assert_called_once_with('task')

    def test_idle_family_with_finish_is_the_successful_outcome(self):
        self.metrics.read.return_value.append({'kind': 'finish'})
        self.assertIsNone(self.wait_for_chief())
        self.metrics.read_events_if_work_allowed.assert_not_called()

    def test_active_worker_keeps_the_wait_open_after_chief_becomes_idle(self):
        self.gateway.active.side_effect = [{'ses_worker'}, set()]
        self.metrics.read.return_value.append({'kind': 'finish'})
        with patch.object(run_pi.time, 'sleep') as sleep:
            self.assertIsNone(self.wait_for_chief())
        sleep.assert_called_once_with(.25)
        self.assertEqual(self.gateway.export_session.call_count, 2)

    def test_protective_stop_remains_a_stop_when_the_chief_is_idle(self):
        self.metrics.read_events_if_work_allowed.side_effect = TaskHalted('STOP: user decision required')
        with self.assertRaisesRegex(TaskHalted, 'user decision'):
            self.wait_for_chief()

    def test_native_process_failure_is_not_treated_as_a_finished_turn(self):
        self.gateway.call.return_value = {'data': {'outcome': {'type': 'error', 'code': 'process_exit'}}}
        with self.assertRaisesRegex(RuntimeError, 'Pi ended with an error'):
            self.wait_for_chief()

    def test_timeout_does_not_interrupt_or_replay_the_running_session(self):
        self.gateway.active.return_value = {'ses_chief'}
        with patch.object(run_pi.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaisesRegex(TimeoutError, 'remains available'):
                self.wait_for_chief(timeout_seconds=1)
        self.gateway.interrupt.assert_not_called()
        self.gateway.call.assert_not_called()

    def test_public_assistant_error_is_not_hidden_by_an_idle_process(self):
        self.gateway.export_session.return_value = {'messages': [
            {'info': {'id': 'msg_error', 'role': 'assistant', 'error': {'type': 'api_error'}}, 'parts': []}]}
        with self.assertRaisesRegex(RuntimeError, 'Pi ended with an error'):
            self.wait_for_chief()


if __name__ == '__main__':
    unittest.main()
