from __future__ import annotations

from collections import defaultdict
from math import hypot
from statistics import mean

from .config import AnalyzerConfig
from .models import AnalysisResult, ClusterSummary, Observation, SpeciesAnalysis
from .rules import SpeciesRule, get_rule


def analyze_observations(observations: list[Observation], source_path: str, config: AnalyzerConfig | None = None) -> AnalysisResult:
    config = config or AnalyzerConfig()
    grouped: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.species].append(observation)

    species_results: list[SpeciesAnalysis] = []
    for species, items in sorted(grouped.items(), key=lambda pair: pair[0].lower()):
        clusters = _build_clusters(items, config)
        rule = get_rule(species)
        concentration = _assess_concentration(items, clusters, rule)
        reproduction = _assess_reproduction(items, clusters, rule)
        summary = _render_species_summary(species, items, clusters, concentration, reproduction, rule)
        species_results.append(
            SpeciesAnalysis(
                species=species,
                total_observations=len(items),
                clusters=clusters,
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

    clusters: list[list[tuple[float, float]]] = []
    for point in centroids:
        matched_cluster = None
        for cluster in clusters:
            if any(hypot(point[0] - existing[0], point[1] - existing[1]) <= config.distance_threshold_m for existing in cluster):
                matched_cluster = cluster
                break
        if matched_cluster is None:
            clusters.append([point])
        else:
            matched_cluster.append(point)

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


def _render_species_summary(
    species: str,
    items: list[Observation],
    clusters: list[ClusterSummary],
    concentration: str,
    reproduction: str,
    rule: SpeciesRule | None,
) -> str:
    parts = [
        f"Art {species}: {len(items)} Nachweise im Untersuchungsgebiet.",
        f"Bewertung der Verteilung: {concentration}.",
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
        return f"Verdacht auf Konzentrationszone bei {rule.species}"
    return "Verdacht auf Konzentrationszone"


def _assess_reproduction(items: list[Observation], clusters: list[ClusterSummary], rule: SpeciesRule | None) -> str:
    if rule is None:
        return "vorläufig zu prüfen"

    months = {observation.observed_at.month for observation in items if observation.observed_at is not None}
    if not months:
        return "Datum fehlt, daher vorläufig zu prüfen"

    breeding_overlap = months & rule.breeding_months
    if breeding_overlap and len(items) >= rule.min_contacts_for_reproduction and clusters:
        return f"Brutverdacht plausibel für {rule.species}"

    if months.isdisjoint(rule.breeding_months):
        return f"außerhalb der Brutzeit, daher kein belastbarer Brutverdacht für {rule.species}"

    return "vorläufig zu prüfen"
