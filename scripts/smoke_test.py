# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Smoke test for a running FleetPilot: sign in and open every page the app links to.

    FP_SMOKE_PASSWORD=... python3 scripts/smoke_test.py --base https://127.0.0.1 --cafile cert.pem

Used by .github/workflows/smoke.yml after install.sh has installed the code under
test, but it works against any installation. Standard library only.

It checks /healthz, signs in, then follows the links on each page (same site only,
breadth first) and fails if a page answers with a server error (5xx), a link the app
shows is missing (404), or a request fails. Links that could change something
(delete, shutdown, update, …) are never opened, although FleetPilot only changes
things on POST.
"""
import argparse
import http.cookiejar
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from html.parser import HTMLParser

# Path parts of links that are not opened, to stay on the safe side.
UNSAFE = re.compile(r"logout|delete|remove|shutdown|reboot|poweroff|power|wake|wol|update|upgrade|install|"
                    r"restart|start|stop|apply|reset|run|scan|sync|export|download|backup_now|test_",
                    re.IGNORECASE)
SKIP_PREFIXES = ("/static/", "/healthz")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def _csrf_token(html):
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    return match.group(1) if match else ""


class Client:
    def __init__(self, base, cafile=None, timeout=30):
        self.base = base.rstrip("/")
        self.host = urllib.parse.urlsplit(self.base).netloc
        self.timeout = timeout
        context = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=context))

    def request(self, path, data=None):
        """Return (status, final path, body); HTTP errors are returned, not raised."""
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, headers={"Referer": self.base + "/"})
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                return resp.status, urllib.parse.urlsplit(resp.geturl()).path, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            return err.code, path, err.read().decode("utf-8", "replace")


def wait_until_healthy(client, seconds):
    deadline = time.monotonic() + seconds
    while True:
        try:
            status, _, body = client.request("/healthz")
            if status == 200 and json.loads(body).get("status") == "ok":
                return
        except (OSError, ValueError):
            pass
        if time.monotonic() > deadline:
            sys.exit(f"FAIL: {client.base}/healthz did not answer ok within {seconds} s")
        time.sleep(2)


def sign_in(client, username, password):
    """FleetPilot's sign-in form is the start page "/" (fields "user" and "pass")."""
    status, _, page = client.request("/")
    if status != 200 or 'name="pass"' not in page:
        sys.exit(f"FAIL: the sign-in page / answered {status} without a sign-in form")
    status, final, page = client.request("/", {"user": username, "pass": password,
                                               "csrf_token": _csrf_token(page)})
    if status >= 400 or 'name="pass"' in page:
        sys.exit(f"FAIL: signing in as {username} did not work (status {status}, ended on {final})")
    return final, page


def crawl(client, start_path, start_page, limit):
    """Breadth-first over the app's own links. Returns {path: status}."""
    seen = {start_path: 200}
    queue = deque([(start_path, start_page)])
    failures = []
    while queue:
        path, page = queue.popleft()
        parser = _Links()
        parser.feed(page)
        for href in parser.links:
            parts = urllib.parse.urlsplit(urllib.parse.urljoin(client.base + path, href))
            if parts.scheme not in ("http", "https") or parts.netloc != client.host:
                continue
            target = parts.path + (f"?{parts.query}" if parts.query else "")
            if (target in seen or len(seen) >= limit or parts.path.startswith(SKIP_PREFIXES)
                    or UNSAFE.search(parts.path)):
                continue
            try:
                status, final, body = client.request(target)
            except OSError as exc:
                seen[target] = "error"
                failures.append(f"{target}: {exc} (linked from {path})")
                continue
            seen[target] = status
            if status >= 500 or status == 404:
                failures.append(f"{target}: HTTP {status} (linked from {path})")
            elif status == 200:
                # After a redirect, links on the page are relative to where it ended.
                queue.append((target if final == parts.path else final, body))
    return seen, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="e.g. https://127.0.0.1 or http://127.0.0.1:5000")
    parser.add_argument("--cafile", help="certificate to trust for HTTPS (the self-signed one from install.sh)")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--limit", type=int, default=300, help="most pages to open")
    parser.add_argument("--wait", type=int, default=120, help="seconds to wait for /healthz")
    args = parser.parse_args()
    password = os.environ.get("FP_SMOKE_PASSWORD")
    if not password:
        sys.exit("Set FP_SMOKE_PASSWORD to the admin password.")

    client = Client(args.base, args.cafile)
    wait_until_healthy(client, args.wait)
    print("ok  /healthz")
    start_path, start_page = sign_in(client, args.user, password)
    print(f"ok  signed in as {args.user}")
    seen, failures = crawl(client, start_path, start_page, args.limit)
    for target, status in sorted(seen.items(), key=lambda item: item[0]):
        print(f"{status!s:>5}  {target}")
    print(f"\n{len(seen)} pages opened, {len(failures)} failed")
    if failures:
        print("\n".join(["", "Failures:"] + failures))
        sys.exit(1)


if __name__ == "__main__":
    main()
