"""Dashboard page and local connection settings."""
import streamlit as st

from goxtrade.runtime import live_process
from goxtrade.execution.contracts import contract_for_symbol, is_valid_contract_id, save_contract
from goxtrade.data.live_store import latest_quotes
from goxtrade.execution.projectx_client import ProjectXAuthError, credentials_present, login, save_credentials
from goxtrade.execution.refresh_contracts import refresh_active_contracts
from goxtrade.data.symbol_store import add_symbol, load_symbols, remove_symbol
from goxtrade.ui import shell


def render_dashboard() -> None:
    shell.page_header("WORKSPACE / OVERVIEW", "Dashboard", "Executed trades and account health")
    from goxtrade.ui.dashboard.dashboard_view import render_statistics
    overview, settings = st.tabs(["Overview", "Symbols & connection"])
    with overview:
        with st.container(key="dashboard_overview"):
            render_statistics()
            with st.expander("Strategy research & execution comparison"):
                from goxtrade.ui.bot.strategy_research import render_comparison
                render_comparison()
    with settings:
        with st.container(key="dashboard_settings"):
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
