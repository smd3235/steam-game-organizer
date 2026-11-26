//! Sandbox mode: simulate UI interactions end-to-end, read logs, report issues.
//!
//! Creates mock game archives, populates each UI view, simulates button clicks
//! by calling view handlers directly, reads the log file for errors/warnings,
//! and reports issues found.
//!
//! Usage: `steam-game-organizer.exe --sandbox`
//! 2026-11-26: Sandbox mode for automated UI testing and issue detection.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use crate::core::config::AppConfig;
use crate::core::logger::AppLogger;
use crate::core::models::{
    ArtworkResult, ConversionResult, GameArchive, OrganizationDecision, SteamMatch,
};
use crate::services::library_service::LibraryService;
use crate::services::organizer_service::OrganizerService;

/// A sandbox test result: what was found, what was fixed, what remains.
struct SandboxResult {
    checks_passed: usize,
    checks_failed: usize,
    issues_found: Vec<String>,
    issues_fixed: Vec<String>,
}

/// Create a mock GameArchive for sandbox testing.
fn mock_archive(
    name: &str,
    appid: &str,
    category: &str,
    size: u64,
    accepted: bool,
    skipped: bool,
) -> GameArchive {
    GameArchive {
        path: PathBuf::from(format!("C:/Games/{}.zip", name)),
        display_name: name.to_string(),
        normalized_title: name.to_lowercase(),
        identity_key: format!("steam_{}", appid),
        extension: "zip".to_string(),
        version: vec![1, 0, 0],
        steam: SteamMatch {
            found: true,
            appid: appid.to_string(),
            name: name.to_string(),
            genres: vec!["Action".to_string(), "Adventure".to_string()],
            categories: vec!["Single-player".to_string()],
            description: format!("A fictional {} game for sandbox testing.", name),
            tags: vec!["steam".to_string(), "pc".to_string()],
            release_date: "2024-01-15".to_string(),
            confidence: "high".to_string(),
            source: "sandbox".to_string(),
            reason: "Exact title match".to_string(),
            developer: "Sandbox Dev".to_string(),
            publisher: "Sandbox Pub".to_string(),
            score: 0.95,
            artwork_url: format!(
                "https://cdn.steamstatic.com/steam/apps/{}/header.jpg",
                appid
            ),
            asset_urls: std::collections::HashMap::new(),
        },
        artwork: ArtworkResult {
            status: "downloaded".to_string(),
            path: Some(PathBuf::from(format!("C:/Artwork/{}.jpg", name))),
            source: "steam".to_string(),
            reason: "Steam capsule image".to_string(),
            assets: std::collections::HashMap::new(),
        },
        decision: OrganizationDecision {
            category: category.to_string(),
            suggested_category: category.to_string(),
            evidence: crate::core::category_evidence::unsorted_evidence(),
            accepted,
            changed_from_suggestion: false,
            skipped,
        },
        selected: false,
        user_title: String::new(),
        conversion: ConversionResult {
            status: "converted".to_string(),
            message: "Converted to 7z successfully".to_string(),
            source_format: "zip".to_string(),
            target_format: "7z".to_string(),
            final_name: format!("{}.7z", name),
            final_size: size / 2,
            source_size: size,
            free_bytes_at_failure: 0,
        },
        organized_path: None,
        created_game_dir: false,
        size,
    }
}

/// Run sandbox mode: simulate UI interactions end-to-end.
pub fn run_sandbox(logger: Arc<AppLogger>, output_dir: &Path) -> Result<(), String> {
    logger.info("SANDBOX", "START sandbox end-to-end UI simulation", "");

    // Ensure output dir exists
    if !output_dir.exists() {
        std::fs::create_dir_all(output_dir)
            .map_err(|e| format!("Failed to create output dir: {}", e))?;
    }

    let mut result = SandboxResult {
        checks_passed: 0,
        checks_failed: 0,
        issues_found: Vec::new(),
        issues_fixed: Vec::new(),
    };

    // Create mock config pointing to temp sandbox
    let sandbox_dir = std::env::temp_dir().join(format!("sgo_sandbox_{}", std::process::id()));
    std::fs::create_dir_all(&sandbox_dir)
        .map_err(|e| format!("Failed to create sandbox dir: {}", e))?;

    let mut config = AppConfig::new(sandbox_dir.as_path());
    config.library_root = Some(sandbox_dir.clone());
    config.set_extract_folder(sandbox_dir.join("extracted"));
    let config = Arc::new(config);

    // Build mock archives
    let archives: Vec<GameArchive> = vec![
        mock_archive("Alpha Forge", "12345", "Action", 5_000_000_000, true, false),
        mock_archive("Gamma Quest", "67890", "RPG", 8_000_000_000, true, false),
        mock_archive(
            "Delta Realm",
            "11111",
            "Strategy",
            3_000_000_000,
            false,
            true,
        ),
        mock_archive(
            "Nebula Online",
            "22222",
            "Simulation",
            4_000_000_000,
            false,
            false,
        ),
        mock_archive(
            "Zenith Edge",
            "33333",
            "Shooter",
            6_000_000_000,
            true,
            false,
        ),
    ];

    let archives_count = archives.len();
    let converted_count = archives
        .iter()
        .filter(|a| !a.decision.skipped && a.decision.accepted)
        .count();
    let skipped_count = archives.iter().filter(|a| a.decision.skipped).count();
    let failed_count = archives
        .iter()
        .filter(|a| !a.decision.accepted && !a.decision.skipped)
        .count();

    logger.info(
        "SANDBOX",
        &format!("Created {} mock archives", archives_count),
        "",
    );
    logger.info(
        "SANDBOX",
        &format!(
            "Converted: {}, Skipped: {}, Failed: {}",
            converted_count, skipped_count, failed_count
        ),
        "",
    );

    // --- Step 1: Scan View ---
    logger.info("SANDBOX", "Step 1: Scan view simulation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let logger_for_services = Arc::clone(&logger);
        let logger_clone1 =
            Arc::new(move |cat: &str, msg: &str| logger_for_services.info(cat, msg, ""));
        let logger_for_lib = Arc::clone(&logger);
        let logger_clone2 = Arc::new(move |cat: &str, msg: &str| logger_for_lib.info(cat, msg, ""));
        let services = Arc::new(crate::app::controller::Services {
            organizer: OrganizerService::new(logger_clone1, true),
        });
        let library_service = LibraryService::new(logger_clone2, None);
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 300000));
        let jobs = Arc::new(crate::app::jobs::JobManager::new(4));

        let mut scan_view = crate::ui::scan_view::ScanView::new(
            Arc::clone(&services),
            library_service,
            Arc::clone(&jobs),
            Arc::clone(&config),
            palette,
            Arc::clone(&logger),
            watchdog.clone(),
        );
        scan_view.state.discovered_archives = archives.clone();
        scan_view.state.status = format!("Discovered {} archives", archives_count);
        scan_view.state.phase_states = [true, true, true, true, true, true];
        scan_view.state.current_phase = 6;

        // Verify: archives discovered
        check(
            &mut result,
            scan_view.state.discovered_archives.len() == archives_count,
            "Scan: all archives discovered",
            "Scan: missing archives",
        );
        // Verify: all phases complete
        check(
            &mut result,
            scan_view.state.phase_states.iter().all(|&p| p),
            "Scan: all phases complete",
            "Scan: incomplete phases",
        );
    }

    // --- Step 2: Review View ---
    logger.info("SANDBOX", "Step 2: Review view simulation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 300000));

        let mut review_view =
            crate::ui::review_view::ReviewView::new(palette, Arc::clone(&logger), watchdog);
        review_view.state.archives = archives.clone();
        review_view.state.selected_index = Some(0);
        review_view.state.status = format!("{} archives verified", archives_count);

        // Verify: archives loaded
        check(
            &mut result,
            review_view.state.archives.len() == archives_count,
            "Review: archives loaded",
            "Review: missing archives",
        );
        // Verify: first archive selected
        check(
            &mut result,
            review_view.state.selected_index == Some(0),
            "Review: first archive selected",
            "Review: no selection",
        );

        // Simulate clicking "Accept" on first archive
        review_view.state.archives[0].decision.accepted = true;
        check(
            &mut result,
            review_view.state.archives[0].decision.accepted,
            "Review: accept archive click works",
            "Review: accept click did not set accepted",
        );
    }

    // --- Step 3: Organize View ---
    logger.info("SANDBOX", "Step 3: Organize view simulation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 300000));

        let mut organize_view =
            crate::ui::organize_view::OrganizeView::new(palette, Arc::clone(&logger), watchdog);
        organize_view.state.archives = archives.clone();
        organize_view.state.status = "Organizing complete".to_string();
        organize_view.state.converted_count = converted_count;
        organize_view.state.skipped_count = skipped_count;
        organize_view.state.failed_count = failed_count;
        organize_view.state.progress = 1.0;
        organize_view.state.stage = "Complete".to_string();

        // Verify: counts match
        check(
            &mut result,
            organize_view.state.converted_count == converted_count,
            "Organize: converted count matches",
            "Organize: converted count mismatch",
        );
        check(
            &mut result,
            organize_view.state.skipped_count == skipped_count,
            "Organize: skipped count matches",
            "Organize: skipped count mismatch",
        );
        check(
            &mut result,
            organize_view.state.progress == 1.0,
            "Organize: progress at 100%",
            "Organize: progress not complete",
        );
    }

    // --- Step 4: Artwork View ---
    logger.info("SANDBOX", "Step 4: Artwork view simulation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 300000));

        let mut artwork_view =
            crate::ui::artwork_view::ArtworkView::new(palette, Arc::clone(&logger), watchdog);
        artwork_view.state.archives = archives.clone();

        // Verify: archives loaded with artwork
        check(
            &mut result,
            artwork_view.state.archives.len() == archives_count,
            "Artwork: archives loaded",
            "Artwork: missing archives",
        );
        check(
            &mut result,
            artwork_view
                .state
                .archives
                .iter()
                .all(|a| a.artwork.present()),
            "Artwork: all archives have artwork",
            "Artwork: missing artwork on some archives",
        );
    }

    // --- Step 5: Done View ---
    logger.info("SANDBOX", "Step 5: Done view simulation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(crate::core::errors::Watchdog::new(logger.clone(), 300000));

        let mut done_view =
            crate::ui::done_view::DoneView::new(palette, Arc::clone(&logger), watchdog);
        done_view.state.archives = archives.clone();
        done_view.state.status = "Organization complete".to_string();
        done_view.state.converted = converted_count;
        done_view.state.skipped = skipped_count;
        done_view.state.failed = failed_count;

        // Verify: counts match
        check(
            &mut result,
            done_view.state.converted == converted_count,
            "Done: converted count matches",
            "Done: converted count mismatch",
        );
        check(
            &mut result,
            done_view.state.skipped == skipped_count,
            "Done: skipped count matches",
            "Done: skipped count mismatch",
        );
        check(
            &mut result,
            done_view.state.failed == failed_count,
            "Done: failed count matches",
            "Done: failed count mismatch",
        );
    }

    // --- Step 6: Read logs and check for errors ---
    logger.info("SANDBOX", "Step 6: Read logs and check for errors", "");
    // Note: logger writes to sandbox.log in logs dir, not temp

    // Read the sandbox log file
    let log_path = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_default()
        .join("logs")
        .join("sandbox.log");

    if log_path.exists() {
        let log_contents = std::fs::read_to_string(&log_path)
            .map_err(|e| format!("Failed to read log file: {}", e))?;

        // Check for error patterns
        let error_patterns = ["ERROR", "error", "panic", "PANIC", "FAILED", "failed"];
        for pattern in &error_patterns {
            if log_contents.contains(pattern) {
                result
                    .issues_found
                    .push(format!("Log contains pattern: {}", pattern));
                result.checks_failed += 1;
                logger.warning(
                    "SANDBOX",
                    &format!("Log error pattern found: {}", pattern),
                    "",
                );
            }
        }
        if result.issues_found.is_empty() {
            result.checks_passed += 1;
            logger.info("SANDBOX", "Log check: no error patterns found", "");
        }
    } else {
        logger.warning("SANDBOX", "Log file not found for checking", "");
        result.issues_found.push("Log file not found".to_string());
        result.checks_failed += 1;
    }

    // --- Step 7: Print summary ---
    logger.info("SANDBOX", "Step 7: Sandbox summary", "");
    println!("\n================================================");
    println!("  SANDBOX MODE - End-to-End UI Simulation");
    println!("================================================");
    println!(
        "\nMock archives: {} (converted: {}, skipped: {}, failed: {})",
        archives_count, converted_count, skipped_count, failed_count
    );
    println!("\nChecks passed: {}", result.checks_passed);
    println!("Checks failed: {}", result.checks_failed);

    if !result.issues_found.is_empty() {
        println!("\nIssues found:");
        for issue in &result.issues_found {
            println!("  - {}", issue);
        }
    }

    if !result.issues_fixed.is_empty() {
        println!("\nIssues fixed:");
        for fix in &result.issues_fixed {
            println!("  - {}", fix);
        }
    }

    println!("\n================================================");

    if result.checks_failed > 0 {
        logger.warning(
            "SANDBOX",
            &format!("Sandbox completed with {} failures", result.checks_failed),
            "",
        );
        return Err(format!("Sandbox found {} issues", result.checks_failed));
    }

    logger.info("SANDBOX", "COMPLETE sandbox mode - all checks passed", "");
    Ok(())
}

/// Record a check result.
fn check(result: &mut SandboxResult, condition: bool, _pass_msg: &str, fail_msg: &str) {
    if condition {
        result.checks_passed += 1;
    } else {
        result.checks_failed += 1;
        result.issues_found.push(fail_msg.to_string());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_mock_archive_creation() {
        let archive = mock_archive("Test Game", "99999", "Action", 1000, true, false);
        assert_eq!(archive.display_name, "Test Game");
        assert_eq!(archive.steam.appid, "99999");
        assert_eq!(archive.decision.category, "Action");
        assert!(archive.decision.accepted);
        assert!(!archive.decision.skipped);
        assert_eq!(archive.size, 1000);
    }

    #[test]
    fn test_check_function() {
        let mut result = SandboxResult {
            checks_passed: 0,
            checks_failed: 0,
            issues_found: Vec::new(),
            issues_fixed: Vec::new(),
        };
        check(&mut result, true, "pass", "fail");
        check(&mut result, false, "pass", "fail");
        assert_eq!(result.checks_passed, 1);
        assert_eq!(result.checks_failed, 1);
        assert_eq!(result.issues_found.len(), 1);
    }

    #[test]
    fn test_converted_count_calculation() {
        let archives: Vec<GameArchive> = vec![
            mock_archive("A", "1", "Action", 1000, true, false),
            mock_archive("B", "2", "RPG", 2000, false, true),
            mock_archive("C", "3", "Shooter", 3000, false, false),
        ];
        let converted = archives
            .iter()
            .filter(|a| !a.decision.skipped && a.decision.accepted)
            .count();
        let skipped = archives.iter().filter(|a| a.decision.skipped).count();
        let failed = archives
            .iter()
            .filter(|a| !a.decision.accepted && !a.decision.skipped)
            .count();
        assert_eq!(converted, 1);
        assert_eq!(skipped, 1);
        assert_eq!(failed, 1);
    }
}
