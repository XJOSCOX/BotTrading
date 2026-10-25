"""Opt-in browser QA: real local API, temporary DB, no broker/account mutations."""
from contextlib import ExitStack
from pathlib import Path
import os
import tempfile
from urllib.parse import urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect

from goxtrade.api import app as api_module, state
from goxtrade.data import live_store
from goxtrade.execution import projectx_client, manager_service
from goxtrade.strategies.strategy_catalog import SPECS


def run():
    base = os.environ.get("GOX_NATIVE_PREVIEW_URL", "http://127.0.0.1:8504")
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        stack.enter_context(patch.object(live_store, "DB_PATH", Path(directory)/"browser.db"))
        stack.enter_context(patch.object(state, "CACHE", state.SnapshotCache()))
        stack.enter_context(patch.object(projectx_client, "post", side_effect=AssertionError("No provider calls")))
        stack.enter_context(patch.object(projectx_client, "login", side_effect=AssertionError("No authentication")))
        stack.enter_context(patch("goxtrade.runtime.live_process.status", return_value=dict(running=False, pid=None)))
        client = stack.enter_context(TestClient(api_module.create_app(), base_url=base))
        session = client.get("/api/session").json()
        saved = []
        def route_api(route):
            request = route.request
            path = urlsplit(request.url).path
            if request.method == "GET":
                response = client.get(path+("?"+urlsplit(request.url).query if urlsplit(request.url).query else ""))
            else:
                assert path == "/api/manager/policy", "No broker, credentials, worker or account actions permitted"
                saved.append(request.post_data_json)
                response = client.post(path, json=request.post_data_json, headers={"origin": base, "x-gox-csrf": session["csrf"]})
            route.fulfill(status=response.status_code, json=response.json())
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            output = Path("data/verification")
            output.mkdir(parents=True, exist_ok=True)
            for width, height in ((2560, 1440), (1440, 1000), (1280, 900), (834, 1112), (390, 844), (320, 740)):
                page = browser.new_page(viewport=dict(width=width, height=height))
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/api/**", route_api)
                page.route_web_socket("**/api/stream", lambda socket: None)
                page.goto(base+"/#controls")
                for profile in ("practice", "leader"):
                    page.get_by_label("Account view", exact=True).select_option(profile)
                    for spec in SPECS:
                        check = page.get_by_role("checkbox", name=spec.name, exact=True)
                        expect(check).to_be_visible()
                        if profile not in spec.execution_profiles:
                            expect(check).to_be_disabled()
                    for tab in ("Intervals & sessions", "VWAP EMA parameters", "Previous Day Box", "Entry policy"):
                        page.get_by_role("tab", name=tab, exact=True).click()
                        expect(page.get_by_role("tab", name=tab, exact=True)).to_have_attribute("aria-selected", "true")
                    page.goto(base+"/#manager")
                    expect(page.get_by_role("heading", name="Strategy Manager", exact=True)).to_be_visible()
                    for tab in ("Research policy", "Portfolio backtest", "Paper portfolio", "Decision journal", "Overview"):
                        page.get_by_role("tab", name=tab, exact=True).click()
                        expect(page.get_by_role("tab", name=tab, exact=True)).to_have_attribute("aria-selected", "true")
                        assert page.evaluate("document.body.scrollWidth <= innerWidth"), (width, profile, tab)
                    page.goto(base+"/#controls")
                page.goto(base+"/#manager")
                page.get_by_role("tab", name="Research policy", exact=True).click()
                page.get_by_label("commission per side", exact=True).fill("0.50")
                page.get_by_label("max trade risk", exact=True).fill("60")
                page.get_by_role("checkbox", name="MYM", exact=True).check()
                page.get_by_role("checkbox", name="EMA Pullback monitoring", exact=True).uncheck()
                expect(page.get_by_role("checkbox", name="EMA Pullback research participation", exact=True)).not_to_be_checked()
                page.get_by_role("button", name="Save research policy", exact=True).click()
                expect(page.locator(".toast")).to_contain_text("Research manager policy saved")
                page.reload()
                page.get_by_role("tab", name="Research policy", exact=True).click()
                expect(page.get_by_label("max trade risk", exact=True)).to_have_value("60")
                expect(page.get_by_role("checkbox", name="MYM", exact=True)).to_be_checked()
                expect(page.get_by_role("checkbox", name="Enable separate portfolio paper entries", exact=True)).not_to_be_checked()
                page.screenshot(path=str(output/f"manager-{width}-policy.png"), full_page=True)
                page.get_by_role("tab", name="Overview", exact=True).click()
                page.screenshot(path=str(output/f"manager-{width}-overview.png"), full_page=True)
                assert not errors, errors
                page.close()
            browser.close()
        assert saved
        assert manager_service.policy().max_trade_risk == 60
        assert not manager_service.policy().paper_enabled
    print("Strategy Manager browser checks passed at six sizes: both profiles share all strategy/interval tabs, restricted Leader choices stay visible, manager policy saves/reloads, paper stays off, no overflow or JS errors. Temporary data only; no broker actions.")


if __name__ == "__main__":
    run()
