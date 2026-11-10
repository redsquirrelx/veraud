"""Opt-in LangChain tools bound to one trusted document index."""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from ...services.document_indexing import DocumentIndexingService


class ListDocumentsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchDocumentsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=100)


class ReadDocumentArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


def create_document_tools(
    service: DocumentIndexingService, index_id: str
) -> list[StructuredTool]:
    """No model-supplied repository/index selection and no indexing write tool."""

    def list_documents(limit: int = 20, offset: int = 0):
        return [
            item.model_dump(mode="json")
            for item in service.list_documents(index_id, limit=limit, offset=offset)
        ]

    def search_documents(query: str, limit: int = 10):
        return [
            item.model_dump(mode="json")
            for item in service.search_fragments(index_id, query, limit=limit)
        ]

    def read_document_section(path: str, start_line: int, end_line: int):
        return service.read_section(index_id, path, start_line, end_line).model_dump(
            mode="json"
        )

    return [
        StructuredTool.from_function(
            list_documents,
            name="list_documents",
            args_schema=ListDocumentsArguments,
            description="List Markdown documents in the bound directory snapshot.",
        ),
        StructuredTool.from_function(
            search_documents,
            name="search_documents",
            args_schema=SearchDocumentsArguments,
            description="Search documentation with literal terms and BM25; not verified code evidence.",
        ),
        StructuredTool.from_function(
            read_document_section,
            name="read_document_section",
            args_schema=ReadDocumentArguments,
            description="Read an original indexed section using its exact path and line range.",
        ),
    ]
