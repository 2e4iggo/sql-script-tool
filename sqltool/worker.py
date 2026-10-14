"""Run blocking work on a background thread; deliver results on the Tk thread."""
import queue
import threading
import traceback


class Cancelled(Exception):
    pass


class Job:
    def __init__(self):
        self._cancel = threading.Event()
        self._queue = queue.Queue()

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def check(self):
        """Call from the worker between units of work."""
        if self._cancel.is_set():
            raise Cancelled()

    def progress(self, *args):
        """Call from the worker; on_progress(*args) runs on the Tk thread."""
        self._queue.put(("progress", args))


def run_bg(widget, fn, on_ok=None, on_err=None, on_progress=None, on_done=None, poll_ms=50):
    """fn(job) runs in a thread. Callbacks run on the Tk thread via widget.after."""
    job = Job()

    def target():
        try:
            job._queue.put(("ok", fn(job)))
        except Cancelled:
            job._queue.put(("cancelled", None))
        except Exception as e:
            e.traceback_text = traceback.format_exc()
            job._queue.put(("err", e))

    def poll():
        try:
            while True:
                kind, payload = job._queue.get_nowait()
                if kind == "progress":
                    if on_progress:
                        on_progress(*payload)
                    continue
                if kind == "ok" and on_ok:
                    on_ok(payload)
                elif kind == "err" and on_err:
                    on_err(payload)
                if on_done:
                    on_done(kind)
                return
        except queue.Empty:
            pass
        widget.after(poll_ms, poll)

    threading.Thread(target=target, daemon=True).start()
    widget.after(poll_ms, poll)
    return job
