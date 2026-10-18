"""Pi preparation keeps roles independent and secrets outside project JSON."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kit import pi_configuration
from kit.lmstudio_models import LoadedModel


class PiConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        prompts = self.root / 'kit/prompts'
        prompts.mkdir(parents=True)
        for name in ('master-chief.md', 'executor.md', 'executor-fast.md', 'bug-fixer.md'):
            (prompts / name).write_text('Prompt for ' + name, encoding='utf-8')

    def save_choices(self, choices):
        path = self.root / pi_configuration.CHOICES_PATH
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(choices), encoding='utf-8')

    def test_unconfigured_chief_requires_an_explicit_choice(self):
        with self.assertRaisesRegex(ValueError, 'Choose the Master Chief'):
            pi_configuration.write_prepared_pi_configuration(self.root)
        self.assertFalse((self.root / pi_configuration.RUNTIME_PATH).exists())

    def test_opencode_connection_is_not_silently_reused(self):
        self.save_choices({'masterChief': {'source': 'opencode', 'model': 'openrouter/author/model'}})
        with self.assertRaisesRegex(ValueError, 'explicitly'):
            pi_configuration.load_choices(self.root)

    def test_independent_apis_preserve_nested_model_ids_and_environment_references(self):
        choices = {'masterChief': {'source': 'api', 'baseURL': 'https://chief.example/v1', 'model': 'author/chief', 'keyEnv': 'PI_CHIEF_TEST'},
                   'executors': {'source': 'api', 'baseURL': 'https://worker.example/v1', 'model': 'author/worker', 'keyEnv': 'PI_WORKER_TEST'},
                   'bugFixer': {'source': 'api', 'baseURL': 'https://fixer.example/v1', 'model': 'author/fixer', 'keyEnv': 'PI_FIXER_TEST'}}
        self.save_choices(choices)
        with patch.dict(os.environ, {'PI_CHIEF_TEST': 'chief-secret', 'PI_WORKER_TEST': 'worker-secret', 'PI_FIXER_TEST': 'fixer-secret'}):
            self.assertIsNone(pi_configuration.write_prepared_pi_configuration(self.root))
        runtime_text = (self.root / pi_configuration.RUNTIME_PATH).read_text()
        models_text = (self.root / pi_configuration.AGENT_DIRECTORY / 'models.json').read_text()
        runtime, models = json.loads(runtime_text), json.loads(models_text)
        self.assertEqual(runtime['roles']['build']['model'], 'author/chief')
        self.assertEqual(runtime['roles']['executor']['model'], 'author/worker')
        self.assertEqual(runtime['roles']['executor-fast']['model'], 'author/worker')
        self.assertEqual(runtime['roles']['bug-fixer']['model'], 'author/fixer')
        self.assertEqual(models['providers']['kit-executor-api']['apiKey'], '$PI_WORKER_TEST')
        self.assertNotIn('secret', models_text + runtime_text)
        self.assertNotIn('cost', models_text)

    def test_loaded_instance_is_used_without_loading_or_unloading(self):
        self.save_choices({'masterChief': {'source': 'pi', 'model': 'openrouter/author/chief'}, 'executors': {'source': 'lmstudio', 'instance': 'loaded-42'}})
        instance = LoadedModel('loaded-42', 'author/model', 'My loaded model')
        with patch.object(pi_configuration, 'loaded_models', return_value=[instance]) as discover:
            self.assertEqual(pi_configuration.write_prepared_pi_configuration(self.root), instance)
        runtime = json.loads((self.root / pi_configuration.RUNTIME_PATH).read_text())
        self.assertEqual(runtime['roles']['executor']['model'], 'loaded-42')
        self.assertFalse(runtime['roles']['bug-fixer']['enabled'])
        references = pi_configuration.resolve_role_model_references(self.root)
        self.assertEqual(references['executors'], 'lmstudio/loaded-42')
        self.assertNotIn('bugFixer', references)
        discover.assert_called_once_with('http://127.0.0.1:1234/v1')

    def test_missing_api_key_does_not_replace_prepared_files(self):
        runtime_path = self.root / pi_configuration.RUNTIME_PATH
        runtime_path.parent.mkdir()
        runtime_path.write_text('{"old": true}')
        self.save_choices({'masterChief': {'source': 'api', 'baseURL': 'https://example.test/v1', 'model': 'm', 'keyEnv': 'PI_MISSING_TEST'}})
        with patch('kit.configurator.workflow.existing_key', return_value=''):
            with self.assertRaisesRegex(ValueError, 'Save the API key'):
                pi_configuration.write_prepared_pi_configuration(self.root)
        self.assertEqual(runtime_path.read_text(), '{"old": true}')

    def test_references_split_provider_only_once(self):
        self.save_choices({'masterChief': {'source': 'pi', 'model': 'openrouter/author/chief'}, 'executors': {'source': 'pi', 'model': 'provider/family/worker'}})
        references = pi_configuration.resolve_role_model_references(self.root)
        self.assertEqual(references['masterChief'], 'openrouter/author/chief')
        self.assertEqual(references['executors'], 'provider/family/worker')

    def test_changing_saved_model_requires_preparation_before_dispatch(self):
        choices = {'masterChief': {'source': 'pi', 'model': 'provider/chief'},
                   'executors': {'source': 'pi', 'model': 'provider/worker'}}
        self.save_choices(choices)
        pi_configuration.write_prepared_pi_configuration(self.root)
        choices['executors']['model'] = 'provider/new-worker'
        self.save_choices(choices)
        with self.assertRaisesRegex(ValueError, 'Prepare Pi settings'):
            pi_configuration.resolve_role_model_references(self.root)

    def test_unprepared_local_choice_cannot_dispatch_a_placeholder_alias(self):
        self.save_choices({'masterChief': {'source': 'pi', 'model': 'provider/chief'}})
        with self.assertRaisesRegex(ValueError, 'already loaded'):
            pi_configuration.resolve_role_model_references(self.root)


if __name__ == '__main__':
    unittest.main()
