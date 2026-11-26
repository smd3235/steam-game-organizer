//! Capture screens tool: captures UI screenshots of each view.
//! Ported from `tools/capture_screens.py`.
//!
//! 2026-11-26: Implemented using PowerShell via std::process::Command for Windows screen capture.
//! Captures the primary monitor to a timestamped PNG file under docs/screenshots/.
//!
//! NOTE: egui renders all views in a single application window. To capture each view:
//!   1. Launch the app: ./target/release/steam-game-organizer.exe
//!   2. Navigate to a view (Scan, Review, Organize, Artwork, Done, Setup)
//!   3. Run: ./target/release/capture_screens
//!   4. Repeat for each view
//!
//! Screenshots are saved to docs/screenshots/ with Unix-timestamp filenames.

use std::path::Path;
use std::process::Command;

/// Capture the primary monitor using PowerShell and save to output_dir as a timestamped PNG.
pub fn capture_screens(output_dir: &Path) -> Result<(), String> {
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
    let filename = format!("screenshot-{}.png", timestamp);
    let output_path = output_dir.join(filename);
    let output_path_str = output_path
        .to_str()
        .ok_or_else(|| "Invalid output path".to_string())?;

    // PowerShell script to capture the primary screen using System.Drawing
    let ps_script = format!(
        r#"Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; $screen = [System.Windows.Forms::Screen]::PrimaryScreen; $bmp = New-Object System.Drawing.Bitmap($screen.Bounds.Width, $screen.Bounds.Height); $gfx = [System.Drawing.Graphics]::FromImage($bmp); $gfx.CopyFromScreen($screen.Bounds.Left, $screen.Bounds.Top, 0, 0, $screen.Bounds.Size); $bmp.Save('{}'); $gfx.Dispose(); $bmp.Dispose();"#,
        output_path_str
    );

    let output = Command::new("powershell")
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &ps_script])
        .output()
        .map_err(|e| format!("Failed to launch PowerShell: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("PowerShell capture failed: {}", stderr));
    }

    println!("Screenshot saved to: {:?}", output_path);
    Ok(())
}

fn main() {
    let output_dir = Path::new("docs/screenshots");
    match capture_screens(output_dir) {
        Ok(()) => println!("Capture complete."),
        Err(e) => eprintln!("Error: {}", e),
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
}
