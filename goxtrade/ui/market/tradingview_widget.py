import json


TRADINGVIEW_SYMBOLS = {
    "MNQ=F": "CME_MINI:MNQ1!",
    "MES=F": "CME_MINI:MES1!",
    "NQ=F": "CME_MINI:NQ1!",
    "ES=F": "CME_MINI:ES1!",
    "YM=F": "CBOT_MINI:YM1!",
    "RTY=F": "CME_MINI:RTY1!",
}

YFINANCE_SYMBOLS = {value: key for key, value in TRADINGVIEW_SYMBOLS.items()}


def to_tradingview_symbol(symbol: str) -> str:
    normalized = (symbol or "").strip().upper()
    if normalized in TRADINGVIEW_SYMBOLS:
        return TRADINGVIEW_SYMBOLS[normalized]
    return normalized


def to_yfinance_symbol(symbol: str) -> str:
    normalized = (symbol or "").strip().upper()
    if normalized in YFINANCE_SYMBOLS:
        return YFINANCE_SYMBOLS[normalized]
    return normalized


def tradingview_chart_html(symbol: str, interval: str = "15", theme: str = "dark") -> str:
    config = {
        "autosize": True,
        "symbol": to_tradingview_symbol(symbol),
        "interval": interval,
        "timezone": "America/Chicago",
        "theme": theme,
        "style": "1",
        "locale": "en",
        "enable_publishing": False,
        "allow_symbol_change": True,
        "calendar": False,
        "support_host": "https://www.tradingview.com",
        "studies": ["Volume@tv-basicstudies"],
    }
    encoded = json.dumps(config)
    return f"""
    <div class="tradingview-widget-container" style="height: 720px; width: 100%;">
      <div class="tradingview-widget-container__widget" style="height: 100%; width: 100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
      {encoded}
      </script>
    </div>
    """
