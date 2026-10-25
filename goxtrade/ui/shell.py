from html import escape

import streamlit as st


PAGES = (
    ("Dashboard", "space_dashboard", "Workspace"),
    ("Charts", "candlestick_chart", "Workspace"),
    ("Strategies", "query_stats", "Trading"),
    ("Control Center", "tune", "Trading"),
    ("Execution", "bolt", "Trading"),
    ("Accounts", "account_balance_wallet", "Settings"),
    ("Connection", "key", "Settings"),
)
ALIASES = {"Market": "Charts", "Bot": "Strategies", "Live": "Execution"}


def render_sidebar() -> str:
    st.sidebar.html(
        '<div class="gx-brand"><span class="gx-brand-mark">GX</span>'
        '<div><strong>GoXTrade</strong><small>Trading workspace</small></div></div>'
        '<div class="gx-workspace">Personal workspace<span>LOCAL</span></div>'
    )
    names = {name for name, _, _ in PAGES}
    if "page" not in st.session_state:
        requested = st.query_params.get("page", "Dashboard")
        requested = ALIASES.get(requested, requested)
        st.session_state.page = requested if requested in names else "Dashboard"
    st.session_state.page = ALIASES.get(st.session_state.page, st.session_state.page)

    def navigate(page: str) -> None:
        st.session_state.page = page
        st.query_params["page"] = page

    with st.sidebar.container(key="main_navigation"):
        previous_group = None
        for name, icon, group in PAGES:
            if group != previous_group:
                st.html(f'<div class="gx-nav-label">{group}</div>')
                previous_group = group
            st.button(
                name, icon=f":material/{icon}:", width="stretch",
                type="primary" if st.session_state.page == name else "secondary",
                on_click=navigate, args=(name,),
            )
    st.sidebar.html(
        '<div class="gx-nav-foot"><b>Micro futures / Topstep</b>'
        'Chicago time (CT)<br>Local credentials &amp; history</div>'
    )
    return st.session_state.page


def page_header(section: str, title: str, detail: str = "", tag: str = "") -> None:
    detail_html = f"<p>{escape(detail)}</p>" if detail else ""
    tag_html = f'<span class="gx-page-tag">{escape(tag)}</span>' if tag else ""
    st.html(
        f'<header class="gx-page-head"><div><span class="gx-eyebrow">'
        f'{escape(section)}</span><h1>{escape(title)}</h1>{detail_html}</div>'
        f'{tag_html}</header>'
    )
