"""Navigation must follow visible content, including programmatic changes and languages."""
from pathlib import Path
import tempfile
import unittest

from kit.configurator import app, desktop
from kit.configurator.tests.test_openrouter import row, snapshot


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.window = app.tk.Tk()
        self.window.withdraw()
        self.ui = desktop.DesktopConfigurator(self.window, self.root, language='en')
        self.addCleanup(self.ui.close)
        self.ui.catalog.loaded = True

    def selected(self):
        return [key for key, button in self.ui.navigation_buttons.items() if 'selected' in button.state()]

    def test_buttons_switch_content_and_exactly_one_section_is_highlighted(self):
        self.window.update()
        self.assertEqual(self.selected(), ['master_chief'])
        for key in ('exec', 'bug_fixer', 'catalog', 'master_chief'):
            self.ui.navigation_buttons[key].invoke()
            self.window.update()
            self.assertEqual(self.ui.notebook.select(), str(self.ui.navigation_pages[key]))
            self.assertEqual(self.selected(), [key])

    def test_error_and_catalog_return_update_navigation_too(self):
        tab = self.ui.catalog
        tab.receive(snapshot(row()))
        self.ui.navigation_buttons['catalog'].invoke()
        tab.tree.selection_set('author/coder')
        tab.target.set('exec')
        tab.go_to_role()
        self.window.update()
        self.assertEqual(self.selected(), ['exec'])
        self.ui.vars['master_chief_source'].set('pi')
        self.ui.on_save()
        self.window.update()
        self.assertEqual(self.selected(), ['master_chief'])

    def test_keyboard_navigation_wraps_to_the_selected_section(self):
        self.ui.cycle_section(-1)
        self.window.update()
        self.assertEqual(self.selected(), ['catalog'])
        self.ui.cycle_section(1)
        self.window.update()
        self.assertEqual(self.selected(), ['master_chief'])
        self.ui.cycle_section(1)
        self.window.update()
        self.assertEqual(self.selected(), ['exec'])

    def test_language_switch_changes_both_button_lines_without_touching_draft(self):
        button = self.ui.navigation_buttons['master_chief']
        label = lambda: self.window.getvar(str(button.cget('textvariable')))
        self.assertEqual(label(), 'Master Chief\nPlanning & review')
        self.ui.typed_keys['exec'].set('private-draft')
        before = self.ui.snapshot()
        self.ui.language.set('Russian')
        self.ui.change_language()
        self.assertEqual(label(), 'Мастер Чиф\nАрхитектура и ревью')
        self.assertEqual(self.ui.snapshot(), before)

    def test_small_window_has_four_large_non_overlapping_buttons(self):
        self.window.deiconify()
        self.window.geometry('760x720')
        self.window.update()
        buttons = list(self.ui.navigation_buttons.values())
        self.assertEqual(len(buttons), 4)
        for index, button in enumerate(buttons):
            self.assertGreaterEqual(button.winfo_height(), 50)
            self.assertGreaterEqual(button.winfo_width(), 200)
            self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                 self.window.winfo_rootx() + self.window.winfo_width())
            for other in buttons[:index]:
                overlap_x = max(button.winfo_rootx(), other.winfo_rootx()) < min(
                    button.winfo_rootx() + button.winfo_width(), other.winfo_rootx() + other.winfo_width())
                overlap_y = max(button.winfo_rooty(), other.winfo_rooty()) < min(
                    button.winfo_rooty() + button.winfo_height(), other.winfo_rooty() + other.winfo_height())
                self.assertFalse(overlap_x and overlap_y)
