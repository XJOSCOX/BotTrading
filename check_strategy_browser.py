"""Read-only UI verification; never saves settings or arms execution."""
from playwright.sync_api import sync_playwright


if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge",headless=True)
        page = browser.new_page(viewport={"width":1440,"height":1100})
        page.goto("http://localhost:8502/?page=Bot")
        page.get_by_text("Strategy settings / shared monitor",exact=True).click(timeout=30000)
        page.get_by_role("combobox",name="Opening range (minutes)").click()
        for value in ("5","15","30"):
            assert page.get_by_role("option",name=value,exact=True).count()==1
        page.keyboard.press("Escape")
        page.get_by_role("combobox",name="Stop & trailing candles (minutes)").click()
        for value in ("5","10","15"):
            assert page.get_by_role("option",name=value,exact=True).count()==1
        page.keyboard.press("Escape")
        page.get_by_text("Strategy settings / shared monitor",exact=True).click()
        for name in ("ORB","VWAP Reclaim","EMA Pullback"):
            page.get_by_text(name,exact=True).first.wait_for(timeout=30000)
        matrix = page.get_by_role("table",name="Strategy monitor")
        assert matrix.count()==1
        assert matrix.locator("tbody tr").count()==5
        assert matrix.locator("tbody td").count()==15
        assert matrix.bounding_box()["height"] < 650
        assert page.locator("section.gx-watch").count()==0
        page.wait_for_timeout(600)
        assert page.locator('[data-testid="stException"]').count()==0
        page.screenshot(path="data/strategies-desktop.png",full_page=True)
        page.set_viewport_size({"width":390,"height":844})
        page.wait_for_timeout(1000)
        assert page.evaluate("document.body.scrollWidth <= innerWidth")
        page.screenshot(path="data/strategies-mobile.png",full_page=True)
        browser.close()
    print("Five-strategy monitor, ORB options and mobile layout verified. No execution controls pressed.")
