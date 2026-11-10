"""Background work dispatch: run a function on a thread pool and report back by callbacks.

JobContext carries a cancellation flag that long-running work polls with checkpoint(),
and JobManager owns the thread pool and the map of in-flight jobs so the window close
can cancel everything instead of waiting.
"""
from concurrent.futures import ThreadPoolExecutor
import threading, uuid
from core.exceptions import CancellationError

class JobContext:
    def __init__(self,job_id): self.job_id=job_id; self._cancel=threading.Event()
    def cancel(self): self._cancel.set()
    @property
    def cancelled(self): return self._cancel.is_set()
    def checkpoint(self):
        # Raise if someone asked for a cancel while this job was mid-work. A run
        # that is cancelled mid-organize surfaces this at the next checkpoint and
        # unwinds cleanly instead of finishing the remaining games.
        if self.cancelled: raise CancellationError(f"Job {self.job_id} cancelled")

class JobManager:
    def __init__(self,max_workers=4): self.executor=ThreadPoolExecutor(max_workers=max_workers,thread_name_prefix="organizer"); self.jobs={}; self._lock=threading.Lock()
    def submit(self,fn,done=None,error=None):
        job_id=uuid.uuid4().hex[:10].upper(); ctx=JobContext(job_id)
        with self._lock: self.jobs[job_id]=ctx
        future=self.executor.submit(fn,ctx)
        def finished(f):
            with self._lock: self.jobs.pop(job_id,None)
            try:
                value=f.result()
                if done: done(job_id,value)
            except Exception as exc:
                if error: error(job_id,exc)
        future.add_done_callback(finished); return job_id,ctx,future
    def cancel_all(self):
        with self._lock:
            for ctx in self.jobs.values(): ctx.cancel()
    def shutdown(self,wait=True):
        # wait=False is for the window-close path. Waiting here runs on the Tk thread, so a running job freezes
        # the window until it finishes; with the tool watcher in place a cancel unwinds in about a second, so
        # the caller's choice is whether to block the UI for that second or close immediately.
        self.cancel_all(); self.executor.shutdown(wait=wait,cancel_futures=True)


