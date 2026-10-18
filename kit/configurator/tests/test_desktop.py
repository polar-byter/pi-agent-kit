"""Exercise real Tk state with fake model services and credential persistence."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from kit.configurator import app, desktop, openrouter
from kit.configurator.tests.test_openrouter import row, snapshot
from kit import pi_configuration


class DesktopTests(unittest.TestCase):
    def test_prepared_callback_fires_only_after_success(self):
        results = []
        self.ui.on_prepared = lambda: results.append(self.ui.preparing)
        self.ui.preparing = True
        self.ui.receive_preparation(False)
        self.assertEqual(results, [])
        self.ui.preparing = True
        self.ui.receive_preparation(True)
        self.assertEqual(results, [False])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.stored = patch.object(desktop.workflow, 'existing_key', return_value='')
        self.stored.start()
        self.addCleanup(self.stored.stop)
        self.window = app.tk.Tk()
        self.window.withdraw()
        self.ui = desktop.DesktopConfigurator(self.window, self.root, language='ru')
        self.addCleanup(self.ui.close)

    def pump_until(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.window.update()
            time.sleep(.01)
        self.assertTrue(predicate(), 'background response was not processed')

    def api(self, role='exec'):
        for name, value in {'source': 'api', 'url': 'https://api.example/v1', 'model': 'my-model'}.items():
            self.ui.vars[role + '_' + name].set(value)
        self.ui.typed_keys[role].set('secret-for-tests')

    def test_only_active_source_panel_is_displayed_and_drafts_survive(self):
        self.api()
        self.ui.vars['exec_source'].set('lmstudio')
        panels = self.ui.widgets['exec']['panels']
        self.assertEqual(panels['api'].winfo_manager(), '')
        self.assertEqual(panels['lmstudio'].winfo_manager(), 'grid')
        self.ui.vars['exec_source'].set('api')
        self.assertEqual(self.ui.vars['exec_model'].get(), 'my-model')
        self.assertEqual(self.ui.typed_keys['exec'].get(), 'secret-for-tests')
        self.assertEqual(panels['api'].winfo_manager(), 'grid')

    def test_new_project_shows_existing_key_without_putting_it_in_entry(self):
        self.ui.vars['exec_source'].set('api')
        self.ui.vars['exec_key_env'].set('OPENROUTER_API_KEY')
        with patch.object(desktop.workflow,'existing_key',return_value='private-registry-key'):
            self.ui.render('exec')
        widgets=self.ui.widgets['exec']
        self.assertIn('Ключ найден',widgets['key_badge'].get())
        self.assertIn('OPENROUTER_API_KEY',widgets['key_status'].get())
        self.assertIn('Повторно вводить не нужно',widgets['key_status'].get())
        self.assertIn('необязательно',widgets['key_title'].get())
        self.assertEqual(widgets['key_hint'].winfo_manager(),'grid')
        self.assertEqual(self.ui.typed_keys['exec'].get(),'')
        self.assertNotIn('private-registry-key',widgets['key_status'].get())
        self.assertFalse((self.root/'.pi').exists())

    def test_typed_replacement_hides_saved_placeholder_and_clear_restores_it(self):
        self.ui.vars['exec_source'].set('api')
        with patch.object(desktop.workflow,'existing_key',return_value='saved-private'):
            self.ui.typed_keys['exec'].set('replacement-private')
            self.assertEqual(self.ui.widgets['exec']['key_hint'].winfo_manager(),'')
            self.assertIn('новый ключ',self.ui.widgets['exec']['key_badge'].get())
            self.ui.typed_keys['exec'].set('')
            self.assertEqual(self.ui.widgets['exec']['key_hint'].winfo_manager(),'grid')

    def test_connection_check_uses_saved_key_without_model_or_saving(self):
        self.ui.vars['exec_source'].set('api');self.ui.vars['exec_url'].set(openrouter.API_URL)
        with patch.object(desktop.workflow,'existing_key',return_value='registry-private'), \
             patch.object(desktop.api_connection,'check',return_value={'authenticated':True}) as check, \
             patch.object(desktop.workflow,'save') as save:
            self.ui.widgets['exec']['connection_button'].invoke()
            self.pump_until(lambda:not self.ui.busy['exec'])
            check.assert_called_once_with(openrouter.API_URL,'registry-private');save.assert_not_called()
        self.assertIn('принял ключ',self.ui.widgets['exec']['connection_status'].get())
        self.assertEqual(self.ui.vars['exec_model'].get(),'')
        self.assertEqual(self.ui.typed_keys['exec'].get(),'')
        self.assertNotIn('disabled',self.ui.widgets['exec']['connection_button'].state())

    def test_connection_check_is_nonblocking_and_stale_result_is_rejected(self):
        self.api();release,started=threading.Event(),threading.Event()
        def slow(*args):started.set();release.wait(2);return {'authenticated':True}
        try:
            with patch.object(desktop.api_connection,'check',side_effect=slow) as check:
                self.ui.check_connection('exec');self.assertTrue(started.wait(1))
                self.ui.check_connection('exec');self.assertEqual(check.call_count,1)
                self.assertIn('disabled',self.ui.widgets['exec']['connection_button'].state())
                heartbeat=[];self.window.after(0,lambda:heartbeat.append(True));self.window.update();self.assertTrue(heartbeat)
                self.ui.vars['exec_url'].set('https://new-api.example/v1')
                release.set();self.pump_until(lambda:not self.ui.busy['exec'])
            self.assertIn('изменились',self.ui.widgets['exec']['connection_status'].get())
            self.assertNotIn('принял ключ',self.ui.widgets['exec']['connection_status'].get())
        finally:release.set()

    def test_connection_feedback_distinguishes_public_models_and_hides_errors(self):
        self.api()
        with patch.object(desktop.api_connection,'check',return_value={'authenticated':False,'models':12}):
            self.ui.check_connection('exec');self.pump_until(lambda:not self.ui.busy['exec'])
        self.assertIn('не подтверждены',self.ui.widgets['exec']['connection_status'].get())
        with patch.object(desktop.api_connection,'check',side_effect=ValueError('secret-for-tests')):
            self.ui.check_connection('exec');self.pump_until(lambda:not self.ui.busy['exec'])
        self.assertNotIn('secret-for-tests',self.ui.widgets['exec']['connection_status'].get())

    def test_connection_shared_draft_and_language_switch_keep_values(self):
        for role in desktop.workflow.ROLES:
            self.ui.vars[role+'_source'].set('api');self.ui.vars[role+'_url'].set(openrouter.API_URL)
            self.ui.vars[role+'_key_env'].set('COMMON_KEY')
        self.ui.typed_keys['exec'].set('shared-private')
        with patch.object(desktop.api_connection,'check',return_value={'authenticated':True}) as check:
            self.ui.check_connection('master_chief');self.pump_until(lambda:not self.ui.busy['master_chief'])
        check.assert_called_once_with(openrouter.API_URL,'shared-private')
        self.ui.translator.switch('en');self.ui.localize()
        self.assertEqual(self.ui.widgets['exec']['connection_button'].cget('text'),'Check connection')
        self.assertIn('accepted',self.ui.widgets['master_chief']['connection_status'].get())
        self.assertEqual(self.ui.typed_keys['exec'].get(),'shared-private')

    def test_connection_button_is_visible_in_small_window_without_scrolling(self):
        self.window.deiconify();self.window.geometry('760x720')
        self.ui.notebook.select(self.ui.pages['exec']);self.api()
        self.ui.canvases['exec'].yview_moveto(0);self.window.update()
        button=self.ui.widgets['exec']['connection_button'];canvas=self.ui.canvases['exec']
        self.assertTrue(button.winfo_ismapped())
        self.assertGreaterEqual(button.winfo_rooty(),canvas.winfo_rooty())
        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),canvas.winfo_rooty()+canvas.winfo_height())

    def test_save_reopen_manual_model_and_key_is_cleared_from_entry(self):
        self.api()
        with patch.object(desktop.workflow.keys, 'save_user_variable') as save:
            self.assertTrue(self.ui.on_save())
        save.assert_called_once()
        text = (self.root / '.pi/kit-models.json').read_text()
        self.assertNotIn('secret-for-tests', text)
        self.assertEqual(json.loads(text)['executors']['model'], 'my-model')
        self.assertEqual(self.ui.typed_keys['exec'].get(), '')
        self.assertEqual(self.ui.dirty.get(), '')
        self.ui.vars['exec_model'].set('draft')
        self.ui.loading = True
        self.ui.load()
        self.ui.loading = False
        self.assertEqual(self.ui.vars['exec_model'].get(), 'my-model')

    def test_error_selects_correct_role_and_opens_advanced_field(self):
        self.api('master_chief')
        self.ui.vars['master_chief_key_env'].set('bad name')
        self.assertFalse(self.ui.on_save())
        self.assertEqual(self.ui.notebook.select(), str(self.ui.pages['master_chief']))
        self.assertTrue(self.ui.advanced['master_chief'].get())
        self.assertIn('переменной', self.ui.status.get())
        self.assertFalse((self.root / '.pi').exists())

    def test_inactive_typed_key_is_never_persisted(self):
        self.ui.typed_keys['exec'].set('hidden-secret')
        with patch.object(desktop.workflow.keys, 'save_user_variable') as save:
            self.assertTrue(self.ui.on_save())
            save.assert_not_called()

    def test_background_discovery_does_not_block_tk_and_keeps_manual_model(self):
        self.api()
        release, started = threading.Event(), threading.Event()

        def slow(url, key):
            started.set()
            release.wait(2)
            return ['one', 'two']

        try:
            with patch.object(desktop.sources, 'api_models', side_effect=slow):
                self.ui.fetch('exec')
                self.assertTrue(started.wait(1))
                heartbeat = []
                self.window.after(0, lambda: heartbeat.append(True))
                self.window.update()
                self.assertEqual(heartbeat, [True])
                self.assertTrue(self.ui.busy['exec'])
                release.set()
                self.pump_until(lambda: not self.ui.busy['exec'])
            self.assertEqual(self.ui.widgets['exec']['fields']['model']['values'], ('one', 'two'))
            self.assertEqual(self.ui.vars['exec_model'].get(), 'my-model')
            self.assertIn('только /models', self.ui.widgets['exec']['activity'].get())
        finally:
            release.set()

    def test_old_response_after_address_change_is_ignored(self):
        self.api()
        generation = self.ui.generations['exec']
        self.ui.vars['exec_url'].set('https://different.example/v1')
        self.ui.receive_models('exec', generation, 'api', ['wrong-service'], '')
        self.assertEqual(self.ui.widgets['exec']['fields']['model']['values'], '')
        self.assertIn('заново', self.ui.widgets['exec']['activity'].get())

    def test_failed_request_keeps_form_and_hides_server_secrets(self):
        self.api()
        before = self.ui.snapshot()
        with patch.object(desktop.sources, 'api_models', side_effect=ValueError('secret-for-tests')):
            self.ui.fetch('exec')
            self.pump_until(lambda: not self.ui.busy['exec'])
        self.assertEqual(before, self.ui.snapshot())
        self.assertNotIn('secret-for-tests', self.ui.widgets['exec']['activity'].get())
        self.assertIn('вручную', self.ui.widgets['exec']['activity'].get())

    def test_reset_preserves_windows_keys_and_invalidates_pending_results(self):
        self.api()
        generation = self.ui.generations['exec']
        with patch.object(desktop.workflow.keys, 'save_user_variable') as save:
            self.ui.on_reset()
            save.assert_not_called()
        self.assertEqual(self.ui.form(), app.EMPTY_FORM)
        self.assertEqual(self.ui.typed_keys['exec'].get(), '')
        self.assertGreater(self.ui.generations['exec'], generation)
        self.assertIn('оставлены', self.ui.status.get())

    def test_preparation_is_explicit_and_does_not_reload_current_session(self):
        form = {'source': 'pi', 'model': 'provider/model'}
        self.ui.vars['exec_source'].set(form['source'])
        self.ui.vars['exec_model'].set(form['model'])
        with patch.object(desktop.workflow, 'prepare', return_value=(0, 'secret-output')) as prepare:
            self.assertTrue(self.ui.on_save())
            prepare.assert_not_called()
            self.ui.on_prepare()
            self.pump_until(lambda: not self.ui.preparing)
        self.assertEqual(prepare.call_count, 1)
        self.assertIn('подготовлены', self.ui.status.get())
        self.assertNotIn('secret-output', self.ui.status.get())
        self.assertNotIn('disabled', self.ui.save_button.state())

    def test_malformed_saved_file_is_not_overwritten_on_open(self):
        path = self.root / '.pi/kit-models.json'
        path.parent.mkdir()
        for text in ('broken json', '{"executors":{"source":"magic"}}', '{"executors":null}'):
            path.write_text(text)
            self.ui.load()
            self.assertIn('Не удалось прочитать', self.ui.status.get())
            self.assertEqual(path.read_text(), text)

    def test_entry_point_uses_new_desktop(self):
        with patch.object(desktop, 'main', return_value=17):
            self.assertEqual(app.main(), 17)

    def test_small_window_scrolls_to_advanced_field_and_keeps_actions_visible(self):
        self.window.deiconify()
        self.window.geometry('760x720')
        self.ui.notebook.select(self.ui.pages['exec'])
        self.api()
        self.ui.advanced['exec'].set(True)
        self.ui.toggle_advanced('exec')
        self.pump_until(lambda: 'exec' not in self.ui.visibility_jobs)
        canvas = self.ui.canvases['exec']
        field = self.ui.widgets['exec']['fields']['key_env']
        self.assertGreaterEqual(field.winfo_rooty(), canvas.winfo_rooty())
        self.assertLessEqual(field.winfo_rooty() + field.winfo_height(),
                             canvas.winfo_rooty() + canvas.winfo_height())
        self.assertLess(self.ui.status_label.winfo_rooty() + self.ui.status_label.winfo_height(),
                        self.window.winfo_rooty() + self.window.winfo_height())

    def test_catalog_selection_fills_one_role_with_exact_api_model_id_without_saving(self):
        tab = self.ui.catalog
        tab.receive(snapshot(row('a/coder:free', pricing={'prompt': '0', 'completion': '0'})))
        other_before = {name: var.get() for name, var in self.ui.vars.items() if name.startswith('master_chief_')}
        self.ui.typed_keys['exec'].set('key-for-different-provider')
        tab.tree.selection_set('a/coder:free')
        tab.assign()
        self.assertEqual(self.ui.vars['exec_source'].get(), 'api')
        self.assertEqual(self.ui.vars['exec_url'].get(), openrouter.API_URL)
        self.assertEqual(self.ui.vars['exec_model'].get(), 'a/coder:free')
        self.assertEqual(self.ui.vars['exec_key_env'].get(), 'OPENROUTER_API_KEY')
        self.assertEqual(self.ui.typed_keys['exec'].get(), '')
        self.assertEqual(other_before, {name: var.get() for name, var in self.ui.vars.items() if name.startswith('master_chief_')})
        self.assertFalse((self.root / '.pi').exists())
        self.assertTrue(self.ui.dirty.get())

    def test_catalog_master_chief_selection_preserves_existing_openrouter_key_draft(self):
        tab = self.ui.catalog
        tab.receive(snapshot(row()))
        self.ui.vars['master_chief_url'].set(openrouter.API_URL)
        self.ui.vars['master_chief_key_env'].set('CUSTOM_OR_KEY')
        self.ui.typed_keys['master_chief'].set('openrouter-draft-key')
        tab.target.set('master_chief')
        tab.tree.selection_set('author/coder')
        tab.assign()
        self.assertEqual(self.ui.vars['master_chief_model'].get(), 'author/coder')
        self.assertEqual(self.ui.vars['master_chief_key_env'].get(), 'CUSTOM_OR_KEY')
        self.assertEqual(self.ui.typed_keys['master_chief'].get(), 'openrouter-draft-key')
        self.assertEqual(self.ui.vars['exec_source'].get(), app.EXEC_LMSTUDIO)

    def test_catalog_filter_refresh_and_programmatic_selection_do_not_change_form(self):
        tab = self.ui.catalog
        before = self.ui.snapshot()
        tab.receive(snapshot(row(), row('a/second')))
        tab.tree.selection_set('author/coder')
        self.window.update()
        tab.query.set('second')
        self.window.update()
        self.assertEqual(self.ui.snapshot(), before)
        self.assertEqual(tab.tree.get_children(), ('a/second',))

    def test_catalog_failure_keeps_last_successful_prices(self):
        tab = self.ui.catalog
        tab.receive(snapshot(row()))
        tab.receive(None)
        self.assertEqual(tab.tree.get_children(), ('author/coder',))
        self.assertIn('прежние', tab.info.get())
        self.assertNotIn('disabled', tab.refresh_button.state())

    def test_catalog_fetch_runs_in_background_and_only_when_tab_is_opened(self):
        tab = self.ui.catalog
        with patch.object(openrouter, 'fetch', return_value=snapshot(row())) as fetch:
            self.window.update()
            fetch.assert_not_called()
            self.ui.notebook.select(tab.page)
            self.window.update()
            self.pump_until(lambda: tab.loaded)
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(tab.tree.get_children(), ('author/coder',))

    def test_catalog_both_roles_share_one_key_and_save_with_existing_launcher_contract(self):
        tab = self.ui.catalog
        tab.receive(snapshot(row()))
        tab.tree.selection_set('author/coder')
        tab.assign()
        tab.target.set('master_chief')
        tab.assign()
        self.ui.typed_keys['exec'].set('one-openrouter-key')
        self.assertIn('Общий ключ', self.ui.widgets['master_chief']['key_status'].get())
        with patch.object(desktop.workflow.keys, 'save_user_variable') as save:
            self.assertTrue(self.ui.on_save())
            save.assert_called_once_with('OPENROUTER_API_KEY', 'one-openrouter-key')
        choices = json.loads((self.root / '.pi/kit-models.json').read_text())
        for role in ('masterChief', 'executors'):
            self.assertEqual(choices[role], {'source': 'api', 'baseURL': openrouter.API_URL,
                            'model': 'author/coder', 'keyEnv': 'OPENROUTER_API_KEY'})
        prompts = self.root / 'kit/prompts'
        prompts.mkdir(parents=True)
        for name in ('master-chief.md', 'executor.md', 'executor-fast.md', 'bug-fixer.md'):
            (prompts / name).write_text('Role prompt', encoding='utf-8')
        with patch.object(desktop.workflow, 'existing_key', return_value='one-openrouter-key'):
            self.assertIsNone(pi_configuration.write_prepared_pi_configuration(self.root))
        runtime_text = (self.root / '.pi/kit-runtime.json').read_text()
        runtime = json.loads(runtime_text)
        models_text = (self.root / '.pi/agent/models.json').read_text()
        providers = json.loads(models_text)['providers']
        self.assertEqual(runtime['roles']['build']['provider'], 'kit-master-chief-api')
        self.assertEqual(runtime['roles']['build']['model'], 'author/coder')
        self.assertEqual(runtime['roles']['executor']['provider'], 'kit-executor-api')
        self.assertEqual(providers['kit-executor-api']['baseUrl'], openrouter.API_URL)
        self.assertNotIn('one-openrouter-key', models_text + runtime_text)

    def test_catalog_cache_is_available_when_refresh_fails(self):
        tab = self.ui.catalog
        with patch.object(openrouter, 'cached', return_value=snapshot(row())), \
             patch.object(openrouter, 'fetch', side_effect=OSError('offline')):
            self.ui.notebook.select(tab.page)
            self.window.update()
            self.pump_until(lambda: tab.failed)
        self.assertEqual(tab.tree.get_children(), ('author/coder',))
        self.assertIn('прежние', tab.info.get())

    def test_catalog_small_window_keeps_several_table_rows_and_restores_form_actions(self):
        tab = self.ui.catalog
        tab.receive(snapshot(row()))
        self.window.deiconify()
        self.window.geometry('760x720')
        self.ui.notebook.select(tab.page)
        self.window.update()
        self.assertFalse(self.ui.footer.winfo_ismapped())
        self.assertGreaterEqual(tab.tree.winfo_height(), 180)
        tab.tree.selection_set('author/coder')
        tab.go_to_role()
        self.window.update()
        self.assertTrue(self.ui.footer.winfo_ismapped())
        self.assertEqual(self.ui.notebook.select(), str(self.ui.pages['exec']))

    def test_catalog_shared_draft_key_is_used_for_model_discovery_too(self):
        tab = self.ui.catalog
        tab.receive(snapshot(row()))
        tab.tree.selection_set('author/coder')
        tab.assign()
        tab.target.set('master_chief')
        tab.assign()
        self.ui.typed_keys['exec'].set('common-key-for-request')
        with patch.object(desktop.sources, 'api_models', return_value=['author/coder']) as fetch:
            self.ui.fetch('master_chief')
            self.pump_until(lambda: not self.ui.busy['master_chief'])
        fetch.assert_called_once_with(openrouter.API_URL, 'common-key-for-request')

    def test_changing_shared_key_invalidates_other_roles_pending_discovery(self):
        tab = self.ui.catalog
        tab.receive(snapshot(row()))
        tab.tree.selection_set('author/coder')
        tab.assign()
        tab.target.set('master_chief')
        tab.assign()
        self.ui.typed_keys['exec'].set('old-key')
        old_generation = self.ui.generations['master_chief']
        self.ui.typed_keys['exec'].set('new-key')
        self.ui.receive_models('master_chief', old_generation, 'api', ['wrong-account/model'], '')
        self.assertEqual(self.ui.widgets['master_chief']['fields']['model']['values'], '')
        self.assertIn('заново', self.ui.widgets['master_chief']['activity'].get())

    def test_catalog_assigns_independent_bug_fixer_and_shared_key_check(self):
        tab = self.ui.catalog
        tab.receive(snapshot(row()))
        tab.tree.selection_set('author/coder')
        for role in ('exec', 'master_chief', 'bug_fixer'):
            tab.target.set(role)
            tab.assign()
        self.ui.typed_keys['exec'].set('shared-key')
        with patch.object(desktop.api_connection, 'check', return_value={'authenticated': True}) as check:
            self.ui.check_connection('bug_fixer')
            self.pump_until(lambda: not self.ui.busy['bug_fixer'])
        check.assert_called_once_with(openrouter.API_URL, 'shared-key')
        self.assertEqual(self.ui.vars['bug_fixer_source'].get(), 'api')
        self.assertEqual(self.ui.notebook.tab(self.ui.pages['bug_fixer'], 'text'), 'Исправитель ошибок')

    def test_bug_fixer_connection_is_invalidated_by_shared_key_change(self):
        for role in ('exec', 'bug_fixer'):
            self.api(role)
            self.ui.vars[role + '_key_env'].set('SHARED_KEY')
        self.ui.typed_keys['bug_fixer'].set('')
        generation = self.ui.generations['bug_fixer']
        self.ui.typed_keys['exec'].set('replacement-key')
        self.ui.receive_connection('bug_fixer', generation, {'authenticated': True}, '')
        self.assertIn('ещё раз', self.ui.widgets['bug_fixer']['connection_status'].get())
