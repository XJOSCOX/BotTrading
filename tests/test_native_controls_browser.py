"""Opt-in control forms against real API routes and a disposable SQLite database.

Browser API requests are intercepted locally. No production configuration or broker
actions are allowed. Leader's isolated command is invoked in-process under patches.
"""
from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect

from goxtrade.api import app as api_module, state
from goxtrade.bot import bot_controls
from goxtrade.data import live_store
from goxtrade.execution import leader_execution, leader_worker, practice_executor, projectx_client


def run():
    base = os.environ.get("GOX_NATIVE_PREVIEW_URL", "http://127.0.0.1:8504")
    with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
        stack.enter_context(patch.object(live_store, "DB_PATH", Path(folder)/"controls.db"))
        stack.enter_context(patch.object(state, "CACHE", state.SnapshotCache()))
        stack.enter_context(patch.object(projectx_client, "post", side_effect=AssertionError("Broker calls prohibited")))
        stack.enter_context(patch.object(projectx_client, "login", side_effect=AssertionError("Broker login prohibited")))
        stack.enter_context(patch.object(practice_executor, "arm", side_effect=AssertionError("Arming prohibited")))
        stack.enter_context(patch("goxtrade.runtime.live_process.status", return_value=dict(running=False,pid=None)))
        # Seed both saved profiles with values different from the intentionally stale stream.
        with closing(live_store.connect()) as conn:
            for profile in ("practice", "leader"):
                conn.execute(f"CREATE TABLE {profile}_control (id INTEGER PRIMARY KEY,settings TEXT,status TEXT)")
                conn.execute(f"INSERT INTO {profile}_control VALUES(1,?, '{{}}')", (json.dumps(dict(enabled=False,quantities=dict(MNQ=3,MES=4,MYM=2),enable_mym=True)),))
            conn.commit()
        for profile in ("practice", "leader"):
            bot_controls.save(["MNQ","MES","MYM"],["CRT","ORB"],8,profile=profile)

        def leader_command(action, **values):
            assert action == "configure", "Only local policy configuration is permitted"
            with patch.object(leader_worker, "PROFILE", "leader"), patch.object(practice_executor, "PROFILE", "leader"), patch.object(bot_controls, "PROFILE", "leader"):
                leader_worker.handle_command(dict(action=action,**values))
        stack.enter_context(patch.object(leader_execution, "command", side_effect=leader_command))
        client = stack.enter_context(TestClient(api_module.create_app(), base_url=base, raise_server_exceptions=False))
        saved_requests = []
        reject_save = False
        def route_api(route):
            request = route.request
            path = urlsplit(request.url).path
            if reject_save and path.startswith("/api/policy/"):
                route.fulfill(status=503, json=dict(detail="Test save rejected; existing settings unchanged."))
                return
            assert request.method == "GET" or path.startswith(("/api/policy/", "/api/intervals", "/api/vwap", "/api/previous-day-box")), path
            headers = {key:value for key,value in request.headers.items() if key in ("origin","x-gox-csrf","content-type")}
            response = client.request(request.method, path, content=request.post_data, headers=headers)
            if request.method == "POST":
                assert response.status_code == 200, (path,response.text)
                saved_requests.append((path,json.loads(request.post_data)))
            data = response.json()
            if path == "/api/snapshot":
                # Old UI incorrectly initialized sizes from this stale snapshot.
                for profile in ("practice","leader"):
                    data["profiles"][profile]["settings"].update(quantities=dict(MNQ=1,MES=1,MYM=1),enable_mym=False)
            response_headers = {key:value for key,value in response.headers.items() if key.lower() not in ("content-length","content-encoding","content-type")}
            route.fulfill(status=response.status_code,headers=response_headers,json=data)

        with sync_playwright() as p:
            browser=p.chromium.launch(channel="msedge",headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1000))
            errors=[]
            page.on("pageerror",lambda error:errors.append(str(error)))
            page.route("**/api/**",route_api)
            page.route_web_socket("**/api/stream",lambda socket:None)
            page.goto(base+"/#controls")
            page.get_by_role("heading",name="Entry configuration").wait_for()

            def verify(strategies, mym, sizes, cooldown):
                for strategy in ("CRT","Reversal","ORB","VWAP Reclaim","EMA Pullback"):
                    expect(page.get_by_role("checkbox",name=strategy,exact=True)).to_be_checked(checked=strategy in strategies)
                expect(page.get_by_role("checkbox",name="Allow MYM entries")).to_be_checked(checked=mym)
                for symbol,size in sizes.items():
                    expect(page.get_by_label(symbol+" contracts")).to_have_value(str(size))
                expect(page.get_by_label("Re-enter after a confirmed close (minutes)")).to_have_value(str(cooldown))

            def save_policy():
                page.get_by_role("button",name="Save entry policy").click()
                expect(page.locator(".control-save-status")).to_contain_text("Entry policy saved")

            for profile in ("practice","leader"):
                page.get_by_label("Account view").select_option(profile)
                verify(["CRT","ORB"],True,dict(MNQ=3,MES=4,MYM=2),8)
                page.get_by_role("checkbox",name="CRT",exact=True).uncheck()
                page.get_by_role("checkbox",name="Reversal",exact=True).check()
                page.get_by_role("checkbox",name="Allow MYM entries").uncheck()
                for symbol,size in dict(MNQ=4,MES=1,MYM=3).items():
                    page.get_by_label(symbol+" contracts").fill(str(size))
                page.get_by_label("Re-enter after a confirmed close (minutes)").fill("19")
                expect(page.locator(".control-save-status")).to_contain_text("Unsaved changes")
                # A reconnect refresh must not replace operator edits.
                page.evaluate("window.dispatchEvent(new Event('gox-connected'))")
                page.wait_for_timeout(400)
                verify(["Reversal","ORB"],False,dict(MNQ=4,MES=1,MYM=3),19)
                save_policy()
                verify(["Reversal","ORB"],False,dict(MNQ=4,MES=1,MYM=3),19)
                page.reload()
                verify(["Reversal","ORB"],False,dict(MNQ=4,MES=1,MYM=3),19)
                saved=state.configuration()
                assert saved["policies"][profile]["strategies"]==["ORB","Reversal"]
                assert saved["execution_settings"][profile]["quantities"]==dict(MNQ=4,MES=1,MYM=3)
                assert not saved["execution_settings"][profile]["enabled"]
                page.get_by_role("checkbox",name="Reversal",exact=True).uncheck()
                page.get_by_role("checkbox",name="ORB",exact=True).uncheck()
                page.get_by_role("checkbox",name="Allow MYM entries").check()
                save_policy()
                page.reload()
                verify([],True,dict(MNQ=4,MES=1,MYM=3),19)
                all_strategies=["CRT","Reversal","ORB","VWAP Reclaim","EMA Pullback"] + (["VWAP EMA Cross"] if profile=="practice" else [])
                for strategy in all_strategies:
                    page.get_by_role("checkbox",name=strategy,exact=True).check()
                save_policy()
                page.reload()
                verify(all_strategies,True,dict(MNQ=4,MES=1,MYM=3),19)
                assert state.configuration()["policies"][profile]["strategies"]==all_strategies
                page.locator('nav[aria-label="Main navigation"]').get_by_role("link",name="Strategies",exact=True).click()
                page.locator("table.matrix tbody th").first.wait_for()
                labels=page.locator("table.matrix tbody th").all_text_contents()
                for strategy in all_strategies:
                    assert any(label.startswith(strategy) and "Selected" in label for label in labels),(strategy,labels)
                assert any(label.startswith("Previous Day Box Reversal") for label in labels),labels
                page.locator('nav[aria-label="Main navigation"]').get_by_role("link",name="Control Center",exact=True).click()
                page.get_by_role("heading",name="Entry configuration").wait_for()
                # Native browser validity must block an out-of-range contract count.
                before=len(saved_requests)
                page.get_by_label("MNQ contracts").fill("5")
                page.get_by_role("button",name="Save entry policy").click()
                assert not page.get_by_label("MNQ contracts").evaluate("field=>field.validity.valid")
                assert len(saved_requests)==before
                page.get_by_label("MNQ contracts").fill("4")
                for strategy in all_strategies:
                    page.get_by_role("checkbox",name=strategy,exact=True).uncheck()
                save_policy()

            # Failed saves keep the draft, show a real error, and do not alter storage.
            reject_save=True
            page.get_by_role("checkbox",name="CRT",exact=True).check()
            page.get_by_role("button",name="Save entry policy").click()
            expect(page.locator(".toast.error")).to_contain_text("Test save rejected")
            expect(page.get_by_role("checkbox",name="CRT",exact=True)).to_be_checked()
            expect(page.locator(".control-save-status")).to_contain_text("Unsaved changes")
            assert state.configuration()["policies"]["leader"]["strategies"]==[]
            reject_save=False

            # Saving one tab must not erase another tab's unsaved changes.
            page.get_by_role("tab",name="Intervals & sessions",exact=True).click()
            page.get_by_label("Opening range",exact=True).select_option("30")
            page.get_by_label("Stop & trailing candles",exact=True).select_option("15")
            page.get_by_role("tab",name="Entry policy",exact=True).click()
            save_policy()
            page.get_by_role("tab",name="Intervals & sessions",exact=True).click()
            expect(page.get_by_label("Opening range",exact=True)).to_have_value("30")
            expect(page.get_by_label("Stop & trailing candles",exact=True)).to_have_value("15")
            page.get_by_role("button",name="Save intervals",exact=True).click()
            expect(page.locator(".control-save-status")).to_contain_text("Intervals saved")
            page.reload()
            page.get_by_role("tab",name="Intervals & sessions",exact=True).click()
            expect(page.get_by_label("Opening range",exact=True)).to_have_value("30")
            expect(page.get_by_label("Stop & trailing candles",exact=True)).to_have_value("15")
            page.get_by_role("tab",name="VWAP EMA parameters",exact=True).click()
            page.get_by_label("signal minutes",exact=True).select_option("5")
            page.get_by_label("ema length",exact=True).fill("12")
            page.get_by_role("checkbox",name="monitor enabled",exact=True).uncheck()
            page.get_by_role("button",name="Save VWAP parameters",exact=True).click()
            expect(page.locator(".control-save-status")).to_contain_text("VWAP parameters saved")
            page.reload()
            page.get_by_role("tab",name="VWAP EMA parameters",exact=True).click()
            expect(page.get_by_label("signal minutes",exact=True)).to_have_value("5")
            expect(page.get_by_label("ema length",exact=True)).to_have_value("12")
            expect(page.get_by_role("checkbox",name="monitor enabled",exact=True)).not_to_be_checked()
            page.get_by_role("tab",name="Previous Day Box",exact=True).click()
            expect(page.get_by_role("checkbox",name="practice enabled",exact=True)).not_to_be_checked()
            expect(page.get_by_role("checkbox",name="paper enabled",exact=True)).not_to_be_checked()
            page.get_by_label("buy percent",exact=True).fill("20")
            page.get_by_label("sell percent",exact=True).fill("80")
            page.get_by_label("session",exact=True).select_option("rth")
            page.get_by_role("button",name="Save box parameters",exact=True).click()
            expect(page.get_by_text("Box settings saved. No account armed.",exact=True)).to_be_visible()
            page.reload()
            page.get_by_role("tab",name="Previous Day Box",exact=True).click()
            expect(page.get_by_label("buy percent",exact=True)).to_have_value("20")
            expect(page.get_by_label("sell percent",exact=True)).to_have_value("80")
            expect(page.get_by_label("session",exact=True)).to_have_value("rth")
            assert not errors, errors
            assert len(saved_requests)==12, saved_requests
            browser.close()
    print("Control Center real-API/temp-DB browser checks passed: both profiles, strategy on/off/all-off, MYM, sizes, cooldown, stale snapshots, reconnect drafts, save failure, independent tabs, intervals, VWAP and reload persistence. No broker actions or production writes.")


if __name__ == "__main__":
    run()
