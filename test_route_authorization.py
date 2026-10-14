"""Every route needs a signed-in user, except a short list of public ones.

Routes are protected by decorators, not by one global check, so this test walks
the whole URL map (including add-on routes) and sends each method without a
session. A new route that forgets its decorator fails here.
"""
from urllib.parse import urlsplit

import pytest
from flask import url_for

import app as fp

# Endpoints anyone may reach, and why.
PUBLIC = {
    'login',             # the sign-in page
    'tfa_verify',        # second sign-in step; sends you back without a pending sign-in
    'logout',
    'healthz',           # liveness for load balancers and systemd
    'api_live',          # liveness for monitoring
    'public_status',     # /status: host and service names with their state, no addresses
    'set_language',      # stores a cookie preference
    'set_theme',
}


def _routes():
    for rule in sorted(fp.app.url_map.iter_rules(), key=str):
        if rule.endpoint == 'static' or rule.endpoint in PUBLIC:
            continue
        for method in sorted(rule.methods - {'HEAD', 'OPTIONS'}):
            yield pytest.param(rule, method, id=f'{method} {rule}')


def _sample_url(rule):
    values = {name: 1 if type(rule._converters.get(name)).__name__ == 'IntegerConverter' else 'x'
              for name in rule.arguments}
    with fp.app.test_request_context():
        return url_for(rule.endpoint, **values)


@pytest.fixture(scope='module')
def client():
    fp.app.config['TESTING'] = True
    csrf = fp.app.config.get('WTF_CSRF_ENABLED', True)
    fp.app.config['WTF_CSRF_ENABLED'] = False  # reach the access check, not the CSRF check
    with fp.app.test_client() as c:
        yield c
    fp.app.config['WTF_CSRF_ENABLED'] = csrf


@pytest.mark.parametrize('rule,method', list(_routes()))
def test_route_refuses_anonymous_requests(client, rule, method):
    response = client.open(_sample_url(rule), method=method)
    if response.status_code in (301, 302, 303, 307, 308):
        assert urlsplit(response.headers['Location']).path in ('/', '/login'), \
            f'{method} {rule} redirects an anonymous user to {response.headers["Location"]}, not to sign-in'
    else:
        assert response.status_code in (400, 401, 403, 404, 405), \
            f'{method} {rule} answered an anonymous request with {response.status_code}'


def test_public_endpoints_exist():
    endpoints = {rule.endpoint for rule in fp.app.url_map.iter_rules()}
    assert PUBLIC <= endpoints, f'stale entries in PUBLIC: {PUBLIC - endpoints}'
