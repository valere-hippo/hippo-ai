from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from .chat import (
    answer_general_question,
    answer_project_question,
    stream_general_question,
    stream_project_question,
    to_dict,
)
from .retrieval import RetrievalFilter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hippo-ai-chat", description="Projektbezogene Chat-Antwort mit Quellen")
    parser.add_argument("--general", action="store_true")
    parser.add_argument("--project-id", default="general")
    parser.add_argument("--project-slug", default="general")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--project-data-root", default=None)
    parser.add_argument("--index-root", default=None)
    parser.add_argument("--question", required=True)
    parser.add_argument("--species", default=None)
    parser.add_argument("--file-type", default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--zone", default=None)
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--no-real-models", action="store_true")
    parser.add_argument("--stream", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.general:
        if args.stream:
            for event in stream_general_question(
                question=args.question,
                history_root=resolve_history_root(args.project_root),
                prefer_real_models=not args.no_real_models,
            ):
                print(json.dumps(event, ensure_ascii=False), flush=True)
            return

        response = answer_general_question(
            question=args.question,
            history_root=resolve_history_root(args.project_root),
            prefer_real_models=not args.no_real_models,
        )
        print(json.dumps(dataclasses.asdict(response), ensure_ascii=False, indent=2))
        return

    project_root = resolve_project_root(args.project_root)
    project_data_root = resolve_project_data_root(args.project_data_root, project_root)
    index_root = Path(args.index_root) if args.index_root else project_root / "workspace" / "state" / "retrieval"
    filters = RetrievalFilter(
        species=args.species,
        file_type=args.file_type,
        category=args.category,
        zone=args.zone,
        date_from=args.date_from,
        date_to=args.date_to,
        limit=args.limit,
    )
    if args.stream:
        for event in stream_project_question(
            project_id=args.project_id,
            project_slug=args.project_slug,
            question=args.question,
            index_root=index_root,
            project_data_root=project_data_root,
            filters=filters,
            prefer_real_models=not args.no_real_models,
            max_sources=args.limit,
        ):
            print(json.dumps(event, ensure_ascii=False), flush=True)
        return

    response = answer_project_question(
        project_id=args.project_id,
        project_slug=args.project_slug,
        question=args.question,
        index_root=index_root,
        project_data_root=project_data_root,
        filters=filters,
        prefer_real_models=not args.no_real_models,
        max_sources=args.limit,
    )
    print(json.dumps(to_dict(response), ensure_ascii=False, indent=2))


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


def resolve_project_data_root(project_data_root: str | None, project_root: Path) -> Path | None:
    if project_data_root:
        return Path(project_data_root).resolve()
    return None


def resolve_history_root(project_root: str | None) -> Path:
    return resolve_project_root(project_root) / "workspace" / "state"


if __name__ == "__main__":
    main()
