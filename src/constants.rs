//! Constants shared across the app, each with the reason it exists written beside it.
//!
//! `APP_NAME`, `ENTRY_POINT` and `USER_AGENT` identify the app; `ARCHIVE_EXTENSIONS`
//! is what the scanner treats as a game; `NO_WINDOW` keeps bundled 7z from flashing a
//! console; `DEFAULT_CATEGORIES` is the starting set the review screen can file under;
//! `LOCK_MARKER`, `PROCESSING_DIRNAME` and the `TEMP_*` names mark in-flight conversion
//! work so a scan never offers a half-built archive as a game; `COMPRESSION_LEVEL` and
//! friends tune 7-Zip against real memory headroom.
//!
//! `CategoryEvidence` was moved to `src/category_evidence.rs`.
//! `suggest_category_with_evidence` was moved to `src/suggest_category_with_evidence.rs`.
//!
//! 2026-11-24: Converted from `core/constants.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::collections::HashMap;

pub const APP_NAME: &str = "Steam Game Organizer";
pub const ENTRY_POINT: &str = "steam_game_organizer.py";
pub const USER_AGENT: &str = APP_NAME;
pub const ARCHIVE_EXTENSIONS: [&str; 3] = [".zip", ".rar", ".7z"];
/// On Windows, pass this to subprocess creation so that console applications
/// (7z.exe etc.) don't flash a CMD window when the app itself runs windowed.
pub const NO_WINDOW: u32 = 0x00000008; // CREATE_NO_WINDOW

pub const DEFAULT_CATEGORIES: [&str; 11] = [
    "Action", "Adventure", "Casual", "Automation", "Idle", "Management", "RPG", "Simulation",
    "Strategy", "Survival", "Unsorted",
];

pub const SUPPLEMENTAL_CATEGORIES: [&str; 34] = [
    "Roguelike", "Soulslike", "Tidy Up", "Cozy", "Bullet Heaven", "Metroidvania", "Platformer",
    "First-Person Shooter", "Third-Person Shooter", "Fighting", "Horror", "Puzzle", "Tower Defense",
    "Deckbuilding", "Card Game", "Turn-Based", "Tactical", "Stealth", "Sandbox", "Open World",
    "Exploration", "Walking Sim", "Life Sim", "Tycoon", "Shop Management", "City Builder", "Fishing",
    "Cooking", "Farming", "Crafting", "Party Game", "Local Co-op", "Rhythm", "Visual Novel",
];

/// Category aliases map alternative spellings to canonical categories.
pub const CATEGORY_ALIASES: [(&str, &str); 56] = [
    ("factory", "Automation"),
    ("factory sim", "Automation"),
    ("automation", "Automation"),
    ("city builder", "City Builder"),
    ("city sim", "City Builder"),
    ("sim city", "City Builder"),
    ("city-building", "City Builder"),
    ("citybuilder", "City Builder"),
    ("town builder", "City Builder"),
    ("town sim", "City Builder"),
    ("colony sim", "City Builder"),
    ("colony builder", "City Builder"),
    ("rogue", "Roguelike"),
    ("roguelike", "Roguelike"),
    ("roguelite", "Roguelike"),
    ("rogue-like", "Roguelike"),
    ("rogue-lite", "Roguelike"),
    ("roguelikes", "Roguelike"),
    // "Survival" is the block-crafting one - gather, craft, build a base, try not to starve.
    // "Bullet Heaven" is the horde auto-shooter one - a horde closing in, auto-attacks, dodge
    // everything. They are different genres and stay apart; only the confusingly named "Survivors"
    // entry is folded into "Survival", because that is the same genre under a second name and two
    // names for one genre is how games end up in two folders.
    ("survivors", "Survival"),
    ("survivor", "Survival"),
    ("survival game", "Survival"),
    ("survival crafting", "Survival"),
    ("survival sim", "Survival"),
    ("voxel", "Survival"),
    ("horde auto-shooter", "Bullet Heaven"),
    ("horde-auto-shooter", "Bullet Heaven"),
    ("horde shooter", "Bullet Heaven"),
    ("bullet hell survivor", "Bullet Heaven"),
    ("bullet-heaven", "Bullet Heaven"),
    ("bullet heaven survivors", "Bullet Heaven"),
    // Every word this one has been filed under, including the category's own previous name. A saved
    // decision or a Steam genre that says "Cleanup" has to keep landing in the same folder, or
    // eleven tidy-up games silently split off into a folder the picker no longer offers.
    ("cleanup", "Tidy Up"),
    ("clean up", "Tidy Up"),
    ("clean-up", "Tidy Up"),
    ("tidy up", "Tidy Up"),
    ("tidy-up", "Tidy Up"),
    ("tiding", "Tidy Up"),
    ("tidying", "Tidy Up"),
    ("decluttering", "Tidy Up"),
    ("souls-like", "Soulslike"),
    ("soulslike", "Soulslike"),
    ("tower defence", "Tower Defense"),
    ("turn based", "Turn-Based"),
    ("deck builder", "Deckbuilding"),
    ("deck-building", "Deckbuilding"),
    ("fps", "First-Person Shooter"),
    ("third person shooter", "Third-Person Shooter"),
    ("walking simulator", "Walking Sim"),
    ("life simulation", "Life Sim"),
    ("farming simulation", "Farming"),
    ("management sim", "Management"),
    ("idle", "Idle"),
    ("idle game", "Idle"),
    ("clicker", "Idle"),
    ("clicker game", "Idle"),
    ("incremental", "Idle"),
    ("incremental game", "Idle"),
];

/// Categories that carry no scoring weight for auto-categorization.
pub const IGNORED_AUTO_CATEGORIES: [&str; 9] = [
    "indie", "early access", "free to play", "multiplayer", "single-player", "single player",
    "online co-op", "co-op", "massively multiplayer",
];

/// Marker file written into a repack folder recording the owning process, so an abandoned
/// extraction can be told apart from one a conversion is still writing into.
pub const LOCK_MARKER: &str = ".organizer-lock";

/// Where in-flight conversions are built. Staging outside the game folders makes a converted
/// game folder hold exactly one thing at all times: its source, untouched, until the replacement
/// is verified and moved in. The rename is still atomic because this lives under the same library
/// root, i.e. the same filesystem.
pub const PROCESSING_DIRNAME: &str = "Processing";

/// Directories the library owns for its own bookkeeping and never treats as game categories.
pub const LIBRARY_RESERVED_DIRS: [&str; 2] = ["Archive", PROCESSING_DIRNAME];

/// Names for the app's own in-flight work, wherever it happens to be written.
pub const TEMP_DIR_PREFIX: &str = ".organizer-repack-";
pub const TEMP_FILE_TAG: &str = ".organizer-temp";

/// 7z compression level ceiling for rebuilt archives, and the floor the adaptive step-down
/// will not go below.
pub const COMPRESSION_LEVEL: u32 = 9;
pub const MIN_COMPRESSION_LEVEL: u32 = 5;

/// Peak RSS measured for each level on a 354 MB extraction. Usage tracks the LZMA2 dictionary
/// almost linearly, which is why 8 and 9 cost the same: both use a 64 MB dictionary, and 9
/// squeezes more.
pub const LEVEL_RAM_BYTES: [u64; 5] = [
    2561 * 1024 * 1024, // 9
    2561 * 1024 * 1024, // 8
    1400 * 1024 * 1024, // 7
    702 * 1024 * 1024,  // 6
    400 * 1024 * 1024,  // 5
];

/// Memory held back for the desktop even when it looks free, so a repack cannot starve the
/// session it is running inside. Also the threshold below which existing swap pressure forces
/// a step down.
pub const RAM_HEADROOM_BYTES: u64 = 768 * 1024 * 1024;

/// Thread count for the compressor. Each 7z thread holds its own match finder, so the default
/// thread count multiplies the level's memory cost. Two keeps a multi-hour unattended run
/// predictable.
pub const COMPRESSION_THREADS: u32 = 2;

/// The default password for WinZip AES-encrypted game zips in this library. Every archive that
/// ships password-protected uses the same value, so it lives here in one place instead of being
/// spelled out in archive_service.py, organizer_service.py, controller.py, and the repair tools.
pub const DEFAULT_ZIP_PASSWORD: &str = "123";

/// Build a lookup map from CATEGORY_ALIASES for canonical_category().
pub fn category_aliases_map() -> HashMap<&'static str, &'static str> {
    CATEGORY_ALIASES.iter().copied().collect()
}
