"""Steps 1-2: models_choices_configurator.py. 
Run from the project root:
    py -m unittest discover -s kit/configurator/tests -t . -v
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kit import pi_configuration
from kit.configurator import models_choices_configurator


class Step1MasterChiefFromOpencode(unittest.TestCase):
    def test_returns_source_and_model(self):
        self.assertEqual(models_choices_configurator.master_chief_from_pi('openai/gpt-6.1-sol'),
                         {'source': 'pi', 'model': 'openai/gpt-6.1-sol'})

    def test_strips_spaces(self):
        self.assertEqual(models_choices_configurator.master_chief_from_pi('  opencode-go/deepseek-v4.1-flash \n')['model'],
                         'opencode-go/deepseek-v4.1-flash')

    def test_model_without_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            models_choices_configurator.master_chief_from_pi('deepseek')

    def test_empty_model_is_rejected(self):
        for value in ('', '   '):
            with self.subTest(value=value), self.assertRaises(ValueError):
                models_choices_configurator.master_chief_from_pi(value)


class ExecutorsFromOpencode(unittest.TestCase):
    def test_same_rules_as_master_chief(self):
        self.assertEqual(models_choices_configurator.executors_from_pi(' openrouter/qwen/qwen3-coder:free '),
                         {'source': 'pi', 'model': 'openrouter/qwen/qwen3-coder:free'})
        with self.assertRaises(ValueError):
            models_choices_configurator.executors_from_pi('qwen3-coder')

    def test_launcher_understands_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            choice = models_choices_configurator.build_choices(
                None, models_choices_configurator.executors_from_pi('a/b'))
            models_choices_configurator.save_choices(root, choice)
            self.assertEqual(pi_configuration.load_choices(root)['executors'], {'source': 'pi', 'model': 'a/b'})


class Step1ApiChoice(unittest.TestCase):
    def test_returns_all_fields(self):
        self.assertEqual(models_choices_configurator.api_choice('https://api.example.com/v1', 'm', 'MY_KEY'),
                         {'source': 'api', 'baseURL': 'https://api.example.com/v1', 'model': 'm', 'keyEnv': 'MY_KEY'})

    def test_cleans_values(self):
        result = models_choices_configurator.api_choice(' http://localhost:8000/v1/ ', ' m ', ' MY_KEY ')
        self.assertEqual(result['baseURL'], 'http://localhost:8000/v1')
        self.assertEqual(result['model'], 'm')
        self.assertEqual(result['keyEnv'], 'MY_KEY')

    def test_url_must_be_http(self):
        for url in ('api.example.com/v1', 'ftp://example.com', ''):
            with self.subTest(url=url), self.assertRaises(ValueError):
                models_choices_configurator.api_choice(url, 'm', 'MY_KEY')

    def test_model_is_required(self):
        with self.assertRaises(ValueError):
            models_choices_configurator.api_choice('https://x/v1', ' ', 'MY_KEY')

    def test_key_itself_is_not_a_variable_name(self):
        for name in ('sk-abc123', '1KEY', 'MY KEY', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                models_choices_configurator.api_choice('https://x/v1', 'm', name)


class Step1LmStudioChoice(unittest.TestCase):
    def test_without_instance(self):
        self.assertEqual(models_choices_configurator.lmstudio_choice(), {'source': 'lmstudio'})

    def test_blank_instance_is_none(self):
        for value in (None, '', '   '):
            with self.subTest(value=value):
                self.assertEqual(models_choices_configurator.lmstudio_choice(value), {'source': 'lmstudio'})

    def test_with_instance(self):
        self.assertEqual(models_choices_configurator.lmstudio_choice(' qwen-1 '), {'source': 'lmstudio', 'instance': 'qwen-1'})


class Step1BuildChoices(unittest.TestCase):
    def test_both_none_is_empty(self):
        self.assertEqual(models_choices_configurator.build_choices(None, None), {})

    def test_only_given_sections(self):
        master_chief = {'source': 'pi', 'model': 'a/b'}
        executors = {'source': 'lmstudio'}
        self.assertEqual(models_choices_configurator.build_choices(master_chief, None), {'masterChief': master_chief})
        self.assertEqual(models_choices_configurator.build_choices(None, executors), {'executors': executors})
        self.assertEqual(models_choices_configurator.build_choices(master_chief, executors), {'masterChief': master_chief, 'executors': executors})


class Step2File(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / models_choices_configurator.CHOICES_PATH

    def test_missing_file_gives_empty_dict(self):
        self.assertEqual(models_choices_configurator.load_choices(self.root), {})

    def test_save_creates_folder_and_returns_path(self):
        data = {'masterChief': {'source': 'pi', 'model': 'a/b'}}
        self.assertEqual(models_choices_configurator.save_choices(self.root, data), self.path)
        self.assertTrue(self.path.is_file())

    def test_save_then_load_round_trip(self):
        data = {'masterChief': {'source': 'api', 'baseURL': 'https://x/v1', 'model': 'модель', 'keyEnv': 'K'},
                'executors': {'source': 'lmstudio', 'instance': 'qwen'}}
        models_choices_configurator.save_choices(self.root, data)
        self.assertEqual(models_choices_configurator.load_choices(self.root), data)

    def test_saved_text_is_readable(self):
        models_choices_configurator.save_choices(self.root, {'masterChief': {'source': 'pi', 'model': 'a/модель'}})
        text = self.path.read_text(encoding='utf-8')
        self.assertIn('модель', text)          # ensure_ascii=False
        self.assertIn('\n  "masterChief"', text)     # indent=2
        self.assertTrue(text.endswith('\n'))

    def test_no_temporary_file_is_left(self):
        models_choices_configurator.save_choices(self.root, {})
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])

    def test_save_overwrites_previous(self):
        models_choices_configurator.save_choices(self.root, {'masterChief': {'source': 'pi', 'model': 'a/b'}})
        models_choices_configurator.save_choices(self.root, {})
        self.assertEqual(models_choices_configurator.load_choices(self.root), {})

    def test_broken_file_is_a_value_error(self):
        self.path.parent.mkdir()
        for text in ('{broken', '[1, 2]'):
            with self.subTest(text=text):
                self.path.write_text(text, encoding='utf-8')
                with self.assertRaises(ValueError):
                    models_choices_configurator.load_choices(self.root)

    def test_reset(self):
        self.assertFalse(models_choices_configurator.reset_choices(self.root))
        models_choices_configurator.save_choices(self.root, {})
        self.assertTrue(models_choices_configurator.reset_choices(self.root))
        self.assertFalse(self.path.exists())


class Contract(unittest.TestCase):
    """What the configurator writes must be accepted by kit/run_opencode.py as is."""

    def test_launcher_reads_what_we_write(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'KIT_CONTRACT_KEY': 'x'}):
            root = Path(folder)
            data = models_choices_configurator.build_choices(
                models_choices_configurator.api_choice('https://api.example.com/v1', 'big', 'KIT_CONTRACT_KEY'),
                models_choices_configurator.lmstudio_choice('qwen-1'))
            models_choices_configurator.save_choices(root, data)
            loaded = pi_configuration.load_choices(root)
        self.assertEqual(loaded['masterChief']['model'], 'big')
        self.assertEqual(loaded['executors'], {'source': 'lmstudio', 'instance': 'qwen-1'})

    def test_same_file_location(self):
        self.assertEqual(models_choices_configurator.CHOICES_PATH, pi_configuration.CHOICES_PATH)


if __name__ == '__main__':
    unittest.main()
