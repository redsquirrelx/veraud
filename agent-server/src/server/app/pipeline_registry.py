"""Composition registry for the server's supported pipelines."""

from server.app.pipeline_contracts import PipelineDefinition


def default_pipeline_registry() -> dict[str, PipelineDefinition]:
    from server.app.functional_adequacy_definition import functional_adequacy_definition
    from server.app.project_architecture_definition import (
        project_architecture_definition,
    )
    from server.app.quality_audit_definition import quality_audit_definition

    return {
        "functional-adequacy": functional_adequacy_definition(),
        "project-architecture": project_architecture_definition(),
        "quality-audit": quality_audit_definition(),
    }
