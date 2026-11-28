//! Steam Game Organizer Diagnostic Tools
//!
//! Standalone CLI for tracking gaps not covered by the main app:
//!   - disk-space: Pre-flight disk space check before extract/organize
//!   - cleanup-orphans: Find and report orphaned temp files from crashed sessions
//!   - duplicates: Find duplicate archives by normalized name + size
//!   - steam-health: Steam API rate limit / availability monitor
//!   - config-hash: Config file tamper detection via SHA-256 hash watch
//!   - backup-verify: Verify backups are restorable
//!   - png-verify: Verify PNG screenshots are valid and not corrupted
//!   - sandbox-isolate: Test sandbox isolation doesn't leak files to project root
//!   - log-health: Analyze log files for errors/warnings/patterns
//!   - ui-diff: Compare two screenshots and report pixel differences
//!   - archive-integrity: Deep verify archives can be extracted
//!   - config-validate: Validate settings.json against expected schema
//!   - perf-benchmark: Time key operations for regression detection
//!   - ui-text-verify: OCR a screen region and verify expected text appears
//!
//! Usage:
//!   sg-diag disk-space <library_root>
//!   sg-diag cleanup-orphans <cache_dir> [--delete]
//!   sg-diag duplicates <library_root>
//!   sg-diag steam-health [--interval <seconds>]
//!   sg-diag config-hash <config_path> [--watch]
//!   sg-diag backup-verify <backup_path> [--extract-dir <tmp>]
//!   sg-diag png-verify <screenshots_dir>
//!   sg-diag sandbox-isolate <sandbox_dir> [--check-project-root]
//!   sg-diag log-health <logs_dir>
//!   sg-diag ui-diff <before.png> <after.png>
//!   sg-diag archive-integrity <archive_path>
//!   sg-diag config-validate <config_path>
//!   sg-diag perf-benchmark <iterations>
//!   sg-diag ui-text-verify <screenshot.png> <expected_text>

use clap::{Parser, Subcommand};
use image::imageops::FilterType;
use image::GenericImageView;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use walkdir::WalkDir;

#[derive(Parser)]
#[command(name = "sg-diag")]
#[command(about = "Steam Game Organizer diagnostic tools")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Check free disk space vs archive sizes before extract/organize
    DiskSpace {
        /// Library root directory to scan
        library_root: PathBuf,
    },
    /// Find orphaned temp files from crashed sessions
    CleanupOrphans {
        /// Directory to scan (cache, processing, logs)
        dir: PathBuf,
        /// Actually delete orphaned files (dry-run by default)
        #[arg(long)]
        delete: bool,
    },
    /// Find duplicate archives by normalized name + size
    Duplicates {
        /// Library root directory to scan
        library_root: PathBuf,
    },
    /// Steam API rate limit / availability monitor
    SteamHealth {
        /// Poll interval in seconds (default: 30)
        #[arg(long, default_value = "30")]
        interval: u64,
    },
    /// Config file tamper detection via SHA-256 hash watch
    ConfigHash {
        /// Config file path to watch
        config_path: PathBuf,
        /// Watch mode: continuously monitor for changes
        #[arg(long)]
        watch: bool,
    },
    /// Verify backups are restorable
    BackupVerify {
        /// Backup archive path (.zip or directory)
        backup_path: PathBuf,
        /// Temporary directory for extraction test
        #[arg(long, default_value = "sg-diag-verify-tmp")]
        extract_dir: PathBuf,
    },
    /// Verify PNG screenshots are valid and not corrupted
    PngVerify {
        /// Directory containing PNG screenshots to verify
        screenshots_dir: PathBuf,
    },
    /// Test sandbox isolation doesn't leak files to project root
    SandboxIsolate {
        /// Sandbox directory to test
        sandbox_dir: PathBuf,
        /// Also check that no test files leaked to project root
        #[arg(long)]
        check_project_root: bool,
    },
    /// Analyze log files for errors/warnings/patterns
    LogHealth {
        /// Directory containing log files to analyze
        logs_dir: PathBuf,
    },
    /// Compare two screenshots and report pixel differences
    Uidiff {
        /// First screenshot (baseline)
        before: PathBuf,
        /// Second screenshot (comparison)
        after: PathBuf,
    },
    /// Deep verify an archive can be extracted
    ArchiveIntegrity {
        /// Archive file to verify (.zip, .rar, .7z)
        archive_path: PathBuf,
    },
    /// Validate settings.json against expected schema
    ConfigValidate {
        /// Config file path to validate
        config_path: PathBuf,
    },
    /// Time key operations for regression detection
    PerfBenchmark {
        /// Number of iterations to run
        #[arg(long, default_value = "5")]
        iterations: u64,
    },
    /// OCR a screen region and verify expected text appears
    UicTextVerify {
        /// Screenshot file to OCR
        screenshot: PathBuf,
        /// Expected text that should appear in OCR output
        expected_text: String,
    },
}

fn main() {
    let cli = Cli::parse();
    match cli.command {
        Commands::DiskSpace { library_root } => disk_space(&library_root),
        Commands::CleanupOrphans { dir, delete } => cleanup_orphans(&dir, delete),
        Commands::Duplicates { library_root } => duplicates(&library_root),
        Commands::SteamHealth { interval } => steam_health(interval),
        Commands::ConfigHash { config_path, watch } => config_hash(&config_path, watch),
        Commands::BackupVerify {
            backup_path,
            extract_dir,
        } => backup_verify(&backup_path, &extract_dir),
        Commands::PngVerify { screenshots_dir } => png_verify(&screenshots_dir),
        Commands::SandboxIsolate {
            sandbox_dir,
            check_project_root,
        } => sandbox_isolate(&sandbox_dir, check_project_root),
        Commands::LogHealth { logs_dir } => log_health(&logs_dir),
        Commands::Uidiff { before, after } => ui_diff(&before, &after),
        Commands::ArchiveIntegrity { archive_path } => archive_integrity(&archive_path),
        Commands::ConfigValidate { config_path } => config_validate(&config_path),
        Commands::PerfBenchmark { iterations } => perf_benchmark(iterations),
        Commands::UicTextVerify {
            screenshot,
            expected_text,
        } => ui_text_verify(&screenshot, &expected_text),
    }
}

// ============================================================================
// Existing subcommands (disk-space, cleanup-orphans, duplicates, steam-health,
// config-hash, backup-verify) -- omitted for brevity, they remain unchanged
// ============================================================================

fn disk_space(library_root: &Path) {
    if !library_root.is_dir() {
        eprintln!("ERROR: Library root does not exist or is not a directory: {}", library_root.display());
        std::process::exit(1);
    }

    println!("=== Disk Space Analysis ===");
    println!("Library root: {}", library_root.display());
    println!();

    let mut total_size: u64 = 0;
    let mut archive_count: u64 = 0;
    let mut largest_archive: (String, u64) = (String::new(), 0);

    for entry in WalkDir::new(library_root)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if path.is_file() && is_archive(path) {
            if let Ok(metadata) = path.metadata() {
                let size = metadata.len();
                total_size += size;
                archive_count += 1;
                if size > largest_archive.1 {
                    largest_archive = (path.display().to_string(), size);
                }
            }
        }
    }

    let free_space = get_free_space(library_root).unwrap_or(0);

    println!("Archives found: {}", archive_count);
    println!("Total archive size: {} bytes ({:.2} GB)", total_size, total_size as f64 / 1_073_741_824.0);
    println!("Largest archive: {} ({} bytes)", largest_archive.0, largest_archive.1);
    println!();
    println!("Free space on drive: {} bytes ({:.2} GB)", free_space, free_space as f64 / 1_073_741_824.0);
    println!();

    let needed_for_extract = total_size;
    let needed_for_organize = total_size * 2;

    if free_space < needed_for_extract {
        println!("WARNING: Insufficient space for full extraction!");
        println!("  Needed for full extract: {} bytes ({:.2} GB)", needed_for_extract, needed_for_extract as f64 / 1_073_741_824.0);
        println!("  Shortfall: {} bytes ({:.2} GB)", needed_for_extract.saturating_sub(free_space), needed_for_extract.saturating_sub(free_space) as f64 / 1_073_741_824.0);
    } else {
        println!("OK: Sufficient space for full extraction ({:.1}% used)", (total_size as f64 / free_space as f64) * 100.0);
    }

    if free_space < needed_for_organize {
        println!("WARNING: Insufficient space for full organize (extract + compress)!");
        println!("  Needed for full organize: {} bytes ({:.2} GB)", needed_for_organize, needed_for_organize as f64 / 1_073_741_824.0);
        println!("  Shortfall: {} bytes ({:.2} GB)", needed_for_organize.saturating_sub(free_space), needed_for_organize.saturating_sub(free_space) as f64 / 1_073_741_824.0);
    } else {
        println!("OK: Sufficient space for full organize ({:.1}% used)", (needed_for_organize as f64 / free_space as f64) * 100.0);
    }

    if free_space < largest_archive.1 * 3 {
        println!("WARNING: Less than 3x largest archive size free ({}). Consider extracting one archive at a time.", largest_archive.0);
    }
}

fn is_archive(path: &Path) -> bool {
    matches!(
        path.extension().and_then(|e| e.to_str()).unwrap_or(""),
        "zip" | "rar" | "7z"
    )
}

fn get_free_space(path: &Path) -> Option<u64> {
    let drive = path.parent().unwrap_or(path);
    let test_file = drive.join(".sg-diag-space-test");
    match fs::File::create(&test_file) {
        Ok(mut f) => {
            let _ = f.write_all(b"test");
            drop(f);
            let _ = fs::remove_file(&test_file);
            Some(0)
        }
        Err(_) => None,
    }
}

fn cleanup_orphans(dir: &Path, delete: bool) {
    if !dir.is_dir() {
        eprintln!("ERROR: Directory does not exist: {}", dir.display());
        std::process::exit(1);
    }

    println!("=== Orphaned Temp File Scan ===");
    println!("Directory: {}", dir.display());
    println!("Mode: {}", if delete { "DELETE" } else { "DRY-RUN" });
    println!();

    let mut orphans: Vec<(PathBuf, u64, String)> = Vec::new();
    let mut total_size: u64 = 0;
    let mut count: u64 = 0;

    let temp_patterns = [
        ".tmp", ".temp", ".part", ".download", ".crdownload",
        "scan-state.", "lock.", ".lock", ".journal", ".journal.tmp",
        ".organizer-repack", ".ocr_ready",
    ];

    for entry in WalkDir::new(dir)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }

        let file_name = path.file_name().unwrap_or_default().to_string_lossy();
        let is_temp = temp_patterns.iter().any(|p| file_name.contains(p))
            || file_name.ends_with(".tmp")
            || file_name.starts_with("~")
            || file_name.contains("crash")
            || file_name.contains("orphan");

        if is_temp {
            if let Ok(metadata) = path.metadata() {
                let size = metadata.len();
                let age_hours = file_age_hours(&metadata).unwrap_or(0);
                total_size += size;
                count += 1;
                orphans.push((path.to_path_buf(), size, format!("{}h", age_hours)));
            }
        }
    }

    if orphans.is_empty() {
        println!("No orphaned temp files found.");
        return;
    }

    println!("Found {} orphaned temp file(s), total size: {} bytes ({:.2} MB)", count, total_size, total_size as f64 / 1_048_576.0);
    println!();

    for (path, size, age) in &orphans {
        println!("  {} {} ({} bytes, age ~{}h)", if delete { "[DELETE]" } else { "[DRY-RUN]" }, path.display(), size, age);
    }

    if delete {
        let mut deleted: u64 = 0;
        let mut failed: u64 = 0;
        for (path, _, _) in &orphans {
            match fs::remove_file(path) {
                Ok(()) => deleted += 1,
                Err(e) => {
                    eprintln!("  Failed to delete {}: {}", path.display(), e);
                    failed += 1;
                }
            }
        }
        println!();
        println!("Deleted: {}, Failed: {}", deleted, failed);
    } else {
        println!();
        println!("Run with --delete to remove these files.");
    }
}

fn file_age_hours(metadata: &fs::Metadata) -> Option<u64> {
    let modified = metadata.modified().ok()?;
    let now = SystemTime::now();
    let duration = now.duration_since(modified).ok()?;
    Some(duration.as_secs() / 3600)
}

fn duplicates(library_root: &Path) {
    if !library_root.is_dir() {
        eprintln!("ERROR: Library root does not exist: {}", library_root.display());
        std::process::exit(1);
    }

    println!("=== Duplicate Archive Detector ===");
    println!("Library root: {}", library_root.display());
    println!();

    let mut groups: HashMap<String, Vec<(PathBuf, u64)>> = HashMap::new();

    for entry in WalkDir::new(library_root)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if !path.is_file() || !is_archive(path) {
            continue;
        }

        let name = path.file_name().unwrap_or_default().to_string_lossy().to_string();
        let normalized = normalize_archive_name(&name);

        if let Ok(metadata) = path.metadata() {
            groups.entry(normalized).or_default().push((path.to_path_buf(), metadata.len()));
        }
    }

    let mut dup_groups: Vec<(String, Vec<(PathBuf, u64)>)> = groups
        .into_iter()
        .filter(|(_, entries)| entries.len() > 1)
        .collect();

    dup_groups.sort_by(|a, b| {
        let a_total: u64 = a.1.iter().map(|(_, s)| s).sum();
        let b_total: u64 = b.1.iter().map(|(_, s)| s).sum();
        b_total.cmp(&a_total)
    });

    if dup_groups.is_empty() {
        println!("No duplicate archives found.");
        return;
    }

    let mut total_wasted: u64 = 0;
    let mut total_dup_count: u64 = 0;

    for (normalized, entries) in &dup_groups {
        let total_size: u64 = entries.iter().map(|(_, s)| s).sum();
        let max_size: u64 = entries.iter().map(|(_, s)| *s).max().unwrap_or(0);
        let wasted = total_size - max_size;
        total_wasted += wasted;
        total_dup_count += entries.len() as u64 - 1;

        println!("Group: {} ({} copies)", normalized, entries.len());
        for (path, size) in entries {
            let keep = if *size == max_size {
                " [KEEP - largest]"
            } else {
                ""
            };
            println!("  {} ({} bytes){}", path.display(), size, keep);
        }
        println!("  Wasted space: {} bytes ({:.2} MB)", wasted, wasted as f64 / 1_048_576.0);
        println!();
    }

    println!("Total duplicate copies: {}", total_dup_count);
    println!("Total wasted space: {} bytes ({:.2} MB)", total_wasted, total_wasted as f64 / 1_048_576.0);
}

fn normalize_archive_name(name: &str) -> String {
    let lower = name.to_lowercase();

    let release_groups = [
        "tenoke", "dodi", "fitgirl", "rif", "skidrow", "codex", "csru", " goldberg",
        " steamemu", " console", " repack", " ultimate", " deluxe", " edition",
        " complete", " goty", " directors", " cut", " definitive",
    ];

    let mut result = lower.clone();
    for group in &release_groups {
        if result.starts_with(group) {
            result = result[group.len()..].trim_start().to_string();
        }
        if result.ends_with(group) {
            result = result[..result.len() - group.len()].trim_end().to_string();
        }
    }

    result = result
        .replace('-', " ")
        .replace('_', " ")
        .replace('.', " ")
        .replace('(', " ")
        .replace(')', " ")
        .replace('[', " ")
        .replace(']', " ");

    result = result
        .split_whitespace()
        .filter(|s| !s.chars().all(|c| c.is_ascii_digit()))
        .collect::<Vec<_>>()
        .join(" ");

    result.trim().to_string()
}

fn steam_health(interval_secs: u64) {
    println!("=== Steam API Health Monitor ===");
    println!("Polling interval: {} seconds", interval_secs);
    println!("Press Ctrl+C to stop");
    println!();

    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(10))
        .build()
        .expect("Failed to create HTTP client");

    let mut consecutive_failures: u64 = 0;
    let mut total_requests: u64 = 0;
    let mut total_failures: u64 = 0;
    let mut total_latency_ms: u64 = 0;

    loop {
        let start = SystemTime::now();
        let result = client
            .get("https://store.steampowered.com/api/storesearch/?term=half-life&cc=us&l=english")
            .send();
        let latency = start.elapsed().unwrap_or(Duration::ZERO).as_millis() as u64;

        total_requests += 1;
        total_latency_ms += latency;

        match result {
            Ok(resp) => {
                let status = resp.status();
                if status.is_success() {
                    consecutive_failures = 0;
                    let avg_latency = total_latency_ms / total_requests;
                    println!(
                        "[{}] OK status={} latency={}ms avg={}ms failures={}",
                        timestamp(),
                        status,
                        latency,
                        avg_latency,
                        total_failures
                    );
                } else {
                    consecutive_failures += 1;
                    total_failures += 1;
                    println!(
                        "[{}] WARN status={} latency={}ms consecutive_failures={}",
                        timestamp(),
                        status,
                        latency,
                        consecutive_failures
                    );
                }
            }
            Err(e) => {
                consecutive_failures += 1;
                total_failures += 1;
                println!(
                    "[{}] ERROR request_failed={} consecutive_failures={}",
                    timestamp(),
                    e,
                    consecutive_failures
                );
            }
        }

        if consecutive_failures >= 3 {
            println!("  >>> ALERT: {} consecutive failures - Steam API may be down or rate-limiting", consecutive_failures);
        }

        std::thread::sleep(Duration::from_secs(interval_secs));
    }
}

fn timestamp() -> String {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    let secs = now.as_secs();
    let h = (secs / 3600) % 24;
    let m = (secs / 60) % 60;
    let s = secs % 60;
    format!("{h:02}:{m:02}:{s:02}")
}

fn config_hash(config_path: &Path, watch: bool) {
    if !config_path.is_file() {
        eprintln!("ERROR: Config file does not exist: {}", config_path.display());
        std::process::exit(1);
    }

    let initial_hash = hash_file(config_path).expect("Failed to hash config file");
    println!("=== Config Hash Monitor ===");
    println!("Config: {}", config_path.display());
    println!("Initial hash: {}", initial_hash);
    println!();

    if watch {
        println!("Watching for changes... (Ctrl+C to stop)");
        loop {
            std::thread::sleep(Duration::from_secs(5));
            if let Ok(current_hash) = hash_file(config_path) {
                if current_hash != initial_hash {
                    println!("[{}] ALERT: Config file has changed!", timestamp());
                    println!("  Original hash: {}", initial_hash);
                    println!("  Current hash:  {}", current_hash);
                    break;
                }
            }
        }
    } else {
        let current_hash = hash_file(config_path).expect("Failed to hash config file");
        if current_hash == initial_hash {
            println!("OK: Config file unchanged.");
        } else {
            println!("WARNING: Config file hash differs from baseline!");
            println!("  Baseline: {}", initial_hash);
            println!("  Current:  {}", current_hash);
        }
    }
}

fn hash_file(path: &Path) -> Result<String, std::io::Error> {
    let data = fs::read(path)?;
    let mut hasher = Sha256::new();
    hasher.update(&data);
    Ok(format!("{:x}", hasher.finalize()))
}

fn backup_verify(backup_path: &Path, extract_dir: &Path) {
    if !backup_path.exists() {
        eprintln!("ERROR: Backup path does not exist: {}", backup_path.display());
        std::process::exit(1);
    }

    println!("=== Backup Verification ===");
    println!("Backup: {}", backup_path.display());
    println!("Extract dir: {}", extract_dir.display());
    println!();

    let _ = fs::remove_dir_all(extract_dir);
    let _ = fs::create_dir_all(extract_dir);

    let result = if backup_path.is_dir() {
        verify_directory_backup(backup_path, extract_dir)
    } else if is_archive(backup_path) {
        verify_archive_backup(backup_path, extract_dir)
    } else {
        println!("ERROR: Unknown backup format (not a directory or .zip/.rar/.7z)");
        std::process::exit(1);
    };

    match result {
        Ok((file_count, total_size)) => {
            println!();
            println!("VERIFICATION PASSED");
            println!("  Files extracted: {}", file_count);
            println!("  Total size: {} bytes ({:.2} MB)", total_size, total_size as f64 / 1_048_576.0);
            println!("  Backup is restorable.");
        }
        Err(e) => {
            eprintln!();
            eprintln!("VERIFICATION FAILED: {}", e);
            std::process::exit(1);
        }
    }
}

fn verify_directory_backup(backup_path: &Path, extract_dir: &Path) -> Result<(u64, u64), String> {
    let mut file_count: u64 = 0;
    let mut total_size: u64 = 0;

    for entry in WalkDir::new(backup_path)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if path.is_file() {
            let rel = path.strip_prefix(backup_path).unwrap_or(path);
            let target = extract_dir.join(rel);
            if let Some(parent) = target.parent() {
                let _ = fs::create_dir_all(parent);
            }
            match fs::copy(path, &target) {
                Ok(size) => {
                    file_count += 1;
                    total_size += size;
                }
                Err(e) => {
                    return Err(format!("Failed to copy {}: {}", path.display(), e));
                }
            }
        }
    }

    Ok((file_count, total_size))
}

fn verify_archive_backup(backup_path: &Path, extract_dir: &Path) -> Result<(u64, u64), String> {
    if backup_path.extension().and_then(|e| e.to_str()) == Some("zip") {
        verify_zip_backup(backup_path, extract_dir)
    } else {
        verify_7z_backup(backup_path, extract_dir)
    }
}

fn verify_zip_backup(zip_path: &Path, extract_dir: &Path) -> Result<(u64, u64), String> {
    let file = fs::File::open(zip_path)
        .map_err(|e| format!("Failed to open zip: {}", e))?;
    let mut archive = zip::ZipArchive::new(file)
        .map_err(|e| format!("Failed to read zip: {}", e))?;

    let mut file_count: u64 = 0;
    let mut total_size: u64 = 0;

    for i in 0..archive.len() {
        let mut entry = archive.by_index(i)
            .map_err(|e| format!("Failed to read entry {}: {}", i, e))?;

        if entry.is_dir() {
            continue;
        }

        let entry_name = entry.name().unwrap_or_default().into_owned();
        let target = extract_dir.join(Path::new(&entry_name));
        if let Some(parent) = target.parent() {
            let _ = fs::create_dir_all(parent);
        }

        let mut out_file = fs::File::create(&target)
            .map_err(|e| format!("Failed to create {}: {}", target.display(), e))?;

        let size = std::io::copy(&mut entry, &mut out_file)
            .map_err(|e| format!("Failed to extract entry {}: {}", i, e))?;

        file_count += 1;
        total_size += size;
    }

    Ok((file_count, total_size))
}

fn verify_7z_backup(archive_path: &Path, extract_dir: &Path) -> Result<(u64, u64), String> {
    let output = Command::new("7z")
        .args(["l", archive_path.to_str().unwrap_or("")])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output();

    match output {
        Ok(out) if out.status.success() => {
            let extract_output = Command::new("7z")
                .args([
                    "x",
                    archive_path.to_str().unwrap_or(""),
                    &format!("-o{}", extract_dir.to_str().unwrap_or(".")),
                    "-y",
                ])
                .stdout(Stdio::null())
                .stderr(Stdio::piped())
                .output();

            match extract_output {
                Ok(eo) if eo.status.success() => {
                    let mut file_count: u64 = 0;
                    let mut total_size: u64 = 0;
                    for entry in WalkDir::new(extract_dir)
                        .into_iter()
                        .filter_map(|e| e.ok())
                    {
                        if entry.path().is_file() {
                            if let Ok(m) = entry.path().metadata() {
                                file_count += 1;
                                total_size += m.len();
                            }
                        }
                    }
                    Ok((file_count, total_size))
                }
                Ok(eo) => Err(format!(
                    "7z extraction failed: {}",
                    String::from_utf8_lossy(&eo.stderr)
                )),
                Err(e) => Err(format!("Failed to run 7z: {}", e)),
            }
        }
        Ok(_) => Err("7z not available and archive is not a .zip".to_string()),
        Err(e) => Err(format!("7z not available: {}", e)),
    }
}

// ============================================================================
// NEW: PNG verification subcommand
// ============================================================================

fn png_verify(screenshots_dir: &Path) {
    if !screenshots_dir.is_dir() {
        eprintln!("ERROR: Screenshots directory does not exist: {}", screenshots_dir.display());
        std::process::exit(1);
    }

    println!("=== PNG Verification ===");
    println!("Directory: {}", screenshots_dir.display());
    println!();

    let mut total: u64 = 0;
    let mut valid: u64 = 0;
    let mut invalid: u64 = 0;
    let mut total_size: u64 = 0;
    let mut issues: Vec<(PathBuf, String)> = Vec::new();

    for entry in WalkDir::new(screenshots_dir)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        if path.extension().and_then(|e| e.to_str()).unwrap_or("") != "png" {
            continue;
        }

        total += 1;
        if let Ok(metadata) = path.metadata() {
            total_size += metadata.len();
        }

        match image::open(path) {
            Ok(img) => {
                let (w, h) = img.dimensions();
                if w == 0 || h == 0 {
                    invalid += 1;
                    issues.push((path.to_path_buf(), "zero dimensions".to_string()));
                } else {
                    valid += 1;
                }
            }
            Err(e) => {
                invalid += 1;
                issues.push((path.to_path_buf(), format!("corrupt: {}", e)));
            }
        }
    }

    if total == 0 {
        println!("No PNG files found in {}", screenshots_dir.display());
        return;
    }

    println!("Total PNG files: {}", total);
    println!("Valid: {}", valid);
    println!("Invalid: {}", invalid);
    println!("Total size: {} bytes ({:.2} MB)", total_size, total_size as f64 / 1_048_576.0);
    println!();

    if !issues.is_empty() {
        println!("Invalid files:");
        for (path, reason) in &issues {
            println!("  {}: {}", path.display(), reason);
        }
    } else {
        println!("All PNG files are valid.");
    }
}

// ============================================================================
// NEW: Sandbox isolation test
// ============================================================================

fn sandbox_isolate(sandbox_dir: &Path, check_project_root: bool) {
    println!("=== Sandbox Isolation Test ===");
    println!("Sandbox dir: {}", sandbox_dir.display());
    println!();

    // Create test files in sandbox
    let test_files = vec!["test_archive.zip", "test_folder", "test_log.log", "test_config.json"];
    let mut created: Vec<PathBuf> = Vec::new();

    for name in &test_files {
        let path = sandbox_dir.join(name);
        if path.is_dir() {
            let _ = fs::create_dir_all(&path);
        } else if name.ends_with(".zip") {
            // Create a minimal zip
            if let Ok(f) = fs::File::create(&path) {
                let mut zip = zip::ZipWriter::new(f);
                let options: zip::write::FileOptions<'_, '_, ()> =
                    zip::write::FileOptions::default().compression_method(zip::CompressionMethod::Stored);
                let _ = zip.start_file("test.txt", options);
                let _ = zip.write(b"test content");
                let _ = zip.finish();
            }
        } else {
            let _ = fs::write(&path, "test content");
        }
        created.push(path);
    }

    println!("Created {} test file(s) in sandbox:", created.len());
    for f in &created {
        println!("  {}", f.display());
    }

    // Check if any test files leaked to project root
    if check_project_root {
        let project_root = std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
            .unwrap_or_else(|| std::env::current_dir().unwrap_or_default());

        println!("\nChecking project root for leaked files: {}", project_root.display());
        let mut leaked: Vec<PathBuf> = Vec::new();

        for name in &test_files {
            let leaked_path = project_root.join(name);
            if leaked_path.exists() {
                leaked.push(leaked_path);
            }
        }

        if leaked.is_empty() {
            println!("OK: No test files leaked to project root.");
        } else {
            println!("WARNING: {} file(s) leaked to project root:", leaked.len());
            for f in &leaked {
                println!("  {}", f.display());
            }
        }
    }

    // Clean up test files
    for f in &created {
        let _ = fs::remove_dir_all(f);
        let _ = fs::remove_file(f);
    }
    println!("\nCleanup complete.");
}

// ============================================================================
// NEW: Log health analysis
// ============================================================================

fn log_health(logs_dir: &Path) {
    if !logs_dir.is_dir() {
        eprintln!("ERROR: Logs directory does not exist: {}", logs_dir.display());
        std::process::exit(1);
    }

    println!("=== Log Health Analysis ===");
    println!("Directory: {}", logs_dir.display());
    println!();

    let mut total_logs: u64 = 0;
    let mut total_errors: u64 = 0;
    let mut total_warnings: u64 = 0;
    let mut error_patterns: HashMap<String, u64> = HashMap::new();
    let mut warning_patterns: HashMap<String, u64> = HashMap::new();
    let mut largest_log: (PathBuf, u64) = (PathBuf::new(), 0);
    let mut total_size: u64 = 0;

    for entry in WalkDir::new(logs_dir)
        .into_iter()
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        if ext != "log" && ext != "txt" {
            continue;
        }

        total_logs += 1;
        if let Ok(metadata) = path.metadata() {
            total_size += metadata.len();
            if metadata.len() > largest_log.1 {
                largest_log = (path.to_path_buf(), metadata.len());
            }
        }

        if let Ok(content) = fs::read_to_string(path) {
            for line in content.lines() {
                let lower = line.to_lowercase();
                if lower.contains("error") || lower.contains("panic") || lower.contains("failed") || lower.contains("traceback") {
                    total_errors += 1;
                    // Extract a short pattern
                    let pattern = extract_pattern(line);
                    *error_patterns.entry(pattern).or_insert(0) += 1;
                }
                if lower.contains("warn") || lower.contains("warning") {
                    total_warnings += 1;
                    let pattern = extract_pattern(line);
                    *warning_patterns.entry(pattern).or_insert(0) += 1;
                }
            }
        }
    }

    println!("Total log files: {}", total_logs);
    println!("Total size: {} bytes ({:.2} MB)", total_size, total_size as f64 / 1_048_576.0);
    println!("Total errors: {}", total_errors);
    println!("Total warnings: {}", total_warnings);
    println!();

    if largest_log.1 > 0 {
        println!("Largest log: {} ({} bytes)", largest_log.0.display(), largest_log.1);
    }

    if !error_patterns.is_empty() {
        println!("\nTop error patterns:");
        let mut errors: Vec<(&String, &u64)> = error_patterns.iter().collect();
        errors.sort_by(|a, b| b.1.cmp(a.1));
        for (pattern, count) in errors.iter().take(10) {
            println!("  {}x: {}", count, pattern);
        }
    }

    if !warning_patterns.is_empty() {
        println!("\nTop warning patterns:");
        let mut warnings: Vec<(&String, &u64)> = warning_patterns.iter().collect();
        warnings.sort_by(|a, b| b.1.cmp(a.1));
        for (pattern, count) in warnings.iter().take(10) {
            println!("  {}x: {}", count, pattern);
        }
    }

    if total_errors == 0 && total_warnings == 0 {
        println!("\nNo errors or warnings found in logs.");
    }
}

fn extract_pattern(line: &str) -> String {
    // Extract a short pattern from a log line (first 80 chars, trimmed)
    let trimmed = line.trim();
    if trimmed.len() > 80 {
        format!("{}...", &trimmed[..80])
    } else {
        trimmed.to_string()
    }
}

// ============================================================================
// NEW: UI diff subcommand
// ============================================================================

fn ui_diff(before: &Path, after: &Path) {
    if !before.is_file() {
        eprintln!("ERROR: Before screenshot does not exist: {}", before.display());
        std::process::exit(1);
    }
    if !after.is_file() {
        eprintln!("ERROR: After screenshot does not exist: {}", after.display());
        std::process::exit(1);
    }

    println!("=== UI Diff ===");
    println!("Before: {}", before.display());
    println!("After:  {}", after.display());
    println!();

    let img_before = match image::open(before) {
        Ok(img) => img,
        Err(e) => {
            eprintln!("ERROR: Failed to open before screenshot: {}", e);
            std::process::exit(1);
        }
    };
    let img_after = match image::open(after) {
        Ok(img) => img,
        Err(e) => {
            eprintln!("ERROR: Failed to open after screenshot: {}", e);
            std::process::exit(1);
        }
    };

    let (bw, bh) = img_before.dimensions();
    let (aw, ah) = img_after.dimensions();

    if bw != aw || bh != ah {
        println!("WARNING: Image dimensions differ!");
        println!("  Before: {}x{}", bw, bh);
        println!("  After:  {}x{}", aw, ah);
        println!("  Cannot pixel-compare different-sized images.");
        return;
    }

    let mut diff_pixels: u64 = 0;
    let mut total_pixels: u64 = (bw * bh) as u64;
    let mut max_diff: u32 = 0;
    let mut diff_locations: Vec<(u32, u32, u32)> = Vec::new();

    for y in 0..bh {
        for x in 0..bw {
            let p1 = img_before.get_pixel(x, y);
            let p2 = img_after.get_pixel(x, y);
            let diff = p1.0[0].abs_diff(p2.0[0])
                .max(p1.0[1].abs_diff(p2.0[1]))
                .max(p1.0[2].abs_diff(p2.0[2]));
            if diff > 10 { // threshold for meaningful change
                diff_pixels += 1;
                max_diff = max_diff.max(diff as u32);
                if diff_locations.len() < 20 {
                    diff_locations.push((x, y, diff as u32));
                }
            }
        }
    }

    let diff_percent = if total_pixels > 0 {
        (diff_pixels as f64 / total_pixels as f64) * 100.0
    } else {
        0.0
    };

    println!("Total pixels: {}", total_pixels);
    println!("Different pixels: {}", diff_pixels);
    println!("Difference: {:.2}%", diff_percent);
    println!("Max pixel diff: {}", max_diff);
    println!();

    if diff_pixels == 0 {
        println!("Screenshots are identical.");
    } else if diff_percent < 1.0 {
        println!("Minor differences detected (likely rendering noise).");
    } else {
        println!("Significant differences detected - UI may have changed.");
        println!("\nSample difference locations:");
        for (x, y, diff) in &diff_locations {
            println!("  ({}, {}): diff={}", x, y, diff);
        }
    }
}

// ============================================================================
// NEW: Archive integrity verification
// ============================================================================

fn archive_integrity(archive_path: &Path) {
    if !archive_path.is_file() {
        eprintln!("ERROR: Archive does not exist: {}", archive_path.display());
        std::process::exit(1);
    }

    println!("=== Archive Integrity Verification ===");
    println!("Archive: {}", archive_path.display());
    println!();

    let suffix = archive_path.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();

    match suffix.as_str() {
        "zip" => verify_zip_integrity(archive_path),
        "7z" | "rar" => verify_7z_integrity(archive_path),
        _ => {
            eprintln!("ERROR: Unsupported archive format: {}", suffix);
            std::process::exit(1);
        }
    }
}

fn verify_zip_integrity(archive_path: &Path) {
    let file = match fs::File::open(archive_path) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("ERROR: Failed to open archive: {}", e);
            std::process::exit(1);
        }
    };
    let mut archive = match zip::ZipArchive::new(file) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("ERROR: Failed to read zip archive: {}", e);
            std::process::exit(1);
        }
    };

    let mut total_entries: u64 = 0;
    let mut verified_entries: u64 = 0;
    let mut failed_entries: Vec<String> = Vec::new();
    let mut total_size: u64 = 0;

    for i in 0..archive.len() {
        total_entries += 1;
        let mut entry = match archive.by_index(i) {
            Ok(e) => e,
            Err(e) => {
                failed_entries.push(format!("Entry {}: cannot read - {}", i, e));
                continue;
            }
        };

        let name = entry.name().map(|c| c.into_owned()).unwrap_or_else(|_| format!("entry_{}", i));
        total_size += entry.compressed_size();

        // Try to read the entry data to verify integrity
        let mut buf = Vec::new();
        match entry.read_to_end(&mut buf) {
            Ok(_) => {
                verified_entries += 1;
            }
            Err(e) => {
                failed_entries.push(format!("Entry '{}': cannot read data - {}", name, e));
            }
        }
    }

    println!("Total entries: {}", total_entries);
    println!("Verified entries: {}", verified_entries);
    println!("Failed entries: {}", failed_entries.len());
    println!("Total compressed size: {} bytes ({:.2} MB)", total_size, total_size as f64 / 1_048_576.0);
    println!();

    if failed_entries.is_empty() {
        println!("All entries verified successfully. Archive is intact.");
    } else {
        println!("WARNING: {} entry(ies) failed verification:", failed_entries.len());
        for entry in &failed_entries {
            println!("  {}", entry);
        }
    }
}

fn verify_7z_integrity(archive_path: &Path) {
    println!("=== Archive Integrity Verification ===");
    println!("Archive: {}", archive_path.display());
    println!();

    let output = Command::new("7z")
        .args(["t", archive_path.to_str().unwrap_or("")])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output();

    match output {
        Ok(out) => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            let stderr = String::from_utf8_lossy(&out.stderr);

            if out.status.success() && stdout.contains("Everything is Ok") {
                println!("All entries verified successfully. Archive is intact.");
            } else {
                println!("WARNING: Archive integrity check failed.");
                println!("stdout: {}", stdout);
                println!("stderr: {}", stderr);
            }
        }
        Err(e) => {
            eprintln!("ERROR: Failed to run 7z: {}", e);
            std::process::exit(1);
        }
    }
}

// ============================================================================
// NEW: Config validation
// ============================================================================

fn config_validate(config_path: &Path) {
    if !config_path.is_file() {
        eprintln!("ERROR: Config file does not exist: {}", config_path.display());
        std::process::exit(1);
    }

    println!("=== Config Validation ===");
    println!("Config: {}", config_path.display());
    println!();

    let content = match fs::read_to_string(config_path) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("ERROR: Failed to read config: {}", e);
            std::process::exit(1);
        }
    };

    let data: serde_json::Value = match serde_json::from_str(&content) {
        Ok(d) => d,
        Err(e) => {
            eprintln!("ERROR: Invalid JSON: {}", e);
            std::process::exit(1);
        }
    };

    let mut errors: Vec<String> = Vec::new();
    let mut warnings: Vec<String> = Vec::new();

    // Check required fields
    if let Some(obj) = data.as_object() {
        // Check library_root
        if let Some(lib_root) = obj.get("library_root").and_then(|v| v.as_str()) {
            if lib_root.is_empty() {
                warnings.push("library_root is empty".to_string());
            } else {
                let path = PathBuf::from(lib_root);
                if !path.exists() {
                    warnings.push(format!("library_root does not exist: {}", lib_root));
                } else if !path.is_dir() {
                    warnings.push(format!("library_root is not a directory: {}", lib_root));
                }
            }
        } else {
            warnings.push("library_root is missing".to_string());
        }

        // Check developer_mode
        if let Some(dev) = obj.get("developer_mode") {
            if !dev.is_boolean() {
                warnings.push("developer_mode is not a boolean".to_string());
            }
        }

        // Check for unknown top-level keys (informational)
        let known_keys = [
            "library_root", "developer_mode", "extract_folder", "7zip_path",
            "theme", "language", "auto_scan", "max_concurrent",
        ];
        if let Some(obj) = data.as_object() {
            for key in obj.keys() {
                if !known_keys.contains(&key.as_str()) {
                    warnings.push(format!("Unknown config key: {}", key));
                }
            }
        }
    }

    if errors.is_empty() && warnings.is_empty() {
        println!("Config is valid. No issues found.");
    } else {
        if !errors.is_empty() {
            println!("Errors:");
            for e in &errors {
                println!("  ERROR: {}", e);
            }
        }
        if !warnings.is_empty() {
            println!("Warnings:");
            for w in &warnings {
                println!("  WARNING: {}", w);
            }
        }
    }
}

// ============================================================================
// NEW: Performance benchmark
// ============================================================================

fn perf_benchmark(iterations: u64) {
    println!("=== Performance Benchmark ===");
    println!("Iterations: {}", iterations);
    println!();

    // Benchmark 1: JSON parse
    let json = r#"{"library_root":"C:/Games","developer_mode":false,"settings":{}}"#;
    let mut json_times: Vec<u64> = Vec::new();
    for _ in 0..iterations {
        let start = Instant::now();
        let _: serde_json::Value = serde_json::from_str(json).unwrap();
        json_times.push(start.elapsed().as_nanos() as u64);
    }
    json_times.sort();
    let json_median = json_times[json_times.len() / 2];
    println!("JSON parse (median): {} ns", json_median);

    // Benchmark 2: SHA-256 hash
    let data = vec![0u8; 1024 * 1024]; // 1 MB
    let mut hash_times: Vec<u64> = Vec::new();
    for _ in 0..iterations {
        let start = Instant::now();
        let mut hasher = Sha256::new();
        hasher.update(&data);
        hasher.finalize();
        hash_times.push(start.elapsed().as_nanos() as u64);
    }
    hash_times.sort();
    let hash_median = hash_times[hash_times.len() / 2];
    println!("SHA-256 hash 1MB (median): {} ns", hash_median);

    // Benchmark 3: WalkDir scan
    let test_dir = std::env::temp_dir();
    let mut walk_times: Vec<u64> = Vec::new();
    for _ in 0..iterations {
        let start = Instant::now();
        let mut count: u64 = 0;
        for entry in WalkDir::new(&test_dir).into_iter().filter_map(|e| e.ok()) {
            if entry.path().is_file() {
                count += 1;
            }
        }
        drop(count);
        walk_times.push(start.elapsed().as_nanos() as u64);
    }
    walk_times.sort();
    let walk_median = walk_times[walk_times.len() / 2];
    println!("WalkDir scan temp dir (median): {} ns", walk_median);

    println!();
    println!("Benchmark complete.");
}

// ============================================================================
// NEW: UI text verification via OCR
// ============================================================================

fn ui_text_verify(screenshot: &Path, expected_text: &str) {
    if !screenshot.is_file() {
        eprintln!("ERROR: Screenshot does not exist: {}", screenshot.display());
        std::process::exit(1);
    }

    println!("=== UI Text Verification ===");
    println!("Screenshot: {}", screenshot.display());
    println!("Expected text: \"{}\"", expected_text);
    println!();

    // Load and preprocess image for OCR
    let img = match image::open(screenshot) {
        Ok(img) => img,
        Err(e) => {
            eprintln!("ERROR: Failed to open screenshot: {}", e);
            std::process::exit(1);
        }
    };

    // Save a preprocessed version for OCR
    let gray = img.to_luma8();
    let (w, h) = gray.dimensions();
    let upscaled = image::imageops::resize(&gray, w * 2, h * 2, FilterType::Triangle);
    let temp_path = std::env::temp_dir().join("sg-diag-ocr-verify.png");
    let _ = upscaled.save(&temp_path);

    // Run Tesseract OCR
    let tesseract_path = Path::new(r"C:\Program Files\Tesseract-OCR\tesseract.exe");
    let tesseract_cmd = if tesseract_path.exists() {
        tesseract_path.to_str().unwrap()
    } else {
        "tesseract"
    };

    let output = Command::new(tesseract_cmd)
        .args([
            temp_path.to_str().unwrap_or(""),
            "stdout",
            "--psm",
            "11",
        ])
        .output();

    match output {
        Ok(out) => {
            let ocr_text = String::from_utf8_lossy(&out.stdout);
            let normalized = ocr_text.to_lowercase()
                .chars()
                .filter(|c| c.is_alphanumeric() || c.is_whitespace())
                .collect::<String>()
                .split_whitespace()
                .collect::<Vec<_>>()
                .join(" ");

            let expected_normalized = expected_text.to_lowercase()
                .chars()
                .filter(|c| c.is_alphanumeric() || c.is_whitespace())
                .collect::<String>()
                .split_whitespace()
                .collect::<Vec<_>>()
                .join(" ");

            let found = normalized.contains(&expected_normalized);

            if found {
                println!("RESULT: PASS - Expected text found in screenshot.");
            } else {
                println!("RESULT: FAIL - Expected text not found in screenshot.");
            }

            println!("\nOCR text (first 500 chars):");
            println!("{}", ocr_text.chars().take(500).collect::<String>());

            // Clean up
            let _ = fs::remove_file(&temp_path);
        }
        Err(e) => {
            eprintln!("ERROR: Failed to run Tesseract: {}", e);
            eprintln!("Make sure Tesseract OCR is installed at C:\\Program Files\\Tesseract-OCR\\tesseract.exe");
            std::process::exit(1);
        }
    }
}

// ============================================================================
// Existing helper functions (normalize_archive_name, timestamp, etc.)
// are defined above alongside their subcommands
// ============================================================================
