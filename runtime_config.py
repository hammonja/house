"""Read private OpenAI configuration without executing .env contents."""
import os
import re
from pathlib import Path

CREDENTIAL_NAMES = ('OPENAI_API_KEY', 'OPENAI_PROJECT', 'OPENAI_ORG_ID')


def read_env_file(path):
    try:
        lines = Path(path).read_text(encoding='utf-8-sig').splitlines()
    except (OSError, ValueError):
        return {}
    values = {}
    for line in lines:
        match = re.fullmatch(r'\s*(?:export\s+)?([A-Z_][A-Z_0-9]*)\s*=\s*(.*?)\s*', line)
        if not match:
            continue
        name, value = match.groups()
        if value.startswith(('"', "'")):
            end = value.find(value[0], 1)
            if end < 0:
                continue
            value = value[1:end]
        else:
            value = value.split(' #', 1)[0].strip()
        values[name] = value
    return values


def load_openai_environment(root, environment=None):
    """Share credentials with sibling apps, but retain House's own model choice.

    Process environment wins over the local .env and the shared .env. Only
    credential fields are inherited from the shared file; nothing is logged.
    """
    environment = os.environ if environment is None else environment
    root = Path(root).resolve()
    local = read_env_file(root / '.env')
    shared_path = environment.get('OPENAI_ENV_FILE') or local.get('OPENAI_ENV_FILE')
    if shared_path:
        shared_path = Path(shared_path)
        if not shared_path.is_absolute():
            shared_path = root / shared_path
    else:
        shared_path = root.parent / 'tools' / '.env'
    shared = read_env_file(shared_path)
    for name in CREDENTIAL_NAMES:
        value = environment.get(name) or local.get(name) or shared.get(name)
        if value:
            environment[name] = value
    for name in ('HOUSE_OPENAI_MODEL', 'OPENAI_MODEL'):
        if not environment.get(name) and local.get(name):
            environment[name] = local[name]
    return environment
