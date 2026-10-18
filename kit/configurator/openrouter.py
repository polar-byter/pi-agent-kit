"""Public OpenRouter catalog: exact model IDs, decimal prices, explicit coding evidence."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

API_URL = 'https://openrouter.ai/api/v1'
KEY_ENV = 'OPENROUTER_API_KEY'
CATALOG_URL = API_URL + '/models'
CACHE_PATH = Path('.metrics') / '.openrouter-catalog.json'
MILLION = Decimal(1_000_000)
CODE_WORDS = re.compile(r'\b(code|coder|coders|coding|programming|software engineering|software development|swe)\b', re.I)
MODEL_ID = re.compile(r'[^\s/]+(?:/[^\s/]+)+')


def price(value) -> Decimal | None:
    """Missing, dynamic (-1), non-finite or malformed amounts are unknown, never zero."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except InvalidOperation:
        return None


def money(value: Decimal | None, per_million=True) -> str:
    if value is None:
        return '—'
    amount = value * MILLION if per_million else value
    return '$' + format(amount, 'f').rstrip('0').rstrip('.') if '.' in format(amount, 'f') else '$' + str(amount)


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    description: str
    input_price: Decimal | None
    output_price: Decimal | None
    request_price: Decimal | None
    cache_read: Decimal | None
    cache_write: Decimal | None
    context: int | None
    tools: bool | None
    coding: str
    conditional: bool
    extra_cost: bool

    @property
    def tariff(self):
        if self.input_price is None or self.output_price is None or self.request_price is None:
            return 'Unknown'
        if self.conditional:
            return 'Conditional'
        if self.input_price == self.output_price == self.request_price == 0 and not self.extra_cost:
            return 'Free'
        return 'Paid'


def parse_models(payload: dict, programming_ids=frozenset()) -> list[Model]:
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        raise ValueError('Invalid model catalog')
    result, seen = [], set()
    for item in payload['data']:
        if not isinstance(item, dict):
            continue
        model_id = item.get('id')
        if (not isinstance(model_id, str) or len(model_id) > 300 or not MODEL_ID.fullmatch(model_id)
                or any(ord(character) < 32 for character in model_id) or model_id in seen):
            continue
        architecture = item.get('architecture')
        if (not isinstance(architecture, dict) or not isinstance(architecture.get('output_modalities'), list)
                or not isinstance(architecture.get('input_modalities'), list)
                or 'text' not in architecture['output_modalities'] or 'text' not in architecture['input_modalities']):
            continue
        seen.add(model_id)
        name = item.get('name') if isinstance(item.get('name'), str) else model_id
        description = item.get('description') if isinstance(item.get('description'), str) else ''
        name, description = ' '.join(name.split())[:300] or model_id, ' '.join(description.split())[:20000]
        pricing = item.get('pricing') if isinstance(item.get('pricing'), dict) else {}
        parameters = item.get('supported_parameters')
        context = item.get('context_length')
        evidence = ('OpenRouter picks' if model_id in programming_ids else
                    'Code in name/description' if CODE_WORDS.search(model_id + ' ' + name + ' ' + description) else '')
        result.append(Model(model_id, name, description, price(pricing.get('prompt')), price(pricing.get('completion')),
                            price(pricing.get('request', '0')), price(pricing.get('input_cache_read')),
                            price(pricing.get('input_cache_write')),
                            context if type(context) is int and context > 0 else None,
                            'tools' in parameters if isinstance(parameters, list) else None,
                            evidence, bool(pricing.get('overrides')),
                            any((price(pricing.get(field)) or Decimal(0)) > 0
                                for field in ('internal_reasoning', 'input_cache_write'))))
    if payload['data'] and not result:
        raise ValueError('No usable text models')
    return result


def select_models(models: list[Model], query='', scope='coding', tariff='all', tools_only=False, sort='price'):
    words = query.casefold().split()
    rows = [model for model in models
            if (scope != 'coding' or model.coding)
            and (not tools_only or model.tools is True)
            and (tariff == 'all' or (model.tariff == 'Free' if tariff == 'free' else model.tariff in ('Paid', 'Conditional')))
            and all(word in (model.id + ' ' + model.name + ' ' + model.description).casefold() for word in words)]
    if sort == 'name':
        key = lambda model: (model.name.casefold(), model.id)
    elif sort == 'context':
        key = lambda model: (model.context is None, -(model.context or 0), model.id)
    elif sort in ('input', 'output'):
        key = lambda model: ((model.input_price if sort == 'input' else model.output_price) is None,
                             (model.input_price if sort == 'input' else model.output_price) or Decimal(0), model.id)
    else:
        key = lambda model: (model.tariff != 'Free', model.input_price is None or model.output_price is None,
                             (model.input_price or Decimal(0)) + (model.output_price or Decimal(0)), model.id)
    return sorted(rows, key=key)


def request_catalog(url: str) -> dict:
    """Public GET, no credentials, bounded response; arbitrary provider output is data."""
    request = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'PiKit-Catalog/1'})
    with urlopen(request, timeout=20) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError('Catalog is too large')
    return json.loads(raw)


def fetch(root: Path) -> dict:
    """Full text catalog is authoritative. Optional programming query adds evidence only.

    Neither limit nor offset is sent: OpenRouter documents this as the complete list.
    Never silently label a paginated response as complete.
    """
    payload = request_catalog(CATALOG_URL)
    parse_models(payload)
    links = payload.get('links')
    if (isinstance(links, dict) and links.get('next')) or (type(payload.get('total_count')) is int and payload['total_count'] > len(payload['data'])):
        raise ValueError('Incomplete catalog')
    warning, programming_ids = '', []
    try:
        programming = request_catalog(CATALOG_URL + '?category=programming')
        programming_ids = [item['id'] for item in programming['data'] if isinstance(item, dict) and isinstance(item.get('id'), str)]
    except Exception:
        warning = 'Programming picks unavailable; For coding uses model names and descriptions.'
    snapshot = {'version': 1, 'fetched_at': time.time(), 'payload': payload,
                'programming_ids': programming_ids, 'warning': warning}
    path = Path(root) / CACHE_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)
    except OSError:
        snapshot['warning'] = (warning + ' Could not save the cache.').strip()
    return snapshot


def cached(root: Path) -> dict | None:
    path = Path(root) / CACHE_PATH
    try:
        if path.stat().st_size > 20 * 1024 * 1024:
            return None
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        fetched = snapshot['fetched_at']
        if (snapshot['version'] != 1 or not isinstance(snapshot['programming_ids'], list)
                or type(fetched) not in (int, float) or not 0 <= fetched <= time.time() + 300):
            return None
        parse_models(snapshot['payload'], set(snapshot['programming_ids']))
        return snapshot
    except (OSError, ValueError, KeyError, TypeError):
        return None


def is_openrouter(value: str) -> bool:
    try:
        parts = urlsplit(value.strip())
        return (parts.scheme == 'https' and parts.hostname == 'openrouter.ai' and parts.port in (None, 443)
                and parts.path.rstrip('/') == '/api/v1' and not parts.username
                and not parts.password and not parts.query and not parts.fragment)
    except ValueError:
        return False
