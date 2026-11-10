import unittest, time
from app.jobs import JobManager
from core.exceptions import CancellationError
class TestLifecycle(unittest.TestCase):
 def test_cancel_checkpoint(self):
  jm=JobManager(1)
  def work(ctx): time.sleep(.02); ctx.checkpoint(); return 1
  jid,ctx,f=jm.submit(work); ctx.cancel()
  with self.assertRaises(CancellationError): f.result(timeout=2)
  jm.shutdown()
 def test_submitted_jobs_receive_unique_ids(self):
  jm=JobManager(2)
  try:
   first,_,future_one=jm.submit(lambda ctx: 1); second,_,future_two=jm.submit(lambda ctx: 2)
   self.assertNotEqual(first,second); self.assertEqual(future_one.result(timeout=2),1); self.assertEqual(future_two.result(timeout=2),2)
  finally: jm.shutdown()

class TestStartupSweepIsCancelledOnShutdown(unittest.TestCase):
    """Closing the app inside the first second must not leave a library walk running afterwards.

    Startup defers `sweep_stale_build_dirs` by 1200ms so a large library folder never delays the window
    appearing. shutdown() cancelled the drain loop and the window's ticker, but not that one-shot timer, and
    the callback had no closed-check of its own - so a fast quit left Tk firing a sweep against a destroyed
    root ("invalid command name ..._sweep_stale_build_dirs" on stderr) and walked the whole library folder
    during shutdown, which is precisely the walk the deferral existed to keep off the startup path.

    These call the callback directly rather than waiting out the 1200ms: what is under test is the decision
    the callback makes once the app is closed, and a real timer would only make that harder to see.
    """

    def setUp(self):
        from tests.tk_support import require_tk,close_root,sandbox_app
        require_tk(self)
        import tkinter as tk
        self.tk=tk
        self.root=tk.Tk()
        self.addCleanup(close_root,self.root)
        self.app=sandbox_app(self,self.root)

    def test_the_startup_sweep_does_nothing_once_the_app_has_closed(self):
        walked=[]
        self.app.services.organizer.sweep_stale_build_dirs=lambda library_root: (walked.append(library_root),(0,0))[1]
        self.app.shutdown()
        # The timer firing after the window went away, which is what Tk does with a callback nobody cancelled.
        self.app._sweep_stale_build_dirs()
        self.assertEqual(walked,[],
                         'the startup sweep still walked the library folder after the app had closed')

    def test_shutdown_cancels_the_pending_startup_sweep_timer(self):
        # The timer is registered at construction, so it has to be there before shutdown has a chance to
        # cancel it - otherwise a test asserting only the "None afterwards" half passes on an app that
        # never scheduled a sweep at all.
        self.assertIsNotNone(self.app._sweep_handle,
                             'no startup sweep timer was registered, so there is nothing for this to cancel')
        self.app.shutdown()
        self.assertIsNone(self.app._sweep_handle,'shutdown left the startup sweep timer armed')

    def test_the_sweep_still_runs_on_an_app_that_is_open(self):
        # The guard must not turn the sweep off: this is the only moment clearing abandoned staging folders
        # is unambiguously safe, so a closed-check that also caught a live app would silently disable it.
        walked=[]
        self.app.services.organizer.sweep_stale_build_dirs=lambda library_root: (walked.append(library_root),(2,4096))[1]
        self.app._sweep_stale_build_dirs()
        self.assertEqual(len(walked),1,'the startup sweep stopped running while the app was open')
