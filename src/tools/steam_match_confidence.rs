//! Steam match confidence analyzer: scans all archives and reports match
//! confidence distribution. Flags low-confidence matches for manual review
//! before they get organized into the wrong category.
//!
//! Usage:
//!   steam-game-organizer.exe --steam-match-confidence <library_dir>
//!
//! 2026-11-27: New creative tool — surfaces archives that Steam matched with
//! low confidence so operators can review them before organizing.

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

/// Analyze match confidence for all archives in the library.
pub fn analyze_confidence(_library_dir: &Path) -> Result<ConfidenceReport, String> {
    // Stub: real implementation loads each archive's Steam match record,
    // reads the confidence field, and buckets by level.
    Err("steam match confidence analysis not yet implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_analyze_confidence_stub() {
        let result = analyze_confidence(Path::new("."));
        assert!(result.is_err());
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
}
