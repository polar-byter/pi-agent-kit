"""Browser proof, work admission and read-only final reports."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from kit.browser_evidence import validate_browser_evidence
from kit.browser_review import run_browser_action
from kit.task_metrics import TaskMetrics
from kit.task_report import read_completed_task_report


class BrowserReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.metrics = TaskMetrics(self.root)
        self.metrics.start('test')
        self.folder = self.root / '.metrics/test/browser'
        self.folder.mkdir()

    def proof(self):
        image = self.folder / 'screen.png'
        image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        record = dict(project=str(self.root), task='test', engine='playwright-cli',
                      screenshot=image.relative_to(self.root).as_posix(),
                      sha256=hashlib.sha256(image.read_bytes()).hexdigest(), actions=[dict(action='open')])
        receipt = self.folder / 'screen.json'
        receipt.write_text(json.dumps(record), encoding='utf-8')
        return receipt.relative_to(self.root).as_posix(), image

    def test_http_scenarios_without_browser_evidence_cannot_complete_ux(self):
        checks = self.root / 'checks.json'
        checks.write_text(json.dumps([dict(scenario='menu', actions='GET /', result='HTTP 200')]))
        with self.assertRaisesRegex(ValueError, 'browser_evidence'):
            self.metrics.ux_review('test', checks=Path('checks.json'))
        self.assertEqual(len(self.metrics.read('test')), 1)

    def test_browser_scenario_requires_a_visual_observation(self):
        reference, _ = self.proof()
        checks = self.root / 'checks.json'
        checks.write_text(json.dumps([dict(scenario='menu', actions='click', result='menu', browser_evidence=reference)]))
        with self.assertRaisesRegex(ValueError, 'visual_observation'):
            self.metrics.ux_review('test', checks=Path('checks.json'))

    def test_modified_screenshot_is_refused(self):
        reference, image = self.proof()
        image.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'screenshot'):
            validate_browser_evidence(self.root, 'test', reference)

    def test_another_tasks_receipt_is_refused(self):
        reference, _ = self.proof()
        with self.assertRaises(ValueError):
            validate_browser_evidence(self.root, 'other', reference)

    def test_browser_does_not_start_after_finish(self):
        self.metrics.finish('test')
        with patch('kit.browser_review.ensure_browser_command') as setup:
            with self.assertRaises(ValueError):
                run_browser_action(self.root, 'test', 'open', ['http://127.0.0.1:8000'])
            setup.assert_not_called()

    def test_caller_cannot_replace_the_session_or_output_path(self):
        for argument in ('-s=other', '--filename=other.png', '--config=other.json'):
            with self.subTest(argument=argument), self.assertRaises(ValueError):
                run_browser_action(self.root, 'test', 'snapshot', [argument])

    def test_cli_json_error_with_exit_zero_cannot_create_evidence(self):
        response = SimpleNamespace(returncode=0, stdout='{"isError":true,"error":"browser missing"}', stderr='')
        with patch('kit.browser_review.ensure_browser_command', return_value=(['node', 'unused'], {})), \
             patch('kit.browser_review.subprocess.run', return_value=response):
            with self.assertRaisesRegex(ValueError, 'browser missing'):
                run_browser_action(self.root, 'test', 'snapshot')
        self.assertFalse((self.folder / 'actions.jsonl').exists())
        self.assertEqual(list(self.folder.glob('*.json')), [])

    def test_final_report_does_not_modify_the_journal_or_recollect_usage(self):
        self.metrics.finish('test', language='en')
        journal = self.root / '.metrics/test/events.jsonl'
        before = journal.read_bytes()
        with patch.object(TaskMetrics, 'collect_exports', side_effect=AssertionError('No new exports')):
            report = read_completed_task_report(self.root, 'test', 'en')
        self.assertIn('Task report', report)
        self.assertEqual(journal.read_bytes(), before)

    def test_unfinished_task_has_no_final_report(self):
        with self.assertRaisesRegex(ValueError, 'finish'):
            read_completed_task_report(self.root, 'test')
