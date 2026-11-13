"""Extracted from core/constants.py.

    CategoryEvidence was moved here during a module split so the original file
    stays under the size threshold. Import it from here instead of defining it
    inline.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryEvidence:
    """Why one category was chosen over the others, so a screen can say why, not only what.

    Frozen, with tuple fields, so it survives the copy.deepcopy() that StateStore.get()
    performs on every state read and cannot be edited once it is attached to a decision.
    Every field is a str, an int, or a tuple of those, which keeps the value JSON-native:
    json.dumps(dataclasses.asdict(evidence)) needs no custom encoder.

    basis is the closed vocabulary a screen reads in one word: "description" when a keyword
    rule won on the title/description text, "tag" when the same rule won on tags or Steam
    categories alone, "genre" when a Steam genre out-scored every rule, "fallback" when
    nothing scored at all and the answer is Unsorted. terms are the keywords that fired, in
    the order they were tested, and are empty for a genre win, where the genre name is the
    reason. runners_up holds at most the next three candidates as (name, score) pairs,
    sorted by score descending then name, so the output is deterministic; a candidate is one
    category, so a category that scored in both passes appears once, with its better score.
    considered counts the candidates that scored above zero, which is how a screen says
    "nothing came close" when it is 0.
    """

    chosen: str
    score: int
    basis: str
    terms: tuple[str, ...] = ()
    runners_up: tuple[tuple[str, int], ...] = ()
    considered: int = 0
