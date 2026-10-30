"""Read-only browser QA; synthetic alerts never reach storage or the broker."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from goxtrade.bot.signal_pnl import watch_outcome


def run():
    base = os.environ.get("GOX_NATIVE_PREVIEW_URL", "http://127.0.0.1:8504")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport=dict(width=1440, height=1000))
        errors, mutations = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: mutations.append(request.url) if request.method != "GET" else None)
        page.route_web_socket("**/api/stream", lambda socket: None)

        def snapshot(route):
            response = route.fetch()
            data = response.json()
            data["alerts"] = [dict(id=i, symbol="NQ=F", strategy="CRT", signal="LONG",
                                   status="Active", entry=100, stop=90, target=120)
                              for i in (42, 43, 44, 50, 51)]
            data["alerts"] += [
                dict(id=45, symbol="NQ=F", strategy="CRT", signal="LONG", status="Closed", entry=100,
                     exit_price=110, exit_time="2026-10-27T02:00:00Z", exit_reason="Trailing stop reached"),
                dict(id=46, symbol="ES=F", strategy="CRT", signal="SHORT", status="Closed", entry=100,
                     exit_price=102, exit_time="2026-10-27T02:00:00Z", exit_reason="Stop reached"),
                dict(id=47, symbol="YM=F", strategy="CRT", signal="LONG", status="Dismissed", entry=100),
                dict(id=48, symbol="YM=F", strategy="CRT", signal="LONG", status="Closed", entry=100,
                     exit_price=110, exit_time="2026-10-27T02:00:00Z", exit_source="broker"),
                dict(id=49, symbol="NQ=F", strategy="Executed-only strategy", signal="LONG", status="Closed", entry=100,
                     exit_price=110, exit_time="2026-10-27T02:00:00Z")]
            for alert in data["alerts"]:
                alert["watch_outcome"] = watch_outcome(alert)
            data["events"] = []
            for profile, record in data["profiles"].items():
                record["jobs"] = [dict(alert_id=44, state="Open", display_state="In Trade", fill_price=100, quantity=1, symbol="MNQ"),
                                  dict(alert_id=50, state="Open", display_state="Unverified", fill_price=100, quantity=1, symbol="MNQ"),
                                  dict(alert_id=51, state="Open", display_state="Reconciliation needed", fill_price=100, quantity=1, symbol="MNQ")]
                record["execution_alert_ids"] = [44, 49, 50, 51]
                record["trades"] = [dict(alert_id=49, strategy="Executed-only strategy", symbol="MNQ", direction="LONG",
                                         quantity=1, exit_price=110, costs=1, net=19, closed_at="2026-10-27T02:00:00Z")]
                record["entry_decisions"] = {
                    "42": dict(detail=f"{profile}: overnight spread exceeds the saved limit", time="2026-10-27T02:00:00Z",
                               previous=[dict(id=99,detail=f"{profile}: 5m momentum does not support direction",time="2026-10-27T01:59:00Z")]),
                    "44": dict(detail="Outdated reason must not appear on a filled trade")}
            route.fulfill(json=data)

        page.route("**/api/snapshot", snapshot)
        page.goto(base + "/#strategies")
        for profile in ("practice", "leader"):
            page.get_by_label("Account view").select_option(profile)
            expect(page.get_by_text("IN TRADE", exact=True)).to_have_count(1)
            expect(page.get_by_text("BROKER STATUS UNVERIFIED", exact=True)).to_have_count(1)
            expect(page.get_by_text("RECONCILIATION NEEDED", exact=True)).to_have_count(1)
            expect(page.locator(".alert-item").filter(has_text="#50")).not_to_contain_text("pts")
            notes = page.locator(".entry-block")
            expect(notes).to_have_count(2)
            expect(notes.filter(has_text=f"{profile}: overnight spread")).to_have_count(1)
            expect(notes.filter(has_text=f"{profile}: 5m momentum does not support direction")).to_have_count(1)
            expect(notes.filter(has_text="No execution decision recorded")).to_have_count(1)
            expect(page.get_by_text("Outdated reason must not appear", exact=False)).to_have_count(0)
            assert notes.first.evaluate("el => getComputedStyle(el).color") == "rgb(239, 163, 163)"
            page.get_by_role("tab", name="Real trades", exact=True).click()
            expect(page.get_by_label("Real trade history")).to_contain_text("$19.00")
            expect(page.get_by_text("gross estimate", exact=False)).to_have_count(0)
            page.get_by_role("tab", name="Watch-only history", exact=True).click()
            expect(page.get_by_label("Hypothetical watch results")).to_contain_text("1 wins")
            expect(page.get_by_label("Hypothetical watch results")).to_contain_text("1 losses")
            expect(page.get_by_label("Hypothetical watch results")).to_contain_text("Hypothetical won $20.00")
            expect(page.get_by_label("Hypothetical watch results")).to_contain_text("Hypothetical lost -$10.00")
            expect(page.get_by_label("Hypothetical watch results")).to_contain_text("Hypothetical net $10.00")
            summary_row = page.locator("table tbody tr").filter(has_text="CRT")
            expect(summary_row).to_have_count(1)
            expect(summary_row).to_contain_text("$20.00")
            expect(summary_row).to_contain_text("-$10.00")
            expect(summary_row.locator("td").nth(7)).to_have_text("$10.00")
            expect(page.get_by_text("Executed-only strategy", exact=True)).to_have_count(0)
            expect(page.get_by_text("$19.00", exact=True)).to_have_count(0)
            if profile == "practice":
                page.get_by_role("tab", name="Active setups", exact=True).click()
        winner = page.locator(".alert-item").filter(has_text="WATCH WIN")
        loser = page.locator(".alert-item").filter(has_text="WATCH LOSS")
        expect(winner).to_contain_text("+10.00 pts hypothetical result")
        expect(winner).to_contain_text("1 MNQ: $20.00 gross estimate")
        expect(winner).to_contain_text("Trailing stop reached")
        expect(loser).to_contain_text("-2.00 pts hypothetical result")
        expect(loser).to_contain_text("1 MES: -$10.00 gross estimate")
        expect(page.locator(".alert-item").filter(has_text="#48")).not_to_contain_text("gross estimate")
        output = Path("data/verification")
        output.mkdir(parents=True, exist_ok=True)
        for width, height in ((1440, 1000), (390, 844)):
            page.set_viewport_size(dict(width=width, height=height))
            assert page.evaluate("document.body.scrollWidth <= innerWidth")
            page.screenshot(path=str(output/f"watch-only-reasons-{width}.png"), full_page=True)
        assert not errors, errors
        assert not mutations, mutations
        browser.close()
        print("Watch-only reasons: profile-scoped, red, no invented reasons, no filled-trade warning; desktop/mobile pass. No mutations.")


if __name__ == "__main__":
    run()
