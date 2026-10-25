"""Opt-in offline fixture measurements; no provider, account or live worker actions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import logging
from pathlib import Path
import statistics
import tempfile
import time
import tracemalloc
from unittest.mock import patch
import pandas as pd
from fastapi.testclient import TestClient
from goxtrade.api import app, state
from goxtrade.data import live_store, lab_store
from goxtrade.execution.strategy_manager import evaluate
from goxtrade.research.portfolio_backtest import candidates_at, run_portfolio_backtest
from goxtrade.replay import replay_session as replay, replay_store as store
from tests.manager_fixtures import NOW, CONTRACT, candidate, facts, policy
from tests.test_portfolio_backtest import minutes
from tests.test_validation_lab import metadata


def distribution(samples):
    ordered = sorted(samples)
    return dict(n=len(samples), p50_ms=1000*statistics.median(samples), p95_ms=1000*ordered[min(len(ordered)-1, int(len(ordered)*.95))], max_ms=1000*max(samples))


def timings(function, count):
    samples = []
    for _ in range(count):
        began = time.perf_counter()
        function()
        samples.append(time.perf_counter()-began)
    return distribution(samples)


def run():
    logging.getLogger("httpx").setLevel(logging.WARNING)
    report = dict(scope="ISOLATED SYNTHETIC FIXTURE; no broker or production latency/profitability evidence")
    with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
        stack.enter_context(patch.object(live_store, "DB_PATH", Path(folder)/"fixture.db"))
        stack.enter_context(patch.object(state, "CACHE", state.SnapshotCache()))
        stack.enter_context(patch("goxtrade.execution.projectx_client.post", side_effect=AssertionError("Broker forbidden")))
        stack.enter_context(patch("goxtrade.execution.projectx_client.login", side_effect=AssertionError("Authentication forbidden")))
        rows = [candidate(), candidate("reversal", key="b"), candidate(symbol="MES", key="c")]
        report["manager_three_candidates"] = timings(lambda: evaluate(rows, facts(), policy(), NOW), 100)
        frame = minutes(180)
        frame["time"] = pd.date_range(pd.Timestamp(NOW)-pd.Timedelta(minutes=180), periods=180, freq="min")
        report["seven_adapter_evaluation"] = timings(lambda: candidates_at({"MNQ": frame}, {"MNQ": 100.}, {"MNQ": CONTRACT}, pd.Timestamp(NOW), policy(), account="test", profile="research"), 30)
        tracemalloc.start()
        wall, cpu = time.perf_counter(), time.process_time()
        result = run_portfolio_backtest([("MNQ", CONTRACT, minutes(180))], policy())
        report["seven_strategy_replay_180_candles"] = dict(wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu, peak_traced_mb=tracemalloc.get_traced_memory()[1]/1e6, trades=len(result["state"]["trades"]), note="tracemalloc instrumentation enabled; constant-price fixture")
        tracemalloc.stop()
        frame = minutes(6)
        meta = {**metadata(), "start": frame.iloc[0].time.isoformat(), "end": (frame.iloc[-1].time+pd.Timedelta(minutes=1)).isoformat()}
        dataset = lab_store.save_dataset(frame, meta)
        session = replay.create(dict(datasets=[dataset["id"]], strategies=["crt"], start=meta["start"], end=meta["end"], execution=dict(commission_per_side=.5)))
        identifier = session["id"]
        def playback_cycle():
            replay.action(identifier, dict(action="play"))
            player = replay._players[identifier]
            replay.action(identifier, dict(action="pause"))
            player.join(5)
            assert not player.is_alive()
        report["play_pause_20_cycles"] = timings(playback_cycle, 20)
        report["playback_final_status"] = store.get(identifier)["status"]
        def write():
            def commit():
                record = store.get(identifier)
                store.save(record)
            return timings(commit, 30)
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(write)
            report["sqlite_read_during_writer"] = timings(lambda: store.get(identifier), 100)
            report["sqlite_write_with_reader"] = writer.result()
        with TestClient(app.create_app(), base_url=f"http://127.0.0.1:{app.PORT}") as browser:
            browser.get("/api/session")
            assert browser.get("/api/snapshot").status_code == 200
            def read_api():
                assert browser.get("/api/snapshot").status_code == 200
            report["api_cached_empty_snapshot"] = timings(read_api, 100)
        replay.loaded.cache_clear()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run()
