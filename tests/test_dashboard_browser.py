"""Read-only flat dashboard checks using browser-only financial fixtures."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def run():
    now = datetime.now(timezone.utc)
    trades = [dict(account_id=42, closed_at=(now-timedelta(hours=30-i)).isoformat(),
                   symbol=("MNQ", "MES", "MYM")[i % 3], strategy=("CRT", "ORB", "EMA Pullback")[i % 3],
                   net=value, costs=2.44, quantity=2, direction="LONG" if i % 2 else "SHORT")
              for i, value in enumerate((85, -35, 110, 62, -48, 95, -27, 140, 36, -70, 88, 125))]
    snapshot = dict(profiles=dict(practice=dict(target=dict(id=42), settings=dict(enabled=False),
                    trades=trades, jobs=[], broker={}, gate={})), prices={}, monitor=[], alerts=[], events=[],
                    session=dict(name="Test session", time=now.isoformat()))
    errors, mutations, assets = [], [], []
    output = Path("data/verification")
    output.mkdir(parents=True, exist_ok=True)

    def route_api(route):
        assert route.request.method == "GET", "Dashboard must never mutate accounts"
        path = route.request.url.split("/api/")[-1]
        route.fulfill(json=snapshot if path == "snapshot" else dict(csrf="test") if path == "session" else {})

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        for width, height in ((2560,1440), (1440,1000), (834,1112), (390,844), (320,740)):
            page = browser.new_page(viewport=dict(width=width, height=height))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda r: mutations.append(r.url) if r.method != "GET" else assets.append(r.url))
            page.route("**/api/**", route_api)
            page.route_web_socket("**/api/stream", lambda _: None)
            page.goto("http://127.0.0.1:8504/#dashboard")
            chart = page.get_by_role("img", name="Realized closed-trade equity", exact=True)
            expect(chart).to_be_visible()
            expect(page.locator(".metric-band .metric").first).to_contain_text("$561.00")
            expect(page.locator(".dashboard canvas")).to_have_count(0)
            expect(page.get_by_role("button", name="Rotate chart", exact=True)).to_have_count(0)
            points = chart.locator("polyline").get_attribute("points").split()
            assert len(points) == len(trades)+1
            assert all(40 <= float(p.split(',')[0]) <= 760 and 30 <= float(p.split(',')[1]) <= 210 for p in points)
            assert page.evaluate("document.body.scrollWidth <= innerWidth"), width
            page.screenshot(path=str(output/f"dashboard-flat-{width}.png"), full_page=True)
            page.get_by_role("button", name="Today", exact=True).click()
            expect(page.get_by_role("button", name="Today", exact=True)).to_have_attribute("aria-pressed", "true")
            page.get_by_role("combobox", name="History scope").select_option("All saved accounts")
            page.close()
        for values in ([], [dict(trades[0], net=-100)]):
            snapshot["profiles"]["practice"]["trades"] = values
            page = browser.new_page(viewport=dict(width=390, height=844))
            page.route("**/api/**", route_api)
            page.route_web_socket("**/api/stream", lambda _: None)
            page.goto("http://127.0.0.1:8504/#dashboard")
            if values:
                expect(page.get_by_role("img", name="Realized closed-trade equity", exact=True)).to_be_visible()
                expect(page.locator(".metric-band .metric").first).to_contain_text("-$100.00")
            else:
                expect(page.get_by_text("No realized equity curve yet", exact=True)).to_be_visible()
                expect(page.locator(".equity-chart polyline")).to_have_count(0)
            page.close()
        assert not errors, errors
        assert not mutations, mutations
        assert not any("three.module" in url or "OrbitControls" in url for url in assets)
        browser.close()
    print("Flat dashboard: 5 viewports, real equity points, filters, negative/empty states; no WebGL assets, errors or mutations.")


if __name__ == "__main__":
    run()
