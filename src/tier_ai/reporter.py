from __future__ import annotations

from .models import AnalysisResult


def render_report(result: AnalysisResult) -> str:
    lines: list[str] = []
    lines.append("Tier-KI Auswertung")
    lines.append(f"Quelle: {result.source_path}")
    lines.append("")

    outline = _build_outline(result)
    if outline:
        lines.append("## Inhaltsverzeichnis")
        lines.extend(f"- {entry}" for entry in outline)
        lines.append("")

    if result.executive_summary:
        lines.append("## Zusammenfassung")
        lines.append(result.executive_summary)
        lines.append("")

    if result.final_conclusion:
        lines.append("## Schlussbewertung")
        lines.append(result.final_conclusion)
        lines.append("")

    if result.metadata is not None:
        lines.append("## Metadaten")
        lines.append(f"Datei: {result.metadata.source_name}")
        if result.metadata.file_size_bytes is not None:
            lines.append(f"Dateigröße: {result.metadata.file_size_bytes} Bytes")
        if result.metadata.record_count is not None:
            lines.append(f"Datensätze: {result.metadata.record_count}")
        if result.metadata.crs:
            lines.append(f"CRS: {result.metadata.crs}")
        if result.metadata.geometry_types:
            lines.append(f"Geometrietypen: {', '.join(result.metadata.geometry_types)}")
        lines.append("")

    if result.species_results:
        lines.append("## Übersicht")
        lines.extend(_render_species_overview(result.species_results))
        lines.append("")

    for species_result in result.species_results:
        lines.append(f"## {species_result.display_name or species_result.species}")
        lines.append(f"Gruppe: {_display_group_name(species_result.taxon_group)}")
        lines.append(f"Nachweise: {species_result.total_observations}")
        lines.append(f"Konzentration: {species_result.concentration_assessment}")
        lines.append(f"Habitat: {species_result.habitat_assessment}")
        lines.append(f"Transit: {species_result.transit_assessment}")
        lines.append(f"Brutbewertung: {species_result.reproduction_assessment}")
        lines.append(f"Empfehlung: {species_result.recommendation}")
        lines.append(f"Priorität: {species_result.priority}")
        if species_result.clusters:
            for cluster in species_result.clusters:
                lines.append(
                    f"- {cluster.label}: {cluster.observation_count} Nachweise, "
                    f"Zentrum bei ({cluster.centroid_x:.2f}, {cluster.centroid_y:.2f})"
                )
        lines.append(species_result.text_summary)
        lines.append("")

    if result.warnings:
        lines.append("## Warnungen")
        lines.extend(f"- {warning}" for warning in result.warnings)

    if result.validation_issues:
        lines.append("## Validierung")
        lines.extend(f"- {issue}" for issue in result.validation_issues)

    return "\n".join(lines).strip() + "\n"


def _build_outline(result: AnalysisResult) -> list[str]:
    outline: list[str] = []
    outline.append("Zusammenfassung")
    if result.final_conclusion:
        outline.append("Schlussbewertung")
    if result.metadata is not None:
        outline.append("Metadaten")
    if result.species_results:
        outline.append("Übersicht")
    outline.extend(f"Art: {species_result.display_name or species_result.species}" for species_result in result.species_results)
    if result.warnings:
        outline.append("Warnungen")
    if result.validation_issues:
        outline.append("Validierung")
    return outline


def _render_species_overview(species_results) -> list[str]:
    lines: list[str] = []
    for species_result in species_results:
        cluster_count = len(species_result.clusters)
        lines.append(
            f"- {species_result.display_name or species_result.species} ({_display_group_name(species_result.taxon_group)}): {species_result.total_observations} Nachweise, "
            f"{cluster_count} Konzentrationsbereich(e), Brut={species_result.reproduction_assessment}, "
            f"Empfehlung={species_result.recommendation}, Priorität={species_result.priority}"
        )
    return lines


def _display_group_name(group: str) -> str:
    normalized = group.strip().casefold()
    if normalized == "unknown":
        return "unbestimmt"
    if normalized == "bat":
        return "Fledermäuse"
    if normalized == "bird":
        return "Vögel"
    return group
