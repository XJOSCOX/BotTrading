"""Manual React/FastAPI launcher. UI restarts never terminate trading workers."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
import requests
from goxtrade.paths import ROOT, DATA_DIR
from goxtrade.runtime.live_process import _pid_running

PID_FILE = DATA_DIR / "native_web.pid"
WEB = ROOT / "web"
WORKSPACE = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]


def record():
    try:
        value = json.loads(PID_FILE.read_text(encoding="utf-8"))
        if type(value["pid"]) is not int or type(value["port"]) is not int or not 8504 <= value["port"] <= 8510:
            return None
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return None


def healthy(port):
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(f"http://127.0.0.1:{port}/api/health", timeout=1)
        return response.status_code == 200 and response.json() == dict(app="goxtrade-native", workspace=WORKSPACE)
    except (requests.RequestException, ValueError):
        return False


def status():
    saved = record()
    return dict(running=bool(saved and _pid_running(saved["pid"]) and healthy(saved["port"])),
                pid=saved["pid"] if saved else None, port=saved["port"] if saved else 8504)


def available_port():
    for port in range(8504, 8511):
        with closing(socket.socket()) as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Ports 8504-8510 are occupied. No existing process was stopped.")


def build_if_needed():
    output = WEB / "dist" / "index.html"
    sources = [WEB/"package.json", WEB/"package-lock.json", *list((WEB/"src").rglob("*"))]
    if output.exists() and all(path.stat().st_mtime <= output.stat().st_mtime for path in sources if path.is_file()):
        return
    executable = "npm.cmd" if os.name == "nt" else "npm"
    if not (WEB/"node_modules").exists():
        subprocess.run([executable, "ci", "--no-fund", "--no-audit"], cwd=WEB, check=True)
    command = [executable, "--script-shell=cmd.exe", "run", "build"] if os.name == "nt" else [executable, "run", "build"]
    subprocess.run(command, cwd=WEB, check=True)


def start(open_browser=False):
    current = status()
    if current["running"]:
        url = f"http://127.0.0.1:{current['port']}"
    else:
        saved = record()
        if saved and _pid_running(saved["pid"]):
            raise RuntimeError("The recorded interface is running but unhealthy. Use Restart; inspect native_api.err.log if needed.")
        if not importlib.util.find_spec("fastapi"):
            raise RuntimeError("Install requirements using the project .venv Python before starting the native interface.")
        build_if_needed()
        port = available_port()
        logs = DATA_DIR/"logs"
        logs.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, GOX_NATIVE_PORT=str(port), PYTHONPATH=str(ROOT))
        with (logs/"native_api.out.log").open("a", encoding="utf-8") as out, (logs/"native_api.err.log").open("a", encoding="utf-8") as error:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "goxtrade.api.app:app", "--app-dir", str(ROOT),
                                        "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
                                       cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=error,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        PID_FILE.write_text(json.dumps(dict(pid=process.pid, port=port)), encoding="utf-8")
        for _ in range(60):
            if healthy(port):
                break
            if process.poll() is not None:
                raise RuntimeError("Interface exited. See data/logs/native_api.err.log.")
            time.sleep(.25)
        else:
            raise RuntimeError("Interface startup timed out. Check logs before retrying.")
        url = f"http://127.0.0.1:{port}"
    print("GoXTrade: "+url)
    print("Interface only. Existing trading workers and Run/Pause choices are unchanged.")
    if open_browser:
        webbrowser.open(url)
    return url


def stop():
    saved = record()
    if not saved:
        print("No native interface process is recorded.")
        return
    pid = saved["pid"]
    if _pid_running(pid):
        if os.name == "nt":
            info = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                                  capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            command = info.stdout.lower()
            if info.returncode or "goxtrade.api.app:app" not in command or str(ROOT).lower() not in command:
                raise RuntimeError("Recorded PID is not a verified GoXTrade API. Nothing was terminated.")
            # No /T: children started by explicit UI actions must survive UI restart.
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            if not healthy(saved["port"]):
                raise RuntimeError("Cannot verify the recorded interface process")
            os.kill(pid, 15)
        for _ in range(30):
            if not _pid_running(pid):
                break
            time.sleep(.1)
    PID_FILE.unlink(missing_ok=True)
    print("Interface stopped. Trading workers were not stopped.")


def restart(open_browser=False):
    stop()
    return start(open_browser)


def menu():
    try:
        start(open_browser=True)
    except Exception as error:
        print(str(error))
    while True:
        print("\nGoXTrade control\n1. Open / start interface\n2. Restart interface (trading continues)\n3. Interface status\n4. Stop interface only\n5. Safely pause and stop trading workers\n6. Close this menu (app keeps running)")
        selection = input("Choose 1-6: ").strip()
        try:
            if selection == "1":
                start(open_browser=True)
            elif selection == "2":
                restart()
            elif selection == "3":
                print(json.dumps(status(), indent=2))
            elif selection == "4":
                stop()
            elif selection == "5":
                if input("Type STOP to pause entries and verify flat broker accounts: ").strip() == "STOP":
                    from goxtrade.runtime.manage_app import stop_workers
                    stop_workers()
            elif selection == "6":
                return
        except Exception as error:
            print("Action could not complete: "+str(error))


def main():
    action = sys.argv[1] if len(sys.argv)>1 else "menu"
    if action == "menu":
        menu()
    elif action == "start":
        start()
    elif action == "restart":
        restart()
    elif action == "stop":
        stop()
    elif action == "status":
        print(json.dumps(status()))
    else:
        raise ValueError("Use menu, start, restart, stop or status")


if __name__ == "__main__":
    main()
