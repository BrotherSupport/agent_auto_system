"""In-process task registry for asyncio.Task cancellation."""
import asyncio
import threading

_TASKS: dict[int, asyncio.Task] = {}
_LOCK = threading.Lock()


def register(run_id: int, task: asyncio.Task) -> None:
    with _LOCK:
        _TASKS[run_id] = task


def cancel(run_id: int) -> bool:
    """Cancel the task for run_id. Returns True if the task was found and cancelled."""
    with _LOCK:
        task = _TASKS.pop(run_id, None)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def unregister(run_id: int) -> None:
    with _LOCK:
        _TASKS.pop(run_id, None)
