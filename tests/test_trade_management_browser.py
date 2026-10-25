"""Opt-in headless QA with a temporary API database and broker transport blocked."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect

from goxtrade.api import app as api_module, state
from goxtrade.data import live_store
from goxtrade.execution import projectx_client, profit_service
from goxtrade.execution.trade_analytics import analytics
from goxtrade.execution.trade_manager import simulate_exit
from tests.test_trade_management import trade, tick


def run():
    base = "http://127.0.0.1:8504"
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        stack.enter_context(patch.object(live_store, "DB_PATH", Path(directory)/"browser.db"))
        stack.enter_context(patch.object(state, "CACHE", state.SnapshotCache()))
        stack.enter_context(patch.object(projectx_client, "post", side_effect=AssertionError("No broker calls")))
        stack.enter_context(patch.object(projectx_client, "login", side_effect=AssertionError("No authentication")))
        stack.enter_context(patch("goxtrade.runtime.live_process.status", return_value=dict(running=False, pid=None)))
        client = stack.enter_context(TestClient(api_module.create_app(), base_url=base))
        session = client.get("/api/session").json()
        saved = []
        fail_save = [False]
        active = tick(trade(mode="profit_lock"), 120., 1)
        closed = simulate_exit(tick(active, 109., 2), "2026-10-22T15:00:02Z")

        def route_api(route):
            request, url = route.request, urlsplit(route.request.url)
            if request.method == "GET":
                response = client.get(url.path+("?"+url.query if url.query else ""))
                if url.path == "/api/trade-management" and response.status_code == 200:
                    data = response.json()
                    data["paper_positions"] = [{**active, "analytics":analytics(active), "population":"Browser fixture paper"}]
                    data["paper_closed"] = [dict(population="Browser fixture paper", strategy="CRT", symbol="MNQ", net=analytics(closed)["realized_net"],
                                                 exit_time=closed["last_time"], reason=closed["last_exit_reason"], management_analytics=analytics(closed))]
                    route.fulfill(status=200, json=data)
                    return
            else:
                assert url.path == "/api/trade-management/policy", "No account or trading actions allowed"
                if fail_save[0]:
                    route.fulfill(status=400, json={"detail": "Fixture save rejected"})
                    return
                saved.append(request.post_data_json)
                response = client.post(url.path, json=request.post_data_json,
                                       headers={"origin": base, "x-gox-csrf": session["csrf"]})
            route.fulfill(status=response.status_code, json=response.json())

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            output = Path("data/verification")
            output.mkdir(parents=True, exist_ok=True)
            for width, height in ((2560,1440), (1440,1000), (1280,900), (834,1112), (390,844), (320,740)):
                page = browser.new_page(viewport=dict(width=width, height=height))
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/api/**", route_api)
                page.route_web_socket("**/api/stream", lambda socket: None)
                page.goto(base+"/#trade-management")
                for profile in ("practice", "leader"):
                    page.get_by_label("Account view", exact=True).select_option(profile)
                    expect(page.get_by_role("heading", name="Trade Management", exact=True)).to_be_visible()
                    for tab in ("Positions", "Exit policy", "Giveback review", "Policy comparison"):
                        page.get_by_role("tab", name=tab, exact=True).click()
                        expect(page.get_by_role("tab", name=tab, exact=True)).to_have_attribute("aria-selected", "true")
                        if tab == "Positions":
                            expect(page.get_by_text("SOFTWARE / SIMULATED STOP - not broker-confirmed", exact=True)).to_be_visible()
                            page.screenshot(path=str(output/f"trade-management-{width}-positions.png"), full_page=True)
                        assert page.evaluate("document.body.scrollWidth <= innerWidth"), (width, profile, tab)
                page.get_by_role("tab", name="Exit policy", exact=True).click()
                page.get_by_label("mode", exact=True).select_option("hybrid")
                page.get_by_label("management minutes", exact=True).select_option("15")
                if page.get_by_role("button", name="Remove target", exact=True).count() == 0:
                    page.get_by_role("button", name="Add partial target", exact=True).click()
                page.get_by_label("Target 1 / contracts", exact=True).fill("2")
                page.get_by_role("button", name="Save exit policy", exact=True).click()
                expect(page.locator(".toast")).to_be_visible()
                page.reload()
                page.get_by_role("tab", name="Exit policy", exact=True).click()
                expect(page.get_by_label("mode", exact=True)).to_have_value("hybrid")
                expect(page.get_by_label("management minutes", exact=True)).to_have_value("15")
                expect(page.get_by_label("Target 1 / contracts", exact=True)).to_have_value("2")
                expect(page.get_by_role("checkbox", name="Apply central exits to new research/paper positions", exact=True)).not_to_be_checked()
                fail_save[0] = True
                page.get_by_label("target r", exact=True).fill("3")
                page.get_by_role("button", name="Save exit policy", exact=True).click()
                expect(page.locator(".toast")).to_contain_text("Fixture save rejected")
                expect(page.get_by_label("target r", exact=True)).to_have_value("3")
                page.get_by_role("button", name="Refresh positions", exact=True).click()
                expect(page.get_by_label("target r", exact=True)).to_have_value("3")
                fail_save[0] = False
                page.screenshot(path=str(output/f"trade-management-{width}.png"), full_page=True)
                assert not errors, errors
                page.close()
            browser.close()
        assert saved and not profit_service.read_policy().enabled
    print("Trade Management browser QA passed: six viewports, both profiles, four tabs, whole-contract settings persist, failed saves retain drafts, no overflow/JS errors. Temporary DB, no broker calls.")


if __name__ == "__main__":
    run()
