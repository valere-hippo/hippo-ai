from __future__ import annotations

from collections import defaultdict
from math import hypot
from statistics import mean

from .config import AnalyzerConfig
from .models import AnalysisResult, ClusterSummary, Observation, SpeciesAnalysis
from .rules import SpeciesRule, detect_habitat_compatibility, get_rule, is_bat_rule
from .validation import validate_frame


def analyze_observations(observations: list[Observation], source_path: str, config: AnalyzerConfig | None = None) -> AnalysisResult:
    config = config or AnalyzerConfig()
    grouped: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.species].append(observation)

    species_results: list[SpeciesAnalysis] = []
    for species, items in sorted(grouped.items(), key=lambda pair: pair[0].lower()):
        clusters = _build_clusters(items, config)
        rule = get_rule(species)
        habitat_assessment = _assess_habitat(species, items, rule)
        concentration = _assess_concentration(items, clusters, rule)
        reproduction = _assess_reproduction(items, clusters, rule, habitat_assessment)
        transit_assessment = _assess_transit(species, items, clusters, rule, habitat_assessment)
        summary = _render_species_summary(
            species,
            items,
            clusters,
            concentration,
            habitat_assessment,
            transit_assessment,
            reproduction,
            rule,
        )
        species_results.append(
            SpeciesAnalysis(
                species=species,
                total_observations=len(items),
                clusters=clusters,
                transit_assessment=transit_assessment,
                habitat_assessment=habitat_assessment,
                reproduction_assessment=reproduction,
                concentration_assessment=concentration,
                text_summary=summary,
            )
        )

    return AnalysisResult(source_path=source_path, species_results=species_results)


def _build_clusters(items: list[Observation], config: AnalyzerConfig) -> list[ClusterSummary]:
    if len(items) < config.min_cluster_size:
        return []

    centroids = []
    for obs in items:
        centroid = getattr(obs.geometry, "centroid", None)
        if centroid is None:
            continue
        centroids.append((centroid.x, centroid.y))

    if len(centroids) < config.min_cluster_size:
        return []

    clusters = _connected_components(centroids, config.distance_threshold_m)

    summaries: list[ClusterSummary] = []
    for index, cluster in enumerate(clusters, start=1):
        if len(cluster) < config.min_cluster_size:
            continue
        xs = [point[0] for point in cluster]
        ys = [point[1] for point in cluster]
        summaries.append(
            ClusterSummary(
                label=f"Cluster {index}",
                observation_count=len(cluster),
                centroid_x=mean(xs),
                centroid_y=mean(ys),
                notes=[f"Abstandsschwelle {config.distance_threshold_m:.1f} m"],
            )
        )
    return summaries


def _connected_components(points: list[tuple[float, float]], threshold: float) -> list[list[tuple[float, float]]]:
    if not points:
        return []

    visited: set[int] = set()
    components: list[list[tuple[float, float]]] = []

    for start_index in range(len(points)):
        if start_index in visited:
            continue

        stack = [start_index]
        visited.add(start_index)
        component: list[tuple[float, float]] = []

        while stack:
            current_index = stack.pop()
            current_point = points[current_index]
            component.append(current_point)

            for other_index, other_point in enumerate(points):
                if other_index in visited:
                    continue
                if hypot(current_point[0] - other_point[0], current_point[1] - other_point[1]) <= threshold:
                    visited.add(other_index)
                    stack.append(other_index)

        components.append(component)

    return components


def _render_species_summary(
    species: str,
    items: list[Observation],
    clusters: list[ClusterSummary],
    concentration: str,
    habitat: str,
    transit: str,
    reproduction: str,
    rule: SpeciesRule | None,
) -> str:
    parts = [
        f"Art {species}: {len(items)} Nachweise im Untersuchungsgebiet.",
        f"Bewertung der Verteilung: {concentration}.",
        f"Habitatbewertung: {habitat}.",
        f"Transitbewertung: {transit}.",
        f"Brut-/Reproduktionsbewertung: {reproduction}.",
    ]
    if rule and rule.notes:
        parts.append(rule.notes)
    if clusters:
        parts.append(f"Es wurde {len(clusters)} Konzentrationsbereich(e) erkannt.")
    else:
        parts.append("Es wurde keine belastbare räumliche Häufung erkannt.")
    return " ".join(parts)


def _assess_concentration(items: list[Observation], clusters: list[ClusterSummary], rule: SpeciesRule | None) -> str:
    if not clusters:
        return "keine erkennbare Konzentration"
    if rule:
        return f"{len(clusters)} Konzentrationsbereich(e), Verdacht auf Konzentrationszone bei {rule.species}"
    return f"{len(clusters)} Konzentrationsbereich(e), Verdacht auf Konzentrationszone"


def _assess_habitat(species: str, items: list[Observation], rule: SpeciesRule | None) -> str:
    if rule is None:
        return "unbekannt"

    attrs = {}
    for observation in items:
        attrs.update({str(key): value for key, value in observation.attrs.items()})

    return detect_habitat_compatibility(species, attrs)


def _assess_reproduction(items: list[Observation], clusters: list[ClusterSummary], rule: SpeciesRule | None, habitat_assessment: str) -> str:
    if rule is None:
        return "vorläufig zu prüfen"

    months = {observation.observed_at.month for observation in items if observation.observed_at is not None}
    if not months:
        return "Datum fehlt, daher vorläufig zu prüfen"

    breeding_overlap = months & rule.breeding_months
    if breeding_overlap and len(items) >= rule.min_contacts_for_reproduction and clusters:
        if "eher unplausibel" in habitat_assessment:
            return f"Brutverdacht fraglich für {rule.species}, da das Habitat eher unplausibel wirkt"
        return f"Brutverdacht plausibel für {rule.species}"

    if months.isdisjoint(rule.breeding_months):
        return f"außerhalb der Brutzeit, daher kein belastbarer Brutverdacht für {rule.species}"

    if clusters and len(items) >= rule.min_contacts_for_reproduction:
        return f"Brutverdacht möglich für {rule.species}, aber noch nicht belastbar"

    return "vorläufig zu prüfen"


def _assess_transit(species: str, items: list[Observation], clusters: list[ClusterSummary], rule: SpeciesRule | None, habitat_assessment: str) -> str:
    if not is_bat_rule(species):
        return "für Vogelarten nicht relevant"

    if rule is None:
        return "für Fledermäuse nicht bewertbar"

    attrs_text = " ".join(str(value).casefold() for observation in items for value in observation.attrs.values() if value is not None)
    line_keywords = ("linie", "leit", "hecke", "allee", "weg", "brücke", "straße", "strasse", "gewässer", "ufer")
    has_leitstruktur = any(keyword in attrs_text for keyword in line_keywords)

    if clusters and has_leitstruktur:
        return f"Transit entlang von Leitstrukturen für {rule.species} plausibel"

    if clusters and "plausibel" in habitat_assessment:
        return f"Transit für {rule.species} möglich"

    if len(items) >= rule.min_contacts_for_reproduction:
        return f"Transitdaten für {rule.species} vorhanden, aber noch nicht eindeutig"

    return f"kein belastbarer Transitnachweis für {rule.species}"
