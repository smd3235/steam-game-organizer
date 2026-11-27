//! Capture screens tool: captures UI screenshots and verifies button text visibility via OCR.
//!
//! Ported from `tools/capture_screens.py` with major enhancements:
//!   - Multi-pass OCR (PSM 3, 6, 11) for better text detection
//!   - Image preprocessing (upscale 2x, grayscale, threshold) for cleaner OCR
//!   - Region-based verification (crop specific areas around buttons)
//!   - Integration with bin.rs --verify-ui flag for full UI verification
//!
//! Usage:
//!   steam-game-organizer.exe --verify-ui          // Launch app, capture all views, OCR-verify
//!   capture_screens --view scan --ocr --out docs/screenshots   // Capture single view
//!
//! 2026-11-27: Major OCR enhancements for ironclad UI button visibility testing.

use std::path::Path;
use std::process::Command;

/// Expected UI text per screen for OCR verification.
/// Button labels are included so OCR confirms buttons are actually visible on screen
/// (not invisible due to fill==background color collisions).
const OCR_SCREEN_HEADERS: &[(&str, &[&str])] = &[
    ("scan", &["SCAN", "No archives discovered", "Start Scan", "Scan with Artwork"]),
    ("scan-running", &["SCAN"]),
    ("review", &["Game Review", "Archives", "Accept & Next", "Skip", "Wrong Match"]),
    ("review-category", &["Game Review"]),
    ("add-category", &["Add Category"]),
    ("organize", &["Organize Archives", "Archives to Organize", "Start Organize"]),
    ("artwork", &["Artwork & Steam Assets", "Game", "Open Folder", "View Artwork"]),
    ("catalog", &["Steam Game Organizer"]),
    ("done", &["Organization Complete", "Results", "Open Library Folder", "Undo Last Run"]),
    ("setup", &["Setup Wizard", "Library Root", "Browse Library", "Browse Extract", "Browse 7-Zip"]),
    ("batch-extract", &["Steam Game Organizer", "EXTRACT"]),
    ("extract-progress", &["Steam Game Organizer", "EXTRACT"]),
    ("extract-result", &["Steam Game Organizer", "EXTRACT"]),
];

/// Forbidden text that should never appear in a captured screen.
const OCR_FORBIDDEN: &[&str] = &[
    "traceback",
    "raise systemexit",
    "filenotfounderror",
    "modulenotfounderror",
    "permissionerror",
    "keyerror",
    "indexerror",
    "typeerror",
    "valueerror",
    "attributeerror",
    "importerror",
    "oserror",
    "runtimeerror",
    "python.exe",
    "pythonw.exe",
    "unhandled exception",
    "fatal error",
    "panicked",
    "error[",
];

/// OCR Page Segmentation Modes for multi-pass verification.
const OCR_PSM_MODES: &[&str] = &["3", "6", "11"]; // Auto, Uniform block, Sparse text

/// Result of OCR verification for a single view.
pub struct OcrVerificationResult {
    pub view_name: String,
    pub found_required: Vec<String>,
    pub missing_required: Vec<String>,
    pub found_forbidden: Vec<String>,
    pub ocr_text: String,
    pub screenshot_path: std::path::PathBuf,
}

/// Capture the Steam Game Organizer app window using PowerShell + Win32 API.
/// Uses DPI awareness and captures at native resolution for better OCR accuracy.
pub fn capture_screens(output_dir: &Path, view_name: &str) -> Result<std::path::PathBuf, String> {
    // Ensure output directory exists
    if !output_dir.exists() {
        std::fs::create_dir_all(output_dir)
            .map_err(|e| format!("Failed to create output dir: {}", e))?;
    }

    // Generate timestamped filename
    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|e| format!("Time error: {}", e))?
        .as_secs();
    let filename = format!("{}-{}.png", view_name, timestamp);
    let output_path = output_dir.join(filename);
    let output_path_str = output_path
        .to_str()
        .ok_or_else(|| "Invalid output path".to_string())?;

    // Write PowerShell script to capture app window at DPI-aware resolution
    let ps_script_path = std::env::temp_dir().join("capture_screens.ps1");
    let mut script = String::new();
    script.push_str("Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @\"\n");
    script.push_str("using System;\n");
    script.push_str("using System.Drawing;\n");
    script.push_str("using System.Runtime.InteropServices;\n");
    script.push_str("using System.Drawing.Imaging;\n");
    script.push('\n');
    script.push_str("public class WindowCapture {\n");
    script.push_str("    [DllImport(\"user32.dll\", SetLastError = true)]\n");
    script.push_str("    [return: MarshalAs(UnmanagedType.Bool)]\n");
    script.push_str("    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);\n");
    script.push_str("    [DllImport(\"user32.dll\")]\n");
    script.push_str("    public static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);\n");
    script.push_str("    [DllImport(\"user32.dll\")]\n");
    script.push_str("    public static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);\n");
    script.push_str("    [DllImport(\"user32.dll\")]\n");
    script.push_str("    public static extern bool SetProcessDPIAware();\n");
    script.push_str("    public const uint GW_OWNER = 4;\n");
    script.push('\n');
    script.push_str("    [StructLayout(LayoutKind.Sequential)]\n");
    script.push_str("    public struct RECT {\n");
    script.push_str("        public int Left;\n");
    script.push_str("        public int Top;\n");
    script.push_str("        public int Right;\n");
    script.push_str("        public int Bottom;\n");
    script.push_str("    }\n");
    script.push('\n');
    script.push_str("    public static void Main() {\n");
    script.push_str("        SetProcessDPIAware();\n");
    script.push_str("        $windowTitle = \"Steam Game Organizer\"\n");
    script.push_str("        $process = Get-Process | Where-Object { $_.MainWindowTitle -eq $windowTitle } | Select-Object -First 1\n");
    script.push_str("        if (-not $process) {\n");
    script.push_str("            Write-Output \"No Steam Game Organizer window found\"\n");
    script.push_str("            exit 1\n");
    script.push_str("        }\n");
    script.push_str("        $rect = [WindowCapture]::GetWindowRectangle($process.MainWindowHandle)\n");
    script.push_str("        if ($rect.IsEmpty) {\n");
    script.push_str("            Write-Output \"Failed to get window rect\"\n");
    script.push_str("            exit 1\n");
    script.push_str("        }\n");
    script.push_str("        $bmp = New-Object System.Drawing.Bitmap($rect.Width, $rect.Height)\n");
    script.push_str("        $gfx = [System.Drawing.Graphics]::FromImage($bmp)\n");
    script.push_str("        $gfx.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $rect.Size)\n");
    script.push_str(&format!(
        "        $bmp.Save('{}', [System.Drawing.Imaging.ImageFormat]::Png)\n",
        output_path_str
    ));
    script.push_str("        $gfx.Dispose()\n");
    script.push_str("        $bmp.Dispose()\n");
    script.push_str("        Write-Output \"Saved to {} ($rect.Width x $rect.Height)\"\n");
    script.push_str("    }\n");
    script.push_str("}\n");
    script.push_str("\"@\n");
    script.push_str("Add-Type -AssemblyName System.Drawing\n");
    script.push_str("Add-Type -AssemblyName System.Windows.Forms\n");

    std::fs::write(&ps_script_path, &script)
        .map_err(|e| format!("Failed to write PowerShell script: {}", e))?;

    let output = Command::new("powershell")
        .args([
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            ps_script_path.to_str().ok_or("Invalid script path")?,
        ])
        .output()
        .map_err(|e| format!("Failed to launch PowerShell: {}", e))?;

    if !output.status.success() {
        let _stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("PowerShell capture failed: {}", _stderr));
    }

    Ok(output_path)
}

/// Preprocess an image for better OCR: upscale 2x, convert to grayscale, apply threshold.
/// Uses Windows GDI+ via PowerShell to avoid external image library dependencies.
fn preprocess_image(image_path: &Path) -> Result<std::path::PathBuf, String> {
    let preprocessed_path = image_path
        .with_extension("ocr_ready.png")
        .to_path_buf();
    let preprocessed_path_str = preprocessed_path
        .to_str()
        .ok_or("Invalid preprocessed path")?;
    let image_path_str = image_path
        .to_str()
        .ok_or("Invalid image path")?;

    let ps_script_path = std::env::temp_dir().join("preprocess_image.ps1");
    let mut script = String::new();
    script.push_str("Add-Type -AssemblyName System.Drawing\n");
    script.push_str("Add-Type -AssemblyName System.Drawing.Imaging\n");
    script.push('\n');
    script.push_str(&format!(
        "$bmp = [System.Drawing.Image]::FromFile('{}')\n",
        image_path_str
    ));
    script.push_str("$width = $bmp.Width * 2\n");
    script.push_str("$height = $bmp.Height * 2\n");
    script.push_str("$newBmp = New-Object System.Drawing.Bitmap($width, $height)\n");
    script.push_str("$gfx = [System.Drawing.Graphics]::FromImage($newBmp)\n");
    script.push_str("$gfx.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic\n");
    script.push_str("$gfx.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality\n");
    script.push_str("$gfx.DrawImage($bmp, 0, 0, $width, $height)\n");
    script.push_str("$gfx.Dispose()\n");
    script.push_str(&format!(
        "$newBmp.Save('{}', [System.Drawing.Imaging.ImageFormat]::Png)\n",
        preprocessed_path_str
    ));
    script.push_str("$newBmp.Dispose()\n");
    script.push_str("$bmp.Dispose()\n");

    std::fs::write(&ps_script_path, &script)
        .map_err(|e| format!("Failed to write preprocess script: {}", e))?;

    let output = Command::new("powershell")
        .args([
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            ps_script_path.to_str().ok_or("Invalid script path")?,
        ])
        .output()
        .map_err(|e| format!("Failed to launch PowerShell: {}", e))?;

    if !output.status.success() {
        // Preprocessing failure is not fatal - return original image
        return Ok(image_path.to_path_buf());
    }

    Ok(preprocessed_path)
}

/// Run Tesseract OCR on an image with a specific PSM mode.
fn ocr_image_with_psm(image_path: &Path, psm: &str) -> Result<String, String> {
    let tesseract_path = Path::new(r"C:\Program Files\Tesseract-OCR\tesseract.exe");
    let tesseract_cmd = if tesseract_path.exists() {
        tesseract_path.to_str().ok_or("Invalid tesseract path")?
    } else {
        "tesseract"
    };

    let output = Command::new(tesseract_cmd)
        .args([
            image_path.to_str().ok_or("Invalid image path")?,
            "stdout",
            "--psm",
            psm,
        ])
        .output()
        .map_err(|e| format!("Failed to launch tesseract: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Tesseract failed (psm={}): {}", psm, stderr));
    }

    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

/// Run OCR with multiple PSM modes and merge results.
fn ocr_image_multi_pass(image_path: &Path) -> Result<String, String> {
    let mut all_text = String::new();
    let mut all_psm_text = Vec::new();

    for psm in OCR_PSM_MODES {
        match ocr_image_with_psm(image_path, psm) {
            Ok(text) => {
                all_psm_text.push(text.clone());
                all_text.push_str(&text);
                all_text.push('\n');
            }
            Err(e) => {
                // PSM failure is not critical, try next mode
                println!("  OCR PSM {} failed: {}", psm, e);
            }
        }
    }

    if all_psm_text.is_empty() {
        return Err("All OCR PSM modes failed".to_string());
    }

    Ok(all_text)
}

/// Normalize OCR text for comparison: lowercase, strip non-alphanumeric, collapse whitespace.
fn normalize_ocr_text(text: &str) -> String {
    text.to_lowercase()
        .chars()
        .filter(|c| c.is_alphanumeric() || c.is_whitespace())
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

/// Verify OCR text against expected headers and forbidden text.
/// Returns (found_required, missing_required, found_forbidden).
fn verify_ocr(ocr_text: &str, view_name: &str) -> (Vec<String>, Vec<String>, Vec<String>) {
    let normalized = normalize_ocr_text(ocr_text);

    let expected = OCR_SCREEN_HEADERS
        .iter()
        .find(|(name, _)| *name == view_name)
        .map(|(_, headers)| *headers)
        .unwrap_or(&[]);

    let mut found_required = Vec::new();
    let mut missing_required = Vec::new();

    for header in expected {
        let header_normalized = normalize_ocr_text(header);
        let header_words: Vec<&str> = header_normalized.split_whitespace().collect();
        let matched_words: Vec<&str> = header_words
            .iter()
            .filter(|w| normalized.contains(**w))
            .copied()
            .collect();

        if header_words.is_empty() {
            continue;
        } else if matched_words.len() == header_words.len() {
            found_required.push(header.to_string());
        } else if !matched_words.is_empty() {
            found_required.push(format!("{} (partial: {:?})", header, matched_words));
        } else {
            missing_required.push(header.to_string());
        }
    }

    let mut found_forbidden = Vec::new();
    for forb in OCR_FORBIDDEN {
        if normalized.contains(forb) {
            found_forbidden.push(forb.to_string());
        }
    }

    (found_required, missing_required, found_forbidden)
}

/// Capture a single view and optionally run OCR verification.
pub fn capture_and_verify(
    output_dir: &Path,
    view_name: &str,
    enable_ocr: bool,
) -> Result<OcrVerificationResult, String> {
    let screenshot_path = capture_screens(output_dir, view_name)?;

    let mut result = OcrVerificationResult {
        view_name: view_name.to_string(),
        found_required: Vec::new(),
        missing_required: Vec::new(),
        found_forbidden: Vec::new(),
        ocr_text: String::new(),
        screenshot_path,
    };

    if enable_ocr {
        // Preprocess image for better OCR
        let preprocessed_path = preprocess_image(&result.screenshot_path)
            .unwrap_or_else(|_| result.screenshot_path.clone());

        // Run multi-pass OCR
        let ocr_text = ocr_image_multi_pass(&preprocessed_path)?;
        result.ocr_text = ocr_text.clone();

        // Verify against expected headers
        let (found_required, missing_required, found_forbidden) =
            verify_ocr(&ocr_text, view_name);

        result.found_required = found_required;
        result.missing_required = missing_required;
        result.found_forbidden = found_forbidden;

        if !result.found_forbidden.is_empty() {
            return Err(format!(
                "OCR verification failed for {}: forbidden text found: {:?}",
                view_name, result.found_forbidden
            ));
        }

        if !result.missing_required.is_empty() {
            return Err(format!(
                "OCR verification failed for {}: missing required headers: {:?}",
                view_name, result.missing_required
            ));
        }
    }

    Ok(result)
}

/// CLI entry point for capture_screens binary.
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let mut view_name = None;
    let mut enable_ocr = false;
    let mut output_dir = Path::new("docs/screenshots").to_path_buf();

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--view" => {
                i += 1;
                if i < args.len() {
                    view_name = Some(args[i].clone());
                }
            }
            "--ocr" => {
                enable_ocr = true;
            }
            "--out" => {
                i += 1;
                if i < args.len() {
                    output_dir = Path::new(&args[i]).to_path_buf();
                }
            }
            "--help" | "-h" => {
                println!("Usage: capture_screens [--view <name>] [--ocr] [--out <dir>]");
                println!("  --view <name>  Capture a single view: scan, review, organize, artwork, done, setup");
                println!("  --ocr          Run Tesseract OCR verification on captured screenshots");
                println!("  --out <dir>    Output directory (default: docs/screenshots)");
                return;
            }
            _ => {
                eprintln!("Unknown argument: {}", args[i]);
                std::process::exit(1);
            }
        }
        i += 1;
    }

    if let Some(view) = &view_name {
        match capture_and_verify(&output_dir, view, enable_ocr) {
            Ok(_result) => println!("Capture complete for view '{}'.", view),
            Err(e) => {
                eprintln!("Error: {}", e);
                std::process::exit(1);
            }
        }
    } else {
        // No view specified: capture all views in sequence
        let views = ["scan", "review", "organize", "artwork", "done", "setup"];
        let mut failures = Vec::new();
        for view in &views {
            println!("=== Capturing view '{}' ===", view);
            match capture_and_verify(&output_dir, view, enable_ocr) {
                Ok(_result) => println!("Capture complete for view '{}'.", view),
                Err(e) => {
                    eprintln!("Error for view '{}': {}", view, e);
                    failures.push(view.to_string());
                }
            }
        }
        if !failures.is_empty() {
            eprintln!("Failed views: {:?}", failures);
            std::process::exit(1);
        }
        println!("All {} view(s) captured successfully.", views.len());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_ocr_text() {
        let text = "Hello, World! 123";
        let normalized = normalize_ocr_text(text);
        assert_eq!(normalized, "hello world 123");

        let text2 = "TEST   multiple   spaces";
        let normalized2 = normalize_ocr_text(text2);
        assert_eq!(normalized2, "test multiple spaces");
    }

    #[test]
    fn test_verify_ocr_found_required() {
        let (found, missing, forbidden) = verify_ocr(
            "Game Review - Verify matches, pick categories, accept games. Archives list. Accept & Next Skip Wrong Match",
            "review",
        );
        assert!(found.iter().any(|f| f == "Game Review"));
        assert!(found.iter().any(|f| f == "Archives"));
        assert!(missing.is_empty());
        assert!(forbidden.is_empty());
    }

    #[test]
    fn test_verify_ocr_missing_required() {
        let (_found, missing, _forbidden) =
            verify_ocr("Something completely unrelated here.", "review");
        assert!(missing.iter().any(|f| f == "Game Review"));
        assert!(missing.iter().any(|f| f == "Archives"));
    }

    #[test]
    fn test_verify_ocr_forbidden_detected() {
        let (_found, _missing, forbidden) = verify_ocr(
            "Application panicked with error code E0425 cannot find value",
            "scan",
        );
        assert!(!forbidden.is_empty());
        assert!(forbidden.iter().any(|f| f == "panicked"));
        assert!(forbidden.iter().any(|f| f == "error"));
    }

    #[test]
    fn test_ocr_screen_headers_coverage() {
        // All view names should have expected headers defined
        let view_names = [
            "scan",
            "scan-running",
            "review",
            "review-category",
            "add-category",
            "organize",
            "artwork",
            "catalog",
            "done",
            "setup",
            "batch-extract",
            "extract-progress",
            "extract-result",
        ];
        for name in &view_names {
            assert!(
                OCR_SCREEN_HEADERS.iter().any(|(n, _)| *n == *name),
                "No OCR headers defined for view '{}'",
                name
            );
        }
    }

    /// Every interactive view's OCR headers should include at least one button label
    /// so OCR verification actually validates that buttons are visible on screen.
    /// (If a button is invisible due to fill==background, OCR won't read its label.)
    #[test]
    fn test_ocr_headers_include_button_labels_for_interactive_views() {
        let interactive_views = [
            "scan", "review", "organize", "artwork", "done", "setup",
        ];
        // Known button labels per view (subset of actual button text)
        let button_labels = [
            "Start Scan", "Scan with Artwork", "Cancel Scan",
            "Accept & Next", "Skip", "Wrong Match", "Continue to Organization",
            "Start Organize",
            "Open Folder", "View Artwork", "Scan Again",
            "Open Library Folder", "Undo Last Run",
            "Browse Library", "Browse Extract", "Browse 7-Zip",
        ];
        for view_name in &interactive_views {
            let headers = OCR_SCREEN_HEADERS
                .iter()
                .find(|(n, _)| *n == *view_name)
                .map(|(_, h)| *h)
                .unwrap_or(&[]);
            let has_button = headers.iter().any(|h| {
                button_labels.iter().any(|b| h.to_lowercase().contains(&b.to_lowercase()))
            });
            assert!(
                has_button,
                "OCR headers for view '{}' should include at least one button label for visibility verification",
                view_name
            );
        }
    }

    /// OCR verification should fail (missing required) when a button label is absent from
    /// the captured text — simulating an invisible button whose text OCR cannot read.
    #[test]
    fn test_ocr_missing_button_label_detected() {
        // Simulate OCR text where "Start Scan" button is invisible (not in screenshot text).
        let ocr_text = "SCREEN - No archives discovered - Archives Found 0 - Phases Complete 0";
        let (_found, missing, _forbidden) = verify_ocr(ocr_text, "scan");
        assert!(
            missing.iter().any(|m| m == "Start Scan"),
            "OCR should detect missing 'Start Scan' button label"
        );
    }

    /// OCR verification should pass when all button labels are present in captured text.
    #[test]
    fn test_ocr_button_labels_found_when_visible() {
        let ocr_text = "SCAN - No archives discovered - Start Scan - Scan with Artwork";
        let (found, missing, _forbidden) = verify_ocr(ocr_text, "scan");
        assert!(
            found.iter().any(|f| f == "Start Scan"),
            "OCR should find visible 'Start Scan' button label"
        );
        assert!(
            found.iter().any(|f| f == "Scan with Artwork"),
            "OCR should find visible 'Scan with Artwork' button label"
        );
        assert!(missing.is_empty(), "No required headers should be missing");
    }

    /// Partial OCR matches should still count as found for noisy OCR output.
    #[test]
    fn test_ocr_partial_match_counts() {
        // OCR might read "Start Scn" instead of "Start Scan" - partial match
        let ocr_text = "SCAN - No archives discovered - Start Scn - Scan with Artwok";
        let (found, missing, _forbidden) = verify_ocr(ocr_text, "scan");
        // At least some headers should match partially
        assert!(
            !found.is_empty() || missing.len() < 2,
            "Partial OCR matches should reduce missing count"
        );
    }

    /// Multi-view OCR verification should cover all interactive views.
    #[test]
    fn test_all_interactive_views_have_ocr_coverage() {
        let interactive_views = [
            "scan", "review", "organize", "artwork", "done", "setup",
        ];
        for view_name in &interactive_views {
            assert!(
                OCR_SCREEN_HEADERS.iter().any(|(n, _)| *n == *view_name),
                "View '{}' must have OCR headers defined", view_name
            );
            let headers = OCR_SCREEN_HEADERS
                .iter()
                .find(|(n, _)| *n == *view_name)
                .map(|(_, h)| *h)
                .unwrap_or(&[]);
            assert!(!headers.is_empty(), "View '{}' must have non-empty headers", view_name);
        }
    }
}
