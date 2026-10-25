"""Explicit deterministic fixture benchmark, never production market data/results."""
import json
import time
from dataclasses import replace
import pandas as pd
from goxtrade.research.portfolio_backtest import run_portfolio_backtest,prepare_portfolio
from tests.manager_fixtures import policy,CONTRACT


def run():
    frame=pd.DataFrame(dict(time=pd.date_range("2026-10-05T13:30:00Z",periods=10000,freq="min"),open=100.,high=101.,low=99.,close=100.,volume=10.))
    frame.attrs["contract_id"]=CONTRACT
    datasets=[("MNQ",CONTRACT,frame)]
    settings=policy(participating=())
    began=time.perf_counter();prepared=prepare_portfolio(datasets);prepared_seconds=time.perf_counter()-began
    began=time.perf_counter()
    result=run_portfolio_backtest(datasets,settings,prepared=prepared)
    seconds=time.perf_counter()-began
    # Same stepping kernel, measured incrementally; no chart, provider or broker I/O.
    checkpoint=None;began=time.perf_counter()
    for _ in range(100):
        result_step=run_portfolio_backtest(datasets,settings,prepared=prepared,checkpoint=checkpoint,max_steps=100)
        checkpoint={**result_step["checkpoint"],"state":result_step["state"]}
    incremental=time.perf_counter()-began
    assert result_step["state"]==result["state"]
    print(json.dumps(dict(scope="TEST FIXTURE / no eligible strategies / OHLC kernel and checkpoints only / not live latency",candles=10000,prepare_seconds=prepared_seconds,batch_seconds=seconds,incremental_100_batches_seconds=incremental,trades=len(result["state"]["trades"]),parity=True)))


if __name__=="__main__":run()
