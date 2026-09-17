from pathlib import Path
from playwright.sync_api import sync_playwright
from chart_history import chart_history
from live_chart_component import indicator_points


if __name__ == '__main__':
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width':1100, 'height':1000})
        page.goto(Path('chart_component/index.html').resolve().as_uri())
        page.wait_for_function('!!window.LightweightCharts')
        args = dict(symbol='NQ=F',timeframe='5min',candle_label='5 min',height=620,
                    points=indicator_points(chart_history('NQ=F'),'5min'))
        page.evaluate('(args)=>window.postMessage({type:"streamlit:render",args},"*")',args)
        page.wait_for_function('!!volumeSeries && volumeSeries.data().length>0')
        print('Rendered volume bars:',page.evaluate('volumeSeries.data().length'))
        assert page.evaluate('rsiSeries.data().some(p=>p.value!=null)')
        page.evaluate('chart.timeScale().setVisibleLogicalRange({from:100,to:150})')
        page.wait_for_timeout(200)
        assert page.evaluate('Math.abs(rsiChart.timeScale().getVisibleLogicalRange().from-100)<0.1')
        assert page.locator('#volume').bounding_box()['height']==60
        page.locator('#indicators summary').click()
        page.locator('#show-ema').check()
        assert page.evaluate('ema20Series.options().visible && ema50Series.options().visible')
        page.locator('#show-volume').uncheck()
        assert not page.locator('#volume-pane').is_visible()
        page.locator('#show-volume').check()
        page.locator('#indicators summary').click()
        args['height'] = 900
        args['metrics'] = [('Price','29,400.00','Last price',''),('Volume','10,000','Session volume','')]
        page.evaluate('(args)=>window.postMessage({type:"streamlit:render",args},"*")',args)
        page.wait_for_timeout(200)
        assert abs(page.locator('#frame').bounding_box()['height']-900)<2
        assert '29,400.00' in page.locator('#summary').inner_text()
        for name in ['volume','rsi']:
            before=page.locator('#'+name).bounding_box()['height']
            handle=page.locator('#'+name+'-resize').bounding_box()
            x=handle['x']+handle['width']/2
            y=handle['y']+3
            page.mouse.move(x,y)
            page.mouse.down()
            page.mouse.move(x,y-35,steps=5)
            page.mouse.up()
            page.wait_for_timeout(100)
            assert page.locator('#'+name).bounding_box()['height']>before+25
        heights=page.evaluate('JSON.stringify(paneHeights)')
        page.evaluate('(args)=>window.postMessage({type:"streamlit:render",args},"*")',args)
        page.wait_for_timeout(100)
        assert page.evaluate('JSON.stringify(paneHeights)')==heights
        assert abs(page.locator('#frame').bounding_box()['height']-900)<2
        page.screenshot(path='data/volume-chart.png')
        browser.close()
