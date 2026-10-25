"""Explicit credential and feed management, separate from performance analytics."""
import streamlit as st
from goxtrade.ui.shell import page_header
from goxtrade.execution.projectx_client import credentials_present, save_credentials, login
from goxtrade.runtime import live_process


def render():
    page_header("Settings", "Connection", "Local API credentials, feed and instruments", "LOCAL SETTINGS")
    api, feed, symbols = st.tabs(["API credentials", "Market feed", "Instruments"])
    with api:
        left, right = st.columns([1.5, 1], gap="large")
        with left:
            st.subheader("Topstep / ProjectX")
            st.caption("Credentials configured" if credentials_present() else "No API credentials configured")
            with st.form("connection_credentials", clear_on_submit=True):
                username = st.text_input("TopstepX username", autocomplete="off")
                key = st.text_input("API key", type="password", autocomplete="new-password")
                save = st.form_submit_button("Save credentials", icon=":material/key:")
            if save:
                try:
                    save_credentials(username, key)
                    st.session_state.pop("account_directory", None)
                    st.success("Credentials saved locally. Restart workers after changing the login.")
                except (ValueError, OSError):
                    st.error("Enter a valid username and API key. Credentials could not be saved.")
            if st.button("Test connection", icon=":material/wifi:", disabled=not credentials_present()):
                try:
                    login()
                    st.success("Authentication succeeded. No orders submitted.")
                except Exception:
                    st.error("Authentication failed. Check the username, API key and network.")
        with right:
            st.subheader("Credential security")
            st.caption("Stored in this project's ignored .env file. Existing keys are never displayed. Saving credentials does not start the feed, enable trading or change copying.")
            st.warning("Pause and verify accounts before changing credentials used by running workers.")
    with feed:
        state = live_process.status()
        a, b, c = st.columns(3)
        a.metric("Market worker", "Running" if state["running"] else "Stopped")
        b.metric("Process ID", str(state["pid"] or "--"))
        from goxtrade.market.market_session import market_session
        c.metric("Market session", market_session()["name"])
        start, stop = st.columns(2)
        from goxtrade.config.execution_identity import restart_required
        if start.button("Start market worker", icon=":material/play_arrow:", disabled=state["running"] or not credentials_present() or restart_required(), width="stretch"):
            st.info(live_process.start()["message"])
            st.rerun()
        if stop.button("Pause & stop trading workers", icon=":material/stop:", disabled=not credentials_present(), width="stretch"):
            try:
                from goxtrade.runtime.manage_app import stop_workers
                stop_workers()
                st.success("Trading workers stopped. The account-maintenance workspace remains open.")
                st.rerun()
            except Exception:
                st.error("Stop blocked. Pause both profiles, resolve orders, and verify both accounts are flat. Exit management remains running.")
        st.caption("Workers run independently of browser navigation. Start/Pause execution remains explicit.")
        with st.expander("Worker logs"):
            st.code(live_process.tail(state["stdout_log"]), language="text")
            st.code(live_process.tail(state["stderr_log"]), language="text")
    with symbols:
        from goxtrade.data.symbol_store import add_symbol, load_symbols, remove_symbol
        from goxtrade.execution.contracts import contract_for_symbol, is_valid_contract_id, save_contract
        from goxtrade.execution.refresh_contracts import refresh_active_contracts
        st.subheader("Watchlist & contract mappings")
        with st.form("connection_instrument"):
            a, b = st.columns(2)
            symbol = a.text_input("Symbol", placeholder="NQ=F")
            contract = b.text_input("Contract ID", placeholder="CON.F.US.ENQ.Z26")
            submit = st.form_submit_button("Add instrument", icon=":material/add:")
        if submit:
            if contract.strip() and not is_valid_contract_id(contract.strip()):
                st.error("Invalid contract ID. No instrument added.")
            else:
                ok, message = add_symbol(symbol)
                if ok and contract.strip():
                    save_contract(symbol.strip().upper(), contract.strip())
                (st.success if ok else st.warning)(message)
        instruments = load_symbols()
        st.dataframe([{"Symbol": s, "Active contract": contract_for_symbol(s) or "Not mapped"} for s in instruments], hide_index=True, width="stretch")
        a, b = st.columns(2)
        selected = a.selectbox("Remove from watchlist", instruments, index=None, placeholder="Select instrument")
        if b.button("Remove instrument", icon=":material/delete:", disabled=selected is None):
            remove_symbol(selected)
            st.rerun()
        if st.button("Refresh active contracts", icon=":material/sync:", disabled=not credentials_present()):
            try:
                refresh_active_contracts()
                st.success("Contract mappings refreshed.")
            except Exception:
                st.error("Contract refresh failed. Existing mappings retained.")
