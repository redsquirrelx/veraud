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
/** Functional adequacy exposes one stage. Its model is optional: exploratory
 *  runs are deterministic and must start without a configured model. */
export const FUNCTIONAL_ADEQUACY_AGENT_TYPE = "functional_adequacy"
export const BACKEND_AGENT_TYPES = [DUMMY_AGENT_TYPE, ORIENTATION_AGENT_TYPE, PROJECT_ARCHITECTURE_AGENT_TYPE, PROJECT_SEMANTIC_VALIDATION_AGENT_TYPE, FUNCTIONAL_ADEQUACY_AGENT_TYPE] as const
/** Agent-server pipeline serving the three project stages above. */
export const PROJECT_ARCHITECTURE_PIPELINE_NAME = "project-architecture"
export const PROJECT_ARCHITECTURE_PIPELINE_STAGES = [ORIENTATION_AGENT_TYPE, PROJECT_ARCHITECTURE_AGENT_TYPE, PROJECT_SEMANTIC_VALIDATION_AGENT_TYPE] as const
export const FUNCTIONAL_ADEQUACY_PIPELINE_NAME = "functional-adequacy"
export const FUNCTIONAL_ADEQUACY_PIPELINE_STAGES = [FUNCTIONAL_ADEQUACY_AGENT_TYPE] as const
