"""Performance analytics; configuration lives in dedicated workspaces."""
import streamlit as st
from goxtrade.ui.shell import page_header


def render_dashboard():
    page_header("Workspace", "Dashboard", "Performance, execution quality and account health")
    performance, research = st.tabs(["Performance", "Research comparison"])
    with performance, st.container(key="dashboard_overview"):
        from goxtrade.ui.dashboard.dashboard_view import render_statistics
        render_statistics()
    with research:
        from goxtrade.ui.bot.strategy_research import render_comparison
        render_comparison()
