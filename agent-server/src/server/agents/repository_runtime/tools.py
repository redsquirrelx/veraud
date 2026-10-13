"""Bounded, snapshot-only tools for a single workspace checkout."""

import hashlib
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from ...services.repository_analysis import RepositoryQueryService
from ...services.repository_analysis.context import create_identifier
from ...services.repository_analysis.schemas import QueryPage
from .access import (
    DEFAULT_WORKSPACE_ROOT,
    RepositoryAccessError,
    RepositoryAccessPolicy,
    repository_relative_path,
)
from .context import RepositoryContext
from .schemas import BudgetUsage, RetrievedEvidence
from .telemetry import ToolMeasurement


class ToolLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    max_page_size: int = Field(default=50, ge=1, le=500)
    max_response_characters: int = Field(default=16_000, ge=512)
    max_source_lines: int = Field(default=120, ge=1)
    max_source_characters: int = Field(default=12_000, ge=1)
    max_metadata_items: int = Field(default=20, ge=1)
    compact: bool = False


class ToolError(BaseModel):
    code: str
    message: str


class RepositoryToolResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tool_call_id: str
    tool_name: str
    snapshot_hash: str
    status: Literal["ok", "error"]
    data: dict[str, Any] | None = None
    evidence: tuple[RetrievedEvidence, ...] = ()
    error: ToolError | None = None


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


PAGINATION = {
    "offset": (int, Field(default=0, ge=0)),
    "limit": (int, Field(default=20, ge=1, le=500)),
}
PROJECT_FILTER = {"project_id": (str | None, None)}


def argument_schema(name: str, fields: dict):
    return create_model(
        "".join(part.title() for part in name.split("_")) + "Arguments",
        __base__=ToolArguments,
        **fields,
    )


TOOL_SCHEMAS = {
    "list_files": argument_schema(
        "list_files",
        PAGINATION
        | PROJECT_FILTER
        | {
            "path_prefix": (str | None, None),
            "language": (str | None, None),
            "status": (str | None, None),
        },
    ),
    "find_symbols": argument_schema(
        "find_symbols",
        PAGINATION
        | PROJECT_FILTER
        | {
            "name": (str | None, None),
            "kind": (str | None, None),
            "file_path": (str | None, None),
        },
    ),
    "get_source_excerpt": argument_schema(
        "get_source_excerpt",
        {
            "path": (str, Field(min_length=1)),
            "start_line": (int, Field(default=1, ge=1)),
            "end_line": (int | None, Field(default=None, ge=1)),
        },
    ),
    "list_relationships": argument_schema(
        "list_relationships",
        PAGINATION
        | PROJECT_FILTER
        | {
            "kind": (str | None, None),
            "resolution": (
                Literal["internal", "external", "builtin", "unresolved", "dynamic"]
                | None,
                None,
            ),
            "source_id": (str | None, None),
            "target_id": (str | None, None),
        },
    ),
    "get_infrastructure": argument_schema(
        "get_infrastructure", PAGINATION | PROJECT_FILTER | {"kind": (str | None, None)}
    ),
    "search_repository_text": argument_schema(
        "search_repository_text",
        PAGINATION
        | PROJECT_FILTER
        | {
            "query": (str, Field(min_length=1, max_length=1000)),
            "path_prefix": (str | None, None),
            "case_sensitive": (bool, False),
        },
    ),
    "get_evidence": argument_schema(
        "get_evidence", {"evidence_id": (str, Field(min_length=1))}
    ),
}


@lru_cache(maxsize=1)
def tool_signatures():
    result = {}
    for name, model in TOOL_SCHEMAS.items():
        schema = model.model_json_schema()
        properties = {}
        for key, value in schema["properties"].items():
            kind = value.get("type") or "|".join(
                child.get("type", "any") for child in value.get("anyOf", [])
            )
            if "default" in value:
                kind += "=" + json.dumps(value["default"])
            properties[key] = kind
        result[name] = {"arguments": properties, "required": schema.get("required", [])}
    return result


class ToolRequestError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class RepositoryToolset:
    """Per-run tools, evidence registry, and tool-budget ledger.

    workspace_root is trusted host configuration, never a tool argument. The
    bound snapshot cannot be switched by the model. Calls are serialized so
    concurrent tool invocations cannot race the shared budget or registry.
    """

    def __init__(
        self,
        context: RepositoryContext,
        *,
        workspace_root: Path = DEFAULT_WORKSPACE_ROOT,
        limits: ToolLimits | None = None,
    ):
        self.context = context
        self.policy = RepositoryAccessPolicy.bind(context.snapshot, workspace_root)
        self.limits = limits or ToolLimits()
        self._snapshot = self.policy.filtered_snapshot(context.snapshot)
        self._queries = RepositoryQueryService(self._snapshot)
        self._files = {source.id: source for source in self._snapshot.files}
        self._paths = {source.path: source for source in self._snapshot.files}
        self._evidence_index = {record.id: record for record in self._snapshot.evidence}
        self._entities = {
            record.id
            for collection in (
                self._snapshot.projects,
                self._snapshot.files,
                self._snapshot.symbols,
                self._snapshot.dependencies,
                self._snapshot.infrastructure,
                self._snapshot.entrypoints,
                self._snapshot.technologies,
                self._snapshot.testing,
                self._snapshot.directories,
                self._snapshot.relationships,
            )
            for record in collection
        }
        self._retrieved: dict[str, RetrievedEvidence] = {}
        self._call_ids: set[str] = set()
        self._tool_calls = 0
        self._retrieved_characters = 0
        self._lock = RLock()
        self._tool_measurements: list[ToolMeasurement] = []
        self._request_signatures: set[str] = set()
        self._query_cache = {}
        self._last_cache_hit = False

    @property
    def tool_measurements(self) -> tuple[ToolMeasurement, ...]:
        with self._lock:
            return tuple(self._tool_measurements)

    @property
    def last_cache_hit(self):
        with self._lock:
            return self._last_cache_hit

    @property
    def budget_usage(self) -> BudgetUsage:
        with self._lock:
            return BudgetUsage(
                tool_calls=self._tool_calls,
                retrieved_characters=self._retrieved_characters,
                elapsed_seconds=self.context.elapsed_seconds,
            )

    @property
    def accessible_snapshot(self):
        """Role projections use the same access policy as agent-facing tools."""
        return self._snapshot

    @property
    def retrieved_evidence(self) -> tuple[RetrievedEvidence, ...]:
        with self._lock:
            return tuple(self._retrieved.values())

    def execute(
        self, name: str, arguments: dict[str, Any], *, tool_call_id: str
    ) -> RepositoryToolResponse:
        """Measure charged requests without storing argument or response content."""
        with self._lock:
            before = self._tool_calls
            started = monotonic()
            self._last_cache_hit = False
            response = self._execute(name, arguments, tool_call_id=tool_call_id)
            if self._tool_calls > before:
                schema = TOOL_SCHEMAS.get(name)
                try:
                    normalized = (
                        schema.model_validate(arguments).model_dump()
                        if schema
                        else arguments
                    )
                except ValidationError:
                    normalized = arguments
                try:
                    encoded = json.dumps(
                        [name, normalized], sort_keys=True, default=str
                    ).encode()
                except (TypeError, ValueError):
                    # Measurement must not change controlled rejection behavior.
                    encoded = json.dumps(
                        [name, "unserializable_arguments", tool_call_id]
                    ).encode()
                signature = hashlib.sha256(encoded).hexdigest()
                self._tool_measurements.append(
                    ToolMeasurement(
                        call_id=tool_call_id,
                        tool=name,
                        request_sha256=signature,
                        repeated=signature in self._request_signatures,
                        status=response.status,
                        cache_hit=self._last_cache_hit,
                        seconds=monotonic() - started,
                    )
                )
                self._request_signatures.add(signature)
            return response

    def _execute(
        self, name: str, arguments: dict[str, Any], *, tool_call_id: str
    ) -> RepositoryToolResponse:
        """Return controlled failures; register only evidence actually delivered."""
        with self._lock:
            if not isinstance(name, str):
                return self._error(
                    "invalid-tool",
                    "invalid-call-id",
                    "unknown_tool",
                    "A tool name is required.",
                )
            # IDs are echoed in bounded envelopes and must not be arbitrary source.
            if not isinstance(tool_call_id, str) or not 1 <= len(tool_call_id) <= 128:
                return self._error(
                    name,
                    "invalid-call-id",
                    "invalid_arguments",
                    "Tool call IDs must contain 1 to 128 characters.",
                )
            if tool_call_id in self._call_ids:
                return self._error(
                    name,
                    tool_call_id,
                    "duplicate_tool_call_id",
                    "Use a fresh tool call ID.",
                )
            budget = self.context.input.budget
            if self.context.elapsed_seconds >= budget.max_elapsed_seconds:
                return self._error(
                    name,
                    tool_call_id,
                    "time_budget_exhausted",
                    "The execution time budget is exhausted.",
                )
            if self._tool_calls >= budget.max_tool_calls:
                return self._error(
                    name,
                    tool_call_id,
                    "tool_budget_exhausted",
                    "The tool call budget is exhausted.",
                )
            self._call_ids.add(tool_call_id)
            self._tool_calls += 1
            self._last_cache_hit = False
            try:
                schema = TOOL_SCHEMAS.get(name)
                if schema is None:
                    raise ToolRequestError(
                        "unknown_tool", "The requested tool is not available."
                    )
                values = schema.model_validate(arguments).model_dump()
                self._validate_arguments(values)
                cache_key = json.dumps([name, values], sort_keys=True)
                if self.limits.compact and cache_key in self._query_cache:
                    result = deepcopy(self._query_cache[cache_key])
                    self._last_cache_hit = True
                else:
                    result = self._query(name, values)
                    if self.limits.compact:
                        self._query_cache[cache_key] = deepcopy(result)
                response = self._bounded_response(name, tool_call_id, result)
                if self.context.elapsed_seconds >= budget.max_elapsed_seconds:
                    raise ToolRequestError(
                        "time_budget_exhausted",
                        "The execution time budget is exhausted.",
                    )
                serialized = response.model_dump_json()
                self._retrieved_characters += len(serialized)
                for record in response.evidence:
                    self._retrieved[record.id] = record
                return response
            except ValidationError as error:
                return self._error(
                    name,
                    tool_call_id,
                    "invalid_arguments",
                    "Arguments do not match the tool schema: "
                    + "; ".join(
                        f"{'.'.join(map(str, item['loc']))}: {item['type']}"
                        for item in error.errors(include_input=False)[:4]
                    ),
                )
            except RepositoryAccessError:
                return self._error(
                    name,
                    tool_call_id,
                    "access_denied",
                    "The request is outside the selected repository or allowed technical files.",
                )
            except ToolRequestError as error:
                return self._error(name, tool_call_id, error.code, str(error))
            except (KeyError, ValueError):
                return self._error(
                    name,
                    tool_call_id,
                    "invalid_request",
                    "The requested reference or source range is unavailable. Use valid references and smaller line ranges.",
                )

    def _error(
        self, name: str, call_id: str, code: str, message: str
    ) -> RepositoryToolResponse:
        return RepositoryToolResponse(
            tool_call_id=call_id,
            tool_name=name[:80],
            snapshot_hash=self.context.input.snapshot_hash,
            status="error",
            error=ToolError(code=code, message=message),
        )

    def _validate_arguments(self, values: dict) -> None:
        if "limit" in values and values["limit"] > self.limits.max_page_size:
            raise ToolRequestError("page_limit_exceeded", "Use a smaller page size.")
        for name in ("path", "file_path", "path_prefix"):
            if values.get(name) is not None:
                original = values[name]
                path = repository_relative_path(
                    original, allow_root=name == "path_prefix"
                )
                if name != "path_prefix" and path not in self._paths:
                    raise RepositoryAccessError(
                        "File is unavailable under the access policy."
                    )
                values[name] = "" if path == "." else path
        if values.get("project_id") is not None and values["project_id"] not in {
            project.id for project in self._snapshot.projects
        }:
            raise ToolRequestError(
                "unknown_reference", "The project reference is not in this snapshot."
            )
        for name in ("source_id", "target_id"):
            if values.get(name) is not None and values[name] not in self._entities:
                raise RepositoryAccessError(
                    "Entity is unavailable under the access policy."
                )
        if (
            "evidence_id" in values
            and values["evidence_id"] not in self._evidence_index
        ):
            raise RepositoryAccessError(
                "Evidence is unavailable under the access policy."
            )

    def _query(self, name: str, values: dict) -> BaseModel | dict:
        if name == "get_source_excerpt":
            path = values["path"]
            start = values["start_line"]
            requested_end = values["end_line"] or self._paths[path].line_count
            if (
                requested_end is None
                or requested_end < start
                or requested_end > (self._paths[path].line_count or 0)
            ):
                raise ToolRequestError(
                    "invalid_source_range", "Source range is outside retained content."
                )
            end = min(requested_end, start + self.limits.max_source_lines - 1)
            source = self._queries.get_source_excerpt(path, start, end)
            if self.limits.compact:
                while (
                    len(source.content) > self.limits.max_source_characters
                    and end > start
                ):
                    end -= 1
                    source = self._queries.get_source_excerpt(path, start, end)
            if len(source.content) > self.limits.max_source_characters:
                raise ToolRequestError(
                    "source_limit_exceeded", "Use a smaller source line range."
                )
            return source.model_dump(mode="json") | {
                "requested_end_line": requested_end,
                "truncated": end < requested_end,
            }
        return getattr(self._queries, name)(**values)

    def _bounded_response(
        self, name: str, call_id: str, result: BaseModel | dict
    ) -> RepositoryToolResponse:
        data = (
            result.model_dump(mode="json", exclude={"items": {"__all__": {"content"}}})
            if isinstance(result, QueryPage)
            else result.model_dump(mode="json")
            if isinstance(result, BaseModel)
            else result
        )
        if isinstance(result, QueryPage):
            data["next_offset"] = (
                result.offset + len(result.items)
                if result.offset + len(result.items) < result.total
                else None
            )
            data["truncated"] = False
        if self.limits.compact:
            data = self.compact_data(name, data)
        self._compact_metadata(data)
        remaining = (
            self.context.input.budget.max_retrieved_characters
            - self._retrieved_characters
        )
        cap = min(self.limits.max_response_characters, remaining)
        while True:
            evidence = self._provenance(data, call_id)
            response = RepositoryToolResponse(
                tool_call_id=call_id,
                tool_name=name,
                snapshot_hash=self.context.input.snapshot_hash,
                status="ok",
                data=data,
                evidence=evidence,
            )
            if len(response.model_dump_json()) <= cap:
                return response
            if isinstance(result, QueryPage) and len(data["items"]) > 1:
                data["items"].pop()
                data["next_offset"] = result.offset + len(data["items"])
                data["truncated"] = True
                continue
            code = (
                "content_budget_exhausted"
                if remaining < self.limits.max_response_characters
                else "response_limit_exceeded"
            )
            raise ToolRequestError(
                code,
                "The result cannot fit the remaining response budget. Request fewer items or a smaller source range.",
            )

    def _compact_metadata(self, value):
        """Expose nested-list omissions explicitly; never shorten source lines."""
        if isinstance(value, dict):
            omitted = {}
            for name, child in tuple(value.items()):
                if (
                    isinstance(child, list)
                    and name != "items"
                    and len(child) > self.limits.max_metadata_items
                ):
                    omitted[name] = len(child) - self.limits.max_metadata_items
                    value[name] = child[: self.limits.max_metadata_items]
                self._compact_metadata(value[name])
            if omitted:
                value["omitted_field_items"] = omitted
        elif isinstance(value, list):
            for child in value:
                self._compact_metadata(child)

    @staticmethod
    def compact_data(name, data):
        """Small query projection; full snapshot and retained source stay internal."""
        data = deepcopy(data)
        if "items" in data:
            fields = {
                "id",
                "name",
                "path",
                "file_id",
                "project_id",
                "language",
                "status",
                "line_count",
                "kind",
                "qualified_name",
                "start_line",
                "end_line",
                "source_id",
                "target_id",
                "http_method",
                "route",
                "target",
                "version",
                "constraint",
                "resolved_version",
                "version_constraint",
                "resolved_versions",
                "environment_marker",
                "scope",
                "usage",
                "detection",
                "image",
                "command",
                "text",
                "line",
                "evidence_ids",
            }
            rows = []
            for item in data["items"]:
                rows.append(
                    {
                        key: value[:2]
                        if key == "evidence_ids" and isinstance(value, list)
                        else value
                        for key, value in item.items()
                        if key in fields and value is not None and value != []
                    }
                )
            data["items"] = rows
        return data

    def model_view(self, response):
        """Compact model envelope while keeping the full provenance ledger internal."""
        value = {"status": response.status, "tool_name": response.tool_name}
        if response.error:
            value["error"] = response.error.model_dump()
        else:
            value["data"] = self.compact_data(response.tool_name, response.data or {})
            value["evidence"] = [
                {
                    key: getattr(record, key)
                    for key in ("id", "kind", "file_id", "start_line", "end_line")
                    if getattr(record, key) is not None
                }
                for record in response.evidence
            ]
        return value

    def _provenance(self, data: dict, call_id: str) -> tuple[RetrievedEvidence, ...]:
        records: dict[tuple, RetrievedEvidence] = {}

        def register(file_id, kind="metadata", start=None, end=None, evidence_ids=()):
            source_file = self._files.get(file_id)
            if source_file is None:
                return
            key = (file_id, kind, start, end, tuple(evidence_ids))
            records[key] = RetrievedEvidence(
                id=create_identifier(
                    "retrieval", self.context.input.snapshot_hash, call_id, *key
                ),
                snapshot_hash=self.context.input.snapshot_hash,
                file_id=file_id,
                content_hash=source_file.content_hash,
                tool_call_id=call_id,
                kind=kind,
                start_line=start,
                end_line=end,
                snapshot_evidence_ids=tuple(evidence_ids),
            )

        def visit(value):
            if isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, dict):
                file_id = value.get("file_id")
                if "content" in value and file_id in self._files:
                    register(file_id, "source", value["start_line"], value["end_line"])
                elif "text" in value and "line" in value and file_id in self._files:
                    register(file_id, "source", value["line"], value["line"])
                elif file_id in self._files:
                    register(file_id)
                if value.get("id") in self._files:
                    register(value["id"])
                evidence_ids = value.get("evidence_ids", [])
                if value.get("id") in self._evidence_index:
                    evidence_ids = [value["id"]]
                for identifier in evidence_ids:
                    evidence = self._evidence_index[identifier]
                    register(evidence.file_id, evidence_ids=(identifier,))
                for child in value.values():
                    visit(child)

        visit(data)
        return tuple(records.values())
