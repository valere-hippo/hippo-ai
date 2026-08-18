from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SpeciesRule:
    """Règle métier minimale pour une espèce."""

    species: str
    taxon_group: str = "bird"
    breeding_months: set[int] = field(default_factory=set)
    habitat_keywords: set[str] = field(default_factory=set)
    min_contacts_for_reproduction: int = 2
    priority_if_breeding: str = "hoch"
    priority_if_transit: str = "mittel"
    priority_if_concentration: str = "mittel"
    priority_default: str = "niedrig"
    notes: str = ""


_RULE_SOURCE: str | None = None


def normalize_species_name(value: str) -> str:
    text = value.strip().casefold()
    text = text.replace("ß", "ss")
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    text = text.replace("Ä", "ae").replace("Ö", "oe").replace("Ü", "ue")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def get_rule(species: str) -> SpeciesRule | None:
    return _rules_for_source(_RULE_SOURCE).get(normalize_species_name(species))


def set_rule_source(rule_source: str | Path | None) -> None:
    global _RULE_SOURCE
    _RULE_SOURCE = str(rule_source) if rule_source is not None else None
    _rules_for_source.cache_clear()


def load_species_rules(rule_source: str | Path | None = None) -> dict[str, SpeciesRule]:
    raw = _load_rule_payload(rule_source)
    rules: dict[str, SpeciesRule] = {}
    for key, value in raw.items():
        rules[normalize_species_name(key)] = _parse_species_rule(value)
    return rules


@lru_cache(maxsize=1)
def _rules_for_source(rule_source: str | None) -> dict[str, SpeciesRule]:
    raw = _load_rule_payload(rule_source)
    rules: dict[str, SpeciesRule] = {}
    for key, value in raw.items():
        rules[normalize_species_name(key)] = _parse_species_rule(value)
    return rules


def _load_rule_payload(rule_source: str | Path | None) -> dict[str, Any]:
    if rule_source is None:
        payload: dict[str, Any] = {}
        data_root = resources.files("tier_ai.data")
        for resource in sorted(
            (child for child in data_root.iterdir() if child.name.startswith("species_rules") and child.suffix == ".json"),
            key=lambda item: item.name,
        ):
            payload.update(json.loads(resource.read_text(encoding="utf-8")))
        return payload

    path = Path(rule_source)
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_species_rule(payload: dict[str, Any]) -> SpeciesRule:
    min_contacts = payload.get("min_contacts_for_reproduction")
    if min_contacts is None:
        min_contacts = payload.get("min_contacts_for_reproduktion", 2)
    return SpeciesRule(
        species=str(payload.get("species", "")).strip(),
        taxon_group=str(payload.get("taxon_group", "bird")).strip().casefold() or "bird",
        breeding_months={int(month) for month in payload.get("breeding_months", [])},
        habitat_keywords={str(keyword).casefold() for keyword in payload.get("habitat_keywords", [])},
        min_contacts_for_reproduction=int(min_contacts),
        priority_if_breeding=str(payload.get("priority_if_breeding", "hoch")).strip().casefold() or "hoch",
        priority_if_transit=str(payload.get("priority_if_transit", "mittel")).strip().casefold() or "mittel",
        priority_if_concentration=str(payload.get("priority_if_concentration", "mittel")).strip().casefold() or "mittel",
        priority_default=str(payload.get("priority_default", "niedrig")).strip().casefold() or "niedrig",
        notes=str(payload.get("notes", "")).strip(),
    )


def is_bat_rule(species: str) -> bool:
    rule = get_rule(species)
    return bool(rule and rule.taxon_group == "bat")


def detect_habitat_compatibility(species: str, attrs: dict[str, object]) -> str:
    rule = get_rule(species)
    if rule is None:
        return "unbekannt"

    haystack = " ".join(str(value).casefold() for value in attrs.values() if value is not None)
    if not haystack.strip():
        return "vorläufig unklar"

    if any(keyword in haystack for keyword in rule.habitat_keywords):
        return f"habitatlich plausibel für {rule.species}"

    return f"habitatlich eher unplausibel für {rule.species}"
