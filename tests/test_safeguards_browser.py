"""Safeguards UI against disposable real API routes and mocked broker reads only."""
from contextlib import ExitStack,closing
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright,expect
from goxtrade.api import app as api,state
from goxtrade.config import execution_identity as identity
from goxtrade.data import live_store
from goxtrade.execution import projectx_client,practice_executor
from goxtrade.execution.safeguards import PROTOCOL_VERSION
from goxtrade.runtime.build_identity import fingerprint
from tests.test_safeguards import TARGETS


def run():
    base=f'http://127.0.0.1:{api.PORT}';wire=[]
    with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
        for item in (patch.object(live_store,'DB_PATH',Path(folder)/'guards.db'),patch.object(identity,'TARGETS',TARGETS),
                     patch.object(identity,'current_targets',return_value=TARGETS),patch.object(state,'CACHE',state.SnapshotCache()),
                     patch.object(projectx_client,'login',return_value='fixture'),patch.object(practice_executor,'arm',side_effect=AssertionError('No arming')),
                     patch('goxtrade.execution.live_accounts.copy_role',side_effect=lambda a:TARGETS['practice' if a['id']==41 else 'leader']['role'])):
            stack.enter_context(item)
        def broker(path,payload,token=None):
            assert path in ('/api/Account/search','/api/Position/searchOpen','/api/Order/searchOpen'),path
            wire.append(path)
            if path=='/api/Account/search':return dict(success=True,accounts=[dict(id=t['id'],name=t['name'],canTrade=True,simulated=True,balance=10000.) for t in TARGETS.values()])
            return dict(success=True,positions=[],orders=[])
        stack.enter_context(patch.object(projectx_client,'post',side_effect=broker))
        with closing(live_store.connect()) as conn:
            for profile in TARGETS:
                conn.execute(f'CREATE TABLE {profile}_control(id INTEGER PRIMARY KEY,settings TEXT,status TEXT)')
                conn.execute(f'INSERT INTO {profile}_control VALUES (1,?,?)',(json.dumps(dict(enabled=False)),json.dumps(dict(account_id=TARGETS[profile]['id'],safeguards_version=PROTOCOL_VERSION,worker_build=fingerprint(),updated_at=datetime.now(timezone.utc).isoformat()))))
            conn.commit()
        client=stack.enter_context(TestClient(api.create_app(),base_url=base,raise_server_exceptions=False))
        def route_api(route):
            request=route.request;path=urlsplit(request.url).path
            assert request.method=='GET' or path.startswith('/api/safeguards/'),path
            headers={k:v for k,v in request.headers.items() if k in ('origin','x-gox-csrf','content-type')}
            response=client.request(request.method,path,content=request.post_data,headers=headers)
            assert response.status_code==200,(path,response.text)
            forwarded={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding','content-type')}
            route.fulfill(status=response.status_code,headers=forwarded,json=response.json())
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1000));errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.route('**/api/**',route_api);page.route_web_socket('**/api/stream',lambda socket:None)
            page.goto(base+'/#safeguards')
            for profile in ('practice','leader'):
                page.get_by_label('Account view').select_option(profile)
                expect(page.get_by_label('Cumulative account loss lock ($)')).to_have_value('500')
                page.get_by_label('Cumulative account loss lock ($)').fill('1000')
                page.get_by_label('Maximum contracts per symbol').select_option('2')
                page.get_by_label('Planned risk per trade ($)').fill('100')
                page.get_by_label('Total open stop-risk budget ($)').fill('200')
                page.get_by_label('Overnight maximum contracts').select_option('2')
                page.get_by_label('Minimum overnight cooldown (minutes)').fill('7')
                page.get_by_label('Maximum overnight spread (ticks)').fill('3')
                page.get_by_role('button',name='Save safeguards',exact=True).click()
                expect(page.locator('.run-panel [role=status]')).to_contain_text('Active limits are unchanged')
                page.reload()
                expect(page.get_by_label('Cumulative account loss lock ($)')).to_have_value('1000')
                expect(page.get_by_label('Overnight maximum contracts')).to_have_value('2')
                expect(page.get_by_label('Minimum overnight cooldown (minutes)')).to_have_value('7')
                expect(page.get_by_label('Maximum overnight spread (ticks)')).to_have_value('3')
                row=page.get_by_role('row').filter(has_text='Cumulative account loss lock ($)')
                expect(row.get_by_role('cell').nth(1)).to_have_text('$500.00')
                page.get_by_role('button',name='Review and apply',exact=True).click()
                confirm=page.get_by_role('button',name='Apply safeguards',exact=True)
                expect(confirm).to_be_disabled()
                page.get_by_label('I approve the saved limits shown above, including any increase in risk.').check()
                expect(confirm).to_be_disabled()
                page.get_by_label('Type the exact account name: '+TARGETS[profile]['name']).fill(TARGETS[profile]['name'])
                confirm.click()
                expect(row.get_by_role('cell').nth(1)).to_have_text('$1,000.00')
            for width,height,name in ((1440,1000,'desktop'),(390,844,'mobile')):
                page.set_viewport_size(dict(width=width,height=height))
                page.wait_for_timeout(400)
                if page.get_by_title('Dismiss message').count():page.get_by_title('Dismiss message').click()
                assert page.evaluate('document.body.scrollWidth<=innerWidth')
                if width<650:assert page.locator('.sidebar').evaluate('el=>el.getBoundingClientRect().right<=1')
                page.screenshot(path=f'data/verification/safeguards-{name}.png',full_page=True)
            assert not errors,errors
            browser.close()
        self_check=client.get('/api/snapshot').json()
        assert all(not value['settings'].get('enabled') for value in self_check['profiles'].values())
        assert len(wire)==6,wire
    print('Safeguards browser passed: both accounts, save/reload persistence, active/saved separation, exact-account Apply, responsive layout, no arming and only mocked read-only broker calls.')


if __name__=='__main__':run()
