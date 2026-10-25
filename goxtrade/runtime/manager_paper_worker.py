"""Explicitly started independent paper process. No broker imports or submission path."""
from contextlib import contextmanager
import logging
import os
import subprocess
import sys
import time

from goxtrade.paths import DATA_DIR, ROOT


@contextmanager
def single_worker():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with (DATA_DIR/"portfolio_paper.lock").open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def start():
    from goxtrade.execution.manager_service import policy
    if not policy().paper_enabled:
        raise ValueError("Explicitly enable separate portfolio paper mode with costs first")
    log_dir = DATA_DIR/"logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir/"portfolio_paper.log").open("ab") as log:
        subprocess.Popen([sys.executable, "-m", "goxtrade.runtime.manager_paper_worker"], cwd=ROOT,
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return "Portfolio paper worker requested. It cannot submit broker orders; duplicate processes exit without advancing state."


def main():
    from goxtrade.execution.manager_service import paper_once
    try:
        with single_worker():
            while True:
                try:
                    result = paper_once()
                    if result.get("enabled") is False:
                        break
                except Exception as error:
                    # Only the error type is logged; no raw provider/account payloads.
                    logging.warning("Portfolio paper cycle unavailable (%s); no synthetic fills", type(error).__name__)
                time.sleep(1)
    except OSError:
        return


if __name__ == "__main__":
    main()
