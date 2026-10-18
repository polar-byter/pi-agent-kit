"""Translate the kit's role choices into an isolated Pi configuration.

The configurator owns the saved choices. This module validates them and prepares
the runtime files without starting a conversation or loading a local model.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading

from .execution_policy import normalize_policy
from .lmstudio_models import DEFAULT_BASE, loaded_models, select_model

CHOICES_PATH = Path('.pi/kit-models.json')
RUNTIME_PATH = Path('.pi/kit-runtime.json')
AGENT_DIRECTORY = Path('.pi/agent')
PI_PACKAGE = '@earendil-works/pi-coding-agent'
PI_VERSION = '1.3.0'
ROLE_SETTINGS = {'masterChief': ('build', 'master-chief.md'),
                 'executors': ('executor', 'executor.md'),
                 'bugFixer': ('bug-fixer', 'bug-fixer.md')}
ENVIRONMENT_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def read_json_object(path: Path, *, missing=None) -> dict:
    """Read one object and preserve the path in validation errors."""
    if not path.exists() and missing is not None:
        return dict(missing)
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f'Could not read {path.name}: {error}') from error
    if not isinstance(value, dict):
        raise ValueError(f'{path.name} must contain a JSON object')
    return value


def load_project_defaults(root: Path) -> dict:
    """Read only Pi defaults; OpenCode connections require an explicit migration."""
    configuration = read_json_object(Path(root) / 'pi-kit.json', missing={})
    defaults = configuration.get('defaults', {})
    if not isinstance(defaults, dict):
        raise ValueError('pi-kit.json defaults must contain an object')
    return defaults


def normalize_model_choice(choice: dict, role: str, *, require_key=False) -> dict:
    """Validate one role without changing model IDs containing slashes."""
    if not isinstance(choice, dict):
        raise ValueError(f'{role} must contain a model choice')
    source = choice.get('source')
    if source == 'opencode':
        raise ValueError(f'{role} uses an OpenCode connection. Select a Pi model or configure its API explicitly.')
    if source == 'lmstudio' and role == 'executors':
        instance = choice.get('instance')
        if instance is not None and (not isinstance(instance, str) or not instance.strip()):
            raise ValueError('executors.instance must be a non-empty instance ID')
        return {'source': source, 'instance': instance.strip() if instance else None}
    if source not in ('pi', 'api'):
        raise ValueError(f'{role} must select a Pi model or own API')
    model = choice.get('model', '')
    if not isinstance(model, str) or not model.strip():
        raise ValueError(f'Select an exact model ID for {role}')
    model = model.strip()
    if any(character.isspace() for character in model):
        raise ValueError(f'Select an exact model ID for {role}')
    if source == 'pi':
        provider, separator, model_id = model.partition('/')
        if not separator or not provider or not model_id:
            raise ValueError(f'{role} model must use provider/model')
        return {'source': 'pi', 'model': model}
    from .configurator.workflow import api_address
    base_url = api_address(str(choice.get('baseURL', '')))
    key_environment_name = choice.get('keyEnv', '')
    if not isinstance(key_environment_name, str) or not ENVIRONMENT_NAME.fullmatch(key_environment_name):
        raise ValueError(f'{role}.keyEnv must name an environment variable')
    api = choice.get('api', 'openai-completions')
    if api not in ('openai-completions', 'openai-responses', 'anthropic-messages', 'google-generative-ai'):
        raise ValueError(f'{role}.api is not a supported Pi API protocol')
    if require_key:
        from .configurator.workflow import existing_key
        key_value = existing_key(key_environment_name)
        if not key_value:
            raise ValueError(f'Save the API key in variable {key_environment_name} before preparing {role}')
        os.environ[key_environment_name] = key_value
    return {'source': 'api', 'baseURL': base_url, 'model': model,
            'keyEnv': key_environment_name, 'api': api}


def load_choices(root: Path) -> dict:
    """Merge explicit Pi project defaults with local choices and validate the result."""
    root = Path(root)
    defaults = load_project_defaults(root)
    saved_choices = read_json_object(root / CHOICES_PATH, missing={})
    choices = {'masterChief': None, 'executors': {'source': 'lmstudio', 'instance': None}, 'bugFixer': None}
    for role in ROLE_SETTINGS:
        choice = saved_choices.get(role, defaults.get(role))
        if choice is not None:
            choices[role] = normalize_model_choice(choice, role)
    choices['execution'] = normalize_policy(saved_choices.get('execution', defaults.get('execution')))
    return choices


def locate_pi_command(root: Path) -> list[str]:
    """Prefer the pinned project package and an existing Node executable."""
    explicit_command = os.environ.get('PI_KIT_COMMAND')
    if explicit_command:
        executable = shutil.which(explicit_command)
        if not executable and Path(explicit_command).is_file():
            executable = str(Path(explicit_command).resolve())
        if executable and Path(executable).suffix.lower() not in ('.cmd', '.bat'):
            return [executable]
        raise ValueError('PI_KIT_COMMAND must point to an installed native Pi executable')
    runtime_root = Path(root).resolve()
    visited_runtime_directories = set()
    while runtime_root not in visited_runtime_directories:
        visited_runtime_directories.add(runtime_root)
        package_directory = runtime_root / '.tools/pi/node_modules' / PI_PACKAGE
        package_file = package_directory / 'package.json'
        if package_file.is_file():
            package = read_json_object(package_file)
            if package.get('version') != PI_VERSION:
                raise ValueError(f'This kit requires Pi {PI_VERSION}; reinstall the pinned project runtime')
            node = shutil.which('node')
            cli = package_directory / 'dist/bundle/cli.js'
            if node and cli.is_file():
                return [node, str(cli)]
        # Installed projects may share the template runtime on the same disk.
        installation = read_json_object(runtime_root / '.pi/installation.json', missing={})
        shared_runtime_root = installation.get('runtime_root')
        if not shared_runtime_root:
            break
        if not isinstance(shared_runtime_root, str) or not Path(shared_runtime_root).is_absolute():
            raise ValueError('Pi installation runtime_root must contain an absolute directory path')
        runtime_root = Path(shared_runtime_root).resolve()
    else:
        raise ValueError('Pi installation contains a circular runtime_root reference. Repair the project installation.')
    raise ValueError(f'Pi {PI_VERSION} was not found. Install the project runtime described in docs/user/PI_QUICKSTART.ru.md.')


def pi_process_environment(root: Path) -> dict[str, str]:
    """Refresh referenced API keys before starting an isolated Pi subprocess."""
    from .configurator.workflow import existing_key
    root = Path(root).resolve()
    environment = os.environ.copy()
    environment['PI_CODING_AGENT_DIR'] = str(root / AGENT_DIRECTORY)
    model_configuration = read_json_object(root / AGENT_DIRECTORY / 'models.json', missing={})
    providers = model_configuration.get('providers', {})
    if not isinstance(providers, dict):
        raise ValueError('Pi models.json providers must contain an object')
    for provider in providers.values():
        if not isinstance(provider, dict):
            continue
        api_key_reference = provider.get('apiKey')
        if not isinstance(api_key_reference, str):
            continue
        variable_reference = re.fullmatch(r'\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))', api_key_reference)
        if variable_reference is None:
            continue
        variable_name = variable_reference.group(1) or variable_reference.group(2)
        key_value = existing_key(variable_name)
        if key_value:
            environment[variable_name] = key_value
        else:
            environment.pop(variable_name, None)
    return environment


def list_available_pi_models(root: Path) -> list[str]:
    """Ask Pi for authenticated models through RPC without a generation request."""
    root = Path(root).resolve()
    environment = pi_process_environment(root)
    command = locate_pi_command(root) + ['--mode', 'rpc', '--no-session', '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-themes', '--no-mcp']
    process = subprocess.Popen(command, cwd=root, env=environment, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    responses = queue.Queue()
    def read_responses():
        for line in process.stdout:
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get('id') == 'kit-model-catalog':
                responses.put(response)
                return
        responses.put(None)
    reader = threading.Thread(target=read_responses, daemon=True)
    reader.start()
    try:
        process.stdin.write(json.dumps({'id': 'kit-model-catalog', 'type': 'get_available_models'}) + '\n')
        process.stdin.flush()
        try:
            response = responses.get(timeout=30)
        except queue.Empty as error:
            raise ValueError('Pi did not return its available model list within 30 seconds') from error
        if not response or not response.get('success'):
            raise ValueError('Pi could not read its available models. Check its installation and provider authentication.')
        models = response.get('data', {}).get('models', [])
        references = {model['provider'] + '/' + model['id'] for model in models
                      if isinstance(model, dict) and isinstance(model.get('provider'), str) and isinstance(model.get('id'), str)}
        return sorted(references)
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
        reader.join(timeout=1)


def role_model_reference(choice: dict, role: str) -> tuple[str, str]:
    """Resolve provider and model independently, splitting only the first slash."""
    if choice['source'] == 'pi':
        provider, model = choice['model'].split('/', 1)
        return provider, model
    provider = {'masterChief': 'kit-master-chief-api', 'executors': 'kit-executor-api',
                'bugFixer': 'kit-bug-fixer-api'}[role]
    if choice['source'] == 'lmstudio':
        return 'lmstudio', choice.get('instance') or 'loaded-executor'
    return provider, choice['model']


def resolve_role_model_references(root: Path, choices=None) -> dict:
    """Return prepared role references and reject settings saved after preparation."""
    choices = load_choices(root) if choices is None else choices
    runtime_path = Path(root) / RUNTIME_PATH
    prepared = read_json_object(runtime_path) if runtime_path.is_file() else None
    if prepared is not None and prepared.get('choices') != choices:
        raise ValueError('Model choices changed. Prepare Pi settings before continuing.')
    references = {}
    for role, (agent_name, _) in ROLE_SETTINGS.items():
        choice = choices.get(role)
        if not choice:
            continue
        provider, model = role_model_reference(choice, role)
        if prepared is not None:
            prepared_role = prepared.get('roles', {}).get(agent_name, {})
            if not prepared_role.get('enabled'):
                raise ValueError(f'Prepare the selected {role} before continuing')
            if choice['source'] != 'lmstudio' and (prepared_role.get('provider'), prepared_role.get('model')) != (provider, model):
                raise ValueError(f'Prepared Pi model does not match the saved {role} choice')
            provider, model = prepared_role['provider'], prepared_role['model']
        elif choice['source'] == 'lmstudio':
            raise ValueError('Prepare Pi settings to select an already loaded LM Studio instance')
        references[role] = provider + '/' + model
    return references


def write_json_atomically(path: Path, value: dict):
    """Replace one generated file after the complete JSON has been written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def prepare_pi_configuration(root: Path, explicit_instance=None):
    """Coordinate preparation with task controls before replacing runtime settings."""
    from .model_switch import preparation
    with preparation(Path(root)):
        return write_prepared_pi_configuration(root, explicit_instance)


def write_prepared_pi_configuration(root: Path, explicit_instance=None):
    """Prepare role prompts and providers, selecting only an already loaded instance.

    The model-switch coordinator owns locking and the active-task checks. Callers
    must enter its preparation context before changing a running project's config.
    """
    root = Path(root).resolve()
    choices = load_choices(root)
    if not choices['masterChief']:
        raise ValueError('Choose the Master Chief model in the Pi configurator before preparing the project')
    if explicit_instance and choices['executors']['source'] != 'lmstudio':
        raise ValueError('--model selects an LM Studio instance; choose LM Studio for the executors first')
    project_settings = read_json_object(root / 'pi-kit.json', missing={})
    lmstudio_base_url = project_settings.get('lmstudio', {}).get('baseURL', DEFAULT_BASE)
    selected_instance = None
    providers, runtime_roles = {}, {}
    for role, (agent_name, prompt_filename) in ROLE_SETTINGS.items():
        choice = choices.get(role)
        prompt_path = root / 'kit/prompts' / prompt_filename
        if prompt_path.is_symlink() or not prompt_path.is_file():
            raise ValueError(f'Role prompt must be a regular project file: {prompt_filename}')
        prompt = prompt_path.read_text(encoding='utf-8')
        if choice is None:
            runtime_roles[agent_name] = {'provider': '', 'model': '', 'system_prompt': prompt, 'enabled': False}
            continue
        choice = normalize_model_choice(choice, role, require_key=True)
        provider, model = role_model_reference(choice, role)
        if choice['source'] == 'lmstudio':
            selected_instance = select_model(loaded_models(lmstudio_base_url), explicit_model=explicit_instance or choice.get('instance'))
            model = selected_instance.id
            providers[provider] = {'baseUrl': lmstudio_base_url, 'api': 'openai-completions',
                                   'apiKey': 'lmstudio', 'models': [{'id': model, 'name': selected_instance.name}]}
        elif choice['source'] == 'api':
            providers[provider] = {'baseUrl': choice['baseURL'], 'api': choice['api'],
                                   'apiKey': '$' + choice['keyEnv'], 'models': [{'id': model}]}
        runtime_roles[agent_name] = {'provider': provider, 'model': model, 'system_prompt': prompt, 'enabled': True}
    fast_prompt = root / 'kit/prompts/executor-fast.md'
    if fast_prompt.is_symlink() or not fast_prompt.is_file():
        raise ValueError('Role prompt must be a regular project file: executor-fast.md')
    runtime_roles['executor-fast'] = {**runtime_roles['executor'], 'system_prompt': fast_prompt.read_text(encoding='utf-8')}
    agent_directory = root / AGENT_DIRECTORY
    runtime = {'format': 1, 'runtime': 'pi', 'roles': runtime_roles,
               'agent_directory': str(agent_directory), 'execution': choices['execution'], 'choices': choices}
    write_json_atomically(agent_directory / 'models.json', {'providers': providers})
    write_json_atomically(root / RUNTIME_PATH, runtime)
    return selected_instance
