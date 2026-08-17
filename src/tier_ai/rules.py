from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SpeciesRule:
    """Règle métier minimale pour une espèce."""

    species: str
    breeding_months: set[int] = field(default_factory=set)
    habitat_keywords: set[str] = field(default_factory=set)
    min_contacts_for_reproduction: int = 2
    notes: str = ""


DEFAULT_SPECIES_RULES: dict[str, SpeciesRule] = {
    "amsel": SpeciesRule(
        species="Amsel",
        breeding_months={3, 4, 5, 6, 7},
        habitat_keywords={"gehölz", "gebüsch", "baum", "hecke"},
        min_contacts_for_reproduction=2,
        notes="Gebüsch- und Gehölzart; offene Felder sind als Brutplatz unplausibel.",
    ),
    "blaumeise": SpeciesRule(
        species="Blaumeise",
        breeding_months={3, 4, 5, 6, 7},
        habitat_keywords={"gehölz", "baum", "park", "hecke"},
        min_contacts_for_reproduction=2,
    ),
    "buntspecht": SpeciesRule(
        species="Buntspecht",
        breeding_months={3, 4, 5, 6, 7},
        habitat_keywords={"wald", "baum", "gehölz", "park"},
        min_contacts_for_reproduction=2,
    ),
}


def normalize_species_name(value: str) -> str:
    return value.strip().casefold()


def get_rule(species: str) -> SpeciesRule | None:
    return DEFAULT_SPECIES_RULES.get(normalize_species_name(species))

