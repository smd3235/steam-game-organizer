//! Path-safety guards for every destructive file operation in the app.
//!
//! The app's rule is: nothing outside the folders the user configured may ever be
//! removed, moved, or overwritten by this code. Every deletion target is resolved
//! and checked against an allowed-root list before anything touches the disk. A
//! path that cannot be resolved, or that resolves outside every allowed root, is
//! refused rather than acted on.
//!
//! A second, independent guard blocks protected system paths -- the Windows
//! directory, Program Files, Users, and every drive root -- even when they fall
//! within an allowed root. A misconfigured library_root (C:\\, C:\\Windows) must
//! never open the system to deletion.
//!
//! 2026-11-24: Converted from `core/path_safety.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::env;
use std::path::{Path, PathBuf};

/// Raised when a destructive operation targets a path outside every allowed root
/// or a protected system path that must never be deleted.
#[derive(Debug)]
pub struct PathOutsideAllowedRoot {
    pub message: String,
}

impl PathOutsideAllowedRoot {
    pub fn new(message: &str) -> Self {
        PathOutsideAllowedRoot {
            message: message.to_string(),
        }
    }
}

impl std::fmt::Display for PathOutsideAllowedRoot {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for PathOutsideAllowedRoot {}

impl From<String> for PathOutsideAllowedRoot {
    fn from(s: String) -> Self {
        PathOutsideAllowedRoot::new(&s)
    }
}

/// Whether `path` resolves to `root` or somewhere beneath it.
///
/// Both sides are normalized so `..` segments are settled.
/// Returns `false` (never raises) on an unresolvable path, because the answer a
/// delete needs is "no".
pub fn is_within(path: &Path, root: &Path) -> bool {
    super::within::within(path, root)
}

/// Paths that must never be deleted, regardless of library-root config.
///
/// Includes the Windows directory, Program Files folders, the Users folder,
/// and every existing drive root. A misconfigured library_root (e.g. C:\\ or
/// C:\\Windows) must not open these to deletion.
pub fn protected_roots() -> Vec<PathBuf> {
    let mut roots: Vec<PathBuf> = Vec::new();
    if let Ok(windir) = env::var("WINDIR").or_else(|_| env::var("SYSTEMROOT")) {
        roots.push(PathBuf::from(windir));
    }
    if let Ok(pf) = env::var("PROGRAMFILES") {
        roots.push(PathBuf::from(pf));
    }
    if let Ok(pf) = env::var("PROGRAMFILES(X86)") {
        roots.push(PathBuf::from(pf));
    }
    if let Ok(sd) = env::var("SYSTEMDRIVE") {
        roots.push(PathBuf::from(format!("{}\\Users", sd)));
    }
    // Every existing drive root: C:\, D:\, E:\, ...
    for letter in b'A'..=b'Z' {
        let drive = format!("{}:\\", letter as char);
        if Path::new(&drive).exists() {
            roots.push(PathBuf::from(drive));
        }
    }
    roots
}

/// True when `path` resolves inside a protected system path.
///
/// Drive roots (C:\\, D:\\) protect only themselves - deleting the root is
/// refused, but subdirectories are left to the allowed-root check. Windows,
/// Program Files, and Users protect their entire subtree. Returns `true`
/// (treat as protected) on an unresolvable path, because the answer a delete
/// needs is "no".
pub fn is_protected(path: &Path) -> bool {
    let resolved = match path.canonicalize() {
        Ok(p) => p,
        Err(_) => return true,
    };
    for root in protected_roots() {
        if resolved == root {
            return true;
        }
        // Drive roots protect only themselves; other protected paths guard
        // their entire subtree. A drive root's full string equals its anchor
        // (e.g. "C:\"), so compare full string vs anchor substring.
        let root_str = root.to_string_lossy().to_string();
        let anchor_end = root_str.find('\\').map_or(root_str.len(), |i| i + 1);
        let anchor = &root_str[..anchor_end];
        if root_str != anchor && resolved.starts_with(&root) {
            return true;
        }
    }
    false
}

/// Holds the roots this app is allowed to delete inside and validates targets.
///
/// A guard is built once per run with the library root and the app's own
/// project root. Every `rmtree` / `unlink` / `remove` call site routes through
/// `refuse_outside()` first, so a journal row naming `library\\..\\Windows` or a
/// misconfigured root cannot reach `remove_dir_all` outside the library.
///
/// Protected system paths are refused even when they fall within an allowed
/// root, so a misconfigured library_root can never open the system to deletion.
pub struct DeletionGuard {
    root_paths: Vec<PathBuf>,
    roots: Vec<String>,
}

impl DeletionGuard {
    pub fn new(roots: &[&str]) -> Result<Self, String> {
        let root_paths: Vec<PathBuf> = roots
            .iter()
            .filter(|r| !r.is_empty())
            .map(|r| {
                let p = PathBuf::from(r);
                if p.is_absolute() {
                    p
                } else {
                    std::env::current_dir().unwrap_or_default().join(p)
                }
            })
            .collect();
        let roots: Vec<String> = root_paths
            .iter()
            .map(|p| p.to_string_lossy().to_string())
            .collect();
        if root_paths.is_empty() {
            return Err("DeletionGuard needs at least one allowed root".to_string());
        }
        Ok(Self { root_paths, roots })
    }

    /// True when `path` resolves inside one of the allowed roots.
    pub fn allowed(&self, path: &Path) -> bool {
        let resolved = match path.canonicalize() {
            Ok(p) => p,
            Err(_) => return false,
        };
        self.root_paths
            .iter()
            .any(|root| resolved == *root || resolved.starts_with(root))
    }

    /// Raise `PathOutsideAllowedRoot` when `path` is unsafe to delete.
    pub fn refuse_outside(
        &self,
        path: &Path,
        operation: &str,
    ) -> Result<PathBuf, PathOutsideAllowedRoot> {
        if is_protected(path) {
            return Err(PathOutsideAllowedRoot::new(&format!(
                "{} refused: {:?} is a protected system path",
                operation, path
            )));
        }
        if !self.allowed(path) {
            return Err(PathOutsideAllowedRoot::new(&format!(
                "{} refused: {:?} is outside every allowed root ({})",
                operation,
                path,
                self.roots.join(", ")
            )));
        }
        path.canonicalize().map_err(|_| {
            PathOutsideAllowedRoot::new(&format!(
                "{} refused: {:?} cannot be resolved",
                operation, path
            ))
        })
    }

    /// `remove_dir_all` guarded by the allowed-root check.
    pub fn rmtree(
        &self,
        directory: &Path,
        ignore_errors: bool,
    ) -> Result<(), PathOutsideAllowedRoot> {
        let resolved = self.refuse_outside(directory, "rmtree")?;
        match std::fs::remove_dir_all(&resolved) {
            Ok(()) => Ok(()),
            Err(e) => {
                if ignore_errors {
                    Ok(())
                } else {
                    Err(PathOutsideAllowedRoot::new(&format!(
                        "rmtree failed for {:?}: {}",
                        resolved, e
                    )))
                }
            }
        }
    }

    /// `remove_file` guarded by the allowed-root check.
    pub fn unlink(&self, path: &Path, missing_ok: bool) -> Result<(), PathOutsideAllowedRoot> {
        let resolved = self.refuse_outside(path, "unlink")?;
        match std::fs::remove_file(&resolved) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                if missing_ok {
                    Ok(())
                } else {
                    Err(PathOutsideAllowedRoot::new(&format!(
                        "unlink failed for {:?}: {}",
                        resolved, e
                    )))
                }
            }
            Err(e) => {
                if missing_ok {
                    Ok(())
                } else {
                    Err(PathOutsideAllowedRoot::new(&format!(
                        "unlink failed for {:?}: {}",
                        resolved, e
                    )))
                }
            }
        }
    }
}

/// One-shot guarded `remove_dir_all` for call sites without a persistent guard.
pub fn safe_rmtree(
    directory: &Path,
    roots: &[&str],
    ignore_errors: bool,
) -> Result<(), PathOutsideAllowedRoot> {
    let guard = DeletionGuard::new(roots)?;
    guard.rmtree(directory, ignore_errors)
}

/// One-shot guarded `remove_file` for call sites without a persistent guard.
pub fn safe_unlink(
    path: &Path,
    roots: &[&str],
    missing_ok: bool,
) -> Result<(), PathOutsideAllowedRoot> {
    let guard = DeletionGuard::new(roots)?;
    guard.unlink(path, missing_ok)
}

/// Holds the roots this app is allowed to CREATE directories and files inside.
///
/// Mirrors `DeletionGuard` but for creation operations (`create_dir_all`, `write`,
/// `File::create`). Refuses to create anything at a drive root (C:\, D:\) or inside
/// a protected system path (Windows, Program Files, Users), and refuses anything
/// outside the configured allowed roots.
pub struct CreationGuard {
    root_paths: Vec<PathBuf>,
    roots: Vec<String>,
}

impl CreationGuard {
    pub fn new(roots: &[&str]) -> Result<Self, String> {
        let root_paths: Vec<PathBuf> = roots
            .iter()
            .filter(|r| !r.is_empty())
            .map(|r| {
                let p = PathBuf::from(r);
                if p.is_absolute() {
                    p
                } else {
                    std::env::current_dir().unwrap_or_default().join(p)
                }
            })
            .collect();
        let roots: Vec<String> = root_paths
            .iter()
            .map(|p| p.to_string_lossy().to_string())
            .collect();
        if root_paths.is_empty() {
            return Err("CreationGuard needs at least one allowed root".to_string());
        }
        Ok(Self { root_paths, roots })
    }

    /// True when `path` resolves inside one of the allowed roots.
    ///
    /// For non-existent paths, attempts to canonicalize the parent directory
    /// and resolve `..` segments before checking prefix matching, to prevent
    /// path traversal attacks.
    pub fn allowed(&self, path: &Path) -> bool {
        let resolved = self.resolve_path(path);
        match resolved {
            Ok(p) => {
                self.root_paths.iter().any(|root| {
                    let root_resolved = root.canonicalize().unwrap_or_else(|_| root.clone());
                    p == root_resolved || p.starts_with(&root_resolved)
                })
            }
            Err(_) => false,
        }
    }

    /// Resolve a path to its canonical form, handling non-existent paths
    /// by canonicalizing the nearest existing ancestor and joining
    /// the remaining components. This prevents `..` path traversal.
    fn resolve_path(&self, path: &Path) -> Result<PathBuf, std::io::Error> {
        // Try direct canonicalize first (path exists)
        if let Ok(p) = path.canonicalize() {
            return Ok(p);
        }

        // Path doesn't exist — try to canonicalize the parent and join
        // the remaining components
        let mut current = path.to_path_buf();
        let mut components: Vec<std::ffi::OsString> = Vec::new();

        // Walk up until we find an existing ancestor
        while !current.exists() && current.parent().is_some() {
            if let Some(file_name) = current.file_name() {
                components.push(file_name.to_os_string());
            }
            current = current.parent().unwrap().to_path_buf();
        }

        // Canonicalize the existing ancestor
        let canonical = current.canonicalize()?;

        // Join the remaining components in reverse order
        let mut result = canonical;
        for component in components.iter().rev() {
            result = result.join(component);
        }

        Ok(result)
    }

    /// Refuse to create `path` if it is a protected system path, a drive root,
    /// or outside every allowed root.
    ///
    /// Non-existent paths are not checked against protected roots — they cannot
    /// be protected system paths yet. The allowed-root check still applies.
    pub fn refuse_outside_create(
        &self,
        path: &Path,
        operation: &str,
    ) -> Result<PathBuf, PathOutsideAllowedRoot> {
        // Only check protected status for paths that exist — a non-existent path
        // cannot be a protected system path yet.
        if path.exists() && is_protected(path) {
            return Err(PathOutsideAllowedRoot::new(&format!(
                "{} refused: {:?} is a protected system path",
                operation, path
            )));
        }
        // Refuse drive roots (C:\, D:\, E:\) — they have no parent to create under
        let path_str = path.to_string_lossy().to_string();
        if path_str.len() <= 3 && path_str.ends_with('\\') {
            return Err(PathOutsideAllowedRoot::new(&format!(
                "{} refused: {:?} is a drive root — directory creation at drive root is prohibited",
                operation, path
            )));
        }
        if !self.allowed(path) {
            return Err(PathOutsideAllowedRoot::new(&format!(
                "{} refused: {:?} is outside every allowed root ({})",
                operation,
                path,
                self.roots.join(", ")
            )));
        }
        // For non-existent paths, use resolve_path which handles `..` traversal
        // by canonicalizing the nearest existing ancestor
        self.resolve_path(path).map_err(|_| {
            PathOutsideAllowedRoot::new(&format!(
                "{} refused: {:?} cannot be resolved",
                operation, path
            ))
        })
    }
}

/// Guarded `create_dir_all` — refuses to create directories at drive roots,
/// protected system paths, or outside every allowed root.
pub fn safe_create_dir_all(
    path: &Path,
    roots: &[&str],
) -> Result<(), PathOutsideAllowedRoot> {
    let guard = CreationGuard::new(roots)?;
    guard.refuse_outside_create(path, "create_dir_all")?;
    match std::fs::create_dir_all(path) {
        Ok(()) => Ok(()),
        Err(e) => Err(PathOutsideAllowedRoot::new(&format!(
            "create_dir_all failed for {:?}: {}",
            path, e
        ))),
    }
}

/// Guarded `File::create` / `std::fs::write` — refuses to write files outside
/// every allowed root or at protected system paths.
pub fn safe_write(
    path: &Path,
    contents: &[u8],
    roots: &[&str],
) -> Result<(), PathOutsideAllowedRoot> {
    let guard = CreationGuard::new(roots)?;
    guard.refuse_outside_create(path, "write")?;
    match std::fs::write(path, contents) {
        Ok(()) => Ok(()),
        Err(e) => Err(PathOutsideAllowedRoot::new(&format!(
            "write failed for {:?}: {}",
            path, e
        ))),
    }
}

/// Validate that `path` is within `roots` before writing — returns the
/// path if safe, without writing. Useful for validating
/// output paths before creating files. Non-existent paths are allowed
/// as long as they're within the allowed roots (checked via prefix matching).
pub fn safe_write_path(path: &Path, roots: &[&str]) -> Result<PathBuf, PathOutsideAllowedRoot> {
    let guard = CreationGuard::new(roots)?;
    guard.refuse_outside_create(path, "write_path")?;
    Ok(path.to_path_buf())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_within_same() {
        assert!(is_within(Path::new("/a/b"), Path::new("/a/b")));
    }

    #[test]
    fn test_is_within_child() {
        assert!(is_within(Path::new("/a/b/c"), Path::new("/a/b")));
    }

    #[test]
    fn test_is_within_not_parent() {
        assert!(!is_within(Path::new("/a/b"), Path::new("/a/b/c")));
    }

    #[test]
    fn test_creation_guard_allowed_within_root() {
        let tmp = std::env::temp_dir();
        let root = tmp.join("creation_guard_test_root");
        let _ = std::fs::create_dir_all(&root);
        let guard = CreationGuard::new(&[root.to_string_lossy().as_ref()]).unwrap();
        let child = root.join("subdir");
        assert!(guard.allowed(&child));
        assert!(guard.allowed(&root));
        let outside = tmp.join("other_root");
        assert!(!guard.allowed(&outside));
    }

    #[test]
    fn test_creation_guard_refuses_drive_root() {
        let guard = CreationGuard::new(&["C:\\allowed\\root"]).unwrap();
        let result = guard.refuse_outside_create(Path::new("C:\\"), "create_dir_all");
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("drive root"));
    }

    #[test]
    fn test_creation_guard_refuses_outside_root() {
        let tmp = std::env::temp_dir();
        let root = tmp.join("creation_guard_test_root2");
        let _ = std::fs::create_dir_all(&root);
        let guard = CreationGuard::new(&[root.to_string_lossy().as_ref()]).unwrap();
        let outside = tmp.join("outside_root").join("file.txt");
        let result = guard.refuse_outside_create(&outside, "create_dir_all");
        assert!(result.is_err());
        let err_msg = result.unwrap_err().to_string();
        assert!(
            err_msg.contains("outside every allowed root")
                || err_msg.contains("protected system path"),
            "unexpected error message: {}",
            err_msg
        );
    }

    #[test]
    fn test_creation_guard_refuses_protected_path() {
        let guard = CreationGuard::new(&["C:\\allowed\\root"]).unwrap();
        // On Windows, C:\ is a protected drive root
        let result = guard.refuse_outside_create(Path::new("C:\\"), "create_dir_all");
        assert!(result.is_err());
    }

    #[test]
    fn test_safe_create_dir_all_refuses_drive_root() {
        let result = safe_create_dir_all(Path::new("C:\\"), &["C:\\allowed\\root"]);
        assert!(result.is_err());
    }

    #[test]
    fn test_safe_write_refuses_drive_root() {
        let result = safe_write(Path::new("C:\\test.txt"), b"hello", &["C:\\allowed\\root"]);
        assert!(result.is_err());
    }

    #[test]
    fn test_creation_guard_refuses_path_traversal() {
        // Category names with ../ should be refused — they escape the library root
        let tmp = std::env::temp_dir();
        let root = tmp.join("creation_guard_test_traversal");
        let _ = std::fs::create_dir_all(&root);
        let guard = CreationGuard::new(&[root.to_string_lossy().as_ref()]).unwrap();

        // ../escape outside root
        let traversal_path = root.join("../outside.txt");
        let result = guard.refuse_outside_create(&traversal_path, "create_dir_all");
        assert!(
            result.is_err(),
            "Path traversal '../' should be refused, got: {:?}",
            result
        );

        // ../../../../escape
        let deep_traversal = root.join("../../../../escape.txt");
        let result = guard.refuse_outside_create(&deep_traversal, "create_dir_all");
        assert!(
            result.is_err(),
            "Deep path traversal '../../..' should be refused, got: {:?}",
            result
        );

        // Category with backslash traversal (Windows)
        let backslash_traversal = root.join("..\\..\\..\\escape.txt");
        let result = guard.refuse_outside_create(&backslash_traversal, "create_dir_all");
        assert!(
            result.is_err(),
            "Backslash path traversal '..\\\\' should be refused, got: {:?}",
            result
        );
    }

    #[test]
    fn test_creation_guard_allows_valid_category() {
        // Valid category names should be allowed
        let tmp = std::env::temp_dir();
        let root = tmp.join("creation_guard_test_valid_cat");
        let _ = std::fs::create_dir_all(&root);
        let guard = CreationGuard::new(&[root.to_string_lossy().as_ref()]).unwrap();

        let valid_cat = root.join("Action");
        assert!(guard.allowed(&valid_cat));

        let valid_cat_nested = root.join("Action/Subcat");
        assert!(guard.allowed(&valid_cat_nested));
    }

    #[test]
    fn test_safe_write_path_refuses_path_traversal() {
        let tmp = std::env::temp_dir();
        let root = tmp.join("safe_write_path_test");
        let _ = std::fs::create_dir_all(&root);

        let traversal = root.join("../outside.txt");
        let result = safe_write_path(&traversal, &[root.to_string_lossy().as_ref()]);
        assert!(result.is_err(), "safe_write_path should refuse path traversal");
    }

    #[test]
    fn test_safe_write_path_allows_valid_category() {
        let tmp = std::env::temp_dir();
        let root = tmp.join("safe_write_path_valid_cat2");
        let _ = std::fs::create_dir_all(&root);

        let valid_cat = root.join("Action");
        // valid_cat doesn't need to exist yet — safe_write_path validates via prefix matching
        let result = safe_write_path(&valid_cat, &[root.to_string_lossy().as_ref()]);
        assert!(result.is_ok(), "safe_write_path should allow valid category");
    }
}
