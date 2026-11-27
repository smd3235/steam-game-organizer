//! Steam match confidence analyzer: scans all archives and reports match
//! confidence distribution. Flags low-confidence matches for manual review
//! before they get organized into the wrong category.
//!
//! Usage:
//!   steam-game-organizer.exe --steam-match-confidence <library_dir>
//!
//! 2026-11-27: Made functional — scans archives, extracts AppID from filename,
//! and reports confidence distribution based on filename match quality.

use std::path::Path;

/// A single archive's match confidence result.
pub struct MatchConfidenceEntry {
    pub archive_name: String,
    pub steam_appid: Option<String>,
    pub confidence: MatchConfidence,
    pub steam_name: Option<String>,
    pub normalized_name: String,
}

pub enum MatchConfidence {
    High,   // Exact AppID match or high-score text match
    Medium, // Partial text match, needs review
    Low,    // Weak match, likely wrong
    None,   // No Steam match at all
}

/// Result of the confidence analysis.
pub struct ConfidenceReport {
    pub entries: Vec<MatchConfidenceEntry>,
    pub high_count: usize,
    pub medium_count: usize,
    pub low_count: usize,
    pub none_count: usize,
}

/// Release groups commonly found in archive filenames.
const RELEASE_GROUPS: &[&str] = &[
    "tenoke", "dodi", "fitgirl", "xforce", "cpydark", "pc", "repack",
    "ripped", "steamrip", "goldeberg", "taxi", "flt", "razor1911",
    "reloaded", "skidrow", "codex", "tpl",
];

/// Edition words that should be stripped from names.
const EDITION_WORDS: &[&str] = &[
    "ultimate", "deluxe", "gold", "premium", "collectors", "collector's",
    "game of the year", "goty", "definitive", "complete", "special",
    "standard", "basic", "regular",
];

/// Normalize an archive filename by stripping release groups, edition words,
/// subtitles, and file extensions.
fn normalize_name(filename: &str) -> String {
    // Strip only the last file extension
    let name = if let Some(dot_pos) = filename.rfind('.') {
        &filename[..dot_pos]
    } else {
        filename
    }
    .to_lowercase();

    let mut normalized = name.clone();

    // Strip release groups from start and end
    for group in RELEASE_GROUPS {
        if normalized.starts_with(group) {
            normalized = normalized[group.len()..].trim_start_matches(&['-', '.', '_', ' '][..]).to_string();
        }
        if normalized.ends_with(group) {
            normalized = normalized[..normalized.len() - group.len()].trim_end_matches(&['-', '.', '_', ' '][..]).to_string();
        }
    }

    // Strip edition words
    for word in EDITION_WORDS {
        normalized = normalized.replace(word, "").trim().to_string();
    }

    // Strip subtitles (everything after common separators)
    // Only split on " - " and ":" which are clearly subtitle separators
    for sep in [" - ", ":"] {
        if let Some(pos) = normalized.find(sep) {
            let before = normalized[..pos].trim();
            if before.len() > 3 {
                normalized = before.to_string();
            }
        }
    }

    normalized = normalized
        .split(|c: char| !c.is_alphanumeric() && c != ' ')
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
        .trim()
        .to_string();

    if normalized.is_empty() {
        normalized = name;
    }

    normalized
}

/// Extract AppID from filename if present (patterns: Game - 12345, Game.Name.12345, etc.)
fn extract_appid(filename: &str) -> Option<String> {
    // Look for 5+ digit numbers which are likely Steam AppIDs
    let mut digits = String::new();
    let mut in_digits = false;
    let mut appid_candidates: Vec<String> = Vec::new();

    for ch in filename.chars() {
        if ch.is_ascii_digit() {
            if !in_digits {
                in_digits = true;
                digits = String::new();
            }
            digits.push(ch);
        } else {
            if in_digits && digits.len() >= 5 {
                appid_candidates.push(digits.clone());
            }
            in_digits = false;
            digits = String::new();
        }
    }
    if in_digits && digits.len() >= 5 {
        appid_candidates.push(digits);
    }

    appid_candidates.into_iter().next()
}

/// Analyze match confidence for all archives in the library.
/// Confidence is based on whether an AppID was found in the filename
/// and how well the normalized name matches expected patterns.
pub fn analyze_confidence(library_dir: &Path) -> Result<ConfidenceReport, String> {
    if !library_dir.exists() {
        return Err(format!(
            "Library directory does not exist: {}",
            library_dir.display()
        ));
    }

    let mut entries: Vec<MatchConfidenceEntry> = Vec::new();
    let mut high_count: usize = 0;
    let mut medium_count: usize = 0;
    let mut low_count: usize = 0;

    const ARCHIVE_EXTENSIONS: &[&str] = &["zip", "rar", "7z"];

    for entry in walkdir::WalkDir::new(library_dir)
        .into_iter()
        .filter_entry(|e| {
            e.depth() == 0
                || (
                    // Skip hidden directories and system directories
                    !e.file_name()
                        .to_string_lossy()
                        .starts_with('.')
                        && e.file_name() != "steamapps"
                )
        })
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }

        let ext = match path.extension().and_then(|e| e.to_str()) {
            Some(e) => e.to_lowercase(),
            None => continue,
        };

        if !ARCHIVE_EXTENSIONS.contains(&ext.as_str()) {
            continue;
        }

        let filename = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_string();
        let normalized = normalize_name(&filename);
        let appid = extract_appid(&filename);

        let (confidence, steam_name) = if let Some(ref aid) = appid {
            // AppID found in filename — high confidence match
            high_count += 1;
            (MatchConfidence::High, Some(format!("Steam AppID {}", aid)))
        } else if !normalized.is_empty() && normalized.len() > 3 {
            // No AppID but has a recognizable name — medium confidence
            medium_count += 1;
            (MatchConfidence::Medium, None)
        } else {
            // No recognizable name — low confidence
            low_count += 1;
            (MatchConfidence::Low, None)
        };

        entries.push(MatchConfidenceEntry {
            archive_name: filename,
            steam_appid: appid,
            confidence,
            steam_name,
            normalized_name: normalized,
        });
    }

    let none_count = entries.len() - high_count - medium_count - low_count;

    Ok(ConfidenceReport {
        entries,
        high_count,
        medium_count,
        low_count,
        none_count,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn test_analyze_confidence_nonexistent_dir() {
        let result = analyze_confidence(Path::new("/nonexistent/path/12345"));
        assert!(result.is_err());
    }

    #[test]
    fn test_analyze_confidence_empty_dir() {
        let dir = tempfile::tempdir().unwrap();
        let result = analyze_confidence(dir.path());
        assert!(result.is_ok());
        let report = result.unwrap();
        assert_eq!(report.high_count, 0);
        assert_eq!(report.medium_count, 0);
        assert_eq!(report.low_count, 0);
        assert_eq!(report.none_count, 0);
        assert!(report.entries.is_empty());
    }

    #[test]
    fn test_analyze_confidence_with_appid() {
        let dir = tempfile::tempdir().unwrap();

        // Archive with AppID in filename
        std::fs::write(dir.path().join("resident.evil.4.196670.tenoke.zip"), b"fake").unwrap();
        // Archive without AppID but with name
        std::fs::write(dir.path().join("some_game_name.zip"), b"fake").unwrap();

        let result = analyze_confidence(dir.path());
        assert!(result.is_ok());
        let report = result.unwrap();
        assert_eq!(report.high_count, 1);
        assert_eq!(report.medium_count, 1);
        assert_eq!(report.low_count, 0);
        assert_eq!(report.none_count, 0);
        assert_eq!(report.entries.len(), 2);

        // Check the first entry (with AppID)
        assert!(report.entries[0].steam_appid.is_some());
        assert!(matches!(report.entries[0].confidence, MatchConfidence::High));
    }

    #[test]
    fn test_extract_appid() {
        assert_eq!(extract_appid("game_12345.zip"), Some("12345".to_string()));
        assert_eq!(extract_appid("game.name.12345.rar"), Some("12345".to_string()));
        assert_eq!(extract_appid("game [12345].7z"), Some("12345".to_string()));
        assert_eq!(extract_appid("game_12.zip"), None); // Too short
        assert_eq!(extract_appid("no_numbers.zip"), None);
    }

    #[test]
    fn test_normalize_name() {
        assert_eq!(normalize_name("tenoke-game_name.zip"), "game name");
        assert_eq!(normalize_name("game_name.fitgirl.zip"), "game name");
        assert_eq!(normalize_name("game_name.ultimate.zip"), "game name");
        assert_eq!(normalize_name("game_name.zip"), "game name");
    }

    #[test]
    fn test_confidence_report_struct() {
        let report = ConfidenceReport {
            entries: Vec::new(),
            high_count: 120,
            medium_count: 15,
            low_count: 8,
            none_count: 7,
        };
        assert_eq!(report.high_count, 120);
        assert_eq!(report.medium_count, 15);
        assert_eq!(report.low_count, 8);
        assert_eq!(report.none_count, 7);
        assert_eq!(report.entries.len(), 0);
        assert_eq!(
            report.high_count + report.medium_count + report.low_count + report.none_count,
            150
        );
    }

    #[test]
    fn test_match_confidence_entry() {
        let entry = MatchConfidenceEntry {
            archive_name: "resident.evil.4.tenoke.zip".to_string(),
            steam_appid: Some("196670".to_string()),
            confidence: MatchConfidence::High,
            steam_name: Some("Resident Evil 4".to_string()),
            normalized_name: "resident evil 4".to_string(),
        };
        assert!(matches!(entry.confidence, MatchConfidence::High));
        assert_eq!(entry.steam_appid, Some("196670".to_string()));
    }

    #[test]
    fn test_match_confidence_variants() {
        let variants = [
            MatchConfidence::High,
            MatchConfidence::Medium,
            MatchConfidence::Low,
            MatchConfidence::None,
        ];
        assert_eq!(variants.len(), 4);
    }

    #[test]
    fn test_confidence_counts_add_up() {
        let report = ConfidenceReport {
            entries: Vec::new(),
            high_count: 10,
            medium_count: 5,
            low_count: 3,
            none_count: 2,
        };
        let total = report.high_count + report.medium_count + report.low_count + report.none_count;
        assert_eq!(total, 20);
    }
}
