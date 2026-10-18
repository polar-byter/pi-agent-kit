"""Translate public Pi transcript entries into the kit's message contract."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json


def timestamp_milliseconds(value, fallback=0):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)
        except ValueError:
            pass
    return fallback


def normalize_session_export(session, entries):
    messages = []
    tool_results = {}
    for entry in entries:
        message = entry.get('message', {}) if isinstance(entry, dict) else {}
        if message.get('role') == 'toolResult':
            tool_results[message.get('toolCallId')] = message
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get('message'), dict):
            continue
        message = entry['message']
        if message.get('role') not in ('user', 'assistant'):
            continue
        created = timestamp_milliseconds(message.get('timestamp'), timestamp_milliseconds(entry.get('timestamp')))
        identifier = entry.get('id') or hashlib.sha256(json.dumps(message, sort_keys=True).encode()).hexdigest()[:24]
        completed = timestamp_milliseconds(entry.get('timestamp'), created)
        info = dict(id='msg_' + str(identifier), role=message['role'], sessionID=session['id'],
                    time=dict(created=created, completed=max(created, completed)))
        if message['role'] == 'assistant':
            usage = message.get('usage') or {}
            provider_identifier = message.get('provider', session.get('model', {}).get('providerID'))
            reported_cost = (usage.get('cost') or {}).get('total')
            # Custom API definitions have no price catalog. Pi's default zero
            # describes missing pricing rather than a free remote request.
            if provider_identifier in ('kit-master-chief-api', 'kit-executor-api', 'kit-bug-fixer-api'):
                reported_cost = None
            info.update(providerID=message.get('provider', session.get('model', {}).get('providerID')),
                        modelID=message.get('model', session.get('model', {}).get('id')),
                        tokens=dict(input=usage.get('input'), output=usage.get('output'), reasoning=None,
                                    cache=dict(read=usage.get('cacheRead'), write=usage.get('cacheWrite'))),
                        cost=reported_cost, finish=message.get('stopReason'))
            if message.get('errorMessage'):
                # Provider failures are useful to the quota watcher, but raw headers are not.
                raw_error = str(message['errorMessage'])
                limited = any(word in raw_error.lower() for word in ('429', 'rate limit', 'quota', 'too many requests'))
                info['error'] = dict(name='RateLimitError' if limited else 'ProviderError',
                                     data=dict(message='429 provider rate limit' if limited else 'Pi provider request failed'))
            if message.get('stopReason') == 'aborted':
                info['error'] = dict(type='aborted', message='Pi execution was interrupted')
        parts = []
        content = message.get('content', [])
        if isinstance(content, str):
            content = [dict(type='text', text=content)]
        for part_index, part in enumerate(content):
            if not isinstance(part, dict):
                continue
            if part.get('type') == 'text':
                parts.append(dict(type='text', text=part.get('text', '')))
            if part.get('type') == 'toolCall':
                result = tool_results.get(part.get('id'))
                public_result = [item.get('text', '') for item in (result or {}).get('content', [])
                                 if isinstance(item, dict) and item.get('type') == 'text']
                parts.append(dict(type='tool', id=part.get('id'), callID=part.get('id'), tool=part.get('name'),
                    state=dict(status=('error' if result.get('isError') else 'completed') if result else 'running',
                               input=part.get('arguments', {}), output='\n'.join(public_result),
                               time=dict(start=created, end=timestamp_milliseconds((result or {}).get('timestamp'), created)))))
        messages.append(dict(info=info, parts=parts))
    return dict(info=dict(id=session['id'], parentID=session.get('parentID'), title=session.get('title', ''),
                         location=dict(directory=session['project']), agent=session.get('agent'),
                         model=session.get('model')), messages=messages)
