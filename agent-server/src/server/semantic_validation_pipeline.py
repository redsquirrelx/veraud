"""Compatibility imports for the semantic coordinator now owned by pipelines."""

from .pipelines.semantic_validation import (
    SemanticPipelineResult,
    validate_architecture_pipeline,
)

__all__ = ["SemanticPipelineResult", "validate_architecture_pipeline"]
