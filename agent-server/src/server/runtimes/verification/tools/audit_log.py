"""JSONL decision/tool audit log for the generation loop."""

import json
import os
import time
from pathlib import Path


class AuditLog:
    def __init__(self, path: str | Path, *, max_events: int = 2000, truncate: bool = False):
        self.path = Path(path)
        self.max_events = max_events
        self.events = 0
        if truncate and self.path.exists():
            self.path.unlink()

    def record(self, kind: str, **fields) -> None:
        if self.events >= self.max_events:
            kind = "log_overflow"  # keep a terminal marker instead of growing unbounded
            fields = {}
        self.events += 1
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), "kind": kind, **fields}
        line = json.dumps(entry, ensure_ascii=False, default=str)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + os.linesep)
