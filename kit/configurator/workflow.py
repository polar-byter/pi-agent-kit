"""Validation and key handling for the desktop form, independent of Tk."""
from __future__ import annotations

import os
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from . import app, keys, models_choices_configurator

ROLES = ('master_chief', 'exec', 'bug_fixer')
ROLE_NAMES = {'master_chief': 'Master Chief', 'exec': 'Executors', 'bug_fixer': 'Bug Fixer'}


class FormError(ValueError):
    """An actionable error associated with one role and one form field."""

    def __init__(self, role: str, field: str, message: str):
        super().__init__(message)
        self.role = role
        self.field = field


def api_address(value: str) -> str:
    """Validate a base URL without silently guessing the provider's route."""
    value = value.strip().rstrip('/')
    try:
        parts = urlsplit(value)
        parts.port  # Validate malformed or out-of-range port numbers.
        valid = (parts.scheme in ('http', 'https') and parts.hostname
                 and not parts.username and not parts.password
                 and '?' not in value and '#' not in value
                 and not any(character.isspace() or ord(character) < 32 for character in value))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Enter an API base URL, for example https://api.example.com/v1. Do not include a key, login, or query parameters.')
    value = parts.scheme + value[value.index(':'):]
    if parts.path.rstrip('/').endswith(('/chat/completions', '/completions', '/models', '/responses')):
        raise ValueError('Enter the API base URL without /chat/completions, /responses, or /models.')
    return value


def existing_key(name: str) -> str:
    """Read the persisted Windows key even if the process environment is stale."""
    if not keys.is_valid_env_name(name):
        return ''
    saved = keys.read_user_variable(name)
    if isinstance(saved, str) and saved.strip():
        return saved.strip()
    return os.environ.get(name, '').strip()


def connection(form: dict, role: str, typed_key: str) -> tuple[str, str]:
    """Validate API connection fields without requiring a model for GET /models."""
    try:
        url = api_address(form[role + '_url'])
    except ValueError as error:
        raise FormError(role, 'url', str(error)) from None
    name = form[role + '_key_env'].strip()
    if not keys.is_valid_env_name(name):
        raise FormError(role, 'key_env', 'In Advanced, enter a variable name using Latin letters, digits, and _. Start with a letter or _.')
    key = typed_key.strip() or existing_key(name)
    if not key:
        raise FormError(role, 'key', 'Paste an API key. If a key is already saved, check its variable name in Advanced.')
    if any(character in key for character in '\r\n\x00'):
        raise FormError(role, 'key', 'The API key must be a single line.')
    return url, key


def validate(form: dict, typed_keys: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """Validate both roles before any writes; return choices and only active typed keys.

    Existing JSON contracts remain unchanged. Conflicting keys sharing one environment
    variable are rejected before writing either the choice file or the Windows registry.
    """
    cleaned = {name: str(value).strip() for name, value in form.items()}
    to_save, supplied = {}, {}
    for role in ROLES:
        if cleaned[role + '_source'] == 'api':
            name, typed = cleaned[role + '_key_env'], typed_keys.get(role, '').strip()
            if typed:
                if name in supplied and supplied[name] != typed:
                    raise FormError(role, 'key_env', 'The roles have different keys but the same variable name. Use different variable names in Advanced.')
                supplied[name] = typed
    for role in ROLES:
        source = cleaned[role + '_source']
        allowed = (('default', 'pi', 'api') if role == 'master_chief' else
                   ('disabled', 'pi', 'api') if role == 'bug_fixer' else ('lmstudio', 'pi', 'api'))
        if source not in allowed:
            raise FormError(role, 'source', 'Choose a model connection type.')
        if source in ('api', 'pi'):
            model = cleaned[role + '_model']
            if not model:
                raise FormError(role, 'model', 'Select a model or enter its exact ID.')
            if source == 'pi':
                try:
                    models_choices_configurator.master_chief_from_pi(model)
                except ValueError:
                    raise FormError(role, 'model', 'Pi requires the full provider/model ID.') from None
        if source == 'api':
            typed = typed_keys.get(role, '').strip()
            url, key = connection(cleaned, role, typed or supplied.get(cleaned[role + '_key_env'], ''))
            cleaned[role + '_url'] = url
            name = cleaned[role + '_key_env']
            if typed:
                to_save[name] = typed
    try:
        choices = app.form_to_choices(cleaned)
    except ValueError as error:
        raise FormError('exec', 'limits', 'Enter valid whole-number limits: workers 1–8, steps 1–256, seconds 1–3600, repeats 2–32, role failures 1–100, total failures 1–200.') from None
    return choices, to_save


def save(root, form: dict, typed_keys: dict[str, str]):
    """Persist a validated choice, never keys in JSON; return path and parsed choices."""
    choices, to_save = validate(form, typed_keys)
    for name, value in to_save.items():
        keys.save_user_variable(name, value)
    path = models_choices_configurator.save_choices(root, choices)
    return path, choices


def prepare(root, choices: dict) -> tuple[int, str]:
    """Make saved keys available to the explicit preparation child process."""
    for choice in choices.values():
        if choice.get('source') == 'api':
            name = choice['keyEnv']
            value = existing_key(name)
            if value:
                os.environ[name] = value
    return app.apply_choices(root)


def model_error(source: str, error: Exception) -> str:
    """Explain common discovery failures without echoing URLs, keys or server bodies."""
    if source == 'lmstudio':
        return 'LM Studio did not respond. Start its server and load a model in LM Studio.'
    if source == 'pi':
        return 'Could not fetch models. Check that Pi is installed and available.'
    reason = error
    for _ in range(6):
        if isinstance(reason, HTTPError):
            if reason.code in (401, 403):
                return 'Access denied. Check the API key and its permissions.'
            if reason.code == 404:
                return 'Model list not found. Check the base URL; you can enter a model ID manually.'
            if reason.code == 429:
                return 'Rate limited (429). Try again later; your entries remain in the form.'
            return 'The service returned an error. Check availability or enter a model ID manually.'
        if isinstance(reason, (TimeoutError, subprocess.TimeoutExpired)):
            return 'The service timed out. Check the connection or try again later.'
        if isinstance(reason, URLError):
            if isinstance(reason.reason, TimeoutError):
                return 'The service timed out. Check the connection or try again later.'
            return 'Could not connect. Check the API address, internet connection, and service availability.'
        if reason.__cause__ is None:
            break
        reason = reason.__cause__
    return 'The response is not an OpenAI-compatible model list. Check the address or enter a model ID manually.'
