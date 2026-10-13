"""Values placed inside <script> must be JSON (|tojson), never HTML-escaped: '&#34;' there is a syntax error
that silently breaks every button on the page."""
import re
import time
from html.parser import HTMLParser

import account_security
import app as fp
import user_management

PAGES = ["/index", "/hosts", "/scanner", "/routers", "/dashboard", "/hw_overview", "/hw", "/smart",
         "/storage/workspace", "/fans", "/vm", "/storage", "/backup", "/shutdown_schedule", "/checkmk",
         "/monitor", "/update_settings", "/email_settings", "/system/proxy", "/system/production",
         "/system/security", "/system/notifications", "/system/audit", "/system/backups", "/plugins",
         "/users/profile", "/users/security", "/users/accessibility", "/users", "/fleetpilot_update",
         "/server_update"]
# An escaped quote where a JavaScript value begins, as in confirm(&#34;... : the signature of
# |tojson|forceescape or plain {{ }} output inside a script. HTML built in JS strings may contain entities.


class _Scripts(HTMLParser):
    """Collect the raw text of every <script> element, as the browser sees it."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts, self._inside = [], False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._inside = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._inside = False

    def handle_data(self, data):
        if self._inside:
            self.scripts[-1] += data


def _scripts(html):
    parser = _Scripts()
    parser.feed(html)
    return parser.scripts


ENTITY = re.compile(r"(?:[(=,:]|\breturn)\s*&(#34|#39|quot|apos);")


def test_no_html_entities_inside_scripts():
    fp.app.config.update(TESTING=True)
    user = user_management.get_user("script_admin")
    uid = user["id"] if user else user_management.create_user("script_admin", "script-test-passphrase", None, ["admin"])
    client = fp.app.test_client()
    with client.session_transaction() as s:
        s.update(user_id=uid, username="script_admin", pw_tag=fp._password_tag(user_management.get_user_by_id(uid)),
                 sid=account_security.create_session(uid), auth_time=time.time())
    broken = []
    for path in PAGES:
        html = client.get(path).get_data(as_text=True)
        for script in _scripts(html):
            for m in ENTITY.finditer(script):
                broken.append(f"{path}: …{script[max(0, m.start() - 40):m.end() + 20]}…")
    assert not broken, "\n".join(broken[:10])
