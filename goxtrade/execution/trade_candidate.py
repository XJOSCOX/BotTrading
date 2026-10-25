"""Immutable execution envelopes. Adapters require explicit account/contract facts."""
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math

from goxtrade.market.instruments import instrument, validate_contract_instrument
from goxtrade.strategies.strategy_catalog import strategy_spec


def stamp(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("Timezone-aware timestamp required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if result.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")
    return result.astimezone(timezone.utc)


def frozen_json(value):
    # A whitelist-shaped envelope, not a copy of broker responses or credentials.
    def check(obj):
        if isinstance(obj, dict):
            for key, item in obj.items():
                if any(word in str(key).lower() for word in ("password", "secret", "token", "api_key", "credential")):
                    raise ValueError("Credentials are prohibited in manager records")
                check(item)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                check(item)
    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(frozen_json(value).encode()).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def exposure_key(symbol):
    name = instrument(symbol).symbol
    return {"MNQ": "NQ", "MES": "ES", "MYM": "YM"}.get(name, name)


@dataclass(frozen=True)
class TradeCandidate:
    candidate_id: str
    strategy_id: str
    strategy_name: str
    symbol: str
    contract_id: str
    account_id: str
    profile: str
    direction: str
    timeframe: int
    classification: str
    created_at: str
    confirmed_at: str
    expires_at: str
    entry_reference: float | None
    price: float | None
    stop: float | None
    target: float | None
    management_mode: str
    session: str
    setup_id: str
    quote_at: str | None
    confirmed: bool
    history_complete: bool
    execution_eligible: bool
    config_json: str = "{}"
    evidence_json: str = "{}"
    risk_json: str = "{}"

    @property
    def exposure(self):
        return exposure_key(self.symbol)

    @property
    def reward_risk(self):
        if not all(finite(v) for v in (self.price, self.stop, self.target)) or self.price == self.stop:
            return None
        sign = 1 if self.direction == "LONG" else -1
        risk, reward = (self.price-self.stop)*sign, (self.target-self.price)*sign
        return reward/risk if risk > 0 and reward > 0 else None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**value)

    def at_price(self, price, time):
        return replace(self, price=price, quote_at=stamp(time).isoformat())


def adapt_alert(alert, *, account_id, profile, symbol, contract_id, price, quote_at,
                confirmed_at, expires_at, confirmed, history_complete, execution_eligible,
                config=None, session=None):
    """Legacy compatibility is additive; no mutation and no guessed execution facts."""
    spec = strategy_spec(alert.get("strategy_id") or alert.get("strategy"))
    if alert.get("strategy") and strategy_spec(alert["strategy"]).id != spec.id:
        raise ValueError("Conflicting strategy identities")
    if not isinstance(account_id, str) or not account_id.strip() or profile not in ("research", "paper", "practice", "leader"):
        raise ValueError("Explicit account identity and profile required")
    name = instrument(symbol).symbol
    if not isinstance(contract_id, str) or not contract_id.strip():
        raise ValueError("Actual executable contract required")
    validate_contract_instrument(name, contract_id)
    if alert.get("symbol") and exposure_key(alert["symbol"]) != exposure_key(name):
        raise ValueError("Alert and executable instrument disagree")
    if alert.get("direction") and alert.get("signal") and alert["direction"] != alert["signal"]:
        raise ValueError("Conflicting signal directions")
    setup = alert.get("consumption_key") or alert.get("crossover_key") or alert.get("unique_setup_id")
    if not isinstance(setup, str) or not setup:
        raise ValueError("Explicit stable source setup identity required")
    created = alert.get("detected_at") or alert.get("observed_at") or alert.get("entry_time")
    created, confirmation, expiry = (stamp(v).isoformat() for v in (created, confirmed_at, expires_at))
    mode = alert.get("entry_mode", "CONFIRMED")
    timeframe = alert.get("signal_minutes", spec.signal_minutes)
    evidence = {key: alert[key] for key in ("reason", "confirmation_method", "box", "candle_time", "source_contract") if key in alert}
    identity = dict(strategy=spec.id, setup=setup, account=account_id, profile=profile,
                    contract=contract_id, direction=alert.get("direction", alert.get("signal")))
    return TradeCandidate(digest(identity), spec.id, spec.name, name, contract_id, account_id, profile,
                          identity["direction"], timeframe, mode, created, confirmation, expiry,
                          alert.get("entry"), price, alert.get("initial_stop", alert.get("stop")), alert.get("target"),
                          alert.get("exit_mode", "unspecified"), session or alert.get("session_id") or "unspecified", setup,
                          stamp(quote_at).isoformat() if quote_at else None, confirmed, history_complete,
                          execution_eligible, frozen_json(config if config is not None else alert.get("config_snapshot", {})),
                          frozen_json(evidence), frozen_json({key: alert[key] for key in (
                              "management_minutes", "structure_lookback", "breaks_required", "trail_start_r", "trail_ticks",
                              "breakeven_r", "initial_stop", "setup_invalidation", "atr", "stop_buffer_ticks", "profit_policy",
                              "trail_buffer", "break_confirmations", "stop_atr") if key in alert}))
