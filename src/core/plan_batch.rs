//! Plan a batch: work out what a batch would do, without unpacking anything.
//!
//! Separate from running it so the window can show the real count, the real total size and the real destination
//! before the user commits - a run of 176 games and 244 GB should be confirmable on the evidence, not on a
//! promise made by a button label.
//!
//! name_map: optional dict mapping archive Path -> (steam_name, release_date). When provided, extraction
//! folders are named "{steam_name} - {release_date}" instead of the messy archive filename stem.
//!
//! 2026-11-25: Converted from `services/plan_batch.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

#![allow(clippy::all)]

use std::collections::HashMap;
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use crate::services::archive_service::ArchiveService;
use crate::core::batch_item::BatchItem;
use crate::core::catalog_status::already_extracted;
use crate::core::filename_utils::normalize_name;
use crate::core::installer_detect::NEEDS_INSTALL_DIRNAME;
use crate::core::models::GameArchive;

/// Everything the window needs before the first archive is touched.
#[derive(Debug, Clone)]
pub struct BatchPlan {
    pub items: Vec<BatchItem>,
    pub total_bytes: u64,
    pub destination: PathBuf,
    pub category: String,
    pub already_done: u32,
}

impl BatchPlan {
    pub fn new(destination: &Path, category: &str) -> Self {
        BatchPlan {
            items: Vec::new(),
            total_bytes: 0,
            destination: destination.to_path_buf(),
            category: if category.is_empty() {
                "the whole library".to_string()
            } else {
                category.to_string()
            },
            already_done: 0,
        }
    }
}

/// Plan a batch: work out what a batch would do, without unpacking anything.
///
/// Separate from running it so the window can show the real count, the real total size and the real destination
/// before the user commits - a run of 176 games and 244 GB should be confirmable on the evidence, not on a
// promise made by a button label.
///
/// name_map: optional dict mapping archive Path -> (steam_name, release_date). When provided, extraction
/// folders are named "{steam_name} - {release_date}" instead of the messy archive filename stem.
pub fn plan_batch(
    library_root: &Path,
    destination: &Path,
    category: &str,
    logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
    skip_existing: bool,
    name_map: Option<&HashMap<PathBuf, (String, String)>>,
) -> BatchPlan {
    let service = ArchiveService::new(logger.clone(), false, None);
    let root = library_root.to_path_buf();
    let result = if category.is_empty() {
        service.discover(&root, None, None, false, false, false, true)
    } else {
        service.discover(&root.join(category), None, None, false, false, false, true)
    };

    // Sort by size, smallest first: a batch is hours of 7z, and a user watching it
    // wants the small games to land first so they can start playing while the big ones
    // grind on. Archives that could not be stat()'d (size=0) sort to the end.
    let mut plan_archives: Vec<&GameArchive> = result.archives.iter().collect();
    plan_archives.sort_by_key(|a| a.size);

    let mut plan = BatchPlan::new(destination, category);
    // Two games can share a stem - a .7z and a .zip of the same title in different folders - and they would
    // otherwise unpack into one folder and interleave. The counter is on the name, not the path, because the
    // name is the folder.
    let mut used: HashSet<String> = HashSet::new();
    for archive in plan_archives {
        // Use the clean Steam name + release date from catalog metadata when available,
        // falling back to the messy archive filename stem.
        let entry = name_map.and_then(|nm| nm.get(&archive.path));
        let (_clean, mut leaf) = if let Some((steam_name, release_date)) = entry {
            let clean = format!("{}", steam_name);
            let clean = if !release_date.is_empty() {
                format!("{} - {}", clean, release_date.replace(",", ""))
            } else {
                clean
            };
            let leaf = normalize_name(&clean);
            (clean, leaf)
        } else {
            let leaf = normalize_name(
                archive
                    .path
                    .file_stem()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .as_ref(),
            );
            (archive.display_name.clone(), leaf)
        };
        if used.contains(&leaf) {
            let mut suffix = 2;
            while used.contains(&format!("{} ({})", leaf, suffix)) {
                suffix += 1;
            }
            leaf = format!("{} ({})", leaf, suffix);
        }
        used.insert(leaf.clone());
        // Installer archives go into <dest>/Needs Install/<leaf> instead of <dest>/<leaf>, so they
        // are separated from ready-to-play games at a glance. The signature is read from the archive
        // index (not its payload), so this is a header scan with no extraction cost.
        let is_installer = service.archive_installer_kind(&archive.path).is_some();
        let target = if is_installer {
            destination.join(NEEDS_INSTALL_DIRNAME).join(&leaf)
        } else {
            destination.join(&leaf)
        };
        let size = archive.path.metadata().map_or(0, |m| m.len());
        if skip_existing && already_extracted(&target) {
            plan.already_done += 1;
            continue;
        }
        plan.items.push(BatchItem {
            archive: Some(archive.path.clone()),
            destination: Some(target.clone()),
            name: archive.display_name.clone(),
            size,
            state: crate::core::batch_item::QUEUED.to_string(),
            detail: String::new(),
            percent: 0,
            written: 0,
            files: 0,
        });
    }
    plan.total_bytes = plan.items.iter().map(|item| item.size).sum();
    plan
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_batch_plan_default() {
        let plan = BatchPlan::new(Path::new("/dest"), "Action");
        assert_eq!(plan.destination, Path::new("/dest"));
        assert_eq!(plan.category, "Action");
        assert_eq!(plan.items.len(), 0);
        assert_eq!(plan.total_bytes, 0);
        assert_eq!(plan.already_done, 0);
    }

    #[test]
    fn test_batch_plan_empty_category() {
        let plan = BatchPlan::new(Path::new("/dest"), "");
        assert_eq!(plan.category, "the whole library");
    }
}

