"""Headless visual checks; does not reopen the user's browser."""
from pathlib import Path
from playwright.sync_api import sync_playwright


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.goto("http://localhost:8502/?page=Bot")
        page.get_by_role("heading", name="Alert history", exact=True).wait_for(timeout=40000)
        page.locator(".gx-watch").first.wait_for()
        assert page.locator(".gx-watch").count() == 3
        assert page.locator(".gx-watch-strategy").count() == 6
        assert page.locator(".gx-history details").count() == 0
        assert page.locator(".gx-evidence").count() >= page.locator(".gx-history").count()
        assert page.get_by_text("Recent Candles", exact=True).count() == 0
        assert page.locator('[data-testid="stDataFrame"]:visible').count() == 0
        past = page.locator('[data-testid="stExpander"]').filter(has_text="Past alerts")
        assert not past.locator("details").evaluate("(el) => el.open")
        assert page.locator(".gx-outcomes").is_visible()
        page.screenshot(path="data/bot-monitor-desktop.png", full_page=True)
        past.locator("summary").click()
        page.wait_for_timeout(2200)
        assert past.locator("details").evaluate("(el) => el.open")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(1000)
        assert page.locator(".gx-watch").count() == 3
        cards = page.locator(".gx-history, .gx-watch")
        for index in range(cards.count()):
            assert cards.nth(index).evaluate("(el) => el.scrollWidth <= el.clientWidth + 1")
        page.screenshot(path="data/bot-monitor-mobile.png", full_page=True)
        browser.close()
    print("Six monitored pairs, alert layout, and mobile card overflow checks passed.")


if __name__ == "__main__":
    run()
