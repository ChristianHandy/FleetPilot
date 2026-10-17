# SPDX-FileCopyrightText: Copyright the FleetPilot contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the project homepage for GitHub Pages (the site root).

    python demo/build_home.py [OUT]       # default OUT: demo/site

Writes index.html (demo/home), the screenshots from docs/screenshots and the
shared assets. With FLEETPILOT_GITHUB_STATS=1 (set by the Pages workflow) the
"Get involved" section shows live counts from the GitHub API (GH_TOKEN raises the
rate limit); otherwise, and if the API fails, it shows the same links without numbers. The live demo (demo/build_live.py) goes to OUT/demo/ and the
static tour (demo/build_site.py) to OUT/tour/; this script leaves them alone.
"""
import datetime
import html
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.join(REPO, "demo", "home")
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(REPO, "demo", "site")

# Until October 2026 the live demo lived at the site root and registered a service
# worker there. This replacement removes that registration from returning visitors.
RETIRED_SW = """// The live demo moved to demo/. This worker only removes the old root registration.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.registration.unregister()));
"""


SLUG = "ChristianHandy/FleetPilot"
GITHUB = f"https://github.com/{SLUG}"

# icon, label, link, how to count: ("search", query) | ("contributors",) | ("stars",)
STATS = (
    ("flag", "Good first issues", "labels/good%20first%20issue", ("search", 'is:issue is:open label:"good first issue"')),
    ("hand-thumbs-up", "Help wanted", "labels/help%20wanted", ("search", 'is:issue is:open label:"help wanted"')),
    ("translate", "Translation tasks", "labels/translation", ("search", "is:issue is:open label:translation")),
    ("record-circle", "Open issues", "issues", ("search", "is:issue is:open")),
    ("git", "Open pull requests", "pulls", ("search", "is:pr is:open")),
    ("people", "Contributors", "graphs/contributors", ("contributors",)),
    ("star", "Stars", "stargazers", ("stars",)),
)


def _api(path):
    request = urllib.request.Request(f"https://api.github.com{path}", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "fleetpilot-homepage"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response), response.headers.get("Link", "")


def _count(kind):
    if kind[0] == "search":
        query = urllib.parse.quote(f"repo:{SLUG} {kind[1]}")
        return int(_api(f"/search/issues?q={query}&per_page=1")[0]["total_count"])
    if kind[0] == "stars":
        return int(_api(f"/repos/{SLUG}")[0]["stargazers_count"])
    # Contributors: one per page, so the number of the last page is the count.
    data, link = _api(f"/repos/{SLUG}/contributors?per_page=1")
    last = re.search(r'[?&]page=(\d+)>; rel="last"', link)
    return int(last.group(1)) if last else len(data)


def github_stats_html(fetch=None):
    """The stat cards; ``fetch`` (kind -> int) is None when no numbers are wanted."""
    numbers = {}
    if fetch:
        try:
            numbers = {label: fetch(kind) for _icon, label, _link, kind in STATS}
        except Exception as exc:   # the site must build without the API
            print(f"homepage: GitHub numbers unavailable ({type(exc).__name__}: {exc}); showing links only")
            numbers = {}
    items = []
    for icon, label, link, _kind in STATS:
        number = f'<span class="stat-num">{numbers[label]:,}</span>' if label in numbers else ""
        items.append(f'        <li><a class="stat" href="{GITHUB}/{link}"><i class="bi bi-{icon}" aria-hidden="true"></i>'
                     f'{number}<span class="stat-label">{html.escape(label)}</span></a></li>')
    out = '      <ul class="stats">\n' + "\n".join(items) + "\n      </ul>"
    if numbers:
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%-d %B %Y")
        out += f'\n      <p class="center muted stats-date">Numbers from GitHub, updated daily (last: {day}).</p>'
    return out


def main():
    sys.path.insert(0, REPO)
    import fleetpilot_version
    os.makedirs(OUT, exist_ok=True)
    for name in ("index.html", "home.css", "home.js"):
        target = os.path.join(OUT, name)
        if os.path.exists(target):
            os.remove(target)
    with open(os.path.join(HOME, "index.html"), encoding="utf-8") as fh:
        page = fh.read().replace("{{VERSION}}", fleetpilot_version.TAG)
    wanted = os.environ.get("FLEETPILOT_GITHUB_STATS") == "1"
    page = page.replace("{{GITHUB_STATS}}", github_stats_html(_count if wanted else None))
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    for name in ("home.css", "home.js"):
        shutil.copy(os.path.join(HOME, name), OUT)

    assets = os.path.join(OUT, "assets")
    shutil.rmtree(assets, ignore_errors=True)
    shutil.copytree(os.path.join(REPO, "static", "vendor", "bootstrap-icons"), os.path.join(assets, "bootstrap-icons"))
    shutil.copy(os.path.join(REPO, "static", "fleetpilot-logo.svg"), assets)
    shutil.copytree(os.path.join(REPO, "docs", "screenshots"), os.path.join(assets, "screens"))

    with open(os.path.join(OUT, "sw.js"), "w") as fh:
        fh.write(RETIRED_SW)
    with open(os.path.join(OUT, "sitemap.xml"), "w") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                 + "".join(f"  <url><loc>https://christianhandy.github.io/FleetPilot/{p}</loc></url>\n"
                           for p in ("", "demo/", "tour/"))
                 + "</urlset>\n")
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    print(f"homepage: {OUT}")


if __name__ == "__main__":
    main()
