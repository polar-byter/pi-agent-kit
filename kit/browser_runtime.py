"""Prepare the pinned browser CLI beside the kit, never in global npm storage."""
import json
import os
from pathlib import Path
import shutil
import subprocess

CLI_VERSION = '0.1.22'


def browser_runtime_root(project):
    project = Path(project).resolve()
    configured = os.environ.get('KIT_BROWSER_RUNTIME_HOME')
    if configured:
        return Path(configured).resolve()
    installation = project / '.pi/installation.json'
    if installation.is_file():
        return Path(json.loads(installation.read_text(encoding='utf-8'))['runtime_root']).resolve() / '.tools/browser'
    return project / '.tools/browser'


def browser_environment(runtime):
    environment = os.environ.copy()
    cache = runtime.parent / 'browser-cache'
    temporary = runtime.parent / 'temporary'
    for path in (cache, temporary):
        path.mkdir(parents=True, exist_ok=True)
    environment.update(NO_UPDATE_NOTIFIER='1', npm_config_cache=str(runtime.parent / 'npm-cache'),
                       PLAYWRIGHT_BROWSERS_PATH=str(runtime.parent / 'browser-binaries'),
                       XDG_CACHE_HOME=str(cache), LOCALAPPDATA=str(cache),
                       TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
    return environment


def ensure_browser_command(project):
    """Use the bundled lock file; npm lifecycle scripts and browser downloads are disabled."""
    runtime = browser_runtime_root(project)
    node = shutil.which('node')
    if not node:
        raise ValueError('Browser review needs Node.js 18 or newer. Install Node and retry.')
    package = runtime / 'node_modules/@playwright/cli'
    if not (package / 'package.json').is_file() or json.loads((package / 'package.json').read_text())['version'] != CLI_VERSION:
        npm = shutil.which('npm')
        if not npm:
            raise ValueError('Browser setup needs npm from the Node.js installation.')
        npm_path = Path(npm).resolve()
        npm_script = npm_path if npm_path.name == 'npm-cli.js' else npm_path.parent / 'node_modules/npm/bin/npm-cli.js'
        if not npm_script.is_file():
            raise ValueError('Cannot locate npm-cli.js beside Node.js.')
        runtime.mkdir(parents=True, exist_ok=True)
        source = Path(__file__).parent / 'browser'
        for name in ('package.json', 'package-lock.json'):
            shutil.copyfile(source / name, runtime / name)
        result = subprocess.run([node, str(npm_script), 'ci', '--ignore-scripts', '--omit=dev', '--no-audit', '--no-fund'],
                                cwd=runtime, env=browser_environment(runtime), capture_output=True, text=True,
                                timeout=600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError('Browser setup failed. Check network access and free space on the project disk.')
    return [node, str(package / 'playwright-cli.js')], browser_environment(runtime)


def browser_channel():
    """Prefer an installed system browser; keep its ordinary user profile separate."""
    configured = os.environ.get('KIT_BROWSER_CHANNEL')
    if configured:
        if configured not in ('chrome', 'msedge', 'firefox', 'webkit'):
            raise ValueError('KIT_BROWSER_CHANNEL must be chrome, msedge, firefox or webkit.')
        return configured
    if os.name == 'nt':
        edge = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        if edge.is_file():
            return 'msedge'
    return 'chrome'
