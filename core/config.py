"""Configuration: the paths this app writes to, and the user's chosen settings.

AppConfig owns every path the app writes under the project root — config/, cache/,
logs/, debug/ — plus the library root, which lives outside it. Settings are read
from and written to config/settings.json as a JSON object, with a tolerated
schema so a hand-edited or truncated file never prevents startup.

A frozen exe also mirrors config into %LOCALAPPDATA% so an update that extracts
the bundle to a new folder does not wipe the setup. sync_to_appdata() copies each
config file there on write, and _migrate_from_appdata() brings them back when the
local tree is fresh or invalid.
"""

from dataclasses import dataclass, field
from pathlib import Path
import json
import os
import sys
import tempfile
import shutil
import time
from datetime import datetime, timezone

from core.constants import APP_NAME, VERSION

ROTATED_LOGS = 10  # keep the last 10 run logs; older ones are removed


@dataclass
class AppConfig:
    """All paths and settings the app persists, rooted on the project directory.

    project_root is where this code lives; every path below it (config/, cache/,
    logs/, debug/) is created lazily. library_root is the game library the user
    configured, which lives outside the project. settings holds the parsed
    contents of config/settings.json; settings_version is reserved for future
    migration of the settings schema.
    """

    project_root: Path
    library_root: Path | None = None
    developer_mode: bool = False
    mock_mode: bool = False
    settings: dict = field(default_factory=dict)
    settings_version: int = 0
    log_file: Path | None = None

    @staticmethod
    def default_library_root():
        return Path.home() / "Downloads" / "Games"

    @staticmethod
    def _appdata_config_dir():
        """Persistent config directory in %LOCALAPPDATA%, or None.

        Stores settings, API keys, and category decisions so they survive
        exe updates that extract the bundle to a new folder. Only used
        when running as a frozen exe on Windows.
        """
        if not getattr(sys, "frozen", False):
            return None
        if os.name != "nt":
            return None
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            return None
        return Path(base) / APP_NAME / "config"

    def __post_init__(self):
        self.project_root = self.project_root.resolve()
        # Every path this app writes, all beneath the project so the app is
        # self-contained and a test can point the root at a temp tree.
        self.config_dir = self.project_root / "config"
        self.cache_dir = self.project_root / "cache"
        self.artwork_dir = self.cache_dir / "artwork"
        self.log_dir = self.project_root / "logs"
        self.debug_dir = self.project_root / "debug"
        self.settings_file = self.config_dir / "settings.json"
        self.state_file = self.config_dir / "scan-state.json"
        test_log = os.environ.get("STEAM_GAME_ORGANIZER_TEST_LOG")
        if test_log:
            self.log_file = Path(test_log)
        elif self.log_file is not None:
            # Explicit log file provided (e.g., for headless URI handlers to reuse main app's log)
            pass
        else:
            # One log file per run, timestamped so old runs are never overwritten
            # and a reader can tell which run produced which log. Rotation keeps
            # the last ROTATED_LOGS so a PC does not accumulate unbounded logs.
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            self.log_file = self.log_dir / f"organizer-{VERSION}-{stamp}.log"
            self._rotate_logs()
        self._migrate_from_appdata()
        self.load()
        if self.library_root is None:
            self.library_root = self.default_library_root()

    def _rotate_logs(self):
        """Keep only the last ROTATED_LOGS run logs; delete older ones so the
        logs directory does not grow without bound across runs."""
        if not self.log_dir.is_dir():
            return
        logs = sorted((p for p in self.log_dir.glob("organizer-*.log") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in logs[ROTATED_LOGS:]:
            try:
                old.unlink()
            except OSError:
                pass

    def _migrate_from_appdata(self):
        """Copy config from %LOCALAPPDATA% when the local config is a fresh extract or has invalid settings.

        An exe update overwrites the local config with defaults from the build.
        When the user has configured this app before, their settings live in
        %LOCALAPPDATA% and are migrated here so the update does not wipe the setup.
        """
        appdata = self._appdata_config_dir()
        if not appdata:
            return
        appdata_settings = appdata / "settings.json"
        if not appdata_settings.is_file():
            return

        # Check if local config is valid (has a settings.json with a valid library_root)
        local_is_valid = False
        if self.settings_file.is_file():
            try:
                local_data = json.loads(self.settings_file.read_text(encoding="utf-8"))
                local_root = local_data.get("library_root", "")
                if local_root and Path(local_root).is_dir():
                    local_is_valid = True
            except (OSError, ValueError, AttributeError):
                pass

        if local_is_valid:
            return

        # Migrate all config files from appdata
        self.config_dir.mkdir(parents=True, exist_ok=True)
        for item in appdata.iterdir():
            if item.is_file():
                dest = self.config_dir / item.name
                shutil.copy2(str(item), str(dest))

    def sync_to_appdata(self):
        """Copy config files to %LOCALAPPDATA% for persistence across exe updates."""
        appdata = self._appdata_config_dir()
        if not appdata:
            return
        try:
            appdata.mkdir(parents=True, exist_ok=True)
            if self.config_dir.is_dir():
                for item in self.config_dir.iterdir():
                    if item.is_file():
                        shutil.copy2(str(item), str(appdata / item.name))
        except OSError:
            pass

    @property
    def convert_archives(self):
        """Whether .zip/.rar should be rebuilt as .7z, defaulting to on.

        Conversion is the expensive part of a scan - it can run for an hour over a large library and needs
        three times the archive size in free disk while it works - so it has to be possible to turn it off
        without turning off the scan. Reading a missing key as True keeps every existing settings file, and
        every user who has never opened this control, on the behaviour they already had.
        """
        return bool(self.settings.get("convert_archives", True))

    @convert_archives.setter
    def convert_archives(self, value):
        self.settings["convert_archives"] = bool(value)
        self.save()

    @property
    def extract_folders(self):
        """The destinations the catalog's Extract button is allowed to use.

        A list rather than a single path because a page cannot show a native folder picker - that is the same
        sandbox boundary that stops it running anything - so the choice has to be offered in the page itself.
        These are the choices it offers, and the protocol handler refuses any destination outside them.

        Deliberately outside the library: an extracted game folder is a directory of loose files, and the
        scanner treats every directory in a category as a game folder. Extracting in place would hand the next
        scan several thousand files to reconsider.
        """
        values = self.settings.get("extract_folders")
        if not isinstance(values, list):
            values = [self.settings["extract_folder"]] if self.settings.get("extract_folder") else []
        cleaned = []
        seen = set()
        for value in values:
            try:
                path = Path(value).expanduser()
            except TypeError:
                continue
            key = str(path)
            if key not in seen:
                seen.add(key)
                cleaned.append(path)
        return cleaned or [Path.home() / "Downloads" / "Extracted"]

    @extract_folders.setter
    def extract_folders(self, values):
        self.settings["extract_folders"] = [str(Path(v).expanduser()) for v in values]
        self.settings.pop("extract_folder", None)
        self.save()

    @property
    def extract_folder(self):
        """The destination used when nothing else was chosen: the first configured folder."""
        return self.extract_folders[0]

    @extract_folder.setter
    def extract_folder(self, value):
        self.extract_folders = [value]

    def ensure_directories(self):
        # A malformed older package could contain a zero-byte file where a
        # runtime directory belongs. Recover those stale artifacts safely so
        # startup does not die with FileExistsError.
        for p in (self.config_dir, self.cache_dir, self.artwork_dir, self.log_dir, self.debug_dir):
            if p.exists() and not p.is_dir():
                backup = p.with_name(p.name + ".invalid-file-backup")
                suffix = 1
                while backup.exists():
                    backup = p.with_name(p.name + f".invalid-file-backup-{suffix}")
                    suffix += 1
                p.replace(backup)
            p.mkdir(parents=True, exist_ok=True)

    def load(self):
        try:
            data = json.loads(self.settings_file.read_text(encoding="utf-8"))
            # Valid JSON is not the same as the JSON this file is written as. A settings.json holding [] or 42
            # - what a hand-edit or another tool leaves behind - reached data.get() and raised AttributeError out
            # of the constructor, so the app would not start at all over its own settings. saved_library_root()
            # below already catches that; this is the read that decides the startup path.
            if not isinstance(data, dict):
                raise ValueError("settings file is not a JSON object")
            value = data.get("library_root")
            if value:
                self.library_root = self._resolve_library(value)
            self.developer_mode = bool(data.get("developer_mode", False))
            self.settings = data
            if not self.library_root:
                self.library_root = self.default_library_root()
            # Extract folders are deliberately not resolved here: a borrowed HD changes drive letters, so
            # D:\Games on the owner's PC may be E:\Games or F:\Games on the reader's. The reader chooses
            # where extraction goes through the Setup wizard rather than having a path silently rewritten.
        except (OSError, ValueError):
            self.settings = {}
            if not self.library_root:
                self.library_root = self.default_library_root()

    def _resolve_library(self, value):
        """Resolve a stored library path, falling back to the folder beside the app when the stored path
        does not exist on this machine. A borrowed HD changes drive letters - the path stored in
        settings.json may be on a drive that does not exist on this PC - but the library always sits
        beside the app, which is project_root."""
        p = Path(value).expanduser()
        if p.is_dir():
            return p.resolve()
        beside = self.project_root
        if beside.is_dir():
            return beside.resolve()
        return p.resolve()

    def saved_library_root(self):
        """The library root as it was last written to disk, or None. Used to avoid replacing a real library
        path with one that has since been deleted."""
        try:
            value = json.loads(self.settings_file.read_text(encoding="utf-8")).get("library_root")
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            return None
        return value if value and Path(value).is_dir() else None

    def save(self):
        # Writing the library root out has to mean something: it is what the app reads next time it starts, and
        # a directory that no longer exists is a worse starting point than no answer at all. Anything setting a
        # root - a scratch directory, a test - can hand it straight back rather than editing the file.
        self.ensure_directories()
        data = dict(self.settings)
        data.update(library_root=str(self.library_root) if self.library_root else "", developer_mode=self.developer_mode)
        if data["library_root"] and not Path(data["library_root"]).is_dir():
            previous = self.saved_library_root()
            if previous:
                print(f"warning: not saving library root {data['library_root']} - the directory does not exist; keeping {previous}", file=sys.stderr)
            data["library_root"] = str(previous or "")
        fd, tmp = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=self.config_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(4):
                try:
                    os.replace(tmp, self.settings_file)
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
        self.sync_to_appdata()

    def save_scan_summary(self, summary):
        """Record what the last scan found, so the scanner can say so before the next one starts.

        Written to `state_file`, which this class had declared and never used. The scan screen has roughly 840px
        of empty panel while idle - a fifth of its height - and the numbers a reader wants before pressing Scan
        are exactly the ones a finished scan already computed and then threw away.

        Best effort by design. This is a convenience readout, so a locked or unwritable file is ignored rather
        than raised: the scan it describes already succeeded, and the alternative is a scan reported as failed
        because its summary could not be filed.
        """
        payload = dict(summary or {})
        payload["recorded_at"] = time.time()
        try:
            self.ensure_directories()
            fd, tmp = tempfile.mkstemp(prefix="scan-state.", suffix=".tmp", dir=self.config_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                # Retried for the same reason settings.json is: this project lives in a synced folder, and a
                # transient lock on the destination is not a reason to lose the summary.
                for attempt in range(4):
                    try:
                        os.replace(tmp, self.state_file)
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
            return None
        self.sync_to_appdata()
        return payload

    def load_scan_summary(self):
        """The last recorded scan summary, or None.

        Tolerates a missing file, an empty one, and one holding valid JSON that is not an object - the same
        three ways the settings file has been found broken, and the same reason each has to be survivable: this
        is read during layout, before anything else has run.
        """
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None
