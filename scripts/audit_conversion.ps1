# audit_conversion.ps1 - Detects Python-to-Rust conversion anti-patterns
# Run this in CI and locally before committing to catch issues early.
#
# Usage: pwsh scripts\audit_conversion.ps1
#
# Exits non-zero if any anti-patterns are found.

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$issues = @()

function Check-Issue($file, $line, $message, $severity = "ERROR") {
    $issues += [PSCustomObject]@{
        File = $file
        Line = $line
        Message = $message
        Severity = $severity
    }
    Write-Host "[$severity] $file($line): $message" -ForegroundColor Yellow
}

# 1. Check for #![allow(clippy::all)] - suppresses ALL lints, hiding conversion bugs
Write-Host "Checking for #![allow(clippy::all)]..." -ForegroundColor Cyan
$clippyAllowFiles = Select-String -Path "$root\src\**\*.rs" -Pattern 'allow\(clippy::all\)' -ErrorAction SilentlyContinue
if ($clippyAllowFiles) {
    foreach ($match in $clippyAllowFiles) {
        $lineNum = $match.LineNumber
        $relFile = $match.Path.Substring($root.Length)
        Check-Issue -file $relFile -line $lineNum -message "#![allow(clippy::all)] suppresses all clippy lints - remove it and fix individual warnings instead" -severity "ERROR"
    }
} else {
    Write-Host "  None found" -ForegroundColor Green
}

# 2. Check for double panic hooks (std::panic::set_hook alongside logger.install_panic_hook)
Write-Host "Checking for double panic hooks..." -ForegroundColor Cyan
$panicHookFiles = Select-String -Path "$root\src\**\*.rs" -Pattern 'panic::set_hook' -ErrorAction SilentlyContinue
if ($panicHookFiles) {
    foreach ($match in $panicHookFiles) {
        $lineNum = $match.LineNumber
        $relFile = $match.Path.Substring($root.Length)
        Check-Issue -file $relFile -line $lineNum -message "std::panic::set_hook may conflict with logger.install_panic_hook() - use only the logger's panic hook" -severity "ERROR"
    }
} else {
    Write-Host "  None found" -ForegroundColor Green
}

# 3. Check for unused config field in AppController
Write-Host "Checking for unused config field..." -ForegroundColor Cyan
$unusedConfigFiles = Select-String -Path "$root\src\app\**\*.rs" -Pattern 'config: Option<Arc<AppConfig>>' -ErrorAction SilentlyContinue
if ($unusedConfigFiles) {
    foreach ($match in $unusedConfigFiles) {
        $lineNum = $match.LineNumber
        $relFile = $match.Path.Substring($root.Length)
        Check-Issue -file $relFile -line $lineNum -message "AppController has config field but set_config() may never be called - wire it to bin.rs and MainWindow" -severity "WARN"
    }
} else {
    Write-Host "  None found" -ForegroundColor Green
}

# 4. Check for stub controller methods that return empty/default results
Write-Host "Checking for stub controller methods..." -ForegroundColor Cyan
$stubFiles = Select-String -Path "$root\src\**\*.rs" -Pattern 'STUB|TODO|unimplemented|todo!' -ErrorAction SilentlyContinue
if ($stubFiles) {
    foreach ($match in $stubFiles) {
        $lineNum = $match.LineNumber
        $relFile = $match.Path.Substring($root.Length)
        Check-Issue -file $relFile -line $lineNum -message "Stub method found - verify it is implemented before release" -severity "WARN"
    }
} else {
    Write-Host "  None found" -ForegroundColor Green
}

# 5. Check for hardcoded Windows paths that should use config
Write-Host "Checking for hardcoded paths..." -ForegroundColor Cyan
$hardcodedPathFiles = Select-String -Path "$root\src\**\*.rs" -Pattern 'C:/|D:/|E:/' -ErrorAction SilentlyContinue
if ($hardcodedPathFiles) {
    foreach ($match in $hardcodedPathFiles) {
        $lineNum = $match.LineNumber
        $relFile = $match.Path.Substring($root.Length)
        Check-Issue -file $relFile -line $lineNum -message "Hardcoded Windows path - should use config value instead" -severity "WARN"
    }
} else {
    Write-Host "  None found" -ForegroundColor Green
}

# 6. Run cargo clippy if available
Write-Host "Running cargo clippy --all-targets..." -ForegroundColor Cyan
$clippyResult = & cargo clippy --all-targets 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Clippy found issues:" -ForegroundColor Yellow
    $clippyResult | Select-String -Pattern "^warning:|^error:" | Select-Object -First 50
} else {
    Write-Host "Clippy clean" -ForegroundColor Green
}

# Summary
Write-Host ""
Write-Host "=== AUDIT SUMMARY ===" -ForegroundColor Cyan
$errorCount = ($issues | Where-Object { $_.Severity -eq "ERROR" }).Count
$warnCount = ($issues | Where-Object { $_.Severity -eq "WARN" }).Count
Write-Host "Errors: $errorCount" -ForegroundColor Red
Write-Host "Warnings: $warnCount" -ForegroundColor Yellow

if ($errorCount -gt 0) {
    Write-Host "AUDIT FAILED - fix errors before committing" -ForegroundColor Red
    exit 1
} else {
    Write-Host "AUDIT PASSED" -ForegroundColor Green
    exit 0
}
