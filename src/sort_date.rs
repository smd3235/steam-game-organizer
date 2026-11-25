//! `sort_date` was moved here during a module split so the original file
//! stays under the size threshold. Import it from here instead of defining it
//! inline.
//!
//! Month name to number, for sorting Steam release dates.
//!
//! 2026-11-25: Converted from `services/sort_date.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::collections::HashMap;

lazy_static::lazy_static! {
    static ref MONTHS: HashMap<&'static str, u32> = {
        let mut m = HashMap::new();
        m.insert("jan", 1);
        m.insert("feb", 2);
        m.insert("mar", 3);
        m.insert("apr", 4);
        m.insert("may", 5);
        m.insert("jun", 6);
        m.insert("jul", 7);
        m.insert("aug", 8);
        m.insert("sep", 9);
        m.insert("oct", 10);
        m.insert("nov", 11);
        m.insert("dec", 12);
        m
    };
}

/// A sortable YYYYMMDD key from a Steam release date, or "00000000" when there is no usable date.
///
/// Steam writes these in at least two shapes - "Jun 24, 2026" and "1 Jan, 2024" - and any part can be missing.
/// Stripping the non-digits and taking the first four characters, which is what this did before, survives
/// neither shape: it returned "6242" for "Jun 24, 2026", because the first digits in that string are the day.
/// Sorting on that key was sorting on the day of the month.
///
/// A missing month or day becomes '00', so a date with only a year still lands in the right year and ties with
/// its neighbours instead of sorting to one end of the library.
pub fn sort_date(text: &str) -> String {
    let raw = text.trim();
    if raw.is_empty() {
        return "00000000".to_string();
    }
    let year_re = regex::Regex::new(r"\b((?:19|20)\d{2})\b").unwrap();
    let year_cap = match year_re.captures(raw) {
        Some(c) => c,
        None => return "00000000".to_string(),
    };
    let year = &year_cap[1];
    let month_re =
        regex::Regex::new(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)").unwrap();
    let month_cap = month_re.captures(raw);
    let month_str = month_cap
        .and_then(|c| c.get(1))
        .map(|m| m.as_str().to_lowercase());
    let month_num = month_str
        .as_deref()
        .and_then(|s| MONTHS.get(s))
        .copied()
        .unwrap_or(0);
    let day_re = regex::Regex::new(r"\b(\d{1,2})\b").unwrap();
    let day_cap = day_re.captures(raw);
    let day_value = day_cap
        .and_then(|c| c.get(1))
        .and_then(|m| m.as_str().parse::<u32>().ok())
        .filter(|&d| d <= 31)
        .unwrap_or(0);
    match month_str {
        Some(_) => format!("{}{:02}{:02}", year, month_num, day_value),
        None => format!("{}00{:02}", year, day_value),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sort_date_full() {
        assert_eq!(sort_date("Jun 24, 2026"), "20260624");
    }

    #[test]
    fn test_sort_date_alt() {
        assert_eq!(sort_date("1 Jan, 2024"), "20240101");
    }

    #[test]
    fn test_sort_date_year_only() {
        assert_eq!(sort_date("2023"), "20230000");
    }

    #[test]
    fn test_sort_date_empty() {
        assert_eq!(sort_date(""), "00000000");
    }
}
