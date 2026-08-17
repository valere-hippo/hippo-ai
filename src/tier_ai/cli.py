from __future__ import annotations

import argparse
from pathlib import Path

from .config import AnalyzerConfig, FieldMapping
from .analyzer import analyze_observations
from .importer import load_observations
from .reporter import render_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tier-ai", description="Analyse geospatialer Tierbeobachtungen")
    parser.add_argument("input", help="GeoPackage oder Shapefile")
    parser.add_argument("--output", "-o", help="Zieldatei für den Bericht", default=None)
    parser.add_argument("--species-column", default="species", help="Name der Art-Spalte")
    parser.add_argument("--date-column", default="observed_at", help="Name der Datums-Spalte")
    parser.add_argument("--distance-threshold-m", type=float, default=75.0, help="Distanzschwelle für Cluster in Metern")
    parser.add_argument("--min-cluster-size", type=int, default=2, help="Minimale Anzahl Beobachtungen für einen Cluster")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    mapping = FieldMapping(species=args.species_column, observed_at=args.date_column)
    config = AnalyzerConfig(distance_threshold_m=args.distance_threshold_m, min_cluster_size=args.min_cluster_size, field_mapping=mapping)
    observations = load_observations(args.input, mapping=mapping)
    result = analyze_observations(observations, source_path=args.input, config=config)
    report = render_report(result)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(report, encoding="utf-8")
    else:
        print(report)
