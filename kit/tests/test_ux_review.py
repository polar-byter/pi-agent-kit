"""The Master Chief's final UI/UX improvement stage: ux-review before finish."""
import io
import hashlib
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task_metrics import TaskMetrics, main  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kit.dashboard import delivery  # noqa: E402

SCENARIOS = [
    {'scenario': 'Новая покупка', 'actions': 'открыть форму, две строки, сохранить',
     'result': 'покупка сохранена, итог 528,00 ₽'},
    {'scenario': 'Ошибка ввода', 'actions': 'пустое количество, сохранить',
     'result': 'сообщение у поля', 'fixed': 'количество 1 по умолчанию'},
]


class UxReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.metrics = TaskMetrics(self.root)

    def write(self, name, data):
        if name == 'ux.json':
            folder = self.root / '.metrics/t/browser'
            folder.mkdir(parents=True, exist_ok=True)
            screenshot = folder / 'test.png'
            screenshot.write_bytes(b'\x89PNG\r\n\x1a\nunit-test-fixture')
            receipt = folder / 'test.json'
            receipt.write_text(json.dumps(dict(project=str(self.root.resolve()), task='t',
                engine='playwright-cli', screenshot=screenshot.relative_to(self.root).as_posix(),
                sha256=hashlib.sha256(screenshot.read_bytes()).hexdigest(), actions=[dict(action='open')])))
            data = [dict(row, browser_evidence=receipt.relative_to(self.root).as_posix(),
                         visual_observation='The screenshot shows the form and validation message beside its field.') for row in data]
        path = self.root / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return Path(name)

    def cli(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = main(['--root', str(self.root), *args])
        return code, err.getvalue()

    def test_implementation_task_needs_the_stage_before_finish(self):
        self.metrics.start('t', track_delegations=True)
        self.assertTrue(self.metrics.read('t')[0]['ux_review_required'])
        with self.assertRaisesRegex(ValueError, 'ux-review'):
            self.metrics.finish('t', language='ru')
        self.assertNotIn('finish', [e['kind'] for e in self.metrics.read('t')])

    def test_completed_stage_is_reported_with_scenarios_and_fixes(self):
        self.metrics.start('t', track_delegations=True)
        event = self.metrics.ux_review('t', checks=self.write('ux.json', SCENARIOS))
        self.assertEqual((event['outcome'], event['scenarios'], event['fixed']), ('completed', 2, 1))
        self.assertEqual(event['checks'][1]['fixed'], 'количество 1 по умолчанию')
        report = self.metrics.finish('t', language='ru')
        self.assertIn('Этап улучшения UI/UX выполнен: проверено сценариев — 2, исправлено замечаний — 1.', report)
        self.assertIn('- Новая покупка — покупка сохранена, итог 528,00 ₽', report)
        self.assertIn('(исправлено: количество 1 по умолчанию)', report)
        english = self.metrics.finish('t', language='en')
        self.assertIn('UI/UX improvement stage completed: 2 scenarios checked, 1 issues fixed.', english)

    def test_skipped_stage_uses_the_neutral_wording(self):
        self.metrics.start('t', track_delegations=True)
        self.metrics.ux_review('t', skipped='отсутствия браузера для проверки')
        report = self.metrics.finish('t', language='ru')
        self.assertIn('Этап улучшения UI/UX пропущен ввиду отсутствия браузера для проверки.', report)
        self.assertNotIn('не проверен', report)

    def test_not_applicable_stage(self):
        self.metrics.start('t', track_delegations=True)
        self.metrics.ux_review('t', not_applicable='консольная утилита без интерфейса')
        report = self.metrics.finish('t', language='ru')
        self.assertIn('Этап улучшения UI/UX не требуется: консольная утилита без интерфейса.', report)

    def test_latest_record_wins(self):
        self.metrics.start('t', track_delegations=True)
        self.metrics.ux_review('t', skipped='no browser')
        self.metrics.ux_review('t', checks=self.write('ux.json', SCENARIOS[:1]))
        report = self.metrics.finish('t', language='en')
        self.assertIn('UI/UX improvement stage completed: 1 scenarios checked, 0 issues fixed.', report)
        self.assertNotIn('skipped', report)

    def test_invalid_records_are_refused_and_not_written(self):
        self.metrics.start('t', track_delegations=True)
        cases = [
            dict(),
            dict(skipped='a', not_applicable='b'),
            dict(skipped='   '),
            dict(not_applicable='x' * 301),
            dict(checks=self.write('empty.json', [])),
            dict(checks=self.write('object.json', {'scenario': 'x'})),
            dict(checks=self.write('missing.json', [{'scenario': 'x', 'actions': 'y'}])),
            dict(checks=self.write('blank.json', [{'scenario': 'x', 'actions': 'y', 'result': ' '}])),
            dict(checks=self.write('fixed.json', [{'scenario': 'x', 'actions': 'y', 'result': 'z', 'fixed': 1}])),
            dict(checks=Path('no-such-file.json')),
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.metrics.ux_review('t', **kwargs)
        self.assertEqual([e['kind'] for e in self.metrics.read('t')], ['start'])

    def test_executor_attempts_must_be_reviewed_first(self):
        self.metrics.start('t', track_delegations=True)
        (self.root / 'app.py').write_text('value = 1\n', encoding='utf-8')
        requirements = self.write('req.json', ['value is one'])
        self.metrics.delegate('t', 'App', ['app.py'], requirements_file=requirements)
        with self.assertRaisesRegex(ValueError, 'review'):
            self.metrics.ux_review('t', skipped='no browser')

    def test_planning_task_and_old_journals_finish_without_the_stage(self):
        self.metrics.start('plan')
        self.assertFalse(self.metrics.read('plan')[0]['ux_review_required'])
        self.assertIn('Task report', self.metrics.finish('plan', language='en'))
        self.metrics.start('legacy', track_delegations=True)
        journal = self.root / '.metrics' / 'legacy' / 'events.jsonl'
        first = json.loads(journal.read_text(encoding='utf-8'))
        first.pop('ux_review_required')
        journal.write_text(json.dumps(first) + '\n', encoding='utf-8')
        self.assertIn('Task report', self.metrics.finish('legacy', language='en'))

    def test_cli_exit_codes(self):
        self.assertEqual(self.cli('start', '--task', 'c', '--track-delegations', '--no-dashboard')[0], 0)
        code, err = self.cli('finish', '--task', 'c')
        self.assertEqual(code, 2)
        self.assertIn('ux-review', err)
        self.assertEqual(self.cli('ux-review', '--task', 'c', '--skipped', 'no browser available')[0], 0)
        self.assertEqual(self.cli('finish', '--task', 'c', '--language', 'en')[0], 0)
        with self.assertRaises(SystemExit):  # argparse: one outcome is required
            self.cli('ux-review', '--task', 'c')

    def test_dashboard_completion_shows_the_stage(self):
        self.metrics.start('t', track_delegations=True)
        self.metrics.ux_review('t', checks=self.write('ux.json', SCENARIOS))
        self.metrics.finish('t', language='en')
        data = delivery.completion(self.root, 't', self.metrics.read('t'))
        self.assertEqual(data['ux'], {'outcome': 'completed', 'scenarios': 2, 'fixed': 1})


if __name__ == '__main__':
    unittest.main()
