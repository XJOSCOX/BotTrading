"""Stable strategy identities; display names remain compatible with saved alerts."""
from dataclasses import dataclass


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


SPECS = (
    StrategySpec("crt", "CRT", indicators=("range",)),
    StrategySpec("reversal", "Reversal", indicators=("rsi14",)),
    StrategySpec("orb", "ORB", indicators=("opening_range",)),
    StrategySpec("vwap_reclaim", "VWAP Reclaim", indicators=("hlc3_vwap", "ema20", "ema50")),
    StrategySpec("ema_pullback", "EMA Pullback", indicators=("ema20", "ema50", "rsi14")),
    StrategySpec("vwap_ema_cross", "VWAP EMA Cross", signal_minutes=3,
                 indicators=("ohlc4_session_vwap", "ema9_close"), lookback_bars=45,
                 modes=("CONFIRMED", "REALTIME", "ANTICIPATORY"), cooldown_minutes=0,
                 execution_profiles=("practice",), risk_policy="strategy-snapshot-v1",
                 required_data=("complete_session_trade_ohlcv", "fresh_trade", "broker_reconciliation"),
                 entry_policy="indicator-event-v1", runtime_adapter="goxtrade.strategies.vwap_ema_runtime"),
)
STRATEGIES = tuple(spec.name for spec in SPECS)
LEGACY_STRATEGIES = STRATEGIES[:-1]
NEW_STRATEGIES = LEGACY_STRATEGIES[2:]
DEFAULT_EXECUTION = ("CRT", "Reversal")


def strategy_spec(value):
    for spec in SPECS:
        if value in (spec.id, spec.name):
            return spec
    raise ValueError(f"Unknown strategy: {value}")


def execution_block(signal, profile):
    """Use at both selection and submission; stored permission lists cannot override this."""
    identity = signal.get("strategy_id") or signal.get("strategy")
    if identity is None:
        return None  # Legacy connection checks and already-saved jobs have no strategy metadata.
    try:
        spec = strategy_spec(identity)
    except ValueError:
        return "Unknown strategy is not eligible for execution"
    if profile not in spec.execution_profiles:
        return f"{spec.name} is disabled for {profile.title()} execution"
    if spec.entry_policy == "indicator-event-v1":
        if signal.get("entry_mode") not in spec.modes:
            return "Unsupported strategy entry mode"
        from goxtrade.strategies.strategy_settings import read_vwap_ema_config
        config = read_vwap_ema_config()
        if not config.practice_enabled:
            return "VWAP EMA Cross Practice execution has not been explicitly enabled"
        aliases = {"MNQ": "NQ=F", "MES": "ES=F", "MYM": "YM=F",
                   "MNQ=F": "NQ=F", "MES=F": "ES=F", "MYM=F": "YM=F"}
        symbol = aliases.get(signal.get("symbol"), signal.get("symbol"))
        selected = {aliases.get(value, value) for value in config.enabled_symbols}
        if not config.monitor_enabled or (symbol and symbol not in selected):
            return "Strategy monitoring or this symbol is disabled"
    return None
