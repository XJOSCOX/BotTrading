import streamlit as st
import app_theme
from html import escape
import streamlit.components.v1 as components

import bot_store
import bot_view
import bot_monitor
from live_page import render_live
from chart_history import chart_history, backfill_history
from live_chart_component import render_live_candles
import live_process
from contracts import contract_for_symbol, is_valid_contract_id, save_contract
from crt_strategy import evaluate_crt, fifteen_minute_candles_from_ticks, minute_candles_from_ticks
from live_store import latest_quotes, latest_prices, price_history_for_symbol, ticks_for_symbol, reported_session_volume
from market_session import market_session, session_signal
from projectx_client import ProjectXAuthError, credentials_present, login, save_credentials
from refresh_contracts import refresh_active_contracts
from reversal_strategy import evaluate_reversal
from symbol_store import add_symbol, load_symbols, remove_symbol
from signal_lifecycle import track_signal, alert_history
from tv_lightweight_chart import lightweight_chart_html


st.set_page_config(page_title="GoXTrade", page_icon="GX", layout="wide")

# Live fragments retain their last values while the next update is calculated.
st.html("""<style>
[data-testid="stElementContainer"][data-stale="true"] {
    opacity: 1 !important;
    transition: none !important;
}
</style>""")


def format_price(value) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.2f}"


def signal_style(signal: str) -> dict:
    if signal == "LONG":
        return {"bg": "#0f3d2e", "border": "#22c55e", "text": "#bbf7d0"}
    if signal == "SHORT":
        return {"bg": "#4a1717", "border": "#ef4444", "text": "#fecaca"}
    if "WATCH" in signal:
        return {"bg": "#3f3111", "border": "#f59e0b", "text": "#fde68a"}
    return {"bg": "#1f2937", "border": "#64748b", "text": "#e5e7eb"}


def render_signal_card(signal: dict, strategy: str, timeframe: str) -> None:
    style = signal_style(signal["signal"])
    st.markdown(
        f"""
        <div style="
            border: 1px solid {style['border']};
            background: {style['bg']};
            border-radius: 8px;
            padding: 16px 18px;
            margin: 0 0 10px 0;
        ">
            <div style="font-size: 12px; color: #aeb7c4; text-transform: uppercase; letter-spacing: .08em;">
                {strategy} / {timeframe}
            </div>
            <div style="font-size: 38px; line-height: 1.1; font-weight: 800; color: {style['text']};">
                {signal['signal']}
            </div>
            <div style="font-size: 14px; color: #d7dde6; margin-top: 8px;">
                {signal['reason']}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def prepare_candle_display(candles):
    display = candles.tail(8).sort_values("time", ascending=False).copy()
    if display.empty:
        return display
    display["time"] = display["time"].dt.tz_convert("America/Chicago").dt.strftime("%Y-%m-%d %H:%M CT")
    numeric_columns = ["open", "high", "low", "close", "volume", "rsi"]
    for column in numeric_columns:
        if column in display:
            display[column] = display[column].round(2)
    columns = ["time", "open", "high", "low", "close", "tick_count"]
    if "rsi" in display:
        columns.append("rsi")
    display = display[[column for column in columns if column in display]]
    display = display.rename(columns={"tick_count": "ticks"})
    return display


def render_status_strip(state: dict, symbol: str, strategy: str, timeframe: str) -> None:
    status = "Running" if state["running"] else "Stopped"
    border = "#22c55e" if state["running"] else "#64748b"
    st.markdown(
        f"""
        <div style="
            display:grid;
            grid-template-columns: repeat(4, minmax(120px, 1fr));
            gap:10px;
            margin: 4px 0 12px 0;
        ">
          <div style="border:1px solid {border};border-radius:8px;padding:10px 12px;background:#111822;">
            <div style="color:#8b96a7;font-size:11px;text-transform:uppercase;">Status</div>
            <div style="color:#f8fafc;font-size:20px;font-weight:700;">{status}</div>
          </div>
          <div style="border:1px solid #263141;border-radius:8px;padding:10px 12px;background:#111822;">
            <div style="color:#8b96a7;font-size:11px;text-transform:uppercase;">Symbol</div>
            <div style="color:#f8fafc;font-size:20px;font-weight:700;">{symbol}</div>
          </div>
          <div style="border:1px solid #263141;border-radius:8px;padding:10px 12px;background:#111822;">
            <div style="color:#8b96a7;font-size:11px;text-transform:uppercase;">Strategy</div>
            <div style="color:#f8fafc;font-size:20px;font-weight:700;">{strategy}</div>
          </div>
          <div style="border:1px solid #263141;border-radius:8px;padding:10px 12px;background:#111822;">
            <div style="color:#8b96a7;font-size:11px;text-transform:uppercase;">Timeframe</div>
            <div style="color:#f8fafc;font-size:20px;font-weight:700;">{timeframe}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_decision_console(signal: dict, strategy: str, timeframe: str, focus_label: str, focus_value: str, state: dict, candle_count: int) -> None:
    style = signal_style(signal["signal"])
    status = "Running" if state["running"] else "Stopped"
    metrics = [
        ("Last", format_price(signal["last_close"])),
        ("Focus", focus_value),
        ("Entry", format_price(signal["entry"])),
        ("Stop", format_price(signal["stop"])),
        ("Target", format_price(signal["target"])),
        ("Candles", str(candle_count)),
        ("Mode", state["mode"]),
        ("Bot", status),
    ]
    metric_html = "\n".join(
        f"""
        <div class="bot-metric">
          <div class="bot-label">{label}</div>
          <div class="bot-value">{value}</div>
        </div>
        """
        for label, value in metrics
    )
    st.markdown(
        f"""
        <style>
          .bot-console {{
            display: grid;
            grid-template-columns: minmax(320px, 0.9fr) minmax(520px, 1.6fr);
            gap: 12px;
            margin: 8px 0 14px 0;
          }}
          .bot-decision {{
            border: 1px solid {style['border']};
            background: {style['bg']};
            border-radius: 8px;
            padding: 18px 20px;
            min-height: 158px;
          }}
          .bot-meta {{
            color: #9aa5b5;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: .08em;
            font-weight: 700;
          }}
          .bot-signal {{
            color: {style['text']};
            font-size: 42px;
            line-height: 1.05;
            font-weight: 850;
            margin-top: 8px;
          }}
          .bot-reason {{
            color: #d7dde6;
            font-size: 14px;
            line-height: 1.45;
            margin-top: 10px;
            max-width: 780px;
          }}
          .bot-metric-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(120px, 1fr));
            gap: 10px;
          }}
          .bot-metric {{
            border: 1px solid #253042;
            background: #111822;
            border-radius: 8px;
            padding: 13px 14px;
            min-height: 74px;
          }}
          .bot-label {{
            color: #8894a6;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: .04em;
            font-weight: 700;
          }}
          .bot-value {{
            color: #f8fafc;
            font-size: 22px;
            line-height: 1.2;
            font-weight: 760;
            margin-top: 7px;
            overflow-wrap: anywhere;
          }}
          @media (max-width: 1100px) {{
            .bot-console {{
              grid-template-columns: 1fr;
            }}
            .bot-metric-grid {{
              grid-template-columns: repeat(2, minmax(120px, 1fr));
            }}
          }}
        </style>
        <div class="bot-console">
          <section class="bot-decision">
            <div class="bot-meta">{strategy} / {timeframe} / {focus_label}</div>
            <div class="bot-signal">{signal['signal']}</div>
            <div class="bot-reason">{signal['reason']}</div>
          </section>
          <section class="bot-metric-grid">
            {metric_html}
          </section>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_levels_panel(levels: dict) -> None:
    rows = "\n".join(
        f"""
        <div class="level-row">
          <span>{name}</span>
          <strong>{value}</strong>
        </div>
        """
        for name, value in levels.items()
    )
    st.markdown(
        f"""
        <style>
          .levels-panel {{
            border: 1px solid #263141;
            background: #0f141d;
            border-radius: 8px;
            padding: 14px 16px;
          }}
          .levels-title {{
            color: #f8fafc;
            font-size: 18px;
            font-weight: 760;
            margin-bottom: 10px;
          }}
          .level-row {{
            display: flex;
            justify-content: space-between;
            gap: 18px;
            border-top: 1px solid #1f2937;
            padding: 10px 0;
            color: #aeb7c4;
            font-size: 13px;
          }}
          .level-row:first-of-type {{
            border-top: 0;
          }}
          .level-row strong {{
            color: #f8fafc;
            font-weight: 720;
            text-align: right;
          }}
        </style>
        <section class="levels-panel">
          <div class="levels-title">Setup Levels</div>
          {rows}
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> str:
    st.sidebar.html('<div class="gx-brand"><span class="gx-brand-mark">GX</span><div><strong>GoXTrade</strong><small>TRADING WORKSPACE</small></div></div>')
    pages = {"Dashboard", "Market", "Bot", "Live"}
    if "page" not in st.session_state:
        requested_page = st.query_params.get("page", "Dashboard")
        st.session_state.page = requested_page if requested_page in pages else "Dashboard"

    def navigate(page):
        st.session_state.page = page
        st.query_params["page"] = page
    with st.sidebar.container(key="main_navigation"):
        for name, icon in (("Dashboard", "dashboard"), ("Market", "candlestick_chart"),
                           ("Bot", "smart_toy"), ("Live", "bolt")):
            st.button(name, icon=f":material/{icon}:", width="stretch",
                      type="primary" if st.session_state.page == name else "secondary",
                      on_click=navigate, args=(name,))
    st.sidebar.html('<div class="gx-nav-foot"><b>Practice / Leader</b><br>Market times in Chicago (CT)</div>')
    return st.session_state.page


def render_dashboard() -> None:
    st.title("Dashboard")
    from dashboard_view import render_statistics
    overview, settings = st.tabs(["Overview", "Symbols & connection"])
    with overview:
        with st.container(key="dashboard_overview"):
            render_statistics()
    with settings:
        render_dashboard_settings()


def render_dashboard_settings() -> None:

    symbols = load_symbols()
    add_col, count_col = st.columns([2, 1])

    with add_col:
        with st.form("add_symbol_form", clear_on_submit=True):
            symbol = st.text_input("Add symbol", placeholder="MNQ=F, AAPL, CME_MINI:MNQ1!")
            contract_id = st.text_input("Contract ID for live data", placeholder="CON.F.US.MNQ.U26")
            submitted = st.form_submit_button("Add Symbol", width="stretch")
            if submitted:
                ok, message = add_symbol(symbol)
                normalized = symbol.strip().upper()
                if contract_id.strip():
                    if is_valid_contract_id(contract_id):
                        save_contract(normalized, contract_id)
                    else:
                        st.warning("Symbol saved, but the contract ID did not look valid.")
                if ok:
                    st.success(message)
                    st.rerun()
                else:
                    st.warning(message)

    with count_col:
        st.metric("Tracked Symbols", len(symbols))

    st.subheader("Live Feed")
    live = live_process.status()
    status_cols = st.columns([1, 1, 1, 2])
    status_cols[0].metric("Collector", "Running" if live["running"] else "Stopped")
    status_cols[1].metric("PID", live["pid"] or "-")
    status_cols[2].metric("Symbols", len(symbols))
    status_cols[3].caption("Uses ProjectX/TopstepX SignalR market data.")

    with st.expander("API credentials", expanded=not credentials_present()):
        st.caption("Saved locally to `.env` in this project.")
        with st.form("api_credentials_form"):
            username = st.text_input("TopstepX username")
            api_key = st.text_input("ProjectX API key", type="password")
            save_clicked = st.form_submit_button("Save Credentials", width="stretch")
            if save_clicked:
                if username.strip() and api_key.strip():
                    save_credentials(username, api_key)
                    st.success("Credentials saved.")
                    st.rerun()
                else:
                    st.warning("Enter both username and API key.")

        if st.button("Test Login", width="stretch", disabled=not credentials_present()):
            try:
                token = login()
                st.success(f"Login OK. Token received ({len(token)} chars).")
            except (ProjectXAuthError, Exception) as error:
                st.error(str(error))

        if st.button("Refresh Active Contracts", width="stretch", disabled=not credentials_present()):
            try:
                updates = refresh_active_contracts()
                st.success(f"Updated {len(updates)} contract mappings.")
                st.rerun()
            except Exception as error:
                st.error(str(error))

    start_col, stop_col = st.columns(2)
    with start_col:
        if st.button("Start Live Feed", width="stretch", disabled=live["running"] or not credentials_present()):
            result = live_process.start()
            st.info(result["message"])
            st.rerun()
    with stop_col:
        if st.button("Stop Live Feed", width="stretch", disabled=not live["running"]):
            result = live_process.stop()
            st.info(result["message"])
            st.rerun()

    quote_frame = latest_quotes()
    if not quote_frame.empty:
        st.dataframe(quote_frame, width="stretch", hide_index=True)

    with st.expander("Live feed logs", expanded=False):
        st.code(live_process.tail(live["stdout_log"]), language="text")
        error_tail = live_process.tail(live["stderr_log"])
        if error_tail:
            st.code(error_tail, language="text")

    if not symbols:
        st.info("Add a symbol to begin.")
        return

    st.subheader("Symbols")
    cols = st.columns(4)
    for index, symbol in enumerate(symbols):
        with cols[index % 4]:
            with st.container(border=True):
                st.markdown(f"### {symbol}")
                st.caption(contract_for_symbol(symbol) or "No live contract ID")
                if st.button("Remove", key=f"remove_{symbol}", width="stretch"):
                    remove_symbol(symbol)
                    st.rerun()


@st.cache_data(ttl=300, show_spinner=False)
def ensure_chart_backfill(symbol):
    try:
        return backfill_history(symbol), None
    except Exception:
        return 0, "Historical API unavailable; showing saved data."


@st.fragment(run_every="1s")
def render_live_market_chart(symbol: str, range_name: str, compact: bool = False, candle_label: str = '1 min', height: int = 800) -> None:
    session = market_session()
    _, history_error = ensure_chart_backfill(symbol)
    if history_error:
        st.caption(history_error)
    if range_name in ("48H", "1D"):
        data = chart_history(symbol, hours=48 if range_name == "48H" else 24)
        data['price'] = data['close']
        range_label = range_name
    else:
        tick_limit = int(range_name.replace(" ticks", "").replace(",", ""))
        data = ticks_for_symbol(symbol, limit=tick_limit)
        range_label = range_name

    if data.empty:
        st.warning("No live ticks yet. Start the Live Feed from the Dashboard and confirm credentials/contract ID.")
        return

    latest = data.iloc[-1]
    latest_ticks = ticks_for_symbol(symbol, limit=1)
    last_time = (latest_ticks['time'].max() if not latest_ticks.empty else data['time'].max()).tz_convert("America/Chicago")
    age = max(0, (session["time"] - last_time).total_seconds())
    if session["is_open"] and age > 60:
        st.warning(f"Feed delayed: last price is {int(age // 60)} minutes old. Waiting for fresh market data.")
    first_price = float(data["open"].iloc[0] if 'open' in data else data["price"].iloc[0])
    latest_price = float(latest["price"])
    change = latest_price - first_price
    change_pct = (change / first_price * 100) if first_price else 0

    volume = reported_session_volume(symbol)
    metrics = [
        ('Price', f'{latest_price:,.2f}', symbol.replace('=F', ''), ''),
        ('Change', f'{change_pct:+.2f}%', f'{change:+.2f} points over selected range', '#65d6bc' if change >= 0 else '#f28c98'),
        ('High', f"{float(data['high' if 'high' in data else 'price'].max()):,.2f}", 'Selected range high', ''),
        ('Low', f"{float(data['low' if 'low' in data else 'price'].min()):,.2f}", 'Selected range low', ''),
        ('Volume', f'{volume:,.0f}' if volume is not None else '--', 'Latest exchange-reported session volume', ''),
    ]
    timeframe = {'1 min': '1min', '5 min': '5min', '15 min': '15min', '30 min': '30min', '1 hour': '1h'}[candle_label]
    render_live_candles(data, symbol, height=height, range_label=range_label,
                        timeframe=timeframe, candle_label=candle_label, metrics=metrics)


def render_session_status() -> dict:
    session = market_session()
    local = session["time"]
    st.caption(f"{session['name']} | {local:%a %I:%M:%S %p} CT | Standard futures schedule")
    with st.expander("Session hours (CT)"):
        st.markdown("Regular: **8:30 AM - 3 PM**  \nExtended: **3 PM - 4 PM**  \nDaily break: **4 PM - 5 PM**  \nOvernight: **5 PM - 8:30 AM**  \nWeekend closed: **Friday 4 PM - Sunday 5 PM**")
        st.caption("Exchange holidays and special halts may change these hours.")
    return session


def render_market() -> None:
    st.title("Market")

    symbols = list(dict.fromkeys(['NQ=F', 'ES=F', 'YM=F'] + load_symbols()))
    if not symbols:
        st.info("Add symbols from the Dashboard first.")
        return

    controls = st.columns([2, 1, 1, 1])
    with controls[0]:
        selected = st.multiselect("Symbols", symbols, default=['NQ=F'], max_selections=3,
                                 format_func=lambda symbol: symbol.replace('=F', ''), key='market_charts')
    with controls[1]:
        range_name = st.selectbox("Range", ["48H", "1D", "500 ticks", "1,000 ticks", "2,500 ticks", "5,000 ticks"], index=0)
    with controls[2]:
        candle_label = st.selectbox('Candles', ['1 min', '5 min', '15 min', '30 min', '1 hour'])
    with controls[3]:
        chart_height = st.number_input('Chart height (px)', min_value=480, max_value=1400, value=800, step=40, key='market_chart_height')
    if not selected:
        st.info("Select up to three charts.")
        return
    for column, symbol in zip(st.columns(len(selected)), selected):
        with column:
            render_live_market_chart(symbol, range_name, compact=len(selected) > 1, candle_label=candle_label, height=int(chart_height))


@st.fragment(run_every="1s")
def render_bot_status(symbol: str, strategies: list[str]) -> None:
    session = market_session()
    data = price_history_for_symbol(symbol, hours=24)
    latest = data['time'].max() if not data.empty else None
    fresh = latest is not None and 0 <= (session['time'] - latest).total_seconds() <= 60
    feed = 'Live' if fresh else ('Delayed' if session['is_open'] else 'Market closed')
    updated = latest.tz_convert('America/Chicago').strftime('%H:%M:%S CT') if latest is not None else '--'
    last = bot_view.price(data.iloc[-1]['price']) if not data.empty else '--'
    st.html(f'''<div class="gx gx-ticker">
      <div><small>CONTRACT</small><strong>{escape(symbol)}</strong></div>
      <div><small>LAST PRICE</small><strong>{last}</strong></div>
      <div><small>SESSION</small><b>{session['name']}</b></div>
      <div><small>FEED / LAST UPDATE</small><b style="color:{'#65d6bc' if fresh else '#e5c477'}">{feed}</b> &nbsp; {updated}</div>
    </div>''')
    results = {strategy: evaluate_strategy_status(symbol, strategy, session, data) for strategy in strategies}
    if st.session_state.get("focused_strategy") not in strategies:
        st.session_state.focused_strategy = strategies[0]
    left, right = st.columns([1, 2.2], gap="large")
    with left:
        st.html('<div class="gx-section">STRATEGIES</div>')
        st.radio("Alert strategy", strategies, key="focused_strategy", label_visibility="collapsed")
        focused_strategy = st.session_state.focused_strategy or strategies[0]
        for strategy, result in results.items():
            bot_view.strategy_row(strategy, result, strategy == focused_strategy)
    with right:
        focused = focused_strategy
        result = results[focused]
        bot_view.alert(symbol, focused, result, updated, fresh)


evaluate_strategy_status = bot_monitor.evaluate_strategy_status


def render_strategy_summary(signal, strategy, timeframe, focus_label, focus_value):
    style = signal_style(signal["signal"])
    levels = [("Entry", signal["entry"]), ("Stop", signal["stop"]), ("Target", signal["target"])]
    level_html = "".join(f'<div><span>{name}</span><strong>{format_price(value)}</strong></div>' for name, value in levels)
    extra = f'<span>Extreme minutes</span><b>{signal.get("extreme_minutes", 0)}</b>' if strategy == "Reversal" else ""
    st.html(f"""
        <style>
        .strategy-board {{border-top:3px solid {style['border']};padding:18px 0 12px;letter-spacing:0;}}
        .strategy-heading {{display:flex;align-items:center;justify-content:space-between;gap:12px;}}
        .strategy-heading h3 {{margin:0;font-size:22px;}}
        .strategy-board span {{color:#aab2bd;font-size:13px;}}
        .strategy-signal {{font-size:32px;font-weight:750;color:{style['text']};margin:18px 0 4px;}}
        .strategy-reason {{min-height:44px;font-size:14px;color:#cbd1da;line-height:1.5;}}
        .strategy-focus {{padding:16px 0;border-top:1px solid #333842;margin-top:12px;}}
        .strategy-focus strong {{display:block;font-size:22px;margin-top:5px;overflow-wrap:anywhere;}}
        .strategy-levels {{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;padding:16px 0;border-block:1px solid #333842;}}
        .strategy-levels strong {{display:block;font-size:22px;margin-top:6px;overflow-wrap:anywhere;}}
        .strategy-details {{display:grid;grid-template-columns:1fr auto;gap:10px;padding-top:16px;font-size:14px;}}
        @media(max-width:600px) {{.strategy-levels strong {{font-size:18px;}}}}
        </style>
        <section class="strategy-board" style="border-color:{style['border']}">
          <div class="strategy-heading"><span>{timeframe}</span><strong style="color:{style['text']}">{escape(signal['signal'])}</strong></div>
          <div class="strategy-focus"><span>{focus_label}</span><strong>{focus_value}</strong></div>
          <div class="strategy-levels">{level_html}</div>
          <div class="strategy-details">
            <span>Last price</span><b>{format_price(signal['last_close'])}</b>
            <span>Range high</span><b>{format_price(signal['range_high'])}</b>
            <span>Range low</span><b>{format_price(signal['range_low'])}</b>{extra}
          </div>
        </section>""")


@st.fragment(run_every='1s')
def render_monitor_history(account_profile="practice"):
    import pandas as pd
    session = market_session()
    results = bot_monitor.read_status()
    prices = latest_prices(bot_monitor.SYMBOLS)
    now = pd.Timestamp.now(tz="UTC")
    healthy = all(
        pair in results and (now - pd.Timestamp(results[pair]["updated_at"])).total_seconds() < 30
        for pair in ((s, t) for s in bot_monitor.SYMBOLS for t in bot_monitor.STRATEGIES)
    )
    history = alert_history(10000)
    history = [row for row in history if row["symbol"] in bot_monitor.SYMBOLS and row["strategy"] in bot_monitor.STRATEGIES]
    active = bot_view.recent_alerts([row for row in history if row["status"] == "Active"])
    closed = bot_view.recent_alerts([row for row in history if row["status"] == "Closed"])
    import practice_executor, practice_history, executed_results
    if account_profile == "leader":
        import leader_execution
        execution = leader_execution.snapshot()
        fills = leader_execution.history()[1]
    else:
        execution = practice_executor.snapshot()
        fills = practice_history.snapshot()[1]
    jobs = execution[2]
    import leader_execution
    other_profile = "leader" if account_profile == "practice" else "practice"
    other_jobs = (leader_execution.snapshot() if other_profile == "leader" else practice_executor.snapshot())[2]
    other_open = [j for j in other_jobs if j.get("state") in ("Open", "Closing")]
    if other_open:
        details = ", ".join(f"{j['quantity']} {j['symbol']} / alert #{j['alert_id']}" for j in other_open)
        st.warning(f"{other_profile.title()} has an open trade: {details}. Current view: {account_profile.title()}. Select {other_profile.title()} in Account view for its trade status and P&L.")
    matched = executed_results.results(jobs, fills)
    by_alert = {j["alert_id"]: j for j in jobs}
    import bot_audit
    entry_decisions = bot_audit.entry_decisions([row["id"] for row in history], account_profile)
    active, closed = bot_view.prioritized_alerts(history, by_alert)
    bot_view.monitoring_summary(
        f"{'Monitoring' if healthy else 'Monitor offline / starting'} | {account_profile.title()} | NQ, ES, YM | All strategies | {session['name']} | {session['time']:%H:%M:%S} CT",
        closed, executed_results.summary(matched),
    )
    if not healthy:
        st.warning("Monitoring is not updating. The live-feed process must be running.")
    left, right = st.columns([1.25, 1.75], gap="medium")
    with left:
        st.subheader("Strategy watch")
        if account_profile == "practice":
            st.session_state["bot_enable_mym"] = practice_executor.snapshot()[0].get("enable_mym", False)
            st.toggle("Enable MYM trading", key="bot_enable_mym",
                      on_change=lambda: practice_executor.set_mym_enabled(st.session_state["bot_enable_mym"]),
                      help="Allows new MYM Practice entries when automation is running. Disabling does not stop management of an existing position.")
        else:
            st.caption("Leader execution: MNQ / MES / MYM." if execution[0].get("enable_mym") else "Leader execution: MNQ / MES. MYM watch only.")
        bot_view.strategy_matrix(bot_monitor.SYMBOLS, results, prices, healthy, session["is_open"], history, by_alert)
    with right:
        st.subheader("Alert history")
        st.caption(account_profile.title()+" execution: " + execution[1].get("message", "Worker unavailable"))
        st.markdown(f"**Active alerts ({len(active)})**")
        if not active:
            st.info("No active alerts. Monitoring for the next setup.")
        for row in active:
            bot_view.history_card(row, prices.get(row["symbol"]), session["is_open"], by_alert.get(row["id"]), matched.get(row["id"]), entry_decisions.get(row["id"], []))
        with st.expander(f"Past alerts ({len(closed)})", expanded=False):
            symbol_col, strategy_col = st.columns(2)
            symbol_filter = symbol_col.selectbox("Symbol", ["All", "NQ", "ES", "YM"], key="alert_symbol_filter")
            strategy_filter = strategy_col.selectbox("Strategy", ["All", *bot_monitor.STRATEGIES], key="alert_strategy_filter")
            filtered = [row for row in closed
                        if (symbol_filter == "All" or row["symbol"].replace("=F", "") == symbol_filter)
                        and (strategy_filter == "All" or row["strategy"] == strategy_filter)]
            if not filtered:
                st.caption("No past alerts." if not closed else "No past alerts match these filters.")
            pages = max(1, (len(filtered) + 11) // 12)
            page = st.selectbox("Page", range(1, pages + 1), key="alert_history_page") if pages > 1 else 1
            for row in filtered[(page - 1) * 12:page * 12]:
                bot_view.history_card(row, job=by_alert.get(row["id"]), result=matched.get(row["id"]), decisions=entry_decisions.get(row["id"], []))


def render_bot() -> None:
    bot_view.theme()
    st.html('<header class="gx gx-top"><h1>Strategy alerts</h1><span class="gx-mode">Watch signals / Account execution</span></header>')
    import bot_workspace, leader_execution, practice_executor
    if "bot_account_view" not in st.session_state:
        leader_state = leader_execution.snapshot()
        leader_active = leader_state[0].get("enabled") or any(j.get("state") in ("Open", "Closing", "Submitted", "Unknown", "Intent") for j in leader_state[2])
        st.session_state["bot_account_view"] = "leader" if leader_active else "practice"
    account_profile = st.selectbox("Account view",["practice","leader"],format_func=str.title,key="bot_account_view",help="Changes the displayed account only; does not start or switch execution.")
    with st.expander("Strategy settings / shared monitor"):
        import strategy_settings
        with st.form("shared_strategy_settings"):
            choices = [5,15,30]
            orb_minutes = st.selectbox("Opening range (minutes)", choices,index=choices.index(strategy_settings.read_orb_minutes()))
            stop_choices = [5,10,15]
            stop_minutes = st.selectbox("Stop & trailing candles (minutes)",stop_choices,index=stop_choices.index(strategy_settings.read_stop_minutes()))
            if st.form_submit_button("Save strategy settings",icon=":material/save:"):
                strategy_settings.save_orb_minutes(orb_minutes)
                strategy_settings.save_stop_minutes(stop_minutes)
                st.success("Saved for new setups. Existing signals retain their original range and exit timeframe.")
    monitor, operations, research, inbox = st.tabs(["Monitor", "Controls & review", "Replay lab", "Notifications"])
    with monitor:
        render_monitor_history(account_profile)
    with operations:
        with st.container(key="bot_operations"):
            bot_workspace.theme()
            if account_profile == "leader":
                from leader_page import render
                render()
            else:
                a,b = st.columns([1,1.6],gap="large")
                with a:
                    bot_workspace.controls()
                with b:
                    bot_workspace.operations_status()
                bot_workspace.timeline()
    with research:
        with st.container(key="bot_research"):
            bot_workspace.replay()
    with inbox:
        bot_workspace.notifications(account_profile)


def main() -> None:
    app_theme.apply()
    if credentials_present():
        from practice_history import ensure_worker
        ensure_worker()
    page = render_sidebar()
    if page == "Dashboard":
        render_dashboard()
    elif page == "Market":
        render_market()
    elif page == "Live":
        render_live()
    else:
        render_bot()


if __name__ == "__main__":
    main()
