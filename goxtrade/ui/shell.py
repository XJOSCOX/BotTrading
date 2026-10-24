from html import escape

import streamlit as st


PAGES = (
    ("Dashboard", "dashboard", "Overview"),
    ("Market", "candlestick_chart", "Price action"),
    ("Bot", "smart_toy", "Signals"),
    ("Live", "bolt", "Execution"),
)


def render_sidebar() -> str:
    st.sidebar.html(
        '<div class="gx-brand"><span class="gx-brand-mark">GX</span>'
        '<div><strong>GoXTrade</strong><small>TRADING WORKSPACE</small></div></div>'
        '<div class="gx-nav-label">WORKSPACE</div>'
    )
    names = {name for name, _, _ in PAGES}
    if "page" not in st.session_state:
        requested = st.query_params.get("page", "Dashboard")
        st.session_state.page = requested if requested in names else "Dashboard"

    def navigate(page: str) -> None:
        st.session_state.page = page
        st.query_params["page"] = page

    with st.sidebar.container(key="main_navigation"):
        for name, icon, _ in PAGES:
            st.button(
                name, icon=f":material/{icon}:", width="stretch",
                type="primary" if st.session_state.page == name else "secondary",
                on_click=navigate, args=(name,),
            )
    st.sidebar.html(
        '<div class="gx-nav-foot"><span class="gx-nav-foot-dot"></span>'
        '<div><b>Local workspace</b><small>Market time: Chicago (CT)</small></div></div>'
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
