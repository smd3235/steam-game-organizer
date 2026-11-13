"""Data models shared across the app.

SteamMatch, ArtworkResult, OrganizationDecision, ConversionResult, GameArchive,
ScanResult and AppState are the plain-data containers that every phase — discovery,
organize, rollback, audit, repair — reads and writes. They are deliberately free of
logic; the why of each field is documented beside it so a change to one model does
not silently break a screen or service that depends on it.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.constants import CategoryEvidence, UNSORTED_EVIDENCE


@dataclass
class SteamMatch:
    """The result of looking one game up against Steam's store API and its own files.

    found is whether a match was made at all; appid is Steam's numeric identifier and
    everything else is the store's copy of the game's identity. score is how confident
    the matcher is, so a screen can show a low-confidence match as a guess the user
    should confirm rather than treat as fact.
    """

    found: bool = False
    appid: str = ""
    name: str = ""
    genres: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    release_date: str = ""
    confidence: str = ""
    source: str = ""
    reason: str = ""
    developer: str = ""
    publisher: str = ""
    score: float = 0.0
    artwork_url: str = ""
    asset_urls: dict[str, str] = field(default_factory=dict)


@dataclass
class ArtworkResult:
    status: str = "not_requested"
    path: Optional[Path] = None
    source: str = ""
    reason: str = ""
    assets: dict[str, Path] = field(default_factory=dict)

    def files(self) -> list[Path]:
        """Every image this result really holds on disk: the primary plus each downloaded asset.

        Steam serves a game's pictures either way. A real run over Glow Stick Samurai.7z came back with an empty
        primary and five real assets - header_image, capsule_image, background and the rest - which
        OrganizerService.move() copies into the game folder in full. So a screen that asks only whether
        `path` is set reports that game as having no artwork at all, while its folder holds five of them.

        Every entry is checked with is_file() rather than merely tested for truth, because that is the same
        test OrganizerService.move() applies before copying, and because a path left behind by a pruned
        cache is not an image. The primary is not repeated when an asset names the same file.
        """
        found: list[Path] = []
        for candidate in [self.path, *self.assets.values()]:
            if not candidate:
                continue
            path = Path(candidate)
            if path.is_file() and path not in found:
                found.append(path)
        return found

    def present(self) -> bool:
        """Whether this game has any artwork on disk at all, whichever way it arrived."""
        return bool(self.files())


@dataclass
class OrganizationDecision:
    category: str = "Unsorted"
    suggested_category: str = ""
    # Why the suggestion was made. This always describes the *computed* suggestion,
    # never `category`: a remembered category decision can replace `category` after
    # the evidence was recorded (app/controller.py), so a screen must read it beside
    # suggested_category, not beside the category that may have replaced it.
    evidence: CategoryEvidence = UNSORTED_EVIDENCE
    accepted: bool = False
    changed_from_suggestion: bool = False
    skipped: bool = False


@dataclass
class ConversionResult:
    """Outcome of the .zip/.rar -> .7z conversion (or rebuild) for one archive. Kept on the archive so the
    Done screen can report what actually happened, including failures that were only visible in the log."""

    status: str = "pending"  # converted | rebuilt | skipped | failed | not_needed
    message: str = ""
    source_format: str = ""
    target_format: str = ""
    final_name: str = ""
    final_size: int = 0
    source_size: int = 0  # bytes before conversion, so the run report can state real space saved
    free_bytes_at_failure: int = 0


@dataclass
class GameArchive:
    path: Path
    display_name: str
    normalized_title: str
    identity_key: str
    extension: str
    version: tuple = (0,)
    steam: SteamMatch = field(default_factory=SteamMatch)
    artwork: ArtworkResult = field(default_factory=ArtworkResult)
    decision: OrganizationDecision = field(default_factory=OrganizationDecision)
    selected: bool = False
    user_title: str = ""
    conversion: ConversionResult = field(default_factory=ConversionResult)
    organized_path: Optional[Path] = None
    # True when this run is the one that created organized_path's folder. A folder that was already there
    # belongs to the user, so a rollback may only take away the ones this run made.
    created_game_dir: bool = False
    # Bytes on disk at discovery. ConversionResult only learns source_size once a conversion is attempted, so
    # without this an archive that is never converted has no size anywhere in the app, and the review pane
    # showed a file name with no idea how big the file was.
    size: int = 0

    def __hash__(self):
        return hash(self.identity_key)


@dataclass
class ScanResult:
    archives: list[GameArchive] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Build folders this app abandoned in earlier runs. They are correctly kept out of the archive list, but
    # nothing ever swept them, so they sat on the library volume holding real disk space with nothing to show
    # for it. A real library was found holding 14 of them and 6.7 GB.
    stale_build_dirs: int = 0
    stale_build_bytes: int = 0


@dataclass
class AppState:
    phase: str = "idle"
    selected_index: int | None = None
    scan_result: ScanResult = field(default_factory=ScanResult)
    job_id: str = ""
    cancel_requested: bool = False
    developer_mode: bool = False
    last_error: str = ""


@dataclass
class MinimalArchive:
    """Lightweight stand-in so LibraryService can reuse OrganizerService.write_metadata() for games that
    predate the .game-info.json sidecar, without needing a full GameArchive/SteamMatch round trip."""

    appid: str = ""
    name: str = ""
    category: str = ""

    @property
    def steam(self):
        return type("S", (), {"appid": self.appid, "name": self.name, "description": "", "release_date": "", "genres": [], "tags": [], "developer": "", "publisher": ""})()

    @property
    def user_title(self):
        return self.name

    @property
    def display_name(self):
        return self.name

    @property
    def decision(self):
        return type("D", (), {"category": self.category})()


@dataclass
class RepairArchive:
    """Minimal stand-in for GameArchive so the library repair pass can reuse the organizer's conversion
    routine on an archive that discovery never built an object for.

    It carries a real ConversionResult, not just the fields the packer reads. Without one the organizer's
    `note = getattr(archive,'conversion',None)` was always None here, so every repair outcome was thrown away:
    the Done screen could not name what the repair pass did, and a caller could not tell a successful
    conversion from an archive that was skipped or that failed to extract."""

    path: Path
    appid: str = ""
    name: str = ""
    found: bool = False
    conversion: ConversionResult = field(default_factory=ConversionResult)

    @property
    def display_name(self):
        return self.name

    @property
    def user_title(self):
        return self.name

    @property
    def steam(self):
        return type("S", (), {"appid": self.appid, "found": self.found, "name": self.name, "description": "", "release_date": "", "genres": [], "tags": []})()

    @property
    def decision(self):
        return type("D", (), {"category": ""})()
