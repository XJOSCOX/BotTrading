"""Opt-in dashboard history QA with synthetic broker results, no mutations."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def run():
    base = os.environ.get('GOX_NATIVE_PREVIEW_URL','http://127.0.0.1:8504')
    output = Path('data/verification')
    output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge',headless=True)
        for width,height in [(1440,1000),(390,844)]:
            page = browser.new_page(viewport=dict(width=width,height=height))
            mutations,errors = [],[]
            page.on('request',lambda r: mutations.append(r.url) if r.method in ('POST','PUT','DELETE') else None)
            page.on('pageerror',lambda e: errors.append(str(e)))
            mode = 'dashboard'
            def snapshot(route):
                response = route.fetch()
                data = response.json()
                profile = data['profiles']['practice']
                current = profile['target']['id']
                if mode != 'dashboard':
                    profile['settings']['enabled'] = mode != 'paused'
                    profile['settings']['automation'] = {**profile['settings'].get('automation',{}),
                                                         'account_id':current,'strategies':['crt']}
                profile['trades'] = [dict(account_id=current+1,net=10,costs=2,closed_at='2026-09-17T03:00:00Z',strategy='CRT',symbol='MNQ',direction='LONG',quantity=1),
                                     dict(account_id=current,net=-5,costs=2,closed_at='2026-09-18T03:00:00Z',strategy='CRT',symbol='MNQ',direction='SHORT',quantity=1)]
                route.fulfill(response=response,json=data)
            page.route('**/api/snapshot',snapshot)
            page.route_web_socket('**/api/stream',lambda socket: None)
            page.goto(base+'/#dashboard')
            expect(page.get_by_label('History scope')).to_have_value('All saved accounts')
            expect(page.locator('.rank-row small')).to_have_text('2 trades \u00b7 50.0% win rate')
            assert page.locator('.table-scroll tbody tr').count()==2
            page.get_by_label('History scope').select_option('Current account')
            expect(page.locator('.rank-row small')).to_have_text('1 trade \u00b7 0.0% win rate')
            page.get_by_label('History scope').select_option(index=3)
            expect(page.locator('.rank-row small')).to_have_text('1 trade \u00b7 100.0% win rate')
            page.reload()
            expect(page.get_by_label('History scope')).to_have_value('All saved accounts')
            expect(page.locator('.rank-row small')).to_have_text('2 trades \u00b7 50.0% win rate')
            assert page.evaluate('document.body.scrollWidth <= innerWidth')
            page.screenshot(path=str(output/f'practice-lifetime-dashboard-{width}.png'),full_page=True)
            mode = 'execution'
            page.goto(base+'/#execution')
            page.reload()
            expect(page.get_by_role('heading',name='Enabled strategies',exact=True)).to_be_visible()
            items = page.get_by_role('list',name='Execution strategies').get_by_role('listitem')
            expect(items).to_have_count(1)
            expect(items).to_contain_text('CRT')
            expect(items).to_contain_text('Enabled')
            assert page.evaluate('document.body.scrollWidth <= innerWidth')
            page.screenshot(path=str(output/f'practice-enabled-strategies-{width}.png'),full_page=True)
            mode = 'paused'
            page.reload()
            expect(page.get_by_role('heading',name='Saved strategies',exact=True)).to_be_visible()
            expect(page.get_by_role('list',name='Execution strategies')).to_contain_text('Paused')
            assert not errors,errors
            assert not mutations,mutations
            page.close()
        browser.close()


if __name__ == '__main__':
    run()
