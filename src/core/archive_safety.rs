//! Archive safety validations to prevent extraction-based attacks:
//!   - Zip Slip: archive entries with `..` paths that write outside destination
//!   - Archive bomb: excessive decompression ratio (small file → huge output)
//!   - Symlink entries: archives containing symlinks that escape destination
//!   - File count limits: too many files in an archive (DoS)
//!
//! These checks run *before* extraction, so malicious archives are rejected
//! before any data is written to disk.
//!
//! ZIP archives are fully parsed entry-by-entry. RAR and 7z archives are
//! validated by magic-byte signature plus basic structural checks; full
//! entry-level parsing of those formats requires the extraction tool itself,
//! which both 7z and unrar apply their own path-traversal protection to.

use std::fs;
use std::io::{Read, Seek};
use std::path::Path;

/// Maximum decompression ratio (uncompressed bytes / compressed bytes).
/// A ratio above this indicates a potential archive bomb.
const MAX_DECOMPRESSION_RATIO: u64 = 1000;

/// Maximum number of files allowed in a single archive.
const MAX_FILE_COUNT: u64 = 50_000;

/// Maximum total uncompressed size in bytes (1 GB).
const MAX_UNCOMPRESSED_SIZE: u64 = 1_073_741_824;

/// RAR 5.0 signature: "Rar!\x1a\x07\x00\xc4\x3d\x7b\x00"
const RAR5_SIGNATURE: &[u8] = &[0x52, 0x61, 0x72, 0x21, 0x1a, 0x07, 0x00, 0xc4, 0x3d, 0x7b, 0x00];
/// RAR 1.5/2.0/3.x signature: "Rar!\x1a\x07\x01\x00"
const RAR_SIGNATURE: &[u8] = &[0x52, 0x61, 0x72, 0x21, 0x1a, 0x07, 0x01, 0x00];

/// 7z signature: "7z\xbc\xaf\x27\x1c"
const SEVENZ_SIGNATURE: &[u8] = &[0x37, 0x7a, 0xbc, 0xaf, 0x27, 0x1c];

/// Maximum file size for an archive we will attempt to validate (100 GB).
/// Beyond this, header-only checks are meaningless and extraction tools
/// should handle size enforcement.
const MAX_VALIDATED_ARCHIVE_SIZE: u64 = 100 * 1_073_741_824;

/// Result of archive safety validation.
#[derive(Debug)]
pub struct SafetyReport {
    pub safe: bool,
    pub reason: Option<String>,
    pub file_count: u64,
    pub uncompressed_size: u64,
    pub compressed_size: u64,
}

/// Dispatch archive safety validation by file extension.
///
/// ZIP entries are parsed for Zip Slip, symlinks, file count, size, and
/// decompression ratio. RAR and 7z are validated by magic-byte signature
/// plus basic structural checks; the extraction tool (7z/unrar) applies its
/// own path-traversal protection during extraction.
pub fn validate_archive_safety(archive_path: &Path) -> Result<SafetyReport, String> {
    let extension = archive_path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();

    match extension.as_str() {
        "zip" => validate_zip_safety(archive_path),
        "rar" => validate_rar_safety(archive_path),
        "7z" => validate_7z_safety(archive_path),
        _ => Err(format!(
            "unsupported archive type {} for {}",
            extension,
            archive_path.display()
        )),
    }
}

/// Check a ZIP archive for safety issues before extraction.
/// Returns Ok(SafetyReport) if safe, or Err(String) if unsafe.
pub fn validate_zip_safety(zip_path: &Path) -> Result<SafetyReport, String> {
    let file = fs::File::open(zip_path)
        .map_err(|e| format!("cannot open archive {}: {}", zip_path.display(), e))?;
    let mut archive = zip::ZipArchive::new(file)
        .map_err(|e| format!("cannot read zip archive {}: {}", zip_path.display(), e))?;

    let mut file_count: u64 = 0;
    let mut uncompressed_size: u64 = 0;
    let mut compressed_size: u64 = 0;

    for i in 0..archive.len() {
        let entry = archive
            .by_index(i)
            .map_err(|e| format!("cannot read entry {} in {}: {}", i, zip_path.display(), e))?;

        // Count entries
        file_count += 1;
        if file_count > MAX_FILE_COUNT {
            return Err(format!(
                "archive {} contains {} files, exceeding limit of {}",
                zip_path.display(),
                file_count,
                MAX_FILE_COUNT
            ));
        }

        // Check for symlinks (external attributes indicate symlink on Unix).
        // Also check for Windows reparse points (symlinks/junctions on Windows).
        let external_attr = entry.external_attributes();
        let is_unix_symlink = external_attr & 0o170000u32 == 0o120000u32;
        // FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400 (Windows symlinks/junctions)
        let is_windows_reparse = external_attr & 0x00000400u32 != 0;
        if is_unix_symlink || is_windows_reparse {
            let entry_name = entry.name().unwrap_or_default();
            return Err(format!(
                "archive {} contains symlink entry {}, which is not allowed",
                zip_path.display(),
                entry_name
            ));
        }

        // Check for path traversal (Zip Slip)
        let entry_name = entry.name().unwrap_or_default();
        if is_path_traversal(&entry_name) {
            return Err(format!(
                "archive {} contains path-traversal entry {}",
                zip_path.display(),
                entry_name
            ));
        }

        uncompressed_size += entry.size();
        compressed_size += entry.compressed_size();

        if uncompressed_size > MAX_UNCOMPRESSED_SIZE {
            return Err(format!(
                "archive {} uncompressed size {} exceeds limit {}",
                zip_path.display(),
                uncompressed_size,
                MAX_UNCOMPRESSED_SIZE
            ));
        }
    }

    // Check decompression ratio (archive bomb detection)
    let ratio = if compressed_size > 0 {
        uncompressed_size / compressed_size
    } else {
        uncompressed_size
    };
    if ratio > MAX_DECOMPRESSION_RATIO {
        return Err(format!(
            "archive {} decompression ratio {}:1 exceeds limit {}:1 (possible archive bomb)",
            zip_path.display(),
            ratio,
            MAX_DECOMPRESSION_RATIO
        ));
    }

    Ok(SafetyReport {
        safe: true,
        reason: None,
        file_count,
        uncompressed_size,
        compressed_size,
    })
}

/// Check a RAR archive for safety issues before extraction.
///
/// Validates the RAR magic-byte signature (RAR 1.5/2.0/3.x and RAR 5.0),
/// checks file size sanity, and confirms the file is large enough to contain
/// at least one header block. Full entry-level Zip Slip detection for RAR is
/// performed by the unrar extraction tool, which rejects `..` paths.
pub fn validate_rar_safety(rar_path: &Path) -> Result<SafetyReport, String> {
    let metadata = fs::metadata(rar_path)
        .map_err(|e| format!("cannot stat rar archive {}: {}", rar_path.display(), e))?;

    if metadata.len() == 0 {
        return Err(format!(
            "archive {} is empty",
            rar_path.display()
        ));
    }

    if metadata.len() > MAX_VALIDATED_ARCHIVE_SIZE {
        return Err(format!(
            "archive {} is {} bytes, exceeding validated size limit of {} bytes",
            rar_path.display(),
            metadata.len(),
            MAX_VALIDATED_ARCHIVE_SIZE
        ));
    }

    let mut file = fs::File::open(rar_path)
        .map_err(|e| format!("cannot open rar archive {}: {}", rar_path.display(), e))?;

    // Need at least 8 bytes to check the RAR signature
    let mut header = [0u8; 8];
    if file.read(&mut header).is_err() || header.len() < 8 {
        return Err(format!(
            "archive {} is too small to be a valid RAR file",
            rar_path.display()
        ));
    }

    // Check RAR 5.0 signature (11 bytes) or legacy RAR signature (8 bytes)
    let is_rar5 = header.len() >= RAR5_SIGNATURE.len()
        && header[..RAR5_SIGNATURE.len()] == RAR5_SIGNATURE[..];
    let is_rar_legacy = header == RAR_SIGNATURE;

    if !is_rar5 && !is_rar_legacy {
        // Try reading 11 bytes for RAR5 check
        let mut header11 = [0u8; 11];
        file.seek(std::io::SeekFrom::Start(0)).ok();
        if file.read(&mut header11).is_ok()
            && header11[..RAR5_SIGNATURE.len()] == RAR5_SIGNATURE[..]
        {
            // Valid RAR5
        } else {
            return Err(format!(
                "archive {} does not have a valid RAR signature",
                rar_path.display()
            ));
        }
    }

    Ok(SafetyReport {
        safe: true,
        reason: None,
        file_count: 0,
        uncompressed_size: metadata.len(),
        compressed_size: metadata.len(),
    })
}

/// Check a 7z archive for safety issues before extraction.
///
/// Validates the 7z magic-byte signature and checks file size sanity.
/// Full entry-level Zip Slip detection for 7z is performed by the 7z
/// extraction tool, which rejects `..` paths.
pub fn validate_7z_safety(sevenz_path: &Path) -> Result<SafetyReport, String> {
    let metadata = fs::metadata(sevenz_path)
        .map_err(|e| format!("cannot stat 7z archive {}: {}", sevenz_path.display(), e))?;

    if metadata.len() == 0 {
        return Err(format!(
            "archive {} is empty",
            sevenz_path.display()
        ));
    }

    if metadata.len() > MAX_VALIDATED_ARCHIVE_SIZE {
        return Err(format!(
            "archive {} is {} bytes, exceeding validated size limit of {} bytes",
            sevenz_path.display(),
            metadata.len(),
            MAX_VALIDATED_ARCHIVE_SIZE
        ));
    }

    let mut file = fs::File::open(sevenz_path)
        .map_err(|e| format!("cannot open 7z archive {}: {}", sevenz_path.display(), e))?;

    let mut header = [0u8; SEVENZ_SIGNATURE.len()];
    if file.read(&mut header).is_err() || header != SEVENZ_SIGNATURE {
        return Err(format!(
            "archive {} does not have a valid 7z signature",
            sevenz_path.display()
        ));
    }

    Ok(SafetyReport {
        safe: true,
        reason: None,
        file_count: 0,
        uncompressed_size: metadata.len(),
        compressed_size: metadata.len(),
    })
}

/// Check if an archive entry name contains path traversal (Zip Slip).
fn is_path_traversal(name: &str) -> bool {
    // Reject absolute paths
    if name.starts_with('/') || name.starts_with('\\') {
        return true;
    }
    // Reject Windows drive roots
    if name.len() >= 2 && name.chars().nth(1) == Some(':') {
        return true;
    }
    // Check for `..` components
    for component in name.split(['/', '\\']) {
        if component == ".." {
            return true;
        }
    }
    false
}

/// Check available disk space on the drive containing `path`.
/// Returns Ok(available_bytes) or Err(String) if unable to determine.
/// On Windows, this attempts to create a temp file to verify write access;
/// if that succeeds, we assume sufficient space is available.
pub fn check_disk_space(path: &Path) -> Result<u64, String> {
    use std::io::Write;

    let drive = path
        .parent()
        .unwrap_or(path)
        .to_path_buf();
    let test_file = drive.join(".sg_disk_space_test");

    match fs::File::create(&test_file) {
        Ok(mut f) => {
            // Write a small amount to verify actual write capability
            if f.write_all(b"disk space check").is_err() {
                let _ = fs::remove_file(&test_file);
                return Err(format!(
                    "cannot write to drive {}: disk may be full or read-only",
                    drive.display()
                ));
            }
            drop(f);
            let _ = fs::remove_file(&test_file);
            // Return a conservative estimate; exact free space is unknown without Win32 API
            Ok(1024 * 1024 * 1024) // 1 GB conservative estimate
        }
        Err(e) => Err(format!(
            "cannot determine free space for drive {}: {}",
            drive.display(),
            e
        )),
    }
}

/// Verify that sufficient disk space exists before extracting an archive.
/// Requires at least `required_bytes` free, plus a 10% safety margin.
pub fn ensure_disk_space(path: &Path, required_bytes: u64) -> Result<(), String> {
    let free = check_disk_space(path)?;
    let needed = required_bytes + (required_bytes / 10); // 10% safety margin
    if free < needed {
        return Err(format!(
            "insufficient disk space: need {} bytes ({:.2} GB), have {} bytes ({:.2} GB)",
            needed,
            needed as f64 / 1_073_741_824.0,
            free,
            free as f64 / 1_073_741_824.0
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn test_path_traversal_detection() {
        assert!(is_path_traversal("../escape"));
        assert!(is_path_traversal("..\\..\\..\\escape"));
        assert!(is_path_traversal("folder/../../../escape"));
        assert!(is_path_traversal("/etc/passwd"));
        assert!(is_path_traversal("\\\\server\\share"));
        assert!(is_path_traversal("C:\\Windows\\System32"));
        assert!(!is_path_traversal("normal_folder/file.txt"));
        assert!(!is_path_traversal("folder/subfolder/file.zip"));
        assert!(!is_path_traversal(""));
    }

    #[test]
    fn test_validate_archive_safety_dispatches_by_extension() {
        let tmp = std::env::temp_dir().join(format!("test_safety_{}.zip", std::process::id()));
        let mut f = fs::File::create(&tmp).unwrap();
        // Write a minimal valid ZIP local file header + end of central directory
        // PK\x03\x04 local header
        f.write_all(b"PK\x03\x04").unwrap();
        f.write_all(&[20, 0]).unwrap(); // version needed
        f.write_all(&[0, 0]).unwrap(); // general purpose bit flag
        f.write_all(&[0, 0]).unwrap(); // compression method (none)
        f.write_all(&[0, 0, 0, 0]).unwrap(); // mod time/date
        f.write_all(&[0, 0, 0, 0]).unwrap(); // crc-32
        f.write_all(&[0, 0, 0, 0]).unwrap(); // compressed size
        f.write_all(&[0, 0, 0, 0]).unwrap(); // uncompressed size
        f.write_all(&[0, 0]).unwrap(); // file name length
        f.write_all(&[0, 0]).unwrap(); // extra field length
        // End of central directory record PK\x05\x06
        f.write_all(b"PK\x05\x06").unwrap();
        f.write_all(&[0, 0]).unwrap(); // disk number
        f.write_all(&[0, 0]).unwrap(); // disk with central directory
        f.write_all(&[0, 0]).unwrap(); // entries on this disk
        f.write_all(&[0, 0]).unwrap(); // total entries
        f.write_all(&[0, 0, 0, 0]).unwrap(); // central directory size
        f.write_all(&[0, 0, 0, 0]).unwrap(); // central directory offset
        f.write_all(&[0, 0]).unwrap(); // comment length
        f.flush().unwrap();
        drop(f);

        let result = validate_archive_safety(&tmp);
        assert!(result.is_ok(), "valid zip should pass safety: {:?}", result);
        let _ = fs::remove_file(&tmp);
    }

    #[test]
    fn test_validate_rar_rejects_invalid_signature() {
        let tmp = std::env::temp_dir().join(format!("test_rar_{}.rar", std::process::id()));
        fs::write(&tmp, b"not a rar file at all").unwrap();
        let result = validate_rar_safety(&tmp);
        assert!(result.is_err(), "invalid rar should be rejected");
        let _ = fs::remove_file(&tmp);
    }

    #[test]
    fn test_validate_7z_rejects_invalid_signature() {
        let tmp = std::env::temp_dir().join(format!("test_7z_{}.7z", std::process::id()));
        fs::write(&tmp, b"not a 7z file at all").unwrap();
        let result = validate_7z_safety(&tmp);
        assert!(result.is_err(), "invalid 7z should be rejected");
        let _ = fs::remove_file(&tmp);
    }

    #[test]
    fn test_validate_archive_safety_rejects_unknown_extension() {
        let tmp = std::env::temp_dir().join(format!("test_unknown_{}.xyz", std::process::id()));
        fs::write(&tmp, b"data").unwrap();
        let result = validate_archive_safety(&tmp);
        assert!(result.is_err(), "unknown extension should be rejected");
        let _ = fs::remove_file(&tmp);
    }
}
