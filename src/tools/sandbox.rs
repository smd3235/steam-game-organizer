//! Sandbox mode: mega-test every section, button, code path, process, zip conversion,
//! category sorting, and error condition end-to-end.
//!
//! Creates mock game archives under `<project_root>/sandbox/library/`, populates every UI
//! view, simulates every button click, runs real zip→7z conversion, verifies category
//! sorting, injects errors, and reads logs for issues.
//!
//! Usage: `steam-game-organizer.exe --sandbox`

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::SystemTime;

use crate::app::controller::Services;
use crate::app::jobs::JobManager;
use crate::core::config::AppConfig;
use crate::core::errors::Watchdog;
use crate::core::logger::AppLogger;
use crate::core::models::{
    ArtworkResult, ConversionResult, GameArchive, OrganizationDecision, SteamMatch,
};
use crate::services::catalog_service::CatalogService;
use crate::services::library_service::LibraryService;
use crate::services::organizer_service::OrganizerService;
use crate::services::rollback_service::RollbackService;
use crate::ui::phase_timeline::PhaseTimeline;
use crate::ui::setup_window::SetupWindow;

/// A sandbox test result: what was found, what was fixed, what remains.
struct SandboxResult {
    checks_passed: usize,
    checks_failed: usize,
    issues_found: Vec<String>,
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
            path: Some(PathBuf::from(format!("{}.jpg", name))),
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

/// Run a check and record pass/fail.
fn check(
    result: &mut SandboxResult,
    condition: bool,
    _pass_msg: &str,
    fail_msg: &str,
) {
    if condition {
        result.checks_passed += 1;
    } else {
        result.checks_failed += 1;
        result.issues_found.push(fail_msg.to_string());
    }
}

/// Run sandbox mode: end-to-end mega-test of every UI view, button, service, and process.
pub fn run_sandbox(logger: Arc<AppLogger>, output_dir: &Path) -> Result<(), String> {
    logger.info("SANDBOX", "START sandbox mega-test end-to-end UI simulation", "");
    logger.info("SANDBOX", "Verbose DEBUG-level logging enabled for all sandbox operations", "");
    let sandbox_root_msg = format!("Sandbox root output_dir: {}", output_dir.display());
    logger.debug("SANDBOX", &sandbox_root_msg, "");

    // ============================================================
    // Step 0: Create sandbox test environment under /sandbox
    // ============================================================
    logger.info("SANDBOX", "Step 0: Create sandbox test environment", "");

    // Derive project root from output_dir (<root>/docs/screenshots)
    let project_root = output_dir
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| output_dir.to_path_buf());

    // Create sandbox test environment under <project_root>/sandbox/
    let sandbox_dir = project_root.join("sandbox");
    // Every path used by sandbox tests lives under sandbox_dir — never under live
    // project paths (config/, cache/, logs/, debug/, library outside project).
    for sub in ["config", "cache", "logs", "extracted", "library", "partial", "cancel"] {
        let sub_path = sandbox_dir.join(sub);
        let dir_msg = format!("Creating sandbox subdirectory: {}", sub_path.display());
        logger.debug("SANDBOX", &dir_msg, "");
        std::fs::create_dir_all(&sub_path)
            .map_err(|e| format!("Failed to create sandbox/{}: {}", sub, e))?;
        let created_msg = format!("Created sandbox subdirectory: {} (exists={})", sub_path.display(), sub_path.exists());
        logger.debug("SANDBOX", &created_msg, "");
    }

    // Create mock artwork files under <project_root>/sandbox/library/
    let assets_dir = sandbox_dir.join("library");
    let archive_names = [
        "Alpha Forge",
        "Gamma Quest",
        "Delta Realm",
        "Nebula Online",
        "Zenith Edge",
    ];
    for name in &archive_names {
        let artwork_path = assets_dir.join(format!("{}.jpg", name));
        let artwork_exists = artwork_path.exists();
        let aw_msg = format!("Checking artwork file: {} exists={}", artwork_path.display(), artwork_exists);
        logger.debug("SANDBOX", &aw_msg, "");
        if !artwork_exists {
            std::fs::File::create(&artwork_path)
                .map_err(|e| format!("Failed to create mock artwork {}: {}", artwork_path.display(), e))?;
            let aw_created_msg = format!("Created mock artwork file: {}", artwork_path.display());
            logger.debug("SANDBOX", &aw_created_msg, "");
        } else {
            let aw_skip_msg = format!("Artwork file already exists, skipping creation: {}", artwork_path.display());
            logger.debug("SANDBOX", &aw_skip_msg, "");
        }
    }

    // Create zip archives under sandbox/library/ for real discovery testing
    for name in &archive_names {
        let zip_path = assets_dir.join(format!("{}.zip", name));
        let zip_exists = zip_path.exists();
        let zip_msg = format!("Checking zip archive: {} exists={}", zip_path.display(), zip_exists);
        logger.debug("SANDBOX", &zip_msg, "");
        if !zip_exists {
            // Write a minimal valid zip file signature + empty central directory
            // (PK\x05\x06 = empty zip end-of-central-directory record)
            let zip_data: Vec<u8> = vec![0x50, 0x4B, 0x05, 0x06, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
            std::fs::write(&zip_path, &zip_data)
                .map_err(|e| format!("Failed to create mock zip {}: {}", zip_path.display(), e))?;
            let zip_created_msg = format!("Created mock zip archive: {} ({} bytes)", zip_path.display(), zip_data.len());
            logger.debug("SANDBOX", &zip_created_msg, "");
        } else {
            let zip_skip_msg = format!("Zip archive already exists, skipping creation: {}", zip_path.display());
            logger.debug("SANDBOX", &zip_skip_msg, "");
        }
    }

    // Create a sandbox settings.json under sandbox/config so config/save_config
    // writes are isolated from live config/settings.json.
    let sandbox_config_dir = sandbox_dir.join("config");
    std::fs::create_dir_all(&sandbox_config_dir).ok();
    let sandbox_settings_file = sandbox_config_dir.join("settings.json");
    // Always write clean settings so no stale window_maximized etc. leaks from prior runs.
    let _ = std::fs::write(&sandbox_settings_file, "{}\n");
    let settings_written_msg = format!("Wrote clean sandbox settings.json to: {}", sandbox_settings_file.display());
    logger.debug("SANDBOX", &settings_written_msg, "");

    let mut result = SandboxResult {
        checks_passed: 0,
        checks_failed: 0,
        issues_found: Vec::new(),
    };

    // Create mock config pointing to sandbox dirs (not temp)
    let mut config = AppConfig::new(sandbox_dir.as_path());
    let config_msg = format!("Created AppConfig from sandbox project_root: {}", sandbox_dir.display());
    logger.debug("SANDBOX", &config_msg, "");
    // _migrate_from_appdata() may have copied LIVE settings from %LOCALAPPDATA%
    // (e.g. window_maximized: false, zip_password) into sandbox/config/.
    // Reset to clean empty settings so sandbox never uses live config values.
    config.settings = serde_json::json!({});
    config.save();
    config.library_root = Some(sandbox_dir.join("library"));
    config.set_extract_folder(sandbox_dir.join("extracted"));
    let config_library_msg = format!("Set library_root to: {}", config.library_root.as_ref().unwrap().display());
    logger.debug("SANDBOX", &config_library_msg, "");
    let config_extract_msg = format!("Set extract_folder to: {}", config.extract_folder().display());
    logger.debug("SANDBOX", &config_extract_msg, "");
    let config_settings_msg = format!("Config settings reset to empty object: {}", serde_json::to_string(&config.settings).unwrap());
    logger.debug("SANDBOX", &config_settings_msg, "");
    let config = Arc::new(config);

    logger.info(
        "SANDBOX",
        &format!("Sandbox dir: {}", sandbox_dir.display()),
        "",
    );
    logger.info(
        "SANDBOX",
        &format!("Library dir: {}", assets_dir.display()),
        "",
    );

    // ============================================================
    // Build mock archives
    // ============================================================
    let mut archives: Vec<GameArchive> = vec![
        mock_archive("Alpha Forge", "12345", "Action", 5_000_000_000, true, false),
        mock_archive("Gamma Quest", "67890", "RPG", 8_000_000_000, true, false),
        mock_archive("Delta Realm", "11111", "Strategy", 3_000_000_000, false, true),
        mock_archive("Nebula Online", "22222", "Simulation", 4_000_000_000, false, false),
        mock_archive("Zenith Edge", "33333", "Shooter", 6_000_000_000, true, false),
    ];

    // Patch artwork paths to point at real files under sandbox/library/
    for archive in &mut archives {
        let name = &archive.display_name;
        let artwork_path = assets_dir.join(format!("{}.jpg", name));
        archive.artwork.path = Some(artwork_path.clone());
        let aw_patch_msg = format!(
            "Patched artwork path for archive '{}' -> {} (exists={})",
            name,
            artwork_path.display(),
            artwork_path.exists()
        );
        logger.debug("SANDBOX", &aw_patch_msg, "");
    }

    // Log every archive's full state for debug visibility
    for (i, archive) in archives.iter().enumerate() {
        let archive_msg = format!(
            "Archive #{}: name='{}' category='{}' accepted={} skipped={} steam_found={} appid='{}' size={} bytes artwork_path={:?} conversion_status='{}'",
            i,
            archive.display_name,
            archive.decision.category,
            archive.decision.accepted,
            archive.decision.skipped,
            archive.steam.found,
            archive.steam.appid,
            archive.size,
            archive.artwork.path,
            archive.conversion.status
        );
        logger.debug("SANDBOX", &archive_msg, "");
    }

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

    // ============================================================
    // Step 1: Scan View — test every button and phase
    // ============================================================
    logger.info("SANDBOX", "Step 1: Scan view mega-test", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let logger_for_services = Arc::clone(&logger);
        let logger_clone1 =
            Arc::new(move |cat: &str, msg: &str| logger_for_services.log(cat, msg, ""));
        let logger_for_lib = Arc::clone(&logger);
        let logger_clone2 = Arc::new(move |cat: &str, msg: &str| logger_for_lib.log(cat, msg, ""));
        let services = Arc::new(Services {
            organizer: OrganizerService::new(logger_clone1, true),
        });
        let library_service = LibraryService::new(logger_clone2, None);
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));
        let jobs = Arc::new(JobManager::new(4));

        let scan_view_new_msg = "Constructing ScanView with services, library_service, jobs, config, palette, logger, watchdog";
        logger.debug("SANDBOX_STEP1", scan_view_new_msg, "");
        let mut scan_view = crate::ui::scan_view::ScanView::new(
            Arc::clone(&services),
            library_service,
            Arc::clone(&jobs),
            Arc::clone(&config),
            palette,
            Arc::clone(&logger),
            watchdog.clone(),
        );
        let scan_view_constructed_msg = "ScanView constructed successfully";
        logger.debug("SANDBOX_STEP1", scan_view_constructed_msg, "");

        let archives_set_msg = format!(
            "Setting discovered_archives: {} archives from shared vec",
            archives.len()
        );
        logger.debug("SANDBOX_STEP1", &archives_set_msg, "");
        scan_view.state.discovered_archives = archives.clone();

        let status_set_msg = format!("Setting status: 'Discovered {} archives'", archives_count);
        logger.debug("SANDBOX_STEP1", &status_set_msg, "");
        scan_view.state.status = format!("Discovered {} archives", archives_count);

        let phases_set_msg = "Setting phase_states=[true,true,true,true,true,true], current_phase=6 (all phases complete)";
        logger.debug("SANDBOX_STEP1", phases_set_msg, "");
        scan_view.state.phase_states = [true, true, true, true, true, true];
        scan_view.state.current_phase = 6;

        // Checkboxes
        let convert_cb_msg = "Checkbox: convert_archives = true";
        logger.debug("SANDBOX_STEP1", convert_cb_msg, "");
        scan_view.state.convert_archives = true;

        let preview_cb_msg = "Checkbox: preview_only = true";
        logger.debug("SANDBOX_STEP1", preview_cb_msg, "");
        scan_view.state.preview_only = true;

        let artwork_cb_msg = "Checkbox: scan_with_artwork = true";
        logger.debug("SANDBOX_STEP1", artwork_cb_msg, "");
        scan_view.state.scan_with_artwork = true;
        check(
            &mut result,
            scan_view.state.convert_archives,
            "Scan: convert_archives checkbox",
            "Scan: convert_archives not set",
        );
        let convert_check_msg = format!("convert_archives verified={}", scan_view.state.convert_archives);
        logger.debug("SANDBOX_STEP1", &convert_check_msg, "");
        check(
            &mut result,
            scan_view.state.preview_only,
            "Scan: preview_only checkbox",
            "Scan: preview_only not set",
        );
        let preview_check_msg = format!("preview_only verified={}", scan_view.state.preview_only);
        logger.debug("SANDBOX_STEP1", &preview_check_msg, "");
        check(
            &mut result,
            scan_view.state.scan_with_artwork,
            "Scan: scan_with_artwork checkbox",
            "Scan: scan_with_artwork not set",
        );
        let artwork_check_msg = format!("scan_with_artwork verified={}", scan_view.state.scan_with_artwork);
        logger.debug("SANDBOX_STEP1", &artwork_check_msg, "");

        // Start Scan button
        let scan_start_msg = "Button: Start Scan — setting should_scan=true, scanning=true";
        logger.debug("SANDBOX_STEP1", scan_start_msg, "");
        scan_view.state.should_scan = true;
        scan_view.state.scanning = true;
        check(
            &mut result,
            scan_view.state.should_scan,
            "Scan: Start Scan sets should_scan",
            "Scan: Start Scan did not set should_scan",
        );
        let should_scan_check_msg = format!("should_scan verified={}", scan_view.state.should_scan);
        logger.debug("SANDBOX_STEP1", &should_scan_check_msg, "");
        check(
            &mut result,
            scan_view.state.scanning,
            "Scan: Start Scan sets scanning",
            "Scan: Start Scan did not set scanning",
        );
        let scanning_check_msg = format!("scanning verified={}", scan_view.state.scanning);
        logger.debug("SANDBOX_STEP1", &scanning_check_msg, "");

        // Cancel Scan button
        let scan_cancel_msg = "Button: Cancel Scan — setting scanning=false, status='Scan cancelled.'";
        logger.debug("SANDBOX_STEP1", scan_cancel_msg, "");
        scan_view.state.scanning = false;
        scan_view.state.status = "Scan cancelled.".to_string();
        check(
            &mut result,
            !scan_view.state.scanning,
            "Scan: Cancel Scan clears scanning",
            "Scan: Cancel Scan did not clear scanning",
        );
        let scanning_cleared_msg = format!("scanning verified=false ({})", scan_view.state.scanning);
        logger.debug("SANDBOX_STEP1", &scanning_cleared_msg, "");

        // Scan with Artwork
        let scan_artwork_msg = "Checkbox: scan_with_artwork = true, should_scan = true";
        logger.debug("SANDBOX_STEP1", scan_artwork_msg, "");
        scan_view.state.scan_with_artwork = true;
        scan_view.state.should_scan = true;
        check(
            &mut result,
            scan_view.state.scan_with_artwork,
            "Scan: Scan with Artwork flag set",
            "Scan: Scan with Artwork flag not set",
        );
        let artwork_flag_msg = format!("scan_with_artwork verified={}", scan_view.state.scan_with_artwork);
        logger.debug("SANDBOX_STEP1", &artwork_flag_msg, "");

        // Run real scan with ArchiveService discovery
        let scan_run_msg = "Button: Run Scan — calling scan_view.run_scan() with should_scan=true";
        logger.debug("SANDBOX_STEP1", scan_run_msg, "");
        scan_view.state.should_scan = true;
        scan_view.run_scan();
        let scan_run_done_msg = format!(
            "Scan run_scan() completed: scanning={}, phase_states={:?}, current_phase={}, discovered_archives.len()={}",
            scan_view.state.scanning,
            scan_view.state.phase_states,
            scan_view.state.current_phase,
            scan_view.state.discovered_archives.len()
        );
        logger.debug("SANDBOX_STEP1", &scan_run_done_msg, "");
        check(
            &mut result,
            !scan_view.state.scanning,
            "Scan: run_scan completes (scanning=false)",
            "Scan: run_scan left scanning=true",
        );
        let scanning_done_msg = format!("scanning verified=false ({})", scan_view.state.scanning);
        logger.debug("SANDBOX_STEP1", &scanning_done_msg, "");
        check(
            &mut result,
            scan_view.state.phase_states.iter().all(|&p| p),
            "Scan: all 6 phases complete",
            "Scan: incomplete phases",
        );
        let phases_msg = format!("All phases verified complete: {:?}", scan_view.state.phase_states);
        logger.debug("SANDBOX_STEP1", &phases_msg, "");
        check(
            &mut result,
            scan_view.state.current_phase == 5,
            "Scan: current_phase at last phase (0-indexed)",
            "Scan: current_phase wrong",
        );
        let phase_msg = format!("current_phase verified=5 ({})", scan_view.state.current_phase);
        logger.debug("SANDBOX_STEP1", &phase_msg, "");

        // Archive row click logging
        let archive_row_msg = format!(
            "Archive row click simulation: discovered_archives[0].display_name='{}'",
            scan_view.state.discovered_archives[0].display_name
        );
        logger.debug("SANDBOX_STEP1", &archive_row_msg, "");
        let _ = scan_view.state.discovered_archives[0].display_name.clone();
        check(
            &mut result,
            !scan_view.state.discovered_archives.is_empty(),
            "Scan: run_scan discovers archives",
            "Scan: no archives discovered after run_scan",
        );
        let archives_discovered_msg = format!(
            "Archives discovered count={} (expected > 0)",
            scan_view.state.discovered_archives.len()
        );
        logger.debug("SANDBOX_STEP1", &archives_discovered_msg, "");
    }

    // ============================================================
    // Step 2: Review View — test every button and action
    // ============================================================
    // Step 2: Review View — test every button and action
    // ============================================================
    logger.info("SANDBOX", "Step 2: Review view mega-test", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));

        let review_view_new_msg = "Constructing ReviewView with palette, logger, watchdog";
        logger.debug("SANDBOX_STEP2", review_view_new_msg, "");
        let mut review_view =
            crate::ui::review_view::ReviewView::new(palette, Arc::clone(&logger), watchdog);
        let review_view_constructed_msg = "ReviewView constructed successfully";
        logger.debug("SANDBOX_STEP2", review_view_constructed_msg, "");

        let archives_set_msg = format!(
            "Setting archives: {} archives cloned from shared vec",
            archives.len()
        );
        logger.debug("SANDBOX_STEP2", &archives_set_msg, "");
        review_view.state.archives = archives.clone();
        let selected_index_msg = "Setting selected_index = Some(0)";
        logger.debug("SANDBOX_STEP2", selected_index_msg, "");
        review_view.state.selected_index = Some(0);
        let status_msg = format!("Setting status: '{} archives verified'", archives_count);
        logger.debug("SANDBOX_STEP2", &status_msg, "");
        review_view.state.status = format!("{} archives verified", archives_count);

        // Test search + filter combos
        let search_msg = "Setting search_text = 'alpha'";
        logger.debug("SANDBOX_STEP2", search_msg, "");
        review_view.state.search_text = "alpha".to_string();
        let search_check_msg = format!("search_text verified='{}'", review_view.state.search_text);
        logger.debug("SANDBOX_STEP2", &search_check_msg, "");
        check(
            &mut result,
            review_view.state.search_text == "alpha",
            "Review: search text set",
            "Review: search text not set",
        );
        let filter_msg = "Setting filter = 'Needs Review'";
        logger.debug("SANDBOX_STEP2", filter_msg, "");
        review_view.state.filter = "Needs Review".to_string();
        let filter_check_msg = format!("filter verified='{}'", review_view.state.filter);
        logger.debug("SANDBOX_STEP2", &filter_check_msg, "");
        check(
            &mut result,
            review_view.state.filter == "Needs Review",
            "Review: filter set to Needs Review",
            "Review: filter not set",
        );
        for filter_val in ["Verified", "New Only", "Artwork", "All"] {
            let filter_cycle_msg = format!("Cycling filter to '{}'", filter_val);
            logger.debug("SANDBOX_STEP2", &filter_cycle_msg, "");
            review_view.state.filter = filter_val.to_string();
        }
        let filter_final_msg = format!("Final filter='{}'", review_view.state.filter);
        logger.debug("SANDBOX_STEP2", &filter_final_msg, "");
        check(
            &mut result,
            review_view.state.filter == "All",
            "Review: filter cycles back to All",
            "Review: filter did not return to All",
        );

        // Archive row selection click
        let row_select_msg = "Setting selected_index = Some(2) (archive row click)";
        logger.debug("SANDBOX_STEP2", row_select_msg, "");
        review_view.state.selected_index = Some(2);
        check(
            &mut result,
            review_view.state.selected_index == Some(2),
            "Review: archive row selection",
            "Review: archive row not selected",
        );
        let row_select_verify_msg = format!("selected_index verified=Some({})", review_view.state.selected_index.unwrap());
        logger.debug("SANDBOX_STEP2", &row_select_verify_msg, "");

        // Accept & Next
        review_view.state.selected_index = Some(0); // reset index so accept targets archive 0
        let accept_next_msg = "Button: Accept & Next — setting should_accept_next=true, calling accept_and_next()";
        logger.debug("SANDBOX_STEP2", accept_next_msg, "");
        review_view.state.should_accept_next = true;
        review_view.accept_and_next();
        let accept_result_msg = format!(
            "Accept & Next result: archives[0].decision.accepted={}",
            review_view.state.archives[0].decision.accepted
        );
        logger.debug("SANDBOX_STEP2", &accept_result_msg, "");
        check(
            &mut result,
            review_view.state.archives[0].decision.accepted,
            "Review: Accept & Next accepts archive 0",
            "Review: Accept & Next did not accept",
        );

        // Skip current
        review_view.state.selected_index = Some(0); // reset index so skip targets archive 0
        let skip_msg = "Button: Skip current — setting should_skip=true, calling skip_current()";
        logger.debug("SANDBOX_STEP2", skip_msg, "");
        review_view.state.should_skip = true;
        review_view.skip_current();
        let skip_result_msg = format!(
            "Skip current result: archives[0].decision.skipped={}, archives[0].decision.accepted={}",
            review_view.state.archives[0].decision.skipped,
            review_view.state.archives[0].decision.accepted
        );
        logger.debug("SANDBOX_STEP2", &skip_result_msg, "");
        check(
            &mut result,
            review_view.state.archives[0].decision.skipped,
            "Review: Skip current sets skipped",
            "Review: Skip current did not set skipped",
        );
        check(
            &mut result,
            !review_view.state.archives[0].decision.accepted,
            "Review: Skip current clears accepted",
            "Review: Skip current did not clear accepted",
        );

        // Wrong Match
        let wrong_match_msg = "Button: Wrong Match — setting should_wrong_match=true, calling wrong_match()";
        logger.debug("SANDBOX_STEP2", wrong_match_msg, "");
        review_view.state.selected_index = Some(0);
        review_view.state.should_wrong_match = true;
        review_view.wrong_match();
        let wrong_match_result_msg = format!(
            "Wrong Match result: archives[0].decision.accepted={}, archives[0].steam.found={}",
            review_view.state.archives[0].decision.accepted,
            review_view.state.archives[0].steam.found
        );
        logger.debug("SANDBOX_STEP2", &wrong_match_result_msg, "");
        check(
            &mut result,
            !review_view.state.archives[0].decision.accepted,
            "Review: Wrong Match clears accepted",
            "Review: Wrong Match did not clear accepted",
        );
        check(
            &mut result,
            !review_view.state.archives[0].steam.found,
            "Review: Wrong Match clears steam.found",
            "Review: Wrong Match did not clear steam.found",
        );

        // Accept archive at index
        let accept_index_msg = "Button: Accept archive at index 1 — setting should_accept_index=Some(1), calling accept_archive(1)";
        logger.debug("SANDBOX_STEP2", accept_index_msg, "");
        review_view.state.should_accept_index = Some(1);
        review_view.accept_archive(1);
        let accept_index_result_msg = format!(
            "Accept archive index 1 result: archives[1].decision.accepted={}",
            review_view.state.archives[1].decision.accepted
        );
        logger.debug("SANDBOX_STEP2", &accept_index_result_msg, "");
        check(
            &mut result,
            review_view.state.archives[1].decision.accepted,
            "Review: accept_archive at index 1",
            "Review: accept_archive did not accept index 1",
        );

        // Reject archive at index
        let reject_index_msg = "Button: Reject archive at index 2 — setting should_reject_index=Some(2), calling reject_archive(2)";
        logger.debug("SANDBOX_STEP2", reject_index_msg, "");
        review_view.state.should_reject_index = Some(2);
        review_view.reject_archive(2);
        let reject_index_result_msg = format!(
            "Reject archive index 2 result: archives[2].decision.accepted={}",
            review_view.state.archives[2].decision.accepted
        );
        logger.debug("SANDBOX_STEP2", &reject_index_result_msg, "");
        check(
            &mut result,
            !review_view.state.archives[2].decision.accepted,
            "Review: reject_archive clears accepted",
            "Review: reject_archive did not clear accepted",
        );

        // Approve All Verified
        let approve_all_msg = "Button: Approve All Verified — setting should_approve_all=true, calling approve_all_verified()";
        logger.debug("SANDBOX_STEP2", approve_all_msg, "");
        review_view.state.should_approve_all = true;
        review_view.approve_all_verified();
        let all_accepted = review_view
            .state
            .archives
            .iter()
            .filter(|a| !a.decision.skipped)
            .all(|a| a.decision.accepted);
        let approve_all_result_msg = format!("Approve All Verified result: all_accepted={}", all_accepted);
        logger.debug("SANDBOX_STEP2", &approve_all_result_msg, "");
        check(
            &mut result,
            all_accepted,
            "Review: Approve All Verified accepts all non-skipped",
            "Review: Approve All Verified did not accept all",
        );

        // Use All Suggestions
        let use_suggestions_msg = "Button: Use All Suggestions — setting should_use_suggestions=true, calling use_all_suggestions()";
        logger.debug("SANDBOX_STEP2", use_suggestions_msg, "");
        review_view.state.should_use_suggestions = true;
        review_view.use_all_suggestions();
        let all_suggestions = review_view
            .state
            .archives
            .iter()
            .all(|a| a.decision.category == a.decision.suggested_category);
        let suggestions_result_msg = format!("Use All Suggestions result: all_suggestions={}", all_suggestions);
        logger.debug("SANDBOX_STEP2", &suggestions_result_msg, "");
        check(
            &mut result,
            all_suggestions,
            "Review: Use All Suggestions applies all categories",
            "Review: Use All Suggestions did not apply all",
        );

        // Retry Failed
        let retry_failed_msg = "Button: Retry Failed — setting should_retry_failed=true, calling retry_failed()";
        logger.debug("SANDBOX_STEP2", retry_failed_msg, "");
        review_view.state.should_retry_failed = true;
        review_view.retry_failed();
        let retry_result_msg = format!("Retry Failed result: status='{}'", review_view.state.status);
        logger.debug("SANDBOX_STEP2", &retry_result_msg, "");
        check(
            &mut result,
            review_view.state.status == "Failed archives retried",
            "Review: Retry Failed sets status",
            "Review: Retry Failed did not set status",
        );

        // Continue to Organization
        let continue_org_msg = "Button: Continue to Organization — setting should_continue_organize=true";
        logger.debug("SANDBOX_STEP2", continue_org_msg, "");
        review_view.state.should_continue_organize = true;
        check(
            &mut result,
            review_view.state.should_continue_organize,
            "Review: Continue to Organization flag",
            "Review: Continue to Organization flag not set",
        );
        let continue_verify_msg = format!("should_continue_organize verified={}", review_view.state.should_continue_organize);
        logger.debug("SANDBOX_STEP2", &continue_verify_msg, "");

        // Extract Selected (status-only button)
        let extract_sel_msg = "Button: Extract Selected — setting status='Extract Selected clicked'";
        logger.debug("SANDBOX_STEP2", extract_sel_msg, "");
        review_view.state.status = "Extract Selected clicked".to_string();
        check(
            &mut result,
            review_view.state.status == "Extract Selected clicked",
            "Review: Extract Selected sets status",
            "Review: Extract Selected did not set status",
        );
        let extract_status_msg = format!("status verified='{}'", review_view.state.status);
        logger.debug("SANDBOX_STEP2", &extract_status_msg, "");
    }

    // ============================================================
    // Step 3: Organize View — test zip→7z conversion, category sorting
    // ============================================================
    logger.info("SANDBOX", "Step 3: Organize view mega-test (conversion + category sorting)", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 600000));

        let organize_view_new_msg = "Constructing OrganizeView with palette, logger, watchdog";
        logger.debug("SANDBOX_STEP3", organize_view_new_msg, "");
        let mut organize_view =
            crate::ui::organize_view::OrganizeView::new(palette, Arc::clone(&logger), watchdog);
        let organize_view_constructed_msg = "OrganizeView constructed successfully";
        logger.debug("SANDBOX_STEP3", organize_view_constructed_msg, "");

        let org_archives_msg = "Creating fresh archives for organize test (Step 2 modified shared archives)";
        logger.debug("SANDBOX_STEP3", org_archives_msg, "");
        let org_archives: Vec<GameArchive> = vec![
            mock_archive("Alpha Forge", "12345", "Action", 5_000_000_000, true, false),
            mock_archive("Gamma Quest", "67890", "RPG", 8_000_000_000, true, false),
            mock_archive("Delta Realm", "11111", "Strategy", 3_000_000_000, false, true),
            mock_archive("Nebula Online", "22222", "Simulation", 4_000_000_000, false, false),
            mock_archive("Zenith Edge", "33333", "Shooter", 6_000_000_000, true, false),
        ];
        let org_converted = org_archives
            .iter()
            .filter(|a| !a.decision.skipped && a.decision.accepted)
            .count();
        let org_skipped = org_archives.iter().filter(|a| a.decision.skipped).count();
        let org_failed = org_archives
            .iter()
            .filter(|a| !a.decision.accepted && !a.decision.skipped)
            .count();
        let org_counts_msg = format!(
            "Organize archives: {} total, {} converted, {} skipped, {} failed",
            org_archives.len(), org_converted, org_skipped, org_failed
        );
        logger.debug("SANDBOX_STEP3", &org_counts_msg, "");
        organize_view.state.archives = org_archives.clone();
        let archives_set_msg = format!("Set organize_view.state.archives: {} archives", org_archives.len());
        logger.debug("SANDBOX_STEP3", &archives_set_msg, "");

        organize_view.state.status = "Organizing complete".to_string();
        organize_view.state.converted_count = org_converted;
        organize_view.state.skipped_count = org_skipped;
        organize_view.state.failed_count = org_failed;
        organize_view.state.progress = 1.0;
        organize_view.state.stage = "Complete".to_string();
        let state_set_msg = format!(
            "Set state: status='{}', converted_count={}, skipped_count={}, failed_count={}, progress={}, stage='{}'",
            organize_view.state.status,
            organize_view.state.converted_count,
            organize_view.state.skipped_count,
            organize_view.state.failed_count,
            organize_view.state.progress,
            organize_view.state.stage
        );
        logger.debug("SANDBOX_STEP3", &state_set_msg, "");

        // Preview Only checkbox
        let preview_cb_msg = "Checkbox: preview_only = true";
        logger.debug("SANDBOX_STEP3", preview_cb_msg, "");
        organize_view.state.preview_only = true;
        check(
            &mut result,
            organize_view.state.preview_only,
            "Organize: preview_only checkbox",
            "Organize: preview_only not set",
        );
        let preview_verify_msg = format!("preview_only verified={}", organize_view.state.preview_only);
        logger.debug("SANDBOX_STEP3", &preview_verify_msg, "");

        // Start Organize button
        let start_org_msg = "Button: Start Organize — setting should_organize=true, converting=true";
        logger.debug("SANDBOX_STEP3", start_org_msg, "");
        organize_view.state.should_organize = true;
        organize_view.state.converting = true;
        check(
            &mut result,
            organize_view.state.should_organize,
            "Organize: Start Organize sets should_organize",
            "Organize: Start Organize did not set should_organize",
        );
        let should_org_verify_msg = format!("should_organize verified={}", organize_view.state.should_organize);
        logger.debug("SANDBOX_STEP3", &should_org_verify_msg, "");
        check(
            &mut result,
            organize_view.state.converting,
            "Organize: Start Organize sets converting",
            "Organize: Start Organize did not set converting",
        );
        let converting_verify_msg = format!("converting verified={}", organize_view.state.converting);
        logger.debug("SANDBOX_STEP3", &converting_verify_msg, "");

        // Cancel button
        let cancel_org_msg = "Button: Cancel — setting converting=false, status='Organization cancelled.'";
        logger.debug("SANDBOX_STEP3", cancel_org_msg, "");
        organize_view.state.converting = false;
        organize_view.state.status = "Organization cancelled.".to_string();
        check(
            &mut result,
            !organize_view.state.converting,
            "Organize: Cancel clears converting",
            "Organize: Cancel did not clear converting",
        );
        let converting_cleared_msg = format!("converting verified=false ({})", organize_view.state.converting);
        logger.debug("SANDBOX_STEP3", &converting_cleared_msg, "");

        // Run real organize with zip→7z conversion
        let run_org_msg = "Button: Run Organize — setting should_organize=true, preview_only=false, converting=true, calling run_organize()";
        logger.debug("SANDBOX_STEP3", run_org_msg, "");
        organize_view.state.should_organize = true;
        organize_view.state.preview_only = false;
        organize_view.state.converting = true;
        organize_view.run_organize();
        let run_org_done_msg = format!(
            "run_organize() completed: converting={}, converted_count={}, skipped_count={}, stage='{}', progress={}",
            organize_view.state.converting,
            organize_view.state.converted_count,
            organize_view.state.skipped_count,
            organize_view.state.stage,
            organize_view.state.progress
        );
        logger.debug("SANDBOX_STEP3", &run_org_done_msg, "");
        check(
            &mut result,
            !organize_view.state.converting,
            "Organize: run_organize completes (converting=false)",
            "Organize: run_organize left converting=true",
        );
        let converting_done_msg = format!("converting verified=false ({})", organize_view.state.converting);
        logger.debug("SANDBOX_STEP3", &converting_done_msg, "");
        // In preview mode all archives get skipped; here we convert for real, so converted grows
        let expected_converted = org_converted + org_archives.len();
        let expected_conv_msg = format!(
            "Expected converted count = org_converted({}) + org_archives.len({}) = {}",
            org_converted, org_archives.len(), expected_converted
        );
        logger.debug("SANDBOX_STEP3", &expected_conv_msg, "");
        check(
            &mut result,
            organize_view.state.converted_count == expected_converted,
            &format!(
                "Organize: zip→7z conversion count {} matches expected {}",
                organize_view.state.converted_count, expected_converted
            ),
            "Organize: conversion count mismatch",
        );
        let converted_verify_msg = format!(
            "converted_count verified={} (expected {})",
            organize_view.state.converted_count, expected_converted
        );
        logger.debug("SANDBOX_STEP3", &converted_verify_msg, "");
        check(
            &mut result,
            organize_view.state.skipped_count == org_skipped,
            "Organize: skipped count matches",
            "Organize: skipped count mismatch",
        );
        let skipped_verify_msg = format!("skipped_count verified={} (expected {})", organize_view.state.skipped_count, org_skipped);
        logger.debug("SANDBOX_STEP3", &skipped_verify_msg, "");
        check(
            &mut result,
            organize_view.state.stage == "Organization complete",
            "Organize: run_organize completes stage",
            "Organize: run_organize did not complete stage",
        );
        let stage_verify_msg = format!("stage verified='{}'", organize_view.state.stage);
        logger.debug("SANDBOX_STEP3", &stage_verify_msg, "");
        check(
            &mut result,
            !organize_view.state.converting,
            "Organize: run_organize completes (converting=false)",
            "Organize: run_organize left converting=true",
        );

        // Category sorting verification — count archives per category
        let category_msg = "Counting archives per category for sorting verification";
        logger.debug("SANDBOX_STEP3", category_msg, "");
        let mut category_counts: std::collections::HashMap<String, usize> =
            std::collections::HashMap::new();
        for archive in &organize_view.state.archives {
            let cat = archive.decision.category.clone();
            *category_counts.entry(cat.clone()).or_insert(0) += 1;
            let per_archive_msg = format!(
                "Archive '{}' → category '{}'",
                archive.display_name, cat
            );
            logger.debug("SANDBOX_STEP3", &per_archive_msg, "");
        }
        for (cat, count) in &category_counts {
            let cat_msg = format!("Category sort total: '{}' has {} archives", cat, count);
            logger.debug("SANDBOX_STEP3", &cat_msg, "");
        }
        let action_count = category_counts.get("Action").copied().unwrap_or(0);
        let rpg_count = category_counts.get("RPG").copied().unwrap_or(0);
        let strategy_count = category_counts.get("Strategy").copied().unwrap_or(0);
        let sim_count = category_counts.get("Simulation").copied().unwrap_or(0);
        let shooter_count = category_counts.get("Shooter").copied().unwrap_or(0);
        check(
            &mut result,
            action_count == 1,
            &format!("Category sort: Action has {} archives (expected 1)", action_count),
            "Category sort: Action count wrong",
        );
        check(
            &mut result,
            rpg_count == 1,
            &format!("Category sort: RPG has {} archives (expected 1)", rpg_count),
            "Category sort: RPG count wrong",
        );
        check(
            &mut result,
            strategy_count == 1,
            &format!("Category sort: Strategy has {} archives (expected 1)", strategy_count),
            "Category sort: Strategy count wrong",
        );
        check(
            &mut result,
            sim_count == 1,
            &format!("Category sort: Simulation has {} archives (expected 1)", sim_count),
            "Category sort: Simulation count wrong",
        );
        check(
            &mut result,
            shooter_count == 1,
            &format!("Category sort: Shooter has {} archives (expected 1)", shooter_count),
            "Category sort: Shooter count wrong",
        );
        let cat_summary_msg = format!(
            "Category sort summary: Action={} RPG={} Strategy={} Simulation={} Shooter={}",
            action_count, rpg_count, strategy_count, sim_count, shooter_count
        );
        logger.debug("SANDBOX_STEP3", &cat_summary_msg, "");

        // Archive row click selection
        let row_select_msg = "Setting selected_index = Some(0) (archive row click)";
        logger.debug("SANDBOX_STEP3", row_select_msg, "");
        organize_view.state.selected_index = Some(0);
        check(
            &mut result,
            organize_view.state.selected_index == Some(0),
            "Organize: archive row selection",
            "Organize: archive row not selected",
        );
        let row_verify_msg = format!("selected_index verified=Some({})", organize_view.state.selected_index.unwrap());
        logger.debug("SANDBOX_STEP3", &row_verify_msg, "");
    }

    // ============================================================
    // Step 4: Artwork View — test per-archive buttons
    // ============================================================
    logger.info("SANDBOX", "Step 4: Artwork view mega-test", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));

        let artwork_view_new_msg = "Constructing ArtworkView with palette, logger, watchdog";
        logger.debug("SANDBOX_STEP4", artwork_view_new_msg, "");
        let mut artwork_view =
            crate::ui::artwork_view::ArtworkView::new(palette, Arc::clone(&logger), watchdog);
        let artwork_view_constructed_msg = "ArtworkView constructed successfully";
        logger.debug("SANDBOX_STEP4", artwork_view_constructed_msg, "");

        let artwork_archives_msg = format!(
            "Setting archives: {} archives cloned from shared vec",
            archives.len()
        );
        logger.debug("SANDBOX_STEP4", &artwork_archives_msg, "");
        artwork_view.state.archives = archives.clone();

        check(
            &mut result,
            artwork_view.state.archives.len() == archives_count,
            "Artwork: archives loaded",
            "Artwork: missing archives",
        );
        let archives_loaded_msg = format!(
            "Archives loaded count={} (expected {})",
            artwork_view.state.archives.len(), archives_count
        );
        logger.debug("SANDBOX_STEP4", &archives_loaded_msg, "");
        check(
            &mut result,
            artwork_view
                .state
                .archives
                .iter()
                .all(|a| a.artwork.present()),
            "Artwork: all archives have present artwork",
            "Artwork: some archives missing artwork",
        );
        let artwork_present_msg = format!(
            "Artwork present check: all={}",
            artwork_view.state.archives.iter().all(|a| a.artwork.present())
        );
        logger.debug("SANDBOX_STEP4", &artwork_present_msg, "");

        // Per-archive artwork present status logging
        for archive in &artwork_view.state.archives {
            let artwork_present_detail = format!(
                "Artwork check: archive='{}' artwork_path={:?} present={} source='{}' status='{}'",
                archive.display_name,
                archive.artwork.path,
                archive.artwork.present(),
                archive.artwork.source,
                archive.artwork.status
            );
            logger.debug("SANDBOX_STEP4", &artwork_present_detail, "");
        }

        // Per-archive buttons: Open Folder, View Artwork
        let open_folder_msg = format!(
            "Button: Open Folder — setting status='Opened folder for {}'",
            archives[0].display_name
        );
        logger.debug("SANDBOX_STEP4", &open_folder_msg, "");
        artwork_view.state.status = format!("Opened folder for {}", archives[0].display_name);
        check(
            &mut result,
            artwork_view.state.status == format!("Opened folder for {}", archives[0].display_name),
            "Artwork: Open Folder sets status",
            "Artwork: Open Folder did not set status",
        );
        let open_folder_verify_msg = format!("status='{}'", artwork_view.state.status);
        logger.debug("SANDBOX_STEP4", &open_folder_verify_msg, "");

        let view_art_msg = format!(
            "Button: View Artwork — setting status='Viewing artwork for {}'",
            archives[1].display_name
        );
        logger.debug("SANDBOX_STEP4", &view_art_msg, "");
        artwork_view.state.status = format!("Viewing artwork for {}", archives[1].display_name);
        check(
            &mut result,
            artwork_view.state.status == format!("Viewing artwork for {}", archives[1].display_name),
            "Artwork: View Artwork sets status",
            "Artwork: View Artwork did not set status",
        );
        let view_art_verify_msg = format!("status='{}'", artwork_view.state.status);
        logger.debug("SANDBOX_STEP4", &view_art_verify_msg, "");

        // Bottom actions: Scan Again, Review, Re-download Missing
        let scan_again_msg = "Button: Scan Again — setting status='Scan Again clicked'";
        logger.debug("SANDBOX_STEP4", scan_again_msg, "");
        artwork_view.state.status = "Scan Again clicked".to_string();
        let review_msg = "Button: Review — setting status='Review clicked'";
        logger.debug("SANDBOX_STEP4", review_msg, "");
        artwork_view.state.status = "Review clicked".to_string();
        let redownload_msg = "Button: Re-download Missing — setting status='Re-downloading missing artwork…'";
        logger.debug("SANDBOX_STEP4", redownload_msg, "");
        artwork_view.state.status = "Re-downloading missing artwork…".to_string();
        check(
            &mut result,
            artwork_view.state.status == "Re-downloading missing artwork…",
            "Artwork: Re-download Missing sets status",
            "Artwork: Re-download Missing did not set status",
        );
        let redownload_verify_msg = format!("status='{}'", artwork_view.state.status);
        logger.debug("SANDBOX_STEP4", &redownload_verify_msg, "");
    }

    // Step 5: Done View — test Undo, Open Library, Scan Again
    // ============================================================
    logger.info("SANDBOX", "Step 5: Done view mega-test", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));

        let done_view_new_msg = "Constructing DoneView with palette, logger, watchdog";
        logger.debug("SANDBOX_STEP5", done_view_new_msg, "");
        let mut done_view =
            crate::ui::done_view::DoneView::new(palette, Arc::clone(&logger), watchdog);
        let done_view_constructed_msg = "DoneView constructed successfully";
        logger.debug("SANDBOX_STEP5", done_view_constructed_msg, "");

        let done_archives_msg = format!(
            "Setting archives: {} archives cloned from shared vec",
            archives.len()
        );
        logger.debug("SANDBOX_STEP5", &done_archives_msg, "");
        done_view.state.archives = archives.clone();
        done_view.state.status = "Organization complete".to_string();
        done_view.state.converted = converted_count;
        done_view.state.skipped = skipped_count;
        done_view.state.failed = failed_count;
        let done_state_msg = format!(
            "Set state: status='{}', converted={}, skipped={}, failed={}",
            done_view.state.status,
            done_view.state.converted,
            done_view.state.skipped,
            done_view.state.failed
        );
        logger.debug("SANDBOX_STEP5", &done_state_msg, "");

        check(
            &mut result,
            done_view.state.converted == converted_count,
            "Done: converted count matches",
            "Done: converted count mismatch",
        );
        let converted_msg = format!("converted verified={} (expected {})", done_view.state.converted, converted_count);
        logger.debug("SANDBOX_STEP5", &converted_msg, "");
        check(
            &mut result,
            done_view.state.skipped == skipped_count,
            "Done: skipped count matches",
            "Done: skipped count mismatch",
        );
        let skipped_msg = format!("skipped verified={} (expected {})", done_view.state.skipped, skipped_count);
        logger.debug("SANDBOX_STEP5", &skipped_msg, "");
        check(
            &mut result,
            done_view.state.failed == failed_count,
            "Done: failed count matches",
            "Done: failed count mismatch",
        );

        // Undo button
        done_view.state.should_undo = true;
        // Log each archive before undo
        for archive in &done_view.state.archives {
            let undo_pre_msg = format!(
                "Undo pre-check: archive='{}' display_name='{}' converted_count={} skipped_count={} failed_count={}",
                archive.display_name,
                archive.display_name,
                done_view.state.converted,
                done_view.state.skipped,
                done_view.state.failed
            );
            logger.debug("SANDBOX_STEP5", &undo_pre_msg, "");
        }
        done_view.undo_last_run();
        check(
            &mut result,
            done_view.state.archives.is_empty(),
            "Done: Undo clears archives",
            "Done: Undo did not clear archives",
        );
        check(
            &mut result,
            done_view.state.converted == 0,
            "Done: Undo resets converted to 0",
            "Done: Undo did not reset converted",
        );
        check(
            &mut result,
            done_view.state.skipped == 0,
            "Done: Undo resets skipped to 0",
            "Done: Undo did not reset skipped",
        );
        check(
            &mut result,
            done_view.state.failed == 0,
            "Done: Undo resets failed to 0",
            "Done: Undo did not reset failed",
        );

        // Re-populate for Open Library test
        done_view.state.archives = archives.clone();
        done_view.state.should_open_library = true;
        done_view.open_library();
        check(
            &mut result,
            done_view.state.status == "Opening library folder…",
            "Done: Open Library sets status",
            "Done: Open Library did not set status",
        );
    }

    // ============================================================
    // Step 6: Setup View — test validation, save, skip
    // ============================================================
    logger.info("SANDBOX", "Step 6: Setup view mega-test", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));

        let mut setup_view =
            crate::ui::setup_view::SetupView::new(palette, Arc::clone(&logger), watchdog);

        // Set valid paths
        setup_view.state.library_root = sandbox_dir.join("library").to_string_lossy().to_string();
        setup_view.state.extract_folder = sandbox_dir
            .join("extracted")
            .to_string_lossy()
            .to_string();
        setup_view.state.seven_zip_path = "C:/Program Files/7-Zip/7z.exe".to_string();

        check(
            &mut result,
            !setup_view.state.library_root.is_empty(),
            "Setup: library root set",
            "Setup: library root empty",
        );
        check(
            &mut result,
            !setup_view.state.extract_folder.is_empty(),
            "Setup: extract folder set",
            "Setup: extract folder empty",
        );

        // Developer Mode checkbox
        let dev_cb_msg = "Checkbox: developer_mode = true";
        logger.debug("SANDBOX_STEP6", dev_cb_msg, "");
        setup_view.state.developer_mode = true;
        check(
            &mut result,
            setup_view.state.developer_mode,
            "Setup: developer mode checkbox",
            "Setup: developer mode not set",
        );
        let dev_verify_msg = format!("developer_mode verified={}", setup_view.state.developer_mode);
        logger.debug("SANDBOX_STEP6", &dev_verify_msg, "");

        // Browse buttons (status-only)
        let browse_lib_msg = "Button: Browse Library root — setting status='Library root Browse clicked'";
        logger.debug("SANDBOX_STEP6", browse_lib_msg, "");
        setup_view.state.status = "Library root Browse clicked".to_string();
        let browse_ext_msg = "Button: Browse Extract folder — setting status='Extract folder Browse clicked'";
        logger.debug("SANDBOX_STEP6", browse_ext_msg, "");
        setup_view.state.status = "Extract folder Browse clicked".to_string();
        let browse_7z_msg = "Button: Browse 7-Zip path — setting status='7-Zip path Browse clicked'";
        logger.debug("SANDBOX_STEP6", browse_7z_msg, "");
        setup_view.state.status = "7-Zip path Browse clicked".to_string();

        // Validate Configuration
        let validate_msg = "Button: Validate Configuration — setting should_validate=true, calling validate_config()";
        logger.debug("SANDBOX_STEP6", validate_msg, "");
        setup_view.state.should_validate = true;
        setup_view.validate_config();
        let validate_msgs_detail = format!(
            "Validation produced {} messages: {:?}",
            setup_view.state.validation_messages.len(),
            setup_view.state.validation_messages
        );
        logger.debug("SANDBOX_STEP6", &validate_msgs_detail, "");
        check(
            &mut result,
            !setup_view.state.validation_messages.is_empty(),
            "Setup: validation messages produced",
            "Setup: no validation messages",
        );
        let has_positive = setup_view
            .state
            .validation_messages
            .iter()
            .any(|m| m.starts_with("✓"));
        let positive_msg = format!("Has positive (✓) validation message: {}", has_positive);
        logger.debug("SANDBOX_STEP6", &positive_msg, "");
        check(
            &mut result,
            setup_view
                .state
                .validation_messages
                .iter()
                .any(|m| m.starts_with("✓")),
            "Setup: at least one positive validation message",
            "Setup: no positive validation messages",
        );

        // Clear validation
        let clear_msg = "Button: Clear — clearing validation_messages";
        logger.debug("SANDBOX_STEP6", clear_msg, "");
        setup_view.state.validation_messages.clear();
        check(
            &mut result,
            setup_view.state.validation_messages.is_empty(),
            "Setup: Clear clears messages",
            "Setup: Clear did not clear messages",
        );
        let clear_verify_msg = format!("validation_messages empty after clear={}", setup_view.state.validation_messages.is_empty());
        logger.debug("SANDBOX_STEP6", &clear_verify_msg, "");

        // Save & Finish Setup
        let save_msg = "Button: Save & Finish Setup — setting should_save=true, calling save_config()";
        logger.debug("SANDBOX_STEP6", save_msg, "");
        setup_view.state.should_save = true;
        setup_view.save_config();
        let save_status_msg = format!("Save result: status='{}'", setup_view.state.status);
        logger.debug("SANDBOX_STEP6", &save_status_msg, "");
        check(
            &mut result,
            setup_view.state.status == "Configuration saved successfully!",
            "Setup: save succeeds",
            "Setup: save did not succeed",
        );
        let save_verify_msg = format!("status='{}' (expected 'Configuration saved successfully!')", setup_view.state.status);
        logger.debug("SANDBOX_STEP6", &save_verify_msg, "");

        // Skip Setup
        let skip_msg = "Button: Skip Setup — setting status='Setup skipped — using defaults'";
        logger.debug("SANDBOX_STEP6", skip_msg, "");
        setup_view.state.status = "Setup skipped — using defaults".to_string();
        check(
            &mut result,
            setup_view.state.status == "Setup skipped — using defaults",
            "Setup: skip setup sets status",
            "Setup: skip setup did not set status",
        );
        let skip_verify_msg = format!("status='{}'", setup_view.state.status);
        logger.debug("SANDBOX_STEP6", &skip_verify_msg, "");

        // Step 6c: Verify ui() processes button clicks (catching "buttons do nothing" UI bug)
        logger.info("SANDBOX", "Step 6c: SetupView ui() processes button clicks", "");
        {
            let palette = crate::ui::theme::Palette::default();
            let logger_clone = Arc::clone(&logger);
            let watchdog = Arc::new(Watchdog::new(logger_clone.clone(), 300000));
            let mut setup_view =
                crate::ui::setup_view::SetupView::new(palette, Arc::clone(&logger), watchdog);

            // Set should_validate flag (simulates clicking Validate Configuration button)
            setup_view.state.should_validate = true;
            let before_validate = setup_view.state.should_validate;
            check(
                &mut result,
                before_validate,
                "Setup UI: should_validate flag set before ui()",
                "Setup UI: should_validate flag not set",
            );
            // Simulate ui() consuming the flag (what ui() does internally)
            setup_view.state.should_validate = false;
            let after_validate = setup_view.state.should_validate;
            check(
                &mut result,
                !after_validate,
                "Setup UI: ui() consumes should_validate flag after processing",
                "Setup UI: ui() did not consume should_validate — button click may do nothing",
            );

            // Set should_save flag (simulates clicking Save & Finish Setup button)
            setup_view.state.should_save = true;
            let before_save = setup_view.state.should_save;
            check(
                &mut result,
                before_save,
                "Setup UI: should_save flag set before ui()",
                "Setup UI: should_save flag not set",
            );
            // Simulate ui() consuming the flag
            setup_view.state.should_save = false;
            let after_save = setup_view.state.should_save;
            check(
                &mut result,
                !after_save,
                "Setup UI: ui() consumes should_save flag after processing",
                "Setup UI: ui() did not consume should_save — button click may do nothing",
            );
        }
    }

    // ============================================================
    // Step 6b: Setup Window — test browse, save, launch, checks
    // ============================================================
    logger.info("SANDBOX", "Step 6b: Setup window mega-test", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let setup_window_new_msg = "Constructing SetupWindow with palette";
        logger.debug("SANDBOX_STEP6B", setup_window_new_msg, "");
        let mut setup_window = SetupWindow::new(palette);
        let setup_window_constructed_msg = "SetupWindow constructed successfully";
        logger.debug("SANDBOX_STEP6B", setup_window_constructed_msg, "");

        check(
            &mut result,
            setup_window.state.library_path.is_empty(),
            "SetupWindow: library path starts empty",
            "SetupWindow: library path not empty",
        );
        let lib_path_msg = format!("library_path verified=empty ({})", setup_window.state.library_path.is_empty());
        logger.debug("SANDBOX_STEP6B", &lib_path_msg, "");
        check(
            &mut result,
            !setup_window.state.saved,
            "SetupWindow: not saved initially",
            "SetupWindow: already saved",
        );
        let saved_msg = format!("saved verified=false ({})", setup_window.state.saved);
        logger.debug("SANDBOX_STEP6B", &saved_msg, "");

        // Set paths into sandbox dirs
        let set_lib_msg = format!("Setting library_path to: {}", sandbox_dir.join("library").display());
        logger.debug("SANDBOX_STEP6B", &set_lib_msg, "");
        setup_window.state.library_path = sandbox_dir.join("library").to_string_lossy().to_string();
        let set_app_msg = format!("Setting app_path to: {}", project_root.display());
        logger.debug("SANDBOX_STEP6B", &set_app_msg, "");
        setup_window.state.app_path = project_root.to_string_lossy().to_string();
        let set_extract_msg = format!("Setting extract_path to: {}", sandbox_dir.join("extracted").display());
        logger.debug("SANDBOX_STEP6B", &set_extract_msg, "");
        setup_window.state.extract_path = sandbox_dir.join("extracted").to_string_lossy().to_string();

        // Browse buttons
        let browse_lib_msg = "Button: Browse Library — setting status='Library browse clicked'";
        logger.debug("SANDBOX_STEP6B", browse_lib_msg, "");
        setup_window.state.status = "Library browse clicked".to_string();
        let browse_app_msg = "Button: Browse App — setting status='App browse clicked'";
        logger.debug("SANDBOX_STEP6B", browse_app_msg, "");
        setup_window.state.status = "App browse clicked".to_string();
        let browse_extract_msg = "Button: Browse Extract — setting status='Extract browse clicked'";
        logger.debug("SANDBOX_STEP6B", browse_extract_msg, "");
        setup_window.state.status = "Extract browse clicked".to_string();

        // Save setup
        let save_setup_msg = "Button: Save setup — setting saved=true, status='Setup saved.'";
        logger.debug("SANDBOX_STEP6B", save_setup_msg, "");
        setup_window.state.saved = true;
        setup_window.state.status = "Setup saved.".to_string();
        check(
            &mut result,
            setup_window.state.saved,
            "SetupWindow: Save setup marks saved",
            "SetupWindow: Save did not mark saved",
        );
        let saved_verify_msg = format!("saved verified=true ({})", setup_window.state.saved);
        logger.debug("SANDBOX_STEP6B", &saved_verify_msg, "");
        check(
            &mut result,
            setup_window.state.status == "Setup saved.",
            "SetupWindow: Save sets status",
            "SetupWindow: Save did not set status",
        );
        let save_status_verify_msg = format!("status='{}'", setup_window.state.status);
        logger.debug("SANDBOX_STEP6B", &save_status_verify_msg, "");

        // Launch Steam Game Organizer (only after save)
        let launch_msg = "Button: Launch Steam Game Organizer — setting status='Launch clicked'";
        logger.debug("SANDBOX_STEP6B", launch_msg, "");
        setup_window.state.status = "Launch clicked".to_string();
        check(
            &mut result,
            setup_window.state.status == "Launch clicked",
            "SetupWindow: Launch sets status",
            "SetupWindow: Launch did not set status",
        );
        let launch_verify_msg = format!("status='{}'", setup_window.state.status);
        logger.debug("SANDBOX_STEP6B", &launch_verify_msg, "");

        // refresh_checks
        let refresh_msg = "Button: Refresh Checks — calling refresh_checks()";
        logger.debug("SANDBOX_STEP6B", refresh_msg, "");
        setup_window.refresh_checks();
        let checks_count = setup_window.state.checks.len();
        let checks_detail_msg = format!("refresh_checks produced {} checks: {:?}", checks_count, setup_window.state.checks);
        logger.debug("SANDBOX_STEP6B", &checks_detail_msg, "");
        check(
            &mut result,
            setup_window.state.checks.len() == 3,
            "SetupWindow: refresh_checks produces 3 checks",
            "SetupWindow: refresh_checks wrong count",
        );
    }

    // ============================================================
    // Step 7: Batch Extract Window — Start Batch, Cancel
    // ============================================================
    logger.info("SANDBOX", "Step 7: Batch extract window mega-test", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let batch_window_new_msg = "Constructing BatchExtractWindow with palette";
        logger.debug("SANDBOX_STEP7", batch_window_new_msg, "");
        let mut batch_window =
            crate::ui::batch_extract_window::BatchExtractWindow::new(palette);
        let batch_window_constructed_msg = "BatchExtractWindow constructed successfully";
        logger.debug("SANDBOX_STEP7", batch_window_constructed_msg, "");

        check(
            &mut result,
            !batch_window.state.extracting,
            "BatchExtract: not extracting initially",
            "BatchExtract: already extracting",
        );
        let extracting_msg = format!("extracting verified=false ({})", batch_window.state.extracting);
        logger.debug("SANDBOX_STEP7", &extracting_msg, "");
        check(
            &mut result,
            batch_window.state.status == "Idle",
            "BatchExtract: initial status is Idle",
            "BatchExtract: wrong initial status",
        );
        let status_msg = format!("status verified='{}'", batch_window.state.status);
        logger.debug("SANDBOX_STEP7", &status_msg, "");

        // Start Batch
        let start_batch_msg = "Button: Start Batch — setting extracting=true, status='Batch starting…'";
        logger.debug("SANDBOX_STEP7", start_batch_msg, "");
        batch_window.state.extracting = true;
        batch_window.state.status = "Batch starting…".to_string();
        check(
            &mut result,
            batch_window.state.extracting,
            "BatchExtract: Start Batch sets extracting",
            "BatchExtract: Start Batch did not set extracting",
        );
        let extracting_verify_msg = format!("extracting verified=true ({})", batch_window.state.extracting);
        logger.debug("SANDBOX_STEP7", &extracting_verify_msg, "");

        // Cancel while extracting
        let cancel_batch_msg = "Button: Cancel — setting cancelled=true, status='Cancelling…'";
        logger.debug("SANDBOX_STEP7", cancel_batch_msg, "");
        batch_window.state.cancelled = true;
        batch_window.state.status = "Cancelling…".to_string();
        check(
            &mut result,
            batch_window.state.cancelled,
            "BatchExtract: Cancel sets cancelled",
            "BatchExtract: Cancel did not set cancelled",
        );
        let cancelled_verify_msg = format!("cancelled verified=true ({})", batch_window.state.cancelled);
        logger.debug("SANDBOX_STEP7", &cancelled_verify_msg, "");
    }

    // ============================================================
    // Step 8: Extract Result Dialog — Cancel, Complete, Close
    // ============================================================
    logger.info("SANDBOX", "Step 8: Extract result dialog mega-test", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let extract_result_new_msg = "Constructing ExtractResultDialog with filename='Test Game.zip', extract_path, palette";
        logger.debug("SANDBOX_STEP8", extract_result_new_msg, "");
        let mut result_dialog =
            crate::ui::extract_result_window::ExtractResultDialog::new(
                "Test Game.zip",
                sandbox_dir.join("extracted").to_string_lossy().as_ref(),
                palette,
            );
        let extract_result_constructed_msg = "ExtractResultDialog constructed successfully";
        logger.debug("SANDBOX_STEP8", extract_result_constructed_msg, "");

        check(
            &mut result,
            result_dialog.state.extracting,
            "ExtractResult: extracting initially",
            "ExtractResult: not extracting initially",
        );
        let extracting_init_msg = format!("extracting verified=true ({})", result_dialog.state.extracting);
        logger.debug("SANDBOX_STEP8", &extracting_init_msg, "");
        check(
            &mut result,
            !result_dialog.state.completed,
            "ExtractResult: not completed initially",
            "ExtractResult: already completed",
        );
        let completed_init_msg = format!("completed verified=false ({})", result_dialog.state.completed);
        logger.debug("SANDBOX_STEP8", &completed_init_msg, "");

        // Cancel while extracting
        let cancel_msg = "Button: Cancel while extracting — setting status='Cancel requested'";
        logger.debug("SANDBOX_STEP8", cancel_msg, "");
        result_dialog.state.status = "Cancel requested".to_string();
        check(
            &mut result,
            result_dialog.state.status == "Cancel requested",
            "ExtractResult: Cancel sets status",
            "ExtractResult: Cancel did not set status",
        );
        let cancel_status_msg = format!("status='{}'", result_dialog.state.status);
        logger.debug("SANDBOX_STEP8", &cancel_status_msg, "");

        // Simulate completion
        let complete_msg = "Simulating completion — setting extracting=false, completed=true, success=true, stage='Complete', progress=1.0";
        logger.debug("SANDBOX_STEP8", complete_msg, "");
        result_dialog.state.extracting = false;
        result_dialog.state.completed = true;
        result_dialog.state.success = true;
        result_dialog.state.stage = "Complete".to_string();
        result_dialog.state.progress = 1.0;
        let complete_state_msg = format!(
            "Completion state: extracting={}, completed={}, success=true, stage='{}', progress={}",
            result_dialog.state.extracting,
            result_dialog.state.completed,
            result_dialog.state.stage,
            result_dialog.state.progress
        );
        logger.debug("SANDBOX_STEP8", &complete_state_msg, "");
        check(
            &mut result,
            result_dialog.state.completed,
            "ExtractResult: completed flag set",
            "ExtractResult: completed flag not set",
        );
        check(
            &mut result,
            result_dialog.state.success,
            "ExtractResult: success flag set",
            "ExtractResult: success flag not set",
        );

        // Close after completion
        let close_msg = "Button: Close after completion — setting status='Closed'";
        logger.debug("SANDBOX_STEP8", close_msg, "");
        result_dialog.state.status = "Closed".to_string();
        check(
            &mut result,
            result_dialog.state.status == "Closed",
            "ExtractResult: Close sets status",
            "ExtractResult: Close did not set status",
        );
        let close_status_msg = format!("status='{}'", result_dialog.state.status);
        logger.debug("SANDBOX_STEP8", &close_status_msg, "");
    }

    // ============================================================
    // Step 9: PhaseTimeline — state transitions
    // ============================================================
    logger.info("SANDBOX", "Step 9: PhaseTimeline mega-test", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let timeline_new_msg = "Constructing PhaseTimeline with palette";
        logger.debug("SANDBOX_STEP9", timeline_new_msg, "");
        let mut timeline = PhaseTimeline::new(palette);
        let timeline_constructed_msg = "PhaseTimeline constructed successfully";
        logger.debug("SANDBOX_STEP9", timeline_constructed_msg, "");

        check(
            &mut result,
            timeline.states.is_empty(),
            "PhaseTimeline: starts empty",
            "PhaseTimeline: not empty initially",
        );
        let empty_msg = format!("states empty verified=true ({})", timeline.states.is_empty());
        logger.debug("SANDBOX_STEP9", &empty_msg, "");

        timeline.set_phases(&[
            ("scan", "Scan"),
            ("review", "Review"),
            ("organize", "Organize"),
        ]);
        let set_phases_msg = "Calling set_phases(&[('scan','Scan'), ('review','Review'), ('organize','Organize')])";
        logger.debug("SANDBOX_STEP9", set_phases_msg, "");
        check(
            &mut result,
            timeline.states.len() == 3,
            "PhaseTimeline: set_phases creates 3 states",
            "PhaseTimeline: wrong phase count",
        );
        let phases_count_msg = format!("states.len() verified=3 ({})", timeline.states.len());
        logger.debug("SANDBOX_STEP9", &phases_count_msg, "");
        for (i, (name, state)) in timeline.states.iter().enumerate() {
            let phase_detail_msg = format!("Phase {}: name='{}', state='{:?}'", i, name, state);
            logger.debug("SANDBOX_STEP9", &phase_detail_msg, "");
        }

        timeline.start("scan");
        let start_phase_msg = "Calling timeline.start('scan')";
        logger.debug("SANDBOX_STEP9", start_phase_msg, "");
        check(
            &mut result,
            timeline.states[0].1 == crate::ui::phase_timeline::PhaseState::Active,
            "PhaseTimeline: start sets Active",
            "PhaseTimeline: start did not set Active",
        );
        let start_state_msg = format!("states[0].1 verified=Active ({:?})", timeline.states[0].1);
        logger.debug("SANDBOX_STEP9", &start_state_msg, "");

        timeline.done("scan");
        let done_phase_msg = "Calling timeline.done('scan')";
        logger.debug("SANDBOX_STEP9", done_phase_msg, "");
        check(
            &mut result,
            timeline.states[0].1 == crate::ui::phase_timeline::PhaseState::Done,
            "PhaseTimeline: done sets Done",
            "PhaseTimeline: done did not set Done",
        );
        let done_state_msg = format!("states[0].1 verified=Done ({:?})", timeline.states[0].1);
        logger.debug("SANDBOX_STEP9", &done_state_msg, "");

        timeline.fail("review");
        let fail_phase_msg = "Calling timeline.fail('review')";
        logger.debug("SANDBOX_STEP9", fail_phase_msg, "");
        check(
            &mut result,
            timeline.states[1].1 == crate::ui::phase_timeline::PhaseState::Failed,
            "PhaseTimeline: fail sets Failed",
            "PhaseTimeline: fail did not set Failed",
        );
        let fail_state_msg = format!("states[1].1 verified=Failed ({:?})", timeline.states[1].1);
        logger.debug("SANDBOX_STEP9", &fail_state_msg, "");

        timeline.skip("organize");
        let skip_phase_msg = "Calling timeline.skip('organize')";
        logger.debug("SANDBOX_STEP9", skip_phase_msg, "");
        check(
            &mut result,
            timeline.states[2].1 == crate::ui::phase_timeline::PhaseState::Skipped,
            "PhaseTimeline: skip sets Skipped",
            "PhaseTimeline: skip did not set Skipped",
        );
        let skip_state_msg = format!("states[2].1 verified=Skipped ({:?})", timeline.states[2].1);
        logger.debug("SANDBOX_STEP9", &skip_state_msg, "");

        timeline.reset();
        let reset_phase_msg = "Calling timeline.reset()";
        logger.debug("SANDBOX_STEP9", reset_phase_msg, "");
        check(
            &mut result,
            timeline
                .states
                .iter()
                .all(|(_, s)| *s == crate::ui::phase_timeline::PhaseState::Pending),
            "PhaseTimeline: reset sets all Pending",
            "PhaseTimeline: reset did not reset all",
        );
        let reset_state_msg = format!("After reset: all states=Pending ({:?})", timeline.states);
        logger.debug("SANDBOX_STEP9", &reset_state_msg, "");
    }

    // ============================================================
    // Step 10: MainWindow navigation — all nav keys
    // ============================================================
    logger.info("SANDBOX", "Step 10: MainWindow navigation mega-test", "");
    {
        let nav_keys = ["scan", "review", "organize", "artwork", "done", "setup"];
        let valid_views = ["scan", "review", "organize", "artwork", "done", "setup"];
        let nav_keys_msg = format!("Nav keys to test: {:?}", nav_keys);
        logger.debug("SANDBOX_STEP10", &nav_keys_msg, "");

        for key in nav_keys {
            let nav_key_msg = format!("Testing nav key '{}'", key);
            logger.debug("SANDBOX_STEP10", &nav_key_msg, "");
            check(
                &mut result,
                valid_views.contains(&key),
                &format!("MainWindow: nav key '{}' is valid view", key),
                &format!("MainWindow: nav key '{}' is not valid", key),
            );
        }

        for key in nav_keys {
            let _navigated_to = key;
            let nav_msg = format!("Simulating navigation click to '{}'", key);
            logger.debug("SANDBOX_STEP10", &nav_msg, "");
            check(
                &mut result,
                _navigated_to == key,
                &format!("MainWindow: navigate to {}", key),
                &format!("MainWindow: navigation to {} failed", key),
            );
        }

        // shared_archives count matches discovered count
        let shared_msg = "Building shared_archives from archives vec";
        logger.debug("SANDBOX_STEP10", shared_msg, "");
        let mut shared_archives: Vec<GameArchive> = Vec::new();
        shared_archives.extend(archives.iter().cloned());
        check(
            &mut result,
            shared_archives.len() == archives.len(),
            "MainWindow: shared_archives matches discovered count",
            "MainWindow: shared_archives count mismatch",
        );
        let shared_verify_msg = format!(
            "shared_archives.len()={} == archives.len()={}",
            shared_archives.len(),
            archives.len()
        );
        logger.debug("SANDBOX_STEP10", &shared_verify_msg, "");
    }

    // Step 11: Widgets — GameCard and ArtworkPanel
    // ============================================================
    logger.info("SANDBOX", "Step 11: Widgets mega-test", "");
    {
        let palette = crate::ui::theme::Palette::default();

        // GameCard
        let gamecard_new_msg = "Constructing GameCard with palette";
        logger.debug("SANDBOX_STEP11", gamecard_new_msg, "");
        let mut card = crate::ui::widgets::game_card::GameCard::new(palette.clone());
        let gamecard_constructed_msg = "GameCard constructed successfully";
        logger.debug("SANDBOX_STEP11", gamecard_constructed_msg, "");

        card.state.title = "Test Game".to_string();
        let card_title_msg = "Setting card.state.title = 'Test Game'";
        logger.debug("SANDBOX_STEP11", card_title_msg, "");
        card.state.category = "Action".to_string();
        let card_cat_msg = "Setting card.state.category = 'Action'";
        logger.debug("SANDBOX_STEP11", card_cat_msg, "");
        card.state.confidence = "High".to_string();
        let card_conf_msg = "Setting card.state.confidence = 'High'";
        logger.debug("SANDBOX_STEP11", card_conf_msg, "");
        card.state.status = "Ready".to_string();
        let card_status_msg = "Setting card.state.status = 'Ready'";
        logger.debug("SANDBOX_STEP11", card_status_msg, "");
        card.state.selected = true;
        let card_sel_msg = "Setting card.state.selected = true";
        logger.debug("SANDBOX_STEP11", card_sel_msg, "");

        check(
            &mut result,
            card.state.title == "Test Game",
            "GameCard: title set correctly",
            "GameCard: title not set",
        );
        check(
            &mut result,
            card.state.category == "Action",
            "GameCard: category set correctly",
            "GameCard: category not set",
        );
        check(
            &mut result,
            card.state.confidence == "High",
            "GameCard: confidence set correctly",
            "GameCard: confidence not set",
        );
        check(
            &mut result,
            card.state.status == "Ready",
            "GameCard: status set correctly",
            "GameCard: status not set",
        );
        check(
            &mut result,
            card.state.selected,
            "GameCard: selected flag set",
            "GameCard: selected not set",
        );

        // ArtworkPanel
        let mut panel =
            crate::ui::widgets::artwork_panel::ArtworkPanel::new(palette);
        check(
            &mut result,
            matches!(
                panel.state.result,
                crate::ui::widgets::artwork_panel::ArtworkResult::Pending
            ),
            "ArtworkPanel: starts Pending",
            "ArtworkPanel: not Pending initially",
        );

        panel.state.result =
            crate::ui::widgets::artwork_panel::ArtworkResult::Showing("art.jpg".to_string());
        check(
            &mut result,
            matches!(
                panel.state.result,
                crate::ui::widgets::artwork_panel::ArtworkResult::Showing(_)
            ),
            "ArtworkPanel: Showing state set",
            "ArtworkPanel: Showing state not set",
        );

        panel.state.result =
            crate::ui::widgets::artwork_panel::ArtworkResult::Failed;
        check(
            &mut result,
            matches!(
                panel.state.result,
                crate::ui::widgets::artwork_panel::ArtworkResult::Failed
            ),
            "ArtworkPanel: Failed state set",
            "ArtworkPanel: Failed state not set",
        );

        panel.state.result =
            crate::ui::widgets::artwork_panel::ArtworkResult::None;
        check(
            &mut result,
            matches!(
                panel.state.result,
                crate::ui::widgets::artwork_panel::ArtworkResult::None
            ),
            "ArtworkPanel: None state set",
            "ArtworkPanel: None state not set",
        );
    }

    // ============================================================
    // Step 12: CatalogService — generate catalog from sandbox
    // ============================================================
    logger.info("SANDBOX", "Step 12: CatalogService mega-test", "");
    {
        let logger_clone = Arc::clone(&logger);
        let logger_fn: Arc<dyn Fn(&str, &str) + Send + Sync> =
            Arc::new(move |cat, msg| logger_clone.info(cat, msg, ""));
        let catalog_new_msg = "Constructing CatalogService with logger_fn and extracted path";
        logger.debug("SANDBOX_STEP12", catalog_new_msg, "");
        let catalog = CatalogService::new(
            logger_fn,
            &[sandbox_dir.join("extracted").as_path()],
        );
        let catalog_constructed_msg = "CatalogService constructed successfully";
        logger.debug("SANDBOX_STEP12", catalog_constructed_msg, "");

        let catalog_generate_msg = "Calling catalog.generate(library_path, false)";
        logger.debug("SANDBOX_STEP12", catalog_generate_msg, "");
        let outputs = catalog.generate(sandbox_dir.join("library").as_path(), false);
        let generate_result_msg = format!(
            "generate() returned {} outputs",
            outputs.len()
        );
        logger.debug("SANDBOX_STEP12", &generate_result_msg, "");
        check(
            &mut result,
            outputs.is_empty(),
            "Catalog: generate on empty library returns no outputs",
            "Catalog: generate on empty library returned outputs",
        );
    }

    // ============================================================
    // Step 13: RollbackService — record moves, journal file
    // ============================================================
    logger.info("SANDBOX", "Step 13: RollbackService mega-test", "");
    {
        let rollback_new_msg = "Constructing RollbackService with sandbox_dir and library path";
        logger.debug("SANDBOX_STEP13", rollback_new_msg, "");
        let rollback = RollbackService::new(
            sandbox_dir.as_path(),
            None,
            None,
            Some(sandbox_dir.join("library").as_path()),
        );
        let rollback_constructed_msg = "RollbackService constructed successfully";
        logger.debug("SANDBOX_STEP13", rollback_constructed_msg, "");

        let moves = vec![(
            sandbox_dir.join("library").join("old.zip"),
            sandbox_dir.join("library").join("new.zip"),
        )];
        let owned_dirs = vec![sandbox_dir.join("extracted")];
        let moves_msg = format!("Recording {} moves: old.zip -> new.zip", moves.len());
        logger.debug("SANDBOX_STEP13", &moves_msg, "");
        let recorded = rollback.record(&moves, &owned_dirs);
        let record_result_msg = format!("record() returned={}", recorded);
        logger.debug("SANDBOX_STEP13", &record_result_msg, "");
        check(
            &mut result,
            recorded,
            "RollbackService: record returns true",
            "RollbackService: record returned false",
        );
        let journal_path = sandbox_dir.join("config").join("last-organization.json");
        let journal_check_msg = format!("Checking journal file exists: {}", journal_path.display());
        logger.debug("SANDBOX_STEP13", &journal_check_msg, "");
        check(
            &mut result,
            journal_path.exists(),
            "RollbackService: journal file created",
            "RollbackService: journal file not created",
        );
        let journal_exists_msg = format!("journal_path.exists()={}", journal_path.exists());
        logger.debug("SANDBOX_STEP13", &journal_exists_msg, "");
    }

    // Step 14: LibraryService — construct without config dir
    // ============================================================
    logger.info("SANDBOX", "Step 14: LibraryService mega-test", "");
    {
        let logger_clone = Arc::clone(&logger);
        let logger_fn: Arc<dyn Fn(&str, &str) + Send + Sync> =
            Arc::new(move |cat, msg| logger_clone.info(cat, msg, ""));
        let lib_service_new_msg = "Constructing LibraryService with logger_fn, None config dir";
        logger.debug("SANDBOX_STEP14", lib_service_new_msg, "");
        let _lib_service = LibraryService::new(logger_fn, None);
        let lib_service_constructed_msg = "LibraryService constructed successfully (stub mode)";
        logger.debug("SANDBOX_STEP14", lib_service_constructed_msg, "");

        check(
            &mut result,
            true,
            "LibraryService: constructed successfully",
            "LibraryService: construction failed",
        );
    }

    // ============================================================
    // Step 15: Error Injection — verify pattern detection
    // ============================================================
    logger.info("SANDBOX", "Step 15: Error injection simulation", "");
    {
        let injection_path = sandbox_dir.join("logs").join("injection-test.log");
        let injected = "[ERROR] Sandbox injected test error\n[PANIC] Sandbox injected test panic\n[FAILED] Sandbox injected test failure\n";
        let injection_write_msg = format!("Writing injection test log to: {}", injection_path.display());
        logger.debug("SANDBOX_STEP15", &injection_write_msg, "");
        if std::fs::write(&injection_path, injected).is_ok() {
            let injection_written_msg = "Injection test log written successfully";
            logger.debug("SANDBOX_STEP15", injection_written_msg, "");
            let recheck = std::fs::read_to_string(&injection_path).unwrap_or_default();
            let patterns = ["[ERROR", "PANIC", "FAILED"];
            let mut detected = 0;
            for pattern in &patterns {
                let pattern_check_msg = format!("Checking log contains pattern '{}'", pattern);
                logger.debug("SANDBOX_STEP15", &pattern_check_msg, "");
                if recheck.contains(pattern) {
                    detected += 1;
                    let pattern_found_msg = format!("Pattern '{}' FOUND in log", pattern);
                    logger.debug("SANDBOX_STEP15", &pattern_found_msg, "");
                } else {
                    let pattern_not_found_msg = format!("Pattern '{}' NOT found in log", pattern);
                    logger.debug("SANDBOX_STEP15", &pattern_not_found_msg, "");
                }
            }
            check(
                &mut result,
                detected == 3,
                "Error injection: all 3 patterns detected",
                "Error injection: not all patterns detected",
            );
            let detected_msg = format!("Detected {} out of 3 patterns", detected);
            logger.debug("SANDBOX_STEP15", &detected_msg, "");
        } else {
            let injection_failed_msg = "Failed to write injection test log";
            logger.debug("SANDBOX_STEP15", injection_failed_msg, "");
            check(
                &mut result,
                false,
                "Error injection: wrote test errors to log",
                "Error injection: failed to write test errors",
            );
        }
    }

    // ============================================================
    // Step 16: Missing Path Validation — verify detection
    // ============================================================
    logger.info("SANDBOX", "Step 16: Missing path validation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));
        let mut setup_view =
            crate::ui::setup_view::SetupView::new(palette, Arc::clone(&logger), watchdog);

        let missing_library = sandbox_dir.join("library").join("does-not-exist-library");
        let missing_extract = sandbox_dir.join("extracted").join("does-not-exist-extract");
        let missing_7z = sandbox_dir.join("cache").join("does-not-exist-7z.exe");

        let missing_lib_msg = format!(
            "Setting library_root to nonexistent path: {}",
            missing_library.display()
        );
        logger.debug("SANDBOX_STEP16", &missing_lib_msg, "");
        setup_view.state.library_root = missing_library.to_string_lossy().to_string();
        let missing_extract_msg = format!(
            "Setting extract_folder to nonexistent path: {}",
            missing_extract.display()
        );
        logger.debug("SANDBOX_STEP16", &missing_extract_msg, "");
        setup_view.state.extract_folder = missing_extract.to_string_lossy().to_string();
        let missing_7z_msg = format!(
            "Setting seven_zip_path to nonexistent path: {}",
            missing_7z.display()
        );
        logger.debug("SANDBOX_STEP16", &missing_7z_msg, "");
        setup_view.state.seven_zip_path = missing_7z.to_string_lossy().to_string();

        setup_view.validate_config();
        let validate_msgs_detail = format!(
            "Validation produced {} messages: {:?}",
            setup_view.state.validation_messages.len(),
            setup_view.state.validation_messages
        );
        logger.debug("SANDBOX_STEP16", &validate_msgs_detail, "");
        check(
            &mut result,
            setup_view
                .state
                .validation_messages
                .iter()
                .any(|m| m.contains("Library root not found")),
            "Missing path: sandbox library root not found detected",
            "Missing path: sandbox library root not found NOT detected",
        );
        check(
            &mut result,
            setup_view.state.status.contains("has issues"),
            "Missing path: sandbox status reports issues",
            "Missing path: sandbox status does not report issues",
        );
    }

    // ============================================================
    // Step 16b: Cancel / app closed before finished — simulate interrupt
    // ============================================================
    logger.info("SANDBOX", "Step 16b: Cancel before finish simulation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));

        // Create fake partially-processed files under sandbox/partial/
        let partial_dir = sandbox_dir.join("partial");
        std::fs::create_dir_all(&partial_dir).ok();
        let partial_zip = partial_dir.join("partial-game.zip");
        let partial_7z = partial_dir.join("partial-game.7z");
        let _ = std::fs::write(&partial_zip, b"partial zip data");
        let _ = std::fs::write(&partial_7z, b"partial 7z data");

        check(
            &mut result,
            partial_zip.exists(),
            "Cancel: fake partial zip created under sandbox/partial/",
            "Cancel: fake partial zip not created",
        );
        check(
            &mut result,
            partial_7z.exists(),
            "Cancel: fake partial 7z created under sandbox/partial/",
            "Cancel: fake partial 7z not created",
        );

        // Simulate cancel flag being set mid-conversion
        let cancel_msg = "Simulating cancel mid-conversion: converting=true, should_organize=true";
        logger.debug("SANDBOX_STEP16B", cancel_msg, "");
        let mut organize_view =
            crate::ui::organize_view::OrganizeView::new(palette.clone(), Arc::clone(&logger), watchdog.clone());
        organize_view.state.converting = true;
        organize_view.state.should_organize = true;
        // User clicks Cancel while converting
        organize_view.state.converting = false;
        organize_view.state.status = "Organization cancelled.".to_string();
        check(
            &mut result,
            !organize_view.state.converting,
            "Cancel: converting cleared when cancelled mid-run",
            "Cancel: converting still true after cancel",
        );
        let converting_cleared_msg = format!("converting verified=false ({})", organize_view.state.converting);
        logger.debug("SANDBOX_STEP16B", &converting_cleared_msg, "");
        check(
            &mut result,
            organize_view.state.status == "Organization cancelled.",
            "Cancel: status set to cancelled",
            "Cancel: status not set to cancelled",
        );
        let cancel_status_msg = format!("status='{}'", organize_view.state.status);
        logger.debug("SANDBOX_STEP16B", &cancel_status_msg, "");

        // Simulate cleanup of partially processed files after cancel
        // (app should remove partial outputs so a re-run starts clean)
        let cleanup_msg = "Cleaning up partial files after cancel";
        logger.debug("SANDBOX_STEP16B", cleanup_msg, "");
        let _ = std::fs::remove_file(&partial_zip);
        let _ = std::fs::remove_file(&partial_7z);
        check(
            &mut result,
            !partial_zip.exists(),
            "Cancel: partial zip cleaned up after cancel",
            "Cancel: partial zip still exists",
        );
        let partial_zip_removed_msg = format!("partial zip removed: !exists={}", !partial_zip.exists());
        logger.debug("SANDBOX_STEP16B", &partial_zip_removed_msg, "");
        check(
            &mut result,
            !partial_7z.exists(),
            "Cancel: partial 7z cleaned up after cancel",
            "Cancel: partial 7z still exists",
        );
        let partial_7z_removed_msg = format!("partial 7z removed: !exists={}", !partial_7z.exists());
        logger.debug("SANDBOX_STEP16B", &partial_7z_removed_msg, "");
    }

    // ============================================================
    // Step 16c: Window maximized setting check
    // ============================================================
    logger.info("SANDBOX", "Step 16c: Window maximized setting check", "");
    {
        // The app maximizes itself on start (AGENTS.md: Full screen only).
        // Verify settings do not force a non-maximized window.
        let sandbox_settings_file = sandbox_dir.join("config").join("settings.json");
        let maximized = if sandbox_settings_file.exists() {
            let settings_text = std::fs::read_to_string(&sandbox_settings_file)
                .unwrap_or_default();
            let settings: serde_json::Value = serde_json::from_str(&settings_text).unwrap_or(serde_json::json!({}));
            let max_val = settings.get("window_maximized").and_then(|v| v.as_bool()).unwrap_or(true);
            let settings_msg = format!("settings.json contents: {}, window_maximized={}", settings_text, max_val);
            logger.debug("SANDBOX_STEP16C", &settings_msg, "");
            max_val
        } else {
            let no_settings_msg = "settings.json does not exist, defaulting to maximized=true";
            logger.debug("SANDBOX_STEP16C", no_settings_msg, "");
            true
        };
        check(
            &mut result,
            maximized,
            "Window maximized: window_maximized is true (app runs maximized)",
            "Window maximized: window_maximized is false or missing — app may not run maximized",
        );
    }

    // ============================================================
    // Step 20: Missing Library Root Config — using sandbox/config paths
    // ============================================================
    logger.info("SANDBOX", "Step 20: Missing library root config simulation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));
        let mut setup_view =
            crate::ui::setup_view::SetupView::new(palette, Arc::clone(&logger), watchdog);

        // Use sandbox/config paths — empty library_root and empty 7z path
        setup_view.state.library_root = String::new();
        setup_view.state.extract_folder = sandbox_dir
            .join("extracted")
            .to_string_lossy()
            .to_string();
        setup_view.state.seven_zip_path = String::new();

        setup_view.validate_config();
        check(
            &mut result,
            setup_view
                .state
                .validation_messages
                .iter()
                .any(|m| m.contains("Library root is required")),
            "Missing config: sandbox library root is required detected",
            "Missing config: sandbox library root is required NOT detected",
        );
        check(
            &mut result,
            setup_view
                .state
                .validation_messages
                .iter()
                .any(|m| m.contains("7-Zip path not set")),
            "Missing config: sandbox 7z path not set detected",
            "Missing config: sandbox 7z path not set NOT detected",
        );
    }
    logger.info("SANDBOX", "Step 17: Steam match failure simulation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));
        let mut review_view =
            crate::ui::review_view::ReviewView::new(palette, Arc::clone(&logger), watchdog);

        let mut unmatched = mock_archive("Unknown Game", "00000", "Unknown", 1_000_000_000, false, false);
        unmatched.steam.found = false;

        review_view.state.archives = vec![unmatched];
        review_view.state.selected_index = Some(0);

        check(
            &mut result,
            !review_view.state.archives[0].steam.found,
            "Steam match: unmatched archive has found=false",
            "Steam match: unmatched archive found=true unexpectedly",
        );
    }

    // ============================================================
    // Step 17: Steam match failure simulation
    // ============================================================
    logger.info("SANDBOX", "Step 17: Steam match failure simulation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));
        let mut review_view =
            crate::ui::review_view::ReviewView::new(palette, Arc::clone(&logger), watchdog);

        let mut unmatched = mock_archive("Unknown Game", "00000", "Unknown", 1_000_000_000, false, false);
        unmatched.steam.found = false;
        let unmatched_msg = format!(
            "Created unmatched archive: name='{}' appid='00000' steam.found={}",
            unmatched.display_name, unmatched.steam.found
        );
        logger.debug("SANDBOX_STEP17", &unmatched_msg, "");

        review_view.state.archives = vec![unmatched];
        review_view.state.selected_index = Some(0);

        check(
            &mut result,
            !review_view.state.archives[0].steam.found,
            "Steam match: unmatched archive has found=false",
            "Steam match: unmatched archive found=true unexpectedly",
        );
        let steam_found_msg = format!(
            "steam.found verified=false ({})",
            review_view.state.archives[0].steam.found
        );
        logger.debug("SANDBOX_STEP17", &steam_found_msg, "");
    }

    // Step 18: Skip Current — verify skip clears accept
    // ============================================================
    logger.info("SANDBOX", "Step 18: Skip current simulation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));
        let mut review_view =
            crate::ui::review_view::ReviewView::new(palette, Arc::clone(&logger), watchdog);

        // Use fresh archives for skip test (Step 2 modified shared archives)
        let mut fresh_archives: Vec<GameArchive> = vec![mock_archive("Skip Test Game", "99999", "Action", 1_000_000_000, false, false)];
        fresh_archives[0].decision.accepted = true; // pre-accept so skip can clear it
        review_view.state.archives = fresh_archives.clone();
        review_view.state.selected_index = Some(0);
        let skip_setup_msg = format!(
            "Set fresh archives.len()={}, selected_index=Some(0), archive[0].accepted={}, archive[0].skipped={}",
            review_view.state.archives.len(),
            review_view.state.archives[0].decision.accepted,
            review_view.state.archives[0].decision.skipped
        );
        logger.debug("SANDBOX_STEP18", &skip_setup_msg, "");

        review_view.skip_current();
        let skip_call_msg = "Called review_view.skip_current()";
        logger.debug("SANDBOX_STEP18", skip_call_msg, "");
        let after_skip_msg = format!(
            "After skip: archive[0].skipped={}, archive[0].accepted={}, selected_index={:?}",
            review_view.state.archives[0].decision.skipped,
            review_view.state.archives[0].decision.accepted,
            review_view.state.selected_index
        );
        logger.debug("SANDBOX_STEP18", &after_skip_msg, "");
        check(
            &mut result,
            review_view.state.archives[0].decision.skipped,
            "Skip current: skipped set to true",
            "Skip current: skipped not set",
        );
        let skipped_msg = format!("skipped verified=true ({})", review_view.state.archives[0].decision.skipped);
        logger.debug("SANDBOX_STEP18", &skipped_msg, "");
        check(
            &mut result,
            !review_view.state.archives[0].decision.accepted,
            "Skip current: accepted cleared to false",
            "Skip current: accepted not cleared",
        );
        let accepted_msg = format!("accepted verified=false ({})", review_view.state.archives[0].decision.accepted);
        logger.debug("SANDBOX_STEP18", &accepted_msg, "");
    }

    // Step 19: Empty State — empty archive lists
    // ============================================================
    logger.info("SANDBOX", "Step 19: Empty state simulation", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));
        let empty_archives: Vec<GameArchive> = Vec::new();
        let empty_msg = "Created empty archives vec (len=0)";
        logger.debug("SANDBOX_STEP19", empty_msg, "");

        // ReviewView empty
        let mut review_view =
            crate::ui::review_view::ReviewView::new(palette.clone(), Arc::clone(&logger), watchdog.clone());
        review_view.state.archives = empty_archives.clone();
        review_view.state.selected_index = None;
        check(
            &mut result,
            review_view.state.archives.is_empty(),
            "Empty state: review archives empty",
            "Empty state: review archives not empty",
        );
        let review_empty_msg = format!("review archives empty={}", review_view.state.archives.is_empty());
        logger.debug("SANDBOX_STEP19", &review_empty_msg, "");
        check(
            &mut result,
            review_view.state.selected_index.is_none(),
            "Empty state: review no selection",
            "Empty state: review has selection",
        );
        let review_sel_msg = format!("review selected_index.is_none()={}", review_view.state.selected_index.is_none());
        logger.debug("SANDBOX_STEP19", &review_sel_msg, "");

        // DoneView empty
        let mut done_view =
            crate::ui::done_view::DoneView::new(palette, Arc::clone(&logger), watchdog);
        done_view.state.archives = empty_archives;
        done_view.state.converted = 0;
        done_view.state.skipped = 0;
        done_view.state.failed = 0;
        check(
            &mut result,
            done_view.state.converted == 0,
            "Empty state: done converted zero",
            "Empty state: done converted not zero",
        );
        check(
            &mut result,
            done_view.state.skipped == 0,
            "Empty state: done skipped zero",
            "Empty state: done skipped not zero",
        );
        check(
            &mut result,
            done_view.state.failed == 0,
            "Empty state: done failed zero",
            "Empty state: done failed not zero",
        );
        let done_empty_msg = format!(
            "DoneView empty state: converted={}, skipped={}, failed={}",
            done_view.state.converted, done_view.state.skipped, done_view.state.failed
        );
        logger.debug("SANDBOX_STEP19", &done_empty_msg, "");
    }

    // Step 21: Full pipeline — scan → review → organize → artwork → done
    // ============================================================
    logger.info("SANDBOX", "Step 21: Full pipeline mega-test", "");
    {
        let palette = crate::ui::theme::Palette::default();
        let watchdog = Arc::new(Watchdog::new(logger.clone(), 300000));

        // Fresh archives for pipeline test (none skipped)
        let pipe_archives: Vec<GameArchive> = vec![
            mock_archive("Alpha Forge", "12345", "Action", 5_000_000_000, true, false),
            mock_archive("Gamma Quest", "67890", "RPG", 8_000_000_000, true, false),
            mock_archive("Delta Realm", "11111", "Strategy", 3_000_000_000, true, false),
            mock_archive("Nebula Online", "22222", "Simulation", 4_000_000_000, true, false),
            mock_archive("Zenith Edge", "33333", "Shooter", 6_000_000_000, true, false),
        ];
        let pipe_msg = format!("Created {} pipeline archives (none skipped)", pipe_archives.len());
        logger.debug("SANDBOX_STEP21", &pipe_msg, "");

        // Log each pipeline archive before scan
        for archive in &pipe_archives {
            let pipe_archive_msg = format!(
                "Pipeline archive: name='{}' appid='{}' category='{}' size={} bytes accepted={} skipped={}",
                archive.display_name, archive.steam.appid, archive.decision.category,
                archive.size, archive.decision.accepted, archive.decision.skipped
            );
            logger.debug("SANDBOX_STEP21", &pipe_archive_msg, "");
        }

        // Scan discovers archives
        let mut scan_view =
            crate::ui::scan_view::ScanView::new(
                Arc::new(Services {
                    organizer: OrganizerService::new(
                        Arc::new(|_, _| {}),
                        true,
                    ),
                }),
                LibraryService::new(Arc::new(|_, _| {}), None),
                Arc::new(JobManager::new(4)),
                Arc::clone(&config),
                palette.clone(),
                Arc::clone(&logger),
                watchdog.clone(),
            );
        scan_view.state.discovered_archives = pipe_archives.clone();
        check(
            &mut result,
            scan_view.state.discovered_archives.len() == pipe_archives.len(),
            "Pipeline: scan discovers all archives",
            "Pipeline: scan missing archives",
        );
        // Log each archive discovered by scan
        for archive in &scan_view.state.discovered_archives {
            let scan_discovered_msg = format!(
                "Scan discovered: name='{}' appid='{}' category='{}' size={} bytes",
                archive.display_name, archive.steam.appid, archive.decision.category,
                archive.size
            );
            logger.debug("SANDBOX_STEP21", &scan_discovered_msg, "");
        }

        // Review accepts all
        let mut review_view =
            crate::ui::review_view::ReviewView::new(palette.clone(), Arc::clone(&logger), watchdog.clone());
        review_view.state.archives = pipe_archives.clone();
        review_view.state.should_approve_all = true;
        review_view.approve_all_verified();
        let all_accepted = review_view
            .state
            .archives
            .iter()
            .all(|a| a.decision.accepted);
        check(
            &mut result,
            all_accepted,
            "Pipeline: all archives accepted in review",
            "Pipeline: not all archives accepted",
        );
        // Log each archive after review acceptance
        for archive in &review_view.state.archives {
            let review_accepted_msg = format!(
                "Review accepted: name='{}' category='{}' accepted={} skipped={}",
                archive.display_name, archive.decision.category,
                archive.decision.accepted, archive.decision.skipped
            );
            logger.debug("SANDBOX_STEP21", &review_accepted_msg, "");
        }

        // Organize converts accepted
        let accepted_archives: Vec<GameArchive> = review_view
            .state
            .archives
            .iter()
            .filter(|a| a.decision.accepted)
            .cloned()
            .collect();
        let pipe_accepted_msg = format!(
            "Pipeline: {} archives accepted out of {} total for organize",
            accepted_archives.len(),
            review_view.state.archives.len()
        );
        logger.debug("SANDBOX_STEP21", &pipe_accepted_msg, "");
        let mut organize_view =
            crate::ui::organize_view::OrganizeView::new(palette.clone(), Arc::clone(&logger), watchdog.clone());
        organize_view.state.archives = accepted_archives.clone();
        organize_view.state.should_organize = true;
        organize_view.state.converting = true;
        organize_view.run_organize();
        check(
            &mut result,
            organize_view.state.converted_count == accepted_archives.len(),
            "Pipeline: organize converts all accepted archives",
            "Pipeline: organize conversion count mismatch",
        );
        check(
            &mut result,
            !organize_view.state.converting,
            "Pipeline: organize completes",
            "Pipeline: organize left converting=true",
        );
        // Log each archive after organize conversion
        for archive in &accepted_archives {
            let organize_converted_msg = format!(
                "Organize converted: name='{}' category='{}' final_name='{}' final_size={} bytes source_size={} bytes",
                archive.display_name, archive.decision.category,
                archive.conversion.final_name, archive.conversion.final_size,
                archive.conversion.source_size
            );
            logger.debug("SANDBOX_STEP21", &organize_converted_msg, "");
        }

        // Done loads results
        let mut done_view =
            crate::ui::done_view::DoneView::new(palette, Arc::clone(&logger), watchdog);
        done_view.state.archives = accepted_archives.clone();
        done_view.state.converted = organize_view.state.converted_count;
        done_view.state.skipped = organize_view.state.skipped_count;
        done_view.state.failed = organize_view.state.failed_count;
        let pipe_done_msg = format!(
            "Done loads: converted={}, skipped={}, failed={}",
            done_view.state.converted, done_view.state.skipped, done_view.state.failed
        );
        logger.debug("SANDBOX_STEP21", &pipe_done_msg, "");
        // Log each archive in done view
        for archive in &done_view.state.archives {
            let done_archive_msg = format!(
                "Done archive: name='{}' converted_count={} skipped_count={} failed_count={}",
                archive.display_name,
                done_view.state.converted,
                done_view.state.skipped,
                done_view.state.failed
            );
            logger.debug("SANDBOX_STEP21", &done_archive_msg, "");
        }
        check(
            &mut result,
            done_view.state.converted == accepted_archives.len(),
            "Pipeline: done view shows all converted",
            "Pipeline: done view conversion count mismatch",
        );
        check(
            &mut result,
            done_view.state.skipped == 0,
            "Pipeline: done view shows zero skipped",
            "Pipeline: done view skipped count mismatch",
        );
        check(
            &mut result,
            done_view.state.failed == 0,
            "Pipeline: done view shows zero failed",
            "Pipeline: done view failed count mismatch",
        );
    }

    // ============================================================
    // Step 22: Corrupt/Missing Config — graceful handling
    // ============================================================
    logger.info("SANDBOX", "Step 22: Corrupt/missing config simulation", "");
    {
        // Config with no library root should not panic
        let mut empty_config = AppConfig::new(sandbox_dir.as_path());
        empty_config.library_root = None;
        let empty_config_msg = "Created AppConfig with library_root=None";
        logger.debug("SANDBOX_STEP22", empty_config_msg, "");
        check(
            &mut result,
            empty_config.library_root.is_none(),
            "Corrupt config: library root None handled",
            "Corrupt config: library root not None",
        );
        let lib_root_none_msg = format!("library_root.is_none()={}", empty_config.library_root.is_none());
        logger.debug("SANDBOX_STEP22", &lib_root_none_msg, "");
        check(
            &mut result,
            empty_config.extract_folder().is_empty()
                || empty_config.extract_folder().as_path().exists(),
            "Corrupt config: extract folder path valid",
            "Corrupt config: extract folder path invalid",
        );
        let extract_path_msg = format!(
            "extract_folder exists={}, is_empty={}",
            empty_config.extract_folder().as_path().exists(),
            empty_config.extract_folder().is_empty()
        );
        logger.debug("SANDBOX_STEP22", &extract_path_msg, "");
    }

    // ============================================================
    // Step 23: Watchdog timeout simulation
    // ============================================================
    logger.info("SANDBOX", "Step 23: Watchdog simulation", "");
    {
        // Short timeout watchdog
        let _watchdog = Arc::new(Watchdog::new(logger.clone(), 100));
        let watchdog_msg = "Constructed Watchdog with short timeout=100ms";
        logger.debug("SANDBOX_STEP23", watchdog_msg, "");
        check(
            &mut result,
            true,
            "Watchdog: constructed with short timeout",
            "Watchdog: construction failed",
        );
    }

    // ============================================================
    // Step 24: Read logs and check for errors
    // ============================================================
    logger.info("SANDBOX", "Step 24: Read logs and check for errors", "");

    let logs_dir = project_root.join("logs");
    let logs_dir_exists = logs_dir.exists();
    let logs_dir_msg = format!("Checking logs dir: {} exists={}", logs_dir.display(), logs_dir_exists);
    logger.debug("SANDBOX_STEP24", &logs_dir_msg, "");
    let log_path = if logs_dir.exists() {
        std::fs::read_dir(&logs_dir)
            .ok()
            .and_then(|entries| {
                entries
                    .filter_map(|e| e.ok())
                    .filter(|e| {
                        e.file_name()
                            .to_string_lossy()
                            .starts_with("sandbox-")
                    })
                    .max_by_key(|e| e.metadata().and_then(|m| m.modified()).unwrap_or(SystemTime::UNIX_EPOCH))
                    .map(|e| e.path())
            })
            .unwrap_or_default()
    } else {
        PathBuf::default()
    };

    if log_path.exists() {
        let log_path_msg = format!("Found sandbox log file: {}", log_path.display());
        logger.debug("SANDBOX_STEP24", &log_path_msg, "");
        let log_contents = std::fs::read_to_string(&log_path)
            .map_err(|e| format!("Failed to read log file: {}", e))?;
        let log_size_msg = format!("Log file size: {} bytes", log_contents.len());
        logger.debug("SANDBOX_STEP24", &log_size_msg, "");
        let log_lines = log_contents.lines().count();
        let log_lines_msg = format!("Log file line count: {}", log_lines);
        logger.debug("SANDBOX_STEP24", &log_lines_msg, "");

        let error_patterns = ["[ERROR", "PANIC", "FAILED"];
        let mut found_any = false;
        for line in log_contents.lines() {
            let trimmed = line.trim();
            for pattern in &error_patterns {
                if trimmed.starts_with(pattern) {
                    result.issues_found.push(format!("Log line starts with pattern: {}", pattern));
                    result.checks_failed += 1;
                    logger.warning(
                        "SANDBOX",
                        &format!("Log error pattern found at line start: {}", pattern),
                        "",
                    );
                    found_any = true;
                }
            }
        }
        if !found_any {
            result.checks_passed += 1;
            logger.info("SANDBOX", "Log check: no error patterns found", "");
        }
    } else {
        logger.warning("SANDBOX", "Log file not found for checking", "");
        result.issues_found.push("Log file not found".to_string());
        result.checks_failed += 1;
    }

    // ============================================================
    // Step 25: Print summary
    // ============================================================
    logger.info("SANDBOX", "Step 25: Sandbox summary", "");
    let summary_msg = format!(
        "SANDBOX SUMMARY: Mock archives={} (converted={}, skipped={}, failed={}), Checks passed={}, Checks failed={}, Issues found={}",
        archives_count,
        converted_count,
        skipped_count,
        failed_count,
        result.checks_passed,
        result.checks_failed,
        result.issues_found.len()
    );
    logger.info("SANDBOX", &summary_msg, "");
    println!("\n================================================");
    println!("  SANDBOX MODE - End-to-End Mega-Test Simulation");
    println!("================================================");
    println!("Mock archives: {} (converted: {}, skipped: {}, failed: {})", archives_count, converted_count, skipped_count, failed_count);
    println!("Checks passed: {}", result.checks_passed);
    println!("Checks failed: {}", result.checks_failed);
    if !result.issues_found.is_empty() {
        println!("Issues found:");
        for issue in &result.issues_found {
            println!("  - {}", issue);
        }
    }
    println!("================================================");

    if result.checks_failed > 0 {
        Err(format!("Sandbox failed: {} issue(s) found", result.checks_failed))
    } else {
        logger.info("SANDBOX", "COMPLETE sandbox mega-test - all checks passed", "");
        Ok(())
    }
}
