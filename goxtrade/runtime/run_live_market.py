import json
import logging
import time
from threading import Event, Thread
from contextlib import closing

from goxtrade.bot.bot_monitor import SYMBOLS, run_monitor
from goxtrade.execution.practice_executor import run_practice

from signalrcore.hub_connection_builder import HttpTransportType, HubConnectionBuilder

from goxtrade.execution.contracts import symbols_with_contracts
from goxtrade.data.live_store import connect
from goxtrade.data.tick_buffer import TickBuffer, event_age
from goxtrade.market.market_session import market_session
from goxtrade.execution.projectx_client import login, market_hub_url
from goxtrade.execution.refresh_contracts import refresh_active_contracts
from goxtrade.strategies.overnight_policy import MICRO_SYMBOLS
from goxtrade.data.symbol_store import load_symbols
from goxtrade.diagnostics import feed_status


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def first_payload(args):
    if not args:
        return None, None
    if len(args) == 1:
        return None, args[0]
    return args[0], args[1]


def run_connection(subscriptions) -> None:
    disconnected = Event()
    last_event = time.monotonic()
    started = time.monotonic()
    latest_market_time = None
    writer = TickBuffer(disconnected)
    contract_to_symbol = {item["contract_id"]: item["symbol"] for item in subscriptions}
    token = login()
    hub_url = f"{market_hub_url()}?access_token={token}"

    connection = (
        HubConnectionBuilder()
        .with_url(
            hub_url,
            options={
                "access_token_factory": lambda: token,
                "skip_negotiation": True,
                "transport": HttpTransportType.web_sockets,
            },
        )
        .build()
    )

    def on_quote(args):
        nonlocal last_event, latest_market_time
        last_event = time.monotonic()
        contract_id, payload = first_payload(args)
        if not isinstance(payload, dict):
            logging.info("Unsupported quote payload; raw server content withheld")
            return
        symbol = contract_to_symbol.get(contract_id) or payload.get("symbol") or contract_id or "UNKNOWN"
        timestamp = payload.get("timestamp") or payload.get("lastUpdated")
        age = event_age(timestamp)
        if age is not None and age >= 0:
            candidate = time.monotonic()-age
            latest_market_time = max(latest_market_time or candidate, candidate)
        writer.add("quote",symbol,contract_id or "",payload)

    def on_trade(args):
        nonlocal last_event, latest_market_time
        last_event = time.monotonic()
        contract_id, payload = first_payload(args)
        for trade in trade_payloads(payload):
            symbol = contract_to_symbol.get(contract_id) or trade.get("symbolId") or contract_id or "UNKNOWN"
            age = event_age(trade.get("timestamp"))
            if age is not None and age >= 0:
                candidate = time.monotonic()-age
                latest_market_time = max(latest_market_time or candidate, candidate)
            writer.add("trade",symbol,contract_id or "",trade)

    def on_open():
        logging.info("market hub connected")
        feed_status.update("connected",subscriptions=subscriptions)
        from goxtrade.data.feed_coverage import opened
        from goxtrade.data.live_store import utc_now
        for item in subscriptions:
            opened(item["symbol"], item["contract_id"], utc_now())
            try:
                connection.invoke("SubscribeContractQuotes", [item["contract_id"]])
                connection.invoke("SubscribeContractTrades", [item["contract_id"]])
            except Exception:
                feed_status.update("connected / subscription request failed",error="SUBSCRIPTION_FAILED")
                raise

    connection.on("GatewayQuote", on_quote)
    connection.on("GatewayTrade", on_trade)
    connection.on_open(on_open)
    def on_error(error):
        logging.error("Market hub reported a stream error; raw server text withheld")
        feed_status.update("connected / stream error",error="UNKNOWN_ERROR")
    connection.on_error(on_error)
    connection.on_close(disconnected.set)
    connection.on("GatewayLogout", lambda *_: disconnected.set())

    try:
        writer.start()
        connection.start()
        while not disconnected.wait(1):
            if market_session()["is_open"] and time.monotonic()-started > 30 and (latest_market_time is None or time.monotonic()-latest_market_time > 30):
                logging.warning("Market timestamps are delayed by over 30 seconds; reconnecting")
                break
            if market_session()["is_open"] and time.monotonic() - last_event > 120:
                logging.warning("No market events for 120 seconds; reconnecting")
                break
    finally:
        try:
            connection.stop()
        except Exception:
            logging.warning("Connection cleanup failed")
        writer.close()
        from goxtrade.data.feed_coverage import closed
        from goxtrade.data.live_store import utc_now
        for item in subscriptions:
            closed(item["symbol"], item["contract_id"], writer.gap_at or utc_now())
        feed_status.update("disconnected")


def trade_payloads(payload):
    items = payload if isinstance(payload, list) else [payload]
    return [item for item in items if isinstance(item, dict)]


def main() -> None:
    # WAL lets chart/strategy readers coexist with the batched tick writer.
    with closing(connect()) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    Thread(target=run_monitor, name="strategy-monitor", daemon=True).start()
    Thread(target=run_practice, name="practice-executor", daemon=True).start()
    feed_symbols = list(dict.fromkeys([*load_symbols(), *SYMBOLS, *MICRO_SYMBOLS]))
    delay = 30
    rejected_credentials = None
    while True:
        started = time.monotonic()
        try:
            # Reload a repaired API key without requiring a browser or worker restart.
            from dotenv import load_dotenv
            from goxtrade.execution.projectx_client import ENV_PATH
            load_dotenv(ENV_PATH, override=True)
            import hashlib,os
            credential_identity=hashlib.sha256((os.getenv("TOPSTEP_USERNAME","")+"\0"+os.getenv("TOPSTEP_API_KEY","")).encode()).hexdigest()
            if rejected_credentials==credential_identity:
                # Continue exit/account management threads, but never hammer rejected credentials.
                time.sleep(30)
                continue
            feed_status.update("connecting",reconnect=True)
            refresh_active_contracts(feed_symbols)
            subscriptions = symbols_with_contracts(feed_symbols)
            if not subscriptions:
                raise RuntimeError("No saved symbols have contract IDs.")
            run_connection(subscriptions)
        except Exception as error:
            logging.warning("Market connection failed (%s)", type(error).__name__)
            from goxtrade.execution.projectx_client import ProjectXAuthError
            if isinstance(error,ProjectXAuthError) and getattr(error,"code",None) in ("AUTH_FAILED","PERMISSION_DENIED"):
                rejected_credentials=credential_identity
                feed_status.update("disconnected",error=error.code)
        if time.monotonic() - started > 300:
            delay = 30
        logging.info("Reconnecting with fresh authentication in %s seconds", delay)
        time.sleep(delay)
        delay = min(delay * 2, 300)


if __name__ == "__main__":
    main()
