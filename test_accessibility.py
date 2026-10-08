"""Accessibility regression tests: settings, page structure, easy language, template hygiene."""
import glob
import re

import pytest

import app as fp
import easy_language
import user_management

PAGES = ['/index', '/hosts', '/scanner', '/dashboard', '/smart', '/storage/workspace', '/disks', '/fans',
         '/vm', '/storage', '/backup', '/shutdown_schedule', '/checkmk', '/hw', '/hw_overview',
         '/email_settings', '/update_settings', '/system/backups', '/users', '/users/profile',
         '/users/accessibility', '/2fa', '/plugins', '/users/security', '/system/security',
         '/system/notifications', '/system/audit', '/reauth?next=/index']


@pytest.fixture
def client():
    fp.app.config['TESTING'] = True
    user_management.init_user_db()
    user = user_management.get_user('a11y_admin')
    uid = user['id'] if user else user_management.create_user('a11y_admin', 'a11y-admin-password', None, ['admin'])
    user_management.save_accessibility(uid, {})
    with fp.app.test_client() as c:
        with c.session_transaction() as s:
            s['user_id'] = uid
            s['username'] = 'a11y_admin'
            s['pw_tag'] = fp._password_tag(user_management.get_user_by_id(uid))
            s['sid'] = __import__('account_security').create_session(uid, '127.0.0.1', 'pytest')
            s['auth_time'] = __import__('time').time()
        c.uid = uid
        yield c


def test_every_page_has_one_h1_a_skip_link_and_a_main_landmark(client):
    for path in PAGES:
        html = client.get(path).get_data(as_text=True)
        assert len(re.findall(r'<h1\b', html)) == 1, path
        assert 'class="skip-link" href="#main"' in html, path
        assert '<main class="page-content" id="main"' in html, path
        assert 'aria-live="polite"' in html, path


def test_settings_are_saved_cleaned_and_applied(client):
    user_management.save_accessibility(client.uid, {'text_size': 'larger', 'contrast': 'high', 'motion': 'nope'})
    prefs = user_management.get_accessibility(client.uid)
    assert prefs['text_size'] == 'larger' and prefs['contrast'] == 'high' and prefs['motion'] == 'system'
    html = client.get('/index').get_data(as_text=True)
    assert 'data-text="larger"' in html and 'data-contrast="high"' in html


def test_easy_language_simplifies_menu_and_explains_pages(client):
    user_management.save_accessibility(client.uid, {'easy_language': 'on'})
    html = client.get('/hosts').get_data(as_text=True)
    assert 'My computers' in html and 'In simple words' in html
    with client.session_transaction() as s:
        s['lang'] = 'de'
    html = client.get('/smart').get_data(as_text=True)
    assert 'In Leichter Sprache' in html and 'Zustand der Festplatten' in html
    assert easy_language.page_help('/hw_overview', 'en').startswith('Here you see the parts')
    assert easy_language.page_help('/hw/setup', 'en').startswith('Here you test computers')


def test_templates_link_labels_and_name_icon_buttons():
    unnamed, unlinked = [], []
    for path in glob.glob('templates/**/*.html', recursive=True):
        src = re.sub(r'<script\b.*?</script>', '', open(path).read(), flags=re.S)
        for m in re.finditer(r'<label\b([^>]*)>(.*?)</label>', src, re.S):
            if 'for=' not in m.group(1) and not re.search(r'<(input|select|textarea)', m.group(2)):
                unlinked.append(path)
        for m in re.finditer(r'<(button|a)\b([^>]*)>((?:(?!</\1>).)*)</\1>', src, re.S):
            text = re.sub(r"\{\{\s*icon\([^)]*\)\s*\}\}|<[^>]+>|&#x[0-9A-Fa-f]+;|[\s✕×]", '', m.group(3))
            if not text and 'aria-label' not in m.group(2) and 'title=' not in m.group(2):
                unnamed.append(f"{path}: {m.group(0)[:60]}")
    assert not unlinked, unlinked
    assert not unnamed, unnamed
