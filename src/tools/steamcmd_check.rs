//! SteamCMD integration tool: verifies Steam client availability and queries
//! Steam app info for match verification and testing.
//!
//! Usage:
//!   steam-game-organizer.exe --steamcmd-check
//!
//! 2026-11-27: New tool — verifies Steam is installed and can query app
//! manifests for Steam match testing.

use std::path::{Path, PathBuf};
use std::process::Command;

/// Result of the SteamCMD check.
pub struct SteamCmdResult {
    pub steamcmd_found: bool,
    pub steamcmd_version: Option<String>,
    pub steam_installed: bool,
    pub appinfo_query_working: bool,
    pub steam_library_path: Option<String>,
    pub steam_exe_path: Option<PathBuf>,
}

/// Check SteamCMD availability and Steam installation status.
pub fn check_steamcmd(_root: &Path) -> Result<SteamCmdResult, String> {
    let steamcmd = find_steamcmd().ok_or_else(|| "steamcmd.exe not found — install SteamCMD".to_string())?;

    // Verify steamcmd runs and get version
    let output = Command::new(&steamcmd)
        .args(["+quit"])
        .output()
        .map_err(|e| format!("Failed to run steamcmd: {}", e))?;

    let steamcmd_found = output.status.success();
    let steamcmd_version = if steamcmd_found {
        get_steamcmd_version(&steamcmd)
    } else {
        None
    };

    // Check for Steam installation via common paths
    let (steam_installed, steam_exe_path, steam_library_path) = detect_steam();

    // Test appinfo query (basic connectivity test)
    let appinfo_query_working = if steam_installed {
        test_appinfo_query(&steamcmd)?
    } else {
        false
    };

    Ok(SteamCmdResult {
        steamcmd_found,
        steamcmd_version,
        steam_installed,
        appinfo_query_working,
        steam_library_path,
        steam_exe_path,
    })
}

/// Find steamcmd.exe in PATH or common locations.
fn find_steamcmd() -> Option<std::path::PathBuf> {
    // Try PATH first
    if let Ok(output) = Command::new("where").arg("steamcmd").output() {
        if output.status.success() {
            let stdout = String::from_utf8_lossy(&output.stdout);
            for line in stdout.lines() {
                let trimmed = line.trim();
                if !trimmed.is_empty() {
                    return Some(std::path::PathBuf::from(trimmed));
                }
            }
        }
    }

    // Common install locations
    let candidates = [
        std::path::PathBuf::from(r"C:\Program Files\Steam\steamcmd.exe"),
        std::path::PathBuf::from(r"C:\Program Files (x86)\Steam\steamcmd.exe"),
        std::path::PathBuf::from(r"C:\steamcmd\steamcmd.exe"),
    ];
    candidates.into_iter().find(|p| p.exists())
}

/// Get steamcmd version by running +version.
fn get_steamcmd_version(steamcmd: &Path) -> Option<String> {
    let output = Command::new(steamcmd).args(["+version"]).output().ok()?;
    let combined = format!(
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    // steamcmd version output looks like "Steam Console Client (TM) v..."
    for line in combined.lines() {
        if line.contains("Steam Console Client") || line.contains("v") {
            return Some(line.trim().to_string());
        }
    }
    None
}

/// Detect Steam installation: check common paths for Steam.exe and steamapps.
fn detect_steam() -> (bool, Option<PathBuf>, Option<String>) {
    let exe_candidates = [
        std::path::PathBuf::from(r"C:\Program Files (x86)\Steam\Steam.exe"),
        std::path::PathBuf::from(r"C:\Program Files\Steam\Steam.exe"),
    ];
    let lib_candidates = [
        r"C:\Program Files (x86)\Steam\steamapps",
        r"C:\Program Files\Steam\steamapps",
    ];

    let steam_exe_path = exe_candidates.iter().find(|p| p.exists()).cloned();
    let steam_library_path = lib_candidates
        .iter()
        .find(|p| std::path::Path::new(p).exists())
        .map(|s| s.to_string());

    let steam_installed = steam_exe_path.is_some() || steam_library_path.is_some();
    (steam_installed, steam_exe_path, steam_library_path)
}

/// Test Steam appinfo query by asking for a well-known app (Half-Life 2, appID 220).
fn test_appinfo_query(steamcmd: &Path) -> Result<bool, String> {
    // Appinfo query without login is limited but we can test that steamcmd
    // can at least parse and attempt the command.
    let output = Command::new(steamcmd)
        .args(["+app_info_print", "220", "+quit"])
        .output()
        .map_err(|e| format!("Failed to run steamcmd appinfo: {}", e))?;

    let combined = format!(
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    // If we get "No steam login" or actual app data, steamcmd is functional
    Ok(combined.contains("No steam login") || combined.contains("state") || combined.contains("appid"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_steamcmd_result_struct() {
        let result = SteamCmdResult {
            steamcmd_found: true,
            steamcmd_version: Some("Steam Console Client (TM) v1.2.3".to_string()),
            steam_installed: true,
            appinfo_query_working: false,
            steam_library_path: Some(r"C:\Program Files (x86)\Steam\steamapps".to_string()),
            steam_exe_path: Some(std::path::PathBuf::from(
                r"C:\Program Files (x86)\Steam\Steam.exe",
            )),
        };
        assert!(result.steamcmd_found);
        assert!(result.steamcmd_version.is_some());
        assert!(result.steam_installed);
        assert!(!result.appinfo_query_working);
        assert!(result.steam_library_path.is_some());
        assert!(result.steam_exe_path.is_some());
    }

    #[test]
    fn test_check_steam_installed() {
        // Just verify the function runs without panicking
        let _ = detect_steam();
    }

    #[test]
    fn test_find_steam_library() {
        // May or may not find Steam — just verify it doesn't panic
        let (_, _, lib) = detect_steam();
        let _: Option<String> = lib;
    }

    #[test]
    fn test_get_steamcmd_version_returns_string_when_installed() {
        if let Some(steamcmd) = find_steamcmd() {
            let version = get_steamcmd_version(&steamcmd);
            // Version may or may not be returned depending on steamcmd output format
            // Just verify it doesn't panic
            let _ = version;
        }
    }

    #[test]
    fn test_test_appinfo_query_structure() {
        // Verify the test_appinfo_query function signature is correct
        // This just checks it compiles and returns a Result
        fn _assert_signature(_f: fn(&std::path::Path) -> Result<bool, String>) {}
        _assert_signature(test_appinfo_query);
    }

    #[test]
    fn test_detect_steam_returns_tuple() {
        let (installed, exe, lib) = detect_steam();
        // Just verify the types are correct
        let _: bool = installed;
        let _: Option<std::path::PathBuf> = exe;
        let _: Option<String> = lib;
    }
}
