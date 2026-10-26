# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Focused checks for production-hardening additions; does not contact or modify hosts."""
from pathlib import Path
import tempfile
from flask import Flask

import audit_log
import fleetpilot_version
import ui_icons
import production_runtime

ROOT = Path(__file__).resolve().parent.parent


def test_runtime_defaults():
    app = Flask(__name__)
    state = production_runtime.configure_app(app)
    assert app.config['SESSION_COOKIE_HTTPONLY'] is True
    assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
    assert state['session_minutes'] >= 15


def test_templates_render():
    app = Flask(__name__, template_folder=str(ROOT / 'templates'))
    app.secret_key = 'test'
    app.jinja_env.globals.update(_=lambda value: value)
    ui_icons.register(app)
    base = {
        'request': type('Req', (), {'path': '/storage/workspace'})(),
        'current_lang': 'en', 'current_theme': 'dark',
        'is_admin': True, 'is_operator': True,
        'current_user': type('User', (), {'username': 'tester', 'is_authenticated': True})(),
        'csrf_token': lambda: '',
        'fleetpilot_release': fleetpilot_version.release_metadata(),
    }
    with app.test_request_context('/storage/workspace'):
        storage = app.jinja_env.get_template('storage_workspace.html').render(
            disks=[{'device': 'sdb', 'model': 'Test disk', 'size': '1 TB', 'usage': None}],
            tasks=[], storage_endpoints=[], smart_summary={}, can_operate=True, **base
        )
        production = app.jinja_env.get_template('production_status.html').render(
            production={'production': False, 'cookie_secure': False, 'trust_proxy': False,
                        'csrf_enabled': False, 'secret_key_configured': True},
            audit_health={'events': 0, 'latest': None}, **base
        )
    import app as fp
    from flask import render_template
    with fp.app.test_request_context('/system/audit'):
        audit = render_template('system_audit.html', events=[], matching=0, filters={}, event_types=[],
                                retention=365, audit_health={'events': 0, 'latest': None})
    assert 'Storage Workspace' in storage
    assert 'Audit Trail' in audit
    assert 'Production Status' in production


def test_release_metadata():
    release = fleetpilot_version.release_metadata()
    # scripts/release.py sets the version; tests/test_release_script.py checks it matches Android and the changelog.
    assert release['version'] == fleetpilot_version.VERSION
    assert release['tag'] == f'v{fleetpilot_version.VERSION}'
    assert release['display_name'] == f'FleetPilot v{fleetpilot_version.VERSION}'


def test_audit_log():
    original = audit_log.DB_PATH
    with tempfile.TemporaryDirectory() as temp:
        audit_log.DB_PATH = Path(temp) / 'audit.db'
        audit_log.init_db()
        audit_log.record_event(actor_id=1, actor='tester', event_type='http.post', target='test', outcome='success')
        events = list(audit_log.list_events())
        assert len(events) == 1
        assert events[0]['actor'] == 'tester'
    audit_log.DB_PATH = original


def test_app_startup_uses_logging_not_print():
    import ast
    import logging
    import app as fp

    assert isinstance(fp.logger, logging.Logger)
    source = (ROOT / 'app.py').read_text(encoding='utf-8')
    assert 'print(' not in source
    tree = ast.parse(source)
    print_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'print'
    ]
    assert print_calls == []


if __name__ == '__main__':
    test_runtime_defaults()
    test_templates_render()
    test_release_metadata()
    test_audit_log()
    test_app_startup_uses_logging_not_print()
    print('production hardening tests: OK')
