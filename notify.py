"""
notify.py — push notifications to chat and phone services.

Channels are stored in DATA_DIR/notify_channels.json.  Webhook URLs often
contain the only secret needed to post (Discord, Slack, Gotify tokens), so
they are encrypted with SecretBox and never sent back to the browser.

Supported kinds: ntfy, gotify, discord, slack, and a generic JSON webhook.
Messages are sent from a background thread with a short timeout so a slow
service never holds up a page or a SMART scan.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import secret_box

logger = logging.getLogger(__name__)
_box = secret_box.SecretBox('sha256')
_lock = threading.Lock()

KINDS = {
    'ntfy': 'ntfy',
    'gotify': 'Gotify',
    'discord': 'Discord',
    'slack': 'Slack / Mattermost',
    'webhook': 'Generic JSON webhook',
}
EVENTS = {
    'smart': 'Disk health alerts',
    'security': 'Security events (lockouts, new admins, settings changes)',
    'backup': 'FleetPilot backups and restores',
}
LEVELS = ('info', 'warning', 'critical')
TIMEOUT = 6


def _path():
    data = os.environ.get('FLEETPILOT_DATA_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'))
    return os.path.join(data, 'notify_channels.json')


def _load():
    try:
        with open(_path()) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(channels):
    path = _path()
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(channels, fh, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def validate_url(url: str) -> str:
    url = (url or '').strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise ValueError('The address must start with http:// or https://')
    if parts.username or parts.password:
        raise ValueError('Put credentials in the token, not in the address.')
    return url


def _mask(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f'{parts.scheme}://{parts.hostname}{":%d" % parts.port if parts.port else ""}/…'


def list_channels():
    """Channels for display. URLs are reduced to scheme and host."""
    out = []
    for ch in _load():
        url = _box.decrypt(ch.get('url', ''))
        out.append({k: ch.get(k) for k in ('id', 'name', 'kind', 'events', 'enabled', 'min_level',
                                           'last_status', 'last_sent')} | {'url_hint': _mask(url) if url else ''})
    return out


def add_channel(name, kind, url, events, min_level='warning'):
    if kind not in KINDS:
        raise ValueError('Unknown channel type')
    name = (name or '').strip()[:64] or KINDS[kind]
    url = validate_url(url)
    events = [e for e in events if e in EVENTS] or list(EVENTS)
    if min_level not in LEVELS:
        min_level = 'warning'
    channel = {'id': secrets.token_hex(6), 'name': name, 'kind': kind, 'url': _box.encrypt(url),
               'events': events, 'enabled': True, 'min_level': min_level, 'last_status': '', 'last_sent': None}
    with _lock:
        channels = _load()
        if len(channels) >= 20:
            raise ValueError('FleetPilot supports up to 20 channels.')
        channels.append(channel)
        _save(channels)
    return channel['id']


def update_channel(channel_id, **changes):
    with _lock:
        channels = _load()
        for ch in channels:
            if ch.get('id') == channel_id:
                if 'enabled' in changes:
                    ch['enabled'] = bool(changes['enabled'])
                if 'events' in changes:
                    ch['events'] = [e for e in changes['events'] if e in EVENTS]
                if changes.get('min_level') in LEVELS:
                    ch['min_level'] = changes['min_level']
                _save(channels)
                return True
    return False


def delete_channel(channel_id):
    with _lock:
        channels = _load()
        kept = [c for c in channels if c.get('id') != channel_id]
        if len(kept) == len(channels):
            return False
        _save(kept)
    return True


def build_request(kind, url, title, message, level, event):
    """Return (url, body bytes, headers) for one channel type."""
    headers = {'User-Agent': 'FleetPilot-Notify/1'}
    if kind == 'ntfy':
        priority = {'info': '3', 'warning': '4', 'critical': '5'}[level]
        # HTTP headers must be latin-1; ntfy accepts RFC 2047 for anything else.
        safe_title = title.encode('latin-1', 'replace').decode('latin-1')
        headers.update({'Title': safe_title, 'Priority': priority, 'Tags': f'fleetpilot,{event}',
                        'Content-Type': 'text/plain; charset=utf-8'})
        return url, message.encode(), headers
    headers['Content-Type'] = 'application/json'
    if kind == 'gotify':
        payload = {'title': title, 'message': message, 'priority': {'info': 2, 'warning': 5, 'critical': 8}[level]}
    elif kind == 'discord':
        payload = {'content': f'**{title}**\n{message}'[:1900], 'allowed_mentions': {'parse': []}}
    elif kind == 'slack':
        payload = {'text': f'*{title}*\n{message}'}
    else:
        payload = {'source': 'fleetpilot', 'event': event, 'level': level, 'title': title,
                   'message': message, 'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    return url, json.dumps(payload).encode(), headers


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _deliver(channel, title, message, level, event):
    url = _box.decrypt(channel.get('url', ''))
    try:
        target, body, headers = build_request(channel['kind'], url, title, message, level, event)
        req = urllib.request.Request(target, data=body, headers=headers, method='POST')
        with _opener.open(req, timeout=TIMEOUT) as resp:
            status = f'OK ({resp.status})'
        ok = True
    except urllib.error.HTTPError as exc:
        status, ok = f'HTTP {exc.code}', False
    except Exception as exc:  # network errors, bad URLs
        status, ok = type(exc).__name__, False
    if not ok:
        logger.warning('[notify] %s channel %r failed: %s', channel.get('kind'), channel.get('name'), status)
    with _lock:
        channels = _load()
        for ch in channels:
            if ch.get('id') == channel.get('id'):
                ch['last_status'], ch['last_sent'] = status, time.time()
        _save(channels)
    return ok, status


def send(event, title, message, level='warning', wait=False, only=None):
    """Send to every enabled channel subscribed to ``event`` at or above ``level``.

    ``only`` restricts delivery to one channel id (used by the test button).
    With ``wait`` the call blocks and returns [(name, ok, status)].
    """
    if level not in LEVELS:
        level = 'warning'
    rank = LEVELS.index(level)
    targets = [c for c in _load() if (only and c.get('id') == only) or
               (not only and c.get('enabled') and event in c.get('events', [])
                and rank >= LEVELS.index(c.get('min_level', 'warning')))]
    if not targets:
        return []
    if wait:
        return [(c['name'], *_deliver(c, title, message, level, event)) for c in targets]
    for c in targets:
        threading.Thread(target=_deliver, args=(c, title, message, level, event), daemon=True).start()
    return []
