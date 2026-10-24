from pathlib import Path

import streamlit as st


_STYLES = Path(__file__).with_name("styles.css")


def apply() -> None:
    st.html(f"<style>{_STYLES.read_text(encoding='utf-8')}</style>")
