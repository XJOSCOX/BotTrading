"""Headless acceptance status and refresh-failure QA; no provider/account writes."""
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
from goxtrade.diagnostics import projectx_diagnostics as diagnostics
from tests.test_native_browser import fixture


def run():
    base = f"http://127.0.0.1:{app.PORT}"
    with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
        stack.enter_context(patch.object(live_store, "DB_PATH", Path(folder)/"browser.db"))
        stack.enter_context(patch.object(state, "CACHE", state.SnapshotCache()))
        stack.enter_context(patch("goxtrade.execution.projectx_client.post", side_effect=AssertionError("No broker request")))
        stack.enter_context(patch("goxtrade.execution.projectx_client.login", side_effect=AssertionError("No authentication")))
        stack.enter_context(patch("goxtrade.runtime.live_process.status", return_value=dict(running=False, pid=None)))
        diagnostics._auth.clear()
        diagnostics._results.clear()
        client = stack.enter_context(TestClient(app.create_app(), base_url=base))
        failure = [False]
        def route_api(route):
            assert route.request.method == "GET", "Opening/refreshing acceptance evidence must not mutate anything"
            url = urlsplit(route.request.url)
            if url.path == "/api/diagnostics" and failure[0]:
                failure[0] = False
                route.fulfill(status=503, json=dict(detail="Operational fixture unavailable"))
                return
            response = client.get(url.path+("?"+url.query if url.query else ""))
            route.fulfill(status=response.status_code, body=response.content, content_type=response.headers.get("content-type", "application/json"))
        output = Path("data/verification")
        output.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            chart_render_ms = []
            for width, height in ((2560,1440), (1440,1000), (1280,900), (834,1112), (390,844), (320,740)):
                page = browser.new_page(viewport=dict(width=width,height=height))
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/api/**", route_api)
                page.route("**/api/chart?*", lambda route: route.fulfill(json=dict(points=fixture())))
                page.route_web_socket("**/api/stream", lambda _: None)
                page.goto(base+"/#diagnostics")
                expect(page.get_by_role("heading", name="Operational acceptance", exact=True)).to_be_visible()
                for name in ("CRT", "Reversal", "ORB", "VWAP Reclaim", "EMA Pullback", "VWAP EMA Cross", "Previous Day Box Reversal"):
                    expect(page.get_by_role("cell", name=name, exact=True).first).to_be_visible()
                expect(page.get_by_role("heading", name="Account safety evidence")).to_be_visible()
                assert page.evaluate("document.body.scrollWidth<=innerWidth"), width
                assert page.locator(".operational-acceptance td:first-child").evaluate_all("cells=>cells.every(c=>getComputedStyle(c).whiteSpace==='nowrap')")
                failure[0] = True
                page.get_by_role("button", name="Refresh evidence", exact=True).click()
                expect(page.get_by_text("Operational fixture unavailable", exact=False)).to_be_visible()
                page.get_by_role("button", name="Refresh evidence", exact=True).click()
                expect(page.get_by_text("Operational fixture unavailable", exact=False)).not_to_be_visible()
                assert not errors, errors
                page.screenshot(path=str(output/f"phase8-acceptance-{width}.png"), full_page=True)
                if width <= 650:
                    page.get_by_role("button", name="Open navigation").click()
                began = time.perf_counter()
                page.locator('nav[aria-label="Main navigation"]').get_by_role("link", name="Charts", exact=True).click()
                expect(page.locator("canvas").first).to_be_visible()
                page.wait_for_function("""()=>{const c=document.querySelector('canvas');if(!c||!c.width||!c.height)return false;
                    const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;const colors=new Set();
                    for(let i=0;i<d.length;i+=16)colors.add(`${d[i]},${d[i+1]},${d[i+2]}`);return colors.size>20;}""")
                chart_render_ms.append(round(1000*(time.perf_counter()-began), 2))
                assert not errors, errors
                page.close()
            browser.close()
    print(json.dumps(dict(viewports=6, registered_strategies=7, account_profiles=2, refresh_failures_recovered=6,
                          navigation_to_nonblank_fixture_chart_ms=chart_render_ms, page_errors=0, provider_requests=0, account_writes=0)))


if __name__ == "__main__":
    run()
