"""Only the three implemented, independent reusability investigators."""

from ...modularity.coordinator.registry import InvestigatorSpec
from ..abstraction import AbstractionAgent, AbstractionRequest, AbstractionResult
from ..component_adaptability import (
    ComponentAdaptabilityAgent,
    ComponentAdaptabilityRequest,
    ComponentAdaptabilityResult,
)
from ..reuse_opportunity import (
    ReuseOpportunityAgent,
    ReuseOpportunityRequest,
    ReuseOpportunityResult,
)
from .schemas import InvestigatorCapability

INVESTIGATORS = {
    "abstraction": InvestigatorSpec(AbstractionAgent, AbstractionRequest, AbstractionResult,
        InvestigatorCapability(id="abstraction", agent_name="AbstractionAgent",
            capability="Do abstractions facilitate concrete reuse or introduce unnecessary complexity/coupling? Inspect implementations, consumers and justified boundaries.")),
    "reuse_opportunity": InvestigatorSpec(ReuseOpportunityAgent, ReuseOpportunityRequest, ReuseOpportunityResult,
        InvestigatorCapability(id="reuse_opportunity", agent_name="ReuseOpportunityAgent",
            capability="Which conceptually similar functionalities could share an implementation? Compare semantics, effects, differences, risks and intentional isolation; similarity is not a mandatory refactor.")),
    "component_adaptability": InvestigatorSpec(ComponentAdaptabilityAgent, ComponentAdaptabilityRequest, ComponentAdaptabilityResult,
        InvestigatorCapability(id="component_adaptability", agent_name="ComponentAdaptabilityAgent",
            capability="Which constraints make selected components difficult to reuse in another context? Verify actual use and mitigating configuration/injection seams, qualifying unspecified targets.")),
}

EVIDENCE_EXPECTATIONS = {
    "abstraction": ["Inspected abstraction declarations, implementations and actual consumers.",
                    "Counterevidence, variation points and concrete indirection/coupling tradeoffs."],
    "reuse_opportunity": ["Inspected distinct implementations with compatible responsibilities and concrete differences.",
                          "Caller constraints, side effects and qualitative sharing/migration tradeoffs."],
    "component_adaptability": ["Inspected component boundaries, construction/configuration and representative usage.",
                               "Actual target mismatch or explicit plausible-context assumptions; inspected mitigating seams."],
}
