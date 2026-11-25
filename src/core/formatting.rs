//! Shared, UI-independent formatting helpers.
//!
//! These lived only in the view layer, which meant the controller had no way to report a real byte count to the
//! user without either importing UI code or growing another divergent copy of the same loop.
//!
//! 2026-11-24: Converted from `utils/formatting.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

/// Formats a byte count for humans. Returns '-' for unusable input instead of raising.
pub fn human_size(value: Option<f64>) -> String {
    let number = match value.filter(|v| v.is_finite()) {
        Some(n) => n.abs(),
        None => return "-".to_string(),
    };
    let mut number = number;
    for unit in ["B", "KB", "MB", "GB", "TB"] {
        if number < 1024.0 {
            let text = format!("{:.1}", number);
            let text = text.trim_end_matches(".0");
            return format!("{} {}", text, unit);
        }
        number /= 1024.0;
    }
    format!("{:.1} PB", number / 1024.0)
}

/// Formats an elapsed time as MM:SS, growing to H:MM:SS once a run passes the hour mark.
pub fn human_duration(seconds: Option<f64>) -> String {
    let total = match seconds.filter(|s| s.is_finite()) {
        Some(t) => t.max(0.0) as i64,
        None => 0,
    };
    let hours = total / 3600;
    let remainder = total % 3600;
    let minutes = remainder / 60;
    let secs = remainder % 60;
    if hours > 0 {
        format!("{}:{:02}:{:02}", hours, minutes, secs)
    } else {
        format!("{:02}:{:02}", minutes, secs)
    }
}

/// Returns the current local time as HH:MM:SS.
pub fn clock_stamp(when: Option<i64>) -> String {
    let secs = match when {
        Some(t) => t,
        None => std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs() as i64,
    };
    let (h, m, s) = ((secs / 3600) % 24, (secs / 60) % 60, secs % 60);
    format!("{:02}:{:02}:{:02}", h, m, s)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_human_size_bytes() {
        assert_eq!(human_size(Some(500.0)), "500 B");
    }

    #[test]
    fn test_human_size_kb() {
        assert_eq!(human_size(Some(1536.0)), "1.5 KB");
    }

    #[test]
    fn test_human_size_none() {
        assert_eq!(human_size(None), "-");
    }

    #[test]
    fn test_human_duration() {
        assert_eq!(human_duration(Some(90.0)), "01:30");
        assert_eq!(human_duration(Some(3661.0)), "1:01:01");
    }
}
