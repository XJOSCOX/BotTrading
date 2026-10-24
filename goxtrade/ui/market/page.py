"""Live market chart page."""
import streamlit as st

from goxtrade.data.chart_history import chart_history, backfill_history
from goxtrade.ui.market.live_chart_component import render_live_candles
from goxtrade.data.live_store import reported_session_volume, ticks_for_symbol
from goxtrade.market.market_session import market_session
from goxtrade.data.symbol_store import load_symbols
from goxtrade.ui import shell


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
    timeframe = {'1 min': '1min', '3 min': '3min', '5 min': '5min', '15 min': '15min', '30 min': '30min', '1 hour': '1h'}[candle_label]
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
    shell.page_header("WORKSPACE / PRICE ACTION", "Market", "Live charts and session data")

    symbols = list(dict.fromkeys(['NQ=F', 'ES=F', 'YM=F'] + load_symbols()))
    if not symbols:
        st.info("Add symbols from the Dashboard first.")
        return

    with st.container(key="market_controls"):
        controls = st.columns([2, 1, 1, 1])
        with controls[0]:
            selected = st.multiselect("Symbols", symbols, default=['NQ=F'], max_selections=3,
                                     format_func=lambda symbol: symbol.replace('=F', ''), key='market_charts')
        with controls[1]:
            range_name = st.selectbox("Range", ["48H", "1D", "500 ticks", "1,000 ticks", "2,500 ticks", "5,000 ticks"], index=0)
        with controls[2]:
            candle_label = st.selectbox('Candles', ['1 min', '3 min', '5 min', '15 min', '30 min', '1 hour'])
        with controls[3]:
            chart_height = st.number_input('Chart height (px)', min_value=480, max_value=1400, value=800, step=40, key='market_chart_height')
    if not selected:
        st.info("Select up to three charts.")
        return
    for column, symbol in zip(st.columns(len(selected)), selected):
        with column:
            with st.container(key=f"market_chart_{symbol.replace('=', '_')}"):
                render_live_market_chart(symbol, range_name, compact=len(selected) > 1, candle_label=candle_label, height=int(chart_height))
