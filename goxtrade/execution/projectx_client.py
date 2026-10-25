from __future__ import annotations

import os

import requests
from dotenv import load_dotenv, set_key
from goxtrade.paths import ROOT


ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH)


class ProjectXAuthError(RuntimeError):
    def __init__(self,message,code=None):
        super().__init__(message)
        self.code=code


def api_url() -> str:
    return os.getenv("PROJECTX_API_URL", "https://api.topstepx.com").rstrip("/")


def market_hub_url() -> str:
    return os.getenv("PROJECTX_MARKET_HUB_URL", "https://rtc.topstepx.com/hubs/market").rstrip("/")


def login() -> str:
    username = os.getenv("TOPSTEP_USERNAME", "").strip()
    api_key = os.getenv("TOPSTEP_API_KEY", "").strip()
    if not username or not api_key:
        raise ProjectXAuthError("Missing TOPSTEP_USERNAME or TOPSTEP_API_KEY in .env.")

    response = requests.post(
        f"{api_url()}/api/Auth/loginKey",
        json={"userName": username, "apiKey": api_key},
        headers={"accept": "text/plain", "Content-Type": "application/json"},
        timeout=15,
    )
    if response.status_code in (401,403):
        raise ProjectXAuthError("ProjectX authentication rejected; verify API credentials and permissions",code="AUTH_FAILED" if response.status_code==401 else "PERMISSION_DENIED")
    response.raise_for_status()
    data = response.json()
    if not data.get("success") or not data.get("token"):
        code="AUTH_FAILED" if data.get("errorCode")==3 else "PERMISSION_DENIED" if data.get("errorCode") in (7,9,10) else "UNKNOWN_ERROR"
        raise ProjectXAuthError("ProjectX authentication unavailable; verify credentials, agreements and subscription",code=code)
    return data["token"]


def post(path: str, payload: dict, token: str | None = None) -> dict:
    session_token = token or login()
    response = requests.post(
        f"{api_url()}{path}",
        json=payload,
        headers={
            "Authorization": f"Bearer {session_token}",
            "accept": "text/plain",
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def search_contracts(search_text: str, live: bool = False, token: str | None = None) -> list[dict]:
    data = post("/api/Contract/search", {"searchText": search_text, "live": live}, token=token)
    if not data.get("success"):
        raise ProjectXAuthError("ProjectX contract search refused; verify contract and subscription")
    return data.get("contracts", [])


def credentials_present() -> bool:
    return bool(os.getenv("TOPSTEP_USERNAME", "").strip() and os.getenv("TOPSTEP_API_KEY", "").strip())


def save_credentials(username: str, api_key: str) -> None:
    if not username.strip() or not api_key.strip() or any(c in username+api_key for c in "\r\n\x00"):
        raise ValueError("Username and API key must be non-empty single-line values")
    # dotenv quotes values and preserves unrelated local settings.
    set_key(ENV_PATH, "TOPSTEP_USERNAME", username.strip())
    set_key(ENV_PATH, "TOPSTEP_API_KEY", api_key.strip())
    load_dotenv(ENV_PATH, override=True)
