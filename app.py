import streamlit as st

from goxtrade.execution.projectx_client import credentials_present
from goxtrade.ui import shell, theme
from goxtrade.ui.bot.page import render_bot
from goxtrade.ui.dashboard.page import render_dashboard
from goxtrade.ui.execution.live_page import render_live
from goxtrade.ui.market.page import render_market


st.set_page_config(page_title="GoXTrade", page_icon="GX", layout="wide")


def main() -> None:
    theme.apply()
    if credentials_present():
        from goxtrade.execution.practice_history import ensure_worker
        ensure_worker()
    page = shell.render_sidebar()
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
