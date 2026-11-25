//! Opening a folder or a URL in whatever the desktop has been told to use for it.
//!
//! Both functions return whether anything was launched. They never raise: a button that cannot do its job
//! should say so, not take the window down with it.
//!
//! This app runs on Windows. Refusing off-platform is honest: the alternative was launching nothing and
//! reporting success.
//!
//! 2026-11-24: Converted from `utils/desktop.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::process::Command;

/// Show `path` in the desktop's file manager. Returns whether anything was launched.
pub fn open_folder(path: &str) -> bool {
    let target = std::path::Path::new(path);
    if !target.is_dir() {
        return false;
    }

    // os.startfile equivalent on Windows: use `explorer` or `rundll32`
    if Command::new("explorer")
        .arg(path)
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
    {
        return true;
    }
    if Command::new("rundll32")
        .args(["url.dll,FileProtocolHandler", path])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
    {
        return true;
    }
    false
}

/// Hand `url` to the default browser. Returns whether anything was launched.
pub fn open_url(url: &str) -> bool {
    if !open_url_validates(url) {
        return false;
    }
    // Use `start` command which invokes the shell association
    Command::new("cmd")
        .args(["/c", "start", "", url])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Validate that `url` is a scheme we are willing to hand to the desktop.
/// Never launches anything — safe to call in tests.
pub fn open_url_validates(url: &str) -> bool {
    if url.trim().is_empty() {
        return false;
    }
    let lower = url.to_lowercase();
    lower.starts_with("http://")
        || lower.starts_with("https://")
        || lower.starts_with("file://")
        || lower.starts_with("mailto:")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_open_url_invalid() {
        assert!(!open_url_validates(""));
        assert!(!open_url_validates("not-a-url"));
        assert!(!open_url_validates("ftp://example.com"));
    }

    #[test]
    fn test_open_url_valid() {
        assert!(open_url_validates("http://example.com"));
        assert!(open_url_validates("https://example.com"));
    }
}
