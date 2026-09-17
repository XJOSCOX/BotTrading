"""Isolated leader worker and explicitly invoked UI commands. Never targets followers."""
import json
import sys
from execution_target import PROFILE, TARGET


def handle_command(request):
    if PROFILE != "leader":
        raise ValueError("Leader commands require an isolated leader process")
    import practice_executor as executor
    import bot_controls
    action = request.get("action")
    if action in ("arm","emergency") and request.get("confirmed_account") != TARGET["name"]:
        raise ValueError("Confirm the exact leader account")
    if action == "configure":
        enable_mym = request.get("enable_mym", False)
        if type(enable_mym) is not bool:
            raise ValueError("MYM activation must be true or false")
        executor.configure(request["quantities"],enable_mym)
        bot_controls.save(["MNQ","MES"] + (["MYM"] if enable_mym else []),request.get("strategies",["CRT","Reversal"]),request.get("cooldown",5))
    elif action == "arm":
        if request.get("copier_confirmed") is not True:
            raise ValueError("Confirm Topstep copier and protective-order settings")
        # Refuse startup against a legacy Practice worker that lacks the account-switch lock.
        from contextlib import closing
        from live_store import connect
        from datetime import datetime,timezone
        with closing(connect()) as conn:
            row = conn.execute("SELECT status FROM practice_control WHERE id=1").fetchone()
        status = json.loads(row[0]) if row else {}
        if status.get("version") != "accounts-v1" or (datetime.now(timezone.utc)-datetime.fromisoformat(status["updated_at"])).total_seconds()>45:
            raise ValueError("Updated Practice/feed worker must be online before leader activation")
        executor.arm(500,500,True,request["quantities"],acknowledge_loss=request.get("acknowledge_loss") is True,enable_mym=executor.snapshot()[0].get("enable_mym") is True)
    elif action == "pause":
        executor.pause()
    elif action == "emergency":
        executor.request_emergency_close(True)
    else:
        raise ValueError("Unsupported leader command")


def main():
    if PROFILE != "leader":
        raise RuntimeError("Refusing to run leader worker without explicit target")
    if sys.argv[1:] == ["command"]:
        try:
            handle_command(json.loads(sys.stdin.read()))
            print(json.dumps(dict(success=True)))
        except Exception as error:
            print(json.dumps(dict(success=False,message=str(error) if isinstance(error,ValueError) else "Leader preflight failed. Verify account, feed and broker state.")))
        return
    if sys.argv[1:]:
        raise RuntimeError("Unknown worker arguments")
    from pathlib import Path
    import msvcrt
    from threading import Thread
    import practice_executor
    import practice_history
    # OS lock is released on exit, preventing duplicate leader execution loops.
    with (Path(__file__).parent/"data"/"leader_worker.lock").open("a+b") as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        Thread(target=practice_history.run,name="leader-history",daemon=True).start()
        practice_executor.run_practice()


if __name__ == "__main__":
    main()
