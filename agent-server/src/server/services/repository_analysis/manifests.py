"""Project boundaries, declared dependencies, lock versions and runtime requirements."""

import ast
import configparser
import json
import posixpath
import re
import tomllib
import warnings

import yaml

from .context import (
    AnalysisContext,
    containing_directory,
    create_identifier,
    normalize_dependency_name,
)
from .schemas import DependencyRecord, EntrypointRecord, ProjectRecord, TechnologyRecord

PROJECT_MANIFEST_NAMES = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "requirements.txt",
        "Pipfile",
    }
)
FRAMEWORK_NAMES = {
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "starlette": "Starlette",
    "pygame": "Pygame",
    "react": "React",
    "next": "Next.js",
    "vue": "Vue",
    "nuxt": "Nuxt",
    "@nestjs/core": "NestJS",
    "express": "Express",
    "svelte": "Svelte",
    "@angular/core": "Angular",
    "lit": "Lit",
}
TOOL_NAMES = frozenset(
    {
        "pytest",
        "jest",
        "vitest",
        "mocha",
        "cypress",
        "@playwright/test",
        "ruff",
        "mypy",
        "typescript",
        "vite",
        "webpack",
        "eslint",
    }
)
REQUIREMENT_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^]]+\])?\s*(.*)$")


def parse_json_configuration(text: str) -> dict:
    """Accept JSON comments/trailing commas without removing text inside strings."""
    characters = list(text)
    position = 0
    inside_string = False
    escaped = False
    while position < len(characters):
        character = characters[position]
        if inside_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                inside_string = False
            position += 1
            continue
        if character == '"':
            inside_string = True
        elif (
            character == "/"
            and position + 1 < len(characters)
            and characters[position + 1] in ("/", "*")
        ):
            is_block = characters[position + 1] == "*"
            comment_end = (
                text.find("*/", position + 2)
                if is_block
                else text.find("\n", position + 2)
            )
            if comment_end < 0:
                if is_block:
                    raise ValueError("Unterminated JSON block comment")
                comment_end = len(characters)
            elif is_block:
                comment_end += 2
            for comment_position in range(position, comment_end):
                if characters[comment_position] not in ("\n", "\r"):
                    characters[comment_position] = " "
            position = comment_end
            continue
        elif character == ",":
            following = position + 1
            while following < len(characters) and characters[following].isspace():
                following += 1
            if following < len(characters) and characters[following] in ("}", "]"):
                characters[position] = " "
        position += 1
    configuration = json.loads("".join(characters))
    if not isinstance(configuration, dict):
        raise TypeError("Configuration must contain an object")
    return configuration


def read_project_configuration(context: AnalysisContext) -> None:
    for source_file in context.processed_files():
        file_name = posixpath.basename(source_file.path)
        try:
            if source_file.language == "json" or source_file.path.endswith(".jsonc"):
                configuration = parse_json_configuration(source_file.content)
            elif source_file.language == "toml" or file_name in (
                "Pipfile",
                "Pipfile.lock",
                "uv.lock",
                "poetry.lock",
            ):
                if file_name == "Pipfile.lock":
                    configuration = parse_json_configuration(source_file.content)
                else:
                    configuration = tomllib.loads(source_file.content)
            elif source_file.language == "yaml":
                configuration = yaml.safe_load(source_file.content)
                if configuration is None:
                    configuration = {}
                if not isinstance(configuration, dict):
                    continue
            elif file_name in ("setup.cfg", "pytest.ini", "tox.ini"):
                parser = configparser.ConfigParser(interpolation=None)
                parser.read_string(source_file.content)
                configuration = {
                    section: dict(parser[section]) for section in parser.sections()
                }
            elif file_name == "setup.py":
                configuration = {}
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    syntax_tree = ast.parse(
                        source_file.content, filename=source_file.path
                    )
                for node in ast.walk(syntax_tree):
                    if (
                        isinstance(node, ast.Call)
                        and ast.unparse(node.func).rsplit(".", 1)[-1] == "setup"
                    ):
                        for keyword in node.keywords:
                            if keyword.arg in (
                                "name",
                                "install_requires",
                                "python_requires",
                                "entry_points",
                            ):
                                try:
                                    configuration[keyword.arg] = ast.literal_eval(
                                        keyword.value
                                    )
                                except (ValueError, TypeError):
                                    context.add_issue(
                                        source_file.path,
                                        "dynamic_configuration",
                                        f"setup.py {keyword.arg} is not a literal value.",
                                    )
            else:
                continue
            validate_configuration_shape(configuration, file_name)
            context.configuration[source_file.path] = configuration
        except (
            ValueError,
            TypeError,
            SyntaxError,
            yaml.YAMLError,
            configparser.Error,
        ) as error:
            # Non-object JSON datasets are not project configuration.
            if (
                file_name in PROJECT_MANIFEST_NAMES
                or file_name.endswith((".lock", "lock.json"))
                or file_name.startswith(("tsconfig", "compose", "docker-compose"))
            ):
                context.add_issue(
                    source_file.path, "configuration_parse_error", type(error).__name__
                )


def validate_configuration_shape(configuration: dict, file_name: str):
    """Reject malformed known fields before one config can interrupt a whole stage."""
    expected_mappings = ()
    if file_name == "package.json":
        expected_mappings = (
            "dependencies",
            "devDependencies",
            "peerDependencies",
            "optionalDependencies",
            "scripts",
            "engines",
        )
    elif file_name == "pyproject.toml":
        expected_mappings = ("project", "tool", "dependency-groups")
    elif file_name.startswith(("tsconfig", "jsconfig")):
        expected_mappings = ("compilerOptions",)
    for key in expected_mappings:
        if key in configuration and not isinstance(configuration[key], dict):
            raise TypeError(f"{key} must be a mapping")


def identify_projects(context: AnalysisContext, repository_name: str) -> None:
    manifests_by_directory: dict[str, list[str]] = {".": []}
    for source_file in context.processed_files():
        if posixpath.basename(source_file.path) in PROJECT_MANIFEST_NAMES:
            manifests_by_directory.setdefault(
                containing_directory(source_file.path), []
            ).append(source_file.path)
    for project_path, manifest_paths in sorted(manifests_by_directory.items()):
        project_name = (
            repository_name if project_path == "." else posixpath.basename(project_path)
        )
        ecosystems = set()
        evidence_ids = []
        for manifest_path in sorted(manifest_paths):
            manifest_file = context.files[manifest_path]
            configuration = context.configuration.get(manifest_path, {})
            if posixpath.basename(manifest_path) == "package.json":
                ecosystems.add("node")
                project_name = configuration.get("name") or project_name
            else:
                ecosystems.add("python")
                project_configuration = configuration.get("project", {})
                poetry_configuration = configuration.get("tool", {}).get("poetry", {})
                project_name = (
                    project_configuration.get("name")
                    or poetry_configuration.get("name")
                    or configuration.get("name")
                    or project_name
                )
            evidence_ids.append(context.add_evidence(manifest_file, "project_manifest"))
        ecosystem = (
            next(iter(ecosystems))
            if len(ecosystems) == 1
            else "mixed"
            if ecosystems
            else "unknown"
        )
        context.projects.append(
            ProjectRecord(
                id=create_identifier("project", project_path),
                path=project_path,
                name=str(project_name),
                ecosystem=ecosystem,
                manifest_paths=tuple(sorted(manifest_paths)),
                evidence_ids=tuple(evidence_ids),
            )
        )
    for file_path, source_file in context.files.items():
        project = context.project_for_path(file_path)
        module_name = None
        if source_file.language in ("python", "javascript", "typescript"):
            module_path = (
                file_path if project.path == "." else file_path[len(project.path) + 1 :]
            )
            module_path = posixpath.splitext(module_path.removeprefix("src/"))[0]
            if source_file.language == "python":
                module_path = module_path.removesuffix("/__init__")
                module_name = module_path.replace("/", ".")
            else:
                module_name = module_path
        context.files[file_path] = source_file.model_copy(
            update={"project_id": project.id, "module_name": module_name}
        )


def register_dependency(
    context: AnalysisContext,
    project_id: str,
    name: str,
    ecosystem: str,
    scope: str,
    detection: str,
    evidence_id: str,
    version_constraint: str | None = None,
    resolved_version: str | None = None,
    environment_marker: str | None = None,
) -> DependencyRecord:
    normalized_name = normalize_dependency_name(name, ecosystem)
    dependency_id = create_identifier(
        "dependency", project_id, ecosystem, normalized_name, scope
    )
    for index, dependency in enumerate(context.dependencies):
        if dependency.id == dependency_id:
            updated = dependency.model_copy(
                update={
                    "resolved_versions": tuple(
                        sorted(
                            set(dependency.resolved_versions)
                            | ({resolved_version} if resolved_version else set())
                        )
                    ),
                    "evidence_ids": tuple(
                        sorted(set(dependency.evidence_ids) | {evidence_id})
                    ),
                }
            )
            context.dependencies[index] = updated
            return updated
    dependency = DependencyRecord(
        id=dependency_id,
        project_id=project_id,
        name=normalized_name,
        ecosystem=ecosystem,
        scope=scope,
        detection=detection,
        version_constraint=version_constraint,
        resolved_versions=(resolved_version,) if resolved_version else (),
        environment_marker=environment_marker,
        evidence_ids=(evidence_id,),
    )
    context.dependencies.append(dependency)
    return dependency


def register_requirement(
    context: AnalysisContext,
    source_file,
    requirement: str,
    scope: str,
    configuration_key=None,
    line=None,
):
    requirement = re.split(r"\s+#", requirement.strip(), maxsplit=1)[0]
    if not requirement or requirement.startswith(("#", "-")):
        return
    match = REQUIREMENT_PATTERN.match(requirement)
    if match is None:
        context.add_issue(
            source_file.path,
            "unsupported_requirement",
            "Requirement name could not be parsed.",
        )
        return
    name, specification = match.groups()
    specification, _, marker = specification.partition(";")
    evidence_id = context.add_evidence(
        source_file, "declared_python_dependency", line, line, configuration_key
    )
    register_dependency(
        context,
        source_file.project_id,
        name,
        "python",
        scope,
        "declared",
        evidence_id,
        specification.strip() or None,
        environment_marker=marker.strip() or None,
    )


def register_runtime(
    context: AnalysisContext,
    source_file,
    name: str,
    requirement: str,
    configuration_key=None,
):
    evidence_id = context.add_evidence(
        source_file, "runtime_requirement", configuration_key=configuration_key
    )
    context.technologies.append(
        TechnologyRecord(
            id=create_identifier(
                "technology",
                source_file.project_id,
                name,
                source_file.path,
                configuration_key,
            ),
            project_id=source_file.project_id,
            name=name,
            kind="runtime",
            detection="declared",
            version_constraint=str(requirement),
            evidence_ids=(evidence_id,),
        )
    )


def extract_manifest_facts(context: AnalysisContext) -> None:
    for source_file in context.processed_files():
        file_name = posixpath.basename(source_file.path)
        configuration = context.configuration.get(source_file.path, {})
        if file_name == "package.json":
            for section, scope in (
                ("dependencies", "runtime"),
                ("devDependencies", "development"),
                ("peerDependencies", "peer"),
                ("optionalDependencies", "optional"),
            ):
                for dependency_name, constraint in sorted(
                    configuration.get(section, {}).items()
                ):
                    evidence_id = context.add_evidence(
                        source_file,
                        "declared_node_dependency",
                        configuration_key=f"{section}.{dependency_name}",
                    )
                    register_dependency(
                        context,
                        source_file.project_id,
                        dependency_name,
                        "node",
                        scope,
                        "declared",
                        evidence_id,
                        str(constraint),
                    )
            for runtime_name, requirement in sorted(
                configuration.get("engines", {}).items()
            ):
                register_runtime(
                    context,
                    source_file,
                    runtime_name,
                    requirement,
                    f"engines.{runtime_name}",
                )
            for script_name, command in sorted(
                configuration.get("scripts", {}).items()
            ):
                evidence_id = context.add_evidence(
                    source_file,
                    "package_script",
                    configuration_key=f"scripts.{script_name}",
                )
                context.entrypoints.append(
                    EntrypointRecord(
                        id=create_identifier(
                            "entrypoint", source_file.path, "script", script_name
                        ),
                        project_id=source_file.project_id,
                        kind="cli",
                        name=script_name,
                        target=str(command),
                        detection="declared",
                        evidence_ids=(evidence_id,),
                    )
                )
            binary_commands = configuration.get("bin", {})
            if isinstance(binary_commands, str):
                binary_commands = {configuration.get("name", "main"): binary_commands}
            for command_name, target in sorted(binary_commands.items()):
                evidence_id = context.add_evidence(
                    source_file,
                    "package_binary",
                    configuration_key=f"bin.{command_name}",
                )
                context.entrypoints.append(
                    EntrypointRecord(
                        id=create_identifier(
                            "entrypoint", source_file.path, "bin", command_name
                        ),
                        project_id=source_file.project_id,
                        kind="cli",
                        name=command_name,
                        target=str(target),
                        detection="declared",
                        evidence_ids=(evidence_id,),
                    )
                )
        elif file_name == "pyproject.toml":
            project_configuration = configuration.get("project", {})
            for requirement in project_configuration.get("dependencies", []):
                register_requirement(
                    context,
                    source_file,
                    str(requirement),
                    "runtime",
                    "project.dependencies",
                )
            for group_name, requirements in sorted(
                project_configuration.get("optional-dependencies", {}).items()
            ):
                for requirement in requirements:
                    register_requirement(
                        context,
                        source_file,
                        str(requirement),
                        f"optional:{group_name}",
                        f"project.optional-dependencies.{group_name}",
                    )
            for group_name, requirements in sorted(
                configuration.get("dependency-groups", {}).items()
            ):
                for requirement in requirements:
                    if isinstance(requirement, str):
                        register_requirement(
                            context,
                            source_file,
                            requirement,
                            f"group:{group_name}",
                            f"dependency-groups.{group_name}",
                        )
            if project_configuration.get("requires-python"):
                register_runtime(
                    context,
                    source_file,
                    "python",
                    project_configuration["requires-python"],
                    "project.requires-python",
                )
            poetry_configuration = configuration.get("tool", {}).get("poetry", {})
            dependency_groups = [
                ("runtime", poetry_configuration.get("dependencies", {}))
            ]
            dependency_groups.append(
                ("development", poetry_configuration.get("dev-dependencies", {}))
            )
            dependency_groups.extend(
                (f"group:{name}", group.get("dependencies", {}))
                for name, group in sorted(poetry_configuration.get("group", {}).items())
            )
            for scope, dependencies in dependency_groups:
                for dependency_name, constraint in sorted(dependencies.items()):
                    version_constraint = (
                        constraint.get("version", "")
                        if isinstance(constraint, dict)
                        else constraint
                    )
                    if dependency_name == "python":
                        register_runtime(
                            context,
                            source_file,
                            "python",
                            str(version_constraint),
                            "tool.poetry.dependencies.python",
                        )
                    else:
                        evidence_id = context.add_evidence(
                            source_file,
                            "poetry_dependency",
                            configuration_key=f"tool.poetry.{scope}.{dependency_name}",
                        )
                        register_dependency(
                            context,
                            source_file.project_id,
                            dependency_name,
                            "python",
                            scope,
                            "declared",
                            evidence_id,
                            str(version_constraint) or None,
                        )
            scripts = {
                **poetry_configuration.get("scripts", {}),
                **project_configuration.get("scripts", {}),
            }
            for command_name, target in sorted(scripts.items()):
                evidence_id = context.add_evidence(
                    source_file,
                    "python_console_script",
                    configuration_key=f"scripts.{command_name}",
                )
                context.entrypoints.append(
                    EntrypointRecord(
                        id=create_identifier(
                            "entrypoint", source_file.path, "script", command_name
                        ),
                        project_id=source_file.project_id,
                        kind="cli",
                        name=command_name,
                        target=str(target),
                        detection="declared",
                        evidence_ids=(evidence_id,),
                    )
                )
        elif file_name.startswith("requirements") and file_name.endswith(
            (".txt", ".in")
        ):
            scope = (
                "development"
                if any(token in file_name for token in ("dev", "test"))
                else "runtime"
            )
            for line_number, requirement in enumerate(
                source_file.content.splitlines(), 1
            ):
                register_requirement(
                    context, source_file, requirement, scope, line=line_number
                )
        elif file_name == "setup.cfg":
            for requirement in (
                configuration.get("options", {})
                .get("install_requires", "")
                .splitlines()
            ):
                register_requirement(
                    context,
                    source_file,
                    requirement,
                    "runtime",
                    "options.install_requires",
                )
        elif file_name == "setup.py":
            for requirement in configuration.get("install_requires", []):
                register_requirement(
                    context,
                    source_file,
                    str(requirement),
                    "runtime",
                    "install_requires",
                )
            if configuration.get("python_requires"):
                register_runtime(
                    context,
                    source_file,
                    "python",
                    str(configuration["python_requires"]),
                    "python_requires",
                )
        elif file_name == "Pipfile":
            for section, scope in (
                ("packages", "runtime"),
                ("dev-packages", "development"),
            ):
                for dependency_name, constraint in sorted(
                    configuration.get(section, {}).items()
                ):
                    constraint = (
                        constraint.get("version", "")
                        if isinstance(constraint, dict)
                        else constraint
                    )
                    register_requirement(
                        context,
                        source_file,
                        f"{dependency_name}{constraint if constraint != '*' else ''}",
                        scope,
                        section,
                    )
        elif file_name in (".python-version", ".nvmrc", ".node-version"):
            register_runtime(
                context,
                source_file,
                "python" if file_name == ".python-version" else "node",
                source_file.content.strip(),
            )


def register_locked_version(
    context: AnalysisContext,
    source_file,
    name: str,
    version: str,
    ecosystem: str,
    configuration_key: str,
):
    normalized_name = normalize_dependency_name(name, ecosystem)
    declared_dependencies = [
        dependency
        for dependency in context.dependencies
        if dependency.project_id == source_file.project_id
        and dependency.name == normalized_name
        and dependency.ecosystem == ecosystem
    ]
    evidence_id = context.add_evidence(
        source_file, "resolved_dependency_version", configuration_key=configuration_key
    )
    if declared_dependencies:
        for dependency in declared_dependencies:
            register_dependency(
                context,
                dependency.project_id,
                dependency.name,
                ecosystem,
                dependency.scope,
                dependency.detection,
                evidence_id,
                resolved_version=version,
            )
    else:
        register_dependency(
            context,
            source_file.project_id,
            name,
            ecosystem,
            "transitive",
            "declared",
            evidence_id,
            resolved_version=version,
        )


def extract_locked_versions(context: AnalysisContext):
    for source_file in context.processed_files():
        file_name = posixpath.basename(source_file.path)
        configuration = context.configuration.get(source_file.path, {})
        if file_name in ("uv.lock", "poetry.lock"):
            for package in configuration.get("package", []):
                if (
                    package.get("name")
                    and package.get("version")
                    and not isinstance(package.get("source", {}).get("editable"), str)
                ):
                    register_locked_version(
                        context,
                        source_file,
                        package["name"],
                        str(package["version"]),
                        "python",
                        f"package.{package['name']}",
                    )
        elif file_name in ("package-lock.json", "npm-shrinkwrap.json"):
            packages = configuration.get("packages", {})
            for package_path, package in sorted(packages.items()):
                if "node_modules/" in package_path and package.get("version"):
                    dependency_name = (
                        package.get("name")
                        or package_path.rsplit("node_modules/", 1)[-1]
                    )
                    register_locked_version(
                        context,
                        source_file,
                        dependency_name,
                        str(package["version"]),
                        "node",
                        f"packages.{package_path}",
                    )
            if not packages:

                def walk_locked_dependencies(dependencies, prefix, lock_file):
                    for dependency_name, dependency in sorted(dependencies.items()):
                        if dependency.get("version"):
                            register_locked_version(
                                context,
                                lock_file,
                                dependency_name,
                                str(dependency["version"]),
                                "node",
                                f"{prefix}.{dependency_name}",
                            )
                        walk_locked_dependencies(
                            dependency.get("dependencies", {}),
                            f"{prefix}.{dependency_name}.dependencies",
                            lock_file,
                        )

                walk_locked_dependencies(
                    configuration.get("dependencies", {}), "dependencies", source_file
                )
        elif file_name == "Pipfile.lock":
            for section in ("default", "develop"):
                for dependency_name, package in sorted(
                    configuration.get(section, {}).items()
                ):
                    version = str(package.get("version", "")).removeprefix("==")
                    if version:
                        register_locked_version(
                            context,
                            source_file,
                            dependency_name,
                            version,
                            "python",
                            f"{section}.{dependency_name}",
                        )
        elif file_name == "pnpm-lock.yaml":
            for package_key, package in sorted(
                configuration.get("packages", {}).items()
            ):
                package_key = str(package_key).lstrip("/").split("(", 1)[0]
                if "@" in package_key[1:]:
                    dependency_name, version = package_key.rsplit("@", 1)
                elif "/" in package_key:
                    dependency_name, version = package_key.rsplit("/", 1)
                else:
                    continue
                register_locked_version(
                    context,
                    source_file,
                    dependency_name,
                    version,
                    "node",
                    f"packages.{package_key}",
                )
        elif file_name == "yarn.lock":
            selectors = []
            for line_number, line in enumerate(source_file.content.splitlines(), 1):
                if (
                    line
                    and not line[0].isspace()
                    and line.endswith(":")
                    and not line.startswith("#")
                ):
                    selectors = [
                        selector.strip().strip('"') for selector in line[:-1].split(",")
                    ]
                version_match = re.match(r'\s+version\s*:?\s+"?([^"\s]+)', line)
                if version_match:
                    for selector in selectors:
                        if "@" in selector[1:]:
                            dependency_name = selector.rsplit("@", 1)[0]
                            register_locked_version(
                                context,
                                source_file,
                                dependency_name,
                                version_match[1],
                                "node",
                                f"line:{line_number}",
                            )


def extract_dependency_technologies(context: AnalysisContext):
    for dependency in context.dependencies:
        if dependency.scope == "transitive":
            continue
        if dependency.name in FRAMEWORK_NAMES or dependency.name in TOOL_NAMES:
            context.technologies.append(
                TechnologyRecord(
                    id=create_identifier("technology", dependency.id),
                    project_id=dependency.project_id,
                    name=FRAMEWORK_NAMES.get(dependency.name, dependency.name),
                    kind="framework" if dependency.name in FRAMEWORK_NAMES else "tool",
                    detection=dependency.detection,
                    version_constraint=dependency.version_constraint,
                    resolved_version=dependency.resolved_versions[0]
                    if len(dependency.resolved_versions) == 1
                    else None,
                    evidence_ids=dependency.evidence_ids,
                )
            )
