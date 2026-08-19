from __future__ import annotations

import argparse
import json
from pathlib import Path

from .retrieval import RetrievalFilter, index_project, search_project, to_dict


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hippo-ai-retrieval", description="Projektbezogene Dokumentensuche")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Projektdateien indizieren")
    add_common_project_args(index_parser)

    search_parser = subparsers.add_parser("search", help="Projektdateien durchsuchen")
    add_common_project_args(search_parser)
    search_parser.add_argument("--query", default="", help="Suchanfrage")
    search_parser.add_argument("--species", default=None, help="Artenfilter")
    search_parser.add_argument("--file-type", default=None, help="Dateitypfilter")
    search_parser.add_argument("--category", default=None, help="Kategoriefilter")
    search_parser.add_argument("--zone", default=None, help="Zonenfilter")
    search_parser.add_argument("--date-from", default=None, help="Startdatum")
    search_parser.add_argument("--date-to", default=None, help="Enddatum")
    search_parser.add_argument("--limit", type=int, default=10, help="Maximale Trefferzahl")

    return parser


def add_common_project_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-id", required=True, help="Projekt-ID")
    parser.add_argument("--project-slug", required=True, help="Projekt-Slug")
    parser.add_argument("--project-root", default=None, help="Pfad zur Repository-Wurzel")
    parser.add_argument("--source-root", default=None, help="Quellordner des Projekts")
    parser.add_argument("--index-root", default=None, help="Speicherort des Retrieval-Index")
    parser.add_argument("--no-qdrant", action="store_true", help="Qdrant deaktivieren und lokalen Index verwenden")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    project_root = resolve_project_root(args.project_root)
    source_root = Path(args.source_root) if args.source_root else project_root
    index_root = Path(args.index_root) if args.index_root else project_root / "workspace" / "state" / "retrieval"

    if args.command == "index":
        summary = index_project(
            project_id=args.project_id,
            project_slug=args.project_slug,
            source_root=source_root,
            index_root=index_root,
            use_qdrant=not args.no_qdrant,
        )
        print(json.dumps(to_dict(summary), ensure_ascii=False, indent=2))
        return

    if args.command == "search":
        filters = RetrievalFilter(
            species=args.species,
            file_type=args.file_type,
            category=args.category,
            zone=args.zone,
            date_from=args.date_from,
            date_to=args.date_to,
            limit=args.limit,
        )
        result = search_project(
            project_id=args.project_id,
            project_slug=args.project_slug,
            query=args.query,
            index_root=index_root,
            filters=filters,
            prefer_real_models=True,
        )
        print(json.dumps(to_dict(result), ensure_ascii=False, indent=2))
        return

    raise SystemExit(1)


def resolve_project_root(project_root: str | None) -> Path:
    if project_root:
        start = Path(project_root).resolve()
    else:
        start = Path.cwd().resolve()

    candidate = start
    while True:
        if candidate.joinpath("pyproject.toml").exists():
            return candidate
        if not candidate.parent or candidate == candidate.parent:
            return start
        candidate = candidate.parent


if __name__ == "__main__":
    main()

