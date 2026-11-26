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

/// Capture the Steam Game Organizer app window (not the whole desktop) using PowerShell + Win32 API.
/// Mirrors the old Python capture_screens.py which grabbed each Tk window's client area via ImageGrab.
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

    // Write PowerShell script to a temp .ps1 file (multi-line C# type definition
    // cannot be passed reliably via -Command; -File works correctly).
    let ps_script_path = std::env::temp_dir().join("capture_screens.ps1");
    let mut script = String::new();
    script.push_str("Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @\"\n");
    script.push_str("using System;\n");
    script.push_str("using System.Drawing;\n");
    script.push_str("using System.Runtime.InteropServices;\n");
    script.push_str("\n");
    script.push_str("public class WindowCapture {\n");
    script.push_str("    [DllImport(\"user32.dll\", SetLastError = true)]\n");
    script.push_str("    [return: MarshalAs(UnmanagedType.Bool)]\n");
    script.push_str("    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);\n");
    script.push_str("\n");
    script.push_str("    [StructLayout(LayoutKind.Sequential)]\n");
    script.push_str("    public struct RECT {\n");
    script.push_str("        public int Left;\n");
    script.push_str("        public int Top;\n");
    script.push_str("        public int Right;\n");
    script.push_str("        public int Bottom;\n");
    script.push_str("    }\n");
    script.push_str("\n");
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
    script.push_str("\n");
    script.push_str("$windowTitle = \"Steam Game Organizer\"\n");
    script.push_str("$process = Get-Process | Where-Object { $_.MainWindowTitle -eq $windowTitle } | Select-Object -First 1\n");
    script.push_str("\n");
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
    script.push_str("\n");
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
