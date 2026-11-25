//! Pure-data index of what the library already looks like, in the shape a screen needs to ask it
//! questions.
//!
//! Built from the metadata walk `CatalogService.generate()` already performs on every scan - see
//! `CatalogService._retain` - so nothing here costs a second pass over game folders and their
//! sidecars.
//!
//! Steam's own tags are deliberately absent from this index. `tags` is `[]` on all sidecars and the
//! `appdetails` API has no such field at all, so anything keyed on it would be keyed on nothing.
//!
//! Genres are present but weak: eleven coarse values across the whole library, with
//! `Indie, Simulation, Strategy` dominating, and IGNORED_AUTO_CATEGORIES already discounting five of them.
//! So `categories_for_genres` answers "where does this genre already live", which is a fact about the
//! library. It does not answer "which category should this be", which would need evidence this index
//! does not have, and a display that presents this tally as a strong signal would be overstating it.
//!
//! `developer` is the one genuinely discriminating field, and it is on all sidecars - but repeats are
//! rare, so `precedent_for` returning `()` is the normal answer.
//!
//! 2026-11-24: Converted from `core/library_summary.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::time::SystemTime;

/// What the library already looks like, in the shape a screen needs to ask it questions.
///
/// Built from the metadata walk `CatalogService.generate()` already performs on every scan - see
/// `CatalogService._retain` - so nothing here costs a second pass over game folders and their
/// sidecars.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct LibrarySummary {
    /// (category, game count, total archive bytes), by game count descending then name, so a display
    /// can render a ranked list without sorting anything itself.
    pub categories: Vec<(String, u32, u64)>,
    /// genre -> category -> count, read off the sidecars. A genre no game carries is not a key here.
    pub genre_placement: BTreeMap<String, BTreeMap<String, u32>>,
    /// Developer, casefolded -> ((game name, category), ...), only where that developer has 2+ games,
    /// because one game is not a precedent. Sorted by name so the order does not depend on the
    /// directory walk.
    pub developer_placement: BTreeMap<String, Vec<(String, String)>>,
    pub total_games: u32,
    /// SystemTime at the build, so a display can say how stale the figures are. None means never
    /// built, which is how "not indexed yet" is told apart from "indexed, and there is nothing".
    pub built_at: Option<SystemTime>,
}

impl LibrarySummary {
    /// Whether this summary was actually built. `None` means "not looked yet", not "no categories".
    pub fn indexed(&self) -> bool {
        self.built_at.is_some()
    }

    /// Where these genres already live: (category, games) pairs, most games first.
    ///
    /// The count is summed across the genres asked about, so a category holding three of a game's
    /// genres scores 3. One game carrying two of them is therefore counted once per genre it
    /// matched, which is deliberate - the question is "how much of this lives here" - but a display
    /// wanting the per-genre breakdown reads `genre_placement` directly instead of this.
    ///
    /// A genre nobody has is ignored rather than an error: the caller is holding whatever Steam
    /// returned for a game that may not be in the library at all, and "no category has this genre"
    /// is an answer.
    pub fn categories_for_genres(&self, genres: Option<&[String]>) -> Vec<(String, u32)> {
        let mut totals: BTreeMap<String, u32> = BTreeMap::new();
        for genre in genres.unwrap_or(&[]) {
            let key = genre.trim();
            if key.is_empty() {
                continue;
            }
            let placement = self
                .genre_placement
                .iter()
                .find(|(name, _)| name.eq_ignore_ascii_case(key))
                .map(|(_, counts)| counts);
            if let Some(placement) = placement {
                for (category, count) in placement {
                    *totals.entry(category.clone()).or_insert(0) += count;
                }
            }
        }
        let mut result: Vec<(String, u32)> = totals.into_iter().collect();
        result.sort_by(|a, b| {
            b.1.cmp(&a.1)
                .then_with(|| a.0.to_lowercase().cmp(&b.0.to_lowercase()))
        });
        result
    }

    /// The same studio's other games and where they live. `()` when there is no precedent.
    ///
    /// Keyed casefolded, because the caller holds a developer string out of a Steam match and the
    /// sidecars are not consistent about capitalisation. No studio, an unknown studio and a studio
    /// with exactly one game all return `()` rather than raising: on a library like this all three
    /// are ordinary outcomes, and only the first is even a mistake.
    pub fn precedent_for(&self, developer: Option<&str>) -> Vec<(String, String)> {
        let dev = developer.unwrap_or("").trim();
        if dev.is_empty() {
            return Vec::new();
        }
        self.developer_placement
            .get(&dev.to_lowercase())
            .cloned()
            .unwrap_or_default()
    }

    /// Build the index from one `_collect()` result. Pure: no I/O, no logging, no service state.
    ///
    /// `categories` is the same dict the catalog renders from, so genre, developer and archive size
    /// are read off dicts that exist either way.
    pub fn from_categories(
        categories: Option<&BTreeMap<String, Vec<GameSummary>>>,
    ) -> LibrarySummary {
        let mut rows: Vec<(String, u32, u64)> = Vec::new();
        let mut by_genre: BTreeMap<String, BTreeMap<String, u32>> = BTreeMap::new();
        let mut by_developer: BTreeMap<String, Vec<(String, String)>> = BTreeMap::new();
        let mut total: u32 = 0;

        if let Some(categories) = categories {
            for (category, games) in categories {
                let games = games.as_slice();
                let game_count = games.len() as u32;
                let archive_bytes: u64 = games.iter().map(|g| g.archive_size).sum();
                rows.push((category.clone(), game_count, archive_bytes));
                total += game_count;

                for game in games {
                    for genre in &game.genres {
                        let genre = genre.trim();
                        if genre.is_empty() {
                            continue;
                        }
                        let placement = by_genre.entry(genre.to_string()).or_default();
                        *placement.entry(category.clone()).or_insert(0) += 1;
                    }
                    let studio = game.developer.trim();
                    if !studio.is_empty() {
                        by_developer
                            .entry(studio.to_lowercase())
                            .or_default()
                            .push((game.name.clone(), category.clone()));
                    }
                }
            }
        }

        let precedent: BTreeMap<String, Vec<(String, String)>> = by_developer
            .into_iter()
            .filter(|(_, found)| found.len() >= 2)
            .map(|(key, mut found)| {
                found.sort_by(|a, b| {
                    a.0.to_lowercase()
                        .cmp(&b.0.to_lowercase())
                        .then_with(|| a.1.cmp(&b.1))
                });
                (key, found)
            })
            .collect();

        let mut categories_sorted = rows;
        categories_sorted.sort_by(|a, b| {
            b.1.cmp(&a.1)
                .then_with(|| a.0.to_lowercase().cmp(&b.0.to_lowercase()))
        });

        LibrarySummary {
            categories: categories_sorted,
            genre_placement: by_genre,
            developer_placement: precedent,
            total_games: total,
            built_at: Some(SystemTime::now()),
        }
    }
}

/// Minimal game summary input for `LibrarySummary::from_categories`.
///
/// Mirrors the fields read from a game dict: `name`, `category`, `developer`, `genres`,
/// and `archive_size`.
#[derive(Debug, Clone)]
pub struct GameSummary {
    pub name: String,
    pub category: String,
    pub developer: String,
    pub genres: Vec<String>,
    pub archive_size: u64,
}
