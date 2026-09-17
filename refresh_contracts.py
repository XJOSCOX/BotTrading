from __future__ import annotations

from contracts import contract_search_text, expected_symbol_id, save_contract
from projectx_client import login, search_contracts
from symbol_store import load_symbols


def refresh_active_contracts() -> list[dict]:
    token = login()
    updates = []
    for symbol in load_symbols():
        search_text = contract_search_text(symbol)
        expected = expected_symbol_id(symbol)
        contracts = search_contracts(search_text, live=False, token=token)
        active = [
            contract
            for contract in contracts
            if contract.get("activeContract") and (not expected or contract.get("symbolId") == expected)
        ]
        if not active:
            continue
        selected = active[0]
        save_contract(symbol, selected["id"])
        updates.append(
            {
                "symbol": symbol,
                "contract_id": selected["id"],
                "name": selected.get("name"),
                "description": selected.get("description"),
            }
        )
    return updates


if __name__ == "__main__":
    for row in refresh_active_contracts():
        print(row)
