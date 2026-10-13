/** Agent types explicitly supported by backend workflows. */
export const ANALYZER_AGENT_TYPE = "analyzer"
export const DUMMY_AGENT_TYPE = "dummy"
export const ARCHITECT_AGENT_TYPE = "architect"
export const JUDGE_AGENT_TYPE = "judge"
export const BACKEND_AGENT_TYPES = [ANALYZER_AGENT_TYPE, ARCHITECT_AGENT_TYPE, DUMMY_AGENT_TYPE, JUDGE_AGENT_TYPE] as const
