"""Focused checks for production-hardening additions; does not contact or modify hosts."""
from pathlib import Path
import tempfile
from flask import Flask

import audit_log
import fleetpilot_version
import production_runtime

ROOT = Path(__file__).parent


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
        audit = app.jinja_env.get_template('system_audit.html').render(
            events=[], audit_health={'events': 0, 'latest': None}, **base
        )
        production = app.jinja_env.get_template('production_status.html').render(
            production={'production': False, 'cookie_secure': False, 'trust_proxy': False,
                        'csrf_enabled': False, 'secret_key_configured': True},
            audit_health={'events': 0, 'latest': None}, **base
        )
    assert 'Storage Workspace' in storage
    assert 'Audit Trail' in audit
    assert 'Production Status' in production


def test_release_metadata():
    release = fleetpilot_version.release_metadata()
    assert release['version'] == '1.1.0'
    assert release['tag'] == 'v1.1.0'
    assert release['display_name'] == 'FleetPilot v1.1.0'


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


if __name__ == '__main__':
    test_runtime_defaults()
    test_templates_render()
    test_release_metadata()
    test_audit_log()
    print('production hardening tests: OK')
