import streamlit as st


def apply():
    st.html("""<style>
    :root {--gx-bg:#101214;--gx-panel:#191d1e;--gx-line:#30393a;--gx-muted:#97a6a3;--gx-accent:#64d6af;}
    [data-testid="stAppViewContainer"], [data-testid="stHeader"] {background:var(--gx-bg);color:#e4e7e8;}
    [data-testid="stSidebar"] {background:#171b1c!important;border-right:1px solid var(--gx-line)!important;}
    [data-testid="stSidebarContent"] {padding-top:20px;}
    .gx-brand {display:flex;align-items:center;gap:12px;padding:8px 0 24px;border-bottom:1px solid var(--gx-line);margin-bottom:18px;}
    .gx-brand-mark {display:grid;place-items:center;width:36px;height:36px;border:1px solid #52786b;border-radius:6px;background:#213b32;color:#7ae3bc;font-size:13px;font-weight:750;}
    .gx-brand strong {font-size:19px;color:#eff4f2;}
    .gx-brand small {display:block;font-size:10px;color:#9aaaA5;margin-top:2px;}
    .st-key-main_navigation [data-testid="stVerticalBlock"] {gap:7px;}
    .st-key-main_navigation button {justify-content:flex-start!important;height:43px;border-radius:5px;background:transparent!important;border:1px solid transparent!important;color:#aab8b3!important;padding-left:13px;transition:background .12s;}
    .st-key-main_navigation button p {font-size:14px;font-weight:500;}
    .st-key-main_navigation button:hover {background:#222c28!important;color:#eef7f2!important;}
    .st-key-main_navigation button[kind="primary"] {background:#203c31!important;color:#91ebc8!important;border-color:#426451!important;box-shadow:inset 3px 0 #64d6af;}
    .st-key-main_navigation button:focus-visible {outline:2px solid #64d6af;outline-offset:2px;}
    .gx-nav-foot {border-top:1px solid var(--gx-line);padding-top:16px;margin-top:24px;color:#8b9b96;font-size:11px;line-height:1.8;}
    .gx-nav-foot b {color:#c6b989;font-weight:500;}
    [data-testid="stMainBlockContainer"] {padding-top:4.5rem;padding-bottom:2rem;}
    [data-testid="stMain"] label p {color:#c2d0ca!important;}
    [data-testid="stMain"] h1 {font-size:27px;line-height:1.25;letter-spacing:0;}
    [data-testid="stMain"] h2 {font-size:22px;letter-spacing:0;}
    [data-testid="stMain"] h3 {font-size:18px;letter-spacing:0;}
    [data-testid="stMain"] [data-testid="stCaptionContainer"] p {color:var(--gx-muted);}
    [data-testid="stMain"] [data-testid="stButton"] button {border-radius:5px;border-color:#3c4b46;background:#202a25;color:#c5dfd3;}
    [data-testid="stMain"] [data-testid="stButton"] button:hover {border-color:#64d6af;color:#a8f0d2;}
    [data-testid="stMain"] [data-testid="stMetricValue"] {font-variant-numeric:tabular-nums;color:#e4eee8;font-size:26px;}
    [data-testid="stMain"] [data-testid="stCaptionContainer"] p {color:#9aaba3!important;}
    [data-testid="stMain"] [role="tab"] {color:#a5b8ae;}
    [data-testid="stMain"] [role="tab"][aria-selected="true"] {color:#64d6af;}
    [data-testid="stMain"] [data-baseweb="tab-highlight"] {background:#64d6af;}
    .gx.gx-history,.gx.gx-watch {background:#181d1b!important;border-color:#34413b!important;box-shadow:none;}
    .gx-history-levels,.gx-watch-strategy,.gx.gx-monitor-line {border-color:#34413b!important;}
    .gx-evidence {border-left-color:#bca468!important;}
    .gx-history-title strong,.gx-watch-head b {color:#f1f5f2;}
    .gx.gx-history {padding:14px 16px!important;}
    .gx-history-levels strong,.gx-live-price b {font-size:18px!important;}
    .gx-top {border-bottom:1px solid #34413b;padding-bottom:12px!important;}
    @media(max-width:700px){[data-testid="stMainBlockContainer"] {padding-top:4rem;padding-left:1rem;padding-right:1rem;}}
    </style>""")
