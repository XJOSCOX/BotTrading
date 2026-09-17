"""Read-only account discovery and local sizing preferences. No order endpoints."""
import json
from pathlib import Path
from projectx_client import post

MICROS = ("MNQ", "MES", "MYM")
SETTINGS = Path(__file__).resolve().parent / "data" / "live_preferences.json"
COPY_PROFILE = Path(__file__).resolve().parent / "copy_accounts.json"


def copy_role(account):
    try:
        profile = json.loads(COPY_PROFILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "Not assigned"
    if account.get("name") == profile.get("leader"):
        return "Leader"
    if account.get("name") in profile.get("followers", []):
        return "Follower"
    return "Not assigned"


def enabled_accounts(accounts):
    return sorted((a for a in accounts if a.get("canTrade") is True),
                  key=lambda a: ({"Leader": 0, "Follower": 1}.get(copy_role(a), 2), str(a.get("name", ""))))


def search_accounts():
    response = post("/api/Account/search", {"onlyActiveAccounts": False})
    if response.get("success") is not True or not isinstance(response.get("accounts"), list):
        raise RuntimeError("Topstep could not return the account list.")
    return response["accounts"]


def load_preferences():
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def quantities_for(account_id):
    values = load_preferences().get("accounts", {}).get(str(account_id), {})
    return {symbol: values.get(symbol) if type(values.get(symbol)) is int and 1 <= values[symbol] <= 4 else 2 for symbol in MICROS}


def save_quantities(account_id, quantities):
    if type(account_id) is not int or account_id <= 0:
        raise ValueError("Select a valid account.")
    if set(quantities) != set(MICROS) or any(type(q) is not int or not 1 <= q <= 4 for q in quantities.values()):
        raise ValueError("Micro quantities must be whole numbers from 1 to 4.")
    data = load_preferences()
    data.setdefault("accounts", {})[str(account_id)] = quantities
    data["selected_account"] = account_id
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    temp = SETTINGS.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp.replace(SETTINGS)
