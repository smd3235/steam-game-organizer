//! Batch extraction service: unpacks many archives in one run, one row of status per game.
//!
//! A single Extract is a link, a 7z call and an exit. A category is twenty games and a whole library is a
//! hundred and seventy-six, which is hours - so this is a queue rather than a loop inline in the entry
//! point: it has to be able to report which game it is on, how many are left, and to stop between games.
//!
//! Two decisions worth stating, because both were the alternative and both were worse:
//!
//!   - The library is enumerated through ArchiveService.discover rather than from a list in the link. The
//!     link names a category and nothing else, so there is no set of paths for a hostile page to choose,
//!     and discover is already the app's own definition of what counts as a game - which keeps dot-folders,
//!     the Processing folder and Archive/ out of a run that is meant to be the user's library.
//!
//!   - A failure is recorded and the queue continues. One unreadable archive in a hundred and seventy-six
//!     must not cost the other hundred and seventy-five, which is the same lesson the organize run learned
//!     the hard way.
//!
//! Skip-if-already-extracted is on by default. Without it, "Extract all" on a shelf of 176 games re-unpacks
//! everything already unpacked on every click, and the button stops being usable after the first hour.
//!
//! 2026-11-25: Converted from `services/batch_extract_service.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use crate::core::batch_item::{BatchItem, CANCELLED, DONE, EXTRACTING, FAILED, QUEUED};
use crate::services::extract_service::ExtractService;
use crate::core::formatting::human_size;
use crate::core::plan_batch::BatchPlan;

/// Runs a BatchPlan on a worker thread and reports each transition.
///
/// The window owns the widgets and this owns the work, and the only thing crossing between them is
/// `on_progress(stage, item, detail)` - the same shape the organize view already uses, so the two progress
/// surfaces in the app behave alike.
pub struct BatchExtractJob {
    items: Vec<Mutex<BatchItem>>,
    destination: PathBuf,
    category: String,
    _already_done: u32,
    _total_bytes: u64,
    logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
    on_progress: Box<dyn Fn(&str, &BatchItem, &str) + Send + Sync>,
    password: String,
    cancel: AtomicBool,
    done: AtomicBool,
    succeeded: Mutex<u32>,
    failed: Mutex<u32>,
    skipped: Mutex<u32>,
    cancelled: Mutex<u32>,
    needs_install: Mutex<u32>,
    written: Mutex<u64>,
    started_at: Mutex<Option<Instant>>,
    finished_at: Mutex<Option<Instant>>,
}

impl BatchExtractJob {
    /// Creates a job from a plan. Consumes the plan so items can be mutated in place during the run.
    pub fn new(
        plan: BatchPlan,
        logger: Arc<dyn Fn(&str, &str) + Send + Sync>,
        on_progress: Option<Box<dyn Fn(&str, &BatchItem, &str) + Send + Sync>>,
        password: &str,
    ) -> Self {
        let BatchPlan {
            items,
            destination,
            category,
            already_done,
            total_bytes,
        } = plan;
        BatchExtractJob {
            items: items.into_iter().map(Mutex::new).collect(),
            destination,
            category,
            _already_done: already_done,
            _total_bytes: total_bytes,
            logger,
            on_progress: on_progress.unwrap_or_else(|| Box::new(|_, _, _| {})),
            password: password.to_string(),
            cancel: AtomicBool::new(false),
            done: AtomicBool::new(false),
            succeeded: Mutex::new(0),
            failed: Mutex::new(0),
            skipped: Mutex::new(0),
            cancelled: Mutex::new(0),
            needs_install: Mutex::new(0),
            written: Mutex::new(0),
            started_at: Mutex::new(None),
            finished_at: Mutex::new(None),
        }
    }

    /// Ask the run to stop. Takes effect on the next tool output line, or between games.
    pub fn cancel(&self) {
        self.cancel.store(true, Ordering::SeqCst);
    }

    /// True when a cancel has been requested.
    pub fn cancel_requested(&self) -> bool {
        self.cancel.load(Ordering::SeqCst)
    }

    /// Count of items not yet finished (done/failed/skipped/cancelled).
    pub fn remaining(&self) -> u32 {
        self.items
            .iter()
            .filter(|item| !item.lock().unwrap().finished())
            .count() as u32
    }

    fn emit(&self, stage: &str, item: Option<&BatchItem>, detail: &str) {
        // A progress callback that raises must not take the run down with it; the window is a readout,
        // and losing the readout is not a reason to lose the extraction.
        if let Some(item) = item {
            let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                (self.on_progress)(stage, item, detail);
            }));
        }
    }

    /// The whole queue. Returns true when every game that ran succeeded.
    pub fn run(&self) -> bool {
        *self.started_at.lock().unwrap() = Some(Instant::now());
        (self.logger)(
            "BATCH",
            &format!(
                "START dest=[{}] games=[{}] category=[{}]",
                self.destination.display(),
                self.items.len(),
                self.category
            ),
        );
        if self.items.is_empty() {
            *self.finished_at.lock().unwrap() = Some(Instant::now());
            self.done.store(true, Ordering::SeqCst);
            self.emit("finished", None, "");
            return true;
        }

        let total = self.items.len();
        let logger = self.logger.clone();
        let extract_service = ExtractService::new(Some(Box::new(move |c, m| {
            (logger)(c, m);
        })));

        for (index, item_mutex) in self.items.iter().enumerate() {
            if self.cancel_requested() {
                let mut item = item_mutex.lock().unwrap();
                item.state = CANCELLED.to_string();
                item.detail = "not started".to_string();
                let item_ref = &*item;
                *self.cancelled.lock().unwrap() += 1;
                self.emit("item", Some(item_ref), "");
                continue;
            }

            {
                let mut item = item_mutex.lock().unwrap();
                item.state = EXTRACTING.to_string();
                item.percent = 0;
                let item_ref = &*item;
                self.emit("item", Some(item_ref), &format!("{} of {}", index + 1, total));
            }

            let archive = {
                let item = item_mutex.lock().unwrap();
                item.archive.clone()
            };
            let destination = {
                let item = item_mutex.lock().unwrap();
                item.destination.clone()
            };
            let name = {
                let item = item_mutex.lock().unwrap();
                item.name.clone()
            };
            let suffix = archive
                .as_ref()
                .and_then(|p| p.extension().map(|e| e.to_string_lossy().to_string()))
                .unwrap_or_default();

            let result = extract_service.extract(
                archive.as_deref().unwrap_or(Path::new("")),
                destination.as_deref().unwrap_or(Path::new("")),
                &suffix,
                &self.password,
            );

            if self.cancel_requested() {
                let mut item = item_mutex.lock().unwrap();
                item.state = CANCELLED.to_string();
                item.detail = "cancelled".to_string();
                let item_ref = &*item;
                *self.cancelled.lock().unwrap() += 1;
                self.emit("item", Some(item_ref), "");
                continue;
            }

            match result.ok {
                true => {
                    let mut item = item_mutex.lock().unwrap();
                    item.state = DONE.to_string();
                    item.detail = format!(
                        "{} files, {}",
                        result.file_count,
                        human_size(Some(result.extracted_bytes as f64))
                    );
                    if result.needs_install {
                        item.detail.push_str(" — installer, needs install");
                        *self.needs_install.lock().unwrap() += 1;
                    }
                    *self.succeeded.lock().unwrap() += 1;
                    let item_ref = &*item;
                    self.emit("item", Some(item_ref), "");
                }
                false => {
                    if self.cancel_requested() {
                        let mut item = item_mutex.lock().unwrap();
                        item.state = CANCELLED.to_string();
                        item.detail = result.message.clone();
                        let item_ref = &*item;
                        *self.cancelled.lock().unwrap() += 1;
                        self.emit("item", Some(item_ref), "");
                    } else {
                        let mut item = item_mutex.lock().unwrap();
                        item.state = FAILED.to_string();
                        item.detail = result.message.clone();
                        let item_ref = &*item;
                        *self.failed.lock().unwrap() += 1;
                        (self.logger)(
                            "BATCH",
                            &format!(
                                "ITEM_FAILED name=[{}] reason=[{}]",
                                name,
                                result.message.chars().take(200).collect::<String>()
                            ),
                        );
                        self.emit("item", Some(item_ref), "");
                    }
                }
            }

            *self.written.lock().unwrap() += result.extracted_bytes;
        }

        // Everything still queued when the run ends was never reached, which is only possible after a cancel.
        for item_mutex in self.items.iter() {
            let mut item = item_mutex.lock().unwrap();
            if item.state == QUEUED {
                item.state = CANCELLED.to_string();
                item.detail = "not started".to_string();
                let item_ref = &*item;
                *self.cancelled.lock().unwrap() += 1;
                self.emit("item", Some(item_ref), "");
            }
        }

        *self.finished_at.lock().unwrap() = Some(Instant::now());
        let started = self.started_at.lock().unwrap().unwrap();
        let finished = self.finished_at.lock().unwrap().unwrap();
        let seconds = finished.duration_since(started).as_secs();
        let succeeded = *self.succeeded.lock().unwrap();
        let failed = *self.failed.lock().unwrap();
        let skipped = *self.skipped.lock().unwrap();
        let cancelled = *self.cancelled.lock().unwrap();
        (self.logger)(
            "BATCH",
            &format!(
                "FINISH ok=[{}] failed=[{}] skipped=[{}] cancelled=[{}] seconds=[{}]",
                succeeded, failed, skipped, cancelled, seconds
            ),
        );
        self.done.store(true, Ordering::SeqCst);
        self.emit("finished", None, "");
        failed == 0 && cancelled == 0
    }

    /// One sentence a person can act on, for the window and for the log.
    pub fn summary(&self) -> String {
        let finished_at_guard = self.finished_at.lock().unwrap();
        let end = finished_at_guard.unwrap_or_else(Instant::now);
        drop(finished_at_guard);

        let started_at_guard = self.started_at.lock().unwrap();
        let elapsed = if let Some(s) = started_at_guard.as_ref() {
            format!("{}s", end.duration_since(*s).as_secs())
        } else {
            "0s".to_string()
        };
        drop(started_at_guard);

        let succeeded = *self.succeeded.lock().unwrap();
        let skipped = *self.skipped.lock().unwrap();
        let failed = *self.failed.lock().unwrap();
        let cancelled = *self.cancelled.lock().unwrap();
        let needs_install = *self.needs_install.lock().unwrap();
        let written = *self.written.lock().unwrap();

        let mut parts = Vec::new();
        parts.push(format!("{} extracted", succeeded));
        if skipped > 0 {
            parts.push(format!("{} already there", skipped));
        }
        if failed > 0 {
            parts.push(format!("{} failed", failed));
        }
        if cancelled > 0 {
            parts.push(format!("{} not done", cancelled));
        }
        if needs_install > 0 {
            parts.push(format!("{} need install", needs_install));
        }
        let written = human_size(Some(written as f64));
        format!("{} in {}  •  {} unpacked", parts.join(", "), elapsed, written)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dummy_logger(_: &str, _: &str) {}

    #[test]
    fn test_batch_extract_job_empty_plan() {
        let plan = BatchPlan::new(Path::new("/dest"), "Action");
        let job = BatchExtractJob::new(plan, Arc::new(dummy_logger), None, "");
        assert!(job.run());
        assert!(job.done.load(Ordering::SeqCst));
    }

    #[test]
    fn test_batch_extract_job_remaining() {
        let plan = BatchPlan::new(Path::new("/dest"), "Action");
        let job = BatchExtractJob::new(plan, Arc::new(dummy_logger), None, "");
        assert_eq!(job.remaining(), 0);
    }

    #[test]
    fn test_batch_extract_job_cancel() {
        let plan = BatchPlan::new(Path::new("/dest"), "Action");
        let job = BatchExtractJob::new(plan, Arc::new(dummy_logger), None, "");
        job.cancel();
        assert!(job.cancel_requested());
    }
}

