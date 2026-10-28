export const auditReportSections = [
  ["identification", "qualityAudits.report.sections.identification"],
  ["executive_summary", "qualityAudits.report.sections.executive_summary"],
  ["objectives_and_scope", "qualityAudits.report.sections.objectives_and_scope"],
  ["methodology_and_criteria", "qualityAudits.report.sections.methodology_and_criteria"],
  ["software_description", "qualityAudits.report.sections.software_description"],
  ["quality_results", "qualityAudits.report.sections.quality_results"],
  ["consolidated_risks", "qualityAudits.report.sections.consolidated_risks"],
  ["general_conclusions", "qualityAudits.report.sections.general_conclusions"],
  ["recommendations_and_improvement_plan", "qualityAudits.report.sections.recommendations_and_improvement_plan"],
  ["annexes_and_traceability", "qualityAudits.report.sections.annexes_and_traceability"],
] as const
export type AuditReportSection = typeof auditReportSections[number][0]
