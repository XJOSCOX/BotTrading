"""Opt-in UI persistence/viewport test using disposable storage and intercepted APIs."""
from contextlib import ExitStack
from datetime import datetime,timezone
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright,expect
from goxtrade.api import app as api_module,state
from goxtrade.data import live_store
from goxtrade.market import economic_calendar as calendar


def run():
    base='http://127.0.0.1:8504'
    with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
        stack.enter_context(patch.object(live_store,'DB_PATH',Path(folder)/'ui.db'))
        stack.enter_context(patch.object(state,'CACHE',state.SnapshotCache()))
        stack.enter_context(patch('requests.sessions.Session.request',side_effect=AssertionError('External network prohibited')))
        stack.enter_context(patch('goxtrade.runtime.live_process.status',return_value=dict(running=False,pid=None)))
        client=stack.enter_context(TestClient(api_module.create_app(),base_url=base))
        def route_api(route):
            request=route.request;path=urlsplit(request.url).path
            assert request.method=='GET' or path.startswith('/api/economic-calendar'),path
            headers={k:v for k,v in request.headers.items() if k in ('origin','x-gox-csrf','content-type')}
            response=client.request(request.method,path,content=request.post_data,headers=headers)
            headers={k:v for k,v in response.headers.items() if k not in ('content-type','content-length','content-encoding')}
            route.fulfill(status=response.status_code,headers=headers,json=response.json())
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1000));errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.route('**/api/**',route_api);page.route_web_socket('**/api/stream',lambda socket:None)
            page.goto(base+'/#economic-calendar')
            page.get_by_role('heading',name='Practice event windows').wait_for()
            page.get_by_label('Before release (min)',exact=True).fill('20')
            page.get_by_role('button',name='Save event windows',exact=True).click()
            expect(page.get_by_text('Event windows saved for Practice. Open-position exits unchanged.')).to_be_visible()
            page.reload();expect(page.get_by_label('Before release (min)',exact=True)).to_have_value('20')
            page.get_by_text('Add reviewed event',exact=True).click()
            page.get_by_label('Event name',exact=True).fill('Fixture CPI')
            page.get_by_label('Release time (Chicago)',exact=True).fill('2026-11-10T07:30')
            page.get_by_label('Official schedule reference',exact=True).fill('https://www.bls.gov/')
            page.get_by_label('From date (CT)',exact=True).fill('2026-11-10')
            page.get_by_role('button',name='Add event',exact=True).click()
            expect(page.get_by_role('cell',name='Fixture CPI',exact=True)).to_be_visible()
            page.screenshot(path='data/verification/economic-calendar-desktop.png',full_page=True)
            page.set_viewport_size(dict(width=390,height=844))
            page.wait_for_timeout(500)
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1')
            page.screenshot(path='data/verification/economic-calendar-mobile.png',full_page=True)
            page.get_by_role('button',name='Remove Fixture CPI',exact=True).click()
            expect(page.get_by_role('cell',name='Fixture CPI',exact=True)).to_have_count(0)
            assert not errors,errors
            browser.close()
    print('Economic calendar desktop/mobile, saved buffers, manual event add/delete and reload persistence passed. Fixture data only.')
