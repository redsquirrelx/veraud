/** Transport identities used by existing workflow adapters, not a registration
 *  allowlist. The database agent catalog is synchronized from agent-server. */
export const DUMMY_AGENT_TYPE = "dummy"
/** Stages of the project-architecture pipeline. These double as backend agent
 *  types on purpose: the transport keys sent to the agent-server must match
 *  its registered stage names exactly, so no mapping layer is needed. */
export const ORIENTATION_AGENT_TYPE = "orientation"
export const PROJECT_ARCHITECTURE_AGENT_TYPE = "architecture"
export const PROJECT_SEMANTIC_VALIDATION_AGENT_TYPE = "semantic_validation"
export const MAINTAINABILITY_AGENT_TYPE = "maintainability_manager"
export const SECURITY_AGENT_TYPE = "security"
/** Agent-server pipeline serving the three project stages above. */
export const PROJECT_ARCHITECTURE_PIPELINE_NAME = "project-architecture"
export const PROJECT_ARCHITECTURE_PIPELINE_STAGES = [ORIENTATION_AGENT_TYPE, PROJECT_ARCHITECTURE_AGENT_TYPE, PROJECT_SEMANTIC_VALIDATION_AGENT_TYPE] as const
