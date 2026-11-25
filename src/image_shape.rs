//! JPEG shape detection extracted from artwork_service.
//!
//! Reads JPEG frame headers from the file itself rather than shelling out to ffprobe.
//! Returns true for portrait, false for wide, None when the file cannot be read as a JPEG.
//!
//! 2026-11-25: Converted from `services/image_shape.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

const SOF_MARKERS: [u16; 13] = [
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
];

/// Returns true if the image at path is portrait, false if it is wide, None if it cannot be read as a JPEG.
///
/// Read from the file's own header rather than by shelling out to ffprobe, because that made the answer
/// depend on whether ffmpeg happened to be installed on the machine. It was not: missing ffprobe raised,
/// the failure was caught, and the function returned False - indistinguishable from "wide". Every caller
/// below deletes what it is told is the wrong shape, so on a machine without ffmpeg the cache emptied
/// itself at startup and every portrait download was thrown away the instant it landed. That is why the
/// artwork worked on some machines and not on others. Unknown is now a third answer, and nothing is
/// deleted on it: a cache is cheap to keep and expensive to lose, and an unreadable file is a reason to
/// look again, not to delete.
pub fn image_shape(path: &std::path::Path) -> Option<bool> {
    let data = match std::fs::read(path) {
        Ok(d) => d,
        Err(_) => return None,
    };
    if data.len() < 4 || &data[..2] != [0xFF, 0xD8] {
        return None;
    }
    let mut index: usize = 2;
    while index + 9 < data.len() {
        if data[index] != 0xFF {
            index += 1;
            continue;
        }
        let marker = data[index + 1];
        if marker == 0xD8 || marker == 0x01 || (0xD0..=0xD7).contains(&marker) {
            index += 2;
            continue;
        }
        if marker == 0xD9 || index + 4 > data.len() {
            return None;
        }
        let length = u16::from_be_bytes([data[index + 2], data[index + 3]]) as usize;
        if length < 2 {
            return None;
        }
        if SOF_MARKERS.contains(&(marker as u16)) {
            let height = u16::from_be_bytes([data[index + 5], data[index + 6]]) as u32;
            let width = u16::from_be_bytes([data[index + 7], data[index + 8]]) as u32;
            return Some(
                width > 0 && height > 0 && height > width && width as f64 / (height as f64) < 0.85,
            );
        }
        index += 2 + length;
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_image_shape_nonexistent() {
        assert_eq!(
            image_shape(std::path::Path::new("/nonexistent/path.jpg")),
            None
        );
    }

    #[test]
    fn test_image_shape_not_jpeg() {
        use std::env;
        let temp = env::temp_dir().join(format!("test_not_jpeg_{}.txt", std::process::id()));
        std::fs::write(&temp, b"not a jpeg").ok();
        let result = image_shape(&temp);
        let _ = std::fs::remove_file(&temp);
        assert_eq!(result, None);
    }

    #[test]
    fn test_sof_markers_excludes_dht_jpg_dac() {
        assert!(!SOF_MARKERS.contains(&0xC4));
        assert!(!SOF_MARKERS.contains(&0xC8));
        assert!(!SOF_MARKERS.contains(&0xCC));
    }
}
