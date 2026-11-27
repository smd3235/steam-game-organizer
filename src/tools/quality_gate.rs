//! Quality gate tool: runs all verification steps in one pass.
//!
//! Ported from `tools/quality_gate.py`.
//! Runs: cargo check → cargo clippy --all-targets → cargo test → cargo build --release → dependency_audit.
//! Returns Err if any step fails — suitable for CI gating.
//!
//! Usage:
//!   steam-game-organizer.exe --quality-gate

use std::path::Path;
use std::process::{Command, Stdio};

/// Result of a single quality gate step.
struct GateStep {
    name: String,
    passed: bool,
    output: String,
}

/// Full quality gate result.
pub struct QualityGateResult {
    steps: Vec<GateStep>,
    dependency_audit: Option<crate::tools::dependency_audit::DependencyAudit>,
}

/// Run a cargo subcommand and capture output.
fn run_cargo(args: &[&str]) -> GateStep {
    let name = args.first().copied().unwrap_or("cargo").to_string();
    let output = Command::new("cargo")
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output();

    match output {
        Ok(out) => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            let stderr = String::from_utf8_lossy(&out.stderr);
            let combined = format!("{}\n{}", stdout, stderr);
            let passed = out.status.success();
            GateStep {
                name,
                passed,
                output: combined.trim().to_string(),
            }
        }
        Err(e) => GateStep {
            name,
            passed: false,
            output: format!("Failed to execute cargo: {}", e),
        },
    }
}

/// Run the full quality gate pipeline.
pub fn quality_gate(_root: &Path) -> Result<QualityGateResult, String> {
    let mut steps = Vec::new();

    // Step 1: cargo check
    let check = run_cargo(&["check"]);
    steps.push(check);

    // Step 2: cargo clippy --all-targets
    let clippy = run_cargo(&["clippy", "--all-targets"]);
    steps.push(clippy);

    // Step 3: cargo test
    let test = run_cargo(&["test"]);
    steps.push(test);

    // Step 4: cargo build --release
    let build = run_cargo(&["build", "--release"]);
    steps.push(build);

    // Step 5: dependency audit
    let audit = match crate::tools::dependency_audit::dependency_audit(Path::new(".")) {
        Ok(audit) => Some(audit),
        Err(e) => {
            return Err(format!("Dependency audit failed: {}", e));
        }
    };

    Ok(QualityGateResult {
        steps,
        dependency_audit: audit,
    })
}

impl QualityGateResult {
    /// Print a human-readable report of all steps.
    pub fn report(&self) {
        println!("=== Quality Gate ===");
        for step in &self.steps {
            let status = if step.passed { "PASS" } else { "FAIL" };
            println!("[{}] {}", status, step.name);
            if !step.passed {
                for line in step.output.lines().take(20) {
                    println!("    {}", line);
                }
                if step.output.lines().count() > 20 {
                    println!("    ... (output truncated)");
                }
            }
        }

        match &self.dependency_audit {
            Some(audit) => audit.report(),
            None => println!("Dependency audit: not run"),
        }
    }

    /// Returns true if all steps passed and dependency audit is clean.
    pub fn is_clean(&self) -> bool {
        self.steps.iter().all(|s| s.passed)
            && self
                .dependency_audit
                .as_ref()
                .map(|a| a.is_clean())
                .unwrap_or(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_quality_gate_result_is_clean_when_all_pass() {
        let result = QualityGateResult {
            steps: vec![
                GateStep {
                    name: "check".to_string(),
                    passed: true,
                    output: "".to_string(),
                },
                GateStep {
                    name: "clippy".to_string(),
                    passed: true,
                    output: "".to_string(),
                },
                GateStep {
                    name: "test".to_string(),
                    passed: true,
                    output: "".to_string(),
                },
                GateStep {
                    name: "build".to_string(),
                    passed: true,
                    output: "".to_string(),
                },
            ],
            dependency_audit: Some(crate::tools::dependency_audit::DependencyAudit {
                outdated: Vec::new(),
                vulnerabilities: Vec::new(),
                audited_count: 10,
            }),
        };
        assert!(result.is_clean());
    }

    #[test]
    fn test_quality_gate_result_not_clean_when_step_fails() {
        let result = QualityGateResult {
            steps: vec![GateStep {
                name: "test".to_string(),
                passed: false,
                output: "test failed".to_string(),
            }],
            dependency_audit: Some(crate::tools::dependency_audit::DependencyAudit {
                outdated: Vec::new(),
                vulnerabilities: Vec::new(),
                audited_count: 1,
            }),
        };
        assert!(!result.is_clean());
    }

    #[test]
    fn test_quality_gate_result_not_clean_when_audit_dirty() {
        let result = QualityGateResult {
            steps: vec![GateStep {
                name: "check".to_string(),
                passed: true,
                output: "".to_string(),
            }],
            dependency_audit: Some(crate::tools::dependency_audit::DependencyAudit {
                outdated: vec![crate::tools::dependency_audit::DepAuditResult {
                    name: "serde".to_string(),
                    current: "1.0.0".to_string(),
                    latest: Some("1.0.229".to_string()),
                }],
                vulnerabilities: Vec::new(),
                audited_count: 1,
            }),
        };
        assert!(!result.is_clean());
    }
}
