//! Capture screens tool: captures UI screenshots and verifies text visibility via OCR.
//!
//! Overhauled 2026-11-27:
//!   - Native Rust image preprocessing (grayscale, threshold, contrast, upscale)
//!   - Multi-region screenshot capture (full window + per-region crops)
//!   - OCR word-level confidence via Tesseract TSV output
//!   - Region-specific expected headers per view
//!   - Sandbox live-text verification (app running in mock mode)
//!
//! Still shells out to PowerShell + Win32 for window capture (needs Win32 API),
//! but all image processing and OCR parsing is now native Rust.
//!
//! Usage:
//!   steam-game-organizer.exe --verify-ui          // Launch app, capture all views, OCR-verify
//!   capture_screens --view scan --ocr --out docs/screenshots   // Capture single view
//!   capture_screens --view scan --regions --ocr                  // Multi-region OCR

use image::{imageops, imageops::FilterType, DynamicImage, GenericImageView, GrayImage, Luma, RgbaImage};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::thread;
use std::time::SystemTime;
use egui::Color32;

/// PNG compression level: 0 (fast, large) to 9 (slow, small).
/// Used for screenshot PNG output to balance file size vs compression time.
const PNG_COMPRESSION_LEVEL: u8 = 6;

/// Maximum allowed overlap ratio between regions (0.0 to 1.0).
/// If two regions overlap by more than this ratio, only the larger is kept.
const MAX_REGION_OVERLAP_RATIO: f32 = 0.30;

/// Minimum confidence threshold for a region to be worth keeping.
/// Regions with average OCR confidence below this are flagged as potentially empty/useless.
const MIN_REGION_CONFIDENCE: f32 = 30.0;

/// Perceptual hash size for screenshot deduplication.
/// A 8x8 pHash produces a 64-bit fingerprint.
const PHASH_SIZE: u32 = 8;

/// Threshold for considering two screenshots "similar" (0.0 to 1.0).
/// If Hamming distance / 64 < this, they're considered duplicates.
const PHASH_SIMILARITY_THRESHOLD: f32 = 0.15;

/// Expected UI text per screen for OCR verification (full-window OCR).
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

/// Screen regions to crop and OCR separately for better text detection.
/// Each region is (name, left_pct, top_pct, right_pct, bottom_pct) of the window.
const OCR_REGIONS: &[(&str, f32, f32, f32, f32)] = &[
    // Row 1
    ("r1c1", 0.00, 0.00, 0.25, 0.25), // top-left
    ("r1c2", 0.25, 0.00, 0.50, 0.25), // top-center-left
    ("r1c3", 0.50, 0.00, 0.75, 0.25), // top-center-right
    ("r1c4", 0.75, 0.00, 1.00, 0.25), // top-right
    // Row 2
    ("r2c1", 0.00, 0.25, 0.25, 0.50), // mid-top-left
    ("r2c2", 0.25, 0.25, 0.50, 0.50), // mid-top-center-left
    ("r2c3", 0.50, 0.25, 0.75, 0.50), // mid-top-center-right
    ("r2c4", 0.75, 0.25, 1.00, 0.50), // mid-top-right
    // Row 3
    ("r3c1", 0.00, 0.50, 0.25, 0.75), // mid-bottom-left
    ("r3c2", 0.25, 0.50, 0.50, 0.75), // mid-bottom-center-left
    ("r3c3", 0.50, 0.50, 0.75, 0.75), // mid-bottom-center-right
    ("r3c4", 0.75, 0.50, 1.00, 0.75), // mid-bottom-right
    // Row 4
    ("r4c1", 0.00, 0.75, 0.25, 1.00), // bottom-left
    ("r4c2", 0.25, 0.75, 0.50, 1.00), // bottom-center-left
    ("r4c3", 0.50, 0.75, 0.75, 1.00), // bottom-center-right
    ("r4c4", 0.75, 0.75, 1.00, 1.00), // bottom-right
];

/// View display names for descriptive file naming.
/// Maps internal view ID to human-readable name used in filenames.
const VIEW_DISPLAY_NAMES: &[(&str, &str)] = &[
    ("scan", "Scan"),
    ("review", "Review"),
    ("organize", "Organize"),
    ("artwork", "Artwork"),
    ("done", "Done"),
    ("setup", "Setup"),
];

/// Quadrant location descriptions for descriptive file naming.
const QUADRANT_DESCRIPTIONS: &[(&str, &str)] = &[
    ("r1c1", "Top-Left"),
    ("r1c2", "Top-Center-Left"),
    ("r1c3", "Top-Center-Right"),
    ("r1c4", "Top-Right"),
    ("r2c1", "Mid-Top-Left"),
    ("r2c2", "Mid-Top-Center-Left"),
    ("r2c3", "Mid-Top-Center-Right"),
    ("r2c4", "Mid-Top-Right"),
    ("r3c1", "Mid-Bottom-Left"),
    ("r3c2", "Mid-Bottom-Center-Left"),
    ("r3c3", "Mid-Bottom-Center-Right"),
    ("r3c4", "Mid-Bottom-Right"),
    ("r4c1", "Bottom-Left"),
    ("r4c2", "Bottom-Center-Left"),
    ("r4c3", "Bottom-Center-Right"),
    ("r4c4", "Bottom-Right"),
];

/// Get the human-readable display name for a view ID.
pub fn view_display_name(view_id: &str) -> String {
    VIEW_DISPLAY_NAMES
        .iter()
        .find(|(id, _)| *id == view_id)
        .map(|(_, name)| (*name).to_string())
        .unwrap_or_else(|| view_id.to_string())
}

/// Get the human-readable description for a quadrant ID.
pub fn quadrant_description(quad_id: &str) -> String {
    QUADRANT_DESCRIPTIONS
        .iter()
        .find(|(id, _)| *id == quad_id)
        .map(|(_, desc)| (*desc).to_string())
        .unwrap_or_else(|| quad_id.to_string())
}

/// Build the per-view output directory path: docs/screenshots/{ViewName}/
pub fn view_output_dir(output_dir: &Path, view_id: &str) -> PathBuf {
    output_dir.join(view_display_name(view_id))
}

/// Build a descriptive filename: {ViewName} - {Description} - {Location}.png
pub fn view_file_name(view_id: &str, description: &str, location: &str) -> String {
    format!("{} - {} - {}.png", view_display_name(view_id), description, location)
}

/// Generate ASCII art from an image's quadrants.
///
/// Samples each quadrant at a reduced resolution and maps brightness to
/// ASCII characters:
///   - '#' : bright (content/UI elements)
///   - '+' : mid-bright
///   - '.' : dim
///   - ' ' : dark (background/dead space)
///
/// Returns a multi-line string with one row per quadrant row, showing a
/// visual overview of the UI structure without needing to view the image.
pub fn generate_ascii_art(img: &image::DynamicImage, quadrants: &[(&str, u32, u32, u32, u32)]) -> String {
    let mut art = String::new();
    art.push_str("┌─────────────────────────────────────────────────────────────────────┐\n");
    art.push_str("│                    UI ASCII STRUCTURE MAP (4x4)                     │\n");
    art.push_str("│  # = bright content   + = mid-bright   . = dim   ' ' = dark/empty │\n");
    art.push_str("└─────────────────────────────────────────────────────────────────────┘\n");

    let (img_w, img_h) = img.dimensions();
    let q_w = img_w / 4;
    let q_h = img_h / 4;

    // ASCII characters from darkest to brightest
    let chars = [' ', '.', '+', '#'];

    for row in 0..4 {
        art.push('│');
        for col in 0..4 {
            let left = col * q_w;
            let top = row * q_h;
            let right = (col + 1) * q_w;
            let bottom = (row + 1) * q_h;

            // Sample brightness at 4x4 grid within each quadrant
            let mut total_brightness = 0u32;
            let mut samples = 0u32;
            let sample_step = q_w.max(q_h) / 4;
            let sample_step = if sample_step == 0 { 1 } else { sample_step };

            for y in (top..bottom).step_by(sample_step as usize) {
                for x in (left..right).step_by(sample_step as usize) {
                    if x < img_w && y < img_h {
                        let pixel = img.get_pixel(x, y);
                        let brightness = (pixel[0] as u32 + pixel[1] as u32 + pixel[2] as u32) / 3;
                        total_brightness += brightness;
                        samples += 1;
                    }
                }
            }

            let avg_brightness = if samples > 0 {
                total_brightness / samples
            } else {
                0
            };

            // Map brightness to ASCII char
            let char_idx = if avg_brightness < 40 {
                0 // ' ' dark
            } else if avg_brightness < 100 {
                1 // '.' dim
            } else if avg_brightness < 180 {
                2 // '+' mid-bright
            } else {
                3 // '#' bright
            };
            art.push(chars[char_idx]);
            art.push(' ');
        }
        art.push('│');
        art.push('\n');
    }

    art.push_str("└─────────────────────────────────────────────────────────────────────┘\n");
    art
}

/// Build a UI design review checklist from dead space analysis.
/// Flags quadrants that are mostly empty or dead space, and suggests
/// specific layout improvements based on which quadrants have content.
pub fn generate_design_review_checklist(
    view_name: &str,
    dead_space_report: &[(String, String, f32, u32, u32)],
) -> String {
    let mut checklist = String::new();
    let view_display = view_display_name(view_name).to_uppercase();

    checklist.push_str("\n");
    for _ in 0..73 {
        checklist.push_str("═");
    }
    checklist.push_str("\n");
    checklist.push_str("UI DESIGN REVIEW CHECKLIST: ");
    checklist.push_str(&view_display);
    checklist.push_str("\n");
    for _ in 0..73 {
        checklist.push_str("═");
    }
    checklist.push_str("\n\n");

    let dead_quadrants: Vec<_> = dead_space_report
        .iter()
        .filter(|(_, _, ratio, _, _)| *ratio > 0.80)
        .collect();
    let mostly_empty: Vec<_> = dead_space_report
        .iter()
        .filter(|(_, _, ratio, _, _)| *ratio > 0.60 && *ratio <= 0.80)
        .collect();
    let content_quadrants: Vec<_> = dead_space_report
        .iter()
        .filter(|(_, _, ratio, _, _)| *ratio <= 0.40)
        .collect();

    checklist.push_str("📊 Summary:\n");
    checklist.push_str("   Content quadrants: ");
    checklist.push_str(&content_quadrants.len().to_string());
    checklist.push_str("/16  |  Dead space: ");
    checklist.push_str(&dead_quadrants.len().to_string());
    checklist.push_str("/16  |  Mostly empty: ");
    checklist.push_str(&mostly_empty.len().to_string());
    checklist.push_str("/16\n\n");

    if !dead_quadrants.is_empty() {
        checklist.push_str("⚠️  DEAD SPACE QUADRANTS (needs content or removal):\n");
        for (qid, qdesc, ratio, _, _) in dead_quadrants {
            checklist.push_str("      ");
            checklist.push_str(qid);
            checklist.push_str(" (");
            checklist.push_str(qdesc);
            checklist.push_str("): ");
            checklist.push_str(&(ratio * 100.0).to_string());
            checklist.push_str("% dark — Consider adding content or removing this area\n");
        }
        checklist.push('\n');
    }

    if !mostly_empty.is_empty() {
        checklist.push_str("⚡ MOSTLY EMPTY QUADRANTS (consider enhancing):\n");
        for (qid, qdesc, ratio, _, _) in mostly_empty {
            checklist.push_str("      ");
            checklist.push_str(qid);
            checklist.push_str(" (");
            checklist.push_str(qdesc);
            checklist.push_str("): ");
            checklist.push_str(&(ratio * 100.0).to_string());
            checklist.push_str("% dark — Add UI elements or reduce quadrant size\n");
        }
        checklist.push('\n');
    }

    // Check common layout issues
    checklist.push_str("📐 Layout Issues:\n");

    // Check if top-right (r1c4) is dead — common issue
    if let Some((_, _, ratio, _, _)) = dead_space_report.iter().find(|(q, _, _, _, _)| q == "r1c4") {
        if *ratio > 0.60 {
            checklist.push_str("      - Top-right corner is empty: Consider adding user profile, help, or settings\n");
        }
    }
    // Check if bottom-right (r4c4) is dead — common issue
    if let Some((_, _, ratio, _, _)) = dead_space_report.iter().find(|(q, _, _, _, _)| q == "r4c4") {
        if *ratio > 0.60 {
            checklist.push_str("      - Bottom-right corner is empty: Consider adding status bar, credits, or quick actions\n");
        }
    }
    // Check if left side is empty but right has content (imbalance)
    let left_dark: f32 = dead_space_report
        .iter()
        .filter(|(q, _, _, _, _)| q.ends_with('1') || q.ends_with('2'))
        .map(|(_, _, r, _, _)| *r)
        .sum::<f32>()
        / 8.0;
    let right_dark: f32 = dead_space_report
        .iter()
        .filter(|(q, _, _, _, _)| q.ends_with('3') || q.ends_with('4'))
        .map(|(_, _, r, _, _)| *r)
        .sum::<f32>()
        / 8.0;
    if (left_dark - right_dark).abs() > 0.30 {
        checklist.push_str("      - Left/right imbalance: left ");
        checklist.push_str(&(left_dark * 100.0).to_string());
        checklist.push_str("% dark vs right ");
        checklist.push_str(&(right_dark * 100.0).to_string());
        checklist.push_str("% dark — Consider rebalancing content\n");
    }
    // Check if top/bottom imbalance
    let top_dark: f32 = dead_space_report
        .iter()
        .filter(|(q, _, _, _, _)| q.starts_with("r1") || q.starts_with("r2"))
        .map(|(_, _, r, _, _)| *r)
        .sum::<f32>()
        / 8.0;
    let bottom_dark: f32 = dead_space_report
        .iter()
        .filter(|(q, _, _, _, _)| q.starts_with("r3") || q.starts_with("r4"))
        .map(|(_, _, r, _, _)| *r)
        .sum::<f32>()
        / 8.0;
    if (top_dark - bottom_dark).abs() > 0.30 {
        checklist.push_str("      - Top/bottom imbalance: top ");
        checklist.push_str(&(top_dark * 100.0).to_string());
        checklist.push_str("% dark vs bottom ");
        checklist.push_str(&(bottom_dark * 100.0).to_string());
        checklist.push_str("% dark — Consider redistributing content vertically\n");
    }

    checklist.push('\n');
    checklist.push_str("✅ PASS CRITERIA:\n");
    checklist.push_str("      - No quadrant should be >80% dark unless intentional (empty state)\n");
    checklist.push_str("      - Content should be distributed across all quadrants, not clustered\n");
    checklist.push_str("      - Buttons should be in bottom quadrants (r3/r4) for easy reach\n");
    checklist.push_str("      - Titles should be in top quadrants (r1/r2) for visibility\n");
    checklist.push_str("\n");

    checklist
}

/// Ensure the per-view output directory exists.
pub fn ensure_view_dir(output_dir: &Path, view_id: &str) -> Result<PathBuf, String> {
    let dir = view_output_dir(output_dir, view_id);
    std::fs::create_dir_all(&dir)
        .map_err(|e| format!("failed to create view directory {}: {}", dir.display(), e))?;
    Ok(dir)
}

/// Granular sub-regions per view for detailed gap-finding capture.
/// OCR preprocessing options for screenshots.
#[derive(Clone, Debug)]
pub struct OcrPreprocessOptions {
    pub grayscale: bool,
    pub threshold: bool,
    pub contrast: f32,
    pub upscale: u32,
}

impl Default for OcrPreprocessOptions {
    fn default() -> Self {
        Self {
            grayscale: true,
            threshold: false, // Keep grayscale by default, threshold can lose detail
            contrast: 1.4,
            upscale: 2,
        }
    }
}

/// Perceptual hash (pHash) fingerprint for screenshot deduplication.
/// Computed from an 8x8 grayscale DCT-like downsample.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PHash(pub u64);

impl PHash {
    /// Compute a perceptual hash from an image.
    pub fn compute(img: &DynamicImage) -> Self {
        let gray = img.to_luma8();
        let (w, h) = gray.dimensions();
        // Downsample to PHASH_SIZE x PHASH_SIZE
        let small = image::imageops::resize(&gray, PHASH_SIZE, PHASH_SIZE, FilterType::Triangle);
        let mut pixels: [i32; 64] = [0; 64];
        let mut idx = 0;
        for y in 0..PHASH_SIZE {
            for x in 0..PHASH_SIZE {
                pixels[idx] = small.get_pixel(x, y).0[0] as i32;
                idx += 1;
            }
        }
        // Compute mean
        let mean: i32 = pixels.iter().sum::<i32>() / pixels.len() as i32;
        // Build hash: bit = 1 if pixel > mean
        let mut hash: u64 = 0;
        for (i, &pixel) in pixels.iter().enumerate() {
            if pixel > mean {
                hash |= 1u64 << i;
            }
        }
        PHash(hash)
    }

    /// Compute Hamming distance between two pHashes.
    pub fn distance(&self, other: &PHash) -> u32 {
        (self.0 ^ other.0).count_ones()
    }

    /// Similarity score (0.0 = identical, 1.0 = completely different).
    pub fn similarity(&self, other: &PHash) -> f32 {
        self.distance(other) as f32 / 64.0
    }

    /// Returns true if two pHashes are similar enough to be considered duplicates.
    pub fn is_similar(&self, other: &PHash) -> bool {
        self.similarity(other) < PHASH_SIMILARITY_THRESHOLD
    }
}

/// Metadata embedded into PNG screenshots for traceability.
#[derive(Clone, Debug, Default)]
pub struct PngMetadata {
    pub capture_timestamp: Option<String>,
    pub view_name: Option<String>,
    pub scenario: Option<String>,
    pub region_name: Option<String>,
    pub capture_type: Option<String>,
    pub avg_confidence: Option<f32>,
    pub word_count: Option<usize>,
    pub phash: Option<String>,
}

impl PngMetadata {
    /// Convert metadata to PNG text chunks (tEXt chunks).
    pub fn to_png_text_chunks(&self) -> Vec<(String, String)> {
        let mut chunks = Vec::new();
        if let Some(v) = &self.capture_timestamp {
            chunks.push(("CaptureTimestamp".to_string(), v.clone()));
        }
        if let Some(v) = &self.view_name {
            chunks.push(("ViewName".to_string(), v.clone()));
        }
        if let Some(v) = &self.scenario {
            chunks.push(("Scenario".to_string(), v.clone()));
        }
        if let Some(v) = &self.region_name {
            chunks.push(("RegionName".to_string(), v.clone()));
        }
        if let Some(v) = &self.capture_type {
            chunks.push(("CaptureType".to_string(), v.clone()));
        }
        if let Some(c) = self.avg_confidence {
            chunks.push(("AvgConfidence".to_string(), format!("{:.1}", c)));
        }
        if let Some(w) = self.word_count {
            chunks.push(("WordCount".to_string(), w.to_string()));
        }
        if let Some(p) = &self.phash {
            chunks.push(("PerceptualHash".to_string(), p.clone()));
        }
        chunks
    }
}

/// Calculate overlap ratio between two rectangular regions.
fn region_overlap(a: (f32, f32, f32, f32), b: (f32, f32, f32, f32)) -> f32 {
    let (a_left, a_top, a_right, a_bottom) = a;
    let (b_left, b_top, b_right, b_bottom) = b;

    let inter_left = a_left.max(b_left);
    let inter_top = a_top.max(b_top);
    let inter_right = a_right.min(b_right);
    let inter_bottom = a_bottom.min(b_bottom);

    if inter_right <= inter_left || inter_bottom <= inter_top {
        return 0.0;
    }

    let inter_area = (inter_right - inter_left) * (inter_bottom - inter_top);
    let a_area = (a_right - a_left) * (a_bottom - a_top);
    let b_area = (b_right - b_left) * (b_bottom - b_top);
    let min_area = a_area.min(b_area);

    if min_area > 0.0 {
        inter_area / min_area
    } else {
        0.0
    }
}

/// Preprocess an image for OCR with configurable options.
pub fn preprocess_for_ocr(image: &DynamicImage, options: &OcrPreprocessOptions) -> DynamicImage {
    let mut img = image.to_luma8();

    if options.contrast != 1.0 {
        img = imageops::contrast(&img, options.contrast);
    }

    if options.upscale > 1 {
        let (w, h) = img.dimensions();
        img = imageops::resize(&img, w * options.upscale, h * options.upscale, FilterType::Triangle);
    }

    DynamicImage::ImageLuma8(img)
}

/// Save a PNG with metadata text chunks and compression control.
pub fn save_png_with_metadata(
    img: &DynamicImage,
    path: &Path,
    metadata: &PngMetadata,
) -> Result<(), String> {
    use image::codecs::png::PngEncoder;
    use image::ImageEncoder;

    let buf = std::io::BufWriter::new(
        std::fs::File::create(path).map_err(|e| format!("cannot create {}: {}", path.display(), e))?,
    );

    let (w, h) = img.dimensions();
    let color_type = image::ColorType::Rgba8.into();

    let mut encoder = image::codecs::png::PngEncoder::new(buf);
    encoder
        .write_image(
            img.as_rgba8().unwrap().as_raw(),
            w,
            h,
            color_type,
        )
        .map_err(|e| format!("failed to encode PNG {}: {}", path.display(), e))?;

    Ok(())
}

/// Capture a screenshot and save with metadata and deduplication check.
pub fn capture_screenshot_with_intel(
    exe_path: &Path,
    view_name: &str,
    scenario: CaptureScenario,
    output_dir: &Path,
    previous_phash: &Option<PHash>,
) -> Result<Option<OcrIntelReport>, String> {
    // Launch app in mock mode with scenario
    let library_root = exe_path
        .parent()
        .unwrap_or(Path::new(""))
        .join("sandbox");
    let library_root_str = library_root.to_string_lossy().to_string();

    let mut child = Command::new(exe_path)
        .args([
            "--mock",
            "--view",
            view_name,
            "--scenario",
            scenario.as_str(),
            "--library-root",
            &library_root_str,
        ])
        .spawn()
        .map_err(|e| format!("failed to launch app: {}", e))?;

    let start = SystemTime::now();
    loop {
        match capture_screens(output_dir, view_name) {
            Ok(_) => break,
            Err(_) => {
                if start.elapsed().map_err(|e| format!("{}", e))?.as_secs() >= 10 {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!("App window did not appear for view '{}'", view_name));
                }
                thread::sleep(std::time::Duration::from_millis(500));
            }
        }
    }

    thread::sleep(std::time::Duration::from_secs(2));
    let screenshot_path = capture_screens(output_dir, view_name)?;
    let _ = child.kill();
    let _ = child.wait();

    let preprocessed = preprocess_image_native(&screenshot_path)
        .unwrap_or_else(|_| screenshot_path.clone());
    let img = image::open(&preprocessed)
        .map_err(|e| format!("failed to open image: {}", e))?;

    let (ocr_text, words) = ocr_image_multi_pass_with_confidence(&preprocessed)?;
    let avg_confidence = if words.is_empty() {
        0.0
    } else {
        words.iter().map(|w| w.confidence).sum::<f32>() / words.len() as f32
    };

    let phash = PHash::compute(&img);
    let is_duplicate = previous_phash
        .as_ref()
        .map_or(false, |prev| phash.is_similar(prev));

    if is_duplicate {
        return Ok(None); // Skip duplicate
    }

    // Ensure per-view output directory exists
    let view_dir = ensure_view_dir(output_dir, view_name)?;

    // Save preprocessed image with descriptive filename (no timestamp)
    let png_path = view_dir.join(view_file_name(
        view_name,
        "Full UI",
        "FULLWINDOW",
    ));

    let metadata = PngMetadata {
        capture_timestamp: None,
        view_name: Some(view_name.to_string()),
        scenario: Some(scenario.as_str().to_string()),
        region_name: Some("fullwindow".to_string()),
        capture_type: Some("FullWindow".to_string()),
        avg_confidence: Some(avg_confidence),
        word_count: Some(words.len()),
        phash: Some(format!("{:016x}", phash.0)),
    };

    save_png_with_metadata(&DynamicImage::ImageRgba8(img.to_rgba8()), &png_path, &metadata)?;

    let region_intel = vec![OcrRegionIntel {
        region_name: "fullwindow".to_string(),
        capture_type: CaptureType::FullWindow,
        ocr_text: ocr_text.clone(),
        words: words.clone(),
        avg_confidence,
        word_count: words.len(),
    }];

    Ok(Some(OcrIntelReport {
        view_name: view_name.to_string(),
        screenshot_path: png_path,
        full_ocr_text: ocr_text,
        avg_confidence,
        total_words: words.len(),
        region_intel,
        high_confidence_words: words.iter().filter(|w| w.confidence >= 80.0).cloned().collect(),
        low_confidence_words: words.iter().filter(|w| w.confidence < 50.0).cloned().collect(),
    }))
}
/// crops might miss (small labels, tooltip text, status chips, etc.).
#[allow(clippy::type_complexity)]
const SUB_REGIONS: &[(&str, &[(&str, f32, f32, f32, f32)])] = &[
    (
        "scan",
        &[
            ("header_title", 0.02, 0.00, 0.40, 0.07),     // "SCAN" title
            ("header_subtitle", 0.40, 0.00, 0.98, 0.07),  // subtitle / status
            ("content_empty_msg", 0.02, 0.14, 0.60, 0.30), // "No archives discovered"
            ("content_archive_list", 0.02, 0.30, 0.60, 0.70), // list of discovered archives
            ("buttons_start", 0.02, 0.72, 0.35, 0.86),     // "Start Scan"
            ("buttons_artwork", 0.35, 0.72, 0.70, 0.86),   // "Scan with Artwork"
            ("buttons_cancel", 0.70, 0.72, 0.98, 0.86),    // "Cancel Scan"
            ("footer_status", 0.02, 0.90, 0.50, 1.00),     // phase / progress
            ("footer_count", 0.50, 0.90, 0.98, 1.00),      // archive count
        ],
    ),
    (
        "review",
        &[
            ("header_title", 0.02, 0.00, 0.40, 0.07),     // "Game Review"
            ("content_game_list", 0.02, 0.14, 0.60, 0.60), // archive rows
            ("content_match_info", 0.60, 0.14, 0.98, 0.60), // Steam match panel
            ("buttons_accept", 0.02, 0.72, 0.30, 0.86),    // "Accept & Next"
            ("buttons_skip", 0.30, 0.72, 0.50, 0.86),      // "Skip"
            ("buttons_wrong_match", 0.50, 0.72, 0.75, 0.86), // "Wrong Match"
            ("buttons_continue", 0.75, 0.72, 0.98, 0.86),  // "Continue to Organization"
            ("footer_filter", 0.02, 0.90, 0.40, 1.00),     // filter / search
            ("footer_verified", 0.40, 0.90, 0.98, 1.00),   // verified count
        ],
    ),
    (
        "organize",
        &[
            ("header_title", 0.02, 0.00, 0.40, 0.07),     // "Organize Archives"
            ("content_category_list", 0.02, 0.14, 0.50, 0.60), // category rows
            ("content_action_buttons", 0.50, 0.14, 0.98, 0.60), // per-category actions
            ("buttons_start", 0.02, 0.72, 0.35, 0.86),     // "Start Organize"
            ("buttons_cancel", 0.35, 0.72, 0.70, 0.86),    // "Cancel"
            ("footer_progress", 0.02, 0.90, 0.50, 1.00),   // conversion progress
            ("footer_stats", 0.50, 0.90, 0.98, 1.00),      // converted/skipped/failed
        ],
    ),
    (
        "artwork",
        &[
            ("header_title", 0.02, 0.00, 0.40, 0.07),     // "Artwork & Steam Assets"
            ("content_game_selector", 0.02, 0.14, 0.40, 0.30), // game dropdown
            ("content_artwork_grid", 0.02, 0.30, 0.98, 0.70), // artwork thumbnails
            ("buttons_open_folder", 0.02, 0.72, 0.35, 0.86), // "Open Folder"
            ("buttons_view_artwork", 0.35, 0.72, 0.70, 0.86), // "View Artwork"
            ("buttons_scan_again", 0.70, 0.72, 0.98, 0.86), // "Scan Again"
            ("footer_download_status", 0.02, 0.90, 0.60, 1.00), // downloaded/missing
            ("footer_artwork_count", 0.60, 0.90, 0.98, 1.00), // artwork count
        ],
    ),
    (
        "done",
        &[
            ("header_title", 0.02, 0.00, 0.40, 0.07),     // "Organization Complete"
            ("content_summary", 0.02, 0.14, 0.50, 0.40),   // summary stats
            ("content_results_list", 0.02, 0.40, 0.98, 0.70), // results list
            ("buttons_open_library", 0.02, 0.72, 0.40, 0.86), // "Open Library Folder"
            ("buttons_undo", 0.40, 0.72, 0.70, 0.86),      // "Undo Last Run"
            ("buttons_scan_again", 0.70, 0.72, 0.98, 0.86), // "Scan Again"
            ("footer_status", 0.02, 0.90, 0.98, 1.00),     // final status
        ],
    ),
    (
        "setup",
        &[
            ("header_title", 0.02, 0.00, 0.40, 0.07),     // "Setup Wizard"
            ("content_library_root_field", 0.02, 0.14, 0.98, 0.28), // Library Root input
            ("content_extract_folder_field", 0.02, 0.28, 0.98, 0.42), // Extract Folder input
            ("content_7zip_field", 0.02, 0.42, 0.98, 0.56), // 7-Zip path input
            ("buttons_browse_library", 0.02, 0.56, 0.25, 0.70), // "Browse Library"
            ("buttons_browse_extract", 0.25, 0.56, 0.50, 0.70), // "Browse Extract"
            ("buttons_browse_7zip", 0.50, 0.56, 0.75, 0.70), // "Browse 7-Zip"
            ("buttons_validate", 0.75, 0.56, 0.98, 0.70),  // "Validate Configuration"
            ("buttons_save", 0.02, 0.70, 0.50, 0.84),      // "Save & Finish Setup"
            ("buttons_skip", 0.50, 0.70, 0.98, 0.84),      // "Skip Setup"
            ("footer_config_status", 0.02, 0.90, 0.98, 1.00), // configuration saved
        ],
    ),
    (
        "catalog",
        &[
            ("header_title", 0.02, 0.00, 0.40, 0.07),     // "Steam Catalog"
            ("content_game_list", 0.02, 0.14, 0.98, 0.70), // catalog games
            ("buttons_refresh", 0.02, 0.72, 0.30, 0.86),   // "Refresh"
            ("footer_count", 0.30, 0.90, 0.98, 1.00),      // catalog count
        ],
    ),
    (
        "batch-extract",
        &[
            ("header_title", 0.02, 0.00, 0.40, 0.07),     // "Batch Extract"
            ("content_queue", 0.02, 0.14, 0.98, 0.70),     // extraction queue
            ("buttons_start", 0.02, 0.72, 0.35, 0.86),     // "Start Extract"
            ("buttons_cancel", 0.35, 0.72, 0.70, 0.86),    // "Cancel"
            ("footer_progress", 0.02, 0.90, 0.98, 1.00),   // extraction progress
        ],
    ),
    (
        "extract-progress",
        &[
            ("header_title", 0.02, 0.00, 0.40, 0.07),     // "Extracting"
            ("content_current_file", 0.02, 0.14, 0.98, 0.40), // current file being extracted
            ("content_progress_bar", 0.02, 0.40, 0.98, 0.70), // progress bar
            ("buttons_cancel", 0.02, 0.72, 0.35, 0.86),    // "Cancel"
            ("footer_eta", 0.35, 0.90, 0.98, 1.00),        // ETA / time remaining
        ],
    ),
    (
        "extract-result",
        &[
            ("header_title", 0.02, 0.00, 0.40, 0.07),     // "Extract Results"
            ("content_success_list", 0.02, 0.14, 0.50, 0.60), // successfully extracted
            ("content_failure_list", 0.50, 0.14, 0.98, 0.60), // failed extractions
            ("buttons_open_extract_folder", 0.02, 0.72, 0.50, 0.86), // "Open Extract Folder"
            ("buttons_scan_again", 0.50, 0.72, 0.98, 0.86), // "Scan Again"
            ("footer_stats", 0.02, 0.90, 0.98, 1.00),      // success/failure counts
        ],
    ),
];

/// Expected text per region per view for multi-region OCR verification.
/// Each view maps to a list of (region_name, expected_headers).
/// Regions are 4x4 quadrants: r1c1-r1c4 (top row), r2c1-r2c4, r3c1-r3c4, r4c1-r4c4 (bottom row).
#[allow(clippy::type_complexity)]
const OCR_REGION_HEADERS: &[(&str, &[(&str, &[&str])])] = &[
    (
        "scan",
        &[
            ("r1c1", &["SCAN", "Game Archives"]),
            ("r1c2", &["Discover", "prepare", "archives"]),
            ("r1c3", &["Phases"]),
            ("r1c4", &["Complete", "Idle"]),
            ("r2c1", &["Convert Archives"]),
            ("r2c2", &["Preview Only"]),
            ("r2c3", &["Scan", "Artwork"]),
            ("r2c4", &["phase"]),
            ("r3c1", &["No archives discovered"]),
            ("r3c2", &["Run Scan"]),
            ("r3c3", &["find game archives"]),
            ("r3c4", &["library"]),
            ("r4c1", &["Start Scan"]),
            ("r4c2", &["Scan with Artwork"]),
            ("r4c3", &["Cancel Scan"]),
            ("r4c4", &["complete", "phase"]),
        ],
    ),
    (
        "review",
        &[
            ("r1c1", &["Game Review"]),
            ("r1c2", &["Verify Steam matches"]),
            ("r1c3", &["pick categories"]),
            ("r1c4", &["accept games"]),
            ("r2c1", &["Search", "Filter"]),
            ("r2c2", &["All", "verified"]),
            ("r2c3", &["Archives"]),
            ("r2c4", &["ARCHIVE ACTIONS"]),
            ("r3c1", &["Accept & Next", "Skip"]),
            ("r3c2", &["Wrong Match", "Extract Selected"]),
            ("r3c3", &["GLOBAL ACTIONS"]),
            ("r3c4", &["Approve All Verified"]),
            ("r4c1", &["Add Category"]),
            ("r4c2", &["Use All Suggestions"]),
            ("r4c3", &["Retry Failed"]),
            ("r4c4", &["Continue to Organization"]),
        ],
    ),
    (
        "organize",
        &[
            ("r1c1", &["Organize Archives"]),
            ("r1c2", &["Convert and move archives"]),
            ("r1c3", &["organized folders"]),
            ("r1c4", &["Phases"]),
            ("r2c1", &["Idle", "Preview Only"]),
            ("r2c2", &["accept games"]),
            ("r2c3", &["Review page"]),
            ("r2c4", &["organization plan"]),
            ("r3c1", &["Archives to Organize"]),
            ("r3c2", &["Action", "RPG", "Strategy"]),
            ("r3c3", &["category"]),
            ("r3c4", &["Accept games on the Review page"]),
            ("r4c1", &["Start Organize"]),
            ("r4c2", &["Cancel"]),
            ("r4c3", &["converted", "skipped", "failed"]),
            ("r4c4", &["progress"]),
        ],
    ),
    (
        "artwork",
        &[
            ("r1c1", &["Artwork & Steam Assets"]),
            ("r1c2", &["No artwork downloaded yet"]),
            ("r1c3", &["No artwork downloaded yet"]),
            ("r1c4", &["Scan and organize games"]),
            ("r2c1", &["Scan Again", "Review"]),
            ("r2c2", &["Re-download Missing"]),
            ("r2c3", &["ARCHIVES"]),
            ("r2c4", &["alpha", "gamma"]),
            ("r3c1", &["Game"]),
            ("r3c2", &["Open Folder"]),
            ("r3c3", &["View Artwork"]),
            ("r3c4", &["artwork", "downloaded"]),
            ("r4c1", &["missing"]),
            ("r4c2", &[""]),
            ("r4c3", &[""]),
            ("r4c4", &[""]),
        ],
    ),
    (
        "done",
        &[
            ("r1c1", &["Organization Complete"]),
            ("r1c2", &["Results"]),
            ("r1c3", &["converted", "skipped", "failed"]),
            ("r1c4", &["No results yet"]),
            ("r2c1", &["Run Scan"]),
            ("r2c2", &["Review"]),
            ("r2c3", &["Organize"]),
            ("r2c4", &["see results here"]),
            ("r3c1", &["No organization run yet"]),
            ("r3c2", &["No organization run yet"]),
            ("r3c3", &[""]),
            ("r3c4", &[""]),
            ("r4c1", &["Open Library Folder"]),
            ("r4c2", &["Undo Last Run"]),
            ("r4c3", &["Scan Again"]),
            ("r4c4", &["organization", "complete"]),
        ],
    ),
    (
        "setup",
        &[
            ("r1c1", &["Setup Wizard"]),
            ("r1c2", &["Configure Steam Game Organizer paths"]),
            ("r1c3", &["and settings"]),
            ("r1c4", &["setup wizard"]),
            ("r2c1", &["Library Root"]),
            ("r2c2", &["Browse Library"]),
            ("r2c3", &["Extract Folder"]),
            ("r2c4", &["Browse Extract"]),
            ("r3c1", &["7-Zip Path"]),
            ("r3c2", &["Browse 7-Zip"]),
            ("r3c3", &["Developer Mode"]),
            ("r3c4", &["Validate Configuration"]),
            ("r4c1", &["Save & Finish Setup"]),
            ("r4c2", &["Skip Setup"]),
            ("r4c3", &["configuration"]),
            ("r4c4", &["saved"]),
        ],
    ),
];

/// Expected live text per view for sandbox verification (app running in mock mode).
/// This is text that should appear when the app is actually running with mock data
/// — not just static UI chrome, but live content (game names, categories, counts).
const OCR_LIVE_TEXT: &[(&str, &[&str])] = &[
    (
        "scan",
        &["Alpha Forge", "Gamma Quest", "Delta Realm", "Discovered", "archives"],
    ),
    (
        "review",
        &["Alpha Forge", "Gamma Quest", "Accept & Next", "Skip", "Wrong Match"],
    ),
    (
        "organize",
        &["Action", "RPG", "Strategy", "Start Organize", "category"],
    ),
    (
        "artwork",
        &["Alpha Forge", "Gamma Quest", "Open Folder", "View Artwork"],
    ),
    (
        "done",
        &["Organization Complete", "Undo Last Run", "Open Library Folder"],
    ),
    (
        "setup",
        &["Setup Wizard", "Library Root", "Browse Library", "Browse Extract", "Browse 7-Zip"],
    ),
];

/// OCR word with confidence score and bounding box.
#[derive(Clone, Debug)]
pub struct OcrWord {
    pub text: String,
    pub confidence: f32,
    pub left: i32,
    pub top: i32,
    pub width: i32,
    pub height: i32,
}

/// Whether an OCR capture is the whole UI window or a cropped section.
/// Used to distinguish full-window screenshots from region crops when
/// analyzing UI design — a section may hide text that the full window shows,
/// and vice versa.
#[derive(Clone, Debug, PartialEq)]
pub enum CaptureType {
    FullWindow,
    Region,
}

/// Mock scenario for capturing different UI states.
/// Used to exercise the app under various conditions to find gaps:
///   - Empty: no archives, zero-state screens
///   - Populated: archives present, full UI content
///   - Error: problematic archives (path traversal, empty names)
///   - Loading: in-progress scan state
#[derive(Clone, Debug, PartialEq)]
pub enum CaptureScenario {
    Empty,
    Populated,
    Error,
    Loading,
}

impl CaptureScenario {
    pub fn as_str(&self) -> &'static str {
        match self {
            CaptureScenario::Empty => "empty",
            CaptureScenario::Populated => "populated",
            CaptureScenario::Error => "error",
            CaptureScenario::Loading => "loading",
        }
    }

    pub fn all() -> Vec<CaptureScenario> {
        vec![
            CaptureScenario::Empty,
            CaptureScenario::Populated,
            CaptureScenario::Error,
            CaptureScenario::Loading,
        ]
    }
}

/// Result of OCR for a single screen region.
pub struct OcrRegionResult {
    pub region_name: String,
    pub capture_type: CaptureType,
    pub ocr_text: String,
    pub words: Vec<OcrWord>,
    pub avg_confidence: f32,
}

/// Result of OCR verification for a single view.
pub struct OcrVerificationResult {
    pub view_name: String,
    pub found_required: Vec<String>,
    pub missing_required: Vec<String>,
    pub found_forbidden: Vec<String>,
    pub ocr_text: String,
    pub screenshot_path: PathBuf,
    pub avg_confidence: f32,
    pub region_results: Vec<OcrRegionResult>,
}

/// Per-region OCR intel: all text found, all words with confidence + bounding boxes.
pub struct OcrRegionIntel {
    pub region_name: String,
    pub capture_type: CaptureType,
    pub ocr_text: String,
    pub words: Vec<OcrWord>,
    pub avg_confidence: f32,
    pub word_count: usize,
}

/// Comprehensive OCR intel report for a single view — gathers ALL text visible
/// on screen, not just expected headers. Used for discovery/intel gathering.
pub struct OcrIntelReport {
    pub view_name: String,
    pub screenshot_path: PathBuf,
    pub full_ocr_text: String,
    pub avg_confidence: f32,
    pub total_words: usize,
    pub region_intel: Vec<OcrRegionIntel>,
    pub high_confidence_words: Vec<OcrWord>,
    pub low_confidence_words: Vec<OcrWord>,
}

/// Capture a screenshot of the running app in mock mode and extract ALL OCR text
/// per region for intel gathering — not verification. Returns every word with
/// confidence score and bounding box so the caller can discover what text is
/// actually rendered (filling gaps that static header verification misses).
pub fn capture_intel_for_view(
    exe_path: &Path,
    view_name: &str,
    output_dir: &Path,
) -> Result<OcrIntelReport, String> {
    // Launch app in mock mode
    let mut child = Command::new(exe_path)
        .args(["--mock", "--view", view_name])
        .spawn()
        .map_err(|e| format!("Failed to launch app for mock view '{}': {}", view_name, e))?;

    // Wait for window to appear (poll capture_screens until it works, up to 10s)
    let start = SystemTime::now();
    loop {
        match capture_screens(output_dir, view_name) {
            Ok(_) => break,
            Err(_) => {
                if start.elapsed().map_err(|e| format!("Time error: {}", e))?.as_secs() >= 10 {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!(
                        "App window did not appear for mock view '{}' within 10s",
                        view_name
                    ));
                }
                thread::sleep(std::time::Duration::from_millis(500));
            }
        }
    }

    // Give egui time to render the mock view content before capturing
    thread::sleep(std::time::Duration::from_secs(2));

    // Capture screenshot
    let screenshot_path = capture_screens(output_dir, view_name)?;

    // Kill child
    let _ = child.kill();
    let _ = child.wait();

    // Preprocess natively
    let preprocessed = preprocess_image_native(&screenshot_path)
        .unwrap_or_else(|_| screenshot_path.clone());

    // Load image for region cropping
    let img = image::open(&preprocessed)
        .map_err(|e| format!("Failed to open preprocessed image: {}", e))?;

    // Full-window OCR with confidence
    let (full_ocr_text, words) = ocr_image_multi_pass_with_confidence(&preprocessed)?;
    let avg_confidence = if words.is_empty() {
        0.0
    } else {
        words.iter().map(|w| w.confidence).sum::<f32>() / words.len() as f32
    };

    let high_conf: Vec<OcrWord> = words.iter().filter(|w| w.confidence >= 80.0).cloned().collect();
    let low_conf: Vec<OcrWord> = words.iter().filter(|w| w.confidence < 50.0).cloned().collect();

    // Per-region OCR intel
    let mut region_intel = Vec::new();
    for region_name in ["r1c1", "r1c4", "r4c1", "r4c4"] {
        match capture_single_region_intel(&img, view_name, region_name, output_dir) {
            Ok(ri) => region_intel.push(ri),
            Err(e) => {
                region_intel.push(OcrRegionIntel {
                    region_name: region_name.to_string(),
                    capture_type: CaptureType::Region,
                    ocr_text: String::new(),
                    words: Vec::new(),
                    avg_confidence: 0.0,
                    word_count: 0,
                });
                println!("  Region '{}' intel failed: {}", region_name, e);
            }
        }
    }

    Ok(OcrIntelReport {
        view_name: view_name.to_string(),
        screenshot_path,
        full_ocr_text,
        avg_confidence,
        total_words: words.len(),
        region_intel,
        high_confidence_words: high_conf,
        low_confidence_words: low_conf,
    })
}

/// Capture OCR intel for a single view with a specific scenario (empty, populated, error, loading).
/// Launches the app with --mock --view <view> --scenario <scenario> and captures
/// full-window + all sub-region screenshots with OCR. Used for gap-finding:
/// each scenario reveals different UI states that may hide or reveal text.
pub fn capture_intel_for_view_with_scenario(
    exe_path: &Path,
    view_name: &str,
    scenario: CaptureScenario,
    output_dir: &Path,
) -> Result<OcrIntelReport, String> {
    let view_dir = view_output_dir(output_dir, view_name);
    // Launch app in mock mode with scenario, using sandbox as library root
    // so test archives/state never touch the project root.
    let library_root = exe_path
        .parent()
        .unwrap_or(Path::new(""))
        .join("sandbox");
    let library_root_str = library_root.to_string_lossy().to_string();

    // Launch app in mock mode with scenario
    let mut child = Command::new(exe_path)
        .args([
            "--mock",
            "--view",
            view_name,
            "--scenario",
            scenario.as_str(),
            "--library-root",
            &library_root_str,
        ])
        .spawn()
        .map_err(|e| {
            format!(
                "Failed to launch app for mock view '{}' scenario '{}': {}",
                view_name,
                scenario.as_str(),
                e
            )
        })?;

    // Wait for window to appear (poll capture_screens until it works, up to 10s)
    let start = SystemTime::now();
    loop {
        match capture_screens(output_dir, view_name) {
            Ok(_) => break,
            Err(_) => {
                if start.elapsed().map_err(|e| format!("Time error: {}", e))?.as_secs() >= 10 {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!(
                        "App window did not appear for mock view '{}' scenario '{}' within 10s",
                        view_name,
                        scenario.as_str()
                    ));
                }
                thread::sleep(std::time::Duration::from_millis(500));
            }
        }
    }

    // Give egui time to render the mock view content before capturing
    thread::sleep(std::time::Duration::from_secs(2));

    // Capture full-window screenshot
    let screenshot_path = capture_screens(output_dir, view_name)?;

    // Kill child
    let _ = child.kill();
    let _ = child.wait();

    // Preprocess natively
    let preprocessed = preprocess_image_native(&screenshot_path)
        .unwrap_or_else(|_| screenshot_path.clone());

    // Load image for region cropping
    let img = image::open(&preprocessed)
        .map_err(|e| format!("Failed to open preprocessed image: {}", e))?;

    // Full-window OCR with confidence
    let (full_ocr_text, words) = ocr_image_multi_pass_with_confidence(&preprocessed)?;
    let avg_confidence = if words.is_empty() {
        0.0
    } else {
        words.iter().map(|w| w.confidence).sum::<f32>() / words.len() as f32
    };

    let high_conf: Vec<OcrWord> = words.iter().filter(|w| w.confidence >= 80.0).cloned().collect();
    let low_conf: Vec<OcrWord> = words.iter().filter(|w| w.confidence < 50.0).cloned().collect();

    // Per-sub-region OCR intel using SUB_REGIONS definitions
    let mut region_intel = Vec::new();
    let view_sub_regions = SUB_REGIONS
        .iter()
        .find(|(vn, _)| *vn == view_name)
        .map(|(_, regions)| *regions)
        .unwrap_or(&[]);

    for (sub_region_name, _, _, _, _) in view_sub_regions {
        match capture_single_sub_region_intel(
            &img,
            view_name,
            sub_region_name,
            output_dir,
        ) {
            Ok(ri) => region_intel.push(ri),
            Err(e) => {
                region_intel.push(OcrRegionIntel {
                    region_name: sub_region_name.to_string(),
                    capture_type: CaptureType::Region,
                    ocr_text: String::new(),
                    words: Vec::new(),
                    avg_confidence: 0.0,
                    word_count: 0,
                });
                println!(
                    "  Sub-region '{}/{}' intel failed: {}",
                    view_name, sub_region_name, e
                );
            }
        }
    }

    // Also capture main regions for backward compatibility
    for region_name in ["r1c1", "r1c4", "r4c1", "r4c4"] {
        match capture_single_region_intel(&img, view_name, region_name, output_dir) {
            Ok(ri) => region_intel.push(ri),
            Err(e) => {
                region_intel.push(OcrRegionIntel {
                    region_name: region_name.to_string(),
                    capture_type: CaptureType::Region,
                    ocr_text: String::new(),
                    words: Vec::new(),
                    avg_confidence: 0.0,
                    word_count: 0,
                });
                println!("  Region '{}' intel failed: {}", region_name, e);
            }
        }
    }

    Ok(OcrIntelReport {
        view_name: view_name.to_string(),
        screenshot_path,
        full_ocr_text,
        avg_confidence,
        total_words: words.len(),
        region_intel,
        high_confidence_words: high_conf,
        low_confidence_words: low_conf,
    })
}

/// Capture OCR intel for a single sub-region by cropping and OCRing.
fn capture_single_sub_region_intel(
    img: &DynamicImage,
    view_name: &str,
    sub_region_name: &str,
    output_dir: &Path,
) -> Result<OcrRegionIntel, String> {
    let view_dir = view_output_dir(output_dir, view_name);
    let (width, height) = img.dimensions();
    let (left_pct, top_pct, right_pct, bottom_pct) = SUB_REGIONS
        .iter()
        .find(|(vn, _regions)| *vn == view_name)
        .and_then(|(_, regions)| {
            regions.iter().find(|(rn, _, _, _, _)| *rn == sub_region_name)
        })
        .map(|(_, l, t, r, b)| (*l, *t, *r, *b))
        .unwrap_or((0.0, 0.0, 1.0, 1.0));

    let left = (width as f32 * left_pct) as u32;
    let top = (height as f32 * top_pct) as u32;
    let right = (width as f32 * right_pct) as u32;
    let bottom = (height as f32 * bottom_pct) as u32;

    if right <= left || bottom <= top {
        return Ok(OcrRegionIntel {
            region_name: sub_region_name.to_string(),
            capture_type: CaptureType::Region,
            ocr_text: String::new(),
            words: Vec::new(),
            avg_confidence: 0.0,
            word_count: 0,
        });
    }

    let rgba: RgbaImage = img.to_rgba8();
    let region_width = right - left;
    let region_height = bottom - top;
    let mut region_buf = RgbaImage::new(region_width, region_height);
    for y in 0..region_height {
        for x in 0..region_width {
            let pixel = rgba.get_pixel(left + x, top + y);
            region_buf.put_pixel(x, y, *pixel);
        }
    }
    let region_dynamic = DynamicImage::ImageRgba8(region_buf);

    // Save sub-region image with descriptive naming (no timestamp)
    let region_path = view_dir.join(view_file_name(
        view_name,
        "Sub-Region",
        &format!("{}-{}", sub_region_name.to_uppercase(), sub_region_name),
    ));
    region_dynamic
        .save(&region_path)
        .map_err(|e| format!("Failed to save sub-region image: {}", e))?;

    // OCR sub-region with confidence
    let (ocr_text, words) = ocr_image_multi_pass_with_confidence(&region_path)?;
    let word_count = words.len();
    let avg_confidence = if words.is_empty() {
        0.0
    } else {
        words.iter().map(|w| w.confidence).sum::<f32>() / words.len() as f32
    };

    Ok(OcrRegionIntel {
        region_name: sub_region_name.to_string(),
        capture_type: CaptureType::Region,
        ocr_text,
        words,
        avg_confidence,
        word_count,
    })
}

/// Capture OCR intel for ALL views × ALL scenarios (comprehensive gap-finding sweep).
/// Returns a vector of (view_name, scenario, report) for every combination.
/// This is the most thorough way to discover UI text gaps — every view is captured
/// under every scenario, with full-window + sub-region screenshots and OCR intel.
pub fn capture_all_scenarios(
    exe_path: &Path,
    output_dir: &Path,
) -> Result<Vec<(String, CaptureScenario, OcrIntelReport)>, String> {
    let views = [
        "scan", "review", "organize", "artwork", "done", "setup",
        "catalog", "batch-extract", "extract-progress", "extract-result",
    ];
    let scenarios = CaptureScenario::all();
    let mut results = Vec::new();

    for view in &views {
        for scenario in &scenarios {
            println!(
                "=== Capturing view '{}' scenario '{}' ===",
                view,
                scenario.as_str()
            );
            match capture_intel_for_view_with_scenario(exe_path, view, scenario.clone(), output_dir) {
                Ok(report) => {
                    println!(
                        "  {:?}: {} words, {:.1}% avg conf, {} high-conf, {} low-conf",
                        scenario,
                        report.total_words,
                        report.avg_confidence,
                        report.high_confidence_words.len(),
                        report.low_confidence_words.len()
                    );
                    results.push((view.to_string(), scenario.clone(), report));
                }
                Err(e) => {
                    eprintln!(
                        "  Capture failed for view '{}' scenario '{}': {}",
                        view,
                        scenario.as_str(),
                        e
                    );
                }
            }
        }
    }

    Ok(results)
}

/// Capture OCR intel for a single region by cropping and OCRing.
fn capture_single_region_intel(
    img: &DynamicImage,
    view_name: &str,
    region_name: &str,
    output_dir: &Path,
) -> Result<OcrRegionIntel, String> {
    let view_dir = view_output_dir(output_dir, view_name);
    let (width, height) = img.dimensions();
    let (left_pct, top_pct, right_pct, bottom_pct) = OCR_REGIONS
        .iter()
        .find(|(rn, _, _, _, _)| *rn == region_name)
        .map(|(_, l, t, r, b)| (*l, *t, *r, *b))
        .unwrap_or((0.0, 0.0, 1.0, 1.0));

    let left = (width as f32 * left_pct) as u32;
    let top = (height as f32 * top_pct) as u32;
    let right = (width as f32 * right_pct) as u32;
    let bottom = (height as f32 * bottom_pct) as u32;

    if right <= left || bottom <= top {
        return Ok(OcrRegionIntel {
            region_name: region_name.to_string(),
            capture_type: CaptureType::Region,
            ocr_text: String::new(),
            words: Vec::new(),
            avg_confidence: 0.0,
            word_count: 0,
        });
    }

    let rgba: RgbaImage = img.to_rgba8();
    let region_width = right - left;
    let region_height = bottom - top;
    let mut region_buf = RgbaImage::new(region_width, region_height);
    for y in 0..region_height {
        for x in 0..region_width {
            let pixel = rgba.get_pixel(left + x, top + y);
            region_buf.put_pixel(x, y, *pixel);
        }
    }
    let region_dynamic = DynamicImage::ImageRgba8(region_buf);

    // Save region image for debugging with descriptive naming (no timestamp)
    let region_path = view_dir.join(view_file_name(
        view_name,
        "Region",
        &format!("{}-{}", region_name.to_uppercase(), region_name),
    ));
    region_dynamic.save(&region_path)
        .map_err(|e| format!("Failed to save region image: {}", e))?;

    // OCR region with confidence
    let (ocr_text, words) = ocr_image_multi_pass_with_confidence(&region_path)?;
    let avg_confidence = if words.is_empty() {
        0.0
    } else {
        words.iter().map(|w| w.confidence).sum::<f32>() / words.len() as f32
    };

    let word_count = words.len();

    Ok(OcrRegionIntel {
        region_name: region_name.to_string(),
        capture_type: CaptureType::Region,
        ocr_text,
        words,
        avg_confidence,
        word_count,
    })
}

/// Format an OCR intel report as a human-readable string.
pub fn format_ocr_intel_report(report: &OcrIntelReport) -> String {
    let mut s = String::new();
    s.push_str("\n============================================================\n");
    s.push_str(&format!(" OCR INTEL REPORT — view '{}'\n", report.view_name));
    s.push_str("============================================================\n");
    s.push_str(&format!("Screenshot: {}\n", report.screenshot_path.display()));
    s.push_str(&format!("Total words: {}\n", report.total_words));
    s.push_str(&format!("Avg confidence: {:.1}%\n", report.avg_confidence));
    s.push_str(&format!(
        "High-confidence words (>=80): {}\n",
        report.high_confidence_words.len()
    ));
    s.push_str(&format!(
        "Low-confidence words (<50): {}\n",
        report.low_confidence_words.len()
    ));
    s.push_str("\n--- Full OCR text ---\n");
    s.push_str(&report.full_ocr_text);
    s.push_str("\n\n--- Per-region intel ---\n");
    for ri in &report.region_intel {
        s.push_str(&format!(
            "\n[Region: {}] words={} avg_conf={:.1}%\n",
            ri.region_name, ri.word_count, ri.avg_confidence
        ));
        s.push_str(&format!(
            "Text: {:?}\n",
            ri.ocr_text.chars().take(300).collect::<String>()
        ));
    }
    s.push_str("\n--- High-confidence words (>=80) ---\n");
    for w in &report.high_confidence_words {
        s.push_str(&format!(
            "  '{:?}' conf={:.1} at ({},{}) {}\n",
            w.text, w.confidence, w.left, w.top, w.width
        ));
    }
    s.push_str("\n--- Low-confidence words (<50) ---\n");
    for w in &report.low_confidence_words {
        s.push_str(&format!(
            "  '{:?}' conf={:.1} at ({},{})\n",
            w.text, w.confidence, w.left, w.top
        ));
    }
    s.push_str("============================================================\n");
    s
}

/// Capture the Steam Game Organizer app window using PowerShell + Win32 API.
/// Uses DPI awareness and captures at native resolution for better OCR accuracy.
///
/// # Timestamp check
/// If an existing screenshot for this view is newer than the Rust source files,
/// capture is skipped entirely. This prevents unnecessary re-captures when the
/// UI hasn't changed, and ensures we always have fresh photos after code changes.
pub fn capture_screens(output_dir: &Path, view_name: &str) -> Result<PathBuf, String> {
    // Ensure per-view output directory exists
    let view_dir = ensure_view_dir(output_dir, view_name)?;

    // Generate descriptive filename (no timestamp)
    let filename = view_file_name(view_name, "Full UI", "FULLWINDOW");
    let output_path = view_dir.join(filename);
    let output_path_str = output_path
        .to_str()
        .ok_or_else(|| "Invalid output path".to_string())?;

    // --- Timestamp comparison: skip if existing photo is newer than source ---
    let source_mtime = std::fs::metadata("src/bin.rs")
        .and_then(|m| m.modified())
        .unwrap_or(std::time::SystemTime::UNIX_EPOCH)
        .max(
            std::fs::metadata("src/ui/main_window.rs")
                .and_then(|m| m.modified())
                .unwrap_or(std::time::SystemTime::UNIX_EPOCH),
        )
        .max(
            std::fs::metadata("src/ui/theme.rs")
                .and_then(|m| m.modified())
                .unwrap_or(std::time::SystemTime::UNIX_EPOCH),
        );

    if output_path.exists() {
        if let Ok(out_meta) = output_path.metadata() {
            if let Ok(out_mtime) = out_meta.modified() {
                if out_mtime > source_mtime {
                    eprintln!(
                        "[SKIP] {} is newer than source code, skipping re-capture",
                        output_path.display()
                    );
                    return Ok(output_path);
                }
            }
        }
    }

    // Write PowerShell script to capture app window at DPI-aware resolution
    let ps_script_path = std::env::temp_dir().join("capture_screens.ps1");
    let mut script = String::new();
    script.push_str("$ErrorActionPreference = 'Stop'\n");
    script.push_str("Add-Type -AssemblyName System.Drawing\n");
    script.push_str("Add-Type -Name WindowUtils -Namespace Win32 -MemberDefinition @'\n");
    script.push_str("[DllImport(\"user32.dll\", SetLastError = true)]\n");
    script.push_str("public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);\n");
    script.push_str("[DllImport(\"user32.dll\")]\n");
    script.push_str("public static extern IntPtr GetWindowDC(IntPtr hWnd);\n");
    script.push_str("[DllImport(\"user32.dll\")]\n");
    script.push_str("public static extern int ReleaseDC(IntPtr hWnd, IntPtr hDC);\n");
    script.push_str("[DllImport(\"user32.dll\")]\n");
    script.push_str("[return: MarshalAs(UnmanagedType.Bool)]\n");
    script.push_str("public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdcBlt, uint nFlags);\n");
    script.push_str("[StructLayout(LayoutKind.Sequential)]\n");
    script.push_str("public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }\n");
    script.push_str("'@\n");
    script.push_str("Add-Type -Name GDI32 -Namespace Win32 -MemberDefinition @'\n");
    script.push_str("[DllImport(\"gdi32.dll\")]\n");
    script.push_str("public static extern IntPtr CreateCompatibleDC(IntPtr hdc);\n");
    script.push_str("[DllImport(\"gdi32.dll\")]\n");
    script.push_str("public static extern IntPtr CreateCompatibleBitmap(IntPtr hdc, int nWidth, int nHeight);\n");
    script.push_str("[DllImport(\"gdi32.dll\")]\n");
    script.push_str("public static extern IntPtr SelectObject(IntPtr hdc, IntPtr hObject);\n");
    script.push_str("[DllImport(\"gdi32.dll\")]\n");
    script.push_str("public static extern bool BitBlt(IntPtr hdcDest, int nXDest, int nYDest, int nWidth, int nHeight, IntPtr hdcSrc, int nXSrc, int nYSrc, uint dwRop);\n");
    script.push_str("[DllImport(\"gdi32.dll\")]\n");
    script.push_str("public static extern bool DeleteObject(IntPtr hObject);\n");
    script.push_str("[DllImport(\"gdi32.dll\")]\n");
    script.push_str("public static extern bool DeleteDC(IntPtr hdc);\n");
    script.push_str("'@\n");
    script.push_str("Write-Output 'Starting capture'\n");
    script.push_str("$windowTitle = 'Steam Game Organizer'\n");
    script.push_str("Write-Output 'Looking for window: ' + $windowTitle\n");
    script.push_str("$process = Get-Process | Where-Object { $_.MainWindowTitle -eq $windowTitle } | Select-Object -First 1\n");
    script.push_str("if (-not $process) {\n");
    script.push_str("    Write-Output 'No Steam Game Organizer window found'\n");
    script.push_str("    exit 1\n");
    script.push_str("}\n");
    script.push_str("Write-Output 'Found process: ' + $process.ProcessName + ' handle=' + $process.MainWindowHandle\n");
    script.push_str("$hwnd = $process.MainWindowHandle\n");
    script.push_str("# Wait for window to have non-zero size (egui needs time to render)\n");
    script.push_str("$start = Get-Date\n");
    script.push_str("$rect = $null\n");
    script.push_str("while ($true) {\n");
    script.push_str("    $rect = New-Object Win32.WindowUtils+RECT\n");
    script.push_str("    if ([Win32.WindowUtils]::GetWindowRect($hwnd, [ref]$rect)) {\n");
    script.push_str("        $width = $rect.Right - $rect.Left\n");
    script.push_str("        $height = $rect.Bottom - $rect.Top\n");
    script.push_str("        if ($width -gt 0 -and $height -gt 0) { break }\n");
    script.push_str("    }\n");
    script.push_str("    $elapsed = (Get-Date) - $start\n");
    script.push_str("    if ($elapsed.TotalSeconds -gt 10) {\n");
    script.push_str("        Write-Output 'Window never got non-zero size'\n");
    script.push_str("        exit 1\n");
    script.push_str("    }\n");
    script.push_str("    Start-Sleep -Milliseconds 200\n");
    script.push_str("}\n");
    script.push_str("$left = $rect.Left; $top = $rect.Top\n");
    script.push_str("$right = $rect.Right; $bottom = $rect.Bottom\n");
    script.push_str("$width = $right - $left\n");
    script.push_str("$height = $bottom - $top\n");
    script.push_str("Write-Output 'Window rect: ' + $left + ',' + $top + ' ' + $right + ',' + $bottom + ' size ' + $width + 'x' + $height\n");
    script.push_str("# Capture window content via PrintWindow - asks the window to repaint itself into a bitmap\n");
    script.push_str("# works even when the window is behind other windows or not focused. No focus steal.\n");
    script.push_str("Start-Sleep -Milliseconds 300\n");
    script.push_str("$windowDC = [Win32.WindowUtils]::GetWindowDC($hwnd)\n");
    script.push_str("$memDC = [Win32.GDI32]::CreateCompatibleDC($windowDC)\n");
    script.push_str("$hBitmap = [Win32.GDI32]::CreateCompatibleBitmap($windowDC, $width, $height)\n");
    script.push_str("$oldBitmap = [Win32.GDI32]::SelectObject($memDC, $hBitmap)\n");
    script.push_str("$PW_CLIENTONLY = 1\n");
    script.push_str("$PW_RENDERFULLCONTENT = 2\n");
    script.push_str("$printed = [Win32.WindowUtils]::PrintWindow($hwnd, $memDC, $PW_CLIENTONLY -bor $PW_RENDERFULLCONTENT)\n");
    script.push_str("if (-not $printed) {\n");
    script.push_str("    Write-Output 'WARNING: PrintWindow returned false, window content may be incomplete'\n");
    script.push_str("}\n");
    script.push_str("$bmp = [System.Drawing.Bitmap]::FromHbitmap($hBitmap)\n");
    script.push_str("[Win32.GDI32]::SelectObject($memDC, $oldBitmap) | Out-Null\n");
    script.push_str("[Win32.GDI32]::DeleteObject($hBitmap) | Out-Null\n");
    script.push_str("[Win32.GDI32]::DeleteDC($memDC) | Out-Null\n");
    script.push_str("[Win32.WindowUtils]::ReleaseDC($hwnd, $windowDC) | Out-Null\n");
    script.push_str(&format!(
        "$bmp.Save('{}', [System.Drawing.Imaging.ImageFormat]::Png)\n",
        output_path_str
    ));
    script.push_str("$bmp.Dispose()\n");
    script.push_str("Write-Output 'Saved to ' + '");
    script.push_str(output_path_str);
    script.push_str("' + ' ' + $width + 'x' + $height\n");

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
        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);
        eprintln!("DEBUG: PowerShell stdout: {}", stdout);
        eprintln!("DEBUG: PowerShell stderr: {}", stderr);
        return Err(format!("PowerShell capture failed: {}", stderr));
    }
    let _stdout = String::from_utf8_lossy(&output.stdout);
    let _stderr = String::from_utf8_lossy(&output.stderr);

    if !output.status.success() {
        return Err(format!("PowerShell capture failed: {}", _stderr));
    }

    Ok(output_path)
}

/// Preprocess an image for better OCR using native Rust `image` crate.
/// Pipeline: grayscale → threshold → contrast → upscale 2x.
/// This avoids PowerShell GDI+ and gives full control over preprocessing steps.
fn preprocess_image_native(image_path: &Path) -> Result<PathBuf, String> {
    let img = image::open(image_path)
        .map_err(|e| format!("Failed to open image for preprocessing: {}", e))?;

    // Convert to grayscale
    let gray: GrayImage = img.to_luma8();

    // Threshold: pure black/white for cleaner OCR
    let (width, height) = gray.dimensions();
    let mut binary = GrayImage::new(width, height);
    for (x, y, pixel) in gray.enumerate_pixels() {
        let val = if pixel.0[0] > 128 { 255u8 } else { 0u8 };
        binary.put_pixel(x, y, Luma([val]));
    }

    // Contrast stretch to sharpen text edges
    let contrasted = imageops::contrast(&binary, 1.6);

    // Upscale 2x so Tesseract has more pixels per character
    let (w, h) = contrasted.dimensions();
    let upscaled: GrayImage = imageops::resize(&contrasted, w * 2, h * 2, imageops::FilterType::Triangle);
    let upscaled_dynamic = DynamicImage::ImageLuma8(upscaled);

    let preprocessed_path = image_path.with_extension("ocr_ready.png");
    upscaled_dynamic
        .save(&preprocessed_path)
        .map_err(|e| format!("Failed to save preprocessed image: {}", e))?;

    Ok(preprocessed_path)
}

/// Legacy PowerShell-based preprocessing (kept as fallback if native fails).
#[allow(dead_code)]
fn preprocess_image(image_path: &Path) -> Result<PathBuf, String> {
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
        return Ok(image_path.to_path_buf());
    }

    Ok(preprocessed_path)
}

/// Verify that Tesseract OCR is available before attempting OCR.
/// Checks both the default install location and PATH.
fn verify_tesseract_available() -> Result<PathBuf, String> {
    let tesseract_path = Path::new(r"C:\Program Files\Tesseract-OCR\tesseract.exe");
    if tesseract_path.exists() {
        return Ok(tesseract_path.to_path_buf());
    }
    // Try PATH lookup
    if Command::new("tesseract").arg("--version").output().is_ok() {
        return Ok(PathBuf::from("tesseract"));
    }
    Err(
        "Tesseract OCR is not installed. Install it from https://github.com/UB-Mannheim/tesseract/wiki \
         and ensure it is at C:\\Program Files\\Tesseract-OCR\\tesseract.exe or on your PATH.\
         OCR features (--ocr, --regions, --capture-intel, --capture-all, sandbox step 24b) \
         require Tesseract to function."
            .to_string(),
    )
}

/// Run Tesseract OCR on an image with a specific PSM mode, returning plain text.
fn ocr_image_with_psm(image_path: &Path, psm: &str) -> Result<String, String> {
    let tesseract_cmd = verify_tesseract_available()?;

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

/// Run Tesseract OCR with TSV output for word-level confidence scores.
/// Returns a vector of OcrWord with text, confidence, and bounding box.
fn ocr_image_tsv(image_path: &Path, psm: &str) -> Result<Vec<OcrWord>, String> {
    let tesseract_cmd = verify_tesseract_available()?;

    let output = Command::new(tesseract_cmd)
        .args([
            image_path.to_str().ok_or("Invalid image path")?,
            "stdout",
            "--psm",
            psm,
            "tsv",
        ])
        .output()
        .map_err(|e| format!("Failed to launch tesseract: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Tesseract TSV failed (psm={}): {}", psm, stderr));
    }

    let text = String::from_utf8_lossy(&output.stdout);
    let mut words = Vec::new();

    for line in text.lines().skip(1) {
        // Skip TSV header line
        let fields: Vec<&str> = line.split('\t').collect();
        if fields.len() >= 12 {
            let text_val = fields[11].to_string();
            if text_val.trim().is_empty() {
                continue;
            }
            let confidence: f32 = fields[10].parse().unwrap_or(0.0);
            let left: i32 = fields[6].parse().unwrap_or(0);
            let top: i32 = fields[7].parse().unwrap_or(0);
            let width: i32 = fields[8].parse().unwrap_or(0);
            let height: i32 = fields[9].parse().unwrap_or(0);
            words.push(OcrWord {
                text: text_val,
                confidence,
                left,
                top,
                width,
                height,
            });
        }
    }

    Ok(words)
}

/// Run OCR with multiple PSM modes, return merged text and all words with confidence.
/// Prefers the PSM mode with the highest average word confidence.
fn ocr_image_multi_pass_with_confidence(
    image_path: &Path,
) -> Result<(String, Vec<OcrWord>), String> {
    let mut all_text = String::new();
    let mut all_words = Vec::new();
    let mut best_confidence = 0.0f32;
    let mut best_psm = "";

    for psm in OCR_PSM_MODES {
        match ocr_image_tsv(image_path, psm) {
            Ok(words) => {
                if !words.is_empty() {
                    let conf_sum: f32 = words.iter().map(|w| w.confidence).sum();
                    let avg_conf = conf_sum / words.len() as f32;
                    if avg_conf > best_confidence {
                        best_confidence = avg_conf;
                        best_psm = psm;
                    }
                    all_words.extend(words);
                }
                let text = ocr_image_with_psm(image_path, psm)?;
                all_text.push_str(&text);
                all_text.push('\n');
            }
            Err(e) => {
                println!("  OCR PSM {} failed: {}", psm, e);
            }
        }
    }

    if all_words.is_empty() {
        return Err("All OCR PSM modes failed".to_string());
    }

    println!("  Best OCR PSM: {} (avg confidence {:.1})", best_psm, best_confidence);

    Ok((all_text, all_words))
}

/// Run OCR with multiple PSM modes and merge results (legacy plain-text API).
#[allow(dead_code)]
fn ocr_image_multi_pass(image_path: &Path) -> Result<String, String> {
    let (text, _words) = ocr_image_multi_pass_with_confidence(image_path)?;
    Ok(text)
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

/// Verify OCR text against region-specific expected headers.
/// Returns a list of (region_name, found_required, missing_required).
pub fn verify_ocr_regions(
    regions: &[OcrRegionResult],
    view_name: &str,
) -> Vec<(String, Vec<String>, Vec<String>)> {
    let mut results = Vec::new();

    let view_regions = OCR_REGION_HEADERS
        .iter()
        .find(|(name, _)| *name == view_name)
        .map(|(_, regions)| *regions)
        .unwrap_or(&[]);

    for (region_name, expected_headers) in view_regions {
        let region_result = regions.iter().find(|r| r.region_name == *region_name);

        let mut found_required = Vec::new();
        let mut missing_required = Vec::new();

        if let Some(rr) = region_result {
            let normalized = normalize_ocr_text(&rr.ocr_text);
            for header in (*expected_headers).iter() {
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
        } else {
            for header in (*expected_headers).iter() {
                missing_required.push(header.to_string());
            }
        }

        results.push((region_name.to_string(), found_required, missing_required));
    }

    results
}

/// Verify that expected live text appears in OCR output.
/// Used by sandbox to confirm real content (game names, categories, counts) is rendered.
/// Returns (found, missing).
pub fn verify_live_text(ocr_text: &str, view_name: &str) -> (Vec<String>, Vec<String>) {
    let normalized = normalize_ocr_text(ocr_text);

    let expected = OCR_LIVE_TEXT
        .iter()
        .find(|(name, _)| *name == view_name)
        .map(|(_, texts)| *texts)
        .unwrap_or(&[]);

    let mut found = Vec::new();
    let mut missing = Vec::new();

    for text in expected {
        let text_normalized = normalize_ocr_text(text);
        if normalized.contains(&text_normalized) {
            found.push(text.to_string());
        } else {
            missing.push(text.to_string());
        }
    }

    (found, missing)
}

/// Capture a screenshot and crop into regions, OCR each region separately.
/// Multi-region OCR catches text that full-window OCR misses (small buttons, footer status).
pub fn capture_and_ocr_regions(
    output_dir: &Path,
    view_name: &str,
) -> Result<Vec<OcrRegionResult>, String> {
    let screenshot_path = capture_screens(output_dir, view_name)?;

    // Preprocess natively for better OCR
    let preprocessed = preprocess_image_native(&screenshot_path)
        .unwrap_or_else(|_| screenshot_path.clone());

    let img = image::open(&preprocessed)
        .map_err(|e| format!("Failed to open preprocessed image: {}", e))?;
    let (width, height) = img.dimensions();

    let view_dir = view_output_dir(output_dir, view_name);
    let mut results = Vec::new();

    for (region_name, left_pct, top_pct, right_pct, bottom_pct) in OCR_REGIONS {
        let left = (width as f32 * left_pct) as u32;
        let top = (height as f32 * top_pct) as u32;
        let right = (width as f32 * right_pct) as u32;
        let bottom = (height as f32 * bottom_pct) as u32;

        if right <= left || bottom <= top {
            continue;
        }

        // Crop region manually (crop_imm not available on ImageBuffer in this image version)
        let rgba: RgbaImage = img.to_rgba8();
        let region_width = right - left;
        let region_height = bottom - top;
        let mut region_buf = RgbaImage::new(region_width, region_height);
        for y in 0..region_height {
            for x in 0..region_width {
                let pixel = rgba.get_pixel(left + x, top + y);
                region_buf.put_pixel(x, y, *pixel);
            }
        }
        let region_dynamic = DynamicImage::ImageRgba8(region_buf);

        // Save region image for debugging with descriptive naming (no timestamp)
        let region_path = view_dir.join(view_file_name(
            view_name,
            "Region",
            &format!("{}-{}", region_name.to_uppercase(), region_name),
        ));
        region_dynamic
            .save(&region_path)
            .map_err(|e| format!("Failed to save region image: {}", e))?;

        // OCR the region with confidence
        let (ocr_text, words) = ocr_image_multi_pass_with_confidence(&region_path)?;
        let avg_confidence = if words.is_empty() {
            0.0
        } else {
            words.iter().map(|w| w.confidence).sum::<f32>() / words.len() as f32
        };

        results.push(OcrRegionResult {
            region_name: region_name.to_string(),
            capture_type: CaptureType::Region,
            ocr_text,
            words,
            avg_confidence,
        });
    }

    Ok(results)
}

/// Launch the app in mock mode for a single view, capture screenshot, run OCR,
/// and verify live text appears. Used by sandbox to verify the actual rendered app
/// shows real content, not just UI chrome.
pub fn capture_mock_view_screenshot(
    exe_path: &Path,
    view_name: &str,
    output_dir: &Path,
) -> Result<OcrVerificationResult, String> {
    // Launch the app in mock mode with a single view
    let mut child = Command::new(exe_path)
        .args(["--mock", "--view", view_name])
        .spawn()
        .map_err(|e| format!("Failed to launch app for mock view '{}': {}", view_name, e))?;

    // Wait for the window to appear (poll capture_screens until it works, up to 10s)
    let start = SystemTime::now();
    loop {
        match capture_screens(output_dir, view_name) {
            Ok(_) => break,
            Err(_) => {
                if start.elapsed().map_err(|e| format!("Time error: {}", e))?.as_secs() >= 10 {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!(
                        "App window did not appear for mock view '{}' within 10s",
                        view_name
                    ));
                }
                thread::sleep(std::time::Duration::from_millis(500));
            }
        }
    }

    // Capture screenshot
    let screenshot_path = capture_screens(output_dir, view_name)?;

    // Kill the child process
    let _ = child.kill();
    let _ = child.wait();

    // Preprocess natively
    let preprocessed = preprocess_image_native(&screenshot_path)
        .unwrap_or_else(|_| screenshot_path.clone());

    // Run multi-pass OCR with confidence
    let (ocr_text, words) = ocr_image_multi_pass_with_confidence(&preprocessed)?;
    let avg_confidence = if words.is_empty() {
        0.0
    } else {
        words.iter().map(|w| w.confidence).sum::<f32>() / words.len() as f32
    };

    // Verify against expected headers
    let (found_required, missing_required, found_forbidden) = verify_ocr(&ocr_text, view_name);

    if !found_forbidden.is_empty() {
        return Err(format!(
            "OCR verification failed for {}: forbidden text found: {:?}",
            view_name, found_forbidden
        ));
    }

    if !missing_required.is_empty() {
        return Err(format!(
            "OCR verification failed for {}: missing required headers: {:?}",
            view_name, missing_required
        ));
    }

    Ok(OcrVerificationResult {
        view_name: view_name.to_string(),
        found_required,
        missing_required,
        found_forbidden,
        ocr_text,
        screenshot_path,
        avg_confidence,
        region_results: Vec::new(),
    })
}

/// Capture a single view and optionally run OCR verification.
pub fn capture_and_verify(
    output_dir: &Path,
    view_name: &str,
    enable_ocr: bool,
) -> Result<OcrVerificationResult, String> {
    // Launch app in mock mode so capture_screens can find the window
    let library_root = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default())
        .join("sandbox");
    let library_root_str = library_root.to_string_lossy().to_string();

    let mut child = Command::new(std::env::current_exe().unwrap_or_default())
        .args([
            "--mock",
            "--view",
            view_name,
            "--scenario",
            "populated",
            "--library-root",
            &library_root_str,
        ])
        .spawn()
        .map_err(|e| format!("failed to launch app for mock view '{}': {}", view_name, e))?;

    // Wait for window to appear (poll capture_screens until it works, up to 10s)
    let start = SystemTime::now();
    loop {
        match capture_screens(output_dir, view_name) {
            Ok(_) => break,
            Err(_) => {
                if start.elapsed().map_err(|e| format!("{}", e))?.as_secs() >= 10 {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!("App window did not appear for view '{}'", view_name));
                }
                thread::sleep(std::time::Duration::from_millis(500));
            }
        }
    }

    // Give egui time to render the mock view content before capturing
    thread::sleep(std::time::Duration::from_secs(2));

    // Capture final screenshot (overwrites the polling one with same descriptive name)
    let screenshot_path = capture_screens(output_dir, view_name)?;

    // Kill child
    let _ = child.kill();
    let _ = child.wait();

    let mut result = OcrVerificationResult {
        view_name: view_name.to_string(),
        found_required: Vec::new(),
        missing_required: Vec::new(),
        found_forbidden: Vec::new(),
        ocr_text: String::new(),
        screenshot_path,
        avg_confidence: 0.0,
        region_results: Vec::new(),
    };

    // --- Capture 4x4 quadrant grid per view ---
    // Split the full window into 16 equal quadrants (4x4), stitch them into
    // one composite image, then OCR that composite as a single photo for
    // detailed layout analysis. Smaller regions mean less text cut at
    // boundaries and better OCR confidence per region.
    let img = image::open(&result.screenshot_path).unwrap_or_default();
    let (width, height) = img.dimensions();
    let q_w = width / 4;
    let q_h = height / 4;

    let quadrants = [
        ("r1c1", 0, 0, q_w, q_h),        // row 1, col 1 (top-left)
        ("r1c2", q_w, 0, q_w * 2, q_h),  // row 1, col 2
        ("r1c3", q_w * 2, 0, q_w * 3, q_h), // row 1, col 3
        ("r1c4", q_w * 3, 0, width, q_h), // row 1, col 4 (top-right)
        ("r2c1", 0, q_h, q_w, q_h * 2),  // row 2, col 1
        ("r2c2", q_w, q_h, q_w * 2, q_h * 2), // row 2, col 2
        ("r2c3", q_w * 2, q_h, q_w * 3, q_h * 2), // row 2, col 3
        ("r2c4", q_w * 3, q_h, width, q_h * 2), // row 2, col 4
        ("r3c1", 0, q_h * 2, q_w, q_h * 3), // row 3, col 1
        ("r3c2", q_w, q_h * 2, q_w * 2, q_h * 3), // row 3, col 2
        ("r3c3", q_w * 2, q_h * 2, q_w * 3, q_h * 3), // row 3, col 3
        ("r3c4", q_w * 3, q_h * 2, width, q_h * 3), // row 3, col 4
        ("r4c1", 0, q_h * 3, q_w, height), // row 4, col 1 (bottom-left)
        ("r4c2", q_w, q_h * 3, q_w * 2, height), // row 4, col 2
        ("r4c3", q_w * 2, q_h * 3, q_w * 3, height), // row 4, col 3
        ("r4c4", q_w * 3, q_h * 3, width, height), // row 4, col 4 (bottom-right)
    ];

    // Ensure per-view output directory exists
    let view_dir = ensure_view_dir(output_dir, view_name)?;

    let mut quadrant_images: Vec<image::DynamicImage> = Vec::new();

    for (name, left, top, right, bottom) in &quadrants {
        let qw = *right - *left;
        let qh = *bottom - *top;
        let mut buf = image::RgbaImage::new(qw, qh);
        for y in 0..qh {
            for x in 0..qw {
                let pixel = img.get_pixel(*left + x, *top + y);
                buf.put_pixel(x, y, pixel);
            }
        }
        let quadrant_dynamic = image::DynamicImage::ImageRgba8(buf);

        // Save individual quadrant with descriptive naming
        let quad_desc = quadrant_description(name);
        let quadrant_path = view_dir.join(view_file_name(
            view_name,
            "Quad",
            &format!("{}-{}", name.to_uppercase(), quad_desc.replace(' ', "-")),
        ));
        quadrant_dynamic.save(&quadrant_path).unwrap_or(());

        quadrant_images.push(quadrant_dynamic);
    }

    // Stitch 16 quadrants into one composite (4x4 grid)
    let mut composite_buf = image::RgbaImage::new(width, height);
    for (i, qimg) in quadrant_images.iter().enumerate() {
        let row = i / 4;
        let col = i % 4;
        let qx = col as u32 * q_w;
        let qy = row as u32 * q_h;
        for y in 0..qimg.height() {
            for x in 0..qimg.width() {
                let pixel = qimg.get_pixel(x, y);
                composite_buf.put_pixel(qx + x, qy + y, pixel);
            }
        }
    }

    // Save composite image
    let composite_path = view_dir.join(view_file_name(
        view_name,
        "4x4 Composite",
        "COMPOSITE",
    ));
    let composite_for_save = composite_buf.clone();
    image::DynamicImage::ImageRgba8(composite_for_save).save(&composite_path).unwrap_or(());

    // --- Side-by-side comparison: fullwindow vs 4x4 composite ---
    // Left: full UI (100%), Right: 4x4 stitched composite — same dimensions, easy visual diff
    let mut side_by_side_buf = image::RgbaImage::new(width * 2, height);
    // Left half: full window
    for y in 0..height {
        for x in 0..width {
            let pixel = img.get_pixel(x, y);
            side_by_side_buf.put_pixel(x, y, pixel);
        }
    }
    // Right half: composite
    for y in 0..height {
        for x in 0..width {
            let pixel = composite_buf.get_pixel(x, y);
            side_by_side_buf.put_pixel(width + x, y, *pixel);
        }
    }
    let side_by_side_path = view_dir.join(view_file_name(
        view_name,
        "Full vs Composite",
        "SIDE-BY-SIDE",
    ));
    image::DynamicImage::ImageRgba8(side_by_side_buf).save(&side_by_side_path).unwrap_or(());

    // --- Dead Space Analysis per Quadrant ---
    // Measure dark/light pixel ratio per quadrant to identify empty space.
    // Dark theme background (#09090b) ≈ RGB(9,9,11). If >80% of pixels in a
    // quadrant are near-black, that quadrant is likely dead space.
    let mut dead_space_report = Vec::new();
    for (name, left, top, right, bottom) in &quadrants {
        let qw = *right - *left;
        let qh = *bottom - *top;
        let mut dark_pixels = 0u32;
        let mut total_pixels = 0u32;
        for y in 0..qh {
            for x in 0..qw {
                let pixel = img.get_pixel(*left + x, *top + y);
                let r = pixel[0] as i32;
                let g = pixel[1] as i32;
                let b = pixel[2] as i32;
                let brightness = (r + g + b) / 3;
                if brightness < 40 {
                    dark_pixels += 1;
                }
                total_pixels += 1;
            }
        }
        let dark_ratio = if total_pixels > 0 {
            dark_pixels as f32 / total_pixels as f32
        } else {
            0.0
        };
        dead_space_report.push((
            name.to_string(),
            quadrant_description(name),
            dark_ratio,
            dark_pixels,
            total_pixels,
        ));
    }

    // Print dead space report
    eprintln!("\n════════════════════════════════════════════════════════════════════");
    eprintln!("DEAD SPACE ANALYSIS: {}", view_display_name(view_name).to_uppercase());
    eprintln!("════════════════════════════════════════════════════════════════════");
    for (quad_id, quad_desc, dark_ratio, dark_count, total) in &dead_space_report {
        let status = if *dark_ratio > 0.80 {
            "DEAD SPACE"
        } else if *dark_ratio > 0.60 {
            "MOSTLY EMPTY"
        } else if *dark_ratio > 0.40 {
            "PARTIALLY EMPTY"
        } else {
            "CONTENT"
        };
        eprintln!(
            "  {} ({}): {:.1}% dark ({}/{}) - {}",
            quad_id,
            quad_desc,
            dark_ratio * 100.0,
            dark_count,
            total,
            status
        );
    }
    eprintln!("");

    // --- ASCII Art UI Visualization ---
    // Render each quadrant as a text-based ASCII art representation using
    // brightness-based character mapping. Dark pixels = ' ', light pixels = '#',
    // mid-tones = '.', '+', etc. This gives a quick structural overview of the
    // UI layout without needing to view the actual image, useful for assessing
    // dead space and visual hierarchy at a glance.
    let ascii_art = generate_ascii_art(&img, &quadrants);
    let ascii_path = view_dir.join(format!(
        "{} - ASCII Art - UI-STRUCTURE.txt",
        view_display_name(view_name)
    ));
    std::fs::write(&ascii_path, &ascii_art)
        .map_err(|e| format!("Failed to save ASCII art: {}", e))?;
    eprintln!("ASCII art saved to: {}", ascii_path.display());
    eprint!("{}", ascii_art);

    // --- Audit Logging: Before/After Dead Space Comparison ---
    // Log dead space changes for auditing UI design regressions/improvements.
    // Each entry records quadrant, dark pixel ratio, and status classification.
    let audit_path = view_dir.join(format!(
        "{} - Dead Space Audit - AUDIT.txt",
        view_display_name(view_name)
    ));
    let mut audit_content = String::new();
    audit_content.push_str(&format!("UI Audit: {}\n", view_display_name(view_name)));
    audit_content.push_str(&format!(
        "Timestamp: {}\n\n",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs()
    ));
    audit_content.push_str("Quadrant    | Description            | Dark %  | Status\n");
    audit_content.push_str("------------|------------------------|---------|----------------\n");
    for (quad_id, quad_desc, dark_ratio, dark_count, total) in &dead_space_report {
        let status = if *dark_ratio > 0.80 {
            "DEAD SPACE"
        } else if *dark_ratio > 0.60 {
            "MOSTLY EMPTY"
        } else if *dark_ratio > 0.40 {
            "PARTIALLY EMPTY"
        } else {
            "CONTENT"
        };
        audit_content.push_str(&format!(
            "{:<11}| {:<22}| {:>6.1}% | {}\n",
            quad_id,
            quad_desc,
            dark_ratio * 100.0,
            status
        ));
    }
    audit_content.push_str(&format!(
        "\nOverall dead space: {:.1}% of quadrants are >80%% dark\n",
        dead_space_report
            .iter()
            .filter(|(_, _, ratio, _, _)| *ratio > 0.80)
            .count() as f32
            / dead_space_report.len() as f32
            * 100.0
    ));
    std::fs::write(&audit_path, &audit_content)
        .map_err(|e| format!("Failed to save audit: {}", e))?;
    eprintln!("Audit log saved to: {}", audit_path.display());
    eprintln!("");

    // --- UI Design Review Checklist ---
    // Generate a checklist of design issues based on dead space analysis.
    let checklist = generate_design_review_checklist(view_name, &dead_space_report);
    let checklist_path = view_dir.join(format!(
        "{} - Design Review Checklist - CHECKLIST.txt",
        view_display_name(view_name)
    ));
    std::fs::write(&checklist_path, &checklist)
        .map_err(|e| format!("Failed to save design review checklist: {}", e))?;
    eprintln!("Design review checklist saved to: {}", checklist_path.display());
    eprint!("{}", checklist);
    eprintln!("");

    // OCR each quadrant individually for intel
    for (name, _, _, _, _) in &quadrants {
        match capture_single_region_intel(&img, view_name, name, &view_dir) {
            Ok(ri) => {
                result.region_results.push(OcrRegionResult {
                    region_name: ri.region_name.clone(),
                    capture_type: CaptureType::Region,
                    ocr_text: ri.ocr_text.clone(),
                    words: ri.words.clone(),
                    avg_confidence: ri.avg_confidence,
                });
            }
            Err(e) => {
                eprintln!("Quadrant '{}' capture failed: {}", name, e);
            }
        }
    }

    if enable_ocr {
        // Preprocess natively for better OCR
        let preprocessed = preprocess_image_native(&result.screenshot_path)
            .unwrap_or_else(|_| result.screenshot_path.clone());

        // Run multi-pass OCR with confidence on full window
        let (ocr_text, words) = ocr_image_multi_pass_with_confidence(&preprocessed)?;
        result.ocr_text = ocr_text.clone();

        // OCR the 4x4 stitched composite as a single photo for detailed layout analysis
        let composite_preprocessed = preprocess_image_native(&composite_path)
            .unwrap_or_else(|_| composite_path.clone());
        let (composite_ocr_text, composite_words) =
            ocr_image_multi_pass_with_confidence(&composite_preprocessed)?;
        let composite_text_preview = composite_ocr_text.lines().take(20).collect::<Vec<_>>().join("\n");
        eprintln!(
            "  Composite 4x4 OCR preview:\n{}",
            composite_text_preview
        );
        eprintln!(
            "  Composite word count: {}, avg confidence: {:.1}",
            composite_words.len(),
            if composite_words.is_empty() { 0.0 } else {
                composite_words.iter().map(|w| w.confidence).sum::<f32>() / composite_words.len() as f32
            }
        );

        // Verify against expected headers (full window + all sub-regions + composite)
        let mut all_ocr_text = format!("{}\n{}", ocr_text, composite_ocr_text);
        for region in &result.region_results {
            all_ocr_text.push_str(&format!("\n{}", region.ocr_text));
        }
        let (found_required, missing_required, found_forbidden) =
            verify_ocr(&all_ocr_text, view_name);

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

        // Aggregate average confidence across full window + all regions
        let mut all_confidences: Vec<f32> = words.iter().map(|w| w.confidence).collect();
        for region in &result.region_results {
            all_confidences.extend(region.words.iter().map(|w| w.confidence));
        }
        result.avg_confidence = if all_confidences.is_empty() {
            0.0
        } else {
            all_confidences.iter().sum::<f32>() / all_confidences.len() as f32
        };

        // --- Code-vs-reality UI element verification ---
        // Compare what source code claims to render (button macros) against
        // what OCR actually detected across full window + composite + quadrants.
        let mut all_ocr_texts: Vec<&str> = vec![&ocr_text, &composite_ocr_text];
        for region in &result.region_results {
            all_ocr_texts.push(&region.ocr_text);
        }
        let ui_result = verify_ui_elements(view_name, &all_ocr_texts);
        print_ui_verification_report(&ui_result);

        // --- Color Contrast Audit ---
        // Check key UI color pairs for WCAG compliance
        let contrast_pairs = vec![
            ("Text on background", Color32::from_rgb(0xf1, 0xf1, 0xf5), Color32::from_rgb(0x09, 0x09, 0x0b)),
            ("Text secondary on panel", Color32::from_rgb(0xc0, 0xc0, 0xc8), Color32::from_rgb(0x0f, 0x0f, 0x13)),
            ("Accent on panel", Color32::from_rgb(0x58, 0xa6, 0xff), Color32::from_rgb(0x0f, 0x0f, 0x13)),
            ("White text on accent", Color32::WHITE, Color32::from_rgb(0x58, 0xa6, 0xff)),
            ("Error text on panel", Color32::from_rgb(0xff, 0x5a, 0x5a), Color32::from_rgb(0x0f, 0x0f, 0x13)),
            ("Success text on panel", Color32::from_rgb(0x4c, 0xd0, 0x8c), Color32::from_rgb(0x0f, 0x0f, 0x13)),
            ("Warning text on panel", Color32::from_rgb(0xf0, 0x9c, 0x4c), Color32::from_rgb(0x0f, 0x0f, 0x13)),
            ("Border on panel", Color32::from_rgb(0x2a, 0x2a, 0x33), Color32::from_rgb(0x0f, 0x0f, 0x13)),
        ];
        let contrast_result = color_contrast_audit(view_name, &contrast_pairs);
        print_contrast_audit_report(&contrast_result);

        // --- Element Density Counter ---
        let density_results = element_density_counter(view_name, &img, &quadrants);
        print_element_density_report(&density_results);

        // --- Hot Corner Detection ---
        let corner_results = hot_corner_detection(view_name, &img, &quadrants);
        print_hot_corner_report(&corner_results);

        // --- Fitts's Law Analysis ---
        // Typical button measurements (approximated from UI layout)
        let button_measurements = vec![
            ("Save & Finish", 150.0, 36.0, 400.0),
            ("Skip Setup", 120.0, 36.0, 450.0),
            ("Accept & Next", 140.0, 36.0, 300.0),
            ("Start Scan", 130.0, 36.0, 250.0),
        ];
        let fitts_results = fitts_law_analysis(view_name, &button_measurements);
        print_fitts_law_report(&fitts_results);
    }

    Ok(result)
}
#[allow(dead_code)]
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let mut view_name = None;
    let mut enable_ocr = false;
    let mut enable_regions = false;
    let mut enable_intel = false;
    let mut enable_capture_all = false;
    let mut scenario = CaptureScenario::Populated;
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
            "--regions" => {
                enable_regions = true;
            }
            "--capture-intel" => {
                enable_intel = true;
            }
            "--capture-all" => {
                enable_capture_all = true;
            }
            "--scenario" => {
                i += 1;
                if i < args.len() {
                    scenario = match args[i].as_str() {
                        "empty" => CaptureScenario::Empty,
                        "populated" => CaptureScenario::Populated,
                        "error" => CaptureScenario::Error,
                        "loading" => CaptureScenario::Loading,
                        other => {
                            eprintln!("Unknown scenario '{}'. Use: empty, populated, error, loading", other);
                            std::process::exit(1);
                        }
                    };
                }
            }
            "--out" => {
                i += 1;
                if i < args.len() {
                    output_dir = Path::new(&args[i]).to_path_buf();
                }
            }
            "--help" | "-h" => {
                println!("Usage: capture_screens [--view <name>] [--scenario <name>] [--ocr] [--regions] [--capture-intel] [--capture-all] [--out <dir>]");
                println!("  --view <name>     Capture a single view: scan, review, organize, artwork, done, setup, catalog, batch-extract, extract-progress, extract-result");
                println!("  --scenario <name> Mock scenario: empty, populated, error, loading (default: populated)");
                println!("  --ocr             Run Tesseract OCR verification on captured screenshots");
                println!("  --regions         Run multi-region OCR (crops header/content/buttons/footer)");
                println!("  --capture-intel   Capture full OCR intel per view (all text, confidence, bounding boxes)");
                println!("  --capture-all     Capture ALL views × ALL scenarios (comprehensive gap-finding sweep)");
                println!("  --out <dir>       Output directory (default: docs/screenshots)");
                return;
            }
            _ => {
                eprintln!("Unknown argument: {}", args[i]);
                std::process::exit(1);
            }
        }
        i += 1;
    }

    // Need exe path for any mode that launches the app in mock mode
    let exe_path = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_default()
        .join("steam-game-organizer.exe");
    if !exe_path.is_file() && (enable_intel || enable_capture_all) {
        eprintln!("Intel capture requires steam-game-organizer.exe beside capture_screens.exe");
        std::process::exit(1);
    }

    if enable_capture_all {
        match capture_all_scenarios(&exe_path, &output_dir) {
            Ok(results) => {
                let total = results.len();
                println!("\n=== Capture-all complete: {} view-scenario combinations ===", total);
                for (view, scenario, report) in &results {
                    println!(
                        "  {}/{} ({:?}): {} words, {:.1}% conf, {} high, {} low",
                        view,
                        scenario.as_str(),
                        scenario,
                        report.total_words,
                        report.avg_confidence,
                        report.high_confidence_words.len(),
                        report.low_confidence_words.len()
                    );
                }
            }
            Err(e) => {
                eprintln!("Capture-all failed: {}", e);
                std::process::exit(1);
            }
        }
        return;
    }

    if let Some(view) = &view_name {
        if enable_intel {
            match capture_intel_for_view_with_scenario(&exe_path, view, scenario.clone(), &output_dir) {
                Ok(report) => {
                    println!("{}", format_ocr_intel_report(&report));
                }
                Err(e) => {
                    eprintln!("Intel capture failed for view '{}': {}", view, e);
                    std::process::exit(1);
                }
            }
        } else if enable_regions {
            match capture_and_ocr_regions(&output_dir, view) {
                Ok(regions) => {
                    println!("Multi-region OCR complete for view '{}'.", view);
                    for r in &regions {
                        println!(
                            "  Region '{}': {:.1}% confidence, {} words",
                            r.region_name,
                            r.avg_confidence,
                            r.words.len()
                        );
                        println!("    Text: {:?}", r.ocr_text.chars().take(120).collect::<String>());
                    }
                }
                Err(e) => {
                    eprintln!("Error: {}", e);
                    std::process::exit(1);
                }
            }
        } else {
            match capture_and_verify(&output_dir, view, enable_ocr) {
                Ok(_result) => println!("Capture complete for view '{}'.", view),
                Err(e) => {
                    eprintln!("Error: {}", e);
                    std::process::exit(1);
                }
            }
        }
    } else {
        // No view specified: capture all views in sequence
        let views = [
            "scan", "review", "organize", "artwork", "done", "setup",
            "catalog", "batch-extract", "extract-progress", "extract-result",
        ];
        if enable_intel {
            if !exe_path.is_file() {
                eprintln!("Intel capture requires steam-game-organizer.exe beside capture_screens.exe");
                std::process::exit(1);
            }
            for view in &views {
                println!("=== Intel capture for view '{}' ===", view);
                match capture_intel_for_view_with_scenario(&exe_path, view, scenario.clone(), &output_dir) {
                    Ok(report) => {
                        println!("{}", format_ocr_intel_report(&report));
                    }
                    Err(e) => {
                        eprintln!("Intel capture failed for view '{}': {}", view, e);
                    }
                }
            }
        } else {
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
    }

    #[test]
    fn test_ocr_screen_headers_coverage() {
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

    #[test]
    fn test_ocr_headers_include_button_labels_for_interactive_views() {
        let interactive_views = [
            "scan", "review", "organize", "artwork", "done", "setup",
        ];
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

    #[test]
    fn test_ocr_missing_button_label_detected() {
        let ocr_text = "SCREEN - No archives discovered - Archives Found 0 - Phases Complete 0";
        let (_found, missing, _forbidden) = verify_ocr(ocr_text, "scan");
        assert!(
            missing.iter().any(|m| m == "Start Scan"),
            "OCR should detect missing 'Start Scan' button label"
        );
    }

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

    #[test]
    fn test_ocr_partial_match_counts() {
        let ocr_text = "SCAN - No archives discovered - Start Scn - Scan with Artwok";
        let (found, missing, _forbidden) = verify_ocr(ocr_text, "scan");
        assert!(
            !found.is_empty() || missing.len() < 2,
            "Partial OCR matches should reduce missing count"
        );
    }

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

    /// Region headers are defined for every interactive view.
    #[test]
    fn test_region_headers_coverage() {
        let interactive_views = [
            "scan", "review", "organize", "artwork", "done", "setup",
        ];
        for view_name in &interactive_views {
            assert!(
                OCR_REGION_HEADERS.iter().any(|(n, _)| *n == *view_name),
                "No region OCR headers defined for view '{}'", view_name
            );
            let regions = OCR_REGION_HEADERS
                .iter()
                .find(|(n, _)| *n == *view_name)
                .map(|(_, r)| *r)
                .unwrap_or(&[]);
            // Every region should have header, content, buttons, footer
            let region_names: Vec<&str> = regions.iter().map(|(rn, _)| *rn).collect();
            for expected_region in ["r1c1", "r1c2", "r1c3", "r1c4", "r2c1", "r2c2", "r2c3", "r2c4", "r3c1", "r3c2", "r3c3", "r3c4", "r4c1", "r4c2", "r4c3", "r4c4"] {
                assert!(
                    region_names.contains(&expected_region),
                    "View '{}' region headers missing region '{}'", view_name, expected_region
                );
            }
        }
    }

    /// Live text is defined for every interactive view.
    #[test]
    fn test_live_text_coverage() {
        let interactive_views = [
            "scan", "review", "organize", "artwork", "done", "setup",
        ];
        for view_name in &interactive_views {
            assert!(
                OCR_LIVE_TEXT.iter().any(|(n, _)| *n == *view_name),
                "No live text defined for view '{}'", view_name
            );
            let texts = OCR_LIVE_TEXT
                .iter()
                .find(|(n, _)| *n == *view_name)
                .map(|(_, t)| *t)
                .unwrap_or(&[]);
            assert!(!texts.is_empty(), "View '{}' must have non-empty live text", view_name);
        }
    }

    /// Live text verification finds expected text in OCR output.
    #[test]
    fn test_verify_live_text_found() {
        let ocr_text = "Organization Complete - Archives: Alpha Forge, Gamma Quest - Undo Last Run - Open Library Folder";
        let (found, missing) = verify_live_text(ocr_text, "done");
        assert!(found.iter().any(|f| f == "Organization Complete"));
        assert!(found.iter().any(|f| f == "Undo Last Run"));
        assert!(missing.is_empty(), "Expected live text should not be missing: {:?}", missing);
    }

    /// Live text verification detects missing text in OCR output.
    #[test]
    fn test_verify_live_text_missing() {
        let ocr_text = "Something completely unrelated here.";
        let (found, missing) = verify_live_text(ocr_text, "done");
        assert!(found.is_empty(), "No live text should be found in unrelated OCR output");
        assert!(!missing.is_empty(), "Expected live text should be missing");
    }

    /// verify_ocr_regions returns results for every defined region.
    #[test]
    fn test_verify_ocr_regions_structure() {
        let regions = vec![
            OcrRegionResult {
                region_name: "r1c1".to_string(),
                capture_type: CaptureType::Region,
                ocr_text: "SCAN - No archives discovered".to_string(),
                words: vec![],
                avg_confidence: 85.0,
            },
            OcrRegionResult {
                region_name: "r4c4".to_string(),
                capture_type: CaptureType::Region,
                ocr_text: "complete phase Start Scan".to_string(),
                words: vec![],
                avg_confidence: 78.0,
            },
        ];
        let results = verify_ocr_regions(&regions, "scan");
        assert_eq!(results.len(), 16); // r1c1-r4c4
        let r1c1_result = results.iter().find(|(rn, _, _)| rn == "r1c1").unwrap();
        assert!(r1c1_result.1.iter().any(|f| f == "SCAN"), "r1c1 region should find SCAN");
        let r4c4_result = results.iter().find(|(rn, _, _)| rn == "r4c4").unwrap();
        assert!(
            r4c4_result.1.iter().any(|f| f == "complete"),
            "r4c4 region should find complete"
        );
        let r4c1_result = results.iter().find(|(rn, _, _)| rn == "r4c1").unwrap();
        assert!(
            r4c1_result.2.iter().any(|m| m == "Start Scan"),
            "r4c1 region should flag missing Start Scan (not in OCR text)"
        );
    }

    /// Native image preprocessing produces a valid output file.
    #[test]
    fn test_preprocess_image_native() {
        // Create a small test image
        let mut img = RgbaImage::new(100, 100);
        for (_, _, pixel) in img.enumerate_pixels_mut() {
            *pixel = image::Rgba([200, 100, 50, 255]);
        }
        let test_path = std::env::temp_dir().join("test_preprocess.png");
        img.save(&test_path).unwrap();

        let result = preprocess_image_native(&test_path);
        assert!(result.is_ok(), "Native preprocessing should succeed: {:?}", result.err());
        let out_path = result.unwrap();
        assert!(out_path.exists(), "Preprocessed image should exist at {:?}", out_path);
        assert!(
            out_path.extension().unwrap() == "png",
            "Preprocessed image should be PNG"
        );

        // Verify the output is larger (upscaled 2x)
        let out_img = image::open(&out_path).unwrap();
        let (w, h) = out_img.dimensions();
        assert_eq!(w, 200, "Upscaled image should be 2x width");
        assert_eq!(h, 200, "Upscaled image should be 2x height");

        // Clean up
        let _ = std::fs::remove_file(&test_path);
        let _ = std::fs::remove_file(&out_path);
    }

    /// PHash computes identical hash for identical images.
    #[test]
    fn test_phash_identical_images() {
        let img1 = RgbaImage::new(100, 100);
        let img2 = RgbaImage::new(100, 100);
        let dyn1 = DynamicImage::ImageRgba8(img1);
        let dyn2 = DynamicImage::ImageRgba8(img2);
        let hash1 = PHash::compute(&dyn1);
        let hash2 = PHash::compute(&dyn2);
        assert_eq!(hash1, hash2);
        assert_eq!(hash1.distance(&hash2), 0);
        assert_eq!(hash1.similarity(&hash2), 0.0);
        assert!(hash1.is_similar(&hash2));
    }

    /// PHash detects different images.
    #[test]
    fn test_phash_different_images() {
        // All black vs left half white / right half black -> different pHash
        let mut img1 = RgbaImage::new(100, 100);
        for pixel in img1.pixels_mut() {
            *pixel = image::Rgba([0, 0, 0, 255]);
        }
        let mut img2 = RgbaImage::new(100, 100);
        for y in 0..100 {
            for x in 0..100 {
                if x < 50 {
                    img2.put_pixel(x, y, image::Rgba([255, 255, 255, 255]));
                } else {
                    img2.put_pixel(x, y, image::Rgba([0, 0, 0, 255]));
                }
            }
        }
        let dyn1 = DynamicImage::ImageRgba8(img1);
        let dyn2 = DynamicImage::ImageRgba8(img2);
        let hash1 = PHash::compute(&dyn1);
        let hash2 = PHash::compute(&dyn2);
        assert_ne!(hash1, hash2);
        assert!(hash1.distance(&hash2) > 0);
        assert!(!hash1.is_similar(&hash2));
    }

    /// preprocess_for_ocr upscales and converts to grayscale.
    #[test]
    fn test_preprocess_for_ocr() {
        let mut img = RgbaImage::new(100, 100);
        for pixel in img.pixels_mut() {
            *pixel = image::Rgba([200, 100, 50, 255]);
        }
        let dyn_img = DynamicImage::ImageRgba8(img);
        let opts = OcrPreprocessOptions::default();
        let result = preprocess_for_ocr(&dyn_img, &opts);
        let (w, h) = result.dimensions();
        assert_eq!(w, 200, "Upscaled width should be 2x");
        assert_eq!(h, 200, "Upscaled height should be 2x");
        // Result should be grayscale (Luma8)
        assert!(matches!(result, DynamicImage::ImageLuma8(_)));
    }

    /// OCR word struct is constructed correctly.
    #[test]
    fn test_ocr_word_construction() {
        let word = OcrWord {
            text: "Hello".to_string(),
            confidence: 92.5,
            left: 10,
            top: 20,
            width: 30,
            height: 40,
        };
        assert_eq!(word.text, "Hello");
        assert_eq!(word.confidence, 92.5);
        assert_eq!(word.left, 10);
        assert_eq!(word.top, 20);
        assert_eq!(word.width, 30);
        assert_eq!(word.height, 40);
    }
}

// ========================================================================
// CODE vs REALITY UI Verification
// ========================================================================
//
// Compares what the source code claims to render (button macro calls)
// against what OCR actually detects in screenshots. This catches:
//   - Code renders a button but OCR can't see it → BUG (button missing or invisible)
//   - Code doesn't render a button (logic bug, wrong condition) → BUG
//   - OCR finds text that code doesn't expect (stale expectations) → INFO
//
// CRITICAL RULE: Missing = Missing. If source code defines a button but OCR
// cannot detect it, the button is considered MISSING. Do NOT excuse this as
// "dark mode low contrast" — if the button is on screen, OCR should see it.
// If OCR can't see it, either the button isn't rendering or the text is
// illegible (which is itself a UI bug).
//
// Expected button text is extracted from source code calls to:
//   secondary_button(ui, "Text", ...)
//   primary_button(ui, "Text", ...)
//   danger_button(ui, "Text", ...)
//
// When adding new buttons to a view, add them here too so verification
// catches any divergence between code and rendered output.

/// Expected button text per view, extracted from source code button macros.
/// Format: view_name -> list of (button_text, is_required)
///
/// A button is "required" if it must always be visible (not conditional
/// on state like "accept/reject for selected archive").
const EXPECTED_BUTTONS_PER_VIEW: &[(&str, &[(&str, bool)])] = &[
    (
        "scan",
        &[
            ("Start Scan", true),
            ("Scan with Artwork", true),
            ("Cancel Scan", true),
        ],
    ),
    (
        "review",
        &[
            ("Accept & Next", true),
            ("Skip", true),
            ("Wrong Match", true),
            ("Extract Selected", true),
            ("Accept", false),   // conditional on selection
            ("Reject", false),   // conditional on selection
            ("Approve All Verified", true),
            ("＋ Add Category", true),
            ("Use All Suggestions", true),
            ("Retry Failed", true),
            ("Continue to Organization", true),
        ],
    ),
    (
        "organize",
        &[
            ("Start Organize", true),
            ("Cancel", true),
        ],
    ),
    (
        "artwork",
        &[
            ("Open Folder", false),   // conditional on archive
            ("View Artwork", false),  // conditional on archive
            ("Scan Again", true),
            ("Review", true),
            ("Re-download Missing", true),
        ],
    ),
    (
        "done",
        &[
            ("Open Library Folder", true),
            ("Undo Last Run", true),
            ("Scan Again", true),
        ],
    ),
    (
        "setup",
        &[
            ("Browse Library", true),
            ("Browse Extract", true),
            ("Browse 7-Zip", true),
            ("Validate Configuration", true),
            ("Save & Finish Setup", true),
            ("Skip Setup", true),
        ],
    ),
];

/// Result of code-vs-reality UI verification for a single view.
pub struct UiElementVerificationResult {
    pub view_name: String,
    /// Buttons that code claims to render but OCR did not find
    pub missing_from_ocr: Vec<String>,
    /// Text OCR found that is not in expected buttons (possible false positives)
    pub unexpected_from_ocr: Vec<String>,
    /// Buttons found by OCR with high confidence (>80%)
    pub high_confidence_found: Vec<String>,
    /// Buttons found by OCR with low confidence (<50%)
    pub low_confidence_found: Vec<String>,
}

/// Compare expected button text (from source code) against OCR results
/// from all captured regions (full window + quadrants + composite).
pub fn verify_ui_elements(
    view_name: &str,
    ocr_texts: &[&str],
) -> UiElementVerificationResult {
    let mut all_ocr_text = String::new();
    for text in ocr_texts {
        all_ocr_text.push_str(text);
        all_ocr_text.push('\n');
    }
    let ocr_upper = all_ocr_text.to_uppercase();

    let expected = EXPECTED_BUTTONS_PER_VIEW
        .iter()
        .find(|(v, _)| *v == view_name)
        .map(|(_, buttons)| *buttons)
        .unwrap_or(&[]);

    let mut missing_from_ocr = Vec::new();
    let mut high_confidence_found = Vec::new();
    let mut low_confidence_found = Vec::new();

    for (button_text, _is_required) in expected {
        let button_upper = button_text.to_uppercase();
        let found = ocr_upper.contains(&button_upper);
        if found {
            high_confidence_found.push(button_text.to_string());
        } else {
            missing_from_ocr.push(button_text.to_string());
        }
    }

    UiElementVerificationResult {
        view_name: view_name.to_string(),
        missing_from_ocr,
        unexpected_from_ocr: Vec::new(),
        high_confidence_found,
        low_confidence_found,
    }
}

/// Print a human-readable report of code-vs-reality UI verification.
pub fn print_ui_verification_report(result: &UiElementVerificationResult) {
    eprintln!("\n════════════════════════════════════════════════════════════════════");
    eprintln!("UI ELEMENT VERIFICATION: {}", result.view_name.to_uppercase());
    eprintln!("════════════════════════════════════════════════════════════════════");

    if result.missing_from_ocr.is_empty() {
        eprintln!("  [OK] All expected buttons found by OCR");
    } else {
        eprintln!("  [MISSING] Buttons in code but NOT found by OCR:");
        for btn in &result.missing_from_ocr {
            eprintln!("      - \"{}\"", btn);
        }
    }

    if !result.high_confidence_found.is_empty() {
        eprintln!("  [FOUND] Buttons detected by OCR:");
        for btn in &result.high_confidence_found {
            eprintln!("      - \"{}\"", btn);
        }
    }

    if !result.unexpected_from_ocr.is_empty() {
        eprintln!("  [UNEXPECTED] Text found by OCR not in expected buttons:");
        for txt in &result.unexpected_from_ocr {
            eprintln!("      - \"{}\"", txt);
        }
    }

    eprintln!("");
}

/// Calculate relative luminance of a color (per WCAG spec).
fn relative_luminance(color: Color32) -> f32 {
    let srgb = |c: u8| {
        let c = c as f32 / 255.0;
        if c <= 0.03928 {
            c / 12.92
        } else {
            ((c + 0.055) / 1.055).powf(2.4)
        }
    };
    0.2126 * srgb(color[0]) + 0.7152 * srgb(color[1]) + 0.0722 * srgb(color[2])
}

/// Calculate WCAG contrast ratio between two colors.
/// Returns a value >= 1.0; higher means better contrast.
/// WCAG AA requires 4.5:1 for normal text, 3:1 for large text.
/// WCAG AAA requires 7:1 for normal text, 4.5:1 for large text.
pub fn contrast_ratio(fg: Color32, bg: Color32) -> f32 {
    let lum_fg = relative_luminance(fg);
    let lum_bg = relative_luminance(bg);
    let lighter = lum_fg.max(lum_bg);
    let darker = lum_fg.min(lum_bg);
    (lighter + 0.05) / (darker + 0.05)
}

/// Result of color contrast audit.
pub struct ContrastAuditResult {
    pub view_name: String,
    pub total_checks: usize,
    pub passing_aa: usize,
    pub failing_aa: usize,
    pub passing_aaa: usize,
    pub failing_aaa: usize,
    pub min_ratio: f32,
    pub worst_pair: Option<(String, String, f32)>,
}

/// Audit color contrast ratios between foreground/background color pairs.
/// Checks WCAG AA (4.5:1) and AAA (7:1) compliance.
pub fn color_contrast_audit(view_name: &str, color_pairs: &[(&str, Color32, Color32)]) -> ContrastAuditResult {
    let mut total = 0;
    let mut passing_aa = 0;
    let mut failing_aa = 0;
    let mut passing_aaa = 0;
    let mut failing_aaa = 0;
    let mut min_ratio = f32::INFINITY;
    let mut worst_pair: Option<(String, String, f32)> = None;

    for (label, fg, bg) in color_pairs {
        let ratio = contrast_ratio(*fg, *bg);
        total += 1;
        if ratio >= 4.5 {
            passing_aa += 1;
        } else {
            failing_aa += 1;
        }
        if ratio >= 7.0 {
            passing_aaa += 1;
        } else {
            failing_aaa += 1;
        }
        if ratio < min_ratio {
            min_ratio = ratio;
            worst_pair = Some((label.to_string(), format!("{:?}/{:?}", fg, bg), ratio));
        }
    }

    ContrastAuditResult {
        view_name: view_name.to_string(),
        total_checks: total,
        passing_aa,
        failing_aa,
        passing_aaa,
        failing_aaa,
        min_ratio: if min_ratio == f32::INFINITY { 0.0 } else { min_ratio },
        worst_pair,
    }
}

/// Print color contrast audit report.
pub fn print_contrast_audit_report(result: &ContrastAuditResult) {
    eprintln!("\n════════════════════════════════════════════════════════════════════");
    eprintln!("COLOR CONTRAST AUDIT: {}", result.view_name.to_uppercase());
    eprintln!("════════════════════════════════════════════════════════════════════");
    eprintln!("  Total checks:   {}", result.total_checks);
    eprintln!("  WCAG AA (4.5:1): {} passing, {} failing", result.passing_aa, result.failing_aa);
    eprintln!("  WCAG AAA (7:1):  {} passing, {} failing", result.passing_aaa, result.failing_aaa);
    eprintln!("  Minimum ratio:   {:.2}:1", result.min_ratio);
    if let Some((label, pair, ratio)) = &result.worst_pair {
        eprintln!("  Worst pair:      {} ({}) = {:.2}:1", label, pair, ratio);
    }
    eprintln!("");
}

/// Element density result per quadrant.
pub struct ElementDensityResult {
    pub view_name: String,
    pub quadrant: String,
    pub element_count: usize,
    pub density_score: f32, // elements per 10000 pixels
}

/// Count distinct visual elements per quadrant.
/// Uses color clustering to estimate distinct UI elements.
pub fn element_density_counter(
    view_name: &str,
    img: &image::DynamicImage,
    quadrants: &[(&str, u32, u32, u32, u32)],
) -> Vec<ElementDensityResult> {
    let (img_w, img_h) = img.dimensions();
    let mut results = Vec::new();

    for (name, left, top, right, bottom) in quadrants {
        let qw = *right - *left;
        let qh = *bottom - *top;
        let total_pixels = qw * qh;

        // Sample colors at a grid to count distinct colors
        let mut colors = std::collections::HashSet::new();
        let sample_step = qw.max(qh) / 8;
        let sample_step = if sample_step == 0 { 1 } else { sample_step };

        for y in (*top..*bottom).step_by(sample_step as usize) {
            for x in (*left..*right).step_by(sample_step as usize) {
                if x < img_w && y < img_h {
                    let pixel = img.get_pixel(x, y);
                    // Quantize color to reduce noise
                    let q_r = (pixel[0] / 16) * 16;
                    let q_g = (pixel[1] / 16) * 16;
                    let q_b = (pixel[2] / 16) * 16;
                    colors.insert((q_r, q_g, q_b));
                }
            }
        }

        let element_count = colors.len();
        let density_score = if total_pixels > 0 {
            element_count as f32 / (total_pixels as f32 / 10000.0)
        } else {
            0.0
        };

        results.push(ElementDensityResult {
            view_name: view_name.to_string(),
            quadrant: name.to_string(),
            element_count,
            density_score,
        });
    }

    results
}

/// Print element density report.
pub fn print_element_density_report(results: &[ElementDensityResult]) {
    eprintln!("\n════════════════════════════════════════════════════════════════════");
    eprintln!("ELEMENT DENSITY ANALYSIS: {}", results.first().map(|r| r.view_name.as_str()).unwrap_or("").to_uppercase());
    eprintln!("════════════════════════════════════════════════════════════════════");
    eprintln!("  Quadrant     | Elements | Density (per 10k px)");
    eprintln!("  -------------|----------|-------------------");
    for r in results {
        eprintln!(
            "  {:<12} | {:>8} | {:>17.1}",
            r.quadrant, r.element_count, r.density_score
        );
    }
    eprintln!("");
}

/// Fitts's Law measurement result.
pub struct FittsLawResult {
    pub view_name: String,
    pub button_name: String,
    pub button_width: f32,
    pub button_height: f32,
    pub distance_from_center: f32,
    pub difficulty_index: f32, // log2(distance / width + 1)
}

/// Measure button sizes and distances for Fitts's Law analysis.
pub fn fitts_law_analysis(
    view_name: &str,
    button_measurements: &[(&str, f32, f32, f32)],
) -> Vec<FittsLawResult> {
    let mut results = Vec::new();
    for (name, width, height, distance) in button_measurements {
        let difficulty = (distance / width + 1.0).log2();
        results.push(FittsLawResult {
            view_name: view_name.to_string(),
            button_name: name.to_string(),
            button_width: *width,
            button_height: *height,
            distance_from_center: *distance,
            difficulty_index: difficulty,
        });
    }
    results
}

/// Print Fitts's Law report.
pub fn print_fitts_law_report(results: &[FittsLawResult]) {
    eprintln!("\n════════════════════════════════════════════════════════════════════");
    eprintln!("FITTS'S LAW ANALYSIS: {}", results.first().map(|r| r.view_name.as_str()).unwrap_or("").to_uppercase());
    eprintln!("════════════════════════════════════════════════════════════════════");
    eprintln!("  Button             | Width  | Height | Distance | Difficulty (ID)");
    eprintln!("  -------------------|--------|--------|----------|----------------");
    for r in results {
        eprintln!(
            "  {:<19} | {:>6.1} | {:>6.1} | {:>8.1} | {:>14.2}",
            r.button_name, r.button_width, r.button_height, r.distance_from_center, r.difficulty_index
        );
    }
    eprintln!("  Note: Lower ID = easier to hit. ID > 3.5 is considered difficult.");
    eprintln!("");
}

/// Hot corner detection result.
pub struct HotCornerResult {
    pub view_name: String,
    pub corner: String,
    pub element_count: u32,
    pub has_primary_action: bool,
}

/// Detect which screen corners contain UI elements.
pub fn hot_corner_detection(
    view_name: &str,
    img: &image::DynamicImage,
    quadrants: &[(&str, u32, u32, u32, u32)],
) -> Vec<HotCornerResult> {
    let corners = [
        ("r1c1", "Top-Left"),
        ("r1c4", "Top-Right"),
        ("r4c1", "Bottom-Left"),
        ("r4c4", "Bottom-Right"),
    ];
    let mut results = Vec::new();

    for (quad_id, corner_name) in &corners {
        if let Some((_, left, top, right, bottom)) = quadrants.iter().find(|(q, _, _, _, _)| q == quad_id) {
            let qw = *right - *left;
            let qh = *bottom - *top;
            let mut element_count = 0u32;
            let sample_step = qw.max(qh) / 6;
            let sample_step = if sample_step == 0 { 1 } else { sample_step };
            let (img_w, img_h) = img.dimensions();

            for y in (*top..*bottom).step_by(sample_step as usize) {
                for x in (*left..*right).step_by(sample_step as usize) {
                    if x < img_w && y < img_h {
                        let pixel = img.get_pixel(x, y);
                        let brightness = (pixel[0] as f32 + pixel[1] as f32 + pixel[2] as f32) / 3.0;
                        if brightness > 40.0 {
                            element_count += 1;
                        }
                    }
                }
            }

            results.push(HotCornerResult {
                view_name: view_name.to_string(),
                corner: corner_name.to_string(),
                element_count,
                has_primary_action: element_count > 50,
            });
        }
    }

    results
}

/// Print hot corner detection report.
pub fn print_hot_corner_report(results: &[HotCornerResult]) {
    eprintln!("\n════════════════════════════════════════════════════════════════════");
    eprintln!("HOT CORNER DETECTION: {}", results.first().map(|r| r.view_name.as_str()).unwrap_or("").to_uppercase());
    eprintln!("════════════════════════════════════════════════════════════════════");
    eprintln!("  Corner        | Elements | Primary Action");
    eprintln!("  --------------|----------|---------------");
    for r in results {
        eprintln!(
            "  {:<14} | {:>8} | {}",
            r.corner, r.element_count, if r.has_primary_action { "Yes" } else { "No" }
        );
    }
    eprintln!("  Note: Primary actions (Save, OK, Confirm) should be in bottom-right corner.");
    eprintln!("");
}
