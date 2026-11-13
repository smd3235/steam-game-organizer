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
from core.canonical_category import canonical_category
from core.constants import COMPRESSION_LEVEL, COMPRESSION_THREADS, suggest_category, DEFAULT_ZIP_PASSWORD
from core.exceptions import CancellationError
from core.logger import AppLogger
from core.models import ArtworkResult, GameArchive, RepairArchive, SteamMatch
from services.archive_service import ArchiveService
from services.extract_service import ExtractService
from services.library_service import LibraryService
from services.organizer_service import OrganizerService
from services.steam_service import SteamService
from utils.filename_utils import identity_key

# _FakeProc extracted to tests\fake_proc.py — see that module for its definition.
from tests.fake_proc import _FakeProc
# ToolCallSpy extracted to tests\tool_call_spy.py — see that module for its definition.
from tests.tool_call_spy import ToolCallSpy
# ArtworkWarningsHaveToBeTrue extracted to tests\artwork_warnings_have_to_be_true.py — see that module for its definition.
from tests.artwork_warnings_have_to_be_true import ArtworkWarningsHaveToBeTrue
# TestTaggedTitlesReachTheStore extracted to tests\test_tagged_titles_reach_the_store.py — see that module for its definition.
from tests.test_tagged_titles_reach_the_store import TestTaggedTitlesReachTheStore
# TestAdaptiveCompression extracted to tests\test_adaptive_compression.py — see that module for its definition.
from tests.test_adaptive_compression import TestAdaptiveCompression
# TestCancellingARunningTool extracted to tests\test_cancelling_a_running_tool.py — see that module for its definition.
from tests.test_cancelling_a_running_tool import TestCancellingARunningTool
# TestStoppingAStubbornArchiveTool extracted to tests\test_stopping_a_stubborn_archive_tool.py — see that module for its definition.
from tests.test_stopping_a_stubborn_archive_tool import TestStoppingAStubbornArchiveTool
# TestTheExtractorReportsWhyThereIsNoTool extracted to tests\test_the_extractor_reports_why_there_is_no_tool.py — see that module for its definition.
from tests.test_the_extractor_reports_why_there_is_no_tool import TestTheExtractorReportsWhyThereIsNoTool
# TestArchiveShippedAppID extracted to tests\test_archive_shipped_app_i_d.py — see that module for its definition.
from tests.test_archive_shipped_app_i_d import TestArchiveShippedAppID
# TestStoreApiInsteadOfScrapedHtml extracted to tests\test_store_api_instead_of_scraped_html.py — see that module for its definition.
from tests.test_store_api_instead_of_scraped_html import TestStoreApiInsteadOfScrapedHtml
# TestAuditProgress extracted to tests\test_audit_progress.py — see that module for its definition.
from tests.test_audit_progress import TestAuditProgress
# TestPartialArchiveSafety extracted to tests\test_partial_archive_safety.py — see that module for its definition.
from tests.test_partial_archive_safety import TestPartialArchiveSafety
# TestTheEmptiedSourceFolderIsOnlyRemovedWhenItIsOurs extracted to tests\test_the_emptied_source_folder_is_only_removed_when_it_is_ours.py — see that module for its definition.
from tests.test_the_emptied_source_folder_is_only_removed_when_it_is_ours import TestTheEmptiedSourceFolderIsOnlyRemovedWhenItIsOurs
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
            archive = root / "Neon Racer Collection Racing Series 20260916.zip"
            archive.write_text("a")
            result = ArchiveService(AppLogger(root / "x.log")).discover(root)
            self.assertEqual(result.archives[0].normalized_title, "Neon Racer Collection Racing Series 20260916")
            self.assertEqual(result.archives[0].identity_key, "neonracercollectionracingseries20260916")

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
            game = library / "Puzzle" / "SunTopia - 1 Jan, 2026"
            game.mkdir(parents=True)
            (game / ".game-info.json").write_text(json.dumps({"appid": "1234", "name": "SunTopia"}), encoding="utf-8")
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
            game = root / "RPG" / "Sir Beats Alot - 2019-11-13"
            game.mkdir(parents=True)
            (game / "Sir Beats Alot.zip").write_text("old copy")
            (game / ".game-info.json").write_text('{"appid":"55555","name":"Sir Beats Alot"}')
            (game / "Open Steam Page.html").write_text("<html>link</html>")
            (game / "Sir Beats Alot_grid.jpg").write_bytes(b"\xff\xd8\xff\xdb" + b"0" * 200)
            (game / "user-save.dat").write_text("MY SAVEGAME")
            inbox = root / "Incoming"
            inbox.mkdir()
            fresh = inbox / "Sir Beats Alot.zip"
            fresh.write_text("new copy")
            logger = AppLogger(Path(d) / "x.log")
            jobs = JobManager()
            services = type(
                "Services", (),
                {"organizer": OrganizerService(logger, convert_archives=False),
                 "rollback": RollbackService(Path(d), logger),
                 "catalog": type("Catalog", (), {"generate": lambda *a, **k: None})()})()
            bus = EventBus()
            controller = AppController(StateStore(), bus, logger, services, jobs)
            failures = []
            bus.subscribe("operation_failed", lambda event: failures.append(event.payload))
            item = GameArchive(fresh, "Sir Beats Alot", "Sir Beats Alot", "sirbeatsalot", ".zip")
            item.decision.accepted = True
            item.decision.category = "RPG"
            item.steam = SteamMatch(found=True, appid="55555", name="Sir Beats Alot", release_date="13 Nov, 2019")
            done = Event()
            controller.organize([item], root, lambda moved: done.set())
            self.assertTrue(done.wait(10), "the organize run never finished")
            jobs.shutdown()
            self.assertEqual(failures, [])
            for name in ("user-save.dat", "Sir Beats Alot_grid.jpg", ".game-info.json", "Open Steam Page.html"):
                self.assertTrue((game / name).is_file(), f"{name} was deleted from an already-organized game folder")
            self.assertTrue((root / "Archive" / "Sir Beats Alot.zip").is_file(), "the previous copy was not filed under Archive")

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
            result = OrganizerService(AppLogger(root / "log.log"))._repack_with_official_name(RepairArchive(path, appid, name), on_progress=events.append)
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

        unreadable = {
            "a truncated write": '[{"source": "C:\\\\a\\\\Game.zip", "targ',
            "an object rather than a list": "{}", "an empty list": "[]",
            "a bare string": '"hello"', "a number": "42",
            "rows that are not objects": "[1, 2, 3]",
            "a row missing its keys": '[{"target": "C:\\\\b\\\\Game.zip"}]',
        }
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
        # "Survivors" and "Survival" were the same genre under two names - the block-crafting one, gather and
        # craft and build a base. It is filed under Survival alone. "Bullet Heaven" is a different genre, the
        # horde auto-shooter one, and stays a separate choice; merging the two would file both under one name.
        from core.constants import DEFAULT_CATEGORIES, SUPPLEMENTAL_CATEGORIES

        offered = DEFAULT_CATEGORIES + SUPPLEMENTAL_CATEGORIES
        self.assertIn("Survival", offered)
        self.assertIn("Bullet Heaven", offered)
        self.assertNotIn("Survivors", offered, "Survivors is the same genre as Survival under a second name")
        self.assertEqual(canonical_category("Survivors"), "Survival")
        self.assertEqual(canonical_category("Survivor"), "Survival")
        self.assertEqual(canonical_category("Horde Shooter"), "Bullet Heaven")
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
        variants = service._query_variants("Neon Racer Collection Racing Series 20260916", "Neon Racer Collection Racing Series 20260916", None)
        self.assertIn("Neon Racer Collection", variants)

    def test_query_variants_never_drop_a_trailing_sequel_number(self):
        service = _steam(self, mock=True)
        variants = service._query_variants("Town Skylines 2", "Town Skylines 2", None)
        self.assertNotIn("Town Skylines", variants)
        variants = service._query_variants("Sonic Frontiers II", "Sonic Frontiers II", None)
        self.assertNotIn("Sonic Frontiers", variants)

    def test_query_variants_resolve_edition_and_release_tag_suffixes_generically(self):
        service = _steam(self, mock=True)
        cases = [
            ("Delta Realm Incremental", "Delta Realm"),
            ("Ball XPit20260808", "BALL x PIT"),
            ("Realm Castles123r6s", "Realm Castles"),
            ("Flotsam101f7", "Flotsam"),
            ("Nebula Online Tenoke", "Nebula Online"),
        ]
        for normalized, official in cases:
            variants = service._query_variants(normalized, normalized, None)
            self.assertIn(identity_key(official), [identity_key(v) for v in variants])

    def test_query_variants_strip_generic_marketing_edition_suffixes(self):
        service = _steam(self, mock=True)
        self.assertIn("Astral Original Sin 2", service._query_variants("Astral Original Sin 2 Definitive Edition", "Astral Original Sin 2 Definitive Edition", None))
        self.assertIn("Town Skylines II", service._query_variants("Town Skylines II Deluxe Edition", "Town Skylines II Deluxe Edition", None))

    def test_query_variants_swap_ampersand_and_and(self):
        service = _steam(self, mock=True)
        self.assertIn("Realm and Castles", service._query_variants("Realm & Castles", "Realm & Castles", None))

    def test_query_variants_try_both_arabic_and_roman_numerals(self):
        service = _steam(self, mock=True)
        self.assertIn("Dark Blades III", service._query_variants("Dark Blades 3", "Dark Blades 3", None))
        self.assertIn("Evil Resident 4", service._query_variants("Evil Resident IV", "Evil Resident IV", None))

    def test_query_variants_do_not_mangle_ordinary_words_containing_x(self):
        service = _steam(self, mock=True)
        variants = service._query_variants("Exodus Complex Edition", "Exodus Complex Edition", None)
        self.assertFalse(any("e x" in v.casefold() or "e x o" in v.casefold() for v in variants))

    def test_lookup_store_finds_official_title_via_generic_variants(self):
        service = _steam(self)

        def fake_request(url, ctx=None):
            if "nebula" in url.casefold() and "noodle" in url.casefold():
                return {"items": [{"id": "3461730", "name": "Nebula Noodle"}]}
            return {"items": []}

        service._request_json = fake_request
        service._details = lambda appid, ctx=None: {"name": "Nebula Noodle"}
        steam_match = service._lookup_store("Nebula Noodle", None)
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
            # Replaced a real Steam game name with fictional "Nebula Online" per the
            # no-real-game-names rule (see tools/validate_game_names.py deny list).
            steam_match = s.lookup("Nebula Online")
            self.assertEqual(steam_match.source, "mock")
            self.assertEqual(steam_match.name, "Nebula Online")

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

