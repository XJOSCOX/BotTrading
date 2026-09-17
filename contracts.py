from __future__ import annotations

import json
import re
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"
CONTRACTS_FILE = DATA_DIR / "contracts.json"
CONTRACT_RE = re.compile(r"^CON\.F\.US\.[A-Z0-9]+\.[FGHJKMNQUVXZ]\d{2}$")

DEFAULT_CONTRACTS = {
    "MNQ=F": "CON.F.US.MNQ.Z26",
    "MES=F": "CON.F.US.MES.Z26",
    "NQ=F": "CON.F.US.ENQ.Z26",
    "ES=F": "CON.F.US.EP.Z26",
    "YM=F": "CON.F.US.YM.Z26",
}


def load_contracts() -> dict[str, str]:
    contracts = DEFAULT_CONTRACTS.copy()
    if not CONTRACTS_FILE.exists():
        return contracts
    try:
        stored = json.loads(CONTRACTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return contracts
    for symbol, contract_id in stored.items():
        symbol_key = str(symbol).strip().upper()
        normalized_contract = str(contract_id).strip().upper()
        if symbol_key and is_valid_contract_id(normalized_contract):
            contracts[symbol_key] = normalized_contract
    return contracts


def save_contract(symbol: str, contract_id: str) -> None:
    symbol_key = str(symbol or "").strip().upper()
    normalized_contract = str(contract_id or "").strip().upper()
    if not symbol_key or not is_valid_contract_id(normalized_contract):
        return
    contracts = load_contracts()
    contracts[symbol_key] = normalized_contract
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONTRACTS_FILE.write_text(json.dumps(contracts, indent=2), encoding="utf-8")


def contract_for_symbol(symbol: str) -> str | None:
    return load_contracts().get(str(symbol or "").strip().upper())


def is_valid_contract_id(contract_id: str) -> bool:
    return bool(CONTRACT_RE.match(str(contract_id or "").strip().upper()))


def symbols_with_contracts(symbols: list[str]) -> list[dict[str, str]]:
    contracts = load_contracts()
    rows = []
    for symbol in symbols:
        contract_id = contracts.get(symbol.upper())
        if contract_id:
            rows.append({"symbol": symbol, "contract_id": contract_id})
    return rows


def contract_search_text(symbol: str) -> str:
    base = str(symbol or "").strip().upper()
    if base.endswith("=F"):
        base = base[:-2]
    return base.split(":")[-1].split(".")[0]


def expected_symbol_id(symbol: str) -> str | None:
    base = contract_search_text(symbol)
    mapping = {
        "MNQ": "F.US.MNQ",
        "MES": "F.US.MES",
        "NQ": "F.US.ENQ",
        "ES": "F.US.EP",
        "YM": "F.US.YM",
    }
    return mapping.get(base)
