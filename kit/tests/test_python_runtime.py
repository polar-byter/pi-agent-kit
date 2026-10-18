"""Native bootstrap rejection paths: no network, global Python changes or GUI."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]


class PythonRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.runtime = self.home / 'kit with spaces' / 'runtime'
        shutil.copytree(ROOT / 'kit/runtime', self.runtime)
        self.cache = self.home / 'runtime cache'
        self.env = dict(os.environ, OPENCODE_KIT_RUNTIME_HOME=str(self.cache), PI_KIT_RUNTIME_HOME=str(self.cache))

    def run_bootstrap(self, *, fake_download=None):
        if os.name == 'nt':
            if fake_download is not None:
                harness = self.home / 'harness.ps1'
                harness.write_text('function Invoke-WebRequest { param([switch]$UseBasicParsing, $Uri, $OutFile, $TimeoutSec)\n'
                    f'Copy-Item -LiteralPath "{fake_download}" -Destination $OutFile\n}}\n'
                    f'& "{self.runtime / "bootstrap.ps1"}" --kit-runtime-path\nexit $LASTEXITCODE\n', encoding='utf-8')
                script = harness
            else:
                script = self.runtime / 'bootstrap.ps1'
            command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)]
            if fake_download is None:
                command.append('--kit-runtime-path')
        else:
            if fake_download is not None:
                binaries = self.home / 'bin'
                binaries.mkdir(exist_ok=True)
                curl = binaries / 'curl'
                curl.write_text('#!/bin/sh\nwhile [ "$1" != --output ]; do shift; done\n'
                                f'cp "{fake_download}" "$2"\n', encoding='utf-8')
                curl.chmod(0o755)
                self.env['PATH'] = str(binaries) + ':' + self.env['PATH']
            command = ['sh', str(self.runtime / 'bootstrap.sh'), '--kit-runtime-path']
        return subprocess.run(command, env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=30)

    def test_invalid_manifest_cannot_trigger_a_download(self):
        lock = self.runtime / 'python.lock'
        lock.write_text(lock.read_text().replace('version=3.13.16', 'version=latest'), encoding='utf-8')
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('version', result.stderr.lower())
        self.assertFalse(self.cache.exists())

    def test_unofficial_source_is_rejected_before_cache_creation(self):
        lock = self.runtime / 'python.lock'
        lock.write_text(lock.read_text().replace('www.python.org', 'example.invalid'), encoding='utf-8')
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('url', result.stderr.lower())
        self.assertFalse(self.cache.exists())

    def test_corrupt_download_is_not_installed_and_next_launch_is_not_locked(self):
        download = self.home / 'corrupt.zip'
        download.write_bytes(b'incomplete download')
        for _ in range(2):
            result = self.run_bootstrap(fake_download=download)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('checksum', result.stderr.lower())
            self.assertEqual([p for p in self.cache.iterdir() if p.is_dir()], [])

    def test_existing_damaged_runtime_is_preserved(self):
        suffix = ('windows_arm64' if os.environ.get('PROCESSOR_ARCHITECTURE') == 'ARM64' else 'windows_x64') if os.name == 'nt' else 'linux-' + os.uname().machine
        target = self.cache / ('cpython-3.13.16-' + suffix)
        target.mkdir(parents=True)
        marker = target / 'user-file'
        marker.write_text('preserve me')
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('damaged', result.stderr.lower())
        self.assertEqual(marker.read_text(), 'preserve me')

    def test_windows_archive_traversal_is_rejected_after_checksum(self):
        if os.name != 'nt':
            # Linux uses the fixed, pinned official tarball. Exercise duplicate
            # manifest rejection here instead of pretending to unpack a Windows ZIP.
            lock = self.runtime / 'python.lock'
            lock.write_text(lock.read_text() + '\nversion=3.13.16\n', encoding='utf-8')
            result = self.run_bootstrap()
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.cache.exists())
            return
        content = io.BytesIO()
        with zipfile.ZipFile(content, 'w') as archive:
            archive.writestr('../escaped.txt', 'must not escape')
        download = self.home / 'unsafe.zip'
        download.write_bytes(content.getvalue())
        digest = hashlib.sha256(download.read_bytes()).hexdigest()
        lock = self.runtime / 'python.lock'
        lines = [line.split('=')[0] + '=' + digest if '_sha256=' in line else line for line in lock.read_text().splitlines()]
        lock.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        result = self.run_bootstrap(fake_download=download)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsafe', result.stderr.lower())
        self.assertFalse(list(self.home.rglob('escaped.txt')))
        self.assertEqual([p for p in self.cache.iterdir() if p.is_dir()], [])

    def test_installed_payload_contains_all_native_entry_points(self):
        from kit.installer import payload
        files = payload(ROOT)
        for name in ('install.cmd', 'install.sh', 'install.py', 'kit/python.cmd',
                     'kit/python.sh', 'kit/runtime/python.lock', 'kit/runtime/bootstrap.ps1',
                     'kit/runtime/bootstrap.sh', 'kit/runtime/desktop.sh'):
            self.assertIn(name, files)


if __name__ == '__main__':
    unittest.main()
