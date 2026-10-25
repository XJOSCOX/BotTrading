"""Opt-in UI-only checks against the disconnected local preview."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright


def run():
    base = os.environ.get("GOXTRADE_PREVIEW_URL", "http://127.0.0.1:8503")
    output = Path("data/verification")
    output.mkdir(parents=True, exist_ok=True)
    names = ["Dashboard", "Charts", "Strategies", "Control Center", "Execution", "Accounts", "Connection"]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        for width, height, device in ((1440, 1000, "desktop"), (390, 844, "mobile")):
            page = browser.new_page(viewport=dict(width=width, height=height))
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for name in names:
                page.goto(base+"/?page="+name.replace(" ", "%20"))
                page.get_by_role("heading", name=name, exact=True).wait_for(timeout=45000)
                page.wait_for_timeout(350)
                assert page.locator('[data-testid="stException"]').count() == 0, name
                assert page.evaluate("document.body.scrollWidth <= innerWidth"), (device, name)
                assert not errors, errors
                if name in ("Dashboard", "Control Center", "Accounts", "Connection", "Execution"):
                    page.screenshot(path=str(output/f"workspace-{device}-{name.lower().replace(' ', '-')}.png"), full_page=True)
            page.close()
        browser.close()
    print("All 7 workspaces render on desktop/mobile without page errors or horizontal overflow. No execution controls pressed.")


if __name__ == "__main__":
    run()
