"""Opt-in lifecycle-panel UI tests. Every service command is intercepted locally."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def run():
    output = Path("data/verification")
    output.mkdir(parents=True, exist_ok=True)
    commands, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        for width, height in ((1440,1000), (834,1112), (390,844), (320,740)):
            services = dict(market=dict(running=False), leader=dict(running=False))
            reject = [False]
            def route_api(route):
                path = route.request.url.split("/api/")[-1]
                result = {}
                if path == "session":
                    result = dict(csrf="test")
                elif path == "snapshot":
                    result = dict(profiles={}, prices={}, monitor=[], events=[], alerts=[])
                elif path == "services":
                    result = services
                elif path.startswith("services/"):
                    assert route.request.method == "POST"
                    commands.append(path)
                    if reject[0]:
                        route.fulfill(status=503, json=dict(detail="Broker exposure cannot be verified. Monitoring remains active."))
                        return
                    running = not path.endswith("/stop")
                    services.update(market=dict(running=running), leader=dict(running=running))
                    result = dict(message="Test command completed. Trading remains paused.", services=services)
                else:
                    assert route.request.method == "GET", "Unexpected mutation"
                route.fulfill(json=result)
            page = browser.new_page(viewport=dict(width=width, height=height))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/api/**", route_api)
            page.route_web_socket("**/api/stream", lambda _: None)
            page.goto("http://127.0.0.1:8504/#dashboard")
            page.get_by_role("button", name="System controls", exact=True).click()
            panel = page.get_by_role("dialog", name="System controls", exact=True)
            expect(panel).to_be_visible()
            expect(panel.locator(".service-state").nth(1)).to_contain_text("Stopped")
            for label in ("Start all", "Restart all", "Stop all"):
                panel.get_by_role("button", name=label, exact=True).click()
                expect(panel.get_by_role("button", name=label, exact=True)).to_be_enabled()
                expect(panel.get_by_role("status")).to_contain_text("Test command completed")
            reject[0] = True
            panel.get_by_role("button", name="Restart all", exact=True).click()
            expect(panel.get_by_role("alert")).to_contain_text("Broker exposure cannot be verified")
            bounds = panel.bounding_box()
            assert bounds["x"] >= 0 and bounds["x"]+bounds["width"] <= width+1
            assert page.evaluate("document.body.scrollWidth <= innerWidth")
            panel.screenshot(path=str(output/f"system-controls-{width}.png"))
            page.keyboard.press("Escape")
            expect(panel).to_have_count(0)
            page.get_by_role("button", name="System controls", exact=True).click()
            page.get_by_role("button", name="Close system controls", exact=True).click()
            expect(panel).to_have_count(0)
            page.close()
        browser.close()
    assert not errors, errors
    assert len(commands) == 16, commands
    print(dict(viewports=4, mocked_commands=len(commands), live_commands=0, page_errors=errors))


if __name__ == "__main__":
    run()
