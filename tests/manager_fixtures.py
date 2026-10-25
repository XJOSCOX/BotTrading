"""Deterministic architecture fixtures, never market or profitability evidence."""
from dataclasses import replace

from goxtrade.execution.execution_policy import ExecutionPolicy
from goxtrade.execution.portfolio_risk import PortfolioState
from goxtrade.execution.trade_candidate import adapt_alert, digest

NOW = "2026-10-22T15:00:00+00:00"
CONTRACT = "CON.F.US.MNQ.Z26"


def candidate(strategy="crt", direction="LONG", symbol="MNQ", key="setup-a", **changes):
    contract = {"MNQ": CONTRACT, "MES": "CON.F.US.MES.Z26", "MYM": "CON.F.US.MYM.Z26", "NQ": "CON.F.US.ENQ.Z26"}[symbol]
    raw = dict(strategy_id=strategy, signal=direction, entry=100., stop=90. if direction == "LONG" else 110.,
               target=120. if direction == "LONG" else 80., unique_setup_id=key, detected_at=NOW,
               exit_mode="fixed", signal_minutes=3 if strategy == "vwap_ema_cross" else 15)
    result = adapt_alert(raw, account_id="test", profile="research", symbol=symbol, contract_id=contract,
        price=100., quote_at=NOW, confirmed_at=NOW, expires_at="2026-10-22T15:02:00+00:00",
        confirmed=True, history_complete=True, execution_eligible=True, config={"entry_window_seconds": 120})
    result = replace(result, **changes)
    return replace(result, candidate_id=digest(dict(strategy=result.strategy_id, setup=result.setup_id, account=result.account_id,
                                                   profile=result.profile, contract=result.contract_id, direction=result.direction)))


def policy(**changes):
    return replace(ExecutionPolicy(commission_per_side=.5), **changes).validate()


def facts(**changes):
    return replace(PortfolioState("test", "research", NOW, session_allowed=True,
        session_reason="Fixture open", contracts=(("MNQ", CONTRACT), ("MES", "CON.F.US.MES.Z26"), ("MYM", "CON.F.US.MYM.Z26"))), **changes)
