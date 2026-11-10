from pathlib import Path
from core.constants import USER_AGENT
from core.models import ArtworkResult
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json
import time
import shutil
from core.exceptions import CancellationError
from utils.filename_utils import identity_key

# JPEG frame headers, which is where the real width and height live: every marker from SOF0 to SOF15 except
# the three in that range that are not frame headers at all (DHT, JPG and DAC).
_SOF_MARKERS = {marker for marker in range(0xC0, 0xD0)} - {0xC4, 0xC8, 0xCC}


def image_shape(path):
    """True if the image at path is portrait, False if it is wide, None if it cannot be read as a JPEG.

    Read from the file's own header rather than by shelling out to ffprobe, because that made the answer depend
    on whether ffmpeg happened to be installed on the machine. It was not: missing ffprobe raised, the failure
    was caught, and the function returned False - indistinguishable from "wide". Every caller below deletes what
    it is told is the wrong shape, so on a machine without ffmpeg the cache emptied itself at startup and every
    portrait download was thrown away the instant it landed. That is why the artwork worked on some machines and not
    on others. Unknown is now a third answer, and nothing is deleted on it: a cache is cheap to keep and
    expensive to lose, and an unreadable file is a reason to look again, not to delete.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read(65536)
    except OSError:
        return None
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if marker == 0xD9 or index + 4 > len(data):
            return None
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        if length < 2:
            return None
        if marker in _SOF_MARKERS:
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            return bool(width and height and height > width and width / height < 0.85)
        index += 2 + length
    return None


def shape_name(shape):
    return "portrait" if shape else "wide" if shape is False else "unknown"


class ArtworkService:
    def __init__(self, cache_dir, logger, api_key="", max_age_days=10):
        try:
            age_days = float(max_age_days)
        except (TypeError, ValueError):
            age_days = 10
        self.cache_dir = Path(cache_dir)
        self.logger = logger
        self.api_key = api_key or ""
        self.max_age_seconds = max(0, age_days) * 86400
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._shape_cache = {}
        self._remove_legacy_cache()
        self._remove_wrong_shape_primary_cache()
        self._prune_expired_cache()

    def set_api_key(self, api_key):
        self.api_key = api_key or ""

    def _remove_legacy_cache(self):
        for path in self.cache_dir.glob("*.jpg"):
            if path.stem.isdigit() or path.stem.endswith(("_steam", "_grid")):
                try:
                    self._invalidate_shape_cache(path)
                    path.unlink()
                    self.logger.info("ARTWORK", f"LEGACY_CACHE_REMOVED path=[{path.name}]")
                except OSError as exc:
                    self.logger.warning("ARTWORK", f"LEGACY_CACHE_REMOVE_FAILED path=[{path.name}] error={type(exc).__name__}")

    def _remove_wrong_shape_primary_cache(self):
        # Only a shape we could actually read counts as a verdict: an unreadable file is left alone.
        for path in self.cache_dir.glob("*_steam_v2.jpg"):
            if path.is_file() and path.stat().st_size > 1024 and self._get_cached_shape(path) is False:
                try:
                    self._invalidate_shape_cache(path)
                    path.unlink()
                    self.logger.info("ARTWORK", f"WRONG_SHAPE_CACHE_REMOVED path=[{path.name}]")
                except OSError as exc:
                    self.logger.warning("ARTWORK", f"WRONG_SHAPE_CACHE_REMOVE_FAILED path=[{path.name}] error={type(exc).__name__}")

    def _prune_expired_cache(self):
        if self.max_age_seconds <= 0:
            return
        cutoff = time.time() - self.max_age_seconds
        removed = 0
        for path in self.cache_dir.rglob("*"):
            if not path.is_file() or path.name.endswith(".tmp"):
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
                    self.logger.info("ARTWORK", f"EXPIRED_CACHE_REMOVED path=[{path.relative_to(self.cache_dir)}]")
            except OSError as exc:
                self.logger.warning("ARTWORK", f"EXPIRED_CACHE_REMOVE_FAILED path=[{path}] error={type(exc).__name__}")
        for directory in sorted((p for p in self.cache_dir.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        # Clean up orphaned shape cache files
        for shape_file in self.cache_dir.glob("*.shape"):
            try:
                # If the corresponding image doesn't exist, remove the shape cache
                image_file = shape_file.with_suffix("")
                if not image_file.exists():
                    shape_file.unlink()
            except OSError:
                pass

    def _shape_cache_path(self, image_path):
        """Get the sidecar shape cache file path for an image."""
        return Path(str(image_path) + ".shape")

    def _get_cached_shape(self, image_path):
        """Get cached shape from sidecar file, or compute and cache it."""
        # Check in-memory cache first
        cache_key = str(image_path)
        if cache_key in self._shape_cache:
            return self._shape_cache[cache_key]

        # Check sidecar file
        shape_file = self._shape_cache_path(image_path)
        if shape_file.is_file():
            try:
                cached = shape_file.read_text(encoding="utf-8").strip()
                if cached in ("portrait", "wide"):
                    shape = cached == "portrait"
                    self._shape_cache[cache_key] = shape
                    return shape
            except OSError:
                pass

        # Compute shape
        shape = image_shape(image_path)
        if shape is not None:
            self._shape_cache[cache_key] = shape
            # Write sidecar file
            try:
                shape_file.write_text("portrait" if shape else "wide", encoding="utf-8")
            except OSError:
                pass
        return shape

    def _invalidate_shape_cache(self, image_path):
        """Invalidate cached shape for an image (e.g., after deletion)."""
        cache_key = str(image_path)
        self._shape_cache.pop(cache_key, None)
        shape_file = self._shape_cache_path(image_path)
        try:
            if shape_file.is_file():
                shape_file.unlink()
        except OSError:
            pass

    def cached_path(self, appid, portrait=False, steam=False, fallback=False):
        return self.cache_dir / f"{appid}{'_steam_fallback' if fallback else '_steam_v2' if steam else '_grid_portrait' if portrait else ''}.jpg"

    def _urls(self, appid, preferred=""):
        if not appid:
            return []
        # header.jpg is tried before library_600x900.jpg so the primary cached image is the banner
        # header, not the portrait grid — the two have different aspect ratios and the panel stretches
        # to fill, so mixing them looks inconsistent. preferred (library_capsule) is inserted between
        # the two groups as a fallback before the generic library_600x900 CDN hosts.
        urls = [
            f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg",
            f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/header.jpg",
        ]
        if preferred:
            urls.append(preferred)
        urls += [
            f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
            f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/library_600x900.jpg",
        ]
        return list(dict.fromkeys(urls))

    def _steamgriddb_url(self, appid, expected_name="", ctx=None):
        if not self.api_key or not appid:
            return ""
        try:
            if ctx:
                ctx.checkpoint()
            headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json", "User-Agent": USER_AGENT}
            req = Request(f"https://www.steamgriddb.com/api/v2/games/steam/{appid}", headers=headers)
            with urlopen(req, timeout=12) as response:
                game_payload = json.loads(response.read().decode("utf-8", errors="replace"))
            games = game_payload.get("data") or []
            if isinstance(games, dict):
                games = [games]
            game = games[0] if games and isinstance(games[0], dict) else {}
            if expected_name and identity_key(game.get("name", "")) != identity_key(expected_name):
                self.logger.warning("ARTWORK", f"STEAMGRIDDB_REJECTED appid={appid} expected=[{expected_name}] returned=[{game.get('name', '')}]")
                return ""
            game_id = game.get("id")
            if not game_id:
                return ""
            if ctx:
                ctx.checkpoint()
            req = Request(f"https://www.steamgriddb.com/api/v2/grids/game/{game_id}", headers=headers)
            with urlopen(req, timeout=12) as response:
                grid_payload = json.loads(response.read().decode("utf-8", errors="replace"))
            grids = grid_payload.get("data") or []
            portrait = [row for row in grids if isinstance(row, dict) and row.get("width") and row.get("height") and float(row["width"]) / float(row["height"]) < 0.85]
            for row in portrait:
                for key in ("url", "thumb"):
                    if isinstance(row, dict) and row.get(key):
                        return row[key]
        except CancellationError:
            raise
        except Exception as exc:
            self.logger.debug("ARTWORK", f"STEAMGRIDDB_FAILED appid={appid} error={type(exc).__name__}")
        return ""

    def download(self, appid, ctx=None, preferred_url="", expected_name=""):
        if not appid:
            return ArtworkResult("unavailable", None, "", "No Steam AppID")
        steam_path = self.cached_path(appid, steam=True)
        portrait_path = self.cached_path(appid, portrait=True)
        fallback_path = self.cached_path(appid, fallback=True)
        cached_paths = []
        if steam_path.is_file() and self._get_cached_shape(steam_path) is False:
            try:
                self._invalidate_shape_cache(steam_path)
                steam_path.unlink()
                self.logger.info("ARTWORK", f"WRONG_SHAPE_CACHE_REMOVED appid={appid} path=[{steam_path.name}]")
            except OSError:
                pass
        # header.jpg (fallback_path) is checked before library_600x900.jpg (steam_path) so the
        # cached banner header is returned as primary when available, not the portrait grid.
        cached_paths.append((fallback_path, "steam_cdn"))
        if steam_path.is_file():
            cached_paths.append((steam_path, "steam_cdn"))
        cached_paths.append((portrait_path, "steamgriddb"))
        for cached, source in cached_paths:
            if cached.is_file() and cached.stat().st_size > 1024:
                self.logger.info("ARTWORK", f"CACHE_HIT appid={appid} path=[{cached.name}]")
                return ArtworkResult("cached", cached, source, "Cache hit")
        last = [None]

        def fetch(url):
            if ctx:
                ctx.checkpoint()
            try:
                req = Request(url, headers={"User-Agent": USER_AGENT})
                with urlopen(req, timeout=12) as r:
                    data = r.read()
                if len(data) < 1024:
                    raise OSError("Steam returned an empty/invalid artwork response")
                primary_url = "library_600x900" in url or "library_capsule" in url
                target = portrait_path if "steamgriddb.com" in url else steam_path if primary_url else fallback_path
                tmp = target.with_suffix(f".tmp.{__import__('os').getpid()}")
                tmp.write_bytes(data)
                tmp.replace(target)
                shape = self._get_cached_shape(target)
                # A Steam library capsule is portrait by definition, so a wide one is genuinely wrong and is not
                # kept. An unreadable one is a different matter: it is kept, because deleting art the app cannot
                # classify is how a whole library ends up with no pictures at all.
                if primary_url and shape is False:
                    target.unlink()
                    self.logger.info("ARTWORK", f"LIBRARY_IMAGE_REJECTED appid={appid} url=[{url}] reason=[not_portrait]")
                    raise OSError("Steam library artwork was not portrait-shaped")
                source = "steamgriddb" if "steamgriddb.com" in url else "steam_cdn"
                self.logger.info("ARTWORK", f"DOWNLOADED appid={appid} file=[{target.name}] bytes={len(data)} source=[{source}] shape=[{shape_name(shape)}]")
                return ArtworkResult("downloaded", target, source, f"Downloaded from {source}")
            except HTTPError as exc:
                last[0] = exc
                self.logger.debug("ARTWORK", f"SOURCE_404 appid={appid} url=[{url}]")
            except Exception as exc:
                last[0] = exc
                self.logger.debug("ARTWORK", f"SOURCE_FAIL appid={appid} url=[{url}] error={type(exc).__name__}:{exc}")
            return None

        steam_urls = self._urls(appid, preferred_url) if preferred_url or not self.api_key else []
        attempted = set()
        for url in list(dict.fromkeys(steam_urls)):
            attempted.add(url)
            result = fetch(url)
            if result:
                return result
        steamgriddb_url = self._steamgriddb_url(appid, expected_name, ctx)
        if steamgriddb_url:
            result = fetch(steamgriddb_url)
            if result:
                return result
        for url in list(dict.fromkeys(self._urls(appid, preferred_url))):
            if url in attempted:
                continue
            result = fetch(url)
            if result:
                return result
        # Not a warning: only the primary image is missing here. The primary and the asset URLs are different
        # families on different hosts, so a game whose library capsule 404s routinely has working asset URLs
        # behind it. A live run of Incremedieval.7z downloaded five images and was logged as UNAVAILABLE,
        # because this fired before download_assets() had tried them. download_assets() decides the real
        # severity once the whole attempt is known.
        self.logger.debug("ARTWORK", f"PRIMARY_UNAVAILABLE appid={appid} reason=[all_steam_sources_failed]")
        return ArtworkResult("unavailable", None, "steam_cdn", f"Artwork unavailable ({type(last[0]).__name__ if last[0] else 'no source'})")

    def download_assets(self, appid, asset_urls=None, ctx=None, preferred_url="", expected_name="", on_progress=None):
        # Artwork download is the slowest part of verification and used to run with no feedback at all, so a
        # large library looked frozen here. Each asset now reports as it lands, cached or freshly downloaded.
        def report(name, state, detail=""):
            if not on_progress:
                return
            try:
                on_progress({"asset": name, "state": state, "appid": appid, "detail": detail})
            except Exception:
                pass

        report("cover", "start", expected_name or "")
        primary = self.download(appid, ctx, preferred_url, expected_name)
        assets = dict(primary.assets)
        if not appid:
            return primary
        asset_dir = self.cache_dir / "assets" / str(appid)
        asset_dir.mkdir(parents=True, exist_ok=True)
        # background and background_store page backgrounds are full-width wallpapers that are never
        # rendered on the Review screen — the panel excludes them — so they are filtered out here
        # as well: downloading and caching 1 MB JPEGs per game only to never display them wastes
        # bandwidth, disk, and slows every verification pass.
        _SKIP_ASSETS = {"background", "background_raw"}
        pending = [(name, url) for name, url in (asset_urls or {}).items() if url and name not in assets and name not in _SKIP_ASSETS]
        for position, (name, url) in enumerate(pending, 1):
            target = asset_dir / f"{name}.jpg"
            if target.is_file() and target.stat().st_size > 1024:
                assets[name] = target
                report(name, "cached", f"{position} of {len(pending)}")
                continue
            try:
                if ctx:
                    ctx.checkpoint()
                req = Request(url, headers={"User-Agent": USER_AGENT})
                with urlopen(req, timeout=12) as response:
                    data = response.read()
                if len(data) < 1024:
                    continue
                tmp = target.with_suffix(f".tmp.{__import__('os').getpid()}")
                tmp.write_bytes(data)
                tmp.replace(target)
                assets[name] = target
                self.logger.info("ARTWORK", f"ASSET_DOWNLOADED appid={appid} name=[{name}] bytes={len(data)}")
                report(name, "downloaded", f"{position} of {len(pending)}  •  {len(data) // 1024} KB")
            except CancellationError:
                raise
            except Exception as exc:
                self.logger.debug("ARTWORK", f"ASSET_FAILED appid={appid} name=[{name}] url=[{url}] error={type(exc).__name__}")
                detail = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
                report(name, "failed", detail)
        primary.assets = assets
        # Only now is the verdict knowable. A game with a primary image, with assets, or with both has artwork
        # and must not be logged as missing any; a game with neither is the one case worth a warning, and this
        # is the only place that can tell the two apart.
        if appid and not primary.present():
            self.logger.warning("ARTWORK", f"UNAVAILABLE appid={appid} reason=[no artwork from any source]")
        return primary

    def lookup(self, appid, game_dir=None):
        if not appid:
            return ArtworkResult("unavailable", None, "", "No Steam AppID")
        for p, source in ((self.cached_path(appid, True), "steamgriddb"), (self.cached_path(appid, steam=True), "steam_cdn"), (self.cached_path(appid, fallback=True), "steam_cdn")):
            if p.is_file():
                return ArtworkResult("cached", p, source, "Cache hit")
        # The artwork cache is pruned after max_age_days, so a re-scan with downloads off
        # must still find images the organizer already copied into the game folder. The files
        # carry the Steam-name prefix that OrganizerService.write() writes as <prefix>_grid.jpg
        # and <prefix>_<asset>.<ext>. If nothing was cached, look there.
        if game_dir and appid:
            game_path = Path(game_dir)
            if game_path.is_dir():
                for path in sorted(game_path.glob("*_grid.jpg")):
                    if path.is_file() and path.stat().st_size > 1024:
                        result = ArtworkResult("cached", path, "steam_cdn", "Found in game folder")
                        asset_urls = {name: game_path / f"{path.stem.replace('_grid', '')}_{name}{p.suffix}" for name in ("header_image", "library_hero", "capsule_image", "capsule_imagev5", "library_capsule", "library_logo", "icon")}
                        result.assets = {name: p for name, p in asset_urls.items() if p.is_file() and p.stat().st_size > 1024}
                        return result
        return ArtworkResult("unavailable", None, "steam_cdn", "Not downloaded")

    def clear(self, appid):
        if not appid:
            return
        for path in (self.cached_path(appid), self.cached_path(appid, True), self.cached_path(appid, steam=True), self.cached_path(appid, fallback=True)):
            try:
                self._invalidate_shape_cache(path)
                path.unlink()
            except FileNotFoundError:
                pass
        asset_dir = self.cache_dir / "assets" / str(appid)
        if asset_dir.is_dir():
            try:
                shutil.rmtree(asset_dir)
            except OSError:
                pass
