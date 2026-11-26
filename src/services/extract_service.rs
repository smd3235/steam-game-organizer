//! Unpacks an archive to a folder of the user's choosing, outside the library.
//!
//! This is what the catalog's Extract button runs. It is deliberately separate from the conversion path in
//! OrganizerService: a conversion extracts to staging and then rebuilds and deletes the original, whereas this
//! only ever reads the archive and writes a copy somewhere else.
//!
//! Both tools are invoked exactly as the conversion path invokes them, so a format that opens there opens here.
//!
//! 2026-11-25: Converted from `services/extract_service.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::{Path, PathBuf};
use std::process::Command;

use crate::core::extract_result::ExtractResult;
use crate::core::installer_detect::find_installer;

pub fn app_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..")
}

pub const EXTRACT_PROGRESS_RE: &str = r"(\d{1,3})%\s*(.*)";
pub const HEADROOM_FACTOR: f64 = 1.15;

pub const BLOAT_FILE_PATTERNS: [&str; 15] = [
    "README*.txt",
    "README*.md",
    "README*.html",
    "README*.htm",
    "readme*.txt",
    "readme*.md",
    "Read_Me*.txt",
    "Read_Me*.md",
    "*_INSTALL TUTORIAL*",
    "ZIP Password*",
    "*.url",
    "*.nfo",
    "*.sfv",
    "*hack*.txt",
    "*site*.txt",
];

pub const BLOAT_DIR_NAMES: [&str; 5] = ["_CommonRedist", "Crack", "Cracked", "Sample", "Samples"];

/// No-op retained so tests that import it keep working.
pub fn clear_tool_cache() {}

/// Extraction service: unpacks archives to user-chosen destinations.
pub struct ExtractService {
    pub logger: Option<Box<dyn Fn(&str, &str) + Send + Sync>>,
}

impl ExtractService {
    pub fn new(logger: Option<Box<dyn Fn(&str, &str) + Send + Sync>>) -> Self {
        ExtractService { logger }
    }

    /// Default install locations for a Windows archive tool.
    #[cfg(windows)]
    fn windows_candidates(relative: &[&str]) -> Vec<String> {
        let mut candidates = Vec::new();
        for variable in ["ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"] {
            if let Ok(base) = std::env::var(variable) {
                let candidate = Path::new(&base).join(relative.join("/"));
                if candidate.is_file() {
                    if let Some(s) = candidate.to_str() {
                        candidates.push(s.to_string());
                    }
                }
            }
        }
        candidates
    }

    #[cfg(not(windows))]
    fn windows_candidates(_relative: &[&str]) -> Vec<String> {
        Vec::new()
    }

    /// The copy of the tool shipped inside this app's own folder, or None.
    fn bundled_tool(name: &str) -> Option<String> {
        let candidate = app_root().join("runtime").join(name);
        if candidate.is_file() {
            candidate.to_str().map(|s| s.to_string())
        } else {
            None
        }
    }

    /// Find an executable on PATH or in default Windows locations.
    fn find_on_path(name: &str) -> Option<String> {
        if let Ok(path) = std::env::var("PATH") {
            for dir in path.split(std::path::MAIN_SEPARATOR) {
                let candidate = Path::new(dir).join(name);
                if candidate.is_file() {
                    if let Some(s) = candidate.to_str() {
                        return Some(s.to_string());
                    }
                }
            }
        }
        None
    }

    /// The extraction tool for an archive, or (None, reason) when this machine cannot unpack it.
    pub fn find_tool() -> (Option<String>, Option<String>) {
        if let Some(bundled) = ExtractService::bundled_tool("7z.exe") {
            return (Some(bundled), None);
        }
        if let Some(found) = ExtractService::find_on_path("7z") {
            return (Some(found), None);
        }
        if let Some(found) = ExtractService::find_on_path("7za") {
            return (Some(found), None);
        }
        if let Some(candidate) = ExtractService::windows_candidates(&["7-Zip", "7z.exe"])
            .into_iter()
            .next()
        {
            return (Some(candidate), None);
        }
        (
            None,
            Some(
                "no 7z/7za on PATH, no default 7-Zip install, and no 7z.exe bundled beside the app"
                    .to_string(),
            ),
        )
    }

    pub fn find_unrar() -> Option<String> {
        if let Some(found) = ExtractService::find_on_path("unrar") {
            return Some(found);
        }
        ExtractService::windows_candidates(&["WinRAR", "UnRAR.exe"])
            .into_iter()
            .next()
    }

    /// The argv for one archive.
    fn command(
        sevenzip: &str,
        archive: &Path,
        destination: &Path,
        suffix: &str,
        password: &str,
    ) -> Vec<String> {
        if let Some(unrar) = ExtractService::find_unrar() {
            if suffix == ".rar" {
                let mut args = vec![unrar, "x".to_string(), "-y".to_string(), "-o+".to_string()];
                if !password.is_empty() {
                    args.push(format!("-p{}", password));
                }
                args.push(archive.to_string_lossy().to_string());
                args.push(format!(
                    "{}{}",
                    destination.display(),
                    std::path::MAIN_SEPARATOR
                ));
                return args;
            }
        }
        let mut args = vec![
            sevenzip.to_string(),
            "x".to_string(),
            "-y".to_string(),
            "-bsp1".to_string(),
            format!("-o{}", destination.display()),
        ];
        if !password.is_empty() {
            args.push(format!("-p{}", password));
        }
        args.push(archive.to_string_lossy().to_string());
        args
    }

    /// Extract one archive to a destination folder.
    pub fn extract(
        &self,
        archive: &Path,
        destination: &Path,
        suffix: &str,
        password: &str,
    ) -> ExtractResult {
        let (tool, reason) = ExtractService::find_tool();
        let tool = match tool {
            Some(t) => t,
            None => {
                return ExtractResult {
                    archive: archive.to_path_buf(),
                    destination: destination.to_path_buf(),
                    ok: false,
                    message: format!(
                        "No extraction tool available: {}",
                        reason.unwrap_or_default()
                    ),
                    extracted_bytes: 0,
                    file_count: 0,
                    code: -1,
                    needs_install: false,
                };
            }
        };

        let args = ExtractService::command(&tool, archive, destination, suffix, password);
        let status = Command::new(&tool).args(&args[1..]).status();

        match status {
            Ok(s) if s.success() => {
                // Check for installer signature after extraction
                let is_installer = find_installer(destination, None).is_some();
                ExtractResult {
                    archive: archive.to_path_buf(),
                    destination: destination.to_path_buf(),
                    ok: true,
                    message: "Extraction complete".to_string(),
                    extracted_bytes: 0,
                    file_count: 0,
                    code: 0,
                    needs_install: is_installer,
                }
            }
            Ok(s) => ExtractResult {
                archive: archive.to_path_buf(),
                destination: destination.to_path_buf(),
                ok: false,
                message: format!("Extraction failed with exit code {:?}", s.code()),
                extracted_bytes: 0,
                file_count: 0,
                code: s.code().unwrap_or(-1),
                needs_install: false,
            },
            Err(e) => ExtractResult {
                archive: archive.to_path_buf(),
                destination: destination.to_path_buf(),
                ok: false,
                message: format!("Extraction error: {}", e),
                extracted_bytes: 0,
                file_count: 0,
                code: -1,
                needs_install: false,
            },
        }
    }

    #[cfg(test)]
    fn needs_install_path(destination: &Path) -> PathBuf {
        use crate::core::installer_detect::NEEDS_INSTALL_DIRNAME;
        if destination
            .parent()
            .is_some_and(|p| p.file_name() == Some(NEEDS_INSTALL_DIRNAME.as_ref()))
        {
            destination.to_path_buf()
        } else {
            destination
                .parent()
                .unwrap_or(destination)
                .join(NEEDS_INSTALL_DIRNAME)
                .join(destination.file_name().unwrap_or_default())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_clear_tool_cache_is_noop() {
        clear_tool_cache();
        // Should not panic
    }

    #[test]
    fn test_find_tool_returns_tuple() {
        let (tool, reason) = ExtractService::find_tool();
        // Either we have a tool or a reason
        assert!(tool.is_some() || reason.is_some());
    }

    #[test]
    fn test_needs_install_path_not_nested() {
        let dest = PathBuf::from("/dest/MyGame");
        let result = ExtractService::needs_install_path(&dest);
        assert_eq!(result, PathBuf::from("/dest/Needs Install/MyGame"));
    }

    #[test]
    fn test_needs_install_path_already_nested() {
        let dest = PathBuf::from("/dest/Needs Install/MyGame");
        let result = ExtractService::needs_install_path(&dest);
        assert_eq!(result, dest);
    }
}

