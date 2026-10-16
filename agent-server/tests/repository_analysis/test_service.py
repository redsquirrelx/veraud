import asyncio
import json
from pathlib import Path

import pytest

from server.services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
    RepositoryQueryService,
)
from server.services.repository_analysis.service import (
    RepositoryChangedError,
    validate_snapshot_references,
)


def write_fixture(root: Path, files: dict[str, str | bytes]) -> None:
    for relative_path, content in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")


@pytest.fixture
def python_repository(tmp_path):
    write_fixture(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "shop"\nrequires-python = ">=3.11"\ndependencies = ["fastapi>=0.100", "pymongo>=4"]\n[project.scripts]\nshop = "shop.app:main"\n[dependency-groups]\ntest = ["pytest>=8"]\n',
            "uv.lock": '[[package]]\nname = "fastapi"\nversion = "0.115.0"\n[[package]]\nname = "pytest"\nversion = "8.3.0"\n',
            "src/shop/__init__.py": "from .app import app\n",
            "src/shop/domain/__init__.py": "",
            "src/shop/domain/repository.py": "from abc import ABC, abstractmethod\nclass ProductRepository(ABC):\n    @abstractmethod\n    def save(self, value):\n        pass\n",
            "src/shop/infrastructure/repository.py": "from shop.domain.repository import ProductRepository\nclass MongoProductRepository(ProductRepository):\n    def save(self, value):\n        return value\n",
            "src/shop/app.py": "from fastapi import FastAPI as Application\nfrom shop.infrastructure.repository import MongoProductRepository\napp = Application()\n@app.get('/products')\nasync def products():\n    return []\ndef main():\n    pass\nif __name__ == '__main__':\n    main()\n",
            "tests/test_shop.py": "from shop.app import products\ndef test_products():\n    assert products is not None\n",
            "pytest.ini": "[pytest]\ntestpaths = tests\n",
            "Dockerfile": 'FROM python:3.13-slim\nCMD ["python", "-m", "shop.app"]\n',
            "compose.yaml": "services:\n  api:\n    build: .\n    depends_on: [mongo]\n  mongo:\n    image: mongo:7\n    ports: ['27017:27017']\n",
            "README.md": "# Shop\nProduct persistence uses a repository port.\n",
            ".env": "PRIVATE_VALUE=not-indexed\n",
            "node_modules/ignored.js": "throw new Error('do not execute');\n",
        },
    )
    return tmp_path


def test_python_snapshot_covers_all_seven_analysis_areas(python_repository):
    snapshot = asyncio.run(RepositoryAnalysisService().analyze(python_repository))
    queries = RepositoryQueryService(snapshot)
    assert snapshot.projects[0].name == "shop"
    assert {technology.name for technology in snapshot.technologies} >= {
        "python",
        "FastAPI",
        "pytest",
    }
    fastapi = next(
        dependency
        for dependency in snapshot.dependencies
        if dependency.name == "fastapi"
    )
    assert fastapi.version_constraint == ">=0.100"
    assert fastapi.resolved_versions == ("0.115.0",)
    assert any(
        directory.path == "src/shop" and directory.kind == "python_package"
        for directory in snapshot.directories
    )
    assert any(
        signal.kind == "repository_or_port_implementation"
        for signal in snapshot.architecture_signals
    )
    assert any(
        entrypoint.http_method == "GET" and entrypoint.route == "/products"
        for entrypoint in snapshot.entrypoints
    )
    assert any(
        resource.name == "MongoDB" and resource.image == "mongo:7"
        for resource in snapshot.infrastructure
    )
    assert queries.get_testing_configuration().items[0].framework == "pytest"
    assert queries.get_testing_configuration().items[0].file_paths == (
        "tests/test_shop.py",
    )
    assert (
        next(
            source_file for source_file in snapshot.files if source_file.path == ".env"
        ).content
        is None
    )
    assert not any(
        source_file.path.startswith("node_modules/") for source_file in snapshot.files
    )
    validate_snapshot_references(snapshot)


def test_repeated_analysis_is_deterministic_and_does_not_write_files(python_repository):
    service = RepositoryAnalysisService()
    original_files = {
        path.relative_to(python_repository).as_posix()
        for path in python_repository.rglob("*")
    }
    first = service.analyze_sync(python_repository)
    second = service.analyze_sync(python_repository)
    assert first.model_dump() == second.model_dump()
    assert original_files == {
        path.relative_to(python_repository).as_posix()
        for path in python_repository.rglob("*")
    }


def test_queries_retain_old_source_and_validate_ranges(python_repository):
    snapshot = RepositoryAnalysisService().analyze_sync(python_repository)
    queries = RepositoryQueryService(snapshot)
    symbol = queries.find_symbols(name="MongoProductRepository.save").items[0]
    expected_source = queries.get_symbol_source(symbol.id)
    (python_repository / "src/shop/infrastructure/repository.py").unlink()
    assert queries.get_symbol_source(symbol.id) == expected_source
    assert "return value" in expected_source.content
    assert (
        queries.search_repository_text("repository port").items[0].path == "README.md"
    )
    with pytest.raises(ValueError, match="outside retained source"):
        queries.get_source_excerpt("README.md", 1, 100)
    with pytest.raises(ValueError, match="not retained"):
        queries.get_source_excerpt(".env")
    with pytest.raises(KeyError):
        queries.get_source_excerpt("../outside.py")


def test_python_relative_imports_and_unknown_dependencies_are_not_host_dependent(
    tmp_path,
):
    write_fixture(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "from . import b\nimport not_installed_anywhere\n",
            "pkg/b.py": "VALUE = 1\n",
        },
    )
    snapshot = RepositoryAnalysisService().analyze_sync(tmp_path)
    files = {source_file.path: source_file.id for source_file in snapshot.files}
    assert any(
        relationship.source_id == files["pkg/a.py"]
        and relationship.target_id == files["pkg/b.py"]
        for relationship in snapshot.relationships
    )
    unknown = next(
        relationship
        for relationship in snapshot.relationships
        if relationship.specifier == "not_installed_anywhere"
    )
    assert unknown.resolution == "unresolved"


def test_monorepo_aliases_lock_versions_and_typescript_decorators(tmp_path):
    write_fixture(
        tmp_path,
        {
            "package.json": json.dumps({"name": "workspace", "workspaces": ["apps/*"]}),
            "tsconfig.base.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"@shared/*": ["shared/*"]}}}',
            "shared/value.ts": "export const value = 42;\n",
            "apps/api/package.json": json.dumps(
                {
                    "name": "api",
                    "dependencies": {"@nestjs/core": "^10", "@nestjs/common": "^10"},
                    "devDependencies": {"jest": "^29"},
                    "scripts": {"test": "jest"},
                }
            ),
            "apps/api/tsconfig.json": '{// inherited aliases\n"extends": "../../tsconfig.base.json", "compilerOptions": {},}',
            "apps/api/src/main.ts": "import { NestFactory } from '@nestjs/core';\nimport { value } from '@shared/value';\nNestFactory.create(value);\n",
            "apps/api/src/controller.ts": "import { Controller, Get } from '@nestjs/common';\n@Controller('products')\nexport class ProductController {\n  @Get(':id')\n  find() { return 42; }\n}\n",
            "apps/api/src/main.spec.ts": "import { ProductController } from './controller.js';\n",
            "apps/api/package-lock.json": json.dumps(
                {"packages": {"node_modules/@nestjs/core": {"version": "10.4.0"}}}
            ),
        },
    )
    snapshot = RepositoryAnalysisService().analyze_sync(tmp_path)
    files = {source_file.path: source_file for source_file in snapshot.files}
    api_project = next(
        project for project in snapshot.projects if project.name == "api"
    )
    assert files["apps/api/src/main.ts"].project_id == api_project.id
    assert any(
        relationship.specifier == "@shared/value"
        and relationship.target_id == files["shared/value.ts"].id
        for relationship in snapshot.relationships
    )
    assert any(
        relationship.specifier == "./controller.js"
        and relationship.target_id == files["apps/api/src/controller.ts"].id
        for relationship in snapshot.relationships
    )
    assert next(
        dependency
        for dependency in snapshot.dependencies
        if dependency.name == "@nestjs/core"
    ).resolved_versions == ("10.4.0",)
    endpoint = next(
        entrypoint
        for entrypoint in snapshot.entrypoints
        if entrypoint.http_method == "GET"
    )
    assert endpoint.route == "/products/:id"
    method = next(symbol for symbol in snapshot.symbols if symbol.name == "find")
    assert method.start_line == 4
    assert (
        "@Get(':id')"
        in RepositoryQueryService(snapshot).get_symbol_source(method.id).content
    )


def test_large_tsx_ranges_and_next_static_export(tmp_path):
    write_fixture(
        tmp_path,
        {
            "package.json": '{"name":"portfolio","dependencies":{"next":"^16"}}',
            "app/page.tsx": "\n" * 300
            + "export default function Home() { return <main>Hello</main>; }\n",
            "next.config.ts": 'const nextConfig = { output: "export" };\nexport default nextConfig;\n',
        },
    )
    snapshot = RepositoryAnalysisService().analyze_sync(tmp_path)
    assert (
        next(symbol for symbol in snapshot.symbols if symbol.name == "Home").start_line
        == 301
    )
    assert any(
        entrypoint.kind == "framework_page" for entrypoint in snapshot.entrypoints
    )
    assert any(
        signal.kind == "static_export" for signal in snapshot.architecture_signals
    )


def test_limits_parse_errors_and_unsupported_languages_are_visible(tmp_path):
    write_fixture(
        tmp_path,
        {
            "a.py": "def broken(:\n",
            "b.go": "package main\n",
            "c.py": "#" * 1000,
            "d.txt": b"\xff\xfe",
            "e.txt": "another file\n",
        },
    )
    snapshot = RepositoryAnalysisService().analyze_sync(
        RepositoryAnalysisInput(
            root_path=str(tmp_path), max_file_bytes=100, max_files=2
        )
    )
    categories = {issue.category for issue in snapshot.coverage.issues}
    assert {"source_parse_error", "too_large", "file_limit"} <= categories
    assert snapshot.coverage.unsupported_source_languages == ("go",)
    assert any(source_file.status == "file_limit" for source_file in snapshot.files)


def test_invalid_manifest_does_not_prevent_other_projects_from_being_extracted(
    tmp_path,
):
    write_fixture(
        tmp_path,
        {
            "package.json": '{"dependencies": []}',
            "child/package.json": '{"name":"valid","dependencies":{"express":"^4"}}',
            "child/app.js": "import express from 'express';\n",
        },
    )
    snapshot = RepositoryAnalysisService().analyze_sync(tmp_path)
    assert any(
        issue.path == "package.json" and issue.category == "configuration_parse_error"
        for issue in snapshot.coverage.issues
    )
    assert any(technology.name == "Express" for technology in snapshot.technologies)


def test_snapshot_rejects_source_changes_during_extraction(tmp_path, monkeypatch):
    from server.services.repository_analysis import service as service_module

    write_fixture(tmp_path, {"app.py": "VALUE = 1\n"})
    original_extractor = service_module.extract_source_code

    def extract_and_modify(context):
        original_extractor(context)
        (tmp_path / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

    monkeypatch.setattr(service_module, "extract_source_code", extract_and_modify)
    with pytest.raises(RepositoryChangedError):
        RepositoryAnalysisService().analyze_sync(tmp_path)


def test_setup_py_is_parsed_but_never_executed_and_empty_directories_are_retained(
    tmp_path,
):
    write_fixture(
        tmp_path,
        {
            "setup.py": "from setuptools import setup\nraise RuntimeError('must not run')\nsetup(name='example', install_requires=['flask>=3'])\n",
        },
    )
    (tmp_path / "empty").mkdir()
    snapshot = RepositoryAnalysisService().analyze_sync(tmp_path)
    assert snapshot.projects[0].name == "example"
    assert any(dependency.name == "flask" for dependency in snapshot.dependencies)
    assert any(directory.path == "empty" for directory in snapshot.directories)


def test_query_pagination_and_relationship_direction(python_repository):
    snapshot = RepositoryAnalysisService().analyze_sync(python_repository)
    queries = RepositoryQueryService(snapshot)
    first = queries.list_files(limit=2)
    second = queries.list_files(offset=2, limit=2)
    assert first.total == second.total == len(snapshot.files)
    assert not {item.id for item in first.items} & {item.id for item in second.items}
    relationship = next(
        relationship
        for relationship in snapshot.relationships
        if relationship.resolution == "internal"
    )
    assert (
        relationship
        in queries.get_outgoing_relationships(relationship.source_id, limit=500).items
    )
    assert (
        relationship
        in queries.get_incoming_relationships(relationship.target_id, limit=500).items
    )
    assert queries.get_evidence(relationship.evidence_ids[0]).file_id in {
        source_file.id for source_file in snapshot.files
    }
    with pytest.raises(ValueError):
        queries.list_files(limit=0)
    with pytest.raises(ValueError):
        queries.search_repository_text(" ")


def test_django_database_engine_and_tiled_xml_are_detected(tmp_path):
    write_fixture(
        tmp_path,
        {
            "project/settings.py": "DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}\n",
            "world/tiles.tsx": '<?xml version="1.0"?>\n<tileset name="tiles"/>\n',
        },
    )
    snapshot = RepositoryAnalysisService().analyze_sync(tmp_path)
    assert snapshot.infrastructure[0].name == "django.db.backends.sqlite3"
    assert (
        next(
            source_file
            for source_file in snapshot.files
            if source_file.path.endswith(".tsx")
        ).language
        == "xml"
    )
    assert not snapshot.coverage.issues
