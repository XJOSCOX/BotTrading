from html import escape

import streamlit as st
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from signal_pnl import dollars, money, dollar_summary
from strategy_catalog import STRATEGIES


def recent_alerts(rows):
    def key(row):
        fields = ("exit_time", "entry_time") if row.get("status") == "Closed" else ("entry_time",)
        for field in fields:
            try:
                value = datetime.fromisoformat(row.get(field) or "")
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.timestamp(), row.get("id", 0)
            except (ValueError, TypeError):
                continue
        return float("-inf"), row.get("id", 0)

    return sorted(rows, key=key, reverse=True)


def price(value):
    return "--" if value is None else f"{float(value):,.2f}"


def prioritized_alerts(rows, jobs):
    priorities = {"Open": 0, "Closing": 1, "Unknown": 2, "Submitted": 3, "Intent": 3}
    current, past = [], []
    for row in recent_alerts(rows):
        state = jobs.get(row["id"], {}).get("state")
        (current if state in priorities or (row["status"] == "Active" and state != "Closed") else past).append(row)
    current.sort(key=lambda row: priorities.get(jobs.get(row["id"], {}).get("state"), 4))
    return current, past


def theme():
    st.html("""<style>
    .gx {font-family:inherit;letter-spacing:0;color:inherit;}
    .gx small,.gx-label {font-size:12px;color:#929aa5;}
    .gx-top {display:flex;justify-content:space-between;align-items:center;gap:16px;padding:0 0 6px;margin-bottom:0;}
    .gx-top h1 {font-size:28px;margin:0;font-weight:650;}
    .gx-mode {color:#a9b2bc;font-size:13px;}
    .gx-ticker {display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:18px 0;border-block:1px solid #303237;margin:8px 0 22px;}
    .gx-ticker strong {font-size:23px;font-variant-numeric:tabular-nums;}
    .gx-ticker small {display:block;margin-bottom:3px;}
    .gx-section {font-size:12px;color:#929aa5;margin:0 0 12px;font-weight:650;}
    .gx-row {border-bottom:1px solid #55585f;padding:12px 0;margin-bottom:4px;}
    .gx-row.selected {background:#202327;border-left:3px solid #65d6bc;padding-left:9px;}
    .gx-row-head {display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px 12px;font-size:15px;}
    .gx-row p {font-size:13px;color:inherit;margin:6px 0;line-height:1.5;}
    .gx-row-foot {font-size:12px;color:inherit;overflow-wrap:anywhere;line-height:1.6;}
    .gx-state {background:#202327;padding:2px 6px;border-radius:3px;font-size:12px;}
    .gx-detail {padding:0 0 0 20px;border-left:1px solid #303237;}
    .gx-detail-head {display:flex;justify-content:space-between;gap:16px;align-items:center;}
    .gx-detail-head h2 {font-size:20px;margin:0;font-weight:600;}
    .gx-signal {font-size:30px;font-weight:700;margin:22px 0 6px;}
    .gx-reason {font-size:14px;color:#b6bec8;line-height:1.6;min-height:44px;margin:0 0 20px;}
    .gx-levels {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-block:1px solid #35373c;padding:22px 0;gap:12px;}
    .gx-levels strong {display:block;font-size:26px;margin-top:8px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;}
    .gx-focus {display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:20px 0;border-bottom:1px solid #303237;}
    .gx-focus strong {font-size:19px;overflow-wrap:anywhere;}
    .gx-facts {display:grid;grid-template-columns:1fr 1fr;gap:0 24px;padding-top:10px;}
    .gx-fact {display:flex;justify-content:space-between;gap:12px;padding:12px 0;font-size:13px;border-bottom:1px solid #292c30;}
    .gx-fact b {font-weight:550;font-variant-numeric:tabular-nums;}
    @media(max-width:700px) {.gx-detail {border-left:0;padding-left:0;} .gx-levels strong {font-size:20px;} .gx-facts {grid-template-columns:1fr;} }
    </style>""")


def color(signal):
    if signal == "LONG":
        return "#65d6bc"
    if signal == "SHORT":
        return "#f28c98"
    if "WATCH" in signal:
        return "#e5c477"
    return "#c7cdd5"


def ct(value):
    if not value:
        return "Time unavailable"
    import pandas as pd
    return pd.Timestamp(value).tz_convert("America/Chicago").strftime("%b %d, %H:%M:%S CT")


def monitor_row(symbol, result, healthy, market_open):
    signal = result["signal"] if result else {}
    state = signal.get("signal", "WAIT")
    if not healthy:
        state = "OFFLINE"
    elif market_open and not result.get("feed_fresh"):
        state = "DATA DELAYED"
    focus = escape(str(result.get("focus_value", "--"))) if result else "--"
    label = escape(str(result.get("focus_label", "Focus"))) if result else "Focus"
    st.html(f'''<div class="gx gx-row">
      <div class="gx-row-head"><b>{escape(symbol.replace("=F", ""))}</b><b class="gx-state" style="color:{color(state)}">{escape(state)}</b></div>
      <p>Last <b>{price(signal.get("last_close"))}</b></p>
      <div class="gx-row-foot">{label} &nbsp; <b>{focus}</b></div>
    </div>''')


def feed_status(tick, market_open):
    import pandas as pd
    if not tick:
        return "No data"
    timestamp = pd.to_datetime(tick.get("event_time"), utc=True, errors="coerce")
    if pd.isna(timestamp):
        timestamp = pd.to_datetime(tick.get("received_at"), utc=True, errors="coerce")
    age = (pd.Timestamp.now(tz="UTC") - timestamp).total_seconds()
    if not market_open:
        return "Market closed"
    return "Live" if 0 <= age <= 10 else "Delayed"


def alert_outcomes(rows):
    import math
    counts = dict(wins=0, losses=0, breakeven=0, unknown=0)
    for row in rows:
        if row.get("status") != "Closed":
            continue
        entry, exit_price = row.get("entry"), row.get("exit_price")
        if entry is None or exit_price is None or row.get("signal") not in ("LONG", "SHORT"):
            counts["unknown"] += 1
            continue
        points = (float(exit_price) - float(entry)) * (1 if row["signal"] == "LONG" else -1)
        if not math.isfinite(points):
            counts["unknown"] += 1
        else:
            counts["wins" if points > 0 else "losses" if points < 0 else "breakeven"] += 1
    total = counts["wins"] + counts["losses"] + counts["breakeven"]
    return {**counts, "win_rate": counts["wins"] / total * 100 if total else None}


def outcome_summary(rows):
    counts = alert_outcomes(rows)
    totals = dollar_summary(rows)
    rate = "--" if counts["win_rate"] is None else f'{counts["win_rate"]:.1f}%'
    st.markdown("**Win / loss summary**")
    st.html(f'''<style>
      .gx-outcomes {{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;padding:16px 0;border-block:1px solid #55585f;margin:6px 0 10px;}}
      .gx-outcomes strong {{display:block;font-size:24px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;}}
      @media(max-width:600px) {{.gx-outcomes {{grid-template-columns:repeat(2,minmax(0,1fr));}}}}
      </style><div class="gx gx-outcomes">
      <div><small>Wins</small><strong>{counts["wins"]}</strong></div>
      <div><small>Losses</small><strong>{counts["losses"]}</strong></div>
      <div><small>Breakeven</small><strong>{counts["breakeven"]}</strong></div>
      <div><small>Win rate</small><strong>{rate}</strong></div>
      <div><small>Total won</small><strong>{money(totals["won"])}</strong></div>
      <div><small>Total lost</small><strong>{money(totals["lost"])}</strong></div>
      <div><small>Net before fees</small><strong>{money(totals["net"])}</strong></div>
      </div>''')
    st.caption("USD estimates / 1 E-mini contract per signal / Before fees and execution slippage / Not account P&L."
               + (f' {totals["missing"]} unpriced outcomes excluded.' if totals["missing"] else ""))
    st.caption("Closed watch signals / Win rate includes breakeven; excludes missing outcomes."
               + (f' {counts["unknown"]} missing outcomes.' if counts["unknown"] else ""))


def monitoring_summary(status, rows, executed=None):
    counts = executed if executed is not None else alert_outcomes(rows)
    totals = executed if executed is not None else dollar_summary(rows)
    rate = "--" if counts["win_rate"] is None else f'{counts["win_rate"]:.1f}%'
    values = [("W/L/BE", f'{counts["wins"]}/{counts["losses"]}/{counts["breakeven"]}'),
              ("Win rate", rate), ("Won", money(totals["won"])),
              ("Lost", money(totals["lost"])), ("Net", money(totals["net"]))]
    metrics = "".join(f'<div><small>{label}</small><b>{value}</b></div>' for label, value in values)
    parts = [escape(part.strip()) for part in status.split("|")]
    primary = " &nbsp; ".join(parts[:2])
    secondary = " / ".join(parts[2:])
    note = "Matched closed bot trades / Net after reported fees and commissions / Unmatched fills excluded"
    if totals["missing"]:
        note += f' / {totals["missing"]} unpriced outcomes excluded'
    st.html(f'''<style>
      .gx.gx-monitor-line {{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px 18px;padding:6px 0;margin:0;background:transparent;color:inherit;border-bottom:1px solid #35373c;}}
      .gx-monitor-status {{display:flex;align-items:center;flex-wrap:wrap;gap:4px 10px;min-width:0;line-height:1.5;}}
      .gx-monitor-status strong {{font-size:12px;font-weight:600;}}
      .gx-monitor-status span {{font-size:12px;color:#929aa5;}}
      .gx-monitor-summary {{min-width:0;margin-left:auto;}}
      .gx-monitor-summary .gx-outcomes {{display:flex;align-items:center;flex-wrap:wrap;gap:4px 12px;margin:0;padding:0;border:0;}}
      .gx-monitor-summary .gx-outcomes > div {{display:flex;align-items:baseline;gap:5px;padding:0;min-width:0;}}
      .gx-monitor-summary .gx-outcomes > div:last-child {{padding-right:0;}}
      .gx-monitor-summary small {{font-size:11px;color:#929aa5;}}
      .gx-monitor-summary b {{font-size:13px;font-weight:650;font-variant-numeric:tabular-nums;}}
      .gx-monitor-summary .gx-outcomes > div:last-child b {{color:{'#65d6bc' if totals['net'] >= 0 else '#f28c98'};}}
      @media(max-width:600px) {{.gx-monitor-summary {{margin-left:0;}}}}
      </style><div class="gx gx-monitor-line">
      <div class="gx-monitor-status"><strong>{primary}</strong><span>{secondary}</span></div>
      <div class="gx-monitor-summary" title="{escape(note)}"><div class="gx-outcomes">{metrics}</div></div>
      </div>''')


def monitor_signal_label(symbol, strategy, signal, history, jobs):
    direction = signal.get("signal", "WAIT")
    if direction not in ("LONG", "SHORT"):
        return direction
    matching = [row for row in history if row.get("symbol") == symbol
                and row.get("strategy") == strategy and row.get("signal") == direction
                and signal.get("setup_time") and row.get("setup_time") == signal["setup_time"]]
    row = max(matching, key=lambda row: row["id"], default={})
    job = jobs.get(row.get("id"), {})
    return {"Closed": "WAIT", "Open": "IN TRADE / " + direction,
            "Closing": "EXIT PENDING", "Submitted": "ORDER PENDING", "Intent": "ORDER PENDING",
            "Unknown": "REVIEW REQUIRED", "Rejected": "NOT ENTERED"}.get(job.get("state"), "WATCH / " + direction)


def strategy_matrix(symbols, results, prices, healthy, market_open, history=(), jobs=None):
    headers = []
    for symbol in symbols:
        tick = prices.get(symbol)
        feed = feed_status(tick, market_open)
        timestamp = (tick.get("event_time") or tick.get("received_at")) if tick else None
        headers.append(f'<th scope="col"><b>{escape(symbol.replace("=F",""))}</b>'
                       f'<strong>{price(tick["price"] if tick else None)}</strong>'
                       f'<small title="{escape(ct(timestamp))}">{escape(feed)}</small></th>')
    rows = []
    for name in STRATEGIES:
        reference = next((results[(s,name)] for s in symbols if (s,name) in results), {})
        label = reference.get("focus_label",name)
        interval = reference.get("timeframe","15 min" if name == "CRT" else "1 min")
        cells = []
        for symbol in symbols:
            result = results.get((symbol,name),{})
            signal = result.get("signal",{})
            state = monitor_signal_label(symbol,name,signal,history,jobs or {}) if healthy else "OFFLINE"
            if healthy and market_open and feed_status(prices.get(symbol),market_open) != "Live":
                state = "DATA DELAYED"
            focus = escape(str(result.get("focus_value","--"))).replace(" - ","<br>").replace(" / ","<br>")
            reason = escape(str(signal.get("reason","Waiting for evaluation.")))
            cells.append(f'<td title="{reason}" tabindex="0"><b class="gx-matrix-state" style="color:{color(state)}">{escape(state)}</b>'
                         f'<span class="gx-matrix-focus">{focus}</span></td>')
        rows.append(f'<tr><th scope="row"><b>{escape(name)}</b><small>{escape(interval)}</small>'
                    f'<small>{escape(label)}</small></th>{"".join(cells)}</tr>')
    st.html(f'''<style>
      .gx-matrix-wrap {{width:100%;overflow-x:auto;border-top:1px solid #363e3b;}}
      table.gx-matrix {{width:100%;table-layout:fixed;border-collapse:collapse;color:#eef0f3;font-size:12px;letter-spacing:0;}}
      .gx-matrix th,.gx-matrix td {{padding:12px 6px;border-bottom:1px solid #303a36;text-align:right;vertical-align:top;overflow-wrap:anywhere;}}
      .gx-matrix th:first-child {{width:27%;text-align:left;padding-left:0;}}
      .gx-matrix th {{font-weight:400;}}
      .gx-matrix thead th {{padding-top:12px;padding-bottom:14px;background:#161e1b;}}
      .gx-matrix thead th:first-child {{padding-left:8px;}}
      .gx-matrix thead b {{font-size:13px;}}
      .gx-matrix strong {{display:block;font-size:14px;margin:5px 0;font-variant-numeric:tabular-nums;}}
      .gx-matrix small {{display:block;color:#a4b1ab;font-size:10px;line-height:1.5;margin-top:3px;}}
      .gx-matrix-state {{display:block;font-size:10px;line-height:1.4;min-height:17px;}}
      .gx-matrix-focus {{display:block;font-size:11px;line-height:1.6;margin-top:5px;font-variant-numeric:tabular-nums;}}
      .gx-matrix tbody tr:hover {{background:#19221f;}}
      .gx-matrix td:focus-visible {{outline:1px solid #65d6bc;outline-offset:-2px;}}
      </style><div class="gx-matrix-wrap"><table class="gx-matrix" aria-label="Strategy monitor">
      <thead><tr><th scope="col">Strategy</th>{''.join(headers)}</tr></thead>
      <tbody>{''.join(rows)}</tbody></table></div>''')


def symbol_monitor(symbol, results, tick, healthy, market_open, history=(), jobs=None):
    feed = feed_status(tick, market_open)
    rows = []
    for name in STRATEGIES:
        result = results.get((symbol, name), {})
        interval = result.get("timeframe", "15 min" if name == "CRT" else "1 min")
        signal = result.get("signal", {})
        state = monitor_signal_label(symbol, name, signal, history, jobs or {}) if healthy else "OFFLINE"
        if healthy and market_open and feed != "Live":
            state = "DATA DELAYED"
        focus = escape(str(result.get("focus_value", "--")))
        label = escape(result.get("focus_label", "Range" if name == "CRT" else "RSI / 30-70" if name == "Reversal" else name))
        rows.append(f'''<div class="gx-watch-strategy">
          <div class="gx-row-head"><span><b>{name}</b> <small>{interval}</small></span>
          <b class="gx-state" style="color:{color(state)}">{escape(state)}</b></div>
          <div class="gx-watch-focus"><small>{label}</small><b>{focus}</b></div>
          <small>{escape(signal.get('reason','')) if name not in ('CRT','Reversal') and state == 'WAIT' else ''}</small>
        </div>''')
    timestamp = tick.get("event_time") or tick.get("received_at") if tick else None
    st.html(f'''<style>
      .gx.gx-watch {{background:#17191d;color:#eef0f3;border:1px solid #36393f;border-radius:6px;padding:16px;margin-bottom:10px;}}
      .gx-watch-head {{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;}}
      .gx-watch-head strong {{font-size:22px;font-variant-numeric:tabular-nums;}}
      .gx-watch-head b {{font-size:19px;}}
      .gx-watch-time {{font-size:11px;color:#aeb5bf;margin:6px 0 14px;}}
      .gx-watch-strategy {{border-top:1px solid #36393f;padding:12px 0 0;margin-top:12px;}}
      .gx-watch-focus {{display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;margin-top:8px;font-size:13px;}}
      .gx-watch-focus b {{font-variant-numeric:tabular-nums;overflow-wrap:anywhere;}}
      </style><section class="gx gx-watch">
      <div class="gx-watch-head"><b>{escape(symbol.replace("=F", ""))}</b><strong>{price(tick["price"] if tick else None)}</strong></div>
      <div class="gx-watch-time">{feed} / {escape(ct(timestamp))}</div>
      {''.join(rows)}</section>''')


def history_card(row, tick=None, market_open=True, job=None, result=None, decisions=()):
    direction = row["signal"]
    trade_closed = bool(job and job.get("state") == "Closed")
    closed = row["status"] == "Closed"
    entry, exit_price = row.get("entry"), row.get("exit_price")
    points = (exit_price - entry) * (1 if direction == "LONG" else -1) if closed and entry is not None and exit_price is not None else None
    outcome = f"{points:+,.2f} pts" if points is not None else ("Closed" if closed else "Active")
    execution = "Watch only" if not job else {"Open":"IN TRADE", "Closing":"EXIT PENDING", "Submitted":"ORDER PENDING", "Closed":"TRADE CLOSED", "Rejected":"NOT ENTERED", "Unknown":"REVIEW REQUIRED", "Intent":"ORDER PENDING"}.get(job["state"],job["state"])
    outcome = money(result["net"]) + " net" if result else execution
    outcome_color = ("#65d6bc" if points >= 0 else "#f28c98") if points is not None else "#e5c477"
    if result:
        outcome_color = "#65d6bc" if result["net"] >= 0 else "#f28c98"
    adaptive = row.get("exit_mode") == "structure-v1"
    levels = [("Signal entry", entry), ("Protective stop", row.get("stop")), ("Target reference" if adaptive else "Target", row.get("target")), ("Observed exit", exit_price)]
    if job:
        levels[0] = ("Broker fill / " + job["symbol"], job.get("fill_price"))
        levels[3] = ("Broker exit", result.get("exit_price") if result else None)
    level_html = "".join(f'<div><small>{label}</small><strong>{price(value)}</strong></div>' for label, value in levels)
    exit_text = f'{escape(row.get("exit_reason", "Closed"))} / {escape(ct(row.get("exit_time")))}' if closed else (escape(row.get("management_status", "Holding")) if adaptive else "Awaiting stop or target")
    if closed and points is not None:
        exit_text += f" / Signal movement {points:+,.2f} pts (not account P&L)"
    if trade_closed:
        exit_text = "Trade closed / " + escape(ct(result["closed_at"] if result else job.get("closed_confirmed_at")))
        if not result:
            exit_text += " / Awaiting matched broker exit fills"
    management_html = ""
    if adaptive and not trade_closed:
        management_html = f'<div class="gx-evidence"><b>Adaptive exit / {int(row.get("management_minutes",1))}m structure</b><p>Original stop {price(row.get("initial_stop"))} / {"Reference target reached; no automatic exit" if row.get("target_reached") else "Reference target does not close the signal"}.</p><p>{escape(row.get("exit_evidence", "Waiting for completed candles after entry."))}</p></div>'
    evidence = escape(row.get("trigger_detail") or row.get("reason") or "")
    decision_html = ""
    if not job or job.get("state") == "Rejected":
        if job and job.get("error_message"):
            note = escape(str(job["error_message"]))
        elif decisions:
            note = "<br>".join(escape(ct(d["time"])) + " / " + escape(d["detail"]) for d in decisions)
        else:
            note = "No entry decision recorded for this alert on the selected account."
        decision_html = '<div class="gx-evidence" style="margin:12px 0;color:#ffaaa4;border-left-color:#f28c98"><b>Why no entry</b><p>' + note + '</p></div>'
    live_html = ""
    if not closed and not trade_closed:
        current = tick["price"] if tick else None
        traded = bool(job and job.get("state") in ("Open", "Closing", "Submitted", "Intent", "Unknown"))
        basis = job.get("fill_price") if traded else entry
        side = (1 if job.get("side") == 0 else -1) if traded and job.get("side") in (0, 1) else (1 if direction == "LONG" else -1)
        movement = (current - basis) * side if current is not None and basis is not None else None
        fresh = feed_status(tick, market_open)
        change = "Awaiting confirmed broker fill" if traded and basis is None else "Price unavailable"
        if movement is not None:
            change = (f"Move from broker fill: {movement:+,.2f} pts ({escape(row['symbol'].replace('=F', ''))} reference; not broker P&L)"
                      if traded else f"Signal movement: {movement:+,.2f} pts from entry")
        timestamp = tick.get("event_time") or tick.get("received_at") if tick else None
        live_html = f'<div class="gx-live-price"><span>{fresh} price <b>{price(current)}</b></span><span>{change}</span><small>{escape(ct(timestamp))}</small></div>'
    st.html(f'''<style>
      .gx.gx-history {{border:1px solid #35373c;border-radius:6px;padding:16px 18px;margin:0 0 12px;background:#14161a;color:#eef0f3;}}
      .gx-history-head {{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;}}
      .gx-history-title {{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:15px;}}
      .gx-history-title strong {{font-size:19px;}}
      .gx-history-levels {{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;border-block:1px solid #303237;margin:14px 0;padding:14px 0;}}
      .gx-history-levels strong {{display:block;font-size:19px;font-variant-numeric:tabular-nums;margin-top:4px;overflow-wrap:anywhere;}}
      .gx-history-foot {{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:12px;color:#afb5be;}}
      .gx-evidence-grid {{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;margin:14px 0;}}
      .gx-evidence-grid > :only-child {{grid-column:1 / -1;}}
      .gx-evidence {{min-width:0;overflow-wrap:anywhere;font-size:13px;color:#d3d8df;border-left:2px solid #e5c477;padding-left:12px;margin:0;line-height:1.6;}}
      .gx-evidence p {{font-size:13px;margin:4px 0 0;}}
      .gx-live-price {{display:flex;gap:16px;align-items:center;flex-wrap:wrap;font-size:13px;margin-top:14px;color:#d3d8df;}}
      .gx-live-price b {{font-size:19px;margin-left:8px;font-variant-numeric:tabular-nums;color:#eef0f3;}}
      @media(max-width:700px) {{.gx-history-levels {{grid-template-columns:repeat(2,minmax(0,1fr));}} .gx-evidence-grid {{grid-template-columns:1fr;gap:14px;}}}}
      </style><article class="gx gx-history">
      <div class="gx-history-head"><div class="gx-history-title">
        <strong>{escape(row["symbol"].replace("=F", ""))}</strong>
        <b style="color:{color(direction)}">{escape(direction)}</b>
        <span>{escape(row["strategy"])}</span></div>
        <b style="color:{outcome_color}">{outcome}</b></div>
      <small>#{row["id"]} / {escape(ct(row.get("entry_time")))} / {"Trade closed" if trade_closed else "Signal " + escape(row["status"])} / {escape(execution)} / Signal entry {price(entry)}</small>
      {live_html}
      {decision_html}
      <div class="gx-history-levels">{level_html}</div>
      <div class="gx-evidence-grid">
        <div class="gx-evidence"><b>Setup evidence</b><p>{evidence or 'Evidence was not recorded for this alert.'}</p></div>
        {management_html}
      </div>
      <div class="gx-history-foot"><span>{exit_text}</span><span>{escape(str(job['quantity']) + ' ' + job['symbol'] + ' / Order ' + str(job.get('order_id')) if job else 'Watch only / Excluded from P&L')}</span></div>
      </article>''')


def strategy_row(name, result, selected):
    signal = result["signal"]
    st.html(f"""<div class="gx gx-row {'selected' if selected else ''}">
      <div class="gx-row-head"><b>{escape(name)}</b><b style="color:{color(signal['signal'])}">{escape(signal['signal'])}</b></div>
      <small>{result['timeframe']} candles</small>
      <p>{escape(signal['reason'])}</p>
      <div class="gx-row-foot">{result['focus_label']} &nbsp; <b>{result['focus_value']}</b></div>
    </div>""")


def setup(name, result):
    signal = result["signal"]
    entry, stop, target = (signal.get(key) for key in ("entry", "stop", "target"))
    risk = abs(entry - stop) if entry is not None and stop is not None else None
    reward = abs(target - entry) if entry is not None and target is not None else None
    ratio = f"1 : {reward / risk:.2f}" if risk and reward is not None else "--"
    facts = [("Range low", price(signal['range_low'])), ("Range high", price(signal['range_high'])),
             ("Risk / reward", ratio), ("Risk (points)", price(risk))]
    if name == "Reversal":
        facts += [("RSI thresholds", "30 / 70"), ("Extreme minutes", str(signal.get('extreme_minutes', 0)))]
    rows = ''.join(f'<div class="gx-fact"><span class="gx-label">{label}</span><b>{value}</b></div>' for label, value in facts)
    st.html(f"""<section class="gx gx-detail">
      <div class="gx-detail-head"><h2>{escape(name)} setup</h2><small>{result['timeframe']} / Watch</small></div>
      <div class="gx-signal" style="color:{color(signal['signal'])}">{escape(signal['signal'])}</div>
      <p class="gx-reason">{escape(signal['reason'])}</p>
      <div class="gx-levels">
        <div><small>ENTRY</small><strong>{price(entry)}</strong></div>
        <div><small>STOP LOSS</small><strong style="color:#f28c98">{price(stop)}</strong></div>
        <div><small>TAKE PROFIT</small><strong style="color:#65d6bc">{price(target)}</strong></div>
      </div>
      <div class="gx-focus"><span class="gx-label">{result['focus_label']}</span><strong>{result['focus_value']}</strong></div>
      <div class="gx-facts">{rows}</div>
    </section>""")


def alert(symbol, name, result, updated, fresh):
    signal = result['signal']
    direction = signal['signal']
    active = direction in ('LONG', 'SHORT')
    title = {'LONG':'LONG alert', 'SHORT':'SHORT alert', 'WAIT':'Waiting for setup',
             'PAUSED':'Market paused', 'LONG WATCH':'Watching oversold', 'SHORT WATCH':'Watching overbought'}.get(direction, direction)
    if not fresh and active:
        title += ' / data delayed'
    timestamp = signal.get('setup_time')
    timestamp = datetime.fromisoformat(timestamp).astimezone(ZoneInfo('America/Chicago')).strftime('%b %d, %H:%M CT') if timestamp else '--'
    entry, stop, target = (signal.get(key) if active else None for key in ('entry','stop','target'))
    long = direction == 'LONG'
    stop_rule = f"Price {'<=' if long else '>='} {price(stop)}" if active else '--'
    target_rule = f"Price {'>=' if long else '<='} {price(target)}" if active else '--'
    reason = escape(signal['reason'])
    evidence = escape(signal.get('trigger_detail', 'Waiting for completed-candle evidence.'))
    st.html(f'''<section class="gx gx-detail">
      <div class="gx-detail-head"><h2>{escape(symbol.replace('=F',''))} / {escape(name)}</h2><small>{result['timeframe']} · Watch only</small></div>
      <div class="gx-signal" style="color:{color(direction)}">{escape(title)}</div>
      <p class="gx-reason">{reason}</p>
      <div class="gx-levels">
        <div><small>TRIGGER ENTRY</small><strong>{price(entry)}</strong></div>
        <div><small>STOP LOSS</small><strong style="color:#f28c98">{price(stop)}</strong></div>
        <div><small>TARGET</small><strong style="color:#65d6bc">{price(target)}</strong></div>
      </div>
      <div class="gx-focus"><span class="gx-label">Trigger evidence</span></div>
      <p class="gx-reason">{evidence}</p>
      <div class="gx-facts">
        <div class="gx-fact"><span>Signal candle start</span><b>{timestamp}</b></div>
        <div class="gx-fact"><span>Latest price</span><b>{price(signal.get('last_close'))}</b></div>
        <div class="gx-fact"><span>Stop condition</span><b>{escape(stop_rule)}</b></div>
        <div class="gx-fact"><span>Target condition</span><b>{escape(target_rule)}</b></div>
        <div class="gx-fact"><span>Data updated</span><b>{updated}</b></div>
        <div class="gx-fact"><span>Feed</span><b>{'Live' if fresh else 'Delayed / closed'}</b></div>
      </div>
    </section>''')
