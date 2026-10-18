"""Step 7: the logic of the window that works without the window (app.py module functions).
The window itself (step 8) is checked by hand: open it and click."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from kit.configurator import app


def form(**changes):
    result = dict(app.EMPTY_FORM)
    result.update(changes)
    return result


class Step7FormToChoices(unittest.TestCase):
    def test_defaults_give_lmstudio_only(self):
        self.assertEqual(app.form_to_choices(form()), {'executors': {'source': 'lmstudio'}})

    def test_master_chief_from_pi(self):
        result = app.form_to_choices(form(master_chief_source=app.MASTER_CHIEF_PI, master_chief_model='openai/gpt-6.1-sol'))
        self.assertEqual(result['masterChief'], {'source': 'pi', 'model': 'openai/gpt-6.1-sol'})

    def test_master_chief_api(self):
        result = app.form_to_choices(form(master_chief_source=app.MASTER_CHIEF_API, master_chief_model='big',
                                          master_chief_url='https://api.example.com/v1', master_chief_key_env='MY_KEY'))
        self.assertEqual(result['masterChief'], {'source': 'api', 'baseURL': 'https://api.example.com/v1',
                                           'model': 'big', 'keyEnv': 'MY_KEY'})

    def test_executors_with_instance(self):
        result = app.form_to_choices(form(exec_instance='qwen-1'))
        self.assertEqual(result['executors'], {'source': 'lmstudio', 'instance': 'qwen-1'})

    def test_executors_api(self):
        result = app.form_to_choices(form(exec_source=app.EXEC_API, exec_model='small',
                                          exec_url='http://localhost:8000/v1', exec_key_env='EXEC_KEY'))
        self.assertEqual(result['executors']['source'], 'api')
        self.assertEqual(result['executors']['model'], 'small')

    def test_errors_from_choices_reach_the_caller(self):
        with self.assertRaises(ValueError):
            app.form_to_choices(form(master_chief_source=app.MASTER_CHIEF_PI, master_chief_model='no-provider'))

    def test_unknown_source_is_an_error(self):
        for changes in ({'master_chief_source': 'magic'}, {'exec_source': 'cloud'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                app.form_to_choices(form(**changes))


class ExecutorsFromOpencode(unittest.TestCase):
    def test_form_to_choices(self):
        result = app.form_to_choices(form(exec_source=app.EXEC_PI, exec_model='openrouter/qwen/qwen3-coder:free'))
        self.assertEqual(result['executors'], {'source': 'pi', 'model': 'openrouter/qwen/qwen3-coder:free'})

    def test_model_without_provider_is_an_error(self):
        with self.assertRaises(ValueError):
            app.form_to_choices(form(exec_source=app.EXEC_PI, exec_model='qwen3-coder'))

    def test_round_trip(self):
        original = form(exec_source=app.EXEC_PI, exec_model='openrouter/qwen/qwen3-coder:free')
        self.assertEqual(app.choices_to_form(app.form_to_choices(original)), original)


class Step7ChoicesToForm(unittest.TestCase):
    def test_empty_file_gives_empty_form(self):
        self.assertEqual(app.choices_to_form({}), app.EMPTY_FORM)

    def test_empty_form_is_not_modified(self):
        before = dict(app.EMPTY_FORM)
        app.choices_to_form({'masterChief': {'source': 'pi', 'model': 'a/b'}})
        self.assertEqual(app.EMPTY_FORM, before)

    def test_round_trip(self):
        cases = [
            form(master_chief_source=app.MASTER_CHIEF_PI, master_chief_model='openai/gpt-6.1-sol'),
            form(master_chief_source=app.MASTER_CHIEF_API, master_chief_model='big', master_chief_url='https://x/v1', master_chief_key_env='K1',
                 exec_source=app.EXEC_API, exec_model='small', exec_url='https://y/v1', exec_key_env='K2'),
            form(exec_instance='qwen-1'),
        ]
        for original in cases:
            with self.subTest(form=original):
                self.assertEqual(app.choices_to_form(app.form_to_choices(original)), original)


class Step7Apply(unittest.TestCase):
    def test_runs_launcher_prepare_only_in_project_root(self):
        done = subprocess.CompletedProcess([], 0, stdout='Master Chief: model from opencode.jsonc\n', stderr='')
        with patch.object(app.subprocess, 'run', return_value=done) as run:
            code, text = app.apply_choices(Path('D:/project'))
        self.assertEqual(code, 0)
        self.assertIn('Master Chief', text)
        command = run.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1:], ['-m', 'kit.run_pi', '--prepare-only'])
        self.assertEqual(run.call_args.kwargs.get('cwd'), Path('D:/project'))
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_error_text_is_returned(self):
        done = subprocess.CompletedProcess([], 1, stdout='', stderr='ERROR: No language model is loaded')
        with patch.object(app.subprocess, 'run', return_value=done):
            self.assertEqual(app.apply_choices(Path('.')), (1, 'ERROR: No language model is loaded'))


if __name__ == '__main__':
    unittest.main()
