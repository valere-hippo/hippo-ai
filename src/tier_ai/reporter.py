from __future__ import annotations

from .models import AnalysisResult


def render_report(result: AnalysisResult) -> str:
    lines: list[str] = []
    lines.append("Tier-KI Auswertung")
    lines.append(f"Quelle: {result.source_path}")
    lines.append("")

    if result.executive_summary:
        lines.append("## Zusammenfassung")
        lines.append(result.executive_summary)
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

    for species_result in result.species_results:
        lines.append(f"## {species_result.species}")
        lines.append(f"Nachweise: {species_result.total_observations}")
        lines.append(f"Konzentration: {species_result.concentration_assessment}")
        lines.append(f"Habitat: {species_result.habitat_assessment}")
        lines.append(f"Transit: {species_result.transit_assessment}")
        lines.append(f"Brutbewertung: {species_result.reproduction_assessment}")
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
