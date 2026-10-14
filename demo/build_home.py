"""Build the project homepage for GitHub Pages (the site root).

    python demo/build_home.py [OUT]       # default OUT: demo/site

Writes index.html (demo/home), the screenshots from docs/screenshots and the
shared assets. The live demo (demo/build_live.py) goes to OUT/demo/ and the
static tour (demo/build_site.py) to OUT/tour/; this script leaves them alone.
"""
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.join(REPO, "demo", "home")
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(REPO, "demo", "site")

# Until October 2026 the live demo lived at the site root and registered a service
# worker there. This replacement removes that registration from returning visitors.
RETIRED_SW = """// The live demo moved to demo/. This worker only removes the old root registration.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.registration.unregister()));
"""


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
