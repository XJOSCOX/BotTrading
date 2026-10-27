"""Opt-in browser QA. Synthetic chart rendering is intercepted, never persisted."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time

import pandas as pd
from playwright.sync_api import sync_playwright, expect
from goxtrade.market.chart_indicators import indicator_points


def fixture():
    rows=[]
    for i in range(240):
        opened=round((100+math.sin((i-1)/11)*2+i/100)*4)/4
        closed=round((100+math.sin(i/11)*2+i/100)*4)/4
        rows.append(dict(time=pd.Timestamp("2026-10-23T14:00Z")+pd.Timedelta(minutes=i),open=opened,high=max(opened,closed)+.25,low=min(opened,closed)-.25,close=closed,volume=i%30+1))
    return indicator_points(pd.DataFrame(rows),"1min")


def run():
    base=os.environ.get("GOX_NATIVE_PREVIEW_URL","http://127.0.0.1:8504")
    output=Path("data/verification");output.mkdir(parents=True,exist_ok=True)
    pages=[("Dashboard","dashboard"),("Charts","charts"),("Strategies","strategies"),("Control Center","controls"),("Execution","execution"),("Safeguards","safeguards"),("Research","research"),("Accounts","accounts"),("Connection","connection")]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel="msedge",headless=True)
        for width,height,device in ((2560,1440,"wide"),(1440,1000,"desktop"),(1280,800,"laptop"),(834,1112,"tablet"),(390,844,"mobile"),(320,740,"small-mobile")):
            page=browser.new_page(viewport=dict(width=width,height=height))
            errors=[];documents=[];frames=[];mutations=[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.on("request",lambda r:documents.append(r.url) if r.resource_type=="document" else None)
            page.on("request",lambda r:mutations.append(r.url) if r.method in ("POST","PUT","DELETE") else None)
            page.on("websocket",lambda ws:ws.on("framereceived",lambda event:frames.append(event)))
            page.route("**/api/chart?*",lambda route:route.fulfill(content_type="application/json",body=json.dumps(dict(points=fixture()))))
            page.goto(base)
            page.get_by_role("heading",name="Dashboard",exact=True).wait_for(timeout=30000)
            page.get_by_role("heading",name="Realized equity").wait_for(timeout=30000)
            for name,key in pages:
                if width<=650:page.get_by_role("button",name="Open navigation").click()
                page.locator('nav[aria-label="Main navigation"]').get_by_role("link",name=name,exact=True).click()
                page.get_by_role("heading",name=name,exact=True).wait_for()
                page.wait_for_timeout(250)
                assert page.evaluate("document.body.scrollWidth <= innerWidth"),(device,name)
                assert page.locator("main").evaluate("el=>innerWidth-el.getBoundingClientRect().right<2"),(device,name,"Unused workspace width")
                assert page.evaluate("parseFloat(getComputedStyle(document.documentElement).fontSize)>=15"),"Base text must remain readable"
                if width>1150:
                    assert page.locator("main").evaluate("el=>el.getBoundingClientRect().left===document.querySelector('.sidebar').getBoundingClientRect().right"),(device,name,"Content should align with navigation")
                assert not errors,errors
                if name=="Execution":
                    for profile in ("leader","practice"):
                        page.get_by_label("Account view").select_option(profile)
                        expect(page.locator(".run-panel h2")).to_have_text("Run controls")
                        expect(page.locator(".run-panel h3")).to_have_count(0)
                        expect(page.get_by_role("heading",name="Saved entry settings",exact=True)).to_have_count(0)
                        expect(page.locator(".run-panel .minor-metrics")).to_have_count(1)
                if name=="Charts":
                    page.locator("canvas").first.wait_for(timeout=30000)
                    page.wait_for_timeout(500)
                    assert page.locator("canvas").count()>=6
                    assert page.locator(".canvas-host").first.evaluate("host=>host.querySelector('canvas').getBoundingClientRect().width >= host.clientWidth - 100"),"Price canvas must fill the chart width"
                    assert page.locator("canvas").first.evaluate("c=>{let d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let v=new Set();for(let i=0;i<d.length;i+=16)v.add(`${d[i]},${d[i+1]},${d[i+2]}`);return v.size>20}")
                    page.get_by_role("button",name="Zoom in",exact=True).click()
                    page.wait_for_timeout(250)
                    before=page.evaluate("localStorage.getItem('gx-range-NQ=F-1')")
                    assert before
                    page.wait_for_timeout(2300)
                    after=page.evaluate("localStorage.getItem('gx-range-NQ=F-1')")
                    assert before==after,(before,after)
                    handle=page.get_by_role("separator",name="Resize volume")
                    handle.scroll_into_view_if_needed();box=handle.bounding_box()
                    page.mouse.move(box["x"]+20,box["y"]+3);page.mouse.down();page.mouse.move(box["x"]+20,box["y"]-30,steps=4);page.mouse.up()
                    assert float(page.evaluate("localStorage.getItem('gx-volume-height')"))>65
                if name=="Control Center":
                    field=page.get_by_label("Re-enter after a confirmed close (minutes)")
                    field.fill("17");page.wait_for_timeout(3300);assert field.input_value()=="17"
                if name in ("Dashboard","Charts","Control Center","Accounts","Execution","Safeguards"):
                    page.screenshot(path=str(output/f"native-{device}-{key}.png"),full_page=True)
            assert len(documents)==1,documents
            assert len(frames)>2,"WebSocket updates were not received"
            assert not mutations,mutations
            if device=="desktop" and os.environ.get("GOX_TEST_NATIVE_RESTART")=="1":
                from goxtrade.runtime.native_app import restart
                count=len(frames);restart()
                expect(page.locator(".connection-status")).to_contain_text("Live interface",timeout=30000)
                page.wait_for_timeout(2200)
                assert len(frames)>count and len(documents)==1,"Reconnect should not reload the document"
                assert not errors,errors
            page.close()

        # UI-only authorization fixture: show the dialog, never confirm or send an order.
        page=browser.new_page(viewport=dict(width=1200,height=900))
        def config_override(route):
            response=route.fetch();data=response.json();data["credentials_present"]=True;data["targets"]["practice"]["name"]="PRAC-UI-FIXTURE"
            route.fulfill(response=response,json=data)
        page.route("**/api/config",config_override)
        def snapshot_override(route):
            response=route.fetch();data=response.json();profile=data["profiles"]["practice"]
            profile["runtime"]=dict(updated_at=datetime.now(timezone.utc).isoformat(),account_id=profile["target"]["id"])
            profile["settings"]["enabled"]=False
            route.fulfill(response=response,json=data)
        page.route("**/api/snapshot",snapshot_override)
        page.route_web_socket("**/api/stream",lambda socket:None)
        page.goto(base+"/#execution")
        page.get_by_role("button",name="Start Practice automation",exact=True).click(timeout=15000)
        dialog=page.get_by_role("dialog")
        dialog.wait_for()
        confirm=dialog.get_by_role("button",name="Confirm start")
        assert confirm.is_disabled()
        dialog.get_by_role("textbox").fill("WRONG");dialog.get_by_role("checkbox").check()
        assert confirm.is_disabled()
        dialog.get_by_role("textbox").fill("PRAC-UI-FIXTURE")
        assert confirm.is_enabled()
        page.keyboard.press("Escape");assert not dialog.count()
        page.close();browser.close()
    print("Native desktop/mobile pages, client-side navigation, WebSocket updates, chart pixels, persistent zoom, pane resizing and authorization dialog passed. No mutations or broker orders submitted.")


if __name__=="__main__":run()
