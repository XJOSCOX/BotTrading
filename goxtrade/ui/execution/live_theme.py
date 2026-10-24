from html import escape
import streamlit as st


def apply():
    st.html("""<style>
    .st-key-live_workspace h3 {font-size:17px!important;font-weight:650;}
    .st-key-live_workspace label p {font-size:12px;}
    .st-key-live_workspace [data-testid="stMetricValue"] {font-size:22px;}
    .st-key-live_workspace [data-testid="stNumberInputContainer"] button {
        background:var(--gx-surface-strong)!important;color:var(--gx-text)!important;
    }
    .st-key-live_workspace [data-testid="stForm"] {border:0;padding:0;}
    .gx-live-status {
        display:flex;align-items:flex-start;gap:9px;padding:10px 0;
        border-block:1px solid var(--gx-border);font-size:12px;
        color:var(--gx-muted);line-height:1.5;
    }
    .gx-live-status strong {color:var(--gx-accent);white-space:nowrap;}
    .gx-live-status.paused strong {color:var(--gx-amber);}
    .gx-live-status.error strong {color:var(--gx-red);}
    </style>""")


def status(enabled, fresh, message):
    tone = "error" if not fresh else "" if enabled else "paused"
    label = "OFFLINE" if not fresh else "RUNNING" if enabled else "PAUSED"
    st.html(f'<div class="gx-live-status {tone}"><strong>{label}</strong><span>{escape(str(message))}</span></div>')


def table(rows):
    import pandas as pd
    def color(value):
        if value in ("Rejected", "Unknown"):
            return "color:#ffaaa4"
        if value in ("Open", "Closed", "Submitted"):
            return "color:#77dfb9"
        return ""
    return (pd.DataFrame(rows).style.set_properties(**{"background-color":"#191e1b", "color":"#d9e4dd"})
            .map(color, subset=[c for c in ("State",) if c in pd.DataFrame(rows).columns]))
