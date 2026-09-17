"""Explicitly invoked, single-contract Practice round-trip test. Never retries orders."""
import time
from datetime import datetime, timezone
import practice_executor as e


def main():
    settings, _, jobs = e.snapshot()
    if settings.get("enabled") or any(j["state"] not in ("Closed", "Rejected") for j in jobs):
        raise RuntimeError("Practice must be paused with no unresolved jobs")
    token = e.login()
    e.verify_account(token)
    positions, orders = e.account_state(token)
    if positions or orders:
        raise RuntimeError("Practice is not flat")
    contracts = e.call("/api/Contract/search", {"searchText": "MES", "live": False}, token)["contracts"]
    matches = [c for c in contracts if c.get("symbolId") == "F.US.MES" and c.get("activeContract") is True]
    if len(matches) != 1:
        raise RuntimeError("No unique MES contract")
    contract = matches[0]
    ident = -time.time_ns() // 1000000
    job = dict(alert_id=ident, symbol="MES", contract_id=contract["id"], quantity=1, side=0,
               state="Intent", sent_at=time.time(), tag=f"gx-test-{abs(ident)}", stop_ticks=20)
    payload = e.build_order(dict(id=ident, symbol="ES=F", signal="LONG", entry=100, stop=95), contract, 1, 25)
    payload["customTag"] = job["tag"]
    if not e.claim(job):
        raise RuntimeError("Test already claimed")
    try:
        response = e.post("/api/Order/place", payload, token=token)
        job.update(state="Submitted" if response.get("success") is True else "Rejected",
                   order_id=response.get("orderId"), error_code=response.get("errorCode"),
                   error_message=str(response.get("errorMessage") or "")[:500])
        e.save_job(job)
    except Exception:
        job.update(state="Unknown", error_message="Test submission response uncertain; do not retry")
        e.save_job(job)
        raise
    print({"state": job["state"], "order": job.get("order_id"), "reason": job.get("error_message")}, flush=True)
    if job["state"] == "Rejected":
        return
    for _ in range(10):
        positions, orders = e.account_state(token)
        position = next((p for p in positions if p["contractId"] == job["contract_id"]), None)
        if position:
            if position.get("size") != 1 or position.get("type") != 1:
                raise RuntimeError("Unexpected position; manual review required")
            job.update(state="Open", fill_price=position.get("averagePrice"),
                       protected=any(o.get("contractId") == job["contract_id"] and o.get("type") == 4 for o in orders))
            e.save_job(job)
            print({"filled": job["fill_price"], "backup_stop_visible": job["protected"]}, flush=True)
            job.update(close_time=time.time(), close_reason="User-requested connection test")
            e.close_job(job, token)
            break
        time.sleep(1)
    else:
        raise RuntimeError("Fill not observed; no retry. Check broker state.")
    for _ in range(10):
        positions, orders = e.account_state(token)
        if not positions and not orders:
            job.update(state="Closed", closed_confirmed_at=datetime.now(timezone.utc).isoformat())
            e.save_job(job)
            print({"state": "Closed", "open_positions": 0, "open_orders": 0}, flush=True)
            return
        time.sleep(1)
    raise RuntimeError("Close submitted but account not confirmed flat; manual review required")


if __name__ == "__main__":
    main()
