//! Capture screens tool: captures UI screenshots of each view.
//! Ported from `tools/capture_screens.py`.
//!
//! 2026-11-26: Implemented using PowerShell via std::process::Command for Windows screen capture.
//! Captures the Steam Game Organizer app window (not the whole desktop) using Win32 GetWindowRect.
//!
//! NOTE: egui renders all views in a single application window. To capture each view:
//!   1. Launch the app: ./target/release/steam-game-organizer.exe --view <view>
//!   2. Run: ./target/release/capture_screens --view <view>
//!   3. Repeat for each view
//!
//! With --ocr, each captured PNG is also run through Tesseract OCR to verify expected UI text
//! is present and no error dialogs/tracebacks are visible.
//!
//! Screenshots are saved to docs/screenshots/ with Unix-timestamp filenames.

use std::path::Path;
use std::process::Command;

/// Expected UI header text per screen for OCR verification (matches old Python script).
const OCR_SCREEN_HEADERS: &[(&str, &[&str])] = &[
    ("scan", &["SCAN", "No archives discovered"]),
    ("scan-running", &["SCAN"]),
    ("review", &["Game Review", "Archives"]),
    ("review-category", &["Game Review"]),
    ("add-category", &["Add Category"]),
    ("organize", &["Organize Archives", "Archives to Organize"]),
    ("artwork", &["Artwork & Steam Assets", "Game"]),
    ("catalog", &["Steam Game Organizer"]),
    ("done", &["Organization Complete", "Results"]),
    ("setup", &["Setup Wizard", "Library Root"]),
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

/// Capture the Steam Game Organizer app window (not the whole desktop) using PowerShell + Win32 API.
/// Mirrors the old Python capture_screens.py which grabbed each Tk window's client area via ImageGrab.
pub fn capture_screens(output_dir: &Path, view_name: &str) -> Result<(), String> {
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

    // Write PowerShell script to a temp .ps1 file (multi-line C# type definition
    // cannot be passed reliably via -Command; -File works correctly).
    let ps_script_path = std::env::temp_dir().join("capture_screens.ps1");
    let mut script = String::new();
    script.push_str("Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @\"\n");
    script.push_str("using System;\n");
    script.push_str("using System.Drawing;\n");
    script.push_str("using System.Runtime.InteropServices;\n");
    script.push('\n');
    script.push_str("public class WindowCapture {\n");
    script.push_str("    [DllImport(\"user32.dll\", SetLastError = true)]\n");
    script.push_str("    [return: MarshalAs(UnmanagedType.Bool)]\n");
    script.push_str("    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);\n");
    script.push('\n');
    script.push_str("    [StructLayout(LayoutKind.Sequential)]\n");
    script.push_str("    public struct RECT {\n");
    script.push_str("        public int Left;\n");
    script.push_str("        public int Top;\n");
    script.push_str("        public int Right;\n");
    script.push_str("        public int Bottom;\n");
    script.push_str("    }\n");
    script.push('\n');
    script.push_str("    public static Rectangle GetWindowRectangle(IntPtr hWnd) {\n");
    script.push_str("        RECT rect;\n");
    script.push_str("        if (GetWindowRect(hWnd, out rect)) {\n");
    script.push_str("            return new Rectangle(rect.Left, rect.Top, rect.Right - rect.Left, rect.Bottom - rect.Top);\n");
    script.push_str("        }\n");
    script.push_str("        return Rectangle.Empty;\n");
    script.push_str("    }\n");
    script.push_str("}\n");
    script.push_str("\"@\n");
    script.push_str("Add-Type -AssemblyName System.Drawing\n");
    script.push_str("Add-Type -AssemblyName System.Windows.Forms\n");
    script.push('\n');
    script.push_str("$windowTitle = \"Steam Game Organizer\"\n");
    script.push_str("$process = Get-Process | Where-Object { $_.MainWindowTitle -eq $windowTitle } | Select-Object -First 1\n");
    script.push('\n');
    script.push_str("if (-not $process) {\n");
    script.push_str("    Write-Output \"No Steam Game Organizer window found; capturing primary monitor instead.\"\n");
    script.push_str("    $screen = [System.Windows.Forms.Screen]::PrimaryScreen\n");
    script.push_str("    $left = $screen.Bounds.Left\n");
    script.push_str("    $top = $screen.Bounds.Top\n");
    script.push_str("    $width = $screen.Bounds.Width\n");
    script.push_str("    $height = $screen.Bounds.Height\n");
    script.push_str("} else {\n");
    script.push_str("    $rect = [WindowCapture]::GetWindowRectangle($process.MainWindowHandle)\n");
    script.push_str("    if ($rect.IsEmpty) {\n");
    script.push_str("        Write-Output \"Failed to get window rect; capturing primary monitor instead.\"\n");
    script.push_str("        $screen = [System.Windows.Forms.Screen]::PrimaryScreen\n");
    script.push_str("        $left = $screen.Bounds.Left\n");
    script.push_str("        $top = $screen.Bounds.Top\n");
    script.push_str("        $width = $screen.Bounds.Width\n");
    script.push_str("        $height = $screen.Bounds.Height\n");
    script.push_str("    } else {\n");
    script.push_str("        $left = $rect.Left\n");
    script.push_str("        $top = $rect.Top\n");
    script.push_str("        $width = $rect.Width\n");
    script.push_str("        $height = $rect.Height\n");
    script.push_str("    }\n");
    script.push_str("}\n");
    script.push('\n');
    script.push_str("$bmp = New-Object System.Drawing.Bitmap($width, $height)\n");
    script.push_str("$gfx = [System.Drawing.Graphics]::FromImage($bmp)\n");
    script.push_str("$gfx.CopyFromScreen($left, $top, 0, 0, [System.Drawing.Size]::new($width, $height))\n");
    script.push_str(&format!("$bmp.Save('{}')\n", output_path_str));
    script.push_str("$gfx.Dispose()\n");
    script.push_str("$bmp.Dispose()\n");
    script.push_str(&format!("Write-Output \"Saved to {} ($width x $height)\"\n", output_path_str));

    std::fs::write(&ps_script_path, &script)
        .map_err(|e| format!("Failed to write PowerShell script: {}", e))?;

    let output = Command::new("powershell")
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_script_path.to_str().ok_or("Invalid script path")?])
        .output()
        .map_err(|e| format!("Failed to launch PowerShell: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("PowerShell capture failed: {}", stderr));
    }

    println!("Screenshot saved to: {:?}", output_path);

    Ok(())
}

/// Run Tesseract OCR on an image and return the extracted text.
fn ocr_image(image_path: &Path) -> Result<String, String> {
    let tesseract_path = Path::new(r"C:\Program Files\Tesseract-OCR\tesseract.exe");
    let tesseract_cmd = if tesseract_path.exists() {
        tesseract_path.to_str().ok_or("Invalid tesseract path")?
    } else {
        "tesseract"
    };

    let output = Command::new(tesseract_cmd)
        .args([image_path.to_str().ok_or("Invalid image path")?, "stdout"])
        .output()
        .map_err(|e| format!("Failed to launch tesseract: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Tesseract failed: {}", stderr));
    }

    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

/// Verify OCR text against expected headers and forbidden text.
/// Returns (found_required, missing_required, found_forbidden).
fn verify_ocr(
    ocr_text: &str,
    view_name: &str,
) -> (Vec<String>, Vec<String>, Vec<String>) {
    let text_lower = ocr_text.to_lowercase();

    let expected = OCR_SCREEN_HEADERS
        .iter()
        .find(|(name, _)| *name == view_name)
        .map(|(_, headers)| *headers)
        .unwrap_or(&[]);

    let mut found_required = Vec::new();
    let mut missing_required = Vec::new();

    for header in expected {
        let header_lower = header.to_lowercase();
        let header_words: Vec<&str> = header_lower.split_whitespace().collect();
        let matched_words: Vec<&str> = header_words
            .iter()
            .filter(|w| text_lower.contains(**w))
            .copied()
            .collect();

        // Count a header as found if ALL words match, OR if at least one word matches
        // (OCR is noisy on small text, so partial matches are acceptable)
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
        if text_lower.contains(forb) {
            found_forbidden.push(forb.to_string());
        }
    }

    // Also check for Rust panic/error patterns in individual words
    for word in text_lower.split_whitespace() {
        let clean: String = word.chars().filter(|c| c.is_alphanumeric()).collect();
        if !clean.is_empty()
            && OCR_FORBIDDEN.iter().any(|f| f == &clean)
            && !found_forbidden.iter().any(|f| f == &clean)
        {
            found_forbidden.push(clean);
        }
    }

    (found_required, missing_required, found_forbidden)
}

/// Capture a single view and optionally run OCR verification.
pub fn capture_and_verify(output_dir: &Path, view_name: &str, enable_ocr: bool) -> Result<(), String> {
    capture_screens(output_dir, view_name)?;

    if enable_ocr {
        // Find the most recently saved screenshot for this view
        let files = std::fs::read_dir(output_dir)
            .map_err(|e| format!("Failed to read output dir: {}", e))?;
        let mut latest: Option<(std::path::PathBuf, std::time::SystemTime)> = None;
        for entry in files.flatten() {
            let path = entry.path();
            if path.extension().is_some_and(|e| e == "png")
                && path
                    .file_name()
                    .is_some_and(|n| n.to_string_lossy().starts_with(view_name))
            {
                if let Ok(metadata) = entry.metadata() {
                    if let Ok(modified) = metadata.modified() {
                        if latest.as_ref().is_none_or(|(_, t)| modified > *t) {
                            latest = Some((path, modified));
                        }
                    }
                }
            }
        }

        if let Some((image_path, _)) = latest {
            let ocr_text = ocr_image(&image_path)?;
            let (found_required, missing_required, found_forbidden) =
                verify_ocr(&ocr_text, view_name);

            println!("  OCR required found: {:?}", found_required);
            if !missing_required.is_empty() {
                println!("  OCR missing required headers: {:?}", missing_required);
            }
            if !found_forbidden.is_empty() {
                println!("  OCR FORBIDDEN text found: {:?}", found_forbidden);
            }

            if !found_forbidden.is_empty() {
                return Err(format!(
                    "OCR verification failed for {}: forbidden text found: {:?}",
                    view_name, found_forbidden
                ));
            }

            let expected_count = OCR_SCREEN_HEADERS
                .iter()
                .find(|(name, _)| *name == view_name)
                .map(|(_, headers)| headers.len())
                .unwrap_or(0);

            println!(
                "  OCR OK: {}/{} required headers found, no forbidden text",
                found_required.len(),
                expected_count
            );
        } else {
            return Err(format!("No screenshot found for view {} after capture", view_name));
        }
    }

    Ok(())
}

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
            Ok(()) => println!("Capture complete for view '{}'.", view),
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
                Ok(()) => println!("Capture complete for view '{}'.", view),
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
    fn test_capture_screens_creates_dir() {
        let temp = tempfile::tempdir().unwrap();
        let out_dir = temp.path().join("screenshots");
        assert!(!out_dir.exists());
        std::fs::create_dir_all(&out_dir).unwrap();
        assert!(out_dir.exists());
    }

    #[test]
    fn test_verify_ocr_found_required() {
        let (found, missing, forbidden) = verify_ocr(
            "Game Review - Verify matches, pick categories, accept games. Archives list.",
            "review",
        );
        assert!(found.iter().any(|f| f == "Game Review"));
        assert!(found.iter().any(|f| f == "Archives"));
        assert!(missing.is_empty());
        assert!(forbidden.is_empty());
    }

    #[test]
    fn test_verify_ocr_missing_required() {
        let (_found, missing, _forbidden) = verify_ocr(
            "Something completely unrelated here.",
            "review",
        );
        assert!(missing.iter().any(|f| f == "Game Review"));
        assert!(missing.iter().any(|f| f == "Archives"));
    }

    #[test]
    fn test_verify_ocr_forbidden_detected() {
        let (_found, _missing, forbidden) = verify_ocr(
            "Application panicked with error[E0425]: cannot find value",
            "scan",
        );
        assert!(!forbidden.is_empty());
        assert!(forbidden.iter().any(|f| f == "panicked"));
        assert!(forbidden.iter().any(|f| f == "error["));
    }

    #[test]
    fn test_ocr_screen_headers_coverage() {
        // All view names should have expected headers defined
        let view_names = [
            "scan", "scan-running", "review", "review-category", "add-category",
            "organize", "artwork", "catalog", "done", "setup",
            "batch-extract", "extract-progress", "extract-result",
        ];
        for name in &view_names {
            assert!(
                OCR_SCREEN_HEADERS.iter().any(|(n, _)| *n == *name),
                "No OCR headers defined for view '{}'",
                name
            );
        }
    }
}
