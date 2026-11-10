"""Tests for the service layer: discovery, Steam resolution, the library and the conversion pipeline."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import pytest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from app.jobs import JobContext
from core.config import AppConfig
from core.constants import COMPRESSION_LEVEL, COMPRESSION_THREADS, canonical_category, suggest_category, DEFAULT_ZIP_PASSWORD
from core.exceptions import CancellationError
from core.logger import AppLogger
from core.models import ArtworkResult, GameArchive, SteamMatch
from services.archive_service import ArchiveService
from services.extract_service import ExtractService
from services.library_service import LibraryService, _RepairArchive
from services.organizer_service import OrganizerService
from services.steam_service import SteamService
from utils.filename_utils import identity_key

GB = 1024**3

# --------------------------------------------------------------------------------------------------
# Archive tool stubs.
#
# The conversion pipeline is driven entirely by what an external archiver prints and what it exits with, so
# it is exercised against a tar-backed fake rather than the real 7-Zip. Two things follow. The tests behave
# identically on a machine with 7-Zip installed and one without, so the genuine tool being found changes
# nothing. And a stub can be made to fail in one specific place - extract_failing below - which is the only
# way to reach the branch that records why an extraction died.
# --------------------------------------------------------------------------------------------------

# The subcommand forms the app actually issues:
#   7z x -y -bsp1 -o<dir> [-p<pw>] <archive>      extract (the destination is a switch)
#   7z a -t7z -mx=<n> -bsp1 -xr!<marker> [-mmt=n] <target> .   build (run in the extracted folder)
#   7z t [--] <archive>                           integrity test
#   7z l -slt -p [--] <archive>                   manifest: blank-line separated blocks of Path =/Size =
#   7z e -so [--] <archive> <member>              one member to stdout, read as bytes
# plus unrar's own spelling, x -y -o+ <archive> <dest>\, where the destination is the last operand.
_STUB_ARCHIVER = r"""#!/usr/bin/env python3
import os,sys,tarfile,zipfile

def _fail(message,code=2):
    sys.stdout.write('ERROR: '+message+'\n')
    sys.stdout.flush()
    raise SystemExit(code)

def _split(args):
    # Unknown switches are ignored. 7-Zip 26.x accepts -mci=off (Defender content-intelligence) and
    # -mhe=on (header encryption) in addition to the ones the stub actually acts on; the stub is a
    # minimal stand-in for the real tool, not a parser of its full flag set.
    return [a for a in args if a.startswith('-') and a not in ('-mci=off','-mhe=on')],[a for a in args if not a.startswith('-')]

def _switch(switches,prefix):
    for item in switches:
        if item.startswith(prefix): return item[len(prefix):]
    return ''

def _open(path):
    try:
        with open(path,'rb') as handle: magic=handle.read(4)
    except OSError as exc: _fail('cannot open archive as archive: '+str(exc))
    try: return zipfile.ZipFile(path) if magic[:2]==b'PK' else tarfile.open(path)
    except Exception as exc: _fail('cannot open archive as archive: '+str(exc))

def _entries(archive):
    if isinstance(archive,tarfile.TarFile):
        return [(m.name,m.size,m.isdir()) for m in archive.getmembers()]
    return [(i.filename,i.file_size,False) for i in archive.infolist() if not i.is_dir()]

def _progress(done,total,name):
    percent=int(done*100/total) if total else 100
    sys.stdout.write(' %d%% %d - %s\n'%(percent,done,name))
    sys.stdout.flush()

def _extract(source,destination):
    archive=_open(source)
    try:
        entries=_entries(archive)
        os.makedirs(destination,exist_ok=True)
        for index,entry in enumerate(entries,1): _progress(index,len(entries),entry[0])
        archive.extractall(destination)
    finally: archive.close()
    sys.stdout.write('Everything is Ok\n')

def _create(target,excluded):
    with tarfile.open(target,'w') as tar:
        for folder,dirs,files in os.walk('.'):
            for name in sorted(dirs)+sorted(files):
                full=os.path.join(folder,name)
                arc=os.path.relpath(full,'.').replace(os.sep,'/')
                if any(arc.endswith(item.lstrip('!')) for item in excluded): continue
                tar.add(full,arcname=arc)
    sys.stdout.write('Everything is Ok\n')

def _list(source):
    archive=_open(source)
    try: entries=_entries(archive)
    finally: archive.close()
    lines=['','----------','Type = 7z','Physical Size = 0']
    for name,size,isdir in entries:
        lines.append('')
        lines.append('Path = '+name)
        # A directory carries no Size of its own; 7-Zip 26.x marks it with Attributes = D and older builds with
        # Folder = +, so both are emitted and the organizer's manifest reader drops it either way.
        lines.append('Folder = +' if isdir else 'Size = %d'%size)
    sys.stdout.write('\n'.join(lines)+'\n')

def _test(source):
    archive=_open(source)
    try:
        if isinstance(archive,tarfile.TarFile):
            for member in archive.getmembers():
                if member.isfile(): archive.extractfile(member).read()
        else: archive.testzip()
    finally: archive.close()
    sys.stdout.write('Everything is Ok\n')

def _emit(source,member):
    archive=_open(source)
    try: data=archive.extractfile(member).read()
    finally: archive.close()
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()

def main():
    argv=sys.argv[1:]
    if not argv: _fail('no command given',1)
    command=argv[0]
    switches,operands=_split(argv[1:])
    if not operands: _fail('no archive given',1)
    if command=='x':
        destination=_switch(switches,'-o')
        if destination in ('','+'): destination=operands[-1] if len(operands)>1 else '.'
        _extract(operands[0],destination)
    elif command=='e' and not _switch(switches,'-o'):
        _emit(operands[0],operands[-1])
    elif command=='a':
        _create(operands[0],[item[4:] for item in switches if item.startswith('-xr!')])
    elif command=='l': _list(operands[0])
    elif command=='t': _test(operands[0])
    else: _fail('unsupported command: '+command,1)

main()
"""

# Inserted straight after the shebang so `7z t` still passes: a stub that failed every command would also
# fail the integrity check, and the organizer now refuses an archive that fails it before it ever reaches
# extraction - correct behaviour that would leave the extraction-failure path untested.
_STUB_FAILING_EXTRACT = r"""import sys as _sys
if len(_sys.argv)>1 and _sys.argv[1]=='x':
    _sys.stdout.write('ERROR: cannot open archive as archive\n')
    _sys.stdout.flush()
    raise SystemExit(2)
"""

_STUB_BODIES = {"7z": _STUB_ARCHIVER, "7za": _STUB_ARCHIVER, "unrar": _STUB_ARCHIVER}


def _write_stub(bin_dir, tool, body):
    """Write one fake archiver in whatever form this platform can actually execute.

    A shebang script with no extension is invisible to shutil.which() on Windows and cannot be started if it
    is found, so the lookup would fall through to whatever real tool the machine has and the test would
    quietly be asserting about that machine instead of about the stub. Hence a .py plus a .bat launcher
    there, and the body itself as the executable everywhere else.
    """
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        script = bin_dir / f"{tool}.py"
        script.write_text(body.split("\n", 1)[1] if body.startswith("#!") else body, encoding="utf-8")
        launcher = bin_dir / f"{tool}.bat"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        stub = bin_dir / tool
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)


def _stub_archive_tools(bin_dir, tools=("7z", "7za", "unrar"), extract_failing=False):
    # unrar is stubbed by default for the same reason 7z is. A .rar prefers unrar when one is on PATH, and a
    # machine that happens to have WinRAR installed would otherwise be what these tests measured.
    for tool in tools:
        body = _STUB_BODIES[tool]
        if extract_failing:
            head, _, rest = body.partition("\n")
            body = f"{head}\n{_STUB_FAILING_EXTRACT}{rest}"
        _write_stub(bin_dir, tool, body)


def _scratch(case, prefix):
    """A temporary directory removed when the test ends, for a service that writes wherever it is pointed.

    The spelling used throughout this module was Path('/tmp'), which on Windows is not an absolute path at all -
    it resolves against whatever drive is current - so the suite created C:\\tmp, appended a log into it, and
    handed ArtworkService a cache directory whose contents that class deletes. Outside this repository, on a
    machine that never agreed to it.
    """
    root = Path(tempfile.mkdtemp(prefix=prefix))
    case.addCleanup(shutil.rmtree, root, ignore_errors=True)
    return root


def _steam(case, *args, **kwargs):
    """A SteamService whose log is a temporary file, because AppLogger.__init__ creates the directory it is handed."""
    return SteamService(AppLogger(_scratch(case, "organizer-steam-") / "steam-test.log"), *args, **kwargs)


def _artwork(case, *args, **kwargs):
    """An ArtworkService over a temporary cache - the same reason as _steam, with more at stake.

    Its __init__ mkdirs the cache directory and then deletes from it: every *.jpg whose stem is a number or
    ends in _steam/_grid, every non-portrait *_steam_v2.jpg over 1 KB, and - through _prune_expired_cache -
    every file in the tree older than max_age_days, followed by rmdir on whatever it emptied. Handed a fixed
    path on a real machine that is a deletion, not a fixture.
    """
    # Imported here rather than at the top because every call site used to import it locally, which is how
    # this module's import list has stayed to what it uses at module scope.
    from services.artwork_service import ArtworkService

    return ArtworkService(_scratch(case, "organizer-artwork-"), AppLogger(_scratch(case, "organizer-artwork-log-") / "artwork.log"), *args, **kwargs)


class _FakeProc:
    """A finished subprocess: 7z died, here is its exit code and the bytes it printed on the way out.

    The output goes through a real pipe rather than a list because _run_tool() reads the child with
    os.read() on stdout.fileno() to pick its progress lines out of the stream. A stand-in that only had the
    lines would leave the reader with nothing to parse, the failure detail would come back empty, and the
    code under test would never see the 'Break signaled' it is supposed to recognise.
    """

    def __init__(self, returncode, stdout=b""):
        self.returncode = returncode
        self.args = []
        self.stderr = None
        read_fd, write_fd = os.pipe()
        if stdout:
            os.write(write_fd, stdout)
        os.close(write_fd)  # closed so the reader's next read returns EOF rather than blocking
        self.stdout = os.fdopen(read_fd, "rb")

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def communicate(self, *args, **kwargs):
        return (self.stdout.read(), None)

    def kill(self):
        pass

    def terminate(self):
        pass


class ToolCallSpy:
    """Record every archive-tool command line, and optionally fake one of them.

    The argv is the only place the conversion's real settings are visible - the password it was handed, the
    compression level it chose, the lock marker it was told to leave out - so the tests read them off the
    calls rather than off the log, which only carries the consequences. `intercept` receives the argv, the
    Popen kwargs and the real Popen; anything it returns stands in for that one call and everything else
    really runs, which is what lets a build be faked while its extraction still produces something real.
    """

    def __init__(self, intercept=None):
        self.calls = []
        self.intercept = intercept
        self._real = subprocess.Popen

    def __enter__(self):
        def spy(argv, *args, **kwargs):
            self.calls.append(list(argv))
            if self.intercept is not None:
                replacement = self.intercept(list(argv), kwargs, self._real)
                if replacement is not None:
                    return replacement
            return self._real(argv, *args, **kwargs)

        subprocess.Popen = spy
        return self

    def __exit__(self, *exc):
        subprocess.Popen = self._real
        return False

    def argv_containing(self, needle):
        """The recorded command lines that carry `needle`, for the common 'was -p passed?' assertion."""
        return [call for call in self.calls if any(needle in part for part in call)]

    def commands(self, subcommand):
        """The argv of every call that ran `subcommand`, e.g. every extract."""
        return [call for call in self.calls if len(call) > 1 and call[1] == subcommand]


@pytest.mark.notkinter
class TestServices(unittest.TestCase):
    def test_mock_discovery_and_steam(self):
        with TemporaryDirectory() as d:
            log = AppLogger(Path(d) / "x.log")
            result = ArchiveService(log, mock=True).discover(Path(d), JobContext("X"))
            self.assertEqual(len(result.archives), 4)
            s = SteamService(log, mock=True).lookup("Alpha Forge v 0 8.zip")
            self.assertEqual(s.appid, "100001")

    def test_discovered_archive_keeps_readable_normalized_title(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            archive = root / "Supercar Collection Simulator Racing Series 20260916.zip"
            archive.write_text("a")
            result = ArchiveService(AppLogger(root / "x.log")).discover(root)
            self.assertEqual(result.archives[0].normalized_title, "Supercar Collection Simulator Racing Series 20260916")
            self.assertEqual(result.archives[0].identity_key, "supercarcollectionsimulatorracingseries20260916")

    def test_new_only_skips_organized_archives(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            fresh = root / "Fresh.zip"
            managed = root / "Simulation" / "Game"
            managed.mkdir(parents=True)
            old = managed / "Game.zip"
            fresh.write_text("a")
            old.write_text("b")
            (managed / "Open Steam Page in Chrome.desktop").write_text("link")
            result = ArchiveService(AppLogger(root / "x.log")).discover(root, new_only=True)
            self.assertEqual([archive.path for archive in result.archives], [fresh])

    def test_unlock_option_preserves_plain_zip(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            archive = root / "Game.zip"
            import zipfile

            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("game.txt", "ok")
            ArchiveService(AppLogger(root / "x.log")).discover(root, unlock_zip=True)
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(z.read("game.txt"), b"ok")

    def test_unlock_option_really_unlocks_a_password_protected_zip(self):
        # The plain-zip case above passes whether or not unlocking works at all, so nothing checked the case
        # the feature exists for. `test_unlock_option_preserves_plain_zip` decompresses nothing: it reads one
        # entry of an archive that was never encrypted.
        #
        # The failure was the shape of the code rather than the choice of library. `_remove_zip_password`
        # rebuilt the archive into a temp file and then called os.replace(temp_name, path) from *inside* the
        # `with zipfile.ZipFile(path) as source:` block - so the source handle was still open. CPython opens a
        # file without FILE_SHARE_DELETE, so on Windows replacing a file it still holds raises
        # PermissionError [WinError 5]. Verified directly on this host: the same os.replace succeeds once the
        # handle is closed.
        #
        # The broad `except Exception` then swallowed it and returned False, so on the primary platform the
        # routine decompressed and rewrote the entire archive and threw the result away, on every scan and for
        # every encrypted zip. And because it returns False, _source_is_intact goes on to run `7z t` with no
        # -p, which a valid encrypted zip fails - so the user was told the archive had failed an integrity test
        # and been left unchanged, which is the opposite of what happened.
        from services.extract_service import ExtractService

        tool = ExtractService.find_tool()[0]
        if not tool:
            self.fail("7-Zip is required to build an encrypted fixture zip and was not found")
        import zipfile

        with TemporaryDirectory() as d:
            root = Path(d)
            payload = root / "payload" / "Game Folder"
            payload.mkdir(parents=True)
            (payload / "main.exe").write_bytes(b"binary" * 400)
            archive = root / "Game.zip"
            built = subprocess.run([tool, "a", "-tzip", "-p123", "-bso0", "-bsp0", str(archive), str(payload.parent)], stdin=subprocess.DEVNULL, capture_output=True)
            self.assertEqual(built.returncode, 0, f"could not build the encrypted fixture: {built.stderr!r}")
            with zipfile.ZipFile(archive) as source:
                self.assertTrue(any(i.flag_bits & 0x1 for i in source.infolist() if not i.is_dir()), "the fixture is not encrypted, so this test proves nothing")
            service = ArchiveService(AppLogger(root / "x.log"))
            self.assertTrue(service._remove_zip_password(archive), "a password-protected zip was not unlocked on this platform")
            with zipfile.ZipFile(archive) as source:
                entries = [i for i in source.infolist() if not i.is_dir()]
                self.assertFalse(any(i.flag_bits & 0x1 for i in entries), "the archive is still flagged as encrypted after unlocking")
                # Readable with no password at all is the property that matters: everything downstream, from
                # 7z t through the extraction, assumes it.
                for entry in entries:
                    source.read(entry)
            self.assertEqual([p.name for p in root.glob(".organizer-*")], [], "unlocking left a temp archive behind in the game folder")

    def test_a_plain_zip_is_left_completely_alone_by_the_unlock_pass(self):
        # The other direction: a zip with no password must not be rewritten at all. Rebuilding it would
        # recompress every entry and lose the original modification time, for no reason.
        import zipfile

        with TemporaryDirectory() as d:
            root = Path(d)
            archive = root / "Plain.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("game.txt", "ok")
            before = archive.stat().st_mtime_ns
            self.assertFalse(ArchiveService(AppLogger(root / "x.log"))._remove_zip_password(archive))
            self.assertEqual(archive.stat().st_mtime_ns, before, "an unencrypted zip was rewritten anyway")

    def test_an_encrypted_zip_is_reported_as_locked_under_preview_only(self):
        """Precondition: unlock_zip=True with preview_only=False rewrites the archive."""
        import subprocess, zipfile
        from services.extract_service import ExtractService

        tool = ExtractService.find_tool()[0]
        if not tool:
            self.fail("7-Zip is required to build an encrypted fixture zip and was not found")
        with TemporaryDirectory() as d:
            root = Path(d)
            payload = root / "payload" / "Game Folder"
            payload.mkdir(parents=True)
            (payload / "main.exe").write_bytes(b"binary" * 400)
            archive = root / "Game.zip"
            built = subprocess.run([tool, "a", "-tzip", "-p123", "-bso0", "-bsp0", str(archive), str(payload.parent)], stdin=subprocess.DEVNULL, capture_output=True)
            self.assertEqual(built.returncode, 0, f"could not build the encrypted fixture: {built.stderr!r}")
            with zipfile.ZipFile(archive) as source:
                self.assertTrue(any(i.flag_bits & 0x1 for i in source.infolist() if not i.is_dir()), "the fixture is not encrypted, so this test proves nothing")
            ArchiveService(AppLogger(root / "unlock.log")).discover(root, unlock_zip=True, preview_only=False)
            with zipfile.ZipFile(archive) as source:
                self.assertFalse(any(i.flag_bits & 0x1 for i in source.infolist() if not i.is_dir()), "the archive is still flagged as encrypted after unlocking")
        with TemporaryDirectory() as d:
            root = Path(d)
            payload = root / "payload" / "Game Folder"
            payload.mkdir(parents=True)
            (payload / "main.exe").write_bytes(b"binary" * 400)
            archive = root / "Game.zip"
            built = subprocess.run([tool, "a", "-tzip", "-p123", "-bso0", "-bsp0", str(archive), str(payload.parent)], stdin=subprocess.DEVNULL, capture_output=True)
            self.assertEqual(built.returncode, 0, f"could not build the encrypted fixture: {built.stderr!r}")
            with zipfile.ZipFile(archive) as source:
                self.assertTrue(any(i.flag_bits & 0x1 for i in source.infolist() if not i.is_dir()), "the fixture is not encrypted, so this test proves nothing")
            before_bytes = archive.read_bytes()
            before_mtime = archive.stat().st_mtime_ns
            result = ArchiveService(AppLogger(root / "preview.log")).discover(root, preview_only=True)
            self.assertTrue(any("cannot be inspected in Preview Only" in e for e in result.errors), f"the encrypted zip was not reported as locked under preview: {result.errors}")
            self.assertEqual(archive.read_bytes(), before_bytes, "the encrypted zip was rewritten under Preview Only")
            self.assertEqual(archive.stat().st_mtime_ns, before_mtime, "the encrypted zip mtime changed under Preview Only")

    def test_preview_only_audit_counts_would_refresh_not_refreshed(self):
        """Under Preview Only the audit reports what a real scan would do without counting it as done."""
        import json
        from unittest.mock import Mock
        from core.logger import AppLogger
        from core.models import ArtworkResult
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            library = root / "Games"
            game = library / "Puzzle" / "Sintopia - 1 Jan, 2026"
            game.mkdir(parents=True)
            (game / ".game-info.json").write_text(json.dumps({"appid": "1234", "name": "Sintopia"}), encoding="utf-8")
            organizer = Mock()
            artwork = type("Artwork", (), {"download_assets": lambda *a, **k: ArtworkResult()})()
            summary = LibraryService(AppLogger(root / "audit.log")).audit(library, artwork, organizer, preview_only=True)
            self.assertGreaterEqual(summary["checked"], 1, "the folder with an AppID was not counted as checked")
            self.assertEqual(summary["refreshed"], 0, "a preview run reported refreshed when it wrote nothing")
            self.assertGreaterEqual(summary["would_refresh"], 1, "a folder with no art was not counted as would_refresh")

    def test_legacy_steam_links_are_replaced_in_existing_game_folders(self):
        # A folder organized by an older release keeps its old link files unless something rewrites them. The
        # library audit pass is what does that: it calls write_steam_links for every game folder, and that
        # normalizes the folder down to the single portable .html shortcut.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Adventure" / "Old Game - 2020-01-02"
            game.mkdir(parents=True)
            (game / ".game-info.json").write_text('{"appid":"777","name":"Old Game"}')
            (game / "Open Steam Page (Steam Deck).desktop").write_text("[Desktop Entry]\nURL=https://store.steampowered.com/app/777/\n")
            (game / "Open Steam Page (Windows).url").write_text("[InternetShortcut]\nURL=https://store.steampowered.com/app/777/\n")
            logger = AppLogger(root / "log.log")
            organizer = OrganizerService(logger)
            artwork = type("Artwork", (), {"download_assets": lambda *a, **k: ArtworkResult()})()
            LibraryService(logger).audit(root, artwork, organizer)
            self.assertFalse((game / "Open Steam Page (Steam Deck).desktop").exists(), "legacy desktop link survived")
            self.assertFalse((game / "Open Steam Page (Windows).url").exists(), "legacy windows link survived")
            replacement = game / "Open Steam Page.html"
            self.assertTrue(replacement.exists(), "portable link was not written")
            self.assertIn("app/777", replacement.read_text(encoding="utf-8"))
            leftovers = [p.name for p in game.iterdir() if p.suffix.lower() in (".url", ".desktop")]
            self.assertEqual(leftovers, [], "old shortcut files remain beside the new one")
            # Running it again must not duplicate or churn anything.
            LibraryService(logger).audit(root, artwork, organizer)
            self.assertEqual([p.name for p in game.iterdir() if p.suffix.lower() == ".html"], ["Open Steam Page.html"])

    def test_organizer_category_move_collision_safe(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            src = root / "Game.zip"
            src.write_text("a")
            existing = root / "artwork.jpg"
            existing.write_text("cover")
            (root / "Simulation").mkdir()
            (root / "Simulation" / "Game - 2020-01-02").write_text("occupied")
            archive = GameArchive(src, "Game", "Game", "game", ".zip")
            archive.decision.accepted = True
            archive.decision.category = "Simulation"
            archive.steam = SteamMatch(found=True, appid="12345", name="Game", release_date="2 Jan, 2020")
            archive.artwork = ArtworkResult(status="cached", path=existing, source="test", assets={"header_image": existing})
            target = OrganizerService(AppLogger(root / "log.log")).move(archive, root)
            self.assertEqual(target.name, "Game.zip")
            self.assertEqual(target.parent.name, "Game - 2020-01-02 (2)")
            self.assertTrue(target.exists())
            self.assertTrue((target.parent / "Game_grid.jpg").exists())
            self.assertTrue((target.parent / "Game_header_image.jpg").exists())
            self.assertFalse(src.exists())
            # One portable link, not a Linux .desktop plus a Windows .url. A .desktop only launches on Linux
            # desktops and a .url only on Windows, so the old pair left one dead file on every platform.
            link = target.parent / "Open Steam Page.html"
            self.assertTrue(link.exists())
            self.assertIn("app/12345", link.read_text(encoding="utf-8"))
            self.assertFalse((target.parent / "Open Steam Page (Steam Deck).desktop").exists())
            self.assertFalse((target.parent / "Open Steam Page (Windows).url").exists())
            link_files = [p.name for p in target.parent.iterdir() if p.suffix.lower() in (".html", ".url", ".desktop")]
            self.assertEqual(link_files, ["Open Steam Page.html"], "exactly one link file per game folder")

    def test_organizer_canonicalizes_factory_category(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            source = root / "Game.zip"
            source.write_text("a")
            item = GameArchive(source, "Game", "Game", "game", ".zip")
            item.decision.accepted = True
            item.decision.category = "Factory"
            item.steam = SteamMatch(found=True, appid="123", name="Game", release_date="2 Jan, 2020")
            target = OrganizerService(AppLogger(root / "log.log")).move(item, root)
            self.assertEqual(target.parent.parent.name, "Automation")

    def test_controller_organize_moves_newest_and_archives_oldest(self):
        from threading import Event
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from services.rollback_service import RollbackService

        with TemporaryDirectory() as d:
            root = Path(d)
            old = root / "Quantum Quest 1.0.zip"
            new = root / "Quantum Quest 1.1.rar"
            old.write_text("old")
            new.write_text("new")
            logger = AppLogger(root / "x.log")
            organizer = OrganizerService(logger)
            jobs = JobManager()
            services = type("Services", (), {"organizer": organizer, "rollback": RollbackService(root, logger)})()
            controller = AppController(StateStore(), EventBus(), logger, services, jobs)
            finished = Event()
            result = []
            items = []
            for path, version in ((old, (1, 0)), (new, (1, 1))):
                item = GameArchive(path, "Quantum Quest", "Quantum Quest", "quantumquest", path.suffix, version)
                item.decision.accepted = True
                item.decision.category = "Factory"
                item.steam = SteamMatch(found=True, appid="123", name="Quantum Quest", release_date="2 Jan, 2020")
                items.append(item)
            controller.organize(items, root, lambda moved: (result.extend(moved), finished.set()))
            self.assertTrue(finished.wait(5))
            jobs.shutdown()
            self.assertTrue((root / "Automation" / "Quantum Quest - 2020-01-02" / "Quantum Quest 1.1.rar").exists())
            self.assertTrue((root / "Archive" / "Quantum Quest 1.0.zip").exists())

    def test_organize_skips_queue_entries_whose_file_is_gone(self):
        # Pressing Organize repeatedly used to loop forever. The queue is a snapshot from scan time; once an
        # earlier pass had archived one of those files, moving it raised FileNotFoundError, which aborted the
        # run and rolled back every game before it - so the next press hit the same missing path again. A file
        # that is no longer there is not this run's work and must not stop the run.
        from threading import Event
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from services.rollback_service import RollbackService

        with TemporaryDirectory() as d:
            root = Path(d)
            live = root / "Game 1.1.rar"
            live.write_text("new")
            vanished = root / "Game 1.0.zip"  # never created: an entry left over from an earlier queue
            logger = AppLogger(root / "x.log")
            organizer = OrganizerService(logger)
            jobs = JobManager()
            services = type("Services", (), {"organizer": organizer, "rollback": RollbackService(root, logger), "catalog": type("Catalog", (), {"generate": lambda *a, **k: None})()})()
            bus = EventBus()
            controller = AppController(StateStore(), bus, logger, services, jobs)
            failures = []
            bus.subscribe("operation_failed", lambda event: failures.append(event.payload))
            items = []
            for path in (live, vanished):
                item = GameArchive(path, "Game", "Game", "game", path.suffix, (1, 1) if path is live else (1, 0))
                item.decision.accepted = True
                item.decision.category = "Factory"
                item.steam = SteamMatch(found=True, appid="123", name="Game", release_date="2 Jan, 2020")
                items.append(item)
            finished = Event()
            result = []
            controller.organize(items, root, lambda moved: (result.extend(moved), finished.set()))
            self.assertTrue(finished.wait(5), "the organize run never finished")
            jobs.shutdown()
            self.assertEqual(failures, [], "a vanished file aborted the run instead of being skipped")
            self.assertTrue((root / "Automation" / "Game - 2020-01-02" / "Game 1.1.rar").exists(), "the games that were actually present were not organized")

    def test_the_organize_run_leaves_no_processing_folder_behind(self):
        # The run is what knows when staging is over, so this is the check that the scratch folder does not
        # outlive it - it is created under the library root, which is the user's folder, not the app's.
        from threading import Event
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from services.rollback_service import RollbackService

        with TemporaryDirectory() as d:
            root = Path(d)
            source = root / "Game 1.0.zip"
            source.write_text("new")
            (root / "Processing").mkdir()
            logger = AppLogger(root / "x.log")
            jobs = JobManager()
            services = type("Services", (), {"organizer": OrganizerService(logger), "rollback": RollbackService(root, logger), "catalog": type("Catalog", (), {"generate": lambda *a, **k: None})()})()
            controller = AppController(StateStore(), EventBus(), logger, services, jobs)
            item = GameArchive(source, "Game", "Game", "game", ".zip")
            item.decision.accepted = True
            item.decision.category = "Factory"
            item.steam = SteamMatch(found=True, appid="123", name="Game", release_date="2 Jan, 2020")
            finished = Event()
            controller.organize([item], root, lambda moved: finished.set())
            self.assertTrue(finished.wait(10), "the organize run never finished")
            jobs.shutdown()
            self.assertFalse((root / "Processing").exists(), "the Processing folder was left behind by the run")

    def test_organizing_a_second_copy_never_deletes_the_game_folder(self):
        # This one lost data. Organising a fresh copy of a game that is already organised moves the archive
        # that was sitting in the game folder out to Archive/, and the tidy-up step then treated the emptied
        # folder as a leftover download folder and deleted it - taking the artwork, the metadata and anything
        # the player had put there, such as a save file, and reporting the run as a success. Nothing that was
        # already organized may be removed by a later run.
        from threading import Event
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from services.rollback_service import RollbackService

        with TemporaryDirectory() as d:
            root = Path(d) / "Games"
            game = root / "RPG" / "Fell & Sell - 2019-11-13"
            game.mkdir(parents=True)
            (game / "Fell & Sell.zip").write_text("old copy")
            (game / ".game-info.json").write_text('{"appid":"261650","name":"Fell & Sell"}')
            (game / "Open Steam Page.html").write_text("<html>link</html>")
            (game / "Fell & Sell_grid.jpg").write_bytes(b"\xff\xd8\xff\xdb" + b"0" * 200)
            (game / "user-save.dat").write_text("MY SAVEGAME")
            inbox = root / "Incoming"
            inbox.mkdir()
            fresh = inbox / "Fell & Sell.zip"
            fresh.write_text("new copy")
            logger = AppLogger(Path(d) / "x.log")
            jobs = JobManager()
            services = type("Services", (), {"organizer": OrganizerService(logger, convert_archives=False), "rollback": RollbackService(Path(d), logger), "catalog": type("Catalog", (), {"generate": lambda *a, **k: None})()})()
            bus = EventBus()
            controller = AppController(StateStore(), bus, logger, services, jobs)
            failures = []
            bus.subscribe("operation_failed", lambda event: failures.append(event.payload))
            item = GameArchive(fresh, "Fell & Sell", "Fell & Sell", "fellsell", ".zip")
            item.decision.accepted = True
            item.decision.category = "RPG"
            item.steam = SteamMatch(found=True, appid="261650", name="Fell & Sell", release_date="13 Nov, 2019")
            done = Event()
            controller.organize([item], root, lambda moved: done.set())
            self.assertTrue(done.wait(10), "the organize run never finished")
            jobs.shutdown()
            self.assertEqual(failures, [])
            for name in ("user-save.dat", "Fell & Sell_grid.jpg", ".game-info.json", "Open Steam Page.html"):
                self.assertTrue((game / name).is_file(), f"{name} was deleted from an already-organized game folder")
            self.assertTrue((root / "Archive" / "Fell & Sell.zip").is_file(), "the previous copy was not filed under Archive")

    def test_the_organize_run_converts_the_smallest_archive_first(self):
        # A conversion is by far the longest thing a run does, and it lands on the primary copy of each game.
        # Doing the small ones first banks the quick wins early and gets a corrupt or unsupported archive
        # failing while there is still run left to react to it, instead of as the last thing that happens.
        from threading import Event
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from services.rollback_service import RollbackService
        from services.catalog_service import CatalogService
        import zipfile as _zipfile

        class _Recording(OrganizerService):
            def __init__(self, logger, order, **kw):
                super().__init__(logger, convert_archives=False, **kw)
                self.order = order

            def move(self, archive, destination, **kw):
                self.order.append((archive.steam.name, archive.path.stat().st_size))
                return super().move(archive, destination, **kw)

        with TemporaryDirectory() as d:
            work = Path(d)
            root = work / "Games"
            inbox = root / "Incoming"
            inbox.mkdir(parents=True)
            order = []
            logger = AppLogger(work / "x.log")
            jobs = JobManager()
            organizer = _Recording(logger, order)
            services = type("Services", (), {"organizer": organizer, "rollback": RollbackService(work, logger), "catalog": CatalogService(logger)})()
            controller = AppController(StateStore(), EventBus(), logger, services, jobs)
            archives = []
            for name, payload in (("Alpha Game", 900), ("Beta Game", 20), ("Gamma Game", 400)):
                path = inbox / f"{name}.zip"
                with _zipfile.ZipFile(path, "w") as zf:
                    zf.writestr(f"{name}/data.bin", b"a" * payload)
                from utils.filename_utils import normalize_name

                item = GameArchive(path, name, name, identity_key(normalize_name(path.name)), ".zip")
                item.decision.accepted = True
                item.decision.category = "Idle"
                item.steam = SteamMatch(found=True, appid="1", name=name, release_date="1 Jan, 2020")
                archives.append(item)
            done = Event()
            controller.organize(archives, root, lambda moved: done.set())
            self.assertTrue(done.wait(20), "the organize run never finished")
            jobs.shutdown()
            self.assertEqual([name for name, _ in order], ["Beta Game", "Gamma Game", "Alpha Game"], "the run did not convert the smallest archive first")
            self.assertEqual([size for _, size in order], sorted(size for _, size in order))

    def test_the_repair_pass_reports_how_many_archives_are_left(self):
        # "3 converted" on its own cannot say whether three of twenty are done or three of three hundred. The
        # count was taken while walking folders, so it moved every time a conversion rewrote the folder it was
        # reading from; it is now fixed before the first rebuild, and every event carries it.
        events = []
        with TemporaryDirectory() as d:
            root = Path(d)
            for name in ("Small Game", "Medium Game", "Big Game"):
                game = root / "Idle" / name
                game.mkdir(parents=True)
                (game / ".game-info.json").write_text('{"appid":"1","name":"%s"}' % name)
                (game / "Open Steam Page.html").write_text("<html></html>")
                with zipfile.ZipFile(game / f"{name}.v1.zip", "w") as zf:
                    zf.writestr(f"{name}/data.bin", b"a" * 400)
            converted = LibraryService(AppLogger(root / "log.log")).convert_pending_archives(root, OrganizerService(AppLogger(root / "log.log")), JobContext("T"), on_progress=events.append)
            self.assertEqual(converted, 3)
        plan = [event for event in events if event.get("stage") == "repair_plan"]
        starts = [event for event in events if event.get("stage") == "repair_start"]
        finished = [event for event in events if event.get("stage") == "converted"]
        self.assertEqual(len(plan), 1, "the pass never announced how much work it had")
        self.assertEqual(plan[0]["total"], 3)
        self.assertEqual([event["index"] for event in starts], [1, 2, 3])
        self.assertEqual([event["index"] for event in finished], [1, 2, 3], "a finished conversion did not report which one it was")

    def test_archive_versions_share_one_game_folder(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            first = root / "Game 1.0.zip"
            second = root / "Game 1.1.zip"
            first.write_text("a")
            second.write_text("b")
            service = OrganizerService(AppLogger(root / "log.log"))
            for archive in (first, second):
                item = GameArchive(archive, "Game", "Game", "game", ".zip")
                item.decision.accepted = True
                item.decision.category = "Simulation"
                item.steam = SteamMatch(found=True, appid="12345", name="Game", release_date="2 Jan, 2020")
                service.move(item, root)
            game_dir = root / "Simulation" / "Game - 2020-01-02"
            self.assertEqual(sorted(path.name for path in game_dir.glob("*.zip")), ["Game 1.0.zip", "Game 1.1.zip"])

    def test_organizer_never_deletes_unrelated_folders(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            source = root / "Game.zip"
            source.write_text("a")
            old = root / "Old Category" / "Old Game"
            old.mkdir(parents=True)
            (old / "notes.txt").write_text("keep")
            item = GameArchive(source, "Game", "Game", "game", ".zip")
            item.decision.accepted = True
            item.decision.category = "Simulation"
            item.steam = SteamMatch(found=True, appid="123", name="Game", release_date="2 Jan, 2020")
            OrganizerService(AppLogger(root / "log.log")).move(item, root)
            self.assertTrue(old.is_dir())
            self.assertTrue((old / "notes.txt").exists())

    def test_organizer_removes_only_artwork_link_source_folder(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            old = root / "Old Category" / "Old Game"
            old.mkdir(parents=True)
            source = old / "Game.zip"
            source.write_text("a")
            (old / "Game_grid.jpg").write_text("cover")
            (old / "Open Steam Page.desktop").write_text("link")
            item = GameArchive(source, "Game", "Game", "game", ".zip")
            item.decision.accepted = True
            item.decision.category = "Simulation"
            item.steam = SteamMatch(found=True, appid="123", name="Game", release_date="2 Jan, 2020")
            OrganizerService(AppLogger(root / "log.log")).move(item, root)
            self.assertFalse(old.exists())
            self.assertTrue((root / "Old Category").exists())

    def test_organizer_keeps_a_leftover_folder_holding_a_file_it_did_not_write(self):
        # This asserted the opposite, and stated the data loss as a rule: "any remaining non-archive leftovers
        # (extracted data, notes, etc.) are safe to clean up; only an actual archive file blocks removal".
        # Twenty lines above, the neighbouring test asserts that a folder holding notes.txt survives - so the
        # suite held two tests contradicting each other over one question, differing only in what the file
        # happened to be called, and a save file was the one that lost. Only the pictures and the shortcut this
        # app writes are removable. A file it did not write belongs to the player, whatever it is called.
        with TemporaryDirectory() as d:
            root = Path(d)
            old = root / "Old Category" / "Old Game"
            old.mkdir(parents=True)
            source = old / "Game.zip"
            source.write_text("a")
            (old / "save.dat").write_text("keep")
            (old / "Open Steam Page.desktop").write_text("link")
            item = GameArchive(source, "Game", "Game", "game", ".zip")
            item.decision.accepted = True
            item.decision.category = "Simulation"
            item.steam = SteamMatch(found=True, appid="123", name="Game", release_date="2 Jan, 2020")
            OrganizerService(AppLogger(root / "log.log")).move(item, root)
            self.assertTrue(old.is_dir(), "a folder holding a save file was removed")
            self.assertTrue((old / "save.dat").exists(), "the save file was deleted")

    def test_organizer_keeps_folder_if_another_archive_remains_inside(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            old = root / "Old Category" / "Old Game"
            old.mkdir(parents=True)
            source = old / "Game.zip"
            source.write_text("a")
            other = old / "Other.rar"
            other.write_text("b")
            item = GameArchive(source, "Game", "Game", "game", ".zip")
            item.decision.accepted = True
            item.decision.category = "Simulation"
            item.steam = SteamMatch(found=True, appid="123", name="Game", release_date="2 Jan, 2020")
            OrganizerService(AppLogger(root / "log.log")).move(item, root)
            self.assertTrue(old.is_dir())
            self.assertTrue(other.exists())

    def test_finds_generic_game_content_folder(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Cleaning.Up.The.Puzzle.Gallery.v1.4.2" / "game"
            game.mkdir(parents=True)
            (game / "main.exe").write_text("x")
            self.assertEqual(OrganizerService(AppLogger(root / "log.log"))._find_generic_content_folder(root), game)

    def test_no_generic_content_folder_for_installer_or_iso_layouts(self):
        organizer = OrganizerService(AppLogger(_scratch(self, "organizer-unused-") / "unused.log"))
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "setup.exe").write_text("x")
            self.assertIsNone(organizer._find_generic_content_folder(root))
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "image.iso").write_text("x")
            self.assertIsNone(organizer._find_generic_content_folder(root))

    def test_repack_leaves_zip_untouched_without_rar_tools(self):
        # "No archive tools" is a property of the machine, and nearly every machine this runs on has 7-Zip
        # installed - including at C:\Program Files\7-Zip, which the finder checks after PATH and which no
        # amount of clearing PATH can hide. So rather than skipping on every real PC, the finder is made to
        # report nothing around the call, which is the one thing the organizer consults before giving up.
        with TemporaryDirectory() as d:
            root = Path(d)
            source = root / "Game.zip"
            source.write_text("a")
            item = GameArchive(source, "Game", "Game", "game", ".zip")
            item.decision.accepted = True
            item.decision.category = "Simulation"
            item.steam = SteamMatch(found=True, appid="123", name="Game", release_date="2 Jan, 2020")
            log_path = root / "log.log"
            with patch("services.organizer_service.ExtractService.find_tool", return_value=(None, "no 7z here")):
                target = OrganizerService(AppLogger(log_path)).move(item, root)
            self.assertEqual(target.suffix, ".zip")
            self.assertTrue(target.exists())
            # The skip must be diagnosable from the log, not a silent no-op (this is what made a prior
            # organize run look like "compression didn't happen" with zero explanation in the log).
            self.assertIn("ARCHIVE_TOOLS_MISSING", log_path.read_text())

    def test_repack_leaves_already_rar_untouched_without_rar_tools(self):
        # An already-.rar archive should still be left alone (not corrupted/renamed in place) when neither
        # rar/unrar nor 7z/7za are available, and must log the same diagnosable reason.
        with TemporaryDirectory() as d:
            root = Path(d)
            source = root / "Game.rar"
            source.write_text("a")
            item = GameArchive(source, "Game", "Game", "game", ".rar")
            item.decision.accepted = True
            item.decision.category = "Simulation"
            item.steam = SteamMatch(found=True, appid="123", name="Game", release_date="2 Jan, 2020")
            log_path = root / "log.log"
            with patch("services.organizer_service.ExtractService.find_tool", return_value=(None, "no 7z here")):
                target = OrganizerService(AppLogger(log_path)).move(item, root)
            self.assertEqual(target.suffix, ".rar")
            self.assertTrue(target.exists())
            self.assertIn("ARCHIVE_TOOLS_MISSING", log_path.read_text())

    def test_repack_rebuilds_already_rar_when_content_folder_renamed(self):
        # Exercises the full extract -> rename "game" folder -> rebuild pipeline using lightweight fake
        # rar/unrar CLI stubs (a tar-backed fake format), so the rename-inside-an-already-.rar path is
        # verified even in environments without the real proprietary rar/unrar tools installed.
        import os as os_module, tarfile

        with TemporaryDirectory() as d:
            root = Path(d)
            bin_dir = root / "fakebin"
            bin_dir.mkdir()
            _write_stub(bin_dir, "rar", "#!/usr/bin/env python3\nimport sys,tarfile\narchive=sys.argv[-2]\nwith tarfile.open(archive,'w') as tar: tar.add('.',recursive=True)\n")
            # unrar here is the pre-existing extract stub; the packing tool is stubbed too, so the result is
            # the same on a host with real 7z installed as on one without it.
            _write_stub(bin_dir, "unrar", _STUB_BODIES["unrar"])
            _stub_archive_tools(bin_dir, tools=("7z", "7za"))
            payload = root / "_payload" / "Cleaning.Up.The.Puzzle.Gallery.v1.4.2" / "game"
            payload.mkdir(parents=True)
            (payload / "main.exe").write_text("binary")
            source = root / "Cleaning.Up.The.Puzzle.Gallery.v1.4.2.rar"
            with tarfile.open(source, "w") as tar:
                tar.add(str(payload.parent), arcname="Cleaning.Up.The.Puzzle.Gallery.v1.4.2")
            item = GameArchive(source, "title", "title", "key", ".rar")
            item.decision.accepted = True
            item.decision.category = "Casual"
            item.steam = SteamMatch(found=True, appid="999", name="Cleaning Up The Puzzle Gallery", release_date="1 Jan, 2024")
            old_path = os_module.environ.get("PATH", "")
            os_module.environ["PATH"] = str(bin_dir) + os_module.pathsep + old_path
            try:
                # The finder answers with a 7z.exe bundled in the app's own runtime/ before
                # PATH, so the stubs these tests exist to exercise are shadowed by the real
                # tool on a machine that has the bundle. Pointing the lookup's root at this
                # temp folder - which holds no runtime/ - is the "nothing but these tools"
                # machine the test describes.
                with patch("services.extract_service.APP_ROOT", root):
                    target = OrganizerService(AppLogger(root / "log.log")).move(item, root)
            finally:
                os_module.environ["PATH"] = old_path
            self.assertEqual(target.suffix, ".7z")
            with tarfile.open(target) as tar:
                names = tar.getnames()
            self.assertTrue(any(name.endswith("Cleaning Up The Puzzle Gallery") for name in names))
            self.assertFalse(any(name.endswith("/game") or name == "game" for name in names))

    def test_repack_falls_back_to_7z_when_only_7z_available(self):
        # Without real rar/unrar, a .zip must still get upgraded to a better-compressed format using the
        # free 7z/7za tool (p7zip), since that's all a PeaZip-only install actually provides.
        import os as os_module, tarfile, zipfile

        with TemporaryDirectory() as d:
            root = Path(d)
            bin_dir = root / "fakebin"
            # Only the packing tool is faked here: the input is a real .zip extracted by the real system
            # unzip, which is exactly the PeaZip-only situation this test describes.
            _stub_archive_tools(bin_dir, tools=("7z", "7za"))
            source = root / "Cleaning.Up.The.Puzzle.Gallery.v1.4.2.zip"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("Cleaning.Up.The.Puzzle.Gallery.v1.4.2/game/main.exe", "binary")
            item = GameArchive(source, "title", "title", "key", ".zip")
            item.decision.accepted = True
            item.decision.category = "Casual"
            item.steam = SteamMatch(found=True, appid="999", name="Cleaning Up The Puzzle Gallery", release_date="1 Jan, 2024")
            old_path = os_module.environ.get("PATH", "")
            os_module.environ["PATH"] = str(bin_dir) + os_module.pathsep + old_path
            try:
                # Same shadowing as the .rar rebuild above: the bundled 7z.exe would win
                # over these stubs, and the test is the PeaZip-only machine, which has no
                # bundle at all - so the lookup's root points at a folder without runtime/.
                with patch("services.extract_service.APP_ROOT", root):
                    target = OrganizerService(AppLogger(root / "log.log")).move(item, root)
            finally:
                os_module.environ["PATH"] = old_path
            self.assertEqual(target.suffix, ".7z")
            with tarfile.open(target) as tar:
                names = tar.getnames()
            self.assertTrue(any(name.endswith("Cleaning Up The Puzzle Gallery") for name in names))
            self.assertFalse(any(name.endswith("/game") or name == "game" for name in names))

    def test_cleanup_leaves_a_repack_folder_that_is_still_live(self):
        # A repack folder carries a lock marker naming its owning process. Deleting one while its owner is
        # still extracting would destroy the run in progress, so cleanup must check the pid and not just the name.
        import os as os_module

        with TemporaryDirectory() as d:
            root = Path(d)
            live = root / ".organizer-repack-live"
            live.mkdir()
            (live / "payload.bin").write_text("x" * 64)
            (live / ".organizer-lock").write_text(f"{os_module.getpid()} {__import__('time').time():.0f}\n")
            dead = root / ".organizer-repack-dead"
            dead.mkdir()
            (dead / "payload.bin").write_text("y" * 64)
            (dead / ".organizer-lock").write_text("999999 1000000000\n")  # pid that cannot exist, long ago
            unmarked = root / ".organizer-repack-old"
            unmarked.mkdir()
            (unmarked / "z.bin").write_text("z")
            old = __import__("time").time() - 7200
            os_module.utime(unmarked, (old, old))
            summary = LibraryService(AppLogger(root / "log.log")).cleanup_leftovers(root)
            self.assertTrue(live.is_dir(), "a repack folder owned by a running process was deleted")
            self.assertTrue((live / "payload.bin").exists())
            self.assertFalse(dead.exists(), "an abandoned repack folder was not reclaimed")
            self.assertFalse(unmarked.exists(), "an old unmarked repack folder was not reclaimed")
            self.assertGreater(summary["bytes_freed"], 0, "reclaimed space was not accounted for")

    def test_repack_extraction_folder_carries_a_lock_marker(self):
        # Without the marker, cleanup can only fall back to age and may delete a live extraction folder.
        import time as time_mod

        with TemporaryDirectory() as d:
            folder = Path(d) / ".organizer-repack-test"
            folder.mkdir()
            OrganizerService._write_lock_marker(folder)
            marker = folder / ".organizer-lock"
            self.assertTrue(marker.is_file(), "no lock marker was written into the extraction folder")
            pid, started = marker.read_text().split()[:2]
            self.assertEqual(int(pid), os.getpid())
            self.assertGreater(float(started), 0)

    def test_repair_pass_passes_the_zip_password_to_the_extractor(self):
        # The library's game zips are password protected and use WinZip AES, which unzip cannot read at all
        # (it exited 81 having written nothing), so the repair pass could never convert them. The password is
        # now handed to 7z on the extract command line. Exercised through convert_pending_archives because
        # that is the path that deals with leftovers inside already-organized folders.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Adventure" / "Locked Game - 2024-01-01"
            game.mkdir(parents=True)
            (game / ".game-info.json").write_text('{"appid":"555","name":"Locked Game"}')
            source = game / "Locked Game v1.zip"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("Locked Game v1/game/main.exe", "binary")
            logger = AppLogger(root / "log.log")
            library = LibraryService(logger)
            organizer = OrganizerService(logger)
            with ToolCallSpy() as spy:
                # The hardcoded "123" zip password now comes from DEFAULT_ZIP_PASSWORD in core.constants.
                converted = library.convert_pending_archives(root, organizer, JobContext("T"), unlocker=None, zip_password=DEFAULT_ZIP_PASSWORD)
            self.assertEqual(converted, 1, "the leftover zip was not converted")
            extract = [c for c in spy.calls if len(c) > 1 and c[1] == "x"]
            self.assertTrue(extract, "no 7z extract call was made")
            self.assertIn("-p123", extract[0], "the zip password was not passed to 7z for extraction")
            self.assertFalse(source.exists(), "the source zip should have been replaced by the 7z")
            self.assertTrue(next(game.glob("*.7z")).exists())

    def test_a_source_that_vanished_before_conversion_is_not_reported_as_a_failure(self):
        # Callers pass a list of candidates collected up front, so an archive can be converted by something
        # else - an Organize run in the same app, or a second repair pass - before this one reaches it. The
        # source is then gone, and stat() used to raise FileNotFoundError that surfaced as a red failure for a
        # conversion that had in fact already succeeded.
        from services.library_service import _RepairArchive

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Adventure" / "Racing Game - 2024-01-01"
            game.mkdir(parents=True)
            (game / ".game-info.json").write_text('{"appid":"888","name":"Racing Game"}')
            source = game / "Racing Game v1.zip"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("Racing Game v1/game/main.exe", "binary")
            library = LibraryService(AppLogger(root / "log.log"))
            candidates = library.pending_candidates(root)
            self.assertEqual(len(candidates), 1, "the candidate snapshot was not taken")
            source.unlink()  # another run converts it first
            _game_dir, path, _size, appid, name = candidates[0]
            events = []
            result = OrganizerService(AppLogger(root / "log.log"))._repack_with_official_name(_RepairArchive(path, appid, name), on_progress=events.append)
            self.assertEqual(result, path, "a resolved archive should be returned untouched")
            self.assertFalse([e for e in events if e.get("stage") == "failed"], f"a resolved archive was reported as failed: {events}")
            self.assertTrue([e for e in events if e.get("stage") == "skipped"], "the archive was not reported as already converted")

    def test_a_build_killed_by_pressure_is_retried_one_level_lower(self):
        # A level 9 build needs ~2.5 GB. When the machine cannot supply it, 7z dies as a bare
        # "Break signaled" and the whole multi-GB extraction is thrown away. The archive must survive:
        # the build is retried at a level that fits rather than reported as a failed conversion.
        attempted = []

        def intercept(argv, kwargs, real_popen):
            # Only the build is faked; extraction must really run so there is something to compress.
            if "-t7z" in argv and "a" in argv[:2]:
                level = next((x for x in argv if x.startswith("-mx=")), "")
                attempted.append(level)
                if level == "-mx=9":
                    return _FakeProc(255, b"\nERROR: Break signaled\n")
            return real_popen(argv, **kwargs)

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Adventure" / "Pressured Game - 2024-01-01"
            game.mkdir(parents=True)
            (game / ".game-info.json").write_text('{"appid":"777","name":"Pressured Game"}')
            source = game / "Pressured Game v1.zip"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("Pressured Game v1/game/main.exe", "binary" * 200)
            logger = AppLogger(root / "log.log")
            library = LibraryService(logger)
            organizer = OrganizerService(logger)
            with ToolCallSpy(intercept):
                converted = library.convert_pending_archives(root, organizer, JobContext("T"), unlocker=None)
            self.assertIn("-mx=9", attempted, "the compressor never attempted level 9")
            self.assertTrue(attempted.index("-mx=8") == 1, "the retry did not step down one level at a time")
            self.assertEqual(converted, 1, "the archive was lost instead of being retried at a lower level")
            self.assertFalse(source.exists(), "the source zip should have been replaced by the 7z")
            self.assertTrue(next(game.glob("*.7z")).exists(), "no rebuilt archive was produced")
            self.assertFalse(list(game.glob(".organizer-temp*")), "a partial build was left behind")

    def test_repair_pass_records_an_outcome_for_every_archive_it_touches(self):
        # Without a ConversionResult on the repair archive, every outcome was discarded, so the Done screen
        # showed these archives as having no conversion result at all.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Strategy" / "Small Game - 2024-02-02"
            game.mkdir(parents=True)
            (game / ".game-info.json").write_text('{"appid":"666","name":"Small Game"}')
            with zipfile.ZipFile(game / "Small Game v1.zip", "w") as zf:
                zf.writestr("Small Game v1/game/x.dat", "y")
            outcomes = []
            library = LibraryService(AppLogger(root / "log.log"))
            organizer = OrganizerService(AppLogger(root / "log.log"))
            library.convert_pending_archives(root, organizer, JobContext("T"), unlocker=None, outcomes=outcomes)
            self.assertEqual(len(outcomes), 1, "no outcome recorded for the repaired archive")
            path, note = outcomes[0]
            self.assertEqual(note.status, "converted")
            self.assertEqual(path.suffix, ".zip", "the outcome should name the original source path")

    def test_repack_extracts_beside_the_archive_not_in_system_tmp(self):
        # Game archives extract to several GB. Using the system temp dir filled the small SteamOS tmpfs and
        # aborted conversions with a bare OSError, leaving the source as .zip/.rar, so extraction must happen
        # on the library volume next to the archive instead.
        import os as os_module, tarfile

        with TemporaryDirectory() as d:
            root = Path(d)
            real_tmp = tempfile.gettempdir()
            holder = Path(tempfile.mkdtemp(dir=real_tmp))
            previous = os_module.environ.get("TMPDIR", "")
            os_module.environ["TMPDIR"] = str(holder)
            try:
                bin_dir = root / "fakebin"
                _stub_archive_tools(bin_dir)
                source = root / "Cleaning.Up.The.Puzzle.Gallery.v1.4.2.rar"
                with tarfile.open(source, "w") as tar:
                    tar.add(str(root), arcname="Cleaning.Up.The.Puzzle.Gallery.v1.4.2")
                item = GameArchive(source, "title", "title", "key", ".rar")
                item.decision.accepted = True
                item.decision.category = "Casual"
                item.steam = SteamMatch(found=True, appid="999", name="Cleaning Up The Puzzle Gallery", release_date="1 Jan, 2024")
                old_path = os_module.environ.get("PATH", "")
                os_module.environ["PATH"] = str(bin_dir) + os_module.pathsep + old_path
                try:
                    target = OrganizerService(AppLogger(root / "log.log")).move(item, root)
                finally:
                    os_module.environ["PATH"] = old_path
                # The conversion succeeded, which is only possible if extraction did not use the tmpfs.
                self.assertEqual(target.suffix, ".7z")
                self.assertEqual(list(holder.iterdir()), [])
            finally:
                os_module.environ["TMPDIR"] = previous
                for child in sorted(holder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                    try:
                        child.unlink() if child.is_file() else child.rmdir()
                    except OSError:
                        pass
                try:
                    holder.rmdir()
                except OSError:
                    pass

    def test_repack_logs_the_reason_when_extraction_fails(self):
        # Extraction failure used to return silently, leaving nothing in the log to explain a .zip that never
        # became a .7z. The extractor, its exit code, and its stderr must all be recorded.
        import os as os_module, tarfile

        with TemporaryDirectory() as d:
            root = Path(d)
            bin_dir = root / "fakebin"
            # Extraction and build fail, but the source passes an integrity test first. A stub that failed
            # every command would also fail `7z t`, and the organizer now refuses an archive that fails its
            # integrity test before it ever reaches extraction - correct behaviour that would leave the
            # extraction failure path untested. The source is a real archive so the integrity test can pass.
            _stub_archive_tools(bin_dir, extract_failing=True)
            source = root / "Broken.Game.rar"
            with zipfile.ZipFile(source, "w") as handle:
                handle.writestr("data.bin", b"payload")
            item = GameArchive(source, "title", "title", "key", ".rar")
            item.decision.accepted = True
            item.decision.category = "Casual"
            item.steam = SteamMatch(found=True, appid="999", name="Broken Game", release_date="1 Jan, 2024")
            log_path = root / "log.log"
            old_path = os_module.environ.get("PATH", "")
            os_module.environ["PATH"] = str(bin_dir) + os_module.pathsep + old_path
            try:
                target = OrganizerService(AppLogger(log_path)).move(item, root)
            finally:
                os_module.environ["PATH"] = old_path
            text = log_path.read_text()
            self.assertIn("ARCHIVE_EXTRACT_FAILED", text)
            self.assertIn("exit=2", text)
            self.assertIn("cannot open archive", text)
            self.assertEqual(target.suffix, ".rar")

    def test_progress_events_carry_stage_file_and_sizes(self):
        # The UI can only show real per-file detail if progress arrives structured rather than as one sentence.
        import os as os_module, tarfile

        with TemporaryDirectory() as d:
            root = Path(d)
            bin_dir = root / "fakebin"
            _stub_archive_tools(bin_dir)
            payload = root / "_payload" / "game"
            payload.mkdir(parents=True)
            (payload / "main.exe").write_text("binary" * 100)
            source = root / "Cleaning.Up.The.Puzzle.Gallery.v1.4.2.rar"
            with tarfile.open(source, "w") as tar:
                tar.add(str(payload.parent), arcname="Cleaning.Up.The.Puzzle.Gallery.v1.4.2")
            item = GameArchive(source, "title", "title", "key", ".rar")
            item.decision.accepted = True
            item.decision.category = "Casual"
            item.steam = SteamMatch(found=True, appid="999", name="Cleaning Up The Puzzle Gallery", release_date="1 Jan, 2024")
            events = []
            old_path = os_module.environ.get("PATH", "")
            os_module.environ["PATH"] = str(bin_dir) + os_module.pathsep + old_path
            try:
                OrganizerService(AppLogger(root / "log.log")).move(item, root, on_progress=events.append)
            finally:
                os_module.environ["PATH"] = old_path
            stages = [event.get("stage") for event in events]
            self.assertIn("extracting", stages)
            self.assertIn("compressing", stages)
            self.assertIn("converted", stages)
            self.assertTrue(all(event.get("file") for event in events))
            extracted = [event for event in events if event.get("stage") == "extracting"][0]
            self.assertGreater(extracted["source_bytes"], 0)
            final = [event for event in events if event.get("stage") == "converted"][0]
            self.assertGreater(final["target_bytes"], 0)

    def test_progress_falls_back_to_a_plain_message(self):
        # A caller still sending a bare sentence must not break the progress UI.
        from ui.organize_view import OrganizeView

        self.assertTrue(hasattr(OrganizeView, "progress_update"))
        from ui.theme import pin_bottom

        self.assertTrue(callable(pin_bottom))

    def test_new_only_scan_repairs_leftover_zip_in_existing_folder(self):
        # Under New Only, discovery hides an archive that already sits beside a Steam link, so a conversion
        # that failed on an earlier run would stay broken forever. The repair pass must still fix it, without
        # the game being re-presented for review.
        import os as os_module, json, zipfile
        from threading import Event
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from services.rollback_service import RollbackService
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            bin_dir = root / "fakebin"
            _stub_archive_tools(bin_dir)
            game = root / "Simulation" / "Retro Arcade Shop Simulator - 2026-01-01"
            game.mkdir(parents=True)
            payload = root / "_p" / "game"
            payload.mkdir(parents=True)
            (payload / "main.exe").write_text("x" * 500)
            leftover = game / "Retro.Arcade.Shop.Simulator.zip"
            with zipfile.ZipFile(leftover, "w") as zip:
                zip.write(payload / "main.exe", "game/main.exe")
            (game / "Open Steam Page (Steam Deck).desktop").write_text("URL=https://store.steampowered.com/app/12345/")
            (game / ".game-info.json").write_text(json.dumps({"appid": "12345", "name": "Retro Arcade Shop Simulator", "release_date": "1 Jan, 2026"}))
            logger = AppLogger(root / "x.log")
            jobs = JobManager()
            services = type("Services", (), {})()
            services.organizer = OrganizerService(logger)
            services.rollback = RollbackService(root, logger)
            services.library = LibraryService(logger)
            services.archive = ArchiveService(logger)
            services.artwork = type("Artwork", (), {"download_assets": lambda *a, **k: ArtworkResult(), "lookup": lambda *a, **k: ArtworkResult()})()
            services.catalog = type("Catalog", (), {"generate": lambda *a, **k: []})()
            controller = AppController(StateStore(), EventBus(), logger, services, jobs)
            finished = Event()
            scanned = []
            old_path = os_module.environ.get("PATH", "")
            os_module.environ["PATH"] = str(bin_dir) + os_module.pathsep + old_path
            try:
                controller.scan(root, lambda result: (scanned.append(result), finished.set()), new_only=True, preview_only=False)
                self.assertTrue(finished.wait(30))
            finally:
                os_module.environ["PATH"] = old_path
                jobs.shutdown()
            # The leftover .zip was converted even though New Only would never show it.
            self.assertFalse(leftover.exists())
            self.assertTrue((game / "Retro.Arcade.Shop.Simulator.7z").exists())
            # And it was NOT re-presented for review, so the queue stays clean.
            self.assertEqual(scanned[0].archives, [])

    def test_scan_progress_reaches_the_sink_without_a_type_error(self):
        # Discovery reports seven positional values. The controller's wrapper took a single argument while
        # discovery called it with seven, so every scan raised TypeError inside its progress callback and the
        # user saw a dead progress display for the whole run. The sink contract is one packed tuple.
        import json as json_module, zipfile as zip_module
        from threading import Event
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from services.rollback_service import RollbackService
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            incoming = root / "Incoming"
            incoming.mkdir(parents=True)
            with zip_module.ZipFile(incoming / "Some Game v1.zip", "w") as archive:
                archive.writestr("game/data.txt", "x")
            logger = AppLogger(root / "x.log")
            jobs = JobManager()
            services = type("Services", (), {})()
            services.organizer = OrganizerService(logger)
            services.rollback = RollbackService(root, logger)
            services.library = LibraryService(logger)
            services.archive = ArchiveService(logger)
            services.artwork = type("Artwork", (), {"download_assets": lambda *a, **k: ArtworkResult(), "lookup": lambda *a, **k: ArtworkResult()})()
            services.catalog = type("Catalog", (), {"generate": lambda *a, **k: []})()
            controller = AppController(StateStore(), EventBus(), logger, services, jobs)
            finished = Event()
            seen = []
            try:
                controller.scan(root, lambda result: finished.set(), progress=lambda event: seen.append(event), preview_only=True)
                self.assertTrue(finished.wait(30))
            finally:
                jobs.shutdown()
            # Every phase announced itself, and discovery telemetry arrived as packed tuples, never splatted.
            stages = [event.get("stage") for event in seen if isinstance(event, dict)]
            for expected in ("cleanup", "cleanup_done", "dedupe_done", "repair", "repair_done", "discover", "discover_done", "audit_done", "catalog_done"):
                self.assertIn(expected, stages, f"{expected} phase never reported itself")
            positional = [event for event in seen if not isinstance(event, dict)]
            self.assertTrue(positional, "discovery progress never reached the sink")
            self.assertEqual(len(positional[0]), 7)

    def test_preview_only_scan_never_converts_leftovers(self):
        # Preview Only promises that no files are moved, so the repair pass must not run under it. Verified
        # through the controller, since that is where the gate lives.
        import json as json_module
        from threading import Event
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from services.rollback_service import RollbackService
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Simulation" / "Game - 2020-01-01"
            game.mkdir(parents=True)
            leftover = game / "Game.zip"
            leftover.write_text("a")
            (game / "Open Steam Page (Steam Deck).desktop").write_text("URL=https://store.steampowered.com/app/12345/")
            (game / ".game-info.json").write_text(json_module.dumps({"appid": "12345", "name": "Game", "release_date": "1 Jan, 2026"}))
            logger = AppLogger(root / "x.log")
            jobs = JobManager()
            organizer = OrganizerService(logger)
            services = type("Services", (), {})()
            services.organizer = organizer
            services.rollback = RollbackService(root, logger)
            services.library = LibraryService(logger)
            services.archive = ArchiveService(logger)
            services.artwork = type("Artwork", (), {"download_assets": lambda *a, **k: ArtworkResult(), "lookup": lambda *a, **k: ArtworkResult()})()
            services.catalog = type("Catalog", (), {"generate": lambda *a, **k: []})()
            controller = AppController(StateStore(), EventBus(), logger, services, jobs)
            finished = Event()
            try:
                controller.scan(root, lambda result: finished.set(), new_only=False, preview_only=True)
                self.assertTrue(finished.wait(30))
            finally:
                jobs.shutdown()
            self.assertTrue(leftover.exists())
            self.assertFalse((game / "Game.7z").exists())

    def test_repair_skips_folders_already_converted_to_7z(self):
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Simulation" / "Game - 2020-01-01"
            game.mkdir(parents=True)
            done = game / "Game.7z"
            done.write_text("a")
            organizer = OrganizerService(AppLogger(root / "x.log"))
            calls = []
            organizer._repack_with_official_name = lambda *a, **k: calls.append(a) or done
            self.assertEqual(LibraryService(AppLogger(root / "x.log")).convert_pending_archives(root, organizer), 0)
            self.assertEqual(calls, [])

    def test_cleanup_removes_stranded_temp_files_but_keeps_real_content(self):
        # A conversion killed mid-run holds an extraction folder plus a partial archive, so several GB can be
        # stranded inside the library folder that syncs to another PC. Cleanup must reclaim it and leave the
        # actual game, and Syncthing's version history, completely alone.
        import os as os_module, time as time_module
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Simulation" / "Game - 2020-01-01"
            game.mkdir(parents=True)
            stranded = game / ".organizer-repack-abc123"
            stranded.mkdir()
            (stranded / "big.bin").write_bytes(b"x" * 2_000_000)
            (game / "Game.7z.organizer-temp.999.7z").write_bytes(b"y" * 500_000)
            os.utime(game / "Game.7z.organizer-temp.999.7z", (0, 0))  # dead owner, and abandoned long enough ago
            (game / ".organizer-zip-Game.qqqqqq.zip").write_bytes(b"z" * 300_000)
            real = game / "Game.7z"
            real.write_bytes(b"REAL")
            versions = root / ".stversions"
            versions.mkdir()
            kept = versions / "Game.7z"
            kept.write_bytes(b"history")
            result = LibraryService(AppLogger(root / "x.log")).cleanup_leftovers(root)
            self.assertEqual(result["removed"], 3)
            self.assertGreater(result["bytes_freed"], 2_000_000)
            self.assertTrue(real.exists())
            self.assertEqual(real.read_bytes(), b"REAL")
            self.assertFalse(stranded.exists())
            self.assertTrue(kept.exists(), "Syncthing version history must never be deleted")

    def test_cleanup_defers_a_syncthing_transfer_that_may_be_in_flight(self):
        # A "*.syncthing.*.tmp" can be an active transfer from the other machine, so it is only removed once
        # it is older than the grace period. Deleting it early would waste bandwidth re-sending the file.
        import os as os_module, time as time_module
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Simulation" / "Game - 2020-01-01"
            game.mkdir(parents=True)
            live = game / "Live.7z.syncthing.abc.tmp"
            live.write_bytes(b"b" * 10)
            stale = game / "Old.7z.sync-conflict-20260101-000000-ABCDEFG.7z"
            stale.write_bytes(b"a" * 10)
            old = (time_module.time() - 90000, time_module.time() - 90000)
            os_module.utime(stale, old)
            service = LibraryService(AppLogger(root / "x.log"))
            result = service.cleanup_leftovers(root)
            self.assertTrue(live.exists(), "in-flight transfer must not be deleted")
            self.assertFalse(stale.exists())
            self.assertEqual(result["deferred_syncthing"], 1)

    def test_cleanup_leaves_ordinary_game_content_alone(self):
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Simulation" / "Game - 2020-01-01"
            game.mkdir(parents=True)
            names = ("Game.7z", "Game (2).7z", "Notes.txt", "Game_grid.jpg", "setup.exe", "Patch v1.2.7z")
            for name in names:
                (game / name).write_bytes(b"data")
            result = LibraryService(AppLogger(root / "x.log")).cleanup_leftovers(root)
            self.assertEqual(result["removed"], 0)
            self.assertTrue(all((game / name).exists() for name in names))

    def test_temp_names_are_unmistakable_so_cleanup_cannot_hit_real_content(self):
        # Every temp artifact must carry a marker that no real game file would have.
        from services.organizer_service import TEMP_DIR_PREFIX, TEMP_FILE_TAG

        self.assertTrue(TEMP_DIR_PREFIX.startswith(".organizer-"))
        self.assertTrue(TEMP_FILE_TAG.startswith(".organizer-"))

    def test_old_archive_moves_to_root_archive_folder(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            old = root / "Simulation" / "Game"
            old.mkdir(parents=True)
            source = old / "Game 1.0.zip"
            source.write_text("old")
            target = OrganizerService(AppLogger(root / "log.log")).archive_file(source, root)
            self.assertEqual(target, root / "Archive" / "Game 1.0.zip")
            self.assertTrue(target.exists())
            self.assertFalse(source.exists())

    def test_extra_archive_in_game_folder_is_moved_to_library_archive(self):
        # A game manually dropped into an already-organized folder leaves two archives side by side. Only one
        # belongs in the game folder, so the extra copy goes to the library Archive folder.
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Simulation" / "Game - 2020-01-02"
            game.mkdir(parents=True)
            kept = game / "Game 1.1.zip"
            extra = game / "Game 1.0.zip"
            kept.write_text("new")
            extra.write_text("old")
            service = LibraryService(AppLogger(root / "x.log"))
            organizer = OrganizerService(AppLogger(root / "x.log"))
            moved = service.enforce_single_archive(root, organizer)
            self.assertEqual(moved, 1)
            self.assertEqual([item.name for item in game.iterdir() if item.suffix == ".zip"], ["Game 1.1.zip"])
            self.assertTrue((root / "Archive" / "Game 1.0.zip").exists())

    def test_single_archive_game_folder_is_untouched(self):
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Simulation" / "Game - 2020-01-02"
            game.mkdir(parents=True)
            only = game / "Game 1.1.zip"
            only.write_text("new")
            service = LibraryService(AppLogger(root / "x.log"))
            self.assertEqual(service.enforce_single_archive(root, OrganizerService(AppLogger(root / "x.log"))), 0)
            self.assertTrue(only.exists())
            self.assertFalse((root / "Archive").exists())

    def test_folder_of_newest_version_wins_and_keeps_artwork_and_links(self):
        # The newest version stays in the game folder and the rest of the folder's contents (artwork, Steam
        # links, metadata) must survive the collapse, since only the extra archive is supposed to move.
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Simulation" / "Game - 2020-01-02"
            game.mkdir(parents=True)
            kept = game / "Game 1.1.7z"
            game.joinpath("Game 1.0.zip").write_text("old")
            kept.write_text("new")
            game.joinpath("Game_grid.jpg").write_text("cover")
            game.joinpath("Open Steam Page (Steam Deck).desktop").write_text("link")
            game.joinpath(".game-info.json").write_text('{"appid":"12345","name":"Game"}')
            service = LibraryService(AppLogger(root / "x.log"))
            service.enforce_single_archive(root, OrganizerService(AppLogger(root / "x.log")))
            self.assertTrue(game.is_dir())
            self.assertTrue(kept.exists())
            self.assertTrue((game / "Game_grid.jpg").exists())
            self.assertTrue((game / "Open Steam Page (Steam Deck).desktop").exists())
            self.assertTrue((game / ".game-info.json").exists())
            self.assertTrue((root / "Archive" / "Game 1.0.zip").exists())

    def test_scan_collapses_manually_added_duplicate_and_undo_restores_it(self):
        # End-to-end reproduction: a game is manually dropped into an already-organized folder, so the folder
        # holds two archives. Scan must collapse it to one and record the move, so Undo can put it back.
        from threading import Event
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from services.rollback_service import RollbackService
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Simulation" / "Game - 2020-01-02"
            game.mkdir(parents=True)
            kept = game / "Game 1.1.zip"
            extra = game / "Game 1.0.zip"
            kept.write_text("new")
            extra.write_text("old")
            (game / "Game_grid.jpg").write_text("cover")
            (game / "Open Steam Page (Steam Deck).desktop").write_text("[Desktop Entry]\nURL=https://store.steampowered.com/app/12345/\n")
            logger = AppLogger(root / "x.log")
            organizer = OrganizerService(logger)
            rollback = RollbackService(root, logger)
            jobs = JobManager()
            services = type("Services", (), {})()
            services.organizer = organizer
            services.rollback = rollback
            services.library = LibraryService(logger)
            services.archive = ArchiveService(logger)
            services.artwork = type("Artwork", (), {"download_assets": lambda *a, **k: ArtworkResult(), "lookup": lambda *a, **k: ArtworkResult()})()
            services.catalog = type("Catalog", (), {"generate": lambda *a, **k: []})()
            controller = AppController(StateStore(), EventBus(), logger, services, jobs)
            finished = Event()
            scanned = []
            controller.scan(root, lambda result: (scanned.append(result), finished.set()), new_only=True)
            self.assertTrue(finished.wait(10))
            jobs.shutdown()
            self.assertEqual([item.name for item in game.iterdir() if item.suffix == ".zip"], ["Game 1.1.zip"])
            self.assertTrue((root / "Archive" / "Game 1.0.zip").exists())
            self.assertTrue((game / "Game_grid.jpg").exists())
            # Nothing new should be queued for organizing, since the extra copy was resolved before discovery.
            self.assertEqual(scanned[0].archives, [])
            undone = rollback.undo_last(root)
            self.assertEqual(undone["moved"], 1)
            self.assertTrue(extra.exists())

    def test_different_games_sharing_one_folder_are_both_kept(self):
        # A bad Steam match can land two genuinely different games in the same folder. Collapsing there would
        # hide a real game in the Archive folder, so only same-identity copies are ever collapsed.
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Simulation" / "Same Steam Page - 2020-01-02"
            game.mkdir(parents=True)
            first = game / "Fabledom Alpha.zip"
            second = game / "Totally Different Game.zip"
            first.write_text("a")
            second.write_text("b")
            service = LibraryService(AppLogger(root / "x.log"))
            log_path = root / "x.log"
            self.assertEqual(service.enforce_single_archive(root, OrganizerService(AppLogger(log_path))), 0)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertFalse((root / "Archive").exists())
            self.assertIn("MULTIPLE_GAMES_IN_FOLDER", log_path.read_text())

    def test_same_game_with_different_format_names_is_collapsed(self):
        # The copy added by hand may be named differently (different format/spacing) yet still normalize to
        # the same game, which is the case this cleanup exists for.
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Simulation" / "Game - 2020-01-02"
            game.mkdir(parents=True)
            kept = game / "Game v1.1.7z"
            extra = game / "Game.Repack.v1.0.zip"
            kept.write_text("new")
            extra.write_text("old")
            service = LibraryService(AppLogger(root / "x.log"))
            self.assertEqual(service.enforce_single_archive(root, OrganizerService(AppLogger(root / "x.log"))), 1)
            self.assertEqual([item.name for item in game.iterdir() if item.suffix.lower() in (".zip", ".7z")], ["Game v1.1.7z"])
            self.assertTrue((root / "Archive" / "Game.Repack.v1.0.zip").exists())

    def test_archive_folder_contents_are_never_reorganized(self):
        from services.library_service import LibraryService

        with TemporaryDirectory() as d:
            root = Path(d)
            archive_dir = root / "Archive"
            archive_dir.mkdir()
            archive_dir.joinpath("Game 1.0.zip").write_text("a")
            archive_dir.joinpath("Game 1.1.zip").write_text("b")
            service = LibraryService(AppLogger(root / "x.log"))
            self.assertEqual(service.enforce_single_archive(root, OrganizerService(AppLogger(root / "x.log"))), 0)
            self.assertEqual(len(list(archive_dir.glob("*.zip"))), 2)

    def test_newer_file_date_wins_when_versions_tie(self):
        import os, time

        with TemporaryDirectory() as d:
            root = Path(d)
            older = root / "Game.zip"
            newer = root / "Game Copy.zip"
            older.write_text("old")
            newer.write_text("new")
            now = time.time()
            os.utime(older, (now - 100, now - 100))
            os.utime(newer, (now, now))
            service = OrganizerService(AppLogger(root / "log.log"))
            first = GameArchive(older, "Game", "Game", "game", ".zip", (0,))
            second = GameArchive(newer, "Game", "Game", "game", ".zip", (0,))
            self.assertGreater(service._promotion_key(second), service._promotion_key(first))

    def test_undo_clears_successfully_consumed_journal(self):
        from services.rollback_service import RollbackService

        with TemporaryDirectory() as d:
            root = Path(d)
            source = root / "Game.zip"
            target = root / "Simulation" / "Game" / "Game.zip"
            target.parent.mkdir(parents=True)
            target.write_text("x")
            service = RollbackService(root, AppLogger(root / "x.log"))
            service.record([(source, target)])
            result = service.undo_last(root)
            self.assertEqual(result["moved"], 1)
            self.assertFalse(service.journal.exists())

    def test_undo_restores_repacked_file_with_its_current_extension(self):
        # If the organized file was repacked from .zip to .rar after the move, undo must restore it with
        # the .rar extension at the original location rather than mislabeling it back to .zip.
        from services.rollback_service import RollbackService

        with TemporaryDirectory() as d:
            root = Path(d)
            source = root / "Game.zip"
            target = root / "Simulation" / "Game" / "Game.rar"
            target.parent.mkdir(parents=True)
            target.write_text("x")
            service = RollbackService(root, AppLogger(root / "x.log"))
            service.record([(source, target)])
            result = service.undo_last(root)
            self.assertEqual(result["moved"], 1)
            restored = root / "Game.rar"
            self.assertTrue(restored.exists())
            self.assertFalse(source.exists())

    def _organize_with_failing_metadata(self, root, logger, jobs, fail_on=3, names=("Alpha Game", "Beta Game", "Gamma Game", "Delta Game")):
        """Runs a real organize over `names`, making the metadata write raise on the fail_on-th game.

        That is the window between shutil.move() landing the archive and move() returning, which is the only
        place a failure can leave the library half-organized.
        """
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from services.organizer_service import OrganizerService
        from services.rollback_service import RollbackService

        for name in names:
            (root / f"{name}.7z").write_bytes(f"payload for {name}".encode())
        organizer = OrganizerService(logger, convert_archives=False)
        real_write = organizer.write_metadata
        calls = {"n": 0}

        def flaky(game_dir, archive):
            calls["n"] += 1
            if calls["n"] == fail_on:
                raise OSError(28, "simulated failure writing metadata")
            return real_write(game_dir, archive)

        organizer.write_metadata = flaky
        services = type("Services", (), {"organizer": organizer, "rollback": RollbackService(root, logger), "catalog": type("Catalog", (), {"generate": lambda *a, **k: None})()})()
        bus = EventBus()
        controller = AppController(StateStore(), bus, logger, services, jobs)
        failures = []
        from threading import Event as ThreadEvent

        finished = ThreadEvent()
        result = []
        # A failed run never reaches the done callback, so the run is over once either one fires.
        bus.subscribe("operation_failed", lambda event: (failures.append(event.payload), finished.set()))
        items = []
        for name in names:
            item = GameArchive(root / f"{name}.7z", name, name, name.lower().replace(" ", ""), ".7z")
            item.steam = SteamMatch(found=True, appid="1", name=name, release_date="2021-01-01")
            item.decision.accepted = True
            item.decision.category = "Unsorted"
            items.append(item)
        controller.organize(items, root, lambda moved: (result.extend(moved), finished.set()))
        self.assertTrue(finished.wait(30), "the organize run never finished")
        return result

    def test_a_failure_after_the_move_rolls_that_game_back_too(self):
        # A move does more work after the archive has landed: repacking, artwork, Steam links, metadata. When
        # one of those failed, the archive had already left the journal entry behind it - the journal was only
        # written once move() returned - so the game was stranded in its category folder with nothing on the
        # screen to say so. It is now put back where it came from, and the run continues.
        from threading import Event
        from core.logger import AppLogger
        from app.jobs import JobManager

        with TemporaryDirectory() as d:
            root = Path(d)
            logger = AppLogger(root / "x.log")
            jobs = JobManager()
            result = self._organize_with_failing_metadata(root, logger, jobs, fail_on=3)
            jobs.shutdown()
            self.assertTrue((root / "Gamma Game.7z").is_file(), "the game that failed mid-move was not put back")
            self.assertEqual([p for p in root.rglob("Gamma Game.7z") if p.parent != root], [], "the game that failed mid-move was left in a category folder")
            filed = {a.display_name for a in result if getattr(a, "organized_path", None)}
            self.assertEqual(filed, {"Alpha Game", "Beta Game", "Delta Game"}, f"the games that succeeded were not left filed: {filed}")
            bad = [a for a in result if a.display_name == "Gamma Game"]
            self.assertEqual([a.conversion.status for a in bad], ["failed"], "the game that failed mid-move was not reported as failed")

    def test_one_unmovable_game_does_not_end_the_run(self):
        # A file the user has open in Explorer cannot be moved, and one such file ended the whole run: every
        # game already filed was rolled back and nothing at all was organized, so a single locked file in a
        # library of two hundred meant fixing that file and starting again. The run now puts that one game back,
        # names it on the Done screen with the reason, and carries on with the rest of the library.
        from threading import Event
        from core.logger import AppLogger
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from services.organizer_service import OrganizerService
        from services.rollback_service import RollbackService

        names = ("Alpha Game", "Bravo Game", "Charlie Game", "Delta Game")
        with TemporaryDirectory() as d:
            root = Path(d)
            logger = AppLogger(root / "x.log")
            jobs = JobManager()
            for name in names:
                (root / f"{name}.7z").write_bytes(f"payload for {name}".encode())
            organizer = OrganizerService(logger, convert_archives=False)
            real = organizer.move

            def unmovable(archive, destination, on_progress=None):
                if archive.display_name == "Charlie Game":
                    raise PermissionError(32, f"{archive.display_name} is open in another process")
                return real(archive, destination, on_progress=on_progress)

            organizer.move = unmovable
            services = type("Services", (), {"organizer": organizer, "rollback": RollbackService(root, logger), "catalog": type("Catalog", (), {"generate": lambda *a, **k: None})()})()
            bus = EventBus()
            controller = AppController(StateStore(), bus, logger, services, jobs)
            failures = []
            bus.subscribe("operation_failed", lambda event: failures.append(event.payload))
            items = []
            for name in names:
                item = GameArchive(root / f"{name}.7z", name, name, name.lower().replace(" ", ""), ".7z")
                item.steam = SteamMatch(found=True, appid="1", name=name, release_date="2021-01-01")
                item.decision.accepted = True
                item.decision.category = "Unsorted"
                items.append(item)
            finished = Event()
            result = []
            controller.organize(items, root, lambda moved: (result.extend(moved), finished.set()))
            self.assertTrue(finished.wait(30), "the run never finished")
            jobs.shutdown()
            self.assertEqual(failures, [], "one unmovable game still ended the run")
            filed = {a.display_name for a in result if getattr(a, "organized_path", None)}
            self.assertEqual(filed, {"Alpha Game", "Bravo Game", "Delta Game"}, f"the games that could be filed were not: {filed}")
            bad = [a for a in result if a.display_name == "Charlie Game"]
            self.assertEqual([a.conversion.status for a in bad], ["failed"], "the game that could not be moved was not handed to the Done screen")
            self.assertIn("another process", bad[0].conversion.message)
            self.assertTrue((root / "Charlie Game.7z").is_file(), "the unmovable game was not left where it was")

    def test_a_rolled_back_run_leaves_no_folder_that_holds_no_game(self):
        # Rolling a game back returns its archive but not the folder the run created, so what stayed behind was a
        # game folder holding a .game-info.json and no game. Nothing in the app could see those and the user had
        # to delete them by hand, one per game, after every failed or cancelled run.
        from core.logger import AppLogger
        from core.constants import ARCHIVE_EXTENSIONS
        from app.jobs import JobManager

        with TemporaryDirectory() as d:
            root = Path(d)
            logger = AppLogger(root / "x.log")
            jobs = JobManager()
            self._organize_with_failing_metadata(root, logger, jobs, fail_on=3)
            jobs.shutdown()
            # The invariant is not "the folder is empty" but "no folder describes a game it does not hold":
            # a Steam link written alongside the metadata is expected, a metadata file with no archive under it
            # is the litter.
            for folder in [p for p in root.rglob("*") if p.is_dir()]:
                if any(item.suffix.lower() in ARCHIVE_EXTENSIONS for item in folder.iterdir()):
                    continue
                self.assertFalse((folder / ".game-info.json").exists(), f"{folder} describes a game but holds no archive")

    def test_the_app_starts_when_settings_hold_valid_json_that_is_not_an_object(self):
        # Valid JSON is not the JSON this file is written as. A settings.json holding [], 42 or a bare string -
        # what a hand-edit or another tool leaves behind - reached data.get() and raised AttributeError straight
        # out of the constructor, so the app would not start at all over its own settings file. saved_library_root()
        # already caught this; the read that decides the whole startup path did not.
        from core.config import AppConfig

        for text in ("[]", "42", '"hello"', "null", "true"):
            with TemporaryDirectory() as d:
                root = Path(d)
                (root / "config").mkdir()
                (root / "config" / "settings.json").write_text(text, encoding="utf-8")
                try:
                    config = AppConfig(root)
                except Exception as exc:
                    self.fail(f"settings.json holding {text} stopped the app starting: {type(exc).__name__}: {exc}")
                self.assertEqual(config.settings, {}, f"settings.json holding {text} was not discarded")
                self.assertIsNotNone(config.library_root)

    def test_undo_survives_a_journal_it_cannot_read(self):
        # The journal is written while the app is running, and it was written with a plain write_text, so a kill
        # or a full disk part-way through leaves it truncated. Undo is a button: raising JSONDecodeError out of it
        # put the app in its error phase, and pending_count() - which the run screen polls live to say what Undo
        # will restore - raised TypeError on the same file.
        from core.logger import AppLogger
        from services.rollback_service import RollbackService

        unreadable = {"a truncated write": '[{"source": "C:\\\\a\\\\Game.zip", "targ', "an object rather than a list": "{}", "an empty list": "[]", "a bare string": '"hello"', "a number": "42", "rows that are not objects": "[1, 2, 3]", "a row missing its keys": '[{"target": "C:\\\\b\\\\Game.zip"}]'}
        for label, text in unreadable.items():
            with TemporaryDirectory() as d:
                root = Path(d)
                journal = root / "config" / "last-organization.json"
                journal.parent.mkdir(parents=True)
                journal.write_text(text, encoding="utf-8")
                service = RollbackService(root, AppLogger(root / "x.log"))
                try:
                    pending = service.pending_count()
                except Exception as exc:
                    self.fail(f"pending_count() raised on {label}: {type(exc).__name__}: {exc}")
                self.assertEqual(pending, 0, f"pending_count() claimed {pending} moves could be undone from {label}")
                try:
                    result = service.undo_last(root)
                except Exception as exc:
                    self.fail(f"undo_last() raised on {label}: {type(exc).__name__}: {exc}")
                self.assertEqual(result["moved"], 0, f"undo_last() reported {result} for {label}")

    def test_the_pending_count_is_not_the_length_of_the_file_contents(self):
        # A JSON string is a perfectly valid journal as far as json.loads is concerned, so len() of one reported
        # how many moves a five character file would restore. The Undo control on the run screen showed that
        # number to the user while a run was in progress.
        from core.logger import AppLogger
        from services.rollback_service import RollbackService

        with TemporaryDirectory() as d:
            root = Path(d)
            journal = root / "config" / "last-organization.json"
            journal.parent.mkdir(parents=True)
            journal.write_text('"hello"', encoding="utf-8")
            self.assertEqual(RollbackService(root, AppLogger(root / "x.log")).pending_count(), 0)

    def test_the_journal_is_written_atomically(self):
        # The truncation the undo test defends against has to stop happening in the first place. record() wrote
        # straight to the journal, so a write interrupted part-way left the only record of where a run put its
        # games half-written. The settings file and the Steam cache both write to a temp file and replace.
        import os
        from unittest.mock import patch
        from core.logger import AppLogger
        from services.rollback_service import RollbackService

        with TemporaryDirectory() as d:
            root = Path(d)
            logger = AppLogger(root / "x.log")
            service = RollbackService(root, logger)
            service.record([(Path("C:/a/One.zip"), Path("C:/b/One.zip"))])
            journal = root / "config" / "last-organization.json"
            self.assertEqual(service.pending_count(), 1)

            def failing_replace(*args, **kwargs):
                raise OSError(28, "no space left on device")

            with patch("os.replace", failing_replace):
                service.record([(Path("C:/a/Two.zip"), Path("C:/b/Two.zip"))])
            # The previous transaction is still intact and still readable, rather than a truncated one.
            self.assertEqual(service.pending_count(), 1, f"the journal was damaged: {journal.read_text(encoding='utf-8')}")
            self.assertEqual(list((root / "config").glob("*.tmp")), [], "a temp journal was left behind")

    # The journal write has to survive what the real machine does to it, and the real machine's habit is
    # documented in this repository's own log: nine PermissionErrors writing last-organization.json, every one
    # of them from a transient lock on the project's OneDrive folder. None of that is reproducible in a temporary
    # directory on a clean disk, which is why it is simulated here rather than waited for.
    #
    # The consequence is the reason this is worth a test at all. controller.py calls record() after every move
    # and does not read its result, so a swallowed write failure means the run keeps moving files with no
    # record of where they went - and Undo then reports that there is nothing to undo, having moved nothing.
    def _journal_service(self, root):
        from core.logger import AppLogger
        from services.rollback_service import RollbackService

        return RollbackService(root, AppLogger(root / "x.log"))

    def test_a_locked_journal_is_retried_and_the_move_is_recorded(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            service = self._journal_service(root)
            moves = [(Path("C:/a/One.zip"), Path("C:/b/One.zip"))]
            real = os.replace
            calls = []

            def locked(source, target):
                calls.append(target)
                if len(calls) <= 2:
                    raise PermissionError(5, "Access is denied", str(target))
                return real(source, target)

            with patch("services.rollback_service.os.replace", side_effect=locked):
                self.assertTrue(service.record(moves), "record() reported failure on a lock that clears")
            self.assertEqual(3, len(calls), f"save gave up after {len(calls)} attempt(s) rather than retrying a locked file")
            self.assertEqual(1, service.pending_count(), "the move was not recorded, so Undo could never restore it")

    def test_a_journal_that_cannot_be_written_says_so(self):
        """The other half, and the one a retry can quietly break.

        A permanently unwritable journal has to be reported rather than absorbed. Every call site ignores
        record()'s result, so a silent failure here is indistinguishable from a successful run until the user
        reaches for Undo and finds nothing there.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            service = self._journal_service(root)

            def always_locked(source, target):
                raise PermissionError(5, "Access is denied", str(target))

            with patch("services.rollback_service.os.replace", side_effect=always_locked):
                # assertIs, not assertFalse: a record() that returned None would satisfy assertFalse while
                # still telling the caller nothing, which is the bug.
                self.assertIs(service.record([(Path("C:/a/One.zip"), Path("C:/b/One.zip"))]), False, "record() did not report that nothing reached the journal")
            logged = (root / "x.log").read_text(encoding="utf-8", errors="replace")
            self.assertIn("JOURNAL_WRITE_FAILED", logged, "a lost undo record was not logged")
            # WinError 5 with no detail is what made this cost time to diagnose: the log said only
            # "PermissionError", which does not distinguish a locked file from a read-only directory.
            self.assertIn("5", logged, f"the log records no error detail to act on: {logged[-400:]}")

    def test_two_app_instances_cannot_share_one_temporary_journal(self):
        """record() built its temp file with with_suffix('.tmp'), which is a fixed name.

        Both instances then write the same path, so the loser's finally-block unlinks the winner's temp file
        before it can be replaced - and the journal for a completed organize is lost with no error anywhere,
        because the replace that fails is not the one being reported. The name has to be unique per write.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            first = self._journal_service(root)
            second = self._journal_service(root)
            names = []
            real_replace = os.replace

            def spy(source, target):
                names.append(Path(source).name)
                return real_replace(source, target)

            with patch("services.rollback_service.os.replace", side_effect=spy):
                first.record([(Path("C:/a/One.zip"), Path("C:/b/One.zip"))])
                second.record([(Path("C:/a/Two.zip"), Path("C:/b/Two.zip"))])
            self.assertEqual(2, len(set(names)), f"both writes used the same temp file {names[0]!r}")
            self.assertEqual(1, second.pending_count(), "the second instance did not record its own move")

    def test_a_run_that_cannot_journal_itself_says_the_run_cannot_be_undone(self):
        """The last link: RollbackService reporting failure is only useful if the run acts on it.

        The files have already moved by the time the journal is written, so a write that fails leaves the run
        looking entirely successful - correct catalog, correct Done screen, and an Undo button that reports
        nothing to undo. The one thing the user could still act on is that the run is not reversible, so that
        has to be stated.
        """
        from threading import Event
        from app.controller import AppController
        from app.events import EventBus
        from app.jobs import JobManager
        from core.logger import AppLogger
        from core.models import GameArchive, SteamMatch
        from core.state import StateStore
        from services.organizer_service import OrganizerService
        from services.rollback_service import RollbackService

        with TemporaryDirectory() as d:
            root = Path(d)
            logger = AppLogger(root / "x.log")
            jobs = JobManager()
            source = root / "Recoverable Game 1.0.zip"
            source.write_text("payload")
            services = type("Services", (), {"organizer": OrganizerService(logger), "rollback": RollbackService(root, logger), "catalog": type("C", (), {"generate": lambda *a, **k: None})()})()
            controller = AppController(StateStore(), EventBus(), logger, services, jobs)
            item = GameArchive(source, "Recoverable Game", "Recoverable Game", "game", source.suffix, (1, 0))
            item.decision.accepted = True
            item.decision.category = "Factory"
            item.steam = SteamMatch(found=True, appid="123", name="Recoverable Game", release_date="2 Jan, 2020")
            finished = Event()

            def locked(*args, **kwargs):
                raise PermissionError(5, "Access is denied", str(args[-1]))

            with patch("services.rollback_service.os.replace", side_effect=locked):
                controller.organize([item], root, lambda moved: finished.set())
                self.assertTrue(finished.wait(10), "the organize run never finished")
            jobs.shutdown()
            moved = (root / "Automation").exists() and any((root / "Automation").rglob("*.zip"))
            self.assertTrue(moved, "the run did not move anything, so this test is not exercising the case")
            logged = (root / "x.log").read_text(encoding="utf-8", errors="replace")
            self.assertIn("ORGANIZE_UNDO_UNAVAILABLE", logged, f"the run moved files with no undo record and did not say so: {logged[-500:]}")

    def _link_directory_back(self, link, target):
        """A directory link pointing somewhere the walk has already been: a junction on Windows, a symlink
        elsewhere. Fails rather than skips when neither can be made, because a skipped test here would report
        the library safe on exactly the machine that cannot demonstrate it."""
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, timeout=30)
        if made.returncode == 0:
            return "junction"
        try:
            link.symlink_to(target, target_is_directory=True)
            return "symlink"
        except OSError as exc:
            self.fail(f"no way to make a directory link on this machine, so the cycle cannot be tested: {exc}")

    def test_a_directory_link_back_into_the_library_is_not_walked_twice(self):
        # rglob('*') descends a junction or a bind mount, because the OS resolves one as an ordinary directory.
        # A link inside a library pointing at the library made a library holding ONE game scan as 64 archives -
        # one per level that still fitted inside MAX_PATH, which is the only reason it stopped - and Organize
        # then treated all 64 as copies of one another, filing the real game under Archive/ as a duplicate of
        # itself. On a filesystem without that path-length limit the walk has no way to end at all.
        from utils.treewalk import walk_files

        with TemporaryDirectory() as d:
            root = Path(d)
            library = root / "Games"
            library.mkdir()
            (library / "Real Game.7z").write_bytes(b"payload")
            self._link_directory_back(library / "Loop", library)
            self.assertEqual([p.name for p in walk_files(library)], ["Real Game.7z"], "the walk descended into a directory it had already been through")
            found = ArchiveService(AppLogger(root / "x.log")).discover(library, None)
            self.assertEqual(sorted(a.display_name for a in found.archives), ["Real Game"], "the library was scanned more than once through the link")

    def test_a_link_to_a_sibling_folder_is_still_followed(self):
        # The cycle is the defect, not the link. A junction a user made to pull another folder of games into
        # their library is a deliberate thing to walk into, and refusing it would hide those games.
        from utils.treewalk import walk_files

        with TemporaryDirectory() as d:
            root = Path(d)
            library = root / "Games"
            library.mkdir()
            outside = root / "Elsewhere"
            outside.mkdir()
            (library / "Real Game.7z").write_bytes(b"payload")
            (outside / "Other Game.7z").write_bytes(b"payload")
            self._link_directory_back(library / "Link", outside)
            self.assertEqual(sorted(p.name for p in walk_files(library)), ["Other Game.7z", "Real Game.7z"])
            found = ArchiveService(AppLogger(root / "x.log")).discover(library, None)
            self.assertEqual(sorted(a.display_name for a in found.archives), ["Other Game", "Real Game"])

    def test_a_move_that_copies_but_cannot_delete_leaves_no_duplicate(self):
        # shutil.move does not give up when a rename fails: it copies and then unlinks. On a file the user has
        # open in Explorer - or one on a read-only source - the copy lands and the unlink fails, so the run
        # reports the file as unmoved while a complete duplicate of it is already filed in the category folder.
        # The next scan finds that copy and treats the game as organized with the real archive still at the root.
        # The orphan is only a duplicate while the original is still there, and because the copy carries the
        # source's read-only attribute across it also has to be made deletable before it can be removed.
        import os, shutil as shutil_module
        from unittest.mock import patch
        from core.logger import AppLogger
        from services.organizer_service import OrganizerService

        with TemporaryDirectory() as d:
            root = Path(d)
            library = root / "Games"
            library.mkdir()
            source = library / "Game.zip"
            source.write_bytes(b"payload")
            os.chmod(source, 0o444)
            real_unlink = os.unlink

            def blocked_rename(*args, **kwargs):
                raise OSError(17, "cross-device link")

            def blocked_source_delete(path, *args, **kwargs):
                # Only the original is undeletable; the orphan in the game folder is ours to clean up.
                if Path(path).parent == library:
                    raise PermissionError(32, "file is in use by another process")
                return real_unlink(path, *args, **kwargs)

            organizer = OrganizerService(AppLogger(root / "x.log"), convert_archives=False)
            item = GameArchive(source, "Game.zip", "Game", "game", ".zip")
            item.steam = SteamMatch(found=True, appid="1", name="Game", release_date="2021-01-01")
            item.decision.accepted = True
            item.decision.category = "Unsorted"
            with patch("os.rename", blocked_rename), patch("os.unlink", blocked_source_delete):
                with self.assertRaises(PermissionError):
                    organizer.move(item, library)
            copies = list(library.rglob("Game.zip"))
            self.assertEqual([c for c in copies if c != source], [], f"an orphan copy was left behind: {copies}")
            self.assertTrue(source.is_file(), "the original archive was removed")
            self.assertEqual(len(copies), 1, f"expected exactly one copy of the game, found {copies}")

    def test_genre_category_suggestion(self):
        self.assertEqual(suggest_category(["Indie", "Simulation"]), "Simulation")
        self.assertEqual(suggest_category(["Indie"]), "Unsorted")
        self.assertEqual(suggest_category(["Indie", "Horror"], "Haunted House", "A terrifying survival game"), "Horror")
        self.assertEqual(suggest_category(["Indie", "Simulation"], "Factory Game", "Automate production", tags=["Automation", "Factory"]), "Automation")
        self.assertEqual(canonical_category("Factory"), "Automation")
        self.assertEqual(canonical_category("City Sim"), "City Builder")
        self.assertEqual(canonical_category("Colony Sim"), "City Builder")
        self.assertEqual(canonical_category("Roguelite"), "Roguelike")
        self.assertEqual(canonical_category("Clicker"), "Idle")
        self.assertEqual(canonical_category("Sim City"), "City Builder")
        self.assertEqual(canonical_category("Rogue-lite"), "Roguelike")
        # The category's previous name. A saved decision or a Steam genre that still says "Cleanup" has to land
        # in Tidy Up, or eleven tidy-up games split off into a folder the picker no longer offers.
        self.assertEqual(canonical_category("Cleanup"), "Tidy Up")
        self.assertEqual(canonical_category("Tidy Up"), "Tidy Up")
        self.assertEqual(suggest_category(["Indie", "Simulation"], "Idle Game", "An incremental clicker game", tags=["Clicker", "Incremental"]), "Idle")
        self.assertEqual(suggest_category(["Indie", "Early Access"]), "Unsorted")
        self.assertEqual(suggest_category(["City Sim"]), "City Builder")
        self.assertEqual(suggest_category(["Simulation"], "Alpha Forge", "Build and manage a factory with automation"), "Automation")
        self.assertEqual(suggest_category(["Simulation"], "Timberborn", "A sandbox city-building game"), "City Builder")
        self.assertEqual(suggest_category(["Simulation"], "Cloud Dwellers", "A 2D simulation and city-building game"), "City Builder")
        self.assertEqual(suggest_category(["Simulation"], "Flotsam", "Rescue survivors in a vibrant floating city-builder"), "City Builder")
        self.assertEqual(suggest_category(["Simulation"], "Tactical Game", "A strategic tactical game", tags=["Idle"]), "Strategy")
        self.assertEqual(suggest_category(["Simulation"], "Money Shop", "Run your own shop and manage store inventory"), "Shop Management")
        self.assertEqual(suggest_category(["Simulation"], "Empire Tycoon", "Build your business empire from nothing"), "Tycoon")
        self.assertEqual(suggest_category(["Action"], "Iron Souls", "A punishing combat souls-like adventure"), "Soulslike")
        self.assertEqual(suggest_category(["Action"], "Cave Runner", "A metroidvania with backtracking exploration"), "Metroidvania")
        self.assertEqual(suggest_category(["Action"], "Neon Rally", "A first-person shooter fps game"), "First-Person Shooter")
        self.assertEqual(suggest_category(["Action"], "Iron Fists", "A fighting game with combo-based combat"), "Fighting")
        self.assertEqual(suggest_category(["Adventure"], "Quiet Roads", "A narrative walking simulator"), "Walking Sim")
        self.assertEqual(suggest_category(["Casual"], "Chart Topper", "A rhythm game beat-matching to music"), "Rhythm")

    def test_the_offered_categories_offer_each_thing_once(self):
        # The picker listed synonyms side by side, so the same kind of game could be filed under either and two
        # folders would hold it: "Roguelite" and "Roguelike", "Colony Sim" and "City Builder", and "Automation"
        # appeared in both the default and the supplemental list. A name whose canonical form is a different
        # name is a synonym, not a choice, so it must not be offered at all.
        from core.constants import DEFAULT_CATEGORIES, SUPPLEMENTAL_CATEGORIES

        offered = DEFAULT_CATEGORIES + SUPPLEMENTAL_CATEGORIES
        duplicates = [name for name in set(offered) if offered.count(name) > 1]
        self.assertEqual(duplicates, [], f"the same category is offered twice: {duplicates}")
        synonyms = [name for name in offered if canonical_category(name) != name]
        self.assertEqual(synonyms, [], f"the picker offers synonyms of another category: {synonyms}")
        for name in ("Roguelite", "Cleanup", "Colony Sim"):
            self.assertNotIn(name, offered, f"{name} is a synonym, not a separate category")
        for name in ("Idle", "Roguelike", "City Builder", "Tidy Up"):
            self.assertIn(name, offered, f"{name} disappeared from the picker")

    def test_the_two_survival_genres_stay_apart(self):
        # "Survivors" and "Survival" were the same genre under two names - the Minecraft-shaped one, gather and
        # craft and build a base. It is filed under Survival alone. "Bullet Heaven" is a different genre, the
        # Vampire Survivors one, and stays a separate choice; merging the two would file both under one name.
        from core.constants import DEFAULT_CATEGORIES, SUPPLEMENTAL_CATEGORIES

        offered = DEFAULT_CATEGORIES + SUPPLEMENTAL_CATEGORIES
        self.assertIn("Survival", offered)
        self.assertIn("Bullet Heaven", offered)
        self.assertNotIn("Survivors", offered, "Survivors is the same genre as Survival under a second name")
        self.assertEqual(canonical_category("Survivors"), "Survival")
        self.assertEqual(canonical_category("Survivor"), "Survival")
        self.assertEqual(canonical_category("Vampire Survivors"), "Bullet Heaven")
        self.assertEqual(canonical_category("Bullet Heaven"), "Bullet Heaven")

    def test_survival_and_bullet_heaven_classify_differently(self):
        # Neither genre had any inference rule, so both fell back to a Steam genre that is far too broad. The
        # survival rule is scored below Horror's on purpose: "survival horror" contains "survival", and a rule
        # given the ordinary priority would outrank a horror game that names the genre outright.
        self.assertEqual(suggest_category(["Indie", "Simulation"], "Valheim", "A brutal survival crafting game, gather resources and build a base"), "Survival")
        self.assertEqual(suggest_category(["Indie", "Simulation"], "Palworld", "Craft, build a base and survive Pals in a voxel world"), "Survival")
        self.assertEqual(suggest_category(["Indie", "Casual"], "Brotato", "A bullet heaven survivors-like game with auto attacks and waves of enemies"), "Bullet Heaven")
        self.assertEqual(suggest_category(["Indie", "Horror"], "Dead by Daylight", "A terrifying asymmetric survival horror game"), "Horror")

    def test_a_tidy_up_game_is_suggested_the_tidy_up_category(self):
        # The category was renamed rather than kept alongside its old name, so the classifier has to know the new
        # one too - otherwise every tidy-up game falls back to its Steam genre and lands in Unsorted.
        self.assertEqual(suggest_category(["Indie", "Simulation"], "Tidy Up", "A relaxing game about cleaning and decluttering your shop"), "Tidy Up")
        self.assertEqual(suggest_category(["Indie", "Casual"], "Cleaning Up The Puzzle Gallery", "Sort, sweep and tidy up a puzzle museum"), "Tidy Up")

    def test_steam_candidate_scoring_rejects_unrelated_results(self):
        service = _steam(self)
        chosen, score = service._choose([{"id": "1", "name": "Alpha Forge"}, {"id": "2", "name": "Industry Giant"}], "Alpha Forge")
        self.assertEqual(chosen["id"], "1")
        self.assertEqual(score, 1.0)
        chosen, score = service._choose([{"id": "2", "name": "Industry Giant"}], "Alpha Forge")
        self.assertIsNone(chosen)
        self.assertEqual(score, 0.0)

    def test_query_variants_strip_attached_release_suffixes(self):
        service = _steam(self, mock=True)
        variants = service._query_variants("airborneempirefitgirl", "airborneempirefitgirl", None)
        self.assertIn("airborneempire", variants)
        self.assertIn("airborneempirefitgirl", variants)

    def test_query_variants_try_shorter_prefixes_for_trailing_subtitle_words(self):
        service = _steam(self, mock=True)
        variants = service._query_variants("Supercar Collection Simulator Racing Series 20260916", "Supercar Collection Simulator Racing Series 20260916", None)
        self.assertIn("Supercar Collection Simulator", variants)

    def test_query_variants_never_drop_a_trailing_sequel_number(self):
        service = _steam(self, mock=True)
        variants = service._query_variants("Cities Skylines 2", "Cities Skylines 2", None)
        self.assertNotIn("Cities Skylines", variants)
        variants = service._query_variants("Sonic Frontiers II", "Sonic Frontiers II", None)
        self.assertNotIn("Sonic Frontiers", variants)

    def test_query_variants_resolve_edition_and_release_tag_suffixes_generically(self):
        service = _steam(self, mock=True)
        cases = [("Delta Realm Incremental", "Delta Realm"), ("Ball XPit20260808", "BALL x PIT"), ("Kingdoms And Castles123r6s", "Kingdoms and Castles"), ("Flotsam101f7", "Flotsam"), ("Epsilon Online Tenoke", "Epsilon Online")]
        for normalized, official in cases:
            variants = service._query_variants(normalized, normalized, None)
            self.assertIn(identity_key(official), [identity_key(v) for v in variants])

    def test_query_variants_strip_generic_marketing_edition_suffixes(self):
        service = _steam(self, mock=True)
        self.assertIn("Divinity Original Sin 2", service._query_variants("Divinity Original Sin 2 Definitive Edition", "Divinity Original Sin 2 Definitive Edition", None))
        self.assertIn("Cities Skylines II", service._query_variants("Cities Skylines II Deluxe Edition", "Cities Skylines II Deluxe Edition", None))

    def test_query_variants_swap_ampersand_and_and(self):
        service = _steam(self, mock=True)
        self.assertIn("Kingdoms and Castles", service._query_variants("Kingdoms & Castles", "Kingdoms & Castles", None))

    def test_query_variants_try_both_arabic_and_roman_numerals(self):
        service = _steam(self, mock=True)
        self.assertIn("Dark Souls III", service._query_variants("Dark Souls 3", "Dark Souls 3", None))
        self.assertIn("Resident Evil 4", service._query_variants("Resident Evil IV", "Resident Evil IV", None))

    def test_query_variants_do_not_mangle_ordinary_words_containing_x(self):
        service = _steam(self, mock=True)
        variants = service._query_variants("Exodus Complex Edition", "Exodus Complex Edition", None)
        self.assertFalse(any("e x" in v.casefold() or "e x o" in v.casefold() for v in variants))

    def test_lookup_store_finds_official_title_via_generic_variants(self):
        service = _steam(self)

        def fake_request(url, ctx=None):
            if "meow" in url.casefold() and "doomsguard" in url.casefold():
                return {"items": [{"id": "3461730", "name": "Meow Tower: Doomsguard"}]}
            return {"items": []}

        service._request_json = fake_request
        service._details = lambda appid, ctx=None: {"name": "Meow Tower: Doomsguard"}
        steam_match = service._lookup_store("Meow Tower Doomsguard", None)
        self.assertEqual(steam_match.appid, "3461730")
        self.assertTrue(steam_match.found)

    def test_steamgriddb_mismatched_game_is_rejected(self):
        from services.artwork_service import ArtworkService

        service = _artwork(self, "key")
        service._steamgriddb_url = lambda appid, expected_name="", ctx=None: ""
        self.assertEqual(service._steamgriddb_url("4428430", "Fantasy Miner: Idle Depths"), "")

    def test_lookup_accepts_steam_url_or_appid(self):
        service = _steam(self)
        service._lookup_appid = lambda appid, ctx: SteamMatch(found=True, appid=appid, name="Direct Game")
        self.assertEqual(service.lookup("https://store.steampowered.com/app/12345/").appid, "12345")
        self.assertEqual(service.lookup("67890").appid, "67890")

    def test_cancelled_controller_emits_cancellation_event(self):
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager
        from core.exceptions import CancellationError

        with TemporaryDirectory() as d:
            events = []
            bus = EventBus()
            bus.subscribe("operation_cancelled", lambda event: events.append(event))
            logger = AppLogger(Path(d) / "x.log")
            jobs = JobManager()
            controller = AppController(StateStore(), bus, logger, type("Services", (), {})(), jobs)
            controller._failed("verify", CancellationError("cancelled"))
            jobs.shutdown()
            self.assertEqual(events[0].payload["operation"], "verify")

    def test_review_queue_deduplicates_archive_formats(self):
        from ui.widgets.game_list import GameList

        first = GameArchive(Path("/tmp/Game.zip"), "Game", "Game", "game", ".zip")
        second = GameArchive(Path("/tmp/Game.rar"), "Game", "Game", "game", ".rar")
        self.assertEqual(first.identity_key, second.identity_key)

    def test_category_decisions_persist(self):
        from app.controller import AppController
        from app.events import EventBus
        from core.state import StateStore
        from app.jobs import JobManager

        with TemporaryDirectory() as d:
            logger = AppLogger(Path(d) / "x.log")
            jobs = JobManager()
            controller = AppController(StateStore(), EventBus(), logger, type("Services", (), {})(), jobs)
            controller.config = type("Config", (), {"config_dir": Path(d), "sync_to_appdata": lambda self: None})()
            controller.remember_category("example", "Simulation")
            self.assertEqual(controller._saved_categories()["identity"]["example"], "Simulation")
            jobs.shutdown()

    def test_direct_steam_service_mock_is_backend_free(self):
        with TemporaryDirectory() as d:
            s = SteamService(AppLogger(Path(d) / "x.log"), mock=True)
            steam_match = s.lookup("Epsilon Online")
            self.assertEqual(steam_match.source, "mock")
            self.assertEqual(steam_match.name, "Epsilon Online")

    def test_artwork_urls_prefer_header_over_grid(self):
        from services.artwork_service import ArtworkService

        urls = _artwork(self)._urls("123", "https://cdn.example/header.jpg")
        # header.jpg on three CDN hosts first, then the preferred URL, then library_600x900.jpg
        # on the two non-store_item_assets hosts so a library capsule that 404s on the new path
        # still has a second CDN family to try.
        self.assertEqual(urls[0], "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/123/header.jpg")
        self.assertIn("https://cdn.example/header.jpg", urls)
        self.assertEqual(len(urls), 6)

    def test_steam_cache_path_is_separate_from_grid_cache(self):
        from services.artwork_service import ArtworkService

        service = _artwork(self)
        self.assertNotEqual(service.cached_path("123", portrait=True), service.cached_path("123", steam=True))
        self.assertNotEqual(service.cached_path("123", steam=True), service.cached_path("123", fallback=True))

    def test_artwork_service_removes_only_legacy_cache_files(self):
        from services.artwork_service import ArtworkService

        with TemporaryDirectory() as d:
            cache = Path(d)
            (cache / "123.jpg").write_bytes(b"old")
            (cache / "456_steam.jpg").write_bytes(b"old")
            (cache / "789_steam_v2.jpg").write_bytes(b"new")
            ArtworkService(cache, AppLogger(cache / "x.log"))
            self.assertFalse((cache / "123.jpg").exists())
            self.assertFalse((cache / "456_steam.jpg").exists())
            self.assertTrue((cache / "789_steam_v2.jpg").exists())

    def test_artwork_cache_expires_old_files_only(self):
        from services.artwork_service import ArtworkService
        import os, time

        with TemporaryDirectory() as d:
            cache = Path(d)
            fresh = cache / "1_steam_v2.jpg"
            old = cache / "2_steam_v2.jpg"
            fresh.write_bytes(b"new")
            old.write_bytes(b"old")
            old_time = time.time() - 11 * 86400
            os.utime(old, (old_time, old_time))
            ArtworkService(cache, AppLogger(cache / "x.log"), max_age_days=10)
            self.assertTrue(fresh.exists())
            self.assertFalse(old.exists())

    def test_steam_primary_uses_library_capsule_fallback_url(self):
        from services.steam_service import SteamService

        service = _steam(self, mock=True)
        steam_match = service._build_match("123", {"name": "Example"}, {"capsule_image": "https://example/capsule.jpg"})
        self.assertIn("/steam/apps/123/library_600x900.jpg", steam_match.artwork_url)

    def test_steam_matches_persist_between_service_instances(self):
        from services.steam_service import SteamService

        with TemporaryDirectory() as d:
            cache = Path(d) / "steam-matches.json"
            logger = AppLogger(Path(d) / "x.log")
            first = SteamService(logger, cache_file=cache)
            steam_match = SteamMatch(found=True, appid="123", name="Example")
            first.remember("Example Archive", steam_match)
            second = SteamService(logger, cache_file=cache)
            self.assertEqual(second.lookup("Example Archive").appid, "123")

    def test_manual_refresh_bypasses_cached_match(self):
        from services.steam_service import SteamService

        with TemporaryDirectory() as d:
            service = SteamService(AppLogger(Path(d) / "x.log"))
            service.cache["example"] = SteamMatch(found=True, appid="old", name="Old")
            service._lookup_store = lambda title, ctx: SteamMatch(found=True, appid="new", name="New")
            self.assertEqual(service.lookup("Example", refresh=True).appid, "new")

    def test_lookup_retries_an_initial_miss(self):
        from services.steam_service import SteamService

        service = _steam(self)
        calls = []
        service._lookup_store = lambda title, ctx: calls.append(title) or (SteamMatch(found=False) if len(calls) == 1 else SteamMatch(found=True, appid="123", name="Farm Factory Simulator"))
        self.assertTrue(service.lookup("Farm Factory Simulator").found)
        self.assertEqual(len(calls), 2)

    def test_lookup_retries_three_times_when_steam_is_transiently_empty(self):
        from services.steam_service import SteamService

        service = _steam(self, mock=True)
        calls = []
        service.mock = False
        service._lookup_store = lambda title, ctx: calls.append(title) or (SteamMatch(found=True, appid="123", name="Example") if len(calls) == 3 else SteamMatch(found=False))
        self.assertTrue(service.lookup("Example").found)
        self.assertEqual(len(calls), 3)

    def test_artwork_service_keeps_steamgriddb_key_configurable(self):
        from services.artwork_service import ArtworkService

        service = _artwork(self, "old-key")
        service.set_api_key("new-key")
        self.assertEqual(service.api_key, "new-key")

    def test_artwork_result_supports_asset_bundle(self):
        from core.models import ArtworkResult

        result = ArtworkResult(assets={"library_hero": Path("/tmp/hero.jpg")})
        self.assertIn("library_hero", result.assets)


class ArtworkWarningsHaveToBeTrue(unittest.TestCase):
    """A run that obtained artwork must not log that artwork was unavailable.

    download_assets() calls download() for the primary image and only then fetches the per-asset URLs. Those are
    different URL families on different hosts, so a game whose library capsule 404s can still have working asset
    URLs. A live run of Incremedieval.7z did exactly that: five images downloaded into the game folder, and one
    WARN reading UNAVAILABLE appid=5076690 reason=[all_steam_sources_failed]. It was the only artwork warning in
    the log and it contradicted the run's own result.

    A warning that is wrong is worse than no warning, because it is the thing a person opens the log to find.
    So the honest severity depends on the whole attempt, which is only known after the asset pass - one warning
    for a game that genuinely has no artwork, and silence for one that does.
    """

    ASSETS = {"header_image": "https://cdn.example/header.jpg", "capsule_image": "https://cdn.example/capsule.jpg"}
    PAYLOAD = b"\xff\xd8\xff\xe0" + b"0" * 4000

    def _download(self, root, assets_succeed=True, preferred_url=""):
        """Fetch with the network faked: the asset URLs behave as asked, every other host 404s.

        The primary image is deliberately not among the URLs that succeed, because that is the situation being
        covered - a missing library capsule with working asset URLs behind it.
        """
        from urllib.error import HTTPError
        from services.artwork_service import ArtworkService

        cache = root / "cache"
        log = root / "x.log"
        working = {self.ASSETS["header_image"]} if assets_succeed else set()
        if preferred_url:
            working.add(preferred_url)

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return self.__class__.payload

        _Response.payload = self.PAYLOAD

        def fake_urlopen(request, timeout=None):
            url = getattr(request, "full_url", None) or str(request)
            if url in working:
                return _Response()
            raise HTTPError(url, 404, "Not Found", {}, None)

        with patch("services.artwork_service.urlopen", side_effect=fake_urlopen):
            result = ArtworkService(cache, AppLogger(log)).download_assets("5076690", dict(self.ASSETS), preferred_url=preferred_url)
        return result, log.read_text(encoding="utf-8", errors="replace")

    def test_assets_downloaded_while_the_primary_404s_logs_no_warning(self):
        with TemporaryDirectory() as d:
            result, text = self._download(Path(d))
            self.assertTrue(result.assets, "the fixture did not download any asset, so it proves nothing")
            self.assertNotIn("[WARN", text, f"a run that downloaded artwork logged a warning about artwork being unavailable:\n{text}")

    def test_a_game_with_no_artwork_anywhere_is_still_warned_about(self):
        """The other half. Silence has to mean artwork arrived, not that the warning was simply removed."""
        with TemporaryDirectory() as d:
            result, text = self._download(Path(d), assets_succeed=False)
            self.assertFalse(result.assets, "the fixture downloaded an asset, so it is not the no-artwork case")
            self.assertIn("5076690", text, "a game with no artwork at all was not recorded in the log")

    def test_a_primary_image_that_downloads_logs_no_warning(self):
        with TemporaryDirectory() as d:
            self._download(Path(d), preferred_url=self.ASSETS["header_image"])
            _, text = self._download(Path(d), preferred_url=self.ASSETS["header_image"])
            self.assertNotIn("[WARN", text, f"the ordinary successful path logged a warning:\n{text}")


class TestArchiveShippedAppID(unittest.TestCase):
    """An archive that states its own AppID answers the question the search engine would be asked.

    Before this, resolving a game meant searching a Steam Store index and scoring whatever came back, and a
    title whose punctuation had been flattened in the filename needed a hand-written alias to come back at all.
    Most releases ship `steam_settings/steam_appid.txt` or an `appmanifest_*.acf`, which is the answer already.
    Built from real archives here, because the reading is done by the real tool.
    """

    def setUp(self):
        # Nothing here needed a scratch folder: the fixtures are built under self.dir, which tearDown removes.
        # It used to be `Path(TemporaryDirectory().name)`, which threw the object away and so had its own
        # finalizer delete the folder the instant setUp returned - one ResourceWarning per test method, for a
        # path nothing ever read.
        self.dir = Path(tempfile.mkdtemp())
        self.service = SteamService(AppLogger(self.dir / "steam.log"))
        self.details = {}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _zip(self, name, entries):
        """A real archive holding the given files, so the AppID is read by the real tool rather than a stub."""
        from services.extract_service import ExtractService

        tool = ExtractService.find_tool()[0]
        if not tool:
            self.fail("7-Zip is required to build the fixture archive and was not found")
        source = self.dir / "tree" / name
        for relative, content in entries.items():
            item = source / relative
            item.parent.mkdir(parents=True, exist_ok=True)
            item.write_text(content, encoding="utf-8")
        archive = self.dir / name
        proc = subprocess.run([tool, "a", "-tzip", "-bso0", "-bsp0", str(archive), str(source)], stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(proc.returncode, 0, "could not build the fixture archive")
        return archive

    def _stub_details(self, appid, name):
        """Answer appdetails for one AppID out of a table, so the network is never involved.

        The name is passed separately rather than assumed to be the AppID: what appdetails returns is the
        game's *official* name, and that is the string the archive's AppID gets checked against. Answering
        with the AppID itself would make every score a mismatch.
        """
        self.details[appid] = {"name": name, "genres": [{"description": "Simulation"}], "release_date": {"date": "1 Jan, 2024"}}
        self.service._details = lambda wanted, ctx=None: self.details.get(wanted, {})
        return appid

    def test_a_shipped_appid_resolves_the_name_without_a_search(self):
        self._stub_details("1614040", "Prison Architect")
        archive = self._zip("Prison Architect.zip", {"Prison Architect/steam_settings/steam_appid.txt": "1614040\n"})
        searched = []
        self.service._lookup_store = lambda title, ctx: searched.append(title) or SteamMatch(found=False)
        result = self.service.lookup("Prison Architect", archive_path=archive)
        self.assertTrue(result.found)
        self.assertEqual(result.appid, "1614040")
        self.assertEqual(result.name, "Prison Architect")
        self.assertEqual(result.source, "steam_appid")
        self.assertEqual(result.confidence, "High")
        self.assertEqual(searched, [], "the AppID the archive shipped was not used, so a search ran anyway")

    def test_an_appmanifest_declares_the_appid_in_its_own_name(self):
        self._stub_details("1128810", "The Witcher 3")
        archive = self._zip("The Witcher 3.zip", {"The Witcher 3/steam_settings/appmanifest_1128810.acf": '"AppState"\n{\n\t"appid"\t\t"1128810"\n}\n'})
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("The Witcher 3", archive_path=archive)
        self.assertTrue(result.found)
        self.assertEqual(result.appid, "1128810")
        self.assertEqual(result.name, "The Witcher 3")

    def test_an_archive_that_declares_nothing_falls_back_to_searching(self):
        archive = self._zip("Some Game.zip", {"Some Game/readme.txt": "nothing useful here"})
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("Some Game", archive_path=archive)
        self.assertFalse(result.found, "an archive with no AppID was still resolved")

    def test_an_archive_naming_several_appids_is_never_guessed_at(self):
        """A pack, or a shared steam_settings, is not one game. Picking one of them would be a coin flip that
        renames the game's folder to whichever title happened to win."""
        archive = self._zip("Pack.zip", {"Pack/steam_settings/appmanifest_1000.acf": '"AppState"{}', "Pack/steam_settings/appmanifest_2000.acf": '"AppState"{}'})
        self._stub_details("1000", "Pack")
        self._stub_details("2000", "Pack")
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("Pack", archive_path=archive)
        self.assertFalse(result.found, "an ambiguous archive resolved to one of its AppIDs anyway")

    def test_a_stale_appid_is_rejected_rather_than_renaming_the_folder(self):
        """Some releases carry a copy-pasted AppID. Believing it would file the game under another game's name,
        which is the one outcome worse than not matching at all."""
        self._stub_details("900001", "Beta Voyager")
        archive = self._zip("AlphaForge.zip", {"AlphaForge/steam_settings/steam_appid.txt": "900001\n"})
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("Alpha Forge", archive_path=archive)
        self.assertFalse(result.found, "a stale AppID was believed and the folder would have been renamed")

    def test_a_punctuation_different_filename_still_matches_its_own_appid(self):
        """The whole point: this title needed a hand-written alias before, because the search could not see it
        through the flattened punctuation."""
        self._stub_details("3062660", "Gamma Quest")
        archive = self._zip("GammaQuest-Chill-Electronics-Repairs.zip", {"GammaQuest/steam_settings/steam_appid.txt": "3062660\n"})
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("Gamma Quest Chill Electronics Repairs", archive_path=archive)
        self.assertTrue(result.found)
        self.assertEqual(result.name, "Gamma Quest")

    def test_a_second_archive_with_the_same_title_is_read_for_its_own_appid(self):
        """The cache is keyed by title, so a title-keyed hit would hand the first archive's AppID to the second.

        An archive that states its own AppID is the authority on which game it is, and two archives can
        flatten onto one title while being different games. Whichever was scanned first would otherwise decide
        the name of the other, and the folder would be renamed to something it is not.
        """
        self._stub_details("200001", "Alpha Forge")
        self._stub_details("200002", "Alpha Forge II")
        first = self._zip("AlphaForge.zip", {"Game/steam_settings/steam_appid.txt": "200001\n"})
        second = self._zip("AlphaForgeII.rar", {"Game/steam_settings/steam_appid.txt": "200002\n"})
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        one = self.service.lookup("Alpha Forge", archive_path=first)
        two = self.service.lookup("Alpha Forge", archive_path=second)
        self.assertEqual(one.appid, "200001")
        self.assertEqual(two.appid, "200002", "the second archive was given the first archive's AppID")
        self.assertEqual(two.name, "Alpha Forge II")

    def test_an_archive_still_wins_over_a_cached_match_for_its_title(self):
        """The cache is still consulted for an archive that states no AppID, and still never for one that does."""
        self._stub_details("200001", "Alpha Forge")
        archive = self._zip("AlphaForge.zip", {"Game/steam_settings/steam_appid.txt": "200001\n"})
        # A match cached under this title by an earlier scan, for a different game entirely.
        self.service.cache["alphaforge"] = SteamMatch(found=True, appid="999", name="Unrelated")
        self.service._lookup_store = lambda title, ctx: SteamMatch(found=False)
        result = self.service.lookup("Alpha Forge", archive_path=archive)
        self.assertEqual(result.appid, "200001", "a stale cached title entry outranked the archive")
        # With no archive to read, the cache is still what answers - it is the fallback, not the dead path.
        self.assertEqual(self.service.lookup("Alpha Forge").appid, "200001")

    def test_the_scan_hands_the_archive_path_to_the_lookup(self):
        """The AppID is inside the file; a lookup that only receives the title can never see it."""
        import inspect
        from app.controller import AppController

        source = inspect.getsource(AppController.verify_all)
        self.assertIn("archive_path=a.path", source, "verify_all no longer passes the archive, so the shipped AppID is unreachable")

    def test_appmanifest_appid_is_read_from_filename_without_extraction(self):
        """An appmanifest_*.acf names its AppID in its filename; the listing already carries the answer.

        The old code ran `7z e -so` to extract the file content before reading the AppID from the
        filename. For a large solid archive that extraction hangs for minutes while 7z decompresses
        the solid block to the file's offset - the Corsair.Cove case, where the steam_appid.txt is
        buried ~14 GB deep and the call ran for the full 60-second timeout. Since the AppID is in
        the path the listing returned, return it immediately and skip extraction entirely.
        """
        archive = self.dir / "Game.7z"
        archive.write_bytes(b"")
        listing = subprocess.CompletedProcess(args=["7z", "l", "-slt", "--", str(archive)], returncode=0, stdout="Path = Game/steam_settings/appmanifest_1128810.acf\n Size = 100\n\n", stderr="")
        with patch.object(subprocess, "run", return_value=listing) as mock_run, patch.object(subprocess, "Popen") as mock_popen:
            result = self.service._appid_in_archive(archive, None)
            self.assertEqual(result, "1128810", "the AppID from the appmanifest filename was not returned")
            self.assertEqual(mock_run.call_count, 1, "7z was called for extraction in addition to listing; the appmanifest branch should return from the filename without a second 7z call")
            mock_popen.assert_not_called()

    def test_steam_appid_extraction_is_cancelable(self):
        """A hung 7z extraction must respond to cancellation, not block for the full 60-second timeout.

        Before the fix, `subprocess.run(timeout=60)` blocked the job thread with no checkpoint, so
        closing the window froze until the timeout expired or the process finished. Now the process is
        polled via Popen and ctx.checkpoint() is checked between polls, so a cancel kills the 7z
        process at once instead of making the user wait.
        """
        archive = self.dir / "Game.7z"
        archive.write_bytes(b"")
        listing = subprocess.CompletedProcess(args=["7z", "l", "-slt", "--", str(archive)], returncode=0, stdout="Path = Game/steam_settings/steam_appid.txt\n Size = 7\n\n", stderr="")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # process never finishes on its own
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.return_value = b""
        ctx = JobContext("cancel-test")
        calls = [0]
        original = ctx.checkpoint

        def checkpoint():
            calls[0] += 1
            if calls[0] > 1:
                ctx._cancel.set()
            original()

        ctx.checkpoint = checkpoint
        with patch.object(subprocess, "run", return_value=listing), patch.object(subprocess, "Popen", return_value=mock_proc):
            with self.assertRaises(CancellationError):
                self.service._appid_in_archive(archive, ctx)
        mock_proc.kill.assert_called_once()


class TestArtworkImageShape(unittest.TestCase):
    """Artwork shape used to be read by shelling out to ffprobe, and a missing ffprobe came back as "wide" - the
    same answer as a genuinely wrong-shaped image. Every caller deletes what it is told is the wrong shape, so on a
    machine with no ffmpeg (any PC) the cache emptied itself at startup and every portrait download was deleted the
    moment it landed. The Deck has ffmpeg, which is why the same library had pictures there and not here. These pin
    the two halves of the fix: the shape is read from the file itself, and an unreadable file is never deleted."""

    def _jpeg(self, width, height):
        """A minimal JPEG carrying just enough structure for the frame header to be found."""
        return b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xc0\x00\x10\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01" + b"\xff\xd9"

    def test_the_shape_is_read_out_of_the_file(self):
        from services.artwork_service import image_shape, shape_name

        with TemporaryDirectory() as d:
            root = Path(d)
            portrait = root / "portrait.jpg"
            portrait.write_bytes(self._jpeg(600, 900))
            wide = root / "wide.jpg"
            wide.write_bytes(self._jpeg(460, 215))
            self.assertIs(image_shape(portrait), True)
            self.assertIs(image_shape(wide), False)
            self.assertEqual([shape_name(image_shape(p)) for p in (portrait, wide)], ["portrait", "wide"])

    def test_an_unreadable_file_is_unknown_rather_than_wide(self):
        from services.artwork_service import image_shape, shape_name

        with TemporaryDirectory() as d:
            root = Path(d)
            truncated = root / "truncated.jpg"
            truncated.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00truncated")
            empty = root / "empty.jpg"
            empty.write_bytes(b"")
            self.assertIsNone(image_shape(truncated))
            self.assertIsNone(image_shape(empty))
            self.assertIsNone(image_shape(root / "never-written.jpg"))
            self.assertEqual(shape_name(None), "unknown")

    def test_a_portrait_cache_file_survives_startup_and_a_download(self):
        from services.artwork_service import ArtworkService

        with TemporaryDirectory() as d:
            root = Path(d)
            cache = root / "cache"
            service = ArtworkService(cache, AppLogger(root / "first.log"))
            keep = service.cached_path("123", steam=True)
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_bytes(self._jpeg(600, 900))
            # A second service is exactly what a second run of the app does: the startup sweep must leave this alone.
            ArtworkService(cache, AppLogger(root / "second.log"))
            self.assertTrue(keep.exists(), "a portrait primary was deleted as wrongly shaped")
            # And download() re-checks the same file before it will use it.
            ArtworkService(cache, AppLogger(root / "third.log")).download("123")
            self.assertTrue(keep.exists(), "download() deleted a portrait primary as wrongly shaped")

    def test_a_file_that_cannot_be_classified_is_kept(self):
        from services.artwork_service import ArtworkService

        with TemporaryDirectory() as d:
            root = Path(d)
            cache = root / "cache"
            service = ArtworkService(cache, AppLogger(root / "first.log"))
            unreadable = service.cached_path("456", steam=True)
            unreadable.parent.mkdir(parents=True, exist_ok=True)
            unreadable.write_bytes(b"not a jpeg at all")
            ArtworkService(cache, AppLogger(root / "second.log"))
            self.assertTrue(unreadable.exists(), "an unreadable cache file was deleted instead of looked at again")

    def test_lookup_falls_back_to_a_game_folder_when_cache_is_empty(self):
        # The cache is pruned after max_age_days; a re-scan with downloads off must still find
        # artwork the organizer copied into the game folder as <prefix>_grid.jpg.
        from services.artwork_service import ArtworkService
        from core.models import ArtworkResult

        with TemporaryDirectory() as d:
            root = Path(d)
            cache = root / "cache"
            game_dir = root / "games" / "Some Game - 2026-10-13"
            game_dir.mkdir(parents=True)
            # A minimal valid JPEG (portrait-shaped) so image_shape() passes the 1024-byte and
            # shape checks in lookup()'s game-folder fallback.
            grid = game_dir / "Some Game_grid.jpg"
            grid.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xc0\x00\x10\x08\x00\x01\x00\x10\x01\x00" + b"\x00" * 2048 + b"\xff\xd9")
            service = ArtworkService(cache, AppLogger(root / "artwork.log"))
            result = service.lookup("9999999", game_dir=game_dir)
            self.assertTrue(result.present(), "game-folder artwork was not found when cache was empty")
            empty_dir = root / "games" / "Empty Game"
            empty_dir.mkdir()
            result_empty = service.lookup("8888888", game_dir=empty_dir)
            self.assertFalse(result_empty.present(), "artwork was fabricated for a game with no files")


class TestTaggedTitlesReachTheStore(unittest.TestCase):
    """The tag stripper and the Steam lookup failed as a pair, and only fixing the stripper is not enough.

    normalize_name() produced the clean title, but _lookup_store() built its search query from the raw folder
    name, so the clean title was never asked for. The variants it did try were right-truncations of the tagged
    string - "Mars Attracts-Steam RIP com", "Mars Attracts-Steam RIP", "Mars Attracts-Steam" - and every one of
    them is a query the Steam Store has no answer to. These pin the wiring, so a future change that goes back to
    querying the raw name fails here rather than in a library scan."""

    QUERIES = {"Mars Attracts-Steam RIP com": "Mars Attracts", "Nivalis Nights-Steam RIP com": "Nivalis Nights", "Brave.New.Wonders-SteamRIP.com": "Brave New Wonders"}

    def test_the_query_variants_include_the_clean_title(self):
        with TemporaryDirectory() as d:
            service = SteamService(AppLogger(Path(d) / "steam.log"))
            from utils.filename_utils import normalize_name

            for tagged, clean in self.QUERIES.items():
                self.assertIn(clean, service._query_variants(normalize_name(tagged), tagged, None), tagged)

    def test_the_lookup_sends_the_clean_title_to_the_store(self):
        with TemporaryDirectory() as d:
            service = SteamService(AppLogger(Path(d) / "steam.log"))
            asked = []

            def fake(url, ctx=None):
                asked.append(url)
                return {"items": [{"id": 1, "name": "Unrelated"}]}

            service._request_json = fake
            service._details = lambda appid, ctx=None: {"name": "Unrelated"}
            service._lookup_store("Mars Attracts-Steam RIP com", None)
            # The first variant is the raw name, which is harmless; the clean one has to be in there too.
            self.assertTrue(any("Mars+Attracts" in url or "Mars%20Attracts" in url for url in asked), asked[:3])


class TestStoreApiInsteadOfScrapedHtml(unittest.TestCase):
    """The eight checks that used to be made against a scraped store page, now made against the JSON API.

    There is no HTML handler left to test - the service reads storesearch and appdetails instead of parsing a
    page - but what those tests were *for* still stands, and it is what these pin. A transport failure has to
    arrive as a diagnosable reason rather than as a crash or a bare "no match". A cancelled lookup has to stay
    cancelled instead of being laundered into a miss. And a cache that is corrupt or half-written must not be
    able to poison the next scan."""

    def service(self, root, **kwargs):
        return SteamService(AppLogger(Path(root) / "steam.log"), **kwargs)

    def test_a_store_http_error_is_reported_as_such_rather_than_as_no_match(self):
        # "No Steam Store search result" and "Steam answered 404" send an organizer down different paths, and only
        # the second is worth retrying, so the code has to survive to the log.
        from urllib.error import HTTPError
        from services.steam_service import _SHARED_POOL

        with TemporaryDirectory() as d:
            service = self.service(d)

            def fake_request(method, url, headers=None, body=None):
                raise HTTPError("https://store.steampowered.com", 404, "Not Found", {}, None)

            with patch.object(_SHARED_POOL, "request", side_effect=fake_request):
                result = service._lookup_store("Any Game", None)
            self.assertFalse(result.found)
            self.assertIn("Steam Store HTTP 404", result.reason)

    def test_a_transport_failure_is_reported_by_its_kind(self):
        # No network at all is ordinary - a Deck asleep, a captive portal - and the exception type is the only
        # thing in the log that says whether another attempt could ever help.
        from urllib.error import URLError
        from services.steam_service import _SHARED_POOL

        with TemporaryDirectory() as d:
            service = self.service(d)

            def fake_request(method, url, headers=None, body=None):
                raise URLError("name resolution failed")

            with patch.object(_SHARED_POOL, "request", side_effect=fake_request):
                result = service._lookup_store("Any Game", None)
            self.assertFalse(result.found)
            self.assertIn("Steam Store lookup failed: URLError", result.reason)

    def test_appdetails_failing_is_a_miss_and_not_an_exception(self):
        # The AppID is known but the name behind it is not. Raising here would abandon an entire scan over the one
        # game whose store page happened to be unavailable when the rest were fine.
        from urllib.error import URLError
        from services.steam_service import _SHARED_POOL

        with TemporaryDirectory() as d:
            service = self.service(d)

            def fake_request(method, url, headers=None, body=None):
                raise URLError("offline")

            with patch.object(_SHARED_POOL, "request", side_effect=fake_request):
                result = service._lookup_appid("1614040", None)
            self.assertFalse(result.found)
            self.assertEqual(result.reason, "Steam AppID details unavailable")

    def test_a_cancelled_lookup_is_not_laundered_into_a_miss(self):
        # A cancel is not a search that found nothing. Swallowing it would leave the game unmatched, and every
        # later scan would report it as a game Steam does not have rather than one the user stopped looking for.
        from services.steam_service import _SHARED_POOL

        with TemporaryDirectory() as d:
            service = self.service(d)

            def fake_request(method, url, headers=None, body=None):
                raise CancellationError("cancelled")

            with patch.object(_SHARED_POOL, "request", side_effect=fake_request):
                with self.assertRaises(CancellationError):
                    service.lookup("Any Game")
                with self.assertRaises(CancellationError):
                    service._details("1614040", None)

    def test_a_corrupt_cache_file_leaves_the_cache_empty_rather_than_raising(self):
        # The cache is written to a temp file and replaced precisely so it cannot be half-written, but a file
        # truncated by a kill during that rename is still a file this has to open on the next run.
        with TemporaryDirectory() as d:
            cache = Path(d) / "steam-matches.json"
            cache.write_text('{"prisonarchitect": {"found": tru')
            service = self.service(d, cache_file=cache)
            self.assertEqual(service.cache, {})
            service._lookup_store = lambda title, ctx: SteamMatch(found=True, appid="1614040", name="Prison Architect")
            self.assertTrue(service.lookup("Prison Architect").found, "a corrupt cache file stopped the lookup entirely")

    def test_cache_rows_that_are_not_a_usable_match_are_discarded(self):
        # A row that cannot be trusted is worse than no row at all: it would then be served from cache indefinitely,
        # and a non-numeric appid is a broken store link rather than a slow one.
        import json

        with TemporaryDirectory() as d:
            cache = Path(d) / "steam-matches.json"
            cache.write_text(json.dumps({"kept": {"found": True, "appid": "123", "name": "Example"}, "unfound": {"found": False, "appid": "123", "name": "Example"}, "notanid": {"found": True, "appid": "abc", "name": "Example"}, "noname": {"found": True, "appid": "123", "name": ""}, "notadict": "Example"}))
            service = self.service(d, cache_file=cache)
            self.assertEqual(sorted(service.cache), ["kept"])

    def test_an_empty_title_never_scores_as_a_match(self):
        # An empty name reaching the scorer means a store row that carried none. Scoring zero against nothing is
        # how such a row ends up winning a ranked list of real games.
        with TemporaryDirectory() as d:
            service = self.service(d)
            self.assertEqual(service._score("", "Prison Architect"), 0.0)
            self.assertEqual(service._score("Prison Architect", ""), 0.0)
            chosen, score = service._choose([{"id": "1", "name": ""}], "Prison Architect")
            self.assertIsNone(chosen, "an unnamed store row was accepted as the match")

    def test_a_numeral_beyond_the_conversion_table_is_refused(self):
        # The tables stop at 39, the highest numeral with a single-character form. Past that the swap has to decline
        # rather than invent a numeral the store has never been indexed under.
        with TemporaryDirectory() as d:
            service = self.service(d)
            self.assertEqual(service._to_roman(40), "")
            self.assertEqual(service._from_roman("XL"), 0)
            self.assertEqual(service._swap_trailing_numeral("Some Game 40"), "")

    def test_a_short_trailing_abbreviation_does_not_sink_a_match(self):
        # Scene release groups abbreviate subtitles: "Voyager AtU" for "Across the Unknown",
        # "AiO" for "All in One". The Steam search still finds the game via a prefix variant,
        # but the scorer compares the full query. A lone short token the rest of the query
        # already matches on should not reject the right game.
        with TemporaryDirectory() as d:
            service = self.service(d)
            name = "Star Trek Voyager - Across the Unknown"
            self.assertGreater(service._score("Star Trek Voyager AtU", name), 0.78, "abbreviation token should not sink a match the search already found")
            chosen, score = service._choose([{"id": "2643390", "name": name}], "Star Trek Voyager AtU")
            self.assertIsNotNone(chosen, "the right game was ranked out by an abbreviation token")

    def test_a_short_trailing_abbreviation_still_rejects_unrelated_games(self):
        # The abbreviation tolerance only fires when dropping it leaves a subset of the name
        # tokens. A genuinely different game must still be rejected.
        with TemporaryDirectory() as d:
            service = self.service(d)
            self.assertLess(service._score("Some Game AiO", "Different Title"), 0.78, "unrelated games should not be rescued by the abbreviation rule")


class TestAuditProgress(unittest.TestCase):
    """The audit pass is the slowest part of a scan - it fetches artwork for every game folder in the library over
    the network - and it reported nothing at all while doing it. The screen showed one line, "Refreshing artwork
    and Steam links for the library", and then sat there for minutes looking hung. These pin the progress channel
    that replaced it."""

    def _library(self, root, names):
        for name in names:
            game = root / "Adventure" / name
            game.mkdir(parents=True)
            (game / ".game-info.json").write_text('{"appid":"777","name":"%s"}' % name.split(" - ")[0])
        return root

    def _services(self, root):
        logger = AppLogger(root / "log.log")
        artwork = type("Artwork", (), {"download_assets": lambda *a, **k: ArtworkResult()})()
        return LibraryService(logger), artwork, OrganizerService(logger)

    def test_it_reports_the_total_before_it_starts(self):
        with TemporaryDirectory() as d:
            root = self._library(Path(d), ["A - 2020-01-01", "B - 2020-01-02", "C - 2020-01-03"])
            library, artwork, organizer = self._services(root)
            seen = []
            library.audit(root, artwork, organizer, None, on_progress=seen.append)
            self.assertEqual(seen[0]["stage"], "audit_plan")
            self.assertEqual(seen[0]["total"], 3, "the total has to be known up front for the bar to mean anything")

    def test_it_reports_every_folder_it_checks(self):
        with TemporaryDirectory() as d:
            root = self._library(Path(d), ["Alpha - 2020-01-01", "Beta - 2020-01-02"])
            library, artwork, organizer = self._services(root)
            seen = []
            library.audit(root, artwork, organizer, None, on_progress=seen.append)
            items = [event for event in seen if event.get("stage") == "audit_item"]
            self.assertEqual([event["index"] for event in items], [1, 2], "one line per folder, in order")
            self.assertTrue(all(event["total"] == 2 for event in items))
            self.assertIn("Alpha - 2020-01-01", items[0]["message"])
            self.assertTrue(any(event.get("state") == "done" for event in items), "no folder ever reported an outcome")

    def test_a_folder_with_no_appid_says_so_rather_than_going_quiet(self):
        # The usual reason a game shows no picture is that nothing could be looked up for it, and that is worth
        # saying out loud instead of letting the folder pass as 'up to date'.
        with TemporaryDirectory() as d:
            root = Path(d) / "lib"
            (root / "Adventure" / "Mystery Game - 2020-01-01").mkdir(parents=True)
            library, artwork, organizer = self._services(root)
            seen = []
            library.audit(root, artwork, organizer, None, on_progress=seen.append)
            items = [event for event in seen if event.get("stage") == "audit_item"]
            self.assertEqual(len(items), 1)
            self.assertIn("no Steam AppID", items[0]["message"])

    def test_a_download_outcome_is_relayed_but_a_start_is_not(self):
        # Relaying every 'started' report would put a second line per folder saying nothing on a library this size.
        with TemporaryDirectory() as d:
            root = self._library(Path(d), ["Alpha - 2020-01-01"])
            library, artwork, organizer = self._services(root)
            seen = []
            artwork.download_assets = lambda *a, **k: [k["on_progress"]({"asset": "cover", "state": "start", "detail": ""}), k["on_progress"]({"asset": "cover", "state": "downloaded", "detail": "42 KB"}), k["on_progress"]({"asset": "hero", "state": "failed", "detail": "HTTPError"})][-1] or ArtworkResult()
            library.audit(root, artwork, organizer, None, on_progress=seen.append)
            messages = [event["message"] for event in seen if event.get("stage") == "audit_item"]
            self.assertTrue(any("downloaded" in message for message in messages), messages)
            self.assertTrue(any("failed" in message for message in messages), messages)
            self.assertFalse(any("start" in message for message in messages), messages)

    def test_a_broken_progress_sink_cannot_abort_the_pass(self):
        # The pass rewrites Steam links and artwork across the whole library; a display callback that throws must
        # never leave half the library done.
        with TemporaryDirectory() as d:
            root = self._library(Path(d), ["Alpha - 2020-01-01", "Beta - 2020-01-02", "Gamma - 2020-01-03"])
            library, artwork, organizer = self._services(root)

            def explode(event):
                raise RuntimeError("the UI went away")

            stats = library.audit(root, artwork, organizer, None, on_progress=explode)
            self.assertEqual(stats["checked"], 3, "a throwing callback aborted the audit")
            for name in ("Alpha - 2020-01-01", "Beta - 2020-01-02", "Gamma - 2020-01-03"):
                self.assertTrue((root / "Adventure" / name / "Open Steam Page.html").exists(), name)

    def test_the_audit_still_returns_its_counts_without_a_sink(self):
        with TemporaryDirectory() as d:
            root = self._library(Path(d), ["Alpha - 2020-01-01"])
            library, artwork, organizer = self._services(root)
            self.assertEqual(library.audit(root, artwork, organizer)["checked"], 1)


class TestPartialArchiveSafety(unittest.TestCase):
    """An interrupted conversion used to leave a partial archive wearing its final name.

    Dedupe then preferred that partial file over the intact source - the promotion rule trusts .7z over
    .zip/.rar - and moved the good copy to Archive. Three games lost their archive this way, so these pin
    each of the three guards that now prevent it."""

    def game_folder(self, root, name="Atomic Game", stems=("Atomic.Game.v1",)):
        game = root / "Adventure" / name
        game.mkdir(parents=True)
        (game / ".game-info.json").write_text('{"appid":"606","name":"%s"}' % name)
        return game

    def make_zip(self, game, stem, payload=b"game-content" * 40):
        path = game / f"{stem}.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(f"{stem}/game/main.exe", payload)
        return path

    def candidate(self, library, path, name="Atomic Game"):
        from services.library_service import _RepairArchive

        return _RepairArchive(path, "606", name)

    def test_a_partial_build_never_appears_under_the_final_name(self):
        # The whole failure started here: the .rar/.zip -> .7z build wrote straight to "Name.7z", so an
        # interrupted build was indistinguishable from a finished one by name alone.
        observed = []
        original = OrganizerService._run_tool

        def spy(self, args, stage, report, **kw):
            if stage == "compressing" and not observed:
                target = kw.get("cwd") and Path(kw["cwd"]).parent / Path(args[-2]).name
                observed.append(target.exists())
            return original(self, args, stage, report, **kw)

        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root)
            self.make_zip(game, "Atomic.Game.v1")
            OrganizerService._run_tool = spy
            try:
                library = LibraryService(AppLogger(root / "log.log"))
                converted = library.convert_pending_archives(root, OrganizerService(AppLogger(root / "log.log")), JobContext("T"), unlocker=None)
            finally:
                OrganizerService._run_tool = original
            self.assertEqual(converted, 1, "the conversion did not run")
            self.assertEqual(observed, [False], "the final .7z name existed while the build was still running, so an interrupted build would look like a complete archive to anything scanning the folder")

    def test_the_replacement_is_built_outside_the_game_folder(self):
        # The staging folder exists so a game folder being converted holds only its source. Anything reading
        # the folder - dedupe, the catalog, Syncthing, the user in a file browser - then sees an untouched
        # folder instead of one containing a half-written archive competing with the good copy.
        seen = []
        original = OrganizerService._run_tool

        def spy(self, args, stage, report, **kw):
            if stage == "compressing" and not seen:
                processing = root / "Processing"
                seen.append(
                    {
                        # .game-info.json is the folder's own metadata, not something the build adds.
                        "archives": sorted(a.name for a in game.iterdir() if a.is_file() and not a.name.startswith(".")),
                        "processing": processing.is_dir(),
                        "staged": sorted(p.name for p in processing.iterdir()) if processing.is_dir() else [],
                        "extracted": any(p.is_dir() for p in processing.glob("*")) if processing.is_dir() else False,
                    }
                )
            return original(self, args, stage, report, **kw)

        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Stage Game")
            source = self.make_zip(game, "Stage.Game.v1")
            OrganizerService._run_tool = spy
            try:
                converted = LibraryService(AppLogger(root / "log.log")).convert_pending_archives(root, OrganizerService(AppLogger(root / "log.log")), JobContext("T"), unlocker=None)
            finally:
                OrganizerService._run_tool = original
            self.assertEqual(converted, 1)
            self.assertEqual(len(seen), 1, "the compressing stage was never observed")
            state = seen[0]
            self.assertEqual(state["archives"], [source.name], "the game folder held extra files while the replacement was being built")
            self.assertTrue(state["processing"], "no Processing folder was used for staging")
            self.assertEqual(len(state["staged"]), 1, "expected exactly one staging folder for this conversion")
            # The extraction lives in the staging folder too, so the game folder holds nothing of ours at any
            # point: not the multi-GB working set, not the build.
            self.assertTrue(state["extracted"], "the extracted files were written into the game folder")
            self.assertTrue((game / "Stage.Game.v1.7z").is_file(), "the converted archive was not published")

    def test_the_staging_folder_is_reclaimed_after_a_conversion(self):
        # A stranded staging folder holds a full extra copy of the archive, so it is disk the library cannot
        # afford to lose and must not be left behind on the success or the failure path.
        for label, break_it in (("success", False), ("failure", True)):
            with self.subTest(outcome=label), TemporaryDirectory() as d:
                root = Path(d)
                game = self.game_folder(root, "Reclaim Game")
                self.make_zip(game, "Reclaim.Game.v1")
                organizer = OrganizerService(AppLogger(root / "log.log"))
                original = OrganizerService._run_tool
                if break_it:

                    def failing(self, args, stage, report, _original=original, **kw):
                        if stage == "compressing":
                            raise OSError("simulated build failure")
                        return _original(self, args, stage, report, **kw)

                    OrganizerService._run_tool = failing
                try:
                    LibraryService(AppLogger(root / "log.log")).convert_pending_archives(root, organizer, JobContext("T"), unlocker=None)
                finally:
                    OrganizerService._run_tool = original
                processing = root / "Processing"
                leftovers = list(processing.iterdir()) if processing.is_dir() else []
                self.assertEqual(leftovers, [], "a staging folder survived the conversion")

    def test_the_processing_folder_is_removed_once_the_conversion_is_done(self):
        # The folder is the app's own scratch area, so an empty Processing/ left in the library root is litter
        # the user has to notice and delete by hand. It must be gone once the last conversion has finished.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Scratch Game")
            self.make_zip(game, "Scratch.Game.v1")
            organizer = OrganizerService(AppLogger(root / "log.log"))
            converted = LibraryService(AppLogger(root / "log.log")).convert_pending_archives(root, organizer, JobContext("T"), unlocker=None)
            self.assertEqual(converted, 1, "the conversion did not run")
            self.assertFalse((root / "Processing").exists(), "the Processing folder was left in the library root")

    def test_the_processing_folder_is_kept_while_a_build_is_still_staged_in_it(self):
        # Removal is rmdir, never rmtree. A staging folder abandoned by a killed run can hold the only copy of a
        # partially built archive, and a second instance of this app can be converting into the same folder right
        # now, so cleanup has to leave those alone and let the next scan reclaim them.
        with TemporaryDirectory() as d:
            root = Path(d)
            staged = root / "Processing" / ".organizer-repack-abandoned"
            staged.mkdir(parents=True)
            (staged / "Some Game v1.7z").write_bytes(b"x" * 100)
            organizer = OrganizerService(AppLogger(root / "log.log"))
            self.assertFalse(organizer.cleanup_processing_dir(root), "cleanup claimed to have removed a staged build")
            self.assertTrue((staged / "Some Game v1.7z").is_file(), "cleanup deleted a staged build")
            (staged / "Some Game v1.7z").unlink()
            staged.rmdir()
            self.assertTrue(organizer.cleanup_processing_dir(root), "cleanup did not remove the emptied folder")
            self.assertFalse((root / "Processing").exists(), "the emptied Processing folder survived")

    def test_the_processing_folder_is_not_treated_as_a_game_category(self):
        # It sits beside the categories, so every scan that walks the library root has to skip it or staged
        # builds show up as games.
        with TemporaryDirectory() as d:
            root = Path(d)
            staged = root / "Processing" / ".organizer-repack-j1"
            staged.mkdir(parents=True)
            (staged / "Some Game v1.7z").write_bytes(b"x" * 100)
            (staged / "Some Game v1.zip").write_bytes(b"y" * 100)
            (staged / "Game.7z").write_bytes(b"z" * 100)
            service = LibraryService(AppLogger(root / "log.log"))
            moved = service.enforce_single_archive(root, OrganizerService(AppLogger(root / "log.log")))
            self.assertEqual(moved, 0, "the Processing folder was scanned as a game category")
            self.assertTrue((staged / "Some Game v1.7z").is_file(), "a staged archive was moved out of staging")
            self.assertTrue((staged / "Some Game v1.zip").is_file(), "a staged archive was moved out of staging")

    def test_a_live_build_is_not_deleted_by_a_concurrent_scan(self):
        # The extraction folder was protected by its lock marker, but the half-built replacement was not: the
        # staleness test only ran on directories, so a scan beside a conversion deleted a build that had been
        # running for hours. The pid is in the file's name, which is all it takes to tell a live build from an
        # abandoned one.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Live Build Game")
            live = game / f"Live.Build.v1.organizer-temp.{os.getpid()}.7z"
            live.write_bytes(b"partial build" * 200)
            dead = game / "Dead.Build.v1.organizer-temp.999999.7z"
            dead.write_bytes(b"abandoned build" * 200)
            os.utime(dead, (0, 0))  # old enough that a dead owner really does mean abandoned
            LibraryService(AppLogger(root / "log.log")).cleanup_leftovers(root)
            self.assertTrue(live.is_file(), "a build that is still being written was deleted by a scan")
            self.assertFalse(dead.exists(), "an abandoned build was left behind")
            # Same rule as the extraction folder: a dead pid alone is not enough, because a recycled pid could
            # belong to a build that started seconds ago. The grace window is what separates the two.
            young = game / "Young.Build.v1.organizer-temp.999999.7z"
            young.write_bytes(b"recent" * 100)
            LibraryService(AppLogger(root / "log.log")).cleanup_leftovers(root)
            self.assertTrue(young.is_file(), "a build younger than the grace window was deleted on a dead pid alone")

    def test_a_scan_never_offers_in_flight_work_as_a_game(self):
        # The extraction folder lives inside the game folder, and a game archive can legitimately contain an
        # archive of its own. Offering that nested file - or the half-built replacement - as a game put temp
        # artefacts into the review queue under names of their own, and an Organize press would then file one
        # under a category as if it were a separate game.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Nested Game")
            source = self.make_zip(game, "Nested.Game.v1")
            extracting = game / ".organizer-repack-live"
            extracting.mkdir()
            with zipfile.ZipFile(extracting / "Inner Disk.zip", "w") as zf:
                zf.writestr("inner/data.bin", b"y" * 512)
            build = game / f"Nested.Game.v1.organizer-temp.{os.getpid()}.7z"
            build.write_bytes(b"partial" * 100)
            found = ArchiveService(AppLogger(root / "log.log")).discover(root).archives
            self.assertEqual([archive.path for archive in found], [source], "a scan offered the extraction folder contents or the in-flight build as games")

    def test_conversion_still_works_without_a_library_root(self):
        # Callers that cannot name the library root must not be left unable to convert; they stage beside the
        # source under the temp tag, which is the older, still-safe behaviour.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "No Root Game")
            source = self.make_zip(game, "No.Root.Game.v1")
            organizer = OrganizerService(AppLogger(root / "log.log"))
            after = organizer._repack_with_official_name(self.candidate(None, source))
            self.assertEqual(after.name, "No.Root.Game.v1.7z")
            self.assertTrue(after.is_file(), "the archive was not published")
            self.assertFalse(source.exists(), "the source was not cleaned up")
            self.assertFalse((game / "Processing").exists(), "staging must not appear inside a game folder")

    def test_the_source_survives_if_publishing_the_result_fails(self):
        # The order matters. Unlinking the source first meant a failed replace destroyed the only copy.
        original_replace = os.replace

        def failing(src, dst, *a, **kw):
            raise OSError("simulated publish failure")

        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root)
            source = self.make_zip(game, "Atomic.Game.v1")
            organizer = OrganizerService(AppLogger(root / "log.log"))
            os.replace = failing
            try:
                try:
                    organizer._repack_with_official_name(self.candidate(None, source))
                except OSError:
                    pass
            finally:
                os.replace = original_replace
            self.assertTrue(source.is_file(), "the source archive was destroyed when publishing the result failed")

    def test_dedupe_leaves_a_folder_alone_while_a_conversion_is_running(self):
        # Mid-repack the folder legitimately holds the source and the half-written replacement. Neither is an
        # extra copy, and archiving the source is what pulled a live archive out from under a running build.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Busy Game")
            source = game / "Busy.Game.v1.zip"
            source.write_bytes(b"source")
            other = game / "Busy.Game.v1.7z"
            other.write_bytes(b"partial build")
            busy = game / ".organizer-repack-live"
            busy.mkdir()
            (busy / ".organizer-lock").write_text(f"{os.getpid()} {time.time():.0f}\n")
            service = LibraryService(AppLogger(root / "log.log"))
            moved = service.enforce_single_archive(root, OrganizerService(AppLogger(root / "log.log")))
            self.assertEqual(moved, 0, "a folder with a conversion in progress was modified")
            self.assertTrue(source.is_file(), "the in-flight source archive was moved out from under the conversion")
            self.assertTrue(other.is_file(), "the in-flight build was moved")

    def test_dedupe_still_collapses_once_the_conversion_is_dead(self):
        # The guard must not become a permanent exemption, or two archives would sit in a folder forever.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Dead Game")
            source = game / "Dead.Game.v1.zip"
            source.write_bytes(b"source" * 100)
            other = game / "Dead.Game.v1.7z"
            other.write_bytes(b"x" * 100)
            stale = game / ".organizer-repack-dead"
            stale.mkdir()
            # A pid that cannot be running, and older than the grace window.
            (stale / ".organizer-lock").write_text(f"{999999999} 1\n")
            service = LibraryService(AppLogger(root / "log.log"))
            moved = service.enforce_single_archive(root, OrganizerService(AppLogger(root / "log.log")))
            self.assertEqual(moved, 1, "a folder abandoned by a dead conversion should still collapse")
            self.assertFalse(source.exists(), "the redundant archive should have been archived")

    def test_nothing_is_archived_when_the_newest_archive_is_an_empty_stub(self):
        # Promoting an empty or missing stub leaves the folder with no usable archive at all, which is how the
        # original bug emptied a game folder. Refusing to archive is the only safe answer.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = self.game_folder(root, "Stub Game")
            source = game / "Stub.Game.v1.zip"
            source.write_bytes(b"real content" * 100)
            # Stamped newer explicitly: the shape an interrupted build leaves behind is the newest file in
            # the folder, and a zero-byte one at that. Left to natural mtimes the two can tie and the test
            # would pass or fail depending on which way the tie broke.
            stub = game / "Stub.Game.v1.7z"
            stub.write_bytes(b"")
            os.utime(stub, (time.time() + 60, time.time() + 60))
            self.assertEqual(max([source, stub], key=OrganizerService(AppLogger(root / "log.log"))._path_promotion_key), stub, "this test only means something if the stub is the one that wins promotion")
            service = LibraryService(AppLogger(root / "log.log"))
            moved = service.enforce_single_archive(root, OrganizerService(AppLogger(root / "log.log")))
            self.assertEqual(moved, 0, "an archive was moved aside on the strength of an empty file")
            self.assertTrue(source.is_file(), "the only usable archive was archived")


class TestSteamLink(unittest.TestCase):
    """One shortcut per game, in the one format every platform opens. A .desktop only launches on Linux and a
    Windows .url only on Windows, so the pair that shipped before meant two files where each platform ignored
    half of them, and no cleanup of the old names."""

    def test_one_html_link_is_written_and_both_old_files_are_removed(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Adventure" / "Linked Game - 2024-01-01"
            game.mkdir(parents=True)
            # Left over from the previous scheme, including an older naming round.
            (game / "Open Steam Page (Steam Deck).desktop").write_text("old deck")
            (game / "Open Steam Page (Windows).url").write_text("old windows")
            (game / "Open Steam Page.desktop").write_text("oldest")
            service = OrganizerService(AppLogger(root / "log.log"))
            link = service.write_steam_links(game, "4242", "Linked Game")
            self.assertEqual(link.name, "Open Steam Page.html", "the shortcut is not a single portable html file")
            self.assertTrue(link.is_file())
            body = link.read_text(encoding="utf-8")
            # A meta-refresh opens it in whatever the default browser is on SteamOS or Windows, and the
            # visible link is the fallback if the browser blocks the automatic redirect.
            self.assertIn('http-equiv="refresh"', body)
            self.assertIn("https://store.steampowered.com/app/4242/", body)
            self.assertIn('<a href="https://store.steampowered.com/app/4242/">', body)
            self.assertNotIn("\n-2024-01-01", body, "the folder date leaked into the page title")
            for legacy in service.LEGACY_LINK_NAMES:
                self.assertFalse((game / legacy).exists(), f"the old {legacy} was left behind")

    def test_no_appid_writes_nothing(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Adventure" / "No Id - 2024-01-01"
            game.mkdir(parents=True)
            self.assertIsNone(OrganizerService(AppLogger(root / "log.log")).write_steam_links(game, None))


class TestConversionToggle(unittest.TestCase):
    """Conversion is the expensive part of a scan - it can run for an hour and needs three times the archive
    size in free disk - so it has to be switchable without switching off the scan. It is on by default,
    because that is the behaviour every existing settings file and every existing user already had."""

    def config(self, **settings):
        with TemporaryDirectory() as d:
            return AppConfig(Path(d), settings=dict(settings))

    def test_conversion_is_on_when_no_setting_has_been_saved(self):
        # A settings file written by an earlier version has no convert_archives key at all. Reading it as
        # False would silently stop converting for every existing user on upgrade.
        self.assertTrue(self.config().convert_archives)

    def test_the_toggle_survives_a_restart(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            first = AppConfig(root)
            first.convert_archives = False
            second = AppConfig(root)  # a fresh instance reads the same settings file
            self.assertFalse(second.convert_archives)
            second.convert_archives = True
            self.assertTrue(AppConfig(root).convert_archives)

    def test_an_unmatched_7z_is_not_extracted_only_to_be_thrown_away(self):
        """The expensive half of the conversion ran for archives that could not possibly be rebuilt.

        `_repack_with_official_name` extracts the whole archive because the one thing that can make a
        rebuild worthwhile is renaming the generic content folder inside it to the official Steam name - and
        that rename is guarded by `archive.steam.found`. An archive with no Steam match can never be renamed,
        so for those the extraction was guaranteed to be discarded: a full 7z integrity read, then a full
        multi-GB write of the extracted tree to staging, then `return path` and the staging folder wiped.

        On a library of games the app itself converted and never matched, that is hours of I/O per run for no
        change to any file. It is worse than slow when the volume is short of space: the extraction fails, and
        the game is filed under FAILED - "7z could not extract this archive" - for an archive that was never
        going to be touched.
        """
        from services.extract_service import ExtractService

        if not ExtractService.find_tool()[0]:
            self.fail("7-Zip is required to build the fixture archive and was not found")
        with TemporaryDirectory() as d:
            root = Path(d)
            library = root / "Games"
            game = library / "Adventure" / "Unmatched Game - 2024-01-01"
            game.mkdir(parents=True)
            payload = root / "_payload" / "Unmatched Game v1" / "game"
            payload.mkdir(parents=True)
            (payload / "main.exe").write_bytes(b"binary" * 500)
            source = game / "Unmatched Game v1.7z"
            sevenzip = ExtractService.find_tool()[0]
            built = subprocess.run([sevenzip, "a", "-t7z", "-bso0", "-bsp0", str(source), str(payload.parent)], stdin=subprocess.DEVNULL, capture_output=True)
            self.assertEqual(built.returncode, 0, f"could not build the fixture archive: {built.stderr!r}")
            before = source.stat().st_size
            events = []
            # No AppID, which is what "the scan could not match this game" looks like to this routine.
            service = OrganizerService(AppLogger(root / "log.log"), convert_archives=lambda: True)
            result = service._repack_with_official_name(_RepairArchive(source, "", "Unmatched Game"), on_progress=events.append, library_root=library)
            stages = [event.get("stage") for event in events]
            self.assertNotIn("extracting", stages, f"an archive that cannot be rebuilt was extracted anyway; stages were {stages}")
            self.assertNotIn("compressing", stages, f"an archive that cannot be rebuilt was rebuilt anyway; stages were {stages}")
            self.assertEqual(result, source, "the archive should have been left exactly where it was")
            self.assertEqual(source.stat().st_size, before, "the untouched archive changed size")
            leftovers = [p.name for p in library.rglob(".organizer-*")]
            self.assertEqual(leftovers, [], f"the skipped conversion left staging folders behind: {leftovers}")

    def test_the_skipped_conversion_still_finishes_the_stage_it_started(self):
        """A conversion that decided to do nothing never said so, so the run's progress display never ended.

        `stage='converted'`, `'failed'` and `'skipped'` are the terminal stages the organize view acts on: it
        marks the timeline done and closes the conversion count on those and nothing else. The "already a .7z
        and the folder is named correctly" branch returned without emitting any of them, so the pill stayed on
        EXTRACTING and the feed had no line for that game. On the last game of a run that is a run that
        finishes looking stuck.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            library = root / "Games"
            game = library / "Adventure" / "Settled Game - 2024-01-01"
            game.mkdir(parents=True)
            source = game / "Settled Game v1.7z"
            with zipfile.ZipFile(source, "w") as archive:  # contents are never read; only the suffix matters
                archive.writestr("Settled Game v1/game/main.exe", "binary")
            events = []
            service = OrganizerService(AppLogger(root / "log.log"), convert_archives=lambda: True)
            with patch.object(service, "_source_is_intact", return_value=True), patch.object(service, "_run_tool", return_value=(0, "")) as run_tool:
                service._repack_with_official_name(_RepairArchive(source, "", "Settled Game"), on_progress=events.append, library_root=library)
            run_tool.assert_not_called()
            stages = [event.get("stage") for event in events]
            self.assertTrue(stages, "the conversion reported nothing at all")
            self.assertIn(stages[-1], ("converted", "failed", "skipped"), f"the last stage was {stages[-1]!r}, which the organize view does not treat as finished, so the timeline stays on the stage it had reached")

    def test_a_matched_7z_that_needs_no_rename_still_finishes_its_stage(self):
        """The other "nothing to do" branch: Steam matched, but the folder inside is already named right.

        Separate from the test above because that one is settled earlier, before any extraction. This branch is
        only reachable once the archive has been extracted and inspected, which is why removing its report
        alone leaves the other test green - and why this one has to exist for the behaviour to be covered.
        """
        with TemporaryDirectory() as d:
            root = Path(d)
            library = root / "Games"
            game = library / "Adventure" / "Named Game - 2024-01-01"
            game.mkdir(parents=True)
            source = game / "Named Game v1.7z"
            with zipfile.ZipFile(source, "w") as archive:  # only the suffix is read; extraction is stubbed
                archive.writestr("Named Game/game/main.exe", "binary")
            events = []
            service = OrganizerService(AppLogger(root / "log.log"), convert_archives=lambda: True)
            with patch.object(service, "_source_is_intact", return_value=True), patch.object(service, "_extraction_is_short", return_value=False), patch.object(service, "_run_tool", return_value=(0, "")), patch.object(service, "_find_generic_content_folder", return_value=None):
                result = service._repack_with_official_name(_RepairArchive(source, "999", "Named Game"), on_progress=events.append, library_root=library)
            stages = [event.get("stage") for event in events]
            self.assertIn("extracting", stages, "the archive should have been extracted before deciding")
            self.assertEqual(result, source)
            self.assertIn(stages[-1], ("converted", "failed", "skipped"), f"the last stage was {stages[-1]!r}, which the organize view does not treat as finished, so the timeline stays on the stage it had reached")

    def test_organizing_still_moves_the_archive_when_conversion_is_off(self):
        # Turning conversion off must never block organizing a game. The archive lands in its game folder
        # in its original format, which is the whole point of the toggle.
        with TemporaryDirectory() as d:
            root = Path(d)
            game = root / "Adventure" / "Toggle Game - 2024-01-01"
            game.mkdir(parents=True)
            (game / ".game-info.json").write_text('{"appid":"321","name":"Toggle Game"}')
            source = game / "Toggle Game v1.zip"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("Toggle Game v1/game/main.exe", "binary")
            library = LibraryService(AppLogger(root / "log.log"))
            candidates = library.pending_candidates(root)
            self.assertEqual(len(candidates), 1)
            _game_dir, path, _size, appid, name = candidates[0]
            events = []
            service = OrganizerService(AppLogger(root / "log.log"), convert_archives=False)
            result = service._repack_with_official_name(_RepairArchive(path, appid, name), on_progress=events.append)
            # The service-level toggle covers the repair pass; organizing itself is covered below because
            # move() owns a different code path.
            self.assertEqual(result, path)

    def test_moving_an_archive_with_conversion_off_keeps_its_format(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            library_root = root / "Games"
            library_root.mkdir()
            source = library_root / "Toggle Game v1.zip"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("Toggle Game v1/game/main.exe", "binary")
            item = GameArchive(source, "Toggle Game", "Toggle Game v1", "togglegame", ".zip")
            item.decision.accepted = True
            item.decision.category = "Adventure"
            item.steam = SteamMatch(found=True, appid="321", name="Toggle Game")
            events = []
            service = OrganizerService(AppLogger(root / "log.log"), convert_archives=False)
            target = service.move(item, library_root, on_progress=events.append)
            self.assertEqual(target.suffix, ".zip", f"the archive was converted anyway: {target.name}")
            self.assertTrue(target.is_file(), "the archive was not moved into its game folder")
            self.assertIn("skipped", [e.get("stage") for e in events], f"the skip was not reported to the user: {[e.get('stage') for e in events]}")
            # And with conversion on, the same move produces a 7z.
            other = library_root / "Other Game v1.zip"
            with zipfile.ZipFile(other, "w") as zf:
                zf.writestr("Other Game v1/game/main.exe", "binary")
            second = GameArchive(other, "Other Game", "Other Game v1", "othergame", ".zip")
            second.decision.accepted = True
            second.decision.category = "Adventure"
            second.steam = SteamMatch(found=True, appid="322", name="Other Game")
            enabled = OrganizerService(AppLogger(root / "log.log"), convert_archives=True)
            self.assertEqual(enabled.move(second, library_root).suffix, ".7z")

    def test_the_service_reads_the_setting_at_the_moment_of_use(self):
        # The service is built once at startup but the control is a live checkbox, so a stale snapshot taken
        # at construction would mean toggling it had no effect until the app was restarted.
        current = [True]
        with TemporaryDirectory() as d:
            service = OrganizerService(AppLogger(Path(d) / "l.log"), convert_archives=lambda: current[0])
            self.assertTrue(service.convert_archives)
            current[0] = False
            self.assertFalse(service.convert_archives, "the service kept a stale copy of the setting")


class TestAdaptiveCompression(unittest.TestCase):
    """The compressor must reach for maximum compression only when the machine can sustain it. Level 9
    needs ~2.5 GB of match finder; picking it regardless of headroom is what killed builds on a busy
    Steam Deck session, so both the headroom check and the step-down retry are pinned here."""

    def service(self):
        return OrganizerService.__new__(OrganizerService)

    def test_level_nine_is_used_when_memory_is_plentiful(self):
        service = self.service()
        service._available_ram = lambda: (12 * GB, 8 * GB)
        self.assertEqual(service._choose_compression_level(), 9)

    def test_level_steps_down_until_the_match_finder_fits(self):
        service = self.service()
        # 1.2 GB of RAM cannot hold the 1.4 GB a level 7 build needs, but a level 6 one is a comfortable fit.
        service._available_ram = lambda: (int(1.2 * GB), 8 * GB)
        self.assertEqual(service._choose_compression_level(), 6)

    def test_level_falls_to_the_floor_on_a_hopelessly_busy_machine(self):
        service = self.service()
        service._available_ram = lambda: (200 * 1024 * 1024, 0)
        self.assertGreaterEqual(service._choose_compression_level(), 5)

    def test_exhausted_swap_forces_a_step_down_even_with_free_ram(self):
        # MemAvailable can look healthy while the machine is already swapping hard. A compressor that
        # then asks for another 2.5 GB is what makes the desktop unusable, so swap pressure wins.
        service = self.service()
        service._available_ram = lambda: (12 * GB, 64 * 1024 * 1024)
        self.assertEqual(service._choose_compression_level(), 8)

    def test_unknown_memory_falls_back_to_the_configured_level(self):
        service = self.service()
        service._available_ram = lambda: (None, None)
        self.assertEqual(service._choose_compression_level(), COMPRESSION_LEVEL)

    def test_resource_failures_are_told_apart_from_real_errors(self):
        service = self.service()
        # 7z reports memory death as a bare "Break signaled" with no diagnosis, indistinguishable from a
        # genuine error by exit code, and only the text separates them.
        self.assertTrue(service._looks_like_resource_failure("Break signaled"))
        self.assertTrue(service._looks_like_resource_failure("ERROR: Not enough memory"))
        self.assertTrue(service._looks_like_resource_failure("Cannot allocate memory"))
        self.assertFalse(service._looks_like_resource_failure("Unexpected end of data"))
        self.assertFalse(service._looks_like_resource_failure(""))

    def test_compressor_threads_are_capped(self):
        # Every 7z thread carries its own match finder, so an uncapped thread count multiplies the cost
        # of whatever level was chosen.
        self.assertGreater(COMPRESSION_THREADS, 0)
        self.assertLessEqual(COMPRESSION_THREADS, 4)


class TestCancellingARunningTool(unittest.TestCase):
    """Cancel has to reach the archive tool, not just the Python that launched it.

    The worker spends minutes blocked reading the tool's progress pipe, so it cannot notice a cancel by
    looking for one. Without a watcher thread killing the child, Cancel and closing the window both sat
    there until a multi-GB build finished on its own - which is what "pressing cancel freezes the app"
    looked like from the outside.
    """

    # Stands in for a level-9 build: runs, produces nothing, and would never end on its own.
    NEVER_ENDING = "import time\nwhile True: time.sleep(0.05)"

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.service = OrganizerService(AppLogger(Path(self.folder.name) / "log.log"))

    def test_cancelling_a_job_stops_the_running_tool_and_raises(self):
        ctx = JobContext("CANCELME")
        result = {}

        def run():
            try:
                result["code"] = self.service._run_tool([sys.executable, "-c", self.NEVER_ENDING], "compressing", lambda *a, **k: None, ctx=ctx)
            except BaseException as exc:
                result["error"] = exc

        # Daemon, so a failure here can never leave this process waiting on a thread at exit.
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        time.sleep(0.5)
        self.assertTrue(worker.is_alive(), "the tool finished on its own, so nothing was being tested")
        cancel_at = time.monotonic()
        ctx.cancel()
        worker.join(timeout=25)
        self.assertFalse(worker.is_alive(), "the tool was still running 25s after the cancel")
        self.assertLess(time.monotonic() - cancel_at, 15, "the cancel took too long to take effect")
        self.assertIsInstance(result.get("error"), CancellationError, "a cancelled tool must not be reported as a normal exit code")
        self.assertNotIn("code", result)

    def test_a_tool_that_finishes_normally_reports_its_real_exit_code(self):
        code, detail = self.service._run_tool([sys.executable, "-c", 'print("built")'], "compressing", lambda *a, **k: None, ctx=JobContext("OK"))
        self.assertEqual(code, 0, "a tool that finishes on its own must report its real exit code")
        self.assertIn("built", detail)

    def test_the_watcher_releases_its_thread_when_the_tool_finishes_normally(self):
        # A watcher left waiting on the cancel event would leak one thread per conversion, and an overnight
        # run is hundreds of them.
        before = threading.active_count()
        for _ in range(20):
            self.service._run_tool([sys.executable, "-c", "pass"], "compressing", lambda *a, **k: None, ctx=JobContext("OK"))
        for _ in range(40):
            if threading.active_count() <= before:
                break
            time.sleep(0.05)
        self.assertLessEqual(threading.active_count(), before, "the cancel watcher thread was not released")

    def test_a_failed_tool_is_not_mistaken_for_a_cancelled_one(self):
        # The two look alike from outside - a non-zero exit and a signal - and reporting a cancel as a
        # conversion failure would blame the user for pressing Cancel, and vice versa.
        code, _ = self.service._run_tool([sys.executable, "-c", "raise SystemExit(3)"], "compressing", lambda *a, **k: None, ctx=JobContext("OK"))
        self.assertEqual(code, 3, "a genuine tool failure was swallowed or reported as a cancel")


class TestTheEmptiedSourceFolderIsOnlyRemovedWhenItIsOurs(unittest.TestCase):
    """`shutil.rmtree` removes a tree without asking, so an allow-list stands in front of it.

    Organizing an archive out of a folder that this app did not file used to delete whatever else was in
    that folder: a save, a notes file, a mods directory, a launcher config. The run reported success. The
    function's own comment and the README both promised the opposite - that anything unexpected prevents
    removal - and only two of the promised guards existed: not a managed game folder, and no archive left
    anywhere inside. A player's own files satisfied both and were removed anyway.

    The whole set is here rather than the one deletion, because the allow-list is only as good as the
    entries that veto it, and the entries are what a later change would get wrong.
    """

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / "Games"
        self.service = OrganizerService(AppLogger(Path(self.folder.name) / "log.log"))

    def _source(self, *contents):
        """A category folder holding one archive, plus whatever else the test needs beside it."""
        source = self.root / "Action" / "Cool Game"
        source.mkdir(parents=True)
        archive = source / "Cool Game.zip"
        archive.write_bytes(b"PK\x03\x04" + b"0" * 512)
        for name in contents:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("player data") if path.suffix != ".zip" else path.write_bytes(b"PK\x03\x04" + b"1" * 64)
        return archive

    def _organize(self, archive):
        record = GameArchive(archive, "Cool Game", "cool game", "coolgame", ".zip", size=archive.stat().st_size)
        record.user_title = "Cool Game"
        return self.service.move(record, self.root)

    def test_a_save_beside_the_archive_is_not_deleted(self):
        archive = self._source("my-save.dat")
        self._organize(archive)
        self.assertTrue((archive.parent / "my-save.dat").is_file(), "organizing one archive out of a folder deleted the player save next to it")
        self.assertTrue(archive.parent.is_dir(), "the folder was removed although it held a file we did not write")

    def test_a_notes_file_beside_the_archive_is_not_deleted(self):
        archive = self._source("notes.txt")
        self._organize(archive)
        self.assertTrue((archive.parent / "notes.txt").is_file())

    def test_a_subdirectory_beside_the_archive_is_not_deleted(self):
        archive = self._source("mods/config.ini")
        self._organize(archive)
        self.assertTrue((archive.parent / "mods" / "config.ini").is_file(), "a subdirectory vetoes removal on sight; rmtree would take its contents with it")

    def test_an_unexpected_file_anywhere_vetoes_the_whole_folder(self):
        """One unrecognised entry is enough. A partial cleanup is not a safer cleanup."""
        archive = self._source("Cool Game_grid.jpg", "notes.txt")
        self._organize(archive)
        self.assertTrue((archive.parent / "Cool Game_grid.jpg").is_file(), "the artwork was removed even though an unrecognised file was vetoing the folder")

    def test_an_empty_folder_is_still_cleaned_up(self):
        """The reason the function exists at all: not leaving a nameless folder per organized game."""
        archive = self._source()
        source = archive.parent
        self._organize(archive)
        self.assertFalse(source.exists(), "the folder was left behind holding nothing")

    def test_a_folder_holding_only_our_own_artwork_is_cleaned_up(self):
        """Recognised artwork is the one unrecognised-looking thing this app does put in a folder.

        Only pictures. A shortcut file would also be on the allow-list, but `Open Steam Page.html` is a
        managed-folder marker first, so a folder holding one is kept by that rule and never reaches this one.
        """
        archive = self._source("Cool Game_grid.jpg", "cover.png")
        source = archive.parent
        self._organize(archive)
        self.assertFalse(source.exists(), "a folder left holding only recognised artwork was not cleaned up")

    def test_a_second_archive_is_never_removed_with_the_folder(self):
        archive = self._source("Cool Game (1).zip")
        source = archive.parent
        self._organize(archive)
        self.assertTrue((source / "Cool Game (1).zip").is_file(), "an archive was still inside and the folder went anyway")

    def test_an_organized_game_folder_holding_only_its_marker_is_removed(self):
        """The marker no longer refuses outright; it routes to the prunable rule.

        A folder this app filed is still the player's - a screenshot ends up beside the game - so
        "never delete a game folder" was wrong in both directions. The folder is judged by
        contents: it is ours to remove only when every entry in it is something this app put
        there. A marker alone is exactly that, so the folder goes - which is what the re-categorise
        case needs. The old test asserted the opposite and was the rule that left the folder
        behind holding the image the app wrote.
        """
        game = self.root / "Action" / "Cool Game - 2020-01-01"
        game.mkdir(parents=True)
        (game / ".game-info.json").write_text("{}", encoding="utf-8")
        archive = game / "Cool Game.zip"
        archive.write_bytes(b"PK" + b"0" * 512)
        self._organize(archive)
        self.assertFalse(game.exists(), "a game folder holding only the app marker was left behind")

    def test_an_organized_game_folder_is_removed_when_only_app_artwork_is_left_in_it(self):
        """Re-categorising a game moves its archive out of the folder it was filed into.

        The folder carries the markers, so the old rule refused it outright and every scan reported
        it as an empty game with no archive, holding the image the app wrote. A folder this app
        filed is still the player's - a screenshot ends up beside the game - so the decision is
        delegated to the prunable rule rather than made by the marker alone: it is ours to remove
        only when every entry in it is something this app put there.
        """
        game = self.root / "Action" / "Cool Game - 2020-01-01"
        game.mkdir(parents=True)
        (game / ".game-info.json").write_text("{}", encoding="utf-8")
        archive = game / "Cool Game.zip"
        archive.write_bytes(b"PK\x03\x04" + b"0" * 512)
        (game / "Cool Game_grid.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        self._organize(archive)
        self.assertFalse(game.exists(), "re-categorising a game left its old folder behind holding the app artwork")

    def test_an_organized_game_folder_holding_a_screenshot_is_not_removed(self):
        """The prunable rule judges provenance by name, and a screenshot is a .jpeg like any other."""
        game = self.root / "Action" / "Cool Game - 2020-01-01"
        game.mkdir(parents=True)
        (game / ".game-info.json").write_text("{}", encoding="utf-8")
        archive = game / "Cool Game.zip"
        archive.write_bytes(b"PK\x03\x04" + b"0" * 512)
        (game / "screenshot.jpeg").write_bytes(b"\xff\xd8\xff\xd9")
        self._organize(archive)
        self.assertTrue(game.is_dir(), "re-categorising a game deleted a folder holding a screenshot")
        self.assertTrue((game / "screenshot.jpeg").is_file(), "the screenshot was removed with the folder")

    def test_the_library_root_and_a_category_folder_are_never_removed(self):
        """An archive filed straight into a category, or straight into the root, is a real layout.

        Both containers are rejected on structure rather than contents: the root is the destination, and a
        category's parent is. Checking contents would have been the wrong rule - a category folder that
        happens to hold nothing but recognised artwork would satisfy it.
        """
        for container in (self.root, self.root / "Action"):
            with self.subTest(container=container.name):
                container.mkdir(parents=True, exist_ok=True)
                archive = container / "Loose.zip"
                archive.write_bytes(b"PK\x03\x04" + b"0" * 512)
                self._organize(archive)
                self.assertTrue(container.is_dir(), f"{container.name} was removed by organizing a loose archive out of it")


class TestStoppingAStubbornArchiveTool(unittest.TestCase):
    """Ending a tool that will not die must not raise on the way out.

    Both helpers ask politely, then kill, then wait with a timeout. The wait is the only one of the three
    that can raise `subprocess.TimeoutExpired`, which descends from `SubprocessError` and therefore from
    `Exception` - not from `OSError`. A `suppress(OSError, AttributeError)` written for the two signals
    therefore let it straight through, out of a `finally` block, where it replaces whatever was already
    failing: the cancellation or the build error is lost and a traceback about the shutdown arrives instead.
    """

    class _Stubborn:
        """Running, ignores both signals, and so is the wait that finally gives up."""

        def __init__(self):
            self.terminated = False
            self.killed = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="7z", timeout=timeout or 0)

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.logger = AppLogger(Path(self.folder.name) / "log.log")

    def test_the_organizers_stop_does_not_raise_when_the_wait_gives_up(self):
        process = self._Stubborn()
        OrganizerService._stop_tool(process, grace=0.01)
        self.assertTrue(process.terminated, "the tool was not asked to stop politely first")
        self.assertTrue(process.killed, "kill() was not used as the backstop for a tool that ignored the first ask")

    def test_the_extractors_stop_does_not_raise_when_the_wait_gives_up(self):
        process = self._Stubborn()
        ExtractService._stop(process, grace=0.01)
        self.assertTrue(process.killed)


class TestTheExtractorReportsWhyThereIsNoTool(unittest.TestCase):
    r"""The finder knows which of PATH and the real install folders came up empty. That answer was thrown away.

    `extract()` bound `find_tool()`'s reason, then rebound the same name to the free-space check, and
    returned a hardcoded "not on PATH" instead. That has been wrong since v9.8, when the finder started
    looking in `C:\Program Files\7-Zip` - a machine where 7-Zip is installed and not on PATH is found
    correctly, and a machine with neither is told to fix a PATH that was never the problem.
    """

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.archive = self.base / "Cool Game.zip"
        self.archive.write_bytes(b"PK\x03\x04" + b"0" * 512)

    def test_the_finders_own_explanation_is_the_one_reported(self):
        service = ExtractService(AppLogger(self.base / "log.log"))
        reason = "7z/7za is not on PATH and no default 7-Zip install was found"
        with patch.object(ExtractService, "find_tool", staticmethod(lambda: (None, reason))):
            result = service.extract(self.archive, self.base / "out")
        self.assertFalse(result.ok)
        self.assertEqual(result.message, reason, "the specific reason the finder gave was discarded for a generic one")

    def test_a_missing_tool_is_not_reported_as_a_path_problem(self):
        service = ExtractService(AppLogger(self.base / "log.log"))
        with patch.object(ExtractService, "find_tool", staticmethod(lambda: (None, "nothing here at all"))):
            result = service.extract(self.archive, self.base / "out")
        self.assertNotIn("PATH", result.message, "the message blames PATH, but the finder also checks the real install folders")
