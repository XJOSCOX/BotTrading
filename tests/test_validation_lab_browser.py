"""Headless research and account-parity QA; temporary fixtures, no broker actions."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright,expect

from goxtrade.api import app as api_module,state
from goxtrade.data import live_store,lab_store as store
from goxtrade.execution import projectx_client
from goxtrade.research import lab_service,validation_lab as lab
from goxtrade.strategies.strategy_catalog import SPECS
from tests.test_portfolio_backtest import signals,minutes
from tests.test_validation_lab import metadata,CONTRACT


def run():
    base="http://127.0.0.1:8504"
    with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
        stack.enter_context(patch.object(live_store,"DB_PATH",Path(directory)/"browser.db"))
        stack.enter_context(patch.object(state,"CACHE",state.SnapshotCache()))
        stack.enter_context(patch.object(projectx_client,"post",side_effect=AssertionError("No provider requests")))
        stack.enter_context(patch.object(projectx_client,"login",side_effect=AssertionError("No login")))
        stack.enter_context(patch("goxtrade.runtime.live_process.status",return_value=dict(running=False,pid=None)))
        stack.enter_context(patch("goxtrade.research.lab_jobs.start",side_effect=lambda identifier:store.get("lab_jobs",identifier)))
        client=stack.enter_context(TestClient(api_module.create_app(),base_url=base))
        session=client.get("/api/session").json()
        frame=minutes();frame.loc[3,["high","close"]]=[125.,110.]
        meta={**metadata(),"start":frame.iloc[0].time.isoformat(),"end":(frame.iloc[-1].time+__import__("pandas").Timedelta(minutes=1)).isoformat()}
        dataset=store.save_dataset(frame,meta)
        job=lab_service.validation(dict(datasets=[dataset["id"]],strategies=["crt"],start=meta["start"],end=meta["end"],execution=dict(commission_per_side=.5),exit_policy=dict(enabled=True,mode="fixed",target_method="rr",target_r=1)),start=False)
        def source(histories,prices,contracts,now,settings,**kw):
            kw.pop("configurations",None)
            return signals(histories,prices,contracts,now,settings,**kw)
        with patch.object(lab,"candidates_at",side_effect=source):lab.execute(job["id"])
        writes=[]
        def route_api(route):
            req,url=route.request,urlsplit(route.request.url)
            if req.method=="GET":
                response=client.get(url.path+("?"+url.query if url.query else ""))
            else:
                assert url.path.startswith("/api/validation-lab/"), "Account/trading mutations prohibited"
                writes.append(url.path)
                response=client.post(url.path,json=req.post_data_json,headers={"origin":base,"x-gox-csrf":session["csrf"]})
            route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get("content-type","application/json"))
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel="msedge",headless=True)
            output=Path("data/verification");output.mkdir(parents=True,exist_ok=True)
            for width,height in ((2560,1440),(1440,1000),(1280,900),(834,1112),(390,844),(320,740)):
                page=browser.new_page(viewport=dict(width=width,height=height))
                errors=[]
                page.on("pageerror",lambda error:errors.append(str(error)))
                page.route("**/api/**",route_api)
                page.route_web_socket("**/api/stream",lambda socket:None)
                page.goto(base+"/#controls")
                for profile in ("practice","leader"):
                    page.get_by_label("Account view",exact=True).select_option(profile)
                    for spec in SPECS:
                        expect(page.get_by_role("checkbox",name=spec.name,exact=True)).to_be_enabled()
                    page.get_by_role("tab",name="VWAP EMA parameters",exact=True).click()
                    expect(page.get_by_role("checkbox",name="leader enabled",exact=True)).to_be_visible()
                    page.get_by_role("tab",name="Previous Day Box",exact=True).click()
                    expect(page.get_by_role("checkbox",name="leader enabled",exact=True)).to_be_visible()
                    page.goto(base+"/#validation-lab")
                    expect(page.get_by_role("heading",name="Strategy Validation Lab",exact=True)).to_be_visible()
                    for tab in ("Datasets","Backtesting","Performance","Trade explorer","Jobs"):
                        page.get_by_role("tab",name=tab,exact=True).click()
                        assert page.evaluate("document.body.scrollWidth <= innerWidth"),(width,profile,tab)
                    page.goto(base+"/#controls")
                page.goto(base+"/#validation-lab")
                page.get_by_role("tab",name="Performance",exact=True).click()
                page.get_by_role("button",name="Inspect run",exact=True).first.click()
                expect(page.get_by_text("Insufficient trades for meaningful conclusions",exact=True)).to_be_visible()
                expect(page.get_by_role("img",name="Marked equity / simulated USD",exact=True)).to_be_visible()
                page.screenshot(path=str(output/f"validation-lab-{width}-performance.png"),full_page=True)
                page.get_by_role("tab",name="Trade explorer",exact=True).click()
                page.get_by_role("button",name="Inspect trade",exact=True).first.click()
                expect(page.get_by_role("img",name="Historical trade candles",exact=True)).to_be_visible()
                page.screenshot(path=str(output/f"validation-lab-{width}-trade.png"),full_page=True)
                page.get_by_role("tab",name="Backtesting",exact=True).click()
                page.get_by_role("checkbox",name=f"MNQ / {CONTRACT} / complete",exact=True).check()
                page.get_by_label("Commission / contract / side",exact=True).fill("0.75")
                page.get_by_label("Maximum contracts",exact=True).fill("2")
                page.get_by_role("button",name="Run historical validation",exact=True).click()
                expect(page.locator(".toast")).to_contain_text("Historical research queued")
                page.get_by_role("tab",name="Backtesting",exact=True).click()
                expect(page.get_by_label("Commission / contract / side",exact=True)).to_have_value("0.75")
                assert not errors,errors
                page.close()
            browser.close()
        assert writes and all(path=="/api/validation-lab/run" for path in writes)
    print("Validation Lab browser passed six sizes, both profiles, all seven selectable strategies, independent permissions, five research tabs, saved result charts/trade candles and research-only submissions. No real data or account writes.")


if __name__=="__main__":run()
