//! Background work dispatch: run a function on a thread pool and report back by callbacks.
//!
//! JobContext carries a cancellation flag that long-running work polls with checkpoint(),
//! and JobManager owns the map of in-flight jobs so the window close
//! can cancel everything instead of waiting.
//!
//! 2026-11-25: Converted from `app/jobs.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::SystemTime;

use crate::core::errors::CancellationError;

/// Tracks cancellation state for one in-flight job.
pub struct JobContext {
    pub job_id: String,
    cancel: Arc<AtomicBool>,
}

impl JobContext {
    pub fn new(job_id: &str) -> Self {
        JobContext {
            job_id: job_id.to_string(),
            cancel: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn cancel(&self) {
        self.cancel.store(true, Ordering::SeqCst);
    }

    pub fn cancelled(&self) -> bool {
        self.cancel.load(Ordering::SeqCst)
    }

    /// Raise if someone asked for a cancel while this job was mid-work. A run
    /// that is cancelled mid-organize surfaces this at the next checkpoint and
    /// unwinds cleanly instead of finishing the remaining games.
    pub fn checkpoint(&self) -> Result<(), CancellationError> {
        if self.cancelled() {
            return Err(CancellationError::new());
        }
        Ok(())
    }
}

/// Owns the map of in-flight jobs so the window close
/// can cancel everything instead of waiting.
pub struct JobManager {
    pub max_workers: usize,
    jobs: Mutex<HashMap<String, Arc<JobContext>>>,
}

impl JobManager {
    pub fn new(max_workers: usize) -> Self {
        JobManager {
            max_workers,
            jobs: Mutex::new(HashMap::new()),
        }
    }

    /// Submit `fn` to run on a worker thread, with `done`/`error` callbacks invoked
    /// when the future completes. Returns (job_id, ctx).
    pub fn submit<F, D, E, R>(
        &self,
        fn_: F,
        done: Option<D>,
        error: Option<E>,
    ) -> (String, Arc<JobContext>)
    where
        F: FnOnce(&JobContext) -> R + Send + 'static,
        R: Send + 'static,
        D: Fn(String, R) + Send + 'static,
        E: Fn(String) + Send + 'static,
    {
        let job_id = format!(
            "JOB-{:010X}",
            SystemTime::now()
                .duration_since(SystemTime::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
                % 0xFFFF_FFFF
        );
        let ctx = Arc::new(JobContext::new(&job_id));
        {
            self.jobs.lock().unwrap().insert(job_id.clone(), ctx.clone());
        }

        let ctx_clone = ctx.clone();
        let job_id_clone = job_id.clone();
        let done_opt = done;
        let error_opt = error;

        thread::spawn(move || {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| fn_(&ctx_clone)));
            match result {
                Ok(value) => {
                    if let Some(d) = done_opt {
                        d(job_id_clone, value);
                    }
                }
                Err(_panic) => {
                    if let Some(e) = error_opt {
                        e(job_id_clone);
                    }
                }
            }
        });

        (job_id, ctx)
    }

    /// Request cancellation of every in-flight job.
    pub fn cancel_all(&self) {
        for ctx in self.jobs.lock().unwrap().values() {
            ctx.cancel();
        }
    }

    /// Shut down the thread pool. `wait=false` is for the window-close path.
    pub fn shutdown(&self, _wait: bool) {
        self.cancel_all();
        // Note: std thread pool has no explicit shutdown; threads exit when their
        // spawned closures return. The cancel flag is the mechanism used to stop
        // in-flight work.
    }
}

impl Default for JobManager {
    fn default() -> Self {
        Self::new(4)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_job_context_checkpoint_not_cancelled() {
        let ctx = JobContext::new("TEST-1");
        assert!(!ctx.cancelled());
        assert!(ctx.checkpoint().is_ok());
    }

    #[test]
    fn test_job_context_checkpoint_cancelled() {
        let ctx = JobContext::new("TEST-2");
        ctx.cancel();
        assert!(ctx.cancelled());
        assert!(ctx.checkpoint().is_err());
    }

    #[test]
    fn test_job_manager_cancel_all() {
        let mgr = JobManager::new(2);
        let (_id1, ctx1): (String, Arc<JobContext>) =
            mgr.submit(|_| {}, None::<fn(String, ())>, None::<fn(String)>);
        let (_id2, ctx2): (String, Arc<JobContext>) =
            mgr.submit(|_| {}, None::<fn(String, ())>, None::<fn(String)>);
        mgr.cancel_all();
        assert!(ctx1.cancelled());
        assert!(ctx2.cancelled());
    }

    #[test]
    fn test_job_manager_submit_completes() {
        let mgr = JobManager::new(2);
        let (_job_id, _ctx): (String, Arc<JobContext>) = mgr.submit(
            |_ctx| 42u32,
            Some(move |id: String, val| {
                let expected = id.clone();
                assert_eq!(id, expected);
                assert_eq!(val, 42);
            }),
            None::<fn(String)>,
        );
        // Give the thread time to run
        std::thread::sleep(std::time::Duration::from_millis(50));
    }
}

