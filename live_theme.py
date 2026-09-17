from html import escape
import streamlit as st


def apply():
    st.html("""<style>
    [data-testid="stAppViewContainer"]:has(.st-key-live_workspace),
    [data-testid="stAppViewContainer"]:has(.st-key-live_workspace) [data-testid="stHeader"] {background:#101214;color:#e4e7e8;}
    body:has(.st-key-live_workspace) [data-testid="stHeader"] {background:#101214;}
    body:has(.st-key-live_workspace) [data-testid="stSidebar"] {background:#191c1e;color:#d6dddd;border-right:1px solid #303638;}
    .st-key-live_workspace {color:#e4e7e8;}
    .st-key-live_workspace h3 {font-size:16px!important;font-weight:650;color:#edf2f1;}
    .st-key-live_workspace label,.st-key-live_workspace label p {color:#bdc8c6!important;font-size:12px;}
    .st-key-live_workspace [data-testid="stCaptionContainer"] {color:#839591;}
    .st-key-live_workspace [data-testid="stNumberInputContainer"],
    .st-key-live_workspace [data-baseweb="select"]>div {background:#202628!important;border:1px solid #36413e;border-radius:5px;color:#eef5f2;}
    .st-key-live_workspace input {color:#eef5f2!important;background:#202628!important;}
    .st-key-live_workspace [data-baseweb="input"],.st-key-live_workspace [data-baseweb="base-input"] {background:#202628!important;}
    .st-key-live_workspace [data-testid="stCaptionContainer"] p {color:#95a79e!important;}
    body:has(.st-key-live_workspace) [data-testid="stSidebar"] button {background:#202628;color:#c5d5cd;border-color:#3a4941;}
    .st-key-live_workspace button {color:#b7c8c2;}
    .st-key-live_workspace [data-testid="stButton"] button,
    .st-key-live_workspace [data-testid="stFormSubmitButton"] button {background:#222b28;border:1px solid #41544b;border-radius:5px;color:#c5e6d8;}
    .st-key-live_workspace button:disabled {opacity:.4;}
    .st-key-live_workspace [role="tab"][aria-selected="true"] {color:#64d6af!important;}
    .st-key-live_workspace [data-baseweb="tab-highlight"] {background:#64d6af;}
    .st-key-live_workspace [data-testid="stMetric"] {border-top:2px solid #43564e;padding:8px 0 5px;}
    .st-key-live_workspace [data-testid="stMetricValue"] {color:#dbe8e2;font-variant-numeric:tabular-nums;}
    .st-key-live_workspace details {border-color:#35403c!important;border-radius:5px;}
    .st-key-live_workspace summary {color:#c8d5cf;}
    .st-key-live_controls,.st-key-leader_controls {border-right:1px solid #303c36;padding-right:20px;}
    .gx-live-head {display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #35413b;padding:0 0 14px;margin-bottom:6px;gap:12px;}
    .gx-live-head h1 {font-size:26px!important;line-height:1.2;padding:0!important;margin:0;color:#f1f5f2;}
    .gx-live-head small {font-size:11px;color:#8da599;letter-spacing:0;}
    .gx-live-tag {font-size:11px;color:#d9c287;border:1px solid #625538;padding:4px 8px;border-radius:4px;white-space:nowrap;}
    .gx-live-status {display:flex;align-items:flex-start;gap:8px;padding:10px 0;border-block:1px solid #303d36;font-size:12px;color:#a7b8b0;line-height:1.5;}
    .gx-live-status strong {color:#67d9ad;white-space:nowrap;}
    .gx-live-status.paused strong {color:#d7ba79;}
    .gx-live-status.error strong {color:#f08f8b;}
    @media(max-width:700px){.st-key-live_controls,.st-key-leader_controls{border-right:0;border-bottom:1px solid #303c36;padding:0 0 16px;}}
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
