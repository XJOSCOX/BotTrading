"""Headless read-only UI checks; never presses execution controls."""
from playwright.sync_api import sync_playwright


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge",headless=True)
        page = browser.new_page(viewport={"width":1440,"height":1100})
        page.goto("http://localhost:8502/?page=Bot")
        page.get_by_role("tab",name="Controls & review",exact=True).wait_for(timeout=30000)
        for label in ("Controls & review","Replay lab","Notifications"):
            page.get_by_role("tab",name=label,exact=True).click()
            page.wait_for_timeout(1800)
            assert page.locator('[data-testid="stException"]').count()==0
            page.screenshot(path="data/bot-"+label.split()[0].lower()+"-desktop.png")
        page.get_by_role("tab",name="Replay lab",exact=True).click()
        page.get_by_role("button",name="Compare replay").click()
        page.get_by_role("button",name="Download replay").wait_for(timeout=60000)
        assert page.locator('[data-testid="stException"]').count()==0
        page.screenshot(path="data/bot-replay-result.png")
        page.set_viewport_size({"width":390,"height":844})
        for label in ("Controls & review","Replay lab","Notifications","Monitor"):
            page.get_by_role("tab",name=label,exact=True).click()
            page.wait_for_timeout(600)
            assert page.locator('[data-testid="stException"]').count()==0
            assert page.evaluate("document.body.scrollWidth <= innerWidth")
        page.screenshot(path="data/bot-workspace-mobile.png")
        browser.close()
    print("Four Bot tabs, saved replay, desktop/mobile checks passed; no execution controls pressed.")


if __name__ == "__main__":
    run()
