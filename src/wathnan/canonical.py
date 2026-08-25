"""Resolve the many spellings of a person's name to one canonical form.

Feeds disagree about how much of a name to print: Sporting Life abbreviates a
trainer to ``W J Haggas`` while the circulated report says ``William Haggas``,
and France Galop shouts ``A.DE MIEULLE``.  Rather than list every variant, a
name resolves to a canonical entry when it shares a **surname and a first
initial** with exactly one of them -- so a new abbreviation of a known person
needs no change to the registry.

Ambiguity is never guessed at: if a surname and initial match two canonical
names, the incoming spelling is left alone.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .models import normalise_key
from .normalise import collapse_space, title_name

REGISTRY_PATH = Path(__file__).resolve().parent / "data" / "people.json"

#: Tokens that are an initial rather than a forename: "W", "W.", "J-P".
INITIAL = re.compile(r"^[A-Za-z](?:[.\-][A-Za-z])*\.?$")
#: Lower-case particles that belong to the surname, not the forenames.
PARTICLES = {"de", "van", "von", "der", "den", "du", "la", "le", "di", "da",
             "el", "al", "des", "dos", "ter", "of"}


class Registry:
    """Canonical names for one role, indexed for surname/initial matching."""

    def __init__(self, names: list[str], aliases: dict[str, str]) -> None:
        self.names = list(names)
        self.aliases = {normalise_key(k): v for k, v in aliases.items()}
        self._exact = {normalise_key(name): name for name in names}
        self._by_surname: dict[tuple[str, str], list[str]] = {}
        for name in names:
            forenames, surname = _split_name(name)
            if not surname:
                continue
            initial = forenames[0][0].lower() if forenames else ""
            self._by_surname.setdefault((surname, initial), []).append(name)

    def resolve(self, name: str) -> str:
        """Return the canonical spelling of ``name``, or ``name`` tidied up."""
        tidy = title_name(name)
        if not tidy:
            return ""
        key = normalise_key(tidy)
        if key in self.aliases:
            return self.aliases[key]
        if key in self._exact:
            return self._exact[key]

        forenames, surname = _split_name(tidy)
        if not surname:
            return tidy
        initial = forenames[0][0].lower() if forenames else ""
        matches = self._by_surname.get((surname, initial), [])
        if len(matches) == 1:
            return matches[0]
        # A bare surname resolves too, when only one canonical name carries it.
        if not forenames:
            flat = [name
                    for (candidate, _), names in self._by_surname.items()
                    if candidate == surname
                    for name in names]
            if len(flat) == 1:
                return flat[0]
        return tidy


def _split_name(name: str) -> tuple[list[str], str]:
    """Split into forenames/initials and a normalised surname key.

    ``W J Haggas`` -> ``(["W", "J"], "haggas")``;
    ``Hamad Al-Jehani`` -> ``(["Hamad"], "aljehani")``;
    ``A. de Mieulle`` -> ``(["A."], "demieulle")``.
    """
    tokens: list[str] = []
    for token in collapse_space(name).split(" "):
        if not token:
            continue
        # Slug-derived forms glue initials to the surname: "K-R-Burke".
        while True:
            head, _, tail = token.partition("-")
            if tail and len(head) == 1 and len(tail) > 1:
                tokens.append(head)
                token = tail
                continue
            tokens.append(token)
            break
    if not tokens:
        return [], ""
    # Walk forward over initials and forenames; the surname is what remains
    # once a particle or the final token is reached.
    index = 0
    while index < len(tokens) - 1:
        token = tokens[index]
        if token.lower() in PARTICLES:
            break
        # A second full forename still belongs to the given names, but a
        # particle or the last token starts the surname.
        if index and not INITIAL.match(token) and index + 1 < len(tokens):
            index += 1
            continue
        index += 1
    return tokens[:index], normalise_key(" ".join(tokens[index:]))


@lru_cache(maxsize=1)
def _registries() -> tuple[Registry, Registry]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    aliases = data.get("aliases", {})
    return (Registry(data.get("trainers", []), aliases),
            Registry(data.get("jockeys", []), aliases))


def canonical_trainer(name: str) -> str:
    return _registries()[0].resolve(name)


def canonical_jockey(name: str) -> str:
    return _registries()[1].resolve(name)
