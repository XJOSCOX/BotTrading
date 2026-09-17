from html import escape
from datetime import datetime
import streamlit as st
from dashboard_view import statistics, usd, CT


def tone(value):
    return "gain" if value>=0 else "loss"


def render(rows,settings,feed,gate,stale,fresh,pending):
    from dashboard_style import apply
    apply()
    s = statistics(rows)
    wins = sum(r["net"]>0 for r in rows)
    losses = sum(r["net"]<0 for r in rows)
    rate = f"{s['win_rate']:.0f}%" if s["win_rate"] is not None else "--"
    factor = f"{s['profit_factor']:.2f}" if s["profit_factor"] is not None else "No losses" if wins else "--"
    mode = "Offline" if not fresh else "Monitoring" if settings.get("enabled") else "Entries paused"
    updated = datetime.fromisoformat(feed["updated_at"]).astimezone(CT).strftime("%H:%M:%S CT") if feed.get("updated_at") else "Unavailable"
    maximum = max([abs(r["net"]) for r in rows] or [1]) or 1
    bars = ''.join(f'<div class="db-outcome"><span>{escape(r["symbol"])}</span><div class="db-track"><i class="{tone(r["net"])}" style="width:{max(1,abs(r["net"])/maximum*100):.2f}%"></i></div><b class="{tone(r["net"])}">{usd(r["net"])}</b></div>' for r in sorted(rows,key=lambda r:r["time"])[-6:])
    journal = ''.join(f'<tr><td><b>{escape(r["symbol"])}</b><small>{escape(r["strategy"])}</small></td><td>{r["time"].astimezone(CT).strftime("%b %d, %H:%M")}</td><td>{r["direction"]}</td><td>{r["quantity"]}</td><td class="{tone(r["net"])}"><b>{usd(r["net"])}</b></td><td>{usd(r["costs"])}</td></tr>' for r in sorted(rows,key=lambda r:r["time"],reverse=True)[:15])
    rankings = []
    for name in sorted({r["strategy"] for r in rows}):
        group = statistics([r for r in rows if r["strategy"]==name])
        rankings.append((group["net"],f'<div class="db-rank"><div><b>{escape(name)}</b><small>{group["trades"]} trades / {group["win_rate"]:.0f}% wins</small></div><strong class="{tone(group["net"])}">{usd(group["net"])}</strong></div>'))
    ranks = ''.join(html for _,html in sorted(rankings,reverse=True))
    symbols = ''.join(f'<div class="db-detail"><span>{symbol}</span><b>{usd(sum(r["net"] for r in rows if r["symbol"]==symbol))}</b></div>' for symbol in ("MNQ","MES","MYM"))
    risk = ''.join(f'<div class="db-detail"><span>{label}</span><b>{usd(s[key])}</b></div>' for label,key in [("Max drawdown","drawdown"),("Average win","average_win"),("Average loss","average_loss"),("Expectancy / trade","expectancy"),("Trading costs","costs")])
    st.html(f'''<section class="db-report">
    <div class="db-status"><b>{mode}</b><span>{'Broker data stale' if stale else 'Synced '+updated}</span><span>{'--' if stale else len(feed.get('positions',[]))} positions / {'--' if stale else len(feed.get('orders',[]))} orders</span><span class="db-lock">Loss lock: {'LOCKED' if gate.get('locked') else 'Clear' if gate else 'Unavailable'}</span></div>
    <div class="db-top"><section class="db-result"><small>REALIZED PERFORMANCE</small><div class="db-net {tone(s['net'])}">{usd(s['net'])}</div><p>Net profit after reported trading costs</p><div class="db-mini"><div><b>{len(rows)}</b><span>Closed trades</span></div><div><b>{rate}</b><span>Win rate</span></div><div><b>{factor}</b><span>Profit factor</span></div></div><div class="db-win-track"><i style="width:{wins/len(rows)*100 if rows else 0}%"></i></div><div class="db-win-key"><span>{wins} won</span><span>{losses} lost / {len(rows)-wins-losses} flat</span></div></section>
    <section class="db-outcomes"><header><h3>Trade outcomes</h3><small>Last {min(6,len(rows))} trades</small></header>{bars or '<p>No completed trades in this period.</p>'}</section><section class="db-risk"><h3>Risk & efficiency</h3>{risk}</section></div>
    <div class="db-bottom"><section><header><h3>Execution journal</h3><small>Newest first / Chicago time</small></header><div class="db-scroll"><table><thead><tr><th>Instrument / Strategy</th><th>Closed</th><th>Side</th><th>Qty</th><th>Net P&L</th><th>Costs</th></tr></thead><tbody>{journal or '<tr><td colspan="6">No matched executions yet.</td></tr>'}</tbody></table></div></section><aside class="db-ranking"><h3>Strategy results</h3>{ranks or '<p>Awaiting completed trades.</p>'}<h3 class="db-symbol-title">By instrument</h3>{symbols}</aside></div>
    <footer>Executed bot trades only. Watch signals, manual trades and tests excluded. {pending} unmatched closed trades excluded. {'Small sample: fewer than 20 completed trades.' if len(rows)<20 else ''}</footer></section>''')
