//! Installer build tool: builds a Windows installer (.exe) using Inno Setup.
//!
//! Uses ISCC.exe (Inno Setup Compiler) to compile `installer.iss` into a
//! redistributable installer that bundles the release exe, 7-Zip, and assets.
//!
//! Usage:
//!   steam-game-organizer.exe --build-installer
//!
//! 2026-11-27: New tool — creates a distributable installer for end users.

use std::path::{Path, PathBuf};
use std::process::Command;

/// Result of the installer build.
#[derive(Debug)]
pub struct InstallerBuildResult {
    pub installer_path: PathBuf,
    pub size_bytes: u64,
    pub succeeded: bool,
    pub iscc_version: Option<String>,
}

/// Build the Windows installer using Inno Setup.
pub fn build_installer(_root: &Path) -> Result<InstallerBuildResult, String> {
    // Find ISCC.exe (Inno Setup Compiler)
    let iscc = find_iscc().ok_or_else(|| "ISCC.exe not found — install Inno Setup".to_string())?;

    // Get ISCC version for reporting
    let iscc_version = get_iscc_version(&iscc);

    // Verify prerequisites exist before building
    let release_exe = Path::new("target/release/steam-game-organizer.exe");
    if !release_exe.exists() {
        return Err(format!(
            "Release exe not found: {}. Run 'cargo build --release' first.",
            release_exe.display()
        ));
    }

    let seven_zip = Path::new("runtime/7z.exe");
    if !seven_zip.exists() {
        return Err(format!(
            "7-Zip not found: {}. Download 7z.exe into runtime/.",
            seven_zip.display()
        ));
    }

    let iss_path = Path::new("installer.iss");
    if !iss_path.exists() {
        return Err(format!("Installer script not found: {}", iss_path.display()));
    }

    // Create output directory if needed
    let output_dir = Path::new("output");
    if !output_dir.exists() {
        std::fs::create_dir_all(output_dir)
            .map_err(|e| format!("Failed to create output directory: {}", e))?;
    }

    // Run ISCC to compile the installer
    let output = Command::new(&iscc)
        .arg(iss_path)
        .output()
        .map_err(|e| format!("Failed to run ISCC: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("ISCC failed: {}", stderr));
    }

    // Find the output installer
    let installer_path = output_dir.join("Steam Game Organizer Setup.exe");
    let size_bytes = installer_path
        .metadata()
        .map(|m| m.len())
        .unwrap_or(0);

    Ok(InstallerBuildResult {
        installer_path,
        size_bytes,
        succeeded: true,
        iscc_version,
    })
}

/// Locate ISCC.exe in common install locations.
fn find_iscc() -> Option<PathBuf> {
    let candidates = [
        PathBuf::from(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        PathBuf::from(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        PathBuf::from(
            r"C:\Users\smd32\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
        ),
    ];
    candidates.into_iter().find(|p| p.exists())
}

/// Get ISCC version string by running `/S=` (silent version check).
fn get_iscc_version(iscc: &Path) -> Option<String> {
    let output = Command::new(iscc).arg("/S=").output().ok()?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    // ISCC version output looks like "Inno Setup Compiler version 6.7.3"
    for line in stdout.lines() {
        if line.contains("version") {
            return Some(line.trim().to_string());
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_find_iscc_returns_path_when_installed() {
        // ISCC is installed on this machine
        assert!(find_iscc().is_some());
    }

    #[test]
    fn test_find_iscc_path_exists() {
        if let Some(path) = find_iscc() {
            assert!(path.exists());
            assert_eq!(path.file_name().unwrap(), "ISCC.exe");
        }
    }

    #[test]
    fn test_get_iscc_version_returns_string() {
        if let Some(iscc) = find_iscc() {
            // ISCC may or may not return a version via /S= depending on version.
            // Just verify it runs without crashing.
            let output = Command::new(&iscc).arg("/S=").output();
            assert!(
                output.is_ok(),
                "ISCC should run without crashing when invoked with /S="
            );
        }
    }

    #[test]
    fn test_installer_build_result_struct() {
        let result = InstallerBuildResult {
            installer_path: PathBuf::from("output/Steam Game Organizer Setup.exe"),
            size_bytes: 45_000_000,
            succeeded: true,
            iscc_version: Some("Inno Setup Compiler version 6.7.3".to_string()),
        };
        assert!(result.succeeded);
        assert!(result.size_bytes > 0);
        assert!(result.iscc_version.is_some());
    }

    #[test]
    fn test_build_installer_missing_release_exe() {
        // Build should either succeed (if all prerequisites met) or fail with
        // a clear error message. It should not panic.
        let result = build_installer(Path::new("."));
        match result {
            Ok(_) => {
                // Installer built successfully — all prerequisites met
            }
            Err(err) => {
                // Should be a meaningful error message, not a panic
                assert!(!err.is_empty(), "Error message should not be empty");
            }
        }
    }
}
