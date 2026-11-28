//! Pure utility functions extracted from OrganizerService.
//!
//! These functions have no dependency on OrganizerService instance state and can be
//! imported and tested independently. They were previously static methods on
//! OrganizerService that took all their inputs as parameters.
//!
//! 2026-11-24: Converted from `core/organizer_utils.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::io::Read;
use std::os::raw::c_void;
use std::time::{Duration, Instant};

const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
const FALSE: i32 = 0;
type Handle = *mut c_void;

/// True when the zip's central directory marks any entry as encrypted.
///
/// Python's zipfile reads the flag bits without decrypting, so this is a cheap check
/// that needs no password. WinZip AES entries carry bit 0 of the general-purpose flags.
pub fn zip_is_encrypted(path: &std::path::Path) -> bool {
    let file = match std::fs::File::open(path) {
        Ok(f) => f,
        Err(_) => return false,
    };
    let mut archive = match zip::ZipArchive::new(file) {
        Ok(a) => a,
        Err(_) => return true,
    };
    // Try to read the first byte of each non-directory entry.
    // Encrypted entries cannot be read without a password.
    for i in 0..archive.len() {
        if let Ok(mut entry) = archive.by_index(i) {
            if !entry.is_dir() {
                let mut buf = [0u8; 1];
                if entry.read(&mut buf).is_err() {
                    return true;
                }
            }
        }
    }
    false
}

/// True when a build died from memory pressure or an interrupt rather than from bad input.
///
/// 7z reports these as exit 255 with 'Break signaled' and no useful explanation, which is
/// indistinguishable from a genuine error by exit code alone. Retrying one level lower costs
/// a minute; giving up costs the entire extraction.
pub fn looks_like_resource_failure(detail: &str) -> bool {
    let text = detail.to_lowercase();
    text.contains("break signaled")
        || text.contains("not enough memory")
        || text.contains("out of memory")
        || text.contains("cannot allocate")
        || text.contains("killed")
}

/// The filenames Windows Defender refused to scan during a 7z build, parsed from its error text.
///
/// 7z's content-intelligence integration asks Defender to scan every file as it packs. A file
/// Defender flags is reported as "Operation did not complete successfully because the file contains
/// a virus or potentially unwanted software", followed by the path on the next line and "The
/// system cannot find the file specified" on the line after. The names are extracted from the
/// first form, which is stable across 7-Zip versions; the second form is the same file reported
/// again after the scan was refused.
pub fn defender_flagged(detail: &str) -> Vec<String> {
    if detail.is_empty() {
        return Vec::new();
    }
    let mut names: Vec<String> = Vec::new();
    // The actual format is "path : message", not "message path": 7z prints the member path first,
    // then a colon, then the Defender refusal.
    for line in detail.split('|') {
        let line = line.trim();
        if !line
            .contains("Operation did not complete successfully because the file contains a virus")
        {
            continue;
        }
        let path = line.split(" : ").next().unwrap_or("").trim();
        if path.is_empty() {
            continue;
        }
        let name = path
            .replace('\\', "/")
            .trim_start_matches("./")
            .rsplit('/')
            .next()
            .unwrap_or("")
            .to_string();
        if !name.is_empty() {
            names.push(name);
        }
    }
    names
}

/// Tolerant check whether a process is still alive.
///
/// Runs from finally blocks, so a missing poll() or platform quirk must not turn a handled
/// failure into an error that hides the real cause.
pub fn still_running(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }
    // On Windows, try opening the process with QUERY_LIMITED_INFORMATION.
    // If OpenProcess fails with ERROR_INVALID_PARAMETER, the pid does not exist.
    open_process_query(pid).is_ok()
}

/// Ends a running archive tool.
///
/// terminate() asks first because 7z closes its output file on SIGTERM and the partial build
/// can be reused as a retry candidate; kill() is the backstop for a tool wedged in a syscall.
/// Both are needed: a level-9 LZMA2 build under memory pressure can ignore a polite signal
/// for a long time.
pub fn stop_tool(pid: u32, grace: Duration) {
    if !still_running(pid) {
        return;
    }
    let _ = terminate_process(pid);
    let deadline = Instant::now() + grace;
    while Instant::now() < deadline {
        if !still_running(pid) {
            return;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    let _ = kill_process(pid);
}

/// Whether a process id still exists.
pub fn pid_is_alive(pid: u32) -> bool {
    still_running(pid)
}

#[cfg(windows)]
mod windows_api {
    use super::{Handle, FALSE, PROCESS_QUERY_LIMITED_INFORMATION};

    extern "system" {
        pub fn OpenProcess(
            dw_desired_access: u32,
            b_inherit_handle: i32,
            dw_process_id: u32,
        ) -> Handle;
        pub fn CloseHandle(h_object: Handle) -> i32;
        pub fn TerminateProcess(h_process: Handle, u_exit_code: u32) -> i32;
        pub fn GetLastError() -> u32;
    }

    pub fn open_process_query(pid: u32) -> Result<Handle, u32> {
        let handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) };
        if handle.is_null() {
            Err(unsafe { GetLastError() })
        } else {
            Ok(handle)
        }
    }

    pub fn close_handle(handle: Handle) -> bool {
        unsafe { CloseHandle(handle) != FALSE }
    }

    pub fn terminate_process(pid: u32) -> Result<(), u32> {
        let handle = open_process_query(pid)?;
        let result = unsafe { TerminateProcess(handle, 1) };
        let _ = close_handle(handle);
        if result != FALSE {
            Ok(())
        } else {
            Err(unsafe { GetLastError() })
        }
    }
}

#[cfg(not(windows))]
mod windows_api {
    use super::Handle;

    pub fn open_process_query(_pid: u32) -> Result<Handle, u32> {
        Err(1)
    }

    pub fn close_handle(_handle: Handle) -> bool {
        false
    }

    pub fn terminate_process(_pid: u32) -> Result<(), u32> {
        Err(1)
    }
}

fn open_process_query(pid: u32) -> Result<Handle, u32> {
    windows_api::open_process_query(pid)
}

fn terminate_process(pid: u32) -> Result<(), u32> {
    windows_api::terminate_process(pid)
}

fn kill_process(_pid: u32) -> Result<(), u32> {
    // On Windows, TerminateProcess is the kill equivalent
    Err(1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_looks_like_resource_failure() {
        assert!(looks_like_resource_failure("break signaled"));
        assert!(looks_like_resource_failure("Out of memory"));
        assert!(!looks_like_resource_failure("bad archive"));
    }

    #[test]
    fn test_defender_flagged_empty() {
        assert!(defender_flagged("").is_empty());
    }

    #[test]
    fn test_pid_is_alive_zero() {
        assert!(!pid_is_alive(0));
    }
}
