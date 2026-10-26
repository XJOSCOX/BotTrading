"""Operator reviews bind provider evidence to an immutable Practice identity."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from goxtrade.config import execution_identity as identity
from goxtrade.diagnostics.practice_validation import Blocked, exact_practice, fresh
from goxtrade.market import calendar_guard
from goxtrade.market.market_session import CENTRAL
from goxtrade.execution.practice_order_store import TestBlocked, digest
from goxtrade.execution.projectx_client import api_url


def identity_key(targets):
    return digest(dict(practice=targets["practice"], leader_id=targets["leader"]["id"],api_origin=api_url()))


def evidence(path, source_url):
    url = urlsplit(source_url)
    if (url.scheme != "https" or url.hostname not in ("topstep.com", "www.topstep.com", "dashboard.topstep.com", "topstepx.com", "www.topstepx.com", "help.topstep.com")
            or url.username or url.password or url.query or url.fragment):
        raise TestBlocked("Provider evidence must reference an official Topstep HTTPS page without credentials or query parameters")
    path = Path(path).resolve()
    if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".pdf") or not 0 < path.stat().st_size <= 10*1024*1024:
        raise TestBlocked("Provide a readable provider screenshot or PDF, at most 10 MiB")
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), source_url=source_url)


def review_account(store, broker, account_evidence, oco_evidence, confirm, now):
    targets = identity.current_targets()
    if identity.PROFILE != "practice":
        raise TestBlocked("Practice process only; Leader cannot run this test")
    account = exact_practice(broker.read("/api/Account/search", {"onlyActiveAccounts": False}), targets)
    payload = {"accountId": account["id"]}
    if broker.read("/api/Position/searchOpen", payload) or broker.read("/api/Order/searchOpen", payload):
        raise TestBlocked("Account must be flat before reviewing bracket settings")
    for item in (account_evidence, oco_evidence):
        if evidence(item["path"], item["source_url"])["sha256"] != item["sha256"]:
            raise TestBlocked("Provider evidence changed during review")
    summary = dict(account_id=account["id"], account_name=account["name"], profile="practice",
                   account_evidence=account_evidence["path"], oco_evidence=oco_evidence["path"],
                   affirmations="Inspect provider account management: this exact ID/name is resettable Practice, not Combine/XFA/funded/Leader. Inspect this account's Risk Settings: Auto OCO, isolated from copiers, no concurrent manual trading. No setting is changed by this command.")
    if not confirm(summary, f"VERIFY PRACTICE {account['id']}"):
        raise TestBlocked("Operator did not verify the exact Practice category and Auto OCO evidence")
    if identity.current_targets() != targets:
        raise TestBlocked("Account identity changed during review")
    record = dict(account_id=account["id"], identity_key=identity_key(targets), category="resettable_practice",
                  basis="OPERATOR_REVIEWED_PROVIDER_EVIDENCE", auto_oco=True, isolated=True,
                  account_evidence=account_evidence, oco_evidence=oco_evidence,
                  reviewed_at=now.isoformat(), expires_at=(now+timedelta(minutes=30)).isoformat())
    store.review("account", record)
    return dict(profile="practice", category=record["category"], basis=record["basis"], expires_at=record["expires_at"])


def account_review(store, targets, now):
    record = store.read("account", review=True)
    if (not record or record.get("identity_key") != identity_key(targets) or record.get("account_id") != targets["practice"]["id"]
            or record.get("category") != "resettable_practice" or record.get("auto_oco") is not True or record.get("isolated") is not True
            or not fresh(record.get("reviewed_at"), now, 1800)):
        raise TestBlocked("Missing, expired or changed exact-account provider/Auto OCO operator review")
    for key in ("account_evidence", "oco_evidence"):
        item = record[key]
        if evidence(item["path"], item["source_url"])["sha256"] != item["sha256"]:
            raise TestBlocked("Reviewed provider evidence changed; inspect and affirm again")
    return record


def review_calendar(store, path, confirm, now):
    path = Path(path).resolve()
    values = json.loads(path.read_text(encoding="utf-8"))
    calendar_guard.validate(values, now)
    if values.get("timezone") != "America/Chicago":
        raise TestBlocked("Review the MNQ calendar in America/Chicago")
    key = digest(values)
    if not confirm(values, "REVIEW CALENDAR "+key[:12]):
        raise TestBlocked("Actual calendar source/session review was not approved")
    store.review("calendar", dict(path=str(path), digest=key, approved_at=now.isoformat()))
    return dict(source=values["source_url"], validity=values["valid_until"], global_calendar_changed=False)


def calendar_review(store, now):
    record = store.read("calendar", review=True)
    if not record or not fresh(record.get("approved_at"), now, 7*86400):
        raise TestBlocked("Operator-reviewed test calendar is missing or stale")
    values = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    if digest(values) != record["digest"]:
        raise TestBlocked("Reviewed calendar changed; fresh review required")
    windows = calendar_guard.validate(values, now)
    current = next((end for begin, end in windows if begin <= now < end), None)
    if current is None or current-now <= timedelta(minutes=15):
        raise TestBlocked("Reviewed exchange session is closed or in its close buffer")
    if calendar_guard.CALENDAR_PATH.exists():
        existing = calendar_guard.restriction(now, required=True)
        if not existing["allow_entry"] or existing["flatten"]:
            raise TestBlocked("Existing global calendar restricts entries; no test override allowed")
    return record
