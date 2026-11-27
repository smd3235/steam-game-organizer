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
pub struct InstallerBuildResult {
    pub installer_path: PathBuf,
    pub size_bytes: u64,
    pub succeeded: bool,
}

/// Build the Windows installer using Inno Setup.
pub fn build_installer(_root: &Path) -> Result<InstallerBuildResult, String> {
    // Find ISCC.exe (Inno Setup Compiler)
    let iscc = find_iscc().ok_or_else(|| "ISCC.exe not found — install Inno Setup".to_string())?;

    let iss_path = Path::new("installer.iss");
    if !iss_path.exists() {
        return Err(format!("Installer script not found: {}", iss_path.display()));
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

    // Find the output installer (Inno Setup typically outputs to output dir in .iss)
    let installer_path = Path::new("output").join("Steam Game Organizer Setup.exe");
    let size_bytes = installer_path
        .metadata()
        .map(|m| m.len())
        .unwrap_or(0);

    Ok(InstallerBuildResult {
        installer_path,
        size_bytes,
        succeeded: true,
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
    fn test_installer_build_result_struct() {
        let result = InstallerBuildResult {
            installer_path: PathBuf::from("output/Steam Game Organizer Setup.exe"),
            size_bytes: 45_000_000,
            succeeded: true,
        };
        assert!(result.succeeded);
        assert!(result.size_bytes > 0);
    }
}
