export const auditReportSections = [
  "identification", "executive_summary", "objectives_and_scope", "methodology_and_criteria", "software_description",
  "quality_results", "consolidated_risks", "general_conclusions", "recommendations_and_improvement_plan", "annexes_and_traceability",
] as const
export type AuditReportSection = typeof auditReportSections[number]
