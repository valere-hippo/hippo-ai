from __future__ import annotations

import argparse

from .config import FieldMapping, load_analyzer_config
from .analyzer import analyze_observations
from .exporter import export_report
from .importer import load_observations_with_issues
from .reporter import render_report
from .rules import set_rule_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hippo-ai", description="Analyse geospatialer Tierbeobachtungen")
    parser.add_argument("input", help="GeoPackage, Shapefile oder GeoJSON")
    parser.add_argument("--output", "-o", help="Zieldatei für den Bericht", default=None)
    parser.add_argument("--species-column", default="species", help="Name der Art-Spalte")
    parser.add_argument("--date-column", default="observed_at", help="Name der Datums-Spalte")
    parser.add_argument("--distance-threshold-m", type=float, default=None, help="Distanzschwelle für Cluster in Metern")
    parser.add_argument("--min-cluster-size", type=int, default=None, help="Minimale Anzahl Beobachtungen für einen Cluster")
    parser.add_argument("--bat-distance-threshold-m", type=float, default=None, help="Distanzschwelle für Fledermaus-Cluster in Metern")
    parser.add_argument("--bird-distance-threshold-m", type=float, default=None, help="Distanzschwelle für Vogel-Cluster in Metern")
    parser.add_argument("--bat-min-cluster-size", type=int, default=None, help="Minimale Clustergröße für Fledermäuse")
    parser.add_argument("--bird-min-cluster-size", type=int, default=None, help="Minimale Clustergröße für Vögel")
    parser.add_argument("--analysis-config-file", default=None, help="Pfad zu einer JSON-Datei mit Analyseparametern")
    parser.add_argument("--rules-file", default=None, help="Pfad zu einer JSON-Datei mit Artenregeln")
    parser.add_argument("--docx-template-dir", default=None, help="Verzeichnis mit DOCX-Vorlagen-XML-Dateien")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    mapping = FieldMapping(species=args.species_column, observed_at=args.date_column)
    config = load_analyzer_config(args.analysis_config_file)
    config.field_mapping = mapping
    if args.distance_threshold_m is not None:
        config.distance_threshold_m = args.distance_threshold_m
    if args.min_cluster_size is not None:
        config.min_cluster_size = args.min_cluster_size
    if args.bat_distance_threshold_m is not None:
        config.distance_threshold_by_group["bat"] = args.bat_distance_threshold_m
    if args.bird_distance_threshold_m is not None:
        config.distance_threshold_by_group["bird"] = args.bird_distance_threshold_m
    if args.bat_min_cluster_size is not None:
        config.min_cluster_size_by_group["bat"] = args.bat_min_cluster_size
    if args.bird_min_cluster_size is not None:
        config.min_cluster_size_by_group["bird"] = args.bird_min_cluster_size
    if args.rules_file:
        set_rule_source(args.rules_file)
    observations, validation_issues, metadata = load_observations_with_issues(args.input, mapping=mapping)
    result = analyze_observations(observations, source_path=args.input, config=config)
    result.validation_issues = validation_issues
    result.metadata = metadata

    if args.output:
        export_report(result, args.output, docx_template_dir=args.docx_template_dir)
    else:
        print(render_report(result))
