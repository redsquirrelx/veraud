"""Shared selection contract for direct and pipeline quality audits."""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field


def unique_attributes(values):
    if len(set(values)) != len(values):
        raise ValueError("Quality attributes must not be duplicated.")
    return values


QualityAttributes = Annotated[list[Literal["maintainability", "security", "functional_adequacy"]],
    Field(min_length=1, max_length=3), AfterValidator(unique_attributes)]


def audit_root(attributes):
    return "maintainability_manager" if "maintainability" in attributes else (
        "security" if "security" in attributes else "functional_adequacy")
