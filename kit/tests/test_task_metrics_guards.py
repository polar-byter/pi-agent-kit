"""Tests for run categories, loop guards, the check command and multi-file JUnit reports."""
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import task_metrics
from task_metrics import (TaskHalted, TaskMetrics, fresh_xml_files, limit_breach, parse_junit_files,
                          resolve_command, run_category)

PASSING_XML = '<testsuite><testcase name="a"/><testcase name="b"/></testsuite>'
FAILING_XML = '<testsuite><testcase name="c"><failure message="boom"/></testcase></testsuite>'


def write_xml_script(target: str, body: str) -> list[str]:
    """A command that writes one JUnit XML file, like a real test tool would."""
    code = f'import pathlib; p = pathlib.Path({target!r}); p.parent.mkdir(parents=True, exist_ok=True); ' \
           f'p.write_text({body!r})'
    return [sys.executable, '-c', code]


class GuardCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.metrics = TaskMetrics(self.root)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            # main lives in the class now; after the refactoring it may become a module function.
            entry = getattr(task_metrics, 'main', None) or TaskMetrics.main
            code = entry(['--root', str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    # --- Windows programs started through .cmd / .bat ---

    def test_resolve_command_uses_full_path_on_windows(self):
        with patch('shutil.which', return_value=r'C:\maven\bin\mvn.cmd'):
            self.assertEqual(resolve_command(['mvn', 'test'], windows=True), [r'C:\maven\bin\mvn.cmd', 'test'])

    def test_resolve_command_keeps_command_elsewhere_or_when_not_found(self):
        self.assertEqual(resolve_command(['mvn', 'test'], windows=False), ['mvn', 'test'])
        with patch('shutil.which', return_value=None):
            self.assertEqual(resolve_command(['mvn', 'test'], windows=True), ['mvn', 'test'])

    # --- JUnit reports ---

    def test_several_junit_files_are_summed(self):
        (self.root / 'a.xml').write_text(PASSING_XML)
        (self.root / 'b.xml').write_text(FAILING_XML)
        result = parse_junit_files([self.root / 'a.xml', self.root / 'b.xml'])
        self.assertEqual((result['tests'], result['failures']), (3, 1))

    def test_one_broken_junit_file_makes_result_unknown(self):
        (self.root / 'a.xml').write_text(PASSING_XML)
        (self.root / 'b.xml').write_text('<broken')
        self.assertIn('diagnostic', parse_junit_files([self.root / 'a.xml', self.root / 'b.xml']))

    def test_no_junit_files_is_a_diagnostic(self):
        self.assertIn('No JUnit XML', parse_junit_files([])['diagnostic'])

    def test_fresh_xml_files_ignores_reports_from_earlier_runs(self):
        folder = self.root / 'reports'
        folder.mkdir()
        old, new = folder / 'TEST-old.xml', folder / 'TEST-new.xml'
        old.write_text(PASSING_XML)
        new.write_text(PASSING_XML)
        os.utime(old, (time.time() - 600, time.time() - 600))
        self.assertEqual(fresh_xml_files(folder, time.time() - 60), [new])

    def test_junit_dir_reads_only_files_of_this_run(self):
        folder = self.root / 'target' / 'surefire-reports'
        folder.mkdir(parents=True)
        stale = folder / 'TEST-Stale.xml'
        stale.write_text(FAILING_XML)
        os.utime(stale, (time.time() - 600, time.time() - 600))
        self.metrics.start('task')
        event = self.metrics.test('task', write_xml_script('target/surefire-reports/TEST-New.xml', PASSING_XML),
                                  junit_dir='target/surefire-reports')
        self.assertEqual((event['status'], event['tests'], event['category']), ('passed', 2, 'passed'))

    def test_junit_and_junit_dir_together_are_rejected(self):
        self.metrics.start('task')
        with self.assertRaises(ValueError):
            self.metrics.test('task', [sys.executable, '-c', 'pass'], junit='a.xml', junit_dir='r')

    def test_missing_report_after_run_is_no_result_with_hint(self):
        self.metrics.start('task')
        event = self.metrics.test('task', [sys.executable, '-c', 'pass'], junit='.metrics/task/run-01.xml')
        self.assertEqual(event['category'], 'no_result')
        self.assertTrue(any('did not write a JUnit XML' in h for h in event['hints']))

    # --- categories ---

    def test_run_categories(self):
        cases = [
            (dict(status='passed', tests=3, failures=0, errors=0, skipped=0), 0, 'passed'),
            (dict(status='failed', tests=3, failures=1, errors=0, skipped=0), 1, 'tests_failed'),
            (dict(status='skipped', tests=3, failures=0, errors=0, skipped=1), 0, 'incomplete'),
            (dict(status='failed', tests=None, failures=None, errors=None, skipped=None), 1, 'no_result'),
            (dict(status='unknown', tests=None, failures=None, errors=None, skipped=None), 0, 'no_result'),
            (dict(status='empty', tests=0, failures=0, errors=0, skipped=0), 0, 'no_result'),
            (dict(status='failed', tests=3, failures=0, errors=0, skipped=0), 1, 'no_result'),
            (dict(status='timeout', tests=None, failures=None, errors=None, skipped=None), 124, 'timeout'),
        ]
        for parsed, code, expected in cases:
            with self.subTest(expected=expected, parsed=parsed):
                self.assertEqual(run_category(parsed, code), expected)

    # --- loop guards ---

    def test_third_rework_of_one_work_item_stops_the_task(self):
        self.metrics.start('task')
        self.metrics.review('task', 'Calc', 'rework')
        self.metrics.review('task', 'Other', 'rework')
        self.assertNotIn('halt', self.metrics.review('task', 'Calc', 'rework'))
        event = self.metrics.review('task', 'Calc', 'rework')
        self.assertIn('Calc was sent back 3 times', event['halt'])
        with self.assertRaises(TaskHalted):
            self.metrics.review('task', 'Calc', 'rework')
        with self.assertRaises(TaskHalted):
            self.metrics.test('task', [sys.executable, '-c', 'pass'])

    def test_resume_gives_every_guard_a_fresh_budget(self):
        self.metrics.start('task', limits={'max_reworks': 1})
        self.assertIn('halt', self.metrics.review('task', 'Calc', 'rework'))
        self.metrics.resume('task', 'User fixed the spec')
        self.assertIn('halt', self.metrics.review('task', 'Calc', 'rework'))

    def test_resume_requires_a_stop_and_a_reason(self):
        self.metrics.start('task')
        with self.assertRaises(ValueError):
            self.metrics.resume('task', 'nothing happened')
        self.metrics.start('other', limits={'max_reworks': 1})
        self.metrics.review('other', 'Calc', 'rework')
        with self.assertRaises(ValueError):
            self.metrics.resume('other', '   ')

    def test_runs_without_result_stop_the_task(self):
        self.metrics.start('task')
        broken = [sys.executable, '-c', 'import sys; print("build failed"); sys.exit(1)']
        first = self.metrics.test('task', broken)
        second = self.metrics.test('task', broken)
        self.assertEqual((first['category'], 'halt' in first, 'halt' in second), ('no_result', False, False))
        third = self.metrics.test('task', broken)
        self.assertIn('no readable result', third['halt'])
        self.assertTrue(any('does not compile' in h for h in third['hints']))

    def test_one_readable_run_resets_the_no_result_streak(self):
        self.metrics.start('task')
        broken = [sys.executable, '-c', 'import sys; sys.exit(1)']
        (self.root / 'test_ok.py').write_text(
            'import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n')
        ok = [sys.executable, '-m', 'unittest', 'test_ok']
        for command in (broken, broken, ok, broken, broken):
            self.assertNotIn('halt', self.metrics.test('task', command))

    def test_long_red_streak_stops_the_task(self):
        self.metrics.start('task', limits={'max_failed_runs': 2})
        (self.root / 'test_bad.py').write_text(
            'import unittest\nclass T(unittest.TestCase):\n def test_bad(self): self.fail()\n')
        failing = [sys.executable, '-m', 'unittest', 'test_bad']
        self.assertNotIn('halt', self.metrics.test('task', failing))
        self.assertIn('were not green', self.metrics.test('task', failing)['halt'])

    def test_total_run_limit(self):
        self.metrics.start('task', limits={'max_runs': 2})
        (self.root / 'test_ok.py').write_text(
            'import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n')
        ok = [sys.executable, '-m', 'unittest', 'test_ok']
        self.metrics.test('task', ok)
        self.assertIn('2 test runs in this task', self.metrics.test('task', ok)['halt'])

    def test_limits_must_be_positive_integers(self):
        for bad in ({'max_reworks': 0}, {'max_runs': -1}, {'max_reworks': 1.5}, {'unknown': 3}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.metrics.start('t' + str(abs(hash(str(bad)))), limits=bad)

    def test_journal_without_limits_uses_defaults(self):
        events = [{'kind': 'start', 'at': 1}] + [
            {'kind': 'review', 'work_item': 'X', 'result': 'rework', 'at': 2}] * 3
        self.assertIn('sent back 3 times', limit_breach(events, task_metrics.task_limits(events)))

    def test_report_shows_stops_and_runs_without_result(self):
        self.metrics.start('task', limits={'max_no_result': 1})
        self.metrics.test('task', [sys.executable, '-c', 'import sys; sys.exit(1)'])
        self.metrics.resume('task', 'Пользователь починил сборку')
        report = self.metrics.finish('task', language='ru')
        self.assertIn('Прогоны без результата', report)
        self.assertIn('Остановки по защитным лимитам: **1**', report)
        self.assertIn('Пользователь починил сборку', report)

    # --- command line ---

    def test_exit_codes(self):
        (self.root / 'test_ok.py').write_text(
            'import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n')
        (self.root / 'test_bad.py').write_text(
            'import unittest\nclass T(unittest.TestCase):\n def test_bad(self): self.fail()\n')
        self.assertEqual(self.run_main('start', '--task', 't', '--max-no-result', '2')[0], 0)
        self.assertEqual(self.run_main('test', '--task', 't', '--', sys.executable, '-m', 'unittest', 'test_ok')[0], 0)
        self.assertEqual(self.run_main('test', '--task', 't', '--', sys.executable, '-m', 'unittest', 'test_bad')[0], 1)
        code, _, err = self.run_main('test', '--task', 't', '--', sys.executable, '-c', 'import sys; sys.exit(1)')
        self.assertEqual(code, 4)
        self.assertIn('NO RESULT', err)
        code, _, err = self.run_main('test', '--task', 't', '--', sys.executable, '-c', 'import sys; sys.exit(1)')
        self.assertEqual(code, 3)
        self.assertIn('STOP:', err)
        code, _, err = self.run_main('test', '--task', 't', '--', sys.executable, '-m', 'unittest', 'test_ok')
        self.assertEqual(code, 3)
        self.assertEqual(self.run_main('resume', '--task', 't', '--reason', 'fixed')[0], 0)
        self.assertEqual(self.run_main('test', '--task', 't', '--', sys.executable, '-m', 'unittest', 'test_ok')[0], 0)

    def test_check_reports_readable_and_unreadable_results(self):
        code, _, err = self.run_main('check', '--junit', 'check.xml', '--',
                                     *write_xml_script('check.xml', PASSING_XML))
        self.assertEqual(code, 0)
        self.assertIn('CHECK OK', err)
        self.assertFalse((self.root / 'check.xml').exists())
        code, _, err = self.run_main('check', '--', sys.executable, '-c', 'print("Passed! - Failed: 0")')
        self.assertEqual(code, 4)
        self.assertIn('not recognized', err)

    def test_check_with_failing_tests_is_still_a_working_setup(self):
        code, out, _ = self.run_main('check', '--junit', 'check.xml', '--',
                                     *write_xml_script('check.xml', FAILING_XML))
        self.assertEqual(code, 0)
        self.assertIn('"category": "tests_failed"', out)

    def test_check_hints_for_missing_dotnet_logger(self):
        command = [sys.executable, '-c',
                   'import sys; print("Could not find a test logger with FriendlyName junit"); sys.exit(1)']
        result = self.metrics.check(command, junit='x.xml')
        self.assertFalse(result['readable'])
        self.assertTrue(any('JunitXml.TestLogger' in h for h in result['hints']))


if __name__ == '__main__':
    unittest.main()
