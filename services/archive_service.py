# Replaced real Steam game names with fictional ones in _mock() to avoid intellectual property concerns. Full dated entry in CHANGELOG.md.
# 2026-11-10: Added incremental discovery — _walk_changed_files() skips directories whose max file mtime matches
# the persisted scan-state.json cache, so a re-scan of an unchanged library costs one stat per directory instead
# of one per file. discover() gained a use_cache parameter; batch_extract_service passes False so plan_batch
# always sees fresh archives. Removed now-unused walk_files import.
# 2026-11-12: _config_dir_for now resolves config inside the project root
# (Path(__file__).resolve().parents[1] / "config") instead of library_root.parent/config which leaked outside
# the project to E:\config. application.py still passes config_dir=self.config.config_dir explicitly; this
# fallback covers every other caller.
from pathlib import Path
import os
import re
import subprocess
import tempfile
import zipfile
import time
import json
# Imports split one per line for GitHub readability; -p123 replaced by DEFAULT_ZIP_PASSWORD below.
from core.models import GameArchive, ScanResult
from core.constants import ARCHIVE_EXTENSIONS, LIBRARY_RESERVED_DIRS, TEMP_DIR_PREFIX, TEMP_FILE_TAG, NO_WINDOW, DEFAULT_ZIP_PASSWORD
from core.exceptions import CancellationError
from services.installer_detect import InstallSignature, installer_from_names
from services.library_service import _is_app_folder
from utils.filename_utils import normalize_name, identity_key, version_key

# Installer-kind sniffs read each archive's index - a `7z l -slt` subprocess call for 7z/rar, a zipfile open
# for zip. One archive can be sniffed more than once in a single run (batch plan, then extract, then catalog
# badge), and each ArchiveService instance is short-lived, so an instance cache would not survive the boundary.
# This module-level cache is keyed by the file's identity (path + size + mtime_ns) so a second sniff of the same
# unchanged archive is a dict lookup instead of another index read. Entries are self-invalidating: a converted
# archive changes path or mtime, so a stale entry is never returned for a file that has since been rewritten.
_installer_kind_cache: dict[str, tuple[int, int, InstallSignature | None]] = {}


class ArchiveService:
    def __init__(self, logger, mock=False, config_dir=None):
        self.logger = logger
        self.mock = mock
        # Cache for directory mtimes to enable incremental discovery
        self._discovery_cache = {}
        self._config_dir = Path(config_dir) if config_dir else None

    def _config_dir_for(self, library_root):
        """Return the config directory for scan state. Uses the app's project-root config_dir when
        available, otherwise falls back to project_root/config (inside the project) instead of
        library_root.parent/config which resolved outside the project root."""
        if self._config_dir is not None:
            return self._config_dir
        return Path(__file__).resolve().parents[1] / "config"

    def _load_discovery_cache(self, library_root):
        """Load directory mtimes from config/scan-state.json for incremental discovery."""
        try:
            config_dir = self._config_dir_for(library_root)
            state_file = config_dir / "scan-state.json"
            if not state_file.is_file():
                return {}
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return data.get("discovery_dir_mtimes", {})
        except (OSError, ValueError, AttributeError):
            return {}

    def _save_discovery_cache(self, library_root, dir_mtimes):
        """Save directory mtimes to config/scan-state.json for incremental discovery."""
        try:
            config_dir = self._config_dir_for(library_root)
            state_file = config_dir / "scan-state.json"
            existing = {}
            if state_file.is_file():
                try:
                    existing = json.loads(state_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
            existing["discovery_dir_mtimes"] = dir_mtimes
            existing["recorded_at"] = time.time()
            config_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="scan-state.", suffix=".tmp", dir=config_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2)
                for attempt in range(4):
                    try:
                        os.replace(tmp, state_file)
                        break
                    except PermissionError:
                        if attempt == 3:
                            raise
                        time.sleep(0.05 * (attempt + 1))
            finally:
                try:
                    os.unlink(tmp)
                except FileNotFoundError:
                    pass
        except (OSError, TypeError, ValueError):
            pass

    def _walk_changed_files(self, root, dir_mtimes_cache):
        """Collect files under root, skipping directories whose mtime hasn't changed since the last scan.

        A directory whose max file mtime matches the cache holds no new, modified, or deleted archives,
        so every file beneath it can be skipped without a stat. This is the whole of incremental
        discovery: a library whose games haven't changed costs one stat per directory instead of one per file.

        Returns (files, updated_cache) where updated_cache maps resolved directory path -> max mtime_ns
        of files beneath it.
        """
        files = []
        updated = {}
        stack = [Path(root)]
        seen = set()

        while stack:
            current = stack.pop()
            try:
                resolved = current.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)

            try:
                dir_stat = current.stat()
            except OSError:
                continue

            cache_key = str(resolved)
            cached_mtime = dir_mtimes_cache.get(cache_key)
            if cached_mtime is not None and cached_mtime == dir_stat.st_mtime_ns:
                # Directory unchanged: every file under it is as it was at the last scan.
                updated[cache_key] = dir_stat.st_mtime_ns
                continue

            updated[cache_key] = dir_stat.st_mtime_ns

            try:
                entries = sorted(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_dir():
                        stack.append(entry)
                    else:
                        files.append(entry)
                except OSError:
                    continue

        return files, updated

    def discover(self, root: str | Path, ctx=None, progress=None, new_only: bool = False, unlock_zip: bool = False, preview_only: bool = False, use_cache: bool = True) -> ScanResult:
        if self.mock:
            return self._mock(ctx, progress)
        root = Path(root).expanduser().resolve()
        result = ScanResult()
        if not root.is_dir():
            result.errors.append(f"Library folder does not exist: {root}")
            return result
        started = time.monotonic()
        self.logger.info("ARCHIVE", f"DISCOVERY_START root=[{root}] new_only={int(new_only)} unlock_zip={int(unlock_zip)} preview_only={int(preview_only)}")
        reserved = {root / name for name in LIBRARY_RESERVED_DIRS}
        candidates = 0
        total_size = 0
        supported = 0
        skipped = 0

        # Incremental discovery: load directory mtimes from the last scan, skip whole
        # directories whose max file mtime hasn't changed. A library whose games haven't
        # moved costs one stat per directory instead of one per file.
        dir_mtimes_cache = self._load_discovery_cache(root) if use_cache else {}
        paths, updated_dir_mtimes = self._walk_changed_files(root, dir_mtimes_cache)
        paths = sorted(paths)
        for index, path in enumerate(paths, 1):
            if ctx:
                ctx.checkpoint()
            # Hidden directories are not part of a game library. Syncthing keeps superseded copies under
            # .stversions, and on a real library that made discovery report 525 archives when the library held
            # 174: two thirds of the count, and every archive count and byte total on every screen, were old
            # versions being presented as games. It also swept in 82 truncated 32-byte downloads that 7z
            # rejects outright, which would each have been offered for conversion during Organize.
            if any(parent.name.startswith(".") for parent in path.relative_to(root).parents):
                skipped += 1
                continue
            if not path.is_file() or any(parent in reserved for parent in path.parents):
                skipped += 1
                continue
            # The app's own project folder is not a game category. When the app is installed inside the
            # library root - which is the default - every scan walked it as a folder of one game: the app
            # itself, and the feed listed its runtime files, its bundled Python and its timezone tables as
            # archives. Discovery had no test for it at all; the audit, repair and catalog passes all had
            # one and skipped it, which is why those phases were clean while discovery reported hundreds of
            # files that were never games. The entry-point filename identifies the project regardless of
            # what the folder is called, so renaming the project folder no longer re-adds it to the catalog.
            #
            # The library root itself is exempt from this check, on purpose. In the shared-library layout
            # the app is installed in the game folder, so the library root IS the app folder - and every
            # file under it would then match, discovery would find nothing at all, and the verify screen
            # would show no games with no way to continue. The root is the thing being scanned; only a
            # folder strictly inside it that happens to hold the entry point is the app's project folder.
            if any(_is_app_folder(parent) for parent in path.parents if parent != root):
                skipped += 1
                continue
            # Never offer the app's own in-flight work as a game. An extraction folder sits inside the game
            # folder while a conversion runs, and a nested archive inside the game archive shows up in it;
            # the no-library-root fallback writes the half-built replacement beside the source. Offering either
            # put a temp artefact into the review queue under a name of its own, and an Organize press would
            # then file it under a category as if it were a separate game.
            if self._is_own_temp_artefact(path):
                skipped += 1
                continue
            if path.suffix.lower() not in ARCHIVE_EXTENSIONS:
                if progress and index % 25 == 0:
                    progress(candidates, index, len(paths), total_size, supported, skipped, path)
                continue
            # Preview Only rewrites nothing. A password-protected zip cannot be inspected without rewriting it
            # (the unlock routine rebuilds the archive in place), so under preview it is reported as locked and
            # uninspectable instead of being opened. A plain zip is left alone just as it was found: the unlock
            # pass below is gated on unlock_zip, and preview does not set it.
            if preview_only and path.suffix.lower() == ".zip" and self._is_encrypted_zip(path):
                skipped += 1
                result.errors.append(f"Password-protected archive cannot be inspected in Preview Only: {path}")
                self.logger.info("ARCHIVE", f"ZIP_LOCKED_IN_PREVIEW path=[{path}] reason=[rewriting to inspect is a write, and Preview Only writes nothing]")
                if progress and index % 25 == 0:
                    progress(candidates, index, len(paths), total_size, supported, skipped, path)
                continue
            # Password removal runs on every matching file regardless of new_only, since new_only only
            # controls which archives are presented for (re)organization below. RAR conversion + the
            # official-name folder rename happen later, at organize time, once the Steam name is known.
            if unlock_zip and path.suffix.lower() == ".zip":
                self._remove_zip_password(path, ctx)
            if new_only and self._is_managed(path):
                if progress and index % 25 == 0:
                    progress(candidates, index, len(paths), total_size, supported, skipped, path)
                continue
            candidates += 1
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            total_size += size
            supported += 1
            title = normalize_name(path.name)
            result.archives.append(GameArchive(path, title, title, identity_key(title), path.suffix.lower(), version_key(path.name), size=size))
            if progress:
                progress(candidates, index, len(paths), total_size, supported, skipped, path)
        self.logger.info("ARCHIVE", f"DISCOVERY_FINISH archives={len(result.archives)} total_bytes={total_size} files_seen={len(paths)} elapsed_ms={int((time.monotonic() - started) * 1000)}")
        result.stale_build_dirs, result.stale_build_bytes = self._stale_build_dirs(root)
        if result.stale_build_dirs:
            self.logger.warning("ARCHIVE", f"STALE_BUILD_DIRS count={result.stale_build_dirs} bytes={result.stale_build_bytes}")
        if progress:
            progress(len(result.archives), len(paths), len(paths), total_size, supported, skipped, None)
        # Persist directory mtimes so the next scan skips unchanged directories.
        if use_cache:
            self._save_discovery_cache(root, updated_dir_mtimes)
        return result

    def _stale_build_dirs(self, root):
        """Build folders left behind by an earlier run, and the disk space they are still holding.

        A conversion stages its work in a TEMP_DIR_PREFIX folder and sweeps it in a finally block, but a run
        that was cancelled, or the process killed, never reached it. Those folders are already excluded from
        discovery, so they cost nothing to scan and everything to ignore: this only measures them so the scan
        can say so, rather than deleting on its own initiative. Nothing is removed here.
        """
        count = 0
        total = 0
        try:
            candidates = sorted(p for p in Path(root).rglob(f"{TEMP_DIR_PREFIX}*") if p.is_dir())
        except OSError:
            return 0, 0
        for folder in candidates:
            count += 1
            try:
                for child in folder.rglob("*"):
                    try:
                        if child.is_file() and not child.is_symlink():
                            total += child.stat().st_size
                    except OSError:
                        pass
            except OSError:
                pass
        return count, total

    def archive_installer_kind(self, path: str | Path):
        """''iso', 'repack', or None: whether the archive at `path` is an installer rather than a ready-to-play game.

        Reads only the archive's own index - never its payload. Best-effort: any failure (no extraction tool, a
        locked zip, a format the bundled 7z cannot read) returns None so a catalog is never stuck on the one
        archive this machine cannot inspect; the post-extraction "Needs Install" marker is the fallback for those.
        """
        path = Path(path)
        suffix = path.suffix.lower()
        # Stat is needed for the cache key; when the file is missing there is nothing
        # to cache, so proceed straight to the sniff (which will fail on its own).
        stat = None
        cache_key = None
        cached = None
        try:
            stat = path.stat()
            cache_key = str(path)
            cached = _installer_kind_cache.get(cache_key)
            if cached and cached[0] == stat.st_size and cached[1] == stat.st_mtime_ns:
                return cached[2]
        except OSError:
            pass
        try:
            if suffix == ".zip":
                with zipfile.ZipFile(path) as handle:
                    names = handle.namelist()
            else:
                # .7z/.7za/.rar are listed with the same bundled 7z the extractor uses; it reads 7z and rar indexes
                # without unpacking, so this is a header scan, not an extraction. -slt gives one `Path =` line per
                # member, which parses cleanly even when names contain spaces or unicode. No `--`/`-p` here: 7z does
                # not use a "--" option terminator and a bare `-p` would ask for a password this archive has none.
                from services.extract_service import ExtractService

                tool, _reason = ExtractService.find_tool()
                if not tool:
                    if stat is not None:
                        _installer_kind_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, None)
                    return None
                proc = subprocess.run([tool, "l", "-slt", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
                if proc.returncode != 0:
                    if stat is not None:
                        _installer_kind_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, None)
                    return None
                names = [m.group(1) for m in re.finditer(r"^Path = (.*)$", proc.stdout, re.M)]
            result = installer_from_names(names)
            if stat is not None:
                _installer_kind_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, result)
            return result
        except Exception as exc:
            self.logger.warning("ARCHIVE", f"INSTALLER_SNIFF_FAILED path=[{path.name}] error={type(exc).__name__}")
            return None

    @staticmethod
    def _is_encrypted_zip(path):
        # True when the zip at path has at least one encrypted entry. Read from the local file header rather
        # than by attempting to extract: a password-protected archive is exactly the case this is asked about,
        # and opening one to test it is the write this routine exists to avoid. The encrypted bit lives in the
        # general-purpose flag, so the whole file is never touched.
        try:
            with zipfile.ZipFile(path) as source:
                return any(info.flag_bits & 0x1 for info in source.infolist() if not info.is_dir())
        except Exception:
            return False

    def _remove_zip_password(self, path, ctx=None):
        # A file that vanished between discovery and the unlock pass is not a failure: it was moved or
        # deleted by an earlier organize, and reporting a warning for it would put a red row on the
        # Done screen for a game that is already filed. Return False quietly rather than raising.
        if not path.is_file():
            return False
        temp_name = None
        try:
            original_stat = path.stat()
            with zipfile.ZipFile(path) as source:
                entries = source.infolist()
                if not any(info.flag_bits & 0x1 for info in entries if not info.is_dir()):
                    return False
                fd, temp_name = tempfile.mkstemp(prefix=f".organizer-zip-{path.stem}.", suffix=".zip", dir=path.parent)
                os.close(fd)
                with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED) as target:
                    for info in entries:
                        if ctx:
                            ctx.checkpoint()
                        # "123" was hardcoded here as the FitGirl/repack zip password; it now comes from
                        # DEFAULT_ZIP_PASSWORD so the value lives in core.constants, not four call sites.
                        target.writestr(info, b"" if info.is_dir() else source.read(info, pwd=DEFAULT_ZIP_PASSWORD.encode()))
            # The replace has to happen with the source handle closed, which means outside the with block
            # above. It used to run inside it, so the archive was still open when os.replace tried to swap it -
            # and CPython opens a file without FILE_SHARE_DELETE, so on Windows that raises PermissionError
            # [WinError 5]. The broad except below swallowed it and returned False, which meant this routine
            # decompressed and rewrote the whole archive on every scan and threw the result away, for every
            # encrypted zip, on the platform this app is primarily run on. It then went on to fail the archive's
            # integrity test for lack of a password and report it as corrupt.
            os.replace(temp_name, path)
            temp_name = None
            try:
                os.chmod(path, original_stat.st_mode & 0o7777)
                os.utime(path, (original_stat.st_atime, original_stat.st_mtime))
            except OSError as metadata_error:
                self.logger.warning("ARCHIVE", f"ZIP_METADATA_RESTORE_FAILED path=[{path.name}] error={type(metadata_error).__name__}")
            self.logger.info("ARCHIVE", f"ZIP_PASSWORD_REMOVED path=[{path.name}]")
            return True
        except CancellationError:
            raise
        except NotImplementedError:
            return self._remove_zip_password_external(path, ctx)
        except Exception as exc:
            self.logger.warning("ARCHIVE", f"ZIP_PASSWORD_REMOVE_FAILED path=[{path.name}] error={type(exc).__name__}")
            return False
        finally:
            # Both the failed replace and the NotImplementedError path (WinZip AES, which zipfile cannot
            # decrypt) can leave a rewritten temp archive sitting next to the game.
            if temp_name and os.path.exists(temp_name):
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass

    def _remove_zip_password_external(self, path, ctx=None):
        # WinZip AES (method 99) is what every password-protected game zip in this library actually is, and
        # Python's zipfile cannot decrypt it - it raises NotImplementedError, which is why this fallback
        # exists. The old implementation used Info-ZIP unzip and zip, neither of which is installed on a
        # stock Windows box: both returned None from shutil.which, and subprocess.run raised
        # FileNotFoundError, which was reported as a warning for a game that was already filed.
        # 7-Zip reads AES and accepts -p, and it is already required below to build the .7z, so it is the
        # one tool that is always here. The fallback now uses it directly.
        if not path.is_file():
            return False
        temp_dir = None
        temp_zip_path = None
        try:
            original_stat = path.stat()
            from services.extract_service import ExtractService

            sevenzip, _reason = ExtractService.find_tool()
            if not sevenzip:
                self.logger.warning("ARCHIVE", f"ZIP_PASSWORD_REMOVE_FAILED path=[{path.name}] error=[no 7z/7za to decrypt WinZip AES]")
                return False
            temp_dir = Path(tempfile.mkdtemp(prefix=".organizer-unzip-", dir=str(path.parent)))
            if ctx:
                ctx.checkpoint()
            extract = subprocess.run([sevenzip, "x", "-y", "-p" + DEFAULT_ZIP_PASSWORD, f"-o{temp_dir}", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
            if extract.returncode != 0:
                self.logger.warning("ARCHIVE", f"ZIP_PASSWORD_REMOVE_FAILED path=[{path.name}] error=[7z extraction failed exit={extract.returncode}]")
                return False
            if ctx:
                ctx.checkpoint()
            # Create temp zip next to original to avoid cross-drive I/O that can stress flaky USB enclosures
            temp_zip = path.with_name(f"{path.stem}.organizer-temp.{os.getpid()}.{time.time_ns()}.zip")
            rebuilt = subprocess.run([sevenzip, "a", "-tzip", "-mx=1", str(temp_zip), "."], cwd=str(temp_dir), stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
            if rebuilt.returncode != 0:
                self.logger.warning("ARCHIVE", f"ZIP_PASSWORD_REMOVE_FAILED path=[{path.name}] error=[7z rebuild failed exit={rebuilt.returncode}]")
                # Clean up on failure
                try:
                    if temp_zip.exists():
                        temp_zip.unlink()
                except OSError:
                    pass
                return False
            os.replace(str(temp_zip), str(path))
            try:
                os.chmod(path, original_stat.st_mode & 0o7777)
                os.utime(path, (original_stat.st_atime, original_stat.st_mtime))
            except OSError as metadata_error:
                self.logger.warning("ARCHIVE", f"ZIP_METADATA_RESTORE_FAILED path=[{path.name}] error={type(metadata_error).__name__}")
            self.logger.info("ARCHIVE", f"ZIP_PASSWORD_REMOVED_7Z path=[{path.name}]")
            return True
        except CancellationError:
            raise
        except Exception as exc:
            self.logger.warning("ARCHIVE", f"ZIP_PASSWORD_REMOVE_FAILED path=[{path.name}] error={type(exc).__name__}")
            return False
        finally:
            if temp_zip_path and os.path.exists(temp_zip_path):
                try:
                    os.unlink(temp_zip_path)
                except OSError:
                    pass
            if temp_dir:
                for child in sorted(temp_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
                    try:
                        child.unlink() if child.is_file() or child.is_symlink() else child.rmdir()
                    except OSError:
                        pass
                try:
                    temp_dir.rmdir()
                except OSError:
                    pass

    def _is_own_temp_artefact(self, path):
        """True for a file that is part of a conversion in progress rather than a game.

        Recognised by name in either position: a file carrying the temp tag is the half-built replacement, and
        anything inside a repack folder is extracted content that happens to be an archive - which the game
        archive legitimately contains and which will still be there, inside the real archive, once the
        conversion finishes."""
        if TEMP_FILE_TAG in path.name:
            return True
        return any(parent.name.startswith(TEMP_DIR_PREFIX) for parent in path.parents)

    def _is_managed(self, path):
        parent = path.parent
        return any((parent / name).is_file() for name in ("Open Steam Page.html", "Open Steam Page.desktop", "Open Steam Page in Chrome.desktop", "Open Steam Page (Steam Deck).desktop", "Open Steam Page (Windows).url"))

    def _mock(self, ctx, progress=None):
        # Replaced a real Steam game name with fictional "Nebula Online" per the
        # no-real-game-names rule (see tools/validate_game_names.py deny list).
        names = ["Alpha Forge v 0 8.zip", "Gamma Quest v 1 0.zip", "Delta Realm Incremental.zip", "Nebula Online.zip"]
        result = ScanResult()
        total = 0
        for i, n in enumerate(names, 1):
            if ctx:
                ctx.checkpoint()
            p = Path("/mock/library") / n
            title = normalize_name(n)
            result.archives.append(GameArchive(p, title, title, identity_key(title), p.suffix, version_key(n), size=i * 1024))
            total += i * 1024
            if progress:
                progress(i, i, len(names), total, i, 0, p)
        self.logger.info("ARCHIVE", f"MOCK_DISCOVERY archives={len(result.archives)}")
        return result
