"""Bounded local snapshots shared by browser clients; no broker polling."""
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
import threading
import time

from goxtrade.data.live_store import connect, latest_prices
from goxtrade.config import execution_identity as identity
from goxtrade.execution.executed_results import results, summary
from goxtrade.market.market_session import market_session
from goxtrade.market.trading_schedule import execution_schedule
from goxtrade.strategies.strategy_catalog import SPECS
from goxtrade.strategies import strategy_settings
from goxtrade.bot import bot_controls
from goxtrade.execution import safeguards

SYMBOLS = ("NQ=F", "ES=F", "YM=F", "MNQ=F", "MES=F", "MYM=F")


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def read_records(conn, tables, table, order="rowid DESC", limit=1000):
    if table not in tables:
        return []
    return [json.loads(row[0]) for row in conn.execute(f"SELECT record FROM {table} ORDER BY {order} LIMIT ?", (limit,))]


def profile_state(conn, tables, profile):
    settings, runtime, history = {}, {}, {}
    table = profile+"_control"
    if table in tables:
        row = conn.execute(f"SELECT settings,status FROM {table} WHERE id=1").fetchone()
        if row:
            settings, runtime = json.loads(row[0]), json.loads(row[1])
    jobs = read_records(conn, tables, profile+"_jobs", limit=10000)
    fills = read_records(conn, tables, profile+"_fills", limit=50000)
    if profile+"_history_status" in tables:
        row = conn.execute(f"SELECT record FROM {profile}_history_status WHERE id=1").fetchone()
        history = json.loads(row[0]) if row else {}
    target = identity.TARGETS[profile]
    if history.get("account_id") not in (None, target["id"]):
        history = dict(error=True)
    gate = {}
    if "practice_loss_gate" in tables:
        row = conn.execute("SELECT record FROM practice_loss_gate WHERE id=?", (target["gate_id"],)).fetchone()
        gate = json.loads(row[0]) if row else {}
    matched = results(jobs, fills)
    trades = [{**matched[job["alert_id"]], "alert_id": job["alert_id"], "account_id": job.get("account_id"),
               "symbol": job.get("symbol"), "strategy": job.get("strategy", "Unknown"), "quantity": job.get("quantity"),
               "direction": "LONG" if job.get("side") == 0 else "SHORT"}
              for job in jobs if job["alert_id"] in matched]
    limits=safeguards.read(target['gate_id'])
    from goxtrade.strategies.overnight_policy import overnight
    night=overnight()
    effective=dict(overnight=night,max_contracts=min(limits['active']['max_contracts'],limits['active']['overnight_max_contracts']) if night else limits['active']['max_contracts'])
    return dict(settings=settings, runtime=runtime, gate=gate, broker=history,safeguards=limits,effective_limits=effective,
                jobs=sorted(jobs, key=lambda row: row.get("sent_at", 0), reverse=True)[:300],
                fills=sorted(fills, key=lambda row: row.get("creationTimestamp", ""), reverse=True)[:150],
                trades=trades, totals=summary(matched), target=target)


def snapshot():
    with closing(connect()) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        profiles = {profile: profile_state(conn, tables, profile) for profile in ("practice", "leader")}
        monitor = []
        if "bot_monitor_status" in tables:
            monitor = [dict(symbol=row[0], strategy=row[1], **json.loads(row[2])) for row in conn.execute("SELECT symbol,strategy,record FROM bot_monitor_status")]
        alerts = []
        if "bot_alert_history" in tables:
            # All active rows plus a bounded closed journal, not only the last N active IDs.
            for row in conn.execute("SELECT id,record FROM bot_alert_history ORDER BY id DESC"):
                alert = dict(id=row[0], **json.loads(row[1]))
                if alert.get("status") == "Active" or len(alerts) < 350:
                    alerts.append(alert)
        events = []
        if "bot_events" in tables:
            events = [dict(row) for row in conn.execute("SELECT * FROM bot_events ORDER BY id DESC LIMIT 100")]
    from goxtrade.data.lab_store import progress_revision
    research_revision = progress_revision()
    return clean(dict(profiles=profiles, monitor=monitor, alerts=alerts, events=events,research_revision=research_revision))


class SnapshotCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.updated = 0.
        self.value = None

    def get(self):
        with self.lock:
            if self.value is None or time.monotonic()-self.updated > 1:
                self.value = snapshot()
                self.updated = time.monotonic()
            return self.value

    def invalidate(self):
        with self.lock:
            self.updated = 0.


CACHE = SnapshotCache()


def ticks():
    return clean(dict(prices=latest_prices(SYMBOLS), session=market_session(), schedule=execution_schedule(),
                      time=datetime.now(timezone.utc).isoformat()))


def configuration():
    from goxtrade.data.symbol_store import load_symbols
    from goxtrade.execution.contracts import contract_for_symbol
    from goxtrade.execution.projectx_client import credentials_present
    from goxtrade.market.calendar_guard import restriction
    from goxtrade.runtime.live_process import status
    execution_settings = {}
    with closing(connect()) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for profile in ("practice", "leader"):
            row = conn.execute(f"SELECT settings FROM {profile}_control WHERE id=1").fetchone() if profile+"_control" in tables else None
            execution_settings[profile] = json.loads(row[0]) if row else {}
    return clean(dict(strategies=[asdict(spec) for spec in SPECS],
                      policies={profile: bot_controls.read(profile) for profile in ("practice", "leader")},
                      execution_settings=execution_settings,
                      safeguards={p:safeguards.read(identity.TARGETS[p]['gate_id']) for p in ('practice','leader')},
                      stop_minutes=strategy_settings.read_stop_minutes(), orb_minutes=strategy_settings.read_orb_minutes(),
                      vwap=strategy_settings.read_vwap_ema_config().to_dict(), targets=identity.current_targets(),
                      previous_day_box=strategy_settings.read_previous_day_box_config().to_dict(),
                      restart_required=identity.restart_required(), credentials_present=credentials_present(),
                      calendar=restriction(datetime.now(timezone.utc), required=True), worker=status(),
                      symbols=[dict(symbol=symbol, contract_id=contract_for_symbol(symbol)) for symbol in load_symbols()]))
