"""Opt-in 3D dashboard checks with browser-only fixtures; no broker requests."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import json
from PIL import Image
from playwright.sync_api import sync_playwright, expect


def run():
    output = Path("data/verification")
    output.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    trades = [dict(account_id=42, closed_at=(now-timedelta(hours=30-i)).isoformat(),
                   symbol=("MNQ", "MES", "MYM")[i % 3], strategy=("CRT", "ORB", "EMA Pullback")[i % 3],
                   net=value, costs=2.44, quantity=2, direction="LONG" if i % 2 else "SHORT")
              for i, value in enumerate((85, -35, 110, 62, -48, 95, -27, 140, 36, -70, 88, 125))]
    snapshot = dict(profiles=dict(practice=dict(target=dict(id=42), settings=dict(enabled=False),
                    trades=trades, jobs=[], broker={}, gate={})), prices={}, monitor=[], alerts=[], events=[],
                    session=dict(name="Test session", time=now.isoformat()))
    requests, errors = [], []
    def route_api(route):
        requests.append(route.request.method)
        assert route.request.method == "GET", "Dashboard must never mutate accounts"
        path = route.request.url.split("/api/")[-1]
        result = snapshot if path == "snapshot" else dict(csrf="test") if path == "session" else {}
        route.fulfill(json=result)

    def pixel_check(canvas):
        picture = Image.open(BytesIO(canvas.screenshot())).convert("RGB")
        colors = picture.getcolors(picture.width * picture.height)
        assert colors is not None and len(colors) > 40, "Blank WebGL canvas"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True, args=["--enable-unsafe-swiftshader"])
        for width, height in ((2560,1440), (1440,1000), (1280,900), (834,1112), (390,844), (320,740)):
            page = browser.new_page(viewport=dict(width=width, height=height))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/api/**", route_api)
            page.route_web_socket("**/api/stream", lambda _: None)
            page.goto("http://127.0.0.1:8504/#dashboard")
            expect(page.locator('.equity-canvas[data-ready="true"]')).to_be_visible(timeout=20000)
            canvas = page.locator(".equity-canvas canvas")
            pixel_check(canvas)
            assert page.evaluate("document.body.scrollWidth <= innerWidth"), width
            expect(page.locator(".metric-band .metric").first).to_contain_text("$561.00")
            page.get_by_role("slider", name="Inspect closed trade").fill("0")
            expect(page.locator(".equity-caption")).to_contain_text("$85.00")
            initial = canvas.screenshot()
            page.get_by_role("button", name="Rotate chart", exact=True).click()
            page.wait_for_timeout(550)
            assert initial != canvas.screenshot(), "Rotation must change chart pixels"
            page.get_by_role("button", name="Pause rotation").click()
            page.get_by_role("button", name="Reset chart view").click()
            canvas.scroll_into_view_if_needed()
            bounds = canvas.bounding_box()
            before_drag = canvas.screenshot()
            page.mouse.move(bounds["x"]+bounds["width"]*.6, bounds["y"]+bounds["height"]*.6)
            page.mouse.down()
            page.mouse.move(bounds["x"]+bounds["width"]*.4, bounds["y"]+bounds["height"]*.5, steps=8)
            page.mouse.up()
            page.wait_for_timeout(150)
            assert before_drag != canvas.screenshot(), "Dragging must orbit the camera"
            canvas.focus()
            page.keyboard.press("Home")
            old_height = canvas.bounding_box()["height"]
            page.get_by_role("button", name="Expand chart height").click()
            page.wait_for_timeout(100)
            assert canvas.bounding_box()["height"] > old_height + 100
            page.get_by_role("button", name="Reduce chart height").click()
            canvas.scroll_into_view_if_needed()
            page.wait_for_timeout(150)
            pixel_check(canvas)
            canvas.screenshot(path=str(output / f"dashboard-3d-canvas-{width}.png"))
            page.screenshot(path=str(output / f"dashboard-3d-{width}.png"), full_page=True)
            page.get_by_role("button", name="Today", exact=True).click()
            expect(page.get_by_role("button", name="Today", exact=True)).to_have_attribute("aria-pressed", "true")
            page.get_by_role("combobox", name="History scope").select_option("All saved accounts")
            page.close()
        # Negative equity must remain framed, rather than disappearing below the grid.
        snapshot["profiles"]["practice"]["trades"] = [dict(trades[0], net=-100)]
        page = browser.new_page(viewport=dict(width=390, height=844))
        page.route("**/api/**", route_api)
        page.route_web_socket("**/api/stream", lambda _: None)
        page.goto("http://127.0.0.1:8504/#dashboard")
        expect(page.locator('.equity-canvas[data-ready="true"]')).to_be_visible()
        canvas = page.locator(".equity-canvas canvas")
        pixel_check(canvas)
        canvas.screenshot(path=str(output / "dashboard-3d-negative.png"))
        expect(page.locator(".metric-band .metric").first).to_contain_text("-$100.00")
        # An idle chart must stop drawing to the GPU.
        page.wait_for_timeout(700)
        frames = canvas.get_attribute("data-frames")
        page.wait_for_timeout(200)
        assert frames == canvas.get_attribute("data-frames")
        page.close()
        # Empty data stays empty, and unavailable WebGL retains the real 2D view.
        snapshot["profiles"]["practice"]["trades"] = []
        page = browser.new_page(viewport=dict(width=1440, height=1000), reduced_motion="reduce")
        page.route("**/api/**", route_api)
        page.route_web_socket("**/api/stream", lambda _: None)
        page.goto("http://127.0.0.1:8504/#dashboard")
        expect(page.locator('.equity-canvas[data-ready="true"]')).to_be_visible()
        expect(page.get_by_text("No realized equity curve yet", exact=True)).to_be_visible()
        expect(page.locator(".metric-band .metric").first).to_contain_text("$0.00")
        pixel_check(page.locator(".equity-canvas canvas"))
        page.locator(".equity-canvas canvas").evaluate("canvas => canvas.dispatchEvent(new Event('webglcontextlost', {cancelable:true}))")
        expect(page.locator(".equity-fallback")).to_be_visible()
        page.close()
        assert not errors, errors
        assert set(requests) == {"GET"}
        browser.close()
    print(json.dumps(dict(viewports=6, nonblank_canvases=True, rotation=True, resize=True,
                          filters=True, empty_state=True, webgl_fallback=True, mutations=0, errors=errors)))


if __name__ == "__main__":
    run()
