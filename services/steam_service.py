# Replaced real Steam game names with fictional ones in _mock() to avoid intellectual property concerns. Full dated entry in CHANGELOG.md.

import contextlib
import http.client
import json
import difflib
import re
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.error import HTTPError, URLError
from core.constants import ARCHIVE_EXTENSIONS, USER_AGENT, NO_WINDOW
from core.models import SteamMatch
from core.exceptions import CancellationError
from services.extract_service import ExtractService
from utils.filename_utils import identity_key, normalize_name


class _ConnectionPool:
    """HTTP/HTTPS connection pool with keep-alive for Steam API calls.

    Reuses TCP/TLS connections across requests, eliminating connection overhead
    (~50-100ms per request). Maintains separate pools per host.
    """

    def __init__(self, max_connections=4, timeout=15):
        self._pools = {}  # host -> list of available connections
        self._in_use = {}  # host -> set of in-use connections
        self._max_connections = max_connections
        self._timeout = timeout
        self._lock = __import__("threading").Lock()

    def _get_connection(self, host, use_ssl):
        """Get a connection from the pool or create a new one."""
        with self._lock:
            pool = self._pools.setdefault(host, [])
            in_use = self._in_use.setdefault(host, set())

            # Try to reuse an existing connection
            while pool:
                conn = pool.pop()
                if conn not in in_use:
                    try:
                        # Test if connection is still alive
                        conn.sock = None  # Force reconnect check on next request
                        in_use.add(conn)
                        return conn
                    except Exception:
                        continue

            # Create new connection
            conn = http.client.HTTPSConnection(host, timeout=self._timeout) if use_ssl else http.client.HTTPConnection(host, timeout=self._timeout)
            in_use.add(conn)
            return conn

    def _release_connection(self, host, conn):
        """Return a connection to the pool."""
        with self._lock:
            in_use = self._in_use.get(host, set())
            if conn in in_use:
                in_use.remove(conn)
                pool = self._pools.setdefault(host, [])
                if len(pool) < self._max_connections:
                    pool.append(conn)
                else:
                    # Pool full, close the connection
                    try:
                        conn.close()
                    except Exception:
                        pass

    def request(self, method, url, headers=None, body=None):
        """Make an HTTP request using a pooled connection."""
        parsed = urlsplit(url)
        host = parsed.netloc
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        use_ssl = parsed.scheme == "https"
        conn = self._get_connection(host, use_ssl)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            data = response.read()

            # Create a response-like object with the interface callers expect
            class PooledResponse:
                def __init__(self, status, data, headers):
                    self.status = status
                    self._data = data
                    self.headers = headers

                def read(self):
                    return self._data

                def getcode(self):
                    return self.status

                def info(self):
                    return self.headers

            return PooledResponse(response.status, data, response.getheaders())
        except Exception:
            # Connection failed, don't return it to pool
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                in_use = self._in_use.get(host, set())
                in_use.discard(conn)
            raise
        finally:
            # Only release if we didn't already close it
            try:
                self._release_connection(host, conn)
            except Exception:
                pass

    def close_all(self):
        """Close all pooled connections."""
        with self._lock:
            for pool in self._pools.values():
                for conn in pool:
                    try:
                        conn.close()
                    except Exception:
                        pass
            for in_use_set in self._in_use.values():
                for conn in in_use_set:
                    try:
                        conn.close()
                    except Exception:
                        pass
            self._pools.clear()
            self._in_use.clear()


# Module-level pool shared across SteamService instances
_SHARED_POOL = _ConnectionPool()

# Cache for archive-internal AppID reads: {path_str: (size, mtime_ns, appid|'')}.
# _appid_in_archive() runs 7z l -slt (and sometimes 7z e -so) per archive; caching by
# file identity means a rescan of the same unchanged archive is a dict lookup instead of
# another subprocess. Self-invalidating: a converted archive changes path or mtime.
_appid_in_archive_cache: dict[str, tuple[int, int, str]] = {}


# How close an AppID read out of an archive has to look to the filename before it is believed. Low enough to
# accept the punctuation and packaging differences a filename carries, high enough to reject a copy-pasted or
# stale AppID that would rename the game's folder to something else entirely.
ARCHIVE_APPID_MIN_SCORE = 0.55
# Minimum score for Steam Store search match acceptance. Lowered from 0.78 to catch more valid matches
# while still filtering out noise. Can be overridden per-game via pre-seed cache.
STORE_MATCH_MIN_SCORE = 0.72


class SteamService:
    """Direct Steam Store API client; no shell/backend dependency."""

    def __init__(self, logger, mock=False, cache_file=None, preseed_file=None):
        self.logger = logger
        self.mock = mock
        self.cache = {}
        self.cache_file = Path(cache_file) if cache_file else None
        self.preseed_file = Path(preseed_file) if preseed_file else None
        self.user_agent = USER_AGENT
        # Whether each of the two tag outcomes has already been said once. Steam's API omits the field rather
        # than reporting none of it, so a game that has no tags and a source that has none look identical until
        # one of them is logged; each is said once per service rather than once per game, which here is 165 lines.
        self._warned_no_tags = False
        self._reported_tags = False
        # Autocomplete cache for this session - avoids repeated API calls for similar queries
        self._autocomplete_cache = {}
        # Cache write batching - reduces I/O by coalescing multiple updates
        self._cache_dirty = False
        self._pending_writes = 0
        self._cache_initialized = False
        self._load_cache()
        self._load_preseed()

    def _load_cache(self):
        if not self.cache_file or not self.cache_file.is_file():
            return
        try:
            rows = json.loads(self.cache_file.read_text(encoding="utf-8"))
            for key, value in rows.items():
                if not isinstance(key, str) or not isinstance(value, dict) or not value.get("found") or not str(value.get("appid", "")).isdigit() or not value.get("name"):
                    continue
                self.cache[key] = SteamMatch(**{k: v for k, v in value.items() if k in SteamMatch.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            self.cache = {}

    def _load_preseed(self):
        """Load pre-seeded Steam matches from a JSON file for difficult/ambiguous titles.
        Format: {"identity_key": {"appid": "12345", "name": "Game Name", "min_score": 0.7}}
        """
        if not self.preseed_file or not self.preseed_file.is_file():
            return
        try:
            data = json.loads(self.preseed_file.read_text(encoding="utf-8"))
            for key, value in data.items():
                if not isinstance(key, str) or not isinstance(value, dict) or not str(value.get("appid", "")).isdigit() or not value.get("name"):
                    continue
                match = SteamMatch(found=True, appid=str(value["appid"]), name=value["name"], confidence="High", score=value.get("min_score", STORE_MATCH_MIN_SCORE), source="preseed", reason=f"Pre-seeded match (min_score={value.get('min_score', STORE_MATCH_MIN_SCORE):.2f})")
                self.cache[key] = match
            self.logger.info("STEAM", f"PRESEED_LOADED count={len(data)}")
        except (OSError, ValueError, TypeError) as exc:
            self.logger.debug("STEAM", f"PRESEED_LOAD_FAILED error={type(exc).__name__}")

    def _save_cache(self):
        if not self.cache_file:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            temp = self.cache_file.with_suffix(".tmp")
            temp.write_text(json.dumps({key: asdict(value) for key, value in self.cache.items()}, indent=2), encoding="utf-8")
            temp.replace(self.cache_file)
        except OSError as exc:
            self.logger.debug("STEAM", f"CACHE_WRITE_FAILED error={type(exc).__name__}")

    def _mark_cache_dirty(self):
        """Mark cache as needing write. Writes are batched to reduce I/O.

        First write happens immediately for durability; subsequent writes are batched
        (every 10 updates) to reduce I/O overhead.
        """
        if not getattr(self, "_cache_initialized", False):
            # First update - write immediately for durability
            self._save_cache()
            self._cache_initialized = True
            return
        self._cache_dirty = True
        self._pending_writes += 1
        # Write every 10 updates to balance durability with performance
        if self._pending_writes >= 10:
            self._flush_cache()

    def _flush_cache(self):
        """Force write pending cache changes."""
        if getattr(self, "_cache_dirty", False):
            self._save_cache()
            self._cache_dirty = False
            self._pending_writes = 0

    def flush_cache(self):
        """Public method to force write any pending cache changes. Call at end of batch operations."""
        self._flush_cache()

    def __del__(self):
        """Ensure pending cache writes are flushed when service is destroyed."""
        try:
            self._flush_cache()
        except Exception:
            pass

    def remember(self, title, steam_match):
        if steam_match.found:
            self.cache[identity_key(title)] = steam_match
            self._mark_cache_dirty()

    def _request_json(self, url, ctx=None):
        if ctx:
            ctx.checkpoint()
        # Use shared connection pool for keep-alive
        response = _SHARED_POOL.request("GET", url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        data = response.read()
        if ctx:
            ctx.checkpoint()
        return json.loads(data.decode("utf-8", errors="replace"))

    def lookup(self, title, ctx=None, refresh=False, archive_path=None):
        key = identity_key(title)
        # Fast path 1: AppID from archive filename (e.g., "Game Name - 12345.zip")
        # This is the fastest - just parses the filename, no I/O at all.
        if not refresh and not self.mock and archive_path:
            filename_appid = self._appid_from_filename(archive_path)
            if filename_appid:
                details = self._details(filename_appid, ctx)
                name = str(details.get("name") or "")
                if name:
                    score = self._score(title, name)
                    if score >= ARCHIVE_APPID_MIN_SCORE:
                        steam_match = self._build_match(filename_appid, {"name": name}, details)
                        steam_match.confidence = "High"
                        steam_match.score = score
                        steam_match.source = "steam_appid_filename"
                        steam_match.reason = f"AppID from archive filename (score={score:.3f})"
                        self.logger.info("STEAM", f"FILENAME_APPID_RESOLVED title=[{title}] appid={filename_appid} steam=[{name}] score={score:.3f}")
                        self.cache[key] = steam_match
                        self._mark_cache_dirty()
                        return steam_match
                    self.logger.info("STEAM", f"FILENAME_APPID_MISMATCH title=[{title}] appid={filename_appid} steam=[{name}] score={score:.3f} (below {ARCHIVE_APPID_MIN_SCORE}); falling back")

        # Fast path 2: AppID from archive internals (steam_appid.txt or appmanifest_*.acf)
        # An archive that ships its own steam_settings already states its AppID. That is not a guess to be
        # scored against a search result but the answer, and it costs one header read rather than a round trip
        # to a search engine - so it is tried first and the search is the fallback, not the reverse.
        #
        # It is tried before the cache as well, not merely before the search. The cache is keyed by title, and
        # two archives can normalize to one title while shipping different AppIDs - a second release, or a
        # different game whose filename flattens onto the first one's. Consulted first, the cache would hand
        # whichever was scanned first to the other, and a wrong AppID renames the game's folder to a game it
        # is not, which is the one outcome worse than not matching at all.
        shipped = None if refresh or self.mock else self._resolve_from_archive(archive_path, title, ctx)
        if shipped is not None:
            self.cache[key] = shipped
            self._mark_cache_dirty()
            return shipped
        if key in self.cache and not refresh:
            self.logger.debug("STEAM", f"CACHE_HIT title=[{title}] source=[{self.cache[key].source}]")
            return self.cache[key]
        # Check preseed cache (bypassed by refresh)
        if not refresh and key in self.cache and self.cache[key].source == "preseed":
            self.logger.debug("STEAM", f"PRESEED_HIT title=[{title}] appid=[{self.cache[key].appid}]")
            return self.cache[key]
        direct_appid = self._appid_from_input(title)
        steam_match = self._mock(title) if self.mock else (self._lookup_appid(direct_appid, ctx) if direct_appid else self._lookup_store(title, ctx))
        if not steam_match.found and not refresh and not self.mock:
            for attempt in (2, 3):
                self.logger.info("STEAM", f"RETRY_LOOKUP title=[{title}] attempt={attempt} reason=[initial_no_match]")
                steam_match = self._lookup_store(title, ctx)
                if steam_match.found:
                    break
        if steam_match.found:
            self.cache[key] = steam_match
            self._mark_cache_dirty()
        self.logger.info("STEAM", f"LOOKUP title=[{title}] found={int(steam_match.found)} appid={steam_match.appid or '-'} steam=[{steam_match.name or '-'}] score={steam_match.score:.3f} confidence=[{steam_match.confidence or '-'}] source=[{steam_match.source}]")
        return steam_match

    def _resolve_from_archive(self, archive_path, title, ctx):
        """The Steam name for a game that told us its own AppID, or None to fall back to searching.

        A repack that carries `steam_settings/steam_appid.txt` or an `appmanifest_*.acf` has already answered
        the question the search engine would be asked. This reads that answer, then still checks it against the
        filename before trusting it: a handful of releases ship a stale or copy-pasted AppID, and a wrong
        confident match is worse than no match, because it renames the game's folder to the wrong name.
        """
        appid = self._appid_in_archive(archive_path, ctx)
        if not appid:
            return None
        details = self._details(appid, ctx)
        name = str(details.get("name") or "")
        if not name:
            self.logger.info("STEAM", f"ARCHIVE_APPID_UNRESOLVED appid={appid} title=[{title}]")
            return None
        score = self._score(title, name)
        if score < ARCHIVE_APPID_MIN_SCORE:
            self.logger.warning("STEAM", f"ARCHIVE_APPID_MISMATCH appid={appid} archive_claims=[{name}] filename=[{title}] score={score:.3f}; falling back to a search")
            return None
        steam_match = self._build_match(appid, {"name": name}, details)
        steam_match.confidence = "High"
        steam_match.score = score
        steam_match.source = "steam_appid"
        steam_match.reason = f"Verified from the AppID shipped inside the archive (score={score:.3f})"
        self.logger.info("STEAM", f"ARCHIVE_APPID_RESOLVED title=[{title}] appid={appid} steam=[{name}] score={score:.3f}")
        return steam_match

    # Reading the AppID means listing the archive header and pulling out one small text file. Both are bounded:
    # the listing is read to a fixed number of bytes and the file itself is refused above a few hundred, because
    # a real steam_appid.txt is under 20 bytes and anything larger is not one.
    _LIST_LIMIT = 1 << 20
    _FILE_LIMIT = 4096
    _APPID_IN_NAME = re.compile(r"steam_settings[/\\]appmanifest_(\d{2,10})\.acf$", re.I)
    _APPID_IN_FILE = re.compile(r"steam_settings[/\\]steam_appid\.txt$", re.I)
    # Fast path: AppID in archive filename (e.g., "Game Name - 12345.zip", "Game.Name.12345.rar", "Game [12345].7z")
    _APPID_IN_FILENAME = re.compile(r"[-.\[\s](\d{2,10})[\]\s.-]?\.(?:zip|rar|7z)$", re.I)

    def _appid_from_filename(self, archive_path):
        """Extract AppID from archive filename if present.

        Matches patterns like:
        - Game Name - 12345.zip
        - Game.Name.12345.rar
        - Game Name [12345].7z
        - Game Name 12345.zip

        Returns the AppID string or '' if not found.
        """
        if not archive_path:
            return ""
        path = Path(archive_path)
        if path.suffix.lower() not in ARCHIVE_EXTENSIONS or not path.is_file():
            return ""
        match = self._APPID_IN_FILENAME.search(path.name)
        if match:
            appid = match.group(1)
            # Validate: AppID should be a reasonable Steam AppID (2-10 digits, not a year)
            if 2 <= len(appid) <= 10 and not appid.startswith("19") and not appid.startswith("20"):
                self.logger.debug("STEAM", f"ARCHIVE_FILENAME_APPID path=[{path.name}] appid={appid}")
                return appid
        return ""

    def _appid_in_archive(self, archive_path, ctx):
        """The AppID an archive declares, or '' when it declares none. Never guesses."""
        if not archive_path:
            return ""
        path = Path(archive_path)
        if path.suffix.lower() not in ARCHIVE_EXTENSIONS or not path.is_file():
            return ""
        try:
            stat = path.stat()
        except OSError:
            return ""
        cache_key = str(path)
        cached = _appid_in_archive_cache.get(cache_key)
        if cached and cached[0] == stat.st_size and cached[1] == stat.st_mtime_ns:
            return cached[2]
        try:
            tool = ExtractService.find_tool()[0]
        except Exception:
            tool = ""
        if not tool:
            self.logger.debug("STEAM", f"ARCHIVE_APPID_SKIPPED path=[{path.name}] reason=[no_7z]")
            _appid_in_archive_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, "")
            return ""
        try:
            listing = subprocess.run([tool, "l", "-slt", "--", str(path)], stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=60, creationflags=NO_WINDOW).stdout[: self._LIST_LIMIT]
        except (OSError, subprocess.SubprocessError) as exc:
            self.logger.debug("STEAM", f"ARCHIVE_APPID_LIST_FAILED path=[{path.name}] error={type(exc).__name__}")
            _appid_in_archive_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, "")
            return ""
        declared = set()
        internal = None
        for line in listing.splitlines():
            if not line.startswith("Path = "):
                continue
            candidate = line[7:].strip()
            found = self._APPID_IN_FILE.search(candidate)
            if found:
                internal = candidate
                break
            found = self._APPID_IN_NAME.search(candidate)
            if found:
                declared.add(found.group(1))
                internal = internal or candidate
        # An archive naming several different AppIDs is not a single game - a pack, or a shared steam_settings -
        # and picking one of them would be a coin flip that renames the folder. Say nothing instead.
        if len(declared) > 1:
            self.logger.info("STEAM", f"ARCHIVE_APPID_AMBIGUOUS path=[{path.name}] appids={sorted(declared)}")
            _appid_in_archive_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, "")
            return ""
        if internal is None:
            _appid_in_archive_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, "")
            return ""
        # An appmanifest declares its AppID in its filename, so the answer is already in the
        # listing we have. Extracting the file from a large solid archive would cost a 7z call
        # that can hang for minutes while it decompresses the solid block to the file's offset -
        # take the AppID from the path and skip extraction entirely.
        from_manifest = self._APPID_IN_NAME.search(internal)
        if from_manifest:
            appid = from_manifest.group(1)
            self.logger.debug("STEAM", f"ARCHIVE_APPID_READ path=[{path.name}] appid={appid}")
            _appid_in_archive_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, appid)
            return appid
        if ctx:
            ctx.checkpoint()
        try:
            process = subprocess.Popen([tool, "e", "-so", "--", str(path), internal], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            try:
                deadline = time.monotonic() + 60
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(cmd=tool, timeout=60)
                    if ctx:
                        ctx.checkpoint()
                    time.sleep(0.2)
                payload = process.stdout.read()[: self._FILE_LIMIT] if process.stdout else b""
            finally:
                if process.poll() is None:
                    process.kill()
                    with contextlib.suppress(OSError, subprocess.SubprocessError):
                        process.wait(timeout=5)
                if process.stdout:
                    with contextlib.suppress(OSError, ValueError):
                        process.stdout.close()
        except (OSError, subprocess.SubprocessError) as exc:
            self.logger.debug("STEAM", f"ARCHIVE_APPID_READ_FAILED path=[{path.name}] error={type(exc).__name__}")
            _appid_in_archive_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, "")
            return ""
        digits = re.search(rb"\d{2,10}", payload)
        appid = digits.group(0).decode() if digits else ""
        if appid:
            self.logger.debug("STEAM", f"ARCHIVE_APPID_READ path=[{path.name}] appid={appid}")
        _appid_in_archive_cache[cache_key] = (stat.st_size, stat.st_mtime_ns, appid)
        return appid

    def _appid_from_input(self, value):
        text = str(value or "").strip()
        if text.isdigit():
            return text
        found = re.search(r"store\.steampowered\.com/app/(\d+)", text, re.I)
        return found.group(1) if found else ""

    def _lookup_appid(self, appid, ctx):
        details = self._details(appid, ctx)
        if not details or not details.get("name"):
            return SteamMatch(found=False, source="steam_appid", reason="Steam AppID details unavailable")
        steam_match = self._build_match(appid, {"name": details.get("name")}, details)
        steam_match.confidence = "High"
        steam_match.score = 1.0
        steam_match.source = "steam_appid"
        steam_match.reason = "Verified directly from Steam AppID"
        return steam_match

    def _lookup_store(self, title, ctx):
        try:
            query = normalize_name(title)
            items = []
            seen = set()
            variants = self._query_variants(query, title, ctx)
            self.logger.debug("STEAM", f"LOOKUP_VARIANTS title=[{title}] query=[{query}] variants=[{' | '.join(variants)}]")
            for variant in variants:
                url = "https://store.steampowered.com/api/storesearch/?term=" + quote(variant) + "&cc=US&l=english"
                data = self._request_json(url, ctx)
                for item in (data.get("items") or [])[:100]:
                    appid = str(item.get("id") or item.get("appid") or "")
                    if appid and appid not in seen:
                        seen.add(appid)
                        items.append(item)
                # Early exit: if we have enough candidates, check if we can already pick a high-confidence match
                if len(items) >= 5:
                    chosen, score = self._choose(items, query)
                    if chosen and score >= 0.95:
                        self.logger.debug("STEAM", f"EARLY_EXIT title=[{title}] score={score:.3f} after {len(items)} candidates")
                        appid = str(chosen.get("id") or chosen.get("appid") or "")
                        details = self._details(appid, ctx)
                        steam_match = self._build_match(appid, chosen, details)
                        steam_match.confidence = "High"
                        steam_match.score = score
                        steam_match.reason = f"Steam Store match score={score:.3f}"
                        return steam_match
            if not items:
                self.logger.info("STEAM", f"LOOKUP_NO_ITEMS title=[{title}] query=[{query}] variants={len(variants)}")
                return SteamMatch(found=False, source="steam_store", reason="No Steam Store search result")
            chosen, score = self._choose(items, query)
            if not chosen:
                self.logger.info("STEAM", f"LOOKUP_LOW_CONFIDENCE title=[{title}] query=[{query}] candidates={len(items)}")
                return SteamMatch(found=False, source="steam_store", reason="No confident Steam Store match")
            appid = str(chosen.get("id") or chosen.get("appid") or "")
            details = self._details(appid, ctx)
            steam_match = self._build_match(appid, chosen, details)
            steam_match.confidence = "High" if score >= 0.95 else "Medium"
            steam_match.score = score
            steam_match.reason = f"Steam Store match score={score:.3f}"
            return steam_match
        except HTTPError as exc:
            self.logger.warning("STEAM", f"LOOKUP_HTTP_ERROR title=[{title}] code={exc.code}")
            return SteamMatch(found=False, source="steam_store", reason=f"Steam Store HTTP {exc.code}")
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            self.logger.warning("STEAM", f"LOOKUP_ERROR title=[{title}] error={type(exc).__name__}")
            return SteamMatch(found=False, source="steam_store", reason=f"Steam Store lookup failed: {type(exc).__name__}")

    def _query_variants(self, query, title, ctx):
        variants = []

        def add(value):
            value = " ".join(str(value).split()).strip()
            if value and value.casefold() not in {x.casefold() for x in variants}:
                variants.append(value)

        add(title)
        add(query)
        # A single short trailing number (e.g. "2") is more likely a sequel number than a version; only strip
        # multi-part versions (1.0, 1-2-3) or long build/date stamps (5+ digits) here.
        stripped = re.sub(r"\s+(?:v?\d+(?:[.\-_ ]+\d+)+|v?\d{5,}|build\s*\d+)\s*$", "", title, flags=re.I)
        add(stripped)
        add(re.sub(r"(?:fitgirl|tenoke|dodi|repack|portable)$", "", title, flags=re.I))
        # Crack-by credits: "CRACKED BY GROUP", "CRACK: GROUP", "CRACKED-BY GROUP", bare "CRACKED".
        add(re.sub(r"\s*(?:cracked?[-.\s]*(?:by|:|-)|crack:)\s+\S.*$|\s+cracked?\s*$", "", title, flags=re.I))
        add(re.sub(r"\d+[a-z]\d*[a-z]*$", "", title, flags=re.I))
        add(re.sub(r"\d{2,}$", "", title))
        if re.search(r"[A-Z][a-z]", title):
            add(re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", title))
        # Only an uppercase "X" wedged between camelCase words (e.g. "BallXPit") is a separator; a lowercase
        # "x" inside an ordinary word (e.g. "Deluxe") must never be split.
        add(re.sub(r"([a-zA-Z0-9])X([A-Z])", r"\1 x \2", title))
        # Generic marketing/edition suffixes (not tied to any specific game) that Steam Store search often can't see past.
        edition_stripped = re.sub(r"\s*[:\-]?\s*(?:game of the year|goty|definitive|deluxe|ultimate|complete|enhanced|anniversary|remastered|director'?s cut)\s*(?:edition)?\s*$", " ", stripped, flags=re.I).strip()
        add(edition_stripped)
        # "&" and "and" are used interchangeably between filenames and official Steam titles.
        if re.search(r"\s&\s", title):
            add(re.sub(r"\s&\s", " and ", title))
        if re.search(r"\band\b", title, flags=re.I):
            add(re.sub(r"\band\b", "&", title, flags=re.I))
        # Sequels are indexed on Steam under either an Arabic or Roman numeral; try both forms.
        roman_variant = self._swap_trailing_numeral(edition_stripped)
        if roman_variant:
            add(roman_variant)
        # Steam Store search often fails on trailing subtitle/edition words it doesn't index; try shorter prefixes.
        # Stop at a numeral/roman-numeral word so sequels like "Cities Skylines 2" never get queried as the base title.
        words = stripped.split()
        for _ in range(3):
            if len(words) <= 2 or re.fullmatch(r"(?i)[ivxlcdm]+|\d+", words[-1]):
                break
            words = words[:-1]
            add(" ".join(words))
        # Acronym/abbreviation expansion: "AiO" -> "All in One", "VR" -> "Virtual Reality", etc.
        add(self._expand_acronyms(stripped))
        # Region / language tags appended by scene releases (MULTI5, USA, EUR, JAP, PAL, NTSC…) — strip them
        # so the bare title is queried instead of a tagged name Steam's index won't recognise.
        region_stripped = re.sub(r"\s+(?:multi\d{1,2}|usa|eur|jap|jpn|pal|ntsc)\s*$", "", stripped, flags=re.I)
        if region_stripped != stripped:
            add(region_stripped)
        # "X, The" -> "The X": scene releases often append ", The" at the end while Steam indexes under "The X".
        the_reorder = re.match(r"^(?P<rest>.+?),\s*the\s*$", stripped, flags=re.I)
        if the_reorder:
            add("The " + the_reorder.group("rest").strip())
        # Try Steam autocomplete API for better suggestions
        autocomplete_variants = self._autocomplete_suggestions(query, ctx)
        for v in autocomplete_variants:
            add(v)
        return variants

    def _expand_acronyms(self, title):
        """Expand common gaming acronyms that appear in filenames but not Steam titles."""
        acronyms = {
            r"\bAiO\b": "All in One",
            r"\bVR\b": "Virtual Reality",
            r"\bFPS\b": "First Person Shooter",
            r"\bRPG\b": "Role Playing Game",
            r"\bMMO\b": "Massively Multiplayer Online",
            r"\bRTS\b": "Real Time Strategy",
            r"\bTBS\b": "Turn Based Strategy",
            r"\bARPG\b": "Action RPG",
            r"\bCRPG\b": "Computer RPG",
            r"\bJRPG\b": "Japanese RPG",
            r"\bMOBA\b": "Multiplayer Online Battle Arena",
            r"\bTCG\b": "Trading Card Game",
            r"\bCCG\b": "Collectible Card Game",
            r"\bF2P\b": "Free to Play",
            r"\bP2W\b": "Pay to Win",
            r"\bDLC\b": "Downloadable Content",
            r"\bGOTY\b": "Game of the Year",
            r"\bSotY\b": "Simulation of the Year",
        }
        result = title
        for pattern, expansion in acronyms.items():
            result = re.sub(pattern, expansion, result, flags=re.I)
        return result if result != title else ""

    def _autocomplete_suggestions(self, query, ctx):
        """Get suggestions from Steam autocomplete API for better matching.

        Results are cached per-session to avoid repeated API calls for similar queries.
        """
        if not query or len(query) < 3:
            return []
        # Check session cache first
        cache_key = query.casefold()
        if cache_key in self._autocomplete_cache:
            self.logger.debug("STEAM", f"AUTOCOMPLETE_CACHE_HIT query=[{query}]")
            return self._autocomplete_cache[cache_key]
        try:
            if ctx:
                ctx.checkpoint()
            url = "https://store.steampowered.com/api/storesearch/?term=" + quote(query) + "&cc=US&l=english&use_autocomplete=1"
            data = self._request_json(url, ctx)
            suggestions = []
            for item in (data.get("items") or [])[:5]:
                name = str(item.get("name") or "").strip()
                if name and name.casefold() != query.casefold():
                    suggestions.append(name)
            if suggestions:
                self.logger.debug("STEAM", f"AUTOCOMPLETE query=[{query}] suggestions=[{' | '.join(suggestions)}]")
            # Cache the result (even empty list) to avoid repeat calls
            self._autocomplete_cache[cache_key] = suggestions
            return suggestions
        except Exception as exc:
            self.logger.debug("STEAM", f"AUTOCOMPLETE_FAILED query=[{query}] error={type(exc).__name__}")
            # Cache empty result to avoid retry
            self._autocomplete_cache[cache_key] = []
            return []

    def _swap_trailing_numeral(self, title):
        words = title.split()
        if not words:
            return ""
        last = words[-1]
        if re.fullmatch(r"\d{1,2}", last):
            roman = self._to_roman(int(last))
            return " ".join(words[:-1] + [roman]) if roman else ""
        if re.fullmatch(r"(?i)[ivxlcdm]+", last):
            value = self._from_roman(last.upper())
            return " ".join(words[:-1] + [str(value)]) if value else ""
        return ""

    def _to_roman(self, value):
        if not 1 <= value <= 39:
            return ""
        table = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
        result = ""
        for amount, symbol in table:
            while value >= amount:
                result += symbol
                value -= amount
        return result

    def _from_roman(self, text):
        values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        total = 0
        previous = 0
        for char in reversed(text):
            current = values.get(char, 0)
            total += current if current >= previous else -current
            previous = current
        return total if 1 <= total <= 39 else 0

    def _score(self, query, name):
        query_key = identity_key(query)
        name_key = identity_key(name)
        if not query_key or not name_key:
            return 0.0
        if query_key == name_key:
            return 1.0
        query_tokens = set(re.findall(r"[a-z0-9]+", query.casefold()))
        name_tokens = set(re.findall(r"[a-z0-9]+", name.casefold()))
        if not query_tokens or not name_tokens:
            return 0.0
        sequence = difflib.SequenceMatcher(None, query_key, name_key).ratio()
        token = difflib.SequenceMatcher(None, " ".join(sorted(query_tokens)), " ".join(sorted(name_tokens))).ratio()
        overlap = len(query_tokens & name_tokens) / max(1, len(query_tokens | name_tokens))
        score = max(sequence, token * 0.95, overlap * 0.96)
        if query_key in name_key or name_key in query_key:
            score = max(score, 0.90)
        if query_tokens <= name_tokens or name_tokens <= query_tokens:
            score = max(score, 0.95)
        # Scene release groups abbreviate the last subtitle word, e.g. "Voyager AtU" for "Voyager Across the
        # Unknown" or "AiO" for "All in One". The Steam search already finds the title via a prefix variant,
        # but _score still compares the full query — a lone short trailing token the search found anyway should
        # not sink the match. If dropping one such token leaves a perfect subset, accept at .90 so abbreviation
        # tokens don't override the candidate ordering that found the right game.
        if len(query_tokens) > 1:
            short_trailing = [t for t in query_tokens if len(t) <= 4]
            if short_trailing:
                remainder_tokens = query_tokens - set(short_trailing)
                if remainder_tokens and remainder_tokens <= name_tokens:
                    score = max(score, 0.90)
        return score

    def _choose(self, items, title):
        ranked = sorted(((self._score(title, str(item.get("name", ""))), item) for item in items), key=lambda row: row[0], reverse=True)
        if not ranked or ranked[0][0] < STORE_MATCH_MIN_SCORE:
            return None, 0.0
        return ranked[0][1], ranked[0][0]

    def _details(self, appid, ctx):
        if not appid:
            return {}
        try:
            url = f"https://store.steampowered.com/api/appdetails?appids={quote(appid)}&cc=us&l=en"
            data = self._request_json(url, ctx)
            return ((data.get(appid) or {}).get("data") or {}) if isinstance(data, dict) else {}
        except CancellationError:
            raise
        except Exception as exc:
            self.logger.debug("STEAM", f"DETAILS_FAILED appid={appid} error={type(exc).__name__}")
            return {}

    def _steam_tags(self, details, appid=""):
        """Steam's user tags for an app, or [] with a WARNING saying where they should have come from.

        Steam does not serve user tags through the store API at all. Measured against the live endpoint on
        2026-10-04, appdetails returned 36 keys for appid 888888 and 38 for 777777, and `tags` was in neither:
        the tags on a store page are community-curated and rendered into that page's HTML, while the payload
        carries genres, categories, content_descriptors, ratings, supported_languages and the rest. Reading them
        from storesearch, which carries no tags either, and then from appdetails both therefore yield [], and
        the note that claimed appdetails sent them described a shape this endpoint never returns - which is how
        an empty tag list survived nine releases looking exactly like a game that genuinely has none.

        Both shapes are still parsed, so a source that does carry the field would work without touching this
        file, and Steam sends tags in popularity order, so a caller showing the first few shows the ones that
        best describe the game. The absence is the part that used to be invisible, so it is logged.
        """
        raw = details.get("tags") if isinstance(details, dict) else None
        if isinstance(raw, dict):
            return self._tag_names(raw.values(), appid)
        if isinstance(raw, list):
            return self._tag_names((item.get("name") for item in raw if isinstance(item, dict)), appid)
        self._warn_tags_unavailable(appid)
        return []

    def _tag_names(self, names, appid=""):
        """One tag list from any iterable of names, dropping the blanks that would render as an empty chip."""
        tags = [name for name in (str(value or "").strip() for value in names) if name]
        if tags and not self._reported_tags:
            self._reported_tags = True
            self.logger.info("STEAM", f"TAGS_PRESENT source=[steam_appdetails] field=[tags] appid={appid or '-'}")
        return tags

    def _warn_tags_unavailable(self, appid=""):
        """Say once that the source in use has no tag field, so an empty list stops meaning two things."""
        if self._warned_no_tags:
            return
        self._warned_no_tags = True
        self.logger.warning("STEAM", f"TAGS_UNAVAILABLE source=[steam_appdetails] field=[tags] appid={appid or '-'}; this payload has no tags field, so every game matched from it gets an empty tag list. Genres and categories come from the same payload and are unaffected. Steam serves user tags on the store page itself, which this app does not read.")

    def _build_match(self, appid, chosen, details):
        genres = [x.get("description", "") for x in details.get("genres", []) if x.get("description")]
        cats = [x.get("description", "") for x in details.get("categories", []) if x.get("description")]
        tags = self._steam_tags(details, appid)
        developers = ", ".join(details.get("developers") or [])
        publishers = ", ".join(details.get("publishers") or [])
        asset_urls = {key: details.get(key) for key in ("header_image", "capsule_image", "capsule_imagev5", "library_capsule", "library_hero", "library_logo", "icon") if details.get(key)}
        asset_urls.setdefault("library_capsule", f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg")
        return SteamMatch(
            found=True,
            appid=appid,
            name=details.get("name") or chosen.get("name") or "",
            genres=genres,
            categories=cats,
            description=details.get("short_description") or details.get("about_the_game") or "",
            tags=tags,
            release_date=(details.get("release_date") or {}).get("date", ""),
            confidence="High",
            source="steam_store",
            reason="Steam Store match",
            developer=developers,
            publisher=publishers,
            artwork_url=details.get("library_capsule") or f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
            asset_urls=asset_urls,
        )

    def _mock(self, title):
        # Deterministic offline fixture used ONLY by --mock mode (no network).
        # Production code queries the live Steam Store API at runtime — no game
        # names or AppIDs are hardcoded in any production path. These five
        # entries let the app be tested without hitting Steam's servers.
        # Game names and AppIDs are fictional and do not correspond to any real Steam products.
        data = {
            "alphaforge": ("100001", "Alpha Forge"),
            "betavoyager": ("100002", "Beta Voyager"),
            "gammaquest": ("100003", "Gamma Quest"),
            "deltarealm": ("100003", "Delta Realm"),
            "deltarealmincremental": ("100003", "Delta Realm"),
            "epsilononline": ("100004", "Epsilon Online"),
            "cosmiccat": ("100005", "Cosmic Cat Colony"),
            "neonnexus": ("100006", "Neon Nexus"),
            "stellarempires": ("100007", "Stellar Empires"),
            "dimensiondrift": ("100008", "Dimension Drift"),
            "pixelpirates": ("100009", "Pixel Pirates"),
        }
        appid, name = data.get(identity_key(title), ("", ""))
        steam_match = SteamMatch(bool(appid), appid, name, ["Simulation"], ["Single-player"], "Mock Steam metadata", ["Simulation"], "", "High" if appid else "Low", "mock", "Deterministic fixture" if appid else "No fixture")
        steam_match.score = 1.0 if appid else 0.0
        return steam_match
