"""Inspect leader controls without arming or submitting orders."""
from playwright.sync_api import sync_playwright


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge",headless=True)
        page = browser.new_page(viewport={"width":1440,"height":1100})
        page.goto("http://localhost:8502/?page=Live")
        page.get_by_role("heading",name="Trading Combine leader",exact=True).wait_for(timeout=30000)
        page.wait_for_timeout(2500)
        assert page.get_by_role("spinbutton",name="MNQ contracts",exact=True).input_value()=="3"
        assert page.get_by_role("spinbutton",name="MES contracts",exact=True).input_value()=="3"
        start = page.locator('[data-testid="stExpander"]').filter(has=page.get_by_text("Start leader trading",exact=True)).first
        start.locator("summary").click()
        assert page.get_by_role("button",name="Start leader trading").is_disabled()
        assert page.locator('[data-testid="stException"]').count()==0
        page.screenshot(path="data/leader-desktop.png")
        page.set_viewport_size({"width":390,"height":844})
        page.wait_for_timeout(800)
        assert page.evaluate("document.body.scrollWidth <= innerWidth")
        page.screenshot(path="data/leader-mobile.png")
        page.goto("http://localhost:8502/?page=Bot")
        page.get_by_role("combobox",name="Account view").wait_for(timeout=30000)
        page.get_by_role("combobox",name="Account view").click()
        page.get_by_role("option",name="Leader",exact=True).click()
        page.wait_for_timeout(1500)
        assert page.locator('[data-testid="stException"]').count()==0
        page.get_by_role("tab",name="Controls & review",exact=True).click()
        page.get_by_role("heading",name="Trading Combine leader",exact=True).wait_for()
        browser.close()
    print("Leader sizes, disabled start, account view and mobile checks passed. No execution controls pressed.")


if __name__ == "__main__":
    run()
