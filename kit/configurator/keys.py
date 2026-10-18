"""API keys in Windows user environment variables or a private POSIX user file.

The choice file stores only the NAME of a variable. The key itself is saved in the
user's environment (registry HKEY_CURRENT_USER\\Environment), like the command setx
does. New programs started after saving see the variable; already running ones
(an open terminal, VS Code) do not, so they must be restarted.

Why the file is called keys.py and not secrets.py: Python already has a standard
module "secrets", and a file with the same name can hide it.
POSIX storage uses posix_keys.py, outside projects, without editing shell profiles.
"""
from __future__ import annotations

import os
import re
import sys

try:
    import winreg  # exists only on Windows
except ImportError:  # tests on other systems replace it with a fake
    winreg = None

MASTER_CHIEF_KEY_ENV = 'PI_KIT_MASTER_CHIEF_API_KEY'
EXECUTOR_KEY_ENV = 'PI_KIT_EXECUTOR_API_KEY'
BUG_FIXER_KEY_ENV = 'PI_KIT_BUG_FIXER_API_KEY'
ENVIRONMENT_KEY = 'Environment'  # registry path under HKEY_CURRENT_USER

ENV_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


# Step 5. helpers

def is_valid_env_name(name: str) -> bool:
    """returns True if the name can be an environment variable name (see ENV_NAME condition)."""
    return bool(ENV_NAME.fullmatch(name))

def mask(value: str) -> str:
    """Show a key safely: first 4 and last 4 characters, the rest hidden.
    "sk-abcdefgh12345678" -> "sk-a…5678". Keys of 8 characters or shorter -> "••••".
    An empty key -> "".
    """
    result_string = ''
    if not value:
        return result_string
    if len(value) <= 8:
        result_string = 4 * '\u2022' 
    else:
        result_string = value[:4] + '\u2026' + value[-4:]
    return result_string


# Step 6. The registry of the OS

def read_user_variable(key_name: str) -> str | None:
    """Value of a user environment variable from the registry, or None if it is absent.
    Reads the registry, not os.environ: right after saving, this program's os.environ
    is already updated, but other programs only learn about the value from the registry.
    """
    if winreg is None:
        from . import posix_keys
        return posix_keys.read().get(key_name)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ENVIRONMENT_KEY) as key:
            value, _ = winreg.QueryValueEx(key, key_name)
            return value
    except (FileNotFoundError, OSError, PermissionError, TypeError) as error:
        return None



def save_user_variable(name: str, value: str) -> None:
    """Save a user environment variable, like "setx NAME VALUE".
    And puts the value into os.environ so this program and the programs it starts
    can see it. Then calls notify_windows().

    Raises:
        ValueError: name is not a valid variable name, or value is empty.
    """
    if not is_valid_env_name(name):
        raise ValueError("Invalid environment variable name")
    if not value:
        raise ValueError("Environment variable value cannot be empty")
    
    if winreg is None:
        from . import posix_keys
        posix_keys.save(name, value)
    else:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ENVIRONMENT_KEY, 0, winreg.KEY_SET_VALUE) as registry_key:
            winreg.SetValueEx(registry_key, name, 0, winreg.REG_SZ, value)
    os.environ[name] = value
    notify_windows()
    return None

def key_is_set(name: str) -> bool:
    """True if the variable is set in the registry or in os.environ.
       non-empty value 
    """
    return bool(os.environ.get(name))  or bool(read_user_variable(name))


# helper

def notify_windows() -> None:
    """Notify running Windows programs that the environment changed.

    Ready code, not a learning step: it calls the Windows API through ctypes.
    Programs that listen (Explorer, new terminals started from it) pick up the change.
    Raises:
        ImportError: if the platform is not Windows.
    """
    if sys.platform != 'win32':
        return
    import ctypes
    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_SETTINGCHANGE, 0, 'Environment',
        SMTO_ABORTIFHUNG, 5000, ctypes.byref(result))
