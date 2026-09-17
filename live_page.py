from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
import live_theme
from practice_page import render_practice, render_trade_history, render_order_attempts
from projectx_client import credentials_present
from live_accounts import search_accounts, load_preferences, quantities_for, save_quantities, MICROS, enabled_accounts, copy_role


def render_live():
    live_theme.apply()
    st.html('''<style>
    .st-key-live_workspace h1 {font-size:26px;padding:0 0 8px;}
    .st-key-live_workspace h3 {font-size:18px;padding:4px 0;}
    .st-key-live_workspace [data-testid="stMetricValue"] {font-size:21px;}
    .st-key-live_workspace [data-testid="stVerticalBlock"] {gap:0.65rem;}
    .st-key-live_workspace [data-testid="stForm"] {border:0;padding:0;}
    .st-key-live_workspace [data-testid="stCaptionContainer"] p {font-size:12px;}
    </style>''')
    with st.container(key="live_workspace"):
        st.html('<header class="gx-live-head"><div><small>GOXTRADE / EXECUTION</small><h1>Live</h1></div><span class="gx-live-tag">ACCOUNT EXECUTION</span></header>')
        if not credentials_present():
            st.warning("Connect your Topstep API credentials on the Dashboard.")
            return
        leader, trading, accounts = st.tabs(["Leader", "Practice", "Accounts & sizing"])
        with leader:
            from leader_page import render
            render()
        with trading:
            left, right = st.columns([1, 2.1], gap="large")
            with left:
                with st.container(key="live_controls"):
                    render_practice()
            with right:
                render_trade_history()
                render_order_attempts()
        with accounts:
            render_accounts()


def render_accounts():
    if not credentials_present():
        st.warning("Connect your Topstep API credentials on the Dashboard.")
        return
    heading, refresh = st.columns([5, 1], vertical_alignment="bottom")
    heading.subheader("Accounts")
    reload = refresh.button("Refresh", icon=":material/refresh:", width="stretch")
    if reload or "topstep_accounts" not in st.session_state:
        try:
            with st.spinner("Loading accounts"):
                st.session_state.topstep_accounts = search_accounts()
            st.session_state.accounts_updated = datetime.now(ZoneInfo("America/Chicago")).strftime("%b %d, %H:%M:%S CT")
            st.session_state.accounts_error = False
        except Exception:
            st.session_state.accounts_error = True
    if st.session_state.get("accounts_error"):
        st.error("Unable to refresh Topstep accounts. Check your API connection and try Refresh.")
        if "topstep_accounts" not in st.session_state:
            return
        st.warning("Showing the last account snapshot. Selection changes are disabled until refresh succeeds.")
    accounts = enabled_accounts(st.session_state.topstep_accounts)
    st.caption(f'{len(accounts)} trading-enabled accounts / Updated {st.session_state.get("accounts_updated", "--")}')
    if not accounts:
        st.session_state.pop("live_account_choice", None)
        st.info("No trading-enabled accounts were returned by Topstep.")
        return
    rows = [dict(Account=a.get("name", "Unnamed"), ID=a["id"], Balance=a.get("balance"),
                 Copy_role=copy_role(a),
                 Environment="Simulated" if a.get("simulated") is True else "Live" if a.get("simulated") is False else "Not provided")
            for a in accounts]
    st.dataframe(rows, hide_index=True, width="stretch", column_config={"Balance": st.column_config.NumberColumn("Balance (USD)", format="$%.2f"), "Copy_role": "Copy role (provided)"})
    st.caption("Copy roles reflect your screenshot, not live copier status. Topstep copier settings are unchanged.")
    st.subheader("Micro sizing")
    ids = [a["id"] for a in accounts]
    saved = load_preferences().get("selected_account")
    if saved not in ids:
        saved = next((a["id"] for a in accounts if copy_role(a) == "Leader"), None)
    if st.session_state.get("live_account_choice") not in ids:
        st.session_state.pop("live_account_choice", None)
    selected = st.selectbox("Account", ids, index=ids.index(saved) if saved in ids else None,
                            format_func=lambda id: next(f'{a.get("name", "Unnamed")} / {id}' for a in accounts if a["id"] == id),
                            placeholder="Select an account", key="live_account_choice", disabled=st.session_state.get("accounts_error", False))
    if selected is None:
        return
    account = next(a for a in accounts if a["id"] == selected)
    if copy_role(account) == "Leader":
        st.info("Leader execution has separate controls in the Leader tab. Saving sizing here does not start trading. Follower copies are managed by Topstep.")
    elif copy_role(account) == "Follower":
        st.warning("This is a follower in your provided setup. Use the leader for copy-trading; separate follower orders could duplicate exposure.")
    if account.get("canTrade") is not True:
        st.warning("Topstep currently marks this account as unavailable for trading.")
    values = quantities_for(selected)
    with st.form(f"micro_sizing_{selected}"):
        columns = st.columns(3)
        quantities = {symbol: column.number_input(symbol, min_value=1, max_value=4, value=values[symbol],
                                                 step=1, key=f"live_qty_{selected}_{symbol}")
                      for symbol, column in zip(MICROS, columns)}
        st.caption("Contracts per trade / Maximum 4 per symbol / No automatic size increases")
        submitted = st.form_submit_button("Save sizing", icon=":material/save:", disabled=st.session_state.get("accounts_error", False))
        if submitted:
            try:
                save_quantities(selected, quantities)
                st.success("Sizing saved. No orders submitted.")
            except (ValueError, OSError):
                st.error("Unable to save sizing. Check the values and retry.")
