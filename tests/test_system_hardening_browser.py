"""Opt-in headless stream fault injection; temporary DB and no account writes."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from urllib.parse import urlsplit
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect
from goxtrade.api import app, state
from goxtrade.data import live_store
from tests.test_native_browser import fixture


def run():
    base = f"http://127.0.0.1:{app.PORT}"
    with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
        stack.enter_context(patch.object(live_store, "DB_PATH", Path(folder)/"browser.db"))
        stack.enter_context(patch.object(state, "CACHE", state.SnapshotCache()))
        for operation in ("post", "login"):
            stack.enter_context(patch("goxtrade.execution.projectx_client."+operation, side_effect=AssertionError("Broker forbidden")))
        stack.enter_context(patch("goxtrade.runtime.live_process.status", return_value=dict(running=False, pid=None)))
        client = stack.enter_context(TestClient(app.create_app(), base_url=base))
        def route_api(route):
            assert route.request.method == "GET", "No mutations allowed"
            url = urlsplit(route.request.url)
            response = client.get(url.path+("?"+url.query if url.query else ""))
            route.fulfill(status=response.status_code, body=response.content, content_type=response.headers.get("content-type", "application/json"))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            output = Path("data/verification")
            output.mkdir(parents=True, exist_ok=True)
            navigation_ms = []
            for width, height in ((2560, 1440), (1440, 1000), (1280, 900), (834, 1112), (390, 844), (320, 740)):
                page = browser.new_page(viewport=dict(width=width, height=height))
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/api/**", route_api)
                page.route("**/api/chart?*", lambda route: route.fulfill(json=dict(points=fixture())))
                page.route_web_socket("**/api/stream", lambda _: None)
                page.goto(base)
                for name in ("Dashboard", "Charts", "Strategies", "Control Center", "Execution", "Research", "Accounts", "Connection"):
                    began = time.perf_counter()
                    if width <= 650:
                        page.get_by_role("button", name="Open navigation").click()
                    page.locator('nav[aria-label="Main navigation"]').get_by_role("link", name=name, exact=True).click()
                    expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()
                    navigation_ms.append(round(1000*(time.perf_counter()-began), 2))
                    assert page.evaluate("document.body.scrollWidth<=innerWidth"), (width, name)
                    if name == "Charts":
                        canvas = page.locator("canvas").first
                        expect(canvas).to_be_visible()
                        page.wait_for_timeout(150)
                        assert canvas.evaluate("c=>{const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;const s=new Set();for(let i=0;i<d.length;i+=16)s.add(`${d[i]},${d[i+1]},${d[i+2]}`);return s.size>20}")
                    if name in ("Dashboard", "Charts", "Execution"):
                        page.screenshot(path=str(output/f"phase7-native-{width}-{name.lower()}.png"), full_page=True)
                assert not errors, errors
                page.close()
            page = browser.new_page(viewport=dict(width=1440, height=1000))
            sockets, errors, documents = [], [], []
            page.route("**/api/**", route_api)
            page.route_web_socket("**/api/stream", lambda socket: sockets.append(socket))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: documents.append(request.url) if request.resource_type == "document" else None)
            page.goto(base)
            status = page.locator(".connection-status")
            expect(status).to_contain_text("Live interface")
            recoveries = []
            for malformed in ("private invalid JSON", "null", '{"data":[]}', '{"data":null}'):
                count = len(sockets)
                began = time.perf_counter()
                sockets[-1].send(malformed)
                expect(status).to_contain_text("Reconnecting")
                deadline = time.monotonic()+10
                while len(sockets) == count and time.monotonic()<deadline:
                    page.wait_for_timeout(50)
                assert len(sockets) == count+1
                expect(status).to_contain_text("Live interface")
                recoveries.append(round(1000*(time.perf_counter()-began), 2))
            sockets[-1].send(json.dumps(dict(data=dict(prices={}, research_revision="fixture"))))
            page.wait_for_timeout(100)
            assert len(documents) == 1, "Recovery must not reload the document"
            assert not errors, errors
            assert "private invalid JSON" not in page.locator("body").inner_text()
            print(json.dumps(dict(viewports=6, pages_per_viewport=8, nonblank_chart=True, navigation_ms=navigation_ms,
                                  stream_faults=4, document_loads=1, page_errors=errors, recovery_ms=recoveries, broker_writes=0)))
            browser.close()


if __name__ == "__main__":
    run()
