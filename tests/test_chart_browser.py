"""Headless verification against the running Streamlit app."""
from playwright.sync_api import sync_playwright


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.goto('http://localhost:8502/?page=Market')
        page.locator('iframe[src*="live_candles"]').wait_for(timeout=30000)
        frame = next(f for f in page.frames if 'live_candles' in f.url)
        frame.wait_for_function('typeof chart !== "undefined" && !!chart && bars.length > 100')
        frame.evaluate('chart.timeScale().setVisibleLogicalRange({from:100,to:150}); remember()')
        before = frame.evaluate('snapshot()')
        page.wait_for_timeout(3500)
        after = frame.evaluate('snapshot()')
        assert abs(before['range']['from'] - after['range']['from']) < 0.1, (before, after)
        assert abs(before['range']['to'] - after['range']['to']) < 0.1
        frame.locator('#in').click()
        page.wait_for_timeout(1500)
        zoomed = frame.evaluate('snapshot()')
        assert zoomed['range']['to'] - zoomed['range']['from'] < 50
        frame.locator('#live').click()
        page.wait_for_timeout(1500)
        assert frame.evaluate('follow')
        page.screenshot(path='data/chart-zoom-desktop.png')
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_timeout(1500)
        assert frame.locator('canvas').count() > 0
        page.screenshot(path='data/chart-zoom-mobile.png')
        browser.close()
        print('Chart rendered; pan and zoom survived live updates; Live button and mobile render passed.')


if __name__ == '__main__':
    run()
