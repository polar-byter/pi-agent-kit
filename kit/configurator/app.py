r"""Configurator entry point and shared, window-independent form helpers.

Run from the project root:
    kit\python.cmd -m kit.configurator.app

The active window lives in desktop.py. Keep the learned form conversion and
preparation helpers here so the launcher, workflow and tests share one contract.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  
    # Python built without Tkinter, or tests on other systems
    # replace it with a fake which does not need Tkinter.
    tk = ttk = None

from . import keys, models_choices_configurator, sources

# Values of the radio buttons; 
# they are also the keys of the form dictionary.
MASTER_CHIEF_DEFAULT, MASTER_CHIEF_PI, MASTER_CHIEF_API = 'default', 'pi', 'api'
EXEC_LMSTUDIO, EXEC_PI, EXEC_API = 'lmstudio', 'pi', 'api'

# Project root: kit/configurator/app.py ->we go 2 levels up.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#   Our form is a dictionary with these keys (these values are strings):
#   master_chief_source      MASTER_CHIEF_DEFAULT | MASTER_CHIEF_PI | MASTER_CHIEF_API
#   master_chief_model       model reference or model name
#   master_chief_url         API address (only for MASTER_CHIEF_API)
#   master_chief_key_env     name of the key variable (only for MASTER_CHIEF_API)
#   exec_source       EXEC_LMSTUDIO | EXEC_PI | EXEC_API
#   exec_instance     loaded instance ID or "" (only for EXEC_LMSTUDIO)
#   exec_model        model reference (EXEC_PI) or model name (EXEC_API)
#   exec_url, exec_key_env   (only for EXEC_API)
EMPTY_FORM = {
    'master_chief_source': MASTER_CHIEF_DEFAULT,
    'master_chief_model': '',
    'master_chief_url': '',
    'master_chief_key_env': keys.MASTER_CHIEF_KEY_ENV,
    'exec_source': EXEC_LMSTUDIO,
    'exec_instance': '',
    'exec_model': '',
    'exec_url': '',
    'exec_key_env': keys.EXECUTOR_KEY_ENV,
    'bug_fixer_source': 'disabled',
    'bug_fixer_model': '',
    'bug_fixer_url': '',
    'bug_fixer_key_env': keys.BUG_FIXER_KEY_ENV,
    'max_executors': '2',
    'max_steps': '24',
    'max_seconds': '600',
    'max_repeated_actions': '3',
    'fixer_max_steps': '32',
    'fixer_max_seconds': '600',
    'executor_max_attempts': '3',
    'fixer_max_attempts': '6',
    'max_attempts': '9',
}

# Step 7. Pure (independent from the window for our tests) Form -> choices (no window needed)
# so that we can unit-test the logic without the window. 
# The window only calls these functions.
def form_to_choices(form: dict) -> dict:   
    """Turn the values of the window fields into the content of the choice file.

    master_chief_source MASTER_CHIEF_DEFAULT -> no "masterChief" section;
    MASTER_CHIEF_PI -> models_choices_configurator.master_chief_from_pi(master_chief_model);
    MASTER_CHIEF_API -> models_choices_configurator.api_choice(master_chief_url, master_chief_model, master_chief_key_env).
    exec_source EXEC_LMSTUDIO -> models_choices_configurator.lmstudio_choice(exec_instance);
    EXEC_PI -> models_choices_configurator.executors_from_pi(exec_model);
    EXEC_API -> models_choices_configurator.api_choice(exec_url, exec_model, exec_key_env).
    Then models_choices_configurator.build_choices(master_chief, executors).

    Raises:
        ValueError: from the models_choices_configurator functions, or an unknown source value.
    """
    master_chief_source = form['master_chief_source']
    if master_chief_source == MASTER_CHIEF_DEFAULT:
        master_chief = None
    elif master_chief_source == MASTER_CHIEF_PI:
        master_chief = models_choices_configurator.master_chief_from_pi(form['master_chief_model'])
    elif master_chief_source == MASTER_CHIEF_API:
        master_chief = models_choices_configurator.api_choice(form['master_chief_url'], form['master_chief_model'], form['master_chief_key_env'])
    else:
        raise ValueError(f'unknown master_chief_source: {master_chief_source}')
    exec_source = form['exec_source']
    if exec_source == EXEC_LMSTUDIO:
        executors = models_choices_configurator.lmstudio_choice(form['exec_instance'])
    elif exec_source == EXEC_PI:
        executors = models_choices_configurator.executors_from_pi(form['exec_model'])
    elif exec_source == EXEC_API:
        executors = models_choices_configurator.api_choice(form['exec_url'], form['exec_model'], form['exec_key_env'])
    else:
        raise ValueError(f'unknown executor_source: {exec_source}')
    result = models_choices_configurator.build_choices(master_chief, executors)
    source = form.get('bug_fixer_source', 'disabled')
    if source == 'pi':
        result['bugFixer'] = models_choices_configurator.executors_from_pi(form['bug_fixer_model'])
    elif source == 'api':
        result['bugFixer'] = models_choices_configurator.api_choice(form['bug_fixer_url'], form['bug_fixer_model'], form['bug_fixer_key_env'])
    elif source != 'disabled':
        raise ValueError('Unknown bug fixer source')
    from ..execution_policy import normalize_policy
    values = {}
    for field, key, default in (('max_executors', 'maxExecutors', '2'), ('max_steps', 'maxSteps', '24'),
                                ('max_seconds', 'maxSeconds', '600'), ('max_repeated_actions', 'maxRepeatedActions', '3'),
                                ('fixer_max_steps', 'fixerMaxSteps', '32'), ('fixer_max_seconds', 'fixerMaxSeconds', '600'),
                                ('executor_max_attempts', 'executorMaxAttempts', '3'), ('fixer_max_attempts', 'fixerMaxAttempts', '6'),
                                ('max_attempts', 'maxAttempts', '9')):
        value = form.get(field, default)
        if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
            raise ValueError('Execution limits must be whole numbers')
        values[key] = int(value)
    policy = normalize_policy(values)
    if policy != normalize_policy():
        result['execution'] = policy
    return result


def choices_to_form(data: dict) -> dict:
    """The reverse: fill the form from a saved choice file, to show it when the window opens.
    Starts from a copy of EMPTY_FORM and overwrites the fields present in data.
    "masterChief" missing -> master_chief_source MASTER_CHIEF_DEFAULT; "executors" missing -> EXEC_LMSTUDIO.
    "instance" missing -> exec_instance "".
    """
    #result_form = {k: v for k, v in EMPTY_FORM.items()}
    result_form = dict(EMPTY_FORM)  # copy
    master_chief = data.get('masterChief')    
    if master_chief is not None:
        if master_chief['source'] == MASTER_CHIEF_PI:
            result_form['master_chief_source'] = MASTER_CHIEF_PI
            result_form['master_chief_model'] = master_chief['model']
        elif master_chief['source'] == MASTER_CHIEF_API:
            result_form['master_chief_source'] = MASTER_CHIEF_API
            result_form['master_chief_model'] = master_chief['model']
            result_form['master_chief_url'] = master_chief['baseURL']
            result_form['master_chief_key_env'] = master_chief['keyEnv']
    executors = data.get('executors')
    if executors is not None:
        if executors['source'] == EXEC_LMSTUDIO:
            result_form['exec_source'] = EXEC_LMSTUDIO
            result_form['exec_instance'] = executors.get('instance', '')
        elif executors['source'] == EXEC_PI:
            result_form['exec_source'] = EXEC_PI
            result_form['exec_model'] = executors['model']
        elif executors['source'] == EXEC_API:
            result_form['exec_source'] = EXEC_API
            result_form['exec_model'] = executors['model']
            result_form['exec_url'] = executors['baseURL']
            result_form['exec_key_env'] = executors['keyEnv']
       
    fixer = data.get('bugFixer')
    if fixer is not None:
        for field, key in (('source', 'source'), ('model', 'model'), ('url', 'baseURL'), ('key_env', 'keyEnv')):
            if key in fixer:
                result_form['bug_fixer_' + field] = fixer[key]
    from ..execution_policy import normalize_policy
    policy = normalize_policy(data.get('execution'))
    for field, key in (('max_executors', 'maxExecutors'), ('max_steps', 'maxSteps'), ('max_seconds', 'maxSeconds'),
                       ('max_repeated_actions', 'maxRepeatedActions'), ('fixer_max_steps', 'fixerMaxSteps'),
                       ('fixer_max_seconds', 'fixerMaxSeconds'), ('executor_max_attempts', 'executorMaxAttempts'),
                       ('fixer_max_attempts', 'fixerMaxAttempts'), ('max_attempts', 'maxAttempts')):
        result_form[field] = str(policy[key])
    return result_form
    


def apply_choices(root: Path = PROJECT_ROOT) -> tuple[int, str]:
    """Rebuild the Pi overlay from the saved choice: run
    "<python> kit/run_pi.py --prepare-only" in the project root.

    Returns:
        (exit code, combined stdout and stderr text) — the window shows the text.
    """
    root = Path(root)
    subprocess_args = [sys.executable, '-m', 'kit.run_pi', '--prepare-only']
    subprocess_kwargs = {
        'cwd': root,
        'capture_output': True,
        'text': True,
        'timeout': sources.TIMEOUT
    }
    subprocess_result = subprocess.run(subprocess_args, **subprocess_kwargs)
    return subprocess_result.returncode, subprocess_result.stdout + subprocess_result.stderr


def main() -> int:
    """Create the window and run the event loop until it is closed."""
    from .desktop import main as desktop_main
    return desktop_main()


if __name__ == '__main__':
    sys.exit(main())
