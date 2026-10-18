/** Agent types explicitly supported by backend workflows. Dummy stays as the
 *  generic single-run agent; the project-architecture stages double as
 *  backend agent types on purpose (see below). */
export const DUMMY_AGENT_TYPE = "dummy"
/** Stages of the project-architecture pipeline. These double as backend agent
 *  types on purpose: the transport keys sent to the agent-server must match
 *  its registered stage names exactly, so no mapping layer is needed. */
export const ORIENTATION_AGENT_TYPE = "orientation"
export const PROJECT_ARCHITECTURE_AGENT_TYPE = "architecture"
export const PROJECT_SEMANTIC_VALIDATION_AGENT_TYPE = "semantic_validation"
export const MAINTAINABILITY_AGENT_TYPE = "maintainability_manager"
export const SECURITY_AGENT_TYPE = "security"
/** Wire IDs of every model-backed participant in a maintainability audit. */
export const MAINTAINABILITY_AUDIT_AGENTS = [
  MAINTAINABILITY_AGENT_TYPE, "modularity", "reusability", "architecture_boundary", "responsibility",
  "dependency_impact", "abstraction", "reuse_opportunity", "component_adaptability",
] as const
export const BACKEND_AGENT_TYPES = [DUMMY_AGENT_TYPE, ORIENTATION_AGENT_TYPE, PROJECT_ARCHITECTURE_AGENT_TYPE, PROJECT_SEMANTIC_VALIDATION_AGENT_TYPE, MAINTAINABILITY_AGENT_TYPE, SECURITY_AGENT_TYPE] as const
/** Agent-server pipeline serving the three project stages above. */
export const PROJECT_ARCHITECTURE_PIPELINE_NAME = "project-architecture"
export const PROJECT_ARCHITECTURE_PIPELINE_STAGES = [ORIENTATION_AGENT_TYPE, PROJECT_ARCHITECTURE_AGENT_TYPE, PROJECT_SEMANTIC_VALIDATION_AGENT_TYPE] as const
