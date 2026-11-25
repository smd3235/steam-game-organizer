//! Service modules: archive, extract, organizer, library, catalog, batch.
//!
//! 2026-11-25: Organized into `services/` folder during Rust conversion.

pub mod archive_service;
pub mod batch_extract_service;
pub mod catalog_service;
pub mod extract_service;
pub mod library_service;
pub mod organizer_service;
pub mod rollback_service;
pub mod setup_service;
