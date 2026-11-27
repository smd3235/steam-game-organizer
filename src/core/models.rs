//! Data models shared across the app.
//!
//! `SteamMatch`, `ArtworkResult`, `OrganizationDecision`, `ConversionResult`, `GameArchive`,
//! `ScanResult`, `AppState`, `MinimalArchive` and `RepairArchive` are the plain-data containers
//! that every phase — discovery, organize, rollback, audit, repair — reads and writes. They are
//! deliberately free of logic; the why of each field is documented beside it so a change to one
//! model does not silently break a screen or service that depends on it.
//!
//! 2026-11-24: Converted from `core/models.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

use crate::core::category_evidence::{unsorted_evidence, CategoryEvidence};

/// The result of looking one game up against Steam's store API and its own files.
///
/// `found` is whether a match was made at all; `appid` is Steam's numeric identifier and
/// everything else is the store's copy of the game's identity. `score` is how confident
/// the matcher is, so a screen can show a low-confidence match as a guess the user
/// should confirm rather than treat as fact.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SteamMatch {
    pub found: bool,
    pub appid: String,
    pub name: String,
    pub genres: Vec<String>,
    pub categories: Vec<String>,
    pub description: String,
    pub tags: Vec<String>,
    pub release_date: String,
    pub confidence: String,
    pub source: String,
    pub reason: String,
    pub developer: String,
    pub publisher: String,
    pub score: f64,
    pub artwork_url: String,
    pub asset_urls: std::collections::HashMap<String, String>,
}

/// Every image this result really holds on disk: the primary plus each downloaded asset.
///
/// Steam serves a game's pictures either way. A real run over Glow Stick Samurai.7z came back with an empty
/// primary and five real assets - header_image, capsule_image, background and the rest - which
/// `OrganizerService::move` copies into the game folder in full. So a screen that asks only whether
/// `path` is set reports that game as having no artwork at all, while its folder holds five of them.
///
/// Every entry is checked with `is_file()` rather than merely tested for truth, because that is the same
/// test `OrganizerService::move` applies before copying, and because a path left behind by a pruned
/// cache is not an image. The primary is not repeated when an asset names the same file.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ArtworkResult {
    pub status: String,
    pub path: Option<PathBuf>,
    pub source: String,
    pub reason: String,
    pub assets: std::collections::HashMap<String, PathBuf>,
}

impl ArtworkResult {
    pub fn files(&self) -> Vec<PathBuf> {
        let mut found: Vec<PathBuf> = Vec::new();
        if let Some(path) = &self.path {
            if path.is_file() && !found.contains(path) {
                found.push(path.clone());
            }
        }
        for path in self.assets.values() {
            if path.is_file() && !found.contains(path) {
                found.push(path.clone());
            }
        }
        found
    }

    pub fn present(&self) -> bool {
        !self.files().is_empty()
    }
}

/// Why the suggestion was made. This always describes the *computed* suggestion,
/// never `category`: a remembered category decision can replace `category` after
/// the evidence was recorded, so a screen must read it beside
/// `suggested_category`, not beside the category that may have replaced it.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrganizationDecision {
    pub category: String,
    pub suggested_category: String,
    pub evidence: CategoryEvidence,
    pub accepted: bool,
    pub changed_from_suggestion: bool,
    pub skipped: bool,
}

/// Outcome of the `.zip`/`.rar` -> `.7z` conversion (or rebuild) for one archive. Kept on the archive
/// so the Done screen can report what actually happened, including failures that were only visible in the log.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ConversionResult {
    pub status: String, // converted | rebuilt | skipped | failed | not_needed
    pub message: String,
    pub source_format: String,
    pub target_format: String,
    pub final_name: String,
    pub final_size: u64,
    pub source_size: u64, // bytes before conversion, so the run report can state real space saved
    pub free_bytes_at_failure: u64,
}

impl Default for OrganizationDecision {
    fn default() -> Self {
        OrganizationDecision {
            category: "Unsorted".to_string(),
            suggested_category: String::new(),
            evidence: unsorted_evidence(),
            accepted: false,
            changed_from_suggestion: false,
            skipped: false,
        }
    }
}

/// One discovered archive, with its Steam match, artwork, decision, and conversion result.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct GameArchive {
    pub path: PathBuf,
    pub display_name: String,
    pub normalized_title: String,
    pub identity_key: String,
    pub extension: String,
    pub version: Vec<u32>,
    pub steam: SteamMatch,
    pub artwork: ArtworkResult,
    pub decision: OrganizationDecision,
    pub selected: bool,
    pub user_title: String,
    pub conversion: ConversionResult,
    pub organized_path: Option<PathBuf>,
    /// True when this run is the one that created `organized_path`'s folder. A folder that was already there
    /// belongs to the user, so a rollback may only take away the ones this run made.
    pub created_game_dir: bool,
    /// Bytes on disk at discovery. `ConversionResult` only learns `source_size` once a conversion is attempted,
    /// so without this an archive that is never converted has no size anywhere in the app, and the review pane
    /// showed a file name with no idea how big the file was.
    pub size: u64,
}

impl std::hash::Hash for GameArchive {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.identity_key.hash(state);
    }
}

impl PartialEq for GameArchive {
    fn eq(&self, other: &Self) -> bool {
        self.identity_key == other.identity_key
    }
}

impl Eq for GameArchive {}

/// Result of a scan: the discovered archives, any errors, and stale build folders.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ScanResult {
    pub archives: Vec<GameArchive>,
    pub errors: Vec<String>,
    /// Build folders this app abandoned in earlier runs. They are correctly kept out of the archive list, but
    /// nothing ever swept them, so they sat on the library volume holding real disk space with nothing to show
    /// for it. A real library was found holding 14 of them and 6.7 GB.
    pub stale_build_dirs: u32,
    pub stale_build_bytes: u64,
}

/// Current UI state: phase, selection, scan result, job, and any error.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AppState {
    pub phase: String,
    pub selected_index: Option<usize>,
    pub scan_result: ScanResult,
    pub job_id: String,
    pub cancel_requested: bool,
    pub developer_mode: bool,
    pub last_error: String,
}

/// Lightweight stand-in so `LibraryService` can reuse `OrganizerService::write_metadata()` for games that
/// predate the `.game-info.json` sidecar, without needing a full `GameArchive`/`SteamMatch` round trip.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct MinimalArchive {
    pub appid: String,
    pub name: String,
    pub category: String,
}

impl MinimalArchive {
    pub fn steam_appid(&self) -> &str {
        &self.appid
    }
    pub fn steam_name(&self) -> &str {
        &self.name
    }
    pub fn user_title(&self) -> &str {
        &self.name
    }
    pub fn display_name(&self) -> &str {
        &self.name
    }
    pub fn decision_category(&self) -> &str {
        &self.category
    }
}

/// Minimal stand-in for `GameArchive` so the library repair pass can reuse the organizer's conversion
/// routine on an archive that discovery never built an object for.
///
/// It carries a real `ConversionResult`, not just the fields the packer reads. Without one the organizer's
/// `note = getattr(archive,'conversion',None)` was always None here, so every repair outcome was thrown away:
/// the Done screen could not name what the repair pass did, and a caller could not tell a successful
/// conversion from an archive that was skipped or that failed to extract.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RepairArchive {
    pub path: PathBuf,
    pub appid: String,
    pub name: String,
    pub found: bool,
    pub conversion: ConversionResult,
}

impl RepairArchive {
    pub fn display_name(&self) -> &str {
        &self.name
    }
    pub fn user_title(&self) -> &str {
        &self.name
    }
    pub fn decision_category(&self) -> &str {
        ""
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_steam_match_default() {
        let m = SteamMatch::default();
        assert!(!m.found);
        assert_eq!(m.appid, "");
        assert_eq!(m.name, "");
        assert_eq!(m.confidence, "");
        assert_eq!(m.score, 0.0);
    }

    #[test]
    fn test_artwork_result_present() {
        let a = ArtworkResult::default();
        assert!(!a.present());
        assert!(a.files().is_empty());
    }

    #[test]
    fn test_artwork_result_files_dedup() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("same.png");
        std::fs::write(&path, b"fake png").unwrap();
        let a = ArtworkResult {
            path: Some(path.clone()),
            assets: std::collections::HashMap::from([("header".to_string(), path)]),
            ..Default::default()
        };
        let files = a.files();
        assert_eq!(files.len(), 1);
    }

    #[test]
    fn test_organization_decision_default() {
        let d = OrganizationDecision::default();
        assert_eq!(d.category, "Unsorted");
        assert!(!d.accepted);
        assert!(!d.changed_from_suggestion);
        assert!(!d.skipped);
    }

    #[test]
    fn test_conversion_result_default() {
        let c = ConversionResult::default();
        assert_eq!(c.status, "");
        assert_eq!(c.final_size, 0);
        assert_eq!(c.source_size, 0);
    }

    #[test]
    fn test_gamearchive_default_hash_eq() {
        let a1 = GameArchive {
            identity_key: "abc".to_string(),
            ..Default::default()
        };
        let a2 = GameArchive {
            identity_key: "abc".to_string(),
            ..Default::default()
        };
        let a3 = GameArchive {
            identity_key: "def".to_string(),
            ..Default::default()
        };
        assert_eq!(a1, a2);
        assert_ne!(a1, a3);
        use std::collections::HashSet;
        let mut set = HashSet::new();
        set.insert(a1.clone());
        set.insert(a2);
        assert_eq!(set.len(), 1);
        set.insert(a3);
        assert_eq!(set.len(), 2);
    }

    #[test]
    fn test_scan_result_default() {
        let s = ScanResult::default();
        assert!(s.archives.is_empty());
        assert!(s.errors.is_empty());
        assert_eq!(s.stale_build_dirs, 0);
        assert_eq!(s.stale_build_bytes, 0);
    }

    #[test]
    fn test_app_state_default() {
        let s = AppState::default();
        assert_eq!(s.phase, "");
        assert_eq!(s.selected_index, None);
        assert!(!s.cancel_requested);
        assert!(!s.developer_mode);
        assert_eq!(s.last_error, "");
    }

    #[test]
    fn test_minimalarchive_methods() {
        let m = MinimalArchive {
            appid: "123".to_string(),
            name: "Test Game".to_string(),
            category: "RPG".to_string(),
        };
        assert_eq!(m.steam_appid(), "123");
        assert_eq!(m.steam_name(), "Test Game");
        assert_eq!(m.user_title(), "Test Game");
        assert_eq!(m.display_name(), "Test Game");
        assert_eq!(m.decision_category(), "RPG");
    }

    #[test]
    fn test_repairarchive_methods() {
        let r = RepairArchive {
            path: std::path::PathBuf::from("/tmp/game.zip"),
            appid: "456".to_string(),
            name: "Repair Game".to_string(),
            found: true,
            conversion: ConversionResult::default(),
        };
        assert_eq!(r.display_name(), "Repair Game");
        assert_eq!(r.user_title(), "Repair Game");
        assert_eq!(r.decision_category(), "");
    }
}
