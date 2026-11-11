"""Command-line entry point for deterministic Markdown indexing."""

import argparse
import json
import sqlite3
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.services.document_indexing import DocumentIndexingService
from server.services.document_indexing.storage import default_database


def result_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "limit must be an integer between 1 and 100"
        ) from error
    if not 1 <= limit <= 100:
        raise argparse.ArgumentTypeError("limit must be between 1 and 100")
    return limit


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Index a directory's committed Markdown and optionally search it with SQLite BM25. No LLM required.",
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory to index (never expanded to a parent repository)",
    )
    parser.add_argument(
        "--commit",
        default="HEAD",
        help="Git commit or ref to verify and index (default: HEAD)",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=default_database(),
        help="SQLite file outside the repository (default: host cache/veraud/document-index.sqlite)",
    )
    parser.add_argument("--query", help="Literal search terms combined with AND")
    parser.add_argument(
        "--output",
        type=Path,
        help="Write a JSON test report (must be a new file; SQLite remains the index)",
    )
    parser.add_argument(
        "--limit",
        type=result_limit,
        default=20,
        help="Maximum documents or search hits to display, 1–100 (default: 20)",
    )
    args = parser.parse_args(argv)
    if args.query is not None and (not args.query.strip() or len(args.query) > 1000):
        parser.error("--query must contain 1–1000 characters")

    try:
        root = args.directory.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("A repository directory is required")
        database = args.database.expanduser().resolve()
        output = args.output.expanduser().resolve() if args.output else None
        if output is not None and (output == database or output.exists()):
            raise ValueError(
                "Output must be a new file, different from the SQLite database"
            )
        # Validate before constructing the service, which creates the database.
        if database.is_relative_to(root):
            raise ValueError(
                "Database must be outside the audited repository; use --database"
            )
        service = DocumentIndexingService(database)
        index = service.index_repository(root, args.commit)
        print(f"Repository: {root}")
        print(f"Commit: {index.commit}")
        print(f"Index: {index.index_id}")
        print(f"Database: {database}")
        print(
            f"Documents: {index.documents}; processed: {index.processed}; reused: {index.reused}"
        )
        print(
            "Source: verified commit within the supplied directory only; local changes are not indexed."
        )
        hits = []
        if args.query is None:
            print(f"\nDocuments (up to {args.limit}):")
            for document in service.list_documents(index.index_id, limit=args.limit):
                print(f"  {document.path} ({document.line_count} lines)")
        else:
            hits = service.search_fragments(
                index.index_id, args.query, limit=args.limit
            )
            print(f"\nSearch results: {len(hits)} (up to {args.limit})")
            for hit in hits:
                print(
                    f"\n{hit.path}:{hit.start_line}-{hit.end_line} (BM25: {hit.score:.6g})"
                )
                if hit.headings:
                    print(" > ".join(heading.title for heading in hit.headings))
                print(
                    hit.content[:1000],
                    end="" if hit.content[:1000].endswith("\n") else "\n",
                )
                if len(hit.content) > 1000:
                    print("[Preview truncated to 1000 characters]")
        if output is not None:
            # Export every document, independently of the console/search limit.
            documents = []
            offset = 0
            while True:
                page = service.list_documents(index.index_id, limit=100, offset=offset)
                documents.extend(item.model_dump(mode="json") for item in page)
                if len(page) < 100:
                    break
                offset += len(page)
            report = {
                "schema_version": "1",
                "repository_path": str(root),
                "database_path": str(database),
                "summary": index.model_dump(mode="json"),
                "documents": documents,
                "query": args.query,
                "search_limit": args.limit,
                "results": [hit.model_dump(mode="json") for hit in hits],
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            print(f"\nJSON report: {output}")
        return 0
    except (OSError, ValueError, sqlite3.Error, subprocess.TimeoutExpired) as error:
        print(f"Document indexing failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
