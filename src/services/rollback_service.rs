//! Small JSON journal for the last organization transaction.
//!
//! 2026-11-25: Converted from `services/rollback_service.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use lazy_static::lazy_static;
use regex::Regex;
use serde_json;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::core::constants::ARCHIVE_EXTENSIONS;
use crate::core::path_safety::is_within;

lazy_static! {
    static ref WHITESPACE_RE: Regex = Regex::new(r"\s+").expect("WHITESPACE_RE regex is valid");
}

/// Small JSON journal for the last organization transaction.
pub struct RollbackService {
    journal: PathBuf,
    logger: Option<Box<dyn Fn(&str, &str) + Send + Sync>>,
    /// Held only to answer one question: may this folder be removed? OrganizerService._folder_is_disposable()
    /// owns that allow-list, and duplicating it here would be a second copy of the rule that decides what
    /// gets deleted from a user's library - exactly the kind of second answer this codebase keeps removing.
    /// Optional, because half the test suite builds this service on its own, and without it nothing is
    /// pruned rather than something being pruned on a guess.
    organizer: Option<Box<dyn Fn(&Path) -> bool + Send + Sync>>,
    library_root: Option<PathBuf>,
}

impl RollbackService {
    pub fn new(
        project_root: &Path,
        logger: Option<Box<dyn Fn(&str, &str) + Send + Sync>>,
        organizer: Option<Box<dyn Fn(&Path) -> bool + Send + Sync>>,
        library_root: Option<&Path>,
    ) -> Self {
        let journal = project_root.join("config").join("last-organization.json");
        let library_root = library_root.map(|l| l.to_path_buf());
        let _ = fs::create_dir_all(journal.parent().unwrap());
        RollbackService {
            journal,
            logger,
            organizer,
            library_root,
        }
    }

    /// Writes the journal atomically, the way the settings file and the Steam cache are written.
    ///
    /// A plain write_text is truncated if the app is killed or the disk fills part-way through, and this file
    /// is the only record of where a run put things. Losing the tail of it is what turned an interrupted run
    /// into an Undo that raised instead of undoing, so the temp-and-replace dance is what keeps a half-written
    /// journal from existing at all.
    ///
    /// Returns True when the journal reached the disk, and False when it did not.
    pub fn record(&self, moves: &[(PathBuf, PathBuf)], owned_dirs: &[PathBuf]) -> bool {
        let owned: std::collections::HashSet<String> = owned_dirs
            .iter()
            .map(|p| p.to_string_lossy().to_string())
            .collect();
        let payload_rows: Vec<serde_json::Value> = moves
            .iter()
            .map(|(a, b)| {
                let target_parent = b
                    .parent()
                    .unwrap_or(Path::new(""))
                    .to_string_lossy()
                    .to_string();
                serde_json::json!({
                    "source": a.to_string_lossy(),
                    "target": b.to_string_lossy(),
                    "owned": owned.contains(&target_parent),
                })
            })
            .collect();
        let payload = match serde_json::to_string_pretty(&payload_rows) {
            Ok(p) => p,
            Err(_) => return false,
        };
        let mut temp: Option<PathBuf> = None;
        let result = (|| -> Result<bool, std::io::Error> {
            fs::create_dir_all(self.journal.parent().unwrap())?;
            // A unique temp name: two instances of the app share this journal, and a
            // fixed name meant the loser's cleanup unlinked the winner's temp file before
            // it could be replaced - losing the record of a completed organize.
            let ts = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0);
            let pid = std::process::id();
            let temp_name = format!("last-organization.{}.{}.tmp", pid, ts);
            let temp_path = self.journal.parent().unwrap().join(&temp_name);
            temp = Some(temp_path.clone());
            {
                let mut f = fs::File::create(&temp_path)?;
                f.write_all(payload.as_bytes())?;
                f.flush()?;
            }
            for attempt in 0..4 {
                match std::fs::rename(&temp_path, &self.journal) {
                    Ok(()) => return Ok(true),
                    Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                        if attempt == 3 {
                            return Err(e);
                        }
                        std::thread::sleep(std::time::Duration::from_millis(
                            50 * (attempt + 1) as u64,
                        ));
                    }
                    Err(e) => return Err(e),
                }
            }
            Ok(false)
        })();
        match result {
            Ok(true) => true,
            Ok(false) => false,
            Err(exc) => {
                let detail = WHITESPACE_RE
                    .replace_all(&exc.to_string(), " ")
                    .trim()
                    .to_string();
                let detail = detail.chars().take(200).collect::<String>();
                if let Some(logger) = &self.logger {
                    logger(
                        "ROLLBACK",
                        &format!(
                            "JOURNAL_WRITE_FAILED path=[{}] error=[{}] errno=[{}] detail=[{}] moves=[{}]",
                            self.journal.display(),
                            exc,
                            exc.raw_os_error().unwrap_or(0),
                            detail,
                            moves.len()
                        ),
                    );
                }
                false
            }
        }
    }

    /// The moves this journal can still undo, as a list of dicts with usable source/target paths.
    fn _rows(&self) -> Vec<serde_json::Value> {
        let text = match fs::read_to_string(&self.journal) {
            Ok(t) => t,
            Err(_) => return Vec::new(),
        };
        let rows: Vec<serde_json::Value> = match serde_json::from_str(&text) {
            Ok(r) => r,
            Err(_) => return Vec::new(),
        };
        rows.into_iter()
            .filter(|row| {
                row.is_object() && row.get("source").is_some() && row.get("target").is_some()
            })
            .collect()
    }

    /// How many moves the last transaction can still undo. Surfaced live during a run so the user knows
    /// what Undo will actually restore before they finish.
    pub fn pending_count(&self) -> usize {
        self._rows().len()
    }

    /// Undo the last organization transaction.
    pub fn undo_last(&self, library_root: Option<&Path>) -> serde_json::Value {
        if !self.journal.is_file() {
            return serde_json::json!({
                "moved": 0,
                "pruned": 0,
                "reason": "No organization transaction to undo"
            });
        }
        let rows = self._rows();
        if rows.is_empty() {
            return serde_json::json!({
                "moved": 0,
                "pruned": 0,
                "reason": "The last organization record could not be read, so there is nothing to undo"
            });
        }
        let mut moved = 0;
        let mut pruned = 0;
        for row in rows.iter().rev() {
            let src = PathBuf::from(row.get("source").and_then(|v| v.as_str()).unwrap_or(""));
            let dst = PathBuf::from(row.get("target").and_then(|v| v.as_str()).unwrap_or(""));
            // The organized file may have been repacked (.zip -> .rar) after the move, so its extension can
            // differ from the recorded source; restore using the current extension, not the stale one.
            let restore = if src.extension() == dst.extension() {
                src.clone()
            } else {
                src.with_extension(dst.extension().unwrap_or_default())
            };
            if dst.exists() && !restore.exists() {
                if let Some(parent) = restore.parent() {
                    let _ = fs::create_dir_all(parent);
                }
                if let Err(e) = fs::rename(&dst, &restore) {
                    if let Some(logger) = &self.logger {
                        logger(
                            "ROLLBACK",
                            &format!("UNDO_MOVE_FAILED path=[{}] error={}", dst.display(), e),
                        );
                    }
                } else {
                    moved += 1;
                }
            }
            if let Some(parent) = dst.parent() {
                let owned = row.get("owned").and_then(|v| v.as_bool()).unwrap_or(false);
                if self._prune_emptied(parent, owned, library_root) {
                    pruned += 1;
                }
            }
        }
        if moved == rows.len() {
            if let Err(e) = fs::remove_file(&self.journal) {
                if let Some(logger) = &self.logger {
                    logger(
                        "ROLLBACK",
                        &format!(
                            "JOURNAL_CLEAR_FAILED path=[{}] error={}",
                            self.journal.display(),
                            e
                        ),
                    );
                }
            }
        }
        if let Some(logger) = &self.logger {
            logger(
                "ROLLBACK",
                &format!("UNDO moved={} pruned={}", moved, pruned),
            );
        }
        serde_json::json!({
            "moved": moved,
            "pruned": pruned,
            "reason": "Rollback complete"
        })
    }

    /// Move the game folder this rollback just emptied to Archive, and report whether it did.
    fn _prune_emptied(&self, game_dir: &Path, owned: bool, library_root: Option<&Path>) -> bool {
        let game_dir = game_dir.to_path_buf();
        if !owned {
            if let Some(logger) = &self.logger {
                logger(
                    "ROLLBACK",
                    &format!(
                        "KEPT_EMPTY_GAME_DIR path=[{}] reason=[this run did not create it]",
                        game_dir.display()
                    ),
                );
            }
            return false;
        }
        let root = library_root
            .map(|l| l.to_path_buf())
            .or_else(|| self.library_root.clone());
        let root = match root {
            Some(r) => r,
            None => {
                if let Some(logger) = &self.logger {
                    logger("ROLLBACK", &format!("KEPT_EMPTY_GAME_DIR path=[{}] reason=[no library root to prove containment]", game_dir.display()));
                }
                return false;
            }
        };
        match (game_dir.canonicalize(), root.canonicalize()) {
            (Ok(g), Ok(r)) => {
                if !is_within(&g, &r) {
                    if let Some(logger) = &self.logger {
                        logger(
                            "ROLLBACK",
                            &format!(
                                "KEPT_EMPTY_GAME_DIR path=[{}] reason=[outside the library]",
                                game_dir.display()
                            ),
                        );
                    }
                    return false;
                }
            }
            _ => return false,
        }
        if !game_dir.is_dir() {
            return false;
        }
        if game_dir.read_dir().map_or(false, |mut entries| {
            entries.any(|e| {
                e.map_or(false, |entry| {
                    entry.path().extension().map_or(false, |ext| {
                        ARCHIVE_EXTENSIONS
                            .iter()
                            .any(|ae| ext.eq_ignore_ascii_case(ae))
                    })
                })
            })
        }) {
            return false;
        }
        if let Some(organizer) = &self.organizer {
            if !organizer(&game_dir) {
                return false;
            }
        } else {
            return false;
        }
        let archive_dir = root.join("Archive");
        if let Err(e) = fs::create_dir_all(&archive_dir) {
            if let Some(logger) = &self.logger {
                logger(
                    "ROLLBACK",
                    &format!(
                        "PRUNE_CREATE_ARCHIVE_FAILED path=[{}] error={}",
                        archive_dir.display(),
                        e
                    ),
                );
            }
            return false;
        }
        let mut target = archive_dir.join(game_dir.file_name().unwrap_or_default());
        let mut n = 2;
        while target.exists() {
            target = archive_dir.join(format!(
                "{} ({})",
                game_dir.file_name().unwrap_or_default().to_string_lossy(),
                n
            ));
            n += 1;
        }
        match fs::rename(&game_dir, &target) {
            Ok(()) => {
                if let Some(logger) = &self.logger {
                    logger(
                        "ROLLBACK",
                        &format!(
                            "PRUNED_EMPTY_GAME_DIR path=[{}] destination=[{}]",
                            game_dir.display(),
                            target.display()
                        ),
                    );
                }
                true
            }
            Err(e) => {
                if let Some(logger) = &self.logger {
                    logger(
                        "ROLLBACK",
                        &format!("PRUNE_FAILED path=[{}] error={}", game_dir.display(), e),
                    );
                }
                false
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pending_count_empty() {
        use std::env;
        let temp = env::temp_dir().join(format!("test_rollback_{}", std::process::id()));
        std::fs::create_dir_all(&temp).ok();
        let service = RollbackService::new(&temp, None, None, None);
        assert_eq!(service.pending_count(), 0);
        let _ = fs::remove_dir_all(&temp);
    }
}

