from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)


class ProjectXAuthError(RuntimeError):
    pass


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
    response.raise_for_status()
    data = response.json()
    if not data.get("success") or not data.get("token"):
        raise ProjectXAuthError(f"ProjectX login failed: {data}")
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
        raise ProjectXAuthError(f"Contract search failed: {data}")
    return data.get("contracts", [])


def credentials_present() -> bool:
    return bool(os.getenv("TOPSTEP_USERNAME", "").strip() and os.getenv("TOPSTEP_API_KEY", "").strip())


def save_credentials(username: str, api_key: str) -> None:
    lines = {
        "TOPSTEP_USERNAME": username.strip(),
        "TOPSTEP_API_KEY": api_key.strip(),
        "PROJECTX_API_URL": api_url(),
        "PROJECTX_MARKET_HUB_URL": market_hub_url(),
    }
    content = "\n".join(f"{key}={value}" for key, value in lines.items()) + "\n"
    ENV_PATH.write_text(content, encoding="utf-8")
    load_dotenv(ENV_PATH, override=True)
