"""Language changes labels, never model choices, keys or the meaning of filters."""
import json
from pathlib import Path
import re
from string import Formatter
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from kit.configurator import app, desktop, i18n, workflow
from kit.configurator.tests.test_openrouter import row, snapshot

CYRILLIC = re.compile('[\u0400-\u04ff]')


class LanguagePreferencesTests(unittest.TestCase):
    def test_missing_invalid_or_unknown_preference_uses_system_language(self):
        with tempfile.TemporaryDirectory() as folder, patch('kit.localization.system_language', return_value='ru'):
            root = Path(folder)
            self.assertEqual(i18n.load_language(root), 'ru')
            path = root / i18n.PREFERENCES
            path.parent.mkdir()
            for value in ('broken', 'null', '{"language":"de"}', '{"language":[]}', ' ' * 4097):
                path.write_text(value)
                self.assertEqual(i18n.load_language(root), 'ru')

    def test_language_is_saved_separately_from_model_choices(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            i18n.save_language(root, 'ru')
            self.assertEqual(i18n.load_language(root), 'ru')
            self.assertFalse((root / '.pi').exists())
            self.assertEqual(json.loads((root / i18n.PREFERENCES).read_text()), {'language': 'ru'})
            self.assertFalse((root / i18n.PREFERENCES).with_suffix('.tmp').exists())
            i18n.save_language(root, 'en')
            self.assertEqual(i18n.load_language(root), 'en')

    def test_translation_placeholders_match_for_every_message(self):
        formatter = Formatter()
        for english, russian in i18n.RU.items():
            with self.subTest(message=english):
                fields = lambda text: {field for literal, field, spec, conversion in formatter.parse(text) if field}
                self.assertEqual(fields(english), fields(russian))

    def test_nested_messages_translate_labels_but_never_interpolate_user_data_as_labels(self):
        translator = i18n.Translator('ru')
        message = i18n.text('{role}: {message}', role=i18n.text('Executors'), message='Free {model}')
        self.assertEqual(translator.render(message), 'Исполнители: Free {model}')
        translator.switch('en')
        self.assertEqual(translator.render(message), 'Executors: Free {model}')


class DesktopLanguageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.saved_key = patch.object(workflow, 'existing_key', return_value='')
        self.saved_key.start()
        self.addCleanup(self.saved_key.stop)
        self.window = app.tk.Tk()
        self.window.withdraw()
        self.ui = desktop.DesktopConfigurator(self.window, self.root, language='en')
        self.addCleanup(lambda: self.ui.close() if not self.ui.closed else None)

    def switch(self, language):
        self.ui.language.set(language)
        self.ui.language_combo.event_generate('<<ComboboxSelected>>')
        self.window.update()

    def pump(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.window.update()
            time.sleep(.01)
        self.assertTrue(predicate())

    def labels(self, widget):
        output = []
        if 'text' in widget.keys():
            output.append(str(widget.cget('text')))
        for child in widget.winfo_children():
            output.extend(self.labels(child))
        return output

    def test_explicit_english_interface_and_errors_override_system_language(self):
        self.assertEqual(self.ui.translator.language, 'en')
        self.assertEqual(self.ui.save_button.cget('text'), 'Save settings')
        self.assertEqual(self.window.title(), 'Project models — Pi Kit')
        self.assertFalse(any(CYRILLIC.search(label) for label in self.labels(self.window)))
        self.ui.vars['exec_source'].set('api')
        self.assertFalse(self.ui.on_save())
        self.assertIn('Select a model', self.ui.status.get())
        self.assertFalse(CYRILLIC.search(self.ui.status.get()))

    def test_switch_translates_existing_error_and_static_labels_in_both_directions(self):
        self.ui.vars['exec_source'].set('api')
        self.ui.on_save()
        self.switch('Russian')
        self.assertEqual(self.ui.save_button.cget('text'), 'Сохранить настройки')
        self.assertIn('Выберите модель', self.ui.status.get())
        self.assertEqual(self.ui.notebook.tab(self.ui.pages['exec'], 'text'), 'Исполнители')
        self.assertEqual(i18n.load_language(self.root), 'ru')
        self.switch('English')
        self.assertIn('Select a model', self.ui.status.get())
        self.assertFalse(CYRILLIC.search(self.ui.status.get()))
        self.assertEqual(i18n.load_language(self.root), 'en')

    def test_switch_preserves_draft_key_user_text_and_catalog_filter_selection(self):
        tab = self.ui.catalog
        tab.receive(snapshot(row('a/one:free', pricing={'prompt': '0', 'completion': '0'}), row('a/paid')))
        tab.tariff.set('Free models')
        tab.tree.selection_set('a/one:free')
        tab.assign()
        self.ui.typed_keys['exec'].set('draft-key-must-not-be-written')
        self.ui.vars['master_chief_model'].set('мой-ввод/{model}')
        before = self.ui.snapshot()
        with patch.object(workflow.keys, 'save_user_variable') as save:
            self.switch('Russian')
            self.assertEqual(tab.tree.get_children(), ('a/one:free',))
            self.assertEqual(tab.tree.item('a/one:free', 'values')[1], 'Бесплатно')
            self.assertEqual(tab.tree.selection(), ('a/one:free',))
            self.assertEqual(tab.tariff.get(), 'Free models')
            self.switch('English')
            self.assertEqual(tab.tree.item('a/one:free', 'values')[1], 'Free')
            self.assertEqual(tab.tree.heading('input', 'text'), 'Input $/1M')
            self.assertEqual(self.ui.snapshot(), before)
            save.assert_not_called()
        self.assertFalse((self.root / '.pi').exists())
        self.assertNotIn('draft-key', (self.root / i18n.PREFERENCES).read_text())

    def test_selected_filter_combo_uses_same_value_after_translation(self):
        tab = self.ui.catalog
        tab.receive(snapshot(row(), row('a/free', pricing={'prompt': '0', 'completion': '0'})))
        self.switch('Russian')
        combo, variable, display, values = tab.choices[1]
        combo.current(1)
        combo.event_generate('<<ComboboxSelected>>')
        self.window.update()
        self.assertEqual(variable.get(), 'Free models')
        self.assertEqual(tab.tree.get_children(), ('a/free',))
        self.switch('English')
        self.assertEqual(display.get(), 'Free models')
        self.assertEqual(tab.tree.get_children(), ('a/free',))

    def test_saved_russian_choice_is_used_on_next_open(self):
        self.switch('Russian')
        self.ui.close()
        self.window = app.tk.Tk()
        self.window.withdraw()
        self.ui = desktop.DesktopConfigurator(self.window, self.root)
        self.assertEqual(self.ui.translator.language, 'ru')
        self.assertEqual(self.ui.save_button.cget('text'), 'Сохранить настройки')

    def test_late_network_error_uses_current_language(self):
        self.ui.vars['exec_source'].set('api')
        self.ui.vars['exec_url'].set('https://api.example/v1')
        self.ui.typed_keys['exec'].set('test-key')
        release = threading.Event()

        def slow(*args):
            release.wait(2)
            raise TimeoutError('do-not-show-this-secret')

        try:
            with patch.object(desktop.sources, 'api_models', side_effect=slow):
                self.ui.fetch('exec')
                self.switch('Russian')
                release.set()
                self.pump(lambda: not self.ui.busy['exec'])
            self.assertIn('не ответил вовремя', self.ui.status.get())
            self.switch('English')
            self.assertIn('timed out', self.ui.status.get())
            self.assertNotIn('do-not-show', self.ui.status.get())
        finally:
            release.set()
