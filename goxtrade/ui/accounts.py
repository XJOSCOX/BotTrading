"""Account discovery and guarded identity replacement; no order placement."""
from html import escape
import streamlit as st
from goxtrade.ui.shell import page_header
from goxtrade.config import execution_identity as identity
from goxtrade.execution.live_accounts import search_accounts, enabled_accounts, copy_role
from goxtrade.execution.projectx_client import credentials_present


def render():
    page_header("Settings", "Accounts", "Execution identities and account replacement", "TOPSTEP")
    targets = identity.current_targets()
    cards = []
    for profile, target in targets.items():
        pending = target != identity.TARGETS[profile]
        configured = not target["name"].startswith("YOUR_")
        label = "Restart required" if pending else "Configured target" if configured else "Not configured"
        title = target["name"] if configured else "No account assigned"
        identifier = f'ID {target["id"]}' if configured else "Select a broker identity"
        cards.append(f'<article class="gx-account-tile"><small>{profile.title()} execution</small><h3>{escape(title)}</h3><footer><span>{identifier}</span><b>{label}</b></footer></article>')
    st.html('<div class="gx-account-grid">'+''.join(cards)+'</div>')
    if identity.restart_required():
        st.warning("Replacement saved. Restart the full app and workers before enabling execution. No account has been armed.")
    accounts, replace = st.tabs(["Available accounts", "Replace execution account"])
    with accounts:
        a, b = st.columns([4, 1], vertical_alignment="bottom")
        a.subheader("Trading-enabled accounts")
        if b.button("Refresh accounts", icon=":material/refresh:", disabled=not credentials_present(), width="stretch"):
            try:
                st.session_state["account_directory"] = enabled_accounts(search_accounts())
                st.session_state.pop("account_directory_error", None)
            except Exception:
                st.session_state["account_directory_error"] = True
        if not credentials_present():
            st.info("Add your API key on Connection to retrieve accounts.")
        if st.session_state.get("account_directory_error"):
            st.error("Account refresh failed. Any saved directory below is stale; replacement always re-verifies with the broker.")
        rows = st.session_state.get("account_directory", [])
        if rows:
            st.dataframe([{"Account": a["name"], "ID": a["id"], "Balance ($)": a.get("balance"), "Copy label": copy_role(a), "Environment": "Simulated" if a.get("simulated") is True else "Live"} for a in rows], hide_index=True, width="stretch")
        else:
            st.caption("No account directory loaded.")
        st.caption("Copy labels are local records, not verification of Topstep copier configuration.")
    with replace:
        left, right = st.columns([1.6, 1], gap="large")
        with left:
            st.subheader("New account identity")
            with st.form("replace_execution_account"):
                profile = st.selectbox("Replace profile", ["leader", "practice"], format_func=str.title)
                account_id = st.number_input("New broker account ID", min_value=1, value=None, step=1, placeholder="Numeric ID from the account directory")
                name = st.text_input("Exact new account name", placeholder="50KTC-... or PRAC-...")
                confirmed = st.checkbox("Both profiles are paused, workers are stopped, and old/new accounts have no positions or orders.")
                copy_confirm = st.checkbox("I verified this account's role and copier configuration in Topstep.")
                submit = st.form_submit_button("Verify & save replacement", icon=":material/manage_accounts:", disabled=not credentials_present())
            if submit:
                if not confirmed or not copy_confirm or account_id is None:
                    st.error("Enter the new identity and confirm the account safeguards.")
                else:
                    from goxtrade.execution.account_management import replace_account
                    try:
                        replace_account(profile, account_id, name)
                        st.success("Replacement saved locally. Restart the full app before trading; history is retained.")
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))
                    except Exception:
                        st.error("Broker verification failed. No account replacement was completed.")
        with right:
            st.subheader("Replacement checklist")
            st.markdown("1. Pause Practice and Leader.\n2. Resolve open and uncertain orders.\n3. Stop trading workers on Connection.\n4. Verify the new ID and exact name.\n5. Save, restart, then explicitly start execution.")
            st.caption("Supported: isolated PRAC accounts and simulated 50K Trading Combine leaders. Funded accounts are not enabled here.")
            st.warning("If the old account cannot be verified flat, replacement is blocked for manual review. History and loss-lock records are never deleted.")
