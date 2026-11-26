//! Pure utility functions extracted from ScanView.
//!
//! These functions have no dependency on ScanView instance state and can be
//! imported and tested independently. They were previously methods on ScanView
//! that took all their inputs as parameters.
//!
//! 2026-11-24: Converted from `core/scan_view_utils.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use crate::core::formatting::human_size;

/// How long ago a scan ran, in the largest unit worth naming.
pub fn ago(stamp: f64) -> String {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
        - stamp;
    let seconds = seconds.max(0.0) as i64;
    if seconds < 60 {
        return format!("{}s ago", seconds);
    }
    if seconds < 3600 {
        return format!("{}m ago", seconds / 60);
    }
    if seconds < 86400 {
        return format!("{}h ago", seconds / 3600);
    }
    format!("{}d ago", seconds / 86400)
}

/// Formats "what it was, what it became, and the difference" for one finished conversion.
pub fn space_delta(event: &serde_json::Value) -> String {
    let source = event
        .get("source_bytes")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let target = event
        .get("target_bytes")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    if source == 0 || target == 0 {
        return String::new();
    }
    let delta = target as i64 - source as i64;
    let sign = if delta > 0 { "+" } else { "-" };
    let share = if source > 0 {
        (delta.abs() as f64 / source as f64) * 100.0
    } else {
        0.0
    };
    let source_format = event
        .get("source_format")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_uppercase();
    let target_format = event
        .get("target_format")
        .and_then(|v| v.as_str())
        .unwrap_or("7Z")
        .to_uppercase();
    let lead = if !source_format.is_empty() {
        format!("{} ", source_format)
    } else {
        String::new()
    };
    format!(
        "{}{} → {} {}   ({}{:.1}, {}{:.1}%)",
        lead,
        human_size(Some(source as f64)),
        target_format,
        human_size(Some(target as f64)),
        sign,
        human_size(Some(delta.abs() as f64)),
        sign,
        share
    )
}

/// Format a byte count as a human-readable string.
pub fn size(n: Option<f64>) -> String {
    human_size(n)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ago_recent() {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();
        let result = ago(now - 30.0);
        assert!(result.contains("s ago"));
    }

    #[test]
    fn test_space_delta_no_sizes() {
        let event = serde_json::json!({});
        assert_eq!(space_delta(&event), "");
    }

    #[test]
    fn test_size_none() {
        assert_eq!(size(None), "-");
    }
}
