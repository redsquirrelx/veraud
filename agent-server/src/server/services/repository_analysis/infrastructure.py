"""Docker/Compose declarations and evidence-backed integration candidates."""

import ast
import posixpath
import re

from .context import AnalysisContext, create_identifier
from .schemas import EntrypointRecord, InfrastructureRecord, RelationshipRecord

DATABASE_IMAGES = {
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "mongo": "MongoDB",
    "redis": "Redis",
    "mssql": "SQL Server",
    "cassandra": "Cassandra",
}
CLIENT_INTEGRATIONS = {
    "psycopg": ("database", "PostgreSQL client integration"),
    "psycopg2": ("database", "PostgreSQL client integration"),
    "psycopg2-binary": ("database", "PostgreSQL client integration"),
    "pymongo": ("database", "MongoDB client integration"),
    "mongodb": ("database", "MongoDB client integration"),
    "mongoose": ("database", "MongoDB client integration"),
    "redis": ("database", "Redis client integration"),
    "sqlite3": ("database", "SQLite client integration"),
    "slonik": ("database", "PostgreSQL client integration"),
    "pg": ("database", "PostgreSQL client integration"),
    "boto3": ("external_service", "AWS SDK integration"),
    "dropbox": ("external_service", "Dropbox SDK integration"),
    "google-genai": ("external_service", "Google GenAI SDK integration"),
    "openai": ("external_service", "OpenAI-compatible SDK integration"),
}


def extract_infrastructure(context: AnalysisContext):
    for file_path, syntax_tree in context.python_trees.items():
        source_file = context.files[file_path]
        if posixpath.basename(file_path) != "settings.py":
            continue
        for node in ast.walk(syntax_tree):
            if (
                not isinstance(node, ast.Assign)
                or not any(
                    isinstance(target, ast.Name) and target.id == "DATABASES"
                    for target in node.targets
                )
                or not isinstance(node.value, ast.Dict)
            ):
                continue
            for database_key, database_value in zip(
                node.value.keys, node.value.values, strict=True
            ):
                if not isinstance(database_key, ast.Constant) or not isinstance(
                    database_value, ast.Dict
                ):
                    continue
                for key, value in zip(
                    database_value.keys, database_value.values, strict=True
                ):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "ENGINE"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                    ):
                        evidence_id = context.add_evidence(
                            source_file,
                            "django_database_engine",
                            value.lineno,
                            value.end_lineno,
                        )
                        context.infrastructure.append(
                            InfrastructureRecord(
                                id=create_identifier(
                                    "infrastructure",
                                    source_file.path,
                                    "database",
                                    database_key.value,
                                ),
                                project_id=source_file.project_id,
                                kind="database",
                                name=value.value,
                                detection="declared",
                                evidence_ids=(evidence_id,),
                            )
                        )
    for source_file in context.processed_files():
        file_name = posixpath.basename(source_file.path).lower()
        if file_name.startswith("dockerfile") or file_name.endswith(".dockerfile"):
            for line_number, line in enumerate(source_file.content.splitlines(), 1):
                instruction = re.match(
                    r"\s*(FROM|CMD|ENTRYPOINT)\s+(.+)", line, re.IGNORECASE
                )
                if not instruction:
                    continue
                instruction_name, argument = instruction.groups()
                evidence_id = context.add_evidence(
                    source_file, "docker_instruction", line_number, line_number
                )
                if instruction_name.upper() == "FROM":
                    image = next(
                        (
                            token
                            for token in argument.split()
                            if not token.startswith("--")
                        ),
                        "",
                    )
                    context.infrastructure.append(
                        InfrastructureRecord(
                            id=create_identifier(
                                "infrastructure", source_file.path, "image", line_number
                            ),
                            project_id=source_file.project_id,
                            kind="container",
                            name=f"{source_file.path}:{line_number}",
                            image=image,
                            detection="declared",
                            evidence_ids=(evidence_id,),
                        )
                    )
                else:
                    context.entrypoints.append(
                        EntrypointRecord(
                            id=create_identifier(
                                "entrypoint",
                                source_file.path,
                                instruction_name,
                                line_number,
                            ),
                            project_id=source_file.project_id,
                            kind="service",
                            name=f"Docker {instruction_name.upper()}",
                            target=argument,
                            file_id=source_file.id,
                            detection="declared",
                            evidence_ids=(evidence_id,),
                            limitations=(
                                "Shell variables and image inheritance are not evaluated.",
                            ),
                        )
                    )
        configuration = context.configuration.get(source_file.path, {})
        if source_file.language != "yaml" or "services" not in configuration:
            continue
        if not (
            file_name.startswith(("compose", "docker-compose"))
            or "compose" in file_name
        ):
            continue
        services = configuration.get("services", {})
        if not isinstance(services, dict):
            context.add_issue(
                source_file.path,
                "configuration_shape_error",
                "Compose services must be a mapping.",
            )
            continue
        service_ids = {
            name: create_identifier("infrastructure", source_file.path, name)
            for name, service_configuration in services.items()
            if isinstance(service_configuration, dict)
        }
        for service_name, service_configuration in sorted(services.items()):
            if not isinstance(service_configuration, dict):
                context.add_issue(
                    source_file.path,
                    "configuration_shape_error",
                    f"Compose service {service_name} must be a mapping.",
                )
                continue
            evidence_id = context.add_evidence(
                source_file,
                "compose_service",
                configuration_key=f"services.{service_name}",
            )
            build = service_configuration.get("build")
            build_context = (
                build.get("context")
                if isinstance(build, dict)
                else build
                if isinstance(build, str)
                else None
            )
            image = service_configuration.get("image")
            ports = tuple(str(port) for port in service_configuration.get("ports", []))
            context.infrastructure.append(
                InfrastructureRecord(
                    id=service_ids[service_name],
                    project_id=source_file.project_id,
                    kind="container",
                    name=service_name,
                    image=str(image) if image else None,
                    build_context=build_context,
                    ports=ports,
                    detection="declared",
                    evidence_ids=(evidence_id,),
                )
            )
            image_name = str(image or "").rsplit("/", 1)[-1].split(":", 1)[0]
            if image_name in DATABASE_IMAGES:
                context.infrastructure.append(
                    InfrastructureRecord(
                        id=create_identifier(
                            "infrastructure", source_file.path, service_name, "database"
                        ),
                        project_id=source_file.project_id,
                        kind="database",
                        name=DATABASE_IMAGES[image_name],
                        image=str(image),
                        ports=ports,
                        detection="declared",
                        evidence_ids=(evidence_id,),
                    )
                )
            for dependency_name in service_configuration.get("depends_on", []):
                context.relationships.append(
                    RelationshipRecord(
                        id=create_identifier(
                            "relationship",
                            source_file.path,
                            service_name,
                            dependency_name,
                        ),
                        project_id=source_file.project_id,
                        source_id=service_ids[service_name],
                        target_id=service_ids.get(dependency_name),
                        kind="depends_on",
                        specifier=dependency_name,
                        resolution="internal"
                        if dependency_name in service_ids
                        else "unresolved",
                        evidence_ids=(evidence_id,),
                    )
                )
    for dependency in context.dependencies:
        if (
            dependency.name not in CLIENT_INTEGRATIONS
            or dependency.scope == "transitive"
        ):
            continue
        kind, integration_name = CLIENT_INTEGRATIONS[dependency.name]
        context.infrastructure.append(
            InfrastructureRecord(
                id=create_identifier("infrastructure", dependency.id),
                project_id=dependency.project_id,
                kind=kind,
                name=integration_name,
                detection="inferred",
                evidence_ids=dependency.evidence_ids,
            )
        )
