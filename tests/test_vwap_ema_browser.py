"""Opt-in headless preview checks. No execution or account controls are pressed."""
import json
import os
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross
from goxtrade.ui.bot.strategy_chart import chart_payload
from tests.vwap_fixtures import minutes


def run():
    base = os.environ.get("GOXTRADE_PREVIEW_URL", "http://127.0.0.1:8503")
    output = Path("data/verification")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport=dict(width=1440, height=1000))
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base+"/?page=Bot")
        page.get_by_role("tab", name="VWAP EMA Cross", exact=True).wait_for(timeout=45000)
        page.get_by_role("tab", name="VWAP EMA Cross", exact=True).click()
        for label in ("Signal & chart", "Parameters", "Backtest", "Comparison"):
            page.get_by_role("tab", name=label, exact=True).click()
            page.wait_for_timeout(800)
            assert page.locator('[data-testid="stException"]').count() == 0
        page.get_by_role("tab", name="Parameters", exact=True).click()
        page.wait_for_timeout(500)
        page.screenshot(path=str(output/"vwap-desktop.png"), full_page=True)
        mobile = browser.new_page(viewport=dict(width=390, height=844))
        mobile.goto(base+"/?page=Bot")
        mobile.get_by_role("tab", name="VWAP EMA Cross", exact=True).click(timeout=45000)
        mobile.get_by_role("tab", name="Parameters", exact=True).click()
        mobile.wait_for_timeout(500)
        mobile.screenshot(path=str(output/"vwap-mobile.png"), full_page=True)
        assert mobile.evaluate("document.body.scrollWidth <= innerWidth")
        assert mobile.locator('[data-testid="stException"]').count() == 0
        mobile.close()

        # Explicitly synthetic fixture only for rendering, never a saved performance run.
        data, config = minutes(), VwapEmaConfig(stop_method="fixed")
        signal, candles, _ = evaluate_vwap_ema_cross(data, 103., data.iloc[-1]["time"]+pd.Timedelta(minutes=1), config, historical=True)
        payload = dict(**chart_payload(candles, config, signal=signal), symbol="NQ=F", height=650,
                       strategy_overlay=True, ema_label="EMA 9", timeframe="3min", candle_label="3 min")
        chart_html = Path("goxtrade/ui/market/chart_component/index.html").read_text(encoding="utf-8")
        root = ('<html><body style="margin:0"><iframe id="preview" style="width:100%;height:660px;border:0" src="/chart"></iframe>'
                '<script>window.addEventListener("message",e=>{if(e.data.type==="streamlit:componentReady")'
                '{e.source.postMessage({type:"streamlit:render",args:'+json.dumps(payload)+'},"*");}});</script></body></html>')
        page.route("http://chart.test/**", lambda route: route.fulfill(content_type="text/html", body=chart_html if route.request.url.endswith("/chart") else root))
        page.set_viewport_size(dict(width=1440, height=800))
        page.goto("http://chart.test/")
        frame = page.frame_locator("#preview")
        frame.locator("canvas").first.wait_for(timeout=30000)
        page.wait_for_timeout(1500)
        chart = page.frames[1]
        assert chart.evaluate("bars.length") == len(payload["points"])
        assert not errors, errors
        assert chart.evaluate("strategyEmaSeries.data().filter(b=>b.value!=null).length") == sum(point["strategy_ema"] is not None for point in payload["points"])
        assert chart.evaluate("series.markers().length") > 0
        assert chart.evaluate("strategyLevels.length") == 3
        assert chart.evaluate("""() => {const c=document.querySelector('canvas');const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
            const colors=new Set();for(let i=0;i<d.length;i+=128)colors.add(d[i]+','+d[i+1]+','+d[i+2]);return colors.size>5;}""")
        frame.get_by_role("button", name="Zoom in", exact=True).click()
        before = chart.evaluate("chart.timeScale().getVisibleLogicalRange()")
        page.evaluate("args=>document.querySelector('iframe').contentWindow.postMessage({type:'streamlit:render',args},'*')", payload)
        page.wait_for_timeout(500)
        after = chart.evaluate("chart.timeScale().getVisibleLogicalRange()")
        assert abs((after["to"]-after["from"])-(before["to"]-before["from"])) < .01
        frame.get_by_title("Show all loaded history", exact=True).click()
        page.wait_for_timeout(300)
        page.screenshot(path=str(output/"vwap-chart-desktop.png"))
        page.set_viewport_size(dict(width=390, height=844))
        page.wait_for_timeout(500)
        page.screenshot(path=str(output/"vwap-chart-mobile.png"))
        assert not errors, errors
        browser.close()
    print("VWAP tabs, desktop/mobile layout, chart pixels, overlays, markers, levels and retained zoom passed. No orders submitted.")


if __name__ == "__main__":
    run()
