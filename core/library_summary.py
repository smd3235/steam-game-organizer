"""Pure-data index of what the library already looks like, in the shape a screen needs to ask it questions.

Built from the metadata walk `CatalogService.generate()` already performs on every scan - see
`CatalogService._retain` - so nothing here costs a second pass over 165 game folders and their sidecars.

Steam's own tags are deliberately absent from this index. `tags` is `[]` on all 165 sidecars and the
`appdetails` API has no such field at all, so anything keyed on it would be keyed on nothing.

Genres are present but weak: eleven coarse values across the whole library, with
`Indie, Simulation, Strategy` dominating, and IGNORED_AUTO_CATEGORIES already discounting five of them.
So `categories_for_genres` answers "where does this genre already live", which is a fact about the
library. It does not answer "which category should this be", which would need evidence this index
does not have, and a display that presents this tally as a strong signal would be overstating it.

`developer` is the one genuinely discriminating field, and it is on all 165 sidecars - but repeats are
rare (Bewolba Studios x3, Allerton Apps x2), so `precedent_for` returning () is the normal answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time


@dataclass(frozen=True)
class LibrarySummary:
    """What the library already looks like, in the shape a screen needs to ask it questions.

    Built from the metadata walk `CatalogService.generate()` already performs on every scan - see
    `CatalogService._retain` - so nothing here costs a second pass over 165 game folders and their sidecars.

    Steam's own tags are deliberately absent from this index. `tags` is `[]` on all 165 sidecars and the
    `appdetails` API has no such field at all, so anything keyed on it would be keyed on nothing.

    Genres are present but weak: eleven coarse values across the whole library, with
    `Indie, Simulation, Strategy` dominating, and IGNORED_AUTO_CATEGORIES already discounting five of them.
    So `categories_for_genres` answers "where does this genre already live", which is a fact about the
    library. It does not answer "which category should this be", which would need evidence this index
    does not have, and a display that presents this tally as a strong signal would be overstating it.

    `developer` is the one genuinely discriminating field, and it is on all 165 sidecars - but repeats are
    rare (Bewolba Studios x3, Allerton Apps x2), so `precedent_for` returning () is the normal answer.
    """

    # (category, game count, total archive bytes), by game count descending then name, so a display can
    # render a ranked list without sorting anything itself.
    categories: tuple[tuple[str, int, int], ...] = ()
    # genre -> category -> count, read off the sidecars. A genre no game carries is not a key here.
    genre_placement: dict[str, dict[str, int]] = field(default_factory=dict)
    # Developer, casefolded -> ((game name, category), ...), only where that developer has 2+ games, because
    # one game is not a precedent. Sorted by name so the order does not depend on the directory walk.
    developer_placement: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    total_games: int = 0
    # time.time() at the build, so a display can say how stale the figures are. 0.0 means never built, which
    # is how "not indexed yet" is told apart from "indexed, and there is nothing" - see `library_summary`.
    built_at: float = 0.0

    @property
    def indexed(self) -> bool:
        """Whether this summary was actually built. False means "not looked yet", not "no categories"."""
        return self.built_at > 0.0

    def categories_for_genres(self, genres) -> tuple[tuple[str, int], ...]:
        """Where these genres already live: (category, games) pairs, most games first.

        The count is summed across the genres asked about, so a category holding three of a game's games'
        genres scores 3. One game carrying two of them is therefore counted once per genre it matched, which
        is deliberate - the question is "how much of this lives here" - but a display wanting the per-genre
        breakdown reads `genre_placement` directly instead of this.

        A genre nobody has is ignored rather than an error: the caller is holding whatever Steam returned for
        a game that may not be in the library at all, and "no category has this genre" is an answer.
        """
        totals = {}
        for genre in genres or ():
            key = str(genre or "").strip()
            # Compared casefolded, so a genre arriving as 'rpg' still finds the 'RPG' the sidecars carry. The
            # keys keep Steam's own capitalisation, because a display prints them; only the comparison is
            # folded. Eleven genres is one pass, and a case-mismatch reported as "nothing here has that" is a
            # wrong answer on a panel whose entire purpose is to say what is already in the library.
            placement = next((counts for name, counts in self.genre_placement.items() if name.casefold() == key.casefold()), {})
            for category, count in placement.items():
                totals[category] = totals.get(category, 0) + int(count)
        return tuple(sorted(totals.items(), key=lambda item: (-item[1], item[0].casefold())))

    def precedent_for(self, developer) -> tuple[tuple[str, str], ...]:
        """The same studio's other games and where they live. () when there is no precedent.

        Keyed casefolded, because the caller holds a developer string out of a Steam match and the sidecars
        are not consistent about capitalisation. No studio, an unknown studio and a studio with exactly one
        game all return () rather than raising: on a library like this all three are ordinary outcomes, and
        only the first is even a mistake.
        """
        return self.developer_placement.get(str(developer or "").strip().casefold(), ())

    @classmethod
    def from_categories(cls, categories, built_at=None):
        """Build the index from one `_collect()` result. Pure: no I/O, no logging, no service state.

        `categories` is the same dict the catalog renders from, so genre, developer and archive size are
        read off dicts that exist either way. The `if games:` guard in `_collect` has already run by the
        time this is called, which is what keeps a directory of loose .rar/.zip files - `Larage Games` on
        the real library - out of the category list rather than a phantom zero-game row in it.
        """
        rows = []
        by_genre = {}
        by_developer = {}
        total = 0
        for category, games in (categories or {}).items():
            games = list(games or ())
            rows.append((category, len(games), sum(int(game.get("archive_size") or 0) for game in games)))
            total += len(games)
            for game in games:
                for value in game.get("genres") or ():
                    genre = str(value or "").strip()
                    if not genre:
                        continue
                    placement = by_genre.setdefault(genre, {})
                    placement[category] = placement.get(category, 0) + 1
                studio = str(game.get("developer") or "").strip()
                if studio:
                    by_developer.setdefault(studio.casefold(), []).append((str(game.get("name") or "").strip(), category))
        precedent = {key: tuple(sorted(found, key=lambda item: (item[0].casefold(), item[1]))) for key, found in by_developer.items() if len(found) >= 2}
        return cls(categories=tuple(sorted(rows, key=lambda row: (-row[1], row[0].casefold()))), genre_placement=by_genre, developer_placement=precedent, total_games=total, built_at=time.time() if built_at is None else float(built_at))
