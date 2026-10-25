"""One explicit research worker per process with a cross-process SQLite claim."""
from concurrent.futures import ThreadPoolExecutor
import threading
from goxtrade.data import lab_store as store

_pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix="gox-research")
_lock = threading.Lock()
_futures = {}


def perform(identifier):
    job=None
    try:
        job = store.claim(identifier)
        if job is None:
            return
        if job["kind"] == "history":
            from goxtrade.data.history_download import download
            download(identifier)
        elif job["kind"] == "validation":
            from goxtrade.research.validation_lab import execute
            execute(identifier)
        else:
            raise ValueError("Unknown research job kind")
    except InterruptedError:
        store.update_job(identifier,status="cancelled",message="Research cancelled; completed datasets/results preserved")
    except ValueError as error:
        # Internal validation errors are deliberately credential-free.
        current = store.get("lab_jobs",identifier)
        if job is None or current.get("owner") != job.get("owner") or current["status"] != "running" or "already running" in str(error) or "Another research job" in str(error):
            return
        store.update_job(identifier,status="failed",message=str(error)[:500])
    except Exception as error:
        current=store.get("lab_jobs",identifier)
        if job and current.get("owner")==job.get("owner"):
            store.update_job(identifier,expected_owner=job["owner"],status="failed",message=f"Research stopped ({type(error).__name__}); no raw provider response or credentials logged")


def start(identifier):
    with _lock:
        for key in list(_futures):
            if _futures[key].done():
                _futures.pop(key)
        previous = _futures.get(identifier)
        if previous is not None and not previous.done():
            return store.get("lab_jobs",identifier)
        _futures[identifier] = _pool.submit(perform,identifier)
    return store.get("lab_jobs",identifier)


def cancel(identifier):
    current = store.get("lab_jobs",identifier)
    if current["status"] == "complete":
        return current
    return store.update_job(identifier,cancel=True,status="cancelled" if current["status"] != "running" else "running")
