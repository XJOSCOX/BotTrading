"""Headless chart viewport regression; all API traffic uses isolated fixtures."""
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect


def run():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        output = Path("data/verification")
        output.mkdir(parents=True, exist_ok=True)
        for width, height in ((1440, 1000), (390, 844)):
            page = browser.new_page(viewport=dict(width=width, height=height))
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            count = [200]

            def route_api(route):
                request = route.request
                assert request.method == "GET", "No account or broker writes permitted"
                path = urlsplit(request.url).path
                if path == "/api/session":
                    result = dict(csrf="isolated-chart-fixture")
                elif path == "/api/chart":
                    result = dict(points=[dict(time=1793106000+i*60, open=100+i*.25,
                        high=101+i*.25, low=99+i*.25, close=100.5+i*.25, volume=10+i,
                        rsi=50+math.sin(i)*10, ema20=100+i*.25, ema50=99+i*.25)
                        for i in range(count[0])])
                elif path == "/api/snapshot":
                    result = dict(profiles={}, monitor=[], alerts=[], events=[], prices={})
                else:
                    result = {}
                route.fulfill(status=200, content_type="application/json", body=json.dumps(result))

            page.route("**/api/**", route_api)
            page.route_web_socket("**/api/stream", lambda _: None)
            page.add_init_script("""localStorage.clear();
                localStorage.setItem('gx-range-NQ=F-1',JSON.stringify({from:50,to:100}));""")
            page.goto("http://127.0.0.1:8504/#charts")
            live = page.get_by_role("button", name="Follow latest price", exact=True)
            expect(live).to_be_visible()

            def wait_latest():
                page.wait_for_function("n=>JSON.parse(localStorage.getItem('gx-range-NQ=F-1')||'null')?.to>=n+2", arg=count[0])
                expect(live).to_have_attribute("aria-pressed", "true")

            def viewport():
                return page.evaluate("JSON.parse(localStorage.getItem('gx-range-NQ=F-1'))")

            wait_latest()
            initial = viewport()
            assert abs(initial['to']-initial['from']-50)<.1
            page.get_by_role("button", name="Zoom in", exact=True).click()
            zoomed = viewport()
            assert zoomed['to']-zoomed['from'] < 50
            count[0] += 4
            wait_latest()
            assert abs(viewport()['to']-viewport()['from']-(zoomed['to']-zoomed['from']))<.1

            page.evaluate("location.hash='connection'")
            expect(page.get_by_role("heading", name="Connection", exact=True)).to_be_visible()
            count[0] += 25
            page.evaluate("location.hash='charts'")
            wait_latest()
            assert abs(viewport()['to']-viewport()['from']-(zoomed['to']-zoomed['from']))<.1

            box = page.locator('.chart-main canvas').first.bounding_box()
            page.mouse.move(box['x']+box['width']*.3, box['y']+90)
            page.mouse.down()
            page.mouse.move(box['x']+box['width']*.8, box['y']+90, steps=12)
            page.mouse.up()
            expect(live).to_have_attribute("aria-pressed", "false")
            manual = viewport()
            count[0] += 5
            page.wait_for_timeout(2300)
            assert abs(viewport()['to']-manual['to'])<.1
            page.evaluate("location.hash='connection'")
            page.wait_for_function("!document.querySelector('.chart-frame')")
            count[0] += 5
            page.evaluate("location.hash='charts'")
            expect(live).to_have_attribute("aria-pressed", "false")
            page.wait_for_timeout(500)
            assert abs(viewport()['to']-manual['to'])<.1

            live.click()
            wait_latest()
            span = viewport()['to']-viewport()['from']
            count[0] += 3
            wait_latest()
            assert abs(viewport()['to']-viewport()['from']-span)<.1
            page.get_by_role("button", name="Fit all history", exact=True).click()
            expect(live).to_have_attribute("aria-pressed", "false")
            page.wait_for_timeout(300)
            expect(live).to_have_attribute("aria-pressed", "false")
            live.click()
            wait_latest()
            assert page.locator('.chart-frame canvas').count()>=3
            colors = page.locator('.chart-main canvas').first.evaluate("""el=>{
                const a=el.getContext('2d').getImageData(0,0,el.width,el.height).data;
                const colors=new Set();for(let i=0;i<a.length;i+=64)colors.add(a.slice(i,i+4).join(','));
                return colors.size;}""")
            assert colors > 5
            assert page.evaluate("document.body.scrollWidth<=innerWidth")
            page.screenshot(path=str(output/f"chart-follow-{width}.png"), full_page=True)
            assert not errors, errors
            page.close()
        browser.close()
    print("Desktop/mobile chart follow passed: page return, new candles, zoom, manual pan persistence, Live and synchronized panes. No broker calls or writes.")


if __name__ == "__main__":
    run()
