"""Separate project installation excludes local choices, credentials and caches."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kit import pi_installation


class PiInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / 'template'
        self.source.mkdir()
        for name in pi_installation.ROOT_FILES:
            (self.source / name).write_text('{}' if name.endswith('.json') else 'Template file', encoding='utf-8')
        for tree in pi_installation.TREES:
            (self.source / tree).mkdir(exist_ok=True)
        (self.source / 'kit/run_pi.py').write_text('print("Pi")')

    def test_installation_creates_a_pi_project_and_shares_the_template_runtime(self):
        destination = self.base / 'application'
        result = pi_installation.install_project(self.source, str(destination))
        self.assertFalse(result['reused'])
        self.assertTrue((destination / 'pi-kit.json').is_file())
        self.assertFalse((destination / 'opencode.jsonc').exists())
        installation = json.loads((destination / '.pi/installation.json').read_text())
        self.assertEqual(installation['runtime_root'], str(self.source.resolve()))
        self.assertTrue(pi_installation.installed(destination))
        self.assertTrue(pi_installation.install_project(self.source, str(destination))['reused'])

    def test_conflicting_project_files_are_preserved(self):
        destination = self.base / 'application'
        destination.mkdir()
        (destination / 'pi-kit.json').write_text('User settings')
        with self.assertRaises(pi_installation.InstallError):
            pi_installation.install_project(self.source, str(destination))
        self.assertEqual((destination / 'pi-kit.json').read_text(), 'User settings')
        self.assertFalse((destination / 'kit').exists())

    def test_payload_excludes_credentials_and_generated_python_files(self):
        for name in ('auth.json', 'credentials.json', 'module.pyc'):
            (self.source / 'kit' / name).write_text('private')
        files = pi_installation.payload(self.source)
        self.assertFalse(any(name.endswith(('auth.json', 'credentials.json', '.pyc')) for name in files))

    def test_existing_application_readme_and_license_are_preserved(self):
        destination = self.base / 'application'
        destination.mkdir()
        for name in ('README.md', 'LICENSE'):
            (destination / name).write_text('Application document')
        pi_installation.install_project(self.source, str(destination))
        for name in ('README.md', 'LICENSE'):
            self.assertEqual((destination / name).read_text(), 'Application document')

    def test_existing_runtime_does_not_start_npm(self):
        with patch.object(pi_installation, 'locate_pi_command', return_value=['node', 'pi.js']), patch.object(pi_installation.subprocess, 'run') as run:
            self.assertEqual(pi_installation.install_pi_runtime(self.source), ['node', 'pi.js'])
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
