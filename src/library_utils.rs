//! Pure utility functions extracted from LibraryService.
//!
//! These functions have no dependency on LibraryService instance state and can be
//! imported and tested independently.
//!
//! 2026-11-24: Converted from `core/library_utils.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::path::Path;

use crate::constants::ENTRY_POINT;

/// True when this folder is the app's own project folder rather than a game category.
pub fn is_app_folder(folder: &Path) -> bool {
    if folder.join(ENTRY_POINT).is_file() {
        return true;
    }
    folder.join("python.exe").is_file()
        && folder
            .parent()
            .is_some_and(|p| p.join(ENTRY_POINT).is_file())
}

/// Whether a game subfolder holds only things this app wrote there.
pub fn game_folder_is_prunable(folder: &Path) -> bool {
    let entries = match folder.read_dir() {
        Ok(e) => e,
        Err(_) => return false,
    };
    for item in entries.flatten() {
        let path = item.path();
        if path.is_symlink() || !path.is_file() {
            return false;
        }
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
        if RECOGNISED_FOLDER_FILES.contains(&name) {
            continue;
        }
        if IGNORED_FILES_IN_SWEEP.contains(&name) {
            continue;
        }
        let is_image = RECOGNISED_IMAGE_SUFFIXES.iter().any(|s| {
            path.extension()
                .and_then(|e| e.to_str())
                .is_some_and(|ext| ext.eq_ignore_ascii_case(s))
        });
        let has_underscore = path
            .file_stem()
            .and_then(|s| s.to_str())
            .is_some_and(|s| s.contains('_'));
        if is_image && has_underscore {
            continue;
        }
        return false;
    }
    true
}

/// Files this app writes into an organized game folder, by exact name.
pub const RECOGNISED_FOLDER_FILES: &[&str] = &[
    ".game-info.json",
    "Open Steam Page.html",
    "Open Steam Page.desktop",
    "Open Steam Page in Chrome.desktop",
    "Open Steam Page (Steam Deck).desktop",
];

/// Artwork, by suffix rather than by the exact name it was written under.
pub const RECOGNISED_IMAGE_SUFFIXES: &[&str] = &[".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"];

/// Syncthing leftovers, matched by name.
pub const IGNORED_FILES_IN_SWEEP: &[&str] = &[
    "Thumbs.db",
    "ehthumbs_vista.db",
    ".DS_Store",
    "desktop.ini",
    "Thumbs",
    "folder.jpg",
    "folder.jpeg",
    "folder.png",
    "folder.webp",
    "folder.gif",
    "folder.bmp",
    "folder.tif",
    "folder.tiff",
    "Folder.jpg",
    "Folder.jpeg",
    "Folder.png",
    "Folder.webp",
    "Folder.gif",
    "Folder.bmp",
    "Folder.tif",
    "Folder.tiff",
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
    "cover.webp",
    "cover.gif",
    "cover.bmp",
    "cover.tif",
    "cover.tiff",
    "Cover.jpg",
    "Cover.jpeg",
    "Cover.png",
    "Cover.webp",
    "Cover.gif",
    "Cover.bmp",
    "Cover.tif",
    "Cover.tiff",
    "label.jpg",
    "label.jpeg",
    "label.png",
    "label.webp",
    "label.gif",
    "label.bmp",
    "label.tif",
    "label.tiff",
    "Label.jpg",
    "Label.jpeg",
    "Label.png",
    "Label.webp",
    "Label.gif",
    "Label.bmp",
    "Label.tif",
    "Label.tiff",
    "banner.jpg",
    "banner.jpeg",
    "banner.png",
    "banner.webp",
    "banner.gif",
    "banner.bmp",
    "banner.tif",
    "banner.tiff",
    "Banner.jpg",
    "Banner.jpeg",
    "Banner.png",
    "Banner.webp",
    "Banner.gif",
    "Banner.bmp",
    "Banner.tif",
    "Banner.tiff",
    "thumb.jpg",
    "thumb.jpeg",
    "thumb.png",
    "thumb.webp",
    "thumb.gif",
    "thumb.bmp",
    "thumb.tif",
    "thumb.tiff",
    "Thumb.jpg",
    "Thumb.jpeg",
    "Thumb.png",
    "Thumb.webp",
    "Thumb.gif",
    "Thumb.bmp",
    "Thumb.tif",
    "Thumb.tiff",
    "thumbnail.jpg",
    "thumbnail.jpeg",
    "thumbnail.png",
    "thumbnail.webp",
    "thumbnail.gif",
    "thumbnail.bmp",
    "thumbnail.tif",
    "thumbnail.tiff",
    "Thumbnail.jpg",
    "Thumbnail.jpeg",
    "Thumbnail.png",
    "Thumbnail.webp",
    "Thumbnail.gif",
    "Thumbnail.bmp",
    "Thumbnail.tif",
    "Thumbnail.tiff",
    "art.jpg",
    "art.jpeg",
    "art.png",
    "art.webp",
    "art.gif",
    "art.bmp",
    "art.tif",
    "art.tiff",
    "Art.jpg",
    "Art.jpeg",
    "Art.png",
    "Art.webp",
    "Art.gif",
    "Art.bmp",
    "Art.tif",
    "Art.tiff",
    "poster.jpg",
    "poster.jpeg",
    "poster.png",
    "poster.webp",
    "poster.gif",
    "poster.bmp",
    "poster.tif",
    "poster.tiff",
    "Poster.jpg",
    "Poster.jpeg",
    "Poster.png",
    "Poster.webp",
    "Poster.gif",
    "Poster.bmp",
    "Poster.tif",
    "Poster.tiff",
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_app_folder_no_entry_point() {
        assert!(!is_app_folder(Path::new("/tmp")));
    }
}
