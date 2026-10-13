"""Take the README screenshots in demo mode (needs: pip install playwright; playwright install chromium).

    python demo/screenshots.py           # writes docs/screenshots/
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seed import fp, PASSWORD, REPO  # noqa: E402

OUT = os.path.join(REPO, "docs", "screenshots")
os.makedirs(OUT, exist_ok=True)
fp.app.config.update(TESTING=False)
from werkzeug.serving import make_server  # noqa: E402
server = make_server("127.0.0.1", 5077, fp.app, threaded=True)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = "http://fleetpilot.home:5077"

from playwright.sync_api import sync_playwright  # noqa: E402
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--host-resolver-rules=MAP fleetpilot.home 127.0.0.1"])
    for theme, size, suffix in [("dark", {"width": 1440, "height": 900}, ""), ("light", {"width": 1440, "height": 900}, "-light")]:
        page = browser.new_page(viewport=size, device_scale_factor=1)
        page.goto(BASE + "/")
        page.evaluate(f"localStorage.setItem('fp_theme', '{theme}')")
        page.fill("#username", "admin")
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        shots = [("/index", "home"), ("/routers", "routers"), ("/smart", "smart"),
                 ("/system/security", "security"), ("/users/accessibility", "accessibility")]
        if theme == "light":
            shots = [("/index", "home")]
        for path, name in shots:
            page.goto(BASE + path)
            page.wait_for_load_state("networkidle")
            time.sleep(0.6)
            page.screenshot(path=os.path.join(OUT, f"{name}{suffix}.png"))
        if theme == "dark":
            page.goto(BASE + "/routers/1")
            page.wait_for_load_state("networkidle")
            time.sleep(0.6)
            page.screenshot(path=os.path.join(OUT, "router-detail.png"))
            mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                      storage_state=page.context.storage_state())
            mobile.goto(BASE + "/index")
            mobile.wait_for_load_state("networkidle")
            time.sleep(0.6)
            mobile.screenshot(path=os.path.join(OUT, "mobile.png"))
            mobile.close()
        page.close()
    browser.close()
server.shutdown()
print("screenshots:", sorted(os.listdir(OUT)))
