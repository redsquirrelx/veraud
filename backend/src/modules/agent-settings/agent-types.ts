/** Agent types explicitly supported by backend workflows. */
export const ANALYZER_AGENT_TYPE = "analyzer"
export const DUMMY_AGENT_TYPE = "dummy"
export const ARCHITECT_AGENT_TYPE = "architect"
export const JUDGE_AGENT_TYPE = "judge"
/** Stages of the project-architecture pipeline. These double as backend agent
 *  types on purpose: the transport keys sent to the agent-server must match
 *  its registered stage names exactly, so no mapping layer is needed. */
export const ORIENTATION_AGENT_TYPE = "orientation"
export const PROJECT_ARCHITECTURE_AGENT_TYPE = "architecture"
export const PROJECT_SEMANTIC_VALIDATION_AGENT_TYPE = "semantic_validation"
export const BACKEND_AGENT_TYPES = [ANALYZER_AGENT_TYPE, ARCHITECT_AGENT_TYPE, DUMMY_AGENT_TYPE, JUDGE_AGENT_TYPE, ORIENTATION_AGENT_TYPE, PROJECT_ARCHITECTURE_AGENT_TYPE, PROJECT_SEMANTIC_VALIDATION_AGENT_TYPE] as const
/** Agent-server pipeline serving the three project stages above. */
export const PROJECT_ARCHITECTURE_PIPELINE_NAME = "project-architecture"
export const PROJECT_ARCHITECTURE_PIPELINE_STAGES = [ORIENTATION_AGENT_TYPE, PROJECT_ARCHITECTURE_AGENT_TYPE, PROJECT_SEMANTIC_VALIDATION_AGENT_TYPE] as const
