"""This part of the module Build, validate, read and write the file .pi/kit-models.json.

The file format is a contract with kit/pi_configuration.py:
    {
      "masterChief":     {"source": "pi", "model": "provider/model"}
                   or {"source": "api", "baseURL": ..., "model": ..., "keyEnv": ...},
      "executors": {"source": "lmstudio"} or {"source": "lmstudio", "instance": ...}
                   or {"source": "api", "baseURL": ..., "model": ..., "keyEnv": ...}
    }

- A missing section means "use the default". 
- A missing file means "use the defaults".

"""
from __future__ import annotations
import json 
from pathlib import Path
import re


# location where the choice file is put, relative to the project root.
CHOICES_PATH = Path('.pi') / 'kit-models.json'

# A valid environment variable name: a letter or "_", then letters, digits or "_".
ENV_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
MODEL_REF_PATTERN_FOR_CHECK_ = re.compile(r'^[^/\s]+(/[^/\s]+)+$')

# Step 1. Dictionaries.

def master_chief_from_pi(model: str) -> dict:
    """the Master Chief uses a model that Pi already knows.
    Args:
        model: reference like "openai/gpt-6.1-sol" or "openrouter/author/model".
    Returns:
        {"source": "pi", "model": <model without surrounding spaces>}
    Raises:
        ValueError: the model is empty or has no "/" (a provider name is required).
    """
    model = model.strip()
    if not model:
        raise ValueError('the model is empty')
    
    if not MODEL_REF_PATTERN_FOR_CHECK_.fullmatch(model):
        raise ValueError('the model is not in the format "provider/model"')
    result_dict = {"source": "pi", "model": model}
    return result_dict

def executors_from_pi(model: str) -> dict:
    """Choice "the executors use a model that Pi already knows", for example a free
    OpenRouter model authenticated in Pi with /login.

    The rules are the same as for the Master Chief, so the check is shared.
    Returns:
        {"source": "pi", "model": <model without surrounding spaces>}
    Raises:
        ValueError: the model is empty or has no "/".
    """
    return master_chief_from_pi(model)


def api_choice(base_url: str, model: str, key_env: str) -> dict:
    """use an own OpenAI-compatible API.
    Args:
        base_url: endpoint like "https://api.example.com/v1".
        model: model name at that service.
        key_env: name of the environment variable with the key, not the key itself.

    Returns:
        {"source": "api", "baseURL": <url without trailing "/">,
         "model": <model>, "keyEnv": <key_env>}; all values without surrounding spaces.

    Raises:
        ValueError: an empty value; the URL does not start with http:// or https://;
                    key_env is not a valid variable name (see ENV_NAME).
    """
    base_url, model, key_env = base_url.strip(), model.strip(), key_env.strip()
    if not all((base_url, model, key_env)):
        raise ValueError('one of the values is empty')
 
    base_url = base_url.rstrip('/')
    
    if not base_url.startswith(('http://', 'https://')):
        raise ValueError('the base URL must start with http:// or https://')
    
    if ENV_NAME.fullmatch(key_env) is None:
        raise ValueError('the key environment variable name is not valid')
    
    return {"source": "api", "baseURL": base_url, "model": model, "keyEnv": key_env}


def lmstudio_choice(instance: str | None = None) -> dict:
    """executors use the model already loaded in LM Studio.
    Args:
        instance: ID of a loaded instance, or None to let the launcher pick
                  the only loaded model. An empty or blank string counts as None.
    Returns:
        {"source": "lmstudio"} when there is no instance,
        {"source": "lmstudio", "instance": <instance>} otherwise.
    """
    instance = instance.strip() if instance is not None else None
  
    if not instance:
        return {"source": "lmstudio"}
    return {"source": "lmstudio", "instance": instance}


def build_choices(master_chief: dict | None, executors: dict | None) -> dict:
    """Complex part of the both sections that combines them into the content of the choice file.
    A section that is None is left out: the launcher, we created before, will consider it as a default.

    Returns:
        dict with keys "masterChief" and/or "executors"; {} when both are None.
    """
    result = {}
    if master_chief is not None:
        result["masterChief"] = master_chief
    if executors is not None:
        result["executors"] = executors
    return result

# Step 2. The file on a disk.
def load_choices(root: Path) -> dict:
    """Read the choice file of the project.
    Args:
        root: project root folder.
    Returns:
        The dictionary from the file, or {} when the file does not exist.

    Raises:
        ValueError: the file is not valid JSON or does not contain a JSON object.
    """
    root = Path(root)
    path = root / CHOICES_PATH
    if not path.exists():
        return {}

    try:
        text = path.read_text(encoding='utf-8')
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"the file {path} is not valid JSON: {error}") from error

    if not isinstance(data, dict):
        raise ValueError(f"the file {path} does not contain a JSON object")

    return data


def save_choices(root: Path, choices: dict) -> Path:
    """Write the choice file safely and return its path.

    Writes to a temporary file next to the target first and then replaces the target.
    If the program crashes in the middle, the old file stays whole.
    Creates the .pi folder when it is missing. JSON is indented by 2 spaces,
    UTF-8, non-ASCII characters are kept as is, and the file ends with a newline.
    """
    root = Path(root)
    path = root / CHOICES_PATH
    folder = path.parent
    folder.mkdir(parents=True, exist_ok=True)
    temporary_to_protect_target = path.with_name(path.name + '.tmp')
    temporary_to_protect_target.write_text(json.dumps(choices, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary_to_protect_target.replace(path)
      
    return path


def reset_choices(root: Path) -> bool:
    """Delete the choice file to return to the defaults.

    Returns:
        True when the file existed and was deleted, False when there was nothing to delete.
    """
    root = Path(root)
    path = root / CHOICES_PATH
    if path.exists():
        path.unlink()
        return True
    return False
