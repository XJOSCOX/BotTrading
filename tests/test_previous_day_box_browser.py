"""Visual/interaction QA with browser-only fixture interception, no broker writes."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright,expect

from goxtrade.api import app as api_module,state
from goxtrade.data import live_store
from goxtrade.execution import projectx_client
from goxtrade.market.chart_indicators import indicator_points
from goxtrade.strategies.previous_day_box import evaluate_previous_day_box
from tests.previous_day_box_fixtures import NOW,CONTRACT,history


def run():
    base=os.environ.get("GOX_NATIVE_PREVIEW_URL","http://127.0.0.1:8504")
    signal,bars=evaluate_previous_day_box(history(),118,NOW,contract_id=CONTRACT,quote_time=NOW)
    payload=dict(points=indicator_points(bars,"15min"),box=signal["box"],signal=signal,
                 levels={**{key:signal["box"][key] for key in ("pdh","pdl","midpoint","buy_upper","sell_lower")},**{key:signal[key] for key in ("entry","stop","target")}},
                 markers=[dict(time=int(NOW.timestamp())-900,position="belowBar",shape="arrowUp",color="#82d6ad",text="wick confirmed")],
                 events=[signal],quote_time=NOW.isoformat(),contract_id=CONTRACT,session_definition="futures")
    with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
        stack.enter_context(patch.object(live_store,"DB_PATH",Path(folder)/"browser.db"))
        stack.enter_context(patch.object(state,"CACHE",state.SnapshotCache()))
        stack.enter_context(patch.object(projectx_client,"post",side_effect=AssertionError("Broker access prohibited")))
        stack.enter_context(patch("goxtrade.runtime.live_process.status",return_value=dict(running=False,pid=None)))
        client=stack.enter_context(TestClient(api_module.create_app(),base_url=base))
        def route_api(route):
            request=route.request
            assert request.method=="GET","This visual test cannot mutate settings"
            path=urlsplit(request.url).path
            if path.startswith("/api/previous-day-box/"):
                route.fulfill(json=state.clean(payload));return
            response=client.get(path)
            headers={key:value for key,value in response.headers.items() if key.lower() not in ("content-length","content-type","content-encoding")}
            route.fulfill(status=response.status_code,headers=headers,json=response.json())
        with sync_playwright() as p:
            browser=p.chromium.launch(channel="msedge",headless=True)
            output=Path("data/verification");output.mkdir(parents=True,exist_ok=True)
            for width,height,name in ((1440,1000,"desktop"),(390,844,"mobile")):
                page=browser.new_page(viewport=dict(width=width,height=height));errors=[]
                page.on("pageerror",lambda error:errors.append(str(error)))
                page.route("**/api/**",route_api)
                page.route_web_socket("**/api/stream",lambda socket:None)
                page.goto(base+"/#strategies")
                # No monitor rows exist: all registry strategies must still be shown.
                page.locator("table.matrix tbody th").first.wait_for()
                names=page.locator("table.matrix tbody th").evaluate_all("headers=>headers.map(header=>header.firstChild.textContent)")
                assert names==[spec.name for spec in api_module.state.SPECS],names
                expect(page.get_by_text("NO CURRENT RESULT",exact=True).first).to_be_visible()
                assert page.evaluate("getComputedStyle(document.querySelector('main')).color") == "rgb(232, 233, 230)"
                assert page.evaluate("getComputedStyle(document.querySelector('.app-shell')).backgroundColor") in ("rgba(0, 0, 0, 0)","rgb(21, 23, 22)")
                page.screenshot(path=str(output/f"box-{name}-all-strategies.png"),full_page=True)
                page.get_by_role("tab",name="Previous Day Box",exact=True).click()
                expect(page.get_by_role("heading",name="Previous Day Box Reversal",exact=True)).to_be_visible()
                page.locator("canvas").first.wait_for()
                page.wait_for_timeout(700)
                assert page.locator("canvas").first.evaluate("c=>{let a=c.getContext('2d').getImageData(0,0,c.width,c.height).data,s=new Set();for(let i=0;i<a.length;i+=16)s.add(`${a[i]},${a[i+1]},${a[i+2]}`);return s.size>25}")
                expect(page.get_by_text("Previous session 2026-10-22 · futures · CT",exact=True)).to_be_visible()
                page.get_by_role("button",name="Zoom in",exact=True).click()
                page.wait_for_timeout(250)
                before=page.evaluate("localStorage.getItem('gx-range-NQ=F-15')")
                page.wait_for_timeout(2500)
                after=page.evaluate("localStorage.getItem('gx-range-NQ=F-15')")
                assert after==before,(before,after)
                assert page.evaluate("document.body.scrollWidth<=innerWidth")
                assert not errors,errors
                page.get_by_role("button",name="Follow latest price",exact=True).click()
                page.wait_for_timeout(250)
                page.screenshot(path=str(output/f"box-{name}-chart.png"),full_page=True)
                page.close()
            browser.close()
    print("All registered strategies remain visible without worker rows; GoXFinance colors, desktop/mobile box chart pixels, zones, levels, confirmed markers and retained zoom passed. Browser fixtures only; no production writes or broker calls.")


if __name__=="__main__":run()
