"""Deterministic, directory-scoped Markdown indexing and retrieval."""

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from .discovery import discover, git
from .schemas import (
    DocumentRecord,
    DocumentSection,
    Heading,
    IndexReference,
    IndexResult,
    SearchHit,
)
from .splitting import SPLITTER_VERSION, split_sections
from .storage import DocumentIndexStore


def identifier(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


class DocumentIndexingService:
    """Owns no models or graphs. Reads a verified commit within the selected scope.

    The database belongs outside the audited repository. UTF-8 Markdown only;
    unsupported encodings and resource-limit violations abort the transaction.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        max_file_bytes: int = 2_000_000,
        max_documents: int = 10_000,
        max_total_bytes: int = 64_000_000,
    ) -> None:
        if min(max_file_bytes, max_documents, max_total_bytes) < 1:
            raise ValueError("Resource limits must be positive")
        self.store = DocumentIndexStore(database_path)
        self.max_file_bytes = max_file_bytes
        self.max_documents = max_documents
        self.max_total_bytes = max_total_bytes

    def index_repository(
        self, repository_path: str | Path, commit: str = "HEAD"
    ) -> IndexResult:
        root = Path(repository_path).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("A repository directory is required")
        if self.store.path.resolve().is_relative_to(root):
            raise ValueError(
                "Document index database must be outside the audited repository"
            )
        if not commit.strip() or commit.startswith("-") or "\0" in commit:
            raise ValueError("Invalid commit reference")
        resolved = (
            git(root, "rev-parse", "--verify", "--end-of-options", commit + "^{commit}")
            .decode()
            .strip()
        )
        repository_id = identifier(str(root))
        files = discover(root, resolved)
        if len(files) > self.max_documents:
            raise ValueError("Markdown document limit exceeded")
        index_id = identifier(
            repository_id,
            resolved,
            SPLITTER_VERSION,
            "git-directory-v1",
        )
        processed = reused = total_bytes = 0
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO indices VALUES (?, ?, ?)",
                (index_id, repository_id, resolved),
            )
            for path, oid in files:
                blob_id = identifier(oid, SPLITTER_VERSION, "git-v1")
                existing = db.execute(
                    "SELECT length(CAST(content AS BLOB)) FROM blobs WHERE id = ?",
                    (blob_id,),
                ).fetchone()
                size = (
                    existing[0] if existing else int(git(root, "cat-file", "-s", oid))
                )
                total_bytes += size
                if size > self.max_file_bytes:
                    raise ValueError(f"Markdown file limit exceeded: {path}")
                if total_bytes > self.max_total_bytes:
                    raise ValueError("Markdown total byte limit exceeded")
                if existing:
                    reused += 1
                else:
                    raw = git(root, "cat-file", "blob", oid)
                    text = raw.decode("utf-8")
                    lines = text.splitlines(keepends=True)
                    db.execute(
                        "INSERT INTO blobs VALUES (?, ?, ?, ?)",
                        (blob_id, hashlib.sha256(raw).hexdigest(), text, len(lines)),
                    )
                    for start, end, headings in split_sections(text):
                        metadata = json.dumps(
                            [heading.model_dump() for heading in headings]
                        )
                        row = db.execute(
                            "INSERT INTO sections(blob_id, start_line, end_line, headings) VALUES (?, ?, ?, ?)",
                            (blob_id, start, end, metadata),
                        )
                        db.execute(
                            "INSERT INTO section_fts(rowid, content, headings) VALUES (?, ?, ?)",
                            (
                                row.lastrowid,
                                "".join(lines[start - 1 : end]),
                                " / ".join(heading.title for heading in headings),
                            ),
                        )
                    processed += 1
                db.execute(
                    "INSERT OR IGNORE INTO documents VALUES (?, ?, ?)",
                    (index_id, path, blob_id),
                )
        return IndexResult(
            index_id=index_id,
            repository_id=repository_id,
            commit=resolved,
            documents=len(files),
            processed=processed,
            reused=reused,
        )

    @staticmethod
    def _reference(db: sqlite3.Connection, index_id: str) -> IndexReference:
        row = db.execute("SELECT * FROM indices WHERE id = ?", (index_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown document index")
        return IndexReference(
            index_id=row["id"],
            repository_id=row["repository_id"],
            commit=row["commit_id"],
        )

    @staticmethod
    def _pagination(limit: int, offset: int = 0) -> None:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Require 1 <= limit <= 100 and offset >= 0")

    def list_documents(
        self, index_id: str, *, limit: int = 20, offset: int = 0
    ) -> list[DocumentRecord]:
        self._pagination(limit, offset)
        with self.store.connect() as db:
            ref = self._reference(db, index_id)
            rows = db.execute(
                """SELECT d.path, b.content_hash, b.line_count FROM documents d
                JOIN blobs b ON b.id = d.blob_id WHERE d.index_id = ? ORDER BY d.path LIMIT ? OFFSET ?""",
                (index_id, limit, offset),
            ).fetchall()
            return [DocumentRecord(**ref.model_dump(), **dict(row)) for row in rows]

    def get_index(self, index_id: str) -> IndexReference:
        """Read index identity without source content, including empty indices."""
        with self.store.connect() as db:
            return self._reference(db, index_id)

    @staticmethod
    def _section(
        ref: IndexReference, row: sqlite3.Row, *, content: str | None = None
    ) -> DocumentSection:
        start, end = row["start_line"], row["end_line"]
        return DocumentSection(
            **ref.model_dump(),
            path=row["path"],
            content_hash=row["content_hash"],
            line_count=row["line_count"],
            section_id=identifier(ref.index_id, row["path"], str(start), str(end)),
            start_line=start,
            end_line=end,
            headings=tuple(
                Heading.model_validate(item) for item in json.loads(row["headings"])
            ),
            content=content
            if content is not None
            else "".join(row["content"].splitlines(keepends=True)[start - 1 : end]),
        )

    def search_fragments(
        self, index_id: str, query: str, *, limit: int = 10
    ) -> list[SearchHit]:
        self._pagination(limit)
        if not query.strip() or len(query) > 1000:
            raise ValueError("Query must contain 1–1000 characters")
        # Literal word search, not an exposed FTS expression language.
        words = re.findall(r"\w+", query, flags=re.UNICODE)
        expression = " AND ".join('"' + word + '"' for word in words)
        with self.store.connect() as db:
            ref = self._reference(db, index_id)
            if not words:
                return []
            rows = db.execute(
                """SELECT d.path, b.*, s.start_line, s.end_line, s.headings,
                bm25(section_fts) AS score FROM section_fts
                JOIN sections s ON s.id = section_fts.rowid
                JOIN blobs b ON b.id = s.blob_id
                JOIN documents d ON d.blob_id = b.id
                WHERE section_fts MATCH ? AND d.index_id = ?
                ORDER BY score, d.path, s.start_line LIMIT ?""",
                (expression, index_id, limit),
            ).fetchall()
            return [
                SearchHit(**self._section(ref, row).model_dump(), score=row["score"])
                for row in rows
            ]

    def read_section(
        self, index_id: str, path: str, start_line: int, end_line: int
    ) -> DocumentSection:
        """Read one exact indexed section, not arbitrary filesystem paths."""
        if start_line < 1 or end_line < start_line:
            raise ValueError("Invalid section range")
        with self.store.connect() as db:
            ref = self._reference(db, index_id)
            row = db.execute(
                """SELECT d.path, b.*, s.start_line, s.end_line, s.headings
                FROM documents d JOIN blobs b ON b.id = d.blob_id
                JOIN sections s ON s.blob_id = b.id
                WHERE d.index_id = ? AND d.path = ? AND s.start_line = ? AND s.end_line = ?""",
                (index_id, path, start_line, end_line),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown document section")
            return self._section(ref, row)

    def read_document_sections(
        self, index_id: str, path: str, *, limit: int = 20, offset: int = 0
    ) -> list[DocumentSection]:
        """Page original sections for an exact indexed path; empty files are valid."""
        self._pagination(limit, offset)
        with self.store.connect() as db:
            ref = self._reference(db, index_id)
            if (
                db.execute(
                    "SELECT 1 FROM documents WHERE index_id = ? AND path = ?",
                    (index_id, path),
                ).fetchone()
                is None
            ):
                raise ValueError("Unknown indexed document")
            rows = db.execute(
                """SELECT d.path, b.content_hash, b.line_count,
                s.start_line, s.end_line, s.headings, f.content
                FROM documents d JOIN blobs b ON b.id = d.blob_id
                JOIN sections s ON s.blob_id = b.id
                JOIN section_fts f ON f.rowid = s.id
                WHERE d.index_id = ? AND d.path = ?
                ORDER BY s.start_line LIMIT ? OFFSET ?""",
                (index_id, path, limit, offset),
            ).fetchall()
            return [self._section(ref, row, content=row["content"]) for row in rows]
