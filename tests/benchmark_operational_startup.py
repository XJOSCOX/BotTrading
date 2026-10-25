"""Opt-in real local API lifecycle test, isolated DB; provider POSTs are forbidden."""
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import requests
from goxtrade.paths import ROOT


def run():
    port = None
    for candidate in range(8505, 8511):
        with closing(socket.socket()) as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
                port = candidate
                break
            except OSError:
                continue
    if port is None:
        raise RuntimeError("No isolated test port available; no existing process was stopped")
    source = """
import os
from pathlib import Path
from goxtrade.data import live_store
live_store.DB_PATH=Path(os.environ['GOX_ACCEPTANCE_DB'])
from goxtrade.execution import projectx_client
def forbidden(*args,**kwargs):
    raise AssertionError('Provider requests forbidden during local lifecycle tests')
projectx_client.login=forbidden
projectx_client.post=forbidden
projectx_client.requests.post=forbidden
from goxtrade.api.app import create_app
import uvicorn
uvicorn.run(create_app(),host='127.0.0.1',port=int(os.environ['GOX_NATIVE_PORT']),log_level='error',access_log=False)
"""
    startup, shutdown, calls = [], [], []
    with tempfile.TemporaryDirectory() as directory, requests.Session() as browser:
        browser.trust_env = False
        for index in range(3):
            browser.cookies.clear()
            env = dict(os.environ, GOX_NATIVE_PORT=str(port), GOX_ACCEPTANCE_DB=str(Path(directory)/f"cycle-{index}.db"))
            began = time.perf_counter()
            process = subprocess.Popen([sys.executable, "-c", source], cwd=ROOT, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                deadline = time.monotonic()+20
                while True:
                    if process.poll() is not None or time.monotonic()>deadline:
                        raise RuntimeError("Isolated API failed startup; no account worker was touched")
                    try:
                        response = browser.get(f"http://127.0.0.1:{port}/api/health", timeout=.5)
                        if response.status_code == 200 and response.json().get("app") == "goxtrade-native":
                            break
                    except (requests.RequestException, ValueError):
                        pass
                    time.sleep(.05)
                startup.append(1000*(time.perf_counter()-began))
                assert browser.get(f"http://127.0.0.1:{port}/api/session", timeout=2).status_code == 200
                for _ in range(20):
                    began = time.perf_counter()
                    response = browser.get(f"http://127.0.0.1:{port}/api/diagnostics", timeout=3)
                    calls.append(1000*(time.perf_counter()-began))
                    assert response.status_code == 200
                    assert response.json()["broker_execution"] is False
                    assert response.json()["operational"]["production"]["storage"] == "MISSING"
                assert not Path(env["GOX_ACCEPTANCE_DB"]).exists(), "Passive diagnostics must not create the account database"
                assert process.poll() is None
            finally:
                began = time.perf_counter()
                process.terminate()  # Only the child handle created by this test.
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                shutdown.append(1000*(time.perf_counter()-began))
    print(json.dumps(dict(scope="ISOLATED LOCAL API / forced child shutdown, not broker recovery",cycles=3,
        startup_ms=startup,shutdown_ms=shutdown,diagnostics_requests=len(calls),
        diagnostics_median_ms=statistics.median(calls),diagnostics_p95_ms=sorted(calls)[int(len(calls)*.95)],
        provider_requests=0,account_workers_touched=0), indent=2))


if __name__ == "__main__":
    run()
