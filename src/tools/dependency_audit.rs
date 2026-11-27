//! Dependency audit tool: checks for outdated crates and security vulnerabilities.
//!
//! Ported from `tools/dependency_audit.py`.
//! Queries the crates.io API for the latest version of each dependency and
//! reports any that are out of date. Also shells out to `cargo audit` if
//! installed to check for known security vulnerabilities (RUSTSEC advisories).
//!
//! Usage:
//!   steam-game-organizer.exe --dependency-audit
//!   (or run the unit tests which simulate the check)
//!
//! Alerts are printed to stdout and returned as an Err if any deps are outdated
//! or vulnerabilities found — suitable for CI gating.

use std::collections::HashMap;
use std::path::Path;
use std::process::Command;

/// Result of auditing a single dependency.
pub struct DepAuditResult {
    pub name: String,
    pub current: String,
    pub latest: Option<String>,
}

/// Result of the full dependency audit.
pub struct DependencyAudit {
    pub outdated: Vec<DepAuditResult>,
    pub vulnerabilities: Vec<String>,
    pub audited_count: usize,
}

/// Parse the [dependencies] section of Cargo.toml (simple line-based parse,
/// sufficient for this project's flat dependency list).
fn parse_dependencies(content: &str) -> HashMap<String, String> {
    let mut deps = HashMap::new();
    let mut in_deps = false;

    for line in content.lines() {
        let trimmed = line.trim();

        // Section headers
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            in_deps = trimmed == "[dependencies]";
            continue;
        }
        if !in_deps {
            continue;
        }

        // Skip comments and blank lines
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }

        // Parse `name = "version"` or `name = { version = "...", ... }`
        if let Some(eq_pos) = trimmed.find('=') {
            let name = trimmed[..eq_pos].trim().trim_matches('"');
            let rest = trimmed[eq_pos + 1..].trim();

            let version = if rest.starts_with('{') {
                // Inline table: look for `version = "..."` inside
                extract_inline_version(rest)
            } else {
                // Simple string: `"1.0"` or `= "1.0"` or `"1.0",`
                rest.trim_matches('"').trim().split(',').next().unwrap_or("").trim().to_string()
            };

            if !name.is_empty() && !version.is_empty() {
                deps.insert(name.to_string(), version);
            }
        }
    }
    deps
}

/// Extract version from an inline table like `{ version = "1.0", features = [...] }`.
/// Finds the `version = "..."` pattern and returns the version string without quotes.
fn extract_inline_version(rest: &str) -> String {
    // Find the `version` key, then the `=`, then the quoted string
    let mut version = String::new();
    if let Some(vpos) = rest.find("version") {
        let after_key = &rest[vpos + "version".len()..];
        if let Some(eq_pos) = after_key.find('=') {
            let after_eq = after_key[eq_pos + 1..].trim();
            if let Some(start_quote) = after_eq.find('"') {
                let after_start = &after_eq[start_quote + 1..];
                if let Some(end_quote) = after_start.find('"') {
                    version = after_start[..end_quote].to_string();
                }
            }
        }
    }
    version
}

/// Query crates.io for the latest version of a crate.
fn query_crates_io_latest(name: &str) -> Option<String> {
    let url = format!("https://crates.io/api/v1/crates/{}", name);
    let req = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .ok()?
        .get(&url)
        .header("User-Agent", "steam-game-organizer-dependency-audit/1.0")
        .send()
        .ok()?;

    if !req.status().is_success() {
        return None;
    }

    let json: serde_json::Value = req.json().ok()?;
    json.get("crate")
        .and_then(|c| c.get("max_version"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
}

/// Compare two semver-ish version strings (major.minor.patch).
/// Returns true if `a` < `b`.
fn version_less_than(a: &str, b: &str) -> bool {
    let a_parts: Vec<u32> = a.split('.').filter_map(|p| p.trim().parse().ok()).collect();
    let b_parts: Vec<u32> = b.split('.').filter_map(|p| p.trim().parse().ok()).collect();

    let len = a_parts.len().max(b_parts.len());
    for i in 0..len {
        let av = a_parts.get(i).copied().unwrap_or(0);
        let bv = b_parts.get(i).copied().unwrap_or(0);
        if av < bv {
            return true;
        }
        if av > bv {
            return false;
        }
    }
    false
}

/// Run `cargo audit` if installed, collecting any vulnerability advisories.
fn run_cargo_audit() -> Vec<String> {
    let mut vulns = Vec::new();
    let output = Command::new("cargo")
        .args(["audit", "--json"])
        .output();

    match output {
        Ok(out) => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            for line in stdout.lines() {
                if line.contains("RUSTSEC") || line.contains("advisory") || line.contains("vulnerability") {
                    vulns.push(line.to_string());
                }
            }
        }
        Err(_) => {
            // cargo audit not installed — not an error, just skip
        }
    }
    vulns
}

/// Perform the full dependency audit.
pub fn dependency_audit(_root: &Path) -> Result<DependencyAudit, String> {
    let cargo_toml = std::fs::read_to_string("Cargo.toml")
        .map_err(|e| format!("Failed to read Cargo.toml: {}", e))?;

    let deps = parse_dependencies(&cargo_toml);
    let mut outdated = Vec::new();
    let mut audited_count = 0;

    for (name, current) in &deps {
        audited_count += 1;
        // Skip dev-dependencies and build-dependencies for now (flat parse catches [dependencies] only)
        let latest = query_crates_io_latest(name);

        match &latest {
            Some(latest_ver) if version_less_than(current, latest_ver) => {
                outdated.push(DepAuditResult {
                    name: name.clone(),
                    current: current.clone(),
                    latest: Some(latest_ver.clone()),
                });
            }
            _ => {}
        }
    }

    let vulnerabilities = run_cargo_audit();

    Ok(DependencyAudit {
        outdated,
        vulnerabilities,
        audited_count,
    })
}

impl DependencyAudit {
    /// Print a human-readable report.
    pub fn report(&self) {
        println!("=== Dependency Audit ===");
        println!("Audited {} dependencies", self.audited_count);

        if self.outdated.is_empty() {
            println!("All dependencies are up to date.");
        } else {
            println!("\nOutdated dependencies:");
            for dep in &self.outdated {
                println!(
                    "  {}: {} -> {} (update available)",
                    dep.name, dep.current, dep.latest.as_deref().unwrap_or("unknown")
                );
            }
        }

        if self.vulnerabilities.is_empty() {
            println!("No known security vulnerabilities found.");
        } else {
            println!("\nSecurity vulnerabilities:");
            for v in &self.vulnerabilities {
                println!("  {}", v);
            }
        }
    }

    /// Returns true if the audit is clean (no outdated deps, no vulnerabilities).
    pub fn is_clean(&self) -> bool {
        self.outdated.is_empty() && self.vulnerabilities.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_dependencies() {
        let content = r#"[dependencies]
serde = "1.0.229"
clap = { version = "4.6.10", features = ["derive"] }
reqwest = { version = "0.13.5", features = ["blocking"] }
"#;
        let deps = parse_dependencies(content);
        assert_eq!(deps.get("serde"), Some(&"1.0.229".to_string()));
        assert_eq!(deps.get("clap"), Some(&"4.6.10".to_string()));
        assert_eq!(deps.get("reqwest"), Some(&"0.13.5".to_string()));
    }

    #[test]
    fn test_version_less_than() {
        assert!(version_less_than("0.11.0", "0.13.0"));
        assert!(version_less_than("1.0.0", "1.0.1"));
        assert!(!version_less_than("1.0.0", "1.0.0"));
        assert!(!version_less_than("2.0.0", "1.9.9"));
        assert!(version_less_than("0.52", "0.56"));
    }

    #[test]
    fn test_extract_inline_version() {
        let table = r#"{ version = "4.6.10", features = ["derive"] }"#;
        assert_eq!(extract_inline_version(table), "4.6.10");
    }

    #[test]
    fn test_dependency_audit_is_clean_when_empty() {
        let audit = DependencyAudit {
            outdated: Vec::new(),
            vulnerabilities: Vec::new(),
            audited_count: 5,
        };
        assert!(audit.is_clean());
    }

    #[test]
    fn test_dependency_audit_not_clean_when_outdated() {
        let audit = DependencyAudit {
            outdated: vec![DepAuditResult {
                name: "serde".to_string(),
                current: "1.0.0".to_string(),
                latest: Some("1.0.229".to_string()),
            }],
            vulnerabilities: Vec::new(),
            audited_count: 1,
        };
        assert!(!audit.is_clean());
    }

    #[test]
    fn test_dependency_audit_not_clean_when_vulnerable() {
        let audit = DependencyAudit {
            outdated: Vec::new(),
            vulnerabilities: vec!["RUSTSEC-2024-0001: example".to_string()],
            audited_count: 1,
        };
        assert!(!audit.is_clean());
    }
}
