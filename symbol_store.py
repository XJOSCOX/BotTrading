import json
import re
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"
SYMBOLS_FILE = DATA_DIR / "symbols.json"
SYMBOL_RE = re.compile(r"^[A-Z0-9.^=_:!/-]{1,40}$")
DEFAULT_SYMBOLS = ["MNQ=F", "MES=F", "NQ=F", "ES=F"]


def normalize_symbol(value: str) -> str:
    return (value or "").strip().upper()


def is_valid_symbol(value: str) -> bool:
    return bool(SYMBOL_RE.match(normalize_symbol(value)))


def load_symbols() -> list[str]:
    if not SYMBOLS_FILE.exists():
        return DEFAULT_SYMBOLS.copy()

    try:
        data = json.loads(SYMBOLS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_SYMBOLS.copy()

    symbols = [normalize_symbol(item) for item in data if is_valid_symbol(str(item))]
    return symbols or DEFAULT_SYMBOLS.copy()


def save_symbols(symbols: list[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    unique = []
    for symbol in symbols:
        normalized = normalize_symbol(symbol)
        if is_valid_symbol(normalized) and normalized not in unique:
            unique.append(normalized)
    SYMBOLS_FILE.write_text(json.dumps(unique, indent=2), encoding="utf-8")


def add_symbol(symbol: str) -> tuple[bool, str]:
    normalized = normalize_symbol(symbol)
    if not is_valid_symbol(normalized):
        return False, "Use a valid ticker like MNQ=F, AAPL, or CME_MINI:MNQ1!."

    symbols = load_symbols()
    if normalized in symbols:
        return False, f"{normalized} is already on the dashboard."

    symbols.append(normalized)
    save_symbols(symbols)
    return True, f"Added {normalized}."


def remove_symbol(symbol: str) -> None:
    target = normalize_symbol(symbol)
    save_symbols([item for item in load_symbols() if item != target])
