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
        rule = get_rule(species)
        taxon_group = rule.taxon_group if rule else "bird"
        clusters = _build_clusters(items, config, taxon_group)
        habitat_assessment = _assess_habitat(species, items, rule)
        concentration = _assess_concentration(items, clusters, rule)
        reproduction = _assess_reproduction(items, clusters, rule, habitat_assessment)
        transit_assessment = _assess_transit(species, items, clusters, rule, habitat_assessment)
        recommendation = _build_recommendation(
            taxon_group,
            concentration,
            habitat_assessment,
            transit_assessment,
            reproduction,
        )
        priority = _build_priority(rule, taxon_group, concentration, transit_assessment, reproduction)
        summary = _render_species_summary(
            species,
            items,
            clusters,
            concentration,
            habitat_assessment,
            transit_assessment,
            reproduction,
            recommendation,
            priority,
            rule,
        )
        species_results.append(
            SpeciesAnalysis(
                species=species,
                total_observations=len(items),
                taxon_group=taxon_group,
                clusters=clusters,
                transit_assessment=transit_assessment,
                habitat_assessment=habitat_assessment,
                reproduction_assessment=reproduction,
                concentration_assessment=concentration,
                recommendation=recommendation,
                priority=priority,
                text_summary=summary,
            )
        )

    executive_summary = _build_executive_summary(species_results)
    final_conclusion = _build_final_conclusion(species_results, executive_summary)
    return AnalysisResult(
        source_path=source_path,
        species_results=species_results,
        executive_summary=executive_summary,
        final_conclusion=final_conclusion,
    )


def _build_clusters(items: list[Observation], config: AnalyzerConfig, taxon_group: str) -> list[ClusterSummary]:
    min_cluster_size = config.min_cluster_size_for(taxon_group)
    distance_threshold = config.distance_threshold_for(taxon_group)

    if len(items) < min_cluster_size:
        return []

    centroids = []
    for obs in items:
        centroid = getattr(obs.geometry, "centroid", None)
        if centroid is None:
            continue
        centroids.append((centroid.x, centroid.y))

    if len(centroids) < min_cluster_size:
        return []

    clusters = _connected_components(centroids, distance_threshold)

    summaries: list[ClusterSummary] = []
    for index, cluster in enumerate(clusters, start=1):
        if len(cluster) < min_cluster_size:
            continue
        xs = [point[0] for point in cluster]
        ys = [point[1] for point in cluster]
        summaries.append(
            ClusterSummary(
                label=f"Cluster {index}",
                observation_count=len(cluster),
                centroid_x=mean(xs),
                centroid_y=mean(ys),
                notes=[f"Abstandsschwelle {distance_threshold:.1f} m"],
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
    recommendation: str,
    priority: str,
    rule: SpeciesRule | None,
) -> str:
    parts = [
        f"Art {species}: {len(items)} Nachweise im Untersuchungsgebiet.",
        f"Bewertung der Verteilung: {concentration}.",
        f"Habitatbewertung: {habitat}.",
        f"Transitbewertung: {transit}.",
        f"Brut-/Reproduktionsbewertung: {reproduction}.",
        f"Empfehlung: {recommendation}.",
        f"Priorität: {priority}.",
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


def _build_executive_summary(species_results: list[SpeciesAnalysis]) -> str:
    if not species_results:
        return "Keine auswertbaren Nachweise im Untersuchungsgebiet."

    total_observations = sum(result.total_observations for result in species_results)
    species_count = len(species_results)
    clustered_species = sum(1 for result in species_results if result.clusters)
    breeding_species = sum(1 for result in species_results if "Brutverdacht" in result.reproduction_assessment)
    bat_species = sum(1 for result in species_results if result.transit_assessment != "für Vogelarten nicht relevant")

    parts = [
        f"Im Datensatz wurden {total_observations} Nachweise aus {species_count} Arten erfasst.",
        f"Für {clustered_species} Arten wurden räumliche Konzentrationsbereiche erkannt.",
    ]
    if breeding_species:
        parts.append(f"Bei {breeding_species} Arten ergibt sich ein fachlich relevanter Brutverdacht.")
    if bat_species:
        parts.append(f"Für {bat_species} taxonomische Einheiten wurde eine Transitbewertung vorgenommen.")

    return " ".join(parts)


def _build_final_conclusion(species_results: list[SpeciesAnalysis], executive_summary: str) -> str:
    if not species_results:
        return "Mangels auswertbarer Nachweise kann keine fachliche Schlussbewertung abgeleitet werden."

    relevant_breeding = [result.species for result in species_results if "Brutverdacht" in result.reproduction_assessment]
    relevant_transit = [result.species for result in species_results if result.transit_assessment.startswith("Transit")]
    concentrated = [result.species for result in species_results if result.clusters]

    parts = [executive_summary]
    if concentrated:
        parts.append(f"Besonders relevant erscheinen die Arten mit Konzentrationsbereichen: {', '.join(concentrated)}.")
    if relevant_breeding:
        parts.append(f"Ein fachlich vertiefter Brutverdacht liegt insbesondere für {', '.join(relevant_breeding)} vor.")
    if relevant_transit:
        parts.append(f"Für die Fledermausarten {', '.join(relevant_transit)} ist die Transitbewertung zu berücksichtigen.")
    parts.append("Die Ergebnisse sollten fachlich gegengeprüft und bei Bedarf kartografisch ergänzt werden.")
    return " ".join(parts)


def _build_recommendation(
    taxon_group: str,
    concentration: str,
    habitat_assessment: str,
    transit_assessment: str,
    reproduction: str,
) -> str:
    if taxon_group == "bat":
        if transit_assessment.startswith("Transit entlang von Leitstrukturen"):
            return "Leitstrukturen und Quartierbezüge kartografisch prüfen"
        if transit_assessment.startswith("Transit"):
            return "Transitkorridore und strukturgebundene Nutzung prüfen"
        if "Brutverdacht" in reproduction:
            return "Quartier- und Reproduktionshinweise fachlich nachprüfen"
        if "Konzentrationszone" in concentration:
            return "Konzentrationsbereiche und Flugkorridore nachprüfen"
        return "für Fledermäuse derzeit keine vertiefte Maßnahme erforderlich"

    if "Brutverdacht plausibel" in reproduction or "Brutverdacht möglich" in reproduction:
        return "Brutrelevante Strukturen kartografisch und fachlich nachprüfen"
    if "Konzentrationszone" in concentration or "Konzentrationsbereich" in concentration:
        return "Revier- oder Konzentrationsraum kartografisch nachprüfen"
    if "eher unplausibel" in habitat_assessment:
        return "Habitat fachlich plausibilisieren"
    return "derzeit keine vertiefte Maßnahme erforderlich"


def _build_priority(
    rule: SpeciesRule | None,
    taxon_group: str,
    concentration: str,
    transit_assessment: str,
    reproduction: str,
) -> str:
    priority_if_breeding = rule.priority_if_breeding if rule else "hoch"
    priority_if_transit = rule.priority_if_transit if rule else "mittel"
    priority_if_concentration = rule.priority_if_concentration if rule else "mittel"
    priority_default = rule.priority_default if rule else "niedrig"

    if "Brutverdacht plausibel" in reproduction:
        return priority_if_breeding
    if taxon_group == "bat" and transit_assessment.startswith("Transit entlang von Leitstrukturen"):
        return priority_if_breeding
    if "Brutverdacht möglich" in reproduction:
        return priority_if_transit if taxon_group == "bat" else priority_if_concentration
    if taxon_group == "bat" and transit_assessment.startswith("Transit"):
        return priority_if_transit
    if "Konzentrationszone" in concentration or "Konzentrationsbereich" in concentration:
        return priority_if_concentration
    return priority_default
