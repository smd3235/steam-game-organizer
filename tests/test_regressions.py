# Fixed 2026-11-10: indentation across the file was broken (docstrings, if/with/for/try bodies, nested classes,
# module-level helpers all at wrong indent), so the module could not be imported or collected by unittest. Every
# body is now indented to its enclosing block so ast.parse() succeeds and the suite loads. ruff F841/F821 findings
# are pre-existing and excluded in ruff.toml per AGENTS.md.
import json, os, shutil, subprocess, zipfile
import tempfile
import threading,time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Installs a tkinter stub only when this machine has no real tkinter, so the UI modules can still be
# imported headlessly without shadowing the genuine toolkit (which silently skipped the geometry tests).

from core.config import AppConfig
from ui.main_window import MainWindow
from utils.filename_utils import identity_key

class TestKnownRegressionCases(unittest.TestCase):
  def test_known_identities(self):
        expected={"Alpha Forge v 0 8.zip":"alphaforge","Gamma Quest v 1 0.zip":"gammaquest","Delta Realm Incremental.zip":"deltarealm","Epsilon Online.zip":"epsilononline"}
        for name,key in expected.items(): self.assertEqual(identity_key(name),key,name)

 # The titles here are the real folders from one library, and every one of them failed to find its Steam name.
 # The cause was the tag stripper, not Steam: it only fired on whitespace-delimited tags, so the hyphenated
 # and dotted spellings these folders actually use survived into the search query, which then asked the store
 # for "Mars Attracts-Steam" and never for "Mars Attracts". The stripper is fixed and covered in
 # tests/test_filename_utils.py; this pins the outcome, so a change to the tag rules that brings any of these
 # back fails here by name.
  def test_tagged_library_folders_still_find_their_real_game(self):
      expected={"Brave.New.Wonders-SteamRIP.com":"Brave New Wonders",
            "Mars Attracts-Steam RIP com":"Mars Attracts",
            "Nivalis Nights-Steam RIP com":"Nivalis Nights",
            "Sintopia-Steam RIP com":"Sintopia"}
      from utils.filename_utils import normalize_name
      for tagged,clean in expected.items():
        self.assertEqual(normalize_name(tagged),clean,tagged)
        self.assertEqual(identity_key(tagged),identity_key(clean),tagged)

 # Both the fake home and the project root hang off one temporary tree, which is the point. They used to be
 # Path('/tmp/...'), and on Windows a leading slash is not absolute - it resolves against whatever drive happens
 # to be current. So the mkdir created C:\tmp\portable-home\Downloads\Games and AppConfig rooted its config,
 # cache and log directories at C:\tmp\project-root: two directories outside this repository, on the one platform
 # whose own guard (tests/test_platform.py) forbids POSIX paths, created by the test asserting nothing is
 # hard-coded. C:\tmp is not a harmless accident either - ArtworkService deletes from whatever cache directory it
 # is handed, and a sibling test handed it C:\tmp\artwork-cache.
  def test_default_library_root_is_portable(self):
      root=Path(_tmp_dir(self)); home=root/'portable-home'
      with patch('pathlib.Path.home', return_value=home):
        expected = home/'Downloads'/'Games'
        expected.mkdir(parents=True, exist_ok=True)
        config = AppConfig(root/'project-root')
        self.assertEqual(config.library_root, expected)

  def test_scan_done_keeps_scan_visible_until_verification_finishes(self):
      window = SimpleNamespace()
      window.closing = False
      window.views = {'scan': Mock(), 'review': Mock()}
      window.views['scan'].art_var = SimpleNamespace(get=lambda: True)
      window.show = Mock()
      window.status = Mock()
      result = SimpleNamespace(archives=[object()])

      MainWindow.scan_done(window, result)

      window.views['scan'].set_result.assert_called_once_with(result)
      window.views['review'].load.assert_called_once_with(result.archives, download_artwork=True)
      window.status.configure.assert_called_once()
      window.show.assert_called_once_with('scan')

  def test_scan_new_artwork_done_routes_to_review_without_calling_end(self):
      """Reproduced before the fix: _scan_new_artwork_done called _end and stopped on Scan, so the
          newly-discovered archives were never loaded into Review and the user could not accept them."""
      window = SimpleNamespace()
      window.closing = False
      window.views = {'scan': Mock(), 'review': Mock()}
      window.show = Mock()
      window.status = Mock()
      archives = [object(), object()]

      MainWindow._scan_new_artwork_done(window, archives)

      window.views['scan'].finish_artwork_scan.assert_called_once_with(archives)
      window.views['review'].load.assert_called_once_with(archives, download_artwork=True)
      window.status.configure.assert_called_once()
      window.show.assert_called_once_with('scan')
   # Must NOT have called _end: verification_done owns the run termination.
      self.assertFalse(hasattr(window, '_end') and window._end.called,
                    '_scan_new_artwork_done called _end, which would leave verification without a run guard')

class TestScanButtonComesBackAfterAScan(unittest.TestCase):
  r"""The app's headline button went dead after the first scan, for the rest of the session.

 `begin_scan` and `progress_update` both set `scan_btn` to `disabled`, so it cannot be pressed twice while a
 run is in progress. Nothing ever set it back. `MainWindow._end` - the one place that ends a run and already
 turns the cancel button off - never touched it.

 So the button the app opens with, and the one the user presses to pick up games they have just downloaded,
 stopped working the first time they used it. Restarting the app was the only way back, which makes "did it
 find the game I just downloaded" answerable only by closing the program. `MainWindow.scan`'s
 `if self.busy: return` guard reads like a second scan is supported and simply is not reachable.

Driven through the real MainWindow rather than a bare ScanView, because the omission is in MainWindow: the
      buttons are correct during a run and only ever brought back at the end, and a test that stops at
      `set_result` never reaches the code that owns the fix.

 Deliberately not asserting any of this by pressing the button. Its command was bound to MainWindow.scan when
 the button was created, so `invoke()` starts a real scan of the configured library root - and this machine's
 settings.json points at D:\Game Installers\Steam Games. While the button was disabled that call was a
 harmless no-op, which is how an earlier version of this test passed without ever pressing it.
  """

  def setUp(self):
      from tests.tk_support import require_tk,close_root,sandbox_app
      from tests.test_ui_geometry import _measured_window
      require_tk(self)
      import tkinter as tk
      self.root=tk.Tk(); self.addCleanup(close_root,self.root)
      self.app=sandbox_app(self,self.root); _measured_window(self.root)
      self.window=self.app.window
      self.scan=self.window.views['scan']
      self.window.show('scan'); self.root.update()

  def _run_a_whole_scan(self):
      """Discovery, then the background verification that follows it, then the run ends."""
      self.window.scan_done(type('R',(),{'archives':[],'errors':[]})())
      self.window.verification_done([])

  def test_the_button_starts_enabled(self):
      self.assertNotEqual(str(self.scan.scan_btn['state']),'disabled',
                      'the scan button is dead on a freshly opened window')

  def test_a_finished_scan_leaves_the_button_usable(self):
      self.window.views['scan'].begin_scan(); self.window._start('Scanning Games…')
      self.assertEqual(str(self.scan.scan_btn['state']),'disabled','the button was live during a running scan')
      self._run_a_whole_scan()
      self.assertFalse(self.window.busy,'the window still believes a run is in progress')
      self.assertFalse(self.scan.scanning,'the view still believes a scan is running')
      self.assertNotEqual(str(self.scan.scan_btn['state']),'disabled',
                      'the scan button is still disabled after the run finished, so the library cannot be '
                      'scanned again without restarting the app')

  def test_the_cancel_button_is_turned_off_when_the_run_ends(self):
      self.window.views['scan'].begin_scan(); self.window._start('Scanning Games…')
      self.assertEqual(str(self.scan.cancel_btn['state']),'normal','cancel was not live during a run')
      self._run_a_whole_scan()
      self.assertEqual(str(self.scan.cancel_btn['state']),'disabled',
                     'the cancel button is still live after the run finished')

class TestOpenFolderIsNotLinuxOnly(unittest.TestCase):
  """Both "open this folder" buttons were wired to xdg-open and nothing else.

 `MainWindow.open_library` and `ArtworkView._open_folder` both did `shutil.which('xdg-open')` and, finding
 nothing, did nothing at all - no message, no error, nothing in the log. On the platform this app is primarily
 run on that is every press: Done's "Open Library Folder" and every Artwork-screen "OPEN GAME FOLDER" were
 dead buttons. Verified on this host: `xdg-open` is not on PATH, `explorer` is, and `os.startfile` exists.

 The two call sites had drifted apart from each other as well, so the behaviour now lives in one helper that
 answers the question the buttons actually care about: did anything get launched.
 """

  def setUp(self):
      from tests.tk_support import require_tk,close_root,sandbox_app
      require_tk(self)
      self.close_root=close_root
      from tempfile import TemporaryDirectory
      # The TemporaryDirectory object has to be kept: only its name was wanted here, and discarding the object
      # deletes the folder its finalizer owns - which is the bug this file already records once, in test_services.
      self._folder= TemporaryDirectory(); self.addCleanup(self._folder.cleanup)
      self.folder=Path(self._folder.name)

  def test_opening_a_folder_launches_something_on_this_platform(self):
      import os
      from utils.desktop import open_folder
      if os.name!='nt':
          self.fail('this app is Windows-only now, so open_folder must refuse elsewhere rather than launch nothing')
      launched=[]
      with patch('utils.desktop.os.startfile',side_effect=lambda p:launched.append(p)):
          self.assertTrue(open_folder(self.folder))
          self.assertEqual(launched,[str(self.folder)],
                   'on Windows the folder was not handed to the shell, so the button did nothing')

  def test_it_reports_failure_instead_of_silently_doing_nothing(self):
      # The old code returned None whether or not anything happened, so a caller could not tell a launched file
      # manager from a dead button. Anything that cannot be launched is a False, never an exception at the caller.
      #
      # Both routes have to be closed off on Windows: os.startfile failing falls back to explorer, and this host
      # does have explorer, so blocking startfile alone would prove nothing.
      from utils.desktop import open_folder
      import os
      if os.name!='nt':
          self.fail('this app is Windows-only now, so open_folder must refuse elsewhere rather than launch nothing')
      with patch('utils.desktop.os.startfile',side_effect=OSError('no shell here')), \
       patch('utils.desktop.shutil.which',return_value=None):
          self.assertFalse(open_folder(self.folder),'a failed launch was reported as a success')

  def test_a_folder_that_is_not_there_is_not_launched(self):
      from utils.desktop import open_folder
      self.assertFalse(open_folder(self.folder/'no-such-folder'),
                   'a missing folder was handed to the shell instead of being refused')

  def test_the_library_button_goes_through_the_helper(self):
      from tests.test_ui_geometry import _measured_window
      from tests.tk_support import sandbox_app
      import tkinter as tk
      root=tk.Tk(); self.addCleanup(self.close_root,root)
      app=sandbox_app(self,root); _measured_window(root)
      app.config.library_root=self.folder
      with patch('utils.desktop.open_folder',return_value=True) as helper:
          app.window.open_library()
          helper.assert_called_once_with(self.folder)

  def test_the_artwork_screen_goes_through_the_helper(self):
      import tkinter as tk
      from ui.artwork_view import ArtworkView
      root=tk.Tk(); self.addCleanup(self.close_root,root)
      view=ArtworkView(tk.Frame(root),lambda:None)
      with patch('utils.desktop.open_folder',return_value=True) as helper:
          view._open_folder(self.folder)
          helper.assert_called_once_with(self.folder)

class TestTheSetupButtonIsInTheAppToolbar(unittest.TestCase):
  """A Setup button in the app's own toolbar.

      The catalog's Set up on this PC button goes through the protocol handler, which runs with no
      main window - so it cannot reach the app. A reader who already has the app running and needs to
      re-point it, because the app folder was moved, had no way to open the wizard at all: the only
      routes were --setup on the command line and the catalog button, both of which assume the app is
      not already open. The button lives in the footer bar beside System Health and Diagnostics.
    """
  def setUp(self):
        from tests.tk_support import require_tk, close_root, sandbox_app
        require_tk(self)
        self.close_root = close_root
        import tkinter as tk
        root = tk.Tk(); self.addCleanup(self.close_root, root)
        self.app = sandbox_app(self, root)

  def test_the_button_is_present_and_open_setup_is_bound_to_it(self):
        self.assertTrue(hasattr(self.app.window, 'setup_btn'),
                        'the app toolbar has no Setup button')
        self.assertTrue(hasattr(self.app.window, 'open_setup'),
                        'MainWindow has no open_setup handler for the button')

  def test_opening_setup_opens_the_wizard(self):
        from unittest.mock import patch
        with patch('ui.setup_window.SetupWindow') as wizard:
            self.app.window.open_setup()
        wizard.assert_called_once()
        args, kwargs = wizard.call_args
        self.assertIs(args[0], self.app.root)
        self.assertIs(args[1], self.app.config)
        self.assertIs(args[2], self.app.logger)


class TestNewOnlyWithNothingNewDoesNotBlockOnTheVerifyScreen(unittest.TestCase):
  """A New Only scan that finds nothing new must still be finishable.

      Under New Only a scan that has nothing new hands an empty list to the review screen, and the run
      is genuinely done: the audit and catalog phases already ran and wrote their pages. The CONTINUE
      button was gated on the list being non-empty, so it was disabled; Approve All Verified was itself
      disabled on an empty list, so the only button available could not be pressed and the run appeared
      to hang on the verify screen with no way to continue.
    """
  def setUp(self):
        from tests.tk_support import require_tk, close_root, sandbox_app
        require_tk(self)
        self.close_root = close_root
        import tkinter as tk
        root = tk.Tk(); self.addCleanup(self.close_root, root)
        self.app = sandbox_app(self, root)
        self.view = self.app.window.views['review']
        self.app.window.show('review')
        self.root = self.app.root
        self.root.update()

  def test_the_continue_button_is_enabled_on_an_empty_list(self):
        self.view.load([])
        self.root.update()
        self.assertEqual(str(self.view.continue_button.cget('state')), 'normal',
                         'a scan with nothing new left no way to finish the run')

  def test_the_continue_button_is_disabled_while_games_are_unresolved(self):
        from core.models import GameArchive
        archive = GameArchive(self.app.config.library_root / 'Game.zip', 'Game', 'game',
                              'game', '.zip', (0,))
        self.view.load([archive])
        self.root.update()
        self.assertEqual(str(self.view.continue_button.cget('state')), 'disabled')

  def test_the_empty_list_says_the_run_is_done(self):
        self.view.load([])
        self.root.update()
        self.assertIn('CONTINUE TO ORGANIZATION', self.view.continue_button.cget('text'))
        self.assertIn('already ran', self.view.subtitle.cget('text'))


class TestApiKeyCheckDoesNotLeakTheSocket(unittest.TestCase):
  """The SteamGridDB connection test read the status code and left the response body undrained.

 `with urlopen(...) as r: code=getattr(r,'status',200)` never touched `r.read()`. Closing the response
 without consuming the body does not shut the SSL socket down cleanly - the connection is left for the
 garbage collector, and every key test printed `ResourceWarning: unclosed <ssl.SSLSocket>` to stderr. It
 was the only one of the five HTTP call sites in the app that skipped the read; the rest all drain.

 This is a leak rather than a crash, which is exactly why it needs a test: nothing fails on its own, and
 an undrained socket per key test is invisible until someone watches the file descriptors.
 """

  def setUp(self):
      from tests.tk_support import require_tk,close_root,sandbox_app
      require_tk(self)
      import tkinter as tk
      from ui.scan_view import ScanView
      self.root=tk.Tk(); self.addCleanup(close_root,self.root)
      self.view=ScanView(tk.Frame(self.root),lambda:None,lambda:None,lambda:None)

  def _run_test_api(self,response,run_mainloop=True):
      """Drive test_api() and wait for the worker thread it spawns.

      Two things this has to get right, both of which hid a failure when it was left to chance:

      test_api posts its result with after(0) from the worker thread, and tkinter refuses a cross-thread after()
      that has no mainloop to hand it to - so with run_mainloop the window runs a short bounded mainloop, and
      without it the update is expected to fail, which is what the RuntimeError test is about.

      And the worker has to be *joined*. Sleeping and hoping left the assertion running before the thread had
      reached its update, which reads as "no exception escaped" every time - a test that cannot fail.
      """
      captured={}
      tracked=threading.Thread

      class _Tracked(tracked):
          def __init__(self,*args,**kwargs):
              super().__init__(*args,**kwargs); captured['worker']=self

      with patch('ui.scan_view.urlopen',return_value=response), patch.object(threading,'Thread',_Tracked):
          self.view.api_var.set('a-key')
          self.view.test_api()
          if run_mainloop:
              self.root.after(400,self.root.quit)
              self.root.mainloop()
          worker=captured.get('worker')
          if worker is not None: worker.join(timeout=5)
          self.root.update()

  def test_the_api_test_drains_the_response_before_closing_it(self):
      calls=[]

      class _Response:
          status=200
          def read(self,*args): calls.append('read'); return b'{"results":[]}'
          def close(self): calls.append('close')
          def __enter__(self): return self
          def __exit__(self,*args): self.close()

      self._run_test_api(_Response())
      self.assertIn('read',calls,'the API test never read the response body, so the socket is never released')
      if 'close' in calls:
          self.assertLess(calls.index('read'),calls.index('close'),
                   'the API test closed the response before reading it, so the socket is never released')

  def test_a_successful_api_test_still_reports_success(self):
      """The drain must not cost the check its answer.

      Reading the body is the fix; losing the status code that makes the button say "connection successful"
      would be a regression traded for a clean socket, which is not a trade worth making.
      """

      class _Response:
          status=200
          def read(self,*args): return b'{"results":[]}'
          def close(self): pass
          def __enter__(self): return self
          def __exit__(self,*args): self.close()

      self._run_test_api(_Response())
      self.assertIn('successful',self.view.api_status.cget('text'))

  def test_a_cross_thread_update_that_cannot_land_does_not_kill_the_worker_with_a_traceback(self):
      """The worker posts its result with after(0) from a non-Tk thread.

      When there is no mainloop to hand that to, tkinter raises RuntimeError("main thread is not in main loop")
      rather than a TclError - and the handler only caught TclError, so the exception escaped a daemon thread
      nobody joins. The visible result is a traceback on stderr with no indication of what it was, from a code
      path whose whole job is to report a status.

      threading.excepthook is what decides whether that is silent or noisy, so that is what this watches.
      """
      class _Response:
          status=200
          def read(self,*args): return b'{}'
          def close(self): pass
          def __enter__(self): return self
          def __exit__(self,*args): self.close()

      escaped=[]; previous=threading.excepthook
      threading.excepthook=lambda args: escaped.append(args.exc_type)
      try:
          self._run_test_api(_Response(),run_mainloop=False)
      finally:
          threading.excepthook=previous
      self.assertEqual(escaped,[],f'the API worker died with {escaped} on a cross-thread update it could not deliver')


class TestSettingsSurvivesASyncClientLock(unittest.TestCase):
  """Config.save() must not let a file lock stop the app working.

 Found in the real log rather than reasoned about: pressing Scan raised PermissionError from os.replace and
      the scan never started. The project lived in a OneDrive folder, and OneDrive opens the file it is syncing,
 so the target is briefly un-replaceable - WinError 5, "Access is denied". os.replace is atomic and that is
 exactly why it is used, but atomicity buys nothing if the one call can fail on a locked destination and the
 exception is allowed to reach the button handler that called it.

 Retrying is the fix, and the bound matters as much as the retry: a genuinely read-only settings directory
 must still report the failure rather than spin.
 """
  def _config(self,tmp):
      (tmp/"Incoming").mkdir(parents=True,exist_ok=True)
      return AppConfig(project_root=tmp,library_root=tmp/"Incoming")

  def _settings(self,tmp):
      """Where AppConfig puts settings.json: a config/ directory under the project root, not the root itself."""
      return tmp/"config"/"settings.json"

  def test_a_transient_lock_does_not_lose_the_settings(self):
      with tempfile.TemporaryDirectory() as raw:
          tmp=Path(raw); config=self._config(tmp); config.settings["steamgriddb_api_key"]="abc123"
          real=os.replace; calls=[]
          def locked(source,target):
              calls.append(target)
              if len(calls)<=2: raise PermissionError(5,"Access is denied",str(target))
              return real(source,target)
          with patch("core.config.os.replace",side_effect=locked):
              config.save()
              self.assertEqual(3,len(calls),f'save() gave up after {len(calls)} attempt(s) instead of retrying a locked file')
              self.assertEqual("abc123",json.loads(self._settings(tmp).read_text(encoding="utf-8"))["steamgriddb_api_key"],
                            'the settings did not reach the file once the lock cleared')

  def test_a_permanent_failure_is_still_reported(self):
      """The opposite requirement, and the one a retry can quietly break.

      A settings directory that cannot be written has to say so. Retrying forever would turn a clear error into a
      hung button, and swallowing it would mean the app runs on settings it never saved.
      """
      with tempfile.TemporaryDirectory() as raw:
          tmp=Path(raw); config=self._config(tmp)
          def always_locked(source,target): raise PermissionError(5,"Access is denied",str(target))
          with patch("core.config.os.replace",side_effect=always_locked):
              with self.assertRaises(PermissionError):
                  config.save()
              self.assertFalse(self._settings(tmp).exists(),'a failed save left a settings file behind')

  def test_the_temporary_file_is_removed_after_a_failed_save(self):
      """A leftover settings.XXXX.tmp is not harmless.

      ensure_directories() and the next mkstemp all work in this directory, so a temp file left by every failed
      save is how a config directory slowly fills with the debris of previous attempts.
      """
      with tempfile.TemporaryDirectory() as raw:
          tmp=Path(raw); config=self._config(tmp)
          def always_locked(source,target): raise PermissionError(5,"Access is denied",str(target))
          with patch("core.config.os.replace",side_effect=always_locked):
              with self.assertRaises(PermissionError): config.save()
          leftovers=list((tmp/"config").glob("settings.*.tmp"))
          self.assertEqual([],leftovers,f'{len(leftovers)} temporary settings file(s) left behind: {[p.name for p in leftovers]}')


class TestPlatformPathsAreNotHardCoded(unittest.TestCase):
  """A path or command from another platform survives long after the platform is dropped.

 Both of these were found by looking at the running app rather than by reading a test: the message was written
 when Steam Deck was the primary platform and told a Windows user to look in /home/deck, and the archive
 verification tool - the thing you run to check a library is intact - exited immediately on a normal PC
 because it looked for 7z only on PATH and 7-Zip installs to Program Files without adding itself there.

 Neither shows up in a test that supplies its own paths, which is why a suite can be entirely green while the
 app is telling the user to go somewhere that does not exist on their machine.
 """
  def _code_strings(self,relative):
      """Every string literal in a module's code, excluding its comments.

      Read from the parsed AST rather than the file text: both of these words appear in the change logs that
      explain why they were removed, and a grep over the raw source reports a Linux path that is only being
      described. That is the same mistake as asserting on a file's text to prove a call was removed.
      """
      import ast
      path=Path(relative)
      if not path.is_file(): path=Path(__file__).resolve().parents[1]/path
      tree=ast.parse(path.read_text(encoding='utf-8'))
      return path,[node.value for node in ast.walk(tree)
               if isinstance(node,ast.Constant) and isinstance(node.value,str)]

  def _code_calls(self,relative):
      """Every call expression in a module, as source. Comments cannot appear here."""
      import ast
      path=Path(relative)
      if not path.is_file(): path=Path(__file__).resolve().parents[1]/path
      tree=ast.parse(path.read_text(encoding='utf-8'))
      return path,[ast.unparse(node) for node in ast.walk(tree) if isinstance(node,ast.Call)]

  def test_the_library_root_dialog_does_not_name_a_path_from_another_platform(self):
      from core.config import AppConfig
      source,literals=self._code_strings(Path('ui')/'main_window.py')
      for dead in ('/home/deck','/home/jail','xdg-open'):
          hits=[s for s in literals if dead in s]
          self.assertEqual([],hits,f'{source.name} still builds a message or command from {dead!r}: {hits}')
      self.assertTrue(AppConfig.default_library_root().is_absolute())

  def test_the_archive_verifier_finds_seven_zip_the_way_the_app_does(self):
      """It must reach the same verdict about this machine as the organizer does.

      Asserted against the real lookup rather than a mock: this is the question the tool exists to answer, and a
      patched shutil.which would only prove the tool calls the function it always called.
      """
      from services.extract_service import ExtractService
      source,literals=self._code_strings(Path('tools')/'verify_archives.py')
      self.assertEqual([],[s for s in literals if '/home/deck' in s],
                   f'{source.name} still defaults to the Steam Deck library path')
      source,calls=self._code_calls(Path('tools')/'verify_archives.py')
      self.assertEqual([],[c for c in calls if 'shutil.which' in c],
                   f'{source.name} still resolves 7z with shutil.which, which cannot see a Windows install')
      self.assertTrue([c for c in calls if 'find_tool' in c],
                  f'{source.name} no longer asks ExtractService where the archive tool is')
      found,reason=ExtractService.find_tool()
      self.assertIsNotNone(found,f'the verifier and the app would both report no archive tool here ({reason})')


def _tmp_dir(case):
    """A scratch directory that is removed when the test finishes, however it finishes.

    A method on each class was how this started, and the second class could not see the first one's - so the
    helper lives at module level and both use it.
    """
    holder=tempfile.mkdtemp(); case.addCleanup(shutil.rmtree,holder,ignore_errors=True); return holder


class TestTheCatalogLauncherIsUsable(unittest.TestCase):
  """A launcher beside the catalog must be a file this machine can actually open.

 Found in the real library rather than reasoned about. `Open Game Library.desktop` was sitting in the library
 root on this PC, containing:

      Exec=google-chrome --new-tab file:///D:/Game%20Installers/...

 and it was dead twice over. Windows has no association for `.desktop`, so double-clicking it opened nothing;
 and `google-chrome` does not exist here (`shutil.which` returns None), because `chrome_command()` returned a
 hardcoded string whenever no browser was found rather than admitting it had none.

 It was written at all because `html_handler()` only ever read the Linux XDG mimeapps.list, which cannot exist
 on this platform - so it always answered "nothing here opens HTML", on a machine where `HKCR\\.html` says
 `htmlfile` and double-clicking the catalog works perfectly well. A launcher is only needed when the machine
 genuinely has no handler, and this one did not know how to tell.

 The suite passed throughout: the one test covering this passed an explicit `/usr/bin/chrome` command and then
 only asserted that the file had been created, which is the one thing that was never the problem.
 """
  def test_a_launcher_file_carries_a_url_and_no_command_at_all(self):
      """The command is not merely unused now - it never could have been used.

      A .url with a `URL=` line and nothing else is resolved by the shell association, so the catalog's launcher
      never had a way to honour a browser command even when it was handed one.       The machinery that searched for
      one is gone; this asserts the file cannot reintroduce the idea.
      """
      from pathlib import Path as _Path
      from core.logger import AppLogger
      from services.catalog_service import CatalogService
      root=_Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree,root,ignore_errors=True)
      catalog=CatalogService(AppLogger(root/'x.log'))
      catalog._write_chrome_launcher(root,root/'Game Library.html')
      text=(root/'Open Game Library.url').read_text()
      self.assertNotIn('Exec=',text,'the launcher names a program again, which the format cannot act on')

  def test_no_launcher_is_written_when_the_machine_already_opens_html(self):
      from pathlib import Path as _Path
      from core.logger import AppLogger
      from services.organizer_service import OrganizerService
      service=OrganizerService(AppLogger(_Path(_tmp_dir(self))/'x.log'))
      # The real registry, not a mock: the whole defect was that this question was answered from a file that does
      # not exist here rather than from the platform that does.
      handler=service.html_handler()
      self.assertTrue(handler,'html_handler() reports nothing on a machine whose HKCR\\.html is set; '
                            'it is still only reading the Linux mimeapps.list')
      self.assertFalse(service.needs_catalog_launcher(),
                   'a launcher was deemed necessary on a machine that already opens .html with a browser')

  def test_a_launcher_is_never_a_linux_desktop_file_on_windows(self):
      """The fallback still has to be a format Windows understands.

      Reaching this branch needs a machine with no HTML association at all, which is rare - so it is reached by
      patching rather than by waiting for one, and the format is asserted rather than the presence.
      """
      import os
      if os.name!='nt': self.fail('this app is Windows-only now')
      from pathlib import Path as _Path
      from core.logger import AppLogger
      from services.catalog_service import CatalogService
      root=_Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree,root,ignore_errors=True)
      catalog=CatalogService(AppLogger(root/'x.log'))
      catalog._write_chrome_launcher(root,root/'Game Library.html')
      written=sorted(p.name for p in root.iterdir())
      self.assertEqual([],[n for n in written if n.endswith('.desktop')],
                   f'wrote a Linux desktop entry on Windows: {written}')
      self.assertTrue(written,f'no launcher at all was written for a machine with no HTML handler: {written}')



class TestSyncthingTempFilesAreCleanedUp(unittest.TestCase):
  """Syncthing writes its in-flight transfers under two different names, and only one was recognised.

 Found in the real library, not in a fixture: three files sat in the library root named

      ~syncthing~Game Library (Steam Deck) - 2026-10-02 115241.html.tmp   (399 KB)
      ~syncthing~Game Library (Windows) - 2026-10-02 115241.html.tmp     (396 KB)
      ~syncthing~Open Game Library (Steam Deck).desktop.tmp             (335 bytes)

 `SYNC_FILE_PATTERNS` listed `*.syncthing.*.tmp` - the tilde-free infix form - so cleanup walked straight past
 all three. They had been there two days. The irony is that the stranded files are named after the old
 Steam Deck catalogs, so the very artifacts this app was supposed to be deleting are the ones it kept.

 Nothing had noticed because every test used the infix spelling, which is the one form the code handles.
 """
  def _service(self,root):
      from core.logger import AppLogger
      from services.library_service import LibraryService
      return LibraryService(AppLogger(Path(root)/'x.log'))

  def _debris(self,root,name):
      path=Path(root)/name; path.write_text('x'*4096)
      # Aged past any grace period, so only the pattern can decide whether it is removed.
      old=time.time()-30*24*3600
      os.utime(path,(old,old))
      return path

  def test_the_tilde_spelling_is_recognised(self):
      for name in ('~syncthing~Game Library (Steam Deck) - 2026-10-02 115241.html.tmp',
               '~syncthing~Open Game Library (Steam Deck).desktop.tmp',
               '~syncthing~game.7z.tmp'):
          with self.subTest(name=name):
              root=Path(_tmp_dir(self)); debris=self._debris(root,name)
              self._service(root).cleanup_leftovers(root,grace_seconds=0)
              self.assertFalse(debris.exists(),f'{name} was left behind; cleanup does not match this spelling')

  def test_the_infix_spelling_still_works(self):
      """Both spellings, because the fix must not have been to swap one for the other."""
      root=Path(_tmp_dir(self)); debris=self._debris(root,'game.7z.syncthing.abc.tmp')
      self._service(root).cleanup_leftovers(root,grace_seconds=0)
      self.assertFalse(debris.exists(),'the spelling that already worked stopped being cleaned up')

  def test_a_transfer_still_in_flight_is_left_alone(self):
      """The grace period is the reason any of this is safe, so it is asserted for the new pattern too.

      A '~syncthing~' file that is minutes old may be an in-flight transfer on the other machine, and deleting it
      would destroy the copy being written.
      """
      root=Path(_tmp_dir(self)); live=root/'~syncthing~game.7z.tmp'; live.write_text('x'*4096)
      self._service(root).cleanup_leftovers(root,grace_seconds=3600)
      self.assertTrue(live.exists(),'a transfer that is still in flight was deleted')

  def test_a_real_game_file_is_never_matched(self):
      """The pattern is a prefix, so it is worth proving it cannot reach a game archive."""
      root=Path(_tmp_dir(self)); keep=root/'~syncthing notes.txt'; keep.write_text('x')
      self._service(root).cleanup_leftovers(root,grace_seconds=0)
      self.assertTrue(keep.exists(),'a file merely starting with ~syncthing~ was deleted')

class TestCleanupDoesNotLeaveTheLibraryThroughAJunction(unittest.TestCase):
  """cleanup_leftovers() deleted a file that was never in the library.

      os.walk(followlinks=False) is documented not to follow symlinks, and the walk here relied on that. A Windows
      junction is not a symlink - Path.is_symlink() answers False for one, because the OS hands it back as an
      ordinary directory - so os.walk stepped straight through it. Everything reached that way is outside the
      folder the caller passed as the library root, and this is the one walk in the app that deletes what it finds.

      Confirmed live before the fix, in a temp directory:

      library/linked/  -> junction -> elsewhere/
      elsewhere/~syncthing~orphan.tmp   4096 bytes

      cleanup_leftovers() reported removed=1, and the file on the far side of the junction was gone. A file matched
      by name in a neighbouring folder, which a Syncthing setup makes routine, was destroyed by a routine scan.

      This is deliberately the opposite of the rule tests/test_services.py pins for scanning, where a junction to a
      sibling folder IS followed: reading a sibling folder through a link finds games the user meant to include, and
      refusing it would hide them. Deleting is not symmetric. The caller named one folder as the boundary, and a link
      is a way out of it, not a road inside.
  """
  def _link_directory(self,link,target):
   # Fails rather than skips: a skipped test here would report the library safe on the one platform where the
   # link is a junction rather than a symlink, which is the platform this defect needs.
      made=subprocess.run(['cmd','/c','mklink','/J',str(link),str(target)],capture_output=True,timeout=30)
      if made.returncode==0: return 'junction'
      try:
          link.symlink_to(target,target_is_directory=True); return 'symlink'
      except OSError as exc:
          self.fail(f'no way to make a directory link on this machine: {exc}')

  def _service(self,root):
      from core.logger import AppLogger
      from services.library_service import LibraryService
      return LibraryService(AppLogger(Path(root)/'x.log'))

  def test_a_matching_file_behind_a_junction_survives(self):
      root=Path(_tmp_dir(self))
      library=root/'Games'; library.mkdir()
      elsewhere=root/'Elsewhere'; elsewhere.mkdir()
      victim=elsewhere/'~syncthing~orphan.tmp'; victim.write_text('x'*4096)
      old=time.time()-30*24*3600; os.utime(victim,(old,old))
      kind=self._link_directory(library/'linked',elsewhere)
   # A file the walk would find and the pattern would match, reached only by walking through the link.
      inside=library/'stale.7z.syncthing.abc.tmp'; inside.write_text('x'*4096)
      os.utime(inside,(old,old))
      self.assertTrue(any(p.name==victim.name for p in library.rglob('*')),
                   f'the {kind} does not lead to the victim, so nothing would have been deleted')
      self._service(root).cleanup_leftovers(library,grace_seconds=0)
      self.assertTrue(victim.exists(),
                   f'cleanup deleted a {kind} and removed a file {victim} that was outside the library root')
      self.assertFalse(inside.exists(),'the leftover actually inside the library was left behind by the fix')

  def test_a_junction_named_like_our_own_temp_folder_is_declined(self):
      """A link matching this app's own temp-folder names is declined, and the decline is visible.

      The content behind such a link was never actually at risk: shutil.rmtree() raises OSError on a Windows
      junction rather than descending it, so the folder survived by accident and cleanup logged
      LEFTOVER_REMOVE_FAILED while reporting a successful sweep. That is a warning about a folder the app did
      not create, on a scan the user reads as a routine clean-up - and it is the only warning in the pass that
      is not about something real.

      So what the fix changes is not the outcome but the intent: the link is recognised and counted, instead of
      attempted, failed, and reported as an error. Asserted on both halves, because either alone would pass
      against the old code - the content check alone passes there too.
      """
      root=Path(_tmp_dir(self))
      library=root/'Games'; library.mkdir()
      precious=root/'Do Not Touch'; precious.mkdir(); (precious/'save.dat').write_text('x'*4096)
      self._link_directory(library/'.organizer-repack-stale',precious)
      summary=self._service(root).cleanup_leftovers(library,grace_seconds=0)
      self.assertTrue((precious/'save.dat').exists(),'cleanup reached through a link named as one of its own temp folders')
      self.assertEqual(summary.get('skipped_links'),1,f'the link was not counted as declined: {summary}')
      logged=(root/'x.log').read_text(encoding='utf-8',errors='replace')
      self.assertNotIn('LEFTOVER_REMOVE_FAILED',logged,
                    f'a link was attempted and then failed, instead of being declined up front: {logged[-400:]}')


  def test_the_summary_reports_what_it_declined_to_walk(self):
      """A skipped junction is invisible otherwise - removed=0 and bytes_freed=0 read identically to 'nothing to
      do', which is how a library full of links could report a clean sweep for ever."""
      root=Path(_tmp_dir(self))
      library=root/'Games'; library.mkdir()
      elsewhere=root/'Elsewhere'; elsewhere.mkdir()
      (elsewhere/'~syncthing~orphan.tmp').write_text('x'*4096)
      self._link_directory(library/'linked',elsewhere)
      summary=self._service(root).cleanup_leftovers(library,grace_seconds=0)
      self.assertEqual(summary.get('skipped_links'),1,f'the junction was not reported as declined: {summary}')

  def test_is_link_says_no_to_a_plain_folder(self):
      """The fix must not turn cleanup into a no-op: a real temp folder, matched by name and old enough, still
      goes. is_link() is on the path of every deletion, so a false positive here would silently disable cleanup."""
      root=Path(_tmp_dir(self))
      junk=root/'.organizer-unzip-gone'; junk.mkdir(); (junk/'part.bin').write_text('x'*4096)
      plain=root/'notes.txt'; plain.write_text('x')
      from utils.treewalk import is_link
      self.assertFalse(is_link(junk),'an ordinary folder was reported as a link')
      self.assertFalse(is_link(plain),'an ordinary file was reported as a link')
      self._service(root).cleanup_leftovers(root,grace_seconds=0)
      self.assertFalse(junk.exists(),'a genuine leftover inside the library stopped being cleaned up')

class TestEmptyCategoryFoldersAreReclaimed(unittest.TestCase):
  """A category folder with no game in it is removed.

      Re-categorising a game moves its archive out of the folder it was filed into, and that folder was
      kept carrying the Steam link, the metadata and the artwork the organizer wrote. Every scan walked it
      as a game folder with no archive and reported it as a scan problem, and the catalog page showed an empty
      category with a broken Extract button. The leftover sweep only ever matched temp artefacts and
      Syncthing files by name, so it never touched these, and the app had no pass for them at all.
    """
  def setUp(self):
        from core.logger import AppLogger
        from services.library_service import LibraryService
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.service = LibraryService(AppLogger(self.tmp / 'x.log'))

  def test_an_empty_category_is_removed(self):
        library = self.tmp / 'Games'; library.mkdir()
        action = library / 'Action'; action.mkdir()
        (action / '.game-info.json').write_text('{}', encoding='utf-8')
        (action / 'Open Steam Page.html').write_text('x')
        summary = self.service.cleanup_leftovers(library, grace_seconds=0)
        self.assertEqual(summary.get('empty_categories_removed'), 1,
                         f'the empty category was not removed: {summary}')
        self.assertFalse(action.exists(), 'the empty category folder was left behind')

  def test_a_category_holding_an_archive_is_not_removed(self):
        library = self.tmp / 'Games'; library.mkdir()
        action = library / 'Action'; action.mkdir()
        (action / 'Loop Miner.zip').write_bytes(b'PK\x03\x04' + b'0' * 512)
        summary = self.service.cleanup_leftovers(library, grace_seconds=0)
        self.assertEqual(summary.get('empty_categories_removed'), 0,
                         f'a category holding an archive was removed: {summary}')
        self.assertTrue(action.exists(), 'a category holding an archive was deleted')

  def test_the_reserved_folders_and_the_app_folder_are_not_removed(self):
        library = self.tmp / 'Games'; library.mkdir()
        (library / 'Archive').mkdir()
        (library / 'Processing').mkdir()
        app = library / 'Steam Game Organizer'; app.mkdir()
        (app / 'steam_game_organizer.py').write_text('# stub\n')
        summary = self.service.cleanup_leftovers(library, grace_seconds=0)
        self.assertEqual(summary.get('empty_categories_removed'), 0,
                         f'a reserved folder or the app folder was removed: {summary}')
        self.assertTrue((library / 'Archive').exists())
        self.assertTrue((library / 'Processing').exists())
        self.assertTrue(app.exists(), 'the app project folder was deleted')

  def test_a_category_holding_a_game_subfolder_is_not_removed(self):
        # A subfolder holding a real game - an archive, which is what makes it a game rather than a
        # leftover - keeps the category. The sweep prunes empty game folders, so the distinction is
        # the archive: a folder with one stays, a folder with only app artefacts goes.
        library = self.tmp / 'Games'; library.mkdir()
        action = library / 'Action'; action.mkdir()
        (action / 'Loop Miner - 2020-01-01').mkdir()
        (action / 'Loop Miner - 2020-01-01' / 'Loop Miner.zip').write_bytes(b'PK\x03\x04' + b'0' * 512)
        summary = self.service.cleanup_leftovers(library, grace_seconds=0)
        self.assertEqual(summary.get('empty_categories_removed'), 0,
                         f'a category holding a game was removed: {summary}')
        self.assertTrue(action.exists(), 'a category holding a game was deleted')


class TestReCategoriseLeftoversAreReclaimed(unittest.TestCase):
  """A game moved to another category leaves its old folder behind, and the sweep reclaims it.

      Re-categorising a game moves its archive out of the folder it was filed into. The folder stays
      carrying the Steam link, the metadata and the artwork the organizer wrote, and every scan walks it
      as a game folder with no archive and reports it as a scan problem. The category that held it is
      then left holding only those empty game folders, and the catalog page shows an empty category with
      a broken Extract button. The leftover sweep only ever matched temp artefacts and Syncthing files by
      name, so it never touched these, and the app had no pass for them at all.
    """
  def setUp(self):
        from core.logger import AppLogger
        from services.library_service import LibraryService
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.service = LibraryService(AppLogger(self.tmp / 'x.log'))

  def _game(self, category, name):
        game = self.tmp / 'Games' / category / name; game.mkdir(parents=True)
        (game / '.game-info.json').write_text('{}', encoding='utf-8')
        (game / 'Open Steam Page.html').write_text('x')
        (game / (name + '_grid.jpg')).write_bytes(b'\xff\xd8\xff\xd9')
        (game / (name + '_header_image.jpg')).write_bytes(b'\xff\xd8\xff\xd9')
        return game

  def test_a_category_holding_only_leftover_game_folders_is_removed(self):
        puzzle = self._game('Puzzle', 'TerraScape - 2024-07-17')
        self._game('Puzzle', 'Twisted Tower - 2026-08-18')
        summary = self.service.cleanup_leftovers(self.tmp / 'Games', grace_seconds=0)
        self.assertEqual(summary.get('empty_categories_removed'), 1,
                         f'the category was not reclaimed: {summary}')
        self.assertFalse((self.tmp / 'Games' / 'Puzzle').exists(),
                         'the category holding only leftover game folders was left behind')
        self.assertFalse(puzzle.exists(), 'the leftover game folder was left behind')

  def test_a_leftover_game_folder_holding_a_save_file_is_not_removed(self):
        game = self._game('Puzzle', 'TerraScape - 2024-07-17')
        (game / 'save.dat').write_text('x')
        summary = self.service.cleanup_leftovers(self.tmp / 'Games', grace_seconds=0)
        self.assertEqual(summary.get('empty_categories_removed'), 0,
                         f'a category holding a player file was reclaimed: {summary}')
        self.assertTrue(game.exists(), 'a game folder holding a save file was deleted')

  def test_a_leftover_game_folder_holding_a_screenshot_is_not_removed(self):
        game = self._game('Puzzle', 'TerraScape - 2024-07-17')
        (game / 'screenshot.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        summary = self.service.cleanup_leftovers(self.tmp / 'Games', grace_seconds=0)
        self.assertEqual(summary.get('empty_categories_removed'), 0,
                         f'a category holding a screenshot was reclaimed: {summary}')
        self.assertTrue(game.exists(), 'a game folder holding a screenshot was deleted')

  def test_a_leftover_game_folder_holding_an_archive_is_not_removed(self):
        game = self._game('Puzzle', 'TerraScape - 2024-07-17')
        (game / 'TerraScape.zip').write_bytes(b'PK\x03\x04' + b'0' * 512)
        summary = self.service.cleanup_leftovers(self.tmp / 'Games', grace_seconds=0)
        self.assertEqual(summary.get('empty_categories_removed'), 0,
                         f'a category holding an archive was reclaimed: {summary}')
        self.assertTrue(game.exists(), 'a game folder holding an archive was deleted')


class TestPreviewOnlyDoesNotMoveAnything(unittest.TestCase):
  """Preview Only said nothing was touched, and moved an archive to Archive/.

      The scan's own two neighbouring phases are guarded by `if not preview_only` and one of them carries a comment
      naming Preview Only as the reason. This third one was not, and it is the only one of the three that writes:
      the leftover-repair pass converts in place behind the review screen, but this one files a file away.

      Confirmed live before the fix, against a real library shape:

      Game/Loop Miner v1.0.zip  +  Game/Loop Miner v2.0.zip

      enforce_single_archive() returned 1 and Loop Miner v1.0.zip turned up in Archive/ - a move, on screen, while
      the feed was reporting 'Skipped in Preview Only - no files touched'.

      Two copies of one game in a folder is the case the method exists for: people drop a second copy in by hand,
      and identity_key() compares names after normalize_name() has stripped the version, so both are one identity.
      The survivor is chosen by version, so which file disappears depends on the versions, not on the user.

      Worth being precise about the first attempt, which is why this test names its files: 'Loop Miner (1).zip' does
      NOT reproduce it, because '(1)' survives normalize_name() as a distinct word and identity_key() returns
      'loopminer1'. It is correctly treated as a second, different game. Written as '(1)' this test would have
      passed against the bug, which is the outcome to avoid.

      The scope question this note raised is now answered, and the answer is the one this release commits to:
      Preview Only writes nothing, in any phase. The audit still runs and still reports - a user wants to know what
      a real scan would find - but it writes no link, no metadata sidecar and no artwork, and its refreshed count
      is literally 0 with a separate would_refresh count naming what a real scan would have done. The catalog is
      skipped outright and the summary says so rather than silently producing nothing. Discovery's password unlock
      rewrites a protected zip in place, so under preview that archive is reported as locked and uninspectable
      instead of being opened. The three gates live beside the existing ones (cleanup, dedupe, repair) in
      app/controller.py, all on the same preview_only argument, so the mode has one definition of read-only.
  """

  def _library_with_two_versions(self,root):
      """Builds <root>/<Category>/<Game>/ holding two versions of one archive, which is the shape the sweep
      actually walks. It needs saying, because a fixture one level deeper passes against the bug: the sweep reads
      library_root/<Category>/<Game>, so a root/Games/Idle/Loop Miner tree has it treating the *category* as the
      game folder, finding no archives in it, collapsing nothing, and reporting a clean sweep. That is exactly the
      shape that made the first version of this test prove nothing."""
      from core.logger import AppLogger
      from services.library_service import LibraryService
      from services.organizer_service import OrganizerService
      root=Path(root)
      game=root/'Idle'/'Loop Miner - 2024-01-01'; game.mkdir(parents=True)
      for name,size in (('Loop Miner v1.0.zip',2048),('Loop Miner v2.0.zip',4096)):
          (game/name).write_bytes(b'PK\x03\x04'+b'0'*size)
      (game/'.game-info.json').write_text(json.dumps({'appid':'1','name':'Loop Miner'}),encoding='utf-8')
      log=AppLogger(root/'x.log')
      return root,LibraryService(log),OrganizerService(log,convert_archives=False)

  def test_the_duplicate_sweep_is_guarded_by_preview_only(self):
      """Asserted on the parsed source, so the guard cannot be satisfied by a word in a comment."""
      import ast
      src=Path('app/controller.py').read_text(encoding='utf-8')
      tree=ast.parse(src)
      calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)
           and isinstance(n.func,ast.Attribute) and n.func.attr=='enforce_single_archive']
      self.assertEqual(len(calls),2,f'expected two enforce_single_archive() calls, found {len(calls)}')
    # The call inside scan() (which has a preview_only parameter) must be guarded so a preview-only
    # run never moves files. The call inside scan_new_artwork() needs no guard: that quick scan has
    # no preview_only mode and always modifies files.
      guards=[]
      for node in ast.walk(tree):
        if not isinstance(node,ast.If): continue
        names={n.id for n in ast.walk(node.test) if isinstance(n,ast.Name)}
        if 'preview_only' not in names: continue
        if any(inner is calls[0] for inner in ast.walk(node)) or any(inner is calls[1] for inner in ast.walk(node)):
            guards.append(node)
      self.assertTrue(guards,'at least one enforce_single_archive() call is inside a `if preview_only:` guard')

  def test_a_second_copy_in_the_folder_is_moved_when_not_previewing(self):
      """The precondition: if this did not move, the scan test below would pass for the wrong reason."""
      root=_tmp_dir(self)
      library,service,organizer=self._library_with_two_versions(root)
      self.assertEqual(service.enforce_single_archive(library,organizer),1)
      self.assertTrue((library/'Archive').is_dir(),'no archive was filed, so the case is not being exercised')
      self.assertFalse((library/'Idle'/'Loop Miner - 2024-01-01'/'Loop Miner v1.0.zip').exists(),
                   'the older version was not the one filed, so this is not the move the guard is about')

  def test_a_preview_only_scan_leaves_the_archives_as_it_found_it(self):
      """Driven through controller.scan(), because that is where the gate lives - the same way the neighbouring
      conversion test is, so the two phases of one scan are pinned by the same kind of evidence.

      Asserted on the archives and on Archive/, not on the folder listing. The audit phase writes a Steam link
      file in a normal scan, but under Preview Only it writes nothing (see the note above), so the folder listing is
      safe to assert on here too. Before the fix this failed with

       ['.game-info.json', 'Loop Miner v1.0.zip', 'Loop Miner v2.0.zip'] -> no Loop Miner v1.0.zip

      i.e. the older copy had been filed into Archive/ during a scan whose feed said nothing was touched."""
      from threading import Event
      from app.controller import AppController
      from app.events import EventBus
      from core.state import StateStore
      from app.jobs import JobManager
      from core.logger import AppLogger
      from services.rollback_service import RollbackService
      from services.library_service import LibraryService
      from services.archive_service import ArchiveService
      from services.artwork_service import ArtworkResult
      root=_tmp_dir(self)
      library,service,organizer=self._library_with_two_versions(root)
      game=library/'Idle'/'Loop Miner - 2024-01-01'
      archives=sorted(p.name for p in game.iterdir() if p.suffix.lower() in ('.zip','.rar','.7z'))
      self.assertEqual(archives,['Loop Miner v1.0.zip','Loop Miner v2.0.zip'],'the fixture is not two archives')
      logger=AppLogger(Path(root)/'scan.log'); jobs=JobManager()
      services=type('Services',(),{})()
      services.organizer=organizer; services.rollback=RollbackService(Path(root),logger)
      services.library=service; services.archive=ArchiveService(logger)
      services.artwork=type('Artwork',(),{'download_assets':lambda *a,**k:ArtworkResult(),'lookup':lambda *a,**k:ArtworkResult()})()
      services.catalog=type('Catalog',(),{'generate':lambda *a,**k:[]})()
      controller=AppController(StateStore(),EventBus(),logger,services,jobs)
      seen=[]; finished=Event()
      try:
          controller.scan(Path(root),lambda result:finished.set(),progress=lambda event:seen.append(event),preview_only=True)
          self.assertTrue(finished.wait(30),'the preview scan never finished')
      finally: jobs.shutdown()
      self.assertEqual(sorted(p.name for p in game.iterdir() if p.suffix.lower() in ('.zip','.rar','.7z')),archives,
                    'Preview Only moved an archive out of the game folder')
      self.assertFalse((library/'Archive').exists(),'Preview Only created the Archive folder')
      skipped=[e for e in seen if isinstance(e,dict) and e.get('stage')=='dedupe_done' and e.get('skipped')]
      self.assertEqual(len(skipped),1,f'the scan did not report the sweep as skipped: {seen}')
      # The rest of the scan still has to run: the first version of this fix returned early out of the phase, which
      # left discovery, the audit and the catalog silent while every phase above still reported itself.
      for stage in ('discover_done','audit_done','catalog_done'):
          self.assertTrue([e for e in seen if isinstance(e,dict) and e.get('stage')==stage],
                    f'{stage} never ran, so the scan was cut short: {[e.get("stage") for e in seen if isinstance(e,dict)]}')

  def test_a_preview_only_scan_leaves_every_file_byte_identical(self):
      """The strongest form: a full snapshot of every file under root is compared after the scan."""
      from services.extract_service import ExtractService
      from app.controller import AppController
      from app.events import EventBus
      from core.state import StateStore
      from app.jobs import JobManager
      from core.logger import AppLogger
      from services.rollback_service import RollbackService
      from services.library_service import LibraryService
      from services.archive_service import ArchiveService
      from services.artwork_service import ArtworkResult
      from services.organizer_service import OrganizerService
      root=Path(_tmp_dir(self))
      category=root/'Idle'; category.mkdir()
      game=category/'Loop Miner - 2024-01-01'; game.mkdir()
      archive=game/'Loop Miner v1.0.zip'
      with zipfile.ZipFile(archive,'w') as z: z.writestr('game.txt','data')
      (game/'.game-info.json').write_text(json.dumps({'appid':'1','name':'Loop Miner'}),encoding='utf-8')
      (game/'Loop Miner_grid.jpg').write_bytes(b'\xff\xd8\xff\xd9')
      tool=ExtractService.find_tool()[0]
      if not tool:
          self.fail('7-Zip is required to build an encrypted fixture zip and was not found')
      payload=root/'payload'; payload.mkdir()
      (payload/'Game Folder').mkdir()
      (payload/'Game Folder'/'main.exe').write_bytes(b'binary'*400)
      encrypted=root/'encrypted.zip'
      built=subprocess.run([tool,'a','-tzip','-p123','-bso0','-bsp0',str(encrypted),str(payload)],
                        stdin=subprocess.DEVNULL,capture_output=True)
      self.assertEqual(built.returncode,0,f'could not build the encrypted fixture: {built.stderr!r}')
      with zipfile.ZipFile(encrypted) as source:
          self.assertTrue(any(i.flag_bits & 0x1 for i in source.infolist() if not i.is_dir()),
                    'the fixture is not encrypted, so this test proves nothing')
      shutil.move(str(encrypted),str(game/'locked.zip'))
      before=sorted((p.relative_to(root),p.read_bytes(),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file())
      log_dir=Path(_tmp_dir(self))
      logger=AppLogger(log_dir/'scan.log'); jobs=JobManager()
      services=type('Services',(),{})()
      organizer=OrganizerService(logger,convert_archives=False)
      services.organizer=organizer
      services.rollback=RollbackService(log_dir,logger)
      services.library=LibraryService(logger)
      services.archive=ArchiveService(logger)
      services.artwork=type('Artwork',(),{'download_assets':lambda *a,**k:ArtworkResult(),'lookup':lambda *a,**k:ArtworkResult()})()
      catalog_calls=[]
class RecordingCatalog:
  def generate(self,*a,**k):
      catalog_calls.append((a,k))
      return []
      services.catalog=RecordingCatalog()
      controller=AppController(StateStore(),EventBus(),logger,services,jobs)
      finished=threading.Event()
      try:
          controller.scan(root,lambda result:finished.set(),progress=lambda event:None,preview_only=True)
          self.assertTrue(finished.wait(30),'the preview scan never finished')
      finally: jobs.shutdown()
      after=sorted((p.relative_to(root),p.read_bytes(),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file())
      self.assertEqual(before,after,'Preview Only changed a file in the library root')
      self.assertFalse(catalog_calls,'catalog.generate was called under Preview Only')

  def test_a_normal_scan_writes_artwork_and_generates_the_catalog(self):
      """The precondition: if this did not write anything, the preview test above would pass for the wrong reason."""
      from app.controller import AppController
      from app.events import EventBus
      from core.state import StateStore
      from app.jobs import JobManager
      from core.logger import AppLogger
      from services.rollback_service import RollbackService
      from services.library_service import LibraryService
      from services.archive_service import ArchiveService
      from services.artwork_service import ArtworkResult
      from services.organizer_service import OrganizerService
      root=Path(_tmp_dir(self))
      category=root/'Idle'; category.mkdir()
      game=category/'Loop Miner - 2024-01-01'; game.mkdir()
      archive=game/'Loop Miner v1.0.zip'
      with zipfile.ZipFile(archive,'w') as z: z.writestr('game.txt','data')
      (game/'.game-info.json').write_text(json.dumps({'appid':'1','name':'Loop Miner'}),encoding='utf-8')
      (game/'Loop Miner_grid.jpg').write_bytes(b'\xff\xd8\xff\xd9')
      before=sorted((p.relative_to(root),p.read_bytes(),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file())
      logger=AppLogger(Path(root)/'scan.log'); jobs=JobManager()
      services=type('Services',(),{})()
      organizer=OrganizerService(logger,convert_archives=False)
      services.organizer=organizer
      services.rollback=RollbackService(Path(root),logger)
      services.library=LibraryService(logger)
      services.archive=ArchiveService(logger)
      services.artwork=type('Artwork',(),{'download_assets':lambda *a,**k:ArtworkResult(),'lookup':lambda *a,**k:ArtworkResult()})()
      catalog_calls=[]
class RecordingCatalog:
  def generate(self,*a,**k):
      catalog_calls.append((a,k))
      return ['catalog.html']
      services.catalog=RecordingCatalog()
      controller=AppController(StateStore(),EventBus(),logger,services,jobs)
      finished=threading.Event()
      try:
          controller.scan(root,lambda result:finished.set(),progress=lambda event:None,preview_only=False)
          self.assertTrue(finished.wait(30),'the normal scan never finished')
      finally: jobs.shutdown()
      after=sorted((p.relative_to(root),p.read_bytes(),p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file())
      self.assertNotEqual(before,after,'a normal scan left the library root unchanged')
      self.assertTrue(catalog_calls,'catalog.generate was not called in a normal scan')
      self.assertTrue((game/'Open Steam Page.html').exists(),'a normal scan did not write the Steam link')


def _label_texts(widget):
    """Every label's text under a widget, in one list. Used to read what a screen actually rendered rather than
    what its code was going to render."""
    import tkinter as tk
    found=[]
    for child in widget.winfo_children():
        if isinstance(child,tk.Label): found.append(str(child.cget('text')))
        found.extend(_label_texts(child))
    return found


class TestTheAppStopsReportingWorkItDidNotDo(unittest.TestCase):
  """Six readouts that answered a question nobody asked, so the number on screen was not the number on disk.

 None of them crashed and none of them logged: each was output that was confidently wrong, on screens whose
 entire job is to tell the user what the last run did. Every case was reproduced on this machine before the
 fix, and each test is written so that putting the fix back fails it - which is the only evidence here that a
 test is looking at the defect rather than at its own fixture.

 Fix 1 and fix 2 are the same function and are kept as two tests, because they were two separate false readouts
 that happened to share a line of code, and one test asserting both would not say which one came back.
 """

  def _facts_view(self,**extra):
      """The Done screen's RUN FACTS rail as a stand-in, so _paint_facts can be called without a window.

      `state` hands back a real AppState, and that is the point of the fixture rather than a shortcut: the defect
      was that AppState carries neither `config` nor `rollback_pending`, so a stand-in state that had them would
      have made the screen look right and hidden the bug these tests exist for. The library root arrives as a
      config object rather than a path, because the screen holds the config - a Path cannot follow the rebind
      MainWindow.choose() makes, and holding one was how the row went stale after a Games-directory change.
      """
      from core.models import AppState
      view=SimpleNamespace(facts={name:Mock() for name in ('duration','compressed','saved','free','undo','where')},
                       state=SimpleNamespace(get=lambda:AppState()),rollback=None,config=None,undo_btn=Mock())
      for name,value in extra.items(): setattr(view,name,value)
      return view

  def _shown(self,view,fact):
      """The text one RUN FACTS row was last given."""
      return view.facts[fact].configure.call_args.kwargs['text']

  def _audit_library(self,root):
      """One organized game folder carrying an AppID and no artwork: the shape of every folder in a real library,
      and the case the audit used to call 'refreshed' whatever else was true."""
      library=Path(root)/'Games'; game=library/'Puzzle'/'Sintopia - 1 Jan, 2026'
      game.mkdir(parents=True)
      (game/'.game-info.json').write_text(json.dumps({'appid':'1234','name':'Sintopia'}),encoding='utf-8')
      # The folder carries its archive, so the empty-folder sweep does not prune it. A game folder with no
      # archive is exactly what the sweep is for, and this fixture is an organized game that is still there.
      (game/'Sintopia.7z').write_bytes(b'7z\xbc\xaf\x27\x1c')
      organizer=SimpleNamespace(write_steam_links=Mock(),write_metadata=Mock())
      return library,game,organizer

  def _image(self,path):
      """A real JPEG rather than four bytes, because ArtworkPanel decodes what it is given and a truncated file
      would fail the artwork test for a reason that has nothing to do with the filenames on it."""
      from PIL import Image
      path.parent.mkdir(parents=True,exist_ok=True)
      Image.new('RGB',(12,16),(24,28,32)).save(str(path),'JPEG')
      return path

  def test_the_done_screen_undo_row_reads_the_journal_rather_than_the_app_state(self):
      """Reproduced before the fix: pending_count() was 1 and the row said 'nothing to undo'.

      It read `getattr(snap,'rollback_pending',())`, and AppState has no such field and nothing anywhere sets one,
      so the getattr default is what the row always showed. The Undo button would in fact have restored every
      move the run had made. The count is read from the journal file rather than remembered anywhere, because
      undo_last() consumes that file - a remembered number is one more thing that can disagree with the button.
      """
      from ui.done_view import DoneView
      view=self._facts_view(rollback=SimpleNamespace(pending_count=lambda:3))
      DoneView._paint_facts(view,[],[],[])
      self.assertEqual(self._shown(view,'undo'),'3 move(s)',
                   'the Undo row disagrees with the journal it exists to summarise')
      view.undo_btn.configure.assert_called_with(state='normal')

  def test_the_done_screen_undo_button_is_disabled_when_journal_is_empty(self):
      """When the rollback journal is empty the Undo button must not offer an action it cannot perform."""
      from ui.done_view import DoneView
      view=self._facts_view(rollback=SimpleNamespace(pending_count=lambda:0))
      DoneView._paint_facts(view,[],[],[])
      view.undo_btn.configure.assert_called_with(state='disabled')

  def test_the_done_screen_names_the_library_and_the_space_left_on_it(self):
      """Reproduced before the fix: both rows rendered their placeholder - 'Library: -' and 'Free space: -' -
      immediately after a successful run, because they read `snap.config` and AppState has no config either.

      Both were getattr-guarded, which is why nothing crashed: the guard is exactly what let the wrong answer
      through. Free space is the number that decides whether the next conversion can finish, so it is read from
      the volume that actually holds the library rather than from a field that does not exist.

      The config is read at paint time, not captured at construction: a Path is an immutable snapshot, and
      MainWindow rebinds config.library_root when the Games directory changes, so a value taken once named the
      previous directory for the rest of the session - the same false row, one level up.
      """
      from utils.formatting import human_size
      library=Path(_tmp_dir(self))/'Steam Games'; library.mkdir()
      config=SimpleNamespace(library_root=library)
      view=self._facts_view(config=config)
      from ui.done_view import DoneView
      DoneView._paint_facts(view,[],[],[])
      self.assertEqual(self._shown(view,'where'),str(library),'the Library row fell back to its placeholder')
      free=self._shown(view,'free')
      self.assertNotEqual(free,'—','the free-space row fell back to its placeholder')
      self.assertEqual(free,human_size(shutil.disk_usage(str(library)).free),
                   'the free-space row is reporting some other volume than the library')
      config.library_root=Path(_tmp_dir(self))/'Other Games'
      DoneView._paint_facts(view,[],[],[])
      self.assertEqual(self._shown(view,'where'),str(config.library_root),
                   'the row still names the directory the app was opened with, after the user changed it')

  def test_the_audit_reports_a_folder_it_could_not_refresh_as_a_failure(self):
      """Reproduced before the fix: offline, with an AppID that has no art on Steam, the audit returned
      `refreshed: 1`, the progress line read 'artwork refreshed', and there was no image on disk.

      `_audit_game` returned `changed or not has_any`, which folds "files were written" and "this folder had no
      artwork and still has none" into the same truthy value, and the per-folder line never asked the function at
      all - it reported 'artwork refreshed' for any folder holding an AppID. A user reading that would go and
      fetch artwork they already had, or believe a failed fetch had succeeded.
      """
      from core.logger import AppLogger
      from core.models import ArtworkResult
      from services.library_service import LibraryService
      root=_tmp_dir(self); library,game,organizer=self._audit_library(root)
      offline=SimpleNamespace(download_assets=lambda *a,**k:ArtworkResult(reason='offline'))
      seen=[]
      summary=LibraryService(AppLogger(Path(root)/'audit.log')).audit(library,offline,organizer,on_progress=seen.append)
      self.assertEqual(summary['refreshed'],0,'a folder nothing was written to was counted as refreshed')
      self.assertEqual(summary['no_artwork'],1,f'the folder was not reported as having no artwork: {summary}')
      self.assertEqual(sorted(p.suffix for p in game.iterdir()),['.7z','.json'],'the fixture gained artwork it was never given')
      lines=[e['message'] for e in seen if isinstance(e,dict) and e.get('stage')=='audit_item' and e.get('state')=='done']
      self.assertTrue(lines,f'the audit reported nothing per folder: {seen}')
      self.assertNotIn('artwork refreshed',lines[-1],f'the per-folder line still claims a refresh: {lines[-1]}')
      self.assertIn('no artwork available',lines[-1],f'the per-folder line does not say what went wrong: {lines[-1]}')
      # Driven through controller.scan(), because the line the user reads last is the controller's and not the
      # service's. audit() reports its own no-artwork figure on its audit_done event, but audit_progress()
      # relabels that as an ordinary 'audit' line and the controller then emits a second audit_done from
      # checked/refreshed alone - so the count was computed, logged, and dropped on the way to the screen.
      from threading import Event
      from app.controller import AppController
      from app.events import EventBus
      from app.jobs import JobManager
      from core.state import StateStore
      from services.archive_service import ArchiveService
      from services.rollback_service import RollbackService
      root2=_tmp_dir(self); library2,game2,organizer2=self._audit_library(root2)
      logger2=AppLogger(Path(root2)/'scan.log'); jobs2=JobManager()
      services2=type('Services',(),{})()
      services2.library=LibraryService(logger2); services2.organizer=organizer2
      services2.rollback=RollbackService(Path(root2),logger2,organizer=organizer2)
      services2.archive=ArchiveService(logger2)
      services2.artwork=type('Artwork',(),{'download_assets':lambda *a,**k:ArtworkResult(reason='offline'),
                                        'lookup':lambda *a,**k:ArtworkResult()})()
      services2.catalog=type('Catalog',(),{'generate':lambda *a,**k:[]})()
      controller2=AppController(StateStore(),EventBus(),logger2,services2,jobs2)
      phases=[]; finished2=Event()
      try:
          controller2.scan(library2,lambda result:finished2.set(),progress=lambda event:phases.append(event))
          self.assertTrue(finished2.wait(30),'the scan never finished')
      finally: jobs2.shutdown()
      summaries=[e['message'] for e in phases if isinstance(e,dict) and e.get('stage')=='audit_done' and e.get('message')]
      self.assertTrue(summaries,f'the scan reported no audit summary at all: {[e.get("stage") for e in phases if isinstance(e,dict)]}')
      self.assertEqual(len(summaries),1,f'the audit announced itself as finished more than once: {summaries}')
      self.assertIn('1 with no artwork',summaries[0],
                f'the last line the user reads drops the count of folders with no artwork: {summaries[0]!r}')

  def test_the_audit_can_still_report_a_folder_it_really_refreshed(self):
      """The precondition for the test above. If this fixture could never refresh anything, that test would pass
      for the wrong reason - so the same folder is audited again with artwork to hand, and must count."""
      from core.logger import AppLogger
      from core.models import ArtworkResult
      from services.library_service import LibraryService
      root=_tmp_dir(self); library,game,organizer=self._audit_library(root)
      cached=self._image(Path(root)/'cache'/'grid.jpg')
      online=SimpleNamespace(download_assets=lambda *a,**k:ArtworkResult(status='downloaded',path=cached))
      summary=LibraryService(AppLogger(Path(root)/'audit.log')).audit(library,online,organizer)
      self.assertEqual(summary['refreshed'],1,f'a folder that gained an image was not counted: {summary}')
      self.assertTrue((game/'Sintopia_grid.jpg').is_file(),f'nothing was copied into the folder: {sorted(p.name for p in game.iterdir())}')

  def test_the_artwork_screen_names_only_files_that_are_on_disk(self):
      """Reproduced before the fix: four of twelve real Steam names were listed under a filename that did not
      exist. Two separate mistakes, and both are exercised here.

      The prefix was rebuilt as `' '.join(name.split())`, which agrees with the sanitiser on an ordinary name and
      disagrees on any name holding a character the sanitiser deletes - so 'Settlements: Legacy' was listed as
      'Settlements: Legacy_grid.jpg' against a file called 'Settlements Legacy_grid.jpg'. The asset name was
      recovered from the cached file's stem with `stem.split('_',1)[-1]`, a guess that only holds while the cache
      happens to prefix every filename; the cache stores each asset as `<key>.jpg` with nothing in front, so
      'header_image' came back as 'image' and 'library_hero' as 'hero'. The plain-named game below pins that
      half, and it is the one that fails on an ordinary title.
      """
      import tkinter as tk
      from core.models import ArtworkResult
      from services.organizer_service import OrganizerService
      from ui.artwork_view import ArtworkView,_asset_prefix_for
      root=Path(_tmp_dir(self)); cache=root/'cache'
      # The organizer's own sanitiser, not the screen's, decides every filename on disk - so the fixture and the
      # assertion both go through it. Asking the screen instead would make the test agree with any prefix at all.
  def sanitize(title): return OrganizerService._safe_name(OrganizerService.__new__(OrganizerService),title)
  def game(title):
   # The folder carries the sanitised name, because a colon cannot exist in a Windows filename - which is
   # precisely why the sanitiser is there, and why the two spellings have to be kept apart here.
      prefix=sanitize(title)
      folder=root/'Puzzle'/f'{prefix} - 1 Jan, 2026'; folder.mkdir(parents=True)
      assets={}
      for key in ('header_image','library_hero','background_raw'):
          assets[key]=self._image(cache/f'{key}.jpg')
          self._image(folder/f'{prefix}_{key}.jpg')
      grid=self._image(folder/f'{prefix}_grid.jpg')
      return SimpleNamespace(path=folder/f'{prefix}.7z',steam=SimpleNamespace(name=title,appid='1234'),
                          user_title='',display_name=title,
                          artwork=ArtworkResult(status='downloaded',path=grid,assets=assets),
                          decision=SimpleNamespace(accepted=True)),folder
      colon,colon_folder=game('Settlements: Legacy')
      # An ordinary title, which sanitises to itself. This is the game that fails when only the asset name is
      # wrong, so the two halves of the defect are pinned by two different games rather than by one of both.
      plain,plain_folder=game('Brave New Wonders')
      self.assertEqual(_asset_prefix_for(colon),sanitize(colon.steam.name))
      self.assertNotEqual(_asset_prefix_for(colon),colon.steam.name,
                      'the prefix was not sanitised, so this test cannot fail for the reason it is here for')
      window=tk.Tk(); window.withdraw(); self.addCleanup(window.destroy)
      view=ArtworkView(window,on_done=lambda:None)
      view.show([colon,plain])
      listed=[text.split('\nAssets: ',1)[1] for text in _label_texts(view.inner) if '\nAssets: ' in text]
      self.assertEqual(len(listed),2,f'the screen did not list assets for both games: {listed}')
      for folder,names in zip((colon_folder,plain_folder),listed,strict=True):
          for name in names.split(', '):
              self.assertTrue((folder/name).is_file(),
                          f'the screen names {name!r}, which is not in {folder.name}: on disk it is {sorted(p.name for p in folder.iterdir())}')

  def test_extract_with_no_dest_lands_in_the_extract_folder_itself(self):
      """Reproduced before the fix: the app's own message named the path -
      `Extracted 2 file(s) to C:\\Users\\...\\Downloads\\extracted\\Extracted`.

      config.extract_folder is already the folder extracted games go in; it is what the catalog's Extract button
      writes to and what the protocol handler is restricted to. The command line appended the name again, so
      every --extract without an explicit --dest landed one level deeper than the same game extracted from the
      catalog, and both runs wrote into folders nothing else ever read.
      """
      import steam_game_organizer
      root=Path(_tmp_dir(self)); extracted=root/'extracted'
      config=SimpleNamespace(extract_folder=extracted,settings={})
      args=SimpleNamespace(dest=None,extract=str(root/'Sintopia.zip'),zip_password='')
      with patch.object(steam_game_organizer,'_extract',return_value=SimpleNamespace(message='',ok=True)) as extract:
          steam_game_organizer._extract_to_disk(args,config,Mock())
          self.assertEqual(extract.call_args.args[1],extracted,
                   f'a folder was appended to the extract folder: {extract.call_args.args[1]}')

  def _undo_case(self,extra=(),owned=True):
      """A journalled organize of one game, ready for undo_last().

      `extra` adds entries to the game folder, and `owned` decides whether the run is recorded as having created
      it. The two matter separately because they are the two independent guards: a folder the run did not create
      is left alone whatever it holds, and a folder it did create is left alone if it holds anything else.
      """
      from core.logger import AppLogger
      from services.organizer_service import OrganizerService
      from services.rollback_service import RollbackService
      root=Path(_tmp_dir(self)); project=root/'project'; project.mkdir()
      # Incoming holds no archive: the run moved it out, which is the state undo_last() is called from. A file left
      # there would make `not restore.exists()` false and the undo a no-op - a fixture that proves nothing.
      source=root/'Incoming'/'Sintopia v1.0.7z'; source.parent.mkdir()
      library=root/'Games'; game=library/'Puzzle'/'Sintopia - 2026-01-01'; game.mkdir(parents=True)
      organized=game/'Sintopia.7z'; organized.write_bytes(b'7z\xbc\xaf\x27\x1c')
      (game/'.game-info.json').write_text(json.dumps({'appid':'1234','name':'Sintopia'}),encoding='utf-8')
      for name,body in extra:
          target=game/name
          if body is None: target.write_bytes(b'\xff\xd8\xff\xd9')
          else: target.write_text(body,encoding='utf-8')
      logger=AppLogger(project/'rollback.log')
      service=RollbackService(project,logger,organizer=OrganizerService(logger))
      dirs=[str(game)] if owned else []
      self.assertTrue(service.record([(source,organized)],dirs),'the move was not journalled, so Undo has nothing to undo')
      return service,source,organized,game,library

  def test_undo_removes_the_game_folders_the_run_emptied(self):
      """Reproduced over a 13-game organize: Undo restored all 13 archives and left 12 folders behind.

      The archive goes home and the folder the run created stays holding what the run wrote into it - the
      metadata, the Steam link, the artwork. It names a game it does not contain, no scan reports it, and the
      user has to delete it by hand. The decision to remove is delegated to OrganizerService._folder_is_prunable
      rather than reimplemented, so the allow-list protecting a player's saves stays in one place.
      """
      service,source,organized,game,library=self._undo_case(extra=(('Sintopia_grid.jpg',None),))
      result=service.undo_last(library)
      self.assertEqual(result['moved'],1,f'the archive was not restored: {result}')
      self.assertEqual(result['pruned'],1,f'the emptied folder was not pruned: {result}')
      self.assertTrue(source.is_file(),'the archive did not go home')
      self.assertFalse(game.exists(),f'Undo left the emptied game folder behind: {sorted(p.name for p in game.iterdir()) if game.is_dir() else "the archive is back and the folder is still there"}')
      self.assertTrue(library.is_dir(),'the category folder the game sat in was removed as well')

  def test_undo_leaves_a_game_folder_holding_something_it_did_not_write(self):
      """Passes either way, deliberately: a pruning rule that has only been shown to remove things is half a
      safety argument. A save file is the obvious case and it is enough."""
      service,source,organized,game,library=self._undo_case(extra=(('save.dat','progress'),))
      service.undo_last(library)
      self.assertTrue((game/'save.dat').is_file(),f'Undo deleted a save file: {game}')
      self.assertTrue(source.is_file(),'the archive was not restored, so this case proved nothing')

  def test_undo_leaves_a_photo_the_player_saved_beside_the_game(self):
      """The allow-list judges provenance by name and suffix, and a screenshot beside a game is a .jpeg like any
      other. It used to be _folder_is_disposable(), which accepts every image suffix - correct for the download
      folder this app emptied itself, and wrong for the user's game folder, where the first version of this prune
      applied it. Verified against that version: the folder came back gone.
      """
      service,source,organized,game,library=self._undo_case(extra=(('my-photo.jpeg',None),))
      service.undo_last(library)
      self.assertTrue((game/'my-photo.jpeg').is_file(),
                  f'Undo deleted a picture the player saved: {sorted(p.name for p in game.iterdir()) if game.is_dir() else "the whole folder is gone"}')

  def test_undo_leaves_a_game_folder_the_run_did_not_create(self):
      """OrganizerService.move() reuses a category/game folder that is already there and records
      created_game_dir=False, so a source/target pair alone cannot tell the two apart. This is the same rule
      AppController._prune_rolled_back_folder() applies from the same flag; the first version of this prune had
      no equivalent and would have removed a folder the user made."""
      service,source,organized,game,library=self._undo_case(owned=False)
      result=service.undo_last(library)
      self.assertEqual(result['moved'],1,f'the archive was not restored: {result}')
      self.assertEqual(result['pruned'],0,f'a folder this run did not create was removed: {result}')
      self.assertTrue((game/'.game-info.json').is_file(),f'the folder was removed anyway: {game}')

  def test_undo_refuses_a_journal_row_naming_a_folder_outside_the_library(self):
      """The journal is a file in config/, and both ends of every row go from it into shutil.move and
      shutil.rmtree. undo_last() already accepted the configured library root and never looked at it."""
      from core.logger import AppLogger
      from services.organizer_service import OrganizerService
      from services.rollback_service import RollbackService
      root=Path(_tmp_dir(self)); project=root/'project'; project.mkdir()
      library=root/'Games'; library.mkdir()
      elsewhere=root/'Photos'/'holiday'; elsewhere.mkdir(parents=True)
      # Named the way the app names its own artwork - an underscore in the stem - so _folder_is_prunable() would
      # accept it and the containment check is the only thing refusing. A plain sunset.jpg would have been saved
      # by the stricter allow-list instead, and this test would have passed without testing what it is for.
      kept=elsewhere/'holiday_grid.jpg'; kept.write_bytes(b'\xff\xd8\xff\xd9')
      away=elsewhere/'clip.rar'; away.write_bytes(b'Rar!\x1a\x07\x00')
      logger=AppLogger(project/'rollback.log')
      service=RollbackService(project,logger,organizer=OrganizerService(logger))
      self.assertTrue(service.record([(root/'Incoming'/'clip.rar',away)],[str(elsewhere)]),
                  'the row was not journalled, so this case proves nothing')
      result=service.undo_last(library)
      self.assertEqual(result['pruned'],0,f'a folder outside the library was removed: {result}')
      self.assertTrue(kept.is_file(),f'Undo deleted a folder outside the library: {sorted(elsewhere.iterdir()) if elsewhere.is_dir() else "it is gone"}')


class TestTheBundledRuntimeTravelsWithTheApp(unittest.TestCase):
  """The runtime folder is what makes a copied app folder work on a bare PC."""

  def test_find_tool_answers_with_the_bundled_copy_before_path(self):
      import services.extract_service as module
      from services.extract_service import ExtractService, clear_tool_cache
      root=Path(_tmp_dir(self))
      bundled=root/'app'/'runtime'; bundled.mkdir(parents=True)
      shipped=bundled/'7z.exe'; shipped.write_bytes(b'bundled')
      on_path=root/'bin'; on_path.mkdir()
      stub=on_path/'7z.bat'; stub.write_text('@echo stub')
      old_path=os.environ['PATH']
      os.environ['PATH']=str(on_path)+os.pathsep+old_path
      self.addCleanup(setattr,os.environ,'PATH',old_path)
      original=module.APP_ROOT
      module.APP_ROOT=root/'app'
      self.addCleanup(setattr,module,'APP_ROOT',original)
      clear_tool_cache()
      found,reason=ExtractService.find_tool()
      self.assertEqual(found,str(shipped),
                       f'the bundled copy was not the answer ({found}, {reason})')
      shipped.unlink()
      clear_tool_cache()
      found,reason=ExtractService.find_tool()
      self.assertEqual(str(found).casefold(),str(stub).casefold(),
                       f'with no bundle the PATH answer was not kept ({found}, {reason})')

  def test_the_plan_builds_the_layout_the_bundled_interpreter_needs(self):
      import sys
      from sysconfig import get_config_var
      from tools.bundle_runtime import build_plan
      version=get_config_var("LDVERSION") or f"python{sys.version_info.major}{sys.version_info.minor}"
      root=Path(_tmp_dir(self)); source=root/'install'; destination=root/'runtime'
      source.mkdir()
      for name in ('python.exe','pythonw.exe','python3.dll','vcruntime140.dll'):
          (source/name).write_bytes(b'x')
      (source/f'{version}.dll').write_bytes(b'x')
      for folder in ('DLLs','tcl','tk'):
          (source/folder).mkdir()
          (source/folder/'a.pyd' if folder=='DLLs' else source/folder/'a').write_bytes(b'x')
      (source/'Lib').mkdir()
      (source/'Lib'/'os.py').write_text('pass')
      (source/'Lib'/'test').mkdir()
      (source/'Lib'/'test'/'test_os.py').write_text('pass')
      (source/'LICENSE.txt').write_text('PSF')
      plan=build_plan(source,destination,sevenzip=root/'7z.exe')
      files={str(step.destination.relative_to(destination)) for step in plan if step.kind=='file'}
      for expected in ('python.exe','pythonw.exe','python3.dll','vcruntime140.dll',
                    f'{version}.dll','LICENSE.txt','7z.exe'):
          self.assertIn(expected,files,f'the plan does not copy {expected}')
      trees={str(step.destination.relative_to(destination)) for step in plan if step.kind=='tree'}
      for expected in ('Lib','DLLs','tcl','tk'):
          self.assertIn(expected,trees,f'the plan does not copy {expected}/')
      lib=next(step for step in plan if step.kind=='tree'
           and str(step.destination.relative_to(destination))=='Lib')
      self.assertIn('test',lib.exclude,'the standard library test suite would travel with the runtime')
      pyth=[step for step in plan if step.kind=='write' and step.destination.suffix=='._pth']
      self.assertEqual(1,len(pyth),'the interpreter needs exactly one _pth')
      self.assertEqual(pyth[0].content,'.\nLib\nDLLs\n',
                   'the _pth is the whole path search on a machine with no registry entry for Python')
      # Pillow must be included: Steam artwork is JPEG and tk.PhotoImage cannot decode it
      pil_steps=[step for step in plan if step.destination.relative_to(destination).parts==('Lib','PIL')]
      has_pillow=any(step.kind=='tree' and step.source for step in pil_steps if step.source and step.source.is_dir())
      self.assertTrue(has_pillow,'the build plan does not include Pillow, so JPEG artwork cannot render')

  def test_a_bundled_runtime_is_reported_by_the_check(self):
      """--check has to say what is actually there, because a folder a friend copied
      is the one place nobody will run a build in - a silent empty runtime/ would
      otherwise look like the answer to "nothing needs installed"."""
      from tools import bundle_runtime
      root=Path(_tmp_dir(self)); (root/'python.exe').write_bytes(b'x')
      original=bundle_runtime.RUNTIME
      bundle_runtime.RUNTIME=root
      self.addCleanup(setattr,bundle_runtime,'RUNTIME',original)
      with patch('subprocess.run') as probe:
          probe.return_value=SimpleNamespace(returncode=0,stdout='3.13.15\n',stderr='')
          with patch('builtins.print') as report:
              self.assertEqual(0,bundle_runtime.check())
      said=' '.join(str(call.args[0]) for call in report.call_args_list)
      self.assertIn('3.13.15',said,'the check did not report the bundled version')
      self.assertIn('NOT bundled',said,'the check did not name a missing 7z.exe')


class TestTheCategoryDecisionSurvivesALockedFolder(unittest.TestCase):
  """remember_category() writes the user's pick through the same folder OneDrive
 syncs. v9.19 absorbed that lock for settings.json; the category decisions were
 written with a fixed temp name and an unguarded replace, so the same brief lock
 raised out of the review screen's click handler and took the pick with it."""

  def _controller(self,d):
      from app.controller import AppController
      from app.events import EventBus
      from app.jobs import JobManager
      from core.state import StateStore
      self.warnings=[]
      logger=SimpleNamespace(warning=lambda *a,**k: self.warnings.append((a,k)))
      jobs=JobManager()
      controller=AppController(StateStore(),EventBus(),logger,type('Services',(),{})(),jobs)
      controller.config=type('Config',(),{'config_dir':Path(d), 'sync_to_appdata': lambda self: None})()
      self.addCleanup(jobs.shutdown)
      return controller

  def test_a_brief_lock_on_the_replace_is_retried(self):
      import os as os_module
      root=Path(_tmp_dir(self)); controller=self._controller(root)
      real=os_module.replace; calls=[]
  def flaky(src,dst):
      calls.append(str(src))
      if len(calls)==1: raise PermissionError('locked')
      return real(src,dst)
      with patch('os.replace',side_effect=flaky):
        controller.remember_category('example','Simulation')
        self.assertEqual(controller._saved_categories()['identity']['example'],'Simulation',
                        'the pick was lost to a lock that a retry would have cleared')

  def test_a_stale_temp_file_of_the_old_fixed_name_cannot_block_the_write(self):
      """The old writer used category-decisions.tmp for every write, so a leftover
      from a crashed run - read-only, or held by a second copy of the app - was in
      the way of the next one. mkstemp names are unique, so the stale file is
      simply never opened: the fixture is the old collision, and the write has to
      succeed around it."""
      root=Path(_tmp_dir(self)); controller=self._controller(root)
      stale=root/'category-decisions.tmp'; stale.write_text('{}')
      os.chmod(stale,0o444)
      self.addCleanup(lambda: os.chmod(stale,0o644))
      controller.remember_category('example','Simulation')
      self.assertEqual(controller._saved_categories()['identity']['example'],'Simulation',
                     'a stale temp file of the old fixed name blocked the write')
      self.assertEqual(stale.read_text(),'{}',
                     'the write went through the stale file instead of around it')

  def test_a_lock_that_outlives_the_retries_costs_a_warning_not_a_crash(self):
      """The decision is already held in memory when the write runs, so a folder
      that stays locked costs the on-disk copy of the pick - not the callback the
      click handler was mid-way through. The old code raised straight out of the
      review screen's handler."""
      root=Path(_tmp_dir(self)); controller=self._controller(root)
      with patch('os.replace',side_effect=PermissionError('locked')):
        controller.remember_category('example','Simulation')
        self.assertEqual(controller._category_cache['identity'].get('example'),'Simulation',
                        'the in-memory decision was lost with the write')
      self.assertTrue(self.warnings,
                    'a pick that could not be saved was not reported anywhere')
      self.assertEqual(list(root.glob('category-decisions.*.tmp')),[],
                     f'the temp file was left behind: {list(root.glob("category-decisions.*"))}')
