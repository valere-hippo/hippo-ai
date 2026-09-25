from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select

from app.models.project import Project
from app.models.tool import AITool
from app.services.project_storage import list_project_files


@dataclass(frozen=True, slots=True)
class AutoToolDefinition:
    name: str
    description: str
    instructions: str
    extensions: frozenset[str]
    parameters: dict[str, Any]


IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})
DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".odt", ".rtf", ".txt", ".md"})
SPREADSHEET_EXTENSIONS = frozenset({".xlsx", ".xls", ".xlsm", ".ods", ".csv"})
PRESENTATION_EXTENSIONS = frozenset({".pptx", ".odp"})
GEODATA_EXTENSIONS = frozenset({".shp", ".shx", ".dbf", ".prj", ".cpg", ".gpkg", ".geojson", ".kml", ".kmz", ".qgz", ".qgs"})
ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".rar", ".tar", ".gz", ".tgz"})


AUTO_TOOL_DEFINITIONS: tuple[AutoToolDefinition, ...] = (
    AutoToolDefinition(
        name="Bild- und Stilanalyse",
        description="Analysiert Bilddateien, Screenshots und visuelle Stile im Projekt.",
        instructions=(
            "Nutze dieses Tool für Bilddateien, Screenshots, Kartenbilder und visuelle Dokumente. "
            "Beschreibe Layout, Farben, Beschriftungen, Stil, Lesbarkeit und sichtbare Objekte. "
            "Wenn OCR- oder Metadaten vorhanden sind, verwende sie. Wenn mehrere Bilder vorhanden sind, vergleiche sie. "
            "Gib für Berichte präzise visuelle Hinweise und keine pauschalen Vermutungen."
        ),
        extensions=IMAGE_EXTENSIONS,
        parameters={"auto_generated": True, "kind": "image", "supported_extensions": sorted(IMAGE_EXTENSIONS)},
    ),
    AutoToolDefinition(
        name="Dokumentenleser",
        description="Liest PDF-, Word- und Textdokumente vollständig und strukturorientiert.",
        instructions=(
            "Nutze dieses Tool für PDF, DOCX, ODT, RTF, TXT und Markdown. "
            "Lies Dokumente vollständig, beachte Überschriften, Absätze, Tabellenhinweise und Zitate. "
            "Wenn der Inhalt sehr lang ist, erfasse die Struktur vollständig und fasse nur dort zusammen, wo Wiederholungen entstehen. "
            "Für Berichte sollen Inhalte aus allen verfügbaren Dokumenten eingearbeitet werden."
        ),
        extensions=DOCUMENT_EXTENSIONS,
        parameters={"auto_generated": True, "kind": "document", "supported_extensions": sorted(DOCUMENT_EXTENSIONS)},
    ),
    AutoToolDefinition(
        name="Tabellenleser",
        description="Liest Tabellen, Excel-Dateien und CSV-Dateien mit Spalten- und Zeilenkontext.",
        instructions=(
            "Nutze dieses Tool für Tabellen und Spreadsheet-Dateien wie XLSX, XLS, XLSM, ODS und CSV. "
            "Achte auf Spaltennamen, Einheiten, Datumsfelder, Ausreißer und Summen. "
            "Wenn mehrere Tabellenblätter existieren, beziehe die wichtigsten ein und erhalte die Beziehungen zwischen Blättern."
        ),
        extensions=SPREADSHEET_EXTENSIONS,
        parameters={"auto_generated": True, "kind": "spreadsheet", "supported_extensions": sorted(SPREADSHEET_EXTENSIONS)},
    ),
    AutoToolDefinition(
        name="Präsentationsleser",
        description="Liest Präsentationen und extrahiert die wichtigsten Folieninhalte.",
        instructions=(
            "Nutze dieses Tool für PPTX- und ODP-Dateien. "
            "Erfasse Titel, Folienstruktur, Bild-/Textverhältnis, Kernaussagen und zusammenfassende Punkte pro Folie. "
            "Wenn Folien Screenshots oder Diagramme enthalten, beschreibe deren visuelle Rolle."
        ),
        extensions=PRESENTATION_EXTENSIONS,
        parameters={"auto_generated": True, "kind": "presentation", "supported_extensions": sorted(PRESENTATION_EXTENSIONS)},
    ),
    AutoToolDefinition(
        name="Geodatenleser",
        description="Liest Geodaten, Shape-Dateien und GIS-Projekte mit Raumbezug.",
        instructions=(
            "Nutze dieses Tool für SHP, SHX, DBF, PRJ, CPG, GPKG, GeoJSON, KML, KMZ, QGZ und QGS. "
            "Erfasse Geometrietypen, Bounding Boxes, Attribute, Beobachtungszeiträume, Artenhinweise und räumliche Cluster. "
            "Wenn mehrere Geodateien zusammengehören, behandle sie als ein Paket."
        ),
        extensions=GEODATA_EXTENSIONS,
        parameters={"auto_generated": True, "kind": "geodata", "supported_extensions": sorted(GEODATA_EXTENSIONS)},
    ),
    AutoToolDefinition(
        name="Archiv-Inspektor",
        description="Erkennt komprimierte Anhänge und behandelt sie als Quellen für weitere Dateitypen.",
        instructions=(
            "Nutze dieses Tool für ZIP, 7Z, RAR, TAR und ähnliche Archive. "
            "Liste enthaltene Dateitypen, erkenne wichtige Dokumente, Bilder und Tabellen und leite sie an passende Tools weiter."
        ),
        extensions=ARCHIVE_EXTENSIONS,
        parameters={"auto_generated": True, "kind": "archive", "supported_extensions": sorted(ARCHIVE_EXTENSIONS)},
    ),
)


async def ensure_project_file_tools(db: Any, project_id: int, source_prefixes: list[str] | None = None) -> list[str]:
    result = await db.execute(select(AITool.name, AITool.id))
    existing_names = {str(name) for name, _tool_id in result.all()}

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        return []

    files = list_project_files(project, source_prefixes=source_prefixes)
    if not files:
        return []

    detected_extensions = {Path(item.filename).suffix.lower() for item in files if Path(item.filename).suffix}
    created_or_updated: list[str] = []

    for definition in AUTO_TOOL_DEFINITIONS:
        if not (definition.extensions & detected_extensions):
            continue

        if definition.name in existing_names:
            tool_result = await db.execute(select(AITool).where(AITool.name == definition.name))
            tool = tool_result.scalar_one_or_none()
            if tool is None:
                continue
            await db.execute(
                AITool.__table__.update()
                .where(AITool.id == tool.id)
                .values(
                    description=definition.description,
                    instructions=definition.instructions,
                    tool_type="workflow",
                    parameters=definition.parameters,
                    is_enabled=True,
                )
            )
            created_or_updated.append(definition.name)
            continue

        stmt = insert(AITool).values(
            name=definition.name,
            description=definition.description,
            instructions=definition.instructions,
            tool_type="workflow",
            command=None,
            arguments=None,
            working_directory=None,
            endpoint=None,
            method=None,
            platform=None,
            timeout_seconds=None,
            requires_confirmation=False,
            parameters=definition.parameters,
            is_enabled=True,
        )
        await db.execute(stmt)
        existing_names.add(definition.name)
        created_or_updated.append(definition.name)

    if created_or_updated:
        await db.commit()
    return created_or_updated
