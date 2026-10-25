import streamlit as st

from goxtrade.execution.projectx_client import credentials_present
from goxtrade.ui import shell, theme
from goxtrade.ui.bot.page import render_bot
from goxtrade.ui.dashboard.page import render_dashboard
from goxtrade.ui.execution.live_page import render_live
from goxtrade.ui.market.page import render_market
from goxtrade.ui.control_center import render as render_controls
from goxtrade.ui.accounts import render as render_accounts
from goxtrade.ui.connection import render as render_connection


st.set_page_config(page_title="GoXTrade", page_icon="GX", layout="wide")


def main() -> None:
    theme.apply()
    if credentials_present():
        from goxtrade.execution.practice_history import ensure_worker
        ensure_worker()
    page = shell.render_sidebar()
    with st.container(key="gox_workspace"):
        from goxtrade.config.execution_identity import restart_required
        if restart_required():
            st.warning("Account identity changed. Restart the full app and workers before trading.")
        pages = {"Dashboard": render_dashboard, "Charts": render_market, "Strategies": render_bot,
                 "Control Center": render_controls, "Execution": render_live,
                 "Accounts": render_accounts, "Connection": render_connection}
        pages.get(page, render_dashboard)()


if __name__ == "__main__":
    main()
