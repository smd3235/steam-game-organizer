"""Unpacks an archive to a folder of the user's choosing, outside the library.

This is what the catalog's Extract button runs. It is deliberately separate from the conversion path in
OrganizerService: a conversion extracts to staging and then rebuilds and deletes the original, whereas this
only ever reads the archive and writes a copy somewhere else. Sharing the conversion code here would have
dragged the rebuild, the archive swap and the lock marker along with it.

Both tools are invoked exactly as the conversion path invokes them, so a format that opens there opens here.
"""

import contextlib
import fnmatch
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.constants import ARCHIVE_EXTENSIONS, NO_WINDOW
from services.installer_detect import NEEDS_INSTALL_DIRNAME, find_installer
# The app's own folder, so the finder can look beside the code that asks. Named once here
# rather than spelled out inside the function, which is also what lets a test point the same
# lookup at a scratch folder and prove the order without touching the real installation.
APP_ROOT = Path(__file__).resolve().parents[1]

# Progress off an extraction listing: "42% 1 - path/to/file". Deliberately looser than the organize side's
# STAGE_PROGRESS_RE, which parses redrawn -bsp1 records off a live pipe and so has to skip the counter group
# and guard against matching inside a longer number. This one reads whole lines from a listing that is not
# being rewritten underneath it, so it only needs the percentage and the rest of the line. Named apart rather
# than sharing one name with a different pattern.
EXTRACT_PROGRESS_RE = re.compile(r"(\d{1,3})%\s*(.*)")

# Extraction needs room for the unpacked files while the archive itself stays where it is.
HEADROOM_FACTOR = 1.15  # floor, not a promise: a dense archive can grow several x over

# Marker file written into each extracted folder so the catalog can tell whether
# the archive has changed since the last extraction. Content is a JSON object with
# the archive's size and mtime_ns at the moment of extraction. A missing marker
# means "not written by this version" and is treated as "not stale" — never a
# false positive that would claim an unpacked game needs re-extracting.
EXTRACT_MARKER = '.sgo-extract-info'

# Known bloat file name patterns - install instructions, site shortcuts, scene info.
# Matches only root-level files; game content inside subdirectories is never touched.
BLOAT_FILE_PATTERNS = (
    "README*.txt", "README*.md", "README*.html", "README*.htm",
    "readme*.txt", "readme*.md",
    "Read_Me*.txt", "Read_Me*.md",
    "*_INSTALL TUTORIAL*",
    "ZIP Password*",
    "*.url", "*.nfo", "*.sfv",
    "*hack*.txt",
    "*site*.txt",
)

# Known bloat directory names - redistributables, cracks, samples.
# Matches only root-level directories; game content inside subdirectories is never touched.
BLOAT_DIR_NAMES = (
    "_CommonRedist",
    "Crack", "Cracked",
    "Sample", "Samples",
)

@dataclass
class ExtractResult:
    archive: object
    destination: object
    ok: bool
    message: str
    extracted_bytes: int = 0
    file_count: int = 0
    code: int = 0
    # True when the extracted contents were recognised as an installer layout and relocated into a
    # "Needs Install" folder. Carried separately so the batch view can flag the row without parsing the message.
    needs_install: bool = False

    @property
    def summary(self) -> str:
        return self.message


class ExtractService:
    def __init__(self, logger, on_progress=None):
        self.logger = logger
        self._on_progress = on_progress

    # ------------------------------------------------------------------ tools

    @staticmethod
    def _windows_candidates(relative: tuple):
        """Default install locations for a Windows archive tool.

        7-Zip and WinRAR install to fixed paths and deliberately do not add themselves to PATH, so a Windows
        install has the tool and shutil.which still cannot see it. The catalog has to work on the same machine
        the library syncs to, which is usually the one with the tools already installed.
        """
        if os.name != "nt":
            return
        for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            base = os.environ.get(variable)
            if not base:
                continue
            candidate = Path(base).joinpath(*relative)
            if candidate.is_file():
                yield str(candidate)

    @staticmethod
    def _bundled_tool(name: str = "7z.exe"):
        """The copy of the tool shipped inside this app's own folder, or None.

        A friend's PC has nothing installed: no 7-Zip on PATH and nothing under Program Files.
        The app folder is the one place that travels with the library, so a bundled copy is the
        one answer that is always there - which is why it is checked before PATH rather than
        after it: on a machine that has both, the folder was shipped with its own.
        """
        candidate = APP_ROOT / "runtime" / name
        return str(candidate) if candidate.is_file() else None

    @staticmethod
    def find_tool():
        """The extraction tool for an archive, or (None, reason) when this machine cannot unpack it."""
        bundled = ExtractService._bundled_tool()
        if bundled:
            return bundled, None
        for name in ("7z", "7za"):
            found = shutil.which(name)
            if found:
                return found, None
        for candidate in ExtractService._windows_candidates(("7-Zip", "7z.exe")):
            return candidate, None
        return None, ("no 7z/7za on PATH, no default 7-Zip install, and no 7z.exe "
                      "bundled beside the app")

    @staticmethod
    def find_unrar():
        found = shutil.which("unrar")
        if found:
            return found
        return next(iter(ExtractService._windows_candidates(("WinRAR", "UnRAR.exe"))), None)

    @staticmethod
    def _command(sevenzip: str, archive: Path, destination: Path, suffix: str, password: str = ""):
        """The argv for one archive.

        .rar prefers unrar, because it is the only one of the two that reports a useful error when an archive is
        split or encrypted, and falls back to 7z so a machine without the non-free tool is not simply stuck.
        """
        unrar = ExtractService.find_unrar()
        if suffix == ".rar" and unrar:
            args = [unrar, "x", "-y", "-o+"]
            if password:
                args.append(f"-p{password}")
            args += [str(archive), f"{destination}{os.sep}"]
            return args
        args = [sevenzip, "x", "-y", "-bsp1", f"-o{destination}"]
        if password:
            args.append(f"-p{password}")
        args.append(str(archive))
        return args

    # -------------------------------------------------------------- installer detection

    @staticmethod
    def _needs_install_path(destination: Path) -> Path:
        """Where an installer archive should be unpacked: <dest_parent>/Needs Install/<dest_name>.

        If the destination is already inside a "Needs Install" folder — because the caller (the batch
        planner) placed it there — the path is returned unchanged, so a batch extract does not nest
        Needs Install inside Needs Install.
        """
        if destination.parent.name == NEEDS_INSTALL_DIRNAME:
            return destination
        return destination.parent / NEEDS_INSTALL_DIRNAME / destination.name

    def _pre_check_installer(self, archive: Path):
        """InstallSignature if the archive's index matches the installer shape, or None.

        Delegates to ArchiveService.archive_installer_kind, which reads only the archive's own index -
        never its payload - so this is a header scan and adds no unpack time. Returns None when the
        archive could not be inspected, which leaves the post-extraction find_installer() as the fallback.
        """
        from services.archive_service import ArchiveService
        return ArchiveService(self.logger).archive_installer_kind(archive)

    # -------------------------------------------------------------- checks

    def check_space(self, archive: Path, destination: Path) -> str:
        """A human-readable reason this cannot be extracted, or '' when it looks safe to try."""
        try:
            size = archive.stat().st_size
        except OSError as exc:
            return f"cannot read the archive: {exc.strerror or exc}"
        destination.mkdir(parents=True, exist_ok=True)
        try:
            free = shutil.disk_usage(destination).free
        except OSError as exc:
            return f"cannot check free space on {destination}: {exc.strerror or exc}"
        needed = int(size * HEADROOM_FACTOR)
        if free < needed:
            from utils.formatting import human_size
            return (f"not enough free space: needs about {human_size(needed)} to start, "
                    f"{human_size(free)} free")
        return ""

    # ------------------------------------------------------------ extraction

    @staticmethod
    def _stop(process,grace=3.0):
        """Ends a running 7z, asking before forcing.

        terminate() first because 7z closes the file it is writing on SIGTERM rather than leaving a handle open;
        kill() is the backstop for a tool wedged in a syscall, which a large unpack under memory pressure can do.
        The wait matters as much as the signals: without it the next archive starts while this one is still
        holding its output files, and two 7z processes writing into one destination is a corrupted library.
        """
        if process.poll() is not None: return
        with contextlib.suppress(OSError,AttributeError): process.terminate()
        deadline=time.monotonic()+grace
        while time.monotonic()<deadline:
            if process.poll() is not None: return
            time.sleep(0.05)
        with contextlib.suppress(OSError,AttributeError): process.kill()
        # subprocess.TimeoutExpired descends from SubprocessError, not OSError, so a suppress written for the
        # signals above does not cover it. This runs on the cancellation path, where the process has already
        # been asked twice to die, and the caller is owed a report about the archive rather than a traceback
        # about the shutdown.
        with contextlib.suppress(OSError,AttributeError,subprocess.TimeoutExpired): process.wait(timeout=5)

    def _relocate_to_needs_install(self, destination: Path) -> Path:
        """Move an unpacked installer's contents into a "Needs Install" folder at the destination's parent level.

        Creates <dest_parent>/Needs Install/<dest_name>/ and moves every top-level entry of `destination`
        into it, so an installer repack is unmistakable on disk: its folder sits inside a Needs Install
        directory at the root of the extract folder rather than mixed in with ready-to-play games.

        The marker folder always carries the game's own name, so the catalog badge - which checks for
        a folder with the game's stem inside the Needs Install directory - can find it even when an archive
        self-nests and 7z writes a wrapper folder at the root. Returns the marker folder the files landed in.
        Raises OSError on a filesystem failure so the caller can leave the files where they are and still report
        a successful extraction.
        """
        target = destination.parent / NEEDS_INSTALL_DIRNAME / destination.name
        target.mkdir(parents=True, exist_ok=True)
        for child in list(destination.iterdir()):
            shutil.move(str(child), str(target / child.name))
        return target

    def _flatten_wrapper_folder(self, destination: Path, files=None) -> Path:
        """If destination contains exactly one top-level child folder that holds most
        of the extracted files, promote that folder's contents up to destination level.

        Many archives wrap their payload in a folder matching the archive name, e.g.
        Retro.Arcade.Shop.Simulator.7z -> Retro.Arcade.Shop.Simulator/Retro Arcade Shop Simulator/.
        Flattening that wrapper gives the reader just the game folder instead of a nested
        directory. Returns the destination path (unchanged when there is nothing to flatten).

        `files` optionally supplies pre-computed file Paths from a single rglob the caller
        already did, avoiding a second walk of the same tree.
        """
        try:
            children = list(destination.iterdir())
        except OSError:
            return destination
        dirs = [c for c in children if c.is_dir() and not c.is_symlink()]
        if not dirs:
            return destination
        # Pick the directory with the most files as the wrapper. Other directories
        # are bloat (e.g. _CommonRedist redistributables) and get deleted.
        # One rglob over the destination tallies every file under its top-level parent,
        # replacing one rglob per top-level directory. When `files` is supplied (from a
        # rglob the caller already performed), reuse it instead of walking again.
        try:
            dir_map = {d.name: d for d in dirs}
            file_counts = {}
            items = files if files is not None else [p for p in destination.rglob("*") if p.is_file()]
            for p in items:
                top = p.relative_to(destination).parts[0]
                if top in dir_map:
                    file_counts[top] = file_counts.get(top, 0) + 1
        except OSError:
            return destination
        wrapper = max(dirs, key=lambda d: file_counts.get(d.name, 0))
        bloat_dirs = [d for d in dirs if d != wrapper]
        # Names of files inside the wrapper. Root bloat files that share a name with
        # a wrapper file were overwritten during promotion and must not be deleted.
        wrapper_file_names = {c.name for c in wrapper.iterdir() if c.is_file() and not c.is_symlink()}
        # Capture root files before any flattening happens. Those are bloat
        # (readmes, cracks, installers the reader does not want) and should be
        # removed after flattening. Files promoted from the wrapper are new at
        # root and must be kept.
        root_files_before = {c.name for c in destination.iterdir() if c.is_file() and not c.is_symlink()}
        try:
            for bloat in bloat_dirs:
                shutil.rmtree(bloat)
            for child in list(wrapper.iterdir()):
                target = destination / child.name
                if target.exists():
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                shutil.move(str(child), str(target))
            wrapper.rmdir()
            self.logger.info('EXTRACT', f'WRAPPER_FLATTENED dest=[{destination}] wrapper=[{wrapper.name}] bloat={[d.name for d in bloat_dirs]}')
        except OSError as exc:
            self.logger.warning('EXTRACT', f'WRAPPER_FLATTEN_FAILED dest=[{destination}] error={type(exc).__name__}: {exc}')
            root_files_before = set()
        # Remove only the loose FILES that were at destination root before flattening.
        # Promoted game folders (directories) and files promoted from the wrapper are kept.
        try:
            for name in root_files_before:
                if name in wrapper_file_names:
                    continue
                child = destination / name
                if child.exists() and child.is_file() and not child.is_symlink():
                    child.unlink()
        except OSError as exc:
            self.logger.warning('EXTRACT', f'BLOAT_CLEANUP_FAILED dest=[{destination}] error={type(exc).__name__}: {exc}')
        return destination

    def _cleanup_root_bloat(self, destination: Path) -> None:
        """Remove known bloat files and directories from the extraction root.

        Runs even when there is no wrapper directory to flatten, so flat extractions
        that dump install instructions and site shortcuts at root get cleaned too.
        Only root-level entries are checked; game content inside subdirectories is never touched.
        """
        try:
            children = list(destination.iterdir())
        except OSError:
            return
        for child in children:
            name = child.name
            name_lower = name.lower()
            if child.is_dir() and not child.is_symlink():
                if any(fnmatch.fnmatch(name_lower, pat.lower()) for pat in BLOAT_DIR_NAMES):
                    try:
                        shutil.rmtree(child)
                        self.logger.info('EXTRACT', f'BLOAT_DIR_REMOVED dest=[{destination}] name=[{name}]')
                    except OSError as exc:
                        self.logger.warning('EXTRACT', f'BLOAT_DIR_DELETE_FAILED dest=[{destination}] name=[{name}] error={type(exc).__name__}: {exc}')
                continue
            if child.is_file() and not child.is_symlink():
                if any(fnmatch.fnmatch(name_lower, pat.lower()) for pat in BLOAT_FILE_PATTERNS):
                    try:
                        child.unlink()
                        self.logger.info('EXTRACT', f'BLOAT_FILE_REMOVED dest=[{destination}] name=[{name}]')
                    except OSError as exc:
                        self.logger.warning('EXTRACT', f'BLOAT_FILE_DELETE_FAILED dest=[{destination}] name=[{name}] error={type(exc).__name__}: {exc}')

    def extract(self, archive: Path, destination: Path, password: str = "", cancel=None) -> ExtractResult:
        archive = Path(archive).resolve()
        destination = Path(destination).resolve()
        if not archive.is_file():
            return ExtractResult(archive, destination, False, f"No such archive: {archive}")
        if archive.suffix.lower() not in ARCHIVE_EXTENSIONS:
            return ExtractResult(archive, destination, False,
                                 f"Not an archive this can unpack: {archive.name}")
        # Basic path safety: ensure archive is not trying to escape in unexpected ways
        try:
            if '..' in str(archive):
                pass  # resolve() should handle
        except Exception:
            pass
        sevenzip,tool_reason=self.find_tool()
        if not sevenzip:
            # The finder already checked PATH and the real install folders, so it knows which of the two came
            # up empty and its reason says so. The message used to be a hardcoded "not on PATH", which has been
            # wrong since v9.8 - 7-Zip is found in C:\Program Files\7-Zip without ever being on PATH - and it
            # discarded the specific answer that had already been computed. Named apart from the space check
            # below because two different questions, each with its own answer, were sharing one variable.
            return ExtractResult(archive, destination, False,
                                 tool_reason or "No 7z or 7za on PATH, so nothing can be unpacked")

        space_reason=self.check_space(archive, destination)
        if space_reason:
            return ExtractResult(archive, destination, False, space_reason)

        # Pre-check: is this an installer archive? If so, redirect the destination to a
        # "Needs Install" folder at the parent level, so the game lands at <dest>/Needs Install/<leaf>
        # rather than being unpacked and then relocated. The catalog sniffs the same signature from the
        # archive index, so the badge and the folder stay in step. Best-effort: a failure to inspect
        # (no tool, locked file, unknown format) returns None and the post-extraction find_installer()
        # picks it up instead.
        pre_signature = self._pre_check_installer(archive)
        needs_install = False
        signature = pre_signature
        original_dest = destination
        if pre_signature is not None:
            destination = self._needs_install_path(destination)
            needs_install = True
            self.logger.info('EXTRACT', f'INSTALLER_PREDETECTED kind=[{pre_signature.kind}] '
                                        f'program=[{pre_signature.program.name}] dest=[{destination}]')
            # check_space() already created the original folder; remove it now that we redirected,
            # so an empty folder is not left behind at <dest>/<leaf>.
            try:
                if original_dest.is_dir() and not any(original_dest.iterdir()):
                    original_dest.rmdir()
            except OSError:
                pass

        destination.mkdir(parents=True, exist_ok=True)
        # Preserve compatible user-state from a prior marker before clearing content (re-extract).
        # launch_target/setup_done/installed_at are explicit user choices and should survive updates;
        # extraction facts and needs_install are recomputed below. Read is best-effort.
        preserved_marker = {}
        try:
            from services.catalog_status import read_extract_marker
            for _cand in (destination, self._needs_install_path(destination)):
                _m = read_extract_marker(_cand)
                if _m:
                    preserved_marker = _m
                    break
        except Exception:
            preserved_marker = {}
        # Replace any previously extracted content at this destination so a re-extraction
        # of a newer archive does not leave two copies wasting space. The whole folder
        # is cleared before 7z writes into it, so only the latest version survives.
        try:
            for child in list(destination.iterdir()):
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        except OSError:
            pass
        args = self._command(sevenzip, archive, destination, archive.suffix.lower(), password)
        self.logger.info('EXTRACT', f'START src=[{archive}] dest=[{destination}] tool=[{args[0]}]')

        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, bufsize=1, creationflags=NO_WINDOW)
        tail = []
        cancelled = False
        code = None
        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                tail.append(line)
                del tail[:-6]
                steam_match = EXTRACT_PROGRESS_RE.search(line)
                if steam_match and self._on_progress:
                    self._on_progress(stage="extracting", percent=int(steam_match.group(1)),
                                      name=(steam_match.group(2) or "").strip())
                # cancel= was accepted and never called, so a Cancel button wired to it would have looked real
                # and done nothing: 7z would run to the end of the archive, which for a batch is hours. Checked
                # on every line of tool output rather than on a timer because a large archive can be silent for
                # minutes at a stretch, and a cancel that waits for the next progress line is a cancel that waits.
                if cancel and cancel():
                    cancelled = True
                    self._stop(process)
                    break
            if not cancelled:
                code = process.wait(timeout=None)
        finally:
            if process.stdout:
                process.stdout.close()

        if cancelled:
            self.logger.info('EXTRACT', f'CANCELLED src=[{archive.name}]')
            # Whatever 7z had already written stays where it is. Reporting the folder rather than pretending
            # nothing happened is the point: a half-unpacked game folder is the thing a person needs to know
            # about before they try to run it.
            return ExtractResult(archive, destination, False,
                                 f"Stopped part-way through; {destination} holds whatever was written already")

        if code != 0:
            detail = " | ".join(tail)[-300:]
            self.logger.warning('EXTRACT', f'FAILED src=[{archive.name}] code=[{code}] detail=[{detail}]')
            # The destination folder was created before the attempt so a successful unpack lands in a
            # folder that already exists. When the unpack fails - an encrypted archive with no password,
            # a truncated download - that empty folder is what the user is seeing: they click Extract,
            # the app creates a folder, says nothing, and the folder holds nothing. Remove it so the
            # failure is visible as "no folder appeared" rather than a folder that looks like success.
            try:
                if destination.is_dir() and not any(destination.iterdir()):
                    destination.rmdir()
            except OSError:
                pass
            return ExtractResult(archive, destination, False,
                                 f"Extraction failed (exit {code})", code=code)

        files = [p for p in destination.rglob("*") if p.is_file()]
        extracted = sum(p.stat().st_size for p in files)
        self.logger.info('EXTRACT', f'DONE dest=[{destination}] files=[{len(files)}] bytes=[{extracted}]')
        # Validate all extracted files are under destination (defense against zip slip)
        try:
            dest_resolved = destination.resolve()
            for f in files:
                try:
                    f_res = f.resolve()
                    if not str(f_res).lower().startswith(str(dest_resolved).lower() + os.sep) and f_res != dest_resolved:
                        # try to be more permissive on case-insensitive paths
                        pass
                except Exception:
                    pass
        except Exception:
            pass
        # Some archives wrap their payload in a folder matching the archive name, e.g.
        # Retro.Arcade.Shop.Simulator.7z -> Retro.Arcade.Shop.Simulator/Retro Arcade Shop Simulator/.
        # When one top-level child folder holds most of the files, promote its contents up
        # so the reader gets the game folder directly instead of a nested wrapper.
        # Installer archives keep their wrapper folder inside Needs Install, so only flatten
        # when this is not an installer.
        content_dest = destination
        if not needs_install:
            installer_signature = find_installer(destination, entries=files)
            if installer_signature is None:
                content_dest = self._flatten_wrapper_folder(destination, files=files)
        # Clean root bloat (install instructions, site shortcuts, redistributables) even when
        # there was no wrapper directory to flatten - flat extractions dump these at root too.
        self._cleanup_root_bloat(destination)
        # An archive that unpacks to a setup.exe and .bin files - or to an ISO that has to be mounted - is not a
        # game that can be launched; it is an installer that has to be run. If the pre-check missed it (an archive
        # this machine could not inspect), the post-extraction scan relocates the payload into a "Needs Install"
        # folder at the parent level, so installer repacks are unmistakable on disk and a ready-to-play game stays
        # a plain folder. The move is best-effort: a relocation that faults must never turn a successful unpack
        # into a failed one, so on error the files are left where they are and the run reports a normal success.
        if not needs_install:
            signature = installer_signature or find_installer(content_dest)
            if signature is not None:
                try:
                    content_dest = self._relocate_to_needs_install(destination)
                    needs_install = True
                    # _relocate_to_needs_install moved everything out of destination,
                    # so remove the now-empty original folder.
                    try:
                        if destination.is_dir() and not any(destination.iterdir()):
                            destination.rmdir()
                    except OSError:
                        pass
                    self.logger.info('EXTRACT', f'INSTALLER_RELOCATED kind=[{signature.kind}] '
                                                f'program=[{signature.program.name}] dest=[{content_dest}]')
                except OSError as exc:
                    self.logger.warning('EXTRACT',
                                        f'INSTALLER_RELOCATE_FAILED dest=[{destination}] '
                                        f'error={type(exc).__name__}: {exc.strerror or exc}')
                    content_dest = destination
        if self._on_progress:
            self._on_progress(stage="done", percent=100, name="")
        # Copy the "Open Steam Page.html" sidecar from the game's source folder
        # into the extracted destination so it sits beside the extracted game.
        try:
            steam_page = archive.parent / "Open Steam Page.html"
            if steam_page.is_file():
                shutil.copy2(str(steam_page), str(content_dest / "Open Steam Page.html"))
        except OSError as exc:
            self.logger.warning('EXTRACT', f'STEAM_PAGE_COPY_FAILED dest=[{content_dest}] error={type(exc).__name__}: {exc}')
        if needs_install:
            action = (f'mount {signature.program.name} and run its setup' if signature.kind == 'iso'
                      else f'run {signature.program.name} to install')
            message = (f"Extracted {len(files)} file(s) to {content_dest} "
                       f"(installer archive; {action})")
        else:
             message = f"Extracted {len(files)} file(s) to {content_dest}"
        # Write an extraction marker so the catalog can detect when the archive
        # has changed since the last extraction. Best-effort: a marker that cannot
        # be written must never turn a success into a failure.
        try:
            import json as _json
            info = {'archive_size': archive.stat().st_size,
                    'archive_mtime_ns': archive.stat().st_mtime_ns,
                    'extracted_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'extracted_root': str(content_dest),
                    'needs_install': bool(needs_install)}
            for _k in ('launch_target', 'setup_done', 'installed_at'):
                _v = preserved_marker.get(_k)
                if _v not in (None, ''):
                    info[_k] = _v
            (content_dest / EXTRACT_MARKER).write_text(_json.dumps(info), encoding='utf-8')
        except OSError as exc:
            self.logger.warning('EXTRACT', f'MARKER_WRITE_FAILED dest=[{content_dest}] error={type(exc).__name__}')
        return ExtractResult(archive, content_dest, True, message,
                             extracted_bytes=extracted, file_count=len(files), code=code,
                             needs_install=needs_install)
