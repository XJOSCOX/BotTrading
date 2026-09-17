import streamlit as st


def apply():
    st.html('''<style>
    .st-key-dashboard_overview {width:100%;max-width:none;margin:0;}
    .st-key-dashboard_overview [data-testid="stButtonGroup"] button {background:#202529;color:#b9c6ca;border-color:#394247;}
    .st-key-dashboard_overview [data-testid="stButtonGroup"] button[aria-pressed="true"] {background:#283c42;color:#9cdee5;border-color:#5b9299;}
    .db-report{color:#dfe5e7;font-size:13px;letter-spacing:0;font-variant-numeric:tabular-nums;}.db-report *{box-sizing:border-box;}
    .db-report h3{font-size:15px!important;font-weight:600;margin:0;padding:0!important;color:#edf1f3;}.db-report small,.db-report p{color:#93a0a7;font-size:12px;}
    .db-report .gain{color:#73d7b3;}.db-report .loss{color:#ed969f;}
    .db-status{display:flex;flex-wrap:wrap;align-items:center;gap:12px 24px;padding:12px 0;border-bottom:1px solid #333a40;color:#aab6bd;font-size:12px;}.db-lock{margin-left:auto;color:#dbc58c;}
    .db-top{display:grid;grid-template-columns:minmax(260px,1fr) minmax(280px,1.4fr) minmax(240px,.9fr);border-bottom:1px solid #333a40;padding:26px 0;gap:32px;}
    .db-result{padding-right:28px;border-right:1px solid #333a40;}.db-net{font-size:38px;line-height:1.2;font-weight:650;margin:10px 0 6px;overflow-wrap:anywhere;}.db-result p{margin:0 0 22px;}
    .db-mini{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;}.db-mini b{display:block;font-size:18px;font-weight:600;}.db-mini span{display:block;color:#93a0a7;font-size:11px;margin-top:5px;}
    .db-win-track{height:5px;background:#9c5960;margin-top:22px;}.db-win-track i{display:block;height:100%;background:#73d7b3;}.db-win-key{display:flex;justify-content:space-between;margin-top:8px;font-size:11px;color:#a7b6bc;}
    .db-report header{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:20px;flex-wrap:wrap;}.db-outcome{display:grid;grid-template-columns:42px minmax(0,1fr) 86px;align-items:center;gap:14px;min-height:38px;}.db-outcome>b{text-align:right;font-size:13px;}
    .db-track{height:8px;background:#252b30;border-radius:2px;overflow:hidden;}.db-track i{display:block;height:100%;border-radius:2px;}.db-track i.gain{background:#73d7b3;}.db-track i.loss{background:#ed969f;}
    .db-risk{border-left:1px solid #333a40;padding-left:26px;}.db-detail{display:flex;justify-content:space-between;gap:14px;padding:11px 0;border-bottom:1px solid #262e33;}.db-detail span{color:#a2afb6;}.db-detail b{font-weight:500;}
    .db-bottom{display:grid;grid-template-columns:minmax(0,2.5fr) minmax(240px,1fr);gap:32px;padding:24px 0;}.db-ranking{border-left:1px solid #333a40;padding-left:26px;}.db-rank{display:flex;justify-content:space-between;gap:12px;padding:16px 0;border-bottom:1px solid #30383d;}.db-rank small{display:block;margin-top:5px;font-size:11px;}.db-symbol-title{margin-top:25px!important;}
    .db-scroll{overflow:auto;width:100%;}.db-report table{border-collapse:collapse;width:100%;text-align:left;font-size:13px;}.db-report th{color:#8f9fa9;font-size:11px;font-weight:500;padding:10px 12px;border-bottom:1px solid #414b53;white-space:nowrap;}.db-report td{padding:14px 12px;border-bottom:1px solid #2a3238;white-space:nowrap;}.db-report td small{display:block;font-size:11px;margin-top:4px;}.db-report td:nth-last-child(-n+3),.db-report th:nth-last-child(-n+3){text-align:right;}.db-report tbody tr:hover{background:#1c2328;}
    .db-report footer{border-top:1px solid #333a40;padding:12px 0;color:#8f9ea6;font-size:11px;line-height:1.6;}
    @media(max-width:1400px){.db-top{grid-template-columns:minmax(0,1fr) minmax(0,1.4fr);}.db-risk{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:12px 24px;border-left:0;border-top:1px solid #333a40;padding:16px 0 0;}.db-risk h3{width:100%;}.db-risk .db-detail{flex:1 1 160px;}.db-bottom{grid-template-columns:minmax(0,1fr);}.db-ranking{border-left:0;border-top:1px solid #333a40;padding:20px 0 0;}}
    @media(max-width:650px){.db-top{grid-template-columns:1fr;gap:24px;}.db-result{border-right:0;padding:0 0 20px;border-bottom:1px solid #333a40;}.db-lock{margin-left:0;}.db-net{font-size:34px;}}
    </style>''')
