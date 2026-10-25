"""Stable strategy identities; display names remain compatible with saved alerts."""
from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class StrategySpec:
    id: str
    name: str
    signal_minutes: int = 15
    indicators: tuple = ()
    lookback_bars: int = 60
    modes: tuple = ("CONFIRMED",)
    symbols: tuple = ("NQ=F", "ES=F", "YM=F")
    cooldown_minutes: int = 5
    risk_policy: str = "buffered-v2"
    execution_profiles: tuple = ("practice", "leader")
    required_data: tuple = ("completed_minutes", "fresh_trade", "broker_reconciliation")
    entry_policy: str = "legacy-multiframe"
    runtime_adapter: str | None = None
    category: str = "reversal"
    correlation_group: str = "US_EQUITY_INDICES"
    default_priority: int = 100
    session_eligibility: tuple = ("exchange_open",)
    confirmation_required: str = "strategy_revalidated"
    expiration_seconds: int = 90


SPECS = (
    StrategySpec("crt", "CRT", indicators=("range",)),
    StrategySpec("reversal", "Reversal", indicators=("rsi14",)),
    StrategySpec("orb", "ORB", indicators=("opening_range",), category="breakout"),
    StrategySpec("vwap_reclaim", "VWAP Reclaim", indicators=("hlc3_vwap", "ema20", "ema50"), category="trend_continuation"),
    StrategySpec("ema_pullback", "EMA Pullback", indicators=("ema20", "ema50", "rsi14"), category="trend_continuation"),
    StrategySpec("vwap_ema_cross", "VWAP EMA Cross", signal_minutes=3,
                 indicators=("ohlc4_session_vwap", "ema9_close"), lookback_bars=45,
                 modes=("CONFIRMED", "REALTIME", "ANTICIPATORY"), cooldown_minutes=0,
                 execution_profiles=("practice", "leader"), risk_policy="strategy-snapshot-v1",
                 required_data=("complete_session_trade_ohlcv", "fresh_trade", "broker_reconciliation"),
                 entry_policy="indicator-event-v1", runtime_adapter="goxtrade.strategies.vwap_ema_runtime", category="momentum"),
    StrategySpec("previous_day_box", "Previous Day Box Reversal", signal_minutes=15,
                 indicators=("previous_session_box", "rejection", "sweep", "confirmed_structure"),
                 lookback_bars=1440, execution_profiles=("practice", "leader"), risk_policy="previous-box-snapshot-v1",
                 required_data=("complete_previous_contract_session", "completed_15m", "fresh_trade", "broker_reconciliation"),
                 entry_policy="previous-box-v1", runtime_adapter="goxtrade.strategies.previous_day_box_runtime"),
)
STRATEGIES = tuple(spec.name for spec in SPECS)
LEGACY_STRATEGIES = tuple(spec.name for spec in SPECS if spec.runtime_adapter is None)
NEW_STRATEGIES = LEGACY_STRATEGIES[2:]
DEFAULT_EXECUTION = ("CRT", "Reversal")


def strategy_spec(value):
    for spec in SPECS:
        if value in (spec.id, spec.name):
            return spec
    raise ValueError(f"Unknown strategy: {value}")


def crossover_key(signal):
    """Trading consumption spans mode/settings changes; research event IDs remain distinct."""
    if signal.get("strategy_id") != "vwap_ema_cross" and signal.get("strategy") != "VWAP EMA Cross":
        return None
    values = ["vwap_ema_cross", signal.get("reference_symbol") or signal.get("symbol"), signal.get("source_contract"),
              signal.get("session_id"), signal.get("signal_minutes"), signal.get("candle_time") or signal.get("setup_time"),
              signal.get("direction") or signal.get("signal")]
    if any(value is None for value in values):
        return None
    return hashlib.sha256("|".join(map(str, values)).encode()).hexdigest()


def execution_block(signal, profile):
    """Use at both selection and submission; stored permission lists cannot override this."""
    if not isinstance(signal, dict):
        return "Invalid strategy metadata"
    snapshot = signal.get("config_snapshot")
    marked = (signal.get("entry_policy") == "indicator-event-v1"
              or signal.get("entry_mode") in ("REALTIME", "ANTICIPATORY")
              or str(signal.get("raw_signal", "")).startswith("ANTICIPATED_")
              or "ema" in signal and "vwap" in signal
              or not signal.get("strategy_id") and not signal.get("strategy") and signal.get("signal_minutes", 15) != 15
              or isinstance(snapshot, dict) and bool({"ema_length", "vwap_source"} & snapshot.keys()))
    identities = [signal[key] for key in ("strategy_id", "strategy") if signal.get(key) is not None]
    try:
        specs = [strategy_spec(value) for value in identities]
    except (ValueError, TypeError):
        return "Unknown strategy is not eligible for execution"
    if len({spec.id for spec in specs}) > 1:
        return "Conflicting strategy ID and display name"
    identity = identities[0] if identities else None
    if identity is None:
        if marked:
            return "Indicator order is missing its canonical strategy identity"
        return None  # Legacy connection checks and already-saved jobs have no strategy metadata.
    try:
        spec = strategy_spec(identity)
    except ValueError:
        return "Unknown strategy is not eligible for execution"
    if profile not in spec.execution_profiles:
        return f"{spec.name} is disabled for {profile.title()} execution"
    if spec.id == "previous_day_box":
        from goxtrade.strategies.strategy_settings import read_previous_day_box_config
        from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
        current = read_previous_day_box_config()
        if not getattr(current, profile+"_enabled", False) or not current.monitor_enabled:
            return "Previous Day Box "+profile.title()+" execution has not been explicitly enabled"
        if (signal.get("reference_symbol") or signal.get("symbol")) and (signal.get("reference_symbol") or signal.get("symbol")) not in current.enabled_symbols:
            return "Previous Day Box symbol is disabled"
        if "entry" in signal or "alert_id" in signal:
            try:
                frozen = PreviousDayBoxConfig.from_dict(snapshot)
                valid = (isinstance(snapshot,dict) and signal.get("entry_policy")==spec.entry_policy
                         and signal.get("config_fingerprint")==frozen.fingerprint and signal.get("signal_minutes")==15
                         and signal.get("entry_mode")=="CONFIRMED" and signal.get("source_contract")
                         and signal.get("unique_setup_id") and signal.get("consumption_key"))
                from goxtrade.strategies.previous_day_box import setup_keys
                consumed,unique = setup_keys({**signal,"symbol":signal.get("reference_symbol") or signal.get("symbol")})
                valid = valid and consumed==signal.get("consumption_key") and unique==signal.get("unique_setup_id")
                if not valid: return "Incomplete or inconsistent previous-day box execution envelope"
            except (ValueError,TypeError,KeyError):
                return "Invalid frozen previous-day box configuration"
        return None
    if marked and spec.id != "vwap_ema_cross":
        return "Indicator metadata does not match the declared legacy strategy"
    if spec.entry_policy != "indicator-event-v1" and signal.get("signal_minutes", spec.signal_minutes) != spec.signal_minutes:
        return "Signal timeframe does not match the declared strategy"
    if spec.entry_policy == "indicator-event-v1":
        if signal.get("entry_mode") not in spec.modes:
            return "Unsupported strategy entry mode"
        if "entry" in signal or "alert_id" in signal:
            from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
            try:
                frozen = VwapEmaConfig.from_dict(snapshot)
            except (ValueError, TypeError, KeyError):
                return "Invalid frozen indicator configuration"
            event = signal.get("unique_setup_id")
            if (not isinstance(snapshot, dict) or signal.get("entry_policy") != spec.entry_policy
                    or signal.get("config_fingerprint") != frozen.fingerprint
                    or signal.get("signal_minutes") != frozen.signal_minutes
                    or signal["entry_mode"] != frozen.entry_mode or not isinstance(event, str)
                    or len(event) != 64 or any(c not in "0123456789abcdef" for c in event)):
                return "Incomplete or inconsistent indicator execution envelope"
            if signal.get("crossover_key") != crossover_key(signal) or signal.get("crossover_key") is None:
                return "Missing or inconsistent crossover consumption identity"
        from goxtrade.strategies.strategy_settings import read_vwap_ema_config
        config = read_vwap_ema_config()
        if not getattr(config, profile+"_enabled", False):
            return "VWAP EMA Cross "+profile.title()+" execution has not been explicitly enabled"
        aliases = {"MNQ": "NQ=F", "MES": "ES=F", "MYM": "YM=F",
                   "MNQ=F": "NQ=F", "MES=F": "ES=F", "MYM=F": "YM=F"}
        symbol = aliases.get(signal.get("symbol"), signal.get("symbol"))
        selected = {aliases.get(value, value) for value in config.enabled_symbols}
        if not config.monitor_enabled or (symbol and symbol not in selected):
            return "Strategy monitoring or this symbol is disabled"
    return None


def order_block(signal, profile, now=None):
    """Submission boundary: stronger than settings/list eligibility."""
    blocked = execution_block(signal, profile)
    if blocked:
        return blocked
    if signal.get("strategy_id") in ("vwap_ema_cross","previous_day_box") or signal.get("strategy") in ("VWAP EMA Cross","Previous Day Box Reversal"):
        from datetime import datetime, timezone
        from goxtrade.market.calendar_guard import entry_block
        return entry_block(now or datetime.now(timezone.utc))
    return None
