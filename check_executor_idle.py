"""Read-only restart preflight, run separately for each execution profile."""
import practice_executor as engine


if __name__ == "__main__":
    settings, _, jobs = engine.snapshot()
    assert not settings.get("enabled"), "Execution is running; do not restart"
    assert all(j["state"] in ("Closed", "Rejected") for j in jobs), "Unresolved jobs"
    token = engine.login()
    engine.verify_account(token)
    positions, orders = engine.account_state(token)
    assert not positions and not orders, "Broker is not flat"
    print(engine.PROFILE + ": paused, flat, no unresolved jobs")
