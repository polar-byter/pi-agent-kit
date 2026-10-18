"""Exercise the Pi wizard with local installation and model calls replaced."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from kit import pi_installer_ui


class PiInstallerWindowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / 'template'
        self.source.mkdir()
        self.window = pi_installer_ui.tk.Tk()
        self.window.withdraw()
        self.wizard = pi_installer_ui.PiInstallerWindow(self.window, self.source)
        self.wizard.language.set('en')
        self.wizard.localize()
        self.addCleanup(self.wizard.close)

    def wait_for_installation(self):
        deadline = time.monotonic() + 3
        while self.wizard.running and time.monotonic() < deadline:
            self.window.update()
            time.sleep(.01)
        self.assertFalse(self.wizard.running)

    def test_language_switch_keeps_the_selected_project_folder(self):
        project = str(self.source.parent / 'application')
        self.wizard.project_directory.set(project)
        self.wizard.language.set('ru')
        self.wizard.localize()
        self.assertEqual(self.wizard.project_directory.get(), project)
        self.assertIn('Создать', self.wizard.heading.cget('text'))

    def test_success_opens_the_actual_project_configurator(self):
        project = self.source.parent / 'application'
        self.wizard.project_directory.set(str(project))
        with patch.object(pi_installer_ui.pi_installation, 'install_pi_runtime', return_value=['node', 'pi.js']) as runtime, \
             patch.object(pi_installer_ui.pi_installation, 'install_project', return_value={'project': str(project)}) as install, \
             patch.object(pi_installer_ui, 'DesktopConfigurator') as configure:
            self.wizard.install_and_configure()
            self.wait_for_installation()
        runtime.assert_called_once_with(self.source)
        install.assert_called_once_with(self.source, str(project))
        self.assertEqual(configure.call_args.args[1], project)
        self.assertEqual(configure.call_args.kwargs['language'], 'en')
        self.assertIn('Project ready', self.wizard.status.get())

    def test_installation_error_does_not_open_a_configurator(self):
        with patch.object(pi_installer_ui.pi_installation, 'install_pi_runtime', side_effect=ValueError('Installation unavailable')), \
             patch.object(pi_installer_ui, 'DesktopConfigurator') as configure:
            self.wizard.install_and_configure()
            self.wait_for_installation()
        configure.assert_not_called()
        self.assertEqual(self.wizard.status.get(), 'Installation unavailable')

    def test_template_directory_is_rejected_before_installation(self):
        self.wizard.project_directory.set(str(self.source))
        with patch.object(pi_installer_ui.pi_installation, 'install_pi_runtime') as runtime:
            self.wizard.install_and_configure()
        runtime.assert_not_called()
        self.assertFalse(self.wizard.running)
