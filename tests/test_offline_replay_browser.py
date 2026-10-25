"""Headless UI QA with temporary fixture datasets and blocked broker transports."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from unittest.mock import patch,Mock
import pandas as pd
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright,expect
from goxtrade.api import app as api_module,state
from goxtrade.data import live_store,lab_store
from goxtrade.replay import replay_session as replay
from goxtrade.diagnostics import projectx_diagnostics as diagnostics
from tests.test_validation_lab import metadata,CONTRACT
from tests.test_portfolio_backtest import minutes,signals


def run():
    base="http://127.0.0.1:8504"
    with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
        stack.enter_context(patch.object(live_store,"DB_PATH",Path(directory)/"browser.db"))
        stack.enter_context(patch.object(state,"CACHE",state.SnapshotCache()))
        stack.enter_context(patch("goxtrade.execution.projectx_client.post",side_effect=AssertionError("Broker transport forbidden")))
        stack.enter_context(patch("goxtrade.execution.projectx_client.login",side_effect=AssertionError("No ProjectX")))
        stack.enter_context(patch("goxtrade.runtime.live_process.status",return_value=dict(running=False,pid=None)))
        stack.enter_context(patch("goxtrade.diagnostics.feed_status.read",return_value={}))
        stack.enter_context(patch.dict("os.environ",dict(TOPSTEP_USERNAME="TEST-FIXTURE",TOPSTEP_API_KEY="TEST-FIXTURE-SECRET")))
        rejected=Mock(status_code=200);rejected.json.return_value=dict(success=False,errorCode=3,errorMessage="TEST-FIXTURE-SECRET")
        network=stack.enter_context(patch("goxtrade.diagnostics.projectx_diagnostics.requests.post",return_value=rejected))
        def source(known,prices,contracts,now,settings,**kw):
            kw.pop("configurations",None)
            return signals(known,prices,contracts,now,settings,**kw)
        stack.enter_context(patch("goxtrade.research.validation_lab.candidates_at",side_effect=source))
        client=stack.enter_context(TestClient(api_module.create_app(),base_url=base))
        csrf=client.get("/api/session").json()["csrf"]
        frame=minutes(30);frame.loc[3,["high","close"]]=[125.,110.]
        meta={**metadata(),"start":frame.iloc[0].time.isoformat(),"end":(frame.iloc[-1].time+pd.Timedelta(minutes=1)).isoformat()}
        dataset=lab_store.save_dataset(frame,meta)
        session=replay.create(dict(datasets=[dataset["id"]],strategies=["crt"],start=meta["start"],end=meta["end"],execution=dict(commission_per_side=.5),exit_policy=dict(enabled=True,mode="fixed",target_method="rr",target_r=1)))
        for _ in range(6):replay.action(session["id"],dict(action="step"))
        mutations=[]
        def route_api(route):
            req,url=route.request,urlsplit(route.request.url)
            if req.method=="GET":response=client.get(url.path+("?"+url.query if url.query else ""))
            else:
                assert url.path.startswith("/api/replay/") or url.path=="/api/diagnostics", "Broker/account writes are forbidden"
                diagnostics._last=0
                mutations.append(url.path)
                response=client.post(url.path,json=req.post_data_json,headers={"origin":base,"x-gox-csrf":csrf})
            route.fulfill(status=response.status_code,body=response.content,content_type=response.headers.get("content-type","application/json"))
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel="msedge",headless=True)
            output=Path("data/verification");output.mkdir(parents=True,exist_ok=True)
            for width,height in ((2560,1440),(1440,1000),(1280,900),(834,1112),(390,844),(320,740)):
                page=browser.new_page(viewport=dict(width=width,height=height));errors=[]
                page.on("pageerror",lambda e:errors.append(str(e)))
                page.route("**/api/**",route_api);page.route_web_socket("**/api/stream",lambda _:None)
                page.goto(base+"/#market-replay")
                expect(page.get_by_role("heading",name="Market Replay",exact=True)).to_be_visible()
                for tab in ("Configuration","Recorded ticks","Saved sessions"):
                    page.get_by_role("tab",name=tab,exact=True).click()
                    assert page.evaluate("document.body.scrollWidth<=innerWidth"),(width,tab)
                page.get_by_role("button",name="Inspect session",exact=True).first.click()
                chart=page.get_by_role("img",name="Offline replay candlestick chart",exact=True)
                expect(chart.locator("canvas").first).to_be_visible()
                page.wait_for_function("document.querySelector('.replay-chart canvas')?.width > 0")
                nonblank=chart.evaluate("el=>{let colors=new Set();for(const c of el.querySelectorAll('canvas')){const a=c.getContext('2d')?.getImageData(0,0,c.width,c.height).data;if(a)for(let i=0;i<a.length;i+=64)colors.add([a[i],a[i+1],a[i+2],a[i+3]].join(','));}return colors.size;}")
                assert nonblank>10,(width,nonblank)
                page.get_by_role("button",name="Step event",exact=True).click()
                page.get_by_role("button",name="Play",exact=True).click()
                page.get_by_role("button",name="Pause",exact=True).click()
                expect(page.get_by_text("PAUSED",exact=True)).to_be_visible()
                page.screenshot(path=str(output/f"offline-replay-{width}.png"),full_page=True)
                assert page.evaluate("document.body.scrollWidth<=innerWidth"),(width,"Replay")
                page.goto(base+"/#diagnostics")
                expect(page.get_by_role("heading",name="Diagnostics",exact=True)).to_be_visible()
                page.get_by_role("button",name="Test authentication",exact=True).click()
                expect(page.get_by_role("cell",name="AUTH_FAILED",exact=True).first).to_be_visible()
                assert not page.get_by_text("TEST-FIXTURE-SECRET",exact=False).count()
                assert page.evaluate("document.body.scrollWidth<=innerWidth"),(width,"Diagnostics")
                page.screenshot(path=str(output/f"projectx-diagnostics-{width}.png"),full_page=True)
                assert not errors,errors
                page.close()
            browser.close()
        assert network.call_count==6
        assert mutations
    print("Offline Replay and Diagnostics browser passed six sizes; nonblank candle/volume/overlay canvas, persisted stepping, play/pause, read-only rejected-auth probe, responsive layouts, no broker/account writes.")


if __name__=="__main__":run()
