"""Small transactional SQLite store; source blobs are shared across commits."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS indices (
    id TEXT PRIMARY KEY, repository_id TEXT NOT NULL, commit_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blobs (
    id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, content TEXT NOT NULL,
    line_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    index_id TEXT NOT NULL REFERENCES indices(id), path TEXT NOT NULL,
    blob_id TEXT NOT NULL REFERENCES blobs(id), PRIMARY KEY(index_id, path)
);
CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY, blob_id TEXT NOT NULL REFERENCES blobs(id),
    start_line INTEGER NOT NULL, end_line INTEGER NOT NULL, headings TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sections_blob ON sections(blob_id);
CREATE VIRTUAL TABLE IF NOT EXISTS section_fts USING fts5(content, headings);
"""


def default_database() -> Path:
    """Persistent host cache shared by CLI and direct agents, outside checkouts."""
    cache = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_CACHE_HOME")
    return (Path(cache) if cache else Path.home() / ".cache") / "veraud" / "document-index.sqlite"


class DocumentIndexStore:
    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()
