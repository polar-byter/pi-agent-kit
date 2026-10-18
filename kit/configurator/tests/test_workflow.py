"""Desktop form validation must finish before writing choices or credentials."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from kit.configurator import app, workflow


def api_form(role='exec', **changes):
    result = dict(app.EMPTY_FORM)
    result.update({role + '_source': 'api', role + '_url': 'https://api.example.com/v1/',
                   role + '_model': 'my-model'})
    result.update(changes)
    return result


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.saved_key = patch.object(workflow, 'existing_key', return_value='')
        self.saved_key.start()
        self.addCleanup(self.saved_key.stop)

    def test_manual_model_works_without_discovery_and_json_never_has_key(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(workflow.keys, 'save_user_variable') as save:
            path, choices = workflow.save(Path(folder), api_form(), {'exec': 'secret-value-for-tests'})
            save.assert_called_once_with(app.EMPTY_FORM['exec_key_env'], 'secret-value-for-tests')
            self.assertNotIn('secret-value-for-tests', path.read_text())
            self.assertEqual(json.loads(path.read_text()), choices)
            self.assertEqual(choices['executors']['baseURL'], 'https://api.example.com/v1')
            self.assertEqual(choices['executors']['model'], 'my-model')

    def test_invalid_second_role_writes_nothing_including_first_roles_key(self):
        form = api_form('master_chief', exec_source='api')
        with tempfile.TemporaryDirectory() as folder, patch.object(workflow.keys, 'save_user_variable') as save:
            with self.assertRaises(workflow.FormError) as caught:
                workflow.save(Path(folder), form, {'master_chief': 'key-one', 'exec': 'key-two'})
            self.assertEqual(caught.exception.role, 'exec')
            self.assertFalse((Path(folder) / '.pi').exists())
            save.assert_not_called()

    def test_hidden_inactive_key_is_not_saved(self):
        form = dict(app.EMPTY_FORM)
        form['master_chief_key_env'] = 'invalid key name'
        choices, to_save = workflow.validate(form, {'master_chief': 'hidden-secret', 'exec': 'also-hidden'})
        self.assertEqual(to_save, {})
        self.assertEqual(choices, {'executors': {'source': 'lmstudio'}})

    def test_missing_key_is_an_actionable_error(self):
        with self.assertRaises(workflow.FormError) as caught:
            workflow.validate(api_form(), {})
        self.assertEqual((caught.exception.role, caught.exception.field), ('exec', 'key'))

    def test_existing_key_is_kept_without_rewriting_registry(self):
        with patch.object(workflow, 'existing_key', return_value='stored'):
            choices, to_save = workflow.validate(api_form(), {})
        self.assertEqual(to_save, {})
        self.assertEqual(choices['executors']['keyEnv'], app.EMPTY_FORM['exec_key_env'])

    def test_connection_does_not_require_model(self):
        form = api_form(exec_model='')
        self.assertEqual(workflow.connection(form, 'exec', 'key'), ('https://api.example.com/v1', 'key'))
        with self.assertRaises(workflow.FormError) as caught:
            workflow.validate(form, {'exec': 'key'})
        self.assertEqual(caught.exception.field, 'model')

    def test_conflicting_environment_names_are_rejected_before_any_write(self):
        form = api_form('master_chief', exec_source='api', exec_url='https://b.example/v1',
                        exec_model='other', exec_key_env=app.EMPTY_FORM['master_chief_key_env'])
        with patch.object(workflow.keys, 'save_user_variable') as save:
            with self.assertRaises(workflow.FormError) as caught:
                workflow.save(Path('unused'), form, {'master_chief': 'first', 'exec': 'second'})
        self.assertEqual(caught.exception.field, 'key_env')
        save.assert_not_called()

    def test_same_environment_and_same_key_can_be_shared(self):
        form = api_form('master_chief', exec_source='api', exec_url='https://b.example/v1',
                        exec_model='other', exec_key_env=app.EMPTY_FORM['master_chief_key_env'])
        choices, to_save = workflow.validate(form, {'master_chief': 'same', 'exec': 'same'})
        self.assertEqual(len(to_save), 1)
        self.assertEqual(choices['masterChief']['source'], 'api')

    def test_one_typed_openrouter_key_supplies_both_roles_using_shared_variable(self):
        form = api_form('master_chief', master_chief_key_env='OPENROUTER_API_KEY', exec_source='api',
                        exec_url='https://openrouter.ai/api/v1', exec_model='a/coder', exec_key_env='OPENROUTER_API_KEY')
        choices, to_save = workflow.validate(form, {'exec': 'one-common-key'})
        self.assertEqual(to_save, {'OPENROUTER_API_KEY': 'one-common-key'})
        self.assertEqual(choices['masterChief']['keyEnv'], choices['executors']['keyEnv'])

    def test_multiline_key_and_invalid_env_are_rejected(self):
        for form, key, field in ((api_form(), 'a\nb', 'key'),
                                 (api_form(exec_key_env='bad name'), 'key', 'key_env')):
            with self.subTest(field=field), self.assertRaises(workflow.FormError) as caught:
                workflow.validate(form, {'exec': key})
            self.assertEqual(caught.exception.field, field)

    def test_bad_addresses_are_rejected(self):
        for url in ('', 'api.example.com/v1', 'file:///c:/key', 'https://', 'https://x:999999/v1',
                    'https://user:key@api.example/v1', 'https://x/v1?key=secret', 'https://x/v1#key',
                    'https://x/v1?', 'https://x/v1#', 'https://x/a b', 'https://x/v1/models',
                    'https://x/v1/chat/completions', 'https://x/v1/responses'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                workflow.api_address(url)

    def test_local_and_custom_base_paths_are_allowed_without_guessing(self):
        for url in ('http://localhost:1234/v1', 'http://[::1]:8000/api', 'https://api.example/custom'):
            self.assertEqual(workflow.api_address(' ' + url + '/ '), url)
        self.assertEqual(workflow.api_address('HTTPS://api.example/v1'), 'https://api.example/v1')

    def test_opencode_names_keep_existing_contract(self):
        form = dict(app.EMPTY_FORM, exec_source='pi', exec_model='no-provider')
        with self.assertRaises(workflow.FormError) as caught:
            workflow.validate(form, {})
        self.assertEqual(caught.exception.field, 'model')
        form['exec_model'] = 'openrouter/provider/model:free'
        self.assertEqual(workflow.validate(form, {})[0]['executors']['model'], form['exec_model'])


class KeyAndErrorsTests(unittest.TestCase):
    def test_registry_value_is_used_over_stale_environment(self):
        with patch.dict(os.environ, {'UX_TEST_KEY': 'stale'}), patch.object(workflow.keys, 'winreg', object()), \
             patch.object(workflow.keys, 'read_user_variable', return_value='fresh'):
            self.assertEqual(workflow.existing_key('UX_TEST_KEY'), 'fresh')

    def test_process_environment_works_when_registry_is_unavailable(self):
        with patch.dict(os.environ, {'UX_TEST_KEY': 'process'}), patch.object(workflow.keys, 'winreg', None):
            self.assertEqual(workflow.existing_key('UX_TEST_KEY'), 'process')

    def test_errors_are_helpful_without_echoing_server_text_or_key(self):
        for code, expected in ((401, 'API key'), (403, 'API key'), (404, 'manually'), (429, '429'), (503, 'error')):
            wrapper = ValueError('secret-string in source error')
            wrapper.__cause__ = HTTPError('https://secret-string', code, 'secret-string', {}, None)
            text = workflow.model_error('api', wrapper)
            self.assertIn(expected, text)
            self.assertNotIn('secret-string', text)
        self.assertIn('timed out', workflow.model_error('api', TimeoutError('secret-string')))
        self.assertIn('connect', workflow.model_error('api', URLError('secret-string')))
        self.assertIn('manually', workflow.model_error('api', ValueError('secret-string')))

    def test_preparation_inherits_persisted_key_and_uses_existing_launcher(self):
        choices = {'executors': {'source': 'api', 'keyEnv': 'UX_TEST_PREPARE'}}
        with patch.dict(os.environ, {}, clear=False), patch.object(workflow, 'existing_key', return_value='persisted'), \
             patch.object(app, 'apply_choices', return_value=(0, 'ready')) as apply:
            self.assertEqual(workflow.prepare(Path('project'), choices), (0, 'ready'))
            self.assertEqual(os.environ['UX_TEST_PREPARE'], 'persisted')
            apply.assert_called_once_with(Path('project'))
