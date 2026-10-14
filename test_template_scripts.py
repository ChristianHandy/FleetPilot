# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
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


# Expressions that may appear unencoded inside an inline <script>: JSON, numbers, booleans,
# fixed translations, URLs and tokens FleetPilot generates itself. Anything else (a host,
# device or fan name, a token from storage) must go through |tojson.
_SAFE_IN_SCRIPT = re.compile(
    r"""^\s*(?:
        .*\|\s*tojson\s*                        # JSON-encoded
      | _\((?:'[^']*'|"[^"]*")\)                # fixed translation
      | url_for\(.*\) | csrf_token\(\)          # generated URL, CSRF token
      | icon\(.*\)                              # inline SVG icon from ui_icons
      | [\w.]+\.id                              # numeric database id
      | \w+\s*\|\s*length                       # a count
      | '(?:true|false)'\s+if\s+\w+\s+else\s+'(?:true|false)'
      | current_theme\|default\("dark"\)        # 'light' or 'dark', validated in set_theme
    )\s*$""", re.X)


def test_inline_scripts_only_contain_encoded_values():
    import glob
    unsafe = []
    for path in sorted(glob.glob("templates/**/*.html", recursive=True)):
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        for script in re.finditer(r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script\b[^>]*>", source, re.S | re.I):
            for expr in re.finditer(r"\{\{(.*?)\}\}", script.group(1), re.S):
                if not _SAFE_IN_SCRIPT.match(expr.group(1)):
                    unsafe.append(f"{path}: {{{{{expr.group(1)}}}}}")
    assert not unsafe, "Use |tojson for values inside <script>:\n" + "\n".join(unsafe)
