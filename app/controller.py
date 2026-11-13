import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from app.events import Event
from core.constants import ARCHIVE_EXTENSIONS, DEFAULT_ZIP_PASSWORD, LIBRARY_RESERVED_DIRS, canonical_category, suggest_category_with_evidence, UNSORTED_EVIDENCE
from core.exceptions import CancellationError
from core.models import ScanResult
from utils.filename_utils import identity_key, normalize_name
from utils.formatting import human_size
from utils.treewalk import walk_files
from core.controller_utils import artwork_present, primary, needs_conversion, primary_size, prune_rolled_back_folder


class AppController:
    def __init__(self, state, bus, logger, services, jobs, dispatch=lambda fn: fn()):
        self.state = state
        self.bus = bus
        self.logger = logger
        self.services = services
        self.jobs = jobs
        self.dispatch = dispatch
        self.config = None
        self._category_cache = None
        self._steam_matches_cache = None
        self._appid_to_identity_keys = None
        self._scan_progress_sink = None

    def _category_file(self):
        return self.config.config_dir / "category-decisions.json" if self.config else None

    def _steam_matches_file(self):
        return self.config.config_dir / "steam-matches.json" if self.config else None

    def _saved_categories(self):
        if self._category_cache is not None:
            return self._category_cache
        path = self._category_file()
        if not path or not path.is_file():
            self._category_cache = {"identity": {}, "appid": {}}
            return self._category_cache
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "identity" in data and "appid" in data:
                self._category_cache = data
            else:
                self._category_cache = {"identity": data, "appid": {}}
        except (OSError, ValueError, TypeError):
            self._category_cache = {"identity": {}, "appid": {}}
        return self._category_cache

    def _build_appid_index(self):
        if self._appid_to_identity_keys is not None:
            return self._appid_to_identity_keys
        path = self._steam_matches_file()
        self._appid_to_identity_keys = {}
        if not path or not path.is_file():
            return self._appid_to_identity_keys
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for identity_key, match in data.items():
                if isinstance(match, dict) and match.get("found") and match.get("appid"):
                    appid = str(match["appid"])
                    self._appid_to_identity_keys.setdefault(appid, []).append(identity_key)
        except (OSError, ValueError, TypeError):
            pass
        return self._appid_to_identity_keys

    def _get_category_by_appid(self, appid):
        if not appid:
            return None
        saved = self._saved_categories()
        if str(appid) in saved.get("appid", {}):
            return saved["appid"][str(appid)]
        categories = saved.get("identity", {})
        for ik in self._build_appid_index().get(str(appid), []):
            if ik in categories:
                return categories[ik]
        return None

    def remember_category(self, identity, category, appid=None):
        path = self._category_file()
        if not path:
            return
        data = self._saved_categories()
        data["identity"][identity] = category
        self._category_cache = data
        path.parent.mkdir(parents=True, exist_ok=True)
        if appid:
            data["appid"][str(appid)] = category
        fd, temp = tempfile.mkstemp(prefix="category-decisions.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2))
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(4):
                try:
                    os.replace(temp, path)
                    break
                except PermissionError:
                    if attempt == 3:
                        self.logger.warning("could not save the category decision for %s beside %s", identity, path)
                        break
                    time.sleep(0.05 * (attempt + 1))
        finally:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass
        if self.config:
            self.config.sync_to_appdata()

    # Pure functions now live in core.controller_utils; these thin wrappers keep existing callers working.
    def _artwork_present(self, archive):
        return artwork_present(archive)

    def _primary(self, group):
        return primary(group, self.services.organizer._promotion_key)

    def _needs_conversion(self, archive):
        return needs_conversion(archive, getattr(self.config, "convert_archives", True))

    def _primary_size(self, group):
        return primary_size(group, self.services.organizer._promotion_key)

    def _prune_rolled_back_folder(self, game_dir, owned, library_root=None):
        return prune_rolled_back_folder(game_dir, owned, library_root, logger=self.logger)

    def _submit(self, phase, work, done, error):
        self.state.update(phase=phase, cancel_requested=False)
        correlation_id = self.logger.correlation_id()
        started = time.monotonic()
        self.logger.info("APPLICATION", f"OPERATION_START phase={phase} correlation={correlation_id}", correlation_id)

        def wrapped_work(ctx):
            with self.logger.context(correlation_id):
                return work(ctx)

        def ok(job, result):
            self.dispatch(lambda: done(result))

        def bad(job, exc):
            self.logger.info("APPLICATION", f"OPERATION_END phase={phase} status=failed elapsed_ms={int((time.monotonic() - started) * 1000)}", correlation_id)
            self.dispatch(lambda: error(exc))

        def completed(job, result):
            self.logger.info("APPLICATION", f"OPERATION_END phase={phase} status=complete elapsed_ms={int((time.monotonic() - started) * 1000)}", correlation_id)
            ok(job, result)

        jid, ctx, _ = self.jobs.submit(wrapped_work, completed, bad)
        self.state.update(job_id=jid)
        return ctx

    def _repair_progress(self, event):
        """Relays the structured conversion record from the repair pass to whichever progress sink the caller
        supplied, so a background conversion is visible on the Scan screen instead of looking like a hang."""
        if not self._scan_progress_sink:
            return
        try:
            self.dispatch(lambda: self._scan_progress_sink(event))
        except Exception:
            pass

    def scan(self, root, done, progress=None, new_only=False, unlock_zip=False, preview_only=False, download_artwork=True):
        self._scan_progress_sink = progress

        # The scan runs several distinct phases and only discovery reported itself, so cleanup, dedupe,
        # repair, audit and catalog all looked like a single silent wait. Every phase now announces itself
        # with its real outcome so the screen can show where the time is going and what actually happened.
        def phase(stage, message, **extra):
            if not progress:
                return
            try:
                self.dispatch(lambda: progress({"stage": stage, "message": message, **extra}))
            except Exception:
                pass

        def work(ctx):
            # Collapse any game folder that holds more than one archive down to a single copy first, so the
            # review queue never contains a path that the same scan is about to move to the Archive folder.
            # Journaled like an organize transaction so a mistaken collapse can be undone from the Done stage.
            dedupe_journal = []
            # Reclaim stranded temp/extraction folders first. A killed conversion can leave several GB inside
            # the library folder, and since that folder syncs to another PC the junk would replicate onward.
            phase("cleanup", "Reclaiming leftover temporary files")
            if not preview_only:
                try:
                    summary = self.services.library.cleanup_leftovers(root, ctx) or {}
                    removed = summary.get("removed", 0)
                    freed = summary.get("bytes_freed", 0)
                    phase("cleanup_done", f"Reclaimed {removed} item(s), freed {human_size(freed)}", removed=removed, bytes_freed=freed, deferred=summary.get("deferred_syncthing", 0))
                except CancellationError:
                    raise
                except Exception as exc:
                    self.logger.warning("APPLICATION", f"CLEANUP_FAILED error={type(exc).__name__}")
                    phase("cleanup_done", f"Cleanup skipped: {type(exc).__name__}", failed=True)
            else:
                phase("cleanup_done", "Skipped in Preview Only — no files touched", skipped=True)
            try:
                # Skipped under Preview Only for the same reason as the repair pass below: this is not a check,
                # it is a move. Two copies of one game left in the folder by hand is a real case, and the survivor
                # is chosen by version, so Preview Only was writing to Archive/ while the screen said no files had
                # been touched. Guarded in place rather than by returning early, since this is one phase of a scan
                # and the phases after it still have to run.
                if not preview_only:
                    collapsed = self.services.library.enforce_single_archive(root, self.services.organizer, ctx, dedupe_journal)
                    if dedupe_journal:
                        self.services.rollback.record(dedupe_journal)
                    # No owned_dirs here, and deliberately: these rows land in the library's Archive/, which
                    # this run never created and which holds archives besides, so an undo restores them and
                    # removes nothing. Saying so beats passing a set that happens to be empty.
                    phase("dedupe_done", "Kept one archive per game folder" + (f" ({collapsed} folder(s) collapsed)" if collapsed else " — nothing to collapse"))
                else:
                    phase("dedupe_done", "Skipped in Preview Only — no files touched", skipped=True)
            except CancellationError:
                raise
            except Exception as exc:
                self.logger.warning("APPLICATION", f"SINGLE_ARCHIVE_FAILED error={type(exc).__name__}")
                phase("dedupe_done", f"Could not check for duplicate archives: {type(exc).__name__}", failed=True)
            # Archive older copies of the same game that live in more than one category. Grouped by Steam appid
            # (each folder's .game-info.json): when an appid appears in two or more categories, every copy but
            # the newest - judged by the archive's creation time - is moved to Archive/. Journaled like the
            # dedupe pass so every archive sweep can be undone from the Done stage. Runs under All and New
            # Only mode alike, since both can surface games that were filed twice before they were reviewed.
            phase("cross_category_duplicates", "Checking for the same game in more than one category")
            if not preview_only:
                try:
                    archived = self._sweep_cross_category_duplicates(root, ctx, dedupe_journal)
                    if dedupe_journal:
                        self.services.rollback.record(dedupe_journal)
                    if archived:
                        phase("cross_category_duplicates_done", f"Cross-category duplicates archived — {archived} older copy(ies) moved to Archive/", archived=archived)
                    else:
                        phase("cross_category_duplicates_done", "Cross-category duplicates checked — nothing to archive")
                except CancellationError:
                    raise
                except Exception as exc:
                    self.logger.warning("APPLICATION", f"CROSS_CATEGORY_DUPLICATE_FAILED error={type(exc).__name__}")
                    phase("cross_category_duplicates_done", f"Cross-category duplicate sweep skipped: {type(exc).__name__}", failed=True)
            else:
                phase("cross_category_duplicates_done", "Skipped in Preview Only — no files touched", skipped=True)
            # Finish .zip/.rar -> .7z conversions inside already-organized folders. This runs in both All and
            # New Only mode, because discovery hides archives that already sit beside a Steam link, so under
            # New Only a conversion that failed on an earlier run would never be retried. Skipped under
            # Preview Only, since that mode promises no files are moved.
            phase("repair", "Checking organized folders for leftover ZIP/RAR archives")
            if preview_only:
                phase("repair_done", "Skipped in Preview Only — no files touched", skipped=True)
            elif not getattr(self.config, "convert_archives", True):
                # Conversion can be switched off independently of the scan. Discovery still finds the
                # leftovers, they are simply reported as needing conversion rather than silently rewritten.
                self._pending_repair_outcomes = []
                phase("repair_done", "Repair pass skipped — ZIP/RAR conversion is turned off", skipped=True)
            else:
                try:
                    repair_outcomes = []
                    candidates = self.services.library.pending_candidates(root)
                    work = [(game_dir, pending, appid, name) for game_dir, pending, _size, appid, name in candidates]
                    # The hardcoded "123" zip password now comes from DEFAULT_ZIP_PASSWORD in core.constants.
                    converted = self.services.library.convert_pending_archives(
                        root,
                        self.services.organizer,
                        ctx,
                        dedupe_journal,
                        self._repair_progress,
                        unlocker=(self.services.archive._remove_zip_password if unlock_zip else None),
                        outcomes=repair_outcomes,
                        zip_password=(DEFAULT_ZIP_PASSWORD if unlock_zip else ""),
                        work=work,
                    )
                    if dedupe_journal:
                        self.services.rollback.record(dedupe_journal)
                    # No owned_dirs here, and deliberately: these rows land in the library's Archive/, which
                    # this run never created and which holds archives besides, so an undo restores them and
                    # removes nothing. Saying so beats passing a set that happens to be empty.
                    # Repair runs on files discovery already skipped, so its outcomes have to be copied back onto
                    # the archives the scan will report; otherwise the run finishes and these have no result at all.
                    self._pending_repair_outcomes = repair_outcomes
                    phase("repair_done", f"Repair pass finished — {converted} archive(s) converted" if converted else "Repair pass finished — every organized archive is already 7z")
                except CancellationError:
                    raise
                except Exception as exc:
                    self.logger.warning("APPLICATION", f"PENDING_CONVERT_FAILED error={type(exc).__name__}")
                    phase("repair_done", f"Repair pass failed: {type(exc).__name__}", failed=True)
            # Discovery telemetry keeps its original positional callback contract.
            phase("discover", "Scanning for archives")
            # Discovery reports seven positional values. The sink takes them as a single tuple and unpacks it
            # itself, so they are packed back into one argument here. The wrapper previously accepted a single
            # positional argument while discovery called it with seven, which raised a TypeError and killed
            # discovery progress for the entire run.
            wrapped_progress = (lambda *event: self.dispatch(lambda event=event: progress(event))) if progress else None
            result = self.services.archive.discover(root, ctx, wrapped_progress, new_only=new_only, unlock_zip=unlock_zip, preview_only=preview_only)
            self.services.library.apply_outcomes(result.archives, getattr(self, "_pending_repair_outcomes", None) or [])
            phase("discover_done", f"Found {len(result.archives)} archive(s)")
            # Runs unconditionally (regardless of New Only mode) so link files and artwork stay fresh for every
            # game already in the library, not only the archives just discovered.
            phase("audit", "Checking game folders and what a real scan would refresh")

            # The audit walks every game folder in the library and fetches artwork for each one, which on a
            # library of any size is minutes of network work. It reported nothing while it did it, so the run
            # looked hung; the per-folder records it emits now land on the Audit phase of the timeline.
            def audit_progress(event):
                message = event.get("message")
                if not message:
                    return
                phase("audit", message, index=event.get("index", 0), total=event.get("total", 0))

            try:
                stats = (
                    self.services.library.audit(
                        root,
                        self.services.artwork,
                        self.services.organizer,
                        ctx,
                        on_progress=audit_progress,
                        preview_only=preview_only,
                        download_artwork=download_artwork,
                    )
                    or {}
                )
                checked = stats.get("checked", 0)
                refreshed = stats.get("refreshed", 0)
                no_art = stats.get("no_artwork", 0)
                # The count the user reads last has to be the complete one. The audit reports its own
                # no-artwork figure on its audit_done event, but audit_progress() above relabels that event
                # as an ordinary 'audit' line and this one then overwrites the phase, so without this the
                # number was computed, logged, and lost on the way to the screen.
                message = f"Checked {checked} game folder(s) — refreshed {refreshed}"
                if no_art:
                    message += f", {no_art} with no artwork"
                if preview_only:
                    message += " — Preview Only: nothing written"
                phase("audit_done", message)
            except CancellationError:
                raise
            except Exception as exc:
                self.logger.warning("APPLICATION", f"LIBRARY_AUDIT_FAILED error={type(exc).__name__}")
                phase("audit_done", f"Library audit skipped: {type(exc).__name__}", failed=True)
            phase("catalog", "Generating the game catalog")
            try:
                if preview_only:
                    # Preview Only rewrites nothing, so the page, the status file and the launcher are not
                    # written at all. Said so in the summary rather than silently producing nothing, which is
                    # the same class of defect as the three phases this release fixes: a preview that
                    # quietly omits a write looks exactly like one that did not need to.
                    phase("catalog_done", "Catalog not generated — Preview Only writes nothing", skipped=True)
                else:
                    written = self.services.catalog.generate(root, self.services.organizer.needs_catalog_launcher()) or []
                    phase("catalog_done", f"Catalog generated — {len(written)} page(s) written", written=len(written))
            except CancellationError:
                raise
            except Exception as exc:
                self.logger.warning("APPLICATION", f"CATALOG_GENERATE_FAILED error={type(exc).__name__}")
                phase("catalog_done", f"Catalog skipped: {type(exc).__name__}", failed=True)
            return result

        return self._submit("scanning", work, lambda r: self._scan_ok(r, done), lambda e: self._failed("scan", e))

    def _scan_ok(self, result, done):
        self.state.update(scan_result=result, job_id="")
        self.bus.emit(Event("scan_completed", {"result": result}))
        done(result)
        # After the result is handed on, never before. Recording the summary is a convenience for the next
        # session, and a controller is constructed without a config by half the test suite, so anything this
        # touches can be absent or broken - and a scan that cannot file its own summary still has to finish.
        self._record_scan(result)

    def scan_new_artwork(self, root, scan_progress, verify_progress, done, download_artwork=True):
        """Quick scan: discover new archives only and download their artwork.

        Runs the same phases as a full scan — cleanup, dedupe, repair,
        discovery, audit, catalog — so a quick scan doesn't leave anything
        behind. Repair still converts ZIP/RAR to 7z inside organized folders;
        any ZIP/RAR that cannot be converted is moved to the library root so
        the next discovery pass picks it up as a new game.
        """
        self._scan_progress_sink = scan_progress

        def phase(stage, message, **extra):
            if not scan_progress:
                return
            try:
                self.dispatch(lambda: scan_progress({"stage": stage, "message": message, **extra}))
            except Exception:
                pass

        def work(ctx):
            dedupe_journal = []
            phase("cleanup", "Reclaiming leftover temporary files")
            try:
                summary = self.services.library.cleanup_leftovers(root, ctx) or {}
                removed = summary.get("removed", 0)
                freed = summary.get("bytes_freed", 0)
                phase("cleanup_done", f"Reclaimed {removed} item(s), freed {human_size(freed)}", removed=removed, bytes_freed=freed, deferred=summary.get("deferred_syncthing", 0))
            except CancellationError:
                raise
            except Exception as exc:
                self.logger.warning("APPLICATION", f"ARTWORK_CLEANUP_FAILED error={type(exc).__name__}")
                phase("cleanup_done", f"Cleanup skipped: {type(exc).__name__}", failed=True)
            phase("dedupe", "Collapsing duplicate archives in game folders")
            try:
                collapsed = self.services.library.enforce_single_archive(root, self.services.organizer, ctx, dedupe_journal)
                if dedupe_journal:
                    self.services.rollback.record(dedupe_journal)
                phase("dedupe_done", "Kept one archive per game folder" + (f" ({collapsed} folder(s) collapsed)" if collapsed else " — nothing to collapse"))
            except CancellationError:
                raise
            except Exception as exc:
                self.logger.warning("APPLICATION", f"ARTWORK_DEDUPE_FAILED error={type(exc).__name__}")
                phase("dedupe_done", f"Dedupe skipped: {type(exc).__name__}", failed=True)
            phase("repair", "Checking organized folders for leftover ZIP/RAR archives")
            repair_outcomes = []
            try:
                converted = self.services.library.convert_pending_archives(
                    root,
                    self.services.organizer,
                    ctx,
                    dedupe_journal,
                    self._repair_progress,
                    unlocker=None,
                    outcomes=repair_outcomes,
                    zip_password="",
                )
                if dedupe_journal:
                    self.services.rollback.record(dedupe_journal)
                self._pending_repair_outcomes = repair_outcomes
                # Any ZIP/RAR that was missed (not converted) gets moved to the library root
                # so the next discovery pass picks it up as a new game.
                missed = [p for p, c in repair_outcomes if c.status not in ("converted", "not_needed") and p.is_file() and p.suffix.lower() in (".zip", ".rar")]
                for p in missed:
                    try:
                        target = root / p.name
                        n = 2
                        while target.exists():
                            target = root / f"{p.stem} ({n}){p.suffix}"
                            n += 1
                        shutil.move(str(p), str(target))
                        self.logger.info("APPLICATION", f"MISSED_ARCHIVE_MOVED source=[{p}] destination=[{target}]")
                    except OSError as exc:
                        self.logger.warning("APPLICATION", f"MISSED_ARCHIVE_MOVE_FAILED source=[{p}] error={type(exc).__name__}")
                phase("repair_done", f"Repair pass finished — {converted} archive(s) converted" if converted else "Repair pass finished — every organized archive is already 7z")
            except CancellationError:
                raise
            except Exception as exc:
                self.logger.warning("APPLICATION", f"ARTWORK_REPAIR_FAILED error={type(exc).__name__}")
                phase("repair_done", f"Repair pass failed: {type(exc).__name__}", failed=True)
            phase("discover", "Scanning for archives")
            wrapped_progress = (lambda *event: self.dispatch(lambda event=event: scan_progress(event))) if scan_progress else None
            result = self.services.archive.discover(root, ctx, wrapped_progress, new_only=True, unlock_zip=False, preview_only=False)
            self.services.library.apply_outcomes(result.archives, getattr(self, "_pending_repair_outcomes", None) or [])
            archives = result.archives
            phase("discover_done", f"Found {len(archives)} new archive(s)")
            phase("catalog", "Generating the game catalog")
            try:
                written = self.services.catalog.generate(root, self.services.organizer.needs_catalog_launcher()) or []
                phase("catalog_done", f"Catalog generated — {len(written)} page(s) written", written=len(written))
            except CancellationError:
                raise
            except Exception as exc:
                self.logger.warning("APPLICATION", f"ARTWORK_CATALOG_FAILED error={type(exc).__name__}")
                phase("catalog_done", f"Catalog generation skipped: {type(exc).__name__}", failed=True)
            if not archives:
                phase("artwork_done", "No new archives found — artwork cache is fresh")
                return archives
            phase("artwork", f"Looking up Steam and downloading artwork for {len(archives)} archive(s)")
            total = len(archives)
            artwork_downloaded = 0
            artwork_cached = 0
            artwork_unavailable = 0
            for i, archive in enumerate(archives, 1):
                if ctx:
                    ctx.checkpoint()
                steam_match = self.services.steam.lookup(archive.normalized_title, ctx, archive_path=archive.path)
                archive.steam = steam_match

                def asset_progress(event, idx=i, arch=archive, mm=steam_match):
                    if verify_progress:
                        self.dispatch(lambda ev=event, ix=idx, a=arch, m=mm, t=total: verify_progress(ix, t, a, m, None, ev))

                if steam_match.found and download_artwork:
                    archive.artwork = self.services.artwork.download_assets(steam_match.appid, steam_match.asset_urls, ctx, steam_match.artwork_url, steam_match.name, on_progress=asset_progress)
                elif steam_match.found:
                    archive.artwork = self.services.artwork.lookup(steam_match.appid, archive.path.parent)
                else:
                    archive.artwork = self.services.artwork.lookup("")
                if archive.artwork.status == "downloaded":
                    artwork_downloaded += 1
                elif archive.artwork.status == "cached":
                    artwork_cached += 1
                else:
                    artwork_unavailable += 1
                if verify_progress:
                    self.dispatch(lambda ix=i, a=archive, m=steam_match, art=archive.artwork, t=total: verify_progress(ix, t, a, m, art))
            self.logger.info("ARTWORK", f"ARTWORK_SCAN_COMPLETE downloaded={artwork_downloaded} cached={artwork_cached} unavailable={artwork_unavailable} total={len(archives)}")
            phase("artwork_done", f"Artwork processed for {len(archives)} archive(s) — downloaded {artwork_downloaded}, cached {artwork_cached}, unavailable {artwork_unavailable}")
            return archives

        return self._submit("scanning_artwork", work, lambda r: self._scan_new_artwork_ok(r, done), lambda e: self._failed("artwork", e))

    def _scan_new_artwork_ok(self, result, done):
        self.state.update(phase="idle", job_id="", scan_result=ScanResult(archives=result))
        self.bus.emit(Event("scan_new_artwork_completed", {"archives": result}))
        done(result)

    def _record_scan(self, result):
        """File what this scan found, so the scanner can report it next time it is opened.

        Every number here was already computed for the Done screen and the log; this is the one place they are
        kept in a form the next session can read. `artwork` counts through the same `present()` the screens use,
        so a game whose pictures arrived as asset URLs is counted here exactly as it is there - the disagreement
        that was a bug in 9.20 would otherwise reappear as a summary that disagreed with the screen above it.
        """
        if self.config is None:
            return
        try:
            archives = list(getattr(result, "archives", ()) or ())
            self.config.save_scan_summary(
                {
                    "archives": len(archives),
                    "total_bytes": sum(getattr(a, "size", 0) or 0 for a in archives),
                    "matched": sum(1 for a in archives if getattr(a.steam, "found", False)),
                    "unmatched": sum(1 for a in archives if not getattr(a.steam, "found", False)),
                    "artwork": sum(1 for a in archives if artwork_present(a)),
                    "errors": len(getattr(result, "errors", ()) or ()),
                    "stale_dirs": len(getattr(result, "stale_build_dirs", ()) or ()),
                    "stale_bytes": int(getattr(result, "stale_build_bytes", 0) or 0),
                    "library_root": str(getattr(self.config, "library_root", "") or ""),
                }
            )
        except Exception as exc:
            # Named rather than swallowed silently: this is the one place a scan does something strictly
            # optional, and a failure here should be visible in the log without affecting the scan.
            self.logger.debug("SCAN", f"SUMMARY_NOT_RECORDED error={type(exc).__name__}")

    def verify_all(self, archives, on_progress, done, download_artwork=True):
        def work(ctx):
            total = len(archives)
            results = []
            for i, a in enumerate(archives, 1):
                ctx.checkpoint()
                steam_match = self.services.steam.lookup(a.normalized_title, ctx, archive_path=a.path)
                a.steam = steam_match
                a.decision.category, a.decision.evidence = (
                    suggest_category_with_evidence(
                        steam_match.genres,
                        steam_match.name,
                        steam_match.description,
                        steam_match.tags,
                        steam_match.categories,
                    )
                    if steam_match.found
                    else ("Unsorted", UNSORTED_EVIDENCE)
                )
                if steam_match.found:
                    evidence = a.decision.evidence
                    runners = ",".join(f"{name}:{score}" for name, score in evidence.runners_up)
                    self.logger.debug(
                        "CATEGORY",
                        f"SUGGEST title=[{steam_match.name}] category=[{a.decision.category}] basis=[{evidence.basis}] score=[{evidence.score}] terms=[{'|'.join(evidence.terms)}] runners_up=[{runners}]",
                    )
                a.decision.suggested_category = a.decision.category
                # The evidence above describes the computed suggestion. The remembered category below
                # can replace decision.category while suggested_category, and the evidence, still
                # describe what was computed, so a screen must render the evidence against
                # suggested_category - not against the category that may have replaced it.
                saved = self._saved_categories()
                category = saved.get("identity", {}).get(a.identity_key)
                if category is None and steam_match.found and steam_match.appid:
                    category = self._get_category_by_appid(steam_match.appid)
                a.decision.category = canonical_category(category if category is not None else a.decision.category)

                # Artwork downloads report per asset, so the slowest part of verification is never a silent wait.
                def asset_progress(event, name=None, idx=i, arch=a):
                    self.dispatch(lambda ev=event: on_progress(idx, total, arch, arch.steam, None, ev))

                if steam_match.found and download_artwork:
                    a.artwork = self.services.artwork.download_assets(
                        steam_match.appid,
                        steam_match.asset_urls,
                        ctx,
                        steam_match.artwork_url,
                        steam_match.name,
                        on_progress=asset_progress,
                    )
                elif steam_match.found:
                    a.artwork = self.services.artwork.lookup(steam_match.appid, a.path.parent)
                else:
                    a.artwork = self.services.artwork.lookup("")
                self.dispatch(lambda i=i, a=a, m=steam_match, art=a.artwork: on_progress(i, total, a, m, art))
                results.append(a)
            return results

        return self._submit("verifying", work, lambda r: self._verify_ok(r, done), lambda e: self._failed("verify", e))

    def verify_one(self, archive, title, done):
        def work(ctx):
            steam_match = self.services.steam.lookup(title, ctx, refresh=True)
            archive.steam = steam_match
            self.services.steam.remember(archive.normalized_title, steam_match)
            archive.decision.category, archive.decision.evidence = (
                suggest_category_with_evidence(
                    steam_match.genres,
                    steam_match.name,
                    steam_match.description,
                    steam_match.tags,
                    steam_match.categories,
                )
                if steam_match.found
                else ("Unsorted", UNSORTED_EVIDENCE)
            )
            if steam_match.found:
                evidence = archive.decision.evidence
                runners = ",".join(f"{name}:{score}" for name, score in evidence.runners_up)
                self.logger.debug(
                    "CATEGORY",
                    f"MANUAL_REEVALUATE title=[{steam_match.name}] category=[{archive.decision.category}] basis=[{evidence.basis}] score=[{evidence.score}] terms=[{'|'.join(evidence.terms)}] runners_up=[{runners}]",
                )
            archive.decision.suggested_category = archive.decision.category
            # The evidence above describes the computed suggestion. The remembered category below
            # can replace decision.category while suggested_category, and the evidence, still
            # describe what was computed, so a screen must render the evidence against
            # suggested_category - not against the category that may have replaced it.
            saved = self._saved_categories()
            category = saved.get("identity", {}).get(archive.identity_key)
            if category is None and steam_match.found and steam_match.appid:
                category = self._get_category_by_appid(steam_match.appid)
            archive.decision.category = canonical_category(category if category is not None else archive.decision.category)
            archive.decision.accepted = False
            archive.decision.skipped = False
            archive.decision.changed_from_suggestion = False
            if steam_match.found:
                archive.artwork = self.services.artwork.download_assets(
                    steam_match.appid,
                    steam_match.asset_urls,
                    ctx,
                    steam_match.artwork_url,
                    steam_match.name,
                )
            else:
                archive.artwork = self.services.artwork.lookup("")
            return archive

        return self._submit("verifying", work, lambda result: (self.state.update(phase="review", job_id=""), done(result)), lambda e: self._failed("verify", e))

    def _verify_ok(self, result, done):
        self.state.update(phase="review", job_id="")
        self.bus.emit(Event("verification_completed", {"archives": result}))
        done(result)

    def _restore_moved(self, source, target, owned_dirs, library_root=None):
        """Puts one journalled move back where it came from, and tidies the folder it came out of.

        Repacking (.zip -> .rar) can change the extension after the move, so the restore is named after the
        current extension rather than the recorded source. Shared by the whole-run rollback and by the
        single-game recovery below, because both have to leave the library exactly as they found it.
        """
        try:
            restore = source if source.suffix == target.suffix else source.with_suffix(target.suffix)
            if target.exists() and not restore.exists():
                restore.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(restore))
            self._prune_rolled_back_folder(Path(target).parent, str(Path(target).parent) in owned_dirs, library_root)
        except OSError as rollback_error:
            self.logger.error("ORGANIZER", f"ROLLBACK_FAILED source=[{source}] target=[{target}] error=[{type(rollback_error).__name__}]")

    def _recover_failed_move(self, archive, source, move_error, journal, owned_dirs, library_root=None):
        """Puts one game back and records why it failed, so the rest of the run carries on.

        A move can fail on a file the user has open in Explorer, or on a permission the library does not grant,
        and one such file used to end the whole run: every game already filed was rolled back and the user was
        left to fix that single file and start again. The archive is restored to where it came from rather than
        left half-filed, and its outcome is recorded the same way a failed conversion is, so the Done screen
        names it instead of the run simply ending.
        """
        stranded = getattr(archive, "organized_path", None)
        if stranded is not None:
            stranded = Path(stranded)
            if stranded.is_file() and not source.exists():
                journal.append((source, stranded))
                self.services.rollback.record(journal, owned_dirs)
                self._restore_moved(source, stranded, owned_dirs, library_root)
                self.logger.error("ORGANIZER", f"ORGANIZE_MOVE_FAILED path=[{source}] landed=[{stranded}] error=[{type(move_error).__name__}] partial move restored, run continues")
        note = archive.conversion
        note.status = "failed"
        note.message = str(move_error)[:300] or type(move_error).__name__
        note.source_format = source.suffix.lstrip(".").upper()
        note.final_name = source.name
        try:
            note.free_bytes_at_failure = shutil.disk_usage(source.parent).free
        except OSError:
            note.free_bytes_at_failure = 0
        archive.organized_path = None
        self.logger.warning("ORGANIZER", f"ORGANIZE_SKIPPED_FAILED path=[{source}] error=[{type(move_error).__name__}] message=[{str(move_error)[:200]}]")

    def organize(self, archives, destination, done, on_progress=None):
        def work(ctx):
            moved = []
            journal = []
            owned_dirs = set()
            failed = []
            target_root = Path(destination).expanduser().resolve()
            accepted = list(archives)
            source_paths = {a.path.expanduser().resolve() for a in accepted}
            groups = {}
            for archive in accepted:
                groups.setdefault(archive.identity_key, []).append(archive)
            # Conversion is by far the longest part of a run, and it lands entirely on the primary copy of each
            # game. Doing the smallest ones first means the quick wins are banked early and any archive that is
            # going to fail - a corrupt download, an unsupported compression - fails while there is still plenty
            # of run left to react to it, instead of last. Version ordering inside a game is untouched: only
            # which game gets worked on first is changed, never which copy wins.
            groups = dict(sorted(groups.items(), key=lambda item: self._primary_size(item[1])))
            # How many of this run's archives will actually be rebuilt. A run of twenty games where only two
            # are .zip/.rar has two conversions, and saying "game 7 of 20" while nothing is converting is the
            # one number that tells a user watching an unattended run nothing. Counted before the first move,
            # because the first move is what changes what is left on disk.
            convert_total = sum(1 for group in groups.values() if self._needs_conversion(self._primary(group)))
            conversion_ordinal = 0
            existing = {}
            existing_by_appid = {}
            for path in walk_files(destination):
                if not path.is_file() or path.suffix.lower() not in ARCHIVE_EXTENSIONS or path.parts[: len((target_root / "Archive").parts)] == (target_root / "Archive").parts:
                    continue
                if path.resolve() in source_paths:
                    continue
                existing.setdefault(identity_key(normalize_name(path.name)), []).append(path)
                # An already-organized game carries its Steam identity in .game-info.json beside the archive.
                # Matching by appid catches a re-download whose archive filename changed (e.g. "Foo.zip" vs
                # "Foo.Update.zip") that normalize_name() cannot collapse to one key, so the old copy would
                # otherwise be left behind in its old category.
                try:
                    meta = json.loads((path.parent / ".game-info.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    meta = {}
                appid = str(meta.get("appid") or "").strip()
                if appid:
                    existing_by_appid.setdefault(appid, []).append(path)
            skipped = []
            try:
                for game_index, (key, group) in enumerate(groups.items(), 1):
                    # The review queue is a snapshot taken when the scan finished. Anything that moved or was
                    # archived since then - an earlier organize press, a dedupe pass, Syncthing - leaves an
                    # entry pointing at a path that no longer exists. Moving one of those raised
                    # FileNotFoundError, which aborted the run and rolled back every earlier game, so pressing
                    # Organize again hit exactly the same missing file and looped forever. A vanished file is
                    # simply not this run's work.
                    live = [a for a in group if a.path.is_file()]
                    for archive in group:
                        if archive.path.is_file():
                            continue
                        skipped.append(archive)
                        self.logger.warning("ORGANIZER", f"ORGANIZE_SKIPPED_MISSING path=[{archive.path}] reason=[no longer present; moved or removed since this queue was built]")
                    if not live:
                        continue
                    group = live
                    primary = max(group, key=self.services.organizer._promotion_key)
                    self.logger.info("ORGANIZER", f"PROMOTION_PLAN identity=[{key}] primary=[{primary.path.name}] version={primary.version} copies={len(group)}")
                    for old in group:
                        if old is primary:
                            continue
                        ctx.checkpoint()
                        source = old.path
                        if not source.is_file():
                            continue
                        target = self.services.organizer.archive_file(source, target_root, note=old.conversion)
                        old.path = target
                        moved.append(old)
                        journal.append((source, target))
                        self.logger.info("ORGANIZER", f"PROMOTION_ARCHIVED source=[{source}] target=[{target}]")
                        self.services.rollback.record(journal)
                    archived = set()
                    for old_path in existing.get(key, []):
                        ctx.checkpoint()
                        if not old_path.is_file():
                            continue
                        target = self.services.organizer.archive_file(old_path, target_root)
                        journal.append((old_path, target))
                        archived.add(str(old_path))
                        self.logger.info("ORGANIZER", f"EXISTING_ARCHIVE_MOVED source=[{old_path}] target=[{target}]")
                        self.services.rollback.record(journal)
                    appid = str(getattr(primary.steam, "appid", "") or "").strip()
                    if appid:
                        # Same Steam appid, different archive filename: normalize_name() could not collapse
                        # the two names to one identity key, so the filename sweep above missed this old copy.
                        # Match by appid instead so a re-download with a new filename still retires the
                        # previous one.
                        for old_path in existing_by_appid.get(appid, []):
                            if str(old_path) in archived or not old_path.is_file():
                                continue
                            ctx.checkpoint()
                            target = self.services.organizer.archive_file(old_path, target_root)
                            journal.append((old_path, target))
                            archived.add(str(old_path))
                            self.logger.info("ORGANIZER", f"EXISTING_ARCHIVE_MOVED_BY_APPID source=[{old_path}] target=[{target}] appid=[{appid}]")
                            self.services.rollback.record(journal)
                    ctx.checkpoint()
                    source = primary.path
                    if not source.is_file():
                        skipped.append(primary)
                        self.logger.warning("ORGANIZER", f"ORGANIZE_SKIPPED_MISSING path=[{source}] reason=[disappeared while the run was in progress]")
                        continue
                    # Ordinal of this archive among the run's rebuilds. The screen counts by this rather than by
                    # tallying events, so a game that is moved without needing a rebuild cannot push the counter
                    # past the total the run reported.
                    if self._needs_conversion(primary):
                        conversion_ordinal += 1
                    if on_progress:
                        self.dispatch(
                            lambda i=game_index,
                                   n=len(groups),
                                   name=source.name,
                                   suffix=source.suffix.lower(),
                                   game=primary.steam.name or primary.display_name,
                                   category=primary.decision.category,
                                   o=conversion_ordinal: on_progress(
                                {
                                    "stage": "organizing",
                                    "message": f"Organizing {i} of {n}",
                                    "file": name,
                                    "source_suffix": suffix,
                                    "game": game,
                                    "category": category,
                                    "index": i,
                                    "total": n,
                                    "conversions": convert_total,
                                    "conversion": o,
                                }
                            )
                        )
                    # A password-protected zip cannot be extracted, so it is unlocked inside the conversion
                    # pass below, after the source has passed its integrity test. Unlocking it here - before
                    # that test - meant a corrupt or missing file was being decrypted and rewritten for
                    # nothing, and the rewrite was what the integrity test was then failing on.
                    relay = (
                        lambda event, o=conversion_ordinal: self.dispatch(
                            lambda event=event, c=convert_total, o=o: on_progress(
                                dict(event, conversions=c, conversion=o)
                            )
                            if isinstance(event, dict)
                            else on_progress(event)
                        )
                    ) if on_progress else None
                    try:
                        target = self.services.organizer.move(primary, target_root, on_progress=relay)
                    except CancellationError:
                        raise
                    except Exception as move_error:
                        # One unmovable file does not end a run of two hundred. The game is put back, the reason
                        # is recorded against it, and the next game is tried; a cancelled run still stops here.
                        self._recover_failed_move(primary, source, move_error, journal, owned_dirs, target_root)
                        failed.append(primary)
                        continue
                    primary.path = target
                    moved.append(primary)
                    journal.append((source, target))
                    # Ownership is settled before the row is written, not after: record() reads owned_dirs to
                    # decide whether an undo may remove the folder, so recording first wrote `owned: false` for
                    # the one folder this run actually created, and Undo left it behind like all the others.
                    if getattr(primary, "created_game_dir", False):
                        owned_dirs.add(str(Path(target).parent))
                    self.services.rollback.record(journal, owned_dirs)
            except Exception:
                for source, target in reversed(journal):
                    self._restore_moved(source, target, owned_dirs, target_root)
                raise
            finally:
                # Whether the run finished, was cancelled, or was rolled back, the staging area goes with it:
                # the library root is the user's folder, not the app's scratch space.
                self.services.organizer.cleanup_processing_dir(target_root)
            if skipped:
                self.logger.info("ORGANIZER", f"ORGANIZE_SKIPPED_MISSING_TOTAL skipped={len(skipped)} organized={len(moved)}")
            if failed:
                self.logger.warning("ORGANIZER", f"ORGANIZE_FAILED_GAMES failed={len(failed)} organized={len(moved)}")
            if not self.services.rollback.record(journal, owned_dirs) and journal:
                # This is the one write that has to be true. Every earlier record() in this run already moved a
                # file, and Undo reads this file and nothing else - so if it cannot be written the run's
                # moves are unrecoverable and the user is the only one who can do anything about that. A
                # silently lost journal otherwise presents as a run that worked perfectly, with an Undo button
                # that does nothing. Nine of these are in this repository's own log, all WinError 5 on the
                # project's OneDrive folder, each one a completed organize with nothing left to undo.
                self.logger.error("ORGANIZER", f"ORGANIZE_UNDO_UNAVAILABLE moves={len(journal)} the run completed but cannot be undone")
            try:
                self.services.catalog.generate(target_root, self.services.organizer.needs_catalog_launcher())
            except Exception as exc:
                self.logger.warning("APPLICATION", f"CATALOG_GENERATE_FAILED error={type(exc).__name__}")
            # The games that could not be filed are handed back too. The Done screen counts what a run achieved
            # from this list, and a game that was quietly dropped from it is a game the user is never told about.
            return moved + failed

        return self._submit("organizing", work, lambda r: self._organize_ok(r, done), lambda e: self._failed("organize", e))

    def _sweep_cross_category_duplicates(self, root, ctx, journal):
        """Archive older copies of the same game that live in more than one category.

        Games are grouped by Steam appid (each game folder's .game-info.json). When an appid appears in
        two or more categories, every copy but the newest - judged by the archive's creation time - is
        archived to Archive/ and its move is journaled so Undo can restore it. The Archive folder itself
        is never walked, so already-archived copies are not compared again.

        Returns the number of older copies archived.
        """
        root = Path(root) if not isinstance(root, Path) else root
        by_appid = {}
        for category_dir in root.iterdir():
            if not category_dir.is_dir() or category_dir.name in LIBRARY_RESERVED_DIRS:
                continue
            for game_dir in category_dir.iterdir():
                if not game_dir.is_dir():
                    continue
                meta_path = game_dir / ".game-info.json"
                if not meta_path.is_file():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                appid = str(meta.get("appid") or "").strip()
                if not appid:
                    continue
                archive = None
                for f in game_dir.iterdir():
                    if f.is_file() and f.suffix.lower() in ARCHIVE_EXTENSIONS:
                        archive = f
                        break
                if not archive:
                    continue
                by_appid.setdefault(appid, []).append((archive, game_dir))
        archived_count = 0
        for appid, entries in by_appid.items():
            if len(entries) <= 1:
                continue
            # Newest creation time first: the primary stays, everything else is archived
            entries.sort(key=lambda entry: entry[0].stat().st_ctime, reverse=True)
            for archive, _game_dir in entries[1:]:
                ctx.checkpoint()
                try:
                    if not archive.is_file():
                        continue
                    target = self.services.organizer.archive_file(archive, root)
                    journal.append((archive, target))
                    archived_count += 1
                    self.logger.info("ORGANIZER", f"CROSS_CATEGORY_DUPLICATE_ARCHIVED source=[{archive}] target=[{target}] appid=[{appid}]")
                    self.services.rollback.record(journal)
                except Exception as exc:
                    self.logger.warning("ORGANIZER", f"CROSS_CATEGORY_DUPLICATE_FAILED source=[{archive}] error={type(exc).__name__}")
        return archived_count

    def _organize_ok(self, result, done):
        self.state.update(phase="done", job_id="")
        self.bus.emit(Event("organize_completed", {"archives": result}))
        done(result)

    def undo_last(self, library_root, done):
        def work(ctx):
            ctx.checkpoint()
            result = self.services.rollback.undo_last(library_root)
            # Undo is the one path that changes the library without regenerating the catalog, so the index the
            # catalog retains is still describing the run that was just put back. Dropped rather than rebuilt
            # here: an index is only read when a screen asks for one, so rebuilding would pay for a metadata
            # walk nobody asked for on the press of a button. Scans and organizes need no such call - both end
            # by generating the catalog, which retains a fresh index of what they left behind.
            if isinstance(result, dict) and (int(result.get("moved") or 0) or int(result.get("pruned") or 0)):
                try:
                    self.services.catalog.invalidate_summary()
                except Exception as exc:
                    self.logger.warning("APPLICATION", f"CATALOG_INDEX_INVALIDATE_FAILED error={type(exc).__name__}")
            return result

        return self._submit("undoing", work, lambda r: self._undo_ok(r, done), lambda e: self._failed("undo", e))

    def _undo_ok(self, result, done):
        self.state.update(phase="idle", job_id="")
        done(result)

    def _failed(self, op, exc):
        if isinstance(exc, CancellationError):
            self.logger.info("APPLICATION", f"OPERATION_CANCELLED op={op}")
            self.bus.emit(Event("operation_cancelled", {"operation": op, "error": exc}))
            return
        self.state.update(phase="error", last_error=str(exc), job_id="")
        self.logger.exception("APPLICATION", f"OPERATION_FAILED op={op}", exc)
        self.bus.emit(Event("operation_failed", {"operation": op, "error": exc}))
